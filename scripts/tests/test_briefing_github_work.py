# SPDX-License-Identifier: MIT
"""The github-work tracker: one row per piece of GitHub work, and the steps a person starts on it.

Two sections (your issues and PRs, the boards) showed the same card twice and disagreed (an issue
`open` in one, `In Progress` in the other, live 2026-10-17), and Do it on a GitHub row gave the agent a
title and a link and nothing else. github-work merges both by id, names the board, the pull requests
that close the issue, the Bridge task that syncs it and the inbox item an agent was started on, and
offers steps whose prompt carries all of it. A step runs nothing itself: `briefing.py act` hands back
the tab to start. Recorded answers only, never a live GitHub."""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "scripts" / "tests" / "fixtures" / "briefing"
sys.dont_write_bytecode = True
if "briefing" in sys.modules:
    bf = sys.modules["briefing"]
else:
    spec = importlib.util.spec_from_file_location("briefing", ROOT / "scripts" / "briefing.py")
    assert spec is not None and spec.loader is not None
    bf = importlib.util.module_from_spec(spec)
    sys.modules["briefing"] = bf
    spec.loader.exec_module(bf)

NOW = dt.datetime(2026, 10, 4, 8, 0)

CARDS = {"items": [
    {"status": "In Progress", "assignees": ["octo"], "labels": [], "title": "Board import drops emoji states",
     "content": {"number": 12, "title": "Board import drops emoji states", "type": "Issue",
                 "repository": "example-org/tool", "updatedAt": "2026-10-03T08:00:00Z",
                 "url": "https://github.com/example-org/tool/issues/12"}},
    {"status": "Todo", "assignees": ["hubot"], "labels": [], "title": "Someone else's card",
     "content": {"number": 50, "title": "Someone else's card", "type": "Issue", "repository": "example-org/tool",
                 "updatedAt": "2026-10-02T08:00:00Z", "url": "https://github.com/example-org/tool/issues/50"}},
]}

# which pull request closes which issue: #31 closes #12
CLOSING = {("example-org/tool", 12): {"closedByPullRequestsReferences": {"nodes": [
    {"number": 31, "url": "https://github.com/example-org/tool/pull/31", "isDraft": False,
     "repository": {"nameWithOwner": "example-org/tool"}}]}},
    ("example-org/tool", 31): {"closingIssuesReferences": {"nodes": [
        {"number": 12, "repository": {"nameWithOwner": "example-org/tool"}}]}}}


def graphql(argv):
    query = argv[-1]
    data = {}
    for alias, owner, name, number in re.findall(
            r'(i\d+): repository\(owner: "([^"]+)", name: "([^"]+)"\) \{ issueOrPullRequest\(number: (\d+)\)', query):
        data[alias] = {"issueOrPullRequest": CLOSING.get((f"{owner}/{name}", int(number)), {})}
    return json.dumps({"data": data})


class FakeRun:
    def __init__(self, answers):
        self.answers = answers
        self.calls: list = []

    def __call__(self, argv, timeout=30, cwd=None):
        self.calls.append(list(argv))
        for prefix, answer in self.answers.items():
            if tuple(argv[: len(prefix)]) == prefix:
                return answer(argv) if callable(answer) else answer
        raise bf.SourceError(f"no recorded answer for {argv[:4]}")


def answers(cards=CARDS):
    issues = (FIX / "github" / "search-issues.json").read_text()
    prs = (FIX / "github" / "search-prs.json").read_text()
    review = (FIX / "github" / "review-requested.json").read_text()
    return {("gh", "api", "user"): '{"login": "octo"}',
            ("gh", "api", "graphql"): graphql,
            ("gh", "search", "issues"): issues,
            ("gh", "search", "prs"): lambda argv: review if "--review-requested" in argv else prs,
            ("gh", "project", "item-list"): json.dumps(cards)}


def bridge(tmp_path: Path, boards: bool = True) -> Path:
    root = tmp_path / "bridge"
    (root / "work" / "inbox").mkdir(parents=True)
    (root / "work" / "tasks").mkdir(parents=True)
    (root / "bridge-config.yaml").write_text(yaml.safe_dump({"integrations": {"github": {"assignee_me": "octo"}}}),
                                             encoding="utf-8")
    if boards:
        (root / "ecosystem.yaml").write_text(yaml.safe_dump({"github_projects": [
            {"org": "example-org", "number": 3, "name": "Tool board"}]}), encoding="utf-8")
        (root / "workflow" / "projects").mkdir(parents=True)
        (root / "workflow" / "projects" / "tool.yaml").write_text(yaml.safe_dump(
            {"project": {"tracker": "github", "org": "example-org", "number": 3}}), encoding="utf-8")
    return root


