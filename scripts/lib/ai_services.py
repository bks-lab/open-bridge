# SPDX-License-Identifier: MIT
"""Per-consumer CLI selection. Missing config preserves Claude; invalid config fails closed.

The configuration chooses a provider and models, never commands or permissions.
Web chat and batch workers share Codex's invocation and event decoding.
SERVICES is the one list of service ids the code selects and the providers each can run; a configured
provider a service cannot run is a gap (gaps), reported by the cockpit, never a silent switch-off.
"""
from __future__ import annotations

import json
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

import yaml

PROVIDERS = ("claude", "codex")
MODEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}\Z")
SESSION_RE = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
CLAUDE_MODELS = {"haiku": "claude-haiku-5-5", "sonnet": "claude-sonnet-5-5", "opus": "claude-opus-5-5"}
CODEX_FLAGS = ["exec", "--sandbox", "read-only", "--ignore-user-config", "--ignore-rules",
               "-c", 'approval_policy="never"', "--json", "--disable", "hooks", "--disable", "apps",
               "--disable", "multi_agent", "--disable", "remote_plugin",
               "--disable", "skill_mcp_dependency_install", "-c", 'web_search="disabled"']

#: Every AI service id the code selects, the providers its code can run, and where that code lives. The one
#: list: the cockpit's Setup page, `bridge-cockpit.py status`, `ai-run.py --list` and docs/ai-services.md read
#: it, and scripts/tests/test_ai_services.py fails when the code selects an id missing here. A worker's own id
#: (ai-run.py --service) runs on every provider and is not listed. Adapting a service to a provider adds it here.
SERVICES = {
    "briefing-chat": {"providers": ("claude", "codex"), "code": "scripts/lib/bridge_cockpit/quick.py"},
    "task-review": {"providers": ("claude", "codex"), "code": "scripts/task.py"},
    "triage": {"providers": ("claude", "codex"), "code": "scripts/triage.py"},
    "cockpit-activity": {"providers": ("claude",), "code": "scripts/lib/bridge_cockpit/activity.py"},
    "cockpit-describe": {"providers": ("claude",), "code": "scripts/lib/bridge_cockpit/describe.py"},
    "cockpit-files": {"providers": ("claude",), "code": "scripts/lib/bridge_cockpit/actions_work.py"},
    "cockpit-instruct": {"providers": ("claude",), "code": "scripts/lib/bridge_cockpit/instruct.py"},
    "cockpit-organize": {"providers": ("claude",), "code": "scripts/lib/bridge_cockpit/organize.py"},
    "cockpit-prio": {"providers": ("claude",), "code": "scripts/lib/bridge_cockpit/prio.py"},
    "cockpit-themes": {"providers": ("claude",), "code": "scripts/lib/bridge_cockpit/themes.py"},
}
GAP = "provider_unsupported"
INVALID = "config_invalid"


@dataclass(frozen=True)
class Selection:
    provider: str
    model: str | None
    configured: bool = False


def load(root: Path, service: str) -> dict:
    if not isinstance(service, str) or not re.fullmatch(r"[a-z][a-z0-9-]*", service):
        raise ValueError("invalid AI service id")
    folder = Path(root).resolve() / "workflow" / "ai-services"
    path = folder / f"{service}.yaml"
    if not path.exists():
        return {}
    if path.resolve().parent != folder.resolve():
        raise ValueError("AI service file must stay in workflow/ai-services")
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (yaml.YAMLError, OSError) as exc:
        raise ValueError(f"cannot read AI service config: {service}") from exc
    if (not isinstance(data, dict) or set(data) - {"schema_version", "scope", "id", "provider", "models"}
            or type(data.get("schema_version")) is not int or data["schema_version"] != 1
            or data.get("scope") != "user" or data.get("id") != service
            or data.get("provider") not in PROVIDERS):
        raise ValueError(f"invalid AI service config: {service}")
    models = data.get("models", {})
    if (not isinstance(models, dict) or set(models) - set(PROVIDERS)
            or any(not isinstance(v, str) or not MODEL_RE.fullmatch(v) for v in models.values())):
        raise ValueError(f"invalid AI service models: {service}")
    return data


def select(root: Path, service: str, default_model: str | None = "haiku", *, provider: str | None = None) -> Selection:
    data = load(root, service)
    chosen = provider if provider is not None else data.get("provider", "claude")
    if chosen not in PROVIDERS:
        raise ValueError("unknown AI provider")
    model = data.get("models", {}).get(chosen)
    if chosen == "claude":
        model = model or default_model
        model = CLAUDE_MODELS.get(model, model)
    if model is not None and (not isinstance(model, str) or not MODEL_RE.fullmatch(model)):
        raise ValueError("invalid AI model")
    return Selection(chosen, model, bool(data))


def supports(service: str, provider: str) -> bool:
    """Whether the service's code can run on the provider; an id SERVICES does not list (a worker's) runs on all"""
    entry = SERVICES.get(service)
    return provider in (entry["providers"] if entry else PROVIDERS)


