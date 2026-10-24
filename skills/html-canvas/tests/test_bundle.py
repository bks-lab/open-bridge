"""bundle.py folds a page and everything it loads into one file with no external references."""
from __future__ import annotations

import base64
import hashlib
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

SKILL = Path(__file__).resolve().parents[1]
REPO = SKILL.parents[1]
SCRIPT = SKILL / "scripts" / "bundle.py"
WRAPPER = REPO / "skills" / "html-slides" / "scripts" / "inline-assets.py"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "bundle"
FONT_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "fonts"

PAYLOAD_RE = re.compile(
    r'<script type="text/plain" class="bundle-payload" id="(?P<id>[^"]+)" data-source="(?P<src>[^"]*)"[^>]*>'
    r'(?P<b64>[^<]*)</script>')


def run(script: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(script), *map(str, args)], capture_output=True, text=True)


@pytest.fixture
def tree(tmp_path) -> Path:
    """A private copy of the fixture tree, so a test can edit it freely."""
    dst = tmp_path / "src"
    shutil.copytree(FIXTURES, dst)
    return dst


@pytest.fixture
def bundled(tree, tmp_path):
    out = tmp_path / "out" / "bundle.html"
    out.parent.mkdir()
    r = run(SCRIPT, tree / "index.html", "--out", out)
    assert r.returncode == 0, r.stderr
    return out


def payloads(html: str) -> dict[str, tuple[str, bytes]]:
    return {m["id"]: (m["src"], base64.b64decode(m["b64"])) for m in PAYLOAD_RE.finditer(html)}


def without_payloads(html: str) -> str:
    return PAYLOAD_RE.sub("", html)


# ---- no external references ------------------------------------------------

def test_output_has_no_external_references(bundled):
    html = without_payloads(bundled.read_text("utf-8"))
    for attr, value in re.findall(r'\b(src|href|poster|data|srcset)\s*=\s*"([^"]*)"', html):
        if attr == "href" and value.startswith("https://example.com"):
            continue  # a hyperlink is navigation, not a load
        assert value == "" or value.startswith(("data:", "#")), (attr, value[:60])
    for arg in re.findall(r"url\(\s*([^)]*)\)", html):
        arg = arg.replace("&quot;", '"')
        assert arg.strip("'\" ").startswith(("data:", "#")), arg[:60]
    assert "@import" not in html
    assert not re.search(r"<link[^>]+rel=\"stylesheet\"", html)


def test_images_css_js_are_inlined_byte_exact(bundled, tree):
    html = bundled.read_text("utf-8")
    dot = (tree / "img" / "dot.png").read_bytes()
    assert "data:image/png;base64," + base64.b64encode(dot).decode() in html
    # the stylesheet became a <style> block, its url() assets became data URIs
    assert "<style" in html and ".hero" in html
    bg = (tree / "img" / "bg.png").read_bytes()
    assert base64.b64encode(bg).decode() in html
    face = (tree / "fonts" / "local-face.woff2").read_bytes()
    assert "data:font/woff2;base64," + base64.b64encode(face).decode() in html
    # the favicon too
    svg = (tree / "img" / "mark.svg").read_bytes()
    assert "data:image/svg+xml;base64," + base64.b64encode(svg).decode() in html
    # the script is inline and its embedded closing tag cannot end the block early
    assert "script ran" in html and '"<\\/script>"' in html
    assert '<script src=' not in html


def test_iframe_payloads_are_byte_equal_to_their_sources(bundled, tree):
    html = bundled.read_text("utf-8")
    found = payloads(html)
    plain = (tree / "frames" / "plain.html").read_bytes()
    by_source = {src: data for src, data in found.values()}
    assert by_source["frames/plain.html"] == plain
    # the same source used by two iframes is stored once
    assert sum(1 for src, _ in found.values() if src == "frames/plain.html") == 1
    assert len(re.findall(r'data-bundle="', html)) == 3
    assert "srcdoc" not in html.split("<script")[0]  # not hand-written into the markup


