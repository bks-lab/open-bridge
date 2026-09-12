# SPDX-License-Identifier: MIT
"""Local Bridge UI service. Markdown/YAML remain the source of truth."""
from __future__ import annotations
import argparse
import codecs
from contextlib import contextmanager
import importlib.util
import hashlib
import fcntl
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import secrets
import selectors
import shutil
import signal
import stat
import subprocess
import sys
import threading
import time
import uuid
from urllib.parse import urlsplit, parse_qs
import yaml

TERMINAL = {'succeeded', 'failed', 'cancelled', 'interrupted'}
LIMIT = 256 * 1024

def now():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())

@contextmanager
def locked(path):
    fd = os.open(path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, 'r+') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        yield


def atomic(path, data):
    temp = path.with_name(path.name + '.' + uuid.uuid4().hex + '.tmp')
    fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'w') as stream:
        json.dump(data, stream, ensure_ascii=False)
        stream.flush()
        os.fsync(stream.fileno())
    os.replace(temp, path)

def identity(pid):
    try:
        text = Path(f'/proc/{pid}/stat').read_text()
        fields = text[text.rfind(')') + 2:].split()
        if fields[0] == 'Z':
            return None
        return fields[19]
    except (OSError, IndexError):
        return None

def read_yaml(path):
    if path.is_symlink() or not path.is_file():
        return {}
    try:
        with path.open() as stream:
            text = stream.read(1024 * 1024 + 1)
        if len(text) > 1024 * 1024:
            return {}
        return yaml.safe_load(text) or {}
    except (OSError, yaml.YAMLError):
        return {}

def lifecycle(root, run, message):
    """Append measured local operational evidence; no prompt or credentials."""
    config = read_yaml(root / 'bridge-config.yaml')
    if not isinstance(config, dict) or not isinstance(config.get('work'), dict) or config['work'].get('enabled') is not True:
        return
    work = root / 'work'
    log = work / 'log.md'
    if work.is_symlink() or log.is_symlink():
        raise ValueError('Work log must be a regular local file')
    work.mkdir(exist_ok=True)
    with log.open('a+') as stream:
        fcntl.flock(stream, fcntl.LOCK_EX)
        stamp = time.strftime('%Y-%m-%d %H:%M')
        stream.write(f'| {stamp} | 🔧 | bridge-ui | Run {run["id"][:8]}: {message}. |\n')
        stream.flush()
        fcntl.flock(stream, fcntl.LOCK_UN)

CONTENT_SUFFIXES = frozenset(('.md', '.markdown', '.yaml', '.yml', '.json', '.txt', '.toml', '.rst', '.csv', '.py', '.sh', '.bash', '.js', '.mjs', '.cjs', '.ts', '.tsx', '.jsx', '.css', '.html', '.sql', '.ini'))
CONTENT_SKIP_DIRS = frozenset(('node_modules', 'vendor', 'dist', 'build', 'coverage', 'cache', 'caches', '__pycache__', 'venv', 'env', 'target'))
CONTENT_EXCLUDED = [
    'Only local canonical text documents are included; external repository contents are not followed.',
    'Symlinks, hidden files and directories are excluded, except role documents in .claude/agents.',
    'Credential, secret, token, private-key and environment files are excluded by filename.',
    'Binary files, generated build directories, caches and dependencies are excluded; source files are displayed as text only.',
    'Document previews are limited to 256 KiB; the listing contains every eligible document without a first-N cutoff.',
]


def content_allowed(parts, directory=False):
    if not parts or any(part in ('', '.', '..') or '/' in part or '\\' in part or '\x00' in part for part in parts):
        return False
    special = parts[0] == '.claude'
    if special:
        if len(parts) == 1:
            return directory
        if parts[1] != 'agents':
            return False
    for index, part in enumerate(parts):
        lower = part.lower()
        if lower.startswith('.') and not (index == 0 and special):
            return False
        if lower in ('id_rsa', 'id_dsa', 'id_ecdsa', 'id_ed25519', 'authorized_keys', 'known_hosts'):
            return False
        if lower in CONTENT_SKIP_DIRS:
            return False
        task_slug = len(parts) >= 3 and parts[0] == 'work' and ((parts[1] in ('tasks', 'streams') and index == 2) or (parts[1] == 'done' and index == 3 and len(parts) >= 4))
        if task_slug and (directory or index < len(parts) - 1):
            continue
        if re.fullmatch(r'(?:auth|authentication|env|environment)(?:[._-].*)?', lower) and Path(lower).suffix not in ('.md', '.rst'):
            return False
        if Path(lower).stem.replace('-', '_') in ('private_key', 'api_key', 'access_token', 'refresh_token', 'auth_token', 'client_secret'):
            return False
        descriptive_doc = index == len(parts) - 1 and not directory and Path(lower).suffix in ('.md', '.markdown', '.rst') and bool(re.search(r'[-_]', Path(lower).stem))
        if descriptive_doc:
            continue
        if re.search(r'(?:^|[._-])(?:credentials?|secrets?|tokens?|private[-_]?keys?|api[-_]?keys?|passwords?)(?:[._-]|$)', lower):
            return False
    return directory or Path(parts[-1]).suffix.lower() in CONTENT_SUFFIXES or not Path(parts[-1]).suffix


def content_decode(data, incomplete=False):
    if any(byte < 32 and byte not in (9, 10, 13) for byte in data):
        raise ValueError('Binary content is excluded')
    try:
        return codecs.getincrementaldecoder('utf-8')('strict').decode(data, final=not incomplete)
    except UnicodeDecodeError as error:
        raise ValueError('Non-UTF-8 content is excluded') from error


