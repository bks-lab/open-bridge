#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Codex entry point for the shared Bridge CLI session checks."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from lib.cli_bridge import (digest, doctor, entrypoint, git, main, needs_log,
                            run, snapshot, valid_log, work_enabled)

if __name__ == '__main__':
    entrypoint('codex')
