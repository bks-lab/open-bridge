# SPDX-License-Identifier: MIT
"""Which folders a workspace may name under `sources.documents`, the one place that says so.

Such a folder goes to a model on behalf of a person, so this refuses by shape what must never go: the home folder and
all above it, the code under ~/Developer, cloud-synced business folders, hidden folders and system folders. It is a
floor, not a choice: which folders belong to a workspace is the owner's call. Used on the words when a definition is
validated, and on the resolved folder before anything is read, so a link cannot walk around it.

An entry without a leading / or ~/ is a pattern inside the Bridge: named files of one folder such as
`docs/family/*.yaml`, with a folder, a known kind of file and no `**`, so it can open a family of files without the rest
of the tree. What such a file holds is copied as it stands: a reference stays a reference, nothing is ever resolved.
"""
from __future__ import annotations

import os
from pathlib import Path

SYSTEM = ("/bin", "/boot", "/dev", "/etc", "/lib", "/opt", "/private", "/proc", "/root", "/sbin", "/sys", "/System",
          "/usr", "/var", "/Applications", "/Library")
SHALLOW = ("/Users", "/home", "/Volumes", "/mnt", "/media")
PATTERN_SUFFIXES = (".md", ".txt", ".yaml", ".yml", ".csv", ".pdf")


def pattern_problem(path: str) -> str | None:
    """What is wrong with an entry that names files inside the Bridge"""
    parts = path.split("/")
    if len(parts) < 2 or not parts[-1]:
        return "must name files in a folder, like folder/*.yaml"
    if "**" in path or any(p in ("", ".", "..") or p.startswith(".") for p in parts):
        return "must stay in one folder, without ** or hidden folders"
    if any(c in p for p in parts[:-1] for c in "*?["):
        return "takes a pattern in the file name only"
    if not parts[-1].lower().endswith(PATTERN_SUFFIXES):
        return f"must end in one of {', '.join(PATTERN_SUFFIXES)}"
    return None


def problem(path: object, home: str | None = None) -> str | None:
    """What is wrong with a folder, None when it may be named"""
    if not isinstance(path, str) or not path.strip():
        return "must be a folder"
    if not path.startswith(("/", "~/")) and path != "~":
        return pattern_problem(path)
    if ".." in path.split("/"):
        return "must not climb with .."
    own = Path(home or os.path.expanduser("~"))
    full = Path(os.path.normpath(os.path.expanduser(path) if home is None else path.replace("~", str(own), 1)))
    if full == Path("/") or full == own or full in own.parents:
        return "must not be the home folder or above it"
    if any(part.startswith(".") for part in full.parts):
        return "must not be a hidden folder"
    if own in full.parents:
        first = full.relative_to(own).parts[0]
        if first in ("Developer", "Library"):
            return f"must not lie under ~/{first}"
    if "CloudStorage" in full.parts:
        return "must not be a cloud-synced folder"
    text = str(full)
    if any(text == s or text.startswith(s + "/") for s in SYSTEM):
        return "must not be a system folder"
    for shallow in SHALLOW:
        if text == shallow or (text.startswith(shallow + "/") and len(Path(text).relative_to(shallow).parts) < 2):
            return "must be a folder on a disk, not the disk"
    return None
