"""scripts/render-pptx.py: an editable PowerPoint copy of a deck.

Skips cleanly without python-pptx, without the playwright Python package or
without the chromium it drives; under CI (env CI set) a missing piece fails
instead, so the suite cannot go quietly green there. The decks are built with new-deck.py from plain
fragments, so the test exercises the markup the docs promise.
"""
from __future__ import annotations

import http.server
import importlib
import io
import os
import re
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from slides_testlib import SKILL

IN_CI = bool(os.environ.get("CI"))


def _need(name: str):
    try:
        return importlib.import_module(name)
    except ImportError as exc:
        if IN_CI:
            raise RuntimeError("%s is required in CI: %s" % (name, exc)) from exc
        pytest.skip("%s not installed" % name, allow_module_level=True)


pptx = _need("pptx")
_need("playwright.sync_api")


RENDER = SKILL / "scripts" / "render-pptx.py"
NEW_DECK = SKILL / "scripts" / "new-deck.py"
SLIDE_W = 12192000  # EMU, 13.333 in
SLIDE_H = 6858000   # EMU, 7.5 in

FRAGMENT = """
<section class="slide slide--title">
  <div class="slide__content">
    <h1 class="slide__display reveal">Export headline</h1>
    <p class="slide__subtitle reveal">A subtitle under the headline.</p>
  </div>
  <aside class="notes"><p>Say hello to the room.</p></aside>
</section>
<section class="slide slide--content">
  <h2 class="slide__heading slide__heading--sm reveal">Numbers table</h2>
  <div class="table-wrap reveal">
    <div class="table-scroll">
      <table class="data-table">
        <thead><tr><th>Name</th><th>Value</th></tr></thead>
        <tbody>
          <tr><td>Alpha</td><td>17</td></tr>
          <tr><td>Beta</td><td>42</td></tr>
        </tbody>
      </table>
    </div>
  </div>
</section>
<section class="slide slide--content">
  <div class="slide__inner">
    <div>
      <h2 class="slide__heading reveal"><span data-de>Deutscher Titel</span><span data-en>English title</span></h2>
      <p class="slide__body reveal"><span data-count="1200">1200</span> users a day</p>
      <ul class="slide__bullets" data-steps>
        <li>Step one</li>
        <li>Step two</li>
        <li>Step three</li>
      </ul>
    </div>
  </div>
</section>
"""


def run(*args, env=None, timeout=180):
    return subprocess.run([sys.executable, str(RENDER), *map(str, args)],
                          capture_output=True, text=True, timeout=timeout, env=env)


@pytest.fixture(scope="module")
def deck(tmp_path_factory) -> Path:
    d = tmp_path_factory.mktemp("pptx")
    frag = d / "slides.html"
    frag.write_text(FRAGMENT, encoding="utf-8")
    out = d / "deck.html"
    subprocess.run([sys.executable, str(NEW_DECK), "--title", "Export sample", "--slides", frag,
                    "--with", "motion", "--with", "steps", "--out", out, "--force", "--no-verify"],
                   check=True, capture_output=True)
    return out


def export(src: Path, out: Path, *args) -> "pptx.Presentation":
    proc = run(src, out, *args)
    if proc.returncode == 2 and "chromium" in proc.stderr.lower() and not IN_CI:
        pytest.skip("chromium not available: " + proc.stderr.strip())
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "render-pptx: wrote" in proc.stdout
    return pptx.Presentation(str(out))


@pytest.fixture(scope="module")
def hybrid(deck, tmp_path_factory):
    out = tmp_path_factory.mktemp("out") / "deck.pptx"
    return export(deck, out, "--lang", "en")


def texts(slide) -> list[str]:
    return [sh.text_frame.text for sh in slide.shapes if sh.has_text_frame and sh.text_frame.text.strip()]


def all_text(slide) -> str:
    return "\n".join(texts(slide))


def find_shape(slide, needle):
    for sh in slide.shapes:
        if sh.has_text_frame and needle in sh.text_frame.text:
            return sh
    raise AssertionError("no text frame with %r in %r" % (needle, texts(slide)))


def pictures(slide):
    return [sh for sh in slide.shapes if sh.shape_type == 13]  # MSO_SHAPE_TYPE.PICTURE


def test_slide_size_is_16_9_and_count_matches(hybrid):
    assert hybrid.slide_width == SLIDE_W and hybrid.slide_height == SLIDE_H
    assert len(hybrid.slides) == 3


