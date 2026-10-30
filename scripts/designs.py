#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Which design a piece of work wears, and which designs this Bridge holds.

    python3 scripts/designs.py list                          # every design, its scope, who points at it
    python3 scripts/designs.py resolve [--context C] [--persona P] [--design ID|PATH] [--target PATH]
    python3 scripts/designs.py check RENDER [--design ID|PATH] [--context C] [--persona P]

A Bridge holds a default design, the root `DESIGN.md`, and any number of
further ones, one brand per file under `identity/designs/<id>.md`, in the same
format and each with its own `scope:`. An organisation's brand declares
`scope: org` and reaches every member Bridge through the org overlay, so
nobody edits the root file for it.

The side that USES a design names it, after the `persona_ref` pattern:
`design_ref:` in a context or a persona, `branding.design:` in a theme. The
reverse direction ("what is this design for") is derived by `list`, never
kept by hand, because a hand-kept table goes stale.

RESOLUTION, the first step that answers wins:

    1  --design <id|path>                    a one-off page in another brand
    2  a target repo with its own DESIGN.md   a deck written into a website repo
    3  workflow/contexts/<ctx>.yaml           design_ref
    4  identity/personas/<id>.yaml            design_ref
    5  the active themes/<name>.yaml          branding.design
    6  the root DESIGN.md                     a Bridge with no further design

Step 2 walks up from the target and stops at the first folder holding `.git`
or `bridge-config.yaml` (the rule html-canvas has always used). It never
counts a Bridge's root, this one or another checkout of it (a worktree, a
second instance): a page written inside a Bridge would find that root
DESIGN.md, and no context or theme could ever brand it.

AN UNKNOWN ID IS AN ERROR naming the id and the file that points at it. A
quiet fall back to the root would render a page in the wrong brand that looks
entirely plausible, which is the failure nobody reports.

`check` holds a render to its design: every hex colour in the render must be
declared in the design's front matter. The prose of a design names retired
values on purpose, so it never declares anything.

Contract: scripts/tests/test_designs.py.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import NamedTuple

import yaml

ROOT = Path(__file__).resolve().parents[1]
FAMILY = Path("identity") / "designs"
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
PROJECT_MARKERS = (".git", "bridge-config.yaml")
USE_FOR = ("mail", "pdf", "html", "slides", "dashboard", "certificate", "video", "site", "cockpit")

STEPS = {
    1: "--design",
    2: "target repository",
    3: "context design_ref",
    4: "persona design_ref",
    5: "theme branding.design",
    6: "root DESIGN.md",
}


class DesignError(ValueError):
    """A design that cannot be resolved; the message names the id and where it came from."""


class Resolved(NamedTuple):
    id: str | None        # the design's id when it lives in identity/designs/, else None
    path: Path | None     # the file to read; None only when even the root DESIGN.md is missing
    step: int             # which step answered, 1..6 (STEPS)


# --- reading ---------------------------------------------------------------------------------