def test_nested_page_gets_its_own_assets_inlined(bundled, tree):
    found = {src: data for src, data in payloads(bundled.read_text("utf-8")).values()}
    nested = found["frames/nested.html"].decode("utf-8")
    assert "Überschrift ÄÖÜ" in nested
    dot = (tree / "img" / "dot.png").read_bytes()
    assert base64.b64encode(dot).decode() in nested
    assert "../" not in re.sub(r"base64,[A-Za-z0-9+/=]+", "", nested)
    assert "script ran" in nested


def test_umlauts_survive_in_file_and_payload(bundled):
    raw = bundled.read_bytes()
    assert "Übersicht: Größe äöüß".encode("utf-8") in raw
    assert b"&auml;" not in raw and b"\\u00e4" not in raw
    found = {src: data for src, data in payloads(raw.decode("utf-8")).values()}
    assert "Größe äöüß € Grüße".encode("utf-8") in found["frames/plain.html"]


def test_output_is_deterministic_and_stable_when_bundled_again(bundled, tmp_path):
    again = tmp_path / "again.html"
    assert run(SCRIPT, bundled, "--out", again).returncode == 0
    assert again.read_bytes() == bundled.read_bytes()


# ---- refusals ----------------------------------------------------------------

def test_remote_resource_is_refused_unless_allowed(tree, tmp_path):
    (tree / "remote.html").write_text(
        '<!doctype html><meta charset="utf-8"><img src="https://example.invalid/x.png">'
        '<link rel="stylesheet" href="//cdn.example.invalid/a.css">', encoding="utf-8")
    out = tmp_path / "o.html"
    r = run(SCRIPT, tree / "remote.html", "--out", out)
    assert r.returncode == 1
    assert "https://example.invalid/x.png" in r.stderr and "--allow-remote" in r.stderr
    assert not out.exists()
    r = run(SCRIPT, tree / "remote.html", "--out", out, "--allow-remote")
    assert r.returncode == 0
    assert "https://example.invalid/x.png" in out.read_text("utf-8")


def test_remote_url_inside_css_is_refused(tree, tmp_path):
    (tree / "css-remote.html").write_text(
        '<!doctype html><style>@import url("https://example.invalid/a.css");'
        '.x{background:url(https://example.invalid/b.png)}</style>', encoding="utf-8")
    r = run(SCRIPT, tree / "css-remote.html", "--out", tmp_path / "o.html")
    assert r.returncode == 1 and "example.invalid" in r.stderr


def test_missing_local_file_fails_and_lists_every_one(tree, tmp_path):
    (tree / "broken.html").write_text(
        '<!doctype html><img src="img/nope.png"><script src="nope.js"></script>', encoding="utf-8")
    r = run(SCRIPT, tree / "broken.html", "--out", tmp_path / "o.html")
    assert r.returncode == 1
    assert "img/nope.png" in r.stderr and "nope.js" in r.stderr


def test_local_page_link_needs_opt_in(tree, tmp_path):
    html = (tree / "index.html").read_text("utf-8").replace(
        "<script src=\"app.js\">", '<a id="to-second" href="pages/second.html#x">Zweite Seite</a>\n<script src="app.js">')
    (tree / "linked.html").write_text(html, encoding="utf-8")
    r = run(SCRIPT, tree / "linked.html", "--out", tmp_path / "o.html")
    assert r.returncode == 1 and "--pages" in r.stderr and "pages/second.html" in r.stderr


# ---- manifest ----------------------------------------------------------------

def test_hash_list_on_stderr_and_in_manifest(tree, tmp_path):
    out, man = tmp_path / "o.html", tmp_path / "hashes.txt"
    r = run(SCRIPT, tree / "index.html", "--out", out, "--manifest", man)
    assert r.returncode == 0
    lines = dict(reversed(ln.split("  ", 1)) for ln in man.read_text("utf-8").splitlines() if ln)
    for rel in ("index.html", "style.css", "app.js", "img/dot.png", "frames/plain.html", "frames/nested.html",
                "fonts/local-face.woff2"):
        assert lines[rel] == hashlib.sha256((tree / rel).read_bytes()).hexdigest(), rel
    # without --manifest the list goes to stderr
    r = run(SCRIPT, tree / "index.html", "--out", tmp_path / "o2.html")
    assert hashlib.sha256((tree / "app.js").read_bytes()).hexdigest() + "  app.js" in r.stderr


