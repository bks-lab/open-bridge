"""new-page.py builds a catalog page, and sections.css is the one home of every block's CSS."""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

from canvas_testlib import ASSETS, FIXTURES, REPO, SCRIPTS, SKILL

SCRIPT = SCRIPTS / "new-page.py"
VERIFY = SCRIPTS / "verify-page.py"
SECTIONS_MD = SKILL / "references" / "sections.md"
SECTIONS_CSS = ASSETS / "sections.css"
PAGES = Path(__file__).resolve().parent / "fixtures" / "pages"
DESIGN = Path(__file__).resolve().parent / "fixtures" / "tokens" / "design-current.md"

BLOCK_HEADING = re.compile(r'^## <a id="([a-z0-9-]+)"></a>', re.M)
CSS_BLOCK = re.compile(r"^/\* @block: ([a-z0-9-]+)(?: requires: ([a-z0-9, -]+))? \*/$", re.M)
CLASS_USE = re.compile(r'\bclass="([^"]*)"')
CLASS_DEF = re.compile(r"\.([A-Za-z_][\w-]*)")
DASHES = ("\u2014", "\u2013", " -- ")


def catalog() -> list[str]:
    return BLOCK_HEADING.findall(SECTIONS_MD.read_text("utf-8"))


def block_markup(name: str) -> str:
    text = SECTIONS_MD.read_text("utf-8")
    start = text.index('<a id="%s"></a>' % name)
    nxt = text.find("\n## ", start)
    body = text[start: nxt if nxt != -1 else len(text)]
    m = re.search(r"```html\n(.*?)```", body, re.S)
    assert m, "no html fence for block %s" % name
    return m.group(1)


def css_blocks() -> dict[str, tuple[list[str], str]]:
    text = SECTIONS_CSS.read_text("utf-8")
    marks = list(CSS_BLOCK.finditer(text))
    out = {}
    for i, m in enumerate(marks):
        end = marks[i + 1].start() if i + 1 < len(marks) else len(text)
        reqs = [r.strip() for r in (m.group(2) or "").split(",") if r.strip()]
        out[m.group(1)] = (reqs, text[m.end():end])
    return out


def resolved_css(name: str) -> str:
    blocks = css_blocks()
    seen: list[str] = []

    def walk(n: str) -> None:
        if n in seen or n == "animations":
            return
        for r in blocks[n][0]:
            walk(r)
        seen.append(n)

    walk("base")
    walk(name)
    css = "".join(blocks[n][1] for n in seen)
    if "animations" in {r for n in seen for r in blocks[n][0]}:
        css += (ASSETS / "animations.css").read_text("utf-8")
    return css


def defined_classes(css: str) -> set[str]:
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r"\{[^{}]*\}", "{}", css)  # keep selectors, drop declaration bodies
    css = re.sub(r"\{[^{}]*\}", "{}", css)
    return set(CLASS_DEF.findall(css))


def used_classes(markup: str) -> set[str]:
    return {c for m in CLASS_USE.finditer(markup) for c in m.group(1).split()}


def run(*args, scripts=SCRIPT, **kw) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(scripts), *args], capture_output=True, text=True, **kw)


def build(tmp_path, *args, name="page.html") -> tuple[Path, subprocess.CompletedProcess]:
    out = tmp_path / name
    r = run("--out", str(out), "--design", str(DESIGN), *args)
    return out, r


# --- the catalog and its single CSS file ----------------------------------------------

def test_catalog_lists_the_decision_page():
    assert "decision-page" in catalog()


def test_every_catalog_block_has_a_css_block():
    missing = [b for b in catalog() if b not in css_blocks()]
    assert not missing, "blocks without CSS in sections.css: %s" % missing


def test_every_requires_target_exists():
    blocks = css_blocks()
    for name, (reqs, _) in blocks.items():
        for r in reqs:
            assert r == "animations" or r in blocks, "%s requires unknown %s" % (name, r)


