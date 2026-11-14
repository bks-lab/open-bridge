#!/usr/bin/env python3
"""a2a: talk to other Bridges over A2A, check their cards, probe their edge, and
scaffold an A2A agent of your own.

Commands (run through ``skills/a2a/a2a.sh``)::

    peers                              list the peers declared in infra/a2a-peers/
    card   <peer|url>                  fetch and check an agent card
    ask    <peer> <question> [--context ID] [--wait S]
    probe  <peer> [--prompts FILE]     auth refusals + boundary prompts
    new-agent <name> --trust public|peer [--port N] [--peer ID:ENV:LOGIN ...]

A peer is one file, ``infra/a2a-peers/<id>.yaml`` (template and schema next to
it). Its token is a secret REFERENCE (``credential_ref``), never a value. The
value reaches this process only through ``skills/secrets/secrets.sh run``, which
puts it into ``A2A_TOKEN`` for the child and scrubs it from the output; this
script never prints it.

Both wire dialects are spoken, chosen from the peer's card: A2A 1.x
(``SendMessage``, ``ROLE_USER``, ``A2A-Version: 1.0``) and 0.3 (``message/send``
with ``kind`` discriminators). Stdlib plus PyYAML.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import ssl
import string
import subprocess
import sys
import time
import urllib.error
import urllib.request
import uuid
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parents[1]
ASSETS = SKILL_DIR / "assets"
TOKEN_ENV = "A2A_TOKEN"
CARD_PATH = "/.well-known/agent-card.json"
LEGACY_CARD_PATH = "/.well-known/agent.json"
SUPPORTED_MAJORS = ("0.", "1.")
TERMINAL = {"completed", "failed", "canceled", "rejected"}
# A peer whose slots are all taken ends the task failed with reason "busy" and a
# suggested retry_after_s (open-bridge#640). ask() waits that long (capped) and asks
# again, up to busy_retries times, so the busy text never comes back as an answer.
BUSY_RETRIES = 2
BUSY_DEFAULT_WAIT_S = 5.0
BUSY_MAX_WAIT_S = 30.0
_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]*$")
_REF = re.compile(r"^(keychain|env|azure-keyvault|1password|keepass|vault|file)://\S+$")


class A2AError(Exception):
    """A peer answered, but not with something usable. The message says why."""


# --------------------------------------------------------------------------- repo

def repo_root(start: Path | None = None) -> Path:
    """The Bridge root: the nearest parent holding AGENTS.md and skills/."""
    here = (start or Path.cwd()).resolve()
    for p in (here, *here.parents):
        if (p / "AGENTS.md").exists() and (p / "skills").is_dir():
            return p
    return SKILL_DIR.parents[1]


def _yaml():
    try:
        import yaml  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover
        raise SystemExit("a2a: PyYAML is required (pip install pyyaml)") from exc
    return yaml


# -------------------------------------------------------------------------- peers

def load_peers(root: Path) -> dict[str, dict]:
    """Every ``infra/a2a-peers/<id>.yaml`` except ``_``-prefixed files."""
    peers: dict[str, dict] = {}
    folder = root / "infra" / "a2a-peers"
    for f in sorted(folder.glob("*.yaml")) if folder.is_dir() else []:
        if f.name.startswith("_"):
            continue
        data = _yaml().safe_load(f.read_text("utf-8")) or {}
        check_peer(data, f.stem)
        peers[data["name"]] = data
    return peers


def check_peer(data: dict, stem: str) -> None:
    """Refuse a peer file that would leak or silently misroute."""
    name = data.get("name")
    if name != stem or not _SLUG.match(str(name or "")):
        raise A2AError(f"infra/a2a-peers/{stem}.yaml: name must be the slug {stem!r}")
    for key in ("token", "password", "secret", "api_key"):
        if key in data:
            raise A2AError(
                f"peer {name}: raw {key!r} in the file; write credential_ref: <scheme>://... instead"
            )
    if not str(data.get("card_url", "")).startswith(("https://", "http://127.0.0.1", "http://localhost")):
        raise A2AError(f"peer {name}: card_url must be https:// (or loopback http for tests)")
    auth = data.get("auth", "none")
    if auth not in ("none", "bearer"):
        raise A2AError(f"peer {name}: auth must be none or bearer, not {auth!r}")
    if auth == "bearer" and not _REF.match(str(data.get("credential_ref", ""))):
        raise A2AError(f"peer {name}: auth bearer needs credential_ref as a secret reference")


def resolve_target(target: str, root: Path) -> tuple[str, dict | None]:
    """A peer name or a URL → (card URL, peer entry or None)."""
    if target.startswith(("http://", "https://")):
        url = target.rstrip("/")
        if not url.endswith((CARD_PATH, LEGACY_CARD_PATH)):
            url += CARD_PATH
        return url, None
    peers = load_peers(root)
    if target not in peers:
        known = ", ".join(sorted(peers)) or "none declared"
        raise A2AError(f"unknown peer {target!r} (known: {known})")
    return peers[target]["card_url"], peers[target]


# --------------------------------------------------------------------------- http

def _open(req, timeout):
    return urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context())


def http_json(url: str, *, body: dict | None = None, headers: dict | None = None, timeout: float = 30):
    """GET or POST JSON. Returns (status, parsed body or None). Never raises on 4xx/5xx."""
    data = json.dumps(body).encode("utf-8") if body is not None else None
    h = {"Accept": "application/json", "User-Agent": "open-bridge-a2a/1"}
    if body is not None:
        h["Content-Type"] = "application/json"
    h.update(headers or {})
    req = urllib.request.Request(url, data=data, headers=h, method="POST" if data else "GET")
    try:
        with _open(req, timeout) as resp:
            raw = resp.read()
            status = resp.status
    except urllib.error.HTTPError as exc:
        raw = exc.read() if hasattr(exc, "read") else b""
        status = exc.code
    try:
        return status, json.loads(raw.decode("utf-8")) if raw else None
    except (ValueError, UnicodeDecodeError):
        return status, None


# --------------------------------------------------------------------------- card

def card_endpoint(card: dict) -> tuple[str, str]:
    """(protocol version, JSON-RPC URL) from a v1 or a 0.3 card, or raise."""
    for iface in card.get("supportedInterfaces") or []:
        binding = str(iface.get("protocolBinding") or iface.get("transport") or "").upper()
        if binding == "JSONRPC" and iface.get("url"):
            return str(iface.get("protocolVersion") or ""), str(iface["url"])
    if card.get("url") and str(card.get("preferredTransport", "JSONRPC")).upper() == "JSONRPC":
        return str(card.get("protocolVersion") or ""), str(card["url"])
    raise A2AError("card offers no JSON-RPC interface")


def check_card(card: dict) -> list[tuple[str, bool, str]]:
    """Findings as (check, ok, detail). Every check says what it measured."""
    out: list[tuple[str, bool, str]] = []
    out.append(("name", bool(card.get("name")), str(card.get("name") or "missing")))
    try:
        version, url = card_endpoint(card)
        out.append(("json-rpc endpoint", True, url))
        out.append((
            "protocol version",
            version.startswith(SUPPORTED_MAJORS),
            version or "missing (a client cannot pick a dialect)",
        ))
        out.append(("endpoint is https", url.startswith("https://"), url.split("/")[2] if "//" in url else url))
        v1 = bool(card.get("supportedInterfaces"))
        out.append(("card dialect", True, "1.x (supportedInterfaces)" if v1 else "0.3 (top-level url)"))
    except A2AError as exc:
        out.append(("json-rpc endpoint", False, str(exc)))
    skills = [s.get("id") for s in card.get("skills") or []]
    out.append(("skills", bool(skills), ", ".join(map(str, skills)) or "none advertised"))
    schemes = sorted((card.get("securitySchemes") or {}).keys())
    out.append(("security schemes", True, ", ".join(schemes) or "none (open agent)"))
    return out


def fetch_card(card_url: str, timeout: float = 20) -> dict:
    status, card = http_json(card_url, timeout=timeout)
    if status != 200 or not isinstance(card, dict):
        raise A2AError(f"card at {card_url} answered {status}")
    return card


# ---------------------------------------------------------------------------- ask

def build_payload(question: str, context_id: str | None, protocol: str, *, nonblocking: bool = False,
                  metadata: dict | None = None) -> dict:
    msg_id = str(uuid.uuid4())
    if protocol.startswith("1."):
        message = {"role": "ROLE_USER", "messageId": msg_id, "parts": [{"text": question}]}
        name = "SendMessage"
    else:
        message = {"kind": "message", "role": "user", "messageId": msg_id,
                   "parts": [{"kind": "text", "text": question}]}
        name = "message/send"
    if context_id:
        message["contextId"] = context_id
    if metadata:
        message["metadata"] = metadata
    params: dict = {"message": message}
    if nonblocking:
        # Return at once and let the caller poll: a peer holding the task for its
        # owner's approval would otherwise keep this HTTP request open for hours.
        params["configuration"] = (
            {"returnImmediately": True} if protocol.startswith("1.") else {"blocking": False}
        )
    return {"jsonrpc": "2.0", "id": msg_id, "method": name, "params": params}


def _state(task: dict) -> str:
    raw = str((task.get("status") or {}).get("state") or "")
    return raw.lower().removeprefix("task_state_")


def _task_of(result: dict) -> dict:
    if "task" in result and isinstance(result["task"], dict):
        return result["task"]
    if "message" in result and isinstance(result["message"], dict):
        return {"status": {"state": "completed"}, "artifacts": [{"parts": result["message"].get("parts", [])}]}
    return result


def busy_retry_after(task: dict) -> float | None:
    """Seconds to wait before asking again when the peer shed the task as busy, else None."""
    if _state(task) != "failed":
        return None
    meta = ((task.get("status") or {}).get("message") or {}).get("metadata") or {}
    if meta.get("reason") != "busy":
        return None
    try:
        wait = float(meta.get("retry_after_s", BUSY_DEFAULT_WAIT_S))
    except (TypeError, ValueError):
        wait = BUSY_DEFAULT_WAIT_S
    return min(max(wait, 0.0), BUSY_MAX_WAIT_S)


def task_text(task: dict) -> str:
    texts = [p.get("text", "") for a in task.get("artifacts") or [] for p in a.get("parts") or []]
    if not any(t.strip() for t in texts):
        msg = (task.get("status") or {}).get("message") or {}
        texts = [p.get("text", "") for p in msg.get("parts") or []]
    return "\n".join(t for t in texts if t).strip()


def _headers(protocol: str, token: str | None) -> dict:
    h = {"A2A-Version": "1.0"} if protocol.startswith("1.") else {}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


def ask(card: dict, question: str, *, token: str | None, context_id: str | None = None,
        wait: float = 0, poll_every: float = 5, timeout: float = 200,
        metadata: dict | None = None, nonblocking: bool = False,
        busy_retries: int = BUSY_RETRIES) -> dict:
    """Send one question; poll while the peer holds the task (e.g. awaiting approval).

    A task the peer shed as busy is sent again after its retry delay, at most
    ``busy_retries`` times; the last busy task is returned as it came.
    """
    protocol, url = card_endpoint(card)
    if not protocol.startswith(SUPPORTED_MAJORS):
        raise A2AError(f"unsupported protocol version {protocol or 'missing'}")
    for attempt in range(max(0, busy_retries) + 1):
        task = _send_once(card, question, protocol, url, token=token, context_id=context_id,
                          wait=wait, poll_every=poll_every, timeout=timeout,
                          metadata=metadata, nonblocking=nonblocking)
        delay = busy_retry_after(task)
        if delay is None or attempt == max(0, busy_retries):
            return task
        time.sleep(delay)
    return task


def _send_once(card: dict, question: str, protocol: str, url: str, *, token: str | None,
               context_id: str | None, wait: float, poll_every: float, timeout: float,
               metadata: dict | None, nonblocking: bool) -> dict:
    payload = build_payload(question, context_id, protocol, nonblocking=nonblocking or wait > 0,
                            metadata=metadata)
    status, body = http_json(url, body=payload,
                             headers=_headers(protocol, token), timeout=timeout)
    if status in (401, 403):
        raise A2AError(f"peer refused the call ({status}): token missing, wrong, or bound to another identity")
    if status != 200 or not isinstance(body, dict):
        raise A2AError(f"peer answered HTTP {status}")
    if "error" in body:
        raise A2AError(f"peer error {body['error'].get('code')}: {body['error'].get('message')}")
    task = _task_of(body.get("result") or {})
    deadline = time.monotonic() + wait
    while _state(task) not in TERMINAL and task.get("id") and time.monotonic() < deadline:
        time.sleep(poll_every)
        task = get_task(card, task["id"], token=token, timeout=timeout) or task
    return task


def get_task(card: dict, task_id: str, *, token: str | None, timeout: float = 60) -> dict | None:
    """Read a task again (a held one may have been approved meanwhile), without sending anything new."""
    protocol, url = card_endpoint(card)
    method = "GetTask" if protocol.startswith("1.") else "tasks/get"
    status, got = http_json(url, body={"jsonrpc": "2.0", "id": "poll", "method": method, "params": {"id": task_id}},
                            headers=_headers(protocol, token), timeout=timeout)
    if status in (401, 403):
        raise A2AError(f"peer refused the call ({status}): token missing, wrong, or bound to another identity")
    if isinstance(got, dict) and isinstance(got.get("result"), dict):
        return _task_of(got["result"])
    return None


# ----------------------------------------------------------------- owner requests

# Skills a peer runtime puts on its card when it takes requests (agents/_runtime/policy.py).
REQUEST_SKILL, POLICY_SKILL = "owner_request", "owner_policy"


def require_skill(card: dict, skill: str) -> None:
    ids = {s.get("id") for s in card.get("skills") or [] if isinstance(s, dict)}
    if skill not in ids:
        raise A2AError(f"this peer's card has no {skill} skill: it takes questions only, "
                         "its owner has not switched on requests")


def print_task(task: dict, as_json: bool) -> int:
    if as_json:
        print(json.dumps({"state": _state(task), "task_id": task.get("id"),
                          "context_id": task.get("contextId"), "text": task_text(task)},
                         ensure_ascii=False))
    else:
        state = _state(task) or "unknown"
        held = f" task {task['id']} (read again: a2a.sh get <peer> {task['id']})" \
            if state not in TERMINAL and task.get("id") else ""
        print(f"[{state}]{held} {task_text(task)}".rstrip())
    return 0 if _state(task) == "completed" else 1


# -------------------------------------------------------------------------- token

def with_token(peer: dict | None, argv: list[str]) -> str | None:
    """Return the token, re-running this command under ``secrets.sh run`` if needed.

    A peer without auth needs none. With auth, the value must already be in
    A2A_TOKEN (set by secrets.sh run); if not, this process re-executes itself
    through secrets.sh so the value never passes through a command line or output.
    """
    if not peer or peer.get("auth", "none") == "none":
        return None
    token = os.environ.get(TOKEN_ENV)
    if token:
        return token
    shim = repo_root() / "skills" / "secrets" / "secrets.sh"
    if not shim.exists():
        raise A2AError("peer needs a token and skills/secrets is not installed to resolve it")
    cmd = [str(shim), "run", "--env", f"{TOKEN_ENV}={peer['credential_ref']}", "--",
           sys.executable, str(Path(__file__).resolve()), *argv]
    raise SystemExit(subprocess.call(cmd))


# -------------------------------------------------------------------------- probe

def load_prompts(path: Path) -> list[dict]:
    items = _yaml().safe_load(path.read_text("utf-8")) or {}
    return list(items.get("prompts") or [])


def probe(card: dict, token: str | None, prompts: list[dict], *, timeout: float = 200) -> list[tuple[str, bool, str]]:
    """The edge first (no token, wrong token), then the boundary prompts."""
    out: list[tuple[str, bool, str]] = []
    protocol, url = card_endpoint(card)
    needs_auth = bool(card.get("securitySchemes"))
    payload = build_payload("ping", None, protocol)
    for label, tok in (("no token", None), ("wrong token", "x" * 64)):
        status, _ = http_json(url, body=payload, headers=_headers(protocol, tok), timeout=30)
        expected = 401 if needs_auth else 200
        out.append((f"edge: {label}", status == expected, f"HTTP {status}, expected {expected}"))
    for item in prompts:
        try:
            task = ask(card, item["text"], token=token, timeout=timeout)
            answer = task_text(task)
        except A2AError as exc:
            out.append((f"prompt: {item.get('id', item['text'][:30])}", False, str(exc)))
            continue
        marker = item.get("refusal_marker", "")
        refused = bool(marker) and marker in answer
        ok = refused if item.get("expect") == "refuse" else (not refused and bool(answer))
        out.append((f"prompt: {item.get('id', item['text'][:30])}", ok, answer[:160].replace("\n", " ")))
    return out


# ---------------------------------------------------------------------- new-agent

def new_agent(root: Path, name: str, trust: str, port: int, peers: list[str]) -> list[Path]:
    """Scaffold agents/<name>/ from agents/_template (public) or the peer assets."""
    if not _SLUG.match(name):
        raise A2AError(f"agent name must be a slug, got {name!r}")
    template = root / "agents" / "_template"
    target = root / "agents" / name
    if not template.is_dir():
        raise A2AError("agents/_template not found; is this an open-bridge checkout?")
    if target.exists():
        raise A2AError(f"agents/{name} already exists; not overwriting")
    shutil.copytree(template, target, ignore=shutil.ignore_patterns("__pycache__"))
    written = [target]
    if trust == "public":
        return written
    if trust != "peer":
        raise A2AError("trust must be public or peer")
    if not peers:
        raise A2AError("a peer agent needs at least one --peer ID:ENV:LOGIN")
    entries = []
    for spec in peers:
        parts = spec.split(":", 2)
        if len(parts) != 3 or not _SLUG.match(parts[0]) or not re.match(r"^[A-Z][A-Z0-9_]*$", parts[1]):
            raise A2AError(f"--peer wants ID:ENV_NAME:TAILSCALE_LOGIN, got {spec!r}")
        entries.append(
            f"    - id: {parts[0]}\n      token_env: {parts[1]}\n"
            + (f"      tailscale_login: {parts[2]}\n" if parts[2] else "")
        )
    values = {"name": name, "port": port, "peers": "".join(entries).rstrip("\n")}
    for asset, dest in (("peer-agent.yaml.tmpl", "agent.yaml"),
                        ("peer-system-prompt.md.tmpl", "system-prompt.md"),
                        ("peer-launch.sh.tmpl", "launch.sh")):
        text = string.Template((ASSETS / asset).read_text("utf-8")).substitute(values)
        (target / dest).write_text(text, "utf-8")
        written.append(target / dest)
    (target / "launch.sh").chmod(0o755)
    share = target / "share"
    share.mkdir()
    (share / "README.md").write_text(
        (ASSETS / "share-README.md").read_text("utf-8"), "utf-8"
    )
    written.append(share / "README.md")
    return written


# ---------------------------------------------------------------------------- cli

def _print_findings(rows: list[tuple[str, bool, str]]) -> int:
    width = max(len(r[0]) for r in rows)
    for check, ok, detail in rows:
        print(f"{'ok  ' if ok else 'FAIL'}  {check:<{width}}  {detail}")
    return 0 if all(ok for _, ok, _ in rows) else 1


def main(argv: list[str] | None = None) -> int:
    argv = list(sys.argv[1:] if argv is None else argv)
    p = argparse.ArgumentParser(prog="a2a", description="Talk to other Bridges over A2A.")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("peers")
    c = sub.add_parser("card"); c.add_argument("target")
    a = sub.add_parser("ask"); a.add_argument("peer"); a.add_argument("question")
    a.add_argument("--context"); a.add_argument("--wait", type=float, default=0)
    a.add_argument("--json", action="store_true")
    g = sub.add_parser("get"); g.add_argument("peer"); g.add_argument("task_id")
    g.add_argument("--json", action="store_true")
    rq = sub.add_parser("request"); rq.add_argument("peer"); rq.add_argument("text")
    rq.add_argument("--subject", default=""); rq.add_argument("--wait", type=float, default=0)
    rq.add_argument("--json", action="store_true")
    ru = sub.add_parser("rules"); ru.add_argument("peer"); ru.add_argument("--json", action="store_true")
    pr = sub.add_parser("probe"); pr.add_argument("peer")
    pr.add_argument("--prompts", type=Path, default=ASSETS / "probe-prompts.yaml")
    n = sub.add_parser("new-agent"); n.add_argument("name")
    n.add_argument("--trust", choices=["public", "peer"], required=True)
    n.add_argument("--port", type=int, default=8015)
    n.add_argument("--peer", action="append", default=[])
    args = p.parse_args(argv)
    root = repo_root()
    try:
        if args.cmd == "peers":
            for peer_id, data in load_peers(root).items():
                print(f"{peer_id:<20} {data.get('auth', 'none'):<7} {data['card_url']}  {data.get('summary', '')}")
            return 0
        if args.cmd == "card":
            url, _ = resolve_target(args.target, root)
            return _print_findings([("card url", True, url), *check_card(fetch_card(url))])
        if args.cmd == "ask":
            url, peer = resolve_target(args.peer, root)
            token = with_token(peer, argv)
            task = ask(fetch_card(url), args.question, token=token, context_id=args.context, wait=args.wait)
            return print_task(task, args.json)
        if args.cmd in ("request", "rules"):
            url, peer = resolve_target(args.peer, root)
            card = fetch_card(url)
            require_skill(card, REQUEST_SKILL if args.cmd == "request" else POLICY_SKILL)
            token = with_token(peer, argv)
            if args.cmd == "request":
                meta = {"kind": "request", **({"subject": args.subject} if args.subject else {})}
                task = ask(card, args.text, token=token, wait=args.wait, nonblocking=True,
                           metadata={"bridge_request": meta})
            else:
                task = ask(card, "rules and history", token=token,
                           metadata={"bridge_request": {"kind": "policy"}})
            return print_task(task, args.json)
        if args.cmd == "get":
            url, peer = resolve_target(args.peer, root)
            token = with_token(peer, argv)
            task = get_task(fetch_card(url), args.task_id, token=token)
            if task is None:
                raise A2AError(f"the peer does not know task {args.task_id}")
            return print_task(task, args.json)
        if args.cmd == "probe":
            url, peer = resolve_target(args.peer, root)
            token = with_token(peer, argv)
            return _print_findings(probe(fetch_card(url), token, load_prompts(args.prompts)))
        if args.cmd == "new-agent":
            for path in new_agent(root, args.name, args.trust, args.port, args.peer):
                print(f"created  {path.relative_to(root)}")
            print(f"next: read skills/a2a/references/{'peer' if args.trust == 'peer' else 'public'}-agent.md")
            return 0
    except A2AError as exc:
        print(f"a2a: {exc}", file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    sys.exit(main())
