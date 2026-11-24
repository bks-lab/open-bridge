"""A page that uses a kit block's classes without the block's CSS (24.11.2026).

A history page for a pupil took the timeline markup from references/sections.md but only
wrote "tweaks" for .tl-row (column widths, no display:grid) and never included the block
CSS. Every entry rendered as two stacked lines, no line, no dots, and the gate stayed green.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

from canvas_testlib import ASSETS, SCRIPTS

SCRIPT = SCRIPTS / "verify-page.py"
FIX = Path(__file__).resolve().parent / "fixtures" / "verify"

MARKUP = ('<div class="timeline"><div class="tl-row key"><div class="tl-date">800</div>'
          '<div>Kaiserkrönung</div></div></div>')


def page(tmp_path: Path, css: str, body: str = MARKUP) -> Path:
    clean = (FIX / "clean.html").read_text(encoding="utf-8")
    html = clean.replace("</style>", css + "\n</style>", 1).replace("</main>", body + "\n</main>", 1)
    assert "</main>" in clean, "clean fixture lost its <main>"
    p = tmp_path / "page.html"
    p.write_text(html, encoding="utf-8")
    return p


def run(p: Path) -> list[dict]:
    proc = subprocess.run([sys.executable, str(SCRIPT), str(p), "--json", "--design", str(FIX / "DESIGN.md")],
                          capture_output=True, text=True)
    assert proc.returncode in (0, 1), proc.stderr
    return [f for pg in json.loads(proc.stdout)["pages"] for f in pg["findings"]]


def block_css(name: str) -> str:
    text = (ASSETS / "sections.css").read_text(encoding="utf-8")
    m = re.search(r"/\* @block: %s\b[^*]*\*/(.*?)(?=/\* @block:|\Z)" % re.escape(name), text, re.S)
    return m.group(1)


def test_tweaks_without_the_block_css_are_an_error_that_names_the_block(tmp_path):
    got = [f for f in run(page(tmp_path, ".tl-row{grid-template-columns:96px 1fr;gap:14px}")) if f["rule"] == "block-css"]
    assert got and got[0]["level"] == "error"
    assert "timeline" in got[0]["message"] and "--blocks" in got[0]["message"]


def test_with_the_block_css_the_rule_is_quiet(tmp_path):
    assert not [f for f in run(page(tmp_path, block_css("timeline"))) if f["rule"] == "block-css"]


def test_an_own_layout_for_the_class_counts(tmp_path):
    css = ".timeline{display:flex;flex-direction:column}.tl-row{display:flex;gap:8px}"
    assert not [f for f in run(page(tmp_path, css)) if f["rule"] == "block-css"]


def test_classes_outside_the_kit_are_ignored(tmp_path):
    assert not [f for f in run(page(tmp_path, "", '<div class="mein-ding">x</div>')) if f["rule"] == "block-css"]


def test_the_timeline_block_draws_a_line_dots_a_key_mark_and_stacks_on_phones():
    css = block_css("timeline")
    assert re.search(r"\.timeline::before\{[^}]*width:2px", css), "no vertical line"
    assert re.search(r"\.tl-row::before\{[^}]*border-radius:50%", css), "no dot per entry"
    assert ".tl-row.key" in css, "no way to mark the years that matter"
    assert re.search(r"@media \(max-width:\s*\d+px\)\{\.tl-row\{grid-template-columns:1fr", css), "no phone layout"
