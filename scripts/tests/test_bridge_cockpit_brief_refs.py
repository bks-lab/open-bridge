# SPDX-License-Identifier: MIT
"""References in a brief (scripts/lib/bridge_cockpit/brief_refs.py): what a reader of a card can reach from the item,
and whether a brief's goal, story and criteria point only at that.

The model writes criteria such as "all gaps in epic #95 are closed" or "the open points of the report (§6)", which a
reader of the card cannot follow: which repository is #95 in, which report? These tests hold the module to what it
collects from a STATUS.md (the bound repository, its issues, links, paths and task slugs that exist), to how a
bare #n is qualified (one repository known: owner/repo#n, else unresolved), and to the parts a card draws a
criterion from (text, a link, an unresolved reference)."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.bridge_cockpit import brief_refs as br  # noqa: E402

REPO = "acme/outbound-operator"
FRONT = {"slug": "ubl-fix", "context": "acme",
         "sync": {"bridge_only": False, "github": {"repo": REPO, "issues": [95], "project": {"org": "acme", "number": 18}}}}
TEXT = """---
slug: ubl-fix
---

# Outbound UBL mapping fix (16 gaps, Epic #95)

Board #18: [#95](https://github.com/acme/outbound-operator/issues/95). The gap list lives in
work/tasks/ubl-fix/gaps.md, the spec gap analysis in `spec-gap-analysis` (see also docs/mapping.md).
Pull request acme/wiki#164 holds the checklist. More at https://example.org/peppol/rules.
A word such as end-to-end or und/oder is no reference, nor is work/tasks/gone/file.md (it does not exist).
"""
EXISTING = {"work/tasks/ubl-fix/gaps.md", "docs/mapping.md", "work/tasks/ubl-fix/deliverables/report.md"}
SLUGS = {"spec-gap-analysis": "work/tasks/spec-gap-analysis", "ubl-fix": "work/tasks/ubl-fix"}


def reach(front=FRONT, text=TEXT, context=None, **kw):
    return br.reachable(text, front, own="work/tasks/ubl-fix", context=context, exists=EXISTING.__contains__,
                        folder_of=SLUGS.get, files=["work/tasks/ubl-fix/deliverables/report.md"], **kw)


def texts(r):
    return br.references(r)


# ---------------------------------------------------------------- what a reader can reach

def test_the_bound_repository_its_issues_and_the_qualified_bare_numbers_are_reachable():
    r = reach()
    assert r["repos"] == [REPO]
    got = texts(r)
    assert f"{REPO}#95" in got and "acme/wiki#164" in got
    assert "https://example.org/peppol/rules" in got
    # a board number is no issue: "Board #18" never becomes owner/repo#18, the board itself is a link
    assert f"{REPO}#18" not in got
    assert "https://github.com/orgs/acme/projects/18" in got


def test_paths_that_exist_the_files_of_the_folder_and_known_slugs_are_reachable_and_nothing_else():
    got = texts(reach())
    assert "work/tasks/ubl-fix/gaps.md" in got and "docs/mapping.md" in got
    assert "work/tasks/ubl-fix/deliverables/report.md" in got
    assert "spec-gap-analysis" in got
    assert "ubl-fix" not in got, "the task itself is no reference"
    assert not any("gone" in x or "end-to-end" in x or "oder" in x for x in got)


def test_a_relative_link_resolves_against_the_task_folder_and_never_leaves_the_root():
    text = "See [the list](gaps.md), [log](../../log.md) and [wiki](../../../../wiki/x.md)."
    r = br.reachable(text, {}, own="work/tasks/ubl-fix", exists={"work/tasks/ubl-fix/gaps.md", "work/log.md"}.__contains__)
    got = texts(r)
    assert "work/tasks/ubl-fix/gaps.md" in got and "work/log.md" in got
    assert not any("wiki" in x for x in got)


def test_the_context_names_the_repository_when_the_task_has_none():
    front = {"context": "acme", "sync": {"bridge_only": True}}
    one = {"sync": {"defaults": {"github": {"repo": "acme/one"}}}, "repos": [{"github": "acme/one"}, {"github": "acme/two"}]}
    assert br.reachable("x", front, context=one)["repos"] == ["acme/one"]
    two = {"repos": [{"github": "acme/one"}, {"github": "acme/two"}]}
    assert br.reachable("x", front, context=two)["repos"] == ["acme/one", "acme/two"]
    # with two repositories a bare #12 of the text cannot be qualified
    assert not any(x.endswith("#12") for x in texts(br.reachable("see #12", front, context=two)))


def test_the_list_is_bounded():
    many = " ".join(f"https://example.org/p/{n}" for n in range(200))
    r = br.reachable(many, {})
    assert len(texts(r)) == br.REFS_MAX


def test_extra_references_of_an_inbox_item_count():
    r = br.reachable("The run failed.", {}, extra=[{"gh_pr": "acme/app#7"}, {"task_status": "spec-gap-analysis"}],
                     folder_of=SLUGS.get)
    assert "acme/app#7" in texts(r) and "spec-gap-analysis" in texts(r)


# ---------------------------------------------------------------- what a brief points at

def parts_of(text, r=None):
    r = r or reach()
    return br.parts(text, br.resolutions([text], r))


def links(parts):
    return [(p["text"], p["ref"]) for p in parts if "ref" in p]


def missing(parts):
    return [p["text"] for p in parts if p.get("unresolved")]


def test_a_bare_number_with_one_bound_repository_becomes_owner_repo_and_a_link():
    parts = parts_of("All 16 gaps are marked done in epic #95.")
    [(text, ref)] = links(parts)
    assert text == f"{REPO}#95"
    assert ref == {"kind": "web", "href": f"https://github.com/{REPO}/issues/95"}
    assert "".join(p["text"] for p in parts) == f"All 16 gaps are marked done in epic {REPO}#95."


def test_a_bare_number_without_a_repository_or_with_two_is_unresolved():
    none = br.reachable("Epic #95 is open.", {"sync": {"bridge_only": True}})
    assert missing(parts_of("Epic #95 is closed.", none)) == ["#95"]
    two = br.reachable("Epic #95 is open.", {"context": "acme"}, context={"repos": [{"github": "a/b"}, {"github": "a/c"}]})
    assert missing(parts_of("Epic #95 is closed.", two)) == ["#95"]


def test_a_number_the_text_never_names_is_unresolved_even_in_the_bound_repository():
    assert missing(parts_of(f"Issue {REPO}#511 is linked.")) == [f"{REPO}#511"]
    assert missing(parts_of("Pull request #38 is merged.")) == ["#38"]


def test_a_section_without_a_place_is_unresolved_and_with_one_it_is_plain_text():
    assert missing(parts_of("The open points of the report (Bericht §6) are answered.")) == ["§6"]
    parts = parts_of("The points of docs/mapping.md §6 are answered.")
    assert missing(parts) == [] and [t for t, _ in links(parts)] == ["docs/mapping.md"]


def test_a_path_that_exists_becomes_a_file_link_and_one_that_does_not_is_unresolved():
    parts = parts_of("Every gap of work/tasks/ubl-fix/gaps.md is closed.")
    assert links(parts) == [("work/tasks/ubl-fix/gaps.md", {"kind": "file", "path": "work/tasks/ubl-fix/gaps.md"})]
    # a file of the task folder named by its place inside the folder
    assert links(parts_of("deliverables/report.md is signed off."))[0][1]["path"] == "work/tasks/ubl-fix/deliverables/report.md"
    assert missing(parts_of("Bericht.md is signed off.")) == ["Bericht.md"]
    assert missing(parts_of("docs/review-list.md is empty.")) == ["docs/review-list.md"]


def test_a_slug_becomes_a_task_link():
    parts = parts_of("The analysis of spec-gap-analysis is closed.")
    assert links(parts) == [("spec-gap-analysis", {"kind": "task", "key": "spec-gap-analysis", "folder": None})]
    closed = br.reachable("see old-work", {}, folder_of={"old-work": "work/done/2026-09/old-work"}.get)
    assert links(parts_of("old-work stays closed.", closed))[0][1] == {"kind": "task", "key": "old-work",
                                                                        "folder": "work/done/2026-09/old-work"}
    # an unknown slug in backticks is a reference that cannot be found; a plain hyphenated word is a word
    assert missing(parts_of("The `review-list` is empty.")) == ["review-list"]
    assert parts_of("It runs end-to-end.") is None


def test_urls_and_full_references_resolve_only_when_reachable():
    assert links(parts_of("The checklist acme/wiki#164 is done."))[0][1]["href"] == "https://github.com/acme/wiki/issues/164"
    assert links(parts_of("Rules at https://example.org/peppol/rules."))[0] == (
        "https://example.org/peppol/rules", {"kind": "web", "href": "https://example.org/peppol/rules"})
    assert missing(parts_of("See https://example.org/other.")) == ["https://example.org/other"]
    gh = parts_of(f"Issue https://github.com/{REPO}/issues/95 is closed.")
    assert links(gh)[0][1]["href"] == f"https://github.com/{REPO}/issues/95"


def test_a_board_number_resolves_to_the_bound_board_only():
    assert links(parts_of("Board #18 shows every batch."))[0][1]["href"] == "https://github.com/orgs/acme/projects/18"
    assert missing(parts_of("Board #19 shows every batch.")) == ["Board #19"]


def test_a_text_without_references_has_no_parts_and_unknown_raw_text_stays_plain():
    assert parts_of("Test invoices are accepted without validation errors.") is None
    # the card of a text the describe view has not looked at (no entry in refs) draws it plain, never as missing
    assert br.parts("Epic #95 is closed.", {}) == [{"text": "Epic #95 is closed."}]
    assert br.parts("Epic #95 is closed.", None) is None


def test_unresolved_names_every_reference_a_reader_cannot_reach():
    r = reach()
    goal, crit = "Bericht §6 is answered", "Epic #95 and #90 are closed"
    refs = br.resolutions([goal, crit], r)
    assert br.unresolved([goal, crit], refs) == ["§6", "#90"]


# ---------------------------------------------------------------- review fixes: no false positives

def test_a_law_section_is_no_reference():
    for text in ("Die Rechnung nennt § 14 UStG korrekt.", "Nach §§ 7, 8 EStG abgeschrieben.",
                 "Gemäß § 3 Abs. 2 geprüft.", "Wie §25a Nr. 1 verlangt."):
        assert not missing(parts_of(text) or []), text
    assert missing(parts_of("Der Bericht §6 ist beantwortet.")) == ["§6"]


def test_words_with_slashes_and_framework_names_are_no_paths_or_files():
    for text in ("Soll/Ist/Delta stimmen überein.", "TCP/IP/UDP sind offen.", "Node.js und Vue.js laufen.",
                 "Peppol/UBL/EN16931 passt."):
        assert parts_of(text) is None, text
    assert missing(parts_of("Unknown/Folder/ is empty.")) == ["Unknown/Folder/"]
    assert missing(parts_of("./notes/plan is done.")) == ["./notes/plan"]
    assert missing(parts_of("work/tasks/other/plan is done.")) == ["work/tasks/other/plan"]


def test_a_plain_word_in_backticks_is_no_slug_unless_known():
    for text in ("The `done` state is set.", "Merged into `main`.", "The `inbox` is empty."):
        assert parts_of(text) is None, text
    known = br.reachable("see `inbox`", {}, folder_of={"inbox": "work/tasks/inbox"}.get)
    assert links(parts_of("The `inbox` task is closed.", known))[0][1]["key"] == "inbox"


def test_a_hex_colour_is_no_issue_number():
    for text in ("The colour #a1b2c3 is used.", "Badge #123abc shows.", "Farbe #123 bleibt."):
        assert not missing(parts_of(text) or []), text


def test_issues_of_the_sync_block_need_the_items_own_repository():
    front = {"context": "acme", "sync": {"github": {"repo": "not a repo", "issues": [95], "project": {"org": "bad org!", "number": 3}}}}
    r = br.reachable("x", front, context={"repos": [{"github": "acme/one"}]})
    assert r["repos"] == ["acme/one"]
    assert not any(x.endswith("#95") for x in texts(r)), "never against the context's repository"
    assert r["project"] is None and not any("projects" in x for x in texts(r))


def test_a_hidden_component_anywhere_in_a_path_is_never_reachable():
    every = lambda _p: True  # noqa: E731
    r = br.reachable("See a/.git/config, foo/.env and docs/ok.md.", {}, exists=every)
    assert texts(r) == ["docs/ok.md"]


def test_slugs_the_text_names_come_before_the_files_of_the_folder_when_the_list_is_full():
    urls = " ".join(f"https://example.org/p/{n}" for n in range(br.REFS_MAX - 4))
    folder = {f"task-{n}": f"work/tasks/task-{n}" for n in range(3)}
    files = [f"work/tasks/ubl-fix/f{n}.md" for n in range(12)]
    r = br.reachable(f"{urls} task-0 task-1 task-2", {}, own="work/tasks/ubl-fix", folder_of=folder.get, files=files)
    got = texts(r)
    assert len(got) == br.REFS_MAX and {"task-0", "task-1", "task-2"} <= set(got)
    assert got[-1] == "work/tasks/ubl-fix/f0.md"
