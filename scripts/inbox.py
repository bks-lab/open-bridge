#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The inbox: one place where everything that needs a person waits until it is done.

A finding, a question from an agent, a decision, a draft waiting for its send:
before this existed each one lived wherever it happened to be written down: a
sentence in the log, a chat message, a mail from a scheduled job, a line in a
STATUS.md. Nothing closed them. A briefing that re-read those sources reported
things as open that had been solved hours earlier, because the sentence saying
"needed" was still there and the one saying "done" was further down.

    python3 scripts/inbox.py add --from homebox/issue-radar --kind decision \\
        --summary "PR #70 is green and waits for a merge" --task a2a \\
        --action-json '{"argv": ["gh", "pr", "merge", "70", "-R", "org/repo"]}' \\
        --closes-when-json '{"gh_pr": "org/repo#70", "state": "merged"}'
    python3 scripts/inbox.py list            # open items, most urgent first
    python3 scripts/inbox.py approve <id> [--when-json '{"gh_pr": "org/repo#70", "state": "green"}']
    python3 scripts/inbox.py check           # close what the live source says is done
    python3 scripts/inbox.py run             # execute what a person released
    python3 scripts/inbox.py render          # regenerate work/inbox.md (a view)
    python3 scripts/inbox.py reopen <id> [--note TEXT]   # undo a close, drop or reject

LAYOUT. ``work/inbox/<id>/item.yaml`` is written once and never changed.
Every later change (a note, a yes, a close) is a NEW file under
``work/inbox/<id>/events/``. Two machines writing the same inbox through git
therefore never touch the same file, the same property that keeps the task
folders conflict-free. The state of an item is derived from its events, never
stored, like the board is derived from the task folders.

CLOSING. ``closes_when`` names a probe against the live source (a PR merged, an
issue closed, a file present, a command exiting 0, a time passed). ``check``
runs the probes and closes what holds. A probe that cannot be evaluated is
UNKNOWN, never true: an item stays open rather than vanishing on a network error.

GATES. ``free`` the Bridge may act alone · ``your-yes`` acts after a person said
yes, also a conditional yes ("merge once green") that ``run`` executes when the
condition holds · ``only-you`` (send, publish, pay) is never executed by this
script, whatever was recorded.

MUTE. A drop may say why: ``once`` (this one, no rule), ``duplicate``, ``family`` (never
this kind again: the source plus the key up to its last colon, or the kind when the key has no
family) or ``source`` (the whole source, for ``MUTE_SOURCE_DAYS``). The last two leave a rule,
one file of its own under ``work/inbox/_mutes/``. A finding that matches a rule is still filed
and dropped at once by ``mute``: it counts in ``stats`` and a reopen brings it back. An item
filed as ``now`` is never muted. ``stats`` shows per source how much a person dropped.

REOPEN. A close by mistake is undone with a ``reopen`` event, never by deleting the
close: the item is open again, every yes before it is void (an executed action does
not run again without a new yes), and a later close closes it again.

The contract lives in ``scripts/tests/test_inbox.py``. Model: docs/inbox.md.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import secrets
import socket
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from lib.inbox_verbs import TERMINAL  # noqa: E402  (shared with the cockpit's return channel)

SCHEMA_VERSION = 1

KINDS = ("decision", "question", "finding", "draft", "result", "idea")
GATES = ("free", "your-yes", "only-you")
URGENCIES = ("now", "today", "later")
#: Who ends an item when it has no probe. `reporter`: the job that filed it closes it when the
#: condition is gone (by key). `person`: only a person can say it is done. `bot`: a watcher acts
#: on it and closes it. An item with neither a probe nor a closer is the one that stays open for
#: ever, which is what the inbox exists to prevent (2026-10-07: 51 of 62 items had no way out).
CLOSERS = ("probe", "reporter", "person", "bot")
VERBS = ("seen", "note", "approve", "reject", "drop", "defer", "close", "executed", "failed", "urgency", "reopen")
ACTIVE_STATES = ("open", "approved", "waiting")
#: Why a person dropped an item. `family` and `source` leave a mute rule behind.
DROP_REASONS = ("once", "duplicate", "family", "source")
MUTE_REASONS = ("family", "source")
#: A source mute ends by itself: a source that was too loud for a month may have been fixed since.
MUTE_SOURCE_DAYS = 30
#: Rules live beside the items; the `_` keeps the folder out of `items()`.
MUTES_DIR = "_mutes"
MUTE_ACTOR = "mute"
ACTION_KEYS = {"argv", "label"}
RUN_TIMEOUT_SEC = 600
PROBE_TIMEOUT_SEC = 30
OUTPUT_TAIL = 400

GhRunner = Callable[[list], str]


# ---------------------------------------------------------------- probes

def _gh_cli(args: list) -> str:
    return subprocess.run(
        ["gh", *args], capture_output=True, text=True, timeout=PROBE_TIMEOUT_SEC, check=True
    ).stdout


def _ref(value: str) -> tuple[str, str]:
    repo, _, number = str(value).partition("#")
    if not repo or not number.isdigit():
        raise ValueError(f"expected owner/repo#N, got {value!r}")
    return repo, number


def _parse_when(value) -> dt.datetime:
    if isinstance(value, dt.datetime):
        return value
    if isinstance(value, dt.date):
        return dt.datetime.combine(value, dt.time())
    text = str(value)
    return dt.datetime.fromisoformat(text) if "T" in text or " " in text else dt.datetime.combine(
        dt.date.fromisoformat(text), dt.time()
    )


def _utc(value: dt.datetime) -> dt.datetime:
    """Every comparison happens in UTC. A naive time is read as the local clock,
    so two machines in different time zones still agree on what came first."""
    return (value if value.tzinfo else value.astimezone()).astimezone(dt.timezone.utc)


# libyaml's loader is several times faster than the pure-Python one and reads the same
# safe subset; a PyYAML built without libyaml simply has no CSafeLoader.
_YAML_LOADER = getattr(yaml, "CSafeLoader", yaml.SafeLoader)


def _yaml_load(text: str):
    return yaml.load(text, Loader=_YAML_LOADER)


def _local_date(value: dt.datetime) -> dt.date:
    return value.date() if value.tzinfo is None else value.astimezone().date()


