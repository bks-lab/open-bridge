"""The `design` preset: DESIGN.md is the only source of colour and type in a deck.

presets/design.map.yaml maps DESIGN.md colour roles onto the variables the
engine reads; html-canvas/scripts/design-to-css.py writes them into the deck's
token region for .theme-light and .theme-dark. The proof is verify-page: a
deck built this way names no hex value DESIGN.md does not declare, and reads
at WCAG contrast in both themes, while a style preset deck fails the same check.
"""
from __future__ import annotations

import importlib.util
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

from slides_testlib import ASSETS, FIXTURES, PRESETS, REFERENCE, SKILL, slide_type_snippets

CANVAS = SKILL.parent / "html-canvas" / "scripts"
NEW_DECK = SKILL / "scripts" / "new-deck.py"
DESIGN = FIXTURES / "tooling" / "DESIGN.md"
MAP = PRESETS / "design.map.yaml"
PRESET = PRESETS / "design.yaml"


def canvas_module(name: str):
    spec = importlib.util.spec_from_file_location(name.replace("-", "_"), CANVAS / (name + ".py"))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def engine_vars() -> set[str]:
    css = (ASSETS / "slide-engine.css").read_text("utf-8")
    return set(re.findall(r"var\(--([a-z0-9-]+)", css))


def all_types_fragment(tmp_path: Path) -> Path:
    frag = tmp_path / "all-types.html"
    frag.write_text("\n".join(h.replace("{color}", "accent") for _, h in slide_type_snippets()), encoding="utf-8")
    return frag


def build(tmp_path: Path, *extra) -> Path:
    shutil.copyfile(DESIGN, tmp_path / "DESIGN.md")
    out = tmp_path / ("deck-%s.html" % ("-".join(a.strip("-") for a in extra) or "design"))
    subprocess.run([sys.executable, str(NEW_DECK), "--title", "Design deck", "--slides", all_types_fragment(tmp_path),
                    "--out", out, "--force", *extra], check=True, capture_output=True)
    return out


def verify(path: Path, *extra) -> dict:
    proc = subprocess.run([sys.executable, str(CANVAS / "verify-page.py"), str(path), "--design",
                           str(path.parent / "DESIGN.md"), "--json", *extra], capture_output=True, text=True)
    assert proc.returncode in (0, 1), proc.stderr
    return json.loads(proc.stdout)["pages"][0]


def findings(report: dict, rule: str) -> list:
    return [f for f in report.get("findings", []) if f.get("rule") == rule]


# --- the files -----------------------------------------------------------------------------

def test_preset_file_declares_its_source():
    data = yaml.safe_load(PRESET.read_text("utf-8"))
    assert data["slug"] == "design" and data["default"] is False
    assert data["source"] == "design"
    assert (PRESETS / data["map"]).resolve() == MAP.resolve()
    for key in ("name", "use_for", "personality"):
        assert isinstance(data[key], str) and data[key].strip()
    assert "colors" not in data, "colours come from DESIGN.md, never from this file"
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b", PRESET.read_text("utf-8")), "no hex in the design preset"


def test_map_loads_and_covers_every_engine_colour():
    entries, selectors = canvas_module("design-to-css").load_map(MAP)
    wanted = {v for v in engine_vars() if not v.startswith("font-")}
    assert wanted, "no variables found in slide-engine.css"
    assert wanted <= set(entries), "engine variables without a map entry: %s" % sorted(wanted - set(entries))
    assert ".theme-dark" in selectors["dark"] and ".theme-light" in selectors["light"]


def test_map_has_no_literal_colours():
    text = MAP.read_text("utf-8")
    assert not re.search(r"#[0-9a-fA-F]{3,8}\b|rgba?\(", text)


