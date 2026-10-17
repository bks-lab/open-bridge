#!/usr/bin/env python3
"""Build one share folder per peer from an access file, and grant topics on request.

A ``trust: peer`` agent with ``access:`` reads only ``<share>/peers/<peer>/`` (see
agents/_runtime/access.py). This program decides what goes in there. The access file
says, per peer, which topics it sees and how deep; the program renders them::

    schema_version: 1
    sources: ["work/tasks/*/STATUS.md", "work/streams/*/STATUS.md"]   # topics from STATUS.md
    next_step_headings: ["next step"]   # optional: the heading ``status`` carries
    peers:
      alice:                         # = auth.peers[].id
        default: none                # what an unmatched topic gets
        rules:                       # first match wins
          - match: {context: [acme]}
            level: details
          - match: {path: ["infra/remotes/bigpc.yaml"]}   # any file is a topic too
            level: details
            only: [name, hardware, services.slug]         # YAML: keep just these keys
            exclude: [some-value]                         # YAML: drop list items with this value
          - match: {context: [labs]}
            level: on_request        # listed by id, opened when the owner says yes
            grant_level: details

Levels: ``none`` (absent everywhere), ``on_request`` (id and a one-line summary in
the index, content only after a grant), ``status`` (headline, state, next step),
``details`` (the text, a list of attachments), ``files`` (details plus copies of
``deliverables/``). A STATUS.md overrides every rule with ``share: {<peer>: <level>}``
in its frontmatter, and a section opened by ``<!-- share: private -->`` never leaves,
whatever the level. In YAML files, keys that name an address, an account or a
secret are always dropped and addresses inside values are masked, ``only:`` or not.

Grants: the agent's grant command (``access.grant.command``) calls ``grant`` with the
runtime's JSON on stdin. ``once`` renders a folder under ``<share>/grants/<task>/``
that ``release`` deletes again; ``always`` records the grant in
``access.grants.yaml`` next to the access file (machine-written; to revoke, delete
the entry and run ``build``, the folder keeps the topic until then) and rebuilds the peer's folder; the re-answer itself still runs in its own
folder under ``<share>/grants/<peer>/<task>/``. Only a topic that resolves to
``on_request`` for that peer can be granted, whichever rule, default or STATUS
override put it there. A topic named only by a path rule exists for the peers whose
rules match it, never through another peer's ``default``.

Usage::

    share_build.py build --config access.yaml --root <repo> --out <share>
    share_build.py grant --config access.yaml --root <repo> --out <share>   # JSON on stdin
"""
from __future__ import annotations

import argparse
import fcntl
import fnmatch
import json
import os
import re
import shutil
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import yaml

LEVELS = ("none", "on_request", "status", "details", "files")
_RANK = {lvl: i for i, lvl in enumerate(LEVELS)}
_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}$")
_TASK_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")

