#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Bridge context and per-turn logging checks for Vibe; no client hook implied."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


def git(root, *args):
    result = subprocess.run(['git', '-c', 'core.fsmonitor=false', '-C', str(root), *args],
                            capture_output=True, check=True, env={**os.environ, 'GIT_OPTIONAL_LOCKS': '0'})
    return result.stdout


def digest(path):
    if path.is_symlink():
        return 'symlink:' + os.readlink(path)
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(65536), b''):
            h.update(block)
    return h.hexdigest()


def work_enabled(root):
    import yaml
    config = root / 'bridge-config.yaml'
    if not config.is_file():
        return False
    data = yaml.safe_load(config.read_text()) or {}
    branch = git(root, 'branch', '--show-current').decode().strip()
    return branch.startswith('user/') and data.get('work', {}).get('enabled') is True


def snapshot(root):
    # Include HEAD so a commit that cleans the worktree cannot hide work.
    paths = set(git(root, 'ls-files', '-m', '-d', '-o', '--exclude-standard', '-z').decode().split('\0'))
    paths.update(git(root, 'diff', '--cached', '--name-only', '-z').decode().split('\0'))
    files = {p: digest(root / p) for p in sorted(paths) if p and not p.startswith('.bridge/')}
    try:
        head = git(root, 'rev-parse', 'HEAD').decode().strip()
    except subprocess.CalledProcessError:
        head = None
    return {'head': head, 'files': files, 'log': digest(root / 'work/log.md'), 'work_enabled': work_enabled(root)}


def needs_log(before, after):
    changed = before['head'] != after['head'] or {
        k: v for k, v in before['files'].items() if k != 'work/log.md'
    } != {k: v for k, v in after['files'].items() if k != 'work/log.md'}
    return before.get('work_enabled', False) and changed and before['log'] == after['log']


def run(root, script, *args):
    result = subprocess.run([sys.executable, str(root / 'scripts' / script), *args], cwd=root)
    if result.returncode:
        raise RuntimeError(f'{script} exited {result.returncode}')


def doctor(root):
    errors = []
    skills = root / '.agents/skills'
    if not skills.is_dir() or skills.resolve() != (root / 'skills').resolve():
        errors.append('.agents/skills must resolve to skills/')
    if not (root / 'AGENTS.md').is_file():
        errors.append('AGENTS.md missing')
    catalog = root / 'work/knowledge/repositories/catalog.json'
    ecosystem = root / 'ecosystem.yaml'
    if catalog.exists():
        import yaml
        registry = yaml.safe_load(ecosystem.read_text()) if ecosystem.exists() else {}
        # Registry entries can occur in several supported sections.
        def paths(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    if key in ('path', 'local_path') and isinstance(value, str):
                        yield os.path.normpath(os.path.expanduser(value))
                    else:
                        yield from paths(value)
            elif isinstance(node, list):
                for value in node:
                    yield from paths(value)
        config = root / 'bridge-config.yaml'
        identity = (yaml.safe_load(config.read_text()) or {}).get('identity', {}) if config.exists() else {}
        def resolve(value):
            def substitute(match):
                key = match.group(1)
                if key not in identity:
                    raise RuntimeError(f'Unknown identity variable in ecosystem path: {key}')
                return str(identity[key])
            value = re.sub(r'\$\{([^}]+)\}', substitute, value)
            path = Path(os.path.expanduser(value))
            return os.path.normpath(str(path if path.is_absolute() else root / path))
        registered = {resolve(value) for value in paths(registry)}
        missing = [r['id'] for r in json.loads(catalog.read_text())['repositories']
                   if os.path.normpath(r['path']) not in registered]
        if missing:
            errors.append(f'{len(missing)} catalog entries missing from ecosystem: ' + ', '.join(missing[:5]))
    for error in errors:
        print('FAIL: ' + error)
    if not errors:
        print('PASS: Vibe skill entry and available repository knowledge routing')
    print('INFO: start/finish are explicit commands, not automatically installed client hooks.')
    return bool(errors)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['doctor', 'start', 'checkpoint', 'finish'])
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument('--session-id', help='Unique per turn/work unit; use a new ID after every finish')
    args = parser.parse_args()
    root = args.root.resolve()
    if args.command == 'doctor':
        return doctor(root)
    if not args.session_id or not re.fullmatch(r'[A-Za-z0-9_-]{1,80}', args.session_id):
        parser.error('--session-id must contain 1–80 letters, digits, underscores or hyphens')
    state_dir = root / '.bridge/vibe-sessions'
    if (root / '.bridge').is_symlink() or state_dir.is_symlink():
        raise RuntimeError('Session state directory must not be a symlink')
    state = state_dir / (args.session_id + '.json')
    if args.command in ('start', 'checkpoint'):
        before = snapshot(root)
        state_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Exclusive creation prevents silently resetting a pending logging check.
        with state.open('x') as stream:
            os.chmod(state, 0o600)
            json.dump(before, stream)
        print('Checkpoint saved. Run Phase 0 first; this command does not switch branches.', flush=True)
        if args.command == 'checkpoint':
            return 0
        if (root / 'bridge-config.yaml').exists():
            run(root, 'bridge-config.py', '--session')
        if (root / 'ecosystem.yaml').exists():
            run(root, 'context-index.py', 'ecosystem.yaml')
        if before['work_enabled'] and (root / 'work/log.md').exists():
            run(root, 'worklog.py', '--recent', '3')
        if before['work_enabled'] and (root / 'work/board.md').exists():
            print((root / 'work/board.md').read_text())
        if before['work_enabled'] and (root / 'scripts/standing-orders.py').exists():
            run(root, 'standing-orders.py', '--index')
        print('Load identity, eager standing-order bodies and triggered rules per Phase 1.')
        return 0
    if state.is_symlink() or not state.is_file():
        raise RuntimeError('No valid checkpoint; run start with a new session ID before work')
    before = json.loads(state.read_text())
    if needs_log(before, snapshot(root)):
        print('FAIL: work changed since checkpoint without a changed work/log.md. Add the substantive log row.')
        return 2
    hook = root / 'scripts/worklog-drift-check.sh'
    if before.get('work_enabled') and hook.exists():
        result = subprocess.run(['bash', str(hook)], cwd=root, env={**os.environ, 'BRIDGE_PROJECT_DIR': str(root), 'BRIDGE_STATUS_ONLY': '1'})
        if result.returncode:
            return result.returncode
    state.unlink()
    print('PASS: per-turn log check and available shared status-drift check')
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(f'ERROR: {error}', file=sys.stderr)
        sys.exit(1)
