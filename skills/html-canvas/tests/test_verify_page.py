"""verify-page.py: one quality gate for every single-file HTML deliverable.

Each static rule has a broken fixture that must produce exactly the one expected
finding, and every rule shares one clean fixture that must stay green. Browser
and deck tests run the script with --browser / --deck and skip cleanly when
playwright or chromium is missing.
"""
from __future__ import annotations

import json
import shutil
import struct
import subprocess
import sys
from pathlib import Path

import pytest

from conftest import REPO, SCRIPTS, render_shell, run_new_simulation

SCRIPT = SCRIPTS / "verify-page.py"
FIX = Path(__file__).resolve().parent / "fixtures" / "verify"
DESIGN = FIX / "DESIGN.md"


def run(*args: str, design: Path | None = DESIGN) -> tuple[int, dict]:
    cmd = [sys.executable, str(SCRIPT), *args, "--json"]
    if design is not None:
        cmd += ["--design", str(design)]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    assert proc.returncode in (0, 1), proc.stderr
    return proc.returncode, json.loads(proc.stdout)


def findings(data: dict) -> list[tuple[str, str]]:
    return [(f["rule"], f["level"]) for page in data["pages"] for f in page["findings"]]


def rules(data: dict, level: str | None = None) -> set[str]:
    return {r for r, lv in findings(data) if level is None or lv == level}


# --- static mode ---------------------------------------------------------------------------

def test_clean_fixture_is_green():
    code, data = run(str(FIX / "clean.html"), "--forbid-chars", "¶")
    assert code == 0
    assert findings(data) == []
    assert data["errors"] == 0 and data["warnings"] == 0


STATIC_CASES = [
    ("external-url.html", "external-url", "error"),
    ("external-css.html", "external-url", "error"),
    ("external-link.html", "external-link", "warning"),
    ("local-ref.html", "local-ref", "error"),
    ("placeholder.html", "placeholder", "error"),
    ("entity.html", "entity", "error"),
    ("escape.html", "entity", "error"),
    ("hex.html", "hex", "error"),
    ("font-face.html", "font-face", "warning"),
    ("lang-pair.html", "lang-pair", "error"),
    ("aria-pair.html", "aria-pair", "error"),
    ("aria-lang.html", "aria-lang", "warning"),
    ("dead-anchor.html", "dead-anchor", "error"),
    ("charset.html", "charset", "error"),
]


@pytest.mark.parametrize("name,rule,level", STATIC_CASES, ids=[c[0] for c in STATIC_CASES])
def test_broken_fixture_yields_exactly_its_finding(name, rule, level):
    code, data = run(str(FIX / name))
    assert findings(data) == [(rule, level)], data
    assert code == (1 if level == "error" else 0)


def test_findings_carry_a_line_number():
    _, data = run(str(FIX / "hex.html"))
    f = data["pages"][0]["findings"][0]
    assert f["line"] > 1 and "#123456" in f["message"]


def test_hex_declared_only_in_prose_still_counts_as_undeclared():
    # DESIGN.md names #123456 below its front matter; only the front matter declares.
    _, data = run(str(FIX / "hex.html"))
    assert rules(data) == {"hex"}


def test_design_md_is_discovered_next_to_the_page(tmp_path):
    shutil.copy(FIX / "hex.html", tmp_path / "page.html")
    shutil.copy(DESIGN, tmp_path / "DESIGN.md")
    _, data = run(str(tmp_path / "page.html"), design=None)
    assert rules(data) == {"hex"}
    assert data["pages"][0]["design"] == str(tmp_path / "DESIGN.md")


def test_hex_check_is_skipped_without_a_design_md(tmp_path):
    shutil.copy(FIX / "hex.html", tmp_path / "page.html")
    code, data = run(str(tmp_path / "page.html"), design=None)
    assert code == 0 and findings(data) == []
    assert data["pages"][0]["design"] is None


def test_allow_host_accepts_a_named_host():
    code, data = run(str(FIX / "external-url.html"), "--allow-host", "cdn.example.org")
    assert code == 0 and findings(data) == []


def test_google_fonts_link_is_red():
    code, data = run(str(FIX / "google-fonts.html"))
    assert code == 1
    msgs = [f["message"] for f in data["pages"][0]["findings"] if f["rule"] == "external-url"]
    assert any("fonts.googleapis.com" in m for m in msgs)


def test_forbidden_chars_are_off_by_default():
    code, data = run(str(FIX / "forbidden.html"))
    assert code == 0 and findings(data) == []


def test_forbid_chars_flag():
    code, data = run(str(FIX / "forbidden.html"), "--forbid-chars", "¶")
    assert code == 1 and findings(data) == [("forbidden-char", "error")]
    assert "U+00B6" in data["pages"][0]["findings"][0]["message"]


def test_forbid_chars_from_file():
    code, data = run(str(FIX / "forbidden.html"), "--forbid-chars-from", str(FIX / "forbid-chars.txt"))
    assert code == 1 and findings(data) == [("forbidden-char", "error")]


