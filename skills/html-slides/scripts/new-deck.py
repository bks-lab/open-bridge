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
  slide-stage:css    <style>  assets/slide-stage.css (only with --with-stage)
  slide-engine:js    <body>   assets/slide-engine.js in a <script>, byte for byte
  slide-stage:js     <body>   assets/slide-stage.js in a <script> (only with --with-stage)

Each region is `<!-- NAME:start -->CONTENT<!-- NAME:end -->`. In a stylesheet
CSS skips only the `<!--` and `-->` of a marker, not the name between them, so
the name would glue onto the next selector and void that rule. Every region
inside <style> therefore opens with an empty rule `{}` that swallows it.

--refresh rewrites only the regions a deck already carries, from the current
assets, DESIGN.md and preset; text outside them is never touched, no region is
added, and a second run gives the same bytes. Every splice is read back and
compared before the file is written.

Preset choice: --preset when given; else `design` when a DESIGN.md is given
(--design) or found walking up from the output path; else the style preset
marked `default: true`. On --refresh the preset is read back from the deck.

Fonts: embedded by default (style presets depend on their typefaces);
--no-embed-fonts leaves the region empty and the deck on its fallback stacks.

Usage:
  new-deck.py --title "Quarterly review" --out deck.html [--slides slides.html]
              [--preset SLUG] [--design DESIGN.md] [--lang en|de]
              [--with-stage] [--no-embed-fonts] [--force]
  new-deck.py --refresh deck.html [--out other.html] [--preset SLUG]
              [--design DESIGN.md] [--embed-fonts | --no-embed-fonts]

--slides is an HTML fragment of <section class="slide ..."> elements
(reference/slide-types.md); without it the deck gets one title slide.
"""
from __future__ import annotations

import argparse
import html as html_mod
import importlib.util
import re
import sys
from pathlib import Path

import yaml

SKILL = Path(__file__).resolve().parents[1]
ASSETS = SKILL / "assets"
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
    ("slide-stage:css", "css"),
    ("slide-engine:js", "body"),
    ("slide-stage:js", "body"),
)
CSS_REGIONS = {name for name, where in REGIONS if where == "css"}
STAGE_REGIONS = ("slide-stage:css", "slide-stage:js")

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
  --code-bg: var(--surface2);
  --code-text: var(--text);
  --green: var(--accent); --green-dim: var(--accent-dim);
  --red: var(--accent); --red-dim: var(--accent-dim);
  --amber: var(--accent); --amber-dim: var(--accent-dim);
  --cyan: var(--accent); --cyan-dim: var(--accent-dim);
}"""

