"""The knowledge block: terms in the text open their knowledge in a panel beside the page.

A knowledge pack (`knowledge-pack@1`, JSON) is embedded in the page or loaded next to
it. `scripts/knowledge-pack.py` builds a pack from a term list and a Markdown corpus,
checks it, marks the terms in a page or deck and embeds the pack. The block script
in `assets/sections.js` shows the panel: no pop-up, the page makes room for it.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

import pytest

from canvas_testlib import SCRIPTS

NEW_PAGE = SCRIPTS / "new-page.py"
PACK = SCRIPTS / "knowledge-pack.py"
VERIFY = SCRIPTS / "verify-page.py"
FIX = Path(__file__).resolve().parent / "fixtures" / "knowledge"
DESIGN = Path(__file__).resolve().parent / "fixtures" / "tokens" / "design-current.md"


def run(script: Path, *args) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(script), *map(str, args)], capture_output=True, text=True)


def build_pack(tmp_path: Path, *extra) -> dict:
    out = tmp_path / "pack.json"
    r = run(PACK, "build", "--terms", FIX / "terms.yaml", "--corpus", FIX / "corpus",
            "--id", "fixture", "--title", "Fixture", "--revision", "r1", "--out", out, *extra)
    assert r.returncode == 0, r.stdout + r.stderr
    return json.loads(out.read_text("utf-8"))


def term(pack: dict, key: str) -> dict:
    return next(t for t in pack["terms"] if t["id"] == key)


# --- the pack -----------------------------------------------------------------------------

def test_build_writes_a_pack_with_every_term(tmp_path):
    pack = build_pack(tmp_path)
    assert pack["schema"] == "knowledge-pack@1"
    assert pack["source"]["revision"] == "r1"
    assert [t["id"] for t in pack["terms"]] == ["latency", "queue", "throughput"]
    lat = term(pack, "latency")
    assert lat["label"] == "Latenz" and lat["aliases"] == ["Antwortzeit"]
    assert lat["summary"].startswith("Zeit zwischen Anfrage und Antwort")


def test_passages_come_from_the_corpus_with_their_place(tmp_path):
    lat = term(build_pack(tmp_path), "latency")
    texts = [p["text"] for p in lat["passages"]]
    assert any("am Client" in t for t in texts)
    assert any("Antwortzeit" in t for t in texts), "an alias finds a passage too"
    first = lat["passages"][0]["source"]
    assert first["title"] == "Grundlagen der Abarbeitung" and first["locator"] == "Latenz"
    assert all(not t.startswith(("-", "*")) for t in texts), "list markers are stripped"


def test_the_summary_source_is_found_under_the_corpus_root_and_ranks_first(tmp_path):
    """summary_source is a path inside the corpus, as the source repository names it."""
    pack = build_pack(tmp_path)
    assert term(pack, "throughput")["passages"][0]["source"]["locator"] == "Kennzahlen"


def test_prose_ranks_before_table_rows_and_quote_marks_are_gone(tmp_path):
    texts = [p["text"] for p in term(build_pack(tmp_path, "--max-passages", "4"), "latency")["passages"]]
    assert not any(t.startswith(">") for t in texts)
    rows = [i for i, t in enumerate(texts) if "Zeile aus einer Tabelle" in t]
    assert not rows or rows[0] == len(texts) - 1, texts


def test_aliases_drop_the_label_and_a_locator_never_repeats_the_title(tmp_path, monkeypatch):
    terms = tmp_path / "t.yaml"
    terms.write_text((FIX / "terms.yaml").read_text("utf-8").replace('aliases: ["Antwortzeit"]', 'aliases: ["Latenz", "Antwortzeit"]'), "utf-8")
    corpus = tmp_path / "c"
    corpus.mkdir()
    (corpus / "a.md").write_text("# Latenz kompakt\n\nDie Latenz zählt.\n", "utf-8")
    out = tmp_path / "p.json"
    assert run(PACK, "build", "--terms", terms, "--corpus", corpus, "--out", out).returncode == 0
    lat = term(json.loads(out.read_text("utf-8")), "latency")
    assert lat["aliases"] == ["Antwortzeit"]
    assert lat["passages"][0]["source"] == {"title": "Latenz kompakt", "locator": ""}


def test_neighbours_are_the_named_relations_then_co_occurrence(tmp_path):
    pack = build_pack(tmp_path)
    lat = term(pack, "latency")
    assert lat["neighbours"][0] == {"id": "queue", "rel": "steigt mit", "label": "Warteschlange"}
    ids = [n["id"] for n in lat["neighbours"]]
    assert "throughput" in ids, "Antwortzeit and Durchsatz share a paragraph"
    assert len(ids) == len(set(ids))


def test_caps_hold(tmp_path):
    pack = build_pack(tmp_path, "--max-passages", "1")
    assert all(len(t["passages"]) <= 1 for t in pack["terms"])
    assert all(len(p["text"]) <= 280 for t in pack["terms"] for p in t["passages"])


def test_check_accepts_a_built_pack_and_refuses_a_broken_one(tmp_path):
    build_pack(tmp_path)
    assert run(PACK, "check", tmp_path / "pack.json").returncode == 0
    broken = json.loads((tmp_path / "pack.json").read_text("utf-8"))
    broken["terms"][0]["summary"] = "x" * 900
    del broken["terms"][1]["label"]
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(broken), encoding="utf-8")
    r = run(PACK, "check", bad)
    assert r.returncode == 1
    assert "summary" in r.stdout and "label" in r.stdout


SLIDES = """<section class="slide" id="a">
  <h2 class="slide__heading">Latenz im Blick</h2>
  <p>Die Latenz steigt, wenn die Warteschlange wächst. Die Latenz bleibt das Maß.</p>
