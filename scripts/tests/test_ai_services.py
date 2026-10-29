# SPDX-License-Identifier: MIT
"""Provider selection is per consumer, never a global CLI replacement."""
import importlib.util
import json
import re
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from lib import ai_services as ai

SID = "11111111-2222-3333-4444-555555555555"


def config(root, service="briefing-chat", provider="codex", models=None):
    folder = root / "workflow" / "ai-services"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{service}.yaml"
    path.write_text(yaml.safe_dump({"schema_version": 1, "scope": "user", "id": service,
                                    "provider": provider, "models": models or {}}))
    return path


def events(text="answer", *, sid=SID, completed=True):
    data = [{"type": "thread.started", "thread_id": sid},
            {"type": "item.completed", "item": {"id": "i1", "type": "agent_message", "text": text}}]
    if completed:
        data.append({"type": "turn.completed", "usage": {"input_tokens": 5, "output_tokens": 1}})
    return "\n".join(json.dumps(x) for x in data)


def test_defaults_and_independent_consumers(tmp_path):
    assert ai.select(tmp_path, "task-review", "sonnet").model == ai.CLAUDE_MODELS["sonnet"]
    config(tmp_path, models={"codex": "test-model"})
    assert ai.select(tmp_path, "briefing-chat").provider == "codex"
    assert ai.select(tmp_path, "briefing-chat").model == "test-model"
    assert ai.select(tmp_path, "task-review").provider == "claude"
    assert ai.select(tmp_path, "arbitrary-worker").provider == "claude"
    assert ai.select(tmp_path, "briefing-chat", provider="claude").model == ai.CLAUDE_MODELS["haiku"]


@pytest.mark.parametrize("change", [{"provider": "typo"}, {"id": "wrong"}, {"command": "sh"},
                                    {"models": {"codex": "--evil"}}, {"models": {"other": "m"}},
                                    {"models": []}, {"schema_version": True}])
def test_bad_config_never_silently_uses_claude(tmp_path, change):
    path = config(tmp_path)
    data = yaml.safe_load(path.read_text())
    path.write_text(yaml.safe_dump({**data, **change}))
    with pytest.raises(ValueError):
        ai.select(tmp_path, "briefing-chat")


def test_path_traversal_and_symlinks(tmp_path):
    for service in ("../x", "_template", "foo/bar", "", None):
        with pytest.raises(ValueError):
            ai.load(tmp_path, service)
    path = config(tmp_path)
    outside = tmp_path / "outside.yaml"
    path.rename(outside)
    path.symlink_to(outside)
    with pytest.raises(ValueError):
        ai.load(tmp_path, "briefing-chat")


def test_codex_parser_requires_completion_and_never_invents_dollars():
    assert ai.parse_codex(events(completed=False)) is None
    got = ai.parse_codex("diagnostic\n" + events())
    assert got["text"] == "answer" and got["session"] == SID and got["total_usd"] is None
    assert got["usage"]["input_tokens"] == 5
    failed = events(completed=False) + '\n{"type":"turn.failed","error":{"message":"limit"}}'
    assert ai.parse_codex(failed)["error"] is True
    assert ai.parse_codex(failed)["text"] == "limit"


def test_readonly_allowlist_on_start_and_resume():
    for session in (None, SID):
        args = ai.codex_argv("/bin/codex", "--dangerously-bypass-approvals-and-sandbox", "test", session)
        assert ai.codex_argv_ok(args, "/bin/codex")
        assert args[-2] == "--"
        assert "read-only" in args and 'approval_policy="never"' in args
        for index, value in enumerate(args[:-2]):
            if value in ("read-only", "--ignore-user-config", "--ignore-rules", "hooks", "apps"):
                bad = args.copy()
                bad[index] = "bad"
                assert not ai.codex_argv_ok(bad, "/bin/codex")
        assert not ai.codex_argv_ok(args[:-2] + ["--dangerously-bypass-approvals-and-sandbox"] + args[-2:], "/bin/codex")
    with pytest.raises(ValueError):
        ai.codex_argv("codex", "hi", session="--last")