PREPAINT = """
<script>
/* Theme pre-paint (html-slides): the saved choice, else the OS, before the first
   paint. Following the OS is not a choice, so it is never written to storage. */
(function () {
  var saved = null;
  try { saved = localStorage.getItem('%s'); } catch (e) { /* no storage */ }
  var dark = saved === 'dark' || (saved !== 'light' && !!window.matchMedia &&
    window.matchMedia('(prefers-color-scheme: dark)').matches);
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

def find_design(start: Path) -> Path | None:
    """The nearest DESIGN.md, never above the project root (html-canvas design-to-css.py)."""
    return design_to_css().find_design(start)


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
        entries, selectors = d2c.load_map(PRESETS / preset.get("map", "design.map.yaml"))
    except (OSError, ValueError, yaml.YAMLError) as e:
        raise DeckError("design map: %s" % e)
    data = d2c.frontmatter(design)
    css, missing = d2c.build_mapped_css(data, entries, selectors)
    if missing:
        print("new-deck: %d mapped role(s) not in %s, the neutral value stays: %s"
              % (len(missing), design, ", ".join(missing)), file=sys.stderr)
    typography = data.get("typography") or {}
    fonts = preset.get("fonts") or {}
    css += "\n:root {\n%s\n}\n" % "\n".join(
        "  --font-%s: %s;" % (var, design_font_stack(typography, fonts.get(role) or {}))
        for var, role in (("display", "display"), ("body", "body"), ("mono", "mono")))
    begin, end, _ = d2c.markers("deck-tokens")
    filled = d2c.inject(begin + "\n" + NEUTRAL_TOKENS + "\n" + end, css, "deck-tokens")
    return css_region("/* deck-preset: design */\n" + filled)


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


def region_contents(names, slug, preset, design, embed) -> dict[str, str]:
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
    return out


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


def verify(html: str, contents: dict[str, str]) -> None:
    """Read every splice back: present once, in order, holding exactly what was meant."""
    last = -1
    for name, _ in REGIONS:
        if name not in contents:
            continue
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


def skeleton(title: str, lang: str, slides: str, stage: bool, attrs: str = "") -> str:
    def r(name: str) -> str:
        s, e = marks(name)
        return s + e
    style = [r("deck-tokens"), r("slide-engine:css"), r("deck-preset-css")]
    body_end = [r("slide-engine:js")]
    if stage:
        style.append(r("slide-stage:css"))
        body_end.append(r("slide-stage:js"))
    return "\n".join([
        "<!DOCTYPE html>",
        '<html lang="%s">' % lang,
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


def title_slide(title: str) -> str:
    return ('<section class="slide slide--title">\n  <div class="slide__content">\n'
            '    <h1 class="slide__display reveal">%s</h1>\n  </div>\n</section>'
            % html_mod.escape(title, quote=False))


def choose_preset(slug: str | None, design_arg: str | None, anchor: Path) -> tuple[str, dict, Path | None]:
    design = None
    if design_arg:
        design = Path(design_arg)
        if not design.is_file():
            raise DeckError("--design: %s not found" % design)
    else:
        design = find_design(anchor)
    slug = slug or ("design" if design else default_style_slug())
    preset = load_preset(slug)
    if is_design(preset) and not design:
        raise DeckError("preset %s takes its colours from DESIGN.md, and none was found above %s; "
                        "pass --design or pick a style preset" % (slug, anchor))
    return slug, preset, design


def build(args) -> int:
    if not args.title or not args.out:
        raise DeckError("a new deck needs --title and --out (or use --refresh DECK)")
    out = Path(args.out)
    if out.exists() and not args.force:
        raise DeckError("%s exists; pass --force to overwrite it, or --refresh it" % out)
    if args.slides:
        slides = Path(args.slides).read_text(encoding="utf-8")
        if not SLIDE_RE.search(slides):
            raise DeckError("%s holds no <section class=\"slide ...\"> element" % args.slides)
    else:
        slides = title_slide(args.title)
    attrs = deck_attrs(args.deck_attr)
    slug, preset, design = choose_preset(args.preset, args.design, out.resolve().parent)

    names = [name for name, _ in REGIONS if args.with_stage or name not in STAGE_REGIONS]
    contents = region_contents(names, slug, preset, design, not args.no_embed_fonts)
    html = splice(skeleton(args.title, args.lang, slides, args.with_stage, attrs), contents)
    verify(html, contents)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    report(out, slug, design, html)
    return 0


def refresh(args) -> int:
    src = Path(args.refresh)
    if not src.is_file():
        raise DeckError("--refresh: %s not found" % src)
    html = src.read_text(encoding="utf-8")
    present = [name for name, _ in REGIONS if span(html, name) is not None]
    if not present:
        raise DeckError("%s carries no marker region; nothing to refresh" % src)

    tokens = span(html, "deck-tokens")
    found = PRESET_RE.search(html[tokens[0]:tokens[1]]) if tokens else None
    slug = args.preset or (found.group(1) if found else None)
    needs_preset = [n for n in ("deck-tokens", "deck-fonts", "deck-preset-css") if n in present]
    preset, design = {}, None
    if needs_preset:
        if slug:
            slug, preset, design = choose_preset(slug, args.design, src.resolve().parent)
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

    contents = region_contents(present, slug, preset, design, embed)
    updated = splice(html, contents)
    verify(updated, contents)
    out = Path(args.out) if args.out else src
    out.write_text(updated, encoding="utf-8")
    report(out, slug, design, updated, refreshed=present)
    return 0


def report(out: Path, slug: str | None, design: Path | None, html: str, refreshed=None) -> None:
    stamp = STAMP_RE.search(read_asset("slide-engine.js").splitlines()[0] if (ASSETS / "slide-engine.js").is_file() else "")
    engine = "engine v%s" % (stamp.group(1) if stamp else "1")
    what = ("refreshed %s" % ", ".join(refreshed)) if refreshed is not None else "built"
    source = (" from %s" % design) if (slug == "design" and design) else ""
    print("new-deck: %s %s (preset %s%s, %s, %d slides)"
          % (what, out, slug or "unknown", source, engine, len(SLIDE_RE.findall(html))))


def main() -> int:
    ap = argparse.ArgumentParser(description="Assemble or refresh a single-file html-slides deck")
    ap.add_argument("--title", help="deck title (<title>, and the title slide without --slides)")
    ap.add_argument("--out", help="the deck to write; with --refresh, write here instead of in place")
    ap.add_argument("--slides", help="HTML fragment of <section class=\"slide ...\"> elements")
    ap.add_argument("--preset", help="preset slug (default: design when a DESIGN.md is found, "
                                     "else the preset marked default)")
    ap.add_argument("--design", help="DESIGN.md to use (default: the nearest one above the output)")
    ap.add_argument("--lang", choices=("en", "de"), default="en", help="<html lang> (default en)")
    ap.add_argument("--with-stage", action="store_true", help="add the live stage (assets/slide-stage.*)")
    ap.add_argument("--deck-attr", action="append", default=[], metavar="data-NAME=VALUE",
                    help="an engine option on the deck element, e.g. data-tracks-default=short or "
                         "data-back-href=page.html (repeatable; build only, a refresh keeps the deck element)")
    ap.add_argument("--no-embed-fonts", action="store_true", help="leave the font region empty")
    ap.add_argument("--embed-fonts", action="store_true", help="with --refresh: embed even if the deck had none")
    ap.add_argument("--refresh", metavar="DECK", help="rewrite the marker regions of an existing deck")
    ap.add_argument("--force", action="store_true", help="overwrite an existing --out when building")
    args = ap.parse_args()
    if args.embed_fonts and args.no_embed_fonts:
        ap.error("--embed-fonts and --no-embed-fonts exclude each other")
    try:
        return refresh(args) if args.refresh else build(args)
    except (DeckError, OSError) as e:
        print("new-deck: %s" % e, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