_STAMP = re.compile(r"\d{4}-\d{2}-\d{2}[T ]\d{2}:\d{2}(:\d{2})?(\.\d+)?(Z|[+-]\d{2}:?\d{2})?")


def _comparable(text) -> str:
    """A finding's text with its timestamps blanked and its whitespace folded."""
    return " ".join(_STAMP.sub("<stamp>", str(text or "")).split())


def _has_command(spec) -> bool:
    if isinstance(spec, dict):
        return "command" in spec or any(_has_command(v) for v in spec.values())
    if isinstance(spec, list):
        return any(_has_command(v) for v in spec)
    return False


def _status_of_task(slug: str, base: Path) -> str | None:
    work = base / "work"
    for path in [work / "tasks" / slug, work / "streams" / slug, *sorted((work / "done").glob(f"*/{slug}"))]:
        status = path / "STATUS.md"
        if status.is_file():
            text = status.read_text(encoding="utf-8")
            match = re.search(r"^status:\s*([a-z]+)", text, re.MULTILINE)
            return match.group(1) if match else None
    return None


def probe(spec, *, now: dt.datetime | None = None, gh: GhRunner | None = None,
          base: Path | None = None, item: "Item | None" = None) -> bool | None:
    """Evaluate one probe. True / False, or None when it cannot be evaluated.

    `item` is the item the probe belongs to; only `unseen_for` reads it.

    Never raises: a broken probe is UNKNOWN, and unknown never closes anything.
    """
    if not isinstance(spec, dict) or not spec:
        return None
    now = now or dt.datetime.now()
    gh = gh or _gh_cli
    base = base or Path.cwd()
    try:
        for combine in ("all", "any"):
            if combine in spec:
                parts = spec[combine]
                if not isinstance(parts, list) or not parts:
                    return None         # an empty list proves nothing; all([]) would say True
                results = [probe(p, now=now, gh=gh, base=base, item=item) for p in parts]
                if combine == "all":
                    return None if None in results else all(results)
                return True if True in results else (None if None in results else False)
        if "path_exists" in spec:
            raw = str(spec["path_exists"] or "").strip()
            if not raw:
                return None             # "" would resolve to the repository root, which always exists
            path = Path(os.path.expanduser(raw))
            return (path if path.is_absolute() else base / path).exists()
        if "after" in spec:
            return _utc(now) >= _utc(_parse_when(spec["after"]))
        if "unseen_for" in spec:
            # A reporter that refiles the same key every run says "still there" by firing
            # again; when it stops, the condition is gone. Needs the item (its sightings).
            cfg = spec["unseen_for"]
            hours = cfg.get("hours") if isinstance(cfg, dict) else None
            if item is None or isinstance(hours, bool) or not isinstance(hours, (int, float)) or hours <= 0:
                return None             # no item, a malformed span, or one that would close at once
            last = max([_event_time(item.data.get("created"))]
                       + [_event_time(e.at) for e in item.events if e.verb == "seen"])
            if last == _NO_TIME:
                return None             # no sighting with a readable time: unknown, never "long ago"
            return _utc(now) - last >= dt.timedelta(hours=hours)
        if "command" in spec:
            argv = spec["command"]
            if not isinstance(argv, list) or not argv:
                return None
            done = subprocess.run([str(a) for a in argv], capture_output=True, timeout=PROBE_TIMEOUT_SEC,
                                  cwd=base)
            return done.returncode == int(spec.get("expect_exit", 0))
        if "gh_pr" in spec:
            repo, number = _ref(spec["gh_pr"])
            data = json.loads(gh(["pr", "view", number, "-R", repo, "--json", "state,statusCheckRollup"]))
            want = str(spec.get("state", "merged")).lower()
            if want == "green":
                checks = data.get("statusCheckRollup") or []
                ok = {"SUCCESS", "SKIPPED", "NEUTRAL"}
                return bool(checks) and all(
                    (c.get("conclusion") or c.get("state") or "").upper() in ok for c in checks
                )
            return str(data.get("state", "")).lower() == want
        if "gh_issue" in spec:
            repo, number = _ref(spec["gh_issue"])
            data = json.loads(gh(["issue", "view", number, "-R", repo, "--json", "state"]))
            return str(data.get("state", "")).lower() == str(spec.get("state", "closed")).lower()
        if "task_status" in spec:
            status = _status_of_task(str(spec["task_status"]), base)
            return None if status is None else status == str(spec.get("status", "done"))
    except (OSError, ValueError, KeyError, TypeError, subprocess.SubprocessError, json.JSONDecodeError):
        return None
    return None


# ---------------------------------------------------------------- model

@dataclass
class Event:
    name: str
    verb: str
    by: str
    at: str
    data: dict = field(default_factory=dict)


