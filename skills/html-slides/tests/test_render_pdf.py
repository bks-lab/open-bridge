"""scripts/render-pdf.cjs: page size, one page per slide, theme, no fixed sleep.

Skips cleanly without node, without a playwright module node can resolve, or
without the chromium that module drives.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from slides_testlib import FIXTURES, SKILL

RENDER = SKILL / "scripts" / "render-pdf.cjs"
NEW_DECK = SKILL / "scripts" / "new-deck.py"
SLIDES = FIXTURES / "tooling" / "slides.html"
MM = 72 / 25.4


def node() -> str:
    exe = shutil.which("node")
    if not exe:
        pytest.skip("node not installed")
    return exe


def render(*args, timeout=120):
    return subprocess.run([node(), str(RENDER), *map(str, args)], capture_output=True, text=True, timeout=timeout)


@pytest.fixture(scope="module")
def renderer():
    probe = render("--probe")
    if probe.returncode != 0:
        pytest.skip("playwright not resolvable from node: %s" % probe.stderr.strip().splitlines()[-1:])
    return probe


def deck(tmp_path: Path, extra_slides: str = "", name: str = "deck.html") -> Path:
    frag = tmp_path / ("slides-" + name)
    frag.write_text(SLIDES.read_text("utf-8") + extra_slides, encoding="utf-8")
    out = tmp_path / name
    subprocess.run([sys.executable, str(NEW_DECK), "--title", "Print sample", "--slides", frag,
                    "--out", out, "--force"], check=True, capture_output=True)
    return out


def to_pdf(src: Path, *args) -> bytes:
    out = src.with_suffix(".pdf")
    proc = render(src, out, *args)
    if proc.returncode != 0 and "Executable doesn't exist" in proc.stderr + proc.stdout:
        pytest.skip("chromium for node playwright not installed")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    return out.read_bytes()


def pages(pdf: bytes) -> int:
    return len(re.findall(rb"/Type\s*/Page(?![A-Za-z])", pdf))


def media_box(pdf: bytes) -> tuple[float, float]:
    m = re.search(rb"/MediaBox\s*\[\s*([\d.]+)\s+([\d.]+)\s+([\d.]+)\s+([\d.]+)\s*\]", pdf)
    assert m, "no MediaBox"
    x0, y0, x1, y1 = (float(v) for v in m.groups())
    return x1 - x0, y1 - y0


def test_probe_names_the_resolved_module(renderer):
    assert "playwright" in renderer.stdout


def test_explicit_size_gives_a4_and_one_page_per_slide(renderer, tmp_path):
    pdf = to_pdf(deck(tmp_path), "--width", "210", "--height", "297")
    w, h = media_box(pdf)
    assert abs(w - 210 * MM) < 2 and abs(h - 297 * MM) < 2, (w, h)
    assert pages(pdf) == 3


def test_without_a_size_the_css_page_size_wins(renderer, tmp_path):
    pdf = to_pdf(deck(tmp_path))
    w, h = media_box(pdf)
    assert abs(w - 297 * MM) < 2 and abs(h - 167 * MM) < 2, (w, h)
    assert pages(pdf) == 3


THEMED = """
<style>.theme-light .slide.only-dark { display: none !important; }</style>
<section class="slide slide--content only-dark"><div class="slide__inner"><p>Dark only.</p></div></section>
"""


def test_theme_flag_sets_the_deck_theme(renderer, tmp_path):
    src = deck(tmp_path, THEMED)
    assert pages(to_pdf(src, "--theme", "light")) == 3
    assert pages(to_pdf(src, "--theme", "dark")) == 4


def test_bad_theme_is_a_usage_error(renderer, tmp_path):
    proc = render(tmp_path / "a.html", tmp_path / "a.pdf", "--theme", "sepia")
    assert proc.returncode == 2


def test_missing_arguments_are_a_usage_error():
    assert render().returncode == 2


def test_waits_on_fonts_not_on_a_fixed_sleep():
    src = RENDER.read_text("utf-8")
    assert "document.fonts.ready" in src
    assert not re.search(r"waitForTimeout\(\s*\d{3,}", src), "a fixed sleep instead of a readiness signal"


def test_live_stages_are_loaded_before_the_pdf_is_written(renderer, tmp_path):
    """The stage loads its frames when print starts; the PDF must not catch them empty."""
    from test_stage import child_html, deck_html
    (tmp_path / "child.html").write_text(child_html(), encoding="utf-8")
    src = tmp_path / "stage-deck.html"
    src.write_text(deck_html(), encoding="utf-8")
    proc = render(src, tmp_path / "stage-deck.pdf")
    if proc.returncode != 0 and "Executable doesn't exist" in proc.stderr + proc.stdout:
        pytest.skip("chromium for node playwright not installed")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    fixture = (FIXTURES / "stage" / "deck.html").read_text("utf-8")
    frames = fixture.count('class="stage"') + fixture.count("<iframe")   # every stage plus a plain frame
    assert ("-> Waited for %d embedded frames" % frames) in proc.stdout, proc.stdout
