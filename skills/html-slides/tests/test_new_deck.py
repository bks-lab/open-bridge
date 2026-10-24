"""scripts/new-deck.py assembles a deck between markers and refreshes it in place.

A deck is the author's slides plus regions the tool owns: the pre-paint theme
script, the embedded fonts, the tokens, the engine CSS and JS, the preset's own
CSS and, on request, the live stage. Everything outside a region belongs to the
author and survives a refresh byte for byte; everything inside one is rebuilt
from the current assets, so running the tool twice gives the same file.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from slides_testlib import ASSETS, FIXTURES, SKILL, load_preset, load_script

SINK = load_script("new-deck.py").CSS_SINK

NEW_DECK = SKILL / "scripts" / "new-deck.py"
TOOLING = FIXTURES / "tooling"
COMPAT = FIXTURES / "compat"
SLIDES = TOOLING / "slides.html"

REGIONS = ("deck-prepaint", "deck-fonts", "deck-tokens", "slide-engine:css",
           "deck-preset-css", "slide-engine:js")
STAGE_REGIONS = ("slide-stage:css", "slide-stage:js")


def run(*args, check=True):
    proc = subprocess.run([sys.executable, str(NEW_DECK), *map(str, args)],
                          capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise AssertionError("new-deck failed (%d):\n%s\n%s" % (proc.returncode, proc.stdout, proc.stderr))
    return proc


def region(html: str, name: str) -> str:
    start, end = "<!-- %s:start -->" % name, "<!-- %s:end -->" % name
    assert html.count(start) == 1, "%s: %d start markers" % (name, html.count(start))
    assert html.count(end) == 1, "%s: %d end markers" % (name, html.count(end))
    a, b = html.index(start), html.index(end)
    assert a < b, name
    return html[a + len(start):b]


def outside(html: str) -> str:
    """The deck with every region's content removed: what belongs to the author."""
    return re.sub(r"(<!-- ([\w:.-]+):start -->).*?(<!-- \2:end -->)", r"\1\3", html, flags=re.S)


@pytest.fixture
def plain_dir(tmp_path) -> Path:
    """A folder with no DESIGN.md anywhere above it (tmp is outside every repo)."""
    d = tmp_path / "plain"
    d.mkdir()
    for folder in [d, *d.parents]:
        if (folder / "DESIGN.md").exists():
            pytest.skip("a DESIGN.md sits above the temp dir: %s" % folder)
    return d


@pytest.fixture
def brand_dir(tmp_path) -> Path:
    """A folder whose parent is a project root (bridge-config.yaml) carrying the fixture DESIGN.md."""
    shutil.copyfile(TOOLING / "DESIGN.md", tmp_path / "DESIGN.md")
    (tmp_path / "bridge-config.yaml").write_text("", encoding="utf-8")
    d = tmp_path / "decks"
    d.mkdir()
    return d


def build(out: Path, *extra) -> str:
    run("--title", "Sample deck", "--slides", SLIDES, "--out", out, *extra)
    return out.read_text("utf-8")


# --- assembly ------------------------------------------------------------------------------

def test_every_region_present_once_and_in_order(plain_dir):
    html = build(plain_dir / "deck.html")
    positions = [html.index("<!-- %s:start -->" % name) for name in REGIONS]
    for name in REGIONS:
        region(html, name)
    assert positions == sorted(positions), "regions out of order"
    for name in STAGE_REGIONS:
        assert "<!-- %s:start -->" % name not in html, "stage only with --with-stage"


def test_engine_blocks_are_byte_equal_with_the_assets(plain_dir):
    html = build(plain_dir / "deck.html")
    css = (ASSETS / "slide-engine.css").read_text("utf-8")
    js = (ASSETS / "slide-engine.js").read_text("utf-8")
    assert region(html, "slide-engine:css") == "\n" + SINK + css
    assert region(html, "slide-engine:js") == "\n<script>\n" + js + "\n</script>\n"


def test_css_regions_sit_inside_style_and_js_after_the_slides(plain_dir):
    html = build(plain_dir / "deck.html")
    style_open, style_close = html.index("<style>"), html.index("</style>", html.index("<!-- slide-engine:css:end -->"))
    for name in ("deck-tokens", "slide-engine:css", "deck-preset-css"):
        assert style_open < html.index("<!-- %s:start -->" % name) < style_close, name
    assert html.index("</section>") < html.index("<!-- slide-engine:js:start -->")


