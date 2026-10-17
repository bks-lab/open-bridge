# SPDX-License-Identifier: MIT
"""scripts/briefing.py act: a row's own step, through the section that offered it.

A command section's row may name `actions: [{id, label}]`; the section's `actions_argv` says how one
runs. `act` asks the section again and runs a step only when that row still offers it; an undo token
(`restore:...`) a step returned goes straight to the command, which checks it itself."""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
if "briefing" in sys.modules:
    bf = sys.modules["briefing"]
else:
    spec = importlib.util.spec_from_file_location("briefing", ROOT / "scripts" / "briefing.py")
    assert spec is not None and spec.loader is not None
    bf = importlib.util.module_from_spec(spec)
    sys.modules["briefing"] = bf
    spec.loader.exec_module(bf)

ROWS = [{"id": "2026-10/a", "title": "A", "actions": [{"id": "followed_up", "label": "followed_up"}]},
        {"id": "2026-10/b", "title": "B"}]


def bridge(tmp: Path, argv_extra=None) -> Path:
    (tmp / "workflow" / "briefings").mkdir(parents=True)
    (tmp / "rows.py").write_text(f"import json; print(json.dumps({ROWS!r}))\n", encoding="utf-8")
    (tmp / "step.py").write_text("import json, sys\nprint(json.dumps({'ok': True, 'did': sys.argv[2], 'id': sys.argv[1],"
                                 " 'undo': 'restore:sent._._'}))\n", encoding="utf-8")
    actions_argv = argv_extra or [sys.executable, "step.py", "{id}", "{action}"]
    (tmp / "workflow" / "briefings" / "p.yaml").write_text(json.dumps({
        "id": "p", "title": "P", "sections": [{"kind": "command", "id": "apps", "argv": [sys.executable, "rows.py"],
                                               "actions_argv": actions_argv}]}), encoding="utf-8")
    return tmp


def run(root, *args, capsys):
    code = bf.main(["--root", str(root), "act", "p", *args])
    out = capsys.readouterr()
    return code, out.out, out.err


def test_a_step_the_row_offers_runs_and_its_result_comes_back(tmp_path, capsys):
    root = bridge(tmp_path)
    code, out, _ = run(root, "apps", "2026-10/a", "followed_up", capsys=capsys)
    assert code == 0 and json.loads(out) == {"ok": True, "did": "followed_up", "id": "2026-10/a", "undo": "restore:sent._._"}


def test_a_step_the_row_does_not_offer_is_refused_before_anything_runs(tmp_path, capsys):
    root = bridge(tmp_path)
    for row, action in (("2026-10/a", "turned_down"), ("2026-10/b", "followed_up"), ("2026-10/zz", "followed_up"),
                        ("2026-10/a", "followed_up; rm"), ("2026-10/a", "restore:../x")):
        code, out, err = run(root, "apps", row, action, capsys=capsys)
        assert code == 2 and out == "" and err, (row, action)


def test_an_undo_token_goes_to_the_command_even_when_the_row_is_gone(tmp_path, capsys):
    root = bridge(tmp_path)
    code, out, _ = run(root, "apps", "2026-10/gone", "restore:sent.2026-09-25._", capsys=capsys)
    assert code == 0 and json.loads(out)["did"] == "restore:sent.2026-09-25._"


def test_actions_argv_is_checked_like_argv_and_needs_whole_placeholders():
    ok = {"kind": "command", "id": "x", "argv": ["a"], "actions_argv": ["python3", "s.py", "{id}", "{action}"]}
    assert not [p for p in bf._section_types(ok)]
    for bad in (["python3", "s.py", "x{id}", "{action}"], ["python3", "s.py", "{id}"], "python3 s.py", []):
        problems = bf._section_types({**ok, "actions_argv": bad})
        assert problems, bad


# A calendar row's step runs nothing here: it comes back as an agent tab to start, with the prompt the
# section declares for it (or the built-in one for "prepare"), its placeholders filled from the event.

def calendar_bridge(tmp: Path, steps) -> tuple[Path, str]:
    day = dt.date.today() + dt.timedelta(days=1)
    (tmp / "workflow" / "briefings").mkdir(parents=True)
    (tmp / "cal.ics").write_text(
        "BEGIN:VCALENDAR\nX-WR-CALNAME:Team\nBEGIN:VEVENT\nSUMMARY:Weekly\n"
        f"DTSTART:{day:%Y%m%d}T180000\nDTEND:{day:%Y%m%d}T184500\nLOCATION:Room 2\n"
        "ATTENDEE;CN=Ann Example:mailto:ann@example.com\nEND:VEVENT\nEND:VCALENDAR\n", encoding="utf-8")
    (tmp / "workflow" / "briefings" / "p.yaml").write_text(json.dumps({
        "id": "p", "title": "P", "sections": [{"kind": "calendar", "id": "cal", "provider": "ics", "path": "cal.ics",
                                               "event_steps": steps}]}), encoding="utf-8")
    return tmp, f"{day.isoformat()}T18:00 Weekly"


def test_a_calendar_step_comes_back_as_a_tab_to_start_with_its_prompt(tmp_path, capsys):
    steps = [{"id": "prepare", "label": "Prepare weekly", "match": "^Weekly$", "prompt": "/cycle prepare {date} ({calendar})"}]
    root, row = calendar_bridge(tmp_path, steps)
    code, out, err = run(root, "cal", row, "prepare", capsys=capsys)
    assert code == 0, err
    data = json.loads(out)
    assert data["did"] == "Prepare weekly"
    assert data["launch"]["prompt"] == f"/cycle prepare {row[:10]} (Team)"
    assert data["launch"]["key"] == f"event:prepare:{row}"
    assert "Weekly" in data["launch"]["summary"]


def test_the_built_in_prepare_step_names_the_event_place_and_people(tmp_path, capsys):
    root, row = calendar_bridge(tmp_path, [])
    code, out, err = run(root, "cal", row, "prepare", capsys=capsys)
    assert code == 0, err
    prompt = json.loads(out)["launch"]["prompt"]
    for word in ("Weekly", "Team", "Room 2", "Ann Example"):
        assert word in prompt


def test_a_calendar_step_the_row_does_not_offer_is_refused(tmp_path, capsys):
    steps = [{"id": "followup", "label": "Follow up", "match": "Weekly", "phase": "after", "prompt": "x"}]
    root, row = calendar_bridge(tmp_path, steps)
    for action in ("followup", "other"):
        code, out, err = run(root, "cal", row, action, capsys=capsys)
        assert code == 2 and out == "" and err, action