# YAML keys that name where something is or how to get in. Dropped at any depth.
# Matched against the key normalised to snake case (``macAddress`` → ``mac_address``,
# ``ssh-user`` → ``ssh_user``), so every spelling of a name is caught.
_SENSITIVE_KEY = re.compile(
    r"(^|_)(ip|ips|ipv4|ipv6|mac|macs|host|hostname|hosts|user|users|username|login|ssh|rdp|"
    r"password|passwd|secret|secrets|token|tokens|credential|credentials|key|keys|apikey|"
    r"gateway|port|ports|url|urls|uri|command|commands|env|path|paths|dir|dirs|address|"
    r"addresses|email|mail|tenant|subscription|iban|bic|phone|mobile|tel|account|pin)($|_)"
    r"|_ref$|^ref$",
)
_GRANT_TTL_SEC = 2 * 3600       # a one-time grant folder older than this is swept
_MASKS = (
    (re.compile(r"\b[a-z][a-z0-9+.-]*://\S+", re.IGNORECASE), "[reference]"),
    (re.compile(r"\b[\w.+-]+@[\w-]+(?:\.[\w-]+)+\b"), "[address]"),
    (re.compile(r"\b(?:ghp|gho|ghs|github_pat|xox[abprs]|sk|pk|rk)[-_][A-Za-z0-9_-]{12,}"), "[secret]"),
    (re.compile(r"\b[\w-]+(?:\.[\w-]+)*\.(?:ts\.net|local|lan|internal|home\.arpa)\b", re.IGNORECASE), "[address]"),
    # IPv4-mapped first (``::ffff:10.1.2.3``), then IPv4, then the rest of IPv6, so no
    # pattern leaves octets of another behind.
    (re.compile(r"(?<![\w:])::ffff:(?:\d{1,3}\.){3}\d{1,3}\b", re.IGNORECASE), "[address]"),
    (re.compile(r"\b(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?\b"), "[address]"),
    (re.compile(r"(?<![\w:])(?=[0-9a-f:]*(?:[a-f]|::))(?:[0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}(?:/\d{1,3})?(?![\w:])(?!\.\d)",
                re.IGNORECASE), "[address]"),
    (re.compile(r"\b[0-9A-Fa-f]{2}(?:[:-][0-9A-Fa-f]{2}){5}\b"), "[address]"),
    (re.compile(r"\b[A-Za-z]:\\[^\s,;)]*"), "[path]"),
    (re.compile(r"(?<![\w.])/(?:Users|home|opt|var|etc|private|Volumes)/[^\s,;)]*"), "[path]"),
    (re.compile(r"(?<![\w])~/[^\s,;)]*"), "[path]"),
)
_PRIVATE_MARK = re.compile(r"<!--\s*share:\s*private\s*-->", re.IGNORECASE)
_HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
# The heading whose section ``status`` carries; an access file may name its own
# (``next_step_headings``) for STATUS.md files written in another language.
_DEFAULT_NEXT_STEP = ("next step", "next steps")


def _next_step_re(access: dict) -> re.Pattern:
    names = access.get("next_step_headings") or _DEFAULT_NEXT_STEP
    return re.compile(r"^(" + "|".join(re.escape(str(n)) for n in names) + r")\b", re.IGNORECASE)
_STATUS_KEYS = ("slug", "status", "headline", "last_updated", "context", "priority", "type")


# --- topics -------------------------------------------------------------------------

@dataclass
class Topic:
    id: str
    path: Path            # absolute
    rel: str              # repo-relative, forward slashes
    kind: str             # status | yaml | markdown
    meta: dict = field(default_factory=dict)
    body: str = ""
    data: object = None
    # True when only a path rule named it: then it exists for the peers whose rules
    # match it, never through someone's ``default``.
    by_path_only: bool = False


def _split_frontmatter(text: str) -> tuple[dict, str]:
    lines = text.splitlines()
    starts = [i for i, line in enumerate(lines) if line.strip() == "---"]
    if len(starts) >= 2 and all(not l.strip() or l.lstrip().startswith("#") for l in lines[:starts[0]]):
        try:
            meta = yaml.safe_load("\n".join(lines[starts[0] + 1:starts[1]])) or {}
        except yaml.YAMLError:
            meta = {}
        return (meta if isinstance(meta, dict) else {}), "\n".join(lines[starts[1] + 1:])
    return {}, text


def _load_topic(path: Path, root: Path, topic_id: str | None = None) -> Topic | None:
    rel = path.relative_to(root).as_posix()
    text = path.read_text("utf-8")
    if path.name == "STATUS.md":
        meta, body = _split_frontmatter(text)
        return Topic(id=topic_id or str(meta.get("slug") or path.parent.name), path=path, rel=rel,
                     kind="status", meta=meta, body=body)
    if path.suffix in (".yaml", ".yml"):
        data = yaml.safe_load(text)
        return Topic(id=topic_id or path.stem, path=path, rel=rel, kind="yaml", data=data,
                     meta={"summary": (data or {}).get("summary") or (data or {}).get("description") or ""}
                     if isinstance(data, dict) else {})
    if path.suffix == ".md":
        meta, body = _split_frontmatter(text)
        return Topic(id=topic_id or path.stem, path=path, rel=rel, kind="markdown", meta=meta, body=body)
    return None


