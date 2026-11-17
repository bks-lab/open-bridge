#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Pytest suite for scripts/repo-rules.py.

CONTRACT, this file is the authoritative spec for that surface.

WHY THIS EXISTS. A Bridge that writes to a repository it does not own (an
issue, a PR, a commit, a label, a board move) follows its own habits unless it
reads that repository's working rules first. Reading AGENTS.md is not enough:
an AGENTS.md often names `docs/workflow.md` only in a folder table, and the
labels, the assignment model and the task-id scheme live there. Nine issues
were once created and redone for exactly that reason.

    THE CORE (pure, offline)

        discover(listing)            candidate files present in a listing,
                                     in CANDIDATES order
        extract_links(text, entry)   paths an entry file links or names that
                                     look like working rules (one hop)

    THE SEAM

        collect(source)              orchestrates discovery over a Source:
                                     list_dir, stat, read, labels
        RemoteSource(repo, ref, run) the GitHub source; `run` replaces `gh`

    EXIT CODES

        0 rule files found, 3 none found, 4 access error. An access error is
        never reported as "no rules": a repo the agent cannot read may still
        have rules, and saying otherwise licenses the habits this exists to stop.
"""

from __future__ import annotations

import base64
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "scripts" / "repo-rules.py"


def _load():
    spec = importlib.util.spec_from_file_location("repo_rules", CLI)
    module = importlib.util.module_from_spec(spec)
    sys.dont_write_bytecode = True
    spec.loader.exec_module(module)
    return module


rr = _load()


# ---------------------------------------------------------------- discovery


def test_discover_orders_by_candidates_not_by_listing():
    listing = {
        "docs/workflow.md": 10,
        "README.md": 5,
        "CONTRIBUTING.md": 7,
        "AGENTS.md": 3,
        ".github/ISSUE_TEMPLATE/bug.md": 2,
        ".github/pull_request_template.md": 4,
        "src/main.py": 1,
    }
    assert rr.discover(listing) == [
        "AGENTS.md",
        "CONTRIBUTING.md",
        "docs/workflow.md",
        ".github/ISSUE_TEMPLATE/bug.md",
        ".github/pull_request_template.md",
    ]


def test_discover_matches_case_insensitively_and_keeps_real_spelling():
    listing = {"docs/WORKFLOW-board.md": 1, ".github/PULL_REQUEST_TEMPLATE.md": 1}
    assert rr.discover(listing) == ["docs/WORKFLOW-board.md", ".github/PULL_REQUEST_TEMPLATE.md"]


def test_discover_ignores_lookalikes_outside_candidate_dirs():
    listing = {"src/docs/workflow.md": 1, "docs/sub/workflow.md": 1, "README.md": 1}
    assert rr.discover(listing) == []


def test_candidate_dirs_cover_every_pattern():
    assert set(rr.candidate_dirs()) == {"", ".github", "docs", ".github/ISSUE_TEMPLATE"}


# ---------------------------------------------------------------- links


def test_extract_links_finds_markdown_link_backtick_and_table_cell():
    text = (
        "See [the workflow](docs/workflow.md#labels) first.\n"
        "| Folder | Holds |\n|---|---|\n| `docs/` | `docs/process/release-process.md` |\n"
        "Plain mention: guides/conventions.md, and README.md.\n"
    )
    assert rr.extract_links(text, "AGENTS.md") == [
        "docs/workflow.md",
        "docs/process/release-process.md",
        "guides/conventions.md",
    ]


def test_extract_links_skips_urls_ci_workflows_and_escapes():
    text = (
        "[x](https://example.org/workflow.md) [y](../outside/workflow.md)\n"
        "`.github/workflows/ci.yml` `.github/workflows/process.md` [z](#workflow)\n"
    )
    assert rr.extract_links(text, "AGENTS.md") == []


def test_extract_links_resolves_relative_to_the_entry_file():
    assert rr.extract_links("[w](./workflow.md) [r](/docs/CONTRIBUTING.md)", "docs/AGENTS.md") == [
        "docs/workflow.md",
        "docs/CONTRIBUTING.md",
    ]


# ---------------------------------------------------------------- collect


class FakeSource:
    def __init__(self, files: dict[str, str], labels=None):
        self.files = files
        self._labels = labels
        self.reads: list[str] = []

    def list_dir(self, d):
        prefix = f"{d}/" if d else ""
        return {p: len(t) for p, t in self.files.items()
                if p.startswith(prefix) and "/" not in p[len(prefix):]}

    def stat(self, path):
        return len(self.files[path]) if path in self.files else None

    def read(self, path):
        self.reads.append(path)
        return self.files[path]

    def labels(self):
        return self._labels


def test_collect_follows_one_hop_from_agents_md():
    src = FakeSource({
        "AGENTS.md": "Folders: `handbook/team-process.md`, see also [c](CONTRIBUTING.md).",
        "CONTRIBUTING.md": "Read `handbook/deeper-conventions.md`.",
        "handbook/team-process.md": "Labels: `handbook/never-followed-workflow.md`",
        "handbook/deeper-conventions.md": "x",
        "handbook/never-followed-workflow.md": "x",
    })
    result = rr.collect(src)
    assert [f["path"] for f in result["files"]] == [
        "AGENTS.md", "CONTRIBUTING.md", "handbook/team-process.md"]
    assert result["files"][2]["via"] == "AGENTS.md"
    assert result["status"] == "found"


def test_collect_names_a_link_that_does_not_resolve():
    result = rr.collect(FakeSource({"AGENTS.md": "see `docs/missing-workflow.md`"}))
    assert result["dangling"] == ["docs/missing-workflow.md"]


def test_collect_bare_name_matching_a_found_file_is_not_dangling():
    # A folder table names `workflow.md` in the `docs/` row: that is docs/workflow.md.
    src = FakeSource({
        "CLAUDE.md": "| `docs/` | `workflow.md`, `release-process.md` |",
        "docs/workflow.md": "x",
    })
    result = rr.collect(src)
    assert [f["path"] for f in result["files"]] == ["CLAUDE.md", "docs/workflow.md"]
    assert result["dangling"] == ["release-process.md"]


def test_collect_path_with_a_folder_still_needs_that_folder():
    src = FakeSource({"AGENTS.md": "see `references/workflow.md`", "docs/workflow.md": "x"})
    assert rr.collect(src)["dangling"] == ["references/workflow.md"]


def test_collect_reports_none_with_labels_kept():
    result = rr.collect(FakeSource({"README.md": "hi"}, labels=[{"name": "bug", "description": ""}]))
    assert result["status"] == "none"
    assert result["files"] == []
    assert result["labels"] == [{"name": "bug", "description": ""}]


def test_collect_with_content_includes_text():
    result = rr.collect(FakeSource({"AGENTS.md": "rules"}), with_content=True)
    assert result["files"][0]["content"] == "rules"


# ---------------------------------------------------------------- remote seam


def _b64(text):
    return base64.b64encode(text.encode()).decode()


class FakeGh:
    """Answers `gh api <endpoint>` from a table; anything else is a 404."""

    def __init__(self, table, fail=None):
        self.table = table
        self.fail = fail
        self.calls: list[list[str]] = []

    def __call__(self, args):
        self.calls.append(args)
        if self.fail:
            return 1, "", self.fail
        assert args[0] == "api"
        endpoint = next(a for a in args[1:] if a.startswith("repos/")).split("?")[0]
        if endpoint in self.table:
            return 0, self.table[endpoint], ""
        return 1, "", "gh: Not Found (HTTP 404)"


def _remote_table():
    return {
        "repos/example-org/example-repo": json.dumps({"full_name": "example-org/example-repo"}),
        "repos/example-org/example-repo/contents": json.dumps([
            {"path": "AGENTS.md", "type": "file", "size": 40},
            {"path": "docs", "type": "dir", "size": 0},
        ]),
        "repos/example-org/example-repo/contents/docs": json.dumps([
            {"path": "docs/workflow.md", "type": "file", "size": 12},
        ]),
        "repos/example-org/example-repo/contents/AGENTS.md": json.dumps(
            {"path": "AGENTS.md", "type": "file", "size": 40, "content": _b64("see docs/workflow.md")}),
        "repos/example-org/example-repo/contents/docs/workflow.md": json.dumps(
            {"path": "docs/workflow.md", "type": "file", "size": 12, "content": _b64("labels: x")}),
        "repos/example-org/example-repo/labels": '{"name":"bug","description":"broken"}\n'
                                                  '{"name":"Let AI do this","description":null}\n',
    }


def test_remote_source_lists_reads_and_labels():
    gh = FakeGh(_remote_table())
    src = rr.RemoteSource("example-org/example-repo", ref=None, run=gh)
    result = rr.collect(src, with_content=True)
    assert [f["path"] for f in result["files"]] == ["AGENTS.md", "docs/workflow.md"]
    assert result["files"][1]["content"] == "labels: x"
    assert [lbl["name"] for lbl in result["labels"]] == ["bug", "Let AI do this"]


def test_remote_source_passes_ref():
    gh = FakeGh(_remote_table())
    src = rr.RemoteSource("example-org/example-repo", ref="dev", run=gh)
    rr.collect(src)
    contents_calls = [a for call in gh.calls for a in call if "/contents" in a]
    assert contents_calls and all("ref=dev" in a for a in contents_calls)


def test_remote_missing_repo_is_access_error_not_none():
    gh = FakeGh({})
    src = rr.RemoteSource("example-org/nope", ref=None, run=gh)
    with pytest.raises(rr.AccessError):
        rr.collect(src)


def test_remote_auth_failure_is_access_error():
    gh = FakeGh(_remote_table(), fail="HTTP 401: Bad credentials")
    with pytest.raises(rr.AccessError):
        rr.collect(rr.RemoteSource("example-org/example-repo", ref=None, run=gh))


def test_remote_dir_error_other_than_404_is_access_error():
    table = _remote_table()

    def run(args):
        if any(a.startswith("repos/example-org/example-repo/contents/docs") for a in args):
            return 1, "", "HTTP 403: rate limit exceeded"
        return FakeGh(table)(args)

    with pytest.raises(rr.AccessError):
        rr.collect(rr.RemoteSource("example-org/example-repo", ref=None, run=run))


# ---------------------------------------------------------------- CLI


def _cli(*args):
    return subprocess.run([sys.executable, "-B", str(CLI), *args],
                          capture_output=True, text=True, cwd=REPO_ROOT)


def test_cli_local_found_summary_and_print(tmp_path):
    (tmp_path / "AGENTS.md").write_text("Read `docs/workflow.md`.\n")
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "workflow.md").write_text("Labels: triage\n")
    out = _cli(str(tmp_path))
    assert out.returncode == 0, out.stderr
    assert "AGENTS.md" in out.stdout and "docs/workflow.md" in out.stdout
    printed = _cli(str(tmp_path), "--print")
    assert "Labels: triage" in printed.stdout


def test_cli_local_none_has_explicit_line_and_exit_3(tmp_path):
    (tmp_path / "README.md").write_text("hello\n")
    out = _cli(str(tmp_path))
    assert out.returncode == rr.EXIT_NONE == 3
    assert "no working rules found, Bridge defaults apply" in out.stdout


def test_cli_missing_path_is_access_error(tmp_path):
    out = _cli(str(tmp_path / "absent" / "dir"))
    assert out.returncode == rr.EXIT_ACCESS == 4
    assert "no working rules found" not in out.stdout


def test_cli_json_several_targets_worst_exit_wins(tmp_path):
    a = tmp_path / "a"
    b = tmp_path / "b"
    a.mkdir()
    b.mkdir()
    (a / "CONTRIBUTING.md").write_text("x")
    out = _cli(str(a), str(b), "--json")
    assert out.returncode == 3
    data = json.loads(out.stdout)
    assert [d["status"] for d in data] == ["found", "none"]
    assert data[0]["files"][0]["path"] == "CONTRIBUTING.md"


def test_cli_ref_with_local_path_is_usage_error(tmp_path):
    out = _cli(str(tmp_path), "--ref", "main")
    assert out.returncode == 2


def test_exit_code_aggregation():
    assert rr.aggregate_exit(["found", "found"]) == 0
    assert rr.aggregate_exit(["found", "none"]) == 3
    assert rr.aggregate_exit(["none", "error", "found"]) == 4