@contextmanager
def content_file(root, relative):
    """Traverse through pinned directory descriptors; never follow a symlink."""
    parts = relative.split('/')
    if not content_allowed(parts) or relative.startswith('/'):
        raise FileNotFoundError('Document is not available')
    descriptors = []
    try:
        parent = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(parent)
        for part in parts[:-1]:
            parent = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
            descriptors.append(parent)
        fd = os.open(parts[-1], os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=parent)
        descriptors.append(fd)
        metadata = os.fstat(fd)
        if not stat.S_ISREG(metadata.st_mode):
            raise FileNotFoundError('Document is not a regular file')
        yield fd, metadata
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


@contextmanager
def directory_chain(root, parts, create=False):
    descriptors = []
    try:
        fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        descriptors.append(fd)
        for part in parts:
            if create:
                try:
                    os.mkdir(part, 0o700, dir_fd=fd)
                except FileExistsError:
                    pass
            fd = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            descriptors.append(fd)
            if create and parts and parts[0] == '.bridge':
                os.fchmod(fd, 0o700)
        yield fd
    finally:
        for fd in reversed(descriptors):
            os.close(fd)


def validate_document(relative, text):
    suffix = Path(relative).suffix.lower()
    try:
        if suffix in ('.yaml', '.yml'):
            yaml.safe_load(text)
        elif suffix == '.json':
            def reject_constant(value):
                raise ValueError('Document syntax is invalid: non-finite JSON number ' + value)
            json.loads(text, parse_constant=reject_constant)
        elif suffix in ('.md', '.markdown'):
            start = re.match(r'^(?:# yaml-language-server:[^\n]*\n)?---\r?\n', text)
            if start:
                end = re.search(r'^---\s*$', text[start.end():], re.MULTILINE)
                if end is None:
                    raise ValueError('Markdown frontmatter is not closed')
                yaml.safe_load(text[start.end():start.end() + end.start()])
    except (yaml.YAMLError, json.JSONDecodeError) as error:
        raise ValueError('Document syntax is invalid: ' + str(error)) from error