@dataclass
class Item:
    id: str
    data: dict
    events: list
    today: dt.date

    def __getattr__(self, key):
        if key == "summary":
            seen = [e.data.get("summary") for e in self.events if e.verb == "seen" and e.data.get("summary")]
            return seen[-1] if seen else self.data.get("summary")
        if key == "urgency":
            # The last `urgency` event wins; item.yaml keeps the urgency it was filed with.
            set_by = [e.data.get("value") for e in self.events
                      if e.verb == "urgency" and e.data.get("value") in URGENCIES]
            return set_by[-1] if set_by else self.data.get("urgency")
        if key in ("kind", "gate", "task", "source", "created", "key",
                   "action", "closes_when", "detail", "due", "closer"):
            return self.data.get("from" if key == "source" else key)
        raise AttributeError(key)

    @property
    def approval(self):
        """The current yes: None, True (plain) or the condition dict."""
        current = None
        for e in self.events:
            if e.verb == "approve":
                current = e.data.get("when") or True
            elif e.verb in ("failed", "reopen"):      # a reopened item needs a new yes
                current = None
        return current

    @property
    def approved_text(self) -> str | None:
        """The text a person released with their yes (an edited draft), if any."""
        for e in reversed(self.events):
            if e.verb == "approve":
                return e.data.get("text")
        return None

    @property
    def deferral(self) -> dict | None:
        """The defer in force: {"until", "on"}. `on` is what it waits on ("runs on": a person, a run);
        a plain "later" has none. A yes or a reopen takes a defer back, as in `state`."""
        current = None
        for e in self.events:
            if e.verb == "defer":
                # stored as waits_on: a bare `on` key is a boolean to YAML 1.1 readers (the first events wrote it)
                current = {"until": e.data.get("until"), "on": e.data.get("waits_on") or e.data.get("on")}
            elif e.verb in ("approve", "reopen") or e.verb in TERMINAL:
                current = None
        return current

    @property
    def last_failed(self) -> bool:
        acting = [e for e in self.events if e.verb in ("approve", "executed", "failed")]
        return bool(acting) and acting[-1].verb == "failed"

    @property
    def state(self) -> str:
        deferred_until, terminal = None, None
        for e in self.events:
            if terminal:                          # after a close only a reopen counts
                if e.verb == "reopen":
                    terminal, deferred_until = None, None
                continue
            if e.verb in TERMINAL:
                terminal = TERMINAL[e.verb]
                continue
            if e.verb == "defer":
                deferred_until = e.data.get("until")
            elif e.verb in ("approve", "reopen"):   # a reopen also takes back a defer ("later" by mistake)
                deferred_until = None
        if terminal:
            return terminal
        if deferred_until:
            try:
                if _local_date(_parse_when(deferred_until)) > self.today:
                    return "deferred"
            except ValueError:
                pass
        approval = self.approval
        if approval is True:
            return "approved"
        if isinstance(approval, dict):
            return "waiting"
        return "open"

    def as_dict(self) -> dict:
        deferral = self.deferral or {}
        return {"id": self.id, "state": self.state, **{k: v for k, v in self.data.items()
                                                      if k != "schema_version"}, "urgency": self.urgency,
                **({"deferred_until": deferral["until"]} if deferral.get("until") else {}),
                **({"waiting_on": deferral["on"]} if deferral.get("on") else {})}


def _warn(text: str) -> None:
    print(f"inbox: {text}", file=sys.stderr)


_NO_TIME = dt.datetime.min.replace(tzinfo=dt.timezone.utc)


def _event_time(at) -> dt.datetime:
    """An ISO string, or the datetime yaml.safe_load makes of an unquoted timestamp."""
    try:
        return _utc(at if isinstance(at, dt.datetime) else dt.datetime.fromisoformat(at))
    except (TypeError, ValueError):
        return _NO_TIME


def _slug(text: str, limit: int = 40) -> str:
    text = text.lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        text = text.replace(a, b)
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")[:limit].rstrip("-") or "item"


def _check_action(action) -> None:
    if action is None:
        return
    if not isinstance(action, dict) or set(action) - ACTION_KEYS:
        raise ValueError(f"action takes only {sorted(ACTION_KEYS)}, got {action!r}")
    argv = action.get("argv")
    if not isinstance(argv, list) or not argv or not all(isinstance(a, str) and a for a in argv):
        raise ValueError("action.argv must be a non-empty list of strings (no shell)")