def test_headline_is_an_editable_text_frame_in_place(hybrid):
    sh = find_shape(hybrid.slides[0], "Export headline")
    assert sh.text_frame.text.strip() == "Export headline"
    # the title slide centres its content: the headline sits in the upper two thirds
    assert 0 < sh.left < SLIDE_W / 2 and sh.left + sh.width > SLIDE_W / 2
    assert 0 < sh.top < SLIDE_H * 0.66
    assert 0.03 * SLIDE_H < sh.height < 0.4 * SLIDE_H
    size = max(r.font.size for p in sh.text_frame.paragraphs for r in p.runs if r.font.size)
    assert size.pt > 24, size.pt
    assert sh.text_frame.word_wrap is False


def test_background_is_one_full_slide_picture_at_the_back(hybrid):
    for slide in hybrid.slides:
        pics = pictures(slide)
        assert len(pics) == 1
        pic = pics[0]
        assert (pic.left, pic.top, pic.width, pic.height) == (0, 0, SLIDE_W, SLIDE_H)
        assert slide.shapes[0].shape_id == pic.shape_id


def test_table_becomes_a_native_table(hybrid):
    slide = hybrid.slides[1]
    tables = [sh for sh in slide.shapes if sh.has_table]
    assert len(tables) == 1
    tbl = tables[0].table
    cells = [[tbl.cell(r, c).text for c in range(len(tbl.columns))] for r in range(len(tbl.rows))]
    assert cells == [["Name", "Value"], ["Alpha", "17"], ["Beta", "42"]]
    head = tbl.cell(0, 0).text_frame.paragraphs[0].runs[0].font
    assert head.bold
    # the cell text is not also a loose text box
    assert "Alpha" not in all_text(slide)


def test_notes_land_on_the_notes_page(hybrid):
    s0 = hybrid.slides[0]
    assert s0.has_notes_slide
    assert "Say hello to the room." in s0.notes_slide.notes_text_frame.text
    assert not hybrid.slides[1].has_notes_slide or not hybrid.slides[1].notes_slide.notes_text_frame.text.strip()


def test_bilingual_deck_exports_only_the_chosen_language(hybrid, deck, tmp_path):
    text = all_text(hybrid.slides[2])
    assert "English title" in text and "Deutscher Titel" not in text
    de = export(deck, tmp_path / "de.pptx", "--lang", "de")
    text = all_text(de.slides[2])
    assert "Deutscher Titel" in text and "English title" not in text


def test_motion_and_steps_export_their_end_state(hybrid):
    text = all_text(hybrid.slides[2])
    assert "1200 users a day" in text
    for item in ("Step one", "Step two", "Step three"):
        assert item in text


def test_image_mode_is_one_picture_and_no_text(deck, tmp_path):
    prs = export(deck, tmp_path / "img.pptx", "--mode", "image")
    assert len(prs.slides) == 3
    for slide in prs.slides:
        assert len(pictures(slide)) == 1
        assert not texts(slide)
        assert not any(sh.has_table for sh in slide.shapes)


def _rgb(px):
    return px[:3]


def test_hidden_text_is_not_baked_into_the_background(hybrid):
    from PIL import Image

    slide = hybrid.slides[0]
    img = Image.open(io.BytesIO(pictures(slide)[0].image.blob)).convert("RGB")
    sx, sy = img.width / SLIDE_W, img.height / SLIDE_H
    sh = find_shape(slide, "Export headline")
    box = (int(sh.left * sx), int(sh.top * sy), int((sh.left + sh.width) * sx), int((sh.top + sh.height) * sy))
    region = img.crop(box)
    # reference colour: a strip just above the headline box, where only the slide background is
    ref = _rgb(img.getpixel((box[0] + 2, max(0, box[1] - 6))))
    colours = region.getcolors(maxcolors=region.width * region.height)
    off = sum(n for n, c in colours if max(abs(a - b) for a, b in zip(c, ref)) > 24)
    assert off / (region.width * region.height) < 0.01, (ref, off)


def test_prints_the_fonts_the_deck_uses(deck, tmp_path):
    proc = run(deck, tmp_path / "f.pptx", "--font-fallback", "Nonexistent=Arial")
    if proc.returncode == 2 and "chromium" in proc.stderr.lower() and not IN_CI:
        pytest.skip("chromium not available")
    assert proc.returncode == 0, proc.stderr
    assert "fonts:" in proc.stderr.lower()


