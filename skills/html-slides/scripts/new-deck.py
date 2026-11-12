#!/usr/bin/env python3
"""Assemble a single-file deck between markers, or refresh the markers of one.

A deck holds two kinds of text. The slides belong to the author. Everything
else is generated, and lives in a marked region the tool owns:

  deck-prepaint      <head>   pre-paint theme script (theme-contract.md, adapted
                              to the engine's .theme-light / .theme-dark)
  deck-fonts         <head>   embedded @font-face rules (html-canvas embed-fonts.py)
  deck-tokens        <style>  colour and font variables: the design preset through
                              html-canvas design-to-css.py --map presets/design.map.yaml
                              --region deck-tokens, a style preset from its YAML
  slide-engine:css   <style>  assets/slide-engine.css, byte for byte
  deck-preset-css    <style>  the preset's css_overrides
  deck-blocks        <style>  html-canvas section blocks (only with --blocks): the block
                              list, an alias layer from the canvas token names onto the
                              deck tokens, the CSS of the blocks and what they require
  slide-stage:css    <style>  assets/slide-stage.css (only with --with-stage)
  slide-engine:js    <body>   assets/slide-engine.js in a <script>, byte for byte
  slide-stage:js     <body>   assets/slide-stage.js in a <script> (only with --with-stage)
  deck-blocks:js     <body>   the sections.js part of every chosen block that has one
  deck-module:NAME   <body>   assets/modules/NAME.css in its own <style>, if present, then
                              assets/modules/NAME.js in a <script> (only with --with NAME),
                              after the engine and the stage, one region per module by name

Each region is `<!-- NAME:start -->CONTENT<!-- NAME:end -->`. In a stylesheet
CSS skips only the `<!--` and `-->` of a marker, not the name between them, so
the name would glue onto the next selector and void that rule. Every region
inside <style> therefore opens with an empty rule `{}` that swallows it.

--refresh rewrites only the regions a deck already carries, from the current
assets, DESIGN.md and preset; text outside them is never touched, and a second
run gives the same bytes. The set of modules stays the one the deck has. One
region can be added: deck-blocks:js, when --blocks on a refresh swaps the block
set of a deck built with --blocks for one that needs a script. Every splice is read back and
compared before the file is written.

Preset choice: --preset when given; else `design` when a DESIGN.md is given
(--design, a path or a design id, or --context / --persona whose design_ref
names one) or found walking up from the output path; else the style preset
marked `default: true`. On --refresh the preset is read back from the deck, and
a design deck reads back the design it recorded (`/* design-source: <id> */`)
unless --design, --context or --persona names another. A walk that ends at the
Bridge's own DESIGN.md asks the Bridge which design applies (the theme's
branding.design, else that file), so a deck inside the Bridge wears the
instance's design while a deck written into another repository keeps that
repository's (html-canvas bridge_design.py).

Every build and refresh ends with the gate, html-canvas verify-page.py (static,
--allow-sample), and exits with its result; --no-verify skips it.

Fonts: embedded by default (style presets depend on their typefaces);
--no-embed-fonts leaves the region empty and the deck on its fallback stacks.

Usage:
  new-deck.py --title "Quarterly review" --out deck.html [--slides slides.html]
              [--title-de T --title-en T] [--preset SLUG]
              [--design DESIGN.md | --context C | --persona P] [--lang en|de]
              [--with-stage] [--with NAME | --with all ...] [--blocks a,b | all]
              [--no-embed-fonts] [--force] [--no-verify]
  new-deck.py --refresh deck.html [--out other.html] [--preset SLUG] [--blocks a,b]
              [--design DESIGN.md | --context C | --persona P] [--embed-fonts | --no-embed-fonts]
  new-deck.py --list

--slides is an HTML fragment of <section class="slide ..."> elements
(reference/slide-types.md); without it the deck gets one title slide, and with
--blocks one sample slide per block after it (marked data-sample).
"""
from __future__ import annotations

import argparse
import html as html_mod
import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import yaml

SKILL = Path(__file__).resolve().parents[1]
ASSETS = SKILL / "assets"
MODULES = ASSETS / "modules"
PRESETS = SKILL / "presets"
CANVAS_SCRIPTS = SKILL.parent / "html-canvas" / "scripts"

THEME_KEY = "slide-theme"  # the engine's storage key; old decks share it
CSS_SINK = "{} /* swallows the marker name above: CSS skips only its <!-- and --> */\n"
NO_FONTS = "<!-- fonts not embedded: the deck uses its fallback stacks (new-deck.py --no-embed-fonts) -->"
SYSTEM_FONTS = "<!-- system fonts only: the preset names no font to embed -->"
PRESET_RE = re.compile(r"/\* deck-preset: ([a-z0-9][a-z0-9-]*) \*/")
SLIDE_RE = re.compile(r"<section\b[^>]*\bclass\s*=\s*[\"'][^\"']*\bslide\b", re.I)
STAMP_RE = re.compile(r"slide-engine v(\d+)")

# Regions in document order, and the context each lives in.
REGIONS = (
    ("deck-prepaint", "head"),
    ("deck-fonts", "head"),
    ("deck-tokens", "css"),
    ("slide-engine:css", "css"),
    ("deck-preset-css", "css"),
    ("deck-blocks", "css"),
    ("slide-stage:css", "css"),
    ("slide-engine:js", "body"),
    ("slide-stage:js", "body"),
    ("deck-blocks:js", "body"),
)
CSS_REGIONS = {name for name, where in REGIONS if where == "css"}
STAGE_REGIONS = ("slide-stage:css", "slide-stage:js")
BLOCKS_CSS, BLOCKS_JS = "deck-blocks", "deck-blocks:js"
BLOCK_REGIONS = (BLOCKS_CSS, BLOCKS_JS)
BLOCKS_LINE_RE = re.compile(r"^/\* blocks: (.*?) \*/$", re.M)
MODULE_PREFIX = "deck-module:"
MODULE_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]*$")
MODULE_MARK_RE = re.compile(r"<!-- deck-module:([a-z0-9][a-z0-9-]*):start -->")

# Hex-free values the deck keeps where DESIGN.md has no role for a variable:
# system colours for the ground and the text, everything else derived from them.
NEUTRAL_TOKENS = """\
:root, .theme-light { color-scheme: light; }
.theme-dark { color-scheme: dark; }
:root {
  --font-display: system-ui, sans-serif;
  --font-body: system-ui, sans-serif;
  --font-mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  --bg: Canvas;
  --text: CanvasText;
  --text-dim: color-mix(in srgb, var(--text) 72%, var(--bg));
  --surface: color-mix(in srgb, var(--text) 3%, var(--bg));
  --surface2: color-mix(in srgb, var(--text) 7%, var(--bg));
  --surface-elevated: var(--surface);
  --border: color-mix(in srgb, var(--text) 14%, var(--bg));
  --border-bright: color-mix(in srgb, var(--text) 28%, var(--bg));
  --accent: LinkText;
  --accent-dim: color-mix(in srgb, var(--accent) 12%, var(--bg));
  --primary: var(--text);
  --on-primary: var(--bg);
  --code-bg: var(--surface2);
  --code-text: var(--text);
  --green: var(--accent); --green-dim: var(--accent-dim);
  --red: var(--accent); --red-dim: var(--accent-dim);
  --amber: var(--accent); --amber-dim: var(--accent-dim);
  --cyan: var(--accent); --cyan-dim: var(--accent-dim);
}"""

PREPAINT = """
<script>
/* Theme pre-paint (html-slides): the saved choice, else the deck's own default
   (data-theme-default on <html>, new-deck.py --theme-default), else the OS, before
   the first paint. A default is not a choice, so it is never written to storage. */
(function () {
  var saved = null;
  try { saved = localStorage.getItem('%s'); } catch (e) { /* no storage */ }
  var def = document.documentElement.getAttribute('data-theme-default');
  var dark = saved === 'dark' || (saved !== 'light' && (def === 'dark' || (def !== 'light' &&
    !!window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches)));
  document.documentElement.classList.add(dark ? 'theme-dark' : 'theme-light');
})();
</script>
""" % THEME_KEY

# The style preset colour keys, in the order SKILL.md lists them.
COLOR_KEYS = (
    "bg", "surface", "surface2", "surface-elevated", "border", "border-bright",
    "text", "text-dim", "accent", "accent-dim", "code-bg", "code-text",
    "green", "green-dim", "red", "red-dim", "amber", "amber-dim", "cyan", "cyan-dim",
)


class DeckError(Exception):
    pass


# --- shared scripts ------------------------------------------------------------------------

_MODULES: dict[str, object] = {}


def module(name: str, path: Path):
    """Import a hyphenated script by path, once."""
    if name not in _MODULES:
        if not path.is_file():
            raise DeckError("%s not found; html-slides needs the html-canvas skill next to it" % path)
        spec = importlib.util.spec_from_file_location(name, path)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        _MODULES[name] = mod
    return _MODULES[name]


def design_to_css():
    return module("html_canvas_design_to_css", CANVAS_SCRIPTS / "design-to-css.py")


def embed_fonts():
    return module("html_canvas_embed_fonts", CANVAS_SCRIPTS / "embed-fonts.py")


def font_face():
    return module("html_slides_font_face", SKILL / "scripts" / "font-face.py")