def test_prepaint_is_the_first_script_above_every_stylesheet(plain_dir):
    html = build(plain_dir / "deck.html")
    head = html[:html.index("</head>")]
    first_script = head.index("<script")
    assert first_script < head.index("<style")
    assert head.index("<!-- deck-prepaint:start -->") < first_script
    pre = region(html, "deck-prepaint")
    assert "slide-theme" in pre and "theme-" in pre
    assert "prefers-color-scheme" in pre
    assert "try" in pre and "catch" in pre


def test_title_lang_and_slides(plain_dir):
    out = plain_dir / "deck.html"
    run("--title", "Fish & Chips <live>", "--lang", "de", "--slides", SLIDES, "--out", out)
    html = out.read_text("utf-8")
    assert '<html lang="de">' in html
    assert "<title>Fish &amp; Chips &lt;live&gt;</title>" in html
    assert html.count('<section class="slide') == 3
    assert "Neutral sample text for the tooling tests." in html


def test_without_slides_gives_a_title_slide(plain_dir):
    out = plain_dir / "deck.html"
    run("--title", "Only a title", "--out", out)
    html = out.read_text("utf-8")
    assert html.count('<section class="slide') == 1
    assert "Only a title" in html[html.index("<body"):]


def test_fragment_without_a_slide_is_refused(plain_dir):
    proc = run("--title", "x", "--slides", TOOLING / "no-slides.html", "--out", plain_dir / "d.html", check=False)
    assert proc.returncode != 0
    assert "slide" in proc.stderr
    assert not (plain_dir / "d.html").exists()


def test_unknown_preset_is_refused(plain_dir):
    proc = run("--title", "x", "--preset", "no-such-preset", "--out", plain_dir / "d.html", check=False)
    assert proc.returncode != 0
    assert "no-such-preset" in proc.stderr


def test_existing_file_is_not_overwritten_without_force(plain_dir):
    out = plain_dir / "deck.html"
    out.write_text("keep me", encoding="utf-8")
    proc = run("--title", "x", "--out", out, check=False)
    assert proc.returncode != 0 and out.read_text("utf-8") == "keep me"
    run("--title", "x", "--out", out, "--force")
    assert "<!-- slide-engine:js:start -->" in out.read_text("utf-8")


# --- preset choice -------------------------------------------------------------------------

def default_slug() -> str:
    return next(p.stem for p in (SKILL / "presets").glob("*.yaml")
                if not p.name.startswith("_") and load_preset(p.stem).get("default") is True)


def test_no_design_md_uses_the_default_style_preset(plain_dir):
    html = build(plain_dir / "deck.html")
    slug = default_slug()
    assert "/* deck-preset: %s */" % slug in region(html, "deck-tokens")
    accent = load_preset(slug)["colors"]["dark"]["accent"]
    assert accent in region(html, "deck-tokens")


def test_design_md_found_above_the_output_selects_the_design_preset(brand_dir):
    html = build(brand_dir / "deck.html")
    tokens = region(html, "deck-tokens")
    assert "/* deck-preset: design */" in tokens
    assert "#2F5D8A" in tokens and "#8DB4E2" in tokens, "accent from DESIGN.md, both modes"
    assert ".theme-dark" in tokens and ".theme-light" in tokens
    assert "/* deck-tokens:begin */" in tokens and "/* deck-tokens:end */" in tokens


def test_explicit_design_path_selects_the_design_preset(plain_dir):
    html = build(plain_dir / "deck.html", "--design", TOOLING / "DESIGN.md")
    assert "/* deck-preset: design */" in region(html, "deck-tokens")


def test_explicit_style_preset_beats_design_md(brand_dir):
    html = build(brand_dir / "deck.html", "--preset", "paper-ink")
    tokens = region(html, "deck-tokens")
    assert "/* deck-preset: paper-ink */" in tokens
    assert "#2F5D8A" not in tokens


def test_design_preset_without_design_md_is_refused(plain_dir):
    proc = run("--title", "x", "--preset", "design", "--out", plain_dir / "d.html", check=False)
    assert proc.returncode != 0
    assert "DESIGN.md" in proc.stderr