def test_missing_python_pptx_exits_2_with_a_message(deck, tmp_path):
    shadow = tmp_path / "shadow" / "pptx"
    shadow.mkdir(parents=True)
    (shadow / "__init__.py").write_text("raise ImportError('shadowed for the test')\n", encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(shadow.parent))
    proc = run(deck, tmp_path / "x.pptx", env=env)
    assert proc.returncode == 2
    assert "python-pptx" in proc.stderr
    assert len(proc.stderr.strip().splitlines()) == 1
    assert not (tmp_path / "x.pptx").exists()


def test_wrong_usage_exits_2(tmp_path):
    proc = run()
    assert proc.returncode == 2
    proc = run(tmp_path / "missing.html", tmp_path / "out.pptx")
    assert proc.returncode == 2


# --------------------------------------------------------------------------- review fixes

def build(tmp: Path, fragment: str, *extra, name="deck.html") -> Path:
    frag = tmp / ("frag-" + name)
    frag.write_text(fragment, encoding="utf-8")
    out = tmp / name
    subprocess.run([sys.executable, str(NEW_DECK), "--title", "Probe", "--slides", frag,
                    "--out", out, "--force", "--no-verify", *map(str, extra)],
                   check=True, capture_output=True)
    return out


def background(slide):
    from PIL import Image

    return Image.open(io.BytesIO(pictures(slide)[0].image.blob)).convert("RGB")


def count_near(img, box, rgb, tol=48):
    region = img.crop(box)
    return sum(n for n, c in region.getcolors(region.width * region.height)
               if max(abs(a - b) for a, b in zip(c, rgb)) <= tol)


def emu_box(img, sh):
    sx, sy = img.width / SLIDE_W, img.height / SLIDE_H
    return (int(sh.left * sx), int(sh.top * sy), int((sh.left + sh.width) * sx), int((sh.top + sh.height) * sy))


def bbox_of(img, rgb, tol=40):
    px = img.load()
    xs, ys = [], []
    for y in range(0, img.height, 2):
        for x in range(0, img.width, 2):
            if max(abs(a - b) for a, b in zip(px[x, y], rgb)) <= tol:
                xs.append(x)
                ys.append(y)
    return (min(xs), min(ys), max(xs), max(ys)) if xs else None


TABLE_STEPS = """
<section class="slide slide--content">
  <h2 class="slide__heading slide__heading--sm">Stepped table</h2>
  <table class="data-table" style="color:#101010">
    <caption>Table caption text</caption>
    <thead><tr><th>Column one</th><th>Column two</th></tr></thead>
    <tbody data-steps>
      <tr><td>Gamma cell text</td><td>Delta cell text</td></tr>
      <tr><td>Epsilon cell text</td><td>Zeta cell text</td></tr>
    </tbody>
  </table>
</section>
"""


def test_table_with_steps_is_not_doubled_and_keeps_its_caption(tmp_path):
    prs = export(build(tmp_path, TABLE_STEPS, "--with", "steps"), tmp_path / "t.pptx")
    slide = prs.slides[0]
    shape = next(sh for sh in slide.shapes if sh.has_table)
    tbl = shape.table
    assert tbl.cell(1, 0).text == "Gamma cell text" and tbl.cell(2, 1).text == "Zeta cell text"
    img = background(slide)
    box = emu_box(img, shape)
    area = (box[2] - box[0]) * (box[3] - box[1])
    assert count_near(img, box, (0x10, 0x10, 0x10)) / area < 0.002, "cell text baked into the picture"
    assert "Table caption text" in all_text(slide)


def test_table_visual_stays_in_the_picture(tmp_path):
    frag = TABLE_STEPS.replace('<table class="data-table" style="color:#101010">',
                               '<table class="data-table" style="color:#101010;border:6px solid #ff0000">')
    prs = export(build(tmp_path, frag), tmp_path / "t.pptx")
    img = background(prs.slides[0])
    assert bbox_of(img, (255, 0, 0)) is not None, "the table border left the picture"


def _red_slide(body):
    return ('<section class="slide slide--content"><h2 class="slide__heading">Wrapped deck heading</h2>'
            '<div style="width:300px;height:120px;background:#ff0000"></div></section>' + body)