def collect_topics(access: dict, root: Path) -> dict[str, Topic]:
    """Every topic the access file can talk about: STATUS.md sources plus named paths."""
    found: dict[str, Topic] = {}
    paths: list[tuple[Path, bool]] = []
    for pattern in access.get("sources") or []:
        paths += [(p, False) for p in sorted(root.glob(pattern))]
    sourced = {p for p, _ in paths}
    for peer in (access.get("peers") or {}).values():
        for rule in (peer or {}).get("rules") or []:
            for pattern in (rule.get("match") or {}).get("path") or []:
                paths += [(p, True) for p in sorted(root.glob(pattern)) if p not in sourced]
    for path, by_path in paths:
        if not path.is_file():
            continue
        topic = _load_topic(path, root)
        if topic is not None:
            topic.by_path_only = by_path
        if topic is None or not _ID_RE.match(topic.id):
            continue
        if topic.id in found and found[topic.id].path != path:
            print(f"share_build: topic id {topic.id!r} used twice, keeping {found[topic.id].rel}",
                  file=sys.stderr)
            continue
        found[topic.id] = topic
    return found


# --- levels -------------------------------------------------------------------------

def _check_level(value, where: str) -> str:
    if value not in _RANK:
        raise ValueError(f"{where}: unknown level {value!r} (one of {', '.join(LEVELS)})")
    return value


def validate(access: dict) -> None:
    if not isinstance(access, dict) or not isinstance(access.get("peers"), dict):
        raise ValueError("access file needs a peers: mapping")
    for pid, peer in access["peers"].items():
        if not _ID_RE.match(str(pid)):
            raise ValueError(f"peer id {pid!r} is not a plain id")
        peer = peer or {}
        _check_level(peer.get("default", "none"), f"peers.{pid}.default")
        for i, rule in enumerate(peer.get("rules") or []):
            where = f"peers.{pid}.rules[{i}]"
            _check_level(rule.get("level"), where)
            if rule.get("level") == "on_request":
                grant = _check_level(rule.get("grant_level", "details"), where + ".grant_level")
                if _RANK[grant] < _RANK["status"]:
                    raise ValueError(f"{where}.grant_level must be status, details or files")
            if not isinstance(rule.get("match"), dict) or not rule["match"]:
                raise ValueError(f"{where}.match must name context, mandant, path or topic")


def _matches(match: dict, topic: Topic) -> bool:
    for key, wanted in match.items():
        wanted = [str(w) for w in (wanted if isinstance(wanted, list) else [wanted])]
        if key == "path":
            if not any(fnmatch.fnmatch(topic.rel, w) for w in wanted):
                return False
        elif key == "topic":
            if topic.id not in wanted:
                return False
        elif key in ("context", "mandant"):
            have = topic.meta.get(key)
            have = [str(h) for h in (have if isinstance(have, list) else [have])] if have else []
            if not set(have) & set(wanted):
                return False
        else:
            return False                       # an unknown key never matches (fail closed)
    return True


def resolve(access: dict, grants: list[dict], peer_id: str, topic: Topic) -> tuple[str, dict]:
    """The level ``peer_id`` gets for ``topic``, and the rule that decided it."""
    level, rule = _base_level(access, peer_id, topic)
    if level == "on_request":
        for g in grants:
            if g.get("peer") == peer_id and g.get("topic") == topic.id:
                return _check_level(g.get("level"), "grant"), rule
    return level, rule


def _base_level(access: dict, peer_id: str, topic: Topic) -> tuple[str, dict]:
    override = topic.meta.get("share") if topic.kind == "status" else None
    if isinstance(override, dict) and peer_id in override:
        return _check_level(override[peer_id], f"{topic.rel} share.{peer_id}"), {}
    peer = access["peers"].get(peer_id) or {}
    rule = next((r for r in peer.get("rules") or [] if _matches(r["match"], topic)), None)
    if rule is not None:
        return rule["level"], rule
    if topic.by_path_only:
        return "none", {}
    return peer.get("default", "none"), {}


# --- rendering ----------------------------------------------------------------------

def mask(text: str) -> str:
    for pattern, replacement in _MASKS:
        text = pattern.sub(replacement, text)
    return text


def _blocks(body: str) -> list[tuple[int, list[str]]]:
    """Split into (heading depth, lines) blocks; depth 0 is the text before any heading.

    A ``#`` line inside a fenced code block is not a heading.
    """
    blocks: list[tuple[int, list[str]]] = [(0, [])]
    fenced = False
    for line in body.splitlines():
        if line.lstrip().startswith(("```", "~~~")):
            fenced = not fenced
        heading = None if fenced else _HEADING.match(line)
        if heading:
            blocks.append((len(heading.group(1)), [line]))
        else:
            blocks[-1][1].append(line)
    return blocks


