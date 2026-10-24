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

from canvas_testlib import REPO, SCRIPTS, render_shell, run_new_simulation

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


def test_browser_reads_text_over_a_sibling_scrim_below_the_fold(browser):
    """A closing slide paints its scrim as a sibling of the text; the ancestor walk misses it."""
    code, data = run(str(FIX / "scrim-dark.html"), "--browser")
    msgs = [f["message"] for f in data["pages"][0]["findings"] if f["rule"] == "contrast"]
    assert msgs and ("Closing words" in msgs[0] or "subtitle" in msgs[0]), data
    assert code == 1


def test_browser_passes_text_over_a_veil_in_the_surface_colour(browser):
    code, data = run(str(FIX / "scrim-veil.html"), "--browser")
    assert "contrast" not in rules(data), data
    assert code == 0, data


def test_browser_flags_low_contrast(browser):
    code, data = run(str(FIX / "contrast.html"), "--browser")
    assert code == 1
    assert "contrast" in rules(data, "error"), data


def test_browser_warns_on_text_hidden_under_reduced_motion(browser):
    code, data = run(str(FIX / "motion.html"), "--browser")
    assert ("reduced-motion", "warning") in findings(data), data
    assert code == 0


def _variant(tmp_path: Path, name: str, css: str = "", body: str = "") -> Path:
    """clean.html with extra CSS and markup, written next to a copy of the fixture DESIGN.md."""
    html = (FIX / "clean.html").read_text("utf-8")
    html = html.replace("</style>", css + "\n</style>", 1).replace("</main>", body + "\n</main>", 1)
    out = tmp_path / name
    out.write_text(html, encoding="utf-8")
    return out


FAINT = "color:color-mix(in srgb,var(--ink) 6%,var(--surface))"


def test_browser_skips_decoration_marked_aria_hidden(browser, tmp_path):
    """A decorative numeral in a faint colour is no readable content once it says so."""
    page = _variant(tmp_path, "faint-hidden.html", body='<span aria-hidden="true" style="%s">01</span>' % FAINT)
    code, data = run(str(page), "--browser")
    assert "contrast" not in rules(data), data
    shown = _variant(tmp_path, "faint-shown.html", body='<span style="%s">01</span>' % FAINT)
    code, data = run(str(shown), "--browser")
    assert "contrast" in rules(data, "error"), "the same text without aria-hidden still counts"


CODE_FONT_CSS = ":root{--font-mono:ui-monospace, Menlo, monospace}"


def test_browser_warns_on_code_outside_the_mono_family(browser, tmp_path):
    page = _variant(tmp_path, "code-font.html", CODE_FONT_CSS + "\ncode{font-family:var(--font-sans)}",
                    "<p>Run <code>verify-page.py</code> first.</p>")
    code, data = run(str(page), "--browser")
    assert ("code-font", "warning") in findings(data), data
    assert code == 0


def test_browser_is_quiet_when_code_uses_the_mono_family(browser, tmp_path):
    page = _variant(tmp_path, "code-mono.html", CODE_FONT_CSS + "\ncode{font-family:var(--font-mono)}",
                    "<p>Run <code>verify-page.py</code> first.</p>")
    code, data = run(str(page), "--browser")
    assert "code-font" not in rules(data), data


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


# --- wave 1 review fixes -------------------------------------------------------------------

DESIGN_TO_CSS = SCRIPTS / "design-to-css.py"


def _fill(html: str) -> str:
    for key, val in (("TITLE_DE", "Titel"), ("TITLE_EN", "Title"), ("TITLE", "Title"),
                     ("DATE", "2026-01-01"), ("SOURCE_PATH", "fixture")):
        html = html.replace("{{%s}}" % key, val)
    return html


def test_shell_from_the_repo_design_md_reads_in_both_themes(browser, tmp_path):
    # The repo DESIGN.md is in the legacy palette shape without dark-primary:
    # dark mode once kept the light ink, headings and buttons at 1:1.
    page = tmp_path / "page.html"
    subprocess.run([sys.executable, str(DESIGN_TO_CSS), str(REPO / "DESIGN.md"), "--shell", "--out", str(page)],
                   check=True, capture_output=True)
    page.write_text(_fill(page.read_text("utf-8")).replace(
        "</main>", "<h2><span data-de>Abschnitt</span><span data-en>Section</span></h2>"
                   "<p data-de>Text.</p><p data-en>Text.</p></main>", 1), encoding="utf-8")
    code, data = run(str(page), "--browser", design=REPO / "DESIGN.md")
    assert "contrast" not in rules(data), data
    assert rules(data, "error") == set(), data