# --- fonts ---------------------------------------------------------------------------------

def test_fonts_are_embedded_by_default(plain_dir):
    fonts = region(build(plain_dir / "deck.html"), "deck-fonts")
    assert "@font-face" in fonts and "data:font/woff2;base64," in fonts


def test_no_embed_fonts_leaves_an_empty_font_region(plain_dir):
    html = build(plain_dir / "deck.html", "--no-embed-fonts")
    assert "@font-face" not in region(html, "deck-fonts")
    assert "data:font/woff2" not in html


def test_design_preset_embeds_the_design_md_families(brand_dir):
    fonts = region(build(brand_dir / "deck.html"), "deck-fonts")
    for family in ("Playfair Display", "Inter", "JetBrains Mono"):
        assert 'font-family: "%s"' % family in fonts, family


def test_font_face_wrapper_embeds_every_weight(plain_dir):
    """font-face.py delegates to embed-fonts.py: a display weight 800 is embedded, not faked."""
    ff = load_script("font-face.py")
    block = ff.font_face_block(ff.collect_roles(load_preset("swiss-modern")))
    assert block.startswith("<style>") and block.rstrip().endswith("</style>")
    assert re.search(r'font-family: "Inter Tight"; font-style: normal; font-weight: 800;', block)
    assert 'font-family: "JetBrains Mono"' in block


def test_font_face_cli_matches_the_deck_region(plain_dir):
    slug = default_slug()
    proc = subprocess.run([sys.executable, str(SKILL / "scripts" / "font-face.py"), slug],
                          capture_output=True, text=True, check=True)
    html = build(plain_dir / "deck.html")
    assert proc.stdout.strip() == region(html, "deck-fonts").strip()


# --- refresh -------------------------------------------------------------------------------

def test_refresh_twice_gives_the_same_bytes(plain_dir):
    out = plain_dir / "deck.html"
    built = build(out)
    run("--refresh", out)
    once = out.read_bytes()
    run("--refresh", out)
    assert out.read_bytes() == once
    assert once.decode("utf-8") == built, "a fresh build is already refreshed"


def test_refresh_keeps_everything_outside_the_regions(brand_dir):
    out = brand_dir / "deck.html"
    html = build(out)
    edited = html.replace("Closing sample text.", "Edited by hand.")
    stale = re.sub(r"(<!-- slide-engine:js:start -->).*?(<!-- slide-engine:js:end -->)",
                   r"\1<script>/* old engine */</script>\2", edited, flags=re.S)
    out.write_text(stale, encoding="utf-8")
    run("--refresh", out)
    refreshed = out.read_text("utf-8")
    assert "Edited by hand." in refreshed
    assert "old engine" not in refreshed
    assert outside(refreshed) == outside(stale)
    assert "/* deck-preset: design */" in region(refreshed, "deck-tokens"), "preset read back from the deck"


def test_refresh_follows_a_changed_design_md(brand_dir):
    out = brand_dir / "deck.html"
    build(out)
    design = brand_dir.parent / "DESIGN.md"
    design.write_text(design.read_text("utf-8").replace("#2F5D8A", "#24507A"), encoding="utf-8")
    run("--refresh", out)
    tokens = region(out.read_text("utf-8"), "deck-tokens")
    assert "#24507A" in tokens and "#2F5D8A" not in tokens


def test_refresh_to_another_file(plain_dir):
    src = plain_dir / "deck.html"
    build(src)
    before = src.read_bytes()
    dst = plain_dir / "copy.html"
    run("--refresh", src, "--out", dst)
    assert src.read_bytes() == before and dst.read_bytes() == before


def test_refresh_without_markers_is_refused(plain_dir):
    f = plain_dir / "bare.html"
    f.write_text("<!DOCTYPE html><html><body><p>no markers</p></body></html>", encoding="utf-8")
    proc = run("--refresh", f, check=False)
    assert proc.returncode != 0
    assert f.read_text("utf-8").endswith("</html>")