def _drop_private_sections(body: str) -> str:
    """Remove every section marked ``<!-- share: private -->``, with its subsections.

    The marker belongs to the heading right after it (only blank lines between), or
    else to the section it stands in, wherever in that section, the heading line
    included. A marker directly under a line of text and directly above a heading
    is ambiguous and hides both sections. Marked text before the first heading
    drops that text.
    """
    blocks = _blocks(body)
    private = [False] * len(blocks)
    for i, (_depth, lines) in enumerate(blocks):
        for j, line in enumerate(lines):
            if not _PRIVATE_MARK.search(line):
                continue
            rest = lines[j + 1:]
            before = lines[j - 1] if j > 0 else ""
            if i + 1 < len(blocks) and all(not l.strip() for l in rest) and not _HEADING.match(line):
                private[i + 1] = True          # marker right before the next heading
                if before.strip() and not _HEADING.match(before):
                    # Glued to the text above it as well: hide both, never guess.
                    private[i] = True
            else:
                private[i] = True
    out: list[str] = []
    skip_depth = None
    for (depth, lines), marked in zip(blocks, private):
        if skip_depth is not None and depth > skip_depth:
            continue
        skip_depth = None
        if marked:
            skip_depth = depth if depth > 0 else None
            continue
        out.extend(l for l in lines if not _PRIVATE_MARK.search(l))
    return "\n".join(out).strip()


def _section(body: str, title_re: re.Pattern) -> str:
    lines = body.splitlines()
    for i, line in enumerate(lines):
        h = _HEADING.match(line)
        if h and title_re.match(h.group(2).strip()):
            depth, chunk = len(h.group(1)), [line]
            for nxt in lines[i + 1:]:
                h2 = _HEADING.match(nxt)
                if h2 and len(h2.group(1)) <= depth:
                    break
                chunk.append(nxt)
            return "\n".join(chunk).strip()
    return ""


def _snake(key) -> str:
    key = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", "_", str(key))
    return re.sub(r"[-\s.]+", "_", key).lower()


def _only_tree(only: list[str] | None) -> dict | None:
    """``["a", "b.c"]`` → ``{"a": None, "b": {"c": None}}``; None keeps everything."""
    if only is None:
        return None
    tree: dict = {}
    for dotted in only:
        node = tree
        parts = str(dotted).split(".")
        for i, part in enumerate(parts):
            if i == len(parts) - 1:
                node[part] = None            # keep the whole subtree
            else:
                child = node.get(part, {})
                if child is None:            # already kept whole
                    break
                node[part] = child
                node = child
    return tree


def _clean_yaml(data, keep: dict | None = None, exclude: frozenset = frozenset()):
    """Drop sensitive keys and excluded values, mask addresses; ``keep`` limits keys."""
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            if _SENSITIVE_KEY.search(_snake(k)):
                continue
            if keep is not None and k not in keep:
                continue
            out[k] = _clean_yaml(v, keep.get(k) if keep is not None else None, exclude)
        return out
    if isinstance(data, list):
        return [_clean_yaml(v, keep, exclude) for v in data
                if not (isinstance(v, str) and v in exclude)]
    if isinstance(data, str):
        return mask(data)
    return data


def _attachments(topic: Topic) -> list[Path]:
    d = topic.path.parent / "deliverables"
    if topic.kind != "status" or not d.is_dir():
        return []
    return sorted(p for p in d.rglob("*") if p.is_file() and not p.name.startswith("."))