def _dump(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")
    tmp.replace(path)


# how a reporter's own all-clear begins (its close text); a fork whose reporters write another
# language adds its words in bridge-config.yaml `inbox.all_clear`
ALL_CLEAR = ("All clear",)


class Inbox:
    def __init__(self, root: Path, *, actor: str, clock: Callable[[], dt.datetime] = dt.datetime.now,
                 gh: GhRunner | None = None, runner: str | None = None, all_clear: tuple = ()):
        self.root = Path(root)
        self.all_clear = ALL_CLEAR + tuple(w for w in all_clear if isinstance(w, str) and w)
        self.actor = _slug(actor, 30)
        self.clock = clock
        self.gh = gh
        # The one host that executes actions. Two machines that both `run` would
        # each see an approved item before the other's `executed` event arrived
        # through git, and a non-idempotent action (open an issue) would run twice.
        self.runner = _slug(runner, 30) if runner else None
        # work/inbox → repository root: probes and actions resolve relative paths there
        self.base = self.root.parent.parent

    # -------------------------------------------------- reading
    def _load_events(self, item_dir: Path) -> list:
        events = []
        for path in sorted((item_dir / "events").glob("*.yaml")):
            try:
                data = _yaml_load(path.read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError) as exc:
                _warn(f"{item_dir.name}: skipping unreadable event {path.name} ({exc})")
                continue
            if not isinstance(data, dict):
                _warn(f"{item_dir.name}: skipping event {path.name}, not a mapping")
                continue
            events.append(Event(path.name, data.pop("verb", ""), data.pop("by", ""),
                                str(data.pop("at", "")), data))
        events.sort(key=lambda e: (_event_time(e.at), e.name))
        return events

    def get(self, item_id: str) -> Item:
        item_dir = self.root / item_id
        data = _yaml_load((item_dir / "item.yaml").read_text(encoding="utf-8")) or {}
        if not isinstance(data, dict) or not data.get("kind"):
            raise ValueError(f"{item_id}: item.yaml is not an item")
        return Item(item_id, data, self._load_events(item_dir), _local_date(self.clock()))

    def items(self) -> list:
        """Every readable item. One broken file (a conflict marker, a hand edit) is
        skipped with a warning; it must not take the whole inbox down with it."""
        if not self.root.is_dir():
            return []
        found = []
        for path in sorted(self.root.iterdir()):
            if path.name.startswith("_") or not (path.is_dir() and (path / "item.yaml").is_file()):
                continue
            try:
                found.append(self.get(path.name))
            except (OSError, ValueError, yaml.YAMLError) as exc:
                _warn(f"skipping {path.name}: {exc}")
        return found

    def open_items(self) -> list:
        kind_rank = {k: i for i, k in enumerate(KINDS)}
        urgency_rank = {u: i for i, u in enumerate(URGENCIES)}
        active = [i for i in self.items() if i.state in ACTIVE_STATES]
        return sorted(active, key=lambda i: (urgency_rank.get(i.urgency, 9), kind_rank.get(i.kind, 9),
                                             str(i.due or "9999"), str(i.created), i.id))

    def recently_closed(self, key: str, detail: str | None, *, hours: float):
        """The item under `key` that a READER closed within `hours`, if `detail` is unchanged.

        Returns (item, close_event) or None. A close by somebody who looked at the finding
        answers that exact text, so a watcher repeating it adds nothing (an alarm closed after
        investigation in the morning must not come back word for word hours later as a new item
        and a new phone message). Two closes do NOT count, because they mean the trouble had
        ended and its return is news: a probe (`check`, closes_when held) and an all-clear
        of the reporter itself (its text begins with a word of `all_clear`). Timestamps are blanked before comparing: a reminder of the
        same failure may carry a re-rendered stamp, a different exit code is still different.
        """
        if not key:
            return None
        now = _utc(self.clock())
        same = [i for i in self.items() if i.key == key and i.state == "done"]
        for item in reversed(same):
            closes = [e for e in item.events if e.verb in ("close", "executed")]
            if not closes:
                continue
            last = closes[-1]
            if last.by == "check" or str(last.data.get("text") or "").startswith(self.all_clear):
                return None
            try:
                age = now - _utc(_parse_when(last.at))
            except ValueError:
                return None
            if age > dt.timedelta(hours=hours):
                return None
            if _comparable(item.detail) != _comparable(detail):
                return None
            return item, last
        return None

    def resolve(self, prefix: str) -> str:
        if (self.root / prefix / "item.yaml").is_file():
            return prefix
        hits = [i.id for i in self.items() if i.id.startswith(prefix)]
        if len(hits) != 1:
            raise KeyError(f"{prefix!r} matches {len(hits)} items" + (f": {hits}" if hits else ""))
        return hits[0]

    # -------------------------------------------------- writing
    def add(self, *, source: str, kind: str, summary: str, task: str | None = None,
            gate: str = "your-yes", urgency: str = "today", detail: str | None = None,
            action: dict | None = None, closes_when: dict | None = None, key: str | None = None,
            due: str | None = None, closer: str | None = None) -> str:
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {KINDS}")
        if gate not in GATES:
            raise ValueError(f"gate must be one of {GATES}")
        if urgency not in URGENCIES:
            raise ValueError(f"urgency must be one of {URGENCIES}")
        if not summary or not str(summary).strip():
            raise ValueError("summary is required")
        if closes_when is not None and not isinstance(closes_when, dict):
            raise ValueError("closes_when must be a probe mapping")
        if closer is not None and closer not in CLOSERS:
            raise ValueError(f"closer must be one of {CLOSERS}")
        _check_action(action)
        if due is not None:
            _parse_when(due)            # raises ValueError on a date nobody can read
        if key:
            # A repeat of an open item is that item. A DROPPED key stays dropped:
            # a person said "do not tell me about this", and the next run of the
            # same watcher must not undo that. A CLOSED key may come back: it
            # was solved, and happening again is news.
            same = [i for i in self.items() if i.key == key]
            live = [i for i in same if i.state not in ("done", "dropped")]
            dropped = [i for i in same if i.state == "dropped"]
            target = (live or dropped or [None])[-1]
            if target is not None:
                self.event(target.id, "seen", summary=summary)
                drops = [e for e in target.events if e.verb == "drop"]
                if (target.state == "dropped" and drops and drops[-1].by == MUTE_ACTOR
                        and (urgency == "now" or self.muted_by(source, kind, key) is None)):
                    # only a rule dropped it, and no rule holds any more (or it is an outage)
                    self.event(target.id, "reopen", by=MUTE_ACTOR, text="no mute rule holds any more")
                return target.id
        now = self.clock()
        # A random tail: two machines filing the same summary in the same minute
        # would otherwise both create the same item.yaml and collide in git.
        stem = f"{now:%Y%m%d-%H%M}-{_slug(summary, 34)}"
        item_id = f"{stem}-{secrets.token_hex(2)}"
        while (self.root / item_id).exists():
            item_id = f"{stem}-{secrets.token_hex(2)}"
        data = {"schema_version": SCHEMA_VERSION, "created": now.isoformat(timespec="minutes"),
                "from": source, "kind": kind, "summary": summary.strip(), "urgency": urgency, "gate": gate}
        for name, value in (("task", task), ("due", due), ("detail", detail), ("key", key),
                            ("action", action), ("closes_when", closes_when), ("closer", closer)):
            if value:
                data[name] = value
        if kind in ("finding", "question") and not closes_when and not closer:
            # A warning, not a refusal: filers run unattended and swallow errors, so a refusal
            # would lose the finding. Pass --closes-when-json or --closer to say how it ends.
            _warn(f"{summary.strip()[:60]!r}: no way to close (neither closes_when nor closer); "
                  f"it stays open until a person closes it")
        _dump(self.root / item_id / "item.yaml", data)
        (self.root / item_id / "events").mkdir(exist_ok=True)
        rule = self.muted_by(source, kind, key) if urgency != "now" else None
        if rule is not None:
            # filed and dropped at once: the noise stays countable and a reopen brings it back
            self.event(item_id, "drop", by=MUTE_ACTOR, reason="muted", rule=rule["id"])
        return item_id

    def event(self, item_id: str, verb: str, *, by: str | None = None, **data) -> None:
        if verb not in VERBS:
            raise ValueError(f"verb must be one of {VERBS}")
        events_dir = self.root / item_id / "events"
        if not (self.root / item_id / "item.yaml").is_file():
            raise KeyError(item_id)
        now = _utc(self.clock())
        actor = _slug(by, 30) if by else self.actor
        stamp = f"{now:%Y%m%dT%H%M%SZ}"
        seq = len(list(events_dir.glob(f"{stamp}-*"))) if events_dir.is_dir() else 0
        body = {"verb": verb, "by": actor, "at": now.isoformat(timespec="seconds")}
        body.update({k: v for k, v in data.items() if v is not None})
        _dump(events_dir / f"{stamp}-{seq:02d}-{actor}-{verb}.yaml", body)

    def note(self, item_id: str, text: str) -> None:
        self.event(item_id, "note", text=text)

    def approve(self, item_id: str, when: dict | None = None, text: str | None = None) -> None:
        if when is not None:
            if self.get(item_id).gate == "only-you":
                raise PermissionError("an only-you item takes no conditional yes: it is never executed")
            if not isinstance(when, dict):
                raise ValueError("when must be a probe mapping")
        self.event(item_id, "approve", when=when, text=text)

    def set_urgency(self, item_id: str, value: str) -> None:
        if value not in URGENCIES:
            raise ValueError(f"urgency must be one of {URGENCIES}")
        state = self.get(item_id).state
        if state in ("done", "dropped"):
            raise ValueError(f"{item_id} is closed ({state}); its urgency no longer matters")
        self.event(item_id, "urgency", value=value)

    def reject(self, item_id: str, note: str | None = None) -> None:
        self.event(item_id, "reject", text=note)

    def close(self, item_id: str, note: str | None = None) -> None:
        self.event(item_id, "close", text=note)

    def drop(self, item_id: str, note: str | None = None, reason: str | None = None) -> str | None:
        """Drop an item, saying why if you know. `family` and `source` also write a mute rule
        and return its id; every other drop returns None."""
        if reason is not None and reason not in DROP_REASONS:
            raise ValueError(f"reason must be one of {DROP_REASONS}")
        item = self.get(item_id)
        self.event(item_id, "drop", text=note, reason=reason)
        return self.mute(item, reason) if reason in MUTE_REASONS else None

    # -------------------------------------------------- mute rules
    def mute(self, item: Item, scope: str) -> str:
        """Write the rule a drop for `scope` asks for. `family`: the source plus the key up to its
        last colon (`mini-health:crash:1a20` -> `mini-health:crash:`), or the kind when the key has
        no family. `source`: everything of the source until MUTE_SOURCE_DAYS from today."""
        if scope not in MUTE_REASONS:
            raise ValueError(f"scope must be one of {MUTE_REASONS}")
        now = self.clock()
        rule = {"schema_version": SCHEMA_VERSION, "created": now.isoformat(timespec="minutes"), "by": self.actor,
                "source": item.source, "scope": scope, "from_item": item.id,
                "summary": str(item.summary or "")[:200]}
        if scope == "family":
            key = str(item.key or "")
            if ":" in key.rstrip(":"):
                rule["key_prefix"] = key[:key.rstrip(":").rindex(":") + 1]
            else:
                rule["kind"] = item.kind
        else:
            rule["until"] = (_local_date(now) + dt.timedelta(days=MUTE_SOURCE_DAYS)).isoformat()
        rule_id = f"{now:%Y%m%d-%H%M}-{_slug(str(item.source), 30)}-{secrets.token_hex(2)}"
        _dump(self.root / MUTES_DIR / f"{rule_id}.yaml", rule)
        return rule_id

    def _rule_files(self) -> list:
        folder = self.root / MUTES_DIR
        return sorted(folder.glob("*.yaml")) if folder.is_dir() else []

    @staticmethod
    def _rule_problem(data) -> str | None:
        if not isinstance(data, dict) or not data.get("source"):
            return "not a rule (needs at least a source)"
        for name in ("key_prefix", "kind"):
            if name in data and not (isinstance(data[name], str) and data[name]):
                return f"{name} {data[name]!r} is not a text"
        if data.get("until"):
            try:
                _parse_when(data["until"])
            except ValueError:
                return f"until {data['until']!r} is not a date"
        return None

    def mutes(self) -> list:
        """The rules in force today, oldest first. An unreadable rule mutes nothing."""
        today = _local_date(self.clock())
        rules = []
        for path in self._rule_files():
            try:
                data = yaml.safe_load(path.read_text(encoding="utf-8"))
            except (OSError, yaml.YAMLError) as exc:
                _warn(f"skipping mute rule {path.name} ({exc})")
                continue
            if self._rule_problem(data):
                _warn(f"skipping mute rule {path.name}: {self._rule_problem(data)}")
                continue
            if data.get("until") and _local_date(_parse_when(data["until"])) <= today:
                continue    # a source mute of N days ends on the Nth day
            rules.append({**{k: v for k, v in data.items() if k != "schema_version"}, "id": path.stem})
        return rules

    def muted_by(self, source: str, kind: str, key: str | None) -> dict | None:
        for rule in self.mutes():
            if rule["source"] != source:
                continue
            if rule.get("key_prefix") and not str(key or "").startswith(rule["key_prefix"]):
                continue
            if rule.get("kind") and (rule["kind"] != kind or ":" in str(key or "").rstrip(":")):
                continue    # a kind rule stands for the keys without a family, it leaves the families alone
            return rule
        return None

    def unmute(self, rule_id: str) -> None:
        path = self.root / MUTES_DIR / f"{rule_id}.yaml"
        if "/" in rule_id or not path.is_file():
            raise KeyError(f"no mute rule {rule_id!r}")
        path.unlink()

    # -------------------------------------------------- noise
    def stats(self, days: int = 30) -> list:
        """Per source, over the items filed in the last `days`: how many were filed, how many a
        person dropped (with the reasons), how many a rule muted, closed or still open. `share` is
        what a person had to drop out of what was filed: the clicks the source cost, so a source
        that was muted and then fixed comes down again. Loudest first."""
        since = _local_date(self.clock()) - dt.timedelta(days=days)
        rows: dict = {}
        for item in self.items():
            try:
                if _local_date(_parse_when(item.created)) < since:
                    continue
            except ValueError:
                continue
            row = rows.setdefault(item.source, {"source": item.source, "filed": 0, "dropped": 0, "muted": 0,
                                                "done": 0, "open": 0, "reasons": {}})
            row["filed"] += 1
            state = item.state
            if state == "dropped":
                drop = next((e for e in reversed(item.events) if e.verb in ("drop", "reject")), None)
                if drop is not None and drop.verb == "reject":
                    row["done"] += 1         # a "no" to a question is an answer, not noise
                    continue
                if drop is not None and drop.by == MUTE_ACTOR:
                    row["muted"] += 1
                else:
                    row["dropped"] += 1
                    why = (drop.data.get("reason") if drop else None) or "unknown"
                    row["reasons"][why] = row["reasons"].get(why, 0) + 1
            elif state == "done":
                row["done"] += 1
            else:
                row["open"] += 1
        out = []
        for row in rows.values():
            row["share"] = round(row["dropped"] / row["filed"], 2) if row["filed"] else 0.0
            row["reasons"] = dict(sorted(row["reasons"].items()))
            out.append(row)
        # the most clicks first, then the worst share: two drops of two outrank two of thirty
        return sorted(out, key=lambda r: (-r["dropped"], -r["share"], r["source"]))

    def reopen(self, item_id: str, note: str | None = None) -> None:
        """Undo a close, drop, reject, defer or a yes that has not run yet: one more event, the item is open
        and needs a new yes."""
        state = self.get(item_id).state
        if state not in ("done", "dropped", "deferred", "approved", "waiting"):
            raise ValueError(f"{item_id} is not closed ({state})")
        self.event(item_id, "reopen", text=note)

    def close_by_key(self, key: str, note: str | None = None) -> list:
        """Close every live item filed under `key`. For a reporter that learns the condition is
        gone: it knows its key, not the item id. A dropped item stays dropped."""
        closed = []
        for item in self.items():
            if key and item.key == key and item.state not in ("done", "dropped"):
                self.close(item.id, note=note)
                closed.append(item.id)
        return closed

    # -------------------------------------------------- acting on the live source
    def check(self) -> list:
        closed = []
        for item in self.items():
            if item.state in ("done", "dropped") or not item.closes_when:
                continue
            if item.gate == "only-you" and _has_command(item.closes_when):
                continue                # only-you means nothing of it executes, a probe command included
            if probe(item.closes_when, now=self.clock(), gh=self.gh, base=self.base, item=item) is True:
                self.event(item.id, "close", by="check", text="closes_when holds")
                closed.append(item.id)
        return closed

    def runnable(self) -> list:
        ready = []
        for item in self.items():
            if not item.action or item.state not in ACTIVE_STATES or item.gate == "only-you":
                continue
            approval = item.approval
            if item.gate == "free" and approval is None:
                if item.last_failed:
                    continue        # a failed free action waits for a person, not for the next tick
                ready.append(item)
            elif approval is True:
                ready.append(item)
            elif isinstance(approval, dict):
                if probe(approval, now=self.clock(), gh=self.gh, base=self.base) is True:
                    ready.append(item)
        return ready

    def is_runner(self) -> bool:
        return self.runner is None or self.runner == self.actor

    def run(self, dry_run: bool = False) -> list:
        return self.run_report(dry_run)["ran"]

    def run_report(self, dry_run: bool = False) -> dict:
        """{"ran": [ids], "failed": [(id, exit)], "skipped": reason or None}."""
        if not self.is_runner():
            # A dry run still lists what is ready: the briefing on a machine that is
            # not the runner shows it as "ready, waiting for <runner>".
            ready = [i.id for i in self.runnable()] if dry_run else []
            return {"ran": ready, "failed": [], "skipped": f"{self.actor} is not the runner ({self.runner})"}
        executed, failed = [], []
        for item in self.runnable():
            if dry_run:
                executed.append(item.id)
                continue
            argv = item.action["argv"]
            try:
                done = subprocess.run(argv, capture_output=True, text=True, timeout=RUN_TIMEOUT_SEC,
                                      cwd=self.base if self.base.is_dir() else None)
                code, output = done.returncode, (done.stdout + done.stderr)[-OUTPUT_TAIL:]
            except (OSError, subprocess.SubprocessError) as exc:
                code, output = -1, str(exc)[-OUTPUT_TAIL:]
            if code == 0:
                self.event(item.id, "executed", exit=0, output=output.strip() or None)
                executed.append(item.id)
            else:
                self.event(item.id, "failed", exit=code, output=output.strip() or None)
                failed.append((item.id, code))
        return {"ran": executed, "failed": failed, "skipped": None}

    # -------------------------------------------------- views and validation
    def render(self) -> str:
        rows = self.open_items()
        lines = [
            "<!-- GENERATED by scripts/inbox.py render from work/inbox/. Do not edit: change an item",
            "     with scripts/inbox.py and regenerate. -->",
            "# Inbox",
            "",
            f"> As of {self.clock():%Y-%m-%d %H:%M} · {len(rows)} open",
            "",
        ]
        if not rows:
            lines.append("_Nothing waits for you._")
        else:
            lines += ["| # | Urgency | Due | Kind | What | Task | Gate | State | Id |",
                      "|---|---|---|---|---|---|---|---|---|"]
            for n, item in enumerate(rows, 1):
                summary = str(item.summary).replace("|", "\\|")
                runs = f"<br>runs `{' '.join(item.action['argv'])}`" if item.action else ""
                lines.append(f"| {n} | {item.urgency} | {item.due or ''} | {item.kind} | {summary}{runs} | {item.task or ''} "
                             f"| {item.gate} | {item.state} | `{item.id}` |")
        return "\n".join(lines) + "\n"

    def validate(self) -> list:
        problems = []
        if not self.root.is_dir():
            return problems
        for path in self._rule_files():
            try:
                problem = self._rule_problem(yaml.safe_load(path.read_text(encoding="utf-8")))
            except (OSError, yaml.YAMLError) as exc:
                problem = f"unreadable ({exc})"
            if problem:
                problems.append(f"{MUTES_DIR}/{path.name}: {problem}")
        for item_dir in sorted(p for p in self.root.iterdir() if p.is_dir() and not p.name.startswith("_")):
            where = item_dir.name
            try:
                data = yaml.safe_load((item_dir / "item.yaml").read_text(encoding="utf-8")) or {}
            except (OSError, yaml.YAMLError) as exc:
                problems.append(f"{where}: unreadable item.yaml ({exc})")
                continue
            for name in ("created", "from", "kind", "summary", "urgency", "gate"):
                if not data.get(name):
                    problems.append(f"{where}: missing {name}")
            for name, allowed in (("kind", KINDS), ("gate", GATES), ("urgency", URGENCIES)):
                if data.get(name) and data[name] not in allowed:
                    problems.append(f"{where}: {name} {data[name]!r} not in {allowed}")
            try:
                _check_action(data.get("action"))
            except ValueError as exc:
                problems.append(f"{where}: {exc}")
            for path in sorted((item_dir / "events").glob("*.yaml")):
                try:
                    verb = (yaml.safe_load(path.read_text(encoding="utf-8")) or {}).get("verb")
                except yaml.YAMLError:
                    verb = None
                if verb not in VERBS:
                    problems.append(f"{where}: event {path.name} has verb {verb!r}")
        return problems


# ---------------------------------------------------------------- CLI

def _json_arg(text: str | None):
    return json.loads(text) if text else None


def _default_actor() -> str:
    return os.environ.get("BRIDGE_ACTOR") or socket.gethostname().split(".")[0] or "bridge"


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="inbox.py", description="The Bridge inbox (docs/inbox.md).")
    p.add_argument("--root", type=Path, default=ROOT, help="repository root (default: this checkout)")
    p.add_argument("--by", default=None, help="who acts (default: $BRIDGE_ACTOR or the host name)")
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("add", help="file a new item (or record a repeat of an open item with the same --key)")
    a.add_argument("--from", dest="source", required=True)
    a.add_argument("--kind", required=True, choices=KINDS)
    a.add_argument("--summary", required=True)
    a.add_argument("--task")
    a.add_argument("--gate", default="your-yes", choices=GATES)
    a.add_argument("--urgency", default="today", choices=URGENCIES)
    a.add_argument("--due", help="YYYY-MM-DD or YYYY-MM-DDTHH:MM: when it happens or must be done")
    a.add_argument("--detail")
    a.add_argument("--key", help="dedup key: a watcher that fires again adds no second item")
    a.add_argument("--action-json")
    a.add_argument("--closes-when-json")
    a.add_argument("--closer", choices=CLOSERS,
                   help="who ends it when there is no probe: reporter, person or bot")
    a.add_argument("--quiet-after-close-h", type=float, default=None,
                   help="if a reader closed this key within N hours and the detail is unchanged, "
                        "record `seen` there, file nothing and print `quiet <id> <by> <at>`")

    ls = sub.add_parser("list", help="open items, most urgent first")
    ls.add_argument("--all", action="store_true")
    ls.add_argument("--json", action="store_true")
    ls.add_argument("--short", action="store_true", help="one line per item, for a phone or an e-ink screen")

    sub.add_parser("show").add_argument("id")
    ap = sub.add_parser("approve", help="say yes; with --when-json it runs once the condition holds")
    ap.add_argument("id")
    ap.add_argument("--when-json")
    ap.add_argument("--text", help="release an edited version of a draft")
    for name in ("reject", "close", "drop"):
        sp = sub.add_parser(name)
        sp.add_argument("id", nargs="?" if name == "close" else None)
        sp.add_argument("--note")
        if name == "close":
            sp.add_argument("--key", help="close every live item filed under this key instead of one id")
        if name == "drop":
            sp.add_argument("--reason", choices=DROP_REASONS,
                            help="why: once, duplicate, family (mute this kind of the source), "
                                 f"source (mute the source for {MUTE_SOURCE_DAYS} days)")
    ro = sub.add_parser("reopen", help="undo a close, drop, reject, defer or a yes not run yet: the item is open again")
    ro.add_argument("id")
    ro.add_argument("--note")
    df = sub.add_parser("defer")
    df.add_argument("id")
    df.add_argument("--until", required=True, help="YYYY-MM-DD")
    df.add_argument("--on", default=None, help="what it waits on (\"runs on\"): a person or a run; quiet until then")
    ur = sub.add_parser("urgency", help="re-prioritise an open item")
    ur.add_argument("id")
    ur.add_argument("value", choices=URGENCIES)
    nt = sub.add_parser("note")
    nt.add_argument("id")
    nt.add_argument("text")
    mu = sub.add_parser("mute", help="the mute rules in force")
    mu.add_argument("what", choices=("list",))
    mu.add_argument("--json", action="store_true")
    sub.add_parser("unmute", help="lift a mute rule").add_argument("id")
    st = sub.add_parser("stats", help="per source: filed, dropped by a person, muted, loudest first")
    st.add_argument("--days", type=int, default=30)
    st.add_argument("--json", action="store_true")
    sub.add_parser("check", help="close every item whose closes_when holds")
    rn = sub.add_parser("run", help="execute released actions (free, yes, or yes-once-condition)")
    rn.add_argument("--dry-run", action="store_true")
    sub.add_parser("render", help="regenerate work/inbox.md")
    sub.add_parser("validate")
    sy = sub.add_parser("sync", help="commit work/inbox/ (and only it), rebase, push; refuses foreign commits")
    sy.add_argument("--no-push", action="store_true")
    return p


