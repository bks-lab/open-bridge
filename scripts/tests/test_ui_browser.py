#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Run the browser workflow against a real service and disposable fake clients."""
import os
from pathlib import Path
import shutil
import selectors
import subprocess
import sys
import tempfile

SOURCE = Path(__file__).resolve().parents[2]

def main():
    with tempfile.TemporaryDirectory(prefix='bridge-ui-browser-') as directory, tempfile.TemporaryDirectory(prefix='bridge-ui-secondary-') as secondary_directory:
        root = Path(directory)
        (root / 'bridge-config.yaml').write_text('language:\n  conversation: de\nwork:\n  enabled: false\n')
        (root / '.gitignore').write_text('.bridge/\nbin/\n')
        (root / 'README.md').write_text('# Browser fixture\n')
        task = root / 'work/tasks/example'
        task.mkdir(parents=True)
        (task / 'STATUS.md').write_text('---\nstatus: doing\npriority: P1\n---\n# Browser task\n')
        subprocess.run(['git', 'init', '-q', str(root)], check=True)
        subprocess.run(['git', '-C', str(root), 'add', 'README.md', '.gitignore', 'bridge-config.yaml', 'work'], check=True)
        subprocess.run(['git', '-C', str(root), '-c', 'user.name=Test', '-c', 'user.email=test@example.com', 'commit', '-qm', 'Fixture'], check=True)
        # More than one overview page: no file/project should require a known query.
        projects = []
        for number in range(18):
            project = root / f'project-{number:02}'
            project.mkdir()
            (project / '.git').mkdir()
            projects.append(f'  - name: Project {number:02}\n    path: {project}\n')
        secondary = Path(secondary_directory)
        (secondary / 'scripts').mkdir()
        (secondary / 'docs').mkdir()
        (secondary / 'AGENTS.md').write_text('# Secondary Bridge\n')
        (secondary / 'scripts/bridge-config.py').write_text('# Marker fixture\n')
        (secondary / 'docs/content-example.md').write_text('# Secondary-only document\n')
        projects.append(f'  - name: Secondary Bridge\n    path: {secondary}\n')
        (root / 'ecosystem.yaml').write_text('projects:\n' + ''.join(projects))
        for name in ('docs', 'identity/agent', 'infra/remotes', 'work/done/2026-08/closed'):
            (root / name).mkdir(parents=True, exist_ok=True)
        for number in range(65):
            (root / f'docs/page-{number:02}.md').write_text(f'# Indexed page {number}\n')
        (root / 'docs/content-example.md').write_text('# Full Bridge content\nLiteral <script>window.contentExecuted=true</script>\n')
        (root / 'identity/agent/SOUL.md').write_text('# Agent identity\nFixture principles.\n')
        (root / 'infra/remotes/local.yaml').write_text('name: Local fixture\n')
        (root / 'work/done/2026-08/closed/STATUS.md').write_text('# Archived task\nHistoric work.\n')
        (root / '.env').write_text('TOKEN=hidden-browser-fixture\n')
        binary = root / 'bin'
        binary.mkdir()
        fake = '''#!/usr/bin/env python3
import json, pathlib, sys, time
prompt = sys.argv[sys.argv.index('-p') + 1] if '-p' in sys.argv else sys.argv[-1]
print(json.dumps({'message': 'Browser client started'}), flush=True)
time.sleep(30 if 'slow task' in prompt else 3)
if 'edit fixture' in prompt:
    with pathlib.Path('README.md').open('a') as stream: stream.write('Browser-tested local edit.\\n')
print(json.dumps({'message': 'Browser client completed'}), flush=True)
'''
        for name in ('codex', 'vibe'):
            path = binary / name
            path.write_text(fake)
            path.chmod(0o700)
        env = dict(os.environ, PATH=str(binary) + os.pathsep + os.environ['PATH'])
        server = subprocess.Popen([sys.executable, str(SOURCE / 'scripts/bridge-ui.py'), '--bridge-root', str(root), '--port', '0'], env=env, stdout=subprocess.PIPE, text=True)
        try:
            with selectors.DefaultSelector() as selector:
                selector.register(server.stdout, selectors.EVENT_READ)
                if not selector.select(timeout=15):
                    raise TimeoutError('Local service readiness exceeded 15 seconds')
            line = server.stdout.readline().strip()
            if not line.startswith('Open Bridge UI: http://127.0.0.1:'):
                raise RuntimeError('Service failed to start: ' + line)
            subprocess.run([shutil.which('node') or 'node', str(SOURCE / 'scripts/tests/test_ui_browser.mjs'), line.split(': ', 1)[1]], check=True, cwd=SOURCE, timeout=120)
            assert not (secondary / '.bridge/ui/runs').exists(), 'Secondary file editing created run state'
            assert list((secondary / '.bridge/ui/backups').glob('*.bak')), 'Editor backup missing'
            assert (secondary / 'docs/content-example.md').read_text() == '# Concurrent secondary document\n'
            assert 'Full Bridge content' in (root / 'docs/content-example.md').read_text(), 'Secondary save changed primary'
        finally:
            server.terminate()
            try:
                server.wait(timeout=10)
            except subprocess.TimeoutExpired:
                server.kill()
                server.wait()

if __name__ == '__main__':
    main()