def render(topic: Topic, level: str, rule: dict, next_step: re.Pattern | None = None) -> str:
    head = [f"# {topic.id}", "", f"Level: {level}", ""]
    if topic.kind == "status":
        meta = {k: topic.meta[k] for k in _STATUS_KEYS if k in topic.meta}
        head += [f"- {k}: {mask(str(v))}" for k, v in meta.items()] + [""]
        body = mask(_drop_private_sections(topic.body))
        if level == "status":
            step = _section(body, next_step or _next_step_re({}))
            return "\n".join(head + ([step] if step else [])).strip() + "\n"
        parts = head + [body]
        files = _attachments(topic)
        if files:
            parts += ["", "## Attachments", ""]
            parts += [f"- {mask(p.relative_to(topic.path.parent).as_posix())}" for p in files]
        return "\n".join(parts).strip() + "\n"
    if topic.kind == "yaml":
        data = topic.data
        if level == "status" and isinstance(data, dict):
            data = {k: v for k, v in data.items() if not isinstance(v, (dict, list))}
        cleaned = _clean_yaml(data, _only_tree(rule.get("only")),
                              frozenset(str(x) for x in rule.get("exclude") or []))
        dumped = yaml.safe_dump(cleaned, allow_unicode=True, sort_keys=False).strip()
        return "\n".join(head + ["```yaml", dumped, "```"]).strip() + "\n"
    body = _drop_private_sections(topic.body)
    if level == "status":
        body = body.split("\n\n")[0] if body else ""
    return "\n".join(head + [mask(body)]).strip() + "\n"


def _summary(topic: Topic) -> str:
    text = topic.meta.get("headline") or topic.meta.get("summary") or ""
    return mask(" ".join(str(text).split()))[:160]


def build_peer(access: dict, grants: list[dict], topics: dict[str, Topic], peer_id: str,
               folder: Path, *, extra: dict[str, str] | None = None) -> None:
    """Write ``folder`` from scratch; ``extra`` lifts topics (id → level) for a grant."""
    staging = Path(tempfile.mkdtemp(prefix=".build-", dir=folder.parent))
    try:
        visible, on_request = [], []
        for topic in sorted(topics.values(), key=lambda t: t.id):
            level, rule = resolve(access, grants, peer_id, topic)
            if extra and topic.id in extra and level == "on_request":
                level = extra[topic.id]
            if level == "none":
                continue
            if level == "on_request":
                on_request.append(topic)
                continue
            (staging / "topics").mkdir(exist_ok=True)
            (staging / "topics" / f"{topic.id}.md").write_text(
                render(topic, level, rule, _next_step_re(access)), "utf-8")
            if level == "files":
                for src in _attachments(topic):
                    dst = staging / "topics" / topic.id / src.relative_to(topic.path.parent / "deliverables")
                    dst.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(src, dst)
            visible.append((topic, level))
        index = ["# Index", "", "Topics you can read, each in topics/<id>.md:", ""]
        index += [f"- {t.id} ({lvl}): {_summary(t)}" for t, lvl in visible] or ["- (none)"]
        if on_request:
            index += ["", "## Available on request", "",
                      "Not in your files. The owner opens one when asked:", ""]
            index += [f"- {t.id}: {_summary(t)}" for t in on_request]
        (staging / "index.md").write_text("\n".join(index) + "\n", "utf-8")
        # Swap, then delete: a turn running in the old folder loses it only for the
        # moment between the two renames, never for the whole rebuild.
        old = None
        if folder.exists():
            old = Path(tempfile.mkdtemp(prefix=f".old-{folder.name}-", dir=folder.parent)) / "x"
            folder.rename(old)
        staging.rename(folder)
        if old is not None:
            shutil.rmtree(old.parent, ignore_errors=True)
    finally:
        if staging.exists():
            shutil.rmtree(staging)


def _load(config: Path) -> tuple[dict, list[dict]]:
    access = yaml.safe_load(config.read_text("utf-8")) or {}
    validate(access)
    grants_path = config.parent / "access.grants.yaml"
    grants = []
    if grants_path.exists():
        grants = (yaml.safe_load(grants_path.read_text("utf-8")) or {}).get("grants") or []
    return access, grants


def build(config: Path, *, root: Path, out: Path) -> None:
    # Under the same lock as grant: a build that read old grants must not swap a stale
    # folder in after an "always" grant rebuilt it.
    with _locked(config):
        access, grants = _load(config)
        topics = collect_topics(access, root)
        peers_dir = out / "peers"
        peers_dir.mkdir(parents=True, exist_ok=True)
        for peer_id in access["peers"]:
            build_peer(access, grants, topics, peer_id, peers_dir / peer_id)
        for stale in peers_dir.iterdir():
            if not stale.is_dir():
                continue
            leftover = stale.name.startswith((".old-", ".build-"))
            if leftover or (stale.name not in access["peers"] and not stale.name.startswith(".")):
                shutil.rmtree(stale, ignore_errors=True)
        _sweep_grants(out)