# --- presets and DESIGN.md -----------------------------------------------------------------

def bridge_design():
    return module("html_canvas_bridge_design", CANVAS_SCRIPTS / "bridge_design.py")


def find_design(start: Path) -> Path | None:
    """The nearest DESIGN.md, never above the project root; at the Bridge's own root, the
    design the Bridge resolves (html-canvas bridge_design.py)."""
    try:
        return bridge_design().resolve(target=start, fallback=False)
    except ValueError as e:
        raise DeckError(str(e))


def load_preset(slug: str) -> dict:
    path = PRESETS / ("%s.yaml" % slug)
    if slug.startswith("_") or not path.is_file():
        known = sorted(p.stem for p in PRESETS.glob("*.yaml")
                       if not p.name.startswith("_") and not p.name.endswith(".map.yaml"))
        raise DeckError("unknown preset %r (known: %s)" % (slug, ", ".join(known)))
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise DeckError("%s is not a mapping" % path)
    return data


def default_style_slug() -> str:
    for p in sorted(PRESETS.glob("*.yaml")):
        if p.name.startswith("_") or p.name.endswith(".map.yaml"):
            continue
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        if data.get("default") is True and data.get("source") != "design":
            return p.stem
    raise DeckError("no style preset is marked default: true")


def is_design(preset: dict) -> bool:
    return preset.get("source") == "design"


# --- region contents -----------------------------------------------------------------------

def read_asset(name: str) -> str:
    path = ASSETS / name
    if not path.is_file():
        raise DeckError("assets/%s not found" % name)
    text = path.read_text(encoding="utf-8")
    closing = "</style" if name.endswith(".css") else "</script"
    if closing in text.lower():
        raise DeckError("assets/%s contains %s>, which would end its element early" % (name, closing))
    return text


def css_region(payload: str) -> str:
    return "\n" + CSS_SINK + payload + ("" if not payload or payload.endswith("\n") else "\n")


def script_region(payload: str) -> str:
    return "\n<script>\n" + payload + "\n</script>\n"


def style_tokens(slug: str, preset: dict) -> str:
    fonts = preset.get("fonts") or {}
    colors = preset.get("colors") or {}
    dark, light = colors.get("dark") or {}, colors.get("light") or {}
    missing = [m + "." + k for m, c in (("dark", dark), ("light", light)) for k in COLOR_KEYS if k not in c]
    if missing:
        raise DeckError("preset %s lacks colours: %s" % (slug, ", ".join(missing)))

    def stack(role: str, fallback: str) -> str:
        entry = fonts.get(role)
        if isinstance(entry, dict):
            return "'%s', %s" % (entry.get("family"), entry.get("fallback") or fallback)
        if isinstance(entry, str):
            return "'%s', %s" % (entry, fallback)
        return fallback

    def decls(c: dict) -> str:
        return "\n".join("  --%s: %s;" % (k, c[k]) for k in COLOR_KEYS)

    css = "\n".join([
        "/* deck-preset: %s */" % slug,
        "/* Dark is the default; light by the class or, without one, by the OS. */",
        ":root {",
        "  --font-display: %s;" % stack("display", "system-ui, sans-serif"),
        "  --font-body: %s;" % stack("body", "system-ui, sans-serif"),
        "  --font-mono: %s;" % stack("mono", "'SF Mono', Consolas, monospace"),
        decls(dark),
        "}",
        ":root.theme-light {", decls(light), "}",
        "@media (prefers-color-scheme: light) {",
        ":root:not(.theme-dark):not(.theme-light) {", decls(light), "}",
        "}",
    ])
    return css_region(css)


def design_font_stack(typography: dict, spec: dict) -> str:
    fallback = spec.get("fallback") or "system-ui, sans-serif"
    for role in spec.get("roles") or []:
        fam = str((typography.get(role) or {}).get("fontFamily") or "").strip()
        if not fam:
            continue
        if "," in fam:
            return fam
        expanded = design_to_css().expand_font(fam)
        if expanded != fam:
            return expanded
        return '"%s", %s' % (fam.strip("'\""), fallback)
    return fallback


def design_tokens(preset: dict, design: Path) -> str:
    d2c = design_to_css()
    try:
        entries, selectors, print_block = d2c.load_map(PRESETS / preset.get("map", "design.map.yaml"))
    except (OSError, ValueError, yaml.YAMLError) as e:
        raise DeckError("design map: %s" % e)
    data = d2c.frontmatter(design)
    try:
        css, missing = d2c.build_mapped_css(data, entries, selectors, print_block)
    except ValueError as e:
        raise DeckError("%s: %s" % (design, e))
    if missing:
        print("new-deck: %d mapped role(s) not in %s, the neutral value stays: %s"
              % (len(missing), design, ", ".join(missing)), file=sys.stderr)
    typography = data.get("typography") or {}
    fonts = preset.get("fonts") or {}
    lines = ["  --font-%s: %s;" % (var, design_font_stack(typography, fonts.get(role) or {}))
             for var, role in (("display", "display"), ("body", "body"), ("mono", "mono"))]
    label = fonts.get("label")
    if isinstance(label, dict):
        lines.append("  --font-label: %s;" % design_font_stack(typography, label))
        for role in label.get("roles") or []:
            spec = typography.get(role) or {}
            if spec.get("fontFamily"):
                track = str(spec.get("letterSpacing") or "").strip()
                if re.match(r"^-?\d+(\.\d+)?(em|px|rem)$", track):
                    lines.append("  --label-tracking: %s;" % track)
                break
    colours = data.get("colors") or {}
    if "gradient-via" in colours and "gradient-via-2" in colours:
        lines.append("  --stat-gradient: linear-gradient(100deg, var(--gradient-from, var(--accent)) 10%, "
                     "var(--gradient-via) 38%, var(--gradient-via-2) 67%, var(--gradient-to, var(--accent)) 95%);")
    elif "gradient-via" in colours:
        lines.append("  --stat-gradient: linear-gradient(100deg, var(--gradient-from, var(--accent)) 10%, "
                     "var(--gradient-via) 52%, var(--gradient-to, var(--accent)) 95%);")
    css += "\n:root {\n%s\n}\n" % "\n".join(lines)
    try:
        css += component_rules(data)
    except ValueError as e:
        raise DeckError("%s: %s" % (design, e))
    begin, end, _ = d2c.markers("deck-tokens")
    filled = d2c.inject(begin + "\n" + NEUTRAL_TOKENS + "\n" + end, css, "deck-tokens")
    return css_region("/* deck-preset: design */\n" + bridge_design().source_mark(design) + filled)


# components.slide-* in a DESIGN.md: how each text role of a slide is set, plus the
# layout around it, all opt-in. A design without them keeps the preset's quiet look.
# A text role takes a typography role ("{typography.h2}") and/or values directly:
# fontFamily (display, body, mono, label), fontWeight, fontSize (a length, vw for a
# size that scales with the slide, or clamp()), letterSpacing, lineHeight,
# textTransform, textColor (a colour role, resolved per mode). The rules carry
# `html .deck` so they win over the preset overrides and the engine; a colour the
# preset forces with !important is set with !important too.
SLIDE_ROLES = {
    "slide-display": (".slide__display",),
    "slide-subtitle": (".slide__subtitle",),
    "slide-heading": (".slide__heading",),
    "slide-label": (".slide__label", ".slide__result-label"),
    "slide-body": (".slide__body", ".slide__bullets li"),
    "slide-small": (".slide__stat-label", ".cheat-card__item", ".slide__numbered > li > :not(strong)",
                    ".data-table td", ".slide__body--sm"),
    "slide-subhead": (".slide h3",),
    "slide-item-title": (".slide__numbered > li > strong", ".cheat-card__title", ".slide h4"),
    "slide-result-value": (".slide__result-value",),
    "slide-stat": (".slide__stat-value",),
    "slide-table-head": (".data-table th",),
    "slide-quote": (".slide__quote p",),
    "slide-number": (".slide__numbered > li::before",),
}
TYPE_PROPS = {"fontWeight": "font-weight", "fontSize": "font-size", "letterSpacing": "letter-spacing",
              "lineHeight": "line-height", "textTransform": "text-transform"}
LENGTH = r"-?\d*\.?\d+(?:em|px|rem|vw|vh|%)"
TYPE_VALUE = {"fontWeight": re.compile(r"^(?:[1-9]\d{0,2}|1000|normal|bold)$"),
              "fontSize": re.compile(r"^(?:%s|clamp\(\s*%s\s*,\s*%s\s*,\s*%s\s*\))$" % (LENGTH, LENGTH, LENGTH, LENGTH)),
              "letterSpacing": re.compile(r"^-?\d*\.?\d+(em|px|rem|%)$|^0$|^normal$"),
              "lineHeight": re.compile(r"^\d*\.?\d+(em|px|rem|%)?$|^normal$"),
              "textTransform": re.compile(r"^(?:none|uppercase|lowercase|capitalize)$")}
FAMILIES = {"display": "var(--font-display)", "body": "var(--font-body)", "mono": "var(--font-mono)",
            "label": "var(--font-label, var(--font-mono))"}