def test_several_pages_and_human_output():
    proc = subprocess.run([sys.executable, str(SCRIPT), str(FIX / "clean.html"), str(FIX / "hex.html"),
                           str(FIX / "font-face.html"), "--design", str(DESIGN)],
                          capture_output=True, text=True)
    assert proc.returncode == 1
    out = proc.stdout
    assert "clean.html: ok" in out
    assert "ERROR" in out and "hex" in out and "WARN" in out and "font-face" in out
    assert out.strip().splitlines()[-1].startswith("verify-page: 1 error, 1 warning")


def test_missing_page_is_a_usage_error(tmp_path):
    proc = subprocess.run([sys.executable, str(SCRIPT), str(tmp_path / "nope.html")],
                          capture_output=True, text=True)
    assert proc.returncode == 2 and "nope.html" in proc.stderr


# --- counter-checks against what the skill itself ships -----------------------------------

def test_filled_shell_has_no_errors(tmp_path):
    page = tmp_path / "page.html"
    page.write_text(render_shell("<p data-de>Inhalt</p><p data-en>Content</p>"), encoding="utf-8")
    code, data = run(str(page), design=REPO / "DESIGN.md")
    assert rules(data, "error") == set(), data
    assert code == 0


@pytest.mark.parametrize("archetype", ["flow", "worklist"])
def test_assembled_simulation_has_no_errors(tmp_path, archetype):
    out = tmp_path / ("sim-%s.html" % archetype)
    r = run_new_simulation(out, "--archetype", archetype, "--title-de", "Lauf", "--title-en", "Run")
    assert r.returncode == 0, r.stderr
    code, data = run(str(out), design=REPO / "DESIGN.md")
    assert rules(data, "error") == set(), data
    assert code == 0


# --- browser mode --------------------------------------------------------------------------

def _png_width(path: Path) -> int:
    with path.open("rb") as fh:
        head = fh.read(24)
    assert head[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">I", head[16:20])[0]


def test_browser_clean_is_green_and_writes_screenshots(browser, tmp_path):
    out = tmp_path / "shots"
    code, data = run(str(FIX / "clean.html"), "--browser", "--out", str(out))
    assert findings(data) == [], data
    assert code == 0
    shots = sorted(p.name for p in out.glob("*.png"))
    for state in ("light-en", "light-de", "dark-en", "dark-de", "reduced-motion", "print"):
        assert any(state in s for s in shots), (state, shots)
    assert all(_png_width(p) >= 500 for p in out.glob("*.png"))


def test_browser_rejects_a_width_under_500():
    proc = subprocess.run([sys.executable, str(SCRIPT), str(FIX / "clean.html"), "--browser", "--width", "390"],
                          capture_output=True, text=True)
    assert proc.returncode == 2 and "500" in proc.stderr


def test_browser_flags_console_errors_and_both_languages(browser):
    code, data = run(str(FIX / "browser-broken.html"), "--browser")
    assert code == 1
    assert {"console-error", "both-languages"} <= rules(data, "error"), data


def test_browser_opens_the_file_alone(browser):
    # pixel.svg sits next to the fixture; in the empty temp dir it must be missing.
    code, data = run(str(FIX / "local-ref.html"), "--browser")
    assert code == 1
    assert "request-failed" in rules(data, "error"), data


def test_browser_flags_low_contrast(browser):
    code, data = run(str(FIX / "contrast.html"), "--browser")
    assert code == 1
    assert "contrast" in rules(data, "error"), data


def test_browser_warns_on_text_hidden_under_reduced_motion(browser):
    code, data = run(str(FIX / "motion.html"), "--browser")
    assert ("reduced-motion", "warning") in findings(data), data
    assert code == 0


# --- deck mode -----------------------------------------------------------------------------

def test_deck_clean_is_green(browser):
    code, data = run(str(FIX / "deck-clean.html"), "--deck")
    assert findings(data) == [], data
    assert code == 0
    assert data["pages"][0]["slides"] == 3


def test_deck_flags_an_overflowing_slide_at_both_sizes(browser):
    code, data = run(str(FIX / "deck-overflow.html"), "--deck")
    assert code == 1
    msgs = [f["message"] for f in data["pages"][0]["findings"] if f["rule"] == "slide-overflow"]
    assert len(msgs) == 2 and all("slide 2" in m for m in msgs), data
    assert any("1280x720" in m for m in msgs) and any("1920x1080" in m for m in msgs)
    assert rules(data) == {"slide-overflow"}


def test_deck_print_pages_must_equal_slides(browser):
    code, data = run(str(FIX / "deck-pages.html"), "--deck")
    assert code == 1
    assert findings(data) == [("print-pages", "error")], data


def test_deck_without_slides_is_red(browser):
    code, data = run(str(FIX / "clean.html"), "--deck")
    assert code == 1
    assert "slide-count" in rules(data, "error")