def test_css_block_names_are_unique():
    names = CSS_BLOCK.findall(SECTIONS_CSS.read_text("utf-8"))
    dup = {n for n, _ in names if [x for x, _ in names].count(n) > 1}
    assert not dup, "block defined twice: %s" % dup


def test_sections_md_no_longer_carries_css_fences():
    assert "```css" not in SECTIONS_MD.read_text("utf-8")
    assert "sections.css" in SECTIONS_MD.read_text("utf-8")


@pytest.mark.parametrize("block", catalog())
def test_block_markup_uses_no_undefined_class(block):
    shell_css = (ASSETS / "shell.html").read_text("utf-8")
    known = defined_classes(resolved_css(block)) | defined_classes(shell_css)
    undefined = sorted(used_classes(block_markup(block)) - known)
    assert not undefined, "%s uses classes no CSS defines: %s" % (block, undefined)


def test_no_dash_punctuation_in_shipped_files():
    for path in (SECTIONS_CSS, SECTIONS_MD, SCRIPT):
        text = path.read_text("utf-8")
        for d in DASHES:
            assert d not in text, "%r in %s" % (d, path.name)


def test_decision_page_is_bilingual_and_complete():
    markup = block_markup("decision-page")
    assert markup.count("data-de") == markup.count("data-en") > 8
    for part in ("dec-options", "dec-criteria", "dec-reco", "dec-open"):
        assert part in markup, part
    assert "tbl-wrap" in markup and "recommended" in markup


# --- building a page ------------------------------------------------------------------

@pytest.mark.parametrize("block", catalog())
def test_each_block_builds_a_verify_green_page(block, tmp_path):
    out, r = build(tmp_path, "--blocks", block, "--title", "Fixture page")
    assert r.returncode == 0, r.stdout + r.stderr
    text = out.read_text("utf-8")
    assert re.search(r"/\* @block: %s\b" % block, text)
    assert "{{" not in text and "<!--@" not in text
    assert "<script src=" not in text and "<link " not in text
    v = run(str(out), "--design", str(DESIGN), "--allow-sample", scripts=VERIFY)
    assert v.returncode == 0, v.stdout


def test_a_fresh_page_is_marked_as_sample_until_its_text_is_written(tmp_path):
    """The catalog text is a sample: new-page passes it with a warning, the send gate does not."""
    out, r = build(tmp_path, "--blocks", "doc-header,callout,table")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "sample" in r.stdout
    text = out.read_text("utf-8")
    assert 'id="blk-callout" data-sample' in text and 'id="blk-table" data-sample' in text
    v = run(str(out), "--design", str(DESIGN), scripts=VERIFY)
    assert v.returncode == 1 and "sample" in v.stdout, v.stdout


def test_catalog_callout_is_bilingual():
    assert "<b>Note</b>" not in block_markup("callout")


def test_all_blocks_page_defines_each_rule_set_once(tmp_path):
    out, r = build(tmp_path, "--blocks", "all")
    assert r.returncode == 0, r.stdout + r.stderr
    text = out.read_text("utf-8")
    marks = re.findall(r"/\* @block: ([a-z0-9-]+)", text)
    assert len(marks) == len(set(marks)), "a block's CSS is in the page twice"
    assert text.count("/* sections:begin */") == 1 and text.count("/* sections:end */") == 1
    region = text.split("/* sections:begin */", 1)[1].split("/* sections:end */", 1)[0]
    assert region.count("--core-bg:") == 1  # the lens triads, once, for every block that needs them
    assert text.count("@keyframes hc-msg-fwd") == 1