TYPE_REF = re.compile(r"^\{typography\.([\w-]+)\}$")
COLOUR_REF = re.compile(r"^\{colors\.([\w-]+)\}$")
# what a plain number drops: the box, its ground and its border
PLAIN_NUMBER = ("background: none; border: 0; padding: 0; min-width: 0; text-align: left; "
                "color: var(--accent);")
CONTENT_SLIDES = ".slide:not(.slide--bleed):not(.slide--divider):not(.slide--title):not(.slide--split)"


def _colour(data: dict, where: str, ref) -> tuple[str, str]:
    m = COLOUR_REF.match(str(ref).strip())
    colors, dark = data.get("colors") or {}, data.get("colorsDark") or {}
    if not m or (m.group(1) not in colors and m.group(1) not in dark):
        raise ValueError('%s: %r must name a colour role of this design as "{colors.<role>}"' % (where, ref))
    role = m.group(1)
    if role not in colors:   # a role only the dark palette has holds in both modes
        return str(dark[role]), str(dark[role])
    return str(colors[role]), str(dark.get(role, colors.get("dark-" + role, colors[role])))


# A value that is CSS rather than one token (a gradient, a shadow, a border) may name
# parts of the design: {colors.<role>} becomes a custom property per mode, and
# {gradients.<name>}, {shadows.<name>}, {rounded.<name>}, {spacing.<name>} are put in
# as written there (and may name colours themselves).
DESIGN_REF = re.compile(r"\{(colors|gradients|shadows|rounded|spacing)\.([\w-]+)\}")
UNSAFE_CSS = re.compile(r"[;{}<>\\]|/\*|url\(|@import|expression\(", re.I)
CSS_LENGTH = r"-?\d*\.?\d+(?:em|px|rem|vw|vh|dvh|ch|%)"
ONE_LENGTH = re.compile(r"^(?:0|%s|clamp\(\s*%s\s*,\s*%s\s*,\s*%s\s*\))$" % ((CSS_LENGTH,) * 4))
COMPONENT_KEYS = {
    "slide-text": {"smoothing"},
    "slide-media": {"share", "gap"},
    "slide-bullet": {"marker", "style", "indent", "gap"},
    "slide-spacing": {"afterHeading", "labelToHeading", "betweenBlocks", "beforeHeading"},
    "plate": {"background", "border", "shadow", "backdropFilter", "rounded", "padding"},
    "toolbar": {"backgroundColor", "textColor", "typography", "padding", "border"},
    "button-present": {"background", "textColor", "fontWeight", "rounded", "padding"},
    "deck-view": {"backgroundColor", "gap", "slideShadow"},
}
SHARES = {"1/3": "33.333%", "2/5": "40%", "1/2": "50%", "4/15": "26.667%", "1/4": "25%"}
# role extras beside the text properties
ROLE_EXTRAS = {"slide-number": {"marker", "paint", "rule", "ruleWidth"},
               "slide-stat": {"gradient", "minWidth"},
               "slide-quote": {"bar", "barWidth", "maxWidth", "paddingStart"}}


class _Css:
    """Resolves design references in CSS values and collects the colour properties they need."""

    def __init__(self, data: dict):
        self.data, self.light, self.dark, self.seen = data, [], [], set()

    def colour_var(self, where: str, ref) -> str:
        light, dark = _colour(self.data, where, ref)
        name = COLOUR_REF.match(str(ref).strip()).group(1)
        var = "--cmp-c-%s" % name
        if var not in self.seen:
            self.seen.add(var)
            self.light.append("  %s: %s;" % (var, light))
            self.dark.append("  %s: %s;" % (var, dark))
        return "var(%s)" % var

    def value(self, where: str, raw) -> str:
        text = str(raw).strip()
        for _ in range(5):
            def sub(m):
                kind, name = m.groups()
                if kind == "colors":
                    return self.colour_var(where, m.group(0))
                block = self.data.get(kind) or {}
                if name not in block:
                    raise ValueError("%s: {%s.%s} names nothing in this design" % (where, kind, name))
                return str(block[name]).strip()
            new = DESIGN_REF.sub(sub, text)
            if new == text:
                break
            text = new
        if not text or DESIGN_REF.search(text) or UNSAFE_CSS.search(text) or "{" in text:
            raise ValueError("%s: %r is not a CSS value this generator writes" % (where, raw))
        return text

    def length(self, where: str, raw) -> str:
        val = str(raw).strip()
        if DESIGN_REF.fullmatch(val):
            val = self.value(where, val)
        if not ONE_LENGTH.match(val):
            raise ValueError("%s: %r is not a length" % (where, raw))
        return val


# components other generators read too: keys this one does not know are theirs
SHARED_COMPONENTS = {"plate", "toolbar", "button-present", "deck-view"}


def _keys(comps: dict, name: str) -> dict | None:
    entry = comps.get(name)
    if entry is None:
        return None
    if isinstance(entry, dict) and name in SHARED_COMPONENTS:
        return {k: v for k, v in entry.items() if k in COMPONENT_KEYS[name]}
    if not isinstance(entry, dict) or set(entry) - COMPONENT_KEYS[name]:
        raise ValueError("components.%s takes %s" % (name, ", ".join(sorted(COMPONENT_KEYS[name]))))
    return entry


def design_extras(data: dict, css: "_Css") -> list[str]:
    """Rules for the components beside the text roles: font smoothing, photo share,
    bullets, spacing, the result plate and the deck view. Each only when named."""
    comps = data.get("components") or {}
    rules = []
    text = _keys(comps, "slide-text")
    if text is not None and "smoothing" in text:
        if text["smoothing"] not in ("antialiased", "auto"):
            raise ValueError("components.slide-text.smoothing: %r is not antialiased or auto" % text["smoothing"])
        if text["smoothing"] == "antialiased":
            rules.append("html body { -webkit-font-smoothing: antialiased; -moz-osx-font-smoothing: grayscale; }")
    media = _keys(comps, "slide-media")
    if media is not None:
        if "share" in media:
            share = str(media["share"]).strip()
            share = SHARES.get(share, share)
            if not re.match(r"^\d+(\.\d+)?%$", share):
                raise ValueError("components.slide-media.share: %r is not %s or a percentage"
                                 % (media["share"], ", ".join(SHARES)))
            rules.append("html .deck .slide--media:not([data-media-size]) { --media-share: %s; }" % share)
        if "gap" in media:
            rules.append("html .deck .slide--media { --media-gap: %s; }" % css.length("components.slide-media.gap", media["gap"]))
    bullet = _keys(comps, "slide-bullet")
    if bullet is not None:
        style = str(bullet.get("style", "dot")).strip()
        if style not in ("dot", "disc"):
            raise ValueError("components.slide-bullet.style: %r is not dot or disc" % style)
        colour = css.colour_var("components.slide-bullet.marker", bullet["marker"]) if "marker" in bullet else None
        indent = css.length("components.slide-bullet.indent", bullet["indent"]) if "indent" in bullet else None
        if style == "disc":
            rules.append("html .deck .slide__bullets { list-style: disc outside; padding-left: %s; }" % (indent or "1.2em"))
            rules.append("html .deck .slide__bullets li { padding-left: 0.4em; }")
            rules.append("html .deck .slide__bullets li::before { content: none; display: none; }")
            if colour:
                rules.append("html .deck .slide__bullets li::marker { color: %s; }" % colour)
        else:
            if colour:
                rules.append("html .deck .slide__bullets li::before { background: %s; }" % colour)
            if indent:
                rules.append("html .deck .slide__bullets li { padding-left: %s; }" % indent)
        if "gap" in bullet:
            gap = css.length("components.slide-bullet.gap", bullet["gap"])
            rules.append("html .deck .slide__bullets li { padding-top: 0; padding-bottom: 0; }")
            rules.append("html .deck .slide__bullets li + li { margin-top: %s; }" % gap)
            if style == "dot":
                rules.append("html .deck .slide__bullets li::before { top: calc(0.75em - 3px); }")
    spacing = _keys(comps, "slide-spacing")
    if spacing is not None:
        flow = "html .deck :is(.slide, .slide__content, .slide__inner > div)"
        # positioned layers (photo, veil, top slot) are no blocks in the flow
        names = (("betweenBlocks", "--space-block",
                  flow + " > * + :not(.slide__bg, .slide__scrim, .slide__top, .slide__decor, .slide__media, .notes)"),
                 ("beforeHeading", "--space-before-heading", flow + " > * + :is(.slide__heading, h3, h4)"),
                 ("afterHeading", "--space-after-heading", flow + " > .slide__heading + *"),
                 ("labelToHeading", "--space-label-heading", flow + " > .slide__label + *"))
        props = [(var, css.length("components.slide-spacing.%s" % key, spacing[key]), sel)
                 for key, var, sel in names if key in spacing]
        if props:
            rules.append(":root { %s }" % " ".join("%s: %s;" % (v, val) for v, val, _ in props))
            if "labelToHeading" in spacing:
                rules.append("html .deck .slide .slide__label { margin-bottom: 0; }")
            rules += ["%s { margin-top: var(%s); }" % (sel, v) for v, _, sel in props]
    plate = _keys(comps, "plate")
    if plate is not None:
        decls = []
        for key, prop in (("background", "background"), ("border", "border"), ("shadow", "box-shadow"),
                          ("rounded", "border-radius"), ("padding", "padding")):
            if key in plate:
                decls.append("%s: %s;" % (prop, css.value("components.plate.%s" % key, plate[key])))
        if "backdropFilter" in plate:
            v = css.value("components.plate.backdropFilter", plate["backdropFilter"])
            decls.append("-webkit-backdrop-filter: %s; backdrop-filter: %s;" % (v, v))
        if decls:
            # the design preset drops blur and shadow outside .fx (0,6,0); a plate the
            # design asks for outranks that
            rules.append(":root:not(.cmp) .deck:not(.cmp) .slide:not(.cmp) .slide__result:not(.cmp) { %s }" % " ".join(decls))
    view = []
    bar = _keys(comps, "toolbar")
    if bar is not None:
        decls = []
        if "backgroundColor" in bar:
            decls.append("background: %s;" % css.value("components.toolbar.backgroundColor", bar["backgroundColor"]))
        if "textColor" in bar:
            decls.append("color: %s;" % css.value("components.toolbar.textColor", bar["textColor"]))
        if "padding" in bar:
            decls.append("padding: %s;" % css.value("components.toolbar.padding", bar["padding"]))
        if "border" in bar:
            decls.append("border-bottom: %s;" % css.value("components.toolbar.border", bar["border"]))
        if decls:
            view.append("html:root.deck-view .deck-view-bar { %s }" % " ".join(decls))
        if "typography" in bar:
            m = TYPE_REF.match(str(bar["typography"]).strip())
            spec = (data.get("typography") or {}).get(m.group(1)) if m else None
            if not isinstance(spec, dict):
                raise ValueError("components.toolbar.typography: %r names no typography role of this design" % bar["typography"])
            tdecls = ["%s: %s;" % (prop, str(spec[key]).strip()) for key, prop in TYPE_PROPS.items()
                      if key in spec and TYPE_VALUE[key].match(str(spec[key]).strip())]
            if tdecls:
                view.append("html .deck-view-bar .deck-view-title { %s }" % " ".join(tdecls))
    btn = _keys(comps, "button-present")
    if btn is not None:
        decls = []
        for key, prop in (("background", "background"), ("textColor", "color"), ("rounded", "border-radius"),
                          ("padding", "padding")):
            if key in btn:
                decls.append("%s: %s;" % (prop, css.value("components.button-present.%s" % key, btn[key])))
        if "fontWeight" in btn:
            fw = str(btn["fontWeight"]).strip()
            if not TYPE_VALUE["fontWeight"].match(fw):
                raise ValueError("components.button-present.fontWeight: %r is not a font weight" % fw)
            decls.append("font-weight: %s;" % fw)
        if "background" in btn:
            decls.append("border-color: transparent;")
        if decls:
            body = " ".join(decls)
            view.append("html .deck-view-bar .deck-view-present, html .deck-view-bar .deck-view-present:hover, "
                        "html .deck-view-bar .deck-view-present:focus-visible { %s }" % body)
    dv = _keys(comps, "deck-view")
    if dv is not None:
        if "backgroundColor" in dv:
            view.append("html:root.deck-view body { background: %s; }" % css.value("components.deck-view.backgroundColor", dv["backgroundColor"]))
        if "gap" in dv:
            view.append(":root.deck-view { --deck-view-gap: %s; }" % css.length("components.deck-view.gap", dv["gap"]))
        if "slideShadow" in dv:
            view.append("html:root.deck-view .deck .slide { box-shadow: %s; }" % css.value("components.deck-view.slideShadow", dv["slideShadow"]))
    if view:
        rules.append("@media screen {\n  %s\n}" % "\n  ".join(view))
    return rules


