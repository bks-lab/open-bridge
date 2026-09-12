# SPDX-License-Identifier: MIT
"""Shared client launcher; keep CLI stdout separate from Bridge diagnostics."""
import argparse
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time
import uuid


def run_child(command, root, finish):
    """Forward wrapper signals, reap the child, then run the completion gate.

    Detached pipes get an owned process group so subprocesses receive cancellation.
    Terminal clients retain their foreground group and terminal access.
    A repeated cancellation escalates to SIGKILL; an ignored first signal is
    escalated after five seconds, so a wrapper cannot leave its child running.
    """
    child = None
    received = []
    deadline = None
    grouped = not sys.stdin.isatty()
    previous = {}

    def forward(sig):
        if child is None:
            return
        try:
            if grouped:
                os.killpg(child.pid, sig)
            else:
                child.send_signal(sig)
        except ProcessLookupError:
            pass

    def cancelled(sig, frame):
        nonlocal deadline
        received.append(sig)
        deadline = time.monotonic() + 5
        forward(signal.SIGKILL if len(received) > 1 else sig)

    for sig in (signal.SIGINT, signal.SIGTERM):
        previous[sig] = signal.signal(sig, cancelled)
    try:
        try:
            child = subprocess.Popen(command, cwd=root, start_new_session=grouped)
            if received:
                forward(signal.SIGKILL if len(received) > 1 else received[0])
            while True:
                try:
                    code = child.wait(timeout=0.1)
                    break
                except subprocess.TimeoutExpired:
                    if deadline is not None and time.monotonic() >= deadline:
                        forward(signal.SIGKILL)
            if received and grouped:
                # The direct child may exit before a signal-ignoring descendant.
                forward(signal.SIGKILL)
            child = None  # Never signal a reaped PID while the completion gate runs.
        finally:
            checked = finish()
        if received:
            return 128 + received[0]
        return (128 - code if code < 0 else code) or checked
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def main(client, root):
    parser = argparse.ArgumentParser(description=f'Open Bridge {client.title()} CLI launcher', allow_abbrev=False)
    parser.add_argument('--check', action='store_true', help='Check this checkout without launching the CLI')
    if client == 'vibe':
        parser.add_argument('--exec', dest='prompt', metavar='PROMPT', help='Run Vibe programmatically with this prompt')
    else:
        parser.add_argument('--exec', dest='noninteractive', action='store_true', help='Run codex exec')
    args, forwarded = parser.parse_known_args()
    if forwarded[:1] == ['--']:
        forwarded = forwarded[1:]
    for value in forwarded:
        option = value.split('=', 1)[0]
        forbidden = ('--workdir', '--worktree', '--add-dir')
        if client == 'vibe':
            invalid = option.startswith('--') and len(option) > 2 and any(full.startswith(option) for full in forbidden)
        else:
            invalid = option in ('--cd', '--worktree', '--remote') or value.startswith('-C')
        if invalid:
            parser.error('checkout/worktree overrides are not supported: checks must cover the launched checkout')
        if client == 'vibe' and args.prompt is not None and (value.startswith('-p') or (option.startswith('--') and len(option) > 2 and '--prompt'.startswith(option))):
            parser.error('use --exec instead of an additional Vibe prompt option')
    try:
        import yaml  # noqa: F401
    except ImportError:
        print('PyYAML is required. Install Bridge dependencies in your Python environment.', file=sys.stderr)
        return 1
    adapter = root / f'scripts/{client}-bridge.py'

    def bridge(command, *extra):
        return subprocess.run([sys.executable, str(adapter), command, '--root', str(root), *extra], cwd=root, stdout=sys.stderr).returncode

    if args.check:
        return bridge('doctor')
    executable = shutil.which(client)
    if not executable:
        print(f'{client.title()} CLI is not on PATH. Install it and authenticate before launching.', file=sys.stderr)
        return 1
    hooks = subprocess.run(['git', '-C', str(root), 'config', '--get', 'core.hooksPath'], capture_output=True, text=True)
    if hooks.returncode not in (0, 1):
        print('Cannot read Git hook configuration.', file=sys.stderr)
        return 1
    if hooks.stdout.strip() not in ('', 'scripts/hooks'):
        print('Custom core.hooksPath detected. Integrate Bridge push protection before using this launcher; existing hooks were preserved.', file=sys.stderr)
        return 1
    subprocess.run(['git', '-C', str(root), 'config', 'core.hooksPath', 'scripts/hooks'], check=True)
    token = 'cli-' + uuid.uuid4().hex
    if bridge('checkpoint', '--session-id', token):
        return 1
    command = [executable]
    if client == 'vibe':
        command.extend(['--workdir', str(root)])
        if args.prompt is not None:
            command.extend(['-p', args.prompt])
    else:
        if args.noninteractive:
            command.append('exec')
        command.extend(['-C', str(root)])
    command.extend(forwarded)
    if not forwarded and (client != 'vibe' or args.prompt is None):
        command.append(f'Follow AGENTS.md and docs/{client}.md. Run the Bridge session-start flow, then show the next appropriate action.')

    def finish():
        checked = bridge('finish', '--session-id', token)
        if checked:
            print(f'Bridge completion check failed; checkpoint retained: {token}', file=sys.stderr)
        return checked

    return run_child(command, root, finish)


def entrypoint(client, root):
    try:
        return main(client, root)
    except (OSError, subprocess.CalledProcessError) as error:
        print(f'Open Bridge {client.title()}: {error}', file=sys.stderr)
        return 1