def task(root: Path, slug: str, bucket: str = "tasks", **fm) -> None:
    d = root / "work" / bucket / slug
    d.mkdir(parents=True)
    fm = {"slug": slug, "status": "doing", **fm}
    (d / "STATUS.md").write_text(f"---\n{yaml.safe_dump(fm)}---\n\n# {slug}\n", encoding="utf-8")


SECTION = {"kind": "tracker", "id": "work", "provider": "github-work", "query": {"owners": ["example-org"]}}


def collect(root, section=SECTION, run=None):
    run = run or FakeRun(answers())
    c = bf.Context(root, now=NOW, run=run)
    sec = bf.collect(root, {"id": "p", "sections": [dict(section)]}, c)["sections"][0]
    assert sec["status"] == "ok", sec.get("reason")
    return {i["id"]: i for i in sec["items"]}, run


# ---------------------------------------------------------------- one row per piece of work

def test_a_card_and_a_search_hit_for_the_same_issue_are_one_row_with_the_board_status(tmp_path):
    rows, _ = collect(bridge(tmp_path))
    row = rows["example-org/tool#12"]
    assert row["state"] == "in_progress" and row["raw_state"] == "In Progress"
    assert row["board"]["name"] == "Tool board" and row["board"]["config"] == "workflow/projects/tool.yaml"
    assert row["group"] == "Tool board" and row["labels"] == ["bug"]       # the label only the search knew
    assert rows["example-org/site#7"]["group"] == "example-org/site"        # not on a board: its repository
    assert "example-org/tool#50" not in rows                                # someone else's card


def test_cards_all_brings_every_open_card_of_the_boards(tmp_path):
    section = dict(SECTION, query={"owners": ["example-org"], "cards": "all"})
    rows, run = collect(bridge(tmp_path), section)
    assert rows["example-org/tool#50"]["assigned_to_me"] is False
    listed = next(c for c in run.calls if c[:3] == ["gh", "project", "item-list"])
    assert listed[-2:] == ["--query", "is:open"]


def test_a_pull_request_that_closes_a_listed_issue_stands_in_its_row(tmp_path):
    rows, _ = collect(bridge(tmp_path))
    assert "example-org/tool#31" not in rows
    assert rows["example-org/tool#12"]["prs"] == [{"id": "example-org/tool#31", "draft": False,
                                                   "url": "https://github.com/example-org/tool/pull/31"}]
    assert rows["example-org/tool#40"]["category"] == "qa"        # asked to review: keeps its own row


def test_without_boards_the_search_alone_answers(tmp_path):
    rows, run = collect(bridge(tmp_path, boards=False))
    assert "example-org/tool#12" in rows and "board" not in rows["example-org/tool#12"]
    assert not [c for c in run.calls if c[:3] == ["gh", "project", "item-list"]]


# ---------------------------------------------------------------- what this Bridge knows about a row

def test_a_task_that_syncs_the_issue_becomes_the_rows_task_and_a_stream_is_only_named(tmp_path):
    root = bridge(tmp_path)
    task(root, "fix-emoji", sync={"github": {"repo": "example-org/tool", "issues": [12]}})
    task(root, "site-work", bucket="streams", sync={"github": {"issues": ["https://github.com/example-org/site/issues/7"]}})
    rows, _ = collect(root)
    assert rows["example-org/tool#12"]["task"] == "fix-emoji"
    assert rows["example-org/site#7"]["linked_task"]["slug"] == "site-work"
    assert "task" not in rows["example-org/site#7"]        # a stream never closes, it is no row's task


def test_the_newest_active_inbox_item_filed_for_a_row_names_it(tmp_path):
    root = bridge(tmp_path)
    box = bf._inbox().Inbox(root / "work" / "inbox", actor="test")
    new = box.add(source="cockpit", kind="decision", summary="go", key="tracker:implement:example-org/site#7")
    done = box.add(source="cockpit", kind="decision", summary="done", key="briefing:p:mine:example-org/tool#12")
    box.close(done)
    box.add(source="cockpit", kind="decision", summary="other", key="tracker:analyze:example-org/site#77")
    rows, _ = collect(root)
    assert rows["example-org/site#7"]["inbox"] == new
    assert "inbox" not in rows["example-org/tool#12"]          # a closed item stands for nothing


