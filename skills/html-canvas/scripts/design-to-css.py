#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""DESIGN.md -> CSS custom properties.

The Bridge's design system lives in DESIGN.md (Google-Labs DESIGN.md alpha
format). Brand colors must NEVER be hand-picked in a deliverable - they are
pulled from DESIGN.md so every surface (deck, dashboards, emails, these HTML
kits) stays visually aligned and a palette change propagates from one place.

This script reads the YAML frontmatter of a DESIGN.md and emits the `:root` +
`html.dark` CSS custom-property blocks that the html-canvas shell expects.
Paste the output into the shell's <style>, or write it to a file and @import-
inline it. The variable names are stable, so the section building blocks and
the shell reference them directly.

Mapping:
  colors.<key>            ->  --<canonical>       (in :root)
  colorsDark.<key>        ->  --<canonical>       (in html.dark)
  colors.dark-<base>      ->  --<base> override   (in html.dark, legacy form)
  typography.<role>.*     ->  --fs/-fw/-lh/-ls-<role>
  typography.display.fontFamily -> --font-display
  typography.body-md.fontFamily -> --font-sans
  typography.code.fontFamily    -> --font-mono
  spacing.<step>          ->  --space-<step>
  rounded.<step>          ->  --radius-<step>
  a bare family name      ->  expanded to a self-hosted stack (no Google Fonts)

A DESIGN.md may carry its dark palette in either shape:
  * `colorsDark:` as a sibling of `colors:`, same key names, no prefix. This is
    the current form and the one the brand upstream uses.
  * `dark-<base>:` keys inside `colors:`. The older form, still read so a fork
    that has not migrated does not silently lose its dark mode.

A color key this script does not know is SKIPPED, and skipping is reported on
stderr. That report is the point: seven tokens once vanished from the output in
silence and nobody noticed for months. stdout stays pure CSS either way.

Usage:
  design-to-css.py [path/to/DESIGN.md] [--out file.css]
  design-to-css.py [path/to/DESIGN.md] --shell [shell.html] --out page.html
  # defaults: DESIGN.md resolved from the repo root; CSS printed to stdout.
  # --shell fills the marked token region of the html-canvas shell and writes
  # the page, so nobody pastes values by hand.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

try:
    import yaml
except ImportError:
    sys.exit("design-to-css: PyYAML required (pip install pyyaml)")

# No Google Fonts (GDPR: no third-party IP logging). All three families are
# SIL OFL and are expected to be self-hosted, degrading to the platform stack.
SANS_STACK = 'Inter, -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, Roboto, "Helvetica Neue", Arial, sans-serif'
SERIF_STACK = '"Playfair Display", Georgia, "Times New Roman", serif'
MONO_STACK = '"JetBrains Mono", ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, "Liberation Mono", monospace'

# DESIGN.md color key  ->  canonical html-canvas CSS-var name(s).
# The shell + section catalog reference SHORT canonical names (--ink/--muted/
# --line), not the raw DESIGN.md key names, so this table is the translation
# layer and the only place the two vocabularies meet.
#
# A key that maps to TWO names is an alias, and every alias is here because the
# brand has one value where the shell grew two variables:
#   surface-raised -> --raised AND --surface-subtle: the brand forbids
#     alternating section backgrounds, so its "other surface" is the white card.
#   on-surface     -> --ink AND --on-surface: headings and body copy are the
#     same color in this brand; the shell separates them, the brand does not.
#   border         -> --line AND --line-subtle: there is exactly one hairline
#     color, "never heavier than 1px" and never a second tone.
#
# Deliberately NOT emitted, because the brand has no such thing any more:
#   --accent-from / --accent-to / --accent-secondary. Gradients are banned
#   ("the brand is flat"), so a gradient anchor pair would be a wrong value,
#   not a missing one.
COLOR_MAP = {
    # brand
    "primary": ["primary"],
    "primary-hover": ["primary-hover"],
    "secondary": ["secondary"],
    "accent": ["accent"],
    "accent-subtle": ["accent-subtle"],
    "accent-line": ["accent-line"],
    # surfaces
    "surface": ["surface"],
    "surface-raised": ["raised", "surface-subtle"],
    "surface-muted": ["surface-muted"],
    # text
    "on-surface": ["ink", "on-surface"],
    "on-surface-muted": ["muted"],
    "on-surface-faint": ["ink-faint"],
    "on-primary": ["on-primary"],
    # lines
    "border": ["line", "line-subtle"],
    "border-strong": ["line-strong"],
    # semantic
    "success": ["ok"],
    "warning": ["warn"],
    "danger": ["danger"],
    "info": ["info"],
    # legacy keys from the pre-2026-07 palette, kept so an un-migrated fork
    # still produces a complete sheet instead of a half-empty one
    "surface-subtle": ["surface-subtle"],
    "border-subtle": ["line-subtle"],
    "accent-secondary": ["accent-secondary"],
    "accent-from": ["accent-from"],
    "accent-to": ["accent-to"],
}

