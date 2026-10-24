"""scripts/check-anonymity.py scans what a reader sees, with word boundaries, and fails on hits.

Embedded font data, stylesheets and scripts are not text anybody reads, and
base64 matches almost any short term somewhere, so they are blanked before the
scan (line numbers stay). A hit exits 1 unless --warn-only says otherwise.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

from slides_testlib import FIXTURES, SKILL

CHECK = SKILL / "scripts" / "check-anonymity.py"
NEW_DECK = SKILL / "scripts" / "new-deck.py"
SLIDES = FIXTURES / "tooling" / "slides.html"


def run(*args):
    return subprocess.run([sys.executable, str(CHECK), *map(str, args)], capture_output=True, text=True)


def wordlist(tmp_path: Path, *terms: str, name: str = "words.txt") -> Path:
    p = tmp_path / name
    p.write_text("\n".join(terms) + "\n", encoding="utf-8")
    return p


def page(tmp_path: Path, body: str, head: str = "", name: str = "deck.html") -> Path:
    p = tmp_path / name
    p.write_text("<!DOCTYPE html>\n<html lang=\"en\">\n<head>\n<meta charset=\"UTF-8\">\n%s\n</head>\n<body>\n%s\n</body>\n</html>\n"
                 % (head, body), encoding="utf-8")
    return p


def test_deck_with_embedded_fonts_gives_no_hits(tmp_path):
    """A real deck: fonts, engine CSS and JS embedded, neutral slides. Zero hits, exit 0."""
    deck = tmp_path / "deck.html"
    subprocess.run([sys.executable, str(NEW_DECK), "--title", "Sample deck", "--slides", SLIDES,
                    "--out", deck], check=True, capture_output=True)
    assert "data:font/woff2;base64," in deck.read_text("utf-8")
    proc = run(deck)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "no " in proc.stdout.lower()


def test_terms_inside_data_uris_styles_and_scripts_are_not_hits(tmp_path):
    words = wordlist(tmp_path, "acme")
    head = ("<style>/* acme theme */ .x { content: 'acme'; }\n"
            "@font-face { src: url(data:font/woff2;base64,QUJD+acme/RUZH) }</style>\n"
            "<script>var owner = 'acme';</script>")
    body = '<img alt="logo" src="data:image/png;base64,AAAA+acme/BBBB">\n<p>Neutral text.</p>'
    proc = run(page(tmp_path, body, head), "--wordlist", words)
    assert proc.returncode == 0, proc.stdout


def test_a_real_term_exits_one_and_names_line_and_term(tmp_path):
    words = wordlist(tmp_path, "acme")
    head = "<style>\n.a {}\n.b {}\n</style>"
    deck = page(tmp_path, "<p>Neutral.</p>\n<p>Prepared for ACME only.</p>", head)
    proc = run(deck, "--wordlist", words)
    assert proc.returncode == 1
    line = next(i for i, ln in enumerate(deck.read_text("utf-8").splitlines(), 1) if "ACME" in ln)
    assert "acme" in proc.stdout.lower()
    assert "L%d" % line in proc.stdout, proc.stdout


def test_attribute_text_is_scanned(tmp_path):
    words = wordlist(tmp_path, "acme")
    proc = run(page(tmp_path, '<img alt="Acme logo" src="data:image/png;base64,AAAA">'), "--wordlist", words)
    assert proc.returncode == 1


def test_warn_only_reports_but_exits_zero(tmp_path):
    words = wordlist(tmp_path, "acme")
    proc = run(page(tmp_path, "<p>acme</p>"), "--wordlist", words, "--warn-only")
    assert proc.returncode == 0
    assert "acme" in proc.stdout


def test_word_boundaries(tmp_path):
    """`todo` matches a TODO marker, not the middle of another word."""
    clean = run(page(tmp_path, "<p>The mastodon and the todos.</p>", name="a.html"))
    assert clean.returncode == 0, clean.stdout
    hit = run(page(tmp_path, "<p>TODO: write this.</p>", name="b.html"))
    assert hit.returncode == 1


def test_terms_with_punctuation_match_whole(tmp_path):
    proc = run(page(tmp_path, "<p>Mail sample@example.com today.</p>"))
    assert proc.returncode == 1
    assert "example.com" in proc.stdout


def test_wordlist_is_repeatable_and_adds_to_the_default(tmp_path):
    a = wordlist(tmp_path, "alpha", name="a.txt")
    b = wordlist(tmp_path, "bravo", name="b.txt")
    deck = page(tmp_path, "<p>alpha</p>\n<p>bravo</p>\n<p>lorem ipsum</p>")
    proc = run(deck, "--wordlist", a, "--wordlist", b)
    assert proc.returncode == 1
    for term in ("alpha", "bravo", "lorem ipsum"):
        assert term in proc.stdout


def test_no_default_wordlist(tmp_path):
    a = wordlist(tmp_path, "alpha")
    proc = run(page(tmp_path, "<p>lorem ipsum</p>"), "--wordlist", a, "--no-default-wordlist")
    assert proc.returncode == 0, proc.stdout


def test_regex_entries(tmp_path):
    words = wordlist(tmp_path, r"re:\bREF-\d{4,}\b")
    proc = run(page(tmp_path, "<p>See REF-20931.</p>"), "--wordlist", words)
    assert proc.returncode == 1


def test_entities_are_decoded_before_the_scan(tmp_path):
    words = wordlist(tmp_path, "café")
    proc = run(page(tmp_path, "<p>Caf&eacute; meeting</p>"), "--wordlist", words)
    assert proc.returncode == 1


def test_instance_wordlist_from_bridge_config(tmp_path):
    root = tmp_path / "bridge"
    (root / "lists").mkdir(parents=True)
    (root / "lists" / "names.txt").write_text("zulu\n", encoding="utf-8")
    (root / "bridge-config.yaml").write_text(
        "html_slides:\n  anonymity_wordlist: lists/names.txt\n", encoding="utf-8")
    decks = root / "work" / "decks"
    decks.mkdir(parents=True)
    deck = page(decks, "<p>Zulu is named here.</p>")
    proc = run(deck)
    assert proc.returncode == 1
    assert "zulu" in proc.stdout
    assert "names.txt" in proc.stdout + proc.stderr, "the report says which list was read"
    assert run(deck, "--no-config").returncode == 0


def test_explicit_config_path(tmp_path):
    (tmp_path / "names.txt").write_text("yankee\n", encoding="utf-8")
    cfg = tmp_path / "cfg.yaml"
    cfg.write_text("html_slides:\n  anonymity_wordlist: [names.txt]\n", encoding="utf-8")
    other = tmp_path / "elsewhere"
    other.mkdir()
    proc = run(page(other, "<p>yankee</p>"), "--config", cfg)
    assert proc.returncode == 1


def test_missing_input_is_a_usage_error(tmp_path):
    assert run(tmp_path / "missing.html").returncode == 2


def test_missing_wordlist_is_a_usage_error(tmp_path):
    assert run(page(tmp_path, "<p>x</p>"), "--wordlist", tmp_path / "nope.txt").returncode == 2


def test_default_wordlist_header_describes_what_the_code_does():
    header = "\n".join(ln for ln in (SKILL / "scripts" / "wordlist-default.txt").read_text("utf-8").splitlines()
                       if ln.startswith("#"))
    assert "substring" not in header
    assert "whole word" in header
    assert "replace this default" not in header and "--no-default-wordlist" in header
    assert "html_slides.anonymity_wordlist" in header
