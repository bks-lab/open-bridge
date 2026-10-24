"""The skill's text says what the tree holds, and nothing in it points at one instance.

CORE ships to every fork, so a path, tool or name that only exists on one
machine is a broken promise everywhere else. The patterns below are generic on
purpose: a test that listed real customer names would itself publish them.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from slides_testlib import SKILL, preset_files, slide_type_snippets

TEXT_SUFFIXES = {".md", ".yaml", ".yml", ".py", ".cjs", ".js", ".css", ".html", ".txt"}
THIS_FILE = Path(__file__).resolve()


def shipped_text_files() -> list[Path]:
    out = []
    for p in sorted(SKILL.rglob("*")):
        if not p.is_file() or p.suffix not in TEXT_SUFFIXES or "__pycache__" in p.parts:
            continue
        if p.resolve() == THIS_FILE or p.name.startswith("LICENSE-"):
            continue
        out.append(p)
    return out


FILES = shipped_text_files()


def _rel(p: Path) -> str:
    return str(p.relative_to(SKILL))


def frontmatter() -> dict:
    text = (SKILL / "SKILL.md").read_text("utf-8")
    m = re.match(r"^---\n(.*?)\n---\n", text, re.S)
    assert m, "SKILL.md has no frontmatter"
    return yaml.safe_load(m.group(1))


# --- frontmatter -------------------------------------------------------------------------

def test_scope_is_core():
    assert frontmatter()["metadata"]["scope"] == "core"


def test_description_is_one_english_trigger_line():
    desc = frontmatter()["description"]
    flat = " ".join(desc.split())
    assert len(flat.encode("utf-8")) <= 380, "listed in every session, keep it short"
    assert "Trigger:" in flat
    assert flat.isascii(), "English triggers only"
    triggers = re.findall(r'"([^"]+)"', flat.split("Trigger:", 1)[1])
    assert triggers, "no quoted triggers"


# --- hygiene over every shipped text file ------------------------------------------------

INSTANCE_PATTERNS = [
    (r"brainstorm|\.superpowers", "brainstorm server"),
    (r"iterm", "iTerm2"),
    (r"current\.md", "work/CURRENT.md"),
    (r"frontend-design", "frontend-design skill"),
    (r"/users/|/home/[a-z]", "absolute home path"),
    (r"the-bridge", "instance repo name"),
    (r"\bbks\b|bks-", "org name or org skill"),
    (r"\.nvm/versions/node/v\d", "pinned local node install"),
]


@pytest.mark.parametrize("path", FILES, ids=_rel)
def test_no_instance_references(path):
    text = path.read_text("utf-8").lower()
    hits = [label for rx, label in INSTANCE_PATTERNS if re.search(rx, text)]
    assert not hits, hits


@pytest.mark.parametrize("path", FILES, ids=_rel)
def test_no_dash_punctuation(path):
    bad = []
    for n, line in enumerate(path.read_text("utf-8").splitlines(), 1):
        if "\u2014" in line or "\u2013" in line or " -- " in line:
            bad.append(n)
    assert not bad, "em dash, en dash or ' -- ' on lines %s" % bad


GERMAN = re.compile(r"\b(und|nicht|oder|f(?:ü|ue)r|wird|werden|eine[nrs]?|keine?|auch|sind|"
                    r"Schriften?|Folien?|erstelle|vorher|liegt|bleibt|direkt|setzt|bei|aber)\b", re.I)


I18N_REGION = re.compile(r"/\* i18n:start \*/.*?/\* i18n:end \*/", re.S)


@pytest.mark.parametrize("path", FILES, ids=_rel)
def test_english_only(path):
    # Localised control labels live between i18n markers on purpose.
    text = I18N_REGION.sub("", path.read_text("utf-8"))
    hits = sorted({m.group(0) for m in GERMAN.finditer(text)})
    assert not hits, hits


def test_no_entities_for_umlauts():
    for path in FILES:
        assert not re.search(r"&[aouAOU]uml;|&szlig;", path.read_text("utf-8")), _rel(path)


# --- counts and references match the tree ------------------------------------------------

COUNT_DOCS = [SKILL / "SKILL.md", SKILL / "CREDITS.md", *sorted((SKILL / "reference").glob("*.md"))]


def _mentions(rx: str) -> list[tuple[str, int]]:
    out = []
    for doc in COUNT_DOCS:
        for m in re.finditer(rx, doc.read_text("utf-8"), re.I):
            out.append((_rel(doc), int(m.group(1))))
    return out


def test_preset_count_matches_tree():
    real = len(preset_files())
    mentions = _mentions(r"\b(\d+) (?:curated )?(?:style )?presets\b")
    assert mentions, "SKILL.md should say how many presets ship"
    assert all(n == real for _, n in mentions), (real, mentions)


def test_slide_type_count_matches_tree():
    real = len(slide_type_snippets())
    mentions = _mentions(r"\b(\d+) slide types\b")
    assert mentions, "the docs should say how many slide types exist"
    assert all(n == real for _, n in mentions), (real, mentions)


def test_slide_types_are_numbered_in_order():
    text = (SKILL / "reference" / "slide-types.md").read_text("utf-8")
    nums = [int(n) for n in re.findall(r"^### (\d+)\. ", text, re.M)]
    assert nums == list(range(1, len(nums) + 1))
    assert len(slide_type_snippets()) == len(nums), "every slide type carries an html example"


def test_skill_md_paths_exist():
    text = (SKILL / "SKILL.md").read_text("utf-8")
    paths = set(re.findall(r"`((?:assets|scripts|reference|presets|tests)/[^`*<>{} ]+)`", text))
    assert paths
    missing = sorted(p for p in paths if not (SKILL / p.rstrip("/")).exists())
    assert not missing, missing


def test_inline_assets_promise_is_realistic():
    """A freshly generated deck already embeds its fonts; inlining is not a size jump."""
    for doc in COUNT_DOCS:
        text = doc.read_text("utf-8")
        assert not re.search(r"\d(?:[.,]\d)?\s*(?:-|to)\s*\d+\s*MB", text), _rel(doc)


# --- the default wordlist is generic -----------------------------------------------------

def test_default_wordlist_is_generic():
    text = (SKILL / "scripts" / "wordlist-default.txt").read_text("utf-8")
    entries = [ln.strip().lower() for ln in text.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    for want in ("lorem ipsum", "todo", "fixme", "confidential"):
        assert want in entries, want
    assert any("example" in e for e in entries), "placeholder domains"
    assert len(entries) <= 30, "a short generic list; instances bring their own"


def test_wordlist_documents_how_an_instance_supplies_its_own():
    text = (SKILL / "scripts" / "wordlist-default.txt").read_text("utf-8")
    assert "--wordlist" in text and "--extra-wordlist" in text
    docs = (SKILL / "reference" / "output-formats.md").read_text("utf-8")
    assert "--extra-wordlist" in docs and "html_slides.wordlist" in docs