@pytest.mark.parametrize("name", sorted(p.name for p in COMPAT.glob("*.html")))
def test_refresh_fills_old_decks_and_touches_nothing_else(tmp_path, name):
    deck = tmp_path / name
    shutil.copyfile(COMPAT / name, deck)
    original = deck.read_text("utf-8")
    run("--refresh", deck)
    once = deck.read_text("utf-8")
    assert outside(once) == outside(original)
    assert region(once, "slide-engine:css") == "\n" + SINK + (ASSETS / "slide-engine.css").read_text("utf-8")
    for name_ in ("deck-tokens", "deck-fonts", "deck-prepaint"):
        assert "<!-- %s:start -->" % name_ not in once, "no region is added to an old deck"
    run("--refresh", deck)
    assert deck.read_text("utf-8") == once


@pytest.mark.parametrize("name", sorted(p.name for p in COMPAT.glob("*.html")))
def test_refreshed_old_decks_still_load(open_html, tmp_path, name):
    deck = tmp_path / name
    shutil.copyfile(COMPAT / name, deck)
    run("--refresh", deck)
    page = open_html(deck.read_text("utf-8"))
    page.wait_for_selector(".deck-progress", state="attached")
    page.wait_for_timeout(200)
    assert page.errors == []
    assert page.evaluate(FIRST_RULE) == "0px", "the engine's first rule survives its marker"


# --- stage ---------------------------------------------------------------------------------

STAGE_ASSETS = [ASSETS / "slide-stage.css", ASSETS / "slide-stage.js"]
needs_stage = pytest.mark.skipif(not all(p.exists() for p in STAGE_ASSETS),
                                 reason="assets/slide-stage.{css,js} not built yet")


@needs_stage
def test_with_stage_splices_the_stage_assets(plain_dir):
    html = build(plain_dir / "deck.html", "--with-stage")
    css = (ASSETS / "slide-stage.css").read_text("utf-8")
    js = (ASSETS / "slide-stage.js").read_text("utf-8")
    assert region(html, "slide-stage:css") == "\n" + SINK + css
    assert region(html, "slide-stage:js") == "\n<script>\n" + js + "\n</script>\n"
    assert html.index("<!-- slide-engine:js:end -->") < html.index("<!-- slide-stage:js:start -->"), \
        "the stage runs after the engine it listens to"
    out = plain_dir / "deck.html"
    run("--refresh", out)
    assert out.read_text("utf-8") == html


def test_with_stage_without_assets_is_refused(plain_dir, tmp_path):
    """Run a copy of both skills whose html-slides lacks the stage assets."""
    tree = tmp_path / "tree" / "skills"
    skip = shutil.ignore_patterns("tests", "__pycache__", "examples", "slide-stage.*")
    for name in ("html-slides", "html-canvas"):
        shutil.copytree(SKILL.parent / name, tree / name, ignore=skip)
    assert not (tree / "html-slides" / "assets" / "slide-stage.js").exists()
    script = tree / "html-slides" / "scripts" / "new-deck.py"
    proc = subprocess.run([sys.executable, str(script), "--title", "x", "--with-stage", "--out",
                           str(plain_dir / "d.html")], capture_output=True, text=True)
    assert proc.returncode != 0 and "slide-stage" in proc.stderr, proc.stdout + proc.stderr
    assert not (plain_dir / "d.html").exists()


# --- in the browser ------------------------------------------------------------------------

BG = "() => getComputedStyle(document.documentElement).getPropertyValue('--bg').trim()"
# slide-engine.css opens with `* { margin: 0 ... }`: a marker name glued onto it would void it.
FIRST_RULE = "() => getComputedStyle(document.body).marginTop"


def test_design_deck_switches_theme_offline(open_html, page, brand_dir):
    html = build(brand_dir / "deck.html")
    page.emulate_media(color_scheme="light")
    open_html(html)
    page.wait_for_selector(".theme-toggle", state="attached")
    page.evaluate("() => document.fonts.ready")
    assert page.errors == []
    assert page.evaluate("() => document.documentElement.classList.contains('theme-light')")
    assert page.evaluate(BG).upper() == "#FAFAF7"
    page.keyboard.press("t")
    assert page.evaluate("() => document.documentElement.classList.contains('theme-dark')")
    assert page.evaluate(BG).upper() == "#141412"
    assert page.evaluate("() => document.fonts.check('500 32px \"Playfair Display\"')")
    assert page.evaluate(FIRST_RULE) == "0px", "the engine's first rule survives its marker"


