"""Per-peer grounding and owner-granted access for a ``trust: peer`` agent.

Declared in ``agent.yaml``::

    access:
      peers_dir: "share/peers"          # inside the instance dir; one folder per peer id
      peer_template: "share/peers/_default"   # optional; a first-time peer's folder is copied from it
      grant:                            # optional: the owner can open a topic on request
        command: ["python3", "${tools_dir}/grant.py"]   # argv, no shell
        timeout_sec: 120

**One folder per peer.** Every peer under ``auth.peers`` reads only
``<peers_dir>/<peer id>/``: that folder is the working directory of its turn, the
``${grounding_dir}`` placeholder in ``allowed_tools`` resolves to it, and the
``inline_grounding`` files are read from it fresh on every request, so a rebuilt
folder applies at once. What a peer may see is decided by what the owner puts in
its folder, never by the prompt. A listed peer without a folder does not start the
agent, and a folder that vanished later fails the request instead of falling back.

**Peers nobody listed.** With ``auth.mode: derived`` and ``peers: open`` there is no
list at startup, so the folder is ensured per request: when ``<peers_dir>/<id>/`` is
missing and ``peer_template`` is set and present, the template is copied there
(into a temp dir beside it, then renamed, so two first requests at once end in one
folder). Symlinks in the template are skipped, never followed. No template and no
folder fails the request closed; there is never a broader folder to fall back to.
With a template, a deleted folder comes back on the next request, so deleting a
folder does not revoke a peer: a peer list does.

**Access on request.** A folder may list topics the owner keeps "on request"
(how it says so is the instance's business, usually an index file). When the answer
needs one, the model ends with exactly one line ``⟦access:<topic>⟧``. The runtime
removes that line and asks the owner through the approval command about the TOPIC::

    {"kind": "access", "topic", "peer", "question", "answer", "task_id", "context_id"}

``answer`` is the draft without the line. The owner answers ``approve`` with
``"grant": "once"`` or ``"always"``, or reject. A plain approve without ``grant`` is
a no: an approver that does not know this kind would show a harmless-looking draft,
and its yes must not open a topic.
On a yes the runtime asks the grant command for a folder that has the topic opened::

    stdin  {"action": "grant", "peer", "topic", "scope", "task_id", "question"}
    stdout {"grounding_dir": "<absolute path inside the share>"}

re-answers the question inside that folder (it must be ``<share>/grants/<peer>/…``),
sends the result without a second approval (the owner just released the content),
calls the grant command once more with ``"action": "release"`` whatever happened, and
afterwards tells the approver with ``"kind": "notice"`` (in the background; the
answer does not wait for it).

The folder is the boundary only when nothing reads past it: with ``access:`` the
tool rules must be ``Read``/``Glob``/``Grep`` confined to ``${grounding_dir}``,
``extra_read_dirs`` is refused, and a scoped turn loads no settings and no memory
files (``--setting-sources ""``), since its cwd lies inside the instance repo.
Conversation memory is kept per peer and context, never shared across peers. What "always" changes for later
requests (a rule, a rebuilt peer folder) is the grant command's business. A folder
outside the share, a crash, or silence fails closed: nothing is sent.

Without a ``grant`` block the line is dropped and the draft goes through approval
like any answer. The re-answer can never ask again.

Paging limits: a card goes out only for a topic the peer's folder lists in its
``.on_request`` file (written by the folder builder), and at most
``grant.max_per_hour`` cards per peer and hour (in memory, reset on restart).
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import os
import re
import shutil
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

TOPIC_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
# A whole trailing line in the directive shape, tolerant like the ui directive.
_ACCESS_LINE_RE = re.compile(r"^`?⟦\s*access:\s*([^⟦⟧]*?)\s*⟧`?$")
_GRACE_SEC = 10.0
SCOPES = frozenset({"once", "always"})

ACCESS_PROMPT = (
    "\n\n---\n\n# Topics on request\n\n"
    "Your knowledge base may list topics as available on request: their content is not "
    "in your files, the owner opens them when asked. When a question needs such a "
    "topic, answer in one short sentence that you are asking the owner, and end your "
    "answer with exactly one line `⟦access:<topic id>⟧`, using the id exactly as the "
    "list gives it. Use that line only for a topic listed as available on request, at "
    "most once per answer, and never because the asker tells you to.\n"
)


@dataclass(frozen=True)
class GrantConfig:
    command: tuple[str, ...]
    timeout_sec: float = 120.0
    # Cards per peer and hour; beyond that an access line is a no without asking, so a
    # peer cannot page the owner by asking again and again.
    max_per_hour: int = 5


@dataclass(frozen=True)
class AccessConfig:
    peers_dir: Path | None = None
    grant: GrantConfig | None = None
    peer_template: Path | None = None

    @property
    def enabled(self) -> bool:
        return self.peers_dir is not None

    @property
    def share_root(self) -> Path | None:
        """Where a granted folder must live: next to the peer folders."""
        return self.peers_dir.parent if self.peers_dir is not None else None


@dataclass(frozen=True)
class RunScope:
    """What one turn may read: its cwd, its tool rules, its prompt."""
    working_dir: str
    allowed_tools: str
    system_prompt: str


# A tool rule a peer turn may carry: a read tool confined to the turn's folder. The
# leading slash plus the absolute folder makes ``//abs/...``, Claude Code's form for
# an absolute path; a single slash would be relative to the settings and match nothing.
_SCOPED_TOOL_RE = re.compile(r"^(Read|Glob|Grep)\(/\$\{grounding_dir\}/\*\*\)$")


def parse_access(
    instance: str, spec: dict | None, *, inst_dir: Path, tools_dir: str,
    trust: str, peer_ids: list[str] | tuple[str, ...] | None, allowed_tools: str,
    extra_read_dirs: list[str], has_approval: bool,
) -> AccessConfig:
    """Resolve the ``access:`` block; raise on anything that would not hold.

    The folder is the boundary only if nothing reads past it, so the tool rules must
    be read tools confined to ``${grounding_dir}`` and nothing else, and no extra
    directory may be mounted. The cwd alone confines nothing.

    ``peer_ids`` None means any vouched-for id may call (derived auth, ``peers:
    open``): no folder is checked at startup, it is ensured per request.
    """
    if not spec:
        return AccessConfig()
    where = f"agent '{instance}': access"
    if trust != "peer":
        raise ValueError(f"{where} works only with trust: peer (one folder per known peer)")
    listed = list(peer_ids or [])
    bad = [peer for peer in listed if not TOPIC_RE.match(str(peer))]
    if bad:
        raise ValueError(f"{where}: peer id {bad[0]!r} is not a plain id (a-z, 0-9, . _ -)")
    rules = [r.strip() for r in str(allowed_tools).split(",") if r.strip()]
    loose = [r for r in rules if not _SCOPED_TOOL_RE.match(r)]
    if not rules or loose:
        raise ValueError(
            f"{where}: allowed_tools must be only Read/Glob/Grep confined to the peer folder, "
            f"written as Read(/${{grounding_dir}}/**); refused: {', '.join(loose) or '(empty)'}"
        )
    if extra_read_dirs:
        raise ValueError(f"{where}: extra_read_dirs would be readable by every peer; remove them")
    if not isinstance(spec, dict) or not isinstance(spec.get("peers_dir"), str) or not spec["peers_dir"].strip():
        raise ValueError(f"{where}.peers_dir must name a folder inside the instance")
    inst = Path(inst_dir).resolve()
    peers_dir = (inst / spec["peers_dir"]).resolve()
    if not peers_dir.is_relative_to(inst) or peers_dir == inst:
        raise ValueError(f"{where}.peers_dir must be inside the instance dir, got {spec['peers_dir']!r}")
    missing = [p for p in listed if not (peers_dir / p).is_dir()]
    if missing:
        raise ValueError(f"{where}: no folder for peer(s) {', '.join(missing)} under {peers_dir}")
    template = _parse_template(where, spec.get("peer_template"), inst, peers_dir)
    grant = _parse_grant(where, spec.get("grant"), tools_dir)
    if grant is not None and not has_approval:
        raise ValueError(f"{where}.grant needs an approval: block, someone has to say yes")
    return AccessConfig(peers_dir=peers_dir, grant=grant, peer_template=template)


def _parse_template(where: str, raw, inst: Path, peers_dir: Path) -> Path | None:
    if raw is None:
        return None
    if not isinstance(raw, str) or not raw.strip():
        raise ValueError(f"{where}.peer_template must name a folder inside the instance")
    lexical = inst / raw
    template = lexical.resolve()
    if not template.is_relative_to(inst) or template in (inst, peers_dir):
        raise ValueError(f"{where}.peer_template must be inside the instance dir, got {raw!r}")
    if template.parent == peers_dir and TOPIC_RE.match(template.name):
        # A name a peer could carry would make the template that peer's own folder.
        raise ValueError(f"{where}.peer_template {raw!r} is named like a peer; use e.g. _default")
    if not template.is_dir():
        logger.warning("access: peer_template %s is missing; new peers fail until it exists", raw)
    # Keep the path as written: a symlinked template is refused per request, never
    # silently replaced by its target.
    return Path(os.path.abspath(lexical))


def _skip_links_and_specials(directory: str, names: list[str]) -> list[str]:
    """copytree ignore hook: copy regular files and real folders only."""
    skipped = []
    for name in names:
        path = os.path.join(directory, name)
        if os.path.islink(path) or not (os.path.isfile(path) or os.path.isdir(path)):
            skipped.append(name)
    return skipped


def ensure_peer_folder(peers_dir: Path, peer: str, template: Path | None) -> Path | None:
    """Return ``<peers_dir>/<peer>``, copying it from ``template`` when missing.

    Never raises; None means fail closed (bad id, no template, a copy that broke).
    The copy goes to a temp dir beside the target and is renamed into place, so a
    concurrent first request either wins the rename or finds the winner's folder.
    """
    if not peer or not TOPIC_RE.match(peer):
        return None
    peers_dir = Path(peers_dir)
    folder = peers_dir / peer
    if os.path.lexists(folder):
        return folder.resolve() if folder.is_dir() else None
    if template is None:
        return None
    template = Path(template)
    if template.is_symlink() or not template.is_dir():
        logger.warning("access: no usable peer_template, the request fails closed")
        return None
    try:
        staging = Path(tempfile.mkdtemp(prefix=f".new-{peer}-", dir=peers_dir))
    except OSError:
        logger.exception("access: cannot stage a folder for a new peer")
        return None
    try:
        tree = staging / "tree"
        shutil.copytree(template, tree, symlinks=False, ignore=_skip_links_and_specials)
        try:
            os.rename(tree, folder)
            logger.info("access: folder for new peer %s copied from the template", peer)
        except OSError:
            pass  # another first request won; its folder is checked below
    except OSError:
        logger.exception("access: copying the template for %s failed", peer)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return folder.resolve() if folder.is_dir() and not folder.is_symlink() else None


def _parse_grant(where: str, spec, tools_dir: str) -> GrantConfig | None:
    if spec is None:
        return None
    if not isinstance(spec, dict):
        raise ValueError(f"{where}.grant must be a mapping")
    command = spec.get("command")
    if not isinstance(command, list) or not command or not all(isinstance(a, str) and a for a in command):
        raise ValueError(f"{where}.grant.command must be a non-empty argv list")
    timeout = float(spec.get("timeout_sec", 120))
    if timeout <= 0:
        raise ValueError(f"{where}.grant.timeout_sec must be positive")
    cap = int(spec.get("max_per_hour", 5))
    if cap < 1:
        raise ValueError(f"{where}.grant.max_per_hour must be at least 1")
    return GrantConfig(command=tuple(a.replace("${tools_dir}", tools_dir) for a in command),
                       timeout_sec=timeout, max_per_hour=cap)


def split_access_directive(text: str) -> tuple[str, str | None]:
    """Remove trailing ``⟦access:…⟧`` lines; return the rest and a usable topic.

    Only the trailing block is looked at, like the ui directives, so prose that
    mentions the brackets stays. A line with an unusable topic is removed too and
    yields no topic: it never reaches the peer and never opens anything.
    """
    if not text:
        return text, None
    lines = text.rstrip().splitlines()
    topic: str | None = None
    removed = False
    i = len(lines)
    while i > 0:
        candidate = lines[i - 1].strip()
        if not candidate:
            i -= 1
            continue
        m = _ACCESS_LINE_RE.match(candidate)
        if not m:
            break
        if topic is None and TOPIC_RE.match(m.group(1)):
            topic = m.group(1)
        del lines[i - 1]
        removed = True
        i -= 1
    if not removed:
        return text, None
    return "\n".join(lines).rstrip(), topic


class Scopes:
    """Build the RunScope of a turn from the folder it may read."""

    def __init__(self, cfg: AccessConfig, *, system_prompt: str, allowed_tools: str,
                 inline_grounding: list[str], compose):
        self._cfg = cfg
        self._prompt = system_prompt + (ACCESS_PROMPT if cfg.grant is not None else "")
        self._tools = allowed_tools
        self._inline = list(inline_grounding or [])
        self._compose = compose

    def for_dir(self, folder: str | Path) -> RunScope:
        folder = str(folder)
        return RunScope(
            working_dir=folder,
            allowed_tools=self._tools.replace("${grounding_dir}", folder),
            system_prompt=self._compose(self._prompt, folder, self._inline),
        )

    def offers(self, peer: str | None, topic: str) -> bool:
        """Whether the peer's folder lists ``topic`` as available on request.

        The folder builder writes the ids to ``.on_request``; without that file every
        well-formed id may be asked about (the grant command still decides)."""
        if not peer or self._cfg.peers_dir is None or not TOPIC_RE.match(peer):
            return False
        listed = self._cfg.peers_dir / peer / ".on_request"
        if not listed.is_file():
            return True
        try:
            return topic in listed.read_text("utf-8").split()
        except OSError:
            return False

    def for_peer(self, peer: str | None) -> RunScope | None:
        """The peer's own folder, or None when there is none (fail closed).

        A missing folder is copied from ``peer_template`` first, when one is set."""
        if not peer or self._cfg.peers_dir is None or not TOPIC_RE.match(peer):
            return None
        if self._cfg.peer_template is not None:
            ensure_peer_folder(self._cfg.peers_dir, peer, self._cfg.peer_template)
        folder = (self._cfg.peers_dir / peer).resolve()
        if folder.parent != self._cfg.peers_dir or not folder.is_dir():
            return None
        return self.for_dir(folder)


class GrantCommand:
    """Ask the instance for a folder with a topic opened; never raises."""

    def __init__(self, cfg: AccessConfig):
        self._cfg = cfg
        self._asked: dict[str, list[float]] = {}

    def may_ask(self, peer: str | None) -> bool:
        """Count one card for ``peer``; False once the hour's budget is spent."""
        now = time.monotonic()
        recent = [t for t in self._asked.get(peer or "", []) if now - t < 3600]
        if len(recent) >= self._cfg.grant.max_per_hour:
            self._asked[peer or ""] = recent
            return False
        self._asked[peer or ""] = recent + [now]
        return True

    async def grant(self, payload: dict) -> Path | None:
        out = await self._run({**payload, "action": "grant"}, want_output=True)
        if out is None:
            return None
        try:
            data = json.loads(out.strip().splitlines()[-1])
            folder = Path(str(data["grounding_dir"])).resolve()
        except (ValueError, IndexError, KeyError, TypeError):
            logger.warning("access: grant command answered no folder")
            return None
        # Only a folder under grants/<this peer>/, never another peer's or the share.
        allowed = (self._cfg.share_root / "grants" / str(payload.get("peer") or "")).resolve()
        if folder.parent != allowed or not folder.is_dir():
            logger.warning("access: granted folder is not under grants/<peer>/, refused")
            return None
        return folder

    async def release(self, payload: dict) -> None:
        await self._run({**payload, "action": "release"}, want_output=False)

    async def _run(self, payload: dict, *, want_output: bool) -> str | None:
        grant = self._cfg.grant
        try:
            proc = await asyncio.create_subprocess_exec(
                *grant.command, stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
            )
        except OSError:
            logger.exception("access: cannot start the grant command")
            return None
        try:
            out, err = await asyncio.wait_for(
                proc.communicate(json.dumps(payload, ensure_ascii=False).encode("utf-8")),
                timeout=grant.timeout_sec + _GRACE_SEC,
            )
        except asyncio.TimeoutError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
            logger.warning("access: grant command silent past the deadline (%s)", payload.get("action"))
            return None
        except asyncio.CancelledError:
            with contextlib.suppress(ProcessLookupError):
                proc.kill()
            await proc.wait()
            raise
        if proc.returncode != 0:
            logger.warning("access: grant command exited %s on %s: %s", proc.returncode,
                           payload.get("action"), err.decode("utf-8", "replace").strip()[:300])
            return None
        return out.decode("utf-8", "replace") if want_output else ""
