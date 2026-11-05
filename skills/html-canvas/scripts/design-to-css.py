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
  design-to-css.py [path/to/DESIGN.md | design-id] [--out file.css]
  design-to-css.py [path/to/DESIGN.md] --shell [shell.html] --out page.html
  design-to-css.py --context <ctx> | --persona <id> [...]
  # defaults: the design the Bridge resolves (scripts/designs.py: the context's
  # or persona's design_ref, the theme's branding.design, else the root
  # DESIGN.md); CSS printed to stdout. An explicit path always wins.
  # --shell fills the marked token region of the html-canvas shell and writes
  # the page, so nobody pastes values by hand.

Serving another consumer (references/theme-contract.md):
  design-to-css.py DESIGN.md --map consumer.map.yaml \
      --selectors light=:root,.theme-light dark=.theme-dark \
      --region deck-tokens --shell deck.html --out deck.html
  # --map       emits only the consumer's variables, named as it names them,
  #             each resolved from a DESIGN.md color role in both modes; a
  #             derived variant (e.g. accent-dim) is a color-mix() of a role.
  #             Like the default sheet it ends in an @media print block: the
  #             light values, with the surface role dropped to surface-raised.
  # --selectors renames the light and dark groups (default :root, html.dark),
  #             with or without --map. A map file may declare them too.
  # --region    fills /* <name>:begin */ ... /* <name>:end */ in any file
  #             instead of the shell's design-tokens region. Idempotent, and
  #             --out may name the input file to rewrite it in place.
  # Under --strict a role the map names and DESIGN.md lacks exits non-zero.

Embedding the typefaces (optional, for a page that is sent or bundled):
  design-to-css.py DESIGN.md --embed-fonts [--font-dir DIR ...] --shell --out page.html
  # adds base64 @font-face rules for the DESIGN.md families (embed-fonts.py)
  # after the tokens, inside the same generated region. Off by default; a
  # family with no font file is reported on stderr and keeps the system stack.