def test_title_lang_date_footer(tmp_path):
    out, r = build(tmp_path, "--title-de", "Lagebild", "--title-en", "Situation", "--lang", "de",
                   "--date", "2026-02-03", "--footer", "unit test")
    assert r.returncode == 0, r.stdout + r.stderr
    text = out.read_text("utf-8")
    assert '<html lang="de"' in text and "<title>Lagebild</title>" in text
    assert "<span data-de>Lagebild</span><span data-en>Situation</span>" in text
    assert "2026-02-03" in text and "unit test" in text
    assert "|| 'de')" in text and "'data-lang', 'de')" in text
    swap = re.findall(r':root[^{]*\[data-(?:de|en)\][^{]*\{display:none\}', text)
    assert len(swap) == 2 and 'data-lang="en"' in swap[0]


def test_title_is_escaped(tmp_path):
    out, r = build(tmp_path, "--title", "A <b> & C")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "A &lt;b&gt; &amp; C" in out.read_text("utf-8")


def test_section_nav_points_at_blocks_that_exist(tmp_path):
    out, r = build(tmp_path, "--blocks", "section-nav,table,callout")
    assert r.returncode == 0, r.stdout + r.stderr
    text = out.read_text("utf-8")
    targets = set(re.findall(r'href="#([^"]+)"', text))
    ids = set(re.findall(r'\bid="([^"]+)"', text))
    assert targets and targets <= ids


def test_unknown_block_is_refused(tmp_path):
    out, r = build(tmp_path, "--blocks", "table,nonsense")
    assert r.returncode != 0 and "nonsense" in r.stderr and not out.exists()


def test_out_is_required_and_existing_file_needs_force(tmp_path):
    assert run().returncode != 0
    out, r = build(tmp_path)
    assert r.returncode == 0
    again = run("--out", str(out), "--design", str(DESIGN))
    assert again.returncode != 0 and "--force" in again.stderr
    assert run("--out", str(out), "--design", str(DESIGN), "--force").returncode == 0


def test_list_names_blocks():
    r = run("--list")
    assert r.returncode == 0
    for b in ("table", "decision-page", "message-flow"):
        assert b in r.stdout


def test_embed_fonts_is_opt_in(tmp_path):
    plain, r1 = build(tmp_path, name="plain.html")
    fonts, r2 = build(tmp_path, "--embed-fonts", name="fonts.html")
    assert r1.returncode == 0 and r2.returncode == 0, r2.stderr
    assert "@font-face" not in plain.read_text("utf-8")
    assert "@font-face" in fonts.read_text("utf-8")
    assert fonts.read_text("utf-8").count("/* page-fonts:begin */") == 1


# --- verify gate ----------------------------------------------------------------------

def test_verify_errors_give_a_nonzero_exit(tmp_path):
    page = tmp_path / "broken.html"
    page.write_text((PAGES / "broken.html").read_text("utf-8"), encoding="utf-8")
    r = run("--refresh", str(page))
    assert r.returncode != 0
    assert "external-url" in r.stdout


# --- refresh --------------------------------------------------------------------------

def test_refresh_of_a_fresh_page_changes_nothing(tmp_path):
    out, r = build(tmp_path, "--blocks", "doc-header,table,swimlane,message-flow,decision-page")
    assert r.returncode == 0
    before = out.read_bytes()
    for _ in range(2):
        rr = run("--refresh", str(out), "--design", str(DESIGN))
        assert rr.returncode == 0, rr.stdout + rr.stderr
        assert out.read_bytes() == before


def test_refresh_leaves_the_content_alone(tmp_path):
    out, _ = build(tmp_path, "--blocks", "callout")
    text = out.read_text("utf-8").replace("</main>", "<p data-de>Mein Text</p><p data-en>My text</p></main>")
    out.write_text(text, encoding="utf-8")
    assert run("--refresh", str(out), "--design", str(DESIGN)).returncode == 0
    assert "My text" in out.read_text("utf-8")


def test_refresh_follows_a_changed_sections_css(tmp_path):
    out, _ = build(tmp_path, "--blocks", "callout")
    stale = out.read_text("utf-8").replace(".note{", ".note{outline:1px solid red;", 1)
    out.write_text(stale, encoding="utf-8")
    assert run("--refresh", str(out), "--design", str(DESIGN)).returncode == 0
    fresh = out.read_text("utf-8")
    assert "outline:1px solid red" not in fresh and fresh.count(".note{") == 1


