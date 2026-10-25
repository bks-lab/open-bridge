# SPDX-License-Identifier: MIT
"""Contract for the data line a card is built from: the brief, the headline, the next step and the checklist.

* `workplace.py tasks` carries, per task, its `brief:` block as a mapping (never flattened to a string), its
  `headline`, the `who` and `due` of its `next:`, and `progress` {done, total} counted from the `- [x]` and
  `- [ ]` lines of the body; `tasks --all` (and `collect_tasks(include_all=True)`) adds the backlog, the
  default stays doing and review so the day plan never sees a parked task;
* the cockpit's `parse_tasks` passes those fields through as they come;
* the task detail reads the brief outside the flat front keys, as a mapping;
* an inbox item takes its brief from its latest `describe` event, the way it takes its area from `area`.
"""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from lib.bridge_cockpit import details, model  # noqa: E402

wspec = importlib.util.spec_from_file_location("workplace_for_brief", ROOT / "scripts" / "workplace.py")
assert wspec is not None and wspec.loader is not None
wp = importlib.util.module_from_spec(wspec)
sys.dont_write_bytecode = True
wspec.loader.exec_module(wp)

ispec = importlib.util.spec_from_file_location("inbox", ROOT / "scripts" / "inbox.py")
assert ispec is not None and ispec.loader is not None
inbox = importlib.util.module_from_spec(ispec)
sys.modules["inbox"] = inbox
ispec.loader.exec_module(inbox)

TODAY = dt.date(2026, 10, 25)
NOW = dt.datetime(2026, 10, 25, 18, 0)
BRIEF = {"goal": "Invoices reach the customer without a manual resend",
         "story": {"as": "an accountant", "want": "every invoice delivered once", "so_that": "nobody chases it"},
         "acceptance": ["No invoice is delivered twice", "A rejection shows in the inbox"],
         "by": "claude-haiku-4-5-20251001", "at": dt.date(2026, 10, 25), "basis": "0123456789abcdef",
         "edited": False}


def write(root: Path, slug: str, front: dict, body: str = "", kind: str = "tasks") -> Path:
    d = root / "work" / kind / slug
    d.mkdir(parents=True)
    path = d / "STATUS.md"
    path.write_text("---\n" + yaml.safe_dump({"slug": slug, "status": "doing", "last_updated": "2026-10-24",
                                              **front}, sort_keys=False, allow_unicode=True)
                    + f"---\n\n# {slug.title()}\n\n{body}", encoding="utf-8")
    return path


@pytest.fixture()
def repo(tmp_path):
    write(tmp_path, "invoices", {"headline": "Resend loop for rejected invoices", "brief": BRIEF,
                                 "next": {"what": "Wire the retry", "who": "bridge", "due": dt.date(2026, 10, 27)}},
          "## Next Steps\n\n- [x] read the logs\n- [X] find the cause\n  - [ ] write the retry\n- [ ] deploy\n"
          "* [ ] not a dash item, still counted\n")
    write(tmp_path, "parked", {"status": "backlog"})
    write(tmp_path, "fleet", {"next": "Patch the router"}, kind="streams")
    write(tmp_path, "flat-brief", {"brief": "just a string"})
    return tmp_path


# ---------------------------------------------------------------- collect_tasks

def test_collect_tasks_keeps_doing_and_review_by_default(repo):
    assert {t["slug"] for t in wp.collect_tasks(repo)} == {"invoices", "fleet", "flat-brief"}


def test_collect_tasks_include_all_adds_the_backlog(repo):
    tasks = {t["slug"]: t for t in wp.collect_tasks(repo, include_all=True)}
    assert set(tasks) == {"invoices", "fleet", "flat-brief", "parked"}
    assert tasks["parked"]["status"] == "backlog"


def test_a_task_carries_its_brief_as_a_mapping_its_headline_and_progress(repo):
    t = {t["slug"]: t for t in wp.collect_tasks(repo)}["invoices"]
    assert t["brief"] == {**BRIEF, "at": "2026-10-25"}
    assert t["headline"] == "Resend loop for rejected invoices"
    assert t["progress"] == {"done": 2, "total": 5}


def test_a_brief_that_is_no_mapping_is_none_and_no_checklist_is_no_progress(repo):
    tasks = {t["slug"]: t for t in wp.collect_tasks(repo)}
    assert tasks["flat-brief"]["brief"] is None
    assert tasks["fleet"]["brief"] is None
    assert tasks["fleet"]["progress"] is None
    assert tasks["fleet"]["headline"] is None


def test_checkboxes_in_the_front_matter_do_not_count(tmp_path):
    write(tmp_path, "x", {"origin": "- [x] pasted into origin"}, "- [ ] one\n")
    assert wp.collect_tasks(tmp_path)[0]["progress"] == {"done": 0, "total": 1}



def test_checkboxes_in_a_code_fence_do_not_count(tmp_path):
    write(tmp_path, "x", {}, "- [x] real\n\n```markdown\n- [ ] an example\n- [x] another\n```\n\n"
                            "~~~\n- [ ] tilde fenced\n~~~\n- [ ] after the fence\n")
    assert wp.collect_tasks(tmp_path)[0]["progress"] == {"done": 1, "total": 2}


# ---------------------------------------------------------------- task_rows and the CLI