def test_every_mapped_role_resolves_under_strict():
    proc = subprocess.run([sys.executable, str(CANVAS / "design-to-css.py"), str(DESIGN), "--map", str(MAP),
                           "--strict"], capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr
    assert proc.stderr == ""


# --- the deck ------------------------------------------------------------------------------

def test_design_deck_declares_no_undeclared_hex(tmp_path):
    report = verify(build(tmp_path))
    assert findings(report, "hex") == [], findings(report, "hex")
    for rule in ("external-url", "local-ref", "placeholder", "charset"):
        assert findings(report, rule) == [], (rule, findings(report, rule))


def test_a_style_preset_deck_fails_the_same_check(tmp_path):
    """Counter-check: the hex rule bites on a hand-picked palette, so the green above means something."""
    report = verify(build(tmp_path, "--preset", "swiss-modern"))
    assert findings(report, "hex"), "swiss-modern names hex values DESIGN.md does not declare"


def test_design_deck_names_no_font_without_face(tmp_path):
    report = verify(build(tmp_path))
    assert findings(report, "font-face") == [], findings(report, "font-face")


def test_design_deck_contrast_in_both_themes(tmp_path):
    pytest.importorskip("playwright.sync_api")
    report = verify(build(tmp_path), "--browser")
    skipped = findings(report, "browser-skipped")
    if skipped:
        pytest.skip(skipped[0]["message"])
    assert findings(report, "contrast") == [], findings(report, "contrast")
    assert findings(report, "console-error") == [] and findings(report, "network") == []


# --- the preset's own rules, rendered ------------------------------------------------------

STYLE = """(sel) => { const cs = getComputedStyle(document.querySelector(sel));
  return {weight: cs.fontWeight, spacing: cs.letterSpacing, size: parseFloat(cs.fontSize),
          bg: cs.backgroundImage, blur: cs.backdropFilter}; }"""


def test_display_weight_letter_spacing_and_fx_gate(open_html, page, tmp_path):
    html = build(tmp_path).read_text("utf-8")
    open_html(html)
    page.wait_for_selector(".theme-toggle", state="attached")
    d = page.evaluate(STYLE, ".slide__display")
    assert d["weight"] == "500"
    assert abs(float(d["spacing"].replace("px", "")) - (-0.01 * d["size"])) < 0.2, d
    assert page.evaluate(STYLE, ".slide--title")["bg"] == "none", "no gradient without .fx"
    assert page.evaluate(STYLE, ".theme-toggle")["blur"] in ("none", ""), "no blur without .fx"
    page.evaluate("() => document.documentElement.classList.add('fx')")
    assert "gradient" in page.evaluate(STYLE, ".slide--title")["bg"], ".fx turns the decoration back on"
    assert page.errors == []


def test_design_subtitle_is_set_in_the_body_family(open_html, page, tmp_path):
    """Subtitles and taglines are body copy in DESIGN.md terms, not letter-spaced mono."""
    open_html(build(tmp_path).read_text("utf-8"))
    fam = page.evaluate("""() => { const cs = getComputedStyle(document.querySelector('.slide__subtitle'));
      return [cs.fontFamily, cs.letterSpacing, getComputedStyle(document.body).fontFamily]; }""")
    assert fam[0] == fam[2], fam
    assert fam[1] in ("normal", "0px"), fam
    mixed = page.evaluate("""() => { const el = document.createElement('span'); el.className = 'str';
      document.querySelector('.slide__code-block').appendChild(el);
      const probe = document.createElement('span'); probe.style.color = 'var(--amber)'; document.body.appendChild(probe);
      return [getComputedStyle(el).color, getComputedStyle(probe).color]; }""")
    assert mixed[0] != mixed[1], "code strings are mixed towards the text colour"


# --- the rules doc -------------------------------------------------------------------------

def test_rules_say_design_md_wins_and_limit_the_font_ban():
    text = (REFERENCE / "rules.md").read_text("utf-8")
    assert "DESIGN.md wins" in text
    assert re.search(r"style presets?", text, re.I)
    ban = next(ln for ln in text.splitlines() if ln.startswith("| Fonts"))
    assert "style preset" in ban.lower(), "the Inter ban names its scope: style presets only"