class Service:
    def __init__(self, root, source, read_only=False, browse_roots=()):
        self.root, self.source = root.resolve(), source.resolve()
        self.bridge_name = self.root.name
        self.read_only = read_only
        self.browse_roots = tuple(Path(path).resolve() for path in browse_roots)
        self.bridge_id = hashlib.sha256(str(self.root).encode()).hexdigest()[:24]
        self.lock = threading.RLock()
        self.sessions = {}
        self.children = []
        spec = importlib.util.spec_from_file_location('_ui_frontmatter', self.source / 'scripts/okf-export.py')
        parser = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(parser)
        self.parse_frontmatter = parser.parse_frontmatter
        self.state = self.root / '.bridge/ui/runs'
        for path in ([] if read_only else [self.root / '.bridge', self.root / '.bridge/ui', self.state]):
            if path.is_symlink():
                raise ValueError('UI state directories must not be symlinks')
            path.mkdir(exist_ok=True, mode=0o700)
            os.chmod(path, 0o700)

    def bridges(self):
        choices = {str(self.root): {'id': self.bridge_id, 'name': self.root.name, 'root': str(self.root), 'read_only': self.read_only, 'content_editable': True}}
        projects = self.projects()
        names = {project['path']: project['name'] for project in projects}
        candidates = [Path(project['path']) for project in projects] + list(self.browse_roots)
        config = read_yaml(self.root / 'bridge-config.yaml')
        variables = config.get('identity', {}) if isinstance(config, dict) else {}
        if not isinstance(variables, dict):
            variables = {}
        for file in (self.root / 'infra/instances').glob('*.yaml'):
            if file.name.startswith('_'):
                continue
            data = read_yaml(file)
            location = data.get('location') if isinstance(data, dict) else None
            value = location.get('path') if isinstance(location, dict) else None
            if not isinstance(value, str):
                continue
            try:
                value = re.sub(r'\$\{([^}]+)\}', lambda match: str(variables[match[1]]), value)
                candidate = Path(value).expanduser()
                candidate = candidate if candidate.is_absolute() else self.root / candidate
                candidates.append(candidate)
                if isinstance(data.get('name'), str):
                    names[str(candidate.resolve())] = data['name'][:200]
            except (KeyError, ValueError):
                continue
        for candidate in candidates:
            try:
                root = candidate.resolve()
                markers = [root / 'AGENTS.md', root / 'scripts/bridge-config.py']
                if not root.is_dir() or not all(path.is_file() and not path.is_symlink() for path in markers):
                    continue
                choices.setdefault(str(root), {'id': hashlib.sha256(str(root).encode()).hexdigest()[:24], 'name': names.get(str(root), root.name), 'root': str(root), 'read_only': True, 'content_editable': True})
            except OSError:
                continue
        return list(choices.values())

    def selected(self, bridge_id):
        if not bridge_id or bridge_id == self.bridge_id:
            return self
        choice = next((choice for choice in self.bridges() if choice['id'] == bridge_id), None)
        if choice is None:
            raise FileNotFoundError('Unknown Bridge selection')
        selected = Service(Path(choice['root']), self.source, read_only=True)
        selected.bridge_name = choice['name']
        return selected

    def content(self, relative=None):
        if relative is not None:
            with content_file(self.root, relative) as (fd, metadata):
                data = bytearray()
                while len(data) <= LIMIT:
                    block = os.read(fd, min(65536, LIMIT + 1 - len(data)))
                    if not block:
                        break
                    data.extend(block)
                content = content_decode(bytes(data[:LIMIT]), len(data) > LIMIT)
                revision = hashlib.sha256(data).hexdigest() if len(data) <= LIMIT else None
                return {'path': relative, 'content': content, 'truncated': len(data) > LIMIT, 'revision': revision, 'editable': len(data) <= LIMIT and metadata.st_nlink == 1}
        entries = []
        def walk(parent, parts):
            with os.scandir(parent) as children:
                names = sorted(item.name for item in children)
            for name in names:
                child_parts = parts + [name]
                try:
                    metadata = os.stat(name, dir_fd=parent, follow_symlinks=False)
                    if stat.S_ISDIR(metadata.st_mode) and content_allowed(child_parts, directory=True):
                        child = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                        try:
                            walk(child, child_parts)
                        finally:
                            os.close(child)
                    elif stat.S_ISREG(metadata.st_mode) and content_allowed(child_parts):
                        # Re-open safely: the entry could have changed since stat.
                        with content_file(self.root, '/'.join(child_parts)) as (fd, current):
                            try:
                                content_decode(os.read(fd, min(8192, current.st_size)), current.st_size > 8192)
                            except ValueError:
                                continue
                            entries.append({'path': '/'.join(child_parts), 'category': child_parts[0] if len(child_parts) > 1 else 'root', 'size': current.st_size})
                except OSError:
                    continue  # Missing, unreadable or concurrently replaced entry.
        root_fd = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
        try:
            walk(root_fd, [])
        finally:
            os.close(root_fd)
        entries.sort(key=lambda entry: entry['path'])
        counts = {}
        for entry in entries:
            counts[entry['category']] = counts.get(entry['category'], 0) + 1
        return {'entries': entries, 'categories': [{'id': key, 'count': value} for key, value in sorted(counts.items())], 'excluded': CONTENT_EXCLUDED}

    def search_content(self, query):
        if not 2 <= len(query.strip()) <= 200:
            raise ValueError('Search requires 2–200 characters')
        needle = query.strip().casefold()
        entries = []
        budget = 32 * 1024 * 1024
        skipped = 0
        for entry in self.content()['entries']:
            if entry['size'] > LIMIT or entry['size'] > budget:
                skipped += 1
                continue
            budget -= entry['size']
            try:
                document = self.content(entry['path'])
                if document['truncated']:
                    skipped += 1
                    continue
                lines = document['content'].splitlines()
                hit = next(((i + 1, line) for i, line in enumerate(lines) if needle in line.casefold()), None)
                if hit or needle in entry['path'].casefold():
                    entries.append({**entry, 'line': hit[0] if hit else None, 'snippet': hit[1][:240] if hit else ''})
            except (ValueError, OSError):
                skipped += 1
        return {'entries': entries, 'skipped': skipped}

    def backups(self, relative, backup=None):
        self.content(relative)  # Same selected-root and eligible-file boundary.
        key = hashlib.sha256(relative.encode()).hexdigest()
        if backup is not None and not re.fullmatch(re.escape(key) + r'-[0-9a-f]{32}\.bak', backup):
            raise ValueError('Invalid backup')
        try:
            with directory_chain(self.root, ['.bridge', 'ui', 'backups']) as folder:
                if backup is not None:
                    fd = os.open(backup, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=folder)
                    with os.fdopen(fd, 'rb') as stream:
                        metadata = os.fstat(stream.fileno())
                        if not stat.S_ISREG(metadata.st_mode) or metadata.st_nlink != 1 or metadata.st_size > LIMIT:
                            raise ValueError('Invalid backup file')
                        content = content_decode(stream.read(LIMIT + 1))
                    return {'content': content}
                entries = []
                for name in os.listdir(folder):
                    if re.fullmatch(re.escape(key) + r'-[0-9a-f]{32}\.bak', name):
                        metadata = os.stat(name, dir_fd=folder, follow_symlinks=False)
                        if stat.S_ISREG(metadata.st_mode) and metadata.st_nlink == 1:
                            entries.append({'id': name, 'modified': metadata.st_mtime, 'size': metadata.st_size})
                return {'entries': sorted(entries, key=lambda item: item['modified'], reverse=True)[:50]}
        except FileNotFoundError:
            if backup is not None:
                raise
            return {'entries': []}

    def save_content(self, data):
        if not isinstance(data, dict) or set(data) != {'path', 'content', 'revision'}:
            raise ValueError('Expected path, content and revision')
        relative, text, revision = data['path'], data['content'], data['revision']
        if not all(isinstance(value, str) for value in (relative, text, revision)) or not re.fullmatch('[0-9a-f]{64}', revision):
            raise ValueError('Invalid document or revision')
        encoded = text.encode('utf-8')
        if len(encoded) > LIMIT:
            raise ValueError('Document exceeds the 256 KiB editing limit')
        content_decode(encoded)
        validate_document(relative, text)
        # Validate before creating any edit state in a selected Bridge.
        current = self.content(relative)
        if not current['editable']:
            raise ValueError('Truncated or hard-linked documents cannot be edited')
        if current['revision'] != revision:
            raise FileExistsError('Document changed; reload before saving')
        durability_warning = None
        key = hashlib.sha256(relative.encode()).hexdigest()
        with directory_chain(self.root, ['.bridge', 'ui', 'edit-locks'], create=True) as lock_dir:
            lock_fd = os.open(key + '.lock', os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600, dir_fd=lock_dir)
            with os.fdopen(lock_fd, 'r+') as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                with content_file(self.root, relative) as (fd, metadata):
                    original = bytearray()
                    while len(original) <= LIMIT:
                        block = os.read(fd, min(65536, LIMIT + 1 - len(original)))
                        if not block:
                            break
                        original.extend(block)
                    if metadata.st_nlink != 1 or len(original) > LIMIT:
                        raise ValueError('Truncated or hard-linked documents cannot be edited')
                    if hashlib.sha256(original).hexdigest() != revision:
                        raise FileExistsError('Document changed; reload before saving')
                    parts = relative.split('/')
                    with directory_chain(self.root, parts[:-1]) as parent:
                        current_stat = os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)
                        version = lambda value: (value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns, value.st_nlink)
                        if version(current_stat) != version(metadata):
                            raise FileExistsError('Document changed; reload before saving')
                        backup = key + '-' + uuid.uuid4().hex + '.bak'
                        with directory_chain(self.root, ['.bridge', 'ui', 'backups'], create=True) as backups:
                            backup_fd = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=backups)
                            with os.fdopen(backup_fd, 'wb') as stream:
                                stream.write(original)
                                stream.flush()
                                os.fsync(stream.fileno())
                            os.fsync(backups)
                        temp = '.bridge-edit-' + uuid.uuid4().hex
                        temp_fd = os.open(temp, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=parent)
                        try:
                            with os.fdopen(temp_fd, 'wb') as stream:
                                stream.write(encoded)
                                os.fchmod(stream.fileno(), stat.S_IMODE(metadata.st_mode))
                                stream.flush()
                                os.fsync(stream.fileno())
                            if version(os.stat(parts[-1], dir_fd=parent, follow_symlinks=False)) != version(metadata) or version(os.fstat(fd)) != version(metadata):
                                raise FileExistsError('Document changed; reload before saving')
                            os.replace(temp, parts[-1], src_dir_fd=parent, dst_dir_fd=parent)
                            try:
                                os.fsync(parent)
                            except OSError as error:
                                durability_warning = 'Document saved, but directory durability could not be confirmed: ' + str(error)
                        finally:
                            try:
                                os.unlink(temp, dir_fd=parent)
                            except FileNotFoundError:
                                pass
        result = {'path': relative, 'content': text, 'revision': hashlib.sha256(encoded).hexdigest(), 'truncated': False, 'editable': True, 'backup': '.bridge/ui/backups/' + backup}
        if durability_warning:
            result['warning'] = durability_warning
        if relative != 'work/log.md':
            try:
                self.log_edit(relative)
            except (OSError, ValueError) as error:
                result['warning'] = (result.get('warning', '') + ' Document saved, but work-log update failed: ' + str(error)).strip()
        return result

    def log_edit(self, relative):
        config = read_yaml(self.root / 'bridge-config.yaml')
        if not isinstance(config, dict) or not isinstance(config.get('work'), dict) or config['work'].get('enabled') is not True:
            return
        with directory_chain(self.root, ['work'], create=True) as work:
            fd = os.open('log.md', os.O_WRONLY | os.O_APPEND | os.O_CREAT | os.O_NOFOLLOW | os.O_NONBLOCK, 0o600, dir_fd=work)
            with os.fdopen(fd, 'a') as stream:
                if not stat.S_ISREG(os.fstat(stream.fileno()).st_mode) or os.fstat(stream.fileno()).st_nlink != 1:
                    raise ValueError('Work log must be a regular file without hard links')
                fcntl.flock(stream, fcntl.LOCK_EX)
                label = relative.replace('|', '/').replace('\n', ' ').replace('\r', ' ')
                stream.write(f'| {time.strftime("%Y-%m-%d %H:%M")} | 🔧 | bridge-ui | Edited {label} via local GUI; previous version backed up. |\n')
                stream.flush()
                os.fsync(stream.fileno())

    def language(self):
        config = read_yaml(self.root / 'bridge-config.yaml')
        if not isinstance(config, dict):
            return 'en'
        language = config.get('language', {})
        value = language.get('conversation') if isinstance(language, dict) else language
        return 'de' if str(value).lower().startswith('de') or config.get('theme') == 'professional-de' else 'en'

    def projects(self):
        config = read_yaml(self.root / 'bridge-config.yaml')
        variables = config.get('identity', {}) if isinstance(config, dict) else {}
        if not isinstance(variables, dict):
            variables = {}
        result = [{'id': 'bridge', 'name': self.root.name, 'path': str(self.root), 'available': True}]
        seen = {str(self.root)}
        def walk(node, name='Project'):
            if isinstance(node, dict):
                raw = node.get('path', node.get('local_path'))
                if isinstance(raw, str):
                    try:
                        raw = re.sub(r'\$\{([^}]+)\}', lambda m: str(variables[m[1]]), raw)
                        path = Path(raw).expanduser()
                        path = (path if path.is_absolute() else self.root / path).resolve()
                        if path.is_dir() and str(path) not in seen:
                            seen.add(str(path))
                            result.append({'id': hashlib.sha256(str(path).encode()).hexdigest()[:24], 'name': str(node.get('name', name))[:200], 'path': str(path), 'available': (path / '.git').exists(), 'archived': node.get('archived') is True or str(node.get('status', '')).lower() in ('archived', 'retired', 'deprecated')})
                    except (KeyError, ValueError, OSError):
                        pass
                for key, value in node.items():
                    walk(value, str(key))
            elif isinstance(node, list):
                for value in node:
                    walk(value, name)
        walk(read_yaml(self.root / 'ecosystem.yaml'))
        return result

    def tasks(self):
        result = []
        for kind in ('tasks', 'streams'):
            descriptors = []
            try:
                parent = os.open(self.root, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW)
                descriptors.append(parent)
                for component in ('work', kind):
                    parent = os.open(component, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                    descriptors.append(parent)
                with os.scandir(parent) as children:
                    names = sorted(entry.name for entry in children if entry.is_dir(follow_symlinks=False))
                for name in names:
                    try:
                        task_fd = os.open(name, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=parent)
                        try:
                            fd = os.open('STATUS.md', os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=task_fd)
                            try:
                                if not stat.S_ISREG(os.fstat(fd).st_mode):
                                    continue
                                data = os.read(fd, 65536)
                                raw = codecs.getincrementaldecoder('utf-8')('strict').decode(data, final=len(data) < 65536)
                            finally:
                                os.close(fd)
                        finally:
                            os.close(task_fd)
                        data, body = self.parse_frontmatter(raw)
                        heading = next((line[2:].strip() for line in body.splitlines() if line.startswith('# ')), name)
                        if isinstance(data, dict):
                            result.append({'id': kind + '/' + name, 'title': str(data.get('title', data.get('headline', heading))), 'status': str(data.get('status', 'backlog')), 'priority': str(data.get('priority', '')), 'context': str(data.get('context', ''))})
                    except (OSError, ValueError, IndexError, yaml.YAMLError):
                        continue
            except OSError:
                continue
            finally:
                for fd in reversed(descriptors):
                    os.close(fd)
        return result

    def path(self, run_id):
        if not re.fullmatch('[0-9a-f]{32}', run_id):
            raise ValueError('Invalid run ID')
        return self.state / run_id / 'run.json'

    def get(self, run_id):
        if self.read_only:
            raise FileNotFoundError('Run history is not exposed for read-only Bridges')
        path = self.path(run_id)
        if path.is_symlink() or path.parent.is_symlink():
            raise ValueError('Invalid run state')
        with locked(path.parent / 'state.lock'):
            with path.open() as stream:
                run = json.loads(stream.read(65536))
            if not isinstance(run, dict) or not all(isinstance(run.get(key), str) for key in ('id', 'status', 'created_at', 'project_id', 'project_path')):
                raise ValueError('Invalid run manifest')
            if any(key in run and (not isinstance(run[key], int) or isinstance(run[key], bool) or run[key] <= 0) for key in ('pid', 'creator_pid')):
                raise ValueError('Invalid process identity')
            dead_worker = run.get('pid') and identity(run['pid']) != run.get('process_identity')
            abandoned_queue = not run.get('pid') and (not run.get('creator_pid') or identity(run['creator_pid']) != run.get('creator_identity'))
            if run['status'] not in TERMINAL and (dead_worker or abandoned_queue):
                run.update(status='cancelled' if (path.parent / 'cancel.requested').exists() else 'interrupted', error='Worker exited without a completion record.', updated_at=now())
                atomic(path, run)
            return run

    def runs(self):
        if self.read_only:
            return []
        for child in self.children[:]:
            if child.poll() is not None:
                self.children.remove(child)
        result = []
        for path in self.state.glob('*/run.json'):
            try:
                result.append(self.public(self.get(path.parent.name)))
            except (ValueError, OSError, KeyError):
                continue
        return sorted(result, key=lambda r: r['created_at'], reverse=True)

    @staticmethod
    def public(run):
        return {k: v for k, v in run.items() if k not in {'pid', 'process_identity', 'project_path', 'fingerprint', 'trust', 'bridge_root', 'creator_pid', 'creator_identity'}}

    def create(self, data):
        if self.read_only:
            raise PermissionError('Selected Bridge is read-only')
        with self.lock, locked(self.state.parent / 'create.lock'):
            if not isinstance(data, dict) or set(data) - {'project_id', 'client', 'prompt', 'mode', 'request_id', 'trust'}:
                raise ValueError('Invalid run request')
            if data.get('client') not in ('codex', 'vibe') or data.get('mode') not in ('inspect', 'edit'):
                raise ValueError('Choose a supported client and mode')
            if not isinstance(data.get('prompt'), str) or not data['prompt'].strip() or len(data['prompt']) > 16000:
                raise ValueError('Prompt must contain 1–16000 characters')
            if not isinstance(data.get('trust', False), bool):
                raise ValueError('Trust must be a boolean')
            try:
                run_id = uuid.UUID(data['request_id']).hex
            except (KeyError, ValueError, TypeError, AttributeError):
                raise ValueError('request_id must be a UUID')
            fingerprint = hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()
            path = self.path(run_id)
            if path.exists():
                run = self.get(run_id)
                if run['fingerprint'] != fingerprint:
                    raise FileExistsError('request_id already belongs to a different request')
                return self.public(run)
            project = next((p for p in self.projects() if p['id'] == data.get('project_id') and p['available']), None)
            if project is None:
                raise ValueError('Unknown or unavailable project')
            if not shutil.which(data['client']):
                raise ValueError('Selected CLI is not installed on PATH')
            if any(r['status'] not in TERMINAL and r['project_id'] == project['id'] for r in self.runs()):
                raise FileExistsError('This project already has an active run')
            path.parent.mkdir(mode=0o700)
            run = dict(creator_pid=os.getpid(), creator_identity=identity(os.getpid()), bridge_root=str(self.root), id=run_id, project_id=project['id'], project_name=project['name'], project_path=project['path'], client=data['client'], prompt=data['prompt'], mode=data['mode'], trust=data.get('trust', False), fingerprint=fingerprint, status='queued', created_at=now(), updated_at=now(), exit_code=None)
            if len(json.dumps(run, ensure_ascii=False).encode()) > 60000:
                raise ValueError('Run metadata exceeds the 60 KB storage limit')
            atomic(path, run)
            try:
                lifecycle(self.root, run, 'queued')
                child = subprocess.Popen([sys.executable, str(self.source / 'scripts/bridge-ui.py'), '--worker', str(path)], stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
                self.children.append(child)
                with locked(path.parent / 'state.lock'):
                    run.update(pid=child.pid, process_identity=identity(child.pid))
                    atomic(path, run)
                # Worker waits for this identity-bearing manifest before execution.
            except (OSError, ValueError) as error:
                with locked(path.parent / 'state.lock'):
                    run.update(status='failed', error=str(error), updated_at=now())
                    atomic(path, run)
            return self.public(run)

    def cancel(self, run_id):
        if self.read_only:
            raise PermissionError('Selected Bridge is read-only')
        with self.lock:
            run = self.get(run_id)
            if run['status'] in TERMINAL:
                return self.public(run)
            pid = run.get('pid')
            if not pid or not run.get('process_identity') or identity(pid) != run['process_identity']:
                raise ValueError('Worker identity cannot be verified')
            # pidfd pins the process, eliminating PID reuse between validation and signal.
            fd = os.pidfd_open(pid)
            try:
                if identity(pid) != run['process_identity']:
                    raise ValueError('Worker identity changed')
                marker = self.path(run_id).parent / 'cancel.requested'
                descriptor = os.open(marker, os.O_CREAT | os.O_WRONLY | os.O_NOFOLLOW, 0o600)
                os.close(descriptor)
                signal.pidfd_send_signal(fd, signal.SIGTERM)
            finally:
                os.close(fd)
            return self.public(self.get(run_id))

    def detail(self, run_id):
        run = self.get(run_id)
        folder = self.path(run_id).parent
        def tail(name):
            path = folder / name
            if not path.is_file() or path.is_symlink():
                return ''
            with path.open('rb') as stream:
                stream.seek(max(0, path.stat().st_size - LIMIT))
                return stream.read(LIMIT).decode(errors='replace')
        def git(*args):
            try:
                command = ['git', '-c', 'core.fsmonitor=false', '-C', run['project_path'], *args]
                with subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0'}) as child:
                    chunks, size, deadline = [], 0, time.monotonic() + 10
                    try:
                        with selectors.DefaultSelector() as selector:
                            selector.register(child.stdout, selectors.EVENT_READ)
                            while size < LIMIT and time.monotonic() < deadline:
                                if not selector.select(timeout=max(0, deadline - time.monotonic())):
                                    break
                                block = os.read(child.stdout.fileno(), min(65536, LIMIT - size))
                                if not block:
                                    break
                                chunks.append(block)
                                size += len(block)
                    finally:
                        if child.poll() is None:
                            child.kill()
                        child.wait()
                    return b''.join(chunks).decode(errors='replace')
            except (OSError, subprocess.TimeoutExpired):
                return ''
        status = git('status', '--porcelain=v1', '-z')
        files = []
        entries = iter(status.split('\0'))
        for item in entries:
            if not item:
                continue
            files.append({'status': item[:2], 'path': item[3:]})
            if 'R' in item[:2] or 'C' in item[:2]:
                next(entries, None)
        return {'run': self.public(run), 'stdout': tail('stdout.log'), 'stderr': tail('stderr.log'), 'diff': git('diff', '--no-ext-diff', '--no-textconv', 'HEAD', '--'), 'changed_files': files, 'review': {'branch': git('branch', '--show-current').strip(), 'dirty': bool(files), 'summary': 'Current working tree; changes may predate this run. Untracked contents are not displayed.'}}

class Handler(BaseHTTPRequestHandler):
    server_version = 'BridgeLocal/1'
    def log_message(self, *args):
        pass
    def send(self, code, data, cookie=None):
        body = json.dumps(data).encode()
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        if cookie:
            self.send_header('Set-Cookie', cookie)
        self.end_headers()
        self.wfile.write(body)
    def guard(self, unsafe=False):
        expected = f'127.0.0.1:{self.server.server_port}'
        if self.headers.get('Host') != expected:
            self.send(403, {'error': 'Invalid local host'})
            return False
        origin = self.headers.get('Origin')
        if origin and origin != 'http://' + expected:
            self.send(403, {'error': 'Cross-origin request denied'})
            return False
        if self.headers.get('Sec-Fetch-Site') in ('cross-site', 'same-site'):
            self.send(403, {'error': 'Cross-site request denied'})
            return False
        if self.path == '/api/bootstrap' and not unsafe:
            return True
        if not self.path.startswith('/api/'):
            return not unsafe
        cookies = dict(item.strip().split('=', 1) for item in self.headers.get('Cookie', '').split(';') if '=' in item)
        session = self.server.service.sessions.get(cookies.get('bridge_session'))
        if not session or (unsafe and not secrets.compare_digest(self.headers.get('X-Bridge-CSRF', ''), session)):
            self.send(403, {'error': 'Session or CSRF token missing; reload the application'})
            return False
        return True
    def setup(self):
        super().setup()
        self.connection.settimeout(10)

    def do_GET(self):
        if not self.guard():
            return
        primary = self.server.service
        try:
            service = primary.selected(self.headers.get('X-Bridge-ID'))
            if self.path == '/api/bootstrap':
                cookies = dict(item.strip().split('=', 1) for item in self.headers.get('Cookie', '').split(';') if '=' in item)
                cookie = cookies.get('bridge_session')
                csrf = primary.sessions.get(cookie)
                if csrf is None:
                    cookie, csrf = secrets.token_urlsafe(32), secrets.token_urlsafe(32)
                    if len(primary.sessions) > 256:
                        primary.sessions.clear()
                    primary.sessions[cookie] = csrf
                self.send(200, {'csrf': csrf, 'bridges': primary.bridges(), 'bridge': {'id': service.bridge_id, 'read_only': service.read_only, 'content_editable': True, 'name': service.bridge_name, 'root': str(service.root), 'language': service.language()}, 'clients': [{'id': c, 'available': bool(shutil.which(c))} for c in ('codex', 'vibe')], 'projects': service.projects(), 'tasks': service.tasks(), 'runs': service.runs()}, f'bridge_session={cookie}; HttpOnly; SameSite=Strict; Path=/')
            elif urlsplit(self.path).path == '/api/content/search':
                query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                if set(query) != {'q'} or len(query['q']) != 1:
                    raise ValueError('Invalid search query')
                self.send(200, service.search_content(query['q'][0]))
            elif urlsplit(self.path).path == '/api/content/backups':
                query = parse_qs(urlsplit(self.path).query, keep_blank_values=True)
                if 'path' not in query or set(query) - {'path', 'backup'} or any(len(value) != 1 for value in query.values()):
                    raise ValueError('Invalid backup query')
                self.send(200, service.backups(query['path'][0], query.get('backup', [None])[0]))
            elif urlsplit(self.path).path == '/api/content':
                query = parse_qs(urlsplit(self.path).query, keep_blank_values=True, strict_parsing=True)
                if set(query) - {'path'} or ('path' in query and len(query['path']) != 1):
                    raise ValueError('Invalid document query')
                self.send(200, service.content(query['path'][0] if 'path' in query else None))
            elif self.path == '/api/runs':
                self.send(200, {'runs': service.runs()})
            elif self.path.startswith('/api/runs/'):
                self.send(200, service.detail(self.path[len('/api/runs/'):]))
            elif self.path.startswith('/api/'):
                self.send(404, {'error': 'Not found'})
            else:
                self.static()
        except (ValueError, OSError):
            self.send(404, {'error': 'Not found'})
    def static(self):
        import mimetypes
        dist = self.server.service.source / 'ui/dist'
        raw = urlsplit(self.path).path
        if '%' in raw or '..' in raw.split('/'):
            self.send(404, {'error': 'Not found'})
            return
        path = dist / (raw.lstrip('/') or 'index.html')
        if not path.resolve().is_relative_to(dist.resolve()) or not path.is_file():
            self.send(404, {'error': 'Build the UI first with npm run build in ui/'})
            return
        body = path.read_bytes()
        self.send_response(200)
        self.send_header('Content-Type', mimetypes.guess_type(path.name)[0] or 'application/octet-stream')
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Content-Security-Policy', "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'")
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.end_headers()
        self.wfile.write(body)
    def failure(self, error, fallback=None):
        payload = {'error': str(error) if fallback is None else fallback}
        if self.path == '/api/content':
            message = str(error)
            if isinstance(error, FileExistsError):
                code = 'conflict'
            elif isinstance(error, FileNotFoundError) or 'Document is not available' in message or 'symbolic link' in message.lower():
                code = 'invalid_path'
            elif 'syntax is invalid' in message or 'frontmatter' in message:
                code = 'invalid_syntax'
            elif 'editing limit' in message or 'body limit' in message:
                code = 'too_large'
            elif 'cannot be edited' in message or 'Binary content' in message or 'Non-UTF-8' in message:
                code = 'not_editable'
            else:
                code = 'save_failed'
            payload['code'] = code
        return payload

    def do_POST(self):
        if not self.guard(True):
            return
        try:
            service = self.server.service.selected(self.headers.get('X-Bridge-ID'))
            if service.read_only and self.path != '/api/content':
                self.send(403, {'error': 'Selected Bridge is read-only; runs and cancellation are disabled'})
                return
            length = int(self.headers.get('Content-Length', '-1'))
            body_limit = 1600000 if self.path == '/api/content' else 32768
            if length < 0 or length > body_limit or self.headers.get('Transfer-Encoding'):
                self.send(413, self.failure(ValueError('Request body limit exceeded')))
                return
            if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                self.send(415, {'error': 'JSON required'})
                return
            data = json.loads(self.rfile.read(length))
            if self.path == '/api/content':
                self.send(200, service.save_content(data))
            elif self.path == '/api/runs':
                self.send(200, {'run': service.create(data)})
            elif self.path.startswith('/api/runs/') and self.path.endswith('/cancel'):
                self.send(200, {'run': service.cancel(self.path[len('/api/runs/'):-len('/cancel')])})
            else:
                self.send(404, {'error': 'Not found'})
        except FileExistsError as error:
            self.send(409, self.failure(error))
        except FileNotFoundError as error:
            self.send(404, self.failure(error, 'Not found'))
        except (ValueError, TypeError, OSError) as error:
            self.send(400, self.failure(error))


def worker(path):
    from cli_bridge import snapshot, needs_log
    from cli_launcher import run_child
    for _ in range(100):
        run = json.loads(path.read_text())
        if run.get('pid') == os.getpid():
            break
        time.sleep(.05)
    else:
        return 1
    readers = []
    def drain(read_fd, output):
        written = 0
        with os.fdopen(read_fd, 'rb') as incoming, os.fdopen(output, 'wb') as outgoing:
            while True:
                block = os.read(incoming.fileno(), 65536)
                if not block:
                    break
                remaining = max(0, 16 * 1024 * 1024 - written)
                if remaining:
                    outgoing.write(block[:remaining])
                    outgoing.flush()
                    written += min(len(block), remaining)
    for number, name in ((1, 'stdout.log'), (2, 'stderr.log')):
        read_fd, write_fd = os.pipe()
        output = os.open(path.parent / name, os.O_CREAT | os.O_WRONLY | os.O_EXCL, 0o600)
        os.dup2(write_fd, number)
        os.close(write_fd)
        reader = threading.Thread(target=drain, args=(read_fd, output), daemon=True)
        reader.start()
        readers.append(reader)
    with locked(path.parent / 'state.lock'):
        run = json.loads(path.read_text())
        if run['status'] in TERMINAL:
            return 1
        run.update(status='running', updated_at=now())
        atomic(path, run)
    try:
        root = Path(run['project_path'])
        before = snapshot(root)
        prompt = 'Read and follow AGENTS.md when present. Record substantive work according to project rules. Do not publish, push, create a PR, or deploy. ' + run['prompt']
        command = [shutil.which(run['client']) or run['client']]
        if run['client'] == 'codex':
            command += ['exec', '-C', str(root), '--sandbox', 'read-only' if run['mode'] == 'inspect' else 'workspace-write', '--json', prompt]
        else:
            command += ['--workdir', str(root), '-p', prompt, '--output', 'json']
            if run['mode'] == 'inspect':
                command += ['--agent', 'plan']
            if run['trust']:
                command += ['--trust']
        def finish():
            if needs_log(before, snapshot(root)):
                print('Bridge completion check: substantive changes require a changed, nonempty work/log.md.', file=sys.stderr)
                return 2
            return 0
        supervisor = [sys.executable, str(Path(__file__).resolve().parents[1] / 'bridge-ui.py'), '--supervise', str(os.getpid()), '--', *command]
        code = run_child(supervisor, root, finish)
        run.update(exit_code=code, status='cancelled' if code in (130, 143) else ('succeeded' if code == 0 else 'failed'))
    except BaseException as error:
        run.update(status='failed', exit_code=1, error=str(error))
    sys.stdout.flush()
    sys.stderr.flush()
    os.close(1)
    os.close(2)
    for reader in readers:
        reader.join(timeout=2)
    run['updated_at'] = now()
    try:
        lifecycle(Path(run['bridge_root']), run, run['status'])
    except (OSError, ValueError) as error:
        run.update(status='failed', error='Lifecycle log failed: ' + str(error))
    with locked(path.parent / 'state.lock'):
        atomic(path, run)
    return run['exit_code']

def supervise(parent, command):
    """Exec-free supervisor kills its owned CLI group if its worker disappears."""
    import ctypes
    if os.getpgrp() != os.getpid():
        raise RuntimeError('Supervisor requires an owned process group')
    def parent_died(sig, frame):
        os.killpg(os.getpgrp(), signal.SIGKILL)
    signal.signal(signal.SIGUSR1, parent_died)
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(1, signal.SIGUSR1, 0, 0, 0) != 0:
        raise OSError(ctypes.get_errno(), 'Cannot set parent-death signal')
    if os.getppid() != parent:
        parent_died(None, None)
    # The outer launcher signals this entire group and owns the five-second
    # escalation timer. Keep supervising while the CLI handles graceful stop.
    # Caught handlers reset to defaults when the CLI execs.
    received = []
    def stopping(signum, frame):
        received.append(signum)
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, stopping)
    if received:
        return 128 + received[0]
    child = subprocess.Popen(command)
    if received:
        # Cancellation may arrive between the pre-spawn check and Popen return.
        # The parent still owns escalation and will kill this group if ignored.
        child.send_signal(received[0])
    code = child.wait()
    # The supervisor still owns this group, so its ID cannot be recycled while
    # cleanup runs. Pin each remaining ordinary group member before signalling.
    deadline = time.monotonic() + 2
    while time.monotonic() < deadline:
        peers = False
        for entry in Path('/proc').iterdir():
            if not entry.name.isdigit() or int(entry.name) == os.getpid():
                continue
            try:
                text = (entry / 'stat').read_text()
                fields = text[text.rfind(')') + 2:].split()
                if fields[0] == 'Z' or int(fields[2]) != os.getpgrp():
                    continue
                pid = int(entry.name)
                marker = fields[19]
                fd = os.pidfd_open(pid)
                try:
                    if identity(pid) == marker:
                        peers = True
                        signal.pidfd_send_signal(fd, signal.SIGKILL)
                finally:
                    os.close(fd)
            except (OSError, ValueError, IndexError):
                continue
        if not peers:
            break
        time.sleep(.02)
    return 128 - code if code < 0 else code


def main():
    if len(sys.argv) > 3 and sys.argv[1] == '--supervise' and sys.argv[3] == '--':
        return supervise(int(sys.argv[2]), sys.argv[4:])
    parser = argparse.ArgumentParser(description='Local Open Bridge React UI and Python service (Linux).')
    parser.add_argument('--bridge-root', type=Path, default=Path.cwd())
    parser.add_argument('--port', type=int, default=8792)
    parser.add_argument('--browse-root', type=Path, action='append', default=[], help='Additional trusted local Bridge for browsing and file editing; CLI runs stay on the startup Bridge; repeatable')
    parser.add_argument('--worker', type=Path, help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.worker:
        return worker(args.worker)
    if not sys.platform.startswith('linux') or not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
        parser.error('This release requires Linux with pidfd support for verified cancellation')
    if not 0 <= args.port <= 65535:
        parser.error('Port must be between 0 and 65535')
    source = Path(__file__).resolve().parents[2]
    service = Service(args.bridge_root, source, browse_roots=args.browse_root)
    server = ThreadingHTTPServer(('127.0.0.1', args.port), Handler)
    server.service = service
    print(f'Open Bridge UI: http://127.0.0.1:{server.server_port}', flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0