def test_task_rows_carry_brief_headline_next_who_due_and_progress(repo):
    rows = {r["slug"]: r for r in wp.task_rows(repo, {}, TODAY)}
    r = rows["invoices"]
    assert r["next"] == "Wire the retry"            # unchanged: the words
    assert (r["next_who"], r["next_due"]) == ("bridge", "2026-10-27")
    assert r["brief"]["goal"] == BRIEF["goal"] and r["brief"]["at"] == "2026-10-25"
    assert r["headline"] == "Resend loop for rejected invoices"
    assert r["progress"] == {"done": 2, "total": 5}
    assert (rows["fleet"]["next_who"], rows["fleet"]["next_due"]) == (None, None)
    assert "parked" not in rows


def test_tasks_json_is_plain_json_and_all_adds_the_backlog(repo, capsys):
    (repo / "bridge-config.yaml").write_text("workplace:\n  workspaces: []\n")
    assert wp.main(["--root", str(repo), "tasks", "--json"]) == 0
    assert "parked" not in {r["slug"] for r in json.loads(capsys.readouterr().out)}
    assert wp.main(["--root", str(repo), "tasks", "--json", "--all"]) == 0
    rows = {r["slug"]: r for r in json.loads(capsys.readouterr().out)}
    assert rows["parked"]["status"] == "backlog"
    assert rows["invoices"]["brief"]["story"]["as"] == "an accountant"


# ---------------------------------------------------------------- the cockpit's parse_tasks

def test_parse_tasks_passes_the_new_fields_through(repo):
    rows = model.parse_tasks(json.dumps(wp.task_rows(repo, {}, TODAY)))
    t = {r["slug"]: r for r in rows}["invoices"]
    assert t["brief"]["acceptance"] == BRIEF["acceptance"]
    assert t["headline"] == "Resend loop for rejected invoices"
    assert (t["next_who"], t["next_due"]) == ("bridge", "2026-10-27")
    assert t["progress"] == {"done": 2, "total": 5}
    assert t["next"] == "Wire the retry"


def test_parse_tasks_drops_a_malformed_brief_or_progress():
    rows = model.parse_tasks(json.dumps([{"slug": "a", "brief": "flat", "progress": {"done": "x", "total": 2}},
                                         {"slug": "b"}]))
    assert [(r["brief"], r["progress"], r["headline"], r["next_who"]) for r in rows] == [(None, None, None, None)] * 2


# ---------------------------------------------------------------- the task detail

def test_the_task_detail_carries_the_brief_as_a_mapping(repo):
    got = details.task_detail(repo, "invoices")
    assert got["brief"]["acceptance"] == BRIEF["acceptance"]
    assert got["brief"]["story"] == BRIEF["story"]
    assert got["brief"]["at"] == "2026-10-25"
    assert "brief" not in got["front"]
    assert details.task_detail(repo, "fleet")["brief"] is None
    assert details.task_detail(repo, "flat-brief")["brief"] is None


# ---------------------------------------------------------------- the inbox describe event

@pytest.fixture()
def box(tmp_path):
    return inbox.Inbox(tmp_path / "work" / "inbox", actor="laptop", clock=lambda: NOW)


def add(box):
    return box.add(source="cli", kind="finding", summary="the sink drips", closer="person")


def test_an_item_has_no_brief_until_described(box):
    item = box.get(add(box))
    assert item.brief is None
    assert item.as_dict()["brief"] is None


def test_the_latest_describe_event_is_the_brief(box):
    item_id = add(box)
    box.describe(item_id, {"goal": "Fix the sink", "by": "claude-haiku-4-5-20251001"})
    box.describe(item_id, {"goal": "Call the plumber", "acceptance": ["The sink is dry"], "edited": True}, by="michael")
    item = box.get(item_id)
    assert item.brief == {"goal": "Call the plumber", "acceptance": ["The sink is dry"], "edited": True}
    assert item.as_dict()["brief"] == item.brief
    assert item.events[-1].by == "michael"
    assert box.validate() == []


def test_an_empty_describe_takes_the_brief_back(box):
    item_id = add(box)
    box.describe(item_id, {"goal": "Fix the sink"})
    box.describe(item_id, None)
    assert box.get(item_id).brief is None


def test_describe_refuses_an_invalid_brief_and_writes_nothing(box):
    item_id = add(box)
    with pytest.raises(ValueError, match="goal"):
        box.describe(item_id, {"acceptance": ["x"]})
    with pytest.raises(ValueError, match="dash"):
        box.describe(item_id, {"goal": "Fix " + chr(0x2014) + " now"})
    assert box.get(item_id).events == []


def test_validate_reports_a_hand_edited_broken_describe_event(box):
    item_id = add(box)
    box.describe(item_id, {"goal": "Fix the sink"})
    path = next((box.root / item_id / "events").glob("*-describe.yaml"))
    data = yaml.safe_load(path.read_text())
    data["brief"]["goal"] = "x" * 200
    path.write_text(yaml.safe_dump(data))
    assert any("describe" in p and "goal" in p for p in box.validate())


def test_cli_describe_sets_and_clears(tmp_path, capsys):
    (tmp_path / "work" / "inbox").mkdir(parents=True)
    assert inbox.main(["--root", str(tmp_path), "add", "--from", "cli", "--kind", "idea", "--summary", "x"]) == 0
    item_id = capsys.readouterr().out.strip()
    brief = {"goal": "Try the idea", "acceptance": ["It runs once"]}
    assert inbox.main(["--root", str(tmp_path), "describe", item_id, "--brief-json", json.dumps(brief)]) == 0
    assert inbox.main(["--root", str(tmp_path), "list", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["brief"] == brief
    assert inbox.main(["--root", str(tmp_path), "describe", item_id, "--clear"]) == 0
    assert inbox.Inbox(tmp_path / "work" / "inbox", actor="t").get(item_id).brief is None
