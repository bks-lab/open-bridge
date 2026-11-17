# SPDX-License-Identifier: MIT
"""The Python code this cockpit server runs, against what lies on disk now.

An update of the Bridge (a merge of the upstream, the daily auto update) changes the files under scripts/, but a
running server keeps the code it imported at its start. The page then loads the new page code at once (server.py
web_stamp) while the server answers with the old one, and a new switch or verb is missing until somebody restarts
it. CodeStamp keeps the size and mtime of every module the server loaded from its own code folder, as they were at
the start; changed() says when one of them differs, and the page offers Restart (features.py, restart.code).
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Iterable, Mapping


def _stat(path: Path) -> tuple[int, int] | None:
    try:
        st = path.stat()
    except OSError:
        return None
    return st.st_mtime_ns, st.st_size


def loaded_files(base: Path | str, modules: Mapping[str, Any] | None = None) -> list[Path]:
    """The files of the modules loaded from under `base` (sys.modules by default), the entry script among them;
    sorted, each once"""
    root = Path(base).resolve()
    found: set[Path] = set()
    for module in list((sys.modules if modules is None else modules).values()):
        name = getattr(module, "__file__", None)
        if not name:
            continue
        try:
            path = Path(name).resolve()
        except (OSError, RuntimeError, TypeError, ValueError):
            continue
        if path.suffix == ".py" and path.is_relative_to(root):
            found.add(path)
    return sorted(found)


class CodeStamp:
    """What the code looked like when this server started; `files` for a test, else the loaded modules"""

    def __init__(self, base: Path | str, files: Iterable[Path] | None = None):
        paths = [Path(f).resolve() for f in files] if files is not None else loaded_files(base)
        self.start = {p: _stat(p) for p in paths}

    def changed(self) -> bool:
        """A file this server runs is different on disk now, or gone"""
        return any(_stat(p) != was for p, was in self.start.items())
