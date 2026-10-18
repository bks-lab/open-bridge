# SPDX-License-Identifier: MIT
"""scripts/usage-export.py: the token use of this machine as one stamped file another cockpit reads over ssh.
The transcripts are a temporary folder; no remote is ever read."""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("usage_export", ROOT / "scripts" / "usage-export.py")
ue = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ue)


def test_export_writes_one_stamped_file_atomically_and_never_follows_remotes(tmp_path, monkeypatch, capsys):
    claude = tmp_path / "claude"
    proj = claude / "projects" / "p"
    proj.mkdir(parents=True)
    when = dt.datetime.now().astimezone(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")
    proj.joinpath("s.jsonl").write_text(json.dumps({
        "timestamp": when, "entrypoint": "cli", "cwd": "/w/alpha", "requestId": "r",
        "message": {"id": "m", "model": "claude-opus-5-5", "usage": {"input_tokens": 1, "output_tokens": 9}}}) + "\n")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude))
    root = tmp_path / "bridge"
    (root / "infra" / "instances").mkdir(parents=True)
    (root / "infra" / "instances" / "alpha.yaml").write_text("name: Alpha\nlocation: {path: /w/alpha}\n")
    (root / "bridge-config.yaml").write_text("cockpit:\n  usage:\n    remotes: [my-server]\n")
    called = []
    monkeypatch.setattr(ue.usage.subprocess, "run", lambda *a, **k: called.append(a))
    out = tmp_path / "out" / "usage.json"
    assert ue.main(["--out", str(out), "--root", str(root), "--host", "my-server", "--days", "30"]) == 0
    doc = json.loads(out.read_text())
    assert doc["schema"] == 1 and doc["kind"] == "usage-export" and doc["host"] == "my-server"
    assert doc["range"] == 30 and doc["total"]["output"] == 9
    assert doc["bridges"][0]["bridge"] == "Alpha" and doc["bridges"][0]["host"] == "my-server"
    assert [h["host"] for h in doc["hosts"]] == ["my-server"] and called == []
    assert not list(out.parent.glob(".*tmp"))
    assert "usage-export:" in capsys.readouterr().out
