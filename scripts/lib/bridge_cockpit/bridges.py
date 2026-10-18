# SPDX-License-Identifier: MIT
"""The other Bridges on this machine, for the cockpit's chat: the siblings in infra/instances/ that
have a clone here.

Shown is an instance whose relationship is sibling or downstream, that is not read-only from here
(access.mode), not dormant or archived (status), and whose clone exists on this machine:
location.path, else location.mac_clone or location.local_clone (a second clone beside the one the
instance usually runs from). Knowing an instance is not reaching into it
(rules/multi-instance-isolation.md): this reads the registry files of THIS Bridge and checks that a
folder exists, nothing inside the other Bridge. Read again at most every CACHE_S seconds.
"""
from __future__ import annotations

import os
import threading
import time
from pathlib import Path

INSTANCES = Path("infra") / "instances"
CACHE_S = 60
RELATIONS = ("sibling", "downstream")
QUIET = ("dormant", "archived")
CLONE_KEYS = ("path", "mac_clone", "local_clone")


def _text(v, cap: int) -> str | None:
    return v.strip()[:cap] if isinstance(v, str) and v.strip() else None


def read_bridges(root: Path) -> list[dict]:
    import yaml
    out = []
    folder = Path(root) / INSTANCES
    for path in sorted(folder.glob("*.yaml")) if folder.is_dir() else []:
        if path.name.startswith("_"):
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(data, dict) or data.get("relationship") not in RELATIONS or data.get("status") in QUIET:
            continue
        access = data.get("access") if isinstance(data.get("access"), dict) else {}
        if access.get("mode") == "read-only-from-here":
            continue
        loc = data.get("location") if isinstance(data.get("location"), dict) else {}
        clone = None
        for key in CLONE_KEYS:
            value = _text(loc.get(key), 500)
            if value and os.path.isdir(os.path.expanduser(value)):
                clone = str(Path(os.path.expanduser(value)).resolve())
                break
        if clone is None or clone == str(Path(root).resolve()):
            continue
        out.append({"id": path.stem, "name": _text(data.get("name"), 80) or path.stem,
                    "purpose": _text(data.get("purpose"), 300), "path": clone,
                    "branch": _text(loc.get("working_branch"), 120)})
    return out


class Bridges:
    def __init__(self, root: Path):
        self.root = Path(root)
        self.lock = threading.Lock()
        self.cached: tuple[float, list[dict]] | None = None

    def state(self) -> list[dict]:
        now = time.monotonic()
        with self.lock:
            if self.cached and now - self.cached[0] < CACHE_S:
                return [dict(b) for b in self.cached[1]]
        rows = read_bridges(self.root)
        with self.lock:
            self.cached = (now, rows)
        return [dict(b) for b in rows]
