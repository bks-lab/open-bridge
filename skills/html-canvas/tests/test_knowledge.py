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

from canvas_testlib import CONTRAST, PANEL_TEXT, SCRIPTS

NEW_PAGE = SCRIPTS / "new-page.py"
PACK = SCRIPTS / "knowledge-pack.py"
VERIFY = SCRIPTS / "verify-page.py"
FIX = Path(__file__).resolve().parent / "fixtures" / "knowledge"
DESIGN = Path(__file__).resolve().parent / "fixtures" / "tokens" / "design-current.md"

BUTTON = '<button type="button" class="kp-term" data-know="%s">%s</button>'


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
    assert [t["id"] for t in pack["terms"]] == ["latency", "queue", "throughput", "it"]
    lat = term(pack, "latency")
    assert lat["label"] == "Latency" and lat["aliases"] == ["response time"]
    assert lat["summary"].startswith("Time between request and response")


def test_passages_come_from_the_corpus_with_their_place(tmp_path):
    lat = term(build_pack(tmp_path), "latency")
    texts = [p["text"] for p in lat["passages"]]
    assert any("at the client" in t for t in texts)
    first = lat["passages"][0]["source"]
    assert first["title"] == "Basics of processing" and first["locator"] == "Latency"
    assert all(not t.startswith(("-", "*")) for t in texts), "list markers are stripped"


def test_words_match_in_any_case_acronyms_only_as_written(tmp_path):
    pack = build_pack(tmp_path, "--max-passages", "4")
    lat = [p["text"] for p in term(pack, "latency")["passages"]]
    assert any("latency rises" in t for t in lat), "a word matches in lower case mid-sentence"
    it = [p["text"] for p in term(pack, "it")["passages"]]
    assert it == ["IT runs the systems and watches the latency-bound jobs."], "'it' and 'It' are not the acronym IT"


def test_an_alias_finds_a_passage_too(tmp_path):
    texts = [p["text"] for p in term(build_pack(tmp_path, "--max-passages", "4"), "latency")["passages"]]
    assert any("response time" in t for t in texts)


def test_the_summary_source_is_found_under_the_corpus_root_and_ranks_first(tmp_path):
    """summary_source is a path inside the corpus, as the source repository names it."""
    pack = build_pack(tmp_path)
    assert term(pack, "throughput")["passages"][0]["source"]["locator"] == "Metrics"


def test_prose_ranks_before_table_rows_and_quote_marks_are_gone(tmp_path):
    texts = [p["text"] for p in term(build_pack(tmp_path, "--max-passages", "4"), "latency")["passages"]]
    assert not any(t.startswith(">") for t in texts)
    rows = [i for i, t in enumerate(texts) if "A row from a table" in t]
    assert not rows or rows[0] == len(texts) - 1, texts


def test_aliases_drop_the_label_and_a_locator_never_repeats_the_title(tmp_path):
    terms = tmp_path / "t.yaml"
    terms.write_text((FIX / "terms.yaml").read_text("utf-8").replace(
        'aliases: ["response time"]', 'aliases: ["Latency", "response time"]'), "utf-8")
    corpus = tmp_path / "c"
    corpus.mkdir()
    (corpus / "a.md").write_text("# Latency in short\n\nThe latency counts.\n", "utf-8")
    out = tmp_path / "p.json"
    assert run(PACK, "build", "--terms", terms, "--corpus", corpus, "--out", out).returncode == 0
    lat = term(json.loads(out.read_text("utf-8")), "latency")
    assert lat["aliases"] == ["response time"]
    assert lat["passages"][0]["source"] == {"title": "Latency in short", "locator": ""}


def test_neighbours_are_the_named_relations_then_co_occurrence(tmp_path):
    pack = build_pack(tmp_path)
    lat = term(pack, "latency")
    assert lat["neighbours"][0] == {"id": "queue", "rel": "rises with", "label": "Queue"}
    ids = [n["id"] for n in lat["neighbours"]]
    assert "throughput" in ids, "response time and throughput share a paragraph"
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
  <h2 class="slide__heading">Latency in view</h2>
  <p>The latency rises when the queue grows. The latency stays the measure.</p>
</section>
<section class="slide" id="b">
  <p>Throughput and latency <code>latency</code> belong together.</p>
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
    assert '<h2 class="slide__heading">Latency in view</h2>' in a, "headings stay plain"
    assert a.count('data-know="latency"') == 1 and a.count('data-know="queue"') == 1
    assert b.count('data-know="latency"') == 1 and b.count('data-know="throughput"') == 1
    assert "<code>latency</code>" in b
    assert BUTTON % ("latency", "latency") in a, "the mark keeps the text as written"
    again = run(PACK, "mark", page, "--pack", tmp_path / "pack.json", "--write")
    assert again.returncode == 0 and page.read_text("utf-8") == html, "marking twice changes nothing"


