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