# ---------------------------------------------------------------- steps

def ids(row):
    return [a["id"] for a in row.get("actions") or []]


def test_built_in_steps_follow_what_the_row_is(tmp_path):
    root = bridge(tmp_path)
    task(root, "fix-emoji", sync={"github": {"repo": "example-org/tool", "issues": [12]}})
    rows, _ = collect(root)
    assert ids(rows["example-org/tool#12"]) == ["analyze", "review", "sync"]          # has a PR and a task
    assert ids(rows["example-org/site#7"]) == ["analyze", "implement", "adopt"]       # no board, no task
    assert ids(rows["example-org/tool#40"]) == ["analyze", "review"]                  # a PR to review


def test_a_sections_own_step_stands_beside_or_in_for_the_built_in_ones(tmp_path):
    section = dict(SECTION, row_steps=[
        {"id": "implement", "label": "Run the pipeline", "types": ["issue"], "prompt": "/pipeline {id} on {board}"},
        {"id": "triage", "label": "Triage", "boards": ["tool"], "prompt": "triage {id}"}])
    rows, _ = collect(bridge(tmp_path), section)
    site = {a["id"]: a["label"] for a in rows["example-org/site#7"]["actions"]}
    assert site["implement"] == "Run the pipeline" and "triage" not in site       # site#7 is on no board
    assert "triage" in ids(rows["example-org/tool#12"])
    off = dict(SECTION, default_steps=False)
    rows, _ = collect(bridge(tmp_path / "b"), off)
    assert not any(r.get("actions") for r in rows.values())


def test_a_done_row_offers_nothing(tmp_path):
    words = bf._view().labels_for("en")
    assert bf.tracker_steps({"provider": "github-work"}, {"id": "o/r#1", "state": "done"}, words) == []


def test_the_view_hands_the_steps_and_the_inbox_item_to_a_dashboard(tmp_path):
    view = bf._view()
    item = {"id": "o/r#1", "title": "Fix it", "state": "in_progress", "raw_state": "In Progress", "type": "issue",
            "project": "Board", "inbox": "20261004-0800-fix-it-ab12", "prs": [{"id": "o/r#2", "draft": True}],
            "actions": [{"id": "analyze", "label": "Analyse"}]}
    row = view._page_row("tracker", item, {"id": "work", "view": "board"}, NOW, view.labels_for("en"))
    assert row["actions"] == [{"id": "analyze", "label": "Analyse"}] and row["row_id"] == "o/r#1"
    assert row["inbox"] == "20261004-0800-fix-it-ab12" and row["actionable"] is False
    assert "PR #2 (draft)" in row["detail"] and "Board" not in row["detail"]      # the board is the lane head


# ---------------------------------------------------------------- act: the tab a step starts

def act_bridge(tmp_path):
    root = bridge(tmp_path)
    (root / "workflow" / "briefings").mkdir(parents=True)
    (root / "workflow" / "briefings" / "p.yaml").write_text(yaml.safe_dump(
        {"schema_version": 1, "scope": "user", "id": "p", "title": "P",
         "sections": [dict(SECTION, cache_minutes=5)]}), encoding="utf-8")
    return root


def test_a_step_comes_back_as_a_tab_to_start_from_the_rows_the_page_showed(tmp_path, capsys, monkeypatch):
    root = act_bridge(tmp_path)
    run = FakeRun(answers())
    c = bf.Context(root, now=dt.datetime.now(), run=run)
    profile = bf.load_profile(root, "p") if hasattr(bf, "load_profile") else yaml.safe_load(
        (root / "workflow" / "briefings" / "p.yaml").read_text())
    bf.collect(root, profile, c)                                  # the page's pass keeps the answer
    monkeypatch.setattr(bf, "_default_run", lambda *a, **k: (_ for _ in ()).throw(AssertionError("asked GitHub")))
    code = bf.main(["--root", str(root), "act", "p", "work", "example-org/site#7", "implement"])
    out = capsys.readouterr().out
    assert code == 0, out
    launch = json.loads(out)["launch"]
    assert launch["key"] == "tracker:implement:example-org/site#7"
    assert "https://github.com/example-org/site/issues/7" in launch["prompt"]
    assert "feature branch" in launch["prompt"] and "Never" in launch["prompt"] and "merge" in launch["prompt"]