def test_refresh_blocks_flag_swaps_the_css_set(tmp_path):
    out, _ = build(tmp_path, "--blocks", "callout")
    assert run("--refresh", str(out), "--design", str(DESIGN), "--blocks", "callout,chips").returncode == 0
    text = out.read_text("utf-8")
    assert "/* @block: chips */" in text and text.count("/* @block: callout */") == 1


def test_refresh_regenerates_tokens(tmp_path):
    out, _ = build(tmp_path)
    mangled = out.read_text("utf-8").replace("--primary:", "--primary-stale:", 1)
    out.write_text(mangled, encoding="utf-8")
    assert run("--refresh", str(out), "--design", str(DESIGN)).returncode == 0
    text = out.read_text("utf-8")
    assert text.count("/* design-tokens:begin */") == 1 and text.count("generated from DESIGN.md") == 1


def test_refresh_adds_fonts_only_when_asked(tmp_path):
    out, _ = build(tmp_path)
    assert run("--refresh", str(out), "--design", str(DESIGN)).returncode == 0
    assert "@font-face" not in out.read_text("utf-8")
    assert run("--refresh", str(out), "--design", str(DESIGN), "--embed-fonts").returncode == 0
    with_fonts = out.read_bytes()
    assert b"@font-face" in with_fonts
    assert run("--refresh", str(out), "--design", str(DESIGN)).returncode == 0  # keeps what is there
    assert out.read_bytes() == with_fonts


@pytest.mark.parametrize("fixture, lang", [("legacy-lang.html", "de"), ("current-lang.html", "en")])
def test_refresh_normalises_either_language_swap_form_without_duplicates(fixture, lang, tmp_path):
    page = tmp_path / fixture
    page.write_text((PAGES / fixture).read_text("utf-8"), encoding="utf-8")
    original_main = re.search(r"<main.*?</main>", page.read_text("utf-8"), re.S).group(0)
    for _ in range(2):
        r = run("--refresh", str(page), "--design", str(DESIGN))
        assert r.returncode == 0, r.stdout + r.stderr
    text = page.read_text("utf-8")
    rules = re.findall(r':root[^{\n]*\[data-(?:de|en)\][^{\n]*\{display:none\}', text)
    assert len(rules) == 2, rules
    other = "en" if lang == "de" else "de"
    assert all(":not([data-" in r for r in rules), "the pair-safe form is the one kept"
    assert re.search(r':root:not\(\[data-lang="%s"\]\) \[data-%s\]:not\(\[data-%s\]\)' % (other, other, lang), text)
    assert re.search(r"<main.*?</main>", text, re.S).group(0) == original_main
    assert '<html lang="%s"' % lang in text


def test_refresh_without_a_sections_region_leaves_the_rest_alone(tmp_path):
    page = tmp_path / "legacy.html"
    page.write_text((PAGES / "legacy-lang.html").read_text("utf-8"), encoding="utf-8")
    r = run("--refresh", str(page), "--design", str(DESIGN))
    assert r.returncode == 0
    assert "sections:begin" not in page.read_text("utf-8")
    assert "body{margin:0;background:var(--surface);color:var(--ink)}" in page.read_text("utf-8")


def test_refresh_refuses_a_missing_page(tmp_path):
    r = run("--refresh", str(tmp_path / "nope.html"))
    assert r.returncode != 0


# --- the real thing, in a browser -----------------------------------------------------

def test_all_blocks_page_runs_offline_from_an_empty_dir(tmp_path, open_page):
    out, r = build(tmp_path, "--blocks", "all", "--embed-fonts")
    assert r.returncode == 0, r.stdout + r.stderr
    page = open_page(out.read_text("utf-8"))
    assert page.errors == []
    assert page.locator("h1:visible").count() >= 1
    vis_de = page.locator("[data-de]:not([data-en]):visible").count()
    assert vis_de == 0, "German is visible while the page is English"
    page.keyboard.press("l")
    assert page.locator("[data-en]:not([data-de]):visible").count() == 0
    assert page.locator("[data-de]:not([data-en]):visible").count() > 0
    width = page.evaluate("document.documentElement.scrollWidth")
    assert width <= 900 + 2, "page scrolls sideways at 900 px: %s" % width