def test_worker_cli_resolves_without_a_model_call(tmp_path):
    config(tmp_path, "night-worker", "codex", {"codex": "test-model"})
    p = subprocess.run([sys.executable, str(ROOT / "scripts/ai-run.py"), "--root", str(tmp_path),
                        "--service", "night-worker", "--show"], capture_output=True, text=True)
    assert p.returncode == 0, p.stderr
    assert json.loads(p.stdout) == {"service": "night-worker", "provider": "codex", "model": "test-model", "configured": True}


def test_review_provider_is_independent_and_normalizes_codex(tmp_path):
    spec = importlib.util.spec_from_file_location("ai_task_test", ROOT / "scripts/task.py")
    task = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(task)
    config(tmp_path, "task-review")
    calls = []
    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        return subprocess.CompletedProcess(argv, 0, events('[{"slug":"demo","verdict":"continue"}]'), "")
    result = task.ask_service(tmp_path, "task-review", task.DEFAULT_REVIEW_COMMAND, "codex-default", "prompt", run, 10)
    assert result["ok"] and result["items"][0]["slug"] == "demo" and result["cost"] is None
    assert calls[0][0][0] == "codex" and "shell_tool" in calls[0][0]
    assert "--model" not in calls[0][0]
    assert task.service_model(tmp_path, "triage", "sonnet") == ai.CLAUDE_MODELS["sonnet"]


def test_template_matches_schema():
    jsonschema = pytest.importorskip("jsonschema")
    folder = ROOT / "workflow/ai-services"
    jsonschema.validate(yaml.safe_load((folder / "_template.yaml").read_text()),
                        yaml.safe_load((folder / "_schema.yaml").read_text()))


# ---------------------------------------------------------------- the declared services and their providers

# a service id the code selects: SERVICE = "x" / X_SERVICE = "x", or a literal passed to select, service_model, ask_service
SELECTS = re.compile(r"""(?:\b[A-Z_]*SERVICE\s*=\s*|\b(?:select|service_model|ask_service)\(\s*[\w.]+\s*,\s*)"([a-z][a-z0-9-]*)\"""")


def selected_ids() -> dict:
    found = {}
    for path in sorted((ROOT / "scripts").rglob("*.py")):
        if "tests" in path.relative_to(ROOT).parts:
            continue
        for sid in SELECTS.findall(path.read_text(encoding="utf-8")):
            found.setdefault(sid, path.relative_to(ROOT).as_posix())
    return found


def test_every_service_id_the_code_selects_is_declared_and_no_declared_one_is_stale():
    found = selected_ids()
    assert {"briefing-chat", "task-review", "triage", "cockpit-prio"} <= set(found)   # the scan reaches them
    missing = sorted(set(found) - set(ai.SERVICES))
    assert not missing, f"selected in code but missing from ai_services.SERVICES: {[(s, found[s]) for s in missing]}"
    assert sorted(set(ai.SERVICES) - set(found)) == [], "declared in ai_services.SERVICES but selected nowhere"
    for sid, entry in ai.SERVICES.items():
        assert entry["providers"] and set(entry["providers"]) <= set(ai.PROVIDERS), sid
        assert "claude" in entry["providers"], sid          # Claude stays the compatibility default
        assert (ROOT / entry["code"]).is_file(), entry["code"]


def test_what_each_service_supports():
    assert ai.supports("briefing-chat", "codex") and ai.supports("task-review", "codex") and ai.supports("triage", "codex")
    assert ai.supports("cockpit-prio", "claude") and not ai.supports("cockpit-prio", "codex")
    assert ai.supports("night-worker", "codex")         # a worker's own id runs through ai-run.py on every provider


