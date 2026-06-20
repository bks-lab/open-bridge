#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""DESIGN.md → CSS custom properties.

The Bridge's design system lives in DESIGN.md (Google-Labs DESIGN.md alpha
format). Brand colors must NEVER be hand-picked in a deliverable — they are
pulled from DESIGN.md so every surface (deck, dashboards, emails, these HTML
kits) stays visually aligned and a palette change propagates from one place.

This script reads the YAML frontmatter of a DESIGN.md and emits the `:root` +
`html.dark` CSS custom-property blocks that the html-canvas shell expects.
Paste the output into the shell's <style>, or write it to a file and @import-
inline it. The variable names are stable, so the section building blocks and
the shell reference them directly.

Mapping:
  colors.<key>            ->  --<key>            (in :root)
  colors.dark-<base>      ->  --<base> override  (in html.dark)
  typography.<role>.*     ->  --fs/-fw/-lh/-ls-<role>
  spacing.<step>          ->  --space-<step>
  rounded.<step>          ->  --radius-<step>
  fontFamily: Inter       ->  expanded to the no-Google-Fonts system stack

Usage:
  design-to-css.py [path/to/DESIGN.md] [--out file.css]
  # defaults: DESIGN.md resolved from the repo root; CSS printed to stdout
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("design-to-css: PyYAML required (pip install pyyaml)")

# No Google Fonts (GDPR — no third-party IP logging). Inter is expected to be
# either installed locally or gracefully degraded to the platform UI font.
SANS_STACK = 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, Roboto, "Helvetica Neue", Arial, sans-serif'
MONO_STACK = '"SF Mono", Monaco, "Cascadia Code", "Roboto Mono", Consolas, "Liberation Mono", monospace'

# DESIGN.md color key  ->  canonical html-canvas CSS-var name.
# The shell + section catalog reference the SHORT canonical names (--ink/--muted/
# --line) seen across every mined deliverable, not the raw DESIGN.md key names.
# Keys absent from this map are intentionally skipped — the shell carries the status
# + lens additions in its documented "skill additions" block. Specifically dropped:
# feature-* decorative gradients, brand-wordmark, on-surface-muted (== --muted),
# attention (== --accent-secondary), and the AA-tuned status variants. `dark-*` keys
# override their base.
COLOR_MAP = {
    "surface": "surface",
    "surface-subtle": "surface-subtle",
    "surface-muted": "surface-muted",
    "on-primary": "on-primary",
    "on-surface": "on-surface",
    "primary": "ink",
    "secondary": "muted",
    "border": "line",
    "border-subtle": "line-subtle",
    "accent": "accent",
    "accent-secondary": "accent-secondary",
    "accent-from": "accent-from",
    "accent-to": "accent-to",
    "success": "ok",
    "info": "info",
    # dark-mode overrides (emitted into html.dark)
    "dark-surface": "surface",
    "dark-surface-subtle": "surface-subtle",
    "dark-surface-muted": "surface-muted",
    "dark-on-surface": "on-surface",
    "dark-border": "line",
    "dark-accent-from": "accent-from",
    "dark-accent-to": "accent-to",
    "dark-primary": "ink",        # add `dark-primary:` to DESIGN.md to fill the dark headline ramp
    "dark-secondary": "muted",    # add `dark-secondary:` to DESIGN.md to fill the dark caption ramp
}


def frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---"):
        sys.exit(f"design-to-css: {path} has no YAML frontmatter")
    parts = text.split("---", 2)
    if len(parts) < 3:
        sys.exit(f"design-to-css: {path} frontmatter not closed")
    data = yaml.safe_load(parts[1])
    if not isinstance(data, dict):
        sys.exit(f"design-to-css: {path} frontmatter is not a mapping")
    return data


def expand_font(value: str) -> str:
    """Turn a bare `Inter` (or a mono spec) into a full self-hosted stack."""
    v = (value or "").strip().strip('"').strip("'")
    if v.lower() == "inter" or v == "":
        return SANS_STACK
    if "mono" in v.lower():
        return MONO_STACK
    return value  # already a full stack — pass through


def emit_colors(colors: dict) -> tuple[list[str], list[str]]:
    root, dark = [], []
    for key, val in colors.items():
        canon = COLOR_MAP.get(str(key))
        if not canon:
            continue  # unmapped (feature-*, brand-*, attention, …) — shell owns those
        target = dark if str(key).startswith("dark-") else root
        target.append(f"  --{canon}: {val};")
    return root, dark


def emit_typography(typo: dict) -> list[str]:
    out = []
    # canonical family vars first (no Google Fonts)
    fam = (typo.get("code") or {}).get("fontFamily", "")
    out.append(f"  --font-sans: {SANS_STACK};")
    out.append(f"  --font-mono: {expand_font(fam) if fam else MONO_STACK};")
    for role, spec in typo.items():
        if not isinstance(spec, dict):
            continue
        if "fontSize" in spec:
            out.append(f"  --fs-{role}: {spec['fontSize']};")
        if "fontWeight" in spec:
            out.append(f"  --fw-{role}: {spec['fontWeight']};")
        if "lineHeight" in spec:
            out.append(f"  --lh-{role}: {spec['lineHeight']};")
        if "letterSpacing" in spec:
            out.append(f"  --ls-{role}: {spec['letterSpacing']};")
    return out


def emit_scale(prefix: str, scale: dict) -> list[str]:
    return [f"  --{prefix}-{k}: {v};" for k, v in scale.items()]


def build_css(design: dict) -> str:
    root_lines: list[str] = []
    dark_lines: list[str] = []

    colors = design.get("colors") or {}
    cr, cd = emit_colors(colors)
    root_lines += cr
    dark_lines += cd

    if design.get("typography"):
        root_lines += emit_typography(design["typography"])
    if design.get("spacing"):
        root_lines += emit_scale("space", design["spacing"])
    if design.get("rounded"):
        root_lines += emit_scale("radius", design["rounded"])

    name = design.get("name", "design")
    header = (
        f"/* Generated from DESIGN.md ({name}) by html-canvas/scripts/design-to-css.py.\n"
        f"   Do not hand-edit colors here — change DESIGN.md and regenerate. */\n"
    )
    css = header + ":root {\n" + "\n".join(root_lines) + "\n}\n"
    if dark_lines:
        css += (
            "\n/* Dark-mode overrides (applied via the .dark class on <html>). */\n"
            "html.dark {\n" + "\n".join(dark_lines) + "\n}\n"
        )
    return css


def main() -> int:
    repo_root = Path(__file__).resolve().parents[3]
    ap = argparse.ArgumentParser(description="DESIGN.md → CSS custom properties")
    ap.add_argument("design", nargs="?", default=str(repo_root / "DESIGN.md"),
                    help="path to DESIGN.md (default: repo-root DESIGN.md)")
    ap.add_argument("--out", help="write CSS to this file instead of stdout")
    args = ap.parse_args()

    css = build_css(frontmatter(Path(args.design)))
    if args.out:
        Path(args.out).write_text(css, encoding="utf-8")
        print(f"✓ wrote {args.out} ({css.count(chr(10))} lines)")
    else:
        sys.stdout.write(css)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