def test_prepaint_follows_the_os_without_saving(open_html, page, brand_dir):
    html = build(brand_dir / "deck.html")
    page.emulate_media(color_scheme="dark")
    open_html(html)
    page.evaluate("() => localStorage.removeItem('slide-theme')")
    page.reload()
    page.wait_for_selector(".theme-toggle", state="attached")
    assert page.evaluate("() => document.documentElement.classList.contains('theme-dark')")
    assert page.evaluate("() => localStorage.getItem('slide-theme')") is None
    page.emulate_media(color_scheme="light")


def test_a_design_md_above_the_project_root_is_ignored(tmp_path):
    """A stray DESIGN.md in a temp or home folder must not brand a deck built below it."""
    shutil.copyfile(TOOLING / "DESIGN.md", tmp_path / "DESIGN.md")
    project = tmp_path / "project"
    (project / "decks").mkdir(parents=True)
    (project / ".git").mkdir()
    html = build(project / "decks" / "deck.html")
    assert "/* deck-preset: %s */" % default_slug() in region(html, "deck-tokens")


def test_deck_attr_sets_engine_options_on_the_deck(plain_dir):
    html = build(plain_dir / "deck.html", "--deck-attr", "data-tracks-default=short",
                 "--deck-attr", 'data-back-label=Zurück "home"', "--deck-attr", "data-counter-format=padded")
    tag = re.search(r'<div class="deck"[^>]*>', html).group(0)
    assert 'data-tracks-default="short"' in tag and 'data-counter-format="padded"' in tag
    assert 'data-back-label="Zurück &quot;home&quot;"' in tag


@pytest.mark.parametrize("bad", ["tracks-default=short", "data-x", "onload=alert(1)", "data-=x"])
def test_deck_attr_takes_only_data_attributes(plain_dir, bad):
    proc = run("--title", "x", "--out", plain_dir / "d.html", "--deck-attr", bad, check=False)
    assert proc.returncode != 0 and "--deck-attr" in proc.stderr


# --- deck modules (--with) -----------------------------------------------------------------

MODULE_FX = FIXTURES / "modules"


@pytest.fixture(scope="module")
def module_tree(tmp_path_factory):
    """A copy of both skills whose assets/modules holds the probe fixture (js + css) and a
    js-only module `beta`, so --with runs against modules this test controls."""
    tree = tmp_path_factory.mktemp("modtree") / "skills"
    skip = shutil.ignore_patterns("tests", "__pycache__", "examples")
    for name in ("html-slides", "html-canvas"):
        shutil.copytree(SKILL.parent / name, tree / name, ignore=skip)
    mods = tree / "html-slides" / "assets" / "modules"
    mods.mkdir(exist_ok=True)
    for f in mods.iterdir():
        f.unlink()
    shutil.copyfile(MODULE_FX / "probe.js", mods / "probe.js")
    shutil.copyfile(MODULE_FX / "probe.css", mods / "probe.css")
    (mods / "beta.js").write_text("/* beta: js only */\nwindow.__beta = 1;\n", encoding="utf-8")
    return tree / "html-slides"


def run_in(tree: Path, *args, check=True):
    proc = subprocess.run([sys.executable, str(tree / "scripts" / "new-deck.py"), *map(str, args)],
                          capture_output=True, text=True)
    if check and proc.returncode != 0:
        raise AssertionError("new-deck failed (%d):\n%s\n%s" % (proc.returncode, proc.stdout, proc.stderr))
    return proc


def module_names(html: str) -> list[str]:
    return re.findall(r"<!-- deck-module:([a-z0-9-]+):start -->", html)


def test_with_inlines_a_module_after_the_engine(module_tree, plain_dir):
    out = plain_dir / "deck.html"
    run_in(module_tree, "--title", "M", "--out", out, "--no-embed-fonts", "--with", "probe")
    html = out.read_text("utf-8")
    body = region(html, "deck-module:probe")
    css = (module_tree / "assets" / "modules" / "probe.css").read_text("utf-8")
    js = (module_tree / "assets" / "modules" / "probe.js").read_text("utf-8")
    assert body == "\n<style>\n" + css + "</style>\n<script>\n" + js + "\n</script>\n"
    assert html.index("<!-- slide-engine:js:end -->") < html.index("<!-- deck-module:probe:start -->")
    assert html.index("<!-- deck-module:probe:end -->") < html.index("</body>")
    assert module_names(html) == ["probe"]


