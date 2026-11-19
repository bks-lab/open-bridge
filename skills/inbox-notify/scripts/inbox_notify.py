#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Inbox notifier: an item that needs a person now reaches that person's phone as a poll.

The inbox (docs/inbox.md) holds what needs a person. Nothing in it rings. A held answer
of a Bridge-Agent (filed by scripts/inbox-approve.py with urgency `now` and the actions
approve and reject) therefore waited unseen until it expired, and three notifiers grew in
three instances to close that gap. This is the generic one.

Each tick:

1. Select the open items that need a person now: urgency in `notify.urgencies` (default
   `now`), a non-empty `actions` list, and, when `notify.sources` is set, a `from` that
   starts with one of those prefixes. Every item not yet announced on this channel gets one
   text message (summary, detail, "valid until") and one poll whose options are the item's
   own `actions` in their display order (one vote). The poll's timestamp, the recipient's
   uuid and the verbs behind the options go onto the item as a note:

       notify poll <timestamp> <uuid> via <channel> options approve,reject

   That note is what makes the announcement happen once and what maps a vote back to its
   item. No state lives anywhere else.
2. Read the channel. A vote by the configured recipient on a known poll runs the verb
   behind the option through the inbox (approve, reject, drop, close; defer for
   `notify.defer_days`), notes `notify decided <verb> via <channel>`, terminates the poll
   and confirms with one line of text. A quoted reply to a poll on an item that offers
   `approve` releases the quoted text as the edited answer (`approve --text`). Votes from
   anyone else, on unknown polls, or withdrawn votes (empty option list) do nothing.
3. A poll whose item was decided elsewhere (the cockpit, a terminal) is terminated and the
   item noted `notify closed-elsewhere via <channel>`, so a phone never shows a live poll
   on a dead question.

Transport: signal-cli (the only one implemented; a second one is one class). Polls need
signal-cli 0.14.5 or newer and render in a direct chat. `receive` CONSUMES: nothing else may
run `signal-cli receive` on this account, it would swallow the votes. The tick is therefore
the account's only reader and takes a lock; a tick that finds the lock held exits 0 at once.

Config: `infra/channels/<slug>.yaml` (assets/channel.yaml is the template), the slug from
`--channel` or `inbox.notify_via` in bridge-config.yaml. Handles (`transport.account`,
`transport.recipient`) are plain values or `file://<path>` / `env://<NAME>` references.
Labels and texts come from `notify.labels` and `notify.texts`, English by default.

    inbox_notify.py [--root R] [--channel SLUG] tick [--dry-run] [--all]
    inbox_notify.py [--root R] [--channel SLUG] test
    inbox_notify.py [--root R] [--channel SLUG] show

Exit 0 after a tick (also when nothing was due), 2 on a config or usage problem before
anything was sent, 1 when the transport failed.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fcntl
import importlib.util
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    sys.exit("inbox-notify: PyYAML required (pip install pyyaml)")

REPO = Path(__file__).resolve().parents[3]
ACTOR = "inbox-notify"
#: The verbs a person may take on an item, in the order inbox.py knows them (PERSON_ACTIONS).
VERBS = ("approve", "reject", "defer", "drop", "close")
DEFAULT_LABELS = {"approve": "Approve", "reject": "Reject", "defer": "Defer", "drop": "Drop", "close": "Close",
                  "later": "Later"}
DEFAULT_TEXTS = {
    "heading": "Waiting for you: {summary}",
    "valid_until": "Valid until {when}",
    "hint": "Vote in the poll below. From a terminal: python3 scripts/inbox.py <verb> {id}",
    "edit_hint": "Quote the poll with your own text to release that text instead of the draft.",
    "cockpit": "Cockpit: {url}",
    "poll": "{summary}",
    "decided": "{label}: {summary}",
    "edited": "Released with your text: {summary}",
    "test": "inbox-notify test from {host}: if you read this, the channel works.",
    "test_poll": "Test poll: does this render in a direct chat?",
}
POLL_MARK = re.compile(r"notify poll (?P<ts>\d{10,16}) (?P<uuid>[0-9a-fA-F-]{36}) via (?P<channel>\S+)"
                       r" options (?P<verbs>[a-z,]+)")