def front_matter(path: Path) -> dict:
    """The YAML between the first two `---` lines; empty when there is none or it does not parse."""
    try:
        text = Path(path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return {}
    m = re.match(r"\A---\s*\n(.*?)\n---\s*(\n|\Z)", text, re.S)
    if not m:
        return {}
    try:
        data = yaml.safe_load(m.group(1))
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def _yaml(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return str(path)


def design_path(root: Path, design_id: str) -> Path:
    return Path(root) / FAMILY / f"{design_id}.md"


def _by_id(root: Path, value, origin: str) -> Resolved | None:
    """The design a reference names, or DesignError naming `origin` (the file or flag it came from)."""
    if value is None:
        return None
    text = str(value).strip()
    if not ID_RE.match(text):
        raise DesignError(f"{origin}: design '{text}' is not a design id "
                          f"(a file name under {FAMILY.as_posix()}/ without .md)")
    path = design_path(root, text)
    if not path.is_file():
        raise DesignError(f"{origin}: design '{text}' is unknown, "
                          f"there is no {_rel(root, path)}")
    return Resolved(text, path, 0)


# --- the steps -------------------------------------------------------------------------------

def is_path(value: str) -> bool:
    """`brand.md` or `sub/brand` names a file; only a bare word is a design id."""
    return value.endswith(".md") or "/" in value or "\\" in value


def _explicit(root: Path, design: str) -> Resolved:
    path = Path(design).expanduser()
    if path.is_file():
        path = path.resolve()
        family = (Path(root) / FAMILY).resolve()
        design_id = path.stem if path.parent == family and not path.name.startswith("_") else None
        return Resolved(design_id, path, 1)
    if is_path(design) or not ID_RE.match(design):
        raise DesignError(f"--design {design}: no such file")
    found = _by_id(root, design, "--design")
    assert found is not None
    return Resolved(found.id, found.path, 1)


def _walk_up(start: Path) -> Path | None:
    """The nearest DESIGN.md at or above `start`, never above the project root.

    Same rule as skills/html-canvas/scripts/design-to-css.py find_design: the
    walk stops at the first folder holding .git or bridge-config.yaml, and
    without such a folder only `start` itself counts.
    """
    start = Path(start).resolve()
    if not start.is_dir():
        start = start.parent
    chain = [start, *start.parents]
    top = next((d for d in chain if any((d / m).exists() for m in PROJECT_MARKERS)), None)
    for d in chain if top else [start]:
        if (d / "DESIGN.md").is_file():
            return d / "DESIGN.md"
        if d == top:
            break
    return None


def is_bridge(folder: Path) -> bool:
    """A Bridge checkout: an instance (bridge-config.yaml) or a tree that ships this resolver."""
    return (folder / "bridge-config.yaml").is_file() or (folder / "scripts" / "designs.py").is_file()


def _target(root: Path, target) -> Resolved | None:
    found = _walk_up(Path(target))
    if found is None or found.resolve() == (Path(root) / "DESIGN.md").resolve() or is_bridge(found.parent):
        return None
    return Resolved(None, found, 2)


def _ref_in(root: Path, folder: str, name: str, kind: str) -> Resolved | None:
    if not ID_RE.match(str(name)):
        raise DesignError(f"{kind} '{name}' is not a valid name")
    path = Path(root) / folder / f"{name}.yaml"
    if not path.is_file():
        raise DesignError(f"{kind} '{name}': {_rel(root, path)} does not exist")
    return _by_id(root, _yaml(path).get("design_ref"), _rel(root, path))


def active_theme(root: Path) -> Path | None:
    """themes/<name>.yaml for bridge-config.yaml `theme:` (rules/theme.md), else professional."""
    name = str(_yaml(Path(root) / "bridge-config.yaml").get("theme") or "professional")
    path = Path(root) / "themes" / f"{name}.yaml"
    if ID_RE.match(name) and path.is_file():
        return path
    fallback = Path(root) / "themes" / "professional.yaml"
    return fallback if fallback.is_file() else None


def theme_design(root: Path, theme: Path | None) -> tuple[str | None, Path | None]:
    """`branding.design` of a theme, inherited through `meta.extends`: (value, the file declaring it).

    The nearest theme that names the key decides, and an explicit `design: null`
    is a child opting out of its parent's design.
    """
    seen = set()
    while theme is not None and theme not in seen:
        seen.add(theme)
        data = _yaml(theme)
        branding = data.get("branding")
        if isinstance(branding, dict) and "design" in branding:
            value = branding["design"]
            return (value, theme) if value is not None else (None, None)
        parent = (data.get("meta") or {}).get("extends") if isinstance(data.get("meta"), dict) else None
        if not parent or not ID_RE.match(str(parent)):
            break
        theme = Path(root) / "themes" / f"{parent}.yaml"
        if not theme.is_file():
            break
    return None, None


def resolve(root: Path = ROOT, *, design: str | None = None, context: str | None = None,
            persona: str | None = None, target=None) -> Resolved:
    """The design that applies, by the six steps in the module docstring."""
    root = Path(root)
    if design:
        return _explicit(root, str(design))
    if target is not None:
        found = _target(root, target)
        if found:
            return found
    if context:
        found = _ref_in(root, "workflow/contexts", context, "context")
        if found:
            return found._replace(step=3)
    if persona:
        found = _ref_in(root, "identity/personas", persona, "persona")
        if found:
            return found._replace(step=4)
    value, theme = theme_design(root, active_theme(root))
    if value is not None and theme is not None:
        found = _by_id(root, value, f"{_rel(root, theme)} branding.design")
        assert found is not None
        return found._replace(step=5)
    default = root / "DESIGN.md"
    return Resolved(None, default if default.is_file() else None, 6)


# --- list: every design, and who points at it --------------------------------------------------

def references(root: Path) -> list[tuple[str, str, str]]:
    """Every pointer at a design: (id, who, file). Templates point at nothing."""
    root = Path(root)
    out = []
    for folder, kind in (("workflow/contexts", "context"), ("identity/personas", "persona")):
        for path in sorted((root / folder).glob("*.yaml")):
            if path.name.startswith("_"):
                continue
            value = _yaml(path).get("design_ref")
            if value is not None:
                out.append((str(value), f"{kind} {path.stem}", _rel(root, path)))
    active = active_theme(root)
    for path in sorted((root / "themes").glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        branding = _yaml(path).get("branding")
        if isinstance(branding, dict) and branding.get("design") is not None:
            who = f"theme {path.stem}" + (" (active)" if path == active else "")
            out.append((str(branding["design"]), who, _rel(root, path)))
    return out


def _source(value) -> str:
    if not isinstance(value, dict):
        return ""
    where = str(value.get("repo") or value.get("manifest") or "")
    at = value.get("taken_at")
    return f"{where}@{at}" if where and at is not None and str(at) else where


def catalogue(root: Path = ROOT) -> list[dict]:
    """One row per design, the root DESIGN.md first (id None)."""
    root = Path(root)
    refs = references(root)
    rows = []
    default = root / "DESIGN.md"
    if default.is_file():
        fm = front_matter(default)
        rows.append({"id": None, "path": "DESIGN.md", "name": str(fm.get("name") or ""),
                     "scope": "default", "use_for": [], "source": _source(fm.get("source")),
                     "referenced_by": []})
    for path in sorted((root / FAMILY).glob("*.md")):
        if path.name.startswith("_"):
            continue
        fm = front_matter(path)
        scope = fm.get("scope")
        use_for = fm.get("use_for")
        rows.append({
            "id": path.stem,
            "path": _rel(root, path),
            "name": str(fm.get("name") or ""),
            "scope": str(scope) if scope else "user (undeclared)",
            "use_for": [str(u) for u in use_for] if isinstance(use_for, list) else [],
            "source": _source(fm.get("source")),
            "referenced_by": [who for ref, who, _ in refs if ref == path.stem],
        })
    return rows


def dangling(root: Path = ROOT) -> list[str]:
    """References to an id with no file, as `file: id` lines."""
    return [f"{where} names '{ref}', which is no design"
            for ref, _, where in references(root)
            if not ID_RE.match(ref) or not design_path(root, ref).is_file()]


# --- check: a render against the design it was made from ---------------------------------------

HEX_RE = re.compile(r"(?<![&\w])#([0-9a-fA-F]{8}|[0-9a-fA-F]{6}|[0-9a-fA-F]{3,4})(?![0-9A-Za-z_-])")
# a fragment link names an anchor, not a colour: href="#bad"
ANCHOR_RE = re.compile(r"""href\s*=\s*["']?\Z""", re.I)


def norm_hex(digits: str) -> str:
    d = digits.lower()
    if len(d) in (3, 4):
        d = "".join(c * 2 for c in d[:3])
    return "#" + d[:6]


def _strings(node):
    if isinstance(node, dict):
        for value in node.values():
            yield from _strings(value)
    elif isinstance(node, list):
        for value in node:
            yield from _strings(value)
    elif isinstance(node, str):
        yield node


def declared(design: Path) -> set[str]:
    """Hex values in the front matter's VALUES only.

    The prose names retired values on purpose, and so does a YAML comment
    (`primary: "#123456"   # was #abcdef`); neither declares a colour.
    """
    return {norm_hex(h.group(1)) for text in _strings(front_matter(design)) for h in HEX_RE.finditer(text)}


# A CSS rule's prelude: the selector before `{`. "#cafe" there names an element, not a colour.
# It stops at `<`, quotes and `=`, so an HTML attribute or a script assignment is never one.
SELECTOR_RE = re.compile(r"[^{};<\"'=]*\{")


def undeclared(render: str, design: Path) -> dict[str, int]:
    """{#rrggbb: uses} for every colour in `render` the design does not declare."""
    known = declared(design)
    render = SELECTOR_RE.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), render)
    hits: dict[str, int] = {}
    for m in HEX_RE.finditer(render):
        if ANCHOR_RE.search(render[max(0, m.start() - 12):m.start()]):
            continue
        h = norm_hex(m.group(1))
        if h not in known:
            hits[h] = hits.get(h, 0) + 1
    return hits


# --- CLI ---------------------------------------------------------------------------------------

def _add_choice(p: argparse.ArgumentParser) -> None:
    p.add_argument("--design", help="a design id under identity/designs/, or a path (step 1)")
    p.add_argument("--context", help="workflow/contexts/<name>.yaml whose design_ref applies (step 3)")
    p.add_argument("--persona", help="identity/personas/<id>.yaml whose design_ref applies (step 4)")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0],
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--root", default=str(ROOT), help=argparse.SUPPRESS)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_list = sub.add_parser("list", help="every design, its scope, what it is for, who points at it")
    p_list.add_argument("--json", action="store_true")
    p_res = sub.add_parser("resolve", help="the design file that applies")
    _add_choice(p_res)
    p_res.add_argument("--target", help="where the output is written (step 2: a repo with its own DESIGN.md)")
    p_res.add_argument("--json", action="store_true")
    p_chk = sub.add_parser("check", help="every hex colour in RENDER is declared by its design")
    p_chk.add_argument("render", help="the rendered file (HTML, CSS, a template)")
    _add_choice(p_chk)
    args = ap.parse_args(argv)
    root = Path(args.root)

    if args.cmd == "list":
        rows = catalogue(root)
        if args.json:
            print(json.dumps({"designs": rows, "dangling": dangling(root)}, indent=2))
            return 0
        print("| design | file | scope | use for | source | referenced by |")
        print("|---|---|---|---|---|---|")
        for r in rows:
            print("| %s | %s | %s | %s | %s | %s |" % (
                r["id"] or "(default)", r["path"], r["scope"], ", ".join(r["use_for"]) or "-",
                r["source"] or "-", ", ".join(r["referenced_by"]) or "-"))
        for line in dangling(root):
            print(f"warning: {line}", file=sys.stderr)
        return 0

    try:
        res = resolve(root, design=args.design, context=args.context, persona=args.persona,
                      target=getattr(args, "target", None))
    except DesignError as err:
        print(f"designs: {err}", file=sys.stderr)
        return 2

    if args.cmd == "resolve":
        if args.json:
            print(json.dumps({"id": res.id, "path": str(res.path) if res.path else None,
                              "step": res.step, "via": STEPS[res.step]}))
        elif res.path is None:
            print(f"designs: no design applies and there is no DESIGN.md in {root}", file=sys.stderr)
            return 2
        else:
            print(f"{_rel(root, res.path)}  (step {res.step}, {STEPS[res.step]})")
        return 0

    render = Path(args.render)
    if not render.is_file():
        print(f"designs: no such render: {render}", file=sys.stderr)
        return 2
    if res.path is None:
        print("designs: no design to check against", file=sys.stderr)
        return 2
    hits = undeclared(render.read_text(encoding="utf-8", errors="replace"), res.path)
    where = _rel(root, res.path)
    if not hits:
        print(f"{render}: every colour is declared in {where}")
        return 0
    for value, uses in sorted(hits.items()):
        print(f"{render}: {value} is not declared in {where} ({uses} use{'s' if uses != 1 else ''})")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
