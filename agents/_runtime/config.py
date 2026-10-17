"""Load a Bridge-Agent instance from ``agents/<name>/``.

An instance is declarative: ``agent.yaml`` (card spec + runtime knobs) plus
``system-prompt.md`` (the persona). Everything the runtime needs is resolved
here into one ``AgentConfig`` — the server/runner/executor stay instance-agnostic.

Env overrides (so the same files run in dev and on the host) take precedence:
``PUBLIC_AGENT_URL``, ``AGENT_HOST``, ``AGENT_PORT``, ``CLAUDE_MODEL``,
``GROUNDING_DIR``, ``CLAUDE_BINARY``, ``ENVIRONMENT``, ``CORS_ALLOWED_ORIGINS``,
``AGENT_TRUST``.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .access import AccessConfig, parse_access
from .approval import ApprovalConfig, parse_approval
from .auth import AuthConfig, parse_auth
from .policy import RequestsConfig, parse_requests

logger = logging.getLogger(__name__)

# config.py → agents/_runtime/config.py ; parents[2] = repo root (contains agents/)
PROJECT_ROOT = Path(__file__).resolve().parents[2]
AGENTS_DIR = PROJECT_ROOT / "agents"

_DEV_ENVIRONMENTS = {"local", "dev", "development", "test"}

# trust: public | private | peer — see § Trust profile below. Anything else (unset,
# blank, typo) MUST fail closed to "public"; never silently widen an agent.
# ``peer`` is hardened exactly like ``public`` (grounding-dir cwd, strict tools) and
# additionally requires an ``auth:`` block: it answers only Bridges it knows.
_VALID_TRUST = frozenset({"public", "private", "peer"})
_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1"})

# Soft ceiling per embedded grounding file — a runaway file must not blow up the
# system prompt. A ~110 KB CV is fine; this only guards against accidents.
MAX_INLINE_GROUNDING_BYTES = 600_000

_INLINE_GROUNDING_HEADER = (
    "\n\n---\n\n"
    "# Embedded knowledge base (read-only — already in your context)\n\n"
    "The file(s) below are provided to you IN FULL. Treat them as your knowledge "
    "base and answer directly from them — you do NOT need to read them again with "
    "the file tools. Use Read/Glob/Grep only to look up something specific that is "
    "not already present below.\n"
)


def compose_inline_grounding(
    system_prompt: str, working_dir: str, patterns: list[str]
) -> str:
    """Append the contents of grounding files to the system prompt.

    Each pattern is a glob resolved against ``working_dir`` (the grounding dir).
    Files are embedded under a clear delimiter so the agent answers from context
    instead of paying a tool round-trip per question — the dominant source of
    public-widget latency. Returns the prompt unchanged when ``patterns`` is empty
    or nothing matches; oversized or unreadable files are skipped and logged.
    """
    if not patterns:
        return system_prompt
    base = Path(working_dir)
    blocks: list[str] = []
    for pattern in patterns:
        for fp in sorted(base.glob(pattern)):
            if not fp.is_file():
                continue
            try:
                size = fp.stat().st_size
            except OSError:
                continue
            if size > MAX_INLINE_GROUNDING_BYTES:
                logger.warning(
                    "inline_grounding: skipping %s (%d bytes > %d cap)",
                    fp.name, size, MAX_INLINE_GROUNDING_BYTES,
                )
                continue
            try:
                text = fp.read_text("utf-8")
            except (OSError, UnicodeDecodeError):
                logger.warning("inline_grounding: cannot read %s", fp.name)
                continue
            blocks.append(f"## File: {fp.name}\n\n{text.strip()}")
    if not blocks:
        return system_prompt
    return system_prompt + _INLINE_GROUNDING_HEADER + "\n" + "\n\n".join(blocks)


@dataclass
class AgentConfig:
    instance: str                 # folder name under agents/
    name: str
    description: str
    version: str
    provider: dict
    documentation_url: str | None
    icon_url: str | None
    public_url: str
    host: str
    port: int
    model: str
    binary: str
    timeout: float
    working_dir: str
    extra_read_dirs: list[str]
    allowed_tools: str
    cors_origins: list[str]
    max_concurrency: int
    max_input_chars: int
    max_turns: int
    max_contexts: int
    messages: dict
    skills: list[dict]
    system_prompt: str
    trust: str = "public"
    auth: AuthConfig = field(default_factory=AuthConfig)
    approval: ApprovalConfig = field(default_factory=ApprovalConfig)
    requests: RequestsConfig = field(default_factory=RequestsConfig)
    # Per-peer folders (see _runtime/access.py). With access on, ``system_prompt`` has
    # no grounding embedded: each turn embeds ``inline_grounding`` from the asking
    # peer's folder into ``base_system_prompt``, fresh.
    access: AccessConfig = field(default_factory=AccessConfig)
    base_system_prompt: str = ""
    inline_grounding: list[str] = field(default_factory=list)
    project_root: str = field(default=str(PROJECT_ROOT))


def _resolve_path(value: str | None) -> str | None:
    """Expand ``~`` and make relative paths relative to the repo root."""
    if not value:
        return None
    expanded = os.path.expanduser(value)
    path = Path(expanded)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return str(path.resolve())


def resolve_trust(instance: str, spec_trust: str | None) -> str:
    """Resolve the ``trust`` profile: ``AGENT_TRUST`` env, then ``agent.yaml``.

    Fail-closed by construction: any value other than exactly ``"public"`` or
    ``"private"`` (unset, blank, or a typo) resolves to ``"public"`` — a
    misconfigured trust field must never silently grant a private agent's
    relaxed settings. A non-blank unrecognized value is logged so the typo is
    visible instead of silently downgrading forever.
    """
    raw = os.getenv("AGENT_TRUST") or spec_trust or "public"
    value = str(raw).strip().lower()
    if value in _VALID_TRUST:
        return value
    logger.warning(
        "agent_trust: instance '%s' has unrecognized trust value %r "
        "(agent.yaml trust: / AGENT_TRUST) — falling back to 'public' (fail-closed)",
        instance, raw,
    )
    return "public"


def resolve_cors(cfg_origins: list[str], dev_origins: list[str], environment: str) -> list[str]:
    """Production origins always; dev origins only in a dev/test environment.

    An explicit ``CORS_ALLOWED_ORIGINS`` env (comma-separated) wins verbatim.
    """
    override = os.getenv("CORS_ALLOWED_ORIGINS")
    if override:
        return [o.strip() for o in override.split(",") if o.strip()]
    origins = list(cfg_origins)
    if environment.lower() in _DEV_ENVIRONMENTS:
        origins += dev_origins
    return origins


def load_agent_config(instance: str, *, environment: str | None = None) -> AgentConfig:
    """Build the resolved config for ``agents/<instance>/``."""
    inst_dir = AGENTS_DIR / instance
    spec_path = inst_dir / "agent.yaml"
    if not spec_path.exists():
        raise FileNotFoundError(
            f"No agent.yaml for instance '{instance}' (looked in {spec_path})"
        )
    spec = yaml.safe_load(spec_path.read_text("utf-8")) or {}

    prompt_file = spec.get("system_prompt_file", "system-prompt.md")
    prompt_path = inst_dir / prompt_file
    system_prompt = prompt_path.read_text("utf-8") if prompt_path.exists() else ""
    if not system_prompt:
        raise FileNotFoundError(f"No system prompt for '{instance}' (looked in {prompt_path})")

    environment = environment or os.getenv("ENVIRONMENT", "production")

    host = os.getenv("AGENT_HOST", spec.get("host", "127.0.0.1"))
    port = int(os.getenv("AGENT_PORT", spec.get("port", 8011)))
    public_url = os.getenv("PUBLIC_AGENT_URL", spec.get("public_url") or f"http://{host}:{port}")

    trust = resolve_trust(instance, spec.get("trust"))
    if trust == "private" and host not in _LOOPBACK_HOSTS:
        logger.warning(
            "agent_trust: instance '%s' has trust: private but binds to non-loopback "
            "host %r — this exposes its relaxed settings (user+project settings, a "
            "wider tool set, cwd=repo root, session resume) to the network. Bind to a "
            "loopback host and put a tunnel/proxy in front, or set trust: public.",
            instance, host,
        )

    auth = parse_auth(instance, spec.get("auth"))
    if trust == "peer" and not auth.enabled:
        raise ValueError(
            f"agent '{instance}': trust: peer needs an auth: block (mode: bearer); "
            "a peer endpoint without authentication would be a public one"
        )

    # working_dir = cwd = read-confinement for the file tools. A public agent is
    # confined to its grounding dir; a private/trusted agent gets the full instance
    # repo root (CLAUDE.md, @-imports, .claude/skills) — see § Trust profile.
    if trust == "private":
        working_dir = str(PROJECT_ROOT)
    else:
        working_dir = _resolve_path(os.getenv("GROUNDING_DIR", spec.get("grounding_dir"))) or str(PROJECT_ROOT)
    extra_read_dirs = [p for p in (_resolve_path(d) for d in spec.get("extra_read_dirs", [])) if p]

    # Substitute path placeholders in allowed_tools so instance tools are invoked
    # by ABSOLUTE path (the agent runs with cwd = working_dir, not the repo root).
    tools_dir = str((inst_dir / "tools").resolve())
    allowed_tools = (
        spec.get("allowed_tools", "Read,Glob,Grep")
        .replace("${tools_dir}", tools_dir)
        .replace("${instance_dir}", str(inst_dir.resolve()))
    )
    # Same substitution in the prompt, so the agent invokes its tools by the exact
    # absolute path that allowed_tools permits (cwd is the grounding dir, not here).
    system_prompt = (
        system_prompt
        .replace("${tools_dir}", tools_dir)
        .replace("${instance_dir}", str(inst_dir.resolve()))
    )

    # Owner approval before an answer leaves (see _runtime/approval.py). Resolved
    # here so a broken block stops the start instead of every later answer.
    approval = parse_approval(instance, spec.get("approval"), tools_dir=tools_dir)

    # Peer requests: something to be DONE, decided by the owner or a rule the owner
    # set (see _runtime/policy.py). Needs both an owner to ask and a known peer.
    requests = parse_requests(
        instance, spec.get("requests"), inst_dir=inst_dir.resolve(), tools_dir=tools_dir,
        has_approval=approval.enabled, has_auth=auth.enabled,
    )

    # One folder per peer, and topics the owner opens on request (see _runtime/access.py).
    access = parse_access(
        instance, spec.get("access"), inst_dir=inst_dir.resolve(), tools_dir=tools_dir,
        trust=trust, peer_ids=[p.id for p in auth.peers], allowed_tools=allowed_tools,
        extra_read_dirs=extra_read_dirs, has_approval=approval.enabled,
    )
    inline_patterns = list(spec.get("inline_grounding") or [])
    base_system_prompt = system_prompt
    if access.enabled:
        # No shared folder: the turn's cwd and tool paths come from the asking peer.
        working_dir = str(access.peers_dir)
    else:
        allowed_tools = allowed_tools.replace("${grounding_dir}", working_dir)

    # Inline grounding: embed declared grounding files straight into the system
    # prompt so the agent answers from context — no Read/Grep round-trip per
    # question (the dominant source of public-widget latency). File tools stay
    # available as a fallback for ad-hoc lookups. Resolved against working_dir,
    # so the same read-confinement (grounding dir) applies.
    if not access.enabled:
        system_prompt = compose_inline_grounding(system_prompt, working_dir, inline_patterns)

    cors = resolve_cors(
        spec.get("cors_origins", []),
        spec.get("cors_dev_origins", []),
        environment,
    )

    return AgentConfig(
        instance=instance,
        name=spec.get("name", instance),
        description=spec.get("description", ""),
        version=str(spec.get("version", "1.0.0")),
        provider=spec.get("provider") or {},
        documentation_url=spec.get("documentation_url"),
        icon_url=spec.get("icon_url"),
        public_url=public_url,
        host=host,
        port=port,
        model=os.getenv("CLAUDE_MODEL", spec.get("model", "sonnet")),
        binary=os.getenv("CLAUDE_BINARY", spec.get("binary", "claude")),
        timeout=float(spec.get("timeout", 90)),
        working_dir=working_dir,
        extra_read_dirs=extra_read_dirs,
        allowed_tools=allowed_tools,
        cors_origins=cors,
        max_concurrency=int(spec.get("max_concurrency", 2)),
        max_input_chars=int(spec.get("max_input_chars", 4000)),
        max_turns=int(spec.get("max_turns", 24)),
        max_contexts=int(spec.get("max_contexts", 500)),
        messages=spec.get("messages") or {},
        skills=spec.get("skills") or [],
        system_prompt=system_prompt,
        trust=trust,
        auth=auth,
        approval=approval,
        requests=requests,
        access=access,
        base_system_prompt=base_system_prompt,
        inline_grounding=inline_patterns,
        project_root=str(PROJECT_ROOT),
    )
