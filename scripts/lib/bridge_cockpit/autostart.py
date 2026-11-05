# SPDX-License-Identifier: MIT
"""The cockpit's login item on macOS: its label and where its LaunchAgent lies, from one place.

`bridge-cockpit.py autostart on|off|status` writes and removes it; the Setup page (scripts/bridge-setup.py)
reads only whether the file is there, so the row says what this computer has, not what a config claims.
One item per Bridge: the label carries a short hash of the Bridge's path.
"""
from __future__ import annotations

import hashlib
from pathlib import Path

LAUNCH_AGENTS = Path.home() / "Library" / "LaunchAgents"
PREFIX = "ai.open-bridge.cockpit."


def label(root: Path | str) -> str:
    return PREFIX + hashlib.sha256(str(Path(root)).encode("utf-8")).hexdigest()[:10]


def plist_path(root: Path | str) -> Path:
    return LAUNCH_AGENTS / f"{label(root)}.plist"


def installed(root: Path | str) -> bool:
    """The LaunchAgent file of this Bridge exists. `autostart status` also asks launchctl; this is the cheap
    read the Setup page makes, without a subprocess."""
    return plist_path(root).is_file()
