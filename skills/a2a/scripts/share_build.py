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
        redact_terms: [Globex]       # paragraphs naming these never leave, at any level
    keep_email_domains: [example.org]

A rule may also carry ``group`` (index section), ``fields`` (frontmatter shown in the
topic) and ``summary`` (index line, ``{field}`` and ``[[optional {part}]]``).

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
    r"addresses|email|mail|tenant|subscription|iban|bic|phone|mobile|tel|account|pin|"
    r"authorization|auth|cookie|cookies|passphrase|pwd|connection_string|dsn|sas|sig|salt|"
    r"cert|certificate|webhook|endpoint|server|servers|fqdn|domain|ssn|imei|vin|serial|"
    r"salary)($|_)"
    r"|_ref$|^ref$",
)
_GRANT_TTL_SEC = 2 * 3600       # a one-time grant folder older than this is swept
# Every quantifier is bounded: a pattern that may run to the end of a 60 KB line from
# every start position is quadratic, and a hostile ``a-a-a-…`` took 100 s (fuzzed).
_NOT_END = r"[^\s,;)\]>`'\"]"
_MASKS = (
    # A markdown link keeps its text; the target (a URL, a relative path into the
    # repo) means nothing to a peer and can name internals.
    (re.compile(r"\[([^\]\n]{1,200})\]\([^)\s]{1,500}\)"), r"\1"),
    (re.compile(r"\b[a-z][a-z0-9+.-]{0,30}://" + _NOT_END + r"{1,2000}", re.IGNORECASE), "[reference]"),
    (re.compile(r"\bwww\." + _NOT_END + r"{1,2000}", re.IGNORECASE), "[reference]"),
    (re.compile(r"\beyJ[\w-]{5,2000}\.[\w-]{5,4000}\.[\w-]{5,2000}"), "[secret]"),
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "[secret]"),
    (re.compile(r"\bAIza[\w-]{30,60}"), "[secret]"),
    (re.compile(r"\b(Bearer)\s+[\w.~+/-]{16,2000}", re.IGNORECASE), r"\1 [secret]"),
    (re.compile(r"\b(?:ghp|gho|ghs|github_pat|xox[abprs]|sk|pk|rk)[-_][A-Za-z0-9_-]{12,400}"), "[secret]"),
    (re.compile(r"\b(AccountKey|SharedAccessSignature|sig)=[^;&\s]{1,2000}", re.IGNORECASE), r"\1=[secret]"),
    (re.compile(r"(?<![A-Za-z])(password|passwort|passwd|pwd|kennwort|secret|token|api[_-]?key|"
                r"client[_-]?secret|access[_-]?token)([\"']?\s{0,20}[:=|]\s{0,20}[\"'`]?)(?!\[)[^\s\"'`|]{1,400}",
                re.IGNORECASE), r"\1\2[secret]"),
    (re.compile(r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b", re.IGNORECASE), "[id]"),
    # Bank details: an IBAN in any spacing (each group after the first carries a digit,
    # so "ab12 test case" stays prose), and a BIC only where it is named.
    (re.compile(r"\b[A-Za-z]{2}\d{2}(?:[ .-]?[A-Za-z0-9]{4})(?:[ .-]?(?=[A-Za-z0-9]{0,3}\d)[A-Za-z0-9]{4}){1,6}"
                r"(?:[ .-]?[A-Za-z0-9]{1,4})?\b"), "_iban"),
    # Labelled account numbers, also shortened ones ("IBAN AT…7000", "Konto `12264476`").
    (re.compile(r"\b(IBAN|Konto(?:nummer|nr\.?)?|Kontonr\.?|Account(?: number)?)(:?\s{0,3}`?)"
                r"(?!\[)[A-Za-z0-9…. -]{0,40}\d", re.IGNORECASE), r"\1\2[account]"),
    (re.compile(r"\b(BIC|SWIFT)(:?\s{0,3})[A-Z]{6}[A-Z0-9]{2}(?:[A-Z0-9]{3})?\b"), r"\1\2[account]"),
    (re.compile(r"\b(USt-?Id[\w.-]{0,5}|Steuer[- ]?(?:nr|nummer|id)[\w.-]{0,22}|St\.?-?Nr\.?)(\s{0,3}:?\s{0,3})"
                r"[A-Z]{0,2}[\d /]{8,20}\d", re.IGNORECASE), r"\1\2[id]"),
    (re.compile(r"(?<![\w.+-])[\w.+-]{1,64}@[\w-]{1,63}(?:\.[\w-]{1,63}){1,8}\b"), "[email]"),
    (re.compile(r"(?<![\w+])\+\d{1,3}[\s\d/().-]{6,20}\d"), "[phone]"),
    (re.compile(r"\b((?:Tel(?:efon)?|Mobil|Handy|Fax|Phone)[\w.-]{0,8})(\s{0,3}:?\s{0,3})\+?\d[\d\s/().-]{5,30}\d",
                re.IGNORECASE), r"\1\2[phone]"),
    # A national number without a label: area code, then a block of at least five
    # digits. Dates and times never start with 0 followed by a space-separated block.
    (re.compile(r"(?<![\w.:/+-])0\d{2,4}[ /-]\d{5,}(?:[ -]\d{2,6}){0,2}(?![\w.:/-])"), "[phone]"),
    (re.compile(r"(?<![\w.-])(?:[\w-]{1,63}\.){1,10}(?:ts\.net|local|lan|internal|home\.arpa)\b", re.IGNORECASE),
     "[address]"),
    # IPv4-mapped first (``::ffff:10.1.2.3``), then IPv4, then the rest of IPv6, so no
    # pattern leaves octets of another behind. "1.2.3.4.5" is a section number.
    (re.compile(r"(?<![\w:])::ffff:(?:\d{1,3}\.){3}\d{1,3}\b", re.IGNORECASE), "[address]"),
    (re.compile(r"(?<![\d.])(?:\d{1,3}\.){3}\d{1,3}(?:/\d{1,2})?(?!\.?\d|\w)"), "[address]"),
    (re.compile(r"(?<![\w:])(?:\d{1,4}:){7}\d{1,4}(?![\w:])"), "[address]"),
    (re.compile(r"(?<![\w:])(?=[0-9a-f:]{0,45}(?:[a-f]|::))(?:[0-9a-f]{0,4}:){2,7}[0-9a-f]{0,4}(?:/\d{1,3})?(?![\w:])(?!\.\d)",
                re.IGNORECASE), "_ipv6"),
    (re.compile(r"\b[0-9A-Fa-f]{2}(?:[:-][0-9A-Fa-f]{2}){5}\b"), "[address]"),
    (re.compile(r"\\\\[\w.$-]{1,255}\\" + _NOT_END + r"{0,2000}"), "[path]"),
    (re.compile(r"\b[A-Za-z]:\\" + _NOT_END + r"{0,2000}"), "[path]"),
    # A home folder may hold a space (a user name with a blank): up to the next slash.
    (re.compile(r"(?<![\w.])/(?:Users|home)/[^/\n`'\"]{1,100}(?:/" + _NOT_END + r"{0,2000})?"), "[path]"),
    (re.compile(r"(?<![\w.])/(?:opt|var|etc|private|Volumes|root|srv|mnt|tmp)/" + _NOT_END + r"{0,2000}"), "[path]"),
    (re.compile(r"(?<![\w])~[\w-]{0,32}/" + _NOT_END + r"{0,2000}"), "[path]"),
)
_PRIVATE_MARK = re.compile(r"<!--[^>]{0,200}?\bshare\s*:\s*private\b[^>]{0,200}?-->", re.IGNORECASE)
_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_OPEN_ITEM = re.compile(r"^\s*[-*]\s+\[ \]\s+(.+)$")
_NEXT_STEP_ANY = re.compile(r"n(ä|ae)chste[rn]? schritt|next step", re.IGNORECASE)
_DETAILS_CAP = 25_000           # bytes of a rendered topic; older sections are cut
_LONG = 20_000                  # the index marks a topic above this as long
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
    """Frontmatter and body. Unreadable frontmatter marks the topic broken, which hides
    it: a ``share: {peer: none}`` in it must not silently stop applying."""
    lines = text.lstrip("\ufeff").splitlines()
    starts = [i for i, line in enumerate(lines) if line.strip() == "---"]
    if len(starts) >= 2 and all(not l.strip() or l.lstrip().startswith("#") for l in lines[:starts[0]]):
        try:
            meta = yaml.safe_load("\n".join(lines[starts[0] + 1:starts[1]])) or {}
        except (yaml.YAMLError, RecursionError):
            meta = {"__broken__": True}
        if not isinstance(meta, dict):
            meta = {"__broken__": True}
        return meta, "\n".join(lines[starts[1] + 1:])
    first = next((l for l in lines if l.strip() and not l.lstrip().startswith("#")), "")
    if first.strip() == "---":
        return {"__broken__": True}, "\n".join(lines)   # opened, never closed
    return {}, "\n".join(lines)


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
    real_root = root.resolve()
    for path, by_path in paths:
        if not path.is_file() or not path.resolve().is_relative_to(real_root):
            continue                           # a rule like ../x.yaml never leaves --root
        try:
            topic = _load_topic(path, root)
        except (OSError, UnicodeDecodeError, yaml.YAMLError, RecursionError, ValueError) as exc:
            # One unreadable file hides itself; it does not stop the other topics.
            print(f"share_build: skipping {path.relative_to(root)}: {type(exc).__name__}", file=sys.stderr)
            continue
        if topic is not None:
            topic.by_path_only = by_path
            if topic.meta.get("__broken__"):
                print(f"share_build: {topic.rel}: frontmatter is not valid YAML, topic hidden",
                      file=sys.stderr)
        if topic is None or not _ID_RE.fullmatch(topic.id):
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
        if not _ID_RE.fullmatch(str(pid)):
            raise ValueError(f"peer id {pid!r} is not a plain id")
        peer = peer or {}
        _check_level(peer.get("default", "none"), f"peers.{pid}.default")
        terms = peer.get("redact_terms") or []
        if not isinstance(terms, list) or not all(isinstance(t, str) and t.strip() for t in terms):
            raise ValueError(f"peers.{pid}.redact_terms must be a list of words")
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
    if topic.meta.get("__broken__"):
        return "none", {}
    override = topic.meta.get("share") if topic.kind == "status" else None
    if override is not None and not isinstance(override, dict):
        return "none", {}                      # an override nobody can read hides the topic
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

def mask(text: str, keep_domains: tuple[str, ...] = ()) -> str:
    """Mask addresses, secrets and paths. Emails of ``keep_domains`` stay readable."""
    kept: list[str] = []
    if keep_domains:
        def park(m: re.Match) -> str:
            kept.append(m.group(0))
            return f"\x00{len(kept) - 1}\x00"
        domains = "|".join(re.escape(d) for d in keep_domains)
        text = re.sub(r"(?<![\w.+-])[\w.+-]{1,64}@(?:[\w-]{1,63}\.){0,8}(?:" + domains + r")(?![\w-]|\.\w)",
                      park, text, flags=re.IGNORECASE)
    text = _mask_pem(text)
    for pattern, replacement in _MASKS:
        if replacement == "_iban":
            text = pattern.sub(_iban_or_keep, text)
        elif replacement == "_ipv6":
            text = pattern.sub(_ipv6_or_keep, text)
        else:
            text = pattern.sub(replacement, text)
    for i, original in enumerate(kept):
        text = text.replace(f"\x00{i}\x00", original)
    return text


_IBAN_COUNTRIES = frozenset(
    "AD AE AL AT AZ BA BE BG BH BR BY CH CR CY CZ DE DK DO EE EG ES FI FO FR GB GE GI GL GR GT HR HU "
    "IE IL IQ IS IT JO KW KZ LB LC LI LT LU LV MC MD ME MK MR MT MU NL NO PK PL PS PT QA RO RS SA SC "
    "SE SI SK SM ST SV TL TN TR UA VA VG XK".split())


def _iban_or_keep(m: re.Match) -> str:
    """An IBAN has a known country, 15 to 34 characters and mostly digits; a short
    git SHA or a release tag shares the shape, not those properties."""
    raw = re.sub(r"[ .-]", "", m.group(0))
    digits = sum(c.isdigit() for c in raw)
    if raw[:2].upper() in _IBAN_COUNTRIES and 15 <= len(raw) <= 34 and digits >= len(raw) * 0.6:
        return "[account]"
    return m.group(0)


def _ipv6_or_keep(m: re.Match) -> str:
    """At least two groups with digits, so ``x[::2]`` and ``f :: Int`` stay code."""
    groups = [g for g in re.split(r":+", m.group(0).split("/")[0]) if g]
    return "[address]" if len(groups) >= 2 else m.group(0)


def _mask_pem(text: str) -> str:
    """A key block, found with str.find (no regex scan): to its END line, or without
    one to the next blank line."""
    out, pos = [], 0
    while True:
        start = text.find("-----BEGIN ", pos)
        if start < 0:
            out.append(text[pos:])
            return "".join(out)
        end = text.find("-----END ", start)
        if end >= 0:
            close = text.find("-----", end + 9)
            stop = close + 5 if close >= 0 else len(text)
        else:
            blank = text.find("\n\n", start)
            stop = blank if blank >= 0 else len(text)
        out.append(text[pos:start] + "[secret]")
        pos = stop


def _term_re(terms) -> re.Pattern | None:
    if not terms:
        return None
    # Open at the end, so a term also catches its inflections ("Mandats", "ACMEs").
    return re.compile(r"(?<!\w)(?:" + "|".join(re.escape(t) for t in terms) + r")", re.IGNORECASE)


def _redact(body: str, terms) -> str:
    """Drop what names a term: a heading's whole section, a prose paragraph, or in a
    list or table only the item or row. A heading left with nothing under it goes too."""
    hit = _term_re(tuple(terms or ()))
    if hit is None or not body:
        return body
    kept_blocks: list[tuple[int, list[str]]] = []
    skip_depth = None
    for depth, lines in _blocks(body):
        if skip_depth is not None and depth > skip_depth:
            continue
        skip_depth = None
        if depth and hit.search(lines[0]):
            skip_depth = depth
            continue
        head, rest = (lines[:1], lines[1:]) if depth else ([], lines)
        paras, out = re.split(r"\n\s*\n", "\n".join(rest)), []
        for para in paras:
            if not hit.search(para):
                out.append(para)
                continue
            plines = para.splitlines()
            if all(re.match(r"\s*([-*+|]|\d+\.)", l) or not l.strip() for l in plines):
                left = [l for l in plines if not hit.search(l)]
                if any(re.match(r"\s*([-*+]|\d+\.)\s", l) or re.match(r"\s*\|.*\w", l) for l in left):
                    out.append("\n".join(left))
        kept_blocks.append((depth, head + ["\n\n".join(out)] if out else head))
    # Drop headings with nothing under them, also not in their subsections.
    result: list[str] = []
    for i, (depth, lines) in enumerate(kept_blocks):
        has_text = any(l.strip() for l in lines[1 if depth else 0:])
        if depth and not has_text:
            deeper = kept_blocks[i + 1:]
            sub = []
            for d2, l2 in deeper:
                if d2 <= depth:
                    break
                sub.append(any(x.strip() for x in l2[1:]))
            if not any(sub):
                continue
        result.extend(lines)
    return "\n".join(result).strip()


def _blocks(body: str) -> list[tuple[int, list[str]]]:
    """Split into (heading depth, lines) blocks; depth 0 is the text before any heading.

    A ``#`` line inside a fenced code block is not a heading.
    """
    blocks: list[tuple[int, list[str]]] = [(0, [])]
    fence = ""                                 # the opening run, ``` or ~~~ and its length
    for line in body.splitlines():
        m = _FENCE.match(line)
        if m:
            run = m.group(1)
            if not fence:
                fence = run
            elif run[0] == fence[0] and len(run) >= len(fence):
                fence = ""
            blocks[-1][1].append(line)
            continue
        heading = None if fence else _HEADING.match(line)
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
    # A comment spread over several lines counts like the one-line marker.
    body = re.sub(r"<!--(?:(?!-->)[\s\S]){0,500}?-->",
                  lambda m: "<!-- share: private -->"
                  if re.search(r"share\s*:\s*private", m.group(0), re.IGNORECASE) else m.group(0), body)
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
    if isinstance(only, str):
        only = [only]
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


def _clean_yaml(data, keep: dict | None = None, exclude: frozenset = frozenset(), terms=None):
    """Drop sensitive keys, keys that are addresses, excluded and redacted values, and
    mask the rest; ``keep`` limits keys; ``terms`` is a compiled redaction pattern."""
    if isinstance(data, dict):
        out = {}
        for k, v in data.items():
            name = str(k)
            if _SENSITIVE_KEY.search(_snake(k)) or mask(name) != name:
                continue
            if terms is not None and (terms.search(name) or (isinstance(v, str) and terms.search(v))):
                continue
            if keep is not None and name not in keep and k not in keep:
                continue
            sub = keep.get(name, keep.get(k)) if keep is not None else None
            out[k] = _clean_yaml(v, sub, exclude, terms)
        return out
    if isinstance(data, list):
        return [_clean_yaml(v, keep, exclude, terms) for v in data
                if not (isinstance(v, str) and (v in exclude or (terms is not None and terms.search(v))))]
    if isinstance(data, str):
        return mask(data)
    return data


def _attachments(topic: Topic) -> list[Path]:
    d = topic.path.parent / "deliverables"
    if topic.kind != "status" or not d.is_dir() or d.is_symlink():
        return []
    real = d.resolve()
    # Never a symlink, never anything that resolves outside the folder: a link to a
    # file elsewhere would carry that file's content into a peer's share.
    found = []
    for p in d.rglob("*"):
        rel = p.relative_to(d)
        if (not p.is_file() or p.is_symlink() or p.name.startswith(".")
                or not p.resolve().is_relative_to(real)
                or any((d / parent).is_symlink() for parent in rel.parents if parent != Path("."))):
            continue
        found.append(p)
    return sorted(found)


def _cap(body: str) -> str:
    """Cut a long body at section boundaries. Kept: the text before the first heading,
    the next-step section, then dated sections newest first, then the rest in order,
    as long as they fit. Kept sections stay in their original order."""
    if len(body.encode("utf-8")) <= _DETAILS_CAP:
        return body
    blocks = _blocks(body)
    sizes = [len("\n".join(lines).encode("utf-8")) + 1 for _d, lines in blocks]
    def date_of(lines):
        head = lines[0] if lines else ""
        m = re.search(r"(\d{4})-(\d{2})-(\d{2})", head) or re.search(r"(\d{1,2})\.(\d{1,2})\.(\d{4})?", head)
        if not m:
            return ""
        if len(m.group(1)) == 4:
            return m.group(0)
        return f"{m.group(3) or '9999'}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    order = [0] + [i for i, (d, l) in enumerate(blocks) if d and _NEXT_STEP_ANY.search(l[0])]
    dated = sorted((i for i, (d, l) in enumerate(blocks) if d and date_of(l)), key=lambda i: date_of(blocks[i][1]),
                   reverse=True)
    order += dated + list(range(len(blocks)))
    keep, size = set(), 0
    for i in order:
        if i in keep:
            continue
        if size + sizes[i] > _DETAILS_CAP and keep:
            continue
        keep.add(i)
        size += sizes[i]
    text = "\n".join("\n".join(blocks[i][1])[:_DETAILS_CAP] for i in sorted(keep)).rstrip()
    return text + "\n\n_(shortened: some older sections are not included)_"


def _next_step(body: str, next_step: re.Pattern) -> str:
    step = _section(body, next_step)
    if step:
        return step
    item = next((m.group(1) for m in map(_OPEN_ITEM.match, body.splitlines()) if m), "")
    return f"Next open item: {item}" if item else ""


def render(topic: Topic, level: str, rule: dict, next_step: re.Pattern | None = None,
           opts: dict | None = None) -> str:
    opts = opts or {}
    keep = tuple(opts.get("keep_domains") or ())
    terms = tuple(opts.get("redact_terms") or ())
    next_step = next_step or _next_step_re({})
    head = [f"# {topic.id}", ""]
    if topic.kind == "status":
        meta = {k: topic.meta[k] for k in _STATUS_KEYS if k in topic.meta}
        # Named fields from the frontmatter, never one with a sensitive name.
        for dotted in rule.get("fields") or []:
            value = _field(topic.meta, dotted)
            if value is not None and not isinstance(value, (dict, list)) \
                    and not any(_SENSITIVE_KEY.search(_snake(p)) for p in str(dotted).split(".")):
                meta[str(dotted)] = value
        head += [f"- {k}: {mask(_redact(str(v), terms), keep)}" for k, v in meta.items()] + [""]
        body = mask(_redact(_drop_private_sections(topic.body), terms), keep)
        if level == "status":
            step = _next_step(body, next_step)
            return "\n".join(head + ([step] if step else [])).strip() + "\n"
        parts = head + [_cap(body)]
        files = _attachments(topic) if level == "files" else []
        if files:
            parts += ["", "## Attachments" + (" (copies in this topic's folder)" if level == "files" else ""), ""]
            parts += [f"- {mask(p.relative_to(topic.path.parent).as_posix(), keep)}" for p in files]
        return "\n".join(parts).strip() + "\n"
    if topic.kind == "yaml":
        data = topic.data
        if level == "status" and isinstance(data, dict):
            data = {k: v for k, v in data.items() if not isinstance(v, (dict, list))}
        cleaned = _clean_yaml(data, _only_tree(rule.get("only")),
                              frozenset(str(x) for x in rule.get("exclude") or []), _term_re(terms))
        dumped = yaml.safe_dump(cleaned, allow_unicode=True, sort_keys=False).strip()
        return "\n".join(head + ["```yaml", dumped, "```"]).strip() + "\n"
    body = _redact(_drop_private_sections(topic.body), terms)
    if level == "status":
        body = body.split("\n\n")[0] if body else ""
    return "\n".join(head + [_cap(mask(body, keep))]).strip() + "\n"


def _first_sentence(body: str) -> str:
    for para in re.split(r"\n\s*\n", body):
        lines = [l.strip() for l in para.splitlines() if l.strip()
                 and not re.match(r"^(?:[-*]\s*)?[\w äöüÄÖÜß/-]{1,30}:\s", l.strip())]
        if not lines:
            continue
        line = lines[0]
        if (line.startswith(("#", "|", "```", "<!--", "---", ">")) or _OPEN_ITEM.match(line)
                or re.match(r"^(?:[-*]\s*)?[\w äöüÄÖÜß/-]{1,30}:\s", line)):
            continue
        text = " ".join(re.sub(r"^[-*]\s+", "", l) for l in lines
                        if not re.match(r"^(?:[-*]\s*)?[\w äöüÄÖÜß/-]{1,30}:\s", l))
        text = re.sub(r"[*_`]", "", text)
        m = re.match(r"(.{20,}?[.!?])(\s|$)", text)
        return m.group(1) if m else text
    return ""


def _from_template(template: str, meta: dict) -> str:
    """Fill ``{key}`` and ``{key[sub]}`` from the frontmatter. No attribute access, no
    format spec. A ``[[ … ]]`` segment appears only when all its fields have a value."""
    def fill(part: str) -> tuple[str, bool]:
        complete = True
        def field(m: re.Match) -> str:
            nonlocal complete
            value = _field(meta, ".".join([m.group(1)] + re.findall(r"\[([\w-]+)\]", m.group(2) or "")))
            if value in (None, "") or isinstance(value, (dict, list)):
                complete = False
                return ""
            return str(value).split(" #")[0].strip()
        text = re.sub(r"\{([A-Za-z_][\w-]*)((?:\[[\w-]+\])*)\}", field, part)
        if re.search(r"[{}]", text):
            return "", False                   # anything but a plain field is refused
        return text, complete
    out = []
    for i, seg in enumerate(re.split(r"\[\[|\]\]", str(template))):
        text, complete = fill(seg)
        if i % 2 == 0 or complete:
            out.append(text)
    text = "".join(out)
    return re.sub(r"\s{2,}", " ", re.sub(r"\s+([,.;)])", r"\1", text)).strip(" ,")


def _field(meta: dict, dotted: str):
    node = meta
    for part in str(dotted).split("."):
        if not isinstance(node, dict) or part not in node:
            return None
        node = node[part]
    return node


def _summary(topic: Topic, opts: dict | None = None, rule: dict | None = None) -> str:
    opts = opts or {}
    rule = rule or {}
    text = (_from_template(rule["summary"], topic.meta) if rule.get("summary") else "") or (
            topic.meta.get("headline") or topic.meta.get("summary") or topic.meta.get("description")
            or (_first_sentence(_drop_private_sections(topic.body)) if topic.kind != "yaml" else ""))
    text = mask(_redact(" ".join(str(text).split()), tuple(opts.get("redact_terms") or ())),
                tuple(opts.get("keep_domains") or ()))
    return text if len(text) <= 160 else text[:157].rsplit(" ", 1)[0] + " …"


def _updated(topic: Topic) -> str:
    """The topic's own date; never the file time, which is only the checkout time."""
    for key in ("last_updated", "updated", "abgeschlossen", "absage_am", "gesendet", "angelegt", "created"):
        value = topic.meta.get(key)
        if value:
            m = re.match(r"\d{4}-\d{2}-\d{2}", str(value))
            if m:
                return m.group(0)
    return ""


_TEXT_SUFFIXES = frozenset({".md", ".txt", ".json", ".yaml", ".yml", ".csv", ".html", ".htm", ".xml", ".toml"})


def _copy_attachment(src: Path, topic: Topic, dest: Path, opts: dict, hit) -> None:
    """Text files go through masking and redaction like the topic itself; a binary file
    is copied only when its name is clean, and its content is not inspected."""
    rel = src.relative_to(topic.path.parent / "deliverables").as_posix()
    if hit is not None and hit.search(rel):
        return
    dst = dest / mask(rel, opts["keep_domains"])
    dst.parent.mkdir(parents=True, exist_ok=True)
    if src.suffix.lower() in _TEXT_SUFFIXES:
        try:
            text = src.read_text("utf-8")
        except UnicodeDecodeError:
            return
        dst.write_text(mask(_redact(_drop_private_sections(text), opts["redact_terms"]), opts["keep_domains"]),
                       "utf-8")
    else:
        shutil.copyfile(src, dst)


def build_peer(access: dict, grants: list[dict], topics: dict[str, Topic], peer_id: str,
               folder: Path, *, extra: dict[str, str] | None = None) -> None:
    """Write ``folder`` from scratch; ``extra`` lifts topics (id → level) for a grant."""
    folder.parent.mkdir(parents=True, exist_ok=True)
    peer = access["peers"].get(peer_id) or {}
    opts = {"keep_domains": tuple(access.get("keep_email_domains") or ()),
            "redact_terms": tuple(peer.get("redact_terms") or ())}
    staging = Path(tempfile.mkdtemp(prefix=".build-", dir=folder.parent))
    try:
        visible, on_request = [], []
        hit = _term_re(opts["redact_terms"])
        for topic in sorted(topics.values(), key=lambda t: t.id):
            try:
                level, rule = resolve(access, grants, peer_id, topic)
            except ValueError as exc:
                # One bad override (a level typo in a STATUS.md) hides that topic only.
                print(f"share_build: {topic.rel}: {exc}, topic hidden", file=sys.stderr)
                continue
            if extra and topic.id in extra and level == "on_request":
                level = extra[topic.id]
            if level == "none" or (hit is not None and hit.search(topic.id)):
                continue
            if level == "on_request":
                on_request.append(topic)
                continue
            (staging / "topics").mkdir(exist_ok=True)
            try:
                rendered = render(topic, level, rule, _next_step_re(access), opts)
            except (ValueError, TypeError, RecursionError) as exc:
                print(f"share_build: {topic.rel}: cannot render ({type(exc).__name__}), topic hidden",
                      file=sys.stderr)
                continue
            (staging / "topics" / f"{topic.id}.md").write_text(rendered, "utf-8")
            if level == "files":
                for src in _attachments(topic):
                    _copy_attachment(src, topic, staging / "topics" / topic.id, opts, hit)
            visible.append((topic, level, rule, len(rendered.encode("utf-8"))))
        index = ["# Index", "",
                 "Topics you can read, each in topics/<id>.md, newest first per group.", ""]
        groups: dict[str, list] = {}
        for item in visible:
            groups.setdefault(str(item[2].get("group") or "Topics"), []).append(item)
        if not groups:
            index += ["- (none)"]
        for name, items in groups.items():
            index += [f"## {name}", ""]
            for t, lvl, _rule, size in sorted(items, key=lambda i: (_updated(i[0]), i[0].id), reverse=True):
                notes = [f"updated {_updated(t)}"] if _updated(t) else []
                if lvl == "status":
                    notes.append("status only")
                if lvl == "files":
                    notes.append(f"files in topics/{t.id}/")
                if size > _LONG:
                    notes.append("long, read the start first")
                index.append(f"- {t.id} ({', '.join(notes)}): {_summary(t, opts, _rule)}")
            index.append("")
        if on_request:
            index += ["## Available on request", "",
                      "Not in your files. The owner opens one when asked:", ""]
            index += [f"- {t.id}: {_summary(t, opts)}" for t in on_request]
        (staging / "index.md").write_text("\n".join(index) + "\n", "utf-8")
        # The ids the runtime may ask the owner about (access.py reads this list).
        (staging / ".on_request").write_text("".join(f"{t.id}\n" for t in on_request), "utf-8")
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
        grants = [g for g in grants if isinstance(g, dict)]
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
    if not _TASK_RE.fullmatch(task_id):
        raise ValueError(f"task id {task_id!r} is not a plain id")
    if not _ID_RE.fullmatch(peer_id):
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
    header = ("# Written by share_build.py grant. To revoke, delete an entry and run "
              "share_build.py build;\n# the peer folder keeps the topic until then.\n")
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
    except (ValueError, OSError, yaml.YAMLError, json.JSONDecodeError, TypeError, AttributeError,
            KeyError, RecursionError) as exc:
        print(f"share_build: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