DECIDED_MARK = "notify decided"
CLOSED_MARK = "notify closed-elsewhere"
MAX_PART = 700
MAX_POLL_QUESTION = 100
DATE_FMT = "%Y-%m-%d %H:%M"


class ConfigError(Exception):
    pass


def log(msg: str) -> None:
    print(f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {msg}", flush=True)


# ------------------------------------------------------------------------------ config

def resolve_ref(value, field: str) -> str:
    """A handle as a plain value, or `file://<path>` / `env://<NAME>` pointing at one."""
    raw = str(value or "").strip()
    if raw.startswith("file://"):
        path = Path(raw[len("file://"):]).expanduser()
        try:
            raw = path.read_text("utf-8").strip()
        except OSError as exc:
            raise ConfigError(f"{field}: {value} is not readable ({exc.strerror})") from exc
    elif raw.startswith("env://"):
        raw = os.environ.get(raw[len("env://"):], "").strip()
    if not raw:
        raise ConfigError(f"{field} is missing: nothing sent")
    return raw


def default_channel(root: Path) -> str | None:
    try:
        data = yaml.safe_load((root / "bridge-config.yaml").read_text("utf-8")) or {}
        value = (data.get("inbox") or {}).get("notify_via")
        return str(value).strip() if value else None
    except (OSError, yaml.YAMLError, AttributeError):
        return None


def load_channel(root: Path, slug: str) -> dict:
    path = root / "infra" / "channels" / f"{slug}.yaml"
    if not path.is_file():
        raise ConfigError(f"infra/channels/{slug}.yaml not found (copy skills/inbox-notify/assets/channel.yaml)")
    try:
        data = yaml.safe_load(path.read_text("utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ConfigError(f"infra/channels/{slug}.yaml: {exc}") from exc
    if not isinstance(data, dict):
        raise ConfigError(f"infra/channels/{slug}.yaml: not a mapping")
    transport = data.get("transport") or {}
    kind = str(transport.get("kind") or "signal-cli")
    if kind != "signal-cli":
        raise ConfigError(f"transport.kind: {kind} is not implemented (signal-cli is)")
    notify = data.get("notify") or {}
    labels = {**DEFAULT_LABELS, **{str(k): str(v) for k, v in (notify.get("labels") or {}).items()}}
    texts = {**DEFAULT_TEXTS, **{str(k): str(v) for k, v in (notify.get("texts") or {}).items()}}
    urgencies = [str(u) for u in (notify.get("urgencies") or ["now"])]
    sources = [str(s) for s in (notify.get("sources") or [])]
    recipient = transport.get("recipient") or (data.get("access") or {}).get("self")
    return {
        "slug": slug,
        "binary": str(transport.get("binary") or "signal-cli"),
        "account": resolve_ref(transport.get("account"), "transport.account"),
        "recipient": resolve_ref(recipient, "transport.recipient"),
        "receive_timeout_sec": int(transport.get("receive_timeout_sec") or 20),
        "urgencies": urgencies,
        "sources": sources,
        "labels": labels,
        "texts": texts,
        "cockpit_url": str(notify.get("cockpit_url") or ""),
        "defer_days": int(notify.get("defer_days") or 1),
        "service_label": str((data.get("runtime") or {}).get("service_label") or ""),
    }


# ------------------------------------------------------------------------------ inbox

def load_inbox_module(root: Path):
    """scripts/inbox.py of THIS checkout (the data root may be another tree, in tests)."""
    for base in (root, REPO):
        path = base / "scripts" / "inbox.py"
        if path.is_file():
            break
    else:  # pragma: no cover
        raise ConfigError("scripts/inbox.py not found")
    spec = importlib.util.spec_from_file_location("inbox", path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise ConfigError("cannot load scripts/inbox.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("inbox", module)
    previous, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def notes_of(item) -> list[str]:
    return [str(e.data.get("text") or "") for e in item.events if e.verb == "note"]


def poll_of(item, channel: str) -> dict | None:
    """The last poll announced for this item on this channel: {ts, uuid, verbs}, or None."""
    found = None
    for text in notes_of(item):
        m = POLL_MARK.search(text)
        if m and m.group("channel") == channel:
            found = {"ts": m.group("ts"), "uuid": m.group("uuid").lower(),
                     "verbs": [v for v in m.group("verbs").split(",") if v]}
    return found


def is_settled(item, channel: str) -> bool:
    """Decided through this channel, or its poll already terminated because it was decided elsewhere."""
    return any(t.startswith((f"{DECIDED_MARK} ", CLOSED_MARK)) and f"via {channel}" in t for t in notes_of(item))


def wants_notice(item, cfg: dict) -> bool:
    if item.state != "open":
        return False
    if str(item.urgency) not in cfg["urgencies"]:
        return False
    actions = item.actions
    if not isinstance(actions, list) or not actions:
        return False
    source = str(item.source or "")
    return not cfg["sources"] or any(source.startswith(p) for p in cfg["sources"])


# ------------------------------------------------------------------------------ texts

def clip(text: str, n: int = MAX_PART) -> str:
    text = (text or "").strip()
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def one_line(text: str, n: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 1].rstrip(" ,;:") + "…"


def fmt_when(value) -> str:
    if not value:
        return ""
    try:
        return dt.datetime.fromisoformat(str(value)).astimezone().strftime(DATE_FMT)
    except ValueError:
        return str(value)


def detail_parts(detail: str) -> list[str]:
    """inbox-approve.py writes "Question:\\n…\\n\\nDrafted answer:\\n…"; each half is clipped on its own so the
    draft survives a long question. Any other detail is one clipped block."""
    detail = (detail or "").strip()
    if "Drafted answer:" in detail:
        question, _, draft = detail.partition("Drafted answer:")
        return [clip(question.strip()), "Drafted answer:\n" + clip(draft.strip())]
    return [clip(detail)] if detail else []


def build_message(item, cfg: dict) -> str:
    texts = cfg["texts"]
    lines = [texts["heading"].format(summary=item.summary, id=item.id), ""]
    for part in detail_parts(str(item.detail or "")):
        lines += [part, ""]
    when = fmt_when(item.expires_at)
    if when:
        lines += [texts["valid_until"].format(when=when), ""]
    lines.append(texts["hint"].format(id=item.id))
    if "approve" in (item.actions or []):
        lines.append(texts["edit_hint"])
    if cfg["cockpit_url"]:
        lines.append(texts["cockpit"].format(url=cfg["cockpit_url"]))
    return "\n".join(lines).rstrip()


def poll_question(item, cfg: dict) -> str:
    return one_line(cfg["texts"]["poll"].format(summary=item.summary, id=item.id), MAX_POLL_QUESTION)


def poll_options(item, cfg: dict) -> tuple[list[str], list[str]]:
    """(verbs, labels) for the poll. Signal needs two options, so a single verb gets a no-op `later`."""
    verbs = [v for v in (item.actions or []) if v in VERBS]
    if len(verbs) == 1:
        verbs.append("later")
    return verbs, [cfg["labels"][v] for v in verbs]


# ------------------------------------------------------------------------------ transport

class SignalCli:
    """The one transport. Every call is one signal-cli process; the account is the sender."""

    def __init__(self, cfg: dict, run=subprocess.run):
        self.binary = cfg["binary"]
        self.account = cfg["account"]
        self.recipient = cfg["recipient"]
        self.receive_timeout = cfg["receive_timeout_sec"]
        self._run = run

    def _recipient_args(self) -> list[str]:
        """`u:<name>` is `-u <name>` (the positional form is refused by sendPoll*), a number stays positional."""
        if self.recipient.startswith("u:"):
            return ["-u", self.recipient[2:]]
        return [self.recipient]

    def _call(self, *args: str, timeout: int = 120) -> subprocess.CompletedProcess:
        return self._run([self.binary, "-a", self.account, "-o", "json", *args], capture_output=True, text=True,
                         timeout=timeout)

    def send_text(self, message: str) -> bool:
        out = self._call("send", "-m", message, *self._recipient_args())
        if out.returncode != 0:
            log(f"signal-cli send failed ({out.returncode}): {out.stderr.strip()[:300]}")
        return out.returncode == 0

    def send_poll(self, question: str, options: list[str]) -> tuple[str, str] | None:
        """(poll timestamp, recipient uuid) or None."""
        out = self._call("sendPollCreate", *self._recipient_args(), "-q", question, "--no-multi", "-o", *options)
        if out.returncode != 0:
            log(f"signal-cli sendPollCreate failed ({out.returncode}): {out.stderr.strip()[:300]}")
            return None
        try:
            data = json.loads(out.stdout.strip().splitlines()[-1])
            ts = str(data["timestamp"])
            ok = [r for r in data.get("results", []) if r.get("type") == "SUCCESS"]
            uuid = str(ok[0]["recipientAddress"]["uuid"]).lower()
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            log(f"signal-cli sendPollCreate: unreadable reply ({exc}): {out.stdout[:200]}")
            return None
        return ts, uuid

    def terminate_poll(self, ts: str) -> None:
        out = self._call("sendPollTerminate", *self._recipient_args(), "--poll-timestamp", ts)
        if out.returncode != 0:
            log(f"signal-cli sendPollTerminate {ts} failed ({out.returncode}): {out.stderr.strip()[:200]}")

    def receive(self) -> list[dict]:
        """Votes and quoted replies, in arrival order.

        vote:  {kind: vote, ts, options, voter_uuid, vote_count}
        quote: {kind: quote, ts, text, voter_uuid}
        """
        try:
            out = self._call("receive", "-t", str(self.receive_timeout), timeout=self.receive_timeout + 60)
        except subprocess.SubprocessError as exc:
            log(f"signal-cli receive failed: {exc}")
            return []
        if out.returncode != 0:
            log(f"signal-cli receive failed ({out.returncode}): {out.stderr.strip()[:200]}")
        events = []
        for line in out.stdout.splitlines():
            line = line.strip()
            if not line.startswith("{"):
                continue
            try:
                env = json.loads(line).get("envelope") or {}
            except (ValueError, AttributeError):
                continue
            data = env.get("dataMessage") or {}
            voter = str(env.get("sourceUuid") or "").lower()
            vote = data.get("pollVote")
            if vote:
                events.append({"kind": "vote", "ts": str(vote.get("targetSentTimestamp") or ""),
                               "options": list(vote.get("optionIndexes") or []), "voter_uuid": voter,
                               "vote_count": int(vote.get("voteCount") or 0)})
                continue
            quote = data.get("quote")
            text = str(data.get("message") or "").strip()
            if quote and text:
                events.append({"kind": "quote", "ts": str(quote.get("id") or ""), "text": text, "voter_uuid": voter})
        return events


# ------------------------------------------------------------------------------ the tick

def announce(box, item, cfg: dict, transport: SignalCli, dry_run: bool) -> bool:
    verbs, labels = poll_options(item, cfg)
    message = build_message(item, cfg)
    question = poll_question(item, cfg)
    if dry_run:
        print(f"----- {item.id}\n{message}\n[poll] {question} :: {' / '.join(labels)}")
        return False
    if not transport.send_text(message):
        return False
    poll = transport.send_poll(question, labels)
    if not poll:
        # The text went out, the poll did not: the next tick sends both again. Twice beats never.
        return False
    ts, uuid = poll
    box.note(item.id, f"notify poll {ts} {uuid} via {cfg['slug']} options {','.join(verbs)} "
                      f"sent {dt.datetime.now().astimezone():%Y-%m-%dT%H:%M:%S%z}")
    log(f"announced {item.id} (poll {ts})")
    return True


def execute(box, inbox, item, verb: str, cfg: dict, text: str | None = None) -> bool:
    try:
        if verb == "approve":
            box.approve(item.id, text=text)
        elif verb == "reject":
            box.reject(item.id, note=f"rejected via {cfg['slug']}")
        elif verb == "drop":
            box.drop(item.id, note=f"dropped via {cfg['slug']}")
        elif verb == "close":
            box.close(item.id, note=f"closed via {cfg['slug']}")
        elif verb == "defer":
            until = (dt.date.today() + dt.timedelta(days=cfg["defer_days"])).isoformat()
            box.event(item.id, "defer", until=until)
        else:
            return False
    except Exception as exc:  # noqa: BLE001  (inbox.py raises plain exceptions on a bad state)
        log(f"{verb} on {item.id} failed: {exc}")
        return False
    return True


def settle_polls(box, cfg: dict, transport: SignalCli) -> int:
    """Terminate the poll of every item that was decided elsewhere, once."""
    done = 0
    for item in box.items():
        poll = poll_of(item, cfg["slug"])
        if not poll or item.state == "open" or is_settled(item, cfg["slug"]):
            continue
        transport.terminate_poll(poll["ts"])
        box.note(item.id, f"{CLOSED_MARK} via {cfg['slug']} ({item.state}) "
                          f"{dt.datetime.now().astimezone():%Y-%m-%dT%H:%M:%S%z}")
        log(f"{item.id}: decided elsewhere ({item.state}), poll {poll['ts']} terminated")
        done += 1
    return done


def act_on(box, inbox, cfg: dict, transport: SignalCli, events: list[dict]) -> int:
    if not events:
        return 0
    index: dict[str, tuple] = {}
    for item in box.items():
        poll = poll_of(item, cfg["slug"])
        if poll:
            index[poll["ts"]] = (item, poll)
    # One decision per poll and tick: the last vote wins (voteCount rises on every change).
    latest: dict[str, dict] = {}
    for ev in events:
        prev = latest.get(ev["ts"])
        if prev is None or ev["kind"] == "quote" or ev.get("vote_count", 0) >= prev.get("vote_count", 0):
            latest[ev["ts"]] = ev
    done = 0
    for ts, ev in latest.items():
        hit = index.get(ts)
        if not hit:
            log(f"{ev['kind']} on unknown poll {ts} ignored")
            continue
        item, poll = hit
        if ev["voter_uuid"] != poll["uuid"]:
            log(f"{ev['kind']} on {item.id} from another identity ignored")
            continue
        item = box.get(item.id)
        if item.state != "open" or is_settled(item, cfg["slug"]):
            log(f"{ev['kind']} on {item.id}: already decided, poll terminated")
            transport.terminate_poll(ts)
            continue
        if ev["kind"] == "quote":
            if "approve" not in poll["verbs"]:
                log(f"quoted reply on {item.id} ignored: the item offers no approve")
                continue
            if not execute(box, inbox, item, "approve", cfg, text=ev["text"]):
                continue
            verb, confirmation = "approve", cfg["texts"]["edited"].format(summary=item.summary, id=item.id)
        else:
            if not ev["options"]:
                log(f"vote on {item.id} withdrawn, nothing done")
                continue
            idx = ev["options"][0]
            verb = poll["verbs"][idx] if 0 <= idx < len(poll["verbs"]) else None
            if verb is None:
                log(f"vote on {item.id} with unknown option {idx}, nothing done")
                continue
            if verb == "later":
                log(f"vote on {item.id}: later, nothing done")
                continue
            if not execute(box, inbox, item, verb, cfg):
                continue
            confirmation = cfg["texts"]["decided"].format(label=cfg["labels"][verb], summary=item.summary, id=item.id)
        box.note(item.id, f"{DECIDED_MARK} {verb} via {cfg['slug']} "
                          f"{dt.datetime.now().astimezone():%Y-%m-%dT%H:%M:%S%z}")
        transport.terminate_poll(ts)
        transport.send_text(confirmation)
        log(f"executed {verb} on {item.id}")
        done += 1
    return done


def lock_path(root: Path, slug: str) -> Path:
    return root / ".bridge" / f"inbox-notify.{slug}.lock"


def tick(root: Path, cfg: dict, *, dry_run: bool, all_items: bool, run=subprocess.run) -> int:
    inbox = load_inbox_module(root)
    box = inbox.Inbox(root / "work" / "inbox", actor=ACTOR)
    transport = SignalCli(cfg, run=run)
    items = [it for it in box.items() if wants_notice(it, cfg)]
    todo = [it for it in items if all_items or not poll_of(it, cfg["slug"])]
    log(f"{len(items)} item(s) need a person now, {len(todo)} to announce")
    sent = sum(1 for it in todo if announce(box, it, cfg, transport, dry_run))
    if dry_run:
        log(f"dry run: {sent} sent, nothing read")
        return 0
    settled = settle_polls(box, cfg, transport)
    executed = act_on(box, inbox, cfg, transport, transport.receive())
    log(f"done: {sent} announced, {executed} executed, {settled} settled elsewhere")
    return 0


def test_send(cfg: dict, run=subprocess.run) -> int:
    transport = SignalCli(cfg, run=run)
    if not transport.send_text(cfg["texts"]["test"].format(host=socket.gethostname())):
        return 1
    poll = transport.send_poll(cfg["texts"]["test_poll"], ["Yes", "No"])
    if not poll:
        return 1
    log(f"test text and poll sent (poll {poll[0]}); vote on the phone, a tick will log the vote as unknown poll")
    return 0


def show(cfg: dict) -> int:
    shown = {k: v for k, v in cfg.items() if k not in ("texts", "labels")}
    shown["labels"] = cfg["labels"]
    print(yaml.safe_dump(shown, sort_keys=False, allow_unicode=True).rstrip())
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="inbox_notify.py", description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--root", type=Path, default=REPO, help="Bridge root (default: this checkout)")
    ap.add_argument("--channel", help="slug under infra/channels/ (default: inbox.notify_via in bridge-config.yaml)")
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("tick", help="announce what is new, read votes, execute them")
    t.add_argument("--dry-run", action="store_true", help="print what would be sent, send nothing, read nothing")
    t.add_argument("--all", action="store_true", help="announce already announced items again (a new poll)")
    sub.add_parser("test", help="send one test text and one test poll to the recipient")
    sub.add_parser("show", help="print the resolved configuration")
    args = ap.parse_args(argv)

    root = args.root.resolve()
    slug = args.channel or default_channel(root)
    if not slug:
        print("inbox-notify: no channel: pass --channel or set inbox.notify_via in bridge-config.yaml", file=sys.stderr)
        return 2
    try:
        cfg = load_channel(root, slug)
    except ConfigError as exc:
        print(f"inbox-notify: {exc}", file=sys.stderr)
        return 2
    if args.cmd == "show":
        return show(cfg)
    if not shutil.which(cfg["binary"]):
        print(f"inbox-notify: {cfg['binary']} not found on PATH", file=sys.stderr)
        return 2
    if args.cmd == "test":
        return test_send(cfg)

    path = lock_path(root, slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+") as handle:
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            log(f"another tick holds {path.name}; this one exits (the account has one reader)")
            return 0
        return tick(root, cfg, dry_run=args.dry_run, all_items=args.all)


if __name__ == "__main__":
    sys.exit(main())