def test_verify_browser_pass_is_green_on_a_generated_page(tmp_path):
    pytest.importorskip("playwright.sync_api")
    out, r = build(tmp_path, "--blocks", "all")
    assert r.returncode == 0
    v = run(str(out), "--design", str(DESIGN), "--browser", "--allow-sample", scripts=VERIFY)
    if "browser-skipped" in v.stdout:
        pytest.skip("chromium not available")
    assert v.returncode == 0, v.stdout


def test_refresh_replaces_tokens_of_a_page_generated_before_the_neutral_block(tmp_path):
    """Older pages hold generated tokens right after :begin, with no neutral block.

    A refresh must not keep that stale set in front of the new one: tokens the new
    DESIGN.md leaves out would inherit the old brand values instead of neutral ones.
    """
    page = tmp_path / "legacy-generated.html"
    page.write_text((PAGES / "legacy-generated.html").read_text("utf-8"), encoding="utf-8")
    r = run("--refresh", str(page), "--design", str(DESIGN))
    assert r.returncode == 0, r.stdout + r.stderr
    region = page.read_text("utf-8").split("/* design-tokens:begin */")[1].split("/* design-tokens:end */")[0]
    for stale in ("#123456", "#654321", "#abcdef", "#fedcba", "--stale-only", "(sample, 2026-01-01)"):
        assert stale not in region, stale
    assert region.count("Generated from DESIGN.md") == 1
    shell = (ASSETS / "shell.html").read_text("utf-8")
    neutral = shell.split("/* design-tokens:begin */")[1].split("/* design-tokens:end */")[0].strip()
    assert region.lstrip().startswith(neutral)
    once = page.read_bytes()
    assert run("--refresh", str(page), "--design", str(DESIGN)).returncode == 0
    assert page.read_bytes() == once


# --- block layout in the browser ------------------------------------------------------

def _left(page, sel):
    return page.evaluate("(s) => document.querySelector(s).getBoundingClientRect().left", sel)


def test_section_opener_lines_up_with_the_page_header(open_page, tmp_path):
    out, r = build(tmp_path, "--blocks", "doc-header,section-opener,pipeline")
    assert r.returncode == 0, r.stdout + r.stderr
    page = open_page(out.read_text("utf-8"), viewport={"width": 1280, "height": 900})
    assert abs(_left(page, "main h1") - _left(page, "#blk-section-opener h2")) < 1.5
    gap = page.evaluate("""() => document.querySelector('#blk-pipeline').getBoundingClientRect().top
                                 - document.querySelector('#blk-section-opener .lead[data-en]').getBoundingClientRect().bottom""")
    assert gap < 100, gap   # was 131 with the old 72 px bottom padding


def test_pipeline_stacks_cleanly_on_a_narrow_screen(open_page, tmp_path):
    out, r = build(tmp_path, "--blocks", "pipeline")
    page = open_page(out.read_text("utf-8"), viewport={"width": 600, "height": 900})
    boxes = page.evaluate("""() => [...document.querySelectorAll('.pipe > .pbox, .pipe > .arrow')].map(e => {
      const b = e.getBoundingClientRect(); return {cls: e.className, top: b.top, bottom: b.bottom, w: b.width}; })""")
    pboxes = [b for b in boxes if b["cls"] == "pbox"]
    assert len({round(b["w"]) for b in pboxes}) == 1, "every stage as wide as the next"
    for prev, cur in zip(boxes, boxes[1:]):
        assert cur["top"] >= prev["bottom"] - 1, "one item per row, in order: %r" % boxes
