"""scripts/render-pptx.py: an editable PowerPoint copy of a deck.

Skips cleanly without python-pptx, without the playwright Python package or
without the chromium it drives. The decks are built with new-deck.py from plain
fragments, so the test exercises the markup the docs promise.
"""
from __future__ import annotations

import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

from slides_testlib import SKILL

pptx = pytest.importorskip("pptx")
pytest.importorskip("playwright.sync_api")


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
    if proc.returncode == 2 and "chromium" in proc.stderr.lower():
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
    if proc.returncode == 2 and "chromium" in proc.stderr.lower():
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
