"""Codex-only launcher integration: no Claude files, fake CLI boundary."""
import json
import os
from pathlib import Path
import shutil
import sys
import subprocess
import tempfile
import signal
import time
import pty
import unittest

ROOT = Path(__file__).resolve().parents[2]


class LauncherTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / 'bridge with spaces'
        self.root.mkdir()
        for name in ('bin/open-bridge-codex', 'scripts/codex-bridge.py', 'scripts/worklog-drift-check.sh', 'scripts/lib/__init__.py', 'scripts/lib/cli_launcher.py', 'scripts/lib/cli_bridge.py'):
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
if os.environ.get('JSON'): print('{"ok":true}', flush=True)
if os.environ.get('DESCENDANT'):
    import subprocess
    descendant = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)'])
    pathlib.Path(os.environ['DESCENDANT']).write_text(str(descendant.pid))
if os.environ.get('READTTY'):
    assert os.isatty(0)
    pathlib.Path(os.environ['READTTY']).write_bytes(os.read(0, 32))
if os.environ.get('WAIT'):
    import time
    if os.environ.get('IGNORE'): signal.signal(signal.SIGTERM, signal.SIG_IGN)
    pathlib.Path(os.environ['READY']).write_text(str(os.getpid()))
    while True: time.sleep(0.1)
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

    def test_child_json_is_the_entire_stdout(self):
        result = self.launch('--exec', '--', '--json', JSON='1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(json.loads(result.stdout), {'ok': True})
        self.assertEqual(result.stdout, '{"ok":true}\n')

    def test_wrapper_signals_reap_child_and_run_completion(self):
        for sig, ignore in ((signal.SIGINT, ''), (signal.SIGTERM, ''), (signal.SIGTERM, '1'), (signal.SIGTERM, 'repeat')):
            with self.subTest(sig=sig, ignore=ignore):
                ready = Path(self.temp.name) / 'ready'
                ready.unlink(missing_ok=True)
                (self.root / 'sample.md').unlink(missing_ok=True)
                process = subprocess.Popen([str(self.root / 'bin/open-bridge-codex'), '--exec', '--', 'work'],
                    env={**self.env, 'WAIT': '1', 'EDIT': '1', 'READY': str(ready), 'IGNORE': ignore, 'DESCENDANT': str(Path(self.temp.name) / 'descendant')},
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    deadline = time.monotonic() + 10
                    while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                        time.sleep(0.02)
                    self.assertTrue(ready.exists(), 'fake CLI did not start')
                    child_pid = int(ready.read_text())
                    process.send_signal(sig)
                    if ignore == 'repeat':
                        time.sleep(0.1)
                        process.send_signal(sig)
                    stdout, stderr = process.communicate(timeout=10)
                    self.assertEqual(process.returncode, 128 + sig, stderr)
                    self.assertEqual(stdout, '')
                    descendant_pid = int((Path(self.temp.name) / 'descendant').read_text())
                    proc_status = Path(f'/proc/{descendant_pid}/status')
                    if proc_status.exists():
                        self.assertIn('State:\tZ', proc_status.read_text(), 'descendant still running')
                    self.assertIn('completion check failed', stderr)
                    with self.assertRaises(ProcessLookupError):
                        os.kill(child_pid, 0)
                finally:
                    if process.poll() is None:
                        process.kill()
                        process.communicate()

    def test_terminal_input_and_wrapper_cancellation(self):
        master, slave = pty.openpty()
        ready = Path(self.temp.name) / 'tty-ready'
        readback = Path(self.temp.name) / 'tty-input'
        process = subprocess.Popen([str(self.root / 'bin/open-bridge-codex'), '--', 'work'],
            env={**self.env, 'WAIT': '1', 'EDIT': '1', 'READY': str(ready), 'READTTY': str(readback)},
            stdin=slave, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        os.close(slave)
        try:
            os.write(master, b'terminal input\n')
            deadline = time.monotonic() + 10
            while not ready.exists() and process.poll() is None and time.monotonic() < deadline:
                time.sleep(0.02)
            self.assertTrue(ready.exists(), 'CLI could not read terminal input')
            self.assertEqual(readback.read_text(), 'terminal input\n')
            child_pid = int(ready.read_text())
            process.send_signal(signal.SIGTERM)
            _, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 143, stderr)
            self.assertIn('completion check failed', stderr)
            with self.assertRaises(ProcessLookupError):
                os.kill(child_pid, 0)
        finally:
            os.close(master)
            if process.poll() is None:
                process.kill()
                process.communicate()

    def test_missing_cli_is_clean_and_doctor_does_not_need_cli(self):
        isolated = Path(self.temp.name) / 'no-cli'
        isolated.mkdir()
        (isolated / 'python3').symlink_to(sys.executable)
        (isolated / 'git').symlink_to(shutil.which('git'))
        result = self.launch('--', 'work', PATH=str(isolated))
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn('CLI is not on PATH', result.stderr)
        self.assertNotIn('Traceback', result.stderr)
        self.assertEqual(self.launch('--check', PATH=str(isolated)).returncode, 0)

    def test_custom_hooks_preserved(self):
        self.git('config', 'core.hooksPath', 'custom-hooks')
        self.assertEqual(self.launch('--', 'work').returncode, 1)
        self.assertEqual(self.git('config', '--get', 'core.hooksPath').stdout.decode().strip(), 'custom-hooks')
        self.assertFalse(self.capture.exists())


if __name__ == '__main__':
    unittest.main()