def _sweep_grants(out: Path) -> None:
    """Delete one-time grant folders a crash left behind (older than the TTL)."""
    grants = out / "grants"
    if not grants.is_dir():
        return
    cutoff = datetime.now(timezone.utc).timestamp() - _GRANT_TTL_SEC
    for peer_dir in grants.iterdir():
        if not peer_dir.is_dir():
            continue
        for folder in peer_dir.iterdir():
            try:
                if folder.is_dir() and folder.stat().st_mtime < cutoff:
                    shutil.rmtree(folder, ignore_errors=True)
            except OSError:
                continue


# --- grants -------------------------------------------------------------------------

def grant(config: Path, *, root: Path, out: Path, request: dict) -> dict:
    """Handle one runtime call; raise on anything that must not open."""
    action = request.get("action")
    task_id = str(request.get("task_id") or "")
    peer_id = str(request.get("peer") or "")
    if not _TASK_RE.match(task_id):
        raise ValueError(f"task id {task_id!r} is not a plain id")
    if not _ID_RE.match(peer_id):
        raise ValueError(f"peer id {peer_id!r} is not a plain id")
    folder = out / "grants" / peer_id / task_id
    if action == "release":
        if folder.is_dir():
            shutil.rmtree(folder)
        return {}
    if action != "grant":
        raise ValueError(f"unknown action {action!r}")
    topic_id, scope = str(request.get("topic") or ""), request.get("scope")
    if scope not in ("once", "always"):
        raise ValueError("unknown scope")
    with _locked(config):
        access, grants = _load(config)
        if peer_id not in access["peers"]:
            raise ValueError(f"unknown peer {peer_id!r}")
        topics = collect_topics(access, root)
        topic = topics.get(topic_id)
        if topic is None:
            raise ValueError(f"no topic {topic_id!r}")
        # Eligibility from the rules alone, so granting again (or once after always)
        # is the same yes, not a refusal.
        level, rule = _base_level(access, peer_id, topic)
        if level != "on_request":
            raise ValueError(f"{topic_id!r} is not available on request for {peer_id!r}")
        granted_level = rule.get("grant_level", "details")
        if scope == "always":
            grants = [g for g in grants if not (g.get("peer") == peer_id and g.get("topic") == topic_id)]
            grants.append({"peer": peer_id, "topic": topic_id, "level": granted_level,
                           "since": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                           "by": str(request.get("by") or "owner")})
            _write_grants(config, grants)
            build_peer(access, grants, topics, peer_id, out / "peers" / peer_id)
        # The re-answer always runs in a folder of its own, so it never depends on the
        # peer folder being swapped under it; release deletes it again.
        folder.parent.mkdir(parents=True, exist_ok=True)
        build_peer(access, grants, topics, peer_id, folder, extra={topic_id: granted_level})
    return {"grounding_dir": str(folder.resolve())}


class _locked:
    """An exclusive lock next to the access file, for read-modify-write of grants."""

    def __init__(self, config: Path):
        self._path = config.parent / ".access.lock"

    def __enter__(self):
        self._fh = open(self._path, "w")
        fcntl.flock(self._fh, fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        fcntl.flock(self._fh, fcntl.LOCK_UN)
        self._fh.close()


def _write_grants(config: Path, grants: list[dict]) -> None:
    path = config.parent / "access.grants.yaml"
    tmp = path.with_suffix(".yaml.tmp")
    header = "# Written by share_build.py grant. Delete an entry to revoke it.\n"
    tmp.write_text(header + yaml.safe_dump({"grants": grants}, allow_unicode=True, sort_keys=False), "utf-8")
    tmp.replace(path)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("action", choices=["build", "grant"])
    ap.add_argument("--config", required=True, type=Path)
    ap.add_argument("--root", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args(argv)
    root, out = args.root.resolve(), args.out.resolve()
    try:
        if args.action == "build":
            build(args.config, root=root, out=out)
            return 0
        print(json.dumps(grant(args.config, root=root, out=out, request=json.loads(sys.stdin.read()))))
        return 0
    except (ValueError, OSError, yaml.YAMLError, json.JSONDecodeError) as exc:
        print(f"share_build: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
