# SPDX-License-Identifier: MIT
"""Contract for skills/briefing/scripts/meeting-obligations.py.

Which captured meeting of a declared series still owes a wiki protocol, answered
from the wiki itself and not from a hand-written `wiki.status:` field. The field
counts only as a deliberate opt-out (`n/a`, `skipped`); `done` is a claim and is
checked like any other. Series come from `workflow/meetings/<id>.yaml`.
"""
from __future__ import annotations

import datetime
import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "meeting_obligations", ROOT / "skills" / "briefing" / "scripts" / "meeting-obligations.py")
mo = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(mo)

TODAY = datetime.date.today()


def _day(offset: int) -> str:
    return (TODAY + datetime.timedelta(days=offset)).isoformat()


def _tree(tmp_path: Path, folders: dict[str, str | None]) -> Path:
    """A Bridge with one series whose wiki is a local directory.

    `folders` maps a meeting folder name to the summary frontmatter body, or None
    for a folder without a summary.
    """
    wiki = tmp_path / "wiki"
    (wiki / ".git").mkdir(parents=True)
    (wiki / "protocols").mkdir()
    series_dir = tmp_path / "workflow" / "meetings"
    series_dir.mkdir(parents=True)
    (series_dir / "weekly.yaml").write_text(
        "schema_version: 1\ntype: meeting-series\nscope: user\nid: weekly\n"
        "display_name: Weekly\n"
        "folder_match: '^(?P<date>\\d{4}-\\d{2}-\\d{2})-weekly(?:$|-)'\n"
        "outputs:\n  wiki:\n"
        f"    local_path: {wiki}\n    dir: protocols\n    file_pattern: '{{date}}-weekly.md'\n",
        encoding="utf-8")
    # The template is CORE and must never be read as a series.
    (series_dir / "_template.yaml").write_text("id: template\nfolder_pattern: '{date}'\n", encoding="utf-8")
    home = tmp_path / "work" / "tasks" / "_meetings"
    for name, fm in folders.items():
        (home / name).mkdir(parents=True)
        if fm is not None:
            (home / name / "summary.md").write_text(f"---\n{fm}\n---\n# Summary\n", encoding="utf-8")
    return wiki


def _states(tmp_path: Path) -> dict[str, str]:
    results, _ = mo.collect(tmp_path, {})
    return {r["folder"]: r["state"] for r in results}


def test_a_future_meeting_owes_nothing_yet(tmp_path):
    ahead, past = f"{_day(4)}-weekly", f"{_day(-1)}-weekly"
    _tree(tmp_path, {ahead: None, past: None})
    states = _states(tmp_path)
    assert states[ahead] == "upcoming"
    assert states[past] == "open"
    open_ones = [r["folder"] for r in mo.collect(tmp_path, {})[0] if r["state"] in mo.OPEN]
    assert ahead not in open_ones


def test_the_wiki_file_decides_not_the_field(tmp_path):
    written = f"{_day(-7)}-weekly"
    wiki = _tree(tmp_path, {written: "wiki:\n  status: pending"})
    (wiki / "protocols" / f"{_day(-7)}-weekly.md").write_text("# protocol\n", encoding="utf-8")
    assert _states(tmp_path)[written] == "done_frontmatter_stale"


def test_done_in_the_frontmatter_without_a_file_is_still_open(tmp_path):
    claimed = f"{_day(-3)}-weekly-extra"
    _tree(tmp_path, {claimed: "wiki:\n  status: done"})
    assert _states(tmp_path)[claimed] == "open_frontmatter_claims_done"


def test_an_explicit_opt_out_is_respected(tmp_path):
    skipped = f"{_day(-2)}-weekly"
    _tree(tmp_path, {skipped: "wiki:\n  status: n/a"})
    assert _states(tmp_path)[skipped] == "opted_out"


def test_a_folder_outside_every_series_counts_only_when_it_declares_pending(tmp_path):
    _tree(tmp_path, {f"{_day(-2)}-one-on-one": "wiki:\n  status: pending",
                     f"{_day(-2)}-other": None})
    states = _states(tmp_path)
    assert states == {f"{_day(-2)}-one-on-one": "open_without_series"}


def test_the_template_is_not_a_series(tmp_path):
    _tree(tmp_path, {})
    series, warnings = mo.load_series(tmp_path)
    assert list(series) == ["weekly"]
    assert warnings == []


def test_a_missing_wiki_clone_is_uncheckable_and_warned(tmp_path):
    _tree(tmp_path, {f"{_day(-1)}-weekly": None})
    path = tmp_path / "workflow" / "meetings" / "weekly.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace(str(tmp_path / "wiki"), str(tmp_path / "nowhere")),
                    encoding="utf-8")
    results, warnings = mo.collect(tmp_path, {})
    assert [r["state"] for r in results] == ["uncheckable"]
    assert any("weekly" in w for w in warnings)