def test_mark_finds_a_term_at_the_head_of_a_compound(tmp_path):
    build_pack(tmp_path)
    page = tmp_path / "c.html"
    page.write_text('<section class="slide"><p>The latency-bound jobs.</p></section>'
                    '<section class="slide"><p>Hyperlatency is a made-up word.</p></section>', encoding="utf-8")
    run(PACK, "mark", page, "--pack", tmp_path / "pack.json", "--write")
    html = page.read_text("utf-8")
    assert '<span class="kp-nobr">' + (BUTTON % ("latency", "latency")) + '-bound</span>' in html, \
        "the help mark and the rest of the compound never part at a line end"
    assert "<p>Hyperlatency is a made-up word.</p>" in html, "inside a word nothing is marked"


def test_mark_without_write_only_reports(tmp_path):
    build_pack(tmp_path)
    page = tmp_path / "slides.html"
    page.write_text(SLIDES, encoding="utf-8")
    r = run(PACK, "mark", page, "--pack", tmp_path / "pack.json")
    assert r.returncode == 0 and page.read_text("utf-8") == SLIDES
    assert "latency" in r.stdout


def test_embed_writes_one_region_and_escapes_the_script_end(tmp_path):
    pack = build_pack(tmp_path)
    pack["terms"][0]["summary"] = "A </script> in the text"
    (tmp_path / "pack.json").write_text(json.dumps(pack), encoding="utf-8")
    page = tmp_path / "page.html"
    page.write_text("<html><body><p>x</p></body></html>", encoding="utf-8")
    for _ in range(2):
        assert run(PACK, "embed", page, "--pack", tmp_path / "pack.json").returncode == 0
    html = page.read_text("utf-8")
    assert html.count('id="knowledge-pack"') == 1
    assert html.lower().count("</script>") == 1
    data = re.search(r'<script type="application/json" id="knowledge-pack">(.*?)</script>', html, re.S).group(1)
    assert json.loads(data)["terms"][0]["summary"] == "A </script> in the text"


def test_embed_keeps_valid_json_whatever_the_text_holds(tmp_path):
    pack = build_pack(tmp_path)
    pack["terms"][0]["summary"] = "A <!-- comment --> and <script>x</script> and </SCRIPT >"
    (tmp_path / "pack.json").write_text(json.dumps(pack), encoding="utf-8")
    page = tmp_path / "page.html"
    page.write_text("<html><body><p>x</p></body></html>", encoding="utf-8")
    assert run(PACK, "embed", page, "--pack", tmp_path / "pack.json").returncode == 0
    html = page.read_text("utf-8")
    data = re.search(r'<script type="application/json" id="knowledge-pack">(.*?)</script>', html, re.S).group(1)
    assert "<" not in data, "no raw angle bracket inside the script element"
    assert json.loads(data)["terms"][0]["summary"] == pack["terms"][0]["summary"]


def test_embed_puts_the_pack_at_the_end_of_the_body_not_into_a_sample(tmp_path):
    page = tmp_path / "page.html"
    page.write_text('<html><body><div data-sample><p>sample</p></div><main><p>x</p></main></body></html>', encoding="utf-8")
    build_pack(tmp_path)
    assert run(PACK, "embed", page, "--pack", tmp_path / "pack.json").returncode == 0
    html = page.read_text("utf-8")
    assert html.index("knowledge-pack:start") > html.index("</main>")


def test_check_refuses_a_link_that_is_not_web_or_mail(tmp_path):
    pack = build_pack(tmp_path)
    pack["terms"][0]["passages"][0]["source"]["href"] = "javascript:alert(1)"
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(pack), encoding="utf-8")
    r = run(PACK, "check", bad)
    assert r.returncode == 1 and "href" in r.stdout


def test_mark_survives_angle_brackets_in_attributes_and_text(tmp_path):
    build_pack(tmp_path)
    page = tmp_path / "t.html"
    page.write_text('<section class="slide"><p title="a > b" data-x=\'<i>\'>If 2 < 3 the latency wins.</p>'
                    '<script>var q = "queue";</script></section>'
                    '<section class="slide"><p>The queue waits.</p></section>', encoding="utf-8")
    run(PACK, "mark", page, "--pack", tmp_path / "pack.json", "--write")
    html = page.read_text("utf-8")
    assert '<p title="a > b" data-x=\'<i>\'>If 2 < 3 the ' + BUTTON % ("latency", "latency") + " wins.</p>" in html
    assert 'var q = "queue";' in html, "script text is never marked"
    assert "The " + BUTTON % ("queue", "queue") + " waits." in html