def gap(root: Path, service: str, use: dict | None = None) -> dict | None:
    """Why the service stays off for its file: a provider its code cannot run ({service, ready: False, reason:
    provider_unsupported, provider, supported}) or a file load refuses ({..., reason: config_invalid, error}).
    `use` is how the caller runs it, {enabled, pinned}: switched off, or pinned to a model of the caller's own (the
    file is never read then), it is no gap. None also when the service runs, and when there is no file."""
    if use is not None and (not use.get("enabled", True) or use.get("pinned")):
        return None
    try:
        data = load(root, service)
    except ValueError as exc:
        return {"service": service, "ready": False, "reason": INVALID, "error": str(exc)[:200]}
    provider = data.get("provider")
    if not data or supports(service, provider):
        return None
    return {"service": service, "ready": False, "reason": GAP, "provider": provider,
            "supported": list(SERVICES[service]["providers"])}


def gaps(root: Path, uses: dict | None = None) -> list[dict]:
    """Every gap of this Bridge, in the order of SERVICES; `uses` maps a service to its `use` (gap)"""
    return [g for g in (gap(root, s, (uses or {}).get(s)) for s in SERVICES) if g]


def services_table() -> str:
    """SERVICES as the Markdown table docs/ai-services.md shows (ai-run.py --list prints it)"""
    rows = ["| Service | Providers | Code |", "|---|---|---|"]
    rows += [f"| `{sid}` | {', '.join(e['providers'])} | `{e['code']}` |" for sid, e in SERVICES.items()]
    return "\n".join(rows) + "\n"


def resolve(provider: str) -> str | None:
    if provider not in PROVIDERS:
        raise ValueError("unknown AI provider")
    local = Path.home() / ".local" / "bin" / provider
    return str(local) if local.is_file() else shutil.which(provider)


def codex_argv(binary: str, prompt: str, model: str | None = None, session: str | None = None,
               *, read_files: bool = True) -> list[str]:
    if model is not None and not MODEL_RE.fullmatch(model):
        raise ValueError("invalid Codex model")
    if session is not None and not SESSION_RE.fullmatch(session):
        raise ValueError("invalid Codex session")
    # Apply restrictions before the subcommand so resume gets the same policy as a new run.
    argv = [binary, *CODEX_FLAGS]
    if not read_files:
        argv += ["--disable", "shell_tool"]
    if model:
        argv += ["--model", model]
    if session:
        argv += ["resume", session]
    return argv + ["--", prompt]


def codex_argv_ok(argv: list[str], binary: str | None) -> bool:
    """Only a read-only chat invocation; never accept arbitrary CLI flags from a web request."""
    if not binary or len(argv) < len(CODEX_FLAGS) + 3 or argv[0] != binary or argv[-2] != "--":
        return False
    tail = argv[len(CODEX_FLAGS) + 1:-2]
    model = session = None
    if tail[:1] == ["--model"] and len(tail) >= 2:
        model, tail = tail[1], tail[2:]
    if tail[:1] == ["resume"] and len(tail) == 2:
        session, tail = tail[1], []
    try:
        return not tail and argv == codex_argv(binary, argv[-1], model, session)
    except ValueError:
        return False


class CodexStream:
    def __init__(self):
        self.text = ""
        self.doing = None
        self.session = None
        self.usage = None
        self.error = None
        self.completed = False

    def feed(self, line: str) -> bool:
        try:
            data = json.loads(line)
        except ValueError:
            return False
        if not isinstance(data, dict):
            return False
        kind = data.get("type")
        if kind == "thread.started":
            self.session = data.get("thread_id")
        elif kind == "turn.completed":
            self.completed = True
            self.usage = data.get("usage")
        elif kind in ("turn.failed", "error"):
            err = data.get("error") or data.get("message") or "Codex failed"
            self.error = str(err.get("message", "Codex failed") if isinstance(err, dict) else err)
        elif kind in ("item.started", "item.updated", "item.completed"):
            item = data.get("item")
            if not isinstance(item, dict):
                return False
            if item.get("type") == "agent_message" and isinstance(item.get("text"), str):
                self.text, self.doing = item["text"], None
                return True
            if item.get("type") == "command_execution":
                self.doing = str(item.get("command") or "Reading")[:160] if kind != "item.completed" else None
                return True
        return False

    def answer(self) -> dict | None:
        if not self.completed and not self.error:
            return None
        return {"text": self.error or self.text.strip(), "session": self.session, "total_usd": None,
                "model": None, "usage": self.usage, "error": bool(self.error) or not self.text.strip()}


def parse_codex(out: str) -> dict | None:
    stream = CodexStream()
    for line in out.splitlines():
        stream.feed(line)
    return stream.answer()


def batch_argv(selection: Selection, prompt: str, binary: str | None = None) -> list[str]:
    binary = binary or resolve(selection.provider)
    if not binary:
        raise ValueError(f"{selection.provider} CLI is not installed")
    if selection.provider == "codex":
        return codex_argv(binary, prompt, selection.model, read_files=False)
    argv = [binary, "-p", "--output-format", "json", "--no-session-persistence", "--setting-sources", "",
            "--strict-mcp-config", "--tools", ""]
    if selection.model:
        argv += ["--model", selection.model]
    return argv + ["--", prompt]
