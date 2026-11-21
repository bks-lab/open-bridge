# SPDX-License-Identifier: MIT
"""Contract for `task.py review`: cheap evidence, one batch call per tier, a cache, honest cost.

No network: git, gh and the model command are a fake runner that records every call.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("task_under_test", ROOT / "scripts" / "task.py")
task = importlib.util.module_from_spec(SPEC)
sys.dont_write_bytecode = True
SPEC.loader.exec_module(task)

NOW = dt.datetime(2026, 10, 9, 8, 0)
HAIKU, SONNET = "claude-haiku-5-5", "claude-sonnet-5-5"


def status(slug, extra="", body="", st="doing"):
    return (f"---\nslug: {slug}\nstatus: {st}\npriority: P2\ncreated: 2026-09-01\n"
            f"last_updated: 2026-09-20\n{extra}---\n\n# {slug.title()} work\n\n{body}")


def add(root, slug, extra="", body="", kind="tasks", st="doing"):
    d = root / "work" / kind / slug
    d.mkdir(parents=True, exist_ok=True)
    (d / "STATUS.md").write_text(status(slug, extra, body, st), encoding="utf-8")


@pytest.fixture()
def repo(tmp_path):
    (tmp_path / "work").mkdir()
    (tmp_path / "work" / "log.md").write_text(
        "## Wed 30.09\n\n| Timestamp | Glyph | Context | What |\n|---|---|---|---|\n"
        "| 2026-09-30 10:00 | 💻 | alpha | alpha: sent the draft for review |\n", encoding="utf-8")
    return tmp_path


class Done:
    def __init__(self, returncode=0, stdout="", stderr=""):
        self.returncode, self.stdout, self.stderr = returncode, stdout, stderr


class Fake:
    """git answers a commit date, gh the GraphQL fixture, the model command per --model."""

    def __init__(self, answers=None, gh=None, gh_fails=False, used=None, cost=0.001):
        self.calls, self.answers, self.gh, self.gh_fails = [], answers or {}, gh or {}, gh_fails
        self.used, self.cost = used or {}, cost

    def model_calls(self):
        return [(argv, stdin) for argv, stdin in self.calls if argv[0] == "claude"]

    def __call__(self, argv, input=None, timeout=None, cwd=None):
        argv = list(argv)
        self.calls.append((argv, input))
        if argv[0] == "git":
            return Done(0, "2026-09-30\n")
        if argv[0] == "gh":
            return Done(1, "", "gh: not logged in") if self.gh_fails else Done(0, json.dumps({"data": self.gh}))
        if argv[0] == "claude":
            model = argv[argv.index("--model") + 1]
            answer = self.answers.get(model)
            items = answer(input) if callable(answer) else answer or []
            text = "```json\n" + json.dumps(items) + "\n```"
            usage = {self.used.get(model, model): {"inputTokens": 100}}
            return Done(0, json.dumps({"result": text, "total_cost_usd": self.cost, "modelUsage": usage}))
        raise AssertionError(f"unexpected call {argv}")


def verdicts(slugs, verdict="continue", confidence="high"):
    return lambda prompt: [{"slug": s, "verdict": verdict, "reason": f"{s} evidence", "confidence": confidence}
                           for s in slugs if f"## {s}\n" in prompt]


def review(repo, fake, *args):
    return task.review(repo, list(args) or None, run=fake, now=NOW)


def test_one_model_call_for_all_tasks_that_need_a_verdict(repo):
    slugs = [f"t{i}" for i in range(5)]
    for s in slugs:
        add(repo, s)
    fake = Fake(answers={HAIKU: verdicts(slugs)})
    out = review(repo, fake)
    assert len(fake.model_calls()) == 1
    assert sorted(t["slug"] for t in out["tasks"]) == slugs
    assert {t["verdict"] for t in out["tasks"]} == {"continue"}
    assert {t["model"] for t in out["tasks"]} == {HAIKU}
    assert out["cost_usd"] == pytest.approx(0.001) and out["models_used"] == [HAIKU]
    assert out["model_mismatch"] == []
    # ONE gh call for every task's references, whatever their number
    assert len([c for c, _ in fake.calls if c[0] == "gh"]) <= 1


def test_the_real_case_the_model_sees_the_closed_issue(repo):
    add(repo, "alpha", extra=("blocked_by: \"waiting on F: review of example-org/x#49\"\n"
                             "sync:\n  bridge_only: false\n  github: {repo: example-org/x, issues: [49]}\n"))
    gh = {"r0": {"n49": {"__typename": "Issue", "state": "CLOSED", "stateReason": "COMPLETED",
                         "closedAt": "2026-10-03T09:00:00Z", "title": "Review the importer"}}}
    fake = Fake(answers={HAIKU: verdicts(["alpha"], "close")}, gh=gh)
    out = review(repo, fake)
    (argv, prompt), = fake.model_calls()
    assert "example-org/x#49" in prompt and "CLOSED" in prompt and "COMPLETED" in prompt
    assert "2026-10-03" in prompt and "waiting on F" in prompt
    query = next(c for c, _ in fake.calls if c[0] == "gh")
    assert "graphql" in query and any("x" in a and "49" in a for a in query)
    assert out["tasks"][0]["verdict"] == "close"
    assert "example-org/x#49" in out["tasks"][0]["evidence_summary"]


def test_gh_failing_marks_refs_unknown_and_the_review_still_runs(repo):
    add(repo, "alpha", extra="blocked_by: \"waiting on example-org/x#49\"\n")
    fake = Fake(answers={HAIKU: verdicts(["alpha"], "waiting")}, gh_fails=True)
    out = review(repo, fake)
    (_, prompt), = fake.model_calls()
    assert "example-org/x#49" in prompt and "unknown" in prompt
    assert out["tasks"][0]["verdict"] == "waiting"


def test_escalation_only_for_unclear_not_for_low_confidence(repo):
    for s in ("alpha", "beta", "gamma"):
        add(repo, s)

    def first(prompt):
        return [{"slug": "alpha", "verdict": "close", "reason": "all steps checked", "confidence": "high"},
                {"slug": "beta", "verdict": "unclear", "reason": "?", "confidence": "medium"},
                {"slug": "gamma", "verdict": "continue", "reason": "maybe", "confidence": "low"}]
    fake = Fake(answers={HAIKU: first, SONNET: verdicts(["beta", "gamma"], "stale", "medium")})
    out = review(repo, fake)
    calls = fake.model_calls()
    assert [argv[argv.index("--model") + 1] for argv, _ in calls] == [HAIKU, SONNET]
    second = calls[1][1]
    assert "## beta\n" in second and "## gamma\n" not in second and "## alpha\n" not in second
    by = {t["slug"]: t for t in out["tasks"]}
    assert by["alpha"]["model"] == HAIKU and by["alpha"]["verdict"] == "close"
    assert by["beta"]["model"] == SONNET and by["beta"]["verdict"] == "stale"
    assert by["gamma"]["model"] == HAIKU and by["gamma"]["confidence"] == "low"
    assert out["models_used"] == [HAIKU, SONNET] and out["cost_usd"] == pytest.approx(0.002)


def test_unchanged_evidence_comes_from_the_cache_without_a_model_call(repo):
    add(repo, "alpha")
    add(repo, "beta")
    fake = Fake(answers={HAIKU: verdicts(["alpha", "beta"])})
    review(repo, fake)
    assert len(fake.model_calls()) == 1
    assert (repo / ".bridge" / "task-review.json").is_file()
    again = Fake(answers={HAIKU: verdicts(["alpha", "beta"])})
    out = review(repo, again)
    assert again.model_calls() == []
    assert all(t["cached"] for t in out["tasks"]) and out["cost_usd"] == 0
    # one task changes: only that one goes to the model
    task.main(["--root", str(repo), "note", "beta", "the customer answered"])
    third = Fake(answers={HAIKU: verdicts(["alpha", "beta"])})
    out = review(repo, third)
    (_, prompt), = third.model_calls()
    assert "## beta\n" in prompt and "## alpha\n" not in prompt
    assert {t["slug"]: t["cached"] for t in out["tasks"]} == {"alpha": True, "beta": False}


def test_fresh_and_an_old_verdict_ask_again(repo):
    add(repo, "alpha")
    review(repo, Fake(answers={HAIKU: verdicts(["alpha"])}))
    fresh = Fake(answers={HAIKU: verdicts(["alpha"])})
    task.review(repo, None, run=fresh, now=NOW, fresh=True)
    assert len(fresh.model_calls()) == 1
    later = Fake(answers={HAIKU: verdicts(["alpha"])})
    task.review(repo, None, run=later, now=NOW + dt.timedelta(days=8))
    assert len(later.model_calls()) == 1


def test_a_model_mismatch_is_reported(repo):
    add(repo, "alpha")
    fake = Fake(answers={HAIKU: verdicts(["alpha"])}, used={HAIKU: "claude-haiku-4-5-20251001"})
    out = review(repo, fake)
    assert out["model_mismatch"] == [{"requested": HAIKU, "used": ["claude-haiku-4-5-20251001"]}]
    assert out["models_used"] == ["claude-haiku-4-5-20251001"]
    assert out["tasks"][0]["model"] == "claude-haiku-4-5-20251001"


def test_models_and_language_come_from_bridge_config(repo):
    add(repo, "alpha")
    (repo / "bridge-config.yaml").write_text(
        "language: {conversation: de}\nmodels: {mechanical: sonnet, directed: claude-opus-5-5}\n", encoding="utf-8")
    fake = Fake(answers={SONNET: verdicts(["alpha"], "unclear"), "claude-opus-5-5": verdicts(["alpha"])})
    review(repo, fake)
    calls = fake.model_calls()
    assert [argv[argv.index("--model") + 1] for argv, _ in calls] == [SONNET, "claude-opus-5-5"]
    assert "German" in calls[0][1]


def test_the_command_is_a_configurable_template(repo):
    add(repo, "alpha")
    (repo / "bridge-config.yaml").write_text(
        "work:\n  review:\n    command: \"claude --print --model {model} --flag x\"\n", encoding="utf-8")
    fake = Fake(answers={HAIKU: verdicts(["alpha"])})
    review(repo, fake)
    (argv, _), = fake.model_calls()
    assert argv == ["claude", "--print", "--model", HAIKU, "--flag", "x"]


def test_default_command_is_the_locked_down_claude_call(repo):
    add(repo, "alpha")
    fake = Fake(answers={HAIKU: verdicts(["alpha"])})
    review(repo, fake)
    (argv, _), = fake.model_calls()
    for flag in ("-p", "--output-format", "--no-session-persistence", "--strict-mcp-config"):
        assert flag in argv
    assert argv[argv.index("--setting-sources") + 1] == ""
    assert argv[argv.index("--tools") + 1] == "" and "--disallowedTools" not in argv


def test_review_never_changes_a_task_and_skips_done_and_streams(repo):
    add(repo, "alpha")
    add(repo, "river", kind="streams")
    before = (repo / "work/tasks/alpha/STATUS.md").read_bytes()
    out = review(repo, Fake(answers={HAIKU: verdicts(["alpha", "river"])}))
    assert [t["slug"] for t in out["tasks"]] == ["alpha"]
    assert (repo / "work/tasks/alpha/STATUS.md").read_bytes() == before
    assert not (repo / "work" / "board.md").exists()


def test_keep_dismisses_until_the_evidence_changes(repo):
    add(repo, "alpha")
    review(repo, Fake(answers={HAIKU: verdicts(["alpha"], "close")}))
    task.keep(repo, ["alpha"])
    out = review(repo, Fake())
    assert out["tasks"][0]["kept"] is True and out["tasks"][0]["cached"] is True
    task.main(["--root", str(repo), "note", "alpha", "new evidence"])
    fake = Fake(answers={HAIKU: verdicts(["alpha"], "close")})
    out = review(repo, fake)
    assert len(fake.model_calls()) == 1 and out["tasks"][0]["kept"] is False


def test_keep_shows_in_the_last_run_at_once(repo):
    add(repo, "alpha")
    add(repo, "beta")
    review(repo, Fake(answers={HAIKU: verdicts(["alpha", "beta"], "close")}))
    task.keep(repo, ["alpha"])
    last = json.loads((repo / ".bridge" / "task-review.json").read_text(encoding="utf-8"))["last"]
    assert {t["slug"]: t["kept"] for t in last["tasks"]} == {"alpha": True, "beta": False}


def test_a_task_the_model_does_not_answer_is_unclear_and_not_cached(repo):
    add(repo, "alpha")
    add(repo, "beta")
    out = review(repo, Fake(answers={HAIKU: verdicts(["alpha"]), SONNET: verdicts(["alpha"])}))
    by = {t["slug"]: t for t in out["tasks"]}
    assert by["beta"]["verdict"] == "unclear" and by["beta"]["model"] is None
    cache = json.loads((repo / ".bridge" / "task-review.json").read_text(encoding="utf-8"))
    assert "beta" not in cache["tasks"]


def test_named_slugs_only_and_unknown_slug_fails(repo):
    add(repo, "alpha")
    add(repo, "beta")
    fake = Fake(answers={HAIKU: verdicts(["alpha", "beta"])})
    out = review(repo, fake, "beta")
    assert [t["slug"] for t in out["tasks"]] == ["beta"]
    with pytest.raises(ValueError):
        review(repo, fake, "ghost")


def test_cli_json_output(repo, monkeypatch):
    add(repo, "alpha")
    fake = Fake(answers={HAIKU: verdicts(["alpha"])})
    monkeypatch.setattr(task, "default_run", fake)
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        assert task.main(["--root", str(repo), "review", "--all", "--json"]) == 0
    data = json.loads(buf.getvalue())
    assert set(data) >= {"tasks", "cost_usd", "models_used", "model_mismatch"}
    assert set(data["tasks"][0]) >= {"slug", "title", "verdict", "reason", "confidence", "model", "cached",
                                     "evidence_summary"}


def test_no_save_writes_nothing_at_all(repo):
    add(repo, "alpha")
    out = task.review(repo, None, run=Fake(answers={HAIKU: verdicts(["alpha"])}), now=NOW, save=False)
    assert out["tasks"][0]["verdict"] == "continue"
    assert not (repo / ".bridge").exists()


# ---------------------------------------------------------------- deterministic signals, scope, stale rule

# Modeled on a real task: the blocker named the issue, the issue was closed as completed, the open
# steps still read as if the person's answer had to be read. The task was in fact done.
FAITHFUL = (
    'type: refactor\n'
    'blocked_by: "waiting on F: review of the ten points in example-org/config#49"\n'
    'headline: "Follow-up to PR #47: F reviews and fixes the points in #49, then bring it back."\n'
    'sync:\n  bridge_only: false\n  github:\n    repo: example-org/config\n    issues: [49]\n'
)
FAITHFUL_BODY = (
    "## Open points\n"
    "- [ ] Read F's answer on #49, review the fix PR\n"
    "- [ ] Bring the changes back into the instance branch\n"
    "- [ ] After the fix PR is merged: close #49, board to Done, task to work/done/\n"
)
CLOSED_49 = {"r0": {"n49": {"__typename": "Issue", "state": "CLOSED", "stateReason": "COMPLETED",
                            "closedAt": "2026-10-03T11:13:00Z", "title": "Review points of PR 47"}}}


def test_the_faithful_case_carries_the_signals_first_and_the_close_rule(repo):
    add(repo, "worker-followup", extra=FAITHFUL, body=FAITHFUL_BODY)
    fake = Fake(answers={HAIKU: verdicts(["worker-followup"], "continue", "medium")}, gh=CLOSED_49)
    out = review(repo, fake)
    (_, prompt), = fake.model_calls()
    block = prompt[prompt.index("## worker-followup\n"):].splitlines()
    assert block[1] == "signals: own_refs_closed, blocker_resolved (example-org/config#49 closed 2026-10-03)"
    assert "When own_refs_closed holds, the verdict is close" in prompt and "blocker_resolved alone" in prompt
    t = out["tasks"][0]
    # the model said continue; the result still carries the signal, and it counts as one to close
    assert t["verdict"] == "continue"
    assert t["signals"] == {"own_refs_closed": True, "blocker_resolved": True,
                            "closed_refs": ["example-org/config#49 2026-10-03"]}
    assert t["resolved"] is True and out["to_close"] == 1


def test_signals_need_every_ref_closed_and_own_refs_closed_as_completed(repo):
    add(repo, "alpha", extra=('blocked_by: "waiting on #49"\n'
                              "sync:\n  bridge_only: false\n  github: {repo: example-org/x, issues: [49, 50]}\n"))
    gh = {"r0": {"n49": {"__typename": "Issue", "state": "CLOSED", "stateReason": "NOT_PLANNED",
                         "closedAt": "2026-10-01T00:00:00Z", "title": "a"},
                 "n50": {"__typename": "Issue", "state": "OPEN", "stateReason": None, "closedAt": None, "title": "b"}}}
    out = review(repo, Fake(answers={HAIKU: verdicts(["alpha"])}, gh=gh))
    sig = out["tasks"][0]["signals"]
    # a bare #49 in the blocker means the task's own repository; closed as not planned still resolves a blocker
    assert sig["blocker_resolved"] is True and sig["own_refs_closed"] is False
    # but a resolved blocker is a hint for the model, never a close by itself
    assert out["tasks"][0]["resolved"] is False and out["to_close"] == 0


def test_no_refs_no_signal(repo):
    add(repo, "alpha", extra='blocked_by: "waiting on the vendor"\n')
    out = review(repo, Fake(answers={HAIKU: verdicts(["alpha"])}))
    assert out["tasks"][0]["signals"] == {"own_refs_closed": False, "blocker_resolved": False, "closed_refs": []}
    assert out["tasks"][0]["resolved"] is False


def test_all_covers_doing_and_review_backlog_only_on_request(repo):
    add(repo, "alpha")
    add(repo, "beta", st="review")
    add(repo, "gamma", st="backlog")
    out = review(repo, Fake(answers={HAIKU: verdicts(["alpha", "beta", "gamma"])}))
    assert [t["slug"] for t in out["tasks"]] == ["alpha", "beta"]
    out = task.review(repo, None, run=Fake(answers={HAIKU: verdicts(["alpha", "beta", "gamma"])}), now=NOW,
                      backlog=True)
    assert [t["slug"] for t in out["tasks"]] == ["alpha", "beta", "gamma"]
    # a named backlog task is reviewed anyway
    assert [t["slug"] for t in review(repo, Fake(answers={HAIKU: verdicts(["gamma"])}), "gamma")["tasks"]] == ["gamma"]


def test_the_stale_threshold_is_a_rule_in_the_prompt(repo):
    add(repo, "alpha")
    fake = Fake(answers={HAIKU: verdicts(["alpha"])})
    review(repo, fake)
    assert "no activity for 21 days or more" in fake.model_calls()[0][1]
    (repo / "bridge-config.yaml").write_text("work:\n  review:\n    stale_days: 30\n", encoding="utf-8")
    fake = Fake(answers={HAIKU: verdicts(["alpha"])})
    task.review(repo, None, run=fake, now=NOW, fresh=True)
    assert "no activity for 30 days or more" in fake.model_calls()[0][1]



def test_a_closed_unmerged_pr_is_not_done(repo):
    add(repo, "alpha", extra="sync:\n  bridge_only: false\n  github: {repo: example-org/x, pull_requests: [5]}\n")
    gh = {"r0": {"n5": {"__typename": "PullRequest", "state": "CLOSED", "merged": False,
                        "closedAt": "2026-10-01T00:00:00Z", "title": "abandoned"}}}
    out = review(repo, Fake(answers={HAIKU: verdicts(["alpha"])}, gh=gh))
    assert out["tasks"][0]["signals"]["own_refs_closed"] is False and out["tasks"][0]["resolved"] is False


def test_the_cache_key_covers_language_models_stale_days_and_prompt_version(repo, monkeypatch):
    add(repo, "alpha")
    review(repo, Fake(answers={HAIKU: verdicts(["alpha"])}))
    for cfg in ("language: de\n", "models: {mechanical: sonnet}\n", "work:\n  review: {stale_days: 30}\n"):
        (repo / "bridge-config.yaml").write_text(cfg, encoding="utf-8")
        fake = Fake(answers={HAIKU: verdicts(["alpha"]), SONNET: verdicts(["alpha"])})
        review(repo, fake)
        assert len(fake.model_calls()) == 1, cfg
    fake = Fake(answers={HAIKU: verdicts(["alpha"])})
    review(repo, fake)
    assert fake.model_calls() == []              # same settings again: from the cache
    monkeypatch.setattr(task, "PROMPT_VERSION", task.PROMPT_VERSION + 1)
    fake = Fake(answers={HAIKU: verdicts(["alpha"])})
    review(repo, fake)
    assert len(fake.model_calls()) == 1


class FailingModel(Fake):
    def __call__(self, argv, input=None, timeout=None, cwd=None):
        if argv[0] == "claude":
            self.calls.append((list(argv), input))
            return Done(124, "", "timed out")
        return super().__call__(argv, input, timeout, cwd)


def test_a_failed_model_call_is_unknown_cost_not_zero(repo):
    add(repo, "alpha")
    out = review(repo, FailingModel())
    assert out["cost_known"] is False and out["tasks"][0]["verdict"] == "unclear"


def test_tier_two_gets_only_the_remaining_time_and_tier_one_is_saved_first(repo, monkeypatch):
    add(repo, "alpha")
    add(repo, "beta")
    clock = [0.0]
    monkeypatch.setattr(task, "_clock", lambda: clock[0])

    class Slow(Fake):
        def __call__(self, argv, input=None, timeout=None, cwd=None):
            if argv[0] == "claude":
                self.timeouts = getattr(self, "timeouts", []) + [timeout]
                if len(self.timeouts) == 2:
                    # the cache already holds the first tier's answers when the second runs
                    cache = json.loads((repo / ".bridge" / "task-review.json").read_text(encoding="utf-8"))
                    assert cache["tasks"]["alpha"]["verdict"] == "close"
                clock[0] += 150
            return super().__call__(argv, input, timeout, cwd)

    def first(prompt):
        return [{"slug": "alpha", "verdict": "close", "reason": "r", "confidence": "high"},
                {"slug": "beta", "verdict": "unclear", "reason": "?", "confidence": "low"}]
    fake = Slow(answers={HAIKU: first, SONNET: verdicts(["beta"], "stale")})
    review(repo, fake)
    assert fake.timeouts[0] <= task.REVIEW_BUDGET_SEC
    assert fake.timeouts[1] <= task.REVIEW_BUDGET_SEC - 150
    assert task.REVIEW_BUDGET_SEC <= 200          # the dashboard waits 240 s for the whole run


# ---------------------------------------------------------------- the overview's data

def test_each_task_carries_activity_age_priority_and_structured_evidence(repo):
    add(repo, "alpha", extra=FAITHFUL, body=FAITHFUL_BODY)
    inbox = task._module("inbox", task.ROOT / "scripts" / "inbox.py").Inbox(repo / "work" / "inbox", actor="test")
    inbox.add(source="test", kind="question", summary="does it ship?", task="alpha")
    out = review(repo, Fake(answers={HAIKU: verdicts(["alpha"], "close")}, gh=CLOSED_49))
    t = out["tasks"][0]
    # the log row of 2026-09-30 is the latest activity; NOW is 2026-10-09
    assert t["days_since_activity"] == 9 and t["priority"] == "P2" and t["status"] == "doing"
    assert t["chips"] == [
        {"kind": "ref", "ref": "example-org/config#49", "state": "closed", "date": "2026-10-03"},
        {"kind": "unblocked"},
        {"kind": "steps", "count": 3},
        {"kind": "inbox", "count": 1},
    ]


def test_an_open_blocker_and_an_open_ref_are_chips_too(repo):
    add(repo, "alpha", extra='blocked_by: "waiting on example-org/x#7"\n')
    gh = {"r0": {"n7": {"__typename": "PullRequest", "state": "MERGED", "merged": True,
                        "closedAt": "2026-10-02T00:00:00Z", "title": "t"}}}
    out = review(repo, Fake(answers={HAIKU: verdicts(["alpha"])}, gh=gh))
    assert out["tasks"][0]["chips"][0] == {"kind": "ref", "ref": "example-org/x#7", "state": "merged",
                                           "date": "2026-10-02"}
    add(repo, "beta", extra='blocked_by: "waiting on the vendor"\n')
    out = review(repo, Fake(answers={HAIKU: verdicts(["alpha", "beta"])}), "beta")
    assert out["tasks"][0]["chips"] == [{"kind": "blocked"}]


def test_previous_verdict_and_changed(repo):
    add(repo, "alpha")
    out = review(repo, Fake(answers={HAIKU: verdicts(["alpha"], "continue")}))
    assert out["tasks"][0]["previous_verdict"] is None and out["tasks"][0]["changed"] is False
    out = task.review(repo, None, run=Fake(answers={HAIKU: verdicts(["alpha"], "stale")}), now=NOW, fresh=True)
    assert out["tasks"][0]["previous_verdict"] == "continue" and out["tasks"][0]["changed"] is True
    # from the cache the change is still known
    out = review(repo, Fake())
    assert out["tasks"][0]["cached"] is True and out["tasks"][0]["changed"] is True


def test_the_run_is_kept_in_the_cache_for_the_overview(repo):
    add(repo, "alpha")
    add(repo, "beta")
    out = review(repo, Fake(answers={HAIKU: verdicts(["alpha", "beta"])}))
    assert out["reviewed_at"] == "2026-10-09T08:00:00" and isinstance(out["duration_sec"], (int, float))
    assert out["cost_by_model"] == {HAIKU: pytest.approx(0.001)}
    last = json.loads((repo / ".bridge" / "task-review.json").read_text(encoding="utf-8"))["last"]
    assert [t["slug"] for t in last["tasks"]] == ["alpha", "beta"] and last["cost_usd"] == pytest.approx(0.001)
    # a run for named slugs updates their rows in the last run and keeps the others
    task.review(repo, ["beta"], run=Fake(answers={SONNET: verdicts(["beta"], "stale")}), now=NOW, escalate=True)
    last = json.loads((repo / ".bridge" / "task-review.json").read_text(encoding="utf-8"))["last"]
    assert {t["slug"]: t["verdict"] for t in last["tasks"]} == {"alpha": "continue", "beta": "stale"}


def test_escalate_asks_the_directed_model_once_for_the_named_tasks_past_the_cache(repo):
    for s in ("alpha", "beta", "gamma"):
        add(repo, s)
    review(repo, Fake(answers={HAIKU: verdicts(["alpha", "beta", "gamma"])}))
    fake = Fake(answers={SONNET: verdicts(["alpha", "beta"], "stale", "high")})
    out = task.review(repo, ["alpha", "beta"], run=fake, now=NOW, escalate=True)
    calls = fake.model_calls()
    assert len(calls) == 1 and calls[0][0][calls[0][0].index("--model") + 1] == SONNET
    assert "## alpha\n" in calls[0][1] and "## beta\n" in calls[0][1] and "## gamma\n" not in calls[0][1]
    assert {t["slug"]: (t["verdict"], t["model"]) for t in out["tasks"]} == {
        "alpha": ("stale", SONNET), "beta": ("stale", SONNET)}


def test_escalate_needs_named_slugs_on_the_command_line(repo, capsys):
    add(repo, "alpha")
    assert task.main(["--root", str(repo), "review", "--all", "--escalate", "--json"]) == 1
    assert "escalate" in capsys.readouterr().err


def test_the_price_of_one_closer_look_is_measured_or_the_known_default(repo):
    add(repo, "alpha")
    out = review(repo, Fake(answers={HAIKU: verdicts(["alpha"])}))
    assert out["escalate_call_usd"] == pytest.approx(task.DIRECTED_CALL_USD)
    out = task.review(repo, ["alpha"], run=Fake(answers={SONNET: verdicts(["alpha"])}, cost=0.03), now=NOW,
                      escalate=True)
    assert out["escalate_call_usd"] == pytest.approx(0.03)


def test_a_task_that_runs_on_is_left_out_of_a_check_of_all_until_its_day(repo):
    add(repo, "alpha")
    add(repo, "waits", extra='blocked_by: "an answer from the vendor"\nquiet_until: 2026-10-20\n')
    slugs = [t["slug"] for t in task.gather(repo, None, Fake(), now_day=NOW.date())]
    assert slugs == ["alpha"]
    assert [t["slug"] for t in task.gather(repo, ["waits"], Fake(), now_day=NOW.date())] == ["waits"]   # named: checked
    assert {t["slug"] for t in task.gather(repo, None, Fake(), now_day=dt.date(2026, 10, 21))} == {"alpha", "waits"}


def test_keep_without_a_recommendation_keeps_the_task_with_a_dated_note(repo):
    # the briefing's "keep" on a resting task (Park or drop): no check has run, the task still stays, and its
    # last_updated moves to today, so the quiet row comes back only once it rests again (skills/briefing advise.py)
    add(repo, "alpha")
    add(repo, "beta")
    review(repo, Fake(answers={HAIKU: verdicts(["alpha"], "close")}), "alpha")
    out = task.keep(repo, ["alpha", "beta"], today="2026-10-09")
    assert out == {"kept": ["alpha", "beta"], "noted": ["beta"]}
    beta = (repo / "work" / "tasks" / "beta" / "STATUS.md").read_text(encoding="utf-8")
    assert "last_updated: 2026-10-09" in beta and "- 2026-10-09: Kept: stays open" in beta
    # a task with a recommendation is only dismissed: a note would change its evidence and undo the dismissal
    alpha = (repo / "work" / "tasks" / "alpha" / "STATUS.md").read_text(encoding="utf-8")
    assert "Kept" not in alpha
    cache = json.loads((repo / ".bridge" / "task-review.json").read_text(encoding="utf-8"))
    assert cache["tasks"]["alpha"]["kept"] is True and "beta" not in cache["tasks"]


def test_keep_of_an_unknown_task_still_fails(repo):
    with pytest.raises(ValueError):
        task.keep(repo, ["ghost"])