def role_extras(name: str, entry: dict, css: "_Css") -> list[str]:
    """The keys of a text role beyond type: paint and rule of the numbers, the gradient
    and width of a big number, the bar and measure of a quote."""
    rules = []
    if name == "slide-number":
        if "paint" in entry:
            if entry["paint"] not in ("gradient", "plain"):
                raise ValueError("components.slide-number.paint: %r is not gradient or plain" % entry["paint"])
            if entry["paint"] == "gradient":
                rules.append("html .deck .slide__numbered > li::before { background-image: var(--stat-gradient, "
                             "linear-gradient(100deg, var(--gradient-from, var(--accent)) 10%, var(--gradient-to, "
                             "color-mix(in oklab, var(--accent) 55%, var(--text))) 95%)); -webkit-background-clip: text; "
                             "background-clip: text; -webkit-text-fill-color: transparent; }")
        if "rule" in entry:
            rules.append(".slide__numbered { --number-rule: %s; }" % css.colour_var("components.slide-number.rule", entry["rule"]))
        if "ruleWidth" in entry:
            rules.append(".slide__numbered { --number-rule-width: %s; }" % css.length("components.slide-number.ruleWidth", entry["ruleWidth"]))
    if name == "slide-stat":
        if "gradient" in entry:
            rules.append(":root { --stat-gradient: %s; }" % css.value("components.slide-stat.gradient", entry["gradient"]))
        if "minWidth" in entry:
            rules.append("html .deck .slide__stat-value { min-width: min(100%%, %s); }"
                         % css.length("components.slide-stat.minWidth", entry["minWidth"]))
    if name == "slide-quote":
        if "bar" in entry:
            width = css.length("components.slide-quote.barWidth", entry.get("barWidth", "3px"))
            rules.append("html .deck .slide__quote { position: relative; border-left: 0; }")
            rules.append("html .deck .slide__quote::before { content: ''; position: absolute; left: 0; top: 0; bottom: 0; "
                         "width: %s; border-radius: %s; background: %s; }"
                         % (width, width, css.value("components.slide-quote.bar", entry["bar"])))
        elif "barWidth" in entry:
            rules.append("html .deck .slide__quote { border-left-width: %s; }" % css.length("components.slide-quote.barWidth", entry["barWidth"]))
        if "maxWidth" in entry:
            mw = css.length("components.slide-quote.maxWidth", entry["maxWidth"])
            rules.append("html .deck .slide__quote, html .deck .slide__quote p { max-width: %s; }" % mw)
        if "paddingStart" in entry:
            rules.append("html .deck .slide__quote { padding-left: %s; }" % css.length("components.slide-quote.paddingStart", entry["paddingStart"]))
    return rules