def test_assembled_simulation_reads_in_both_themes(browser, tmp_path):
    out = tmp_path / "sim-flow.html"
    r = run_new_simulation(out, "--archetype", "flow", "--title-de", "Lauf", "--title-en", "Run")
    assert r.returncode == 0, r.stderr
    code, data = run(str(out), "--browser", design=REPO / "DESIGN.md")
    assert "contrast" not in rules(data), data


def test_neutral_shell_reads_in_both_themes(browser, tmp_path):
    # no DESIGN.md tokens at all: the system-colour fallbacks must stay legible
    page = tmp_path / "page.html"
    page.write_text(render_shell("<p data-de>Inhalt</p><p data-en>Content</p>"), encoding="utf-8")
    code, data = run(str(page), "--browser", design=None)
    assert "contrast" not in rules(data), data


def test_flow_simulation_has_no_one_language_aria_label(tmp_path):
    out = tmp_path / "sim-flow.html"
    r = run_new_simulation(out, "--archetype", "flow", "--title-de", "Lauf", "--title-en", "Run")
    assert r.returncode == 0, r.stderr
    _, data = run(str(out), design=REPO / "DESIGN.md")
    assert ("aria-lang", "warning") not in findings(data), data


# Elements that carry both data-de and data-en show in both languages: the
# value form (data-de="Start" data-en="Start") and the empty form alike.

def test_dual_attribute_elements_hidden_in_both_languages_are_red(browser):
    code, data = run(str(FIX / "dual-hidden.html"), "--browser")
    assert code == 1
    msgs = [f["message"] for f in data["pages"][0]["findings"] if f["rule"] == "lang-hidden"]
    assert len(msgs) == 1, data
    assert "2 elements" in msgs[0] and "dual-value" in msgs[0], msgs


def test_dual_attribute_elements_shown_are_green(browser):
    code, data = run(str(FIX / "dual-shown.html"), "--browser")
    assert findings(data) == [], data
    assert code == 0


def test_dual_attribute_elements_pass_the_static_rules():
    code, data = run(str(FIX / "dual-hidden.html"))
    assert findings(data) == [] and code == 0, data


# A requested browser pass that cannot run is not a pass.

def _fake_no_playwright(tmp_path: Path) -> dict:
    import os
    pkg = tmp_path / "fake" / "playwright"
    pkg.mkdir(parents=True)
    (pkg / "__init__.py").write_text("raise ImportError('playwright hidden by the test')\n", "utf-8")
    env = dict(os.environ)
    env["PYTHONPATH"] = str(tmp_path / "fake") + os.pathsep + env.get("PYTHONPATH", "")
    return env


def _run_env(env: dict, *args: str) -> tuple[int, dict]:
    proc = subprocess.run([sys.executable, str(SCRIPT), *args, "--json", "--design", str(DESIGN)],
                          capture_output=True, text=True, env=env)
    assert proc.returncode in (0, 1), proc.stderr
    return proc.returncode, json.loads(proc.stdout)


@pytest.mark.parametrize("flag", ["--browser", "--deck"])
def test_requested_browser_pass_without_playwright_is_an_error(tmp_path, flag):
    code, data = _run_env(_fake_no_playwright(tmp_path), str(FIX / "clean.html"), flag)
    assert ("browser-skipped", "error") in findings(data), data
    assert code == 1


def test_requested_browser_pass_without_chromium_is_an_error(tmp_path):
    pytest.importorskip("playwright.sync_api")
    import os
    env = dict(os.environ, PLAYWRIGHT_BROWSERS_PATH=str(tmp_path / "no-browsers"))
    code, data = _run_env(env, str(FIX / "clean.html"), "--browser")
    assert ("browser-skipped", "error") in findings(data), data
    assert code == 1


def test_static_mode_never_needs_a_browser(tmp_path):
    code, data = _run_env(_fake_no_playwright(tmp_path), str(FIX / "clean.html"))
    assert findings(data) == [] and code == 0


# Dark mode is found where the page keeps it: .theme-dark, [data-theme], or a
# selector the caller names.

@pytest.mark.parametrize("name", ["theme-class.html", "data-theme.html", "theme-light-preset.html"])
def test_browser_detects_class_and_attribute_dark_modes(browser, name):
    code, data = run(str(FIX / name), "--browser")
    msgs = [f["message"] for f in data["pages"][0]["findings"] if f["rule"] == "contrast"]
    assert msgs and all(m.startswith("dark-") for m in msgs), data
    assert code == 1


def test_browser_takes_a_dark_selector(browser):
    code, data = run(str(FIX / "night.html"), "--browser")
    assert "contrast" not in rules(data), data          # .night is nothing it can guess
    code, data = run(str(FIX / "night.html"), "--browser", "--dark-selector", ".night")
    msgs = [f["message"] for f in data["pages"][0]["findings"] if f["rule"] == "contrast"]
    assert msgs and all(m.startswith("dark-") for m in msgs), data
    assert code == 1