def test_a_step_the_row_does_not_offer_is_refused(tmp_path, capsys):
    root = act_bridge(tmp_path)
    c = bf.Context(root, now=dt.datetime.now(), run=FakeRun(answers()))
    bf.collect(root, yaml.safe_load((root / "workflow" / "briefings" / "p.yaml").read_text()), c)
    for row, action in (("example-org/tool#40", "implement"), ("example-org/gone#1", "analyze"),
                        ("not a row", "analyze"), ("example-org/site#7", "rm -rf")):
        code = bf.main(["--root", str(root), "act", "p", "work", row, action])
        assert code == 2, (row, action)
    capsys.readouterr()


def test_the_prompt_carries_the_board_config_and_a_step_prompt_its_placeholders():
    words = bf._view().labels_for("de")
    item = {"id": "o/r#5", "title": "Fix", "url": "https://github.com/o/r/issues/5", "type": "issue",
            "state": "in_progress", "raw_state": "In Progress",
            "board": {"name": "Tools", "slug": "tools", "number": 3, "org": "o", "config": "workflow/projects/tools.yaml"},
            "linked_task": {"slug": "fix", "path": "work/tasks/fix/STATUS.md"}}
    text = bf.tracker_prompt({"id": "sync", "prompt": None}, item, words)
    assert "workflow/projects/tools.yaml" in text and "work/tasks/fix/STATUS.md" in text and "tracker-sync" in text
    own = bf.tracker_prompt({"id": "x", "prompt": "/pipeline {id} {board_slug} {nope}"}, item, words)
    assert own == "/pipeline o/r#5 tools {nope}"


# ---------------------------------------------------------------- validation

def test_row_steps_are_checked():
    good = {"kind": "tracker", "provider": "github-work", "query": {"owners": ["o"], "others_prs": 7},
            "row_steps": [{"id": "triage", "label": "Triage", "prompt": "x", "types": ["pr"]}]}
    assert bf._section_types(good) == []
    bad = dict(good, row_steps=[{"id": "Bad", "label": "", "prompt": "", "types": ["epic"], "colour": 1}],
               default_steps="yes")
    problems = " ".join(bf._section_types(bad))
    for word in ("unknown key", "id must", "label must", "prompt must", "types must", "default_steps must"):
        assert word in problems
    assert "belong to a tracker" in " ".join(bf._section_types({"kind": "command", "argv": ["x"], "row_steps": []}))


# ---------------------------------------------------------------- the shared GitHub budget

LIMITED = "gh: GraphQL: API rate limit already exceeded for user ID 1."


def limited_run(reset_in_min=20, hits=None):
    """GitHub that is out of budget: every call fails, rate_limit names the reset (it costs nothing)."""
    import time as _time
    reset = int(_time.time()) + reset_in_min * 60

    def run(argv, timeout=30, cwd=None):
        if hits is not None:
            hits.append(list(argv))
        if argv[:3] == ["gh", "api", "rate_limit"]:
            return json.dumps({"resources": {"graphql": {"remaining": 0, "reset": reset},
                                             "core": {"remaining": 4000, "reset": reset + 999}}})
        raise bf.SourceError(LIMITED)
    return run


def profile_with_cache():
    return {"id": "p", "sections": [dict(SECTION, cache_minutes=5)]}


def test_a_spent_budget_stops_every_github_section_until_the_reset(tmp_path):
    root = bridge(tmp_path)
    hits: list = []
    c = bf.Context(root, now=dt.datetime.now(), run=limited_run(hits=hits))
    sec = bf.collect(root, profile_with_cache(), c)["sections"][0]
    assert sec["status"] == "error" and "rate limit" in sec["reason"]      # nothing kept yet to show
    asked = [h for h in hits if h[:3] != ["gh", "api", "rate_limit"]]
    assert len(asked) <= 3            # the first answer stops the rest: no retries, no further boards or searches
    until = bf.github_blocked(root, dt.datetime.now())
    assert until is not None and 19 <= (until - dt.datetime.now()).total_seconds() / 60 <= 22
    hits.clear()
    other = {"id": "q", "sections": [{"kind": "tracker", "id": "mine", "provider": "github", "query": {}}]}
    c.fresh = True                                    # even a reload asks nothing while the budget is spent
    sec = bf.collect(root, other, c)["sections"][0]
    assert sec["status"] == "error" and "not asked until" in sec["reason"]
    assert hits == []