def component_rules(data: dict) -> str:
    """CSS for components.slide-* of a design, or '' without them."""
    comps = data.get("components") or {}
    typography = data.get("typography") or {}
    rules, light_vars, dark_vars = [], [], []
    css = _Css(data)
    for name, selectors in SLIDE_ROLES.items():
        entry = comps.get(name)
        if entry is None:
            continue
        if not isinstance(entry, dict):
            raise ValueError("components.%s must be a mapping" % name)
        known = {"typography", "fontFamily", "textColor", *TYPE_PROPS} | ROLE_EXTRAS.get(name, set())
        for key in entry:
            if key not in known:
                raise ValueError("components.%s.%s: unknown key; known: %s" % (name, key, ", ".join(sorted(known))))
        spec = {}
        if "typography" in entry:
            m = TYPE_REF.match(str(entry["typography"]).strip())
            if not m or not isinstance(typography.get(m.group(1)), dict):
                raise ValueError("components.%s.typography: %r names no typography role of this design"
                                 % (name, entry["typography"]))
            spec.update({k: v for k, v in typography[m.group(1)].items() if k in ("fontWeight", "letterSpacing", "lineHeight")})
        spec.update({k: v for k, v in entry.items() if k in TYPE_PROPS})
        decls = []
        if name == "slide-number" and "marker" in entry:
            if entry["marker"] not in ("plain", "box"):
                raise ValueError("components.slide-number.marker: %r is not plain or box" % entry["marker"])
            if entry["marker"] == "plain":
                decls.append(PLAIN_NUMBER)
        if "fontFamily" in entry:
            fam = str(entry["fontFamily"]).strip()
            if fam not in FAMILIES:
                raise ValueError("components.%s.fontFamily: %r is not one of %s" % (name, fam, ", ".join(FAMILIES)))
            decls.append("font-family: %s;" % FAMILIES[fam])
        for key, prop in TYPE_PROPS.items():
            if key in spec:
                val = str(spec[key]).strip()
                if not TYPE_VALUE[key].match(val):
                    raise ValueError("components.%s.%s: %r is not a %s value" % (name, key, val, prop))
                decls.append("%s: %s;" % (prop, val))
        if "textColor" in entry:
            light, dark = _colour(data, "components.%s.textColor" % name, entry["textColor"])
            var = "--cmp-%s-color" % name
            light_vars.append("  %s: %s;" % (var, light))
            dark_vars.append("  %s: %s;" % (var, dark))
            # the preset forces label and heading colours with a long !important chain;
            # this selector outranks it (0,8,0) without touching the preset
            colour_rule = ":root:not(.cmp) .deck:not(.cmp) .slide:not(.cmp) :is(%s):not(.cmp) { color: var(%s) !important; }" % (
                ", ".join(s for s in selectors if "::" not in s), var)
            rules.append(colour_rule)
        if decls:
            rules.append("html .deck :is(%s) { %s }" % (", ".join(s for s in selectors if "::" not in s), " ".join(decls))
                         if not any("::" in s for s in selectors)
                         else "html .deck %s { %s }" % (selectors[0], " ".join(decls)))
        if name == "slide-body" and "fontSize" in spec:
            # the bullet dot sits on the first line whatever the size
            rules.append("html .deck .slide__bullets li::before { top: calc(10px + 0.7em - 3px); }")
        rules += role_extras(name, entry, css)
    layout = comps.get("slide-layout")
    if layout is not None:
        if not isinstance(layout, dict) or set(layout) - {"align", "paddingTop", "paddingX"}:
            raise ValueError("components.slide-layout takes align, paddingTop and paddingX")
        if "paddingX" in layout:
            px_ = str(layout["paddingX"]).strip()
            if not re.match("^%s$" % LENGTH, px_):
                raise ValueError("components.slide-layout.paddingX: %r is not a length" % px_)
            # a photo slide keeps the room for its photo on the photo side
            rules.append("html .deck %s:not(.slide--media) { padding-left: %s; padding-right: %s; }" % (CONTENT_SLIDES, px_, px_))
            rules.append('html .deck .slide.slide--media:not([data-media="left"]) { padding-left: %s; }' % px_)
            rules.append('html .deck .slide.slide--media[data-media="left"] { padding-right: %s; }' % px_)
            rules.append("html .deck .slide--bleed .slide__content { padding-left: %s; padding-right: %s; }" % (px_, px_))
        align = str(layout.get("align", "center")).strip()
        if align not in ("top", "center"):
            raise ValueError("components.slide-layout.align: %r is not top or center" % align)
        if align == "top":
            pad = str(layout.get("paddingTop", "")).strip()
            if pad and not re.match("^%s$" % LENGTH, pad):
                raise ValueError("components.slide-layout.paddingTop: %r is not a length" % pad)
            rules.append("html .deck %s { justify-content: flex-start;%s }"
                         % (CONTENT_SLIDES, " padding-top: %s;" % pad if pad else ""))
            rules.append("html .deck .slide--content .slide__inner { align-items: start; }")
            rules.append("html .deck .slide__aside { align-items: flex-start; }")
    arc = comps.get("slide-arc")
    if arc is not None:
        if not isinstance(arc, dict) or set(arc) - {"width", "span", "baseline", "height", "fade", "glow"}:
            raise ValueError("components.slide-arc takes width, span, baseline, height, fade and glow")
        if "height" in arc:
            rules.append(":root { --arc-height: %s; }" % css.length("components.slide-arc.height", arc["height"]))
        if "fade" in arc:
            fade = str(arc["fade"]).strip()
            if not re.match(r"^\d+(\.\d+)?%$", fade) or float(fade[:-1]) > 50:
                raise ValueError("components.slide-arc.fade: %r is not a percentage up to 50%%" % arc["fade"])
            rules.append(":root { --arc-fade: %s; }" % fade)
        if "glow" in arc:
            parts = str(arc["glow"]).split()
            if len(parts) != 2:
                raise ValueError("components.slide-arc.glow: %r is not two lengths (inner, outer)" % arc["glow"])
            rules.append(":root { --arc-glow-inner: %s; --arc-glow-outer: %s; }"
                         % tuple(css.length("components.slide-arc.glow", x) for x in parts))
        if "width" in arc:
            width = str(arc["width"]).strip()
            if not re.match(r"^\d*\.?\d+px$", width):
                raise ValueError("components.slide-arc.width: %r is not a width in px" % width)
            rules.append(":root { --arc-width: %s; }" % width)
        if "span" in arc:
            span = str(arc["span"]).strip()
            if not re.match("^%s$" % LENGTH, span):
                raise ValueError("components.slide-arc.span: %r is not a length" % span)
            rules.append("html .deck .slide__arc { width: %s; max-width: 100%%; }" % span)
        if "baseline" in arc:
            light, dark = _colour(data, "components.slide-arc.baseline", arc["baseline"])
            light_vars.append("  --arc-base: %s;" % light)
            dark_vars.append("  --arc-base: %s;" % dark)
            rules.append("html .deck .slide__arc::after { content: ''; position: absolute; left: 0; right: 0; "
                         "top: 50%; height: 1px; background: var(--arc-base); }")
    bleed = comps.get("slide-bleed")
    if bleed is not None:
        if not isinstance(bleed, dict) or set(bleed) - {"veil", "dim", "padding", "textColor"}:
            raise ValueError("components.slide-bleed takes veil, dim, padding and textColor")
        if "padding" in bleed:
            parts = str(bleed["padding"]).split()
            if not 1 <= len(parts) <= 3:
                raise ValueError("components.slide-bleed.padding: %r is one to three lengths (top, sides, bottom)"
                                 % bleed["padding"])
            vals = [css.length("components.slide-bleed.padding", x) for x in parts]
            top, side, bottom = (vals * 3)[:3] if len(vals) == 1 else (vals[0], vals[1], vals[-1 if len(vals) == 3 else 0])
            rules.append("html .deck .slide--bleed > .slide__top { padding: %s %s 0; }" % (top, side))
            rules.append("html .deck .slide--bleed .slide__content { padding: %s %s %s; }" % (top, side, bottom))
        if "textColor" in bleed:
            light, dark = _colour(data, "components.slide-bleed.textColor", bleed["textColor"])
            light_vars.append("  --cmp-bleed-color: %s;" % light)
            dark_vars.append("  --cmp-bleed-color: %s;" % dark)
            rules.append(":root:not(.cmp) .deck:not(.cmp) .slide.slide--bleed:not(.cmp) :is(.slide__content, .slide__top) "
                         ":is(p, h1, h2, h3, h4, li, span, strong, .slide__label, .slide__display, .slide__heading, "
                         ".slide__subtitle, .slide__body):not(.cmp) { color: var(--cmp-bleed-color) !important; }")
        if "dim" in bleed:
            dim = bleed["dim"]
            if isinstance(dim, bool) or not isinstance(dim, (int, float)) or not 0 < dim <= 1:
                raise ValueError("components.slide-bleed.dim: %r is not a brightness from 0 to 1" % dim)
            # dark mode: the photo is darkened neutrally, as a presentation tool does, instead
            # of veiled in the ground colour, which tints it; light mode keeps its veil
            rules.append(".theme-dark .deck .slide--bleed .slide__bg { filter: brightness(%g); }" % dim)
            rules.append(".theme-dark .deck .slide--bleed .slide__scrim { background: none; }")
            rules.append(".theme-dark .deck .slide--bleed .slide__content::before { background: none; }")
        if "veil" not in bleed:
            veil = None
        else:
            veil = bleed.get("veil")
        if veil is not None and (isinstance(veil, bool) or not isinstance(veil, (int, float)) or not 0 <= veil <= 100):
            raise ValueError("components.slide-bleed.veil: %r is not a percentage from 0 to 100" % veil)
        if veil is not None:
          rules.append("html .deck .slide--bleed .slide__content::before { background: linear-gradient(to top, "
                     "color-mix(in srgb, var(--bg) %g%%, transparent) 0%%, color-mix(in srgb, var(--bg) %g%%, "
                     "transparent) 55%%, transparent 100%%); }" % (veil, veil * 0.6))
          rules.append("html .deck .slide--bleed .slide__scrim { opacity: %g; }" % (veil / 100))
    rules += design_extras(data, css)
    light_vars += css.light
    dark_vars += css.dark
    if not rules:
        return ""
    out = "\n/* design-components: from components.slide-* in the design */\n"
    if light_vars:
        out += ":root, .theme-light {\n%s\n}\n.theme-dark {\n%s\n}\n" % ("\n".join(light_vars), "\n".join(dark_vars))
    return out + "\n".join(rules) + "\n"


def design_families(preset: dict, design: Path) -> dict[str, list[int]]:
    ef = embed_fonts()
    families = {f: set(w) for f, w in ef.collect_families(design).items()}
    typography = design_to_css().frontmatter(design).get("typography") or {}
    for spec in (preset.get("fonts") or {}).values():
        if not isinstance(spec, dict):
            continue
        for role in spec.get("roles") or []:
            fam = str((typography.get(role) or {}).get("fontFamily") or "")
            first = fam.split(",")[0].strip().strip("'\"").strip()
            if not first:
                continue
            if first in families or (first.lower() not in ef.SYSTEM_FAMILIES and first.lower() not in ef.GENERIC):
                families.setdefault(first, set()).update(int(w) for w in spec.get("weights") or [])
            break
    return {f: sorted(ws or {400}) for f, ws in families.items()}


def fonts_region(slug: str, preset: dict, design: Path | None, embed: bool) -> str:
    if not embed:
        return "\n" + NO_FONTS + "\n"
    ff = font_face()
    if is_design(preset):
        roles = list(design_families(preset, design).items())
    else:
        roles = ff.collect_roles(preset)
    if not roles:
        return "\n" + SYSTEM_FONTS + "\n"
    return "\n" + ff.font_face_block(roles) + "\n"