def test_mark_reads_entities_as_their_characters(tmp_path):
    terms = tmp_path / "t.yaml"
    terms.write_text('terms:\n  - {id: qa, label: "Q&A", summary: "Questions."}\n'
                     '  - {id: copy, label: copy, summary: "A copy."}\n', encoding="utf-8")
    pack = tmp_path / "p.json"
    corpus = tmp_path / "c"
    corpus.mkdir()
    (corpus / "a.md").write_text("# T\n\nQ&A and a copy.\n", "utf-8")
    assert run(PACK, "build", "--terms", terms, "--corpus", corpus, "--out", pack).returncode == 0
    page = tmp_path / "e.html"
    page.write_text("<section class=\"slide\"><p>&copy; 2026, see the Q&amp;A.</p></section>", encoding="utf-8")
    run(PACK, "mark", page, "--pack", pack, "--write")
    html = page.read_text("utf-8")
    assert BUTTON % ("qa", "Q&amp;A") in html
    assert 'data-know="copy"' not in html, "the entity &copy; is not the word copy"


# --- the block on a page ------------------------------------------------------------------

USAGE = ('<p id="usage">The ' + BUTTON % ("latency", "latency") + ' depends on the '
         + BUTTON % ("queue", "queue") + '. ' + BUTTON % ("missing", "Unknown") + '</p>\n'
         '<p id="plain">The latency depends on the queue. Unknown</p>')


def page_with_pack(tmp_path: Path) -> Path:
    out = tmp_path / "page.html"
    r = run(NEW_PAGE, "--out", out, "--design", DESIGN, "--blocks", "doc-header,knowledge")
    assert r.returncode == 0, r.stdout + r.stderr
    build_pack(tmp_path)
    assert run(PACK, "embed", out, "--pack", tmp_path / "pack.json").returncode == 0
    html = out.read_text("utf-8").replace('<main class="wrap">', '<main class="wrap">\n' + USAGE, 1)
    out.write_text(html, encoding="utf-8")
    return out


def opened(page) -> bool:
    return page.evaluate("document.documentElement.classList.contains('kp-open')")


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
    page.wait_for_function("() => document.documentElement.classList.contains('kp-open')")
    assert page.locator(".kp-panel").is_visible()
    assert page.locator(".kp-title").inner_text().strip() == "Latency"
    assert "Time between request" in page.locator(".kp-summary").inner_text()
    assert page.locator(".kp-pass li").count() >= 1
    assert trigger.get_attribute("aria-expanded") == "true"
    assert page.evaluate("document.querySelector('.gl-pop, [popover]:popover-open')") is None, "no pop-up"
    main_right = page.evaluate("document.querySelector('main').getBoundingClientRect().right")
    panel_left = page.evaluate("document.querySelector('.kp-panel').getBoundingClientRect().left")
    assert main_right <= panel_left + 1, "the panel sits beside the page, not over it"


def test_a_mark_does_not_change_the_line_height(open_page, tmp_path):
    """The question mark sits in the line; a marked line is as tall as a plain one."""
    page = open_page(page_with_pack(tmp_path).read_text("utf-8"))
    page.set_viewport_size({"width": 1400, "height": 900})
    marked = page.evaluate("document.querySelector('#usage').getBoundingClientRect().height")
    plain = page.evaluate("document.querySelector('#plain').getBoundingClientRect().height")
    assert abs(marked - plain) < 1, (marked, plain)


def test_a_neighbour_opens_in_the_panel_and_back_returns(open_page, tmp_path):
    page = open_page(page_with_pack(tmp_path).read_text("utf-8"))
    page.locator('#usage [data-know="latency"]').click()
    page.locator('.kp-rel button[data-kp-go="queue"]').click()
    assert page.locator(".kp-title").inner_text().strip() == "Queue"
    page.locator(".kp-back").click()
    assert page.locator(".kp-title").inner_text().strip() == "Latency"


def test_opened_from_the_keyboard_escape_gives_the_focus_back(open_page, tmp_path):
    page = open_page(page_with_pack(tmp_path).read_text("utf-8"))
    page.locator('#usage [data-know="queue"]').focus()
    page.keyboard.press("Enter")
    page.wait_for_function("() => document.documentElement.classList.contains('kp-open')")
    page.keyboard.press("Escape")
    page.wait_for_function("() => !document.documentElement.classList.contains('kp-open')")
    assert not page.locator(".kp-panel").is_visible()
    assert page.evaluate("document.activeElement.getAttribute('data-know')") == "queue"


def test_opened_with_the_pointer_escape_leaves_no_focus_on_the_term(open_page, tmp_path):
    """A pointer user gets no focus parked on the term: the next Space or Enter must
    not reopen the panel (in a deck it moves the slides on)."""
    page = open_page(page_with_pack(tmp_path).read_text("utf-8"))
    page.locator('#usage [data-know="queue"]').click()
    page.keyboard.press("Escape")
    page.wait_for_function("() => !document.documentElement.classList.contains('kp-open')")
    assert page.evaluate("document.activeElement === document.body")
    page.keyboard.press("Enter")
    assert not opened(page)


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