@pytest.mark.parametrize("sel", ["html.night", ":root.night", '[data-mode="night"]', "[data-night]"])
def test_dark_selector_forms_are_accepted(sel):
    proc = subprocess.run([sys.executable, str(SCRIPT), str(FIX / "clean.html"), "--dark-selector", sel],
                          capture_output=True, text=True)
    assert proc.returncode == 0, proc.stderr


@pytest.mark.parametrize("sel", ["body .night", "div", ".a .b", ""])
def test_dark_selector_outside_the_root_is_a_usage_error(sel):
    proc = subprocess.run([sys.executable, str(SCRIPT), str(FIX / "clean.html"), "--dark-selector", sel],
                          capture_output=True, text=True)
    assert proc.returncode == 2 and "--dark-selector" in proc.stderr


# A stack that leads with a system family is a system stack by choice.

@pytest.mark.parametrize("stack,warns", [
    ('"SF Mono", Monaco, "Cascadia Code", "Roboto Mono", Consolas, monospace', False),
    ('"Roboto Mono", monospace', True),
])
def test_system_led_font_stack_does_not_warn(tmp_path, stack, warns):
    text = (FIX / "clean.html").read_text("utf-8").replace(
        "</style>", "code{font-family:%s}\n</style>" % stack, 1)
    page = tmp_path / "page.html"
    page.write_text(text, encoding="utf-8")
    _, data = run(str(page))
    assert (("font-face", "warning") in findings(data)) is warns, data


# --- which DESIGN.md the gate checks against ----------------------------------------------

def test_text_output_names_the_design_md_it_used():
    proc = subprocess.run([sys.executable, str(SCRIPT), str(FIX / "clean.html"), "--design", str(DESIGN)],
                          capture_output=True, text=True)
    assert "note: checked against %s" % DESIGN in proc.stdout, proc.stdout


def _built_from(tmp_path: Path, header: str) -> Path:
    page = tmp_path / "built.html"
    page.write_text((FIX / "clean.html").read_text("utf-8").replace("<style>", "<style>\n" + header, 1),
                    encoding="utf-8")
    return page


@pytest.mark.parametrize("header, word", [
    ("/* Generated from DESIGN.md (other-brand, 2026-01-01) by\n   design-to-css.py. */", "other-brand"),
    ("/* Generated from DESIGN.md (verify-fixture, 2020-01-01) by\n   design-to-css.py. */", "2020-01-01"),
])
def test_a_page_built_from_another_design_md_warns(tmp_path, header, word):
    design = tmp_path / "DESIGN.md"
    design.write_text(DESIGN.read_text("utf-8").replace("name: verify-fixture", "name: verify-fixture\nlast_updated: 2026-05-01", 1),
                      encoding="utf-8")
    code, data = run(str(_built_from(tmp_path, header)), design=design)
    msgs = [f["message"] for f in data["pages"][0]["findings"] if f["rule"] == "design-source"]
    assert msgs and word in msgs[0], data
    assert ("design-source", "warning") in findings(data)


def test_a_page_built_from_the_same_design_md_stays_quiet(tmp_path):
    header = "/* Generated from DESIGN.md (verify-fixture) by\n   design-to-css.py. */"
    code, data = run(str(_built_from(tmp_path, header)))
    assert "design-source" not in rules(data), data


# --- catalog sample text ------------------------------------------------------------------

SAMPLE_PAGE = (FIX / "clean.html").read_text("utf-8")


def _page(tmp_path: Path, body: str) -> Path:
    p = tmp_path / "sample.html"
    p.write_text(SAMPLE_PAGE.replace('<main id="main">', '<main id="main">\n' + body, 1), encoding="utf-8")
    return p


def test_a_block_still_marked_as_sample_fails_the_gate(tmp_path):
    code, data = run(str(_page(tmp_path, '<div class="blk" data-sample><p>Sample</p></div>')))
    assert ("sample", "error") in findings(data) and code == 1


def test_a_bare_ellipsis_cell_fails_the_gate(tmp_path):
    code, data = run(str(_page(tmp_path, "<table><tr><td>Key</td><td> … </td></tr></table>")))
    assert ("sample", "error") in findings(data) and code == 1


def test_an_ellipsis_inside_prose_is_fine(tmp_path):
    code, data = run(str(_page(tmp_path, "<p>Wait for it … and then it runs.</p>")))
    assert "sample" not in rules(data), data


def test_allow_sample_turns_it_into_a_warning(tmp_path):
    code, data = run(str(_page(tmp_path, '<div data-sample><p>…</p></div>')), "--allow-sample")
    assert ("sample", "warning") in findings(data) and ("sample", "error") not in findings(data)
    assert code == 0
