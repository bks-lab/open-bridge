# SPDX-License-Identifier: MIT
"""Contract for the two overview parts of a briefing: commit activity and board summaries.

`kind: commits` counts commits per repository per day (the repositories registered in
the ecosystem files, or a list) and draws them as a sparkline, the "what moved this
week" a briefing showed before profiles. `summary: true` on a github-board section
adds one line per board with its cards per state, so a person sees the whole board
while their own cards still land in the view's buckets.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True


def _load(name: str, path: Path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


bf = _load("briefing", ROOT / "scripts" / "briefing.py")
bv = _load("briefing_view", ROOT / "scripts" / "lib" / "briefing_view.py")
NOW = dt.datetime(2026, 10, 5, 9, 0)
ANSI = re.compile(r"\x1b\[[0-9;]*m")


def bridge(tmp_path: Path, ecosystem: dict | None = None) -> Path:
    root = tmp_path / "bridge"
    (root / "work" / "inbox").mkdir(parents=True)
    (root / "work" / "tasks").mkdir(parents=True)
    (root / ".git").mkdir()
    if ecosystem is not None:
        (root / "ecosystem.yaml").write_text(yaml.safe_dump(ecosystem), encoding="utf-8")
    return root


def repo(path: Path) -> Path:
    (path / ".git").mkdir(parents=True)
    return path


class Git:
    """git log answers per repository path, as dates; records the calls."""

    def __init__(self, dates: dict, branch="main", email="me@example.com"):
        self.dates, self.branch, self.email, self.calls = dates, branch, email, []

    def __call__(self, argv, timeout=30, cwd=None):
        self.calls.append(list(argv))
        path = argv[2]
        if argv[3] == "log":
            return "\n".join(self.dates.get(path, [])) + "\n"
        if argv[3:6] == ["rev-parse", "--abbrev-ref", "HEAD"]:
            return self.branch + "\n"
        if argv[3:5] == ["config", "user.email"]:
            return self.email + "\n"
        raise bf.SourceError(f"unexpected {argv}")


def run_commits(root, section, git):
    c = bf.Context(root, now=NOW, run=git, cfg={})
    return bf.collect(root, {"id": "p", "sections": [section]}, c)["sections"][0]


# ---------------------------------------------------------------- commits

def test_commits_count_per_day_over_the_registered_repositories(tmp_path):
    a = repo(tmp_path / "code" / "alpha")
    repo(tmp_path / "code" / "quiet")
    root = bridge(tmp_path, {"local_root": str(tmp_path / "code"),
                             "base": {"alpha": {"github": "o/alpha"}, "quiet": {"github": "o/quiet"},
                                      "missing": {"github": "o/missing"}}})
    git = Git({str(a): ["2026-10-05", "2026-10-05", "2026-10-03", "2026-09-29"]})
    sec = run_commits(root, {"kind": "commits", "days": 7}, git)
    assert sec["status"] == "ok"
    [item] = sec["items"]                              # quiet and missing leave no row
    assert item["id"] == "alpha" and item["total"] == 4 and item["branch"] == "main"
    assert item["counts"] == [1, 0, 0, 0, 1, 0, 2]     # 29.09 .. 05.10, oldest first
    assert len(item["spark"]) == 7 and item["spark"][-1] == "█" and item["spark"][1] == "▁"


def test_commits_take_an_explicit_list_and_the_authors_filter(tmp_path):
    b = repo(tmp_path / "beta")
    root = bridge(tmp_path)
    git = Git({str(b): ["2026-10-04"]})
    sec = run_commits(root, {"kind": "commits", "repos": [str(b)], "author": "me", "all_branches": True}, git)
    assert sec["items"][0]["id"] == "beta"
    log = next(c for c in git.calls if c[3] == "log")
    assert "--author=me@example.com" in log and "--branches" in log


def test_a_repository_that_fails_is_skipped_not_the_section(tmp_path):
    good, bad = repo(tmp_path / "good"), repo(tmp_path / "bad")
    root = bridge(tmp_path)

    class Flaky(Git):
        def __call__(self, argv, timeout=30, cwd=None):
            if argv[2] == str(bad):
                raise bf.SourceError("not a git repository")
            return super().__call__(argv, timeout, cwd)

    sec = run_commits(root, {"kind": "commits", "repos": [str(bad), str(good)]},
                      Flaky({str(good): ["2026-10-05"]}))
    assert sec["status"] == "ok" and [i["id"] for i in sec["items"]] == ["good"]


def test_commits_are_validated(tmp_path):
    ok = {"schema_version": 1, "scope": "user", "id": "p",
          "sections": [{"kind": "commits", "days": 7, "repos": ["a"], "author": ["me", "x@y"],
                        "all_branches": True}]}
    assert bf.profile_problems(ok, "p") == []
    bad = {**ok, "sections": [{"kind": "commits", "repos": "a", "author": 3, "all_branches": "yes"}]}
    text = " | ".join(bf.profile_problems(bad, "p"))
    assert "repos" in text and "author" in text and "all_branches" in text


def test_sources_render_draws_the_sparkline():
    result = {"profile": "p", "title": "P", "sections": [
        {"id": "commits", "kind": "commits", "title": "Commits", "status": "ok", "total": 1, "items": [
            {"id": "alpha", "title": "alpha", "branch": "main", "spark": "▁▃█", "total": 4}]}]}
    assert "alpha" in bf.render(result) and "▁▃█" in bf.render(result) and "4" in bf.render(result)


# ---------------------------------------------------------------- views

def sec(sid, kind, items, **extra):
    return {"id": sid, "kind": kind, "title": sid, "status": "ok", "items": items, "all": items,
            "total": len(items), **extra}


def view_of(*sections, style="triage", labels=None):
    result = {"profile": "p", "title": "P", "collected_at": NOW.isoformat(timespec="minutes"),
              "sections": list(sections)}
    v = {"style": style}
    if labels:
        v["labels"] = labels
    return bv.build(result, {"id": "p", "sections": [{"kind": s["kind"], "id": s["id"]} for s in sections],
                             "view": v})


def test_triage_shows_activity_as_one_block_not_as_buckets():
    v = view_of(sec("commits", "commits", [{"id": "alpha", "title": "alpha", "branch": "main", "spark": "▁▃█",
                                            "total": 4, "counts": [0, 1, 3]}], days=3))
    assert v["buckets"] == []
    out = ANSI.sub("", bv.draw(v))
    assert "Activity (3 days)" in out and re.search(r"alpha\s+main\s+▁▃█\s+4 commits", out)


def test_brevity_leaves_activity_out():
    v = view_of(sec("commits", "commits", [{"id": "alpha", "title": "alpha", "branch": "main", "spark": "▁▃█",
                                            "total": 4}]), style="brevity")
    assert "alpha" not in bv.draw(v)


# ---------------------------------------------------------------- board summary

def board_payload():
    def card(n, status, assignee=None):
        return {"id": f"PVT_{n}", "status": status, "title": f"Card {n}", "assignees": [assignee] if assignee else [],
                "content": {"number": n, "repository": "o/infra", "type": "Issue", "title": f"Card {n}"}}
    return {"items": [card(1, "Todo", "me"), card(2, "Todo"), card(3, "In Progress"), card(4, "In Review"),
                      card(5, "Done")]}


def test_board_summary_counts_every_card_while_rows_stay_mine(tmp_path, monkeypatch):
    import json
    root = bridge(tmp_path, {"github_projects": [{"number": 26, "name": "Infra", "org": "o", "slug": "infra"}]})
    git_calls = []

    def run(argv, timeout=30, cwd=None):
        git_calls.append(argv)
        if argv[:3] == ["gh", "project", "item-list"]:
            return json.dumps(board_payload())
        raise bf.SourceError(f"unexpected {argv}")

    c = bf.Context(root, now=NOW, run=run, cfg={"integrations": {"github": {"assignee_me": "me"}}})
    section = {"kind": "tracker", "id": "boards", "provider": "github-board", "summary": True,
               "query": {"assigned_to_me": True}}
    s = bf.collect(root, {"id": "p", "sections": [section]}, c)["sections"][0]
    assert s["status"] == "ok", s.get("reason")
    assert [i["title"] for i in s["items"]] == ["Card 1"]
    [board] = s["summary"]
    assert board["name"] == "Infra" and board["open"] == 4
    assert sum(board["counts"].values()) == 4                       # done is not open work
    out = bf.render(bf._public(s and {"profile": "p", "title": "P", "sections": [s]}))
    assert "Infra" in out


def test_board_summary_is_one_line_per_board_in_the_view():
    s = sec("boards", "tracker", [], summary=[{"name": "Infra", "number": 26, "open": 4,
                                               "counts": {"new": 2, "in_progress": 1, "review": 1}}])
    out = ANSI.sub("", bv.draw(view_of(s, labels={"st_in_progress": "in Arbeit"})))
    assert re.search(r"Infra.*2 new.*1 in Arbeit.*1 review", out)
    assert bf.profile_problems({"schema_version": 1, "scope": "user", "id": "p", "sections": [
        {"kind": "tracker", "provider": "github-board", "summary": "yes"}]}, "p")


def test_a_board_without_open_cards_takes_no_line():
    s = sec("boards", "tracker", [], summary=[{"name": "Quiet", "number": 1, "open": 0, "counts": {}},
                                              {"name": "Busy", "number": 2, "open": 1, "counts": {"review": 1}}])
    out = ANSI.sub("", bv.draw(view_of(s)))
    assert "Busy" in out and "Quiet" not in out


# ---------------------------------------------------------------- findings of the independent review

def log_call(git):
    return next(c for c in git.calls if c[3] == "log")


def test_days_count_by_local_committer_date_and_branches_not_all_refs(tmp_path):
    b = repo(tmp_path / "beta")
    git = Git({str(b): ["2026-10-05"]})
    run_commits(bridge(tmp_path), {"kind": "commits", "repos": [str(b)], "all_branches": True}, git)
    argv = log_call(git)
    assert "--format=%cd" in argv and "--date=short-local" in argv
    assert "--branches" in argv and "--all" not in argv


def test_commits_need_at_least_one_day_and_the_title_follows_the_counts(tmp_path):
    p = {"schema_version": 1, "scope": "user", "id": "p", "sections": [{"kind": "commits", "days": 0}]}
    assert any("days" in x for x in bf.profile_problems(p, "p"))
    b = repo(tmp_path / "beta")
    s = run_commits(bridge(tmp_path), {"kind": "commits", "repos": [str(b)], "days": 3}, Git({str(b): ["2026-10-05"]}))
    assert s["days"] == 3 and len(s["items"][0]["counts"]) == 3


def test_repos_given_by_name_resolve_through_the_registry(tmp_path):
    w = repo(tmp_path / "code" / "wiki")
    root = bridge(tmp_path, {"local_root": str(tmp_path / "code"), "base": {"wiki": {"github": "o/wiki"}}})
    s = run_commits(root, {"kind": "commits", "repos": ["wiki"]}, Git({str(w): ["2026-10-05"]}))
    assert [i["id"] for i in s["items"]] == ["wiki"]


def test_two_repositories_with_one_basename_keep_distinct_ids(tmp_path):
    a, b = repo(tmp_path / "a" / "app"), repo(tmp_path / "b" / "app")
    s = run_commits(bridge(tmp_path), {"kind": "commits", "repos": [str(a), str(b)]},
                    Git({str(a): ["2026-10-05"], str(b): ["2026-10-05"]}))
    assert len({i["id"] for i in s["items"]}) == 2


def test_discovery_inherits_local_root_uses_the_github_name_and_expands_variables(tmp_path):
    code = tmp_path / "code"
    io = repo(code / "me.github.io")
    rel = repo(tmp_path / "bridge" / "rel" / "tool")
    var = repo(tmp_path / "proj" / "x")
    root = bridge(tmp_path, {"local_root": str(code)})
    (root / "ecosystem.personal.yaml").write_text(yaml.safe_dump({
        "personal": {"site": {"github": "me/me.github.io"},
                     "tool": {"github": "me/tool", "local_path": "rel/tool"},
                     "x": {"github": "me/x", "local_path": "${projects_root}/x"}}}), encoding="utf-8")
    (root / "bridge-config.yaml").write_text(yaml.safe_dump({"identity": {"projects_root": str(tmp_path / "proj")}}),
                                             encoding="utf-8")
    paths = {str(p) for _, p in bf._ecosystem_repos(root, bf.read_config(root))}
    assert str(io) in paths and str(rel) in paths and str(var) in paths


def test_a_repository_that_cannot_be_read_is_named_not_silently_dropped(tmp_path):
    good, bad = repo(tmp_path / "good"), repo(tmp_path / "bad")

    class Flaky(Git):
        def __call__(self, argv, timeout=30, cwd=None):
            if argv[2] == str(bad):
                raise bf.SourceError("no user.email")
            return super().__call__(argv, timeout, cwd)

    s = run_commits(bridge(tmp_path), {"kind": "commits", "repos": [str(bad), str(good)], "author": "me"},
                    Flaky({str(good): ["2026-10-05"]}))
    assert s["skipped"] == ["bad"]
    v = bv.build({"profile": "p", "collected_at": NOW.isoformat(), "sections": [s]},
                 {"id": "p", "sections": [{"kind": "commits"}], "view": {"style": "triage"}})
    assert any("bad" in h for h in v["hygiene"])


def test_the_section_time_limit_fails_the_section_instead_of_hiding_repositories(tmp_path):
    import time
    repos = [repo(tmp_path / f"r{n}") for n in range(3)]

    class Slow(Git):
        def __call__(self, argv, timeout=30, cwd=None):
            time.sleep(0.6)
            return super().__call__(argv, timeout, cwd)

    c = bf.Context(bridge(tmp_path), now=NOW, run=Slow({str(r): ["2026-10-05"] for r in repos}), cfg={})
    s = bf.collect(c.root, {"id": "p", "timeout_sec": 1,
                            "sections": [{"kind": "commits", "repos": [str(r) for r in repos]}]}, c)["sections"][0]
    assert s["status"] == "error" and "time limit" in s["reason"]


def test_board_counts_use_the_section_state_map_and_skip_unknown_states(tmp_path):
    import json
    root = bridge(tmp_path, {"github_projects": [{"number": 30, "name": "People", "org": "o"}]})

    def card(n, status):
        return {"id": f"P{n}", "status": status, "title": f"C{n}", "assignees": [],
                "content": {"number": n, "repository": "o/r", "type": "Issue", "title": f"C{n}"}}

    payload = {"items": [card(1, "QA"), card(2, "Parked"), card(3, "Todo")]}
    c = bf.Context(root, now=NOW, run=lambda argv, timeout=30, cwd=None: json.dumps(payload),
                   cfg={"integrations": {"github": {"assignee_me": "me"}}})
    sec_ = {"kind": "tracker", "id": "b", "provider": "github-board", "summary": True,
            "state_map": {"QA": "review"}}
    s = bf.collect(root, {"id": "p", "sections": [sec_]}, c)["sections"][0]
    [board] = s["summary"]
    assert board["counts"]["review"] == 1 and board["open"] == 2      # Parked is not counted as new


def test_board_summary_says_when_the_limit_cut_it(tmp_path):
    import json
    root = bridge(tmp_path, {"github_projects": [{"number": 1, "name": "Big", "org": "o"}]})
    items = [{"id": f"P{n}", "status": "Todo", "title": "t", "assignees": [],
              "content": {"number": n, "repository": "o/r", "type": "Issue", "title": "t"}} for n in range(3)]
    c = bf.Context(root, now=NOW, run=lambda argv, timeout=30, cwd=None: json.dumps({"items": items}), cfg={})
    s = bf.collect(root, {"id": "p", "sections": [{"kind": "tracker", "id": "b", "provider": "github-board",
                                                    "summary": True, "query": {"limit": 3}}]}, c)["sections"][0]
    assert s["summary"][0]["capped"] == 3
    out = ANSI.sub("", bv.draw(view_of(sec("b", "tracker", [], summary=s["summary"]))))
    assert "first 3 cards" in out


def test_overview_blocks_respect_width_sections_and_duplicates():
    row = {"id": "a-very-long-repository-name", "title": "x", "branch": "feature/very-long-branch",
           "spark": "▁" * 7, "total": 3, "counts": [0] * 7}
    s1 = sec("c7", "commits", [row], days=7)
    s2 = sec("c30", "commits", [{**row, "spark": "▁" * 30, "counts": [0] * 30}], days=30)
    board = {"name": "Infra", "number": 26, "org": "o", "open": 1, "counts": {"new": 1}}
    b1, b2 = sec("b1", "tracker", [], summary=[board]), sec("b2", "tracker", [], summary=[board])
    result = {"profile": "p", "collected_at": NOW.isoformat(), "sections": [s1, s2, b1, b2]}
    v = bv.build(result, {"id": "p", "sections": [{"kind": "commits", "id": "c7"}, {"kind": "commits", "id": "c30"},
                                                  {"kind": "tracker", "id": "b1"}, {"kind": "tracker", "id": "b2"}],
                          "view": {"style": "triage", "width": 50}})
    out = ANSI.sub("", bv.draw(v))
    assert "Activity (7 days)" in out and "Activity (30 days)" in out
    assert out.count("#26 Infra") == 1
    assert all(len(line) <= 50 for line in out.splitlines() if "▁▁▁▁▁▁▁" in line and len(line) and "▁" * 30 not in line)


# ---------------------------------------------------------------- where a row leads

class GitWithRemote(Git):
    def __init__(self, dates: dict, remote: str, **kw):
        super().__init__(dates, **kw)
        self.remote = remote
        self.upstream = f"origin/{self.branch}"

    def __call__(self, argv, timeout=30, cwd=None):
        if argv[3:6] == ["remote", "get-url", "origin"]:
            return self.remote + "\n"
        if argv[3:6] == ["rev-parse", "--abbrev-ref", "@{u}"]:
            if self.upstream is None:
                raise bf.SourceError("no upstream")
            return self.upstream + "\n"
        return super().__call__(argv, timeout, cwd)


def test_a_repository_on_a_web_host_links_to_its_commits(tmp_path):
    a = repo(tmp_path / "code" / "alpha")
    root = bridge(tmp_path, {"local_root": str(tmp_path / "code"), "base": {"alpha": {"github": "o/alpha"}}})
    for remote in ("git@github.com:o/alpha.git", "https://github.com/o/alpha.git", "https://token@github.com/o/alpha"):
        [item] = run_commits(root, {"kind": "commits"}, GitWithRemote({str(a): ["2026-10-05"]}, remote, branch="dev"))["items"]
        assert item["url"] == "https://github.com/o/alpha/commits/dev", remote


def test_a_repository_without_a_web_remote_has_no_link_and_still_counts(tmp_path):
    a = repo(tmp_path / "code" / "alpha")
    root = bridge(tmp_path, {"local_root": str(tmp_path / "code"), "base": {"alpha": {"github": "o/alpha"}}})
    [item] = run_commits(root, {"kind": "commits"}, Git({str(a): ["2026-10-05"]}))["items"]   # get-url fails
    assert "url" not in item and item["total"] == 1
    [item] = run_commits(root, {"kind": "commits"}, GitWithRemote({str(a): ["2026-10-05"]}, "/srv/git/alpha"))["items"]
    assert "url" not in item


def test_own_commits_of_a_range_as_times_per_repository_for_the_log_page(tmp_path):
    a, q = repo(tmp_path / "code" / "alpha"), repo(tmp_path / "code" / "quiet")
    root = bridge(tmp_path, {"local_root": str(tmp_path / "code"),
                             "base": {"alpha": {"github": "o/alpha"}, "quiet": {"github": "o/quiet"}}})
    git = GitWithRemote({str(a): ["1790003600", "1790000000", "not a time"]}, "git@github.com:o/alpha.git", branch="dev")
    c = bf.Context(root, now=NOW, run=git, cfg={})
    got = bf.commit_times({"kind": "commits", "author": "me", "all_branches": True}, c, "2026-10-01", "2026-10-05")
    # a repository without a commit in the range leaves no entry; the times oldest first, as epoch seconds
    assert got == {"repos": [{"repo": "alpha", "branch": "dev", "url": "https://github.com/o/alpha/commits/dev",
                              "ts": [1790000000, 1790003600]}], "skipped": []}
    log = next(call for call in git.calls if call[3] == "log" and call[2] == str(a))
    assert log[4:10] == ["--since", "2026-10-01 00:00", "--until", "2026-10-05 23:59:59", "--format=%ct", "--date=local"]
    assert "--author=me@example.com" in log and "--branches" in log
    assert not any(call[2] == str(q) and call[3] == "rev-parse" for call in git.calls)


def test_the_command_lists_own_commits_of_a_range_from_the_profiles_commits_section(tmp_path, monkeypatch, capsys):
    b = repo(tmp_path / "beta")
    root = bridge(tmp_path)
    (root / "workflow" / "briefings").mkdir(parents=True)
    (root / "workflow" / "briefings" / "day.yaml").write_text(yaml.safe_dump(
        {"schema_version": 1, "scope": "user", "id": "day", "default": True,
         "sections": [{"kind": "activity"}, {"id": "repos", "kind": "commits", "repos": [str(b)]}]}), encoding="utf-8")
    calls = []

    def fake(argv, timeout=30, cwd=None):
        calls.append(list(argv))
        if argv[3] == "log":
            return "1790000000\n"
        if argv[3:6] == ["rev-parse", "--abbrev-ref", "HEAD"]:
            return "main\n"
        raise bf.SourceError("no remote")

    monkeypatch.setattr(bf, "_default_run", fake)
    assert bf.main(["--root", str(root), "commits", "day", "--section", "repos", "--since", "2026-10-01",
                    "--until", "2026-10-05"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data == {"ok": True, "section": "repos", "repos": [{"repo": "beta", "branch": "main", "url": None,
                                                               "ts": [1790000000]}], "skipped": []}
    assert bf.main(["--root", str(root), "commits", "day", "--section", "nope", "--since", "2026-10-01",
                    "--until", "2026-10-05"]) == 2
    assert bf.main(["--root", str(root), "commits", "--since", "2026-10-05", "--until", "2026-10-01"]) == 2


def test_a_log_row_names_its_task_and_status_file_when_the_task_exists(tmp_path):
    root = bridge(tmp_path)
    (root / "work" / "tasks" / "alpha").mkdir()
    (root / "work" / "streams" / "beta").mkdir(parents=True)
    (root / "work" / "log.md").write_text(
        "| 2026-10-05 10:00 | ✨ | alpha | did a |\n| 2026-10-05 11:00 | ✨ | beta | did b |\n"
        "| 2026-10-05 12:00 | ✨ | some-repo | did c |\n", encoding="utf-8")
    c = bf.Context(root, now=NOW, cfg={})
    items = {i["project"]: i for i in bf.collect(root, {"id": "p", "sections": [{"kind": "activity"}]}, c)["sections"][0]["items"]}
    assert items["alpha"]["task"] == "alpha" and items["alpha"]["url"] == "work/tasks/alpha/STATUS.md"
    assert items["beta"]["url"] == "work/streams/beta/STATUS.md"
    assert "task" not in items["some-repo"]


def test_web_url_knows_ssh_aliases_and_ssh_urls():
    assert bf._web_url("git@github.com-work:acme/core.git") == "https://github.com/acme/core"
    assert bf._web_url("ssh://git@github.com/o/r.git") == "https://github.com/o/r"
    assert bf._web_url("/srv/git/r") is None


def test_a_branch_without_an_upstream_gets_no_link(tmp_path):
    a = repo(tmp_path / "code" / "alpha")
    root = bridge(tmp_path, {"local_root": str(tmp_path / "code"), "base": {"alpha": {"github": "o/alpha"}}})
    git = GitWithRemote({str(a): ["2026-10-05"]}, "git@github.com:o/alpha.git", branch="local-only")
    git.upstream = None
    [item] = run_commits(root, {"kind": "commits"}, git)["items"]
    assert "url" not in item


def test_a_log_context_that_is_no_task_name_gets_no_task(tmp_path):
    root = bridge(tmp_path)
    (root / "work" / "tasks" / "_meetings").mkdir()
    (root / "work" / "log.md").write_text("| 2026-10-05 10:00 | ✨ | _meetings | weekly |\n", encoding="utf-8")
    c = bf.Context(root, now=NOW, cfg={})
    [item] = bf.collect(root, {"id": "p", "sections": [{"kind": "activity"}]}, c)["sections"][0]["items"]
    assert "task" not in item