def _short(item: Item) -> str:
    mark = {"now": "!", "today": "·", "later": " "}.get(item.urgency, " ")
    return f"{mark} {item.summary}" + (f"  [{item.task}]" if item.task else "")


INBOX_PATH = "work/inbox"


def _sync(root: Path, actor: str, push: bool) -> int:
    """Commit work/inbox/ (and nothing else), rebase onto the upstream, push.

    The generated view work/inbox.md is NOT committed here: every render rewrites
    its time stamp, so two machines committing it would conflict on every sync.
    The push refuses when the branch carries unpushed commits outside the inbox:
    "sync the inbox" must never ship somebody's unfinished work along with it.
    A rebase that conflicts is aborted, so the checkout is never left half-done.
    """
    def git(*args, timeout=120):
        return subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=timeout)

    if (root / INBOX_PATH).exists():
        git("add", "--", INBOX_PATH)
        if git("diff", "--cached", "--quiet", "--", INBOX_PATH).returncode != 0:
            msg = f"inbox: {actor} {dt.datetime.now():%Y-%m-%d %H:%M}"
            done = git("commit", "-m", msg, "--", INBOX_PATH)
            if done.returncode != 0:
                print(done.stderr.strip(), file=sys.stderr)
                return 1
    if not push:
        return 0
    if git("fetch", "--quiet").returncode != 0:
        print("inbox sync: fetch failed, the commit stays local for the next sync", file=sys.stderr)
        return 1
    if git("rev-parse", "--abbrev-ref", "@{u}").returncode != 0:
        print("inbox sync: the branch has no upstream to push to", file=sys.stderr)
        return 1
    outside = [p for p in git("diff", "--name-only", "@{u}...HEAD").stdout.split()
               if not p.startswith(INBOX_PATH + "/")]
    if outside:
        print(f"inbox sync: unpushed commits touch files outside {INBOX_PATH}/ "
              f"({', '.join(outside[:3])}); push them yourself, not pushing", file=sys.stderr)
        return 1
    # The view is derived, so a local rendering is thrown away rather than
    # autostashed: put back on top of a moved upstream copy it conflicts, and a
    # conflicting autostash pop leaves the index unmerged, which blocks every
    # later stash and rebase on this checkout (2026-10-07, hours of exit 65/75).
    if git("ls-files", "--error-unmatch", "--", "work/inbox.md").returncode == 0:
        git("checkout", "--", "work/inbox.md")
    done = git("rebase", "--autostash", "@{u}")
    if done.returncode != 0:
        git("rebase", "--abort")
        print(f"inbox sync: rebase onto the upstream failed and was aborted: {done.stderr.strip()[:200]}",
              file=sys.stderr)
        return 1
    done = git("push", "--quiet")
    if done.returncode != 0:
        print(f"inbox sync: push failed, the commit stays local: {done.stderr.strip()[:200]}", file=sys.stderr)
        return 1
    return 0