"""
from __future__ import annotations

import argparse
import importlib.util
import re
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
# un-migrated fork keeps the meaning its keys had (emit_colors adds the dark
# values that shape never declared, see the legacy branch there). There, the
# headline ramp was `primary` and the caption ramp was `secondary`; in the
# current brand those two names mean the brand ink color and the working accent,
# and the text ramp lives on `on-surface*`. Same key, opposite meaning: mapping
# it by one table would quietly write brand blue into the caption variable.
LEGACY_COLOR_MAP = {
    # the old `primary` is the headline ink AND the surface `on-primary` sits
    # on; leaving --primary neutral paired a white on-primary with a system
    # colour that turns white in dark mode (the run button read 1:1)
    "primary": ["ink", "primary"],
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
    elif is_legacy_shape(colors, dark_colors) and "dark-primary" not in (colors or {}) \
            and "dark-on-surface" in (colors or {}):
        # The legacy headline ink is `primary`, and a legacy manifest rarely
        # declares a `dark-primary`. html.dark then kept the light ink, so
        # headings and controls rendered dark on the dark ground. The dark body
        # colour is the closest declared readable value; it stands in for the ink.
        at = next((i for i, l in enumerate(dark) if l.startswith("  --on-surface:")), len(dark))
        dark.insert(at, f"  --ink: {colors['dark-on-surface']};")
        # Same gap one step down: the legacy caption colour `secondary` was tuned
        # for the light ground and falls under 4.5:1 on a dark one. Without a
        # declared dark value it becomes the dark body colour mixed into the dark
        # ground, a derived value that follows both tokens.
        if "secondary" in colors and "dark-secondary" not in colors:
            dark.insert(min(at + 2, len(dark)),
                        "  --muted: color-mix(in srgb, var(--on-surface) 72%, var(--surface));")
        # A primary surface is ink-coloured in this shape, so on dark it follows
        # the ink and its label takes the ground colour: an inverted button
        # instead of a dark box on a dark ground.
        if "dark-on-primary" not in colors:
            dark += ["  --primary: var(--ink);", "  --on-primary: var(--surface);"]

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


# The shell's theme contract. A consumer with other selectors passes its own.
DEFAULT_SELECTORS = {"light": ":root", "dark": "html.dark"}


def css_header(design: dict) -> str:
    name = design.get("name", "design")
    stamp = design.get("last_updated", "")
    return (
        f"/* Generated from DESIGN.md ({name}{', ' + str(stamp) if stamp else ''}) by\n"
        f"   html-canvas/scripts/design-to-css.py. Do not hand-edit colors here:\n"
        f"   change DESIGN.md and regenerate. */\n"
    )


def build_css(design: dict, selectors: dict | None = None) -> tuple[str, list[str]]:
    light_sel, dark_sel = _selectors(selectors)
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

    css = css_header(design) + light_sel + " {\n" + "\n".join(root_lines) + "\n}\n"
    if dark_lines:
        how = ("applied via the .dark class on <html>" if dark_sel == DEFAULT_SELECTORS["dark"]
               else "applied via " + dark_sel)
        css += (
            f"\n/* Dark-mode overrides ({how}). */\n"
            + dark_sel + " {\n" + "\n".join(dark_lines) + "\n}\n"
        )
    if print_lines:
        css += (
            "\n/* Print: light palette on a white ground, whatever the screen mode. */\n"
            "@media print {\n" + light_sel + ", " + dark_sel + " {\n"
            + "\n".join("  " + l for l in print_lines)
            + "\n}\n}\n"
        )
    return css, skipped


def _selectors(selectors: dict | None) -> tuple[str, str]:
    sel = dict(DEFAULT_SELECTORS)
    sel.update({k: v for k, v in (selectors or {}).items() if v})
    return sel["light"], sel["dark"]


def parse_selectors(items: list[str]) -> dict:
    """`light=<selector>` / `dark=<selector>` pairs from the command line."""
    out = {}
    for item in items:
        key, sep, val = item.partition("=")
        if not sep or key not in DEFAULT_SELECTORS or not val.strip():
            raise ValueError("--selectors takes light=<selector> and/or dark=<selector>, got %r" % item)
        out[key] = val.strip()
    return out


# A consumer map names its own variables and says which DESIGN.md color role
# feeds each one. It is data the consumer owns, so this script knows nothing
# about any consumer:
#
#   selectors: {light: ":root", dark: ".theme-dark"}   # optional
#   vars:
#     bg: surface                                      # --bg from colors.surface
#     accent-dim: {role: accent, mix: 15}              # 15 % accent over transparent
#     ok-dim: {role: success, mix: 20, with: surface}  # 20 % success over the surface
#   print: false                                       # optional, default true
#
# `print: false` leaves out the light @media print block, for a consumer that
# prints the mode it shows (a slide deck, whose PDF mode render-pdf picks).
#
# A role resolves per mode: light from `colors:`, dark from `colorsDark:` or a
# legacy `dark-<role>` key, falling back to the light value when the manifest
# has no dark one (the dark group then repeats it, so both groups stay whole).
def load_map(path: Path) -> tuple[dict, dict, bool]:
    """Return (vars, selectors, print block) from a map file, or raise ValueError."""
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict) or not isinstance(data.get("vars"), dict) or not data["vars"]:
        raise ValueError(f"{path}: needs a non-empty 'vars:' mapping")
    entries = {}
    for name, spec in data["vars"].items():
        name = str(name).lstrip("-")
        if isinstance(spec, str):
            spec = {"role": spec}
        if not isinstance(spec, dict) or not isinstance(spec.get("role"), str):
            raise ValueError(f"{path}: {name} needs a role name or {{role: ..., mix: ...}}")
        if "mix" in spec:
            mix = spec["mix"]
            if isinstance(mix, bool) or not isinstance(mix, (int, float)) or not 0 <= mix <= 100:
                raise ValueError(f"{path}: {name} mix must be a percentage from 0 to 100")
        elif "with" in spec:
            raise ValueError(f"{path}: {name} sets 'with' but no 'mix' percentage")
        if not isinstance(spec.get("with", ""), str):
            raise ValueError(f"{path}: {name} 'with' must be a role name or transparent")
        entries[name] = spec
    selectors = data.get("selectors") or {}
    if not isinstance(selectors, dict) or set(selectors) - set(DEFAULT_SELECTORS):
        raise ValueError(f"{path}: 'selectors:' takes only light and dark")
    print_block = data.get("print", True)
    if not isinstance(print_block, bool):
        raise ValueError(f"{path}: 'print:' takes true or false")
    return entries, {k: str(v) for k, v in selectors.items()}, print_block


def build_mapped_css(design: dict, entries: dict, selectors: dict | None = None,
                     print_block: bool = True) -> tuple[str, list[str]]:
    """Return (css, missing roles) holding exactly the mapped variables per mode."""
    light_sel, dark_sel = _selectors(selectors)
    colors = design.get("colors") or {}
    dark_colors = design.get("colorsDark") or {}

    def resolve(role: str, dark: bool, paper: bool = False):
        if role not in colors:
            return None
        if paper:
            # print: the light value, the ground dropped to the card colour (as build_css)
            return colors.get("surface-raised", colors[role]) if role == "surface" else colors[role]
        if dark:
            if dark_colors:
                return dark_colors.get(role, colors[role])
            return colors.get("dark-" + role, colors[role])
        return colors[role]

    light, darks, paper, missing = [], [], [], []
    for name, spec in entries.items():
        roles = [spec["role"]] + ([spec["with"]] if spec.get("with") not in (None, "transparent") else [])
        absent = [r for r in roles if r not in colors]
        if absent:
            missing += [f"{name} <- {r}" for r in absent]
            continue
        for target, dark, on_paper in ((light, False, False), (darks, True, False), (paper, False, True)):
            val = resolve(spec["role"], dark, on_paper)
            if "mix" in spec:
                ground = (resolve(spec["with"], dark, on_paper) if spec.get("with") not in (None, "transparent")
                          else "transparent")
                val = f"color-mix(in srgb, {val} {spec['mix']:g}%, {ground})"
            target.append(f"  --{name}: {val};")

    css = css_header(design) + light_sel + " {\n" + "\n".join(light) + "\n}\n"
    css += "\n" + dark_sel + " {\n" + "\n".join(darks) + "\n}\n"
    if paper and print_block:
        # the same print block the default sheet carries (build_css), in the consumer's names
        css += ("\n/* Print: light palette on a white ground, whatever the screen mode. */\n"
                "@media print {\n" + light_sel + ", " + dark_sel + " {\n"
                + "\n".join("  " + l for l in paper) + "\n}\n}\n")
    return css, missing


# The shell marks the one region this script owns. Everything between the two
# markers is replaced; everything outside stays byte for byte. The committed
# shell carries brand neutral system colours there, so a copy that was never
# generated is plain but legible, and the core file never holds a brand value.
# Any other file can carry its own region under its own name (--region).
REGION = "design-tokens"
REGION_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")


def markers(region: str = REGION) -> tuple[str, str, str]:
    """The begin, end and generated-block comments of a named region."""
    if not REGION_NAME.match(region):
        raise ValueError("region name %r must be letters, digits, '.', '_' or '-'" % region)
    return (f"/* {region}:begin */", f"/* {region}:end */",
            f"/* {region}: generated from DESIGN.md, overrides the neutral values above */")


BEGIN, END, GENERATED = markers()


LEGACY_HEADER = "/* Generated from DESIGN.md"


def region_neutral(text: str, region: str = REGION) -> str:
    """The neutral block of `region` in `text`: what sits before the generated comment."""
    begin, end, generated = markers(region)
    body = text.split(begin, 1)[1].split(end, 1)[0]
    return body.split(generated, 1)[0].rstrip("\n")


def inject(shell: str, css: str, region: str = REGION, neutral_default: str | None = None) -> str:
    """Return `shell` with `css` added to its token region.

    The shell's own neutral values stay first and `css` follows, so a token the
    DESIGN.md does not define keeps its neutral value instead of going undefined:
    a legacy manifest without warn/danger/accent-line left the run button of a
    simulation invisible (white on white) when the region was replaced whole.

    A page generated before that rule holds generated tokens right after :begin,
    with no generated comment. That block is stale brand output, not neutral
    values, so it is replaced by `neutral_default` (for the design-tokens region,
    the bundled shell's neutral block) instead of being kept in front of `css`.
    """
    begin, end, generated = markers(region)
    if shell.count(begin) != 1 or shell.count(end) != 1:
        raise ValueError("shell needs exactly one %s and one %s marker" % (begin, end))
    head, rest = shell.split(begin, 1)
    if end not in rest:
        raise ValueError("%s comes before %s" % (end, begin))
    neutral, tail = rest.split(end, 1)
    if generated not in neutral and neutral.lstrip().startswith(LEGACY_HEADER):
        if neutral_default is None and region == REGION:
            neutral_default = region_neutral(default_shell().read_text(encoding="utf-8"))
        neutral = "\n" + (neutral_default or "").strip("\n")
    neutral = neutral.split(generated, 1)[0].rstrip("\n")
    return (head + begin + neutral + "\n" + generated + "\n" + css.rstrip("\n") + "\n"
            + end + tail)


def font_faces(design_path: Path, font_dirs: list[Path]) -> str:
    """base64 @font-face rules for the DESIGN.md families, via embed-fonts.py."""
    path = Path(__file__).resolve().parent / "embed-fonts.py"
    spec = importlib.util.spec_from_file_location("embed_fonts", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    faces = mod.build_font_face_css(mod.collect_families(design_path), font_dirs)
    if not faces:
        return ""
    return "\n/* Embedded fonts (embed-fonts.py), so the page needs no font files. */\n" + faces


PROJECT_MARKERS = (".git", "bridge-config.yaml")


def bridge_design():
    """bridge_design.py: which DESIGN.md a page wears, asked of the Bridge."""
    spec = importlib.util.spec_from_file_location("bridge_design", Path(__file__).resolve().parent / "bridge_design.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def find_design(start: Path) -> Path | None:
    """The nearest DESIGN.md at or above `start` (a folder, or a file's folder).

    The walk stops at the project root: the first folder holding .git or
    bridge-config.yaml. Without such a folder above, only `start` itself counts,
    so a stray DESIGN.md somewhere in a temp or home folder never brands a page
    or skews the gate. The walk lives in bridge_design.py, which every script
    that looks for a DESIGN.md asks.
    """
    return bridge_design().find_design(start)


def default_shell() -> Path:
    return Path(__file__).resolve().parents[1] / "assets" / "shell.html"


def main() -> int:
    ap = argparse.ArgumentParser(description="DESIGN.md -> CSS custom properties")
    ap.add_argument("design", nargs="?",
                    help="path to a DESIGN.md, or a design id under identity/designs/ "
                         "(default: the design the Bridge resolves, else the repo-root DESIGN.md)")
    ap.add_argument("--context", help="workflow/contexts/<name>.yaml whose design_ref applies")
    ap.add_argument("--persona", help="identity/personas/<id>.yaml whose design_ref applies")
    ap.add_argument("--out", help="write CSS to this file instead of stdout")
    ap.add_argument("--shell", nargs="?", const=str(Path(__file__).resolve().parents[1] / "assets" / "shell.html"),
                    help="write a filled copy of the html-canvas shell (default: the bundled "
                         "assets/shell.html) to --out instead of bare CSS")
    ap.add_argument("--strict", action="store_true",
                    help="exit non-zero when a color key was skipped, or with --map "
                         "when a mapped role is missing from DESIGN.md")
    ap.add_argument("--map", metavar="YAML",
                    help="emit only the variables this consumer map names, each from a "
                         "DESIGN.md color role (see references/theme-contract.md)")
    ap.add_argument("--selectors", nargs="+", metavar="MODE=SELECTOR",
                    help="light=<selector> and/or dark=<selector> for the two groups "
                         "(default light=:root dark=html.dark)")
    ap.add_argument("--region", metavar="NAME",
                    help="with --shell: fill the /* NAME:begin */ ... /* NAME:end */ region "
                         "of that file instead of design-tokens")
    ap.add_argument("--embed-fonts", action="store_true",
                    help="also emit base64 @font-face rules for the DESIGN.md font families "
                         "(off by default; for pages that are sent or bundled)")
    ap.add_argument("--font-dir", action="append", default=[], metavar="DIR",
                    help="with --embed-fonts: extra directory of <family>-latin-<weight>.woff2 "
                         "files, searched before the bundled assets/fonts/")
    args = ap.parse_args()

    selectors: dict = {}
    entries = None
    print_block = True
    try:
        if args.map:
            entries, selectors, print_block = load_map(Path(args.map))
        if args.selectors:
            selectors.update(parse_selectors(args.selectors))
        region = args.region or REGION
        markers(region)
    except (ValueError, OSError, yaml.YAMLError) as e:
        sys.exit("design-to-css: %s" % e)
    if args.region and not args.shell:
        sys.exit("design-to-css: --region needs --shell <file> (the file holding the region)")
    if args.font_dir and not args.embed_fonts:
        sys.exit("design-to-css: --font-dir needs --embed-fonts")

    try:
        chosen = bridge_design().resolve(args.design, context=args.context, persona=args.persona)
    except ValueError as e:
        sys.exit("design-to-css: %s" % e)
    if chosen is None:
        sys.exit("design-to-css: no DESIGN.md found; pass a path")
    args.design = str(chosen)
    design = frontmatter(Path(args.design))
    if entries is not None:
        css, missing = build_mapped_css(design, entries, selectors, print_block)
        skipped = []
    else:
        css, skipped = build_css(design, selectors)
        missing = []
    if missing and args.strict:
        sys.exit("design-to-css: %d mapped role(s) not in DESIGN.md colors: %s"
                 % (len(missing), ", ".join(missing)))
    if args.embed_fonts:
        css += font_faces(Path(args.design), [Path(d) for d in args.font_dir])
    if args.shell:
        if not args.out:
            sys.exit("design-to-css: --shell needs --out (the page to write)")
        try:
            page = inject(Path(args.shell).read_text(encoding="utf-8"), css, region)
        except ValueError as e:
            sys.exit("design-to-css: %s" % e)
        Path(args.out).write_text(page, encoding="utf-8")
        print(f"wrote {args.out} (shell with tokens from {args.design})")
    elif args.out:
        Path(args.out).write_text(css, encoding="utf-8")
        print(f"wrote {args.out} ({css.count(chr(10))} lines)")
    else:
        sys.stdout.write(css)

    if missing:
        print("design-to-css: %d mapped role(s) not in DESIGN.md colors, skipped: %s"
              % (len(missing), ", ".join(missing)), file=sys.stderr)
        print("  -> add the role to DESIGN.md or fix the map", file=sys.stderr)

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
