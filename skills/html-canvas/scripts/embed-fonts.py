#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Font families -> a base64 @font-face block, so a page needs no font files.

Embedding is optional. A page without it degrades to the platform stack that
design-to-css.py already emits; a page that is sent or bundled turns it on, so
the brand typeface survives being opened alone from a mail attachment or a
download folder, offline and with no third-party request (DESIGN.md forbids
font CDNs).

The family list comes from one of two sources:
  * a DESIGN.md      every typography.<role> with a fontFamily, plus its
                     fontWeight (a stack such as "Inter, system-ui" yields its
                     first family; generic names are ignored)
  * a preset YAML    a `fonts:` mapping, entries flat (`body: Inter`) or nested
                     (`body: {family: Inter, weights: [400, 700]}`); a
                     `fonts.weights` list is the fallback for entries without
                     their own, and `fonts.system_only: true` embeds nothing

Font files are found by name in the bundled assets/fonts/ and in every
--font-dir (searched first, so a fork can override or add families):
  <family-slug>-latin-<weight>.woff2   one static weight, e.g. inter-latin-400.woff2
  <family-slug>-latin-wght.woff2       a variable font covering 100-900
A requested weight is served by the exact static file, else by a variable file;
a weight nothing can serve is reported on stderr and skipped, as is a family
with no file at all. stdout stays pure CSS either way.

Usage:
  embed-fonts.py [DESIGN.md | preset.yaml] [--font-dir DIR ...] [--style]
                 [--out file] [--strict]
  # default input: the repo-root DESIGN.md. --style wraps the CSS in <style>.
  # --strict exits non-zero when anything was skipped.

From Python:
  build_font_face_css({"Inter": [400, 600]}, [Path("my-fonts")]) -> str