# ---- fonts -------------------------------------------------------------------

def test_fonts_from_design_are_embedded_when_the_page_uses_them(tree, tmp_path):
    out = tmp_path / "o.html"
    r = run(SCRIPT, tree / "index.html", "--out", out, "--design", tree / "fixture-design.md", "--font-dir", FONT_FIXTURES)
    assert r.returncode == 0, r.stderr
    html = out.read_text("utf-8")
    face = (FONT_FIXTURES / "fixture-sans-latin-400.woff2").read_bytes()
    assert base64.b64encode(face).decode() in html
    assert 'font-family: "Fixture Sans"' in html or "font-family:'Fixture Sans'" in html or "Fixture Sans" in html
    # the existing, already inlined @font-face is kept, not duplicated
    assert html.count('"Local Face"') == 1


def test_font_not_mentioned_by_the_page_is_not_embedded(tree, tmp_path):
    (tree / "plainpage.html").write_text('<!doctype html><meta charset="utf-8"><p>x</p>', encoding="utf-8")
    out = tmp_path / "o.html"
    r = run(SCRIPT, tree / "plainpage.html", "--out", out, "--design", tree / "fixture-design.md", "--font-dir", FONT_FIXTURES)
    assert r.returncode == 0
    assert "@font-face" not in out.read_text("utf-8")


# ---- browser: the file works alone ------------------------------------------

def _open_alone(browser, bundle: Path, tmp_path):
    """Copy only the bundle into an empty dir and open it over file://."""
    alone = tmp_path / "empty"
    alone.mkdir(exist_ok=True)
    target = alone / "bundle.html"
    shutil.copy(bundle, target)
    ctx = browser.new_context(viewport={"width": 900, "height": 800})
    page = ctx.new_page()
    page.errors, page.requests = [], []
    page.on("pageerror", lambda e: page.errors.append(str(e)))
    page.on("request", lambda rq: page.requests.append(rq.url))
    page.goto(target.as_uri())
    return ctx, page, target


def test_bundle_renders_alone_with_iframes(browser, bundled, tmp_path):
    ctx, page, target = _open_alone(browser, bundled, tmp_path)
    try:
        page.wait_for_function("document.querySelector('#f-nested').contentDocument.querySelector('#note').textContent.length > 0")
        assert page.eval_on_selector("#dot", "i => i.naturalWidth") == 1
        assert "Größe äöüß €" in page.inner_text("#note")
        plain = page.frame_locator("#f-plain")
        assert plain.locator("#p").inner_text() == "Größe äöüß € Grüße"
        nested = page.frame_locator("#f-nested")
        assert nested.locator("#h").inner_text() == "Überschrift ÄÖÜ"
        assert nested.locator("#note").inner_text() == "script ran: Größe äöüß €"
        assert page.frame_locator("#f-nested").locator("#dot").evaluate("i => i.naturalWidth") == 1
        # styles from the inlined stylesheet apply inside the frame
        assert nested.locator("#note").evaluate("e => getComputedStyle(e).color") == "rgb(0, 128, 0)"
        assert page.errors == []
        outside = [u for u in page.requests if not u.startswith(("data:", "blob:", "about:")) and u != target.as_uri()]
        assert outside == [], outside
    finally:
        ctx.close()


def test_lazy_iframe_waits_for_load_call(browser, bundled, tmp_path):
    ctx, page, _ = _open_alone(browser, bundled, tmp_path)
    try:
        assert page.eval_on_selector("#f-lazy", "f => f.hasAttribute('srcdoc')") is False
        page.evaluate("window.__bundle.load(document.querySelector('#f-lazy'))")
        assert page.frame_locator("#f-lazy").locator("#p").inner_text() == "Größe äöüß € Grüße"
    finally:
        ctx.close()