def test_the_block_never_outlives_an_hour_and_a_bit(tmp_path):
    root = bridge(tmp_path)
    c = bf.Context(root, now=dt.datetime.now(), run=limited_run(reset_in_min=600))
    until = bf.block_github(root, c, LIMITED)
    assert (until - c.now).total_seconds() / 60 <= bf.LIMIT_CAP_MIN
    unreadable = bf.Context(root, now=dt.datetime.now(), run=lambda *a, **k: (_ for _ in ()).throw(bf.SourceError("x")))
    until = bf.block_github(root, unreadable, LIMITED)
    assert 15 <= (until - unreadable.now).total_seconds() / 60 <= 17       # no answer: a quarter of an hour


def test_a_section_that_cannot_answer_shows_its_last_rows_and_closes_nothing(tmp_path):
    root = bridge(tmp_path)
    now = dt.datetime.now()
    good = bf.Context(root, now=now - dt.timedelta(minutes=30), run=FakeRun(answers()))
    kept = bf.collect(root, profile_with_cache(), good)["sections"][0]
    assert kept["status"] == "ok" and kept["total"]
    c = bf.Context(root, now=now, run=limited_run())
    result = bf.collect(root, profile_with_cache(), c)
    sec = result["sections"][0]
    assert sec["status"] == "ok" and sec["total"] == kept["total"]
    assert sec["stale"]["until"] and "rate limit" in sec["stale"]["reason"]
    assert "stale, as of" in bf.render(bf._public(result))
    view = bf._view()
    page = view._page_section(sec, {"id": "work"}, now, view.labels_for("de"))
    assert "Kontingent" in page["stale"] and sec["stale"]["until"] in page["stale"]


def test_a_failure_older_than_twelve_hours_is_an_error_again(tmp_path):
    root = bridge(tmp_path)
    now = dt.datetime.now()
    bf.collect(root, profile_with_cache(), bf.Context(root, now=now - dt.timedelta(hours=13), run=FakeRun(answers())))
    sec = bf.collect(root, profile_with_cache(), bf.Context(root, now=now, run=limited_run()))["sections"][0]
    assert sec["status"] == "error"


def test_the_board_view_and_the_stale_note_reach_the_page():
    model = sys.modules.get("bridge_cockpit.model")
    if model is None:
        sys.path.insert(0, str(ROOT / "scripts" / "lib"))
        from bridge_cockpit import model   # noqa: E402
    pages = model.parse_pages({"pages": [{"id": "github", "title": "GitHub", "sections": [
        {"id": "work", "kind": "tracker", "title": "GitHub", "status": "ok", "items": [], "view": "board",
         "stale": "GitHub limit reached"}]}]})
    sec = pages[0]["sections"][0]
    assert sec["view"] == "board" and sec["stale"] == "GitHub limit reached"


# ---------------------------------------------------------------- the person's boards, the figures

def two_boards(root):
    (root / "ecosystem.yaml").write_text(yaml.safe_dump({"github_projects": [
        {"org": "example-org", "number": 3, "name": "Tool board"}, {"org": "example-org", "number": 4, "name": "Site board"}]}),
        encoding="utf-8")


def test_a_board_switched_off_is_not_asked_and_one_on_all_shows_every_card(tmp_path):
    root = bridge(tmp_path)
    two_boards(root)
    gw = bf._providers().get("github-work")
    gw.save_board_mode(root, "site-board", "off")
    gw.save_board_mode(root, "tool", "all")          # tool.yaml names board 3: its slug is the file's
    rows, run = collect(root)
    listed = [c for c in run.calls if c[:3] == ["gh", "project", "item-list"]]
    assert [c[3] for c in listed] == ["3"]                          # board 4 is off: never asked
    assert "example-org/tool#50" in rows                            # all: someone else's card too
    sec = bf.collect(root, {"id": "p", "sections": [dict(SECTION)]}, bf.Context(root, now=NOW, run=FakeRun(answers())))
    summary = {b["slug"]: b for b in sec["sections"][0]["summary"]}
    assert summary["tool"]["mode"] == "all" and summary["site-board"] == {**summary["site-board"], "mode": "off", "open": None}


