# SPDX-License-Identifier: MIT
"""validate-status.py checks a STATUS.md `brief:` block through the gate (card_fields.validate_brief).

The schema's `$defs/Brief` is only real if CI reads it: a goal over its limit, an alias in `by` or a dash in
a text fails a task (work/tasks/) like a bad status does, and is a warning for a stream or a closed task.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location("validate_status", ROOT / "scripts" / "validate-status.py")
assert spec is not None and spec.loader is not None
vs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(vs)


def write(root: Path, rel: str, brief: str) -> None:
    path = root / rel / "STATUS.md"
    path.parent.mkdir(parents=True)
    path.write_text(f"---\nslug: x\nstatus: doing\n{brief}---\n\n# X\n", encoding="utf-8")


def run(monkeypatch, root: Path, capsys) -> tuple[int, str]:
    monkeypatch.setattr(vs, "ROOT", root)
    monkeypatch.setattr(sys, "argv", ["validate-status.py"])
    with pytest.raises(SystemExit) as end:
        vs.main()
    return end.value.code, capsys.readouterr().err


def test_a_good_brief_passes(tmp_path, monkeypatch, capsys):
    write(tmp_path, "work/tasks/a", "brief:\n  goal: Invoices reach the customer\n  by: claude-haiku-4-5-20251001\n")
    code, err = run(monkeypatch, tmp_path, capsys)
    assert code == 0 and "brief" not in err


def test_a_bad_brief_in_a_task_fails(tmp_path, monkeypatch, capsys):
    write(tmp_path, "work/tasks/a", f"brief:\n  goal: {'x' * 141}\n  by: haiku\n")
    code, err = run(monkeypatch, tmp_path, capsys)
    assert code == 1
    assert "work/tasks/a/STATUS.md: brief: goal: 141 characters" in err and "brief: by:" in err


def test_a_dash_in_a_brief_text_fails(tmp_path, monkeypatch, capsys):
    write(tmp_path, "work/tasks/a", "brief:\n  goal: Invoices — reach the customer\n")
    code, err = run(monkeypatch, tmp_path, capsys)
    assert code == 1 and "dash" in err


def test_a_bad_brief_in_a_stream_is_a_warning(tmp_path, monkeypatch, capsys):
    write(tmp_path, "work/streams/s", "brief: just a string\n")
    code, err = run(monkeypatch, tmp_path, capsys)
    assert code == 0 and "work/streams/s/STATUS.md: brief: brief: not a mapping" in err


def test_no_brief_is_fine(tmp_path, monkeypatch, capsys):
    write(tmp_path, "work/tasks/a", "")
    code, err = run(monkeypatch, tmp_path, capsys)
    assert code == 0 and "brief" not in err