def test_a_provider_the_service_cannot_run_is_a_gap_not_a_silence(tmp_path):
    assert ai.gaps(tmp_path) == []
    config(tmp_path, "briefing-chat", "codex")
    config(tmp_path, "cockpit-describe", "claude")
    config(tmp_path, "night-worker", "codex")
    assert ai.gaps(tmp_path) == []
    config(tmp_path, "cockpit-prio", "codex")
    config(tmp_path, "cockpit-themes", "codex")
    assert ai.gaps(tmp_path) == [
        {"service": "cockpit-prio", "ready": False, "reason": "provider_unsupported", "provider": "codex",
         "supported": ["claude"]},
        {"service": "cockpit-themes", "ready": False, "reason": "provider_unsupported", "provider": "codex",
         "supported": ["claude"]}]
    assert ai.gap(tmp_path, "cockpit-prio")["reason"] == "provider_unsupported"
    assert ai.gap(tmp_path, "briefing-chat") is None
    # a file that is there but cannot be used switches the service off as well: said, not swallowed
    (tmp_path / "workflow/ai-services/cockpit-themes.yaml").write_text("provider: [")
    config(tmp_path, "briefing-chat", "gemini")
    got = {g["service"]: g for g in ai.gaps(tmp_path)}
    assert set(got) == {"briefing-chat", "cockpit-prio", "cockpit-themes"}
    for sid in ("briefing-chat", "cockpit-themes"):
        assert got[sid]["ready"] is False and got[sid]["reason"] == "config_invalid", got[sid]
        assert sid in got[sid]["error"] and len(got[sid]["error"]) <= 200
    assert "provider" not in got["cockpit-themes"]


def test_how_the_caller_runs_a_service_decides_whether_it_is_a_gap(tmp_path):
    # one rule for every caller: a service switched off is no gap, nor one whose model the caller pins (its file
    # is never read then); without a word from the caller the service counts as on and unpinned
    config(tmp_path, "cockpit-prio", "codex")
    (tmp_path / "workflow/ai-services/cockpit-themes.yaml").write_text("provider: [")
    assert ai.gap(tmp_path, "cockpit-prio", {"enabled": False, "pinned": False}) is None
    assert ai.gap(tmp_path, "cockpit-prio", {"enabled": True, "pinned": True}) is None
    assert ai.gap(tmp_path, "cockpit-themes", {"enabled": True, "pinned": True}) is None
    assert ai.gap(tmp_path, "cockpit-prio", {"enabled": True, "pinned": False})["reason"] == "provider_unsupported"
    uses = {"cockpit-prio": {"enabled": False, "pinned": False}, "cockpit-themes": {"enabled": True, "pinned": False}}
    assert [g["service"] for g in ai.gaps(tmp_path, uses)] == ["cockpit-themes"]


def test_the_docs_show_the_declared_list():
    text = (ROOT / "docs/ai-services.md").read_text(encoding="utf-8")
    begin, end = "<!-- ai-services:begin -->", "<!-- ai-services:end -->"
    assert begin in text and end in text
    shown = text.split(begin, 1)[1].split(end, 1)[0].strip()
    assert shown == ai.services_table().strip(), "docs/ai-services.md: paste python3 scripts/ai-run.py --list"
    p = subprocess.run([sys.executable, str(ROOT / "scripts/ai-run.py"), "--list"], capture_output=True, text=True)
    assert p.returncode == 0 and p.stdout.strip() == ai.services_table().strip(), p.stderr
    p = subprocess.run([sys.executable, str(ROOT / "scripts/ai-run.py"), "--list", "--json"], capture_output=True, text=True)
    assert json.loads(p.stdout) == {k: {"providers": list(v["providers"]), "code": v["code"]} for k, v in ai.SERVICES.items()}


def test_the_template_names_no_list_of_its_own():
    text = (ROOT / "workflow/ai-services/_template.yaml").read_text(encoding="utf-8")
    assert "cockpit-describe" not in text and "ai-run.py --list" in text