def region_contents(names, slug, preset, design, embed, blocks=()) -> dict[str, str]:
    out: dict[str, str] = {}
    for name in names:
        if name == "deck-prepaint":
            out[name] = PREPAINT
        elif name == "deck-fonts":
            out[name] = fonts_region(slug, preset, design, embed)
        elif name == "deck-tokens":
            out[name] = design_tokens(preset, design) if is_design(preset) else style_tokens(slug, preset)
        elif name == "deck-preset-css":
            out[name] = css_region(preset.get("css_overrides") or "")
        elif name == "slide-engine:css":
            out[name] = css_region(read_asset("slide-engine.css"))
        elif name == "slide-engine:js":
            out[name] = script_region(read_asset("slide-engine.js"))
        elif name == "slide-stage:css":
            out[name] = css_region(read_asset("slide-stage.css"))
        elif name == "slide-stage:js":
            out[name] = script_region(read_asset("slide-stage.js"))
        elif name == BLOCKS_CSS:
            out[name] = blocks_css(list(blocks), preset)
        elif name == BLOCKS_JS:
            out[name] = js_region(blocks_js(list(blocks)))
        elif name.startswith(MODULE_PREFIX):
            out[name] = module_region(name[len(MODULE_PREFIX):])
    return out


# --- html-canvas section blocks ------------------------------------------------------------

# Blocks a deck answers in its own way: asked for by name they are refused, `all` leaves
# them out. The engine owns navigation, the overview and print.
DECK_REFUSED = {
    "hero": "the title slide (slide type 1) opens a deck",
    "section-opener": "its rule restyles every <section>, so every slide; a divider slide (type 2) opens a section",
    "section-nav": "the deck navigates by its keys, dots and counter",
    "toc": "an overview slide (type 10) is the deck's table of contents",
    "index": "an overview slide (type 10) links the slides",
    "print": "the engine prints one slide per page",
}
# Required by a block on a page, never spliced into a deck: the canvas animation layer
# brings its own .reveal, which would fight the engine's; the motion module moves a
# deck's message flow instead.
DECK_DROPPED = {"animations"}
NEEDS_MOTION = {"message-flow"}

# The canvas token names a block reads, on the deck tokens. On :root for what lives
# outside a slide (the glossary popover), on .slide so a slide's own tokens carry over.
ALIASES = """\
/* canvas tokens on deck tokens: html-canvas blocks read the names on the left */
:root, .slide {
  --ink: var(--text); --on-surface: var(--text); --muted: var(--text-dim);
  --raised: var(--surface); --surface-subtle: var(--surface); --surface-muted: var(--surface2);
  --line: var(--border); --line-subtle: var(--border); --line-strong: var(--border-bright);
  --accent-text: var(--accent); --accent-line: var(--accent);
  --accent-soft: var(--accent-dim); --accent-subtle: var(--accent-dim);
  --secondary: var(--accent);
  --ok: var(--green); --ok-text: var(--green); --warn: var(--amber); --danger: var(--red); --info: var(--cyan);
  --radius-sm: 4px; --radius-md: 6px; --radius-lg: 10px; --radius-full: 9999px;
  --shadow-soft: none;
  --shadow-hover: 0 8px 20px -6px color-mix(in srgb, var(--text) 18%, transparent);
{style}}"""
# A style preset names no heading colour and no text on a fill; the design preset does.
STYLE_ALIASES = "  --heading: var(--text); --on-primary: var(--bg);\n"

# A block on a 16:9 slide: no page margins, nothing wider than the slide.
DECK_FIT = """\
/* deck fit: a block on a slide */
.slide .blk { margin: 0; width: 100%; min-width: 0; }
.slide .blk + .blk, .slide .slide__label + .blk { margin-top: clamp(12px, 2.4vh, 24px); }
.slide .tbl-wrap table { min-width: 0; }
.slide .diagram svg { min-width: 0; }
.slide .glossary { border: 0; padding: 0; }
/* code on the deck's code ground: its text colour, accents lifted toward it */
.slide .term-body { color: var(--code-text); }
.slide .term-body .pr { color: color-mix(in srgb, var(--accent) 45%, var(--code-text)); }
.slide .term-body .ok { color: color-mix(in srgb, var(--green) 45%, var(--code-text)); }
/* a decision page is a page: on a slide it closes up (split it over two slides when it grows) */
.slide .decision { gap: clamp(8px, 1.8vh, 18px); }
.slide .decision h3 { margin: 0; }
.slide .dec-opt { padding: 10px 14px; gap: 4px 12px; }
.slide .decision th, .slide .decision td { padding: 6px 12px; }
.slide .decision .note { margin: 0; padding: 10px 16px; }
.slide .dec-open { gap: 2px; }"""


def new_page():
    return module("html_canvas_new_page", CANVAS_SCRIPTS / "new-page.py")


def block_catalog() -> list[str]:
    return new_page().catalog()


def parse_blocks(raw: str | None) -> list[str]:
    """--blocks a,b or `all`: names checked against the catalog and the deck, each once."""
    if not raw:
        return []
    names = block_catalog()
    wanted = [b for b in re.split(r"[,\s]+", raw.strip()) if b]
    if wanted == ["all"]:
        left = [b for b in names if b in DECK_REFUSED]
        if left:
            print("new-deck: --blocks all leaves out what a deck answers itself: %s" % ", ".join(left),
                  file=sys.stderr)
        return [b for b in names if b not in DECK_REFUSED]
    unknown = [b for b in wanted if b not in names]
    if unknown:
        raise DeckError("unknown block(s): %s (see --list)" % ", ".join(unknown))
    refused = [b for b in wanted if b in DECK_REFUSED]
    if refused:
        raise DeckError("not in a deck: %s" % "; ".join("%s (%s)" % (b, DECK_REFUSED[b]) for b in refused))
    return list(dict.fromkeys(wanted))


def resolve_blocks(blocks: list[str]) -> list[str]:
    """The blocks with what they require, dependencies first (html-canvas new-page.py)."""
    try:
        order = new_page().resolve(blocks)
    except SystemExit:
        raise DeckError("html-canvas sections.css does not hold every block it requires")
    return [b for b in order if b not in DECK_DROPPED]


def blocks_css(blocks: list[str], preset: dict) -> str:
    table = new_page().css_blocks()
    parts = ["/* blocks: %s */" % ", ".join(blocks), ALIASES.replace("{style}", "" if is_design(preset) else STYLE_ALIASES)]
    parts += [table[b][1] for b in resolve_blocks(blocks)]
    parts.append(DECK_FIT)
    css = "\n\n".join(parts)
    if "</style" in css.lower():
        raise DeckError("html-canvas sections.css contains </style>, which would end its element early")
    return css_region(css)


def blocks_js(blocks: list[str]) -> str:
    table = new_page().js_blocks()
    body = "\n\n".join(table[b] for b in resolve_blocks(blocks) if b in table)
    if "</script" in body.lower():
        raise DeckError("html-canvas sections.js contains </script>, which would end its element early")
    return body


def js_region(body: str) -> str:
    return script_region(body) if body else "\n"


def recorded_blocks(html: str) -> list[str] | None:
    pos = span(html, BLOCKS_CSS)
    m = BLOCKS_LINE_RE.search(html[pos[0]:pos[1]]) if pos else None
    return [b for b in re.split(r",\s*", m.group(1)) if b] if m else None


def block_label(name: str) -> str:
    de, en = new_page().LABELS.get(name, (name, name))
    return "<span data-de>%s</span><span data-en>%s</span>" % (de, en)


def block_slides(blocks: list[str]) -> str:
    """One sample slide per block: its catalog markup under a label, marked data-sample."""
    np_ = new_page()
    out = []
    for b in [x for x in blocks if x not in np_.LAST_BLOCKS] + [x for x in blocks if x in np_.LAST_BLOCKS]:
        try:
            markup = np_.markup(b)
        except SystemExit:
            raise DeckError("html-canvas sections.md has no example for block %s" % b)
        if not markup:
            continue
        out.append('<section class="slide slide--content" data-sample>\n'
                   '  <p class="slide__label">%s</p>\n'
                   '  <div class="blk" id="blk-%s">\n%s\n  </div>\n</section>'
                   % (block_label(b), b, np_.unescape_symbols(markup)))
    return "\n".join(out)


# --- deck modules --------------------------------------------------------------------------

def available_modules(root: Path = MODULES) -> list[str]:
    return sorted(p.stem for p in root.glob("*.js") if MODULE_NAME_RE.match(p.stem)) if root.is_dir() else []


def module_region_name(name: str) -> str:
    return MODULE_PREFIX + name


def module_region(name: str, root: Path = MODULES) -> str:
    """One module: its stylesheet in an own <style> (no marker inside CSS), then its script."""
    js = root / ("%s.js" % name)
    if not MODULE_NAME_RE.match(name) or not js.is_file():
        raise DeckError("unknown module %r (available: %s)"
                        % (name, ", ".join(available_modules(root)) or "none"))
    css = js.with_suffix(".css")
    out = "\n"
    for path, closing in ((css, "</style"), (js, "</script")):
        if path.is_file() and closing in path.read_text(encoding="utf-8").lower():
            raise DeckError("modules/%s contains %s>, which would end its element early" % (path.name, closing))
    if css.is_file():
        text = css.read_text(encoding="utf-8")
        out += "<style>\n" + text + ("" if text.endswith("\n") else "\n") + "</style>\n"
    return out + "<script>\n" + js.read_text(encoding="utf-8") + "\n</script>\n"


def resolve_modules(requested: list[str]) -> list[str]:
    """--with values: names or `all`, unknown names refused, each once, sorted."""
    known = available_modules()
    names: set[str] = set()
    for item in requested or []:
        if item == "all":
            names.update(known)
        elif item in known:
            names.add(item)
        else:
            raise DeckError("unknown module %r (available: %s)" % (item, ", ".join(known) or "none"))
    return sorted(names)