@pytest.mark.parametrize("variant", ["wrapper", "body"])
def test_deck_without_a_top_level_deck_element_is_not_blank(tmp_path, variant):
    src = build(tmp_path, _red_slide(""))
    html = src.read_text("utf-8")
    m = re.search(r'<div class="deck"[^>]*>', html)
    assert m
    if variant == "wrapper":
        html = html.replace(m.group(0), '<main class="page-wrap">' + m.group(0), 1).replace("</body>", "</main></body>", 1)
    else:
        # slides straight in <body>: drop the deck element, keep its children
        start = m.end()
        end = html.index("</section>", html.rindex("<section", 0, html.index("</body>"))) + len("</section>")
        close = html.index("</div>", end)
        html = html[:m.start()] + html[start:close] + html[close + len("</div>"):]
    src.write_text(html, encoding="utf-8")
    prs = export(src, tmp_path / "w.pptx")
    assert "Wrapped deck heading" in all_text(prs.slides[0])
    assert bbox_of(background(prs.slides[0]), (255, 0, 0)) is not None, "slide blanked"


def _autonum(slide):
    out = []
    for sh in slide.shapes:
        if not sh.has_text_frame:
            continue
        for p in sh.text_frame.paragraphs:
            ppr = p._p.pPr
            num = None if ppr is None else ppr.find("{http://schemas.openxmlformats.org/drawingml/2006/main}buAutoNum")
            if num is not None:
                out.append((p.text, num.get("startAt"), sh.shape_id))
    return out


def test_numbered_lists_keep_their_numbers(tmp_path):
    frag = """
<section class="slide slide--content"><div class="slide__inner"><div>
  <ol start="3" style="list-style:decimal;padding-left:2em"><li>third item</li><li>fourth item</li></ol>
  <ol reversed style="list-style:decimal;padding-left:2em"><li>rev three</li><li>rev two</li><li>rev one</li></ol>
  <ol style="list-style:decimal;padding-left:2em"><li value="10">item ten</li><li>item eleven</li></ol>
</div></div></section>"""
    prs = export(build(tmp_path, frag), tmp_path / "n.pptx")
    nums = _autonum(prs.slides[0])
    first = {t: (s, sid) for t, s, sid in nums}
    assert first["third item"][0] == "3"
    # a paragraph that continues the sequence sits in the same box (PowerPoint counts on)
    assert first["fourth item"][1] == first["third item"][1]
    assert first["item ten"][0] == "10" and first["item eleven"][1] == first["item ten"][1]
    # a reversed list cannot count on: every item carries its own number
    assert [first[t][0] for t in ("rev three", "rev two", "rev one")] == ["3", "2", "1"]
    assert len({first[t][1] for t in ("rev three", "rev two", "rev one")}) == 3


def test_notes_keep_every_block_once(tmp_path):
    frag = """
<section class="slide slide--content"><h2 class="slide__heading">Notes probe</h2>
<aside class="notes"><p>Intro para</p>Loose words<blockquote>Quoted line</blockquote>
<ul><li>Item alpha</li><li>Item beta</li></ul><pre>code line</pre><h5>Small head</h5>
<div><p>Nested para</p></div></aside></section>"""
    prs = export(build(tmp_path, frag), tmp_path / "notes.pptx")
    text = prs.slides[0].notes_slide.notes_text_frame.text
    for part in ("Intro para", "Loose words", "Quoted line", "Item alpha", "Item beta", "code line",
                 "Small head", "Nested para"):
        assert text.count(part) == 1, (part, text)


def test_hiding_text_does_not_move_the_picture(tmp_path):
    frag = """
<section class="slide slide--content"><style>.shift > * { margin-left: 120px; }</style>
<div class="slide__inner"><div>
  <p class="shift slide__body">Plain words <b style="background:#ff0000;color:#ff0000">mark</b></p>
  <p class="slide__body"><span style="text-decoration:underline 4px #00ff00">Underlined words</span></p>
  <p class="slide__body" style="text-decoration:line-through 4px #0000ff"><span>Struck words</span></p>
</div></div></section>"""
    src = build(tmp_path, frag)
    hyb = export(src, tmp_path / "h.pptx")
    img = export(src, tmp_path / "i.pptx", "--mode", "image")
    a, b = background(hyb.slides[0]), background(img.slides[0])
    # the red mark is a background box: same place in both pictures
    ra = bbox_of(a, (255, 0, 0))
    rb = bbox_of(b, (255, 0, 0))
    assert ra and rb and all(abs(x - y) <= 4 for x, y in zip(ra, rb)), (ra, rb)
    assert bbox_of(a, (0, 255, 0)) is None, "underline left in the picture"
    assert bbox_of(a, (0, 0, 255)) is None, "line-through left in the picture"