def test_linked_page_opens_from_payload(browser, tree, tmp_path):
    html = (tree / "index.html").read_text("utf-8").replace(
        '<script src="app.js">', '<a id="to-second" href="pages/second.html">Zweite Seite</a>\n<script src="app.js">')
    (tree / "linked.html").write_text(html, encoding="utf-8")
    out = tmp_path / "linked-out.html"
    r = run(SCRIPT, tree / "linked.html", "--out", out, "--pages")
    assert r.returncode == 0, r.stderr
    text = out.read_text("utf-8")
    assert "pages/second.html" not in without_payloads(text)
    second = (tree / "pages" / "second.html").read_bytes()
    assert any(src == "pages/second.html" for src, _ in payloads(text).values())
    ctx, page, _ = _open_alone(browser, out, tmp_path)
    try:
        with ctx.expect_page() as popup:
            page.click("#to-second")
        new = popup.value
        new.wait_for_load_state()
        assert new.inner_text("#h") == "Zweite Seite: Größe äöüß"
        assert new.eval_on_selector("img", "i => i.naturalWidth") == 20
        assert second  # source stayed untouched
    finally:
        ctx.close()


# ---- the slides wrapper ------------------------------------------------------

def test_inline_assets_wrapper_delegates_to_bundle(tree, tmp_path):
    out = tmp_path / "deck-standalone.html"
    r = run(WRAPPER, tree / "index.html", out)
    assert r.returncode == 0, r.stderr
    html = out.read_text("utf-8")
    assert 'src="img/' not in html and "href=\"style.css\"" not in html
    assert any(src == "frames/nested.html" for src, _ in payloads(html).values())
    assert run(WRAPPER).returncode == 2


def test_inline_assets_wrapper_reports_missing_input(tmp_path):
    r = run(WRAPPER, tmp_path / "nope.html", tmp_path / "o.html")
    assert r.returncode == 1 and "nope.html" in r.stderr


def test_design_md_above_the_entry_is_found_without_flag(tree, tmp_path):
    shutil.copy(tree / "fixture-design.md", tree / "DESIGN.md")
    out = tmp_path / "o.html"
    r = run(SCRIPT, tree / "index.html", "--out", out, "--font-dir", FONT_FIXTURES)
    assert r.returncode == 0, r.stderr
    face = (FONT_FIXTURES / "fixture-sans-latin-400.woff2").read_bytes()
    assert base64.b64encode(face).decode() in out.read_text("utf-8")


def test_no_remote_check_false_positive_from_script_text(tree, tmp_path):
    (tree / "jsstring.html").write_text(
        '<!doctype html><meta charset="utf-8"><script>var s = \'<img src="https://example.invalid/a.png">\';</script>',
        encoding="utf-8")
    r = run(SCRIPT, tree / "jsstring.html", "--out", tmp_path / "o.html")
    assert r.returncode == 0, r.stderr


# ---- live stages and pages named in script --------------------------------

def test_a_stage_data_src_becomes_a_base64_srcdoc_ref(tree, tmp_path):
    """slide-stage.js reads data-srcdoc-ref + data-encoding="base64"; a send copy needs no sibling page."""
    index = tree / "index.html"
    index.write_text(index.read_text("utf-8").replace(
        "</body>", '<div class="stage" id="st" data-src="frames/plain.html" data-mode="read"></div>\n</body>', 1),
        encoding="utf-8")
    out = tmp_path / "stage.html"
    r = run(SCRIPT, index, "--out", out)
    assert r.returncode == 0, r.stderr
    html = out.read_text("utf-8")
    tag = re.search(r'<div class="stage" id="st"[^>]*>', html).group(0)
    assert "data-src=" not in tag and 'data-mode="read"' in tag
    ref = re.search(r'data-srcdoc-ref="([^"]+)"', tag).group(1)
    block = re.search(r'<script type="text/plain" class="bundle-payload" id="%s"[^>]*>' % re.escape(ref), html).group(0)
    assert 'data-encoding="base64"' in block
    src, data = payloads(html)[ref]
    assert src == "frames/plain.html" and "Größe" in data.decode("utf-8")