def region_order(names) -> list[str]:
    """Document order of the given region names: fixed regions first, modules after, by name."""
    fixed = [n for n, _ in REGIONS if n in names]
    return fixed + sorted(n for n in names if n.startswith(MODULE_PREFIX))


# --- markers -------------------------------------------------------------------------------

def marks(name: str) -> tuple[str, str]:
    return "<!-- %s:start -->" % name, "<!-- %s:end -->" % name


def span(html: str, name: str) -> tuple[int, int] | None:
    """(content start, content end) of a region, None when absent; raises when malformed."""
    start, end = marks(name)
    ns, ne = html.count(start), html.count(end)
    if ns == 0 and ne == 0:
        return None
    if ns != 1 or ne != 1:
        raise DeckError("region %s needs exactly one start and one end marker (found %d and %d)" % (name, ns, ne))
    a, b = html.index(start), html.index(end)
    if b < a:
        raise DeckError("region %s ends before it starts" % name)
    return a + len(start), b


def splice(html: str, contents: dict[str, str]) -> str:
    for name, content in contents.items():
        pos = span(html, name)
        if pos is None:
            raise DeckError("region %s is missing" % name)
        html = html[:pos[0]] + content + html[pos[1]:]
    return html


def verify(html: str, contents: dict[str, str], order: list[str] | None = None) -> None:
    """Read every splice back: present once, in order, holding exactly what was meant.

    A build checks the order it writes; a refresh passes the order the deck already
    has, since module order is behaviour (key priority, transition nesting)."""
    last = -1
    for name in (order or region_order(contents)):
        pos = span(html, name)
        if pos is None:
            raise DeckError("verify: region %s is missing after the splice" % name)
        if html[pos[0]:pos[1]] != contents[name]:
            raise DeckError("verify: region %s does not hold what was spliced" % name)
        if pos[0] < last:
            raise DeckError("verify: region %s is out of order" % name)
        last = pos[0]


# --- build and refresh ---------------------------------------------------------------------

DECK_ATTR_RE = re.compile(r"^(data-[a-z0-9][a-z0-9-]*)=(.*)$", re.S)


def deck_attrs(items: list[str]) -> str:
    """--deck-attr NAME=VALUE pairs as attribute text for the deck element (engine options)."""
    out = []
    for item in items or []:
        m = DECK_ATTR_RE.match(item)
        if not m:
            raise DeckError("--deck-attr takes data-NAME=VALUE (an engine option such as "
                            "data-tracks-default=short), got %r" % item)
        out.append(' %s="%s"' % (m.group(1), html_mod.escape(m.group(2), quote=True)))
    return "".join(out)


def skeleton(title: str, lang: str, slides: str, stage: bool, attrs: str = "", modules=(),
             blocks: bool = False, block_js: bool = False, theme_default: str | None = None) -> str:
    def r(name: str) -> str:
        s, e = marks(name)
        return s + e
    style = [r("deck-tokens"), r("slide-engine:css"), r("deck-preset-css")]
    if blocks:
        style.append(r(BLOCKS_CSS))
    body_end = [r("slide-engine:js")]
    if stage:
        style.append(r("slide-stage:css"))
        body_end.append(r("slide-stage:js"))
    if block_js:
        body_end.append(r(BLOCKS_JS))
    body_end.extend(r(module_region_name(m)) for m in modules)
    return "\n".join([
        "<!DOCTYPE html>",
        '<html lang="%s"%s>' % (lang, ' data-theme-default="%s"' % theme_default if theme_default else ""),
        "<head>",
        '<meta charset="UTF-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1.0">',
        "<title>%s</title>" % html_mod.escape(title, quote=False),
        r("deck-prepaint"),
        r("deck-fonts"),
        "<style>",
        *style,
        "</style>",
        "</head>",
        "<body>",
        '<div class="deck"%s>' % attrs,
        slides.strip("\n"),
        "</div>",
        *body_end,
        "</body>",
        "</html>",
        "",
    ])


def title_slide(title: str, title_de: str | None = None, title_en: str | None = None) -> str:
    text = html_mod.escape(title, quote=False)
    if title_de or title_en:
        text = "<span data-de>%s</span><span data-en>%s</span>" % (
            html_mod.escape(title_de or title, quote=False), html_mod.escape(title_en or title, quote=False))
    return ('<section class="slide slide--title">\n  <div class="slide__content">\n'
            '    <h1 class="slide__display reveal">%s</h1>\n  </div>\n</section>' % text)


def named_design(design_arg: str | None, context: str | None, persona: str | None, anchor: Path) -> Path | None:
    """The design --design, --context or --persona names, else the one found above `anchor`."""
    try:
        if design_arg:
            design = bridge_design().resolve(design_arg)
        elif context or persona:
            design = bridge_design().resolve(context=context, persona=persona, target=anchor, fallback=False)
        else:
            return find_design(anchor)
    except ValueError as e:
        raise DeckError(str(e))
    if design is not None and not design.is_file():
        raise DeckError("--design: %s not found" % design)
    return design


def choose_preset(slug: str | None, design_arg: str | None, anchor: Path, context: str | None = None,
                  persona: str | None = None, design: Path | None = None) -> tuple[str, dict, Path | None]:
    design = design or named_design(design_arg, context, persona, anchor)
    slug = slug or ("design" if design else default_style_slug())
    preset = load_preset(slug)
    if is_design(preset) and not design:
        raise DeckError("preset %s takes its colours from DESIGN.md, and none was found above %s; "
                        "pass --design or pick a style preset" % (slug, anchor))
    return slug, preset, design


def deck_title(args) -> str:
    title = args.title or (args.title_de if args.lang == "de" else args.title_en) or args.title_en or args.title_de
    if not title:
        raise DeckError("a new deck needs --title (or --title-de / --title-en) and --out (or use --refresh DECK)")
    if args.lang == "de" and args.title_de:
        return args.title_de
    if args.lang == "en" and args.title_en:
        return args.title_en
    return title


def design_default_mode(slug: str, design: Path | None) -> str | None:
    """defaultMode: light|dark of the design a deck wears, the default for --theme-default."""
    if slug != "design" or design is None:
        return None
    mode = design_to_css().frontmatter(design).get("defaultMode")
    if mode is None:
        return None
    if mode not in ("light", "dark"):
        raise DeckError("%s: defaultMode %r is not light or dark" % (design, mode))
    return mode


def build(args) -> int:
    title = deck_title(args)
    if not args.out:
        raise DeckError("a new deck needs --title and --out (or use --refresh DECK)")
    out = Path(args.out)
    if out.exists() and not args.force:
        raise DeckError("%s exists; pass --force to overwrite it, or --refresh it" % out)
    blocks = parse_blocks(args.blocks)
    if args.slides:
        slides = Path(args.slides).read_text(encoding="utf-8")
        if not SLIDE_RE.search(slides):
            raise DeckError("%s holds no <section class=\"slide ...\"> element" % args.slides)
    else:
        slides = title_slide(args.title or title, args.title_de, args.title_en)
        if blocks:
            slides += "\n" + block_slides(blocks)
    attrs = deck_attrs(args.deck_attr)
    slug, preset, design = choose_preset(args.preset, args.design, out.resolve().parent, args.context, args.persona)
    theme_default = args.theme_default or design_default_mode(slug, design)

    requested = list(args.with_modules)
    if NEEDS_MOTION & set(blocks) and "motion" in available_modules() and "motion" not in resolve_modules(requested):
        print("new-deck: %s moves with the motion module; added --with motion"
              % ", ".join(sorted(NEEDS_MOTION & set(blocks))), file=sys.stderr)
        requested.append("motion")
    modules = resolve_modules(requested)
    block_js = bool(blocks) and bool(blocks_js(blocks))
    names = [name for name, _ in REGIONS
             if (args.with_stage or name not in STAGE_REGIONS)
             and (name != BLOCKS_CSS or blocks) and (name != BLOCKS_JS or block_js)]
    names += [module_region_name(m) for m in modules]
    contents = region_contents(names, slug, preset, design, not args.no_embed_fonts, blocks)
    html = splice(skeleton(title, args.lang, slides, args.with_stage, attrs, modules, bool(blocks), block_js,
                          theme_default),
                  contents)
    verify(html, contents)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    report(out, slug, design, html)
    return gate(out, design, args)


def add_block_js_region(html: str) -> str:
    """An empty deck-blocks:js region after the engine (and stage) script, for a refresh
    whose new block set needs a script the old one did not."""
    anchor = None
    for name in ("slide-stage:js", "slide-engine:js"):
        if span(html, name) is not None:
            anchor = marks(name)[1]
            break
    if anchor is None:
        raise DeckError("the deck has no engine script region to place the block scripts after")
    s, e = marks(BLOCKS_JS)
    i = html.index(anchor) + len(anchor)
    return html[:i] + "\n" + s + e + html[i:]


