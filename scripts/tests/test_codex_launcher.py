"""Codex-only launcher integration: no Claude files, fake CLI boundary."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[2]


class LauncherTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'bridge with spaces'
        self.root.mkdir()
        for name in ('bin/open-bridge-codex', 'scripts/codex-bridge.py', 'scripts/worklog-drift-check.sh'):
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(ROOT / name, path)
        (self.root / 'scripts/hooks').mkdir()
        (self.root / '.agents').mkdir()
        (self.root / 'skills').mkdir()
        (self.root / '.agents/skills').symlink_to('../skills')
        (self.root / 'AGENTS.md').write_text('fixture')
        (self.root / 'bridge-config.yaml').write_text('work:\n  enabled: true\n')
        (self.root / 'work').mkdir()
        (self.root / 'work/log.md').write_text('old log\n')
        self.git('init', '-q', '-b', 'user/test')
        self.git('add', '.')
        self.git('-c', 'user.name=Fixture', '-c', 'user.email=fixture@example.invalid', 'commit', '-qm', 'fixture')
        fake = Path(self.temp.name) / 'tools'
        fake.mkdir()
        codex = fake / 'codex'
        codex.write_text('''#!/usr/bin/env python3
import json, os, pathlib, sys, signal
pathlib.Path(os.environ['CAPTURE']).write_text(json.dumps(sys.argv[1:]))
if os.environ.get('EDIT'):
    pathlib.Path('sample.md').write_text('work')
if os.environ.get('LOG'):
    with pathlib.Path('work/log.md').open('a') as stream: stream.write('new row\\n')
if os.environ.get('SIGNAL'): os.kill(os.getpid(), int(os.environ['SIGNAL']))
sys.exit(int(os.environ.get('CLI_EXIT', '0')))
''')
        codex.chmod(0o755)
        self.capture = Path(self.temp.name) / 'capture.json'
        self.env = {**os.environ, 'PATH': str(fake) + os.pathsep + os.environ['PATH'], 'CAPTURE': str(self.capture)}

    def git(self, *args):
        return subprocess.run(['git', '-C', str(self.root), *args], check=True, capture_output=True)

    def launch(self, *args, **env):
        return subprocess.run([str(self.root / 'bin/open-bridge-codex'), *args], env={**self.env, **env}, capture_output=True, text=True)

    def test_interactive_and_exec_forward_arguments_without_claude(self):
        self.assertFalse((self.root / '.claude').exists())
        for prefix in ([], ['--exec']):
            result = self.launch(*prefix, '--', 'a prompt with spaces')
            self.assertEqual(result.returncode, 0, result.stderr + result.stdout)
            captured = json.loads(self.capture.read_text())
            self.assertEqual(captured, (['exec'] if prefix else []) + ['-C', str(self.root), 'a prompt with spaces'])

    def test_exit_checks_detect_unlogged_work_and_preserve_checkpoint(self):
        result = self.launch('--', 'work', EDIT='1')
        self.assertEqual(result.returncode, 2, result.stderr + result.stdout)
        self.assertEqual(len(list((self.root / '.bridge/codex-sessions').glob('*.json'))), 1)

    def test_logged_work_passes_and_cli_failure_survives(self):
        self.assertEqual(self.launch('--exec', '--', 'work', EDIT='1', LOG='1').returncode, 0)
        self.assertEqual(self.launch('--', 'fail', CLI_EXIT='7').returncode, 7)

    def test_cwd_override_rejected_before_launch(self):
        for args in (['-C', '/tmp'], ['--cd=/tmp'], ['--worktree']):
            self.assertEqual(self.launch('--', *args).returncode, 2)
        self.assertFalse(self.capture.exists())

    def test_signalled_cli_still_checks_and_retains_unlogged_work(self):
        import signal
        for sig in (signal.SIGINT, signal.SIGTERM):
            result = self.launch('--', 'work', EDIT='1', SIGNAL=str(sig))
            self.assertEqual(result.returncode, 128 + sig, result.stderr)
        self.assertTrue(list((self.root / '.bridge/codex-sessions').glob('*.json')))

    def test_custom_hooks_preserved(self):
        self.git('config', 'core.hooksPath', 'custom-hooks')
        self.assertEqual(self.launch('--', 'work').returncode, 1)
        self.assertEqual(self.git('config', '--get', 'core.hooksPath').stdout.decode().strip(), 'custom-hooks')
        self.assertFalse(self.capture.exists())


if __name__ == '__main__':
    unittest.main()
