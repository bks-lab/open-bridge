"""The shell filled from the repo's DESIGN.md defines every token it and the simulation use.

The token adapter (--map, --selectors, --region) serves consumers with other
variable names and theme selectors without changing the default output.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1]
REPO = SKILL.parents[1]
SCRIPT = str(SKILL / "scripts" / "design-to-css.py")
TOKENS = Path(__file__).resolve().parent / "fixtures" / "tokens"


def _vars(text: str) -> tuple[set[str], set[str]]:
    defined = set(re.findall(r"(--[\w-]+)\s*:", text))
    used = set(re.findall(r"var\((--[\w-]+)\s*[,)]", text))
    return defined, used


def _run(*args, check=True) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, SCRIPT, *map(str, args)], check=check,
                          capture_output=True, text=True, encoding="utf-8")


def _groups(css: str) -> dict[str, dict[str, str]]:
    """Top-level `selector { --name: value; }` blocks, keyed by selector."""
    body = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    out = {}
    for sel, decls in re.findall(r"([^{}]+)\{([^{}]*)\}", body):
        out[sel.strip()] = dict(re.findall(r"--([\w-]+)\s*:\s*([^;]+);", decls))
    return out


MAPPED = {"bg", "surface", "text", "text-dim", "accent", "accent-dim", "green", "green-dim"}


def test_filled_shell_leaves_no_token_undefined(tmp_path):
    out = tmp_path / "shell.html"
    subprocess.run([sys.executable, str(SKILL / "scripts" / "design-to-css.py"), str(REPO / "DESIGN.md"),
                    "--shell", "--out", str(out)], check=True, capture_output=True)
    text = out.read_text("utf-8") + (SKILL / "assets" / "simulation.css").read_text("utf-8")
    defined, used = _vars(text)
    assert not (used - defined), sorted(used - defined)


def test_filling_twice_does_not_stack_generated_blocks(tmp_path):
    first, second = tmp_path / "a.html", tmp_path / "b.html"
    script = str(SKILL / "scripts" / "design-to-css.py")
    subprocess.run([sys.executable, script, str(REPO / "DESIGN.md"), "--shell", "--out", str(first)],
                   check=True, capture_output=True)
    subprocess.run([sys.executable, script, str(REPO / "DESIGN.md"), "--shell", str(first), "--out", str(second)],
                   check=True, capture_output=True)
    assert second.read_text("utf-8").count("generated from DESIGN.md") == 1


# Without the new flags nothing changes. The goldens were written by the script
# as it stood before --map, --selectors and --region existed.

@pytest.mark.parametrize("design,golden", [("design-current.md", "golden-current.css"),
                                           ("design-legacy.md", "golden-legacy.css")])
def test_absent_flags_give_the_output_from_before(design, golden):
    assert _run(TOKENS / design).stdout == (TOKENS / golden).read_text("utf-8")


def test_absent_flags_fill_a_shell_as_before(tmp_path):
    out = tmp_path / "page.html"
    _run(TOKENS / "design-current.md", "--shell", TOKENS / "shell-region.html", "--out", out)
    assert out.read_bytes() == (TOKENS / "golden-shell-region.html").read_bytes()


# --map: exactly the mapped variables, in both selector groups.

def test_map_gives_exactly_the_mapped_variables_in_both_groups():
    groups = _groups(_run(TOKENS / "design-current.md", "--map", TOKENS / "map.yaml").stdout)
    assert set(groups) == {":root", "html.dark"}
    assert set(groups[":root"]) == MAPPED
    assert set(groups["html.dark"]) == MAPPED
    assert groups[":root"]["bg"] == "#F8F6F2"
    assert groups["html.dark"]["bg"] == "#121417"
    assert groups[":root"]["surface"] == "#FFFFFF"
    assert groups["html.dark"]["text"] == "#ECECEC"


def test_map_derives_dim_variants_with_color_mix():
    groups = _groups(_run(TOKENS / "design-current.md", "--map", TOKENS / "map.yaml").stdout)
    assert groups[":root"]["accent-dim"] == "color-mix(in srgb, #3060C0 15%, transparent)"
    assert groups["html.dark"]["accent-dim"] == "color-mix(in srgb, #80A8E0 15%, transparent)"
    assert groups[":root"]["green-dim"] == "color-mix(in srgb, #2E7D32 20%, #F8F6F2)"
    assert groups["html.dark"]["green-dim"] == "color-mix(in srgb, #66BB6A 20%, #121417)"


def test_map_reads_the_legacy_dark_shape_and_falls_back_to_light():
    groups = _groups(_run(TOKENS / "design-legacy.md", "--map", TOKENS / "map-selectors.yaml").stdout)
    assert groups[".theme-dark"] == {"bg": "#111111", "text": "#DDDDDD"}
    assert groups[":root, .theme-light"] == {"bg": "#FFFFFF", "text": "#333333"}


def test_map_with_selectors_flag():
    css = _run(TOKENS / "design-current.md", "--map", TOKENS / "map.yaml",
               "--selectors", "light=.theme-light", "dark=.theme-dark").stdout
    groups = _groups(css)
    assert set(groups) == {".theme-light", ".theme-dark"}
    assert set(groups[".theme-light"]) == MAPPED == set(groups[".theme-dark"])


def test_selectors_flag_overrides_the_map_file():
    groups = _groups(_run(TOKENS / "design-current.md", "--map", TOKENS / "map-selectors.yaml",
                          "--selectors", "dark=[data-theme=dark]").stdout)
    assert set(groups) == {":root, .theme-light", "[data-theme=dark]"}


def test_selectors_without_map_rename_the_full_sheet():
    css = _run(TOKENS / "design-legacy.md", "--selectors", "dark=.theme-dark").stdout
    golden = (TOKENS / "golden-legacy.css").read_text("utf-8")
    assert "html.dark" not in css
    assert ".theme-dark {" in css and ":root, .theme-dark {" in css
    assert _groups(css)[".theme-dark"] == _groups(golden)["html.dark"]


def test_bad_selector_argument_fails_clearly():
    res = _run(TOKENS / "design-current.md", "--selectors", "darkish", check=False)
    assert res.returncode != 0
    assert "light=" in res.stderr and "dark=" in res.stderr


# Missing roles: reported always, fatal under --strict.

def test_missing_role_fails_under_strict():
    res = _run(TOKENS / "design-current.md", "--map", TOKENS / "map-missing.yaml", "--strict", check=False)
    assert res.returncode != 0
    assert "warning" in res.stderr and "amber" in res.stderr


def test_missing_role_is_reported_and_skipped_without_strict():
    res = _run(TOKENS / "design-current.md", "--map", TOKENS / "map-missing.yaml")
    assert res.returncode == 0
    assert "warning" in res.stderr
    groups = _groups(res.stdout)
    assert set(groups[":root"]) == {"bg"} == set(groups["html.dark"])


def test_map_ignores_unmapped_design_keys_under_strict():
    # brand-only-key is not in COLOR_MAP; with a map only the map's roles count.
    assert _run(TOKENS / "design-current.md", "--map", TOKENS / "map.yaml", "--strict").returncode == 0


def test_malformed_map_fails_clearly(tmp_path):
    bad = tmp_path / "bad.yaml"
    bad.write_text("vars:\n  accent-dim: {role: accent, mix: 150}\n", encoding="utf-8")
    res = _run(TOKENS / "design-current.md", "--map", bad, check=False)
    assert res.returncode != 0 and "accent-dim" in res.stderr


# --region: any file with named markers, idempotent.

def _fill_region(tmp_path, src, name="first.html"):
    out = tmp_path / name
    _run(TOKENS / "design-current.md", "--map", TOKENS / "map.yaml",
         "--selectors", "light=:root,.theme-light", "dark=.theme-dark",
         "--region", "deck-tokens", "--shell", src, "--out", out)
    return out


def test_region_fills_named_markers_and_keeps_the_rest(tmp_path):
    out = _fill_region(tmp_path, TOKENS / "target.html")
    text = out.read_text("utf-8")
    src = (TOKENS / "target.html").read_text("utf-8")
    assert text.count("/* deck-tokens:begin */") == 1 and text.count("/* deck-tokens:end */") == 1
    assert "--bg: #121417;" in text
    head, tail = src.split("/* deck-tokens:begin */")[0], src.split("/* deck-tokens:end */")[1]
    assert text.startswith(head) and text.endswith(tail)
    assert ":root { --bg: Canvas; --text: CanvasText; }" in text


def test_region_twice_gives_identical_bytes(tmp_path):
    first = _fill_region(tmp_path, TOKENS / "target.html")
    second = _fill_region(tmp_path, first, "second.html")
    assert first.read_bytes() == second.read_bytes()


def test_region_in_place(tmp_path):
    target = tmp_path / "deck.html"
    shutil.copy(TOKENS / "target.html", target)
    _fill_region(tmp_path, target, "deck.html")
    once = target.read_bytes()
    _fill_region(tmp_path, target, "deck.html")
    assert target.read_bytes() == once


def test_region_missing_in_target_fails_clearly(tmp_path):
    res = _run(TOKENS / "design-current.md", "--region", "nope", "--shell", TOKENS / "target.html",
               "--out", tmp_path / "x.html", check=False)
    assert res.returncode != 0 and "nope:begin" in res.stderr
    assert not (tmp_path / "x.html").exists()


def test_region_rejects_a_name_that_breaks_the_comment(tmp_path):
    res = _run(TOKENS / "design-current.md", "--region", "a*/b", "--shell", TOKENS / "target.html",
               "--out", tmp_path / "x.html", check=False)
    assert res.returncode != 0
    assert not (tmp_path / "x.html").exists()


# In a browser, offline, the mapped variables follow the theme class.

def test_region_page_switches_theme_in_a_browser(tmp_path):
    sync_api = pytest.importorskip("playwright.sync_api")
    page_dir = tmp_path / "offline"
    page_dir.mkdir()
    out = _fill_region(page_dir, TOKENS / "target.html", "deck.html")
    with sync_api.sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except sync_api.Error as e:
            pytest.skip(f"chromium unavailable: {e}")
        page = browser.new_page(viewport={"width": 800, "height": 600})
        requests = []
        page.on("request", lambda r: requests.append(r.url))
        page.goto(out.as_uri())
        bg = "getComputedStyle(document.body).backgroundColor"
        light = page.evaluate(bg)
        page.evaluate("document.documentElement.classList.add('theme-dark')")
        dark = page.evaluate(bg)
        browser.close()
    assert light == "rgb(248, 246, 242)"
    assert dark == "rgb(18, 20, 23)"
    assert all(u.startswith("file:") for u in requests), requests


# --embed-fonts: the DESIGN.md families as base64 @font-face, inside the region.

FONT_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "fonts"


def _region_body(text: str, region: str = "design-tokens") -> str:
    return text.split("/* %s:begin */" % region, 1)[1].split("/* %s:end */" % region, 1)[0]


def test_embed_fonts_is_off_by_default(tmp_path):
    out = tmp_path / "page.html"
    _run(TOKENS / "design-current.md", "--shell", "--out", out)
    assert "@font-face" not in out.read_text("utf-8")
    assert "@font-face" not in _run(TOKENS / "design-current.md").stdout


def test_embed_fonts_puts_faces_inside_the_generated_region(tmp_path):
    out = tmp_path / "page.html"
    res = _run(TOKENS / "design-current.md", "--embed-fonts", "--shell", "--out", out)
    text = out.read_text("utf-8")
    body = _region_body(text)
    generated = body.split("generated from DESIGN.md", 1)[1]
    assert text.count("@font-face") == generated.count("@font-face") == 2
    assert 'font-family: "Inter"' in generated and 'font-family: "Playfair Display"' in generated
    assert "data:font/woff2;base64," in generated
    assert "fonts.googleapis" not in text
    # the fixture's mono family has no bundled file: reported, not fatal
    assert "JetBrains Mono" in res.stderr


def test_embed_fonts_twice_gives_identical_bytes(tmp_path):
    first, second = tmp_path / "a.html", tmp_path / "b.html"
    _run(TOKENS / "design-current.md", "--embed-fonts", "--shell", "--out", first)
    _run(TOKENS / "design-current.md", "--embed-fonts", "--shell", first, "--out", second)
    assert first.read_bytes() == second.read_bytes()


def test_embed_fonts_on_stdout_and_with_a_font_dir(tmp_path):
    design = tmp_path / "DESIGN.md"
    design.write_text("---\nname: t\ncolors:\n  surface: '#ffffff'\ntypography:\n"
                      "  body-md:\n    fontFamily: Fixture Sans\n    fontWeight: 600\n---\n", "utf-8")
    res = _run(design, "--embed-fonts", "--font-dir", FONT_FIXTURES)
    assert res.stdout.count("@font-face") == 1 and 'font-family: "Fixture Sans"' in res.stdout
    assert "font-weight: 600" in res.stdout
    assert res.stdout.index(":root {") < res.stdout.index("@font-face")


def test_font_dir_needs_embed_fonts():
    res = _run(TOKENS / "design-current.md", "--font-dir", FONT_FIXTURES, check=False)
    assert res.returncode != 0 and "--embed-fonts" in res.stderr


def test_embedded_font_loads_offline_in_a_browser(tmp_path, open_page):
    out = tmp_path / "page.html"
    _run(TOKENS / "design-current.md", "--embed-fonts", "--shell", "--out", out)
    page = open_page(out.read_text("utf-8"))
    loaded = page.evaluate("document.fonts.load('16px Inter').then(f => f.length)")
    assert loaded >= 1
    assert page.evaluate("document.fonts.check('16px Inter')")