def test_with_all_and_repeated_with(module_tree, plain_dir):
    out = plain_dir / "all.html"
    run_in(module_tree, "--title", "M", "--out", out, "--no-embed-fonts", "--with", "all")
    html = out.read_text("utf-8")
    assert module_names(html) == ["beta", "probe"]
    assert "<style>" not in region(html, "deck-module:beta"), "no empty style for a js-only module"
    out2 = plain_dir / "two.html"
    run_in(module_tree, "--title", "M", "--out", out2, "--no-embed-fonts", "--with", "probe", "--with", "beta",
           "--with", "probe")
    assert module_names(out2.read_text("utf-8")) == ["beta", "probe"], "one region each, in a stable order"


def test_with_stage_and_modules_keep_their_order(module_tree, plain_dir):
    out = plain_dir / "s.html"
    run_in(module_tree, "--title", "M", "--out", out, "--no-embed-fonts", "--with-stage", "--with", "probe")
    html = out.read_text("utf-8")
    assert html.index("<!-- slide-stage:js:end -->") < html.index("<!-- deck-module:probe:start -->")


def test_unknown_module_lists_the_available_ones(module_tree, plain_dir):
    proc = run_in(module_tree, "--title", "M", "--out", plain_dir / "x.html", "--with", "nope", check=False)
    assert proc.returncode != 0
    assert "nope" in proc.stderr and "beta" in proc.stderr and "probe" in proc.stderr, proc.stderr
    assert not (plain_dir / "x.html").exists()


def test_refresh_keeps_the_module_set_and_refreshes_code(module_tree, plain_dir, tmp_path):
    out = plain_dir / "r.html"
    run_in(module_tree, "--title", "M", "--out", out, "--no-embed-fonts", "--with", "probe")
    html = out.read_text("utf-8")
    stale = html.replace("window.__probe =", "window.__probe_old =")
    out.write_text(stale, encoding="utf-8")
    run_in(module_tree, "--refresh", out)
    again = out.read_text("utf-8")
    assert again == html, "the code is refreshed from the asset, nothing else changes"
    assert module_names(again) == ["probe"], "beta is not added by a refresh"
    run_in(module_tree, "--refresh", out)
    assert out.read_text("utf-8") == html, "idempotent"


def test_refresh_refuses_with(module_tree, plain_dir):
    out = plain_dir / "rw.html"
    run_in(module_tree, "--title", "M", "--out", out, "--no-embed-fonts")
    proc = run_in(module_tree, "--refresh", out, "--with", "probe", check=False)
    assert proc.returncode != 0 and "--with" in proc.stderr


def test_refresh_with_a_module_gone_is_an_error(module_tree, plain_dir):
    out = plain_dir / "gone.html"
    run_in(module_tree, "--title", "M", "--out", out, "--no-embed-fonts", "--with", "probe")
    html = out.read_text("utf-8").replace("deck-module:probe:", "deck-module:vanished:")
    out.write_text(html, encoding="utf-8")
    proc = run_in(module_tree, "--refresh", out, check=False)
    assert proc.returncode != 0 and "vanished" in proc.stderr
    assert out.read_text("utf-8") == html, "nothing written"


def test_shipped_modules_are_splice_safe():
    """Every module under assets/modules can be inlined: no closing style or script tag."""
    mods = ASSETS / "modules"
    for f in sorted(mods.glob("*.js")) if mods.is_dir() else []:
        assert "</script" not in f.read_text("utf-8").lower(), f.name
        css = f.with_suffix(".css")
        if css.exists():
            assert "</style" not in css.read_text("utf-8").lower(), css.name


def test_module_deck_runs_in_the_browser(module_tree, plain_dir, open_html, page):
    out = plain_dir / "b.html"
    run_in(module_tree, "--title", "M", "--out", out, "--no-embed-fonts", "--with", "all")
    open_html(out.read_text("utf-8"))
    page.wait_for_function("() => window.__probe && window.__probe.inits === 1 && window.__beta === 1")
    assert page.errors == []