"""
from __future__ import annotations

import argparse
import base64
import importlib.util
import re
import sys
from pathlib import Path
from typing import Iterable, Mapping, Sequence

try:
    import yaml
except ImportError:
    sys.exit("embed-fonts: PyYAML required (pip install pyyaml)")

SKILL = Path(__file__).resolve().parents[1]
BUNDLED_DIR = SKILL / "assets" / "fonts"

# The glyphs the bundled latin subsets actually carry: Basic Latin, Latin-1
# (umlauts, sharp s), general punctuation, the euro sign and a few symbols.
# Declared so the browser falls back to the system stack for anything else.
LATIN_RANGE = ("U+0000-00FF, U+0131, U+0152-0153, U+02BB-02BC, U+02C6, U+02DA, U+02DC, "
               "U+0304, U+0308, U+0329, U+2000-206F, U+20AC, U+2122, U+2191, U+2193, "
               "U+2212, U+2215, U+FEFF, U+FFFD")
VARIABLE_RANGE = (100, 900)
GENERIC = {"serif", "sans-serif", "monospace", "cursive", "fantasy", "system-ui", "ui-monospace",
           "ui-sans-serif", "ui-serif", "ui-rounded", "emoji", "math", "fangsong"}
FILE_RE = re.compile(r"^(?P<slug>[a-z0-9][a-z0-9-]*?)-latin-(?P<w>wght|\d{3})(?:-normal)?\.woff2$")


def slugify(family: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", family.strip().lower()).strip("-")


def _design_to_css():
    """Reuse design-to-css.py's frontmatter parser (hyphenated name, so importlib)."""
    path = Path(__file__).resolve().parent / "design-to-css.py"
    spec = importlib.util.spec_from_file_location("design_to_css", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _weight(value) -> int | None:
    try:
        w = int(str(value).strip())
    except ValueError:
        return None
    return w if 1 <= w <= 1000 else None


def _first_family(value) -> str | None:
    for part in str(value or "").split(","):
        name = part.strip().strip('"').strip("'").strip()
        if name and name.lower() not in GENERIC and not name.startswith("-"):
            return name
    return None


def _add(found: dict[str, set[int]], family: str | None, weights: Iterable) -> None:
    if not family:
        return
    ws = {w for w in (_weight(x) for x in weights) if w}
    found.setdefault(family, set()).update(ws)


def collect_families(path: Path) -> dict[str, list[int]]:
    """Read {family: sorted weights} from a DESIGN.md or a preset YAML."""
    path = Path(path)
    if path.suffix.lower() == ".md":
        data = _design_to_css().frontmatter(path)
    else:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        sys.exit(f"embed-fonts: {path} is not a mapping")
    found: dict[str, set[int]] = {}

    typography = data.get("typography")
    if isinstance(typography, dict):
        for spec in typography.values():
            if isinstance(spec, dict):
                _add(found, _first_family(spec.get("fontFamily")), [spec.get("fontWeight", 400)])

    fonts = data.get("fonts")
    if isinstance(fonts, dict) and not fonts.get("system_only"):
        fallback = fonts.get("weights")
        fallback = fallback if isinstance(fallback, list) and fallback else [400]
        for role, entry in fonts.items():
            if role in ("weights", "system_only"):
                continue
            if isinstance(entry, str):
                _add(found, _first_family(entry), fallback)
            elif isinstance(entry, dict) and not entry.get("system_only"):
                own = entry.get("weights")
                _add(found, _first_family(entry.get("family")),
                     own if isinstance(own, list) and own else fallback)
    return {fam: sorted(ws) for fam, ws in found.items()}


def _index(directory: Path) -> dict[str, dict]:
    """{slug: {"static": {weight: file}, "variable": file | None}} for one directory."""
    out: dict[str, dict] = {}
    if not directory.is_dir():
        return out
    for f in sorted(directory.glob("*.woff2")):
        m = FILE_RE.match(f.name)
        if not m:
            continue
        entry = out.setdefault(m["slug"], {"static": {}, "variable": None})
        if m["w"] == "wght":
            entry["variable"] = f
        else:
            entry["static"][int(m["w"])] = f
    return out


def _face(family: str, weight: str, data: bytes) -> str:
    b64 = base64.b64encode(data).decode("ascii")
    return (f'@font-face {{ font-family: "{family}"; font-style: normal; font-weight: {weight}; '
            f'font-display: swap; src: url(data:font/woff2;base64,{b64}) format("woff2"); '
            f'unicode-range: {LATIN_RANGE}; }}')


def _build(families: Mapping[str, Iterable[int]], font_dirs: Sequence[Path]) -> tuple[str, list[str]]:
    indexes = [_index(Path(d)) for d in list(font_dirs)] + [_index(BUNDLED_DIR)]
    rules: list[str] = []
    warnings: list[str] = []
    for family, weights in families.items():
        slug = slugify(family)
        if not any(slug in ix for ix in indexes):
            warnings.append(f'no font files for family "{family}" (falls back to the system stack)')
            continue
        done: set[Path] = set()
        for w in sorted(set(int(x) for x in weights)):
            hit = None  # (file, css weight)
            for ix in indexes:
                entry = ix.get(slug)
                if not entry:
                    continue
                if w in entry["static"]:
                    hit = (entry["static"][w], str(w))
                elif entry["variable"]:
                    hit = (entry["variable"], "%d %d" % VARIABLE_RANGE)
                if hit:
                    break
            if not hit:
                warnings.append(f'"{family}" has no file for weight {w} (not embedded)')
                continue
            if hit[0] in done:
                continue
            done.add(hit[0])
            rules.append(_face(family, hit[1], hit[0].read_bytes()))
    return "\n".join(rules) + ("\n" if rules else ""), warnings


def build_font_face_css(families: Mapping[str, Iterable[int]], font_dirs: Sequence[Path] = ()) -> str:
    """Return base64 @font-face rules for {family: weights}; skips are printed on stderr."""
    css, warnings = _build(families, font_dirs)
    for w in warnings:
        print(f"embed-fonts: WARN {w}", file=sys.stderr)
    return css


def main() -> int:
    ap = argparse.ArgumentParser(description="Font families -> base64 @font-face block")
    ap.add_argument("source", nargs="?", default=str(SKILL.parents[1] / "DESIGN.md"),
                    help="DESIGN.md or preset YAML (default: repo-root DESIGN.md)")
    ap.add_argument("--font-dir", action="append", default=[], metavar="DIR",
                    help="extra directory of <family>-latin-<weight>.woff2 files, searched first")
    ap.add_argument("--style", action="store_true", help="wrap the CSS in a <style> element")
    ap.add_argument("--out", help="write to this file instead of stdout")
    ap.add_argument("--strict", action="store_true", help="exit non-zero when anything was skipped")
    args = ap.parse_args()

    families = collect_families(Path(args.source))
    css, warnings = _build(families, [Path(d) for d in args.font_dir])
    for w in warnings:
        print(f"embed-fonts: WARN {w}", file=sys.stderr)
    if args.style and css:
        css = "<style>\n" + css + "</style>\n"
    if args.out:
        Path(args.out).write_text(css, encoding="utf-8")
        print(f"embed-fonts: wrote {args.out} ({len(css)} bytes)", file=sys.stderr)
    else:
        sys.stdout.write(css)
    return 1 if (args.strict and warnings) else 0


if __name__ == "__main__":
    sys.exit(main())
