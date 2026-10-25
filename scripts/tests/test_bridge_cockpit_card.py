# SPDX-License-Identifier: MIT
"""One card for every item (scripts/lib/bridge_cockpit/card.py, docs/bridge-cockpit-dev.md "One card for every item").

Every kind of entry the cockpit shows (a task, a stream, a closed task, an inbox item, a GitHub issue or pull
request, a calendar event, a check, a command or info row, a tab that asks) reaches the page as a `card` of one
shape: exactly the keys of card_fields.CARD_FIELDS, every one of them optional. These tests hold each adapter to
the mapping, the derived `written` and `gaps`, the link to a closed task, the closes_when probe in words and the
card the detail readers attach.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.bridge_cockpit import card as cd  # noqa: E402
from lib.bridge_cockpit import details, model  # noqa: E402
from lib.bridge_cockpit.card_fields import CARD_FIELDS, NEXT_FIELDS, STATE_FIELDS  # noqa: E402
from lib.bridge_cockpit.text import T  # noqa: E402

BRIEF = {"goal": "Invoices reach the customer without a manual resend",
         "story": {"as": "an accountant", "want": "every invoice delivered once", "so_that": "nobody chases a resend"},
         "acceptance": ["No invoice is delivered twice"], "by": "claude-haiku-5-5", "at": "2026-10-25",
         "edited": False}
TASK = {"slug": "invoices", "title": "Invoice delivery", "kind": "tasks", "status": "doing", "priority": "P1",
        "area": "Billing", "updated": "2026-10-20", "next": "Ask the customer for the rejected ids",
        "next_who": "me", "next_due": "2026-10-28", "headline": "Invoices bounce at the customer gateway",
        "brief": None, "progress": {"done": 1, "total": 3}, "placeholder": False, "blocked_by": None}
ORIGIN = {"category": "work", "word_key": "task", "detail": None, "raw": None, "ref": None, "via_cockpit": False}


def row(**extra) -> dict:
    base = {"key": "task:invoices", "bucket": "do", "title": "Invoice delivery", "task": "invoices", "inbox_id": None,
            "priority": "P1", "area": "Billing", "due": None, "status": "doing",
            "next": {"what": "Ask the customer for the rejected ids", "from": "status", "since": "2026-10-20", "key": None},
            "origin": ORIGIN, "work_kind": "task", "link": None, "gate": None, "inbox_kind": None, "inbox_state": None}
    base.update(extra)
    return base


def ctx(**extra) -> cd.Ctx:
    base = {"tasks": {"invoices": dict(TASK)}, "work": {"invoices": "task"}}
    base.update(extra)
    return cd.Ctx(**base)


def assert_shape(card: dict) -> None:
    assert tuple(card) == CARD_FIELDS
    if card["next"] is not None:
        assert tuple(card["next"]) == NEXT_FIELDS
    if card["state"] is not None:
        assert tuple(card["state"]) == STATE_FIELDS


# ---------------------------------------------------------------- tasks and streams

def test_a_task_row_maps_title_next_state_and_the_headline_as_summary():
    c = cd.card_of(row(), ctx())
    assert_shape(c)
    assert c["kind"] == "task" and c["subkind"] is None
    assert c["title"] == "Invoice delivery"
    assert c["summary"] == "Invoices bounce at the customer gateway"
    assert c["next"] == {"what": "Ask the customer for the rejected ids", "who": "me", "due": "2026-10-28",
                         "from": "status", "since": "2026-10-20"}
    assert c["state"] == {"word": "doing", "blocked_by": None, "since": None}
    assert (c["owner"], c["priority"], c["area"], c["updated"], c["due"]) == ("me", "P1", "Billing", "2026-10-20", "2026-10-28")
    assert c["progress"] == {"done": 1, "total": 3}
    assert c["source"] == ORIGIN
    assert c["links"] == [{"kind": "task", "key": "invoices", "label": "Invoice delivery", "closed": False}]
    assert c["written"] == "status"
    assert c["gaps"] == ["no_goal"]


def test_a_brief_gives_goal_story_acceptance_and_the_story_is_the_summary():
    c = cd.card_of(row(), ctx(tasks={"invoices": {**TASK, "brief": BRIEF}}))
    assert c["goal"] == BRIEF["goal"]
    assert c["story"] == BRIEF["story"]
    assert c["acceptance"] == BRIEF["acceptance"]
    assert c["summary"] == "As an accountant, I want every invoice delivered once, so that nobody chases a resend."
    assert c["written"] == "ai" and c["gaps"] == []


def test_the_story_sentence_follows_the_language():
    tx = T("de")["card"]
    c = cd.card_of(row(), ctx(tx=tx, tasks={"invoices": {**TASK, "brief": BRIEF}}))
    assert c["summary"].startswith("Als an accountant möchte ich every invoice delivered once, damit ")


def test_written_is_human_once_edited_and_status_for_a_brief_without_a_model():
    edited = cd.card_of(row(), ctx(tasks={"invoices": {**TASK, "brief": {**BRIEF, "edited": True}}}))
    assert edited["written"] == "human"
    by_hand = {k: v for k, v in BRIEF.items() if k not in ("by", "edited")}
    assert cd.card_of(row(), ctx(tasks={"invoices": {**TASK, "brief": by_hand}}))["written"] == "status"


def test_a_brief_the_gate_refuses_is_not_shown():
    bad = {**BRIEF, "goal": "x" * 141}
    c = cd.card_of(row(), ctx(tasks={"invoices": {**TASK, "brief": bad}}))
    assert c["goal"] is None and "no_goal" in c["gaps"] and c["written"] == "status"


def test_a_proposal_of_the_describe_hook_fills_a_task_without_a_brief_and_reads_as_ai():
    c = cd.card_of(row(), ctx(describe={"task:invoices": {"brief": BRIEF}}))
    assert c["goal"] == BRIEF["goal"] and c["written"] == "ai"
    stored = cd.card_of(row(), ctx(tasks={"invoices": {**TASK, "brief": {**BRIEF, "goal": "Stored goal", "edited": True}}},
                                   describe={"task:invoices": {"brief": BRIEF}}))
    assert stored["goal"] == "Stored goal"


def test_the_headline_is_clipped_to_140_and_the_triage_gist_stands_in_without_one():
    long = "word " * 60
    c = cd.card_of(row(), ctx(tasks={"invoices": {**TASK, "headline": long}}))
    assert len(c["summary"]) <= 140 and c["summary"].endswith("…")
    gist = cd.card_of(row(), ctx(tasks={"invoices": {**TASK, "headline": None}},
                                 triage={"task:invoices": {"gist": "Bounced invoices", "doer": "ai"}}))
    assert gist["summary"] == "Bounced invoices" and gist["written"] == "ai"
    bare = cd.card_of(row(), ctx(tasks={"invoices": {**TASK, "headline": None}}))
    assert bare["summary"] is None and bare["written"] == "title"


def test_the_owner_falls_back_to_the_triage_doer():
    facts = {**TASK, "next_who": None}
    for doer, owner in (("ai", "bridge"), ("you", "me"), ("either", "bridge_then_me"), ("nobody", None)):
        c = cd.card_of(row(), ctx(tasks={"invoices": facts}, triage={"task:invoices": {"doer": doer}}))
        assert c["owner"] == owner, doer


def test_no_next_and_the_template_placeholder_are_gaps():
    none = cd.card_of(row(next=None), ctx(tasks={"invoices": {**TASK, "next": None}}))
    assert none["next"] is None and "no_next" in none["gaps"]
    first = cd.card_of(row(next={"what": "First step", "from": "status", "since": None, "key": None}), ctx())
    assert "placeholder_next" in first["gaps"]
    body = cd.card_of(row(), ctx(tasks={"invoices": {**TASK, "placeholder": True}}))
    assert "placeholder_next" in body["gaps"]


def test_a_task_row_without_a_next_of_its_own_reads_the_task_list():
    c = cd.card_of(row(next=None, status=None), ctx())
    assert c["next"]["what"] == TASK["next"] and c["next"]["from"] == "status"
    assert c["state"]["word"] == "doing"


def test_a_next_from_the_inbox_keeps_its_source_and_no_status_who():
    nxt = {"what": "Approve the resend", "from": "inbox", "since": "2026-10-21T09:00", "key": "inbox:x"}
    c = cd.card_of(row(next=nxt), ctx())
    assert c["next"] == {"what": "Approve the resend", "who": None, "due": None, "from": "inbox",
                         "since": "2026-10-21T09:00"}


def test_a_blocked_task_says_so_in_its_state():
    c = cd.card_of(row(), ctx(tasks={"invoices": {**TASK, "blocked_by": "customer gateway down"}}))
    assert c["state"]["blocked_by"] == "customer gateway down"


def test_a_stream_has_no_goal_gap_for_acceptance_and_kind_stream():
    c = cd.card_of(row(work_kind="stream"), ctx(tasks={"invoices": {**TASK, "kind": "streams"}},
                                                work={"invoices": "stream"}))
    assert c["kind"] == "stream"


def test_a_closed_task_has_a_closed_link_and_no_gaps():
    c = cd.card_of(row(work_kind="done_task", status="done", next=None),
                   ctx(tasks={}, work={"invoices": "done_task"}))
    assert c["kind"] == "done_task"
    assert c["links"][0]["closed"] is True
    assert c["gaps"] == []


# ---------------------------------------------------------------- inbox

INBOX_FACTS = {"detail": "The customer gateway rejected 14 invoices last night; a resend needs your yes.",
               "kind": "decision", "gate": "your-yes", "due": "2026-10-27", "created": "2026-10-24T08:00",
               "task": None, "closes_when": None, "closer": None, "brief": None, "updated": "2026-10-24T09:00",
               "area": "Billing"}


def inbox_row(**extra) -> dict:
    base = {"key": "inbox:20261024-0800-resend", "bucket": "do", "title": "Resend 14 invoices",
            "inbox_id": "20261024-0800-resend", "task": None, "gate": "your-yes", "inbox_kind": "decision",
            "inbox_state": "open", "due": "2026-10-27", "priority": None, "area": "Billing", "created": "2026-10-24T08:00",
            "origin": {"category": "bot"}, "work_kind": None, "link": None, "next": None, "status": None}
    base.update(extra)
    return base


def inbox_ctx(facts=None, **extra) -> cd.Ctx:
    got = {**INBOX_FACTS, **(facts or {})}
    return ctx(inbox=lambda item_id: got if item_id == "20261024-0800-resend" else None, **extra)


def test_an_inbox_row_maps_subkind_owner_next_and_its_detail_as_summary():
    c = cd.card_of(inbox_row(), inbox_ctx())
    assert_shape(c)
    assert (c["kind"], c["subkind"]) == ("inbox", "decision")
    assert c["title"] == "Resend 14 invoices"
    assert c["summary"] == "The customer gateway rejected 14 invoices last night; a resend needs your yes."
    assert c["owner"] == "bridge_then_me"
    assert c["next"]["what"] == "decide" and c["next"]["who"] == "me" and c["next"]["from"] == "item"
    assert c["state"] == {"word": "open", "blocked_by": None, "since": "2026-10-24T08:00"}
    assert c["due"] == "2026-10-27" and c["updated"] == "2026-10-24T09:00"
    assert c["links"] == [{"kind": "inbox", "key": "20261024-0800-resend", "label": "Resend 14 invoices"}]
    assert c["written"] == "item" and c["gaps"] == ["no_goal"]


def test_the_gate_names_the_owner():
    for gate, owner in (("only-you", "me"), ("your-yes", "bridge_then_me"), ("free", "bridge"), (None, None)):
        assert cd.card_of(inbox_row(gate=gate), inbox_ctx({"gate": gate}))["owner"] == owner


def test_the_latest_describe_brief_of_an_item_fills_goal_and_story():
    c = cd.card_of(inbox_row(), inbox_ctx({"brief": BRIEF}))
    assert c["goal"] == BRIEF["goal"] and c["written"] == "ai" and "no_goal" not in c["gaps"]


def test_an_item_that_closes_by_itself_says_when_in_its_next():
    probe = {"gh_pr": "example/repo#12", "state": "merged"}
    c = cd.card_of(inbox_row(gate="free"), inbox_ctx({"gate": "free", "kind": "finding", "closes_when": probe}))
    assert c["next"]["what"] == "closes by itself when pull request example/repo#12 is merged"
    assert c["next"]["from"] == "probe" and c["next"]["who"] == "bridge"


def test_an_item_on_a_closed_task_links_it_closed_and_has_the_gap():
    c = cd.card_of(inbox_row(task="old-task"), inbox_ctx({"task": "old-task"}, work={"old-task": "done_task"}))
    task_link = [x for x in c["links"] if x["kind"] == "task"]
    assert task_link == [{"kind": "task", "key": "old-task", "label": "old-task", "closed": True}]
    assert "task_closed" in c["gaps"]


def test_an_item_whose_detail_barely_adds_to_its_title_has_no_content():
    c = cd.card_of(inbox_row(title="example/repo#7 is assigned to you"),
                   inbox_ctx({"detail": "example/repo#7 is assigned to you, no Bridge task"}))
    assert "no_content" in c["gaps"]
    assert c["summary"] is None and c["written"] == "title"


def test_an_inbox_row_without_facts_still_has_a_card():
    c = cd.card_of(inbox_row(), ctx())
    assert_shape(c)
    assert c["kind"] == "inbox" and c["title"] == "Resend 14 invoices"
    assert c["gaps"] == ["no_goal"] and c["next"]["what"] == "decide" and c["due"] == "2026-10-27"


def test_the_triage_gist_stands_in_for_an_item_without_detail():
    c = cd.card_of(inbox_row(), inbox_ctx({"detail": None}, triage={"inbox:20261024-0800-resend": {"gist": "A resend"}}))
    assert c["summary"] == "A resend" and c["written"] == "ai"


# ---------------------------------------------------------------- probe text

@pytest.mark.parametrize("spec,en,de", [
    ({"gh_pr": "a/b#1"}, "pull request a/b#1 is merged", "Pull Request a/b#1 ist gemergt"),
    ({"gh_issue": "a/b#2"}, "issue a/b#2 is closed", "Issue a/b#2 ist geschlossen"),
    ({"task_status": "demo"}, "task demo reaches done", "Aufgabe demo steht auf done"),
    ({"path_exists": "out/x.pdf"}, "out/x.pdf exists", "out/x.pdf existiert"),
    ({"after": "2026-10-30T09:00"}, "after 30.10.2026 09:00", "nach dem 30.10.2026 09:00"),
    ({"unseen_for": {"hours": 24}}, "its reporter has not seen it for 24 hours",
     "der Melder hat es 24 Stunden nicht mehr gesehen"),
    ({"command": ["make", "check"]}, "the command make check succeeds", "der Befehl make check gelingt"),
    ({"all": [{"gh_pr": "a/b#1"}, {"nope": 1}]}, "pull request a/b#1 is merged and a check the page cannot describe",
     "Pull Request a/b#1 ist gemergt und eine Prüfung, die die Seite nicht beschreiben kann"),
    ({"any": [{"path_exists": "a"}, {"path_exists": "b"}]}, "a exists or b exists", "a existiert oder b existiert"),
])
def test_probe_text_says_a_closes_when_in_words(spec, en, de):
    assert cd.probe_text(spec, T("en")["card"]) == en
    assert cd.probe_text(spec, T("de")["card"]) == de


def test_probe_text_is_none_without_a_probe():
    for spec in (None, [], "x", 3):
        assert cd.probe_text(spec) is None


# ---------------------------------------------------------------- page items

def info(**extra) -> dict:
    base = {"key": "item:x", "title": "Row", "detail": "", "when": "", "tone": None, "link": None, "task": None,
            "priority": None, "state": None, "lines": [], "gh": None, "cal": None, "due_at": None, "inbox": None,
            "at": None, "who": None, "flags": None, "origin": {"category": "other"}, "work_kind": None}
    base.update(extra)
    return base


GH = {"title": "Fix the gateway retry", "repo": "example/repo", "number": 12, "type": "pr", "state": "open",
      "status": "In Review", "priority": "P1", "labels": ["bug"], "people": ["alice"], "prs": [], "task": "invoices",
      "stream": False, "changed": "2026-10-24T10:00", "quiet": None, "note": None}


def test_a_github_pull_request_maps_its_facts():
    c = cd.card_of(info(title="Fix the gateway retry", gh=GH, flags=["ask_review"],
                        link={"kind": "web", "href": "https://github.com/example/repo/pull/12"}), ctx())
    assert_shape(c)
    assert (c["kind"], c["subkind"]) == ("github", "pr")
    assert c["title"] == "Fix the gateway retry"
    assert c["state"]["word"] == "In Review" and c["priority"] == "P1" and c["updated"] == "2026-10-24T10:00"
    assert c["owner"] == "alice"
    assert c["summary"] == "bug"
    assert c["next"]["what"] == "review it" and c["next"]["who"] == "me"
    assert {"kind": "web", "href": "https://github.com/example/repo/pull/12", "label": "example/repo#12"} in c["links"]
    assert {"kind": "task", "key": "invoices", "label": "Invoice delivery", "closed": False} in c["links"]
    assert c["gaps"] == [] and c["goal"] is None


def test_a_github_issue_and_draft_keep_their_subkind_and_quiet_days():
    issue = cd.card_of(info(gh={**GH, "type": "issue", "status": None, "quiet": 9, "note": "Waiting on ops"}), ctx())
    assert issue["subkind"] == "issue" and issue["state"]["word"] == "open" and issue["summary"] == "Waiting on ops"
    assert issue["state"]["since"] == "2026-10-24T10:00"
    assert cd.card_of(info(gh={**GH, "type": "draft"}), ctx())["subkind"] == "draft"


def test_a_calendar_event_maps_where_people_and_its_state():
    cal = {"start": "2026-10-26T10:00", "end": "2026-10-26T11:00", "day": "2026-10-26", "minutes": 60,
           "all_day": False, "calendar": "Work", "info": False, "where": "Room 2", "online": False,
           "people": ["Alice", "Bob"], "past": False, "running": True, "overlaps": []}
    c = cd.card_of(info(title="Weekly", cal=cal), ctx())
    assert_shape(c)
    assert c["kind"] == "event" and c["title"] == "Weekly"
    assert c["summary"] == "Room 2 · Alice, Bob"
    assert c["due"] == "2026-10-26T10:00" and c["state"]["word"] == "running"
    past = cd.card_of(info(cal={**cal, "running": False, "past": True}), ctx())
    assert past["state"]["word"] == "past"


def test_a_check_and_a_command_row():
    check = cd.card_of(info(title="Backup", detail="last run 3 days ago", tone="bad",
                            link={"kind": "file", "path": "infra/backups/x.yaml"}), ctx(section_kind="command"))
    assert_shape(check)
    assert check["kind"] == "check" and check["state"]["word"] == "bad" and check["summary"] == "last run 3 days ago"
    assert check["links"] == [{"kind": "file", "path": "infra/backups/x.yaml", "label": "Backup"}]
    assert check["gaps"] == [] and check["written"] == "item"
    plain = cd.card_of(info(title="Disk", detail="41 GB free"), ctx(section_kind="command"))
    assert (plain["kind"], plain["subkind"]) == ("info", "command")
    other = cd.card_of(info(title="Commit"), ctx(section_kind="commits"))
    assert (other["kind"], other["subkind"], other["written"]) == ("info", "commits", "title")


def test_a_page_item_that_is_a_task_or_an_inbox_item_gets_their_card():
    task = cd.card_of(info(title="Invoice delivery", task="invoices", work_kind="task"), ctx())
    assert task["kind"] == "task" and task["next"]["what"] == TASK["next"]
    item = cd.card_of(info(title="Resend 14 invoices", inbox="20261024-0800-resend"), inbox_ctx())
    assert item["kind"] == "inbox" and item["subkind"] == "decision"


def test_a_tab_that_asks():
    tab = {"ref": "surface:4", "name": "Invoices tab", "state": "needs-you", "workspace": "Billing", "slug": "invoices",
           "ask": {"text": "Proceed with the resend?", "options": [{"n": 1, "label": "Yes"}, {"n": 2, "label": "No"}]}}
    c = cd.card_of(tab, ctx())
    assert_shape(c)
    assert c["kind"] == "ask" and c["title"] == "Invoices tab" and c["summary"] == "Proceed with the resend?"
    assert c["next"]["what"] == "Yes / No" and c["owner"] == "me" and c["state"]["word"] == "needs-you"
    assert c["area"] == "Billing"
    assert {"kind": "task", "key": "invoices", "label": "Invoice delivery", "closed": False} in c["links"]


def test_card_of_never_raises_and_keeps_its_keys_on_junk():
    for raw in (None, {}, {"bucket": "do", "key": 3}, {"front": "x", "slug": None}, {"ask": {}, "ref": 1}, [], "x"):
        assert tuple(cd.card_of(raw)) == CARD_FIELDS


# ---------------------------------------------------------------- the checklist helpers

def test_progress_and_placeholder_count_the_body_outside_code_fences():
    text = "---\nstatus: doing\n---\n# T\n\n- [x] one\n- [ ] First step\n```\n- [ ] example\n```\n"
    assert cd.progress(text) == {"done": 1, "total": 2}
    assert cd.placeholder_steps(text) is True
    assert cd.placeholder_steps("# T\n\n- [ ] First action\n- [ ] Second action\n") is True
    assert cd.placeholder_steps("# T\n\n- [ ] Ship it\n- [x] First step\n") is False
    assert cd.progress("# no list\n") is None


# ---------------------------------------------------------------- the detail readers attach the card

def bridge(tmp_path: Path) -> Path:
    root = tmp_path / "bridge"
    task = root / "work" / "tasks" / "invoices"
    task.mkdir(parents=True)
    (task / "STATUS.md").write_text(
        "---\nstatus: doing\npriority: P1\nlast_updated: 2026-10-20\nheadline: Invoices bounce\n"
        "next: {what: Ask the customer, who: me, due: 2026-10-28}\n"
        "brief:\n  goal: Invoices reach the customer\n  by: claude-haiku-5-5\n  edited: false\n---\n\n"
        "# Invoice delivery\n\n## Next Steps\n\n- [x] Read the log\n- [ ] Ask the customer\n", encoding="utf-8")
    done = root / "work" / "done" / "2026-10" / "old-task"
    done.mkdir(parents=True)
    (done / "STATUS.md").write_text("---\nstatus: done\n---\n\n# Old task\n\n## Notes\n\nIt shipped.\n", encoding="utf-8")
    item = root / "work" / "inbox" / "20261024-0800-resend"
    (item / "events").mkdir(parents=True)
    (item / "item.yaml").write_text(
        "schema_version: 1\ncreated: '2026-10-24T08:00'\nfrom: briefing/demo\nkind: question\nsummary: Resend?\n"
        "detail: The gateway rejected 14 invoices last night and the customer asks whether we resend them today.\n"
        "gate: only-you\ntask: old-task\n", encoding="utf-8")
    (item / "events" / "20261024T090000Z-01-x-describe.yaml").write_text(
        "verb: describe\nby: claude-haiku-5-5\nat: '2026-10-24T09:00'\nbrief:\n  goal: The customer knows what we resend\n",
        encoding="utf-8")
    (item / "events" / "20261024T080000Z-00-x-describe.yaml").write_text(
        "verb: describe\nby: claude-haiku-5-5\nat: '2026-10-24T08:30'\nbrief:\n  goal: An older goal\n", encoding="utf-8")
    return root


def test_task_detail_attaches_a_card_read_from_its_status_md(tmp_path):
    root = bridge(tmp_path)
    d = details.task_detail(root, "invoices", [])
    c = d["card"]
    assert_shape(c)
    assert c["kind"] == "task" and c["title"] == "Invoice delivery"
    assert c["goal"] == "Invoices reach the customer" and c["written"] == "ai"
    assert c["next"] == {"what": "Ask the customer", "who": "me", "due": "2026-10-28", "from": "status",
                         "since": "2026-10-20"}
    assert c["progress"] == {"done": 1, "total": 2}
    assert d["front"]["next"] == "Ask the customer"          # the old fields stay as they were


def test_a_closed_task_detail_reads_as_done(tmp_path):
    c = details.task_detail(bridge(tmp_path), "old-task", [])["card"]
    assert c["kind"] == "done_task" and c["state"]["word"] == "done" and c["links"][0]["closed"] is True
    assert c["gaps"] == []


def test_inbox_detail_attaches_a_card_with_the_latest_describe_brief(tmp_path):
    root = bridge(tmp_path)
    d = details.inbox_detail(root, "20261024-0800-resend", [{"id": "20261024-0800-resend", "state": "open"}])
    c = d["card"]
    assert_shape(c)
    assert (c["kind"], c["subkind"], c["owner"]) == ("inbox", "question", "me")
    assert c["goal"] == "The customer knows what we resend"
    assert c["next"]["what"] == "answer"
    assert "task_closed" in c["gaps"]
    assert d["item"]["summary"] == "Resend?"


def test_inbox_facts_reads_an_item_once_until_it_changes(tmp_path):
    root = bridge(tmp_path)
    first = details.inbox_facts(root, "20261024-0800-resend")
    assert first["brief"]["goal"] == "The customer knows what we resend" and first["kind"] == "question"
    assert details.inbox_facts(root, "20261024-0800-resend") is first
    assert details.inbox_facts(root, "../etc") is None and details.inbox_facts(root, "20261024-0800-none") is None


def test_workplace_lists_the_placeholder_and_the_model_passes_it_on(tmp_path):
    root = Path(__file__).resolve().parents[2]
    spec = importlib.util.spec_from_file_location("workplace_for_card", root / "scripts" / "workplace.py")
    wp = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(wp)
    for slug, steps in (("fresh", "- [ ] First step\n"), ("real", "- [ ] Ship it\n")):
        folder = tmp_path / "work" / "tasks" / slug
        folder.mkdir(parents=True)
        (folder / "STATUS.md").write_text(f"---\nstatus: doing\n---\n\n# {slug}\n\n{steps}", encoding="utf-8")
    tasks = {t["slug"]: t for t in wp.collect_tasks(tmp_path)}
    assert tasks["fresh"]["placeholder"] is True and tasks["real"]["placeholder"] is False
    assert tasks["fresh"]["progress"] == {"done": 0, "total": 1}
    rows = wp.task_rows(tmp_path, {}, wp.dt.date(2026, 10, 25))
    parsed = {t["slug"]: t for t in model.parse_tasks(json.dumps(rows))}
    assert parsed["fresh"]["placeholder"] is True and parsed["real"]["placeholder"] is False