def refresh(args) -> int:
    src = Path(args.refresh)
    if not src.is_file():
        raise DeckError("--refresh: %s not found" % src)
    if args.with_modules:
        raise DeckError("--with is for a new build; --refresh keeps the modules the deck has "
                        "(add one by building the slides into a fresh deck)")
    if args.deck_attr:
        raise DeckError("--deck-attr is for a new build; --refresh keeps the deck element as it is "
                        "(build the slides again with --deck-attr for a copy with other options)")
    html = src.read_text(encoding="utf-8")

    blocks: list[str] = []
    if span(html, BLOCKS_CSS) is not None:
        blocks = parse_blocks(args.blocks) if args.blocks else (recorded_blocks(html) or [])
        unknown = [b for b in blocks if b not in block_catalog() or b in DECK_REFUSED]
        if unknown:
            raise DeckError("the deck names block(s) the catalog no longer has for a deck: %s" % ", ".join(unknown))
        if NEEDS_MOTION & set(blocks) and span(html, module_region_name("motion")) is None:
            print("new-deck: %s moves with the motion module, which this deck does not carry; build the "
                  "slides into a fresh deck with --with motion" % ", ".join(sorted(NEEDS_MOTION & set(blocks))),
                  file=sys.stderr)
        if blocks and blocks_js(blocks) and span(html, BLOCKS_JS) is None:
            html = add_block_js_region(html)
    elif args.blocks:
        raise DeckError("--blocks on --refresh swaps the set of a deck built with --blocks; this one has no "
                        "deck-blocks region (build the slides into a fresh deck with --blocks)")

    present = [name for name, _ in REGIONS if span(html, name) is not None]
    present += [module_region_name(m) for m in sorted(set(MODULE_MARK_RE.findall(html)))
                if span(html, module_region_name(m)) is not None]
    if not present:
        raise DeckError("%s carries no marker region; nothing to refresh" % src)
    present.sort(key=lambda n: span(html, n)[0])   # the deck's own order, kept

    tokens = span(html, "deck-tokens")
    found = PRESET_RE.search(html[tokens[0]:tokens[1]]) if tokens else None
    slug = args.preset or (found.group(1) if found else None)
    needs_preset = [n for n in ("deck-tokens", "deck-fonts", "deck-preset-css") if n in present]
    preset, design = {}, None
    if needs_preset:
        if slug:
            named = args.design or args.context or args.persona
            built_with = None
            if not named and tokens:
                try:
                    built_with = bridge_design().recorded(html[tokens[0]:tokens[1]])
                except ValueError as e:
                    raise DeckError("%s records a design that no longer resolves: %s" % (src, e))
                if built_with is not None and not built_with.is_file():
                    raise DeckError("%s records the design %s, which is gone; pass --design" % (src, built_with))
            slug, preset, design = choose_preset(slug, args.design, src.resolve().parent, args.context,
                                                 args.persona, built_with)
        else:
            print("new-deck: no preset recorded in %s and none given; left as they are: %s"
                  % (src, ", ".join(needs_preset)), file=sys.stderr)
            present = [n for n in present if n not in needs_preset]

    fonts = span(html, "deck-fonts")
    if args.no_embed_fonts:
        embed = False
    elif args.embed_fonts:
        embed = True
    else:
        embed = not (fonts and NO_FONTS in html[fonts[0]:fonts[1]])

    contents = region_contents(present, slug, preset, design, embed, blocks)
    updated = splice(html, contents)
    verify(updated, contents, [n for n in present if n in contents])
    out = Path(args.out) if args.out else src
    out.write_text(updated, encoding="utf-8")
    report(out, slug, design, updated, refreshed=present)
    return gate(out, design, args)


def gate(out: Path, design: Path | None, args) -> int:
    """The quality gate on what was just written (html-canvas verify-page.py, static).

    A fresh deck may hold catalog sample slides by design, so sample text is a warning
    here; the send gate (verify-page without --allow-sample) is where it has to be gone.
    """
    if getattr(args, "no_verify", False):
        return 0
    script = CANVAS_SCRIPTS / "verify-page.py"
    if not script.is_file():
        raise DeckError("%s not found; html-slides needs the html-canvas skill next to it" % script)
    cmd = [sys.executable, str(script), str(out), "--allow-sample"]
    if design:
        cmd += ["--design", str(design)]
    r = subprocess.run(cmd, capture_output=True, text=True)
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    return 1 if r.returncode else 0


def report(out: Path, slug: str | None, design: Path | None, html: str, refreshed=None) -> None:
    stamp = STAMP_RE.search(read_asset("slide-engine.js").splitlines()[0] if (ASSETS / "slide-engine.js").is_file() else "")
    engine = "engine v%s" % (stamp.group(1) if stamp else "1")
    what = ("refreshed %s" % ", ".join(refreshed)) if refreshed is not None else "built"
    source = (" from %s" % design) if (slug == "design" and design) else ""
    mods = [m for m in MODULE_MARK_RE.findall(html)]
    modules = (", modules %s" % ", ".join(dict.fromkeys(mods))) if mods else ""
    blocks = recorded_blocks(html)
    blocks = (", blocks %s" % ", ".join(blocks)) if blocks else ""
    print("new-deck: %s %s (preset %s%s, %s, %d slides%s%s)"
          % (what, out, slug or "unknown", source, engine, len(SLIDE_RE.findall(html)), modules, blocks))


def list_all() -> int:
    """--list: the presets, the modules and the blocks a deck can take."""
    print("presets:")
    default = default_style_slug()
    for p in sorted(PRESETS.glob("*.yaml")):
        if p.name.startswith("_") or p.name.endswith(".map.yaml"):
            continue
        data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        mark = "  (default)" if p.stem == default else ("  (from DESIGN.md)" if data.get("source") == "design" else "")
        print("  %-18s%s%s" % (p.stem, str(data.get("name") or "").strip(), mark))
    print("modules:")
    for m in available_modules():
        print("  %s" % m)
    print("blocks:")
    table = new_page().css_blocks()
    for name in block_catalog():
        if name in DECK_REFUSED:
            print("  %-15s not in a deck: %s" % (name, DECK_REFUSED[name]))
            continue
        req = [r for r in table.get(name, ([], ""))[0] if r not in DECK_DROPPED]
        extra = ["needs %s" % ", ".join(req)] if req else []
        if name in NEEDS_MOTION:
            extra.append("moves with --with motion")
        print("  %-15s%s" % (name, ("  (%s)" % "; ".join(extra)) if extra else ""))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Assemble or refresh a single-file html-slides deck")
    ap.add_argument("--title", help="deck title (<title>, and the title slide without --slides)")
    ap.add_argument("--title-de", dest="title_de", help="the title in German (the title slide shows the pair)")
    ap.add_argument("--title-en", dest="title_en", help="the title in English")
    ap.add_argument("--out", help="the deck to write; with --refresh, write here instead of in place")
    ap.add_argument("--slides", help="HTML fragment of <section class=\"slide ...\"> elements")
    ap.add_argument("--preset", help="preset slug (default: design when a DESIGN.md is found, "
                                     "else the preset marked default)")
    ap.add_argument("--design", help="DESIGN.md or design id to use (default: the nearest one above the "
                                    "output, inside the Bridge the design it resolves)")
    ap.add_argument("--context", help="workflow/contexts/<name>.yaml whose design_ref the deck wears")
    ap.add_argument("--persona", help="identity/personas/<id>.yaml whose design_ref the deck wears")
    ap.add_argument("--lang", choices=("en", "de"), default="en", help="<html lang> (default en)")
    ap.add_argument("--theme-default", choices=("light", "dark"),
                    help="the theme the deck opens in when the viewer chose none (default: the design's "
                         "defaultMode, else the OS); "
                         "build only, a refresh keeps the <html> tag")
    ap.add_argument("--with-stage", action="store_true", help="add the live stage (assets/slide-stage.*)")
    ap.add_argument("--with", dest="with_modules", action="append", default=[], metavar="NAME",
                    help="inline the deck module assets/modules/NAME.js (+ .css); repeatable, "
                         "`all` takes every module (build only, a refresh keeps the deck's set)")
    ap.add_argument("--blocks", help="html-canvas section blocks, comma separated, or `all` (see --list); "
                                     "on --refresh: swap the set of a deck built with --blocks")
    ap.add_argument("--deck-attr", action="append", default=[], metavar="data-NAME=VALUE",
                    help="an engine option on the deck element, e.g. data-tracks-default=short or "
                         "data-back-href=page.html (repeatable; build only, a refresh keeps the deck element)")
    ap.add_argument("--no-embed-fonts", action="store_true", help="leave the font region empty")
    ap.add_argument("--embed-fonts", action="store_true", help="with --refresh: embed even if the deck had none")
    ap.add_argument("--refresh", metavar="DECK", help="rewrite the marker regions of an existing deck")
    ap.add_argument("--force", action="store_true", help="overwrite an existing --out when building")
    ap.add_argument("--no-verify", action="store_true", help="skip the gate (verify-page.py) after writing; for tests and scripted "
                         "pipelines that run the gate themselves")
    ap.add_argument("--list", action="store_true", help="list presets, modules and blocks, then exit")
    args = ap.parse_args()
    if args.embed_fonts and args.no_embed_fonts:
        ap.error("--embed-fonts and --no-embed-fonts exclude each other")
    try:
        if args.list:
            return list_all()
        return refresh(args) if args.refresh else build(args)
    except (DeckError, OSError) as e:
        print("new-deck: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
