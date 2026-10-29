# SPDX-License-Identifier: MIT
"""Contract for scripts/briefing.py: a briefing is a profile file the Bridge executes.

Every person describes the briefing they want in workflow/briefings/<id>.yaml:
which sections, in which order, which tracker with which query, which rows
become inbox items. The script collects deterministically (a failing section is
an error line, never an abort) and the agent only advises on and renders the
result. Without any profile a built-in one keeps today's behaviour.

Trackers are tested against recorded CLI and HTTP answers under
scripts/tests/fixtures/briefing/<provider>/, never against a live service.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "scripts" / "tests" / "fixtures" / "briefing"
sys.dont_write_bytecode = True


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


bf = _load("briefing", ROOT / "scripts" / "briefing.py")
inbox = sys.modules.get("inbox") or _load("inbox", ROOT / "scripts" / "inbox.py")

NOW = dt.datetime(2026, 10, 4, 8, 0)


class FakeRun:
    """Answers argv by prefix from recorded output; records every call."""

    def __init__(self, answers: dict | None = None):
        self.answers = answers or {}
        self.calls: list = []

    def __call__(self, argv, timeout=30, cwd=None):
        self.calls.append(list(argv))
        for prefix, answer in self.answers.items():
            if tuple(argv[: len(prefix)]) == prefix:
                if isinstance(answer, Exception):
                    raise answer
                return answer(argv) if callable(answer) else answer
        raise bf.SourceError(f"no recorded answer for {argv[:4]}")


def bridge(tmp_path: Path, config: dict | None = None, profiles: dict | None = None) -> Path:
    root = tmp_path / "bridge"
    (root / "work" / "inbox").mkdir(parents=True)
    (root / "work" / "tasks").mkdir(parents=True)
    (root / "bridge-config.yaml").write_text(yaml.safe_dump(config or {}), encoding="utf-8")
    for pid, data in (profiles or {}).items():
        path = root / "workflow" / "briefings" / f"{pid}.yaml"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(yaml.safe_dump({"schema_version": 1, "scope": "user", "id": pid, **data}),
                        encoding="utf-8")
    return root


def task(root: Path, slug: str, **fm) -> None:
    d = root / "work" / "tasks" / slug
    d.mkdir(parents=True)
    fm = {"slug": slug, "status": "doing", "last_updated": "2026-10-03", **fm}
    (d / "STATUS.md").write_text(f"---\n{yaml.safe_dump(fm)}---\n\n# {slug}\n", encoding="utf-8")


def ctx(root: Path, run=None, **kw):
    return bf.Context(root, now=NOW, run=run or FakeRun(), **kw)


SECTIONS = [{"kind": "tasks", "status": ["doing"]}]


# ---------------------------------------------------------------- discovery

def test_list_finds_profiles_and_skips_reserved_files(tmp_path):
    root = bridge(tmp_path, profiles={"morning": {"sections": SECTIONS, "default": True},
                                      "customer-x": {"sections": SECTIONS, "title": "Customer X"}})
    (root / "workflow" / "briefings" / "_template.yaml").write_text("id: nope\n", encoding="utf-8")
    ids = [p["id"] for p in bf.load_profiles(root)]
    assert ids == ["customer-x", "morning"]


def test_select_prefers_default_flag_then_config_then_single(tmp_path):
    root = bridge(tmp_path, profiles={"a": {"sections": SECTIONS}, "b": {"sections": SECTIONS, "default": True}})
    assert bf.select(root, {})["id"] == "b"
    assert bf.select(root, {"briefing": {"default": "a"}})["id"] == "a"
    assert bf.select(root, {}, "a")["id"] == "a"
    one = bridge(tmp_path / "one", profiles={"only": {"sections": SECTIONS}})
    assert bf.select(one, {})["id"] == "only"


def test_select_without_a_default_among_several_names_the_choices(tmp_path):
    root = bridge(tmp_path, profiles={"a": {"sections": SECTIONS}, "b": {"sections": SECTIONS}})
    with pytest.raises(bf.Ambiguous) as exc:
        bf.select(root, {})
    assert exc.value.ids == ["a", "b"]
    with pytest.raises(bf.UnknownProfile):
        bf.select(root, {}, "c")


def test_without_profiles_the_builtin_keeps_todays_briefing(tmp_path):
    root = bridge(tmp_path, config={"integrations": {"github": {"enabled": True}}})
    profile = bf.select(root, {"integrations": {"github": {"enabled": True}}})
    assert profile["id"] == "builtin"
    kinds = [s["kind"] for s in profile["sections"]]
    assert kinds[:3] == ["inbox", "advise", "tasks"]
    assert "activity" in kinds and "calendar" in kinds
    assert any(s.get("provider") == "github-board" for s in profile["sections"])
    bare = bf.builtin_profile({})
    assert not any(s["kind"] == "tracker" for s in bare["sections"])
    # what runs on and what comes next: collected for the dashboard's work page, never counted in the briefing
    extra = {s["id"]: s for s in bare["sections"] if s.get("id") in ("inbox-runs", "tasks-next")}
    assert extra["inbox-runs"]["deferred"] == "runs" and extra["inbox-runs"]["bucket"] == "none"
    assert extra["tasks-next"]["status"] == ["backlog"] and extra["tasks-next"]["bucket"] == "none"
    assert bf.profile_problems({k: v for k, v in bare.items() if k != "_path"}, "builtin") == []
    german = {s.get("id") or s["kind"]: s.get("title") for s in bf.builtin_profile({"language": {"conversation": "de"}})["sections"]}
    assert german["inbox"] == "Posteingang" and german["inbox-runs"] == "Läuft" and german["tasks-next"] == "Als Nächstes"


def test_offer_matches_the_profiles_vocabulary(tmp_path):
    root = bridge(tmp_path, profiles={
        "morning": {"sections": SECTIONS, "offer_on": ["good morning"]},
        "acme": {"sections": SECTIONS, "offer_on": ["acme", "customer review"]}})
    profiles = bf.load_profiles(root)
    assert bf.offer(profiles, "Good morning, what is up?") == ["morning"]
    assert bf.offer(profiles, "prep the ACME call") == ["acme"]
    assert bf.offer(profiles, "lunch") == []


# ---------------------------------------------------------------- validation

def test_validate_names_every_broken_profile(tmp_path):
    root = bridge(tmp_path, profiles={
        "good": {"sections": SECTIONS, "default": True},
        "also-default": {"sections": SECTIONS, "default": True},
        "wrongname": {"sections": SECTIONS},
        "bad-kind": {"sections": [{"kind": "weather"}]},
        "no-provider": {"sections": [{"kind": "tracker"}]},
        "odd-provider": {"sections": [{"kind": "tracker", "provider": "trello"}]},
        "bad-rule": {"sections": [{"kind": "tasks", "to_inbox": [{"urgency": "now"}]}]},
        "dup-ids": {"sections": [{"kind": "tasks"}, {"kind": "tasks"}]},
        "stray-key": {"sections": [{"kind": "tasks", "token": "abc"}]},
        "inline-secret": {"sections": [{"kind": "tracker", "provider": "jira",
                                        "query": {"jql": "x", "api_token": "s3cr3t"}}]},
    })
    path = root / "workflow" / "briefings" / "wrongname.yaml"
    data = yaml.safe_load(path.read_text())
    data["id"] = "other"
    path.write_text(yaml.safe_dump(data))
    problems = "\n".join(bf.validate(root))
    for pid in ("also-default", "wrongname", "bad-kind", "no-provider", "odd-provider", "bad-rule",
                "dup-ids", "stray-key", "inline-secret"):
        assert pid in problems, pid
    assert "good.yaml" not in problems


def test_validate_accepts_the_shipped_template_and_examples():
    template = ROOT / "workflow" / "briefings" / "_template.yaml"
    data = yaml.safe_load(template.read_text(encoding="utf-8"))
    assert bf.profile_problems(data, data["id"]) == []
    examples = sorted(ROOT.glob("examples/*/workflow/briefings/*.yaml"))
    assert examples, "ship at least one worked example profile"
    for path in examples:
        assert bf.profile_problems(yaml.safe_load(path.read_text(encoding="utf-8")), path.stem) == [], path


def test_template_satisfies_the_json_schema():
    jsonschema = pytest.importorskip("jsonschema")
    schema = yaml.safe_load((ROOT / "workflow" / "briefings" / "_schema.yaml").read_text(encoding="utf-8"))
    data = yaml.safe_load((ROOT / "workflow" / "briefings" / "_template.yaml").read_text(encoding="utf-8"))
    jsonschema.validate(data, schema)


# ---------------------------------------------------------------- collecting

def test_tasks_section_filters_by_status_and_context(tmp_path):
    root = bridge(tmp_path)
    task(root, "alpha", context="acme")
    task(root, "beta", status="review", context="other")
    task(root, "gamma", status="backlog")
    profile = {"id": "p", "sections": [{"kind": "tasks", "status": ["doing", "review"]},
                                       {"kind": "tasks", "id": "acme", "contexts": ["acme"]}]}
    result = bf.collect(root, profile, ctx(root))
    first, second = result["sections"]
    assert [i["id"] for i in first["items"]] == ["alpha", "beta"]
    assert first["status"] == "ok"
    assert [i["id"] for i in second["items"]] == ["alpha"]


def test_a_failing_section_is_an_error_line_not_an_abort(tmp_path):
    root = bridge(tmp_path)
    task(root, "alpha")
    run = FakeRun({("gh",): bf.SourceError("gh: not logged in")})
    profile = {"id": "p", "sections": [
        {"kind": "tracker", "provider": "github", "query": {"assignee": "@me"}},
        {"kind": "tasks"}]}
    result = bf.collect(root, profile, ctx(root, run))
    gh, tasks = result["sections"]
    assert gh["status"] == "error" and "not logged in" in gh["reason"]
    assert tasks["status"] == "ok" and tasks["items"]


def test_an_unexpected_exception_in_a_section_is_contained(tmp_path, monkeypatch):
    root = bridge(tmp_path)
    monkeypatch.setitem(bf.KINDS, "tasks", lambda section, c: 1 / 0)
    result = bf.collect(root, {"id": "p", "sections": [{"kind": "tasks"}]}, ctx(root))
    assert result["sections"][0]["status"] == "error"
    assert "ZeroDivisionError" in result["sections"][0]["reason"]


def gh_answers():
    issues = (FIX / "github" / "search-issues.json").read_text()
    prs = (FIX / "github" / "search-prs.json").read_text()
    review = (FIX / "github" / "review-requested.json").read_text()
    return {("gh", "api", "user"): '{"login": "octo"}',
            ("gh", "search", "issues"): issues,
            ("gh", "search", "prs"): lambda argv: review if "--review-requested" in argv else prs}


def test_github_provider_normalizes_issues_prs_and_review_requests(tmp_path):
    root = bridge(tmp_path)
    run = FakeRun(gh_answers())
    section = {"kind": "tracker", "provider": "github",
               "query": {"assignee": "@me", "owners": ["example-org"], "kinds": ["issues", "prs"],
                         "review_requested": True}}
    result = bf.collect(root, {"id": "p", "sections": [section]}, ctx(root, run))
    items = {i["id"]: i for i in result["sections"][0]["items"]}
    assert set(items) == {"example-org/tool#12", "example-org/site#7", "example-org/tool#31",
                          "example-org/tool#33", "example-org/tool#40"}
    assert items["example-org/tool#12"]["state"] == "ready"
    assert items["example-org/site#7"]["state"] == "blocked"          # a `blocked` label
    assert items["example-org/tool#31"]["state"] == "review"
    assert items["example-org/tool#33"]["state"] == "in_progress"     # a draft PR
    assert items["example-org/tool#40"]["assigned_to_me"] is True     # asked to review it
    assert items["example-org/tool#40"]["category"] == "qa"
    assert all(i["tracker"] == "github" for i in items.values())
    search = [c for c in run.calls if c[:3] == ["gh", "search", "issues"]][0]
    assert "--owner" in search and "example-org" in search and "--assignee" in search
    # newest first
    assert result["sections"][0]["items"][0]["changed_at"] >= result["sections"][0]["items"][-1]["changed_at"]


def test_github_board_provider_reuses_tracker_sync_and_the_registry(tmp_path):
    root = bridge(tmp_path, config={"integrations": {"github": {"assignee_me": "octo"}}})
    (root / "ecosystem.yaml").write_text(yaml.safe_dump({"github_projects": [
        {"org": "example-org", "number": 3, "name": "Tool board"}]}), encoding="utf-8")
    run = FakeRun({("gh", "project", "item-list"): (FIX / "github-board" / "item-list.json").read_text()})
    section = {"kind": "tracker", "provider": "github-board", "query": {"assigned_to_me": True}}
    result = bf.collect(root, {"id": "p", "sections": [section]}, ctx(root, run))
    sec = result["sections"][0]
    assert sec["status"] == "ok", sec.get("reason")
    assert [i["id"] for i in sec["items"]] == ["example-org/tool#5"]     # done + others' cards filtered
    assert sec["items"][0]["state"] == "in_progress" and sec["items"][0]["project"] == "Tool board"
    every = dict(section, query={"include_done": True})
    states = {i["state"] for i in bf.collect(root, {"id": "p", "sections": [every]},
                                             ctx(root, run))["sections"][0]["items"]}
    assert states == {"in_progress", "done", "blocked"}


def test_github_board_asks_github_for_open_cards_before_the_limit(tmp_path):
    """gh lists a board's oldest cards first: 393 cards behind a limit of 200 showed none of the
    10 open ones (live 2026-10-17). The filter goes to GitHub, so the limit counts open cards."""
    root = bridge(tmp_path, config={"integrations": {"github": {"assignee_me": "octo"}}})
    (root / "ecosystem.yaml").write_text(yaml.safe_dump({"github_projects": [
        {"org": "example-org", "number": 3, "name": "Tool board"}]}), encoding="utf-8")
    run = FakeRun({("gh", "project", "item-list"): (FIX / "github-board" / "item-list.json").read_text()})
    section = {"kind": "tracker", "provider": "github-board", "query": {}}
    def listed(calls):
        return [c for c in calls if c[:3] == ["gh", "project", "item-list"]][0]

    def lean(calls):
        return [c for c in calls if c[:3] == ["gh", "api", "graphql"] and "projectV2(number" in c[4]][0]

    bf.collect(root, {"id": "p", "sections": [section]}, ctx(root, run))
    assert "q=is:open" in lean(run.calls) and listed(run.calls)[-2:] == ["--query", "is:open"]   # lean, then the old way
    run.calls.clear()
    own = dict(section, query={"filter": "assignee:@me -status:Parked"})
    bf.collect(root, {"id": "p", "sections": [own]}, ctx(root, run))
    assert "q=assignee:@me -status:Parked" in lean(run.calls)
    for query in ({"include_done": True}, {"filter": ""}, {"states": ["done"]}):
        run.calls.clear()
        bf.collect(root, {"id": "p", "sections": [dict(section, query=query)]}, ctx(root, run))
        assert "q=" in lean(run.calls) and "--query" not in listed(run.calls), query


def lean_page(cards, more=None):
    return json.dumps({"data": {"repositoryOwner": {"projectV2": {"items": {
        "pageInfo": {"hasNextPage": more is not None, "endCursor": more}, "nodes": cards}}}}})


def lean_card(n, status, people=("octo",), kind="Issue", repo="example-org/tool"):
    return {"id": f"PVTI_{n}", "fieldValueByName": {"name": status} if status else None,
            "content": {"__typename": kind, "number": n, "title": f"Card {n}", "updatedAt": "2026-10-03T08:00:00Z",
                        "url": f"https://github.com/{repo}/issues/{n}", "repository": {"nameWithOwner": repo},
                        "assignees": {"nodes": [{"login": p} for p in people]}, "labels": {"nodes": [{"name": "bug"}]}}}


def test_github_board_asks_only_what_a_row_needs_page_by_page(tmp_path):
    """gh project item-list cost about 100 GraphQL points a board whatever its size; the lean query cost 2
    (live 2026-10-18, eight boards 721 points a pass against an hourly budget of 5000)."""
    root = bridge(tmp_path, config={"integrations": {"github": {"assignee_me": "octo"}}})
    (root / "ecosystem.yaml").write_text(yaml.safe_dump({"github_projects": [
        {"org": "example-org", "number": 3, "name": "Tool board"}]}), encoding="utf-8")
    pages = {None: lean_page([lean_card(1, "In Progress"), lean_card(2, "Todo", people=("hubot",))], more="c1"),
             "c1": lean_page([lean_card(3, "In Review"), {"id": "PVTI_d", "fieldValueByName": None,
                                                          "content": {"__typename": "DraftIssue", "title": "Idea"}}])}

    def graphql(argv):
        after = next((a.split("=", 1)[1] for a in argv if a.startswith("after=")), None)
        return pages[after]
    run = FakeRun({("gh", "api", "graphql"): graphql})
    section = {"kind": "tracker", "provider": "github-board", "summary": True, "query": {"assigned_to_me": True}}
    sec = bf.collect(root, {"id": "p", "sections": [section]}, ctx(root, run))["sections"][0]
    assert sec["status"] == "ok", sec.get("reason")
    assert [i["id"] for i in sec["items"]] == ["example-org/tool#1", "example-org/tool#3"]
    assert sec["items"][0]["labels"] == ["bug"] and sec["items"][0]["changed_at"] == "2026-10-03T08:00:00Z"
    assert sec["summary"][0]["open"] == 4                       # the draft counts as open work
    assert not [c for c in run.calls if c[:3] == ["gh", "project", "item-list"]]
    assert len([c for c in run.calls if c[:3] == ["gh", "api", "graphql"]]) == 2    # two pages, no date call


def test_github_board_a_draft_card_names_who_made_it(tmp_path):
    """A draft card has no author, GitHub names its creator: the row says who opened it like any other (round 6d)."""
    root = bridge(tmp_path, config={"integrations": {"github": {"assignee_me": "octo"}}})
    (root / "ecosystem.yaml").write_text(yaml.safe_dump({"github_projects": [
        {"org": "example-org", "number": 3, "name": "Tool board"}]}), encoding="utf-8")
    issue = lean_card(1, "Todo")
    issue["content"]["author"] = {"login": "hubot"}
    draft = {"id": "PVTI_d", "fieldValueByName": {"name": "Todo"},
             "content": {"__typename": "DraftIssue", "title": "Idea", "creator": {"login": "octo"},
                         "assignees": {"nodes": []}}}
    asked = []

    def graphql(argv):
        asked.append(next(a for a in argv if a.startswith("query=")))
        return lean_page([issue, draft])
    run = FakeRun({("gh", "api", "graphql"): graphql})
    section = {"kind": "tracker", "provider": "github-board", "query": {}}
    sec = bf.collect(root, {"id": "p", "sections": [section]}, ctx(root, run))["sections"][0]
    assert sec["status"] == "ok", sec.get("reason")
    assert "creator { login }" in asked[0]
    by = {i.get("type"): i.get("author") for i in sec["items"]}
    assert by == {"issue": "hubot", "draft": "octo"}


def _registry(root, board=None, state_map=None):
    """A registry for the Tool board (example-org #3), with a `board:` block when given."""
    path = root / "workflow" / "projects" / "tool.yaml"
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {"schema_version": 1, "scope": "user", "identity": {"slug": "tool", "display_name": "Tool board"},
            "project": {"tracker": "github", "org": "example-org", "number": 3},
            "fields": {"Status": {"type": "single-select"}}, "state_map": state_map or {}}
    if board:
        data["board"] = board
    path.write_text(yaml.safe_dump(data), encoding="utf-8")
    (root / "ecosystem.yaml").write_text(yaml.safe_dump({"github_projects": [
        {"org": "example-org", "number": 3, "name": "Tool board"}]}), encoding="utf-8")


def _field_card(n, values, people=("octo",)):
    """A lean card as GitHub answers it: the status under `fieldValueByName`, the priority under its alias."""
    card = lean_card(n, values.get("status"), people=people)
    if "priority" in values:
        card["priority"] = {"name": values["priority"]} if values["priority"] else None
    return card


def _arg(argv, name):
    return next((a.split("=", 1)[1] for a in argv if a.startswith(f"{name}=")), None)


def test_github_board_reads_the_lifecycle_field_the_registry_names(tmp_path):
    """A board whose lifecycle lives in a custom column (`board.status_field: Workflow`): the built-in Status
    still says Todo on every card, so the rows and the counts read the Workflow value instead."""
    root = bridge(tmp_path, config={"integrations": {"github": {"assignee_me": "octo"}}})
    _registry(root, board={"status_field": "Workflow"},
              state_map={"Ready": "ready", "Building": "in_progress", "Todo": "new"})

    def graphql(argv):
        workflow = _arg(argv, "status") == "Workflow"
        return lean_page([_field_card(1, {"status": "Ready" if workflow else "Todo"}),
                          _field_card(2, {"status": "Building" if workflow else "Todo"})])
    run = FakeRun({("gh", "api", "graphql"): graphql})
    section = {"kind": "tracker", "provider": "github-board", "summary": True, "query": {}}
    sec = bf.collect(root, {"id": "p", "sections": [section]}, ctx(root, run))["sections"][0]
    assert sec["status"] == "ok", sec.get("reason")
    by = {i["id"]: i for i in sec["items"]}
    assert by["example-org/tool#1"]["raw_state"] == "Ready" and by["example-org/tool#1"]["state"] == "ready"
    assert by["example-org/tool#2"]["state"] == "in_progress"
    counts = sec["summary"][0]["counts"]
    assert counts["ready"] == 1 and counts["in_progress"] == 1 and counts["new"] == 0
    assert not [c for c in run.calls if c[:3] == ["gh", "project", "item-list"]]     # still the lean query


def test_github_board_without_a_status_field_asks_status_and_no_priority(tmp_path):
    root = bridge(tmp_path, config={"integrations": {"github": {"assignee_me": "octo"}}})
    _registry(root)
    run = FakeRun({("gh", "api", "graphql"): lambda argv: lean_page([lean_card(1, "In Progress")])})
    section = {"kind": "tracker", "provider": "github-board", "query": {}}
    sec = bf.collect(root, {"id": "p", "sections": [section]}, ctx(root, run))["sections"][0]
    assert sec["status"] == "ok", sec.get("reason")
    lean = [c for c in run.calls if c[:3] == ["gh", "api", "graphql"] and "projectV2(number" in c[4]][0]
    assert _arg(lean, "status") == "Status" and _arg(lean, "priority") is None
    assert "$priority" not in lean[4]
    assert sec["items"][0]["state"] == "in_progress" and sec["items"][0]["priority"] is None


def test_github_board_carries_the_priority_the_registry_names(tmp_path):
    root = bridge(tmp_path, config={"integrations": {"github": {"assignee_me": "octo"}}})
    _registry(root, board={"priority_field": "Priority"})

    def graphql(argv):
        assert _arg(argv, "priority") == "Priority" and "priority: fieldValueByName(name: $priority)" in argv[4]
        return lean_page([_field_card(1, {"status": "In Progress", "priority": "P2"}),
                          _field_card(2, {"status": "Todo", "priority": None})])
    run = FakeRun({("gh", "api", "graphql"): graphql})
    section = {"kind": "tracker", "provider": "github-board", "query": {}}
    sec = bf.collect(root, {"id": "p", "sections": [section]}, ctx(root, run))["sections"][0]
    assert sec["status"] == "ok", sec.get("reason")
    by = {i["id"]: i for i in sec["items"]}
    assert by["example-org/tool#1"]["priority"] == "P2" and by["example-org/tool#2"]["priority"] is None


def test_github_board_listed_the_old_way_reads_the_same_fields(tmp_path):
    """When the lean query cannot answer, gh item-list keys each field by its lower-cased name."""
    root = bridge(tmp_path, config={"integrations": {"github": {"assignee_me": "octo"}}})
    _registry(root, board={"status_field": "Work Flow", "priority_field": "Priority"},
              state_map={"Ready": "ready"})
    listing = json.dumps({"items": [{"status": "Blocked", "workflow": "Ready", "priority": "P1", "assignees": ["octo"],
                                     "labels": [], "title": "Card 7",
                                     "content": {"number": 7, "title": "Card 7", "type": "Issue",
                                                 "repository": "example-org/tool",
                                                 "url": "https://github.com/example-org/tool/issues/7"}}]})
    run = FakeRun({("gh", "api", "graphql"): '{"data": null}', ("gh", "project", "item-list"): listing})
    section = {"kind": "tracker", "provider": "github-board", "query": {}}
    sec = bf.collect(root, {"id": "p", "sections": [section]}, ctx(root, run))["sections"][0]
    assert sec["status"] == "ok", sec.get("reason")
    assert sec["items"][0]["state"] == "ready" and sec["items"][0]["priority"] == "P1"


def test_github_board_lists_without_a_filter_when_gh_does_not_know_it(tmp_path):
    root = bridge(tmp_path, config={"integrations": {"github": {"assignee_me": "octo"}}})
    (root / "ecosystem.yaml").write_text(yaml.safe_dump({"github_projects": [
        {"org": "example-org", "number": 3, "name": "Tool board"}]}), encoding="utf-8")
    listing = (FIX / "github-board" / "item-list.json").read_text()

    def answer(argv):
        if "--query" in argv:
            raise bf.SourceError("unknown flag: --query")
        return listing
    run = FakeRun({("gh", "project", "item-list"): answer})
    section = {"kind": "tracker", "provider": "github-board", "query": {"assigned_to_me": True}}
    sec = bf.collect(root, {"id": "p", "sections": [section]}, ctx(root, run))["sections"][0]
    assert sec["status"] == "ok", sec.get("reason")
    assert sec["items"][0]["board"] == {"slug": "tool-board", "name": "Tool board", "number": 3, "org": "example-org"}


def _three_boards(root):
    (root / "ecosystem.yaml").write_text(yaml.safe_dump({"github_projects": [
        {"org": "example-org", "number": n, "name": f"Board {n}"} for n in (3, 4, 5)]}), encoding="utf-8")


def _cards_of(argv):
    """One card per board, numbered after the board, so the order of the rows shows."""
    n = int(argv[3])
    return json.dumps({"items": [{"status": "In Progress", "assignees": ["octo"], "labels": [], "title": f"Card {n}",
                                  "content": {"number": n, "title": f"Card {n}", "type": "Issue",
                                              "repository": "example-org/tool", "updatedAt": "2026-10-04T05:00:00Z",
                                              "url": f"https://github.com/example-org/tool/issues/{n}"}}]})


def test_github_board_loads_the_boards_side_by_side(tmp_path):
    """Eight boards one after another took 64 s live (2026-10-09) against a 30 s section
    limit. Each list call here waits until all three are in flight: one after another,
    the barrier breaks and the section fails."""
    import threading
    root = bridge(tmp_path, config={"integrations": {"github": {"assignee_me": "octo"}}})
    _three_boards(root)
    gate = threading.Barrier(3, timeout=5)

    def listing(argv):
        gate.wait()
        return _cards_of(argv)
    run = FakeRun({("gh", "project", "item-list"): listing})
    section = {"kind": "tracker", "provider": "github-board", "summary": True, "query": {"assigned_to_me": True}}
    sec = bf.collect(root, {"id": "p", "sections": [section]}, ctx(root, run))["sections"][0]
    assert sec["status"] == "ok", sec.get("reason")
    assert sorted(i["id"] for i in sec["items"]) == ["example-org/tool#3", "example-org/tool#4", "example-org/tool#5"]


def test_github_board_asks_at_most_four_boards_at_once(tmp_path):
    """Side by side, but not all at once: eight boards in one burst tripped GitHub's
    secondary rate limit (live 2026-10-09)."""
    import threading
    import time as _time
    root = bridge(tmp_path, config={"integrations": {"github": {"assignee_me": "octo"}}})
    (root / "ecosystem.yaml").write_text(yaml.safe_dump({"github_projects": [
        {"org": "example-org", "number": n, "name": f"Board {n}"} for n in range(3, 11)]}), encoding="utf-8")
    lock, now, most = threading.Lock(), [0], [0]

    def listing(argv):
        with lock:
            now[0] += 1
            most[0] = max(most[0], now[0])
        _time.sleep(0.05)
        with lock:
            now[0] -= 1
        return _cards_of(argv)
    run = FakeRun({("gh", "project", "item-list"): listing})
    section = {"kind": "tracker", "provider": "github-board", "query": {"assigned_to_me": True}}
    sec = bf.collect(root, {"id": "p", "sections": [section]}, ctx(root, run))["sections"][0]
    assert sec["status"] == "ok", sec.get("reason")
    assert 1 < most[0] <= 4


def test_github_board_keeps_the_registry_order_when_boards_answer_out_of_order(tmp_path):
    import time as _time
    root = bridge(tmp_path, config={"integrations": {"github": {"assignee_me": "octo"}}})
    _three_boards(root)

    def listing(argv):
        _time.sleep({"3": 0.3, "4": 0.15, "5": 0.0}[argv[3]])    # the first board answers last
        return _cards_of(argv)
    run = FakeRun({("gh", "project", "item-list"): listing})
    section = {"kind": "tracker", "provider": "github-board", "summary": True, "query": {"assigned_to_me": True}}
    result = bf.collect(root, {"id": "p", "sections": [section]}, ctx(root, run))
    sec = result["sections"][0]
    assert sec["status"] == "ok", sec.get("reason")
    assert [i["project"] for i in sec["items"]] == ["Board 3", "Board 4", "Board 5"]
    assert [b["number"] for b in sec["summary"]] == [3, 4, 5]


def test_github_board_calls_on_other_threads_keep_the_section_time_limit(tmp_path):
    """The deadline lives per thread: a board fetched on a helper thread must still end
    with its section, not start a fresh limit of its own."""
    import time as _time
    root = bridge(tmp_path, config={"integrations": {"github": {"assignee_me": "octo"}}})
    _three_boards(root)
    run = FakeRun({("gh", "project", "item-list"): _cards_of})
    c = ctx(root, run)
    c.deadline = _time.monotonic() - 1            # the section's time is already used up
    gb = bf._providers().get("github-board")
    with pytest.raises(bf.SourceError, match="time limit"):
        gb.collect({"kind": "tracker", "provider": "github-board", "query": {}}, c)
    assert not [call for call in run.calls if call[:3] == ["gh", "project", "item-list"]]


def test_github_board_rows_get_the_date_their_issue_last_changed(tmp_path):
    root = bridge(tmp_path, config={"integrations": {"github": {"assignee_me": "octo"}}})
    (root / "ecosystem.yaml").write_text(yaml.safe_dump({"github_projects": [
        {"org": "example-org", "number": 3, "name": "Tool board"}]}), encoding="utf-8")
    dates = json.dumps({"data": {"i0": {"issueOrPullRequest": {"updatedAt": "2026-10-03T14:00:00Z"}}}})
    # gh 2.x lists cards without any date (live 2026-10-09); the fixture's dates stand for an older gh.
    listing = json.loads((FIX / "github-board" / "item-list.json").read_text())
    for raw in listing["items"]:
        raw.pop("updatedAt", None)
        (raw.get("content") or {}).pop("updatedAt", None)
    run = FakeRun({("gh", "project", "item-list"): json.dumps(listing),
                   ("gh", "api", "graphql"): dates})
    section = {"kind": "tracker", "provider": "github-board", "query": {"assigned_to_me": True}}
    item = bf.collect(root, {"id": "p", "sections": [section]}, ctx(root, run))["sections"][0]["items"][0]
    assert item["changed_at"] == "2026-10-03T14:00:00Z"
    query = next(c for c in run.calls if c[:3] == ["gh", "api", "graphql"] and "issueOrPullRequest" in c[-1])[-1]
    assert 'repository(owner: "example-org", name: "tool")' in query and "issueOrPullRequest(number: 5)" in query


def test_one_unanswerable_card_does_not_take_the_other_dates(tmp_path):
    root = bridge(tmp_path, config={"integrations": {"github": {"assignee_me": "octo"}}})
    (root / "ecosystem.yaml").write_text(yaml.safe_dump({"github_projects": [
        {"org": "example-org", "number": 3, "name": "Tool board"}]}), encoding="utf-8")
    listing = json.loads((FIX / "github-board" / "item-list.json").read_text())
    for raw in listing["items"]:
        raw.pop("updatedAt", None)
        (raw.get("content") or {}).pop("updatedAt", None)
    calls = []

    def graphql(argv):
        calls.append(argv[-1])
        if len(calls) == 1:   # the shared call: one alias GitHub cannot answer fails it all
            raise bf.SourceError("gh: Could not resolve to a Repository")
        return json.dumps({"data": {"i0": {"issueOrPullRequest": {"updatedAt": "2026-10-03T14:00:00Z"}}}})
    run = FakeRun({("gh", "project", "item-list"): json.dumps(listing), ("gh", "api", "graphql"): graphql})
    section = {"kind": "tracker", "provider": "github-board", "query": {"include_done": True}}
    items = bf.collect(root, {"id": "p", "sections": [section]}, ctx(root, run))["sections"][0]["items"]
    assert len(items) > 1 and len(calls) >= 2      # the shared call failed, the halves were asked
    assert any(i.get("changed_at") == "2026-10-03T14:00:00Z" for i in items)


def test_one_unanswerable_card_among_many_leaves_every_other_date(tmp_path):
    """The fallback must reach every row, not the first few: a row that loses its date
    whenever the shared call fails is marked changed on that run and the next."""
    import re as _re
    root = bridge(tmp_path, config={"integrations": {"github": {"assignee_me": "octo"}}})
    (root / "ecosystem.yaml").write_text(yaml.safe_dump({"github_projects": [
        {"org": "example-org", "number": 3, "name": "Tool board"}]}), encoding="utf-8")
    cards = [{"status": "In Progress", "assignees": ["octo"], "labels": [], "title": f"Card {n}",
              "content": {"number": n, "title": f"Card {n}", "type": "Issue", "repository": "example-org/tool",
                          "url": f"https://github.com/example-org/tool/issues/{n}"}} for n in range(1, 61)]
    bad = 47

    def graphql(argv):
        query = argv[-1]
        if f"issueOrPullRequest(number: {bad})" in query:
            raise bf.SourceError("gh: Could not resolve to an issue or pull request")
        aliases = _re.findall(r"(i\d+): repository", query)
        return json.dumps({"data": {a: {"issueOrPullRequest": {"updatedAt": "2026-10-03T14:00:00Z"}}
                                    for a in aliases}})
    run = FakeRun({("gh", "project", "item-list"): json.dumps({"items": cards}), ("gh", "api", "graphql"): graphql})
    section = {"kind": "tracker", "provider": "github-board", "query": {"assigned_to_me": True, "limit": 100}}
    items = bf.collect(root, {"id": "p", "sections": [section]}, ctx(root, run))["sections"][0]["items"]
    assert len(items) == 60
    undated = sorted(i["id"] for i in items if not i.get("changed_at"))
    assert undated == [f"example-org/tool#{bad}"]
    asked = [c for c in run.calls if c[:3] == ["gh", "api", "graphql"]]
    assert len(asked) <= 20       # halves, not one call per card


def test_section_state_map_overrides_the_provider(tmp_path):
    root = bridge(tmp_path)
    run = FakeRun(gh_answers())
    section = {"kind": "tracker", "provider": "github", "query": {"assignee": "@me", "kinds": ["issues"]},
               "state_map": {"open": "in_progress"}}
    items = bf.collect(root, {"id": "p", "sections": [section]}, ctx(root, run))["sections"][0]["items"]
    assert {i["id"]: i["state"] for i in items}["example-org/tool#12"] == "in_progress"


def test_command_section_reads_json_from_any_program(tmp_path):
    root = bridge(tmp_path)
    script = root / "source.py"
    script.write_text("import json; print(json.dumps([{'id': 'X-1', 'title': 'From my tool', 'state': 'ready'}]))")
    bad = root / "bad.py"
    bad.write_text("print('not json')")
    profile = {"id": "p", "sections": [
        {"kind": "command", "id": "mine", "argv": [sys.executable, "source.py"]},
        {"kind": "command", "id": "broken", "argv": [sys.executable, "bad.py"]}]}
    good, broken = bf.collect(root, profile, bf.Context(root, now=NOW))["sections"]
    assert good["items"][0]["title"] == "From my tool" and good["items"][0]["tracker"] == "mine"
    assert broken["status"] == "error"


def test_max_caps_items_but_keeps_the_total(tmp_path):
    root = bridge(tmp_path)
    for s in ("a", "b", "c"):
        task(root, s)
    sec = bf.collect(root, {"id": "p", "sections": [{"kind": "tasks", "max": 2}]}, ctx(root))["sections"][0]
    assert len(sec["items"]) == 2 and sec["total"] == 3
    # a dashboard that pages itself (--max-items) keeps every row: a cut row would vanish from its page
    whole = bf.collect(root, {"id": "p", "_whole": True, "sections": [{"kind": "tasks", "max": 2}]}, ctx(root))["sections"][0]
    assert len(whole["items"]) == 3


def test_inbox_section_lists_open_items(tmp_path):
    root = bridge(tmp_path)
    box = inbox.Inbox(root / "work" / "inbox", actor="t", clock=lambda: NOW)
    a = box.add(source="t", kind="decision", summary="Merge the fix?", urgency="now")
    b = box.add(source="t", kind="finding", summary="Old thing")
    box.close(b)
    sec = bf.collect(root, {"id": "p", "sections": [{"kind": "inbox"}]}, ctx(root))["sections"][0]
    assert [i["id"] for i in sec["items"]] == [a]
    assert sec["items"][0]["urgency"] == "now"


def test_inbox_section_says_whether_an_item_has_an_action_to_run(tmp_path):
    """A yes only does something when the item carries an action; a UI offers a tab otherwise."""
    root = bridge(tmp_path)
    box = inbox.Inbox(root / "work" / "inbox", actor="t", clock=lambda: NOW)
    plain = box.add(source="t", kind="finding", summary="Look at this", gate="your-yes")
    acting = box.add(source="t", kind="decision", summary="Restart it?", gate="your-yes",
                     action={"argv": ["true"]})
    sec = bf.collect(root, {"id": "p", "sections": [{"kind": "inbox"}]}, ctx(root))["sections"][0]
    by = {i["id"]: i for i in sec["items"]}
    assert by[plain]["has_action"] is False and by[acting]["has_action"] is True


def test_inbox_section_can_keep_ideas_apart_and_show_shelved_ones(tmp_path):
    # An idea waits on nobody: the "waiting for you" list leaves it out, a second section lists
    # the ideas, including the ones put on the shelf (deferred) whatever their return date.
    root = bridge(tmp_path)
    box = inbox.Inbox(root / "work" / "inbox", actor="t", clock=lambda: NOW)
    d = box.add(source="t", kind="decision", summary="Merge the fix?")
    i1 = box.add(source="t", kind="idea", summary="Try a model")
    i2 = box.add(source="t", kind="idea", summary="Shelved idea")
    box.event(i2, "defer", until="2027-01-01")
    profile = {"id": "p", "sections": [{"kind": "inbox", "skip_kinds": ["idea"]},
                                       {"kind": "inbox", "id": "ideas", "kinds": ["idea"], "deferred": "all"}]}
    waiting, ideas = bf.collect(root, profile, ctx(root))["sections"]
    assert [i["id"] for i in waiting["items"]] == [d]
    assert sorted(i["id"] for i in ideas["items"]) == sorted([i1, i2])
    assert bf.profile_problems({**profile, "schema_version": 1, "scope": "user"}, "p") == []


def test_an_inbox_section_can_list_what_runs_on(tmp_path):
    # "still running": put off with what it waits on; `deferred: runs` lists exactly those, a plain later stays out
    root = bridge(tmp_path)
    box = inbox.Inbox(root / "work" / "inbox", actor="t", clock=lambda: NOW)
    runs = box.add(source="t", kind="question", summary="Answer from Ada")
    later = box.add(source="t", kind="decision", summary="Later, just later")
    box.event(runs, "defer", until="2027-01-01", on="Ada")
    box.event(later, "defer", until="2027-01-01")
    profile = {"id": "p", "sections": [{"kind": "inbox"}, {"kind": "inbox", "id": "runs", "deferred": "runs"}]}
    waiting, running = bf.collect(root, profile, ctx(root))["sections"]
    assert waiting["items"] == []
    assert [(i["id"], i["waiting_on"], i["until"]) for i in running["items"]] == [(runs, "Ada", "2027-01-01")]
    assert bf.profile_problems({**profile, "schema_version": 1, "scope": "user"}, "p") == []


def test_an_unknown_inbox_kind_is_a_problem_not_an_empty_section():
    profile = {"schema_version": 1, "scope": "user", "id": "p", "sections": [{"kind": "inbox", "kinds": ["ideas"]}]}
    assert any("ideas" in p for p in bf.profile_problems(profile, "p"))


def test_activity_section_reads_recent_log_rows(tmp_path):
    root = bridge(tmp_path)
    (root / "work" / "log.md").write_text(textwrap.dedent("""\
        # Log

        ## Thursday 24.09
        | 2026-09-24 10:00 | 💻 | old | too old |

        ## Saturday 03.10
        | 2026-10-03 09:00 | 💻 | tool | shipped the parser |
        | 2026-10-03 11:00 | 📋 | site | planned the page |
        """), encoding="utf-8")
    sec = bf.collect(root, {"id": "p", "sections": [{"kind": "activity", "days": 7}]}, ctx(root))["sections"][0]
    assert [i["title"] for i in sec["items"]] == ["planned the page", "shipped the parser"]
    assert sec["items"][0]["project"] == "site"


def test_calendar_icalbuddy_and_ics(tmp_path):
    root = bridge(tmp_path)
    run = FakeRun({("icalBuddy",): (FIX / "calendar" / "icalbuddy.txt").read_text(encoding="utf-8")})
    sec = bf.collect(root, {"id": "p", "sections": [{"kind": "calendar", "provider": "icalbuddy", "days": 1}]},
                     ctx(root, run))["sections"][0]
    assert sec["status"] == "ok", sec.get("reason")
    assert [(i["title"], i["start"]) for i in sec["items"]] == [
        ("Standup", "2026-10-04T09:00"), ("Customer review", "2026-10-04T14:00"), ("Holiday", "2026-10-05")]
    call = run.calls[0]
    assert "-nrd" in call and "eventsToday+1" in call
    ics = {"kind": "calendar", "provider": "ics", "path": str(FIX / "calendar" / "sample.ics"), "days": 2}
    items = bf.collect(root, {"id": "p", "sections": [ics]}, ctx(root))["sections"][0]["items"]
    assert [i["title"] for i in items] == ["Planning", "All day"]


def test_calendar_auto_without_icalbuddy_is_skipped_not_an_error(tmp_path, monkeypatch):
    root = bridge(tmp_path)
    monkeypatch.setattr(bf.shutil, "which", lambda name: None)
    sec = bf.collect(root, {"id": "p", "sections": [{"kind": "calendar", "provider": "auto"}]},
                     ctx(root))["sections"][0]
    assert sec["status"] == "skipped"
    # a source missing on this machine is not "left out": it never comes with the full pass (18.10.)
    assert "icalBuddy" in sec["reason"] and "left_out" not in sec


def test_advise_section_sees_the_calendar_wherever_it_stands(tmp_path):
    root = bridge(tmp_path)
    box = inbox.Inbox(root / "work" / "inbox", actor="t", clock=lambda: NOW)
    box.add(source="t", kind="decision", summary="Call the vendor", due="2026-10-04T14:15")
    run = FakeRun({("icalBuddy",): (FIX / "calendar" / "icalbuddy.txt").read_text(encoding="utf-8")})
    profile = {"id": "p", "sections": [{"kind": "advise"},
                                       {"kind": "calendar", "provider": "icalbuddy", "days": 1}]}
    advice = bf.collect(root, profile, ctx(root, run))["sections"][0]
    assert any(i.get("check") == "collision" for i in advice["items"]), advice


def test_workplace_section_uses_the_none_driver_without_config(tmp_path):
    root = bridge(tmp_path)
    task(root, "alpha")
    sec = bf.collect(root, {"id": "p", "sections": [{"kind": "workplace"}]}, ctx(root))["sections"][0]
    assert sec["status"] == "ok", sec.get("reason")
    assert sec["plan"]["workspaces"] and sec["items"][0]["id"] == "alpha"


# ---------------------------------------------------------------- change marks and inbox

def test_rows_are_marked_new_or_changed_against_the_last_run(tmp_path):
    root = bridge(tmp_path)
    task(root, "alpha")
    task(root, "beta")
    profile = {"id": "p", "sections": [{"kind": "tasks", "status": ["doing", "review"]}]}
    first = bf.collect(root, profile, ctx(root))
    assert all(i["new"] for i in first["sections"][0]["items"])
    bf.save_snapshot(root, first)
    (root / "work" / "tasks" / "beta" / "STATUS.md").write_text(
        "---\nslug: beta\nstatus: review\nlast_updated: 2026-10-04\n---\n", encoding="utf-8")
    task(root, "gamma")
    second = bf.collect(root, profile, ctx(root), previous=bf.load_snapshot(root, "p"))
    marks = {i["id"]: (i["new"], i["changed"]) for i in second["sections"][0]["items"]}
    assert marks == {"alpha": (False, False), "beta": (False, True), "gamma": (True, False)}
    assert (root / ".bridge" / "briefings" / "p.last.json").is_file()


def test_to_inbox_files_matching_rows_and_closes_them_when_gone(tmp_path):
    root = bridge(tmp_path)
    run = FakeRun(gh_answers())
    section = {"kind": "tracker", "id": "gh", "provider": "github",
               "query": {"assignee": "@me", "kinds": ["issues"]},
               "to_inbox": [{"when": {"state": "blocked"}, "urgency": "now"}]}
    profile = {"id": "morning", "sections": [section]}
    box = inbox.Inbox(root / "work" / "inbox", actor="t", clock=lambda: NOW)
    filed, closed = bf.file_to_inbox(box, profile, bf.collect(root, profile, ctx(root, run)))
    assert (filed, closed) == (1, 0)
    item = box.open_items()[0]
    assert item.key == "briefing:morning:gh:example-org/site#7" and item.urgency == "now"
    assert "Write the onboarding page" in item.summary

    # a run where the section FAILED must not close it
    broken = FakeRun({("gh",): bf.SourceError("offline")})
    assert bf.file_to_inbox(box, profile, bf.collect(root, profile, ctx(root, broken))) == (0, 0)
    assert len(box.open_items()) == 1

    # the row is gone on a good run: closed
    clean = json.loads((FIX / "github" / "search-issues.json").read_text())[:1]
    run2 = FakeRun({**gh_answers(), ("gh", "search", "issues"): json.dumps(clean)})
    assert bf.file_to_inbox(box, profile, bf.collect(root, profile, ctx(root, run2))) == (0, 1)
    assert box.open_items() == []


def test_to_inbox_rule_matches_lists_and_booleans(tmp_path):
    assert bf.rule_matches({"state": ["review", "blocked"], "assigned_to_me": True},
                           {"state": "review", "assigned_to_me": True})
    assert not bf.rule_matches({"state": "review", "assigned_to_me": True},
                               {"state": "review", "assigned_to_me": False})
    assert not bf.rule_matches({"labels": "urgent"}, {"labels": ["later"]})
    assert bf.rule_matches({"labels": "urgent"}, {"labels": ["urgent", "x"]})


# ---------------------------------------------------------------- rendering and CLI

def test_render_shows_sections_in_order_with_marks_and_errors(tmp_path):
    result = {"profile": "p", "title": "Morning", "collected_at": "2026-10-04T08:00", "sections": [
        {"id": "gh", "kind": "tracker", "title": "GitHub", "status": "error", "reason": "gh: offline",
         "items": [], "total": 0},
        {"id": "tasks", "kind": "tasks", "title": "Tasks", "status": "ok", "total": 3, "items": [
            {"id": "alpha", "title": "alpha", "state": "doing", "new": True, "changed": False}]}]}
    text = bf.render(result)
    assert text.index("GitHub") < text.index("Tasks")
    assert "gh: offline" in text and "alpha" in text and "new" in text and "1 of 3" in text


def test_cli_collect_json_saves_a_snapshot_and_asks_when_ambiguous(tmp_path, capsys):
    root = bridge(tmp_path, profiles={"a": {"sections": SECTIONS}, "b": {"sections": SECTIONS}})
    task(root, "alpha")
    assert bf.main(["--root", str(root), "collect"]) == 2
    assert "a, b" in capsys.readouterr().err
    assert bf.main(["--root", str(root), "collect", "a", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data["profile"] == "a" and data["sections"][0]["items"][0]["id"] == "alpha"
    assert (root / ".bridge" / "briefings" / "a.last.json").is_file()
    assert bf.main(["--root", str(root), "list"]) == 0
    assert "a" in capsys.readouterr().out
    assert bf.main(["--root", str(root), "validate"]) == 0


def test_cli_validate_fails_on_a_broken_profile(tmp_path, capsys):
    root = bridge(tmp_path, profiles={"bad": {"sections": [{"kind": "weather"}]}})
    assert bf.main(["--root", str(root), "validate"]) == 1
    assert "bad" in capsys.readouterr().out


def test_a_token_quoted_by_a_failing_adapter_is_redacted(tmp_path, monkeypatch):
    root = bridge(tmp_path)

    def leaky(section, c):
        token = c.secret("keychain://example/token")
        raise RuntimeError(f"request failed with Authorization: Bearer {token}")

    monkeypatch.setitem(bf.KINDS, "tasks", leaky)
    c = bf.Context(root, now=NOW, secret=lambda ref: "tok-very-secret")
    result = bf.collect(root, {"id": "p", "sections": [{"kind": "tasks"}]}, c)
    assert "tok-very-secret" not in json.dumps(result)
    assert "[redacted]" in result["sections"][0]["reason"]


def test_default_http_gets_the_profile_timeout(tmp_path, monkeypatch):
    root = bridge(tmp_path)
    seen = {}
    monkeypatch.setattr(bf, "_default_http", lambda m, u, h=None, b=None, timeout=None: seen.update(t=timeout))
    c = bf.Context(root, now=NOW)
    bf.collect(root, {"id": "p", "timeout_sec": 7, "sections": [{"kind": "tasks"}]}, c)
    c.http("GET", "https://example.invalid/x")
    assert seen["t"] == 7


def test_task_title_is_the_body_heading_not_a_frontmatter_comment(tmp_path):
    root = bridge(tmp_path)
    d = root / "work" / "tasks" / "alpha"
    d.mkdir(parents=True)
    (d / "STATUS.md").write_text("---\n# yaml-language-server: $schema=x\nslug: alpha\nstatus: doing\n---\n\n"
                                 "# Ship the alpha\n", encoding="utf-8")
    sec = bf.collect(root, {"id": "p", "sections": [{"kind": "tasks"}]}, ctx(root))["sections"][0]
    assert sec["items"][0]["title"] == "Ship the alpha"


def test_render_writes_dates_day_first():
    result = {"profile": "p", "title": "P", "sections": [
        {"id": "calendar", "kind": "calendar", "title": "Calendar", "status": "ok", "total": 2, "items": [
            {"id": "a", "title": "Standup", "start": "2026-10-05T09:00"},
            {"id": "b", "title": "Holiday", "start": "2026-10-06"}]}]}
    text = bf.render(result)
    assert "05.10 09:00" in text and "06.10 all day" in text


def test_icalbuddy_leaves_out_excluded_calendars(tmp_path):
    root = bridge(tmp_path)
    run = FakeRun({("icalBuddy",): ""})
    section = {"kind": "calendar", "provider": "icalbuddy", "exclude_calendars": ["Holidays", "Birthdays"]}
    bf.collect(root, {"id": "p", "sections": [section]}, ctx(root, run))
    call = run.calls[0]
    assert call[call.index("-ec") + 1] == "Holidays,Birthdays" and call[-1] == "eventsToday+1"


# ---------------------------------------------------------------- review findings (each one a test)

def test_builtin_maps_the_documented_gitlab_and_ado_config():
    cfg = {"integrations": {"gitlab": {"enabled": True, "repos": ["g/p"], "limit": 20},
                            "ado": {"enabled": True, "org": "https://dev.azure.com/example-org", "project": "Demo"}}}
    sections = {s.get("id"): s for s in bf.builtin_profile(cfg)["sections"]}
    assert sections["gitlab"]["query"] == {"repos": ["g/p"], "limit": 20}
    assert sections["ado"]["query"] == {"organization": "https://dev.azure.com/example-org", "project": "Demo"}
    bare = bf.builtin_profile({"integrations": {"gitlab": {"enabled": True}}})
    assert "gitlab" not in {s.get("id") for s in bare["sections"]}


@pytest.mark.parametrize("bad, word", [
    ({"kind": "tasks", "max": "x"}, "max"),
    ({"kind": "tasks", "max": 0}, "max"),
    ({"kind": "activity", "days": -1}, "days"),
    ({"kind": "tasks", "status": "doing"}, "status"),
    ({"kind": "tasks", "status": ["wip"]}, "status"),
    ({"kind": "tracker", "provider": "github", "state_map": ["a"]}, "state_map"),
    ({"kind": "tasks", "to_inbox": {"when": {"state": "x"}}}, "to_inbox"),
    ({"kind": "command", "argv": ["python3", 3]}, "argv"),
    ({"kind": "tasks", "id": "Not OK"}, "id"),
    ({"kind": "calendar", "provider": "command"}, "argv"),
])
def test_validate_catches_what_the_schema_rejects(bad, word):
    problems = bf.profile_problems({"schema_version": 1, "scope": "user", "id": "p", "sections": [bad]}, "p")
    assert any(word in p for p in problems), problems
    schema = yaml.safe_load((ROOT / "workflow" / "briefings" / "_schema.yaml").read_text(encoding="utf-8"))
    jsonschema = pytest.importorskip("jsonschema")
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate({"schema_version": 1, "scope": "user", "id": "p", "sections": [bad]}, schema)


def test_validate_rejects_a_bad_profile_level_timeout():
    problems = bf.profile_problems({"schema_version": 1, "scope": "user", "id": "p", "timeout_sec": "abc",
                                    "sections": [{"kind": "tasks"}]}, "p")
    assert any("timeout_sec" in p for p in problems)


def test_collect_survives_bad_numbers_it_was_handed(tmp_path):
    root = bridge(tmp_path)
    task(root, "alpha")
    result = bf.collect(root, {"id": "p", "timeout_sec": "abc", "sections": [{"kind": "tasks", "max": "x"}]},
                        ctx(root))
    assert result["sections"][0]["status"] == "ok"


def test_an_errored_run_keeps_the_last_good_snapshot(tmp_path):
    root = bridge(tmp_path)
    profile = {"id": "p", "sections": [{"kind": "tracker", "id": "gh", "provider": "github",
                                        "query": {"kinds": ["issues"]}}]}
    good = bf.collect(root, profile, ctx(root, FakeRun(gh_answers())))
    bf.save_snapshot(root, good)
    bad = bf.collect(root, profile, ctx(root, FakeRun({("gh",): bf.SourceError("offline")})),
                     previous=bf.load_snapshot(root, "p"))
    bf.save_snapshot(root, bad, bf.load_snapshot(root, "p"))
    again = bf.collect(root, profile, ctx(root, FakeRun(gh_answers())), previous=bf.load_snapshot(root, "p"))
    assert not any(i["new"] for i in again["sections"][0]["items"])


def test_ics_converts_utc_and_tzid_to_local_time(tmp_path, monkeypatch):
    monkeypatch.setenv("TZ", "Europe/Berlin")
    import time as _time
    if hasattr(_time, "tzset"):
        _time.tzset()
    try:
        assert bf._ics_date("20261004T080000Z") == "2026-10-04T10:00"
        assert bf._ics_date("20261004T090000", "TZID=Europe/London") == "2026-10-04T10:00"
        assert bf._ics_date("20261004T100000") == "2026-10-04T10:00"
    finally:
        monkeypatch.delenv("TZ")
        if hasattr(_time, "tzset"):
            _time.tzset()


def test_skip_leaves_kinds_out_and_closes_nothing(tmp_path):
    root = bridge(tmp_path)
    run = FakeRun()
    profile = {"id": "p", "sections": [{"kind": "tracker", "provider": "github"}, {"kind": "tasks"}]}
    result = bf.collect(root, profile, ctx(root, run), skip=("tracker",))
    assert result["sections"][0]["status"] == "skipped" and run.calls == []
    assert result["sections"][0]["left_out"] is True
    assert result["sections"][1]["status"] == "ok"


def test_the_time_limit_covers_the_whole_section(tmp_path, monkeypatch):
    root = bridge(tmp_path)
    clock = iter([0.0, 0.0, 5.0, 11.0, 11.0, 50.0])
    monkeypatch.setattr(bf.time, "monotonic", lambda: next(clock, 99.0))
    limits = []

    def slow(argv, timeout=None, cwd=None):
        limits.append(timeout)
        return "[]"

    c = bf.Context(root, now=NOW, run=slow, timeout=10)
    section = {"kind": "tracker", "provider": "github", "query": {"kinds": ["issues", "prs"]}}
    sec = bf.collect(root, {"id": "p", "sections": [section]}, c)["sections"][0]
    assert sec["status"] == "error" and "time limit" in sec["reason"]
    assert limits and all(t <= 10 for t in limits)


def test_icalbuddy_keeps_events_across_midnight_and_several_days(tmp_path):
    root = bridge(tmp_path)
    out = "2026-10-04 at 23:00 - 2026-10-05 at 01:00\tLate deploy\n2026-10-04 - 2026-10-06\tOffsite\n"
    run = FakeRun({("icalBuddy",): out})
    items = bf.collect(root, {"id": "p", "sections": [{"kind": "calendar", "provider": "icalbuddy"}]},
                       ctx(root, run))["sections"][0]["items"]
    # in time order, an all-day event first on its day (as the ics provider sorts)
    assert [(i["title"], i["start"], i["end"]) for i in items] == [
        ("Offsite", "2026-10-04", "2026-10-06"), ("Late deploy", "2026-10-04T23:00", "2026-10-05T01:00")]


def test_provider_errors_are_source_errors_under_the_cli(tmp_path, capsys):
    import subprocess
    root = bridge(tmp_path, profiles={"p": {"sections": [{"kind": "tracker", "provider": "gitlab"}]}})
    res = subprocess.run([sys.executable, str(ROOT / "scripts" / "briefing.py"), "--root", str(root), "render", "p",
                          "--no-save"], capture_output=True, text=True, timeout=60,
                         env={**__import__("os").environ, "PYTHONDONTWRITEBYTECODE": "1"})
    assert "query.repos is required" in res.stdout and "RuntimeError" not in res.stdout


def test_github_review_request_wins_over_the_assigned_copy(tmp_path):
    root = bridge(tmp_path)
    pr = json.loads((FIX / "github" / "search-prs.json").read_text())[:1]
    run = FakeRun({("gh", "api", "user"): '{"login": "octo"}', ("gh", "search", "issues"): "[]",
                   ("gh", "search", "prs"): json.dumps(pr)})
    section = {"kind": "tracker", "provider": "github", "query": {"review_requested": True}}
    item = bf.collect(root, {"id": "p", "sections": [section]}, ctx(root, run))["sections"][0]["items"][0]
    assert item["category"] == "qa" and item["assigned_to_me"] is True


def test_github_assignee_other_than_me_is_not_mine(tmp_path):
    root = bridge(tmp_path)
    run = FakeRun({**gh_answers(), ("gh", "api", "user"): '{"login": "someone-else"}'})
    section = {"kind": "tracker", "provider": "github", "query": {"assignee": "octo", "kinds": ["issues"]}}
    items = bf.collect(root, {"id": "p", "sections": [section]}, ctx(root, run))["sections"][0]["items"]
    assert items and not any(i["assigned_to_me"] for i in items)


def test_items_close_when_rules_or_the_section_are_removed(tmp_path):
    root = bridge(tmp_path)
    task(root, "alpha", blocked_by="vendor")
    box = inbox.Inbox(root / "work" / "inbox", actor="t", clock=lambda: NOW)
    with_rule = {"id": "m", "sections": [{"kind": "tasks", "to_inbox": [{"when": {"state": "doing"}}]}]}
    assert bf.file_to_inbox(box, with_rule, bf.collect(root, with_rule, ctx(root)))[0] == 1
    without = {"id": "m", "sections": [{"kind": "tasks"}]}
    assert bf.file_to_inbox(box, without, bf.collect(root, without, ctx(root))) == (0, 1)
    assert bf.file_to_inbox(box, with_rule, bf.collect(root, with_rule, ctx(root)))[0] == 1
    gone = {"id": "m", "sections": [{"kind": "activity"}]}
    assert bf.file_to_inbox(box, gone, bf.collect(root, gone, ctx(root))) == (0, 1)


def test_an_item_the_cockpit_filed_for_a_row_closes_when_the_row_is_gone_not_when_no_rule_wants_it(tmp_path):
    """Do it on a page row files an item under the to_inbox key; no rule asked for it, so the sweep that
    closes what no rule wants must leave it while its row is there"""
    root = bridge(tmp_path)
    task(root, "alpha", blocked_by="vendor")
    box = inbox.Inbox(root / "work" / "inbox", actor="t", clock=lambda: NOW)
    profile = {"id": "m", "sections": [{"kind": "tasks"}]}
    box.add(source="bridge-cockpit", kind="decision", summary="Tasks: alpha", gate="free", closer="reporter",
            key="briefing:m:tasks:alpha")
    assert bf.file_to_inbox(box, profile, bf.collect(root, profile, ctx(root))) == (0, 0)
    box.add(source="bridge-cockpit", kind="decision", summary="Tasks: vanished", gate="free", closer="reporter",
            key="briefing:m:tasks:vanished")
    assert bf.file_to_inbox(box, profile, bf.collect(root, profile, ctx(root))) == (0, 1)


def test_account_ref_must_stay_inside_the_bridge(tmp_path):
    root = bridge(tmp_path)
    outside = tmp_path / "elsewhere.yaml"
    outside.write_text("base_url: https://x\n", encoding="utf-8")
    with pytest.raises(bf.SourceError):
        ctx(root).account({"account_ref": "../elsewhere.yaml"})


def test_builtin_shows_the_workplace_when_one_is_configured():
    assert "workplace" not in [s["kind"] for s in bf.builtin_profile({})["sections"]]
    kinds = [s["kind"] for s in bf.builtin_profile({"workplace": {"driver": "none"}})["sections"]]
    assert "workplace" in kinds and kinds.index("workplace") > kinds.index("tasks")


def test_workplace_section_names_a_failing_driver(tmp_path):
    """Without the tab list every task looks new; the briefing must say so, not hide it."""
    root = bridge(tmp_path, config={"workplace": {"driver": {"command": ["/definitely/not/here"]}}})
    task(root, "alpha")
    sec = bf.collect(root, {"id": "p", "sections": [{"kind": "workplace"}]}, ctx(root))["sections"][0]
    assert sec["items"][0]["state"] == "warning"
    assert "unknown" in sec["items"][0]["title"].lower()
    assert sec["plan"]["driver_error"]


# ---------------------------------------------------------------- housekeeping (--file)
# The steps the playbook used to leave to the agent (today's day block, the log row,
# regenerating the board, noticing an overdue archive) were skipped the morning the
# view looked complete. A step a run can skip is a step nobody did: the engine does them.

LOG = """# Week 41

## Mon 05.10

| Timestamp | Type | Context | What |
|---|---|---|---|
| 2026-10-05 07:18 | 📋 | bridge | earlier |
"""


def _hk_root(tmp_path, log=LOG):
    root = tmp_path / "bridge"
    (root / "work" / "inbox").mkdir(parents=True)
    (root / "work" / "log.md").write_text(log, encoding="utf-8")
    (root / "bridge-config.yaml").write_text("work:\n  enabled: true\n", encoding="utf-8")
    return root


def test_housekeeping_opens_todays_day_block_and_writes_the_log_row(tmp_path):
    root = _hk_root(tmp_path)
    now = dt.datetime(2026, 10, 6, 7, 38)
    notes = bf.housekeep(root, now, summary="Do 1 · Plan 6", profile_id="morning", run=lambda *a, **k: "")
    text = (root / "work" / "log.md").read_text(encoding="utf-8")
    assert "\n## " in text.split("2026-10-05 07:18")[1] and " 06.10" in text
    assert text.rstrip().endswith("| 2026-10-06 07:38 | 📋 | bridge | /briefing (morning): Do 1 · Plan 6 |")
    assert text.count(" 06.10") == 1
    bf.housekeep(root, now.replace(minute=50), summary="Do 0", profile_id="morning", run=lambda *a, **k: "")
    text = (root / "work" / "log.md").read_text(encoding="utf-8")
    assert text.count(" 06.10\n") == 1 and text.rstrip().endswith("/briefing (morning): Do 0 |")
    assert isinstance(notes, list)


def test_housekeeping_regenerates_the_board_when_the_generator_exists(tmp_path):
    root = _hk_root(tmp_path)
    (root / "scripts").mkdir()
    (root / "scripts" / "gen-board.py").write_text("", encoding="utf-8")
    calls = []
    bf.housekeep(root, NOW, summary="x", profile_id="p", run=lambda argv, **k: calls.append(argv) or "")
    assert any(str(a).endswith("gen-board.py") for c in calls for a in c)


def test_housekeeping_names_an_overdue_archive(tmp_path):
    root = _hk_root(tmp_path)
    (root / "scripts").mkdir()
    (root / "scripts" / "archive-buckets.py").write_text("", encoding="utf-8")
    plan = json.dumps({"buckets": [{"label": "Week 40", "closed": True, "archive": True},
                                   {"label": "Week 41", "closed": False, "archive": False}]})
    notes = bf.housekeep(root, NOW, summary="x", profile_id="p",
                         run=lambda argv, **k: plan if any("archive-buckets" in str(a) for a in argv) else "")
    assert any("Week 40" in n and "/archive" in n for n in notes)


def test_housekeeping_failure_is_a_note_never_an_abort(tmp_path):
    root = _hk_root(tmp_path)
    (root / "scripts").mkdir()
    (root / "scripts" / "gen-board.py").write_text("", encoding="utf-8")

    def boom(argv, **k):
        raise bf.SourceError("exit 1")
    notes = bf.housekeep(root, NOW, summary="x", profile_id="p", run=boom)
    assert any("gen-board" in n for n in notes)


def test_housekeeping_without_a_log_does_nothing_to_it(tmp_path):
    root = _hk_root(tmp_path)
    (root / "work" / "log.md").unlink()
    bf.housekeep(root, NOW, summary="x", profile_id="p", run=lambda *a, **k: "")
    assert not (root / "work" / "log.md").exists()


TEMPLATE_LOG = """# Week 41

## Mon 05.10

<details>
<summary>Worklog (1)</summary>

| Timestamp        | Glyph | Context | What |
|------------------|-------|---------|------|
| 2026-10-05 07:18 | 📋 | bridge | earlier |

</details>
"""

DAY_TEMPLATE = """<!--
comment
-->

## {Weekday} DD.MM

<details open>
<summary>Worklog (0)</summary>

| Timestamp        | Glyph | Context | What |
|------------------|-------|---------|------|

</details>
"""


def _row_lines(text):
    return [l for l in text.splitlines() if l.startswith("| 2026-")]


def test_housekeeping_follows_the_day_template_and_stays_inside_the_table(tmp_path):
    root = _hk_root(tmp_path, TEMPLATE_LOG)
    (root / "work" / "templates").mkdir()
    (root / "work" / "templates" / "day.md").write_text(DAY_TEMPLATE, encoding="utf-8")
    now = dt.datetime(2026, 10, 6, 7, 38)
    bf.housekeep(root, now, summary="Do 1", profile_id="morning", run=lambda *a, **k: "", weekday="Tue")
    text = (root / "work" / "log.md").read_text(encoding="utf-8")
    today = text[text.index("## Tue 06.10"):]
    assert "<summary>Worklog (1)</summary>" in today
    assert today.index("/briefing (morning)") < today.index("</details>")
    assert "comment" not in today and "{Weekday}" not in today


def test_housekeeping_finds_today_in_a_newest_first_log(tmp_path):
    log = ("# Week 41\n\n## Tue 06.10\n\n| Timestamp | Glyph | Context | What |\n|---|---|---|---|\n"
           "| 2026-10-06 07:00 | 📋 | x | first |\n\n## Mon 05.10\n\n| Timestamp | Glyph | Context | What |\n"
           "|---|---|---|---|\n| 2026-10-05 07:18 | 📋 | bridge | earlier |\n")
    root = _hk_root(tmp_path, log)
    bf.housekeep(root, dt.datetime(2026, 10, 6, 7, 38), summary="Do 1", profile_id="m", run=lambda *a, **k: "")
    text = (root / "work" / "log.md").read_text(encoding="utf-8")
    assert text.count("06.10\n") == 1
    rows = _row_lines(text)
    assert rows[1].startswith("| 2026-10-06 07:38") and rows[2].startswith("| 2026-10-05")


def test_housekeeping_twice_in_one_run_writes_one_row(tmp_path):
    root = _hk_root(tmp_path)
    for minute in (38, 39):
        bf.housekeep(root, dt.datetime(2026, 10, 6, 7, minute), summary=f"Do {minute}", profile_id="morning",
                     run=lambda *a, **k: "")
    rows = [r for r in _row_lines((root / "work" / "log.md").read_text(encoding="utf-8")) if "/briefing" in r]
    assert len(rows) == 1 and rows[0].startswith("| 2026-10-06 07:39") and "Do 39" in rows[0]


def test_housekeeping_escapes_a_pipe_in_the_summary(tmp_path):
    root = _hk_root(tmp_path)
    bf.housekeep(root, NOW, summary="A | B", profile_id="m", run=lambda *a, **k: "")
    row = _row_lines((root / "work" / "log.md").read_text(encoding="utf-8"))[-1]
    assert row.count("|") == 5


def test_summary_counts_rows_in_every_style(tmp_path):
    sections = [{"kind": "inbox"}]
    item = {"id": "1", "title": "x", "state": "open", "urgency": "today", "kind": "decision", "gate": "your-yes",
            "due": None, "task": None}
    result = {"profile": "p", "collected_at": "2026-10-06T07:38", "sections": [
        {"id": "inbox", "kind": "inbox", "title": "Inbox", "status": "ok", "items": [item], "all": [item], "total": 1}]}
    for style in ("triage", "plan", "brevity"):
        assert "1" in bf._summary(result, {"id": "p", "sections": sections, "view": {"style": style}}, None)


def test_render_file_end_to_end_writes_one_row_and_shows_housekeeping(tmp_path, capsys):
    root = _hk_root(tmp_path)
    prof = {"schema_version": 1, "scope": "user", "id": "morning", "default": True,
            "sections": [{"kind": "inbox"}], "view": {"style": "triage"}}
    (root / "workflow" / "briefings").mkdir(parents=True)
    (root / "workflow" / "briefings" / "morning.yaml").write_text(yaml.safe_dump(prof), encoding="utf-8")
    for _ in range(2):   # collect --file then render --file, as a playbook might
        assert bf.main(["--root", str(root), "render", "--file"]) == 0
    text = (root / "work" / "log.md").read_text(encoding="utf-8")
    assert sum(1 for l in text.splitlines() if "/briefing (morning)" in l) == 1
    assert "/briefing (morning): nothing open" in text


# ---------------------------------------------------------------- owed streams
# A profile covers some streams; the playbook's other streams were left to the agent's
# judgement, and a test run improvised its own commands (and failed on them). The engine
# names what the profile does not cover, with the way to run it, so nothing is guessed.

def _owed_root(tmp_path, cfg=""):
    root = tmp_path / "bridge"
    (root / "work" / "inbox").mkdir(parents=True)
    (root / "bridge-config.yaml").write_text(cfg or "{}\n", encoding="utf-8")
    return root


def test_owed_names_relevant_streams_the_profile_does_not_cover(tmp_path):
    root = _owed_root(tmp_path, "upstreams:\n  - {name: core, repo: acme/core, role: oss-core}\n"
                                "applications: {enabled: true}\nintegrations: {github: {enabled: true}}\n")
    (root / "work" / "tasks" / "_meetings").mkdir(parents=True)
    (root / "work" / "imports").mkdir(parents=True)
    (root / "work" / "imports" / "call.vtt").write_text("x", encoding="utf-8")
    profile = {"id": "m", "sections": [{"kind": "inbox"}]}
    owed = {o["id"] for o in bf.owed(root, bf.read_config(root), profile)}
    assert owed == {"prs", "meetings", "imports", "upstream", "applications"}


def test_owed_is_empty_when_nothing_applies(tmp_path):
    root = _owed_root(tmp_path)
    assert bf.owed(root, bf.read_config(root), {"id": "m", "sections": [{"kind": "inbox"}]}) == []


def test_a_section_covers_streams_by_declaration_and_others_prs_covers_prs(tmp_path):
    root = _owed_root(tmp_path, "integrations: {github: {enabled: true}}\n")
    (root / "work" / "tasks" / "_meetings").mkdir(parents=True)
    profile = {"id": "m", "sections": [
        {"kind": "command", "id": "dl", "argv": ["x"], "covers": ["meetings"]},
        {"kind": "tracker", "provider": "github", "query": {"owners": ["acme"], "others_prs": 14}}]}
    assert bf.owed(root, bf.read_config(root), profile) == []


def test_every_owed_stream_says_how_to_run_it(tmp_path):
    root = _owed_root(tmp_path, "integrations: {github: {enabled: true}}\n")
    (o,) = bf.owed(root, bf.read_config(root), {"id": "m", "sections": []})
    assert o["id"] == "prs" and o["how"] and o["title"]


def test_covers_is_validated(tmp_path):
    p = {"schema_version": 1, "scope": "user", "id": "m",
         "sections": [{"kind": "command", "argv": ["x"], "covers": ["nonsense"]}]}
    assert any("covers" in m for m in bf.profile_problems(p, "m"))


def test_render_names_owed_streams_under_housekeeping(tmp_path, capsys):
    root = _owed_root(tmp_path, "integrations: {github: {enabled: false}}\n")
    (root / "work" / "tasks" / "_meetings").mkdir(parents=True)
    prof = {"schema_version": 1, "scope": "user", "id": "morning", "default": True,
            "sections": [{"kind": "inbox"}], "view": {"style": "triage"}}
    (root / "workflow" / "briefings").mkdir(parents=True)
    (root / "workflow" / "briefings" / "morning.yaml").write_text(yaml.safe_dump(prof), encoding="utf-8")
    assert bf.main(["--root", str(root), "render", "--no-save"]) == 0
    out = capsys.readouterr().out
    assert "meetings" in out and "briefing.py owed" in out
    assert bf.main(["--root", str(root), "owed"]) == 0
    assert "meeting-obligations.py" in capsys.readouterr().out


def test_render_file_writes_the_overview_and_names_it(tmp_path, capsys):
    root = _hk_root(tmp_path)
    prof = {"schema_version": 1, "scope": "user", "id": "morning", "default": True,
            "sections": [{"kind": "inbox"}], "view": {"style": "triage", "overview": "file"}}
    (root / "workflow" / "briefings").mkdir(parents=True)
    (root / "workflow" / "briefings" / "morning.yaml").write_text(yaml.safe_dump(prof), encoding="utf-8")
    assert bf.main(["--root", str(root), "render", "--file"]) == 0
    out = capsys.readouterr().out
    path = root / ".bridge" / "briefings" / "morning.overview.txt"
    assert path.is_file() and str(path.relative_to(root)) in out


# ---------------------------------------------------------------- gh rate-limit retry
# On 2026-10-06 the GitHub sections failed with "API rate limit already exceeded"
# while the token had used 103 of 5000 points: bursts from several sessions at once,
# not an empty quota. A short wait and one more try is the right answer to a burst.

class Flaky:
    # a burst: GitHub's secondary limit, which passes in seconds (the hour's spent budget does not, below)
    def __init__(self, failures, message="gh: You have exceeded a secondary rate limit. Please wait a few minutes."):
        self.failures, self.message, self.calls = failures, message, 0

    def __call__(self, argv, timeout=30, cwd=None):
        self.calls += 1
        if self.calls <= self.failures:
            raise bf.SourceError(self.message)
        return "ok"


def test_gh_rate_limit_is_retried_after_a_wait(tmp_path):
    waits = []
    ctx = bf.Context(tmp_path, now=NOW, run=Flaky(2), cfg={}, sleep=waits.append, rand=lambda: 0.0)
    assert ctx.run(["gh", "search", "issues"]) == "ok"
    assert waits == list(bf.GH_RETRY_WAITS)


def test_gh_retry_waits_are_spread_so_side_by_side_calls_do_not_retry_together(tmp_path):
    """Boards are asked side by side (#317). When a burst limit hits them all, equal waits
    send every retry in the same second and hit the limit again (live 2026-10-09)."""
    low, high = [], []
    bf.Context(tmp_path, now=NOW, run=Flaky(2), cfg={}, sleep=low.append, rand=lambda: 0.0).run(["gh", "x"])
    bf.Context(tmp_path, now=NOW, run=Flaky(2), cfg={}, sleep=high.append, rand=lambda: 1.0).run(["gh", "x"])
    assert low == list(bf.GH_RETRY_WAITS)
    assert high == [w * 1.5 for w in bf.GH_RETRY_WAITS]


def test_gh_unknown_owner_type_is_retried_like_a_rate_limit(tmp_path):
    """gh 2.x reports a throttled owner lookup of `gh project item-list` as "unknown owner
    type" (live 2026-10-09, while a single call with a valid owner failed the same way)."""
    waits = []
    flaky = Flaky(1, message="unknown owner type")
    ctx = bf.Context(tmp_path, now=NOW, run=flaky, cfg={}, sleep=waits.append, rand=lambda: 0.0)
    assert ctx.run(["gh", "project", "item-list", "3", "--owner", "example-org"]) == "ok"
    assert waits == [bf.GH_RETRY_WAITS[0]] and flaky.calls == 2


def test_a_spent_hourly_budget_is_not_retried_and_stops_github_until_the_reset(tmp_path):
    """Waiting seconds does not refill an hour's budget: on 2026-10-18 every section retried twice into
    a spent GraphQL budget, pass after pass. The first such answer blocks GitHub for every section."""
    waits = []
    flaky = Flaky(9, message="gh: GraphQL: API rate limit already exceeded for user ID 1.")
    ctx = bf.Context(tmp_path, now=dt.datetime.now(), run=flaky, cfg={}, sleep=waits.append)
    with pytest.raises(bf.SourceError, match="rate limit"):
        ctx.run(["gh", "search", "issues"])
    assert waits == [] and bf.github_blocked(tmp_path, dt.datetime.now()) is not None
    calls = flaky.calls
    with pytest.raises(bf.SourceError, match="not asked until"):
        ctx.run(["gh", "project", "item-list", "3"])
    assert flaky.calls == calls                    # blocked before it reached GitHub
    other = bf.Context(tmp_path, now=dt.datetime.now(), run=Flaky(0), cfg={})
    assert other.run(["glab", "issue", "list"]) == "ok"   # other tools are not GitHub


def test_gh_rate_limit_gives_up_after_the_retries(tmp_path):
    ctx = bf.Context(tmp_path, now=NOW, run=Flaky(9), cfg={}, sleep=lambda s: None)
    with pytest.raises(bf.SourceError, match="rate limit"):
        ctx.run(["gh", "search", "issues"])


def test_other_errors_and_other_tools_are_not_retried(tmp_path):
    waits = []
    flaky = Flaky(1, message="gh: not logged in")
    with pytest.raises(bf.SourceError):
        bf.Context(tmp_path, now=NOW, run=flaky, cfg={}, sleep=waits.append).run(["gh", "api", "user"])
    other = Flaky(1)
    with pytest.raises(bf.SourceError):
        bf.Context(tmp_path, now=NOW, run=other, cfg={}, sleep=waits.append).run(["glab", "issue", "list"])
    assert waits == [] and flaky.calls == 1 and other.calls == 1


def test_no_retry_when_the_wait_would_exceed_the_section_limit(tmp_path):
    waits = []
    ctx = bf.Context(tmp_path, now=NOW, run=Flaky(1), cfg={}, sleep=waits.append, timeout=3)
    ctx.deadline = __import__("time").monotonic() + 3
    with pytest.raises(bf.SourceError):
        ctx.run(["gh", "search", "issues"])
    assert waits == []


# ---------------------------------------------------------------- info calendars
# A family calendar shows what others do: information, not a commitment of the
# reader. Its events are tagged `info` at the source, so an overlap with them
# never becomes a do row and never a collision finding.

ICAL_TWO = ("2026-10-04 at 18:00 - 18:45\tWeekly\n"
            "2026-10-04 at 18:05 - 19:05\tSchool play\n")


ICAL_BY_CALENDAR = ("Work:@@calendar@@\n" + ICAL_TWO.splitlines()[0] + "\nFamily:@@calendar@@\n"
                    + ICAL_TWO.splitlines()[1] + "\n")


def test_icalbuddy_tags_events_of_info_calendars(tmp_path):
    # one call: -sc puts each event under a line naming its calendar, the info calendars are matched by name
    root = bridge(tmp_path)
    run = FakeRun({("icalBuddy",): ICAL_BY_CALENDAR})
    section = {"kind": "calendar", "provider": "icalbuddy", "exclude_calendars": ["Holidays"],
               "info_calendars": ["Family", "Kids"]}
    items = bf.collect(root, {"id": "p", "sections": [section]}, ctx(root, run))["sections"][0]["items"]
    assert {i["title"]: bool(i.get("info")) for i in items} == {"Weekly": False, "School play": True}
    (call,) = run.calls
    assert "-ic" not in call and "-sc" in call and call[-1] == "eventsToday+1"


def test_icalbuddy_without_info_calendars_calls_once(tmp_path):
    root = bridge(tmp_path)
    run = FakeRun({("icalBuddy",): ICAL_TWO})
    items = bf.collect(root, {"id": "p", "sections": [{"kind": "calendar", "provider": "icalbuddy"}]},
                       ctx(root, run))["sections"][0]["items"]
    assert len(run.calls) == 1 and not any(i.get("info") for i in items)


def test_ics_file_named_as_info_calendar_is_info(tmp_path):
    root = bridge(tmp_path)
    ics = tmp_path / "family.ics"
    ics.write_text("BEGIN:VCALENDAR\nX-WR-CALNAME:Family\nBEGIN:VEVENT\nSUMMARY:School play\n"
                   "DTSTART:20261004T180500\nDTEND:20261004T190500\nEND:VEVENT\nEND:VCALENDAR\n", encoding="utf-8")
    section = {"kind": "calendar", "provider": "ics", "path": str(ics), "info_calendars": ["Family"]}
    items = bf.collect(root, {"id": "p", "sections": [section]}, ctx(root))["sections"][0]["items"]
    assert [(i["title"], i.get("info")) for i in items] == [("School play", True)]
    plain = dict(section, info_calendars=["Other"])
    items = bf.collect(root, {"id": "p", "sections": [plain]}, ctx(root))["sections"][0]["items"]
    assert not items[0].get("info")


def test_command_calendar_passes_info_through_and_matches_calendar_names(tmp_path):
    root = bridge(tmp_path)
    events = [{"title": "Weekly", "start": "2026-10-04T18:00", "end": "2026-10-04T18:45"},
              {"title": "School play", "start": "2026-10-04T18:05", "end": "2026-10-04T19:05", "info": True},
              {"title": "Swim", "start": "2026-10-04T20:00", "end": "2026-10-04T21:00", "calendar": "Family"}]
    run = FakeRun({("cal",): json.dumps(events)})
    section = {"kind": "calendar", "provider": "command", "argv": ["cal"], "info_calendars": ["Family"]}
    items = bf.collect(root, {"id": "p", "sections": [section]}, ctx(root, run))["sections"][0]["items"]
    assert {i["title"]: bool(i.get("info")) for i in items} == {"Weekly": False, "School play": True, "Swim": True}


def test_advise_ignores_info_events_for_collisions(tmp_path):
    root = bridge(tmp_path)
    box = inbox.Inbox(root / "work" / "inbox", actor="t", clock=lambda: NOW)
    box.add(source="t", kind="decision", summary="Call the vendor", due="2026-10-04T19:00")
    run = FakeRun({("icalBuddy",): ICAL_BY_CALENDAR})
    profile = {"id": "p", "sections": [{"kind": "advise"},
                                       {"kind": "calendar", "provider": "icalbuddy", "info_calendars": ["Family"]}]}
    advice = bf.collect(root, profile, ctx(root, run))["sections"][0]
    assert not any(i.get("check") == "collision" for i in advice["items"]), advice


def test_validate_info_calendars_is_a_list_of_text():
    ok = {"schema_version": 1, "scope": "user", "id": "p",
          "sections": [{"kind": "calendar", "info_calendars": ["Family"]}]}
    assert bf.profile_problems(ok, "p") == []
    bad = {**ok, "sections": [{"kind": "calendar", "info_calendars": "Family"}]}
    assert any("info_calendars" in p for p in bf.profile_problems(bad, "p"))
    schema = yaml.safe_load((ROOT / "workflow" / "briefings" / "_schema.yaml").read_text(encoding="utf-8"))
    jsonschema = pytest.importorskip("jsonschema")
    jsonschema.validate(ok, schema)


def test_tasks_section_carries_priority_from_the_frontmatter(tmp_path):
    root = bridge(tmp_path)
    task(root, "alpha", priority="P0")
    task(root, "beta")
    items = bf.collect(root, {"id": "p", "sections": [{"kind": "tasks"}]}, ctx(root))["sections"][0]["items"]
    by = {i["id"]: i for i in items}
    assert by["alpha"]["priority"] == "P0" and by["beta"]["priority"] is None


def test_cli_max_items_lifts_the_view_cap_for_one_run(tmp_path, capsys, monkeypatch):
    """A dashboard with its own paging wants every row; the profile's cap stays for the text."""
    root = bridge(tmp_path, profiles={"a": {"sections": SECTIONS, "view": {"style": "triage", "max_items": 1}}})
    seen = []
    real = bf._view().build
    monkeypatch.setattr(bf._view(), "build", lambda result, profile, style=None: (
        seen.append(profile["view"]["max_items"]) or real(result, profile, style)))
    assert bf.main(["--root", str(root), "collect", "a", "--json", "--no-save"]) == 0
    assert bf.main(["--root", str(root), "collect", "a", "--json", "--no-save", "--max-items", "500"]) == 0
    capsys.readouterr()
    assert seen == [1, 500]
    assert "max_items: 1" in (root / "workflow" / "briefings" / "a.yaml").read_text(encoding="utf-8")


def test_two_board_sections_loading_tracker_sync_at_once_both_get_it_whole(tmp_path):
    """Sections run side by side: the second board section must never see a half-loaded
    tracker-sync (it would fail with AttributeError on resolve_boards)."""
    root = bridge(tmp_path, config={"integrations": {"github": {"assignee_me": "octo"}}})
    (root / "ecosystem.yaml").write_text(yaml.safe_dump({"github_projects": [
        {"org": "example-org", "number": 3, "name": "Tool board"}]}), encoding="utf-8")
    run = FakeRun({("gh", "project", "item-list"): (FIX / "github-board" / "item-list.json").read_text()})
    sections = [{"kind": "tracker", "provider": "github-board", "id": f"board{n}", "query": {"include_done": True}}
                for n in range(8)]
    for _ in range(20):
        saved = sys.modules.pop("tracker_sync", None)
        try:
            result = bf.collect(root, {"id": "p", "sections": sections}, ctx(root, run))
        finally:
            if saved is not None:
                sys.modules["tracker_sync"] = saved
        assert [s["status"] for s in result["sections"]] == ["ok"] * 8, [s.get("reason") for s in result["sections"]]


# ---------------------------------------------------------------- the detail of a task row

def test_tasks_carry_origin_type_open_steps_and_their_latest_log_rows(tmp_path):
    root = bridge(tmp_path)
    task(root, "alpha", origin="Asked on 2026-10-01 in chat", type="feature")
    status = root / "work" / "tasks" / "alpha" / "STATUS.md"
    status.write_text(status.read_text(encoding="utf-8") + "\n## Next Steps\n- write the draft\n\n"
                      "- [x] a done box\n- [ ] first open box\n- [ ] second open box\n", encoding="utf-8")
    task(root, "beta")
    status = root / "work" / "tasks" / "beta" / "STATUS.md"
    status.write_text(status.read_text(encoding="utf-8") + "\n## Next steps\n\n- one\n- two\n"
                      "- three\n- four\n\n## Notes\n- not a step\n", encoding="utf-8")
    task(root, "alpha-two")
    (root / "work" / "log.md").write_text(
        "## Thursday 01.10\n\n| Time | | ctx | what |\n|---|---|---|---|\n"
        "| 2026-10-01 09:00 | x | bridge | alpha started |\n"
        "| 2026-10-02 10:00 | x | bridge | beta only, alpha-two too |\n"
        "| 2026-10-03 11:00 | x | bridge | alpha draft done |\n"
        "| 2026-10-03 12:00 | x | bridge | alpha review asked |\n", encoding="utf-8")
    items = {i["id"]: i for i in bf.sec_tasks({"status": ["doing"]}, ctx(root))}
    alpha = items["alpha"]
    assert alpha["origin"] == "Asked on 2026-10-01 in chat" and alpha["type"] == "feature"
    assert alpha["steps"] == ["first open box", "second open box"]       # open boxes before bullets
    assert alpha["log"] == ["2026-10-03 11:00 alpha draft done", "2026-10-03 12:00 alpha review asked"]
    assert items["beta"]["steps"] == ["one", "two", "three"]
    assert items["beta"]["log"] == ["2026-10-02 10:00 beta only, alpha-two too"]
    assert items["alpha-two"]["log"] == ["2026-10-02 10:00 beta only, alpha-two too"]
    assert items["alpha-two"]["steps"] == [] and items["alpha-two"]["origin"] is None


def test_task_step_headings_come_from_the_section_not_from_core(tmp_path):
    # CORE knows the English headings only; an instance names its own in the profile's section.
    root = bridge(tmp_path)
    task(root, "alpha")
    status = root / "work" / "tasks" / "alpha" / "STATUS.md"
    status.write_text(status.read_text(encoding="utf-8") + "\n## Upcoming\n- one\n- two\n", encoding="utf-8")
    assert bf.sec_tasks({"status": ["doing"]}, ctx(root))[0]["steps"] == []
    (item,) = bf.sec_tasks({"status": ["doing"], "step_headings": ["upcoming"]}, ctx(root))
    assert item["steps"] == ["one", "two"]


def test_a_wrapped_open_box_keeps_its_continuation_and_loses_its_markdown(tmp_path):
    root = bridge(tmp_path)
    task(root, "alpha")
    status = root / "work" / "tasks" / "alpha" / "STATUS.md"
    status.write_text(status.read_text(encoding="utf-8")
                      + "\n- [ ] **Decide** where rates live (`identity/x`\n      vs. `workflow/y`), open gap\n"
                      "- [ ] second\n", encoding="utf-8")
    (item,) = bf.sec_tasks({"status": ["doing"]}, ctx(root))
    assert item["steps"] == ["Decide where rates live (identity/x vs. workflow/y), open gap", "second"]


# ---------------------------------------------------------------- schema and validator agree
# `step_headings` reached the schema and the template but not SECTION_KEYS, so a profile
# that used it as documented failed `briefing.py validate` (live 2026-10-09).

def test_validator_knows_every_key_the_schema_documents():
    schema = yaml.safe_load((ROOT / "workflow" / "briefings" / "_schema.yaml").read_text(encoding="utf-8"))
    section = set(schema["$defs"]["section"]["properties"])
    profile = set(schema["properties"])
    assert section - bf.SECTION_KEYS == set(), "documented section keys the validator rejects"
    assert bf.SECTION_KEYS - section == set(), "section keys the validator accepts but the schema does not document"
    assert profile - bf.PROFILE_KEYS == set(), "documented profile keys the validator rejects"


def test_a_tasks_section_with_step_headings_validates(tmp_path):
    root = bridge(tmp_path, profiles={"a": {"id": "a", "sections": [
        {"kind": "tasks", "status": ["doing"], "step_headings": ["Next moves"]}]}})
    assert not [p for p in bf.validate(root) if "step_headings" in str(p)]


def test_a_section_naming_python3_runs_under_the_interpreter_of_the_briefing():
    # Homebrew moved `python3` to a release without PyYAML; a section saying "python3"
    # means the interpreter the briefing itself runs in, whose packages are known to work
    out = bf._default_run(["python3", "-c", "import sys; print(sys.executable)"])
    assert out.strip() == sys.executable
    assert bf._own_python(["python", "x.py"])[0] == sys.executable
    assert bf._own_python(["gh", "api"]) == ["gh", "api"]


# ---------------------------------------------------------------- one profile builds on another (the cockpit's)

def test_a_profile_extends_another_and_adds_to_it(tmp_path):
    # the cockpit's profile takes every section of the morning briefing and adds its own, with its own pages
    root = bridge(tmp_path, profiles={
        "morning": {"default": True, "offer_on": ["good morning"], "title": "Morning",
                    "sections": [{"kind": "inbox"}, {"kind": "tasks", "status": ["doing"]}],
                    "view": {"style": "triage", "max_items": 7}},
        "cockpit": {"extends": "morning", "title": "Cockpit",
                    "sections": [{"kind": "tasks", "status": ["doing", "review"]},
                                 {"kind": "command", "id": "res", "argv": ["echo"]}],
                    "view": {"pages": [{"id": "ops", "sections": ["res", "inbox"]}]}}})
    by = {p["id"]: p for p in bf.load_profiles(root)}
    c = by["cockpit"]
    assert [bf.section_id(s) for s in c["sections"]] == ["inbox", "tasks", "res"]
    assert c["sections"][1]["status"] == ["doing", "review"]                 # its own wins over the base
    assert c["view"]["style"] == "triage" and c["view"]["max_items"] == 7     # the base's view carries over
    assert c["view"]["pages"][0]["id"] == "ops" and "pages" not in by["morning"]["view"]
    assert c.get("default") is not True and not c.get("offer_on")             # it never becomes the briefing
    assert c["title"] == "Cockpit"
    assert bf.select(root, {})["id"] == "morning"
    assert bf.validate(root) == []                                            # pages may name the base's sections


def test_extends_names_an_existing_profile_and_never_itself(tmp_path):
    root = bridge(tmp_path, profiles={
        "morning": {"default": True, "sections": SECTIONS},
        "lost": {"extends": "nowhere", "sections": SECTIONS},
        "loop-a": {"extends": "loop-b", "sections": SECTIONS},
        "loop-b": {"extends": "loop-a", "sections": SECTIONS}})
    problems = " | ".join(bf.validate(root))
    assert "lost.yaml: extends: no profile 'nowhere'" in problems
    assert "loop-a.yaml: extends: a circle" in problems


# ---------------------------------------------------------------- calendar details and steps
# icalBuddy separates its events by calendar (-sc), so each event knows the calendar it comes
# from; location, attendees and the meeting link come along. The notes never leave the source,
# only the meeting link found in them.

# what icalBuddy prints, as Python reads it: the calendar line carries the section mark, and a carriage
# return inside the notes has become a line break, so the notes (and what follows them) run on below
CAL = "{name}:" + "@@calendar@@"
ICAL_RICH = (CAL.format(name="Team") + "\n"
             "2026-10-04 at 18:00 - 18:45\tWeekly\tlocation: Online meeting\t"
             "attendees: Ann Example, Bob Example\u2069\tnotes: ____\n"
             " Help <https://aka.ms/JoinTeamsMeeting>\n"
             " Join <https://teams.microsoft.com/l/meetup-join/19%3ameeting_x%40thread.v2/0?context=%7b%7d>\n"
             " Agenda:\n"
             " secret agenda ____\tuid: B2\n"
             + CAL.format(name="Family") + "\n"
             "2026-10-04 at 18:05 - 19:05\tSchool play\n"
             "\n"
             + CAL.format(name="Work") + "\n"
             "2026-10-04 at 09:00 - 09:30\tStandup\tlocation: Room 2\tuid: A1\n")


def _rich(tmp_path, out=ICAL_RICH, **section):
    root = bridge(tmp_path)
    run = FakeRun({("icalBuddy",): out})
    sec = {"kind": "calendar", "provider": "icalbuddy", "info_calendars": ["Family"], **section}
    return bf.collect(root, {"id": "p", "sections": [sec]}, ctx(root, run))["sections"][0], run


def test_icalbuddy_events_know_their_calendar_place_people_and_meeting_link(tmp_path):
    sec, run = _rich(tmp_path)
    assert sec["status"] == "ok", sec.get("reason")
    by = {i["title"]: i for i in sec["items"]}
    assert by["Standup"]["calendar"] == "Work" and by["Standup"]["location"] == "Room 2"
    weekly = by["Weekly"]
    assert weekly["calendar"] == "Team" and weekly["attendees"] == ["Ann Example", "Bob Example"]
    assert weekly["url"] == "https://teams.microsoft.com/l/meetup-join/19%3ameeting_x%40thread.v2/0?context=%7b%7d"
    assert "url" not in by["Standup"]                       # no meeting host, no link
    assert "secret agenda" not in json.dumps(sec["items"])  # the notes stay at the source
    assert by["School play"]["info"] is True and by["School play"]["calendar"] == "Family"
    assert [i["title"] for i in sec["items"]] == ["Standup", "Weekly", "School play"]   # by time, not by calendar
    call = run.calls[0]
    assert len(run.calls) == 1 and "-sc" in call and "-uid" in call   # one call, info by the calendar's name
    assert call[call.index("-ss") + 1] == "@@calendar@@"
    assert "calendar" not in by["Weekly"].get("location", "") and "Agenda" not in json.dumps(sec["items"])


def test_calendar_rows_offer_prepare_and_the_steps_the_section_declares(tmp_path):
    steps = [{"id": "prepare", "label": "Prepare weekly", "match": "^weekly$", "prompt": "/cycle prepare {date}"},
             {"id": "followup", "label": "Follow up", "match": "weekly", "phase": "after", "prompt": "/cycle follow-up"}]
    sec, _ = _rich(tmp_path, event_steps=steps)
    offered = {i["title"]: [(a["id"], a["label"]) for a in i.get("actions") or []] for i in sec["items"]}
    assert offered["Weekly"] == [("prepare", "Prepare weekly")]    # the declared step stands in for the built-in one
    assert offered["Standup"] == [("prepare", "Prepare")]
    assert offered["School play"] == []                             # an info event is not the reader's to prepare


def test_a_step_after_the_event_is_offered_once_it_has_ended(tmp_path):
    out = CAL.format(name="Team") + "\n2026-10-04 at 07:00 - 07:30\tWeekly\n2026-10-04 at 18:00 - 18:45\tWeekly\n"
    steps = [{"id": "followup", "label": "Follow up", "match": "weekly", "phase": "after", "prompt": "x"}]
    sec, _ = _rich(tmp_path, out, event_steps=steps, prepare=False)
    assert [[a["id"] for a in i.get("actions") or []] for i in sec["items"]] == [["followup"], []]


def test_event_steps_are_checked():
    ok = {"kind": "calendar", "event_steps": [{"id": "prepare", "label": "Prepare", "match": "x", "prompt": "p"}]}
    assert bf._section_types(ok) == []
    for bad in ([{"id": "Bad", "label": "L", "match": "x", "prompt": "p"}],
                [{"id": "a", "label": "", "match": "x", "prompt": "p"}],
                [{"id": "a", "label": "L", "match": "(", "prompt": "p"}],
                [{"id": "a", "label": "L", "match": "x", "prompt": ""}],
                [{"id": "a", "label": "L", "match": "x", "prompt": "p", "phase": "during"}],
                [{"id": "a", "label": "L", "match": "x", "prompt": "p", "extra": 1}],
                "prepare"):
        assert bf._section_types({**ok, "event_steps": bad}), bad
    assert bf._section_types({**ok, "prepare": "no"})
    assert bf._section_types({"kind": "tasks", "event_steps": ok["event_steps"]})


def test_to_inbox_items_name_the_briefing_as_their_closer(tmp_path):
    # The briefing closes these items itself when the row is gone, so it is their closer. Without
    # one an item filed by a run looks hand-made: `add` would file it as `closer: person`, and a
    # watcher that investigates reporter findings before announcing them passes it on raw.
    root = bridge(tmp_path)
    section = {"kind": "tracker", "id": "gh", "provider": "github",
               "query": {"assignee": "@me", "kinds": ["issues"]},
               "to_inbox": [{"when": {"state": "blocked"}, "urgency": "now"}]}
    profile = {"id": "morning", "sections": [section]}
    box = inbox.Inbox(root / "work" / "inbox", actor="t", clock=lambda: NOW)
    bf.file_to_inbox(box, profile, bf.collect(root, profile, ctx(root, FakeRun(gh_answers()))))
    assert box.open_items()[0].closer == "reporter"


# ---------------------------------------------------------------- one matter, one line (29.10.)

def test_a_github_search_row_names_the_task_that_syncs_it_so_the_view_can_fold_it(tmp_path):
    # the `github` provider linked nothing by default, so its row of a task's issue stood beside the task's inbox line
    root = bridge(tmp_path)
    task(root, "fix-emoji", sync={"github": {"repo": "example-org/tool", "issues": [12]}})
    section = {"kind": "tracker", "provider": "github",
               "query": {"assignee": "@me", "owners": ["example-org"], "kinds": ["issues", "prs"]}}
    result = bf.collect(root, {"id": "p", "sections": [section]}, ctx(root, FakeRun(gh_answers())))
    items = {i["id"]: i for i in result["sections"][0]["items"]}
    assert items["example-org/tool#12"]["about_task"] == "fix-emoji"
    assert items["example-org/tool#12"]["task"] == "fix-emoji"
    assert bf.links_local({"provider": "github"}) and bf.links_local({"provider": "github-board"})
    assert not bf.links_local({"provider": "jira"}) and not bf.links_local({"provider": "github", "link": False})


def test_an_inbox_section_marks_an_item_that_waits_for_a_condition(tmp_path):
    root = bridge(tmp_path)
    box = inbox.Inbox(root / "work" / "inbox", actor="t", clock=lambda: NOW)
    waits = box.add(source="t", kind="result", summary="Quota raised", waits_for={"path_exists": str(tmp_path / "no")})
    plain = box.add(source="t", kind="decision", summary="Merge it?")
    box.approve(plain, when={"path_exists": str(tmp_path / "no")})          # a conditional yes is no wait for
    sec = bf.collect(root, {"id": "p", "sections": [{"kind": "inbox"}]}, ctx(root))["sections"][0]
    by = {i["id"]: i for i in sec["items"]}
    assert by[waits]["state"] == "waiting" and by[waits]["waits_for"] is True
    assert by[plain]["state"] == "waiting" and not by[plain].get("waits_for")