def test_a_board_left_out_of_the_query_starts_switched_off(tmp_path):
    root = bridge(tmp_path)
    two_boards(root)
    rows, run = collect(root, dict(SECTION, query={"owners": ["example-org"], "boards": ["tool"]}))
    assert [c[3] for c in run.calls if c[:3] == ["gh", "project", "item-list"]] == ["3"]


def test_a_bad_switch_is_refused_and_a_broken_file_is_no_choice(tmp_path):
    root = bridge(tmp_path)
    gw = bf._providers().get("github-work")
    import pytest
    for slug, mode in (("../x", "all"), ("tool", "everything")):
        with pytest.raises(ValueError):
            gw.save_board_mode(root, slug, mode)
    (root / gw.BOARDS_FILE).parent.mkdir(parents=True, exist_ok=True)
    (root / gw.BOARDS_FILE).write_text("{not json")
    assert gw.board_modes(root) == {}


def test_the_figures_count_what_the_rows_are_and_what_you_finished(tmp_path):
    def done(argv):
        return json.dumps([{"number": n} for n in range(3 if "--closed" in argv else 2)])
    run = FakeRun({**answers(), ("gh", "search", "issues", "--assignee", "@me", "--closed"): done,
                   ("gh", "search", "prs", "--author", "@me", "--merged"): done})
    run.answers = dict(sorted(run.answers.items(), key=lambda kv: -len(kv[0])))   # the longer prefix first
    root = bridge(tmp_path)
    c = bf.Context(root, now=NOW, run=run)
    result = bf.collect(root, {"id": "p", "sections": [dict(SECTION)]}, c)
    sec = result["sections"][0]
    assert sec["metrics"] == {"days": 7, "closed": 3, "landed": 2}
    view = bf._view()
    page = view._page_section(sec, {"id": "work"}, NOW, view.labels_for("en"))
    figures = {m["id"]: m for m in page["metrics"]}
    assert figures["open"]["n"] == len(sec["items"]) and figures["ask_review"]["n"] == 1
    assert figures["closed"] == {"id": "closed", "n": 3, "days": 7} and figures["landed"]["n"] == 2
    assert figures["blocked"]["n"] == 1                               # site#7 carries the label blocked
    row = next(r for r in page["items"] if r["row_id"] == "example-org/tool#40")
    assert "ask_review" in row["flags"]
    assert page["boards"][0]["name"] == "Tool board" and page["boards"][0]["mode"] == "mine"


def test_a_quick_pass_shows_what_the_slow_sources_last_said_at_once(tmp_path):
    root = bridge(tmp_path)
    now = dt.datetime.now()
    bf.collect(root, profile_with_cache(), bf.Context(root, now=now - dt.timedelta(minutes=20), run=FakeRun(answers())))
    quiet = FakeRun({})
    sec = bf.collect(root, profile_with_cache(), bf.Context(root, now=now, run=quiet), skip=("tracker",))["sections"][0]
    assert sec["status"] == "ok" and sec["total"] and sec["stale"]["refreshing"] is True
    assert quiet.calls == []                                          # nothing asked
    view = bf._view()
    assert view._page_section(sec, {"id": "work"}, now, view.labels_for("de"))["stale"] == "letzter Stand, wird gerade aktualisiert"
    fresh_root = bridge(tmp_path / "fresh")                           # nothing kept: left out, as before
    sec = bf.collect(fresh_root, profile_with_cache(), bf.Context(fresh_root, now=now, run=quiet), skip=("tracker",))["sections"][0]
    assert sec["status"] == "skipped"


# ---------------------------------------------------------------- the detail of one row

ISSUE_NODE = {"__typename": "Issue", "number": 7, "title": "Write the onboarding page", "url": "https://github.com/o/r/issues/7",
              "state": "OPEN", "body": "## Goal\n\nOne page.", "createdAt": "2026-10-01T08:00:00Z", "updatedAt": "2026-10-03T08:00:00Z",
              "author": {"login": "octo"}, "assignees": {"nodes": [{"login": "octo"}]},
              "labels": {"nodes": [{"name": "docs", "color": "0e8a16"}]}, "milestone": None,
              "comments": {"totalCount": 9, "nodes": [{"author": {"login": "hubot"}, "body": "x" * 5000, "createdAt": "2026-10-02T08:00:00Z"}]},
              "projectItems": {"nodes": [{"project": {"title": "Site board", "number": 4}, "fieldValueByName": {"name": "Todo"}}]},
              "closedByPullRequestsReferences": {"nodes": [{"number": 8, "title": "Add page", "url": "u", "state": "OPEN", "isDraft": True}]}}
