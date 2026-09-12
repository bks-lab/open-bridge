# SPDX-License-Identifier: MIT
"""Exercise the real local HTTP boundary and detached worker using a fake CLI."""
import http.client
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import uuid
from urllib.parse import quote
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'lib'))
from ui_service import Handler, Service, ThreadingHTTPServer, identity, atomic

SOURCE = Path(__file__).resolve().parents[2]

class ServiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        subprocess.run(['git', 'init', '-q', str(self.root)], check=True)
        subprocess.run(['git', '-C', str(self.root), '-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '--allow-empty', '-qm', 'initial'], check=True)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        fake = self.bin / 'codex'
        fake.write_text('#!/usr/bin/env python3\nimport sys,time,json\nif "slow" in sys.argv[-1]: time.sleep(20)\nprint(json.dumps({"ok":True}))\nsys.exit(7 if "fail" in sys.argv[-1] else 0)\n')
        fake.chmod(0o700)
        self.env = patch.dict(os.environ, {'PATH': str(self.bin) + os.pathsep + os.environ['PATH']})
        self.env.start()
        self.service = Service(self.root, SOURCE)
        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.server.service = self.service
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.cookie, self.csrf = '', ''
        code, data, headers = self.request('GET', '/api/bootstrap')
        self.assertEqual(code, 200)
        self.cookie = headers['Set-Cookie'].split(';')[0]
        self.csrf = data['csrf']

    def tearDown(self):
        for run in self.service.runs():
            if run['status'] not in ('succeeded','failed','cancelled','interrupted'):
                self.service.cancel(run['id'])
        for child in self.service.children:
            child.wait(timeout=10)
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()
        self.env.stop()
        self.tmp.cleanup()

    def request(self, method, path, data=None, headers=None):
        conn = http.client.HTTPConnection('127.0.0.1', self.server.server_port, timeout=10)
        base = {'Cookie': self.cookie, 'X-Bridge-CSRF': self.csrf, 'Content-Type': 'application/json'}
        base.update(headers or {})
        conn.request(method, path, json.dumps(data, ensure_ascii=False).encode() if data is not None else None, base)
        response = conn.getresponse()
        status, hdr, body = response.status, dict(response.getheaders()), response.read()
        conn.close()
        return status, json.loads(body), hdr

    def payload(self, prompt='inspect'):
        return {'project_id':'bridge','client':'codex','prompt':prompt,'mode':'inspect','request_id':str(uuid.uuid4()),'trust':False}

    def completed(self, run_id):
        for _ in range(100):
            detail = self.request('GET', '/api/runs/' + run_id)[1]
            if detail['run']['status'] in ('succeeded','failed','cancelled','interrupted'):
                return detail
            time.sleep(.1)
        self.fail('Worker did not complete')

    def test_security_boundary(self):
        self.assertEqual(self.request('GET','/api/bootstrap',headers={'Host':'evil.example'})[0],403)
        self.assertEqual(self.request('GET','/api/bootstrap',headers={'Origin':'https://evil.example'})[0],403)
        self.assertEqual(self.request('GET','/api/runs',headers={'Cookie':''})[0],403)
        self.assertEqual(self.request('POST','/api/runs',self.payload(),{'X-Bridge-CSRF':'bad'})[0],403)
        self.assertEqual(self.request('GET','/api/runs/../../etc/passwd')[0],404)
        payload = self.payload(); payload['project_id'] = '/tmp'
        self.assertEqual(self.request('POST','/api/runs',payload)[0],400)

    def test_idempotency_failure_json_and_persistence(self):
        payload = self.payload('fail')
        code, data, _ = self.request('POST','/api/runs',payload)
        self.assertEqual(code,200)
        run_id = data['run']['id']
        self.assertEqual(self.request('POST','/api/runs',payload)[1]['run']['id'],run_id)
        payload['prompt'] = 'different'
        self.assertEqual(self.request('POST','/api/runs',payload)[0],409)
        detail = self.completed(run_id)
        self.assertEqual(detail['run']['exit_code'],7)
        self.assertEqual(detail['run']['status'],'failed')
        self.assertEqual(json.loads(detail['stdout']), {'ok':True})
        restarted = Service(self.root,SOURCE)
        self.assertEqual(restarted.get(run_id)['status'],'failed')
        self.assertEqual((self.service.path(run_id).stat().st_mode & 0o777),0o600)

    def test_cancel_and_restart_running(self):
        run = self.request('POST','/api/runs',self.payload('slow'))[1]['run']
        time.sleep(.3)
        restarted = Service(self.root,SOURCE)
        self.assertEqual(restarted.get(run['id'])['status'],'running')
        self.assertEqual(self.request('POST','/api/runs/' + run['id'] + '/cancel',{})[0],200)
        self.assertEqual(self.completed(run['id'])['run']['status'],'cancelled')

    def test_success_lifecycle_and_language(self):
        (self.root / 'bridge-config.yaml').write_text('work:\n  enabled: true\ntheme: professional-de\n')
        self.assertEqual(self.service.language(), 'de')
        run = self.request('POST', '/api/runs', self.payload())[1]['run']
        self.assertEqual(self.completed(run['id'])['run']['status'], 'succeeded')
        log = (self.root / 'work/log.md').read_text()
        self.assertIn('queued', log)
        self.assertIn('succeeded', log)
        self.assertRegex(log, r'\| \d{4}-\d{2}-\d{2} \d{2}:\d{2} \|')

    def test_unknown_worker_is_interrupted_not_signalled(self):
        run = self.request('POST', '/api/runs', self.payload())[1]['run']
        self.completed(run['id'])
        path = self.service.path(run['id'])
        data = json.loads(path.read_text())
        data.update(status='running', pid=os.getpid(), process_identity='wrong')
        path.write_text(json.dumps(data))
        self.assertEqual(self.service.cancel(run['id'])['status'], 'interrupted')

    def test_failed_queue_and_abandoned_creator_release_project(self):
        with patch('ui_service.lifecycle', side_effect=ValueError('broken log')):
            run = self.service.create(self.payload())
        self.assertEqual(run['status'], 'failed')
        path = self.service.path(run['id'])
        data = json.loads(path.read_text())
        data.update(status='queued', creator_identity='dead')
        atomic(path, data)
        self.assertEqual(self.service.get(run['id'])['status'], 'interrupted')
        next_run = self.service.create(self.payload())
        self.assertEqual(self.completed(next_run['id'])['run']['status'], 'succeeded')

    def test_corrupt_manifest_and_leading_comment_task(self):
        directory = self.service.state / uuid.uuid4().hex
        directory.mkdir()
        (directory / 'run.json').write_text('null')
        self.assertEqual(self.request('GET', '/api/runs')[0], 200)
        task = self.root / 'work/tasks/example'
        task.mkdir(parents=True)
        (task / 'STATUS.md').write_text('# yaml-language-server: schema.json\n---\nstatus: doing\npriority: high\n---\n# Actual task title\n')
        self.assertEqual(self.service.tasks()[0]['title'], 'Actual task title')
        self.assertEqual(self.service.tasks()[0]['status'], 'doing')

    def test_worker_death_kills_cli_and_child(self):
        fake = self.bin / 'codex'
        pidfile = self.root / 'processes.json'
        fake.write_text('#!/usr/bin/env python3\nimport os,json,subprocess,time\np=subprocess.Popen(["sleep","30"])\nopen(' + repr(str(pidfile)) + ',"w").write(json.dumps([os.getpid(),p.pid]))\ntime.sleep(30)\n')
        run = self.service.create(self.payload('slow'))
        for _ in range(100):
            if pidfile.exists(): break
            time.sleep(.05)
        pids = json.loads(pidfile.read_text())
        manifest = self.service.get(run['id'])
        os.kill(manifest['pid'], 9)
        for _ in range(100):
            if all(identity(pid) is None for pid in pids): break
            time.sleep(.05)
        self.assertTrue(all(identity(pid) is None for pid in pids))
        self.assertEqual(self.service.get(run['id'])['status'], 'interrupted')

    def test_two_service_instances_serialize_project_creation(self):
        second = Service(self.root, SOURCE)
        run = self.service.create(self.payload('slow'))
        with self.assertRaises(FileExistsError):
            second.create(self.payload('slow'))
        self.service.cancel(run['id'])
        self.completed(run['id'])

    def test_unicode_prompt_remains_visible_and_idempotent(self):
        payload = self.payload('😀' * 7000)
        code, response, _ = self.request('POST', '/api/runs', payload)
        self.assertEqual(code, 200)
        run = response['run']
        self.assertEqual(self.service.get(run['id'])['prompt'], payload['prompt'])
        self.assertEqual(self.service.runs()[0]['id'], run['id'])
        self.assertEqual(self.request('POST', '/api/runs', payload)[1]['run']['id'], run['id'])
        self.assertEqual(self.completed(run['id'])['run']['status'], 'succeeded')

    def test_success_cleans_background_grandchild(self):
        fake = self.bin / 'codex'
        pidfile = self.root / 'background.json'
        fake.write_text('#!/usr/bin/env python3\nimport json,subprocess\np=subprocess.Popen(["sleep","30"])\nopen(' + repr(str(pidfile)) + ',"w").write(json.dumps(p.pid))\n')
        run = self.service.create(self.payload())
        self.assertEqual(self.completed(run['id'])['run']['status'], 'succeeded')
        self.assertIsNone(identity(json.loads(pidfile.read_text())))

    def test_cancel_allows_cli_graceful_flush(self):
        fake = self.bin / 'codex'
        marker = self.root / 'flushed'
        ready = self.root / 'ready'
        fake.write_text('#!/usr/bin/env python3\nimport signal,time,sys\ndef stop(sig,frame):\n time.sleep(.2)\n open(' + repr(str(marker)) + ',"w").write("done")\n sys.exit(0)\nsignal.signal(signal.SIGTERM,stop)\nopen(' + repr(str(ready)) + ',"w").write("ready")\ntime.sleep(30)\n')
        run = self.service.create(self.payload('slow'))
        for _ in range(100):
            if ready.exists(): break
            time.sleep(.05)
        self.service.cancel(run['id'])
        self.assertEqual(self.completed(run['id'])['run']['status'], 'cancelled')
        self.assertEqual(marker.read_text(), 'done')

    def test_content_lists_nested_archives_future_folders_and_sources(self):
        documents = {
            'AGENTS.md': '# Bridge',
            'rules/secret-placement.md': '# Secret placement rule',
            'docs/secrets-guide.md': '# Referencing secrets',
            'docs/token-budget.md': '# Budget',
            'work/done/2026-01/old/STATUS.md': '# Archived task',
            'work/tasks/new/attachments/notes.txt': 'Working notes',
            'future-knowledge/deep/überblick.yaml': 'name: Überblick',
            'scripts/sample.py': 'print("sample")',
            '.claude/agents/reviewer.md': '# Reviewer',
        }
        for name, text in documents.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        code, listing, _ = self.request('GET', '/api/content')
        self.assertEqual(code, 200)
        paths = [entry['path'] for entry in listing['entries']]
        self.assertEqual(paths, sorted(paths))
        for name in documents:
            self.assertIn(name, paths)
        self.assertTrue(listing['excluded'])
        for name, text in documents.items():
            code, document, _ = self.request('GET', '/api/content?path=' + quote(name, safe=''))
            self.assertEqual(code, 200)
            self.assertEqual(document['content'], text)
            self.assertFalse(document['truncated'])

    def test_content_denies_traversal_symlinks_credentials_and_binary(self):
        for name in ('credentials.json', 'access_token.txt', 'id_rsa', '.env', 'docs/env.yaml', 'docs/auth.json', 'docs/secret.yaml', 'node_modules/test.md'):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('do not expose')
        (self.root / 'binary.txt').write_bytes(b'binary\x00data')
        (self.root / 'nonutf8.txt').write_bytes(b'\xff\xfe\xfd' * 30)
        (self.root / 'escape.md').symlink_to('/etc/passwd')
        (self.root / 'redirect').symlink_to('/etc', target_is_directory=True)
        for name in ('../etc/passwd', '/etc/passwd', 'escape.md', 'redirect/hosts', 'credentials.json', 'access_token.txt', 'id_rsa', '.env', 'docs/env.yaml', 'docs/auth.json', 'docs/secret.yaml', 'node_modules/test.md', 'binary.txt', 'nonutf8.txt'):
            self.assertEqual(self.request('GET', '/api/content?path=' + quote(name, safe=''))[0], 404, name)
        listing = self.request('GET', '/api/content')[1]
        paths = {entry['path'] for entry in listing['entries']}
        self.assertNotIn('credentials.json', paths)
        self.assertNotIn('escape.md', paths)
        self.assertNotIn('binary.txt', paths)
        self.assertEqual(self.request('GET', '/api/content', headers={'Cookie': ''})[0], 403)
        self.assertEqual(self.request('GET', '/api/content?path=a&path=b')[0], 404)

    def test_content_large_text_is_explicitly_truncated(self):
        (self.root / 'large.md').write_text('x' * (256 * 1024 + 10))
        code, document, _ = self.request('GET', '/api/content?path=large.md')
        self.assertEqual(code, 200)
        self.assertTrue(document['truncated'])
        self.assertEqual(len(document['content']), 256 * 1024)

    def secondary_bridge(self, name='secondary'):
        root = self.root / name
        (root / 'scripts').mkdir(parents=True)
        (root / 'AGENTS.md').write_text('# ' + name)
        (root / 'scripts/bridge-config.py').write_text('# marker')
        (root / 'README.md').write_text(name)
        return root

    def test_bridge_selection_isolates_content_and_reuses_session(self):
        secondary = self.secondary_bridge()
        (self.root / 'README.md').write_text('primary')
        self.service.browse_roots = (secondary,)
        code, bootstrap, headers = self.request('GET', '/api/bootstrap')
        self.assertEqual(code, 200)
        self.assertEqual(self.request('GET', '/api/bootstrap', headers={'X-Bridge-ID': ''})[0], 200)
        self.assertEqual(bootstrap['csrf'], self.csrf)
        self.assertEqual(headers['Set-Cookie'].split(';')[0], self.cookie)
        choice = next(bridge for bridge in bootstrap['bridges'] if bridge['root'] == str(secondary))
        self.assertTrue(choice['read_only'])
        selected_header = {'X-Bridge-ID': choice['id']}
        selected = self.request('GET', '/api/bootstrap', headers=selected_header)[1]
        self.assertEqual(selected['bridge']['id'], choice['id'])
        self.assertEqual(selected['csrf'], self.csrf)
        self.assertEqual(selected['runs'], [])
        self.assertEqual(self.request('GET', '/api/content?path=README.md', headers=selected_header)[1]['content'], 'secondary')
        self.assertEqual(self.request('GET', '/api/content?path=README.md')[1]['content'], 'primary')
        self.assertEqual(self.request('POST', '/api/runs', self.payload(), selected_header)[0], 403)
        self.assertEqual(self.request('POST', '/api/runs/' + uuid.uuid4().hex + '/cancel', {}, selected_header)[0], 403)
        self.assertFalse((secondary / '.bridge').exists())
        self.assertEqual(self.request('GET', '/api/bootstrap', headers={'X-Bridge-ID': '/tmp'})[0], 404)
        self.assertEqual(self.request('GET', '/api/content', headers={'X-Bridge-ID': 'forged'})[0], 404)
        self.assertEqual(self.request('POST', '/api/runs', self.payload(), {'X-Bridge-ID': 'forged'})[0], 404)

    def test_bridge_discovery_uses_registry_instances_and_explicit_roots(self):
        registered = self.secondary_bridge('registered')
        instance = self.secondary_bridge('instance')
        explicit = self.secondary_bridge('explicit')
        ordinary = self.root / 'ordinary'; ordinary.mkdir()
        (self.root / 'ecosystem.yaml').write_text('repos:\n  registry-label:\n    path: ' + str(registered) + '\n  ordinary:\n    path: ' + str(ordinary) + '\n')
        declarations = self.root / 'infra/instances'; declarations.mkdir(parents=True)
        (declarations / 'sample.yaml').write_text('name: Instance label\nlocation:\n  path: ' + str(instance) + '\n')
        self.service.browse_roots = (explicit, ordinary)
        bridges = self.service.bridges()
        self.assertEqual({bridge['root'] for bridge in bridges}, {str(root) for root in (self.root, registered, instance, explicit)})
        self.assertEqual(next(bridge['name'] for bridge in bridges if bridge['root'] == str(registered)), 'registry-label')
        self.assertEqual(next(bridge['name'] for bridge in bridges if bridge['root'] == str(instance)), 'Instance label')
        for root in (registered, instance, explicit):
            self.assertFalse((root / '.bridge').exists())

    def test_tasks_reject_symlinked_work_and_kind_ancestors(self):
        with tempfile.TemporaryDirectory() as outside:
            task = Path(outside) / 'tasks/private'
            task.mkdir(parents=True)
            (task / 'STATUS.md').write_text('---\ntitle: OUTSIDE_SELECTED_BRIDGE\nstatus: doing\n---\n')
            work = self.root / 'work'
            work.symlink_to(outside, target_is_directory=True)
            self.assertEqual(self.service.tasks(), [])
            work.unlink()
            work.mkdir()
            (work / 'tasks').symlink_to(Path(outside) / 'tasks', target_is_directory=True)
            self.assertEqual(self.service.tasks(), [])
            self.assertNotIn('OUTSIDE_SELECTED_BRIDGE', json.dumps(self.request('GET', '/api/bootstrap')[1]))

    def test_security_task_slug_is_not_filtered_from_task_metadata(self):
        task = self.root / 'work/tasks/rotate-api-keys'
        task.mkdir(parents=True)
        (task / 'STATUS.md').write_text('---\nstatus: doing\n---\n# Rotate API keys\n')
        self.assertEqual(self.service.tasks()[0]['title'], 'Rotate API keys')
        self.assertEqual(self.request('GET', '/api/content?path=work/tasks/rotate-api-keys/STATUS.md')[0], 200)
        archived = self.root / 'work/done/2026-01/rotate-api-keys'
        archived.mkdir(parents=True)
        (archived / 'STATUS.md').write_text('# Archived security task')
        self.assertEqual(self.request('GET', '/api/content?path=work/done/2026-01/rotate-api-keys/STATUS.md')[0], 200)
        (task / 'credentials.json').write_text('private')
        self.assertEqual(self.request('GET', '/api/content?path=work/tasks/rotate-api-keys/credentials.json')[0], 404)

    def test_large_unicode_task_remains_visible_at_preview_boundary(self):
        task = self.root / 'work/tasks/unicode-large'
        task.mkdir(parents=True)
        prefix = '---\nstatus: doing\n---\n# Unicode task\n'
        prefix += 'x' * ((1 - len(prefix.encode())) % 4)
        (task / 'STATUS.md').write_text(prefix + '😀' * 20000)
        self.assertEqual(self.service.tasks()[0]['title'], 'Unicode task')
        self.assertEqual(self.service.tasks()[0]['status'], 'doing')

    def test_editor_saves_valid_documents_backup_mode_and_conflicts(self):
        path = self.root / 'README.md'; path.write_text('# Original')
        path.chmod(0o640)
        doc = self.request('GET', '/api/content?path=README.md')[1]
        payload = {'path': 'README.md', 'content': '# Updated', 'revision': doc['revision']}
        code, saved, _ = self.request('POST', '/api/content', payload)
        self.assertEqual(code, 200)
        self.assertEqual(path.read_text(), '# Updated')
        self.assertEqual(path.stat().st_mode & 0o777, 0o640)
        backup = self.root / saved['backup']
        self.assertEqual(backup.read_text(), '# Original')
        self.assertEqual(backup.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.request('POST', '/api/content', payload)[0], 409)
        self.assertEqual(path.read_text(), '# Updated')
        config = self.root / 'sample.yaml'; config.write_text('value: before\n')
        before = self.request('GET', '/api/content?path=sample.yaml')[1]
        self.assertEqual(self.request('POST', '/api/content', {'path': 'sample.yaml', 'content': 'value: after\n', 'revision': before['revision']})[0], 200)

    def test_editor_validation_and_security_preserve_original(self):
        path = self.root / 'config.yaml'; path.write_text('valid: true\n')
        revision = self.request('GET', '/api/content?path=config.yaml')[1]['revision']
        payload = {'path': 'config.yaml', 'content': 'broken: [', 'revision': revision}
        self.assertEqual(self.request('POST', '/api/content', payload)[0], 400)
        self.assertEqual(path.read_text(), 'valid: true\n')
        payload['content'] = 'valid: false\n'
        self.assertEqual(self.request('POST', '/api/content', payload, {'X-Bridge-CSRF': 'wrong'})[0], 403)
        payload['revision'] = '0' * 64
        self.assertEqual(self.request('POST', '/api/content', payload)[0], 409)
        for name in ('../outside.md', 'missing.md'):
            payload['path'] = name
            self.assertIn(self.request('POST', '/api/content', payload)[0], (400, 404))
        link = self.root / 'linked.yaml'; link.symlink_to(path)
        payload['path'] = 'linked.yaml'
        self.assertIn(self.request('POST', '/api/content', payload)[0], (400, 404))
        os.link(path, self.root / 'hard.yaml')
        doc = self.request('GET', '/api/content?path=hard.yaml')[1]
        self.assertFalse(doc['editable'])
        self.assertEqual(self.request('POST', '/api/content', {'path': 'hard.yaml', 'content': 'valid: false', 'revision': doc['revision']})[0], 400)
        large = self.root / 'large.md'; large.write_text('x' * (256 * 1024 + 1))
        doc = self.request('GET', '/api/content?path=large.md')[1]
        self.assertFalse(doc['editable'])
        self.assertEqual(self.request('POST', '/api/content', {'path': 'large.md', 'content': 'short', 'revision': doc['revision']})[0], 400)

    def test_editor_secondary_isolation_and_log_warning(self):
        secondary = self.secondary_bridge()
        self.service.browse_roots = (secondary,)
        (self.root / 'README.md').write_text('primary unchanged')
        choice = next(item for item in self.service.bridges() if item['root'] == str(secondary))
        self.assertTrue(choice['content_editable'])
        header = {'X-Bridge-ID': choice['id']}
        doc = self.request('GET', '/api/content?path=README.md', headers=header)[1]
        (secondary / 'bridge-config.yaml').write_text('work:\n  enabled: true\n')
        (secondary / 'work').symlink_to(self.root, target_is_directory=True)
        code, saved, _ = self.request('POST', '/api/content', {'path': 'README.md', 'content': 'secondary updated', 'revision': doc['revision']}, header)
        self.assertEqual(code, 200)
        self.assertIn('warning', saved)
        self.assertEqual((secondary / 'README.md').read_text(), 'secondary updated')
        self.assertEqual((self.root / 'README.md').read_text(), 'primary unchanged')
        self.assertEqual((secondary / saved['backup']).read_text(), 'secondary')
        self.assertFalse((self.root / 'log.md').exists())
        self.assertEqual(self.request('POST', '/api/runs', self.payload(), header)[0], 403)

    def test_editor_invalid_frontmatter_and_json_are_not_saved(self):
        for name, original, invalid in [('note.md', '# Valid', '---\nbroken: [\n---\n# Note'), ('data.json', '{"valid": true}', '{invalid}'), ('nan.json', '{"valid": true}', '{"a": NaN}'), ('infinity.json', '{}', '{"a": Infinity}')]:
            path = self.root / name; path.write_text(original)
            doc = self.request('GET', '/api/content?path=' + name)[1]
            self.assertEqual(self.request('POST', '/api/content', {'path': name, 'content': invalid, 'revision': doc['revision']})[0], 400)
            self.assertEqual(path.read_text(), original)

    def test_editor_committed_durability_failure_reports_success_warning(self):
        path = self.root / 'README.md'; path.write_text('before')
        revision = self.service.content('README.md')['revision']
        original_fsync = os.fsync
        def fail_parent(fd):
            if os.fstat(fd).st_ino == self.root.stat().st_ino:
                raise OSError('directory fsync unavailable')
            return original_fsync(fd)
        with patch('ui_service.os.fsync', side_effect=fail_parent):
            saved = self.service.save_content({'path': 'README.md', 'content': 'after', 'revision': revision})
        self.assertEqual(path.read_text(), 'after')
        self.assertIn('durability', saved['warning'])
        self.assertEqual((self.root / saved['backup']).read_text(), 'before')

    def test_editor_precommit_failure_preserves_original_and_large_reads_bounded(self):
        path = self.root / 'README.md'; path.write_text('before')
        revision = self.service.content('README.md')['revision']
        with patch('ui_service.os.fsync', side_effect=OSError('fsync failed')):
            with self.assertRaises(OSError):
                self.service.save_content({'path': 'README.md', 'content': 'after', 'revision': revision})
        self.assertEqual(path.read_text(), 'before')
        path.write_text('x' * (1024 * 1024))
        original_read = os.read
        sizes = []
        def measured(fd, size):
            block = original_read(fd, size); sizes.append(len(block)); return block
        with patch('ui_service.os.read', side_effect=measured):
            document = self.service.content('README.md')
        self.assertIsNone(document['revision'])
        self.assertFalse(document['editable'])
        self.assertLessEqual(sum(sizes), 256 * 1024 + 1)

    def test_editor_records_selected_work_log_and_does_not_log_itself(self):
        (self.root / 'bridge-config.yaml').write_text('work:\n  enabled: true\n')
        (self.root / 'README.md').write_text('before')
        revision = self.service.content('README.md')['revision']
        self.service.save_content({'path': 'README.md', 'content': 'after', 'revision': revision})
        log = self.root / 'work/log.md'
        self.assertIn('Edited README.md', log.read_text())
        revision = self.service.content('work/log.md')['revision']
        self.service.save_content({'path': 'work/log.md', 'content': '# User log text\n', 'revision': revision})
        self.assertEqual(log.read_text(), '# User log text\n')

    def test_symlink_state_denied(self):
        other = self.root / 'other'; other.mkdir()
        (other / '.bridge').symlink_to(self.root / '.bridge', target_is_directory=True)
        with self.assertRaises(ValueError): Service(other,SOURCE)

    def test_content_fulltext_and_backup_boundaries(self):
        (self.root / 'README.md').write_text('# Unique searchable phrase\n')
        (self.root / '.env').write_text('Unique searchable phrase')
        (self.root / 'outside.md').symlink_to('/etc/passwd')
        code, result, _ = self.request('GET', '/api/content/search?q=searchable')
        self.assertEqual(code, 200)
        self.assertEqual([entry['path'] for entry in result['entries']], ['README.md'])
        self.assertEqual(result['entries'][0]['line'], 1)
        self.assertEqual(self.request('GET', '/api/content/search?q=x')[0], 404)
        doc = self.request('GET', '/api/content?path=README.md')[1]
        saved = self.request('POST', '/api/content', {'path': 'README.md', 'content': '# Changed', 'revision': doc['revision']})[1]
        listing = self.request('GET', '/api/content/backups?path=README.md')[1]
        backup = listing['entries'][0]['id']
        restored = self.request('GET', '/api/content/backups?path=README.md&backup=' + backup)[1]
        self.assertEqual(restored['content'], '# Unique searchable phrase\n')
        self.assertEqual((self.root / 'README.md').read_text(), '# Changed')
        self.assertNotEqual(self.request('GET', '/api/content/backups?path=README.md&backup=../../README.md')[0], 200)
        (self.root / 'other.md').write_text('Other')
        self.assertNotEqual(self.request('GET', '/api/content/backups?path=other.md&backup=' + backup)[0], 200)
        target = self.root / saved['backup']
        target.unlink(); target.symlink_to(self.root / 'README.md')
        self.assertNotEqual(self.request('GET', '/api/content/backups?path=README.md&backup=' + backup)[0], 200)

    def test_registry_interpolation(self):
        project = self.root / 'project'; project.mkdir(); (project / '.git').mkdir()
        (self.root / 'bridge-config.yaml').write_text('identity:\n  projects_root: ' + str(self.root) + '\n')
        (self.root / 'ecosystem.yaml').write_text('repos:\n  sample:\n    path: ${projects_root}/project\n  missing:\n    path: ${unknown}/x\n')
        projects = self.service.projects()
        self.assertEqual(len(projects),2)
        self.assertEqual(projects[1]['name'],'sample')

if __name__ == '__main__': unittest.main()
