# SPDX-License-Identifier: MIT
"""Contract of skills/github-projects-manager/scripts/issue_transition.py: one GitHub issue to its board's review or
done state, the board from workflow/projects/, the governance of references/governance.md, every write read back.

The GitHub side is a small stateful fake: the GraphQL read answers from the boards' current statuses, `gh project
item-edit` changes them, `gh issue close` closes the issue, and every argv is kept in order."""
from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "skills" / "github-projects-manager" / "scripts" / "issue_transition.py"


def load():
    spec = importlib.util.spec_from_file_location("issue_transition", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


it = load()

BOARD_STRICT = """schema_version: 1
identity: {slug: ops, display_name: Ops}
project: {tracker: github, org: acme, number: 7}
governance:
  rules: [done_requires_review, done_only_by_user]
  review_states: ["👀 In Review"]
  done_states: ["✅ Done", "❌ Declined"]
"""
BOARD_PLAIN = """schema_version: 1
identity: {slug: plain, display_name: Plain}
project: {tracker: github, org: acme, number: 8}
board: {status_field: Workflow}
governance:
  done_states: ["Shipped"]
  review_comment_template: |
    Status changed to {{new_state}} on {{date}}.
"""


def bridge(tmp_path: Path, *boards: tuple[str, str]) -> Path:
    root = tmp_path / "bridge"
    (root / "workflow" / "projects").mkdir(parents=True)
    (root / "workflow" / "projects" / "_template.yaml").write_text("project: {tracker: github, org: x, number: 1}\n",
                                                                    encoding="utf-8")
    (root / "workflow" / "projects" / "ado.yaml").write_text("project: {tracker: ado, org: acme, number: 7}\n",
                                                              encoding="utf-8")
    for name, text in boards:
        (root / "workflow" / "projects" / f"{name}.yaml").write_text(text, encoding="utf-8")
    return root


class GitHub:
    """The issue acme/app#5 with its project items; statuses by (owner, number)"""

    def __init__(self, items: dict, kind: str = "Issue", state: str = "OPEN", field: str = "Status"):
        self.items = dict(items)            # {("acme", 7): "🏗 In Progress"}
        self.fields = {k: field for k in items}
        self.kind = kind
        self.state = state
        self.calls: list[list[str]] = []
        self.bodies: list[str] = []
        self.fail_edit = False
        self.ignore_edit = False

    def node(self) -> dict:
        if self.kind == "PullRequest":
            return {"__typename": "PullRequest", "state": "OPEN", "url": "https://github.com/acme/app/pull/5", "title": "PR"}
        nodes = [{"project": {"number": n, "title": f"Board {n}", "owner": {"login": o}},
                  "fieldValues": {"nodes": [{}, {"name": s, "field": {"name": self.fields[(o, n)]}}]}}
                 for (o, n), s in self.items.items()]
        return {"__typename": "Issue", "state": self.state, "url": "https://github.com/acme/app/issues/5",
                "title": "Ship it", "projectItems": {"nodes": nodes}}

    def __call__(self, argv: list[str], timeout: float = 60, input: str | None = None):
        self.calls.append(list(argv))
        out = ""
        if argv[:3] == ["gh", "api", "graphql"]:
            out = json.dumps({"data": {"repository": {"issueOrPullRequest": self.node()}}})
        elif argv[:3] == ["gh", "issue", "comment"]:
            self.bodies.append(input or "")
            out = "https://github.com/acme/app/issues/5#issuecomment-1\n"
        elif argv[:3] == ["gh", "project", "item-edit"]:
            if self.fail_edit:
                return subprocess.CompletedProcess(argv, 1, "", "GraphQL: field not found")
            key = (argv[argv.index("--owner") + 1], int(argv[3]))
            assert argv[argv.index("--field") + 1] == self.fields[key], "the board's own status field"
            if not self.ignore_edit:
                self.items[key] = argv[argv.index("--value") + 1]
        elif argv[:3] == ["gh", "issue", "close"]:
            self.state = "CLOSED"
        return subprocess.CompletedProcess(argv, 0, out, "")

    def writes(self) -> list[str]:
        """The writes in order, in words: comment, status <owner>/<n> <value>, close"""
        out = []
        for c in self.calls:
            if c[:3] == ["gh", "issue", "comment"]:
                out.append("comment")
            elif c[:3] == ["gh", "project", "item-edit"]:
                out.append(f"status {c[c.index('--owner') + 1]}/{c[3]} {c[c.index('--value') + 1]}")
            elif c[:3] == ["gh", "issue", "close"]:
                out.append("close")
        return out


REF = "acme/app#5"
TODAY = "2026-10-29"


def test_boards_come_from_workflow_projects_github_only_without_reserved_files(tmp_path):
    root = bridge(tmp_path, ("ops", BOARD_STRICT), ("plain", BOARD_PLAIN))
    boards = {b["slug"]: b for b in it.load_boards(root)}
    assert sorted(boards) == ["ops", "plain"]
    want = {"owner": "acme", "number": 7, "status_field": "Status", "review_states": ["👀 In Review"],
            "done_states": ["✅ Done", "❌ Declined"], "rules": ["done_requires_review", "done_only_by_user"], "title": "Ops"}
    assert {k: boards["ops"][k] for k in want} == want
    assert boards["plain"]["status_field"] == "Workflow" and boards["plain"]["review_states"] == []


def test_plan_names_the_matching_boards_their_status_and_rules_and_writes_nothing(tmp_path):
    root = bridge(tmp_path, ("ops", BOARD_STRICT))
    gh = GitHub({("acme", 7): "🏗 In Progress", ("other", 3): "Todo"})
    out = it.plan(root, REF, run=gh)
    assert out["ok"] and out["type"] == "issue" and out["state"] == "OPEN"
    assert [(b["slug"], b["status"], b["review_state"], b["done_state"], b["in_review"], b["in_done"]) for b in out["boards"]] == \
        [("ops", "🏗 In Progress", "👀 In Review", "✅ Done", False, False)]
    assert out["boards"][0]["rules"] == ["done_requires_review", "done_only_by_user"]
    assert out["unmatched"] == [{"owner": "other", "number": 3, "title": "Board 3"}]
    assert gh.writes() == []


def test_review_posts_the_review_comment_first_then_sets_the_review_state_and_reads_it_back(tmp_path):
    root = bridge(tmp_path, ("ops", BOARD_STRICT))
    gh = GitHub({("acme", 7): "🏗 In Progress"})
    out = it.transition(root, REF, "review", "Rollout verified on prod", run=gh, today=TODAY)
    assert out["ok"], out
    assert gh.writes() == ["comment", "status acme/7 👀 In Review"]
    assert "Rollout verified on prod" in gh.bodies[0] and "👀 In Review" in gh.bodies[0] and TODAY in gh.bodies[0]
    assert "—" not in gh.bodies[0] and "–" not in gh.bodies[0]
    assert out["boards"] == [{"slug": "ops", "from": "🏗 In Progress", "to": "👀 In Review", "now": "👀 In Review"}]
    assert out["closed"] is False


def test_review_on_an_item_already_in_review_writes_nothing(tmp_path):
    root = bridge(tmp_path, ("ops", BOARD_STRICT))
    gh = GitHub({("acme", 7): "👀 In Review"})
    out = it.transition(root, REF, "review", "x", run=gh, today=TODAY)
    assert out["ok"] and gh.writes() == []
    assert out["boards"][0]["now"] == "👀 In Review"


def test_done_passes_through_review_where_the_board_wants_it_then_done_then_the_issue_closes(tmp_path):
    root = bridge(tmp_path, ("ops", BOARD_STRICT))
    gh = GitHub({("acme", 7): "🏗 In Progress"})
    out = it.transition(root, REF, "done", "Accepted in the cockpit", run=gh, today=TODAY)
    assert out["ok"], out
    assert gh.writes() == ["comment", "status acme/7 👀 In Review", "status acme/7 ✅ Done", "close"]
    assert len(gh.bodies) == 1, "one comment covers the pass through review"
    assert "Accepted in the cockpit" in gh.bodies[0]
    assert out["closed"] is True and out["boards"][0]["now"] == "✅ Done"
    close = next(c for c in gh.calls if c[:3] == ["gh", "issue", "close"])
    assert close[3:] == ["5", "--repo", "acme/app", "--reason", "completed"]


def test_done_from_review_sets_done_and_closes_with_a_comment_only_when_there_is_text(tmp_path):
    root = bridge(tmp_path, ("ops", BOARD_STRICT))
    gh = GitHub({("acme", 7): "👀 In Review"})
    assert it.transition(root, REF, "done", "", run=gh, today=TODAY)["ok"]
    assert gh.writes() == ["status acme/7 ✅ Done", "close"]
    gh2 = GitHub({("acme", 7): "👀 In Review"})
    assert it.transition(root, REF, "done", "Looks good", run=gh2, today=TODAY)["ok"]
    assert gh2.writes() == ["comment", "status acme/7 ✅ Done", "close"]


def test_done_on_a_board_without_review_goes_straight_and_uses_its_template_and_status_field(tmp_path):
    root = bridge(tmp_path, ("plain", BOARD_PLAIN))
    gh = GitHub({("acme", 8): "Building"}, field="Workflow")
    out = it.transition(root, REF, "done", "Released", run=gh, today=TODAY)
    assert out["ok"], out
    assert gh.writes() == ["comment", "status acme/8 Shipped", "close"]
    assert gh.bodies[0].startswith(f"Status changed to Shipped on {TODAY}.")
    assert "Released" in gh.bodies[0], "a template without {{reason}} gets the text below it"


def test_refusals_write_nothing(tmp_path):
    root = bridge(tmp_path, ("ops", BOARD_STRICT), ("plain", BOARD_PLAIN))
    # on no board of workflow/projects
    gh = GitHub({("other", 3): "Todo"})
    out = it.transition(root, REF, "done", "", run=gh, today=TODAY)
    assert not out["ok"] and out["error"] == "no_board" and gh.writes() == []
    # a pull request is merged, not closed from here
    pr = GitHub({}, kind="PullRequest")
    out = it.transition(root, REF, "done", "", run=pr, today=TODAY)
    assert out["error"] == "not_an_issue" and pr.writes() == []
    # review on a board that has no review state
    plain = GitHub({("acme", 8): "Building"}, field="Workflow")
    out = it.transition(root, REF, "review", "", run=plain, today=TODAY)
    assert out["error"] == "no_review_state" and plain.writes() == []
    # an issue closed already
    closed = GitHub({("acme", 7): "✅ Done"}, state="CLOSED")
    out = it.transition(root, REF, "done", "", run=closed, today=TODAY)
    assert out["ok"] and closed.writes() == [], "nothing left to do"
    # not owner/repo#n
    with pytest.raises(ValueError):
        it.transition(root, "acme/app", "done", "", run=gh, today=TODAY)


def test_a_failed_write_stops_there_and_says_so_and_a_write_that_did_not_land_fails_the_readback(tmp_path):
    root = bridge(tmp_path, ("ops", BOARD_STRICT))
    gh = GitHub({("acme", 7): "👀 In Review"})
    gh.fail_edit = True
    out = it.transition(root, REF, "done", "", run=gh, today=TODAY)
    assert not out["ok"] and out["error"] == "write_failed" and "field not found" in out["detail"]
    assert "close" not in gh.writes(), "the issue stays open when its board could not follow"
    lost = GitHub({("acme", 7): "👀 In Review"})
    lost.ignore_edit = True
    out = it.transition(root, REF, "done", "", run=lost, today=TODAY)
    assert not out["ok"] and out["error"] == "readback"


def test_the_cli_prints_one_json_object_and_exits_by_outcome(tmp_path, capsys, monkeypatch):
    root = bridge(tmp_path, ("ops", BOARD_STRICT))
    gh = GitHub({("acme", 7): "🏗 In Progress"})
    monkeypatch.setattr(it, "default_run", gh)
    text = tmp_path / "text.md"
    text.write_text("Verified", encoding="utf-8")
    assert it.main(["--root", str(root), "review", REF, "--text-file", str(text)]) == 0
    assert json.loads(capsys.readouterr().out)["ok"] is True
    assert it.main(["--root", str(root), "plan", REF]) == 0
    assert json.loads(capsys.readouterr().out)["boards"][0]["in_review"] is True
    none = GitHub({})
    monkeypatch.setattr(it, "default_run", none)
    assert it.main(["--root", str(root), "done", REF]) == 1
    assert json.loads(capsys.readouterr().out)["error"] == "no_board"
