"""Every shipped style preset passes the contrast gate on the showcase deck.

The showcase uses every slide type and the syntax colours, in both modes and both
languages, so a preset colour that reads too faintly on a surface or on the code
block shows up here. Colours are fixed in the preset YAML, never by loosening the gate.
"""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

from slides_testlib import SKILL, preset_files

NEW_DECK = SKILL / "scripts" / "new-deck.py"
VERIFY = SKILL.parent / "html-canvas" / "scripts" / "verify-page.py"
SHOWCASE = SKILL / "examples" / "showcase.slides.html"


@pytest.mark.parametrize("slug", [p.stem for p in preset_files()])
def test_showcase_has_no_contrast_error_with_every_preset(tmp_path, slug):
    pytest.importorskip("playwright.sync_api")
    out = tmp_path / ("%s.html" % slug)
    subprocess.run([sys.executable, str(NEW_DECK), "--title", "Gate", "--preset", slug, "--slides", str(SHOWCASE),
                    "--out", str(out), "--force"], check=True, capture_output=True)
    run = subprocess.run([sys.executable, str(VERIFY), str(out), "--deck", "--json"], capture_output=True, text=True)
    findings = json.loads(run.stdout)["pages"][0]["findings"]
    skipped = [f["message"] for f in findings if f["rule"] == "browser-skipped"]
    if skipped:
        pytest.skip(skipped[0])   # nothing was measured: never a pass
    errors = [f["message"] for f in findings if f["level"] == "error" and f["rule"] == "contrast"]
    assert errors == [], errors


def _png(rgb: tuple[int, int, int], size: int = 64) -> bytes:
    import struct
    import zlib
    raw = b"".join(b"\x00" + bytes(rgb) * size for _ in range(size))

    def chunk(kind: bytes, data: bytes) -> bytes:
        body = kind + data
        return struct.pack(">I", len(data)) + body + struct.pack(">I", zlib.crc32(body))
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


@pytest.mark.parametrize("shade", [(8, 8, 12), (245, 245, 240)], ids=["dark-image", "light-image"])
@pytest.mark.parametrize("slug", ["swiss-modern", "bold-signal"])
def test_bleed_text_is_readable_over_any_image_in_both_themes(tmp_path, slug, shade):
    pytest.importorskip("playwright.sync_api")
    import base64
    uri = "data:image/png;base64," + base64.b64encode(_png(shade)).decode()
    frag = tmp_path / "bleed.html"
    frag.write_text("""<section class="slide slide--bleed">
  <img class="slide__bg" src="%s" alt="">
  <div class="slide__scrim"></div>
  <div class="slide__content">
    <p class="slide__label">A label above</p>
    <h2 class="slide__heading slide__heading--xl">A closing line</h2>
    <p class="slide__subtitle">A subtitle below</p>
  </div>
</section>""" % uri, encoding="utf-8")
    out = tmp_path / "bleed-deck.html"
    subprocess.run([sys.executable, str(NEW_DECK), "--title", "Bleed", "--preset", slug, "--slides", str(frag),
                    "--out", str(out), "--force"], check=True, capture_output=True)
    run = subprocess.run([sys.executable, str(VERIFY), str(out), "--deck", "--json"], capture_output=True, text=True)
    findings = json.loads(run.stdout)["pages"][0]["findings"]
    skipped = [f["message"] for f in findings if f["rule"] == "browser-skipped"]
    if skipped:
        pytest.skip(skipped[0])   # nothing was measured: never a pass
    errors = [f["message"] for f in findings if f["level"] == "error" and f["rule"] == "contrast"]
    assert errors == [], errors
