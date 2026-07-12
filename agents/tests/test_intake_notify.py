"""The CORE fixed-recipient intake+notify scaffold upholds its safety contract.

Locks ``agents/_template/tools/intake_notify.py`` against the contract formalized
in ``docs/representative-agent.md`` §4 "Fixed-recipient intake". Every assertion
maps to one clause of that contract. Hermetic: no network, no ``claude``
subprocess, no real transport — the ``send()`` seam is the only mock point. Env is
read at call time, so ``monkeypatch`` fully sandboxes each case.
"""
from __future__ import annotations

import ast
import json
import types

import pytest

from _runtime.config import AGENTS_DIR

_TOOL = AGENTS_DIR / "_template" / "tools" / "intake_notify.py"


def _load(monkeypatch, tmp_path, recipient=None):
    """Load the scaffold fresh with a sandboxed env. recipient=None → unconfigured.

    Loaded via ``compile``+``exec`` rather than an import, so no ``__pycache__``
    ``.pyc`` is written under ``_template`` (which would break the English-only /
    pathless guardrail that rglobs that dir as UTF-8 text)."""
    if recipient is None:
        monkeypatch.delenv("AGENT_NOTIFY_TO", raising=False)
    else:
        monkeypatch.setenv("AGENT_NOTIFY_TO", recipient)
    monkeypatch.setenv("AGENT_CAPTURE_DIR", str(tmp_path))
    monkeypatch.delenv("AGENT_NOTIFY_LOG", raising=False)
    mod = types.ModuleType("intake_notify")
    mod.__file__ = str(_TOOL)
    exec(compile(_TOOL.read_text("utf-8"), str(_TOOL), "exec"), mod.__dict__)
    return mod


def test_capture_only_when_unconfigured(monkeypatch, tmp_path):
    # Clause 2 + 4: durable capture first; unconfigured stays capture-only and loud.
    mod = _load(monkeypatch, tmp_path)  # no AGENT_NOTIFY_TO
    rc = mod.run(["--summary", "book a call", "--field", "contact=v@x.test"])
    assert rc == 0, "the turn must never fail on intake"
    rec = json.loads((tmp_path / "intake.jsonl").read_text("utf-8").strip())
    assert rec["summary"] == "book a call", "capture must be durable and happen first"
    audit = (tmp_path / "notify.log").read_text("utf-8")
    assert "WARN" in audit and "not configured" in audit, "unconfigured must be loud"


def test_no_recipient_flag_exists(monkeypatch, tmp_path):
    # Clause 1: fixed-recipient enforced by ABSENCE — there is no --to/--recipient flag.
    mod = _load(monkeypatch, tmp_path)
    with pytest.raises(SystemExit):  # argparse rejects the unknown flag
        mod.run(["--summary", "x", "--to", "evil@x.test"])


def test_recipient_comes_only_from_env(monkeypatch, tmp_path):
    # Clause 1: the recipient is resolved ONLY from AGENT_NOTIFY_TO.
    mod = _load(monkeypatch, tmp_path, recipient="owner@example.test")
    seen = {}
    monkeypatch.setattr(mod, "send", lambda s, b: seen.update(to=mod._recipients()))
    assert mod.notify("subj", "body", source="test") is True
    assert seen["to"] == ["owner@example.test"], "recipient must come from env only"
    # a visitor-controlled field can never become the recipient:
    mod.run(["--summary", "hi", "--field", "contact=attacker@x.test"])
    assert mod._recipients() == ["owner@example.test"]


def test_send_seam_raises_by_default(monkeypatch, tmp_path):
    # Clause 7: CORE ships the pattern, not the transport — send() raises by default.
    mod = _load(monkeypatch, tmp_path)
    with pytest.raises(NotImplementedError):
        mod.send("subj", "body")


def test_notify_never_raises_when_seam_unimplemented(monkeypatch, tmp_path):
    # Clause 3: notify() is best-effort — even a configured-but-unimplemented send
    # degrades to capture-only rather than crashing the turn.
    mod = _load(monkeypatch, tmp_path, recipient="owner@example.test")
    assert mod.notify("subj", "body", source="test") is False  # swallowed, no raise
    assert "WARN" in (tmp_path / "notify.log").read_text("utf-8")


def test_audit_log_is_pii_free(monkeypatch, tmp_path):
    # Clause 5: the audit log never carries visitor text or the recipient address.
    mod = _load(monkeypatch, tmp_path)
    mod.run(["--summary", "meet me", "--field", "contact=secret@visitor.test"])
    audit = (tmp_path / "notify.log").read_text("utf-8")
    assert "secret@visitor.test" not in audit and "meet me" not in audit


def test_notify_success_logs_info(monkeypatch, tmp_path):
    mod = _load(monkeypatch, tmp_path, recipient="owner@example.test")
    monkeypatch.setattr(mod, "send", lambda s, b: None)  # transport succeeds
    assert mod.notify("subj", "body", source="test") is True
    assert "INFO" in (tmp_path / "notify.log").read_text("utf-8")


def test_scaffold_is_stdlib_only():
    # Clause 7 corollary: the CORE scaffold pulls no provider SDK — stdlib only.
    tree = ast.parse(_TOOL.read_text("utf-8"))
    roots = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            roots.add(node.module.split(".")[0])
    allowed = {"argparse", "json", "os", "sys", "datetime", "pathlib", "__future__"}
    assert roots <= allowed, f"scaffold must be stdlib-only, found extra: {sorted(roots - allowed)}"
