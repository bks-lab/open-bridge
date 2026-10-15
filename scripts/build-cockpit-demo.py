#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Build the cockpit demo on the website: docs/cockpit-demo/ from scripts/web.

The cockpit's page lives in scripts/web and is served by the cockpit server. The website
is GitHub Pages, which serves only docs/ and follows no symlink out of it, so the demo
needs a real copy under docs/. A copy drifts the day the source changes, which is why
this script writes it and CI checks it.

What it writes into docs/cockpit-demo/:
- every file of scripts/web, byte for byte, except vendor/README.md (provenance notes
  for the source tree, not part of the page);
- colors.css, generated from DESIGN.md by bridge_cockpit.design.stylesheet, the same
  text the server sends at /colors.css (never hand-picked colours). The demo shows
  open-bridge, so this is open-bridge's DESIGN.md: in a configured instance (it has a
  bridge-config.yaml and often a DESIGN.md of its own) colors.css is neither checked
  nor rewritten, or every instance would be red and --write would carry its colours
  into a file that ships upstream;
- index.html, the source page with three changes: a tiny inline script as the first
  thing in <head> that adds mock=1 to the address when it is missing (app.js reads it
  when the module loads, so the bare address cockpit-demo/ opens the demo with invented
  data and makes no request), a robots noindex, the site's icon (the cockpit page has
  none, and a missing one is a 404 in the console), and the title "Bridge Cockpit demo".

    python3 scripts/build-cockpit-demo.py --write    # rewrite the copy, remove stale files
    python3 scripts/build-cockpit-demo.py --check    # exit 1 and name what drifted

After changing anything in scripts/web, run --write and commit the result.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.dont_write_bytecode = True
if str(REPO / "scripts" / "lib") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts" / "lib"))

from bridge_cockpit.design import stylesheet  # noqa: E402

SOURCE = Path("scripts") / "web"
OUT = Path("docs") / "cockpit-demo"
SKIP = {"vendor/README.md"}
FIX = "python3 scripts/build-cockpit-demo.py --write"

# Classic script, first in <head>: before app.js (a module, so deferred) reads the address.
BOOT = (
    "<script>(function () { var u = new URL(window.location.href); "
    "if (u.searchParams.get('mock') !== '1') { u.searchParams.set('mock', '1'); "
    "window.history.replaceState(null, '', u.toString()) } })()</script>"
)


def demo_index(source: str) -> str:
    """The source index.html turned into the demo's page."""
    head = "<head>\n"
    if source.count(head) != 1 or source.count("<title>Bridge Cockpit</title>") != 1:
        raise SystemExit("build-cockpit-demo: scripts/web/index.html no longer has the expected <head> or <title>")
    page = source.replace(head, head + BOOT + "\n", 1)
    page = page.replace("<title>Bridge Cockpit</title>",
                        '<meta name="robots" content="noindex">\n<link rel="icon" href="../assets/favicon.svg" type="image/svg+xml">\n'
                        '<title>Bridge Cockpit demo</title>', 1)
    return page


def is_instance(root: Path) -> bool:
    """A configured Bridge (it carries its own bridge-config.yaml), not open-bridge itself."""
    return (Path(root) / "bridge-config.yaml").is_file()


def expected(root: Path) -> dict[str, bytes]:
    """Every file the demo folder must hold, by path relative to it."""
    root = Path(root)
    src = root / SOURCE
    files: dict[str, bytes] = {}
    for path in sorted(src.rglob("*")):
        if not path.is_file():
            continue
        rel = path.relative_to(src).as_posix()
        if rel in SKIP or path.name == ".DS_Store":
            continue
        files[rel] = path.read_bytes()
    files["index.html"] = demo_index(files["index.html"].decode("utf-8")).encode("utf-8")
    if not is_instance(root):
        files["colors.css"] = stylesheet(root).encode("utf-8")
    return files


def _present(out: Path) -> set[str]:
    if not out.is_dir():
        return set()
    return {p.relative_to(out).as_posix() for p in out.rglob("*") if p.is_file()}


def drift(root: Path) -> list[tuple[str, str]]:
    """What differs between the demo folder and what it should hold: (path, changed|missing|stale)."""
    out = Path(root) / OUT
    want = expected(root)
    have = _present(out)
    found: list[tuple[str, str]] = []
    for rel, data in want.items():
        if rel not in have:
            found.append((rel, "missing"))
        elif (out / rel).read_bytes() != data:
            found.append((rel, "changed"))
    kept = {"colors.css"} if is_instance(root) else set()
    found.extend((rel, "stale") for rel in sorted(have - set(want) - kept))
    return found


def write(root: Path) -> list[tuple[str, str]]:
    """Bring the demo folder in line; returns what it changed."""
    out = Path(root) / OUT
    changes = drift(root)
    want = expected(root)
    for rel, why in changes:
        target = out / rel
        if why == "stale":
            target.unlink()
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(want[rel])
    for folder in sorted((p for p in out.rglob("*") if p.is_dir()), key=lambda p: len(p.parts), reverse=True):
        if not any(folder.iterdir()):
            folder.rmdir()
    return changes


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build or check the cockpit demo in docs/cockpit-demo/.")
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--write", action="store_true", help="rewrite the copy and remove stale files")
    mode.add_argument("--check", action="store_true", help="exit 1 when the copy has drifted")
    parser.add_argument("--root", type=Path, default=REPO, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.write:
        changes = write(args.root)
        for rel, why in changes:
            print(f"  {why:8} {OUT.as_posix()}/{rel}")
        print(f"build-cockpit-demo: {len(changes)} file(s) updated" if changes else "build-cockpit-demo: up to date")
        return 0

    changes = drift(args.root)
    if not changes:
        print("build-cockpit-demo: docs/cockpit-demo/ matches scripts/web and DESIGN.md")
        return 0
    print(f"build-cockpit-demo: docs/cockpit-demo/ has drifted from scripts/web ({len(changes)} file(s)):", file=sys.stderr)
    for rel, why in changes:
        print(f"  {why:8} {OUT.as_posix()}/{rel}", file=sys.stderr)
    print(f"Fix: {FIX}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