# Delta applied only to a manifest still in the PRE-2026-07 shape, so an
# un-migrated fork regenerates byte-for-byte what it got before. There, the
# headline ramp was `primary` and the caption ramp was `secondary`; in the
# current brand those two names mean the brand ink color and the working accent,
# and the text ramp lives on `on-surface*`. Same key, opposite meaning: mapping
# it by one table would quietly write brand blue into the caption variable.
LEGACY_COLOR_MAP = {
    "primary": ["ink"],
    "secondary": ["muted"],
    "on-surface": ["on-surface"],
    "border": ["line"],
    # empty = known but not emitted: in the old palette this key held the same
    # value as `secondary`, so emitting both wrote --muted twice. It is reported
    # as skipped rather than dropped in silence.
    "on-surface-muted": [],
}


def is_legacy_shape(colors: dict, dark_colors: dict) -> bool:
    """True when the manifest predates the surface-raised / colorsDark shape."""
    if dark_colors:
        return False
    return "surface-raised" not in (colors or {})


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
    """Turn a bare family name into a full self-hosted stack (never a CDN)."""
    v = (value or "").strip().strip('"').strip("'")
    if v == "":
        return SANS_STACK
    # A comma means the manifest already spelled out its own stack. Respect it.
    # Without this guard the mono branch below swallowed any declared stack that
    # merely contained the word "mono", which is every mono stack ever written.
    if "," in v:
        return v
    if v.lower() == "inter":
        return SANS_STACK
    if "playfair" in v.lower() or v.lower() == "serif":
        return SERIF_STACK
    if "mono" in v.lower():
        return MONO_STACK
    return value


def emit_colors(colors: dict, dark_colors: dict) -> tuple[list[str], list[str], list[str]]:
    """Return (:root lines, html.dark lines, skipped keys).

    `colors:` feeds :root. The dark palette comes from `colorsDark:` when the
    manifest carries one, and from `dark-<base>:` keys inside `colors:` when it
    carries the older shape instead. Both may be present; colorsDark wins.
    """
    root, dark, skipped = [], [], []

    table = dict(COLOR_MAP)
    if is_legacy_shape(colors, dark_colors):
        table.update(LEGACY_COLOR_MAP)

    def push(target: list[str], key: str, val, where: str) -> None:
        canon = table.get(str(key))
        if not canon:
            skipped.append(f"{where}.{key}")
            return
        for name in canon:
            target.append(f"  --{name}: {val};")

    for key, val in (colors or {}).items():
        k = str(key)
        if k.startswith("dark-"):
            # legacy shape: dark-<base> overrides <base> in html.dark
            push(dark, k[len("dark-"):], val, "colors")
        else:
            push(root, k, val, "colors")

    if dark_colors:
        dark = []  # colorsDark is authoritative; do not mix the two shapes
        for key, val in dark_colors.items():
            push(dark, str(key), val, "colorsDark")

    return root, dark, skipped


def emit_typography(typo: dict) -> list[str]:
    out = []
    # Canonical family vars first. The family switch is the type hierarchy in
    # this brand, so --font-display is load-bearing, not decoration.
    display_fam = (typo.get("display") or {}).get("fontFamily", "")
    body_fam = (typo.get("body-md") or {}).get("fontFamily", "")
    mono_fam = (typo.get("code") or {}).get("fontFamily", "")
    out.append(f"  --font-sans: {expand_font(body_fam)};")
    out.append(f"  --font-display: {expand_font(display_fam)};")
    out.append(f"  --font-mono: {expand_font(mono_fam) if mono_fam else MONO_STACK};")
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


