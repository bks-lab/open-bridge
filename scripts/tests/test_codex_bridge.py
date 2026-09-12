"""Behavioral contract: dirty baselines, commits, deletions, routing and checkpoints."""
import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().parents[1] / 'codex-bridge.py'
spec = importlib.util.spec_from_file_location('codex_bridge', SCRIPT)
bridge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bridge)


class CodexBridgeTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.git('init', '-q')
        self.git('checkout', '-qb', 'user/fixture')
        (self.root / 'bridge-config.yaml').write_text('work:\n  enabled: true\n')
        self.git('config', 'user.name', 'Fixture')
        self.git('config', 'user.email', 'fixture@example.invalid')
        (self.root / 'work').mkdir()
        (self.root / 'work/log.md').write_text('existing log\n')
        (self.root / 'sample.txt').write_text('base')
        self.git('add', '.')
        self.git('commit', '-qm', 'baseline')

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args], check=True, capture_output=True)

    def test_dirty_log_from_earlier_turn_does_not_mask_new_work(self):
        log = self.root / 'work/log.md'
        log.write_text('earlier turn\n')
        before = bridge.snapshot(self.root)
        (self.root / 'sample.txt').write_text('new work')
        self.assertTrue(bridge.needs_log(before, bridge.snapshot(self.root)))
        log.write_text('earlier turn\nnew substantive row\n')
        self.assertFalse(bridge.needs_log(before, bridge.snapshot(self.root)))

    def test_unchanged_dirty_baseline_is_read_only(self):
        (self.root / 'sample.txt').write_text('preexisting')
        before = bridge.snapshot(self.root)
        self.assertFalse(bridge.needs_log(before, bridge.snapshot(self.root)))

    def test_commit_cannot_hide_work(self):
        before = bridge.snapshot(self.root)
        (self.root / 'sample.txt').write_text('committed change')
        self.git('add', 'sample.txt')
        self.git('commit', '-qm', 'work')
        self.assertTrue(bridge.needs_log(before, bridge.snapshot(self.root)))

    def test_deleted_file_and_untracked_space_name(self):
        before = bridge.snapshot(self.root)
        (self.root / 'sample.txt').unlink()
        (self.root / 'new file.txt').write_text('new')
        after = bridge.snapshot(self.root)
        self.assertIn('new file.txt', after['files'])
        self.assertTrue(bridge.needs_log(before, after))

    def test_symlink_does_not_read_target(self):
        (self.root / 'link').symlink_to('/nonexistent/private-target')
        self.assertEqual(bridge.snapshot(self.root)['files']['link'], 'symlink:/nonexistent/private-target')

    def test_doctor_detects_catalog_not_registered(self):
        (self.root / 'AGENTS.md').write_text('fixture')
        (self.root / 'skills').mkdir()
        (self.root / '.agents').mkdir()
        (self.root / '.agents/skills').symlink_to('../skills')
        catalog = self.root / 'work/knowledge/repositories'
        catalog.mkdir(parents=True)
        (catalog / 'catalog.json').write_text(json.dumps({'repositories': [{'id': 'demo', 'path': '/projects/demo'}]}))
        self.assertTrue(bridge.doctor(self.root))
        (self.root / 'ecosystem.yaml').write_text('base:\n  demo:\n    path: /projects/demo\n')
        self.assertFalse(bridge.doctor(self.root))

    def test_disabled_work_and_core_development_do_not_require_log(self):
        (self.root / 'bridge-config.yaml').write_text('work:\n  enabled: false\n')
        before = bridge.snapshot(self.root)
        (self.root / 'sample.txt').write_text('disabled work')
        self.assertFalse(bridge.needs_log(before, bridge.snapshot(self.root)))
        (self.root / 'bridge-config.yaml').write_text('work:\n  enabled: true\n')
        self.git('checkout', '-qb', 'feature/demo')
        self.assertFalse(bridge.snapshot(self.root)['work_enabled'])

    def test_shared_hook_status_only_skips_legacy_log_gate(self):
        import os
        hook = SCRIPT.parents[1] / 'scripts/worklog-drift-check.sh'
        log = self.root / 'work/log.md'
        os.utime(log, (1, 1))
        (self.root / 'changed.md').write_text('preexisting dirty file')
        result = subprocess.run(['bash', str(hook)], cwd=self.root,
            env={**os.environ, 'BRIDGE_PROJECT_DIR': str(self.root), 'BRIDGE_STATUS_ONLY': '1'}, capture_output=True)
        self.assertEqual(result.returncode, 0)
        task = self.root / 'work/tasks/example'
        task.mkdir(parents=True)
        (task / 'STATUS.md').write_text('---\nstatus: doing\n---\n# Done\n')
        result = subprocess.run(['bash', str(hook)], cwd=self.root,
            env={**os.environ, 'BRIDGE_PROJECT_DIR': str(self.root), 'BRIDGE_STATUS_ONLY': '1'}, capture_output=True)
        self.assertEqual(result.returncode, 2)

    def test_doctor_resolves_identity_and_relative_paths(self):
        (self.root / 'AGENTS.md').write_text('fixture')
        (self.root / 'skills').mkdir()
        (self.root / '.agents').mkdir()
        (self.root / '.agents/skills').symlink_to('../skills')
        (self.root / 'bridge-config.yaml').write_text('identity:\n  projects_root: /projects\n')
        catalog = self.root / 'work/knowledge/repositories'
        catalog.mkdir(parents=True)
        (catalog / 'catalog.json').write_text(json.dumps({'repositories': [
            {'id': 'demo', 'path': '/projects/demo'}, {'id': 'relative', 'path': str(self.root / 'relative')}]}))
        (self.root / 'ecosystem.yaml').write_text('base:\n  demo:\n    path: ${projects_root}/demo\n  relative:\n    path: relative\n')
        self.assertFalse(bridge.doctor(self.root))

    def test_parent_symlink_is_rejected(self):
        with tempfile.TemporaryDirectory() as target:
            (self.root / '.bridge').symlink_to(target)
            result = subprocess.run(['python3', str(SCRIPT), 'start', '--root', str(self.root), '--session-id', 'test'], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((Path(target) / 'codex-sessions').exists())

    def test_start_finish_workflow(self):
        import shutil
        scripts = self.root / 'scripts'
        scripts.mkdir()
        for name in ('bridge-config.py', 'worklog.py'):
            shutil.copyfile(SCRIPT.parent / name, scripts / name)
        def command(action):
            return subprocess.run(['python3', str(SCRIPT), action, '--root', str(self.root), '--session-id', 'turn'], capture_output=True)
        self.assertEqual(command('start').returncode, 0)
        (self.root / 'sample.txt').write_text('work')
        self.assertEqual(command('finish').returncode, 2)
        (self.root / 'work/log.md').write_text('new substantive row')
        self.assertEqual(command('finish').returncode, 0)
        self.assertFalse((self.root / '.bridge/codex-sessions/turn.json').exists())

    def test_checkpoint_reuse_and_missing_finish_fail(self):
        def command(action):
            return subprocess.run(['python3', str(SCRIPT), action, '--root', str(self.root), '--session-id', 'test'], capture_output=True)
        self.assertNotEqual(command('finish').returncode, 0)
        # No context scripts in fixture: start fails AFTER preserving checkpoint.
        command('start')
        self.assertTrue((self.root / '.bridge/codex-sessions/test.json').is_file())
        self.assertNotEqual(command('start').returncode, 0)


if __name__ == '__main__':
    unittest.main()
