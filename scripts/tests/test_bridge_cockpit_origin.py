# SPDX-License-Identifier: MIT
"""Contract for where a work row comes from (scripts/lib/bridge_cockpit/origin.py, docs/bridge-cockpit.md
"Where a row comes from").

The classifier is pure: a free `from` text or a row plus the names a Bridge declares (`Known`) give one category
with a short detail, the raw text kept as written. The rules are shapes and lookups in the instance's own tree, never
names of one instance; the person's `cockpit.origin_map` comes first.

Run: pytest -q scripts/tests/test_bridge_cockpit_origin.py
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lib.bridge_cockpit import origin as o  # noqa: E402

ROOT = Path(__file__).resolve().parents[2]

KNOWN = o.Known(
    skills=frozenset({"briefing", "debrief", "notes-bot"}),
    runs=frozenset({"notes-bot", "nightly-report"}),
    hosts=frozenset({"homebox", "shared-name", "old-shared"}),
    scripts=frozenset({"cloud-costs", "archive-autorun", "briefing"}),
    work={"team-onboarding": "stream", "docs-refresh": "task", "old-cleanup": "done_task", "old-stream": "done_stream",
          "shared-name": "task", "old-shared": "done_task"},
)


def cat(raw, known=KNOWN):
    out = o.classify_from(raw, known)
    return out and (out["category"], out["detail"])


@pytest.mark.parametrize("raw, category, detail", [
    ("homebox/issue-radar", "bot", "issue-radar"),
    ("anyhost/nightly", "bot", "anyhost/nightly"),      # only a machine this Bridge knows is dropped
    ("agent-approval/axel", "bot", "agent-approval/axel"),
    ("claude-code", "session", "claude"),
    ("codex-cli", "session", "codex"),
    ("github", "github", None),
    ("GitHub", "github", None),
    ("acme/web#12", "github", "acme/web"),
    ("https://github.com/acme/web/issues/9", "github", "acme/web"),
    ("cloud-costs", "bot", "cloud-costs"),               # CORE's own filers (scripts/*.py) read as a bot
    ("archive-autorun", "bot", "archive-autorun"),
    ("deploy-notifier", "bot", "deploy-notifier"),       # a bot by its ending
    ("shared-name", "work", "shared-name"),              # an open task wins over a machine of the same name
    ("old-shared", "bot", "old-shared"),                 # a closed one does not
    ("laptop/session", "session", "laptop"),
    ("laptop/chat", "session", "laptop"),
    ("claude", "session", "claude"),
    ("codex", "session", "codex"),
    ("gemini", "session", "gemini"),
    ("claude-session", "session", "claude"),
    ("cockpit-session", "session", "cockpit"),
    ("tab:docs-refresh", "session", "docs-refresh"),
    ("tab-docs-refresh", "session", "docs-refresh"),
    ("chat", "other", "chat"),
    ("briefing/morning", "skill", "briefing/morning"),
    ("debrief", "skill", "debrief"),
    ("bridge/debrief", "skill", "debrief"),
    ("bridge/notify-x", "bot", "notify-x"),
    ("notes-bot", "bot", "notes-bot"),          # a declared run wins over a skill of the same name
    ("homebox", "bot", "homebox"),
    ("team-onboarding", "work", "team-onboarding"),
    ("docs-refresh", "work", "docs-refresh"),
    ("team-notes", "other", "team-notes"),
])
def test_a_from_text_gets_its_category_by_shape_and_by_what_the_bridge_declares(raw, category, detail):
    assert cat(raw) == (category, detail)


def test_a_ref_as_source_is_github_with_its_ref():
    out = o.classify_from("acme/web#12", KNOWN)
    assert out["ref"] == "acme/web#12"
    out = o.classify_from("https://github.com/acme/web/pull/7", KNOWN)
    assert out["category"] == "github" and out["ref"] == "acme/web#7"


def test_the_cockpit_and_no_source_at_all():
    out = o.classify_from("bridge-cockpit", KNOWN)
    assert out["category"] == "person" and out["via_cockpit"] is True and out["raw"] == "bridge-cockpit"
    assert o.classify_from("None", KNOWN) is None


def test_the_raw_text_stays_as_written_and_the_match_ignores_case():
    out = o.classify_from("HomeBox/Notify", KNOWN)
    assert out["category"] == "bot" and out["raw"] == "HomeBox/Notify" and out["detail"] == "Notify"
    assert o.classify_from("Claude", KNOWN)["category"] == "session"


def test_a_skill_needs_the_skill_folder_of_this_bridge():
    assert cat("debrief", o.Known()) == ("other", "debrief")
    assert cat("debrief", o.Known(skills=frozenset({"debrief"}))) == ("skill", "debrief")


@pytest.mark.parametrize("slug, kind", [("team-onboarding", "stream"), ("docs-refresh", "task"),
                                        ("old-cleanup", "done_task"), ("old-stream", "done_stream")])
def test_a_task_slug_as_source_names_the_work_kind(slug, kind):
    out = o.classify_from(slug, KNOWN)
    assert out["category"] == "work" and out["word_key"] == kind
    assert o.work_kind(slug, KNOWN) == kind


def test_the_persons_map_comes_first_exact_then_globs_and_a_wrong_category_is_ignored():
    known = o.Known(mapping=(("claude", "person"), ("*-health", "bot"), ("team-notes", "nonsense")))
    assert o.classify_from("claude", known)["category"] == "person"
    assert o.classify_from("homebox/daily-health", known)["category"] == "bot"
    assert o.classify_from("team-notes", known)["category"] == "other"
    assert o.classify_from("alex", o.Known(mapping=(("alex", "person"),)))["category"] == "person"


def test_a_long_detail_is_cut_and_nothing_gives_none():
    out = o.classify_from("x" * 80, KNOWN)
    assert out["category"] == "other" and len(out["detail"]) <= o.DETAIL_MAX and out["detail"].endswith("…")
    assert out["raw"] == "x" * 80
    assert o.classify_from(None, KNOWN) is None and o.classify_from("", KNOWN) is None and o.classify_from("  ", KNOWN) is None


def test_the_tracker_lists_are_the_briefings():
    text = (ROOT / "scripts" / "briefing.py").read_text(encoding="utf-8")
    trackers = re.search(r"^TRACKERS = (\(.*\))$", text, re.M).group(1)
    github = re.search(r"^GITHUB_TRACKERS = (\(.*\))$", text, re.M).group(1)
    assert eval(trackers) == o.TRACKERS and eval(github) == o.GITHUB_TRACKERS  # noqa: S307 - our own literal


# ---------------------------------------------------------------- one row

SECTIONS = {"gh": {"kind": "tracker", "provider": "github-board", "title": "GitHub"},
            "gl": {"kind": "tracker", "provider": "gitlab", "title": "GitLab"},
            "cal": {"kind": "calendar", "provider": "auto", "title": "Calendar"},
            "checks": {"kind": "command", "provider": None, "title": "Checks"},
            "apps": {"kind": "tracker", "provider": None, "title": "Applications"},
            "inbox": {"kind": "inbox", "provider": None, "title": "Inbox"}}
WITH = o.Known(skills=KNOWN.skills, runs=KNOWN.runs, hosts=KNOWN.hosts, work=KNOWN.work, sections=SECTIONS)


def inbox(**over):
    return {"inbox_id": "20261001-0900-x-ab12", "inbox_key": None, "origin_raw": None, "sources": ["inbox"], **over}


def test_an_inbox_row_names_who_filed_it_and_keeps_the_ref_of_its_key():
    out = o.classify_row(inbox(origin_raw="homebox/issue-radar", inbox_key="issue-radar:untasked:acme/web#12"), WITH)
    assert out["category"] == "bot" and out["detail"] == "issue-radar" and out["ref"] == "acme/web#12"
    assert out["via_cockpit"] is False


def test_a_row_the_cockpit_filed_takes_the_origin_of_the_section_it_came_from():
    out = o.classify_row(inbox(origin_raw="bridge-cockpit", inbox_key="briefing:p:gh:acme/web#4"), WITH)
    assert out["category"] == "github" and out["via_cockpit"] is True and out["ref"] == "acme/web#4"
    assert out["raw"] == "bridge-cockpit"
    out = o.classify_row(inbox(origin_raw="bridge-cockpit", inbox_key="briefing:p:cal:ev1"), WITH)
    assert out["category"] == "calendar" and out["via_cockpit"] is True
    out = o.classify_row(inbox(origin_raw="bridge-cockpit", inbox_key="web:x:y"), WITH)
    assert out["category"] == "person" and out["via_cockpit"] is True
    # a click on a board row files it as web:<row key>, the key of a board row being ref:<owner/repo#n>
    out = o.classify_row(inbox(origin_raw="bridge-cockpit", inbox_key="web:ref:org/repo#1"), WITH)
    assert out["category"] == "github" and out["via_cockpit"] is True and out["ref"] == "org/repo#1"
    out = o.classify_row(inbox(origin_raw="bridge-cockpit", inbox_key="web:ref:grp/app#2", origin_provider="gitlab"), WITH)
    assert out["category"] == "tracker" and out["word_key"] == "GitLab"


def test_an_inbox_row_without_a_source_is_a_neutral_other_unless_a_tab_filed_it():
    out = o.classify_row(inbox(inbox_key="demo-review"), WITH)
    assert out["category"] == "other" and out["detail"] is None and out["raw"] is None
    assert o.classify_row(inbox(origin_raw="None"), WITH)["category"] == "other"
    out = o.classify_row(inbox(inbox_key="tab-docs-refresh-20261001"), WITH)
    assert out["category"] == "session" and out["detail"] == "docs-refresh"


@pytest.mark.parametrize("row, category, extra", [
    ({"key": "item:gl:grp/app#3", "ref": "grp/app#3", "sources": ["gl"], "origin_provider": "gitlab"}, "tracker", {"word_key": "GitLab"}),
    ({"key": "item:x", "ref": None, "url": "https://github.com/acme/web/issues/9", "sources": ["mystery"]}, "github", {"detail": "acme/web"}),
    ({"key": "ref:acme/web#12", "ref": "acme/web#12", "sources": ["github"]}, "github", {"detail": "acme/web"}),
    ({"key": "clash:x", "sources": ["cal"]}, "calendar", {"detail": "Calendar"}),
    ({"key": "item:checks:b1", "ref": "b1", "sources": ["checks"]}, "bot", {"detail": "Checks"}),
    ({"key": "advise:wip:1", "sources": ["advise"], "task": "docs-refresh"}, "bridge", {}),
    ({"key": "item:apps:7", "ref": "7", "sources": ["apps"]}, "other", {"detail": "Applications"}),
])
def test_a_section_row_names_its_board_or_section(row, category, extra):
    out = o.classify_row(row, WITH)
    assert out["category"] == category, out
    for k, v in extra.items():
        assert out[k] == v, out


def test_a_gitlab_row_is_never_called_github_even_with_a_ref_that_looks_alike():
    out = o.classify_row({"key": "item:grp/app#3", "ref": "grp/app#3", "sources": ["gl"]}, WITH)
    assert out["category"] == "tracker" and out["word_key"] == "GitLab"


def test_a_task_row_names_how_its_task_began():
    origin = "inbox 2026-10-01-a (2026-10-01, homebox/probe): x"
    assert o.from_task_origin(origin) == "homebox/probe"
    out = o.classify_row({"key": "task:docs-refresh", "task": "docs-refresh", "origin_raw": origin}, WITH)
    assert out["category"] == "bot" and out["raw"] == origin
    out = o.classify_row({"key": "task:docs-refresh", "task": "docs-refresh", "origin_raw": "Ad-hoc 2026-10-01"}, WITH)
    assert out["category"] == "bridge" and out["raw"] == "Ad-hoc 2026-10-01"
    out = o.classify_row({"key": "task:docs-refresh", "task": "docs-refresh"}, WITH)
    assert out["category"] == "bridge" and out["raw"] is None
    out = o.classify_row({"key": "task:docs-refresh", "task": "docs-refresh", "origin_raw": "debrief 2026-10-01 weekly"}, WITH)
    assert out["category"] == "skill"
    out = o.classify_row({"key": "task:docs-refresh", "task": "docs-refresh", "origin_raw": "from acme/web#7"}, WITH)
    assert out["category"] == "github" and out["ref"] == "acme/web#7"


def test_a_task_origin_is_github_only_when_it_begins_there():
    row = lambda raw: o.classify_row({"key": "task:docs-refresh", "task": "docs-refresh", "origin_raw": raw}, WITH)
    out = row("https://github.com/acme/web/issues/4")
    assert out["category"] == "github" and out["detail"] == "acme/web" and out["ref"] == "acme/web#4"
    assert row("acme/web#9: flaky parser")["ref"] == "acme/web#9"
    # a PR merely mentioned in the middle is no origin on GitHub: the text is shown as written
    mid = "Follow-up of work/done/2026-09/old-cleanup (PR acme/web#191 merged 30.09.), open points"
    out = row(mid)
    assert out["category"] == "other" and out["raw"] == mid and out["ref"] is None


def test_a_written_task_origin_no_rule_knows_is_shown_as_written_not_as_bridge():
    out = o.classify_row({"key": "task:docs-refresh", "task": "docs-refresh", "origin_raw": "Call with Alex on 2026-10-01"}, WITH)
    assert out["category"] == "other" and out["detail"].startswith("Call with Alex") and out["raw"].startswith("Call")
    assert o.classify_row({"key": "task:a", "task": "a", "origin_raw": "Ad-hoc 2026-10-01"}, WITH)["category"] == "bridge"


def test_a_task_made_from_a_cockpit_filing_was_made_by_hand():
    out = o.classify_row({"key": "task:a", "task": "a", "origin_raw": "inbox 2026-10-01-a (2026-10-01, bridge-cockpit): x"},
                         o.Known(work={"bridge-cockpit": "done_task"}))
    assert out["category"] == "person" and out["via_cockpit"] is True
    out = o.classify_row({"key": "task:a", "task": "a", "origin_raw": "inbox 2026-10-01-a (2026-10-01, None): x"}, WITH)
    assert out["category"] == "other" and out["detail"] is None


def test_nothing_breaks_the_classifier():
    for bad in (None, 3, [], {"inbox_id": 5, "inbox_key": 7, "origin_raw": 9}, {"sources": None}):
        o.classify_row(bad, WITH)
    assert o.work_kind(None, WITH) is None and o.work_kind("../x", WITH) is None


# ---------------------------------------------------------------- the tree of a Bridge

def test_the_known_names_come_from_the_tree_of_the_bridge(tmp_path):
    (tmp_path / "skills" / "debrief").mkdir(parents=True)
    (tmp_path / "skills" / "debrief" / "SKILL.md").write_text("x")
    (tmp_path / "skills" / "loose").mkdir()
    for folder, name in (("workflow/workloads", "nightly-report"), ("workflow/workloads", "_template"),
                         ("infra/channels", "notes-bot"), ("infra/remotes", "homebox")):
        (tmp_path / folder).mkdir(parents=True, exist_ok=True)
        (tmp_path / folder / f"{name}.yaml").write_text("hostname: homebox-lan\n")
    (tmp_path / "agents" / "helper").mkdir(parents=True)
    (tmp_path / "agents" / "helper" / "agent.yaml").write_text("name: helper\n")
    (tmp_path / "agents" / "tests").mkdir()          # no agent.yaml: no agent
    (tmp_path / "agents" / "_template").mkdir()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "cloud-costs.py").write_text("")
    (tmp_path / "skills" / "debrief" / "scripts").mkdir()
    (tmp_path / "skills" / "debrief" / "scripts" / "debrief-scan.py").write_text("")
    (tmp_path / "infra" / "remotes" / "nested.yaml").write_text("hostname: nestbox\nservices:\n  - name: backup\n    user: debrief\n")
    for path, text in (("work/tasks/docs-refresh/STATUS.md", "---\nstatus: doing\n---\n"),
                       ("work/streams/team-onboarding/STATUS.md", "---\nstatus: doing\n---\n"),
                       ("work/done/2026-09/old-cleanup/STATUS.md", "---\nstatus: done\n---\n"),
                       ("work/done/2026-09/old-stream/STATUS.md", "---\nstatus: done\nwas_stream: true\n---\n"),
                       # task.py writes a comment line before the fence: the stream is still read as one
                       ("work/done/2026-10/commented-stream/STATUS.md",
                        "# yaml-language-server: $schema=../../templates/_schema.status.yaml\n---\nstatus: done\nwas_stream: true\n---\n")):
        (tmp_path / path).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / path).write_text(text)
    k = o.known_from_root(tmp_path, (("alex", "person"),), {"gh": {"kind": "tracker"}}, fresh=True)
    assert k.skills == {"debrief"}
    assert k.runs == {"nightly-report", "notes-bot", "helper"}
    assert {"cloud-costs", "debrief-scan"} <= k.scripts
    assert {"homebox", "homebox-lan", "nestbox"} <= k.hosts and not {"backup", "debrief"} & k.hosts
    assert dict(k.work) == {"docs-refresh": "task", "team-onboarding": "stream", "old-cleanup": "done_task",
                            "old-stream": "done_stream", "commented-stream": "done_stream"}
    assert k.mapping == (("alex", "person"),) and k.sections == {"gh": {"kind": "tracker"}}
    assert o.known_from_root(tmp_path / "missing", ()).skills == frozenset()


def test_the_front_reader_skips_a_leading_comment_line():
    head = "# yaml-language-server: $schema=x\n---\nstatus: done\nwas_stream: true\n---\n# Body\n"
    assert o.was_stream(head) is True
    assert o.was_stream("---\nstatus: done\n---\nwas_stream: true\n") is False     # in the body, not the front
    assert o.front_block("no front") == "" and o.was_stream(None) is False