def _settings(root: Path) -> dict:
    """The `inbox:` block of bridge-config.yaml, empty when there is none or it cannot be read."""
    path = root / "bridge-config.yaml"
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {} if path.is_file() else {}
    except (OSError, yaml.YAMLError):
        return {}
    block = (data or {}).get("inbox") if isinstance(data, dict) else None
    return block if isinstance(block, dict) else {}


def _runner(root: Path) -> str | None:
    return _settings(root).get("runner")


def _all_clear(root: Path) -> tuple:
    words = _settings(root).get("all_clear") or ()
    return tuple(words) if isinstance(words, list) else ()


def main(argv=None) -> int:
    args = build_parser().parse_args(argv)
    actor = args.by or _default_actor()
    box = Inbox(args.root / "work" / "inbox", actor=actor, runner=_runner(args.root), all_clear=_all_clear(args.root))
    try:
        if args.cmd == "add" and args.quiet_after_close_h and args.key and (
                hit := box.recently_closed(args.key, args.detail, hours=args.quiet_after_close_h)):
            item, closed = hit
            box.event(item.id, "seen", summary=args.summary)
            print(f"quiet {item.id} {closed.by} {closed.at}")
        elif args.cmd == "add":
            print(box.add(source=args.source, kind=args.kind, summary=args.summary, task=args.task,
                          gate=args.gate, urgency=args.urgency, detail=args.detail, key=args.key, due=args.due,
                          action=_json_arg(args.action_json), closes_when=_json_arg(args.closes_when_json),
                          closer=args.closer))
        elif args.cmd == "list":
            items = box.items() if args.all else box.open_items()
            if args.json:
                print(json.dumps([i.as_dict() for i in items], ensure_ascii=False, indent=1))
            elif args.short:
                print("\n".join(_short(i) for i in items) if items else "Nothing waits.")
            else:
                for i in items:
                    print(f"{i.id}  {i.state:8} {i.urgency:5} {i.kind:8} {i.gate:8}  {i.summary}"
                          + (f"  [{i.task}]" if i.task else ""))
                    if i.action:            # a yes is a yes to THIS command, so it is always shown
                        print(f"    runs: {' '.join(i.action['argv'])}")
        elif args.cmd == "show":
            item = box.get(box.resolve(args.id))
            print(yaml.safe_dump(item.as_dict(), allow_unicode=True, sort_keys=False), end="")
            for e in item.events:
                print(f"  {e.at}  {e.by:12} {e.verb:9} {json.dumps(e.data, ensure_ascii=False) if e.data else ''}")
        elif args.cmd == "approve":
            box.approve(box.resolve(args.id), when=_json_arg(args.when_json), text=args.text)
        elif args.cmd == "close" and getattr(args, "key", None):
            for item_id in box.close_by_key(args.key, note=args.note):
                print(f"closed {item_id}")
        elif args.cmd == "drop":
            rule = box.drop(box.resolve(args.id), note=args.note, reason=args.reason)
            if rule:
                print(f"muted {rule}")
        elif args.cmd in ("reject", "close"):
            if not args.id:
                raise ValueError(f"{args.cmd} needs an id" + (" or --key" if args.cmd == "close" else ""))
            box.event(box.resolve(args.id), args.cmd, text=args.note)
        elif args.cmd == "mute":
            rules = box.mutes()
            if args.json:
                print(json.dumps(rules, ensure_ascii=False, indent=1, default=str))
            else:
                for r in rules:
                    what = r.get("key_prefix") or r.get("kind") or "everything"
                    print(f"{r['id']}  {r['source']}  {what}" + (f"  until {r['until']}" if r.get("until") else ""))
        elif args.cmd == "unmute":
            box.unmute(args.id)
        elif args.cmd == "stats":
            rows = box.stats(days=args.days)
            if args.json:
                print(json.dumps(rows, ensure_ascii=False, indent=1))
            else:
                for r in rows:
                    print(f"{r['share']:>5.0%}  {r['dropped']:>3}/{r['filed']:<3} {r['source']}"
                          + (f"  muted {r['muted']}" if r["muted"] else ""))
        elif args.cmd == "reopen":
            box.reopen(box.resolve(args.id), note=args.note)
            (args.root / "work" / "inbox.md").write_text(box.render(), encoding="utf-8")
        elif args.cmd == "defer":
            dt.date.fromisoformat(args.until)
            box.event(box.resolve(args.id), "defer", until=args.until, **({"waits_on": args.on} if args.on else {}))
        elif args.cmd == "urgency":
            box.set_urgency(box.resolve(args.id), args.value)
            (args.root / "work" / "inbox.md").write_text(box.render(), encoding="utf-8")
        elif args.cmd == "note":
            box.note(box.resolve(args.id), args.text)
        elif args.cmd == "check":
            for item_id in box.check():
                print(f"closed {item_id}")
        elif args.cmd == "run":
            report = box.run_report(dry_run=args.dry_run)
            if report["skipped"]:
                print(f"not running: {report['skipped']}")
            for item_id in report["ran"]:
                if report["skipped"]:
                    print(f"ready, waiting for {box.runner}: {item_id}")
                else:
                    print(("would run " if args.dry_run else "ran ") + item_id)
            for item_id, code in report["failed"]:
                print(f"failed {item_id} (exit {code})")
            return 1 if report["failed"] else 0
        elif args.cmd == "render":
            target = args.root / "work" / "inbox.md"
            target.write_text(box.render(), encoding="utf-8")
            print(f"{target.relative_to(args.root)} regenerated: {len(box.open_items())} open")
        elif args.cmd == "validate":
            problems = box.validate()
            for line in problems:
                print(line, file=sys.stderr)
            return 1 if problems else 0
        elif args.cmd == "sync":
            return _sync(args.root, actor, push=not args.no_push)
    except (KeyError, ValueError, PermissionError, json.JSONDecodeError) as exc:
        print(f"inbox: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