def test_a_page_named_in_a_script_string_is_warned_about(tree, tmp_path):
    index = tree / "index.html"
    index.write_text(index.read_text("utf-8").replace(
        "</body>", "<script>var next = 'pages/second.html'; var gone = 'missing.html';</script>\n</body>", 1),
        encoding="utf-8")
    out = tmp_path / "named.html"
    r = run(SCRIPT, index, "--out", out)
    assert r.returncode == 0, r.stderr
    warned = [ln for ln in r.stderr.splitlines() if ln.startswith("bundle: WARNING")]
    assert len(warned) == 1 and "pages/second.html" in warned[0], r.stderr


# ---- the deck back link (data-back-href) -------------------------------------

# What slide-engine.js does with the attribute: one link in the corner.
BACK_LINK_JS = ("<script>(function(){var d=document.querySelector('[data-back-href]');"
                "var a=document.createElement('a');a.className='deck-back';a.id='back';"
                "a.href=d.getAttribute('data-back-href');a.textContent='Back';document.body.appendChild(a);})();</script>")


def _deck(tree: Path, back: str, name: str = "deck.html") -> Path:
    page = tree / name
    page.write_text('<!doctype html><html lang="en" data-back-href="%s"><head><meta charset="utf-8">'
                    '<title>Deck</title></head><body><h1>Deck</h1>%s</body></html>' % (back, BACK_LINK_JS),
                    encoding="utf-8")
    return page


def _warnings(r) -> list[str]:
    return [ln for ln in r.stderr.splitlines() if ln.startswith("bundle: WARNING")]


def test_back_link_to_a_missing_page_is_warned_about(tree, tmp_path):
    r = run(SCRIPT, _deck(tree, "gone.html"), "--out", tmp_path / "o.html")
    assert r.returncode == 0, r.stderr
    warned = _warnings(r)
    assert len(warned) == 1 and "data-back-href" in warned[0] and "gone.html" in warned[0], r.stderr
    assert "missing" in warned[0]


def test_back_link_to_a_local_page_without_pages_is_warned_about(tree, tmp_path):
    out = tmp_path / "o.html"
    r = run(SCRIPT, _deck(tree, "pages/second.html"), "--out", out)
    assert r.returncode == 0, r.stderr
    warned = _warnings(r)
    assert len(warned) == 1 and "--pages" in warned[0] and "pages/second.html" in warned[0], r.stderr
    assert 'data-back-href="pages/second.html"' in out.read_text("utf-8")


def test_back_link_in_page_or_remote_is_left_alone(tree, tmp_path):
    for back in ("#top", "https://example.com/deck"):
        out = tmp_path / "o.html"
        r = run(SCRIPT, _deck(tree, back), "--out", out)
        assert r.returncode == 0 and not _warnings(r), r.stderr
        assert 'data-back-href="%s"' % back in out.read_text("utf-8")


def test_back_link_to_a_file_becomes_a_data_uri(tree, tmp_path):
    out = tmp_path / "o.html"
    r = run(SCRIPT, _deck(tree, "img/dot.png"), "--out", out)
    assert r.returncode == 0 and not _warnings(r), r.stderr
    dot = (tree / "img" / "dot.png").read_bytes()
    assert 'data-back-href="data:image/png;base64,%s"' % base64.b64encode(dot).decode() in out.read_text("utf-8")


def test_back_link_with_pages_travels_as_a_payload_and_opens(browser, tree, tmp_path):
    out = tmp_path / "deck-out.html"
    r = run(SCRIPT, _deck(tree, "pages/second.html#h"), "--out", out, "--pages")
    assert r.returncode == 0 and not _warnings(r), r.stderr
    text = out.read_text("utf-8")
    tag = re.search(r"<html[^>]*>", text).group(0)
    assert 'data-back-href="#"' in tag and 'data-back-hash="#h"' in tag
    ref = re.search(r'data-back-bundle="([^"]+)"', tag).group(1)
    assert payloads(text)[ref][0] == "pages/second.html"
    ctx, page, _ = _open_alone(browser, out, tmp_path)
    try:
        with ctx.expect_page() as popup:
            page.click("#back")
        new = popup.value
        new.wait_for_load_state()
        assert new.inner_text("#h") == "Zweite Seite: Größe äöüß"
        assert new.url.endswith("#h")
        assert page.errors == []
    finally:
        ctx.close()