def test_main_runs_without_a_bridge_config_and_exits_by_what_is_owed(tmp_path, capsys):
    _tree(tmp_path, {f"{_day(-1)}-weekly": None})
    assert mo.main(["--root", str(tmp_path), "--json"]) == 1
    data = json.loads(capsys.readouterr().out)
    assert [r["folder"] for r in data["open"]] == [f"{_day(-1)}-weekly"]


def test_nothing_owed_exits_zero(tmp_path, capsys):
    _tree(tmp_path, {})
    assert mo.main(["--root", str(tmp_path)]) == 0
    assert "nothing owed" in capsys.readouterr().out


def _rewrite_series(tmp_path: Path, old: str, new: str) -> None:
    path = tmp_path / "workflow" / "meetings" / "weekly.yaml"
    path.write_text(path.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")


def test_a_repo_without_an_org_never_joins_an_empty_name(tmp_path):
    """`repo: wiki` must find a clone named `wiki`, never an unrelated git folder."""
    _tree(tmp_path, {})
    base = tmp_path / "projects"
    (base / "other-repo" / ".git").mkdir(parents=True)
    series = {"outputs": {"wiki": {"repo": "wiki"}}}
    config = {"identity": {"projects_root": str(base)}}
    assert mo.wiki_root(series, config) is None
    (base / "someorg" / "wiki" / ".git").mkdir(parents=True)
    assert mo.wiki_root(series, config) == base / "someorg" / "wiki"


def _scoped_config() -> dict:
    return {"work": {"meetings": {"tracked_obligations": {
        "wiki_protocol": {"required_for_scopes": ["org"]}}}}}


def _context(tmp_path: Path, slug: str, scope: str) -> None:
    folder = tmp_path / "workflow" / "contexts"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{slug}.yaml").write_text(f"schema_version: 1\nscope: {scope}\n", encoding="utf-8")


def test_a_context_slug_is_resolved_to_its_scope(tmp_path):
    inside, outside = f"{_day(-2)}-weekly", f"{_day(-3)}-weekly"
    _tree(tmp_path, {inside: "context: acme", outside: "context: home"})
    _context(tmp_path, "acme", "org")
    _context(tmp_path, "home", "user")
    states = {r["folder"]: r["state"] for r in mo.collect(tmp_path, _scoped_config())[0]}
    assert states[inside] == "open"
    assert states[outside] == "out_of_scope"


def test_an_unresolvable_context_keeps_the_obligation(tmp_path):
    folder = f"{_day(-2)}-weekly"
    _tree(tmp_path, {folder: "context: unknown-slug"})
    states = {r["folder"]: r["state"] for r in mo.collect(tmp_path, _scoped_config())[0]}
    assert states[folder] == "open"


def test_an_explicit_scope_outside_the_set_opts_out(tmp_path):
    folder = f"{_day(-2)}-weekly"
    _tree(tmp_path, {folder: "scope: user"})
    states = {r["folder"]: r["state"] for r in mo.collect(tmp_path, _scoped_config())[0]}
    assert states[folder] == "out_of_scope"


def test_a_series_file_that_is_not_a_mapping_is_skipped_with_a_warning(tmp_path):
    _tree(tmp_path, {})
    (tmp_path / "workflow" / "meetings" / "broken.yaml").write_text("- a\n- b\n", encoding="utf-8")
    series, warnings = mo.load_series(tmp_path)
    assert list(series) == ["weekly"]
    assert any("broken.yaml" in w for w in warnings)


def test_an_invalid_folder_match_skips_only_that_series(tmp_path):
    folder = f"{_day(-1)}-weekly"
    _tree(tmp_path, {folder: None})
    (tmp_path / "workflow" / "meetings" / "bad.yaml").write_text(
        "id: bad\nfolder_match: '^(unclosed'\n", encoding="utf-8")
    results, warnings = mo.collect(tmp_path, {})
    assert {r["folder"]: r["state"] for r in results} == {folder: "open"}
    assert any("bad" in w for w in warnings)


def test_an_unknown_placeholder_in_file_pattern_is_uncheckable_not_a_crash(tmp_path):
    folder = f"{_day(-1)}-weekly"
    _tree(tmp_path, {folder: None})
    _rewrite_series(tmp_path, "'{date}-weekly.md'", "'{date}-{slug}.md'")
    results, warnings = mo.collect(tmp_path, {})
    assert [r["state"] for r in results] == ["uncheckable"]
    assert any("file_pattern" in w for w in warnings)