def test_clipped_text_is_cut_and_tiny_text_exports(tmp_path):
    frag = """
<section class="slide slide--content"><div class="slide__inner"><div>
  <div style="width:240px;height:60px;overflow:hidden"><p class="slide__body" style="white-space:nowrap">Seen start of a line
  that runs on and on far beyond the clip box until FARWORD</p></div>
  <p style="font-size:1px">tiny</p>
</div></div></section>"""
    prs = export(build(tmp_path, frag), tmp_path / "c.pptx")
    text = all_text(prs.slides[0])
    assert "Seen" in text and "FARWORD" not in text
    sizes = [r.font.size.pt for sh in prs.slides[0].shapes if sh.has_text_frame
             for p in sh.text_frame.paragraphs for r in p.runs if r.font.size]
    assert min(sizes) >= 1


TRACKS = """
<section class="slide"><h2 class="slide__heading">Common slide</h2></section>
<section class="slide" data-track="long"><h2 class="slide__heading">Long only</h2></section>
<section class="slide" data-track="short"><h2 class="slide__heading">Short only</h2></section>
"""


def test_track_exports_that_track_and_refuses_an_unknown_one(tmp_path):
    src = build(tmp_path, TRACKS)
    prs = export(src, tmp_path / "s.pptx", "--track", "short")
    assert [all_text(s) for s in prs.slides] == ["Common slide", "Short only"]
    proc = run(src, tmp_path / "x.pptx", "--track", "nosuch")
    assert proc.returncode == 2 and "nosuch" in proc.stderr
    assert not (tmp_path / "x.pptx").exists()


def test_theme_dark_renders_dark(tmp_path):
    src = build(tmp_path, TRACKS)
    light = background(export(src, tmp_path / "l.pptx", "--theme", "light").slides[0]).getpixel((5, 5))
    dark = background(export(src, tmp_path / "d.pptx", "--theme", "dark").slides[0]).getpixel((5, 5))
    assert sum(dark) < sum(light) - 150, (light, dark)


def test_network_is_blocked_unless_allowed(tmp_path):
    hits = []

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            hits.append(self.path)
            self.send_response(404)
            self.end_headers()

        def log_message(self, *a):
            pass

    srv = http.server.HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        url = "http://127.0.0.1:%d/probe.png" % srv.server_port
        src = build(tmp_path, '<section class="slide"><h2 class="slide__heading">Net</h2><img src="%s" alt="x"></section>' % url)
        export(src, tmp_path / "a.pptx")
        assert hits == []
        export(src, tmp_path / "b.pptx", "--allow-network")
        assert hits
    finally:
        srv.shutdown()


def test_output_equal_to_input_is_refused(deck, tmp_path):
    copy = tmp_path / "same.html"
    copy.write_bytes(deck.read_bytes())
    proc = run(copy, copy)
    assert copy.read_bytes() == deck.read_bytes()
    assert proc.returncode == 2 and "same" in proc.stderr.lower()


def test_unwritable_output_is_one_line_and_exit_1(deck, tmp_path):
    blocker = tmp_path / "file.txt"
    blocker.write_text("x", encoding="utf-8")
    proc = run(deck, blocker / "out.pptx")
    assert proc.returncode == 1, proc.stderr
    assert len(proc.stderr.strip().splitlines()) == 1 and "Traceback" not in proc.stderr


def test_a_word_broken_across_lines_is_kept(tmp_path):
    frag = """
<section class="slide slide--content"><div class="slide__inner"><div>
  <p class="slide__body" style="width:260px">Freigabe des Termins mit dem IT-Security-Verantwortlichen-Ende.</p>
</div></div></section>"""
    prs = export(build(tmp_path, frag), tmp_path / "w.pptx")
    text = all_text(prs.slides[0]).replace("\v", "").replace("\n", "")
    assert "Verantwortlichen-Ende." in text, text
