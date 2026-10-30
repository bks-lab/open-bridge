#!/usr/bin/env python3
"""Which DESIGN.md a page wears, asked of the Bridge this skill ships in.

A Bridge can hold more than one design: the root DESIGN.md is the default, and
every further brand is a file under identity/designs/. The Bridge resolves
which one applies (scripts/designs.py): --design, a target repository with its
own DESIGN.md, the context's design_ref, the persona's, the active theme's
branding.design, then the root DESIGN.md. Every html-canvas script and
html-slides new-deck.py ask through this module, so they agree.

Outside a Bridge, or without PyYAML, the rule that always held stays: the
nearest DESIGN.md above the page (never above the project root), else the
DESIGN.md three levels above this folder.

Standard library only: verify-page.py imports it and needs no PyYAML.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

BRIDGE = Path(__file__).resolve().parents[3]
PROJECT_MARKERS = (".git", "bridge-config.yaml")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")


# The design a page was built with, recorded in its token region so a refresh and the
# standalone gate read it back instead of resolving afresh (new-deck records its preset
# the same way): an id under identity/designs/, or a path relative to the Bridge.
SOURCE_RE = re.compile(r"/\* design-source: ([^*\n]+?) \*/")


class DesignError(ValueError):
    """The Bridge could not resolve a design; the message names the id and its source."""


def is_path(value: str) -> bool:
    """`brand.md` or `sub/brand` names a file; only a bare word is a design id."""
    return value.endswith(".md") or "/" in value or "\\" in value


def source_mark(path: Path | None) -> str:
    """The marker a page carries for `path`: a design id, or a path inside the Bridge.

    A design outside the Bridge (a target repository's own DESIGN.md) is found
    again by walking up from the page, so it is not recorded.
    """
    if path is None:
        return ""
    path = Path(path).resolve()
    family = (BRIDGE / "identity" / "designs").resolve()
    if path.parent == family and ID_RE.match(path.stem) and path.suffix == ".md":
        label = path.stem
    else:
        try:
            label = path.relative_to(BRIDGE.resolve()).as_posix()
        except ValueError:
            return ""
    return "/* design-source: %s */\n" % label


def recorded(text: str) -> Path | None:
    """The design a page says it was built with, or None when it records none."""
    m = SOURCE_RE.search(text)
    if not m:
        return None
    label = m.group(1).strip()
    if ID_RE.match(label) and not is_path(label):
        return resolve(label)
    return BRIDGE / label


def find_design(start: Path) -> Path | None:
    """The nearest DESIGN.md at or above `start` (a folder, or a file's folder).

    The walk stops at the project root: the first folder holding .git or
    bridge-config.yaml. Without such a folder above, only `start` itself counts,
    so a stray DESIGN.md somewhere in a temp or home folder never brands a page
    or skews the gate.
    """
    start = Path(start).resolve()
    if not start.is_dir():
        start = start.parent
    chain = [start, *start.parents]
    root = next((d for d in chain if any((d / m).exists() for m in PROJECT_MARKERS)), None)
    for d in chain if root else [start]:
        if (d / "DESIGN.md").is_file():
            return d / "DESIGN.md"
        if d == root:
            break
    return None


def resolver():
    """scripts/designs.py of this Bridge, or None (outside a Bridge, or no PyYAML)."""
    path = BRIDGE / "scripts" / "designs.py"
    if not path.is_file():
        return None
    spec = importlib.util.spec_from_file_location("bridge_designs", path)
    if spec is None or spec.loader is None:
        return None
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except ImportError:
        return None
    return mod


def resolve(design: str | None = None, *, context: str | None = None, persona: str | None = None,
            target=None, fallback: bool = True) -> Path | None:
    """The DESIGN.md to read, or None.

    An explicit path wins as given; the caller reports one that does not exist,
    as it always did. A bare id (`--design example-org`) is looked up in
    identity/designs/. `fallback=False` is for the gates that only ever read a
    DESIGN.md found above the page: with nothing named, a page outside every
    project keeps no design, while a page inside the Bridge gets the Bridge's.
    A page that records its design (`recorded`) is read with that one instead.
    """
    if design and (Path(design).exists() or is_path(str(design)) or not ID_RE.match(str(design))):
        return Path(design)
    designs = resolver()
    if designs is None:
        if design:
            return Path(design)
        found = find_design(target) if target is not None else None
        if found or not fallback:
            return found
        root = BRIDGE / "DESIGN.md"
        return root if root.is_file() else None
    if not (fallback or design or context or persona):
        if target is None or find_design(target) is None:
            return None
    try:
        return designs.resolve(BRIDGE, design=design, context=context, persona=persona, target=target).path
    except designs.DesignError as err:
        raise DesignError(str(err)) from err