def test_every_panel_text_reads_in_both_themes(open_page, tmp_path):
    page = open_page(page_with_pack(tmp_path).read_text("utf-8"))
    for theme in ("light", "dark"):
        if page.evaluate("document.documentElement.classList.contains('dark')") != (theme == "dark"):
            page.keyboard.press("t")
        page.locator('#usage [data-know="latency"]').click()
        page.wait_for_function("() => document.documentElement.classList.contains('kp-open')")
        low = [(s, round(v, 2)) for s, v in page.evaluate(CONTRAST, PANEL_TEXT) if v is not None and v < 4.5]
        assert low == [], (theme, low)
        page.keyboard.press("Escape")


def test_print_hides_the_panel(open_page, tmp_path):
    page = open_page(page_with_pack(tmp_path).read_text("utf-8"))
    page.locator('#usage [data-know="latency"]').click()
    page.emulate_media(media="print")
    assert not page.locator(".kp-panel").is_visible()


def test_a_link_from_the_pack_is_only_followed_when_it_is_web_or_mail(open_page, tmp_path):
    """check() refuses such a pack, but the panel must not trust a pack another tool wrote."""
    page_file = page_with_pack(tmp_path)
    html = page_file.read_text("utf-8")
    m = re.search(r'(<script type="application/json" id="knowledge-pack">)(.*?)(</script>)', html, re.S)
    pack = json.loads(m.group(2))
    pack["terms"][0]["passages"][0]["source"]["href"] = "javascript:alert(1)"
    pack["terms"][0]["sources"] = [{"title": "Evil", "href": "JavaScript:alert(2)"}, {"title": "Good", "href": "https://example.org/a"}]
    html = html[:m.start(2)] + json.dumps(pack).replace("<", "\\u003c") + html[m.end(2):]
    page = open_page(html)
    page.locator('#usage [data-know="latency"]').click()
    hrefs = page.evaluate("[...document.querySelectorAll('.kp-panel a')].map(a => a.getAttribute('href'))")
    assert "https://example.org/a" in hrefs
    assert not any(h and h.lower().startswith("javascript:") for h in hrefs), hrefs


def test_the_close_button_speaks_the_page_language(open_page, tmp_path):
    page = open_page(page_with_pack(tmp_path).read_text("utf-8").replace('lang="de"', 'lang="en"'))
    page.locator('#usage [data-know="latency"]').click()
    close = page.locator(".kp-close")
    assert close.get_attribute("aria-label") == "Close" and "Close" in close.get_attribute("title")


def test_back_keeps_the_focus_in_the_panel(open_page, tmp_path):
    page = open_page(page_with_pack(tmp_path).read_text("utf-8"))
    page.locator('#usage [data-know="latency"]').click()
    page.locator('.kp-rel button[data-kp-go="queue"]').click()
    page.locator(".kp-back").click()
    assert page.evaluate("document.querySelector('.kp-panel').contains(document.activeElement)")


def test_print_leaves_no_room_for_the_panel(open_page, tmp_path):
    page = open_page(page_with_pack(tmp_path).read_text("utf-8"))
    page.set_viewport_size({"width": 800, "height": 900})
    page.locator('#usage [data-know="latency"]').click()
    page.emulate_media(media="print")
    pad = page.evaluate("[getComputedStyle(document.body).paddingRight, getComputedStyle(document.body).paddingBottom]")
    page.emulate_media(media="screen")
    page.keyboard.press("Escape")
    base = page.evaluate("[getComputedStyle(document.body).paddingRight, getComputedStyle(document.body).paddingBottom]")
    assert pad == base, (pad, base)


def mark_style(page) -> dict:
    return page.evaluate("""() => { const t = document.querySelector('#usage [data-know="latency"]');
        const s = getComputedStyle(t), a = getComputedStyle(t, '::after');
        return {style: s.textDecorationStyle, line: s.textDecorationLine, after: a.display}; }""")


def test_a_term_is_a_dashed_underline_without_a_symbol(open_page, tmp_path):
    page = open_page(page_with_pack(tmp_path).read_text("utf-8"))
    st = mark_style(page)
    assert st["line"] == "underline" and st["style"] == "dashed", st
    assert st["after"] == "none", "no help symbol by default"


def test_the_help_symbol_is_an_option_on_the_page(open_page, tmp_path):
    html = page_with_pack(tmp_path).read_text("utf-8").replace("<html ", '<html data-kp-mark="icon" ', 1)
    page = open_page(html)
    st = mark_style(page)
    assert st["after"] == "inline-block", "data-kp-mark=icon shows the help symbol"
