"""Helpers shared by the html-slides tests (imported by name, unlike conftest).

A uniquely named module on purpose: several skills ship a tests/conftest.py, and
`from conftest import ...` resolves to whichever one pytest imported first when
their suites run in one session.
"""
from __future__ import annotations

import importlib.util
import re
from pathlib import Path

import yaml

SKILL = Path(__file__).resolve().parents[1]
ASSETS = SKILL / "assets"
PRESETS = SKILL / "presets"
REFERENCE = SKILL / "reference"
FIXTURES = Path(__file__).resolve().parent / "fixtures"

# Every colour token a preset defines per mode, in the order SKILL.md lists them.
COLOR_KEYS = (
    "bg", "surface", "surface2", "surface-elevated", "border", "border-bright",
    "text", "text-dim", "accent", "accent-dim", "code-bg", "code-text",
    "green", "green-dim", "red", "red-dim", "amber", "amber-dim", "cyan", "cyan-dim",
)

# Marker regions a deck carries; html-slides/scripts/new-deck.py splices between them.
ENGINE_CSS_RE = re.compile(r"(<!-- slide-engine:css:start -->)(.*?)(<!-- slide-engine:css:end -->)", re.S)
ENGINE_JS_RE = re.compile(r"(<!-- slide-engine:js:start -->)(.*?)(<!-- slide-engine:js:end -->)", re.S)


def preset_files() -> list[Path]:
    """Every shipped style preset: `_` files, `*.map.yaml` token maps and the
    DESIGN.md driven preset (source: design, no colours of its own) excluded."""
    return sorted(p for p in PRESETS.glob("*.yaml")
                  if not p.name.startswith("_") and not p.name.endswith(".map.yaml")
                  and (yaml.safe_load(p.read_text("utf-8")) or {}).get("source") != "design")


def load_preset(slug: str) -> dict:
    return yaml.safe_load((PRESETS / f"{slug}.yaml").read_text("utf-8"))


def slide_type_snippets() -> list[tuple[str, str]]:
    """(heading, html) for every numbered slide type in reference/slide-types.md."""
    lines = (REFERENCE / "slide-types.md").read_text("utf-8").splitlines()
    out: list[tuple[str, str]] = []
    heading, block, inside = None, [], False
    for ln in lines:
        m = re.match(r"^### (\d+)\. (.+)$", ln)
        if m and not inside:
            heading = m.group(2).strip()
            continue
        if ln.startswith("```"):
            if inside:
                if heading is not None:
                    out.append((heading, "\n".join(block)))
                    heading = None
                block, inside = [], False
            elif ln.strip() == "```html":
                inside = True
            continue
        if inside:
            block.append(ln)
    return out


def _font_stack(entry, fallback: str) -> str:
    if isinstance(entry, dict):
        return "'%s', %s" % (entry["family"], entry.get("fallback") or fallback)
    return "'%s', %s" % (entry, fallback)


def theme_css(preset: dict) -> str:
    """The :root block SKILL.md describes: dark default, light by class and by OS."""
    fonts = preset["fonts"]
    dark, light = preset["colors"]["dark"], preset["colors"]["light"]

    def decls(colors: dict) -> str:
        return "\n".join("  --%s: %s;" % (k, colors[k]) for k in COLOR_KEYS)

    return "\n".join([
        ":root {",
        "  --font-display: %s;" % _font_stack(fonts["display"], "system-ui, sans-serif"),
        "  --font-body: %s;" % _font_stack(fonts["body"], "system-ui, sans-serif"),
        "  --font-mono: %s;" % _font_stack(fonts["mono"], "'SF Mono', Consolas, monospace"),
        decls(dark),
        "}",
        ":root.theme-light {", decls(light), "}",
        "@media (prefers-color-scheme: light) {",
        ":root:not(.theme-dark):not(.theme-light) {", decls(light), "}",
        "}",
    ])


THEME_INIT = (
    "<script>(function(){ try { var s = localStorage.getItem('slide-theme');"
    " if (s === 'light' || s === 'dark') { document.documentElement.classList.add('theme-' + s); } }"
    " catch(e){} })();</script>"
)


def splice_engine(html: str) -> str:
    """Fill the engine marker regions with the CURRENT engine assets."""
    css = (ASSETS / "slide-engine.css").read_text("utf-8")
    js = (ASSETS / "slide-engine.js").read_text("utf-8")
    assert ENGINE_CSS_RE.search(html) and ENGINE_JS_RE.search(html), "deck lacks engine markers"
    # The `{}` sink swallows the marker name: inside <style>, CSS skips only the
    # <!-- and --> of a marker, so its name would glue onto the first selector.
    sink = load_script("new-deck.py").CSS_SINK
    html = ENGINE_CSS_RE.sub(lambda m: m.group(1) + "\n" + sink + css + "\n" + m.group(3), html, count=1)
    html = ENGINE_JS_RE.sub(lambda m: m.group(1) + "\n<script>\n" + js + "\n</script>\n" + m.group(3), html, count=1)
    return html


def load_script(filename: str):
    """Import a hyphenated script from scripts/ by path (font-face.py)."""
    name = "html_slides_" + filename.replace("-", "_").removesuffix(".py")
    spec = importlib.util.spec_from_file_location(name, SKILL / "scripts" / filename)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def font_block(preset: dict) -> str:
    """The embedded @font-face <style> block scripts/font-face.py prints for a preset."""
    ff = load_script("font-face.py")
    roles = ff.collect_roles(preset)
    return ff.font_face_block(roles) if roles else ""


def build_probe_deck(preset_slug: str = "swiss-modern", lang: str = "en") -> str:
    """A deck holding one slide of every documented type, themed by a preset."""
    preset = load_preset(preset_slug)
    slides = "\n".join(html.replace("{color}", "accent") for _, html in slide_type_snippets())
    overrides = preset.get("css_overrides") or ""
    return splice_engine("""<!DOCTYPE html>
<html lang="%s">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Probe deck</title>
%s
%s
<style>
%s
<!-- slide-engine:css:start --><!-- slide-engine:css:end -->
%s
</style>
</head>
<body>
<div class="deck">
%s
</div>
<!-- slide-engine:js:start --><!-- slide-engine:js:end -->
</body>
</html>
""" % (lang, THEME_INIT, font_block(preset), theme_css(preset), overrides, slides))
    # The CSS markers sit inside <style> on purpose: CSS skips `<!--` and `-->`
    # at the top level of a stylesheet, so they cost nothing there.