PR_NODE = {"__typename": "PullRequest", "number": 8, "title": "Add page", "state": "OPEN", "isDraft": False,
           "headRefName": "docs/page", "baseRefName": "main", "additions": 10, "deletions": 2, "changedFiles": 1,
           "reviewDecision": "CHANGES_REQUESTED", "reviewRequests": {"nodes": [{"requestedReviewer": {"login": "hubot"}}]},
           "latestReviews": {"nodes": [{"author": {"login": "hubot"}, "state": "CHANGES_REQUESTED"}]},
           "commits": {"nodes": [{"commit": {"statusCheckRollup": {"state": "FAILURE", "contexts": {"totalCount": 3, "nodes": [
               {"name": "tests", "conclusion": "FAILURE", "status": "COMPLETED"}, {"name": "lint", "conclusion": "SUCCESS"},
               {"name": "e2e", "status": "IN_PROGRESS"}]}}}}]},
           "closingIssuesReferences": {"nodes": [{"number": 7, "title": "Write the onboarding page", "url": "u", "state": "OPEN"}]}}


def test_an_opened_issue_says_what_it_is_who_is_on_it_and_where_it_stands():
    d = bf.detail_of(ISSUE_NODE, "o/r#7")
    assert d["type"] == "issue" and d["state"] == "open" and d["assignees"] == ["octo"]
    assert d["boards"] == [{"title": "Site board", "number": 4, "status": "Todo"}]
    assert d["prs"][0]["draft"] is True and d["comments"]["total"] == 9
    assert len(d["comments"]["items"][0]["body"]) == bf.COMMENT_MAX


def test_an_opened_pull_request_names_its_review_and_its_red_checks():
    d = bf.detail_of(PR_NODE, "o/r#8")
    assert d["type"] == "pr" and d["pr"]["review"] == "changes_requested" and d["pr"]["requested"] == ["hubot"]
    assert d["pr"]["checks"] == {"state": "failure", "total": 3, "failing": ["tests"], "running": ["e2e"]}
    assert d["closes"][0]["number"] == 7


def test_a_detail_is_kept_ten_minutes_and_shown_old_when_github_is_blocked(tmp_path):
    root = bridge(tmp_path)
    answer = json.dumps({"data": {"repository": {"issueOrPullRequest": ISSUE_NODE}}})
    run = FakeRun({("gh", "api", "graphql"): answer})
    now = dt.datetime.now()
    code, d = bf.github_detail(root, "o/r#7", ctx=bf.Context(root, now=now, run=run))
    assert code == 0 and d["title"] == "Write the onboarding page" and len(run.calls) == 1
    code, d = bf.github_detail(root, "o/r#7", ctx=bf.Context(root, now=now + dt.timedelta(minutes=5), run=run))
    assert len(run.calls) == 1                                        # kept
    later = bf.Context(root, now=now + dt.timedelta(minutes=30), run=limited_run())
    code, d = bf.github_detail(root, "o/r#7", ctx=later)
    assert code == 0 and "rate limit" in d["stale"]                  # the last kept detail, said to be old
    assert bf.github_detail(root, "not a ref")[0] == 2


def test_someone_elses_card_offers_a_reminder_drafted_never_sent(tmp_path):
    section = dict(SECTION, query={"owners": ["example-org"], "cards": "all"})
    rows, _ = collect(bridge(tmp_path), section)
    other = rows["example-org/tool#50"]
    assert "remind" in ids(other) and "remind" not in ids(rows["example-org/tool#12"])
    words = bf._view().labels_for("de")
    text = bf.tracker_prompt({"id": "remind", "prompt": None}, other, words)
    assert "@hubot" in text and "Poste und sende nichts" in text
    view = bf._view()
    assert view._page_row("tracker", other, {"id": "work"}, NOW, view.labels_for("de"))["who"] == "hubot"