def build_css(design: dict) -> tuple[str, list[str]]:
    root_lines: list[str] = []
    dark_lines: list[str] = []

    colors = design.get("colors") or {}
    dark_colors = design.get("colorsDark") or {}
    cr, cd, skipped = emit_colors(colors, dark_colors)
    root_lines += cr
    dark_lines += cd

    if design.get("typography"):
        root_lines += emit_typography(design["typography"])
    if design.get("spacing"):
        root_lines += emit_scale("space", design["spacing"])
    if design.get("rounded"):
        root_lines += emit_scale("radius", design["rounded"])

    # A manifest in the older shape has no surface-raised, so the shell's card
    # colour would be undefined. Cards then sit on the page colour, as before.
    if not any(l.lstrip().startswith("--raised:") for l in root_lines):
        root_lines.append("  --raised: var(--surface);")

    # Print: the dark palette never reaches paper, and the page ground drops to
    # the card colour (DESIGN.md, Colors: "drop the warm ground to white, keep
    # every other token"). Emitted from the same tables, so it cannot drift.
    print_lines = [l for l in cr]
    raised = colors.get("surface-raised")
    if raised:
        print_lines = [l for l in print_lines if not l.lstrip().startswith("--surface:")]
        print_lines.append(f"  --surface: {raised};")

    name = design.get("name", "design")
    stamp = design.get("last_updated", "")
    header = (
        f"/* Generated from DESIGN.md ({name}{', ' + str(stamp) if stamp else ''}) by\n"
        f"   html-canvas/scripts/design-to-css.py. Do not hand-edit colors here:\n"
        f"   change DESIGN.md and regenerate. */\n"
    )
    css = header + ":root {\n" + "\n".join(root_lines) + "\n}\n"
    if dark_lines:
        css += (
            "\n/* Dark-mode overrides (applied via the .dark class on <html>). */\n"
            "html.dark {\n" + "\n".join(dark_lines) + "\n}\n"
        )
    if print_lines:
        css += (
            "\n/* Print: light palette on a white ground, whatever the screen mode. */\n"
            "@media print {\n:root, html.dark {\n"
            + "\n".join("  " + l for l in print_lines)
            + "\n}\n}\n"
        )
    return css, skipped


# The shell marks the one region this script owns. Everything between the two
# markers is replaced; everything outside stays byte for byte. The committed
# shell carries brand neutral system colours there, so a copy that was never
# generated is plain but legible, and the core file never holds a brand value.
BEGIN = "/* design-tokens:begin */"
END = "/* design-tokens:end */"


def inject(shell: str, css: str) -> str:
    """Return `shell` with the token region replaced by `css`."""
    if shell.count(BEGIN) != 1 or shell.count(END) != 1:
        raise ValueError("shell needs exactly one %s and one %s marker" % (BEGIN, END))
    head, rest = shell.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    return head + BEGIN + "\n" + css.rstrip("\n") + "\n" + END + tail


def default_shell() -> Path:
    return Path(__file__).resolve().parents[1] / "assets" / "shell.html"


def main() -> int:
    repo_root = Path(__file__).resolve().parents[3]
    ap = argparse.ArgumentParser(description="DESIGN.md -> CSS custom properties")
    ap.add_argument("design", nargs="?", default=str(repo_root / "DESIGN.md"),
                    help="path to DESIGN.md (default: repo-root DESIGN.md)")
    ap.add_argument("--out", help="write CSS to this file instead of stdout")
    ap.add_argument("--shell", nargs="?", const=str(Path(__file__).resolve().parents[1] / "assets" / "shell.html"),
                    help="write a filled copy of the html-canvas shell (default: the bundled "
                         "assets/shell.html) to --out instead of bare CSS")
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero when a color key was skipped")
    args = ap.parse_args()

    css, skipped = build_css(frontmatter(Path(args.design)))
    if args.shell:
        if not args.out:
            sys.exit("design-to-css: --shell needs --out (the page to write)")
        try:
            page = inject(Path(args.shell).read_text(encoding="utf-8"), css)
        except ValueError as e:
            sys.exit("design-to-css: %s" % e)
        Path(args.out).write_text(page, encoding="utf-8")
        print(f"wrote {args.out} (shell with tokens from {args.design})")
    elif args.out:
        Path(args.out).write_text(css, encoding="utf-8")
        print(f"wrote {args.out} ({css.count(chr(10))} lines)")
    else:
        sys.stdout.write(css)

    # Reported, never silent: an unknown key produces no variable, so a
    # deliverable would fall back to nothing and look plausible while being
    # wrong. stderr keeps stdout usable as pure CSS in a pipe.
    if skipped:
        print(
            "design-to-css: %d color key(s) not in COLOR_MAP, skipped: %s"
            % (len(skipped), ", ".join(skipped)),
            file=sys.stderr,
        )
        print(
            "  -> add them to COLOR_MAP (and to the consuming shell) "
            "or remove them from DESIGN.md",
            file=sys.stderr,
        )
        if args.strict:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