</section>
<section class="slide" id="b">
  <p>Durchsatz und Latenz <code>Latenz</code> gehören zusammen.</p>
</section>
"""


def test_mark_wraps_the_first_mention_per_slide_outside_headings_and_code(tmp_path):
    build_pack(tmp_path)
    page = tmp_path / "slides.html"
    page.write_text(SLIDES, encoding="utf-8")
    r = run(PACK, "mark", page, "--pack", tmp_path / "pack.json", "--write")
    assert r.returncode == 0, r.stdout + r.stderr
    html = page.read_text("utf-8")
    a, b = html.split('id="b"')
    assert '<h2 class="slide__heading">Latenz im Blick</h2>' in a, "headings stay plain"
    assert a.count('data-know="latency"') == 1 and a.count('data-know="queue"') == 1
    assert b.count('data-know="latency"') == 1 and b.count('data-know="throughput"') == 1
    assert "<code>Latenz</code>" in b
    assert re.search(r'<button type="button" class="kp-term" data-know="latency">Latenz</button>', a)
    again = run(PACK, "mark", page, "--pack", tmp_path / "pack.json", "--write")
    assert again.returncode == 0 and page.read_text("utf-8") == html, "marking twice changes nothing"


def test_mark_finds_a_term_at_the_head_of_a_compound(tmp_path):
    build_pack(tmp_path)
    page = tmp_path / "c.html"
    page.write_text('<section class="slide"><p>Die Latenz-Messung und Gesamtlatenz.</p></section>', encoding="utf-8")
    run(PACK, "mark", page, "--pack", tmp_path / "pack.json", "--write")
    html = page.read_text("utf-8")
    assert 'data-know="latency">Latenz</button>-Messung' in html
    assert "Gesamtlatenz" in html, "inside a word nothing is marked"


def test_mark_without_write_only_reports(tmp_path):
    build_pack(tmp_path)
    page = tmp_path / "slides.html"
    page.write_text(SLIDES, encoding="utf-8")
    r = run(PACK, "mark", page, "--pack", tmp_path / "pack.json")
    assert r.returncode == 0 and page.read_text("utf-8") == SLIDES
    assert "latency" in r.stdout


def test_embed_writes_one_region_and_escapes_the_script_end(tmp_path):
    pack = build_pack(tmp_path)
    pack["terms"][0]["summary"] = "Ein </script> im Text"
    (tmp_path / "pack.json").write_text(json.dumps(pack), encoding="utf-8")
    page = tmp_path / "page.html"
    page.write_text("<html><body><p>x</p></body></html>", encoding="utf-8")
    for _ in range(2):
        assert run(PACK, "embed", page, "--pack", tmp_path / "pack.json").returncode == 0
    html = page.read_text("utf-8")
    assert html.count('id="knowledge-pack"') == 1
    assert html.lower().count("</script>") == 1
    data = re.search(r'<script type="application/json" id="knowledge-pack">(.*?)</script>', html, re.S).group(1)
    assert json.loads(data)["terms"][0]["summary"] == "Ein </script> im Text"


# --- the block on a page ------------------------------------------------------------------

def page_with_pack(tmp_path: Path) -> Path:
    out = tmp_path / "page.html"
    r = run(NEW_PAGE, "--out", out, "--design", DESIGN, "--blocks", "doc-header,knowledge")
    assert r.returncode == 0, r.stdout + r.stderr
    build_pack(tmp_path)
    assert run(PACK, "embed", out, "--pack", tmp_path / "pack.json").returncode == 0
    html = out.read_text("utf-8").replace(
        '<main class="wrap">',
        '<main class="wrap">\n<p id="usage">Die <button type="button" class="kp-term" data-know="latency">Latenz</button> '
        'hängt an der <button type="button" class="kp-term" data-know="queue">Warteschlange</button>. '
        '<button type="button" class="kp-term" data-know="missing">Unbekannt</button></p>', 1)
    out.write_text(html, encoding="utf-8")
    return out


def test_knowledge_is_a_catalog_block_with_a_script():
    r = run(NEW_PAGE, "--list")
    assert re.search(r"^\s+knowledge\b", r.stdout, re.M)


def test_a_page_with_the_block_passes_the_static_gate(tmp_path):
    page = page_with_pack(tmp_path)
    v = run(VERIFY, page, "--design", DESIGN, "--allow-sample")
    assert v.returncode == 0, v.stdout


def test_a_term_opens_the_panel_and_the_page_makes_room(open_page, tmp_path):
    page = open_page(page_with_pack(tmp_path).read_text("utf-8"))
    assert page.errors == []
    page.set_viewport_size({"width": 1400, "height": 900})
    trigger = page.locator('#usage [data-know="latency"]')
    trigger.click()
    panel = page.locator(".kp-panel")
    page.wait_for_function("() => document.documentElement.classList.contains('kp-open')")
    assert panel.is_visible()
    assert page.locator(".kp-title").inner_text().strip() == "Latenz"
    assert "Zeit zwischen Anfrage" in page.locator(".kp-summary").inner_text()
    assert page.locator(".kp-pass li").count() >= 1
    assert trigger.get_attribute("aria-expanded") == "true"
    assert page.evaluate("document.querySelector('.gl-pop, [popover]:popover-open')") is None, "no pop-up"
    main_right = page.evaluate("document.querySelector('main').getBoundingClientRect().right")
    panel_left = page.evaluate("document.querySelector('.kp-panel').getBoundingClientRect().left")
    assert main_right <= panel_left + 1, "the panel sits beside the page, not over it"


def test_a_neighbour_opens_in_the_panel_and_back_returns(open_page, tmp_path):
    page = open_page(page_with_pack(tmp_path).read_text("utf-8"))
    page.locator('#usage [data-know="latency"]').click()
    page.locator('.kp-rel button[data-kp-go="queue"]').click()
    assert page.locator(".kp-title").inner_text().strip() == "Warteschlange"
    page.locator(".kp-back").click()
    assert page.locator(".kp-title").inner_text().strip() == "Latenz"


def test_escape_closes_and_the_focus_returns(open_page, tmp_path):
    page = open_page(page_with_pack(tmp_path).read_text("utf-8"))
    page.locator('#usage [data-know="queue"]').click()
    page.keyboard.press("Escape")
    page.wait_for_function("() => !document.documentElement.classList.contains('kp-open')")
    assert not page.locator(".kp-panel").is_visible()
    assert page.evaluate("document.activeElement.getAttribute('data-know')") == "queue"


def test_a_term_missing_from_the_pack_stays_plain_text(open_page, tmp_path):
    page = open_page(page_with_pack(tmp_path).read_text("utf-8"))
    miss = page.locator('#usage [data-know="missing"]')
    assert miss.get_attribute("disabled") is not None or miss.get_attribute("aria-disabled") == "true"
    assert page.errors == []


def test_k_opens_the_list_of_terms_on_the_page(open_page, tmp_path):
    page = open_page(page_with_pack(tmp_path).read_text("utf-8"))
    page.locator("body").click(position={"x": 5, "y": 5})
    page.keyboard.press("k")
    page.wait_for_function("() => document.documentElement.classList.contains('kp-open')")
    assert page.locator('.kp-list button[data-kp-go="latency"]').count() == 1
    assert page.locator('.kp-list button[data-kp-go="queue"]').count() == 1


def test_print_hides_the_panel(open_page, tmp_path):
    page = open_page(page_with_pack(tmp_path).read_text("utf-8"))
    page.locator('#usage [data-know="latency"]').click()
    page.emulate_media(media="print")
    assert not page.locator(".kp-panel").is_visible()
