# SPDX-License-Identifier: MIT
"""The shared record of rows settled in the cockpit: work/cockpit/settled/, tracked by git.

A row without a place of its own (a GitHub issue, an application, a deadline from a protocol) that
the person marked done or not doing, and any row put off with "not now until <day>", has to stay
settled on every machine. state.json lives under the ignored .bridge/, so each decision is written
here as well: one new file per decision, written once and never changed, the pattern of the inbox's
events. Two machines writing through git therefore only ever add different files, and a rebase has
nothing to merge. Taking a decision back ("show again", an undo) is a record too (`act: unsettle`),
never a deletion: a delete on one side and an older copy on the other would be the one git conflict
this layout avoids.

A file is `<UTC stamp>-<seq>-<rand>-<act>.yaml` with `key`, `act` (dismiss, hide, ack, unsettle) and, by
act, `outcome` and `title`, or `until`, or for a finding marked seen (`ack`, its key `ack:<row key>`) the
finding's fingerprint `fp`, the close `note` and the inbox item that closed it, if any. The latest file for a key decides (by name: the stamp sorts,
seq orders one machine's decisions within a second, rand keeps two machines' names apart). Entries
migrated from state.json are `legacy-<hash>-<act>.yaml`: the name is the hash of the entry, so two
machines migrating the same entry write the same file, and they sort before every dated decision.
Reading lists the folder on each call and parses only names not seen before, so a file a pull
brought counts without a restart; a file that is not a decision is skipped and read again next time,
since git writes a file in place and a read can meet it empty or cut short.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import os
import secrets
import tempfile
import threading
from pathlib import Path
from typing import Callable

import yaml

from .model import SETTLE_OUTCOMES, iso_date

SCHEMA_VERSION = 1
ACTS = ("dismiss", "hide", "ack", "unsettle")
ACK_PREFIX = "ack:"
LEGACY_PREFIX = "legacy-"
DATE_LEN = len("YYYY-MM-DD")


def _valid(data: object) -> dict | None:
    """The decision a file holds, or None when it is none."""
    if not isinstance(data, dict) or not isinstance(data.get("key"), str) or not data["key"]:
        return None
    act = data.get("act")
    if act == "dismiss":
        if data.get("outcome") not in SETTLE_OUTCOMES:
            return None
    elif act == "hide":
        if not isinstance(data.get("until"), str) or len(data["until"]) != DATE_LEN:
            return None
    elif act == "ack":
        if not isinstance(data.get("fp"), str) or not data["fp"]:
            return None
    elif act != "unsettle":
        return None
    return data


def _order(name: str) -> tuple[int, str]:
    return (0 if name.startswith(LEGACY_PREFIX) else 1, name)


class SettledStore:
    def __init__(self, folder: Path, clock: Callable[[], float]):
        self.folder = Path(folder)
        self.clock = clock                   # epoch ms, like the rest of the cockpit
        self.lock = threading.Lock()
        self._read: dict[str, dict] = {}     # file name -> its decision; a file that holds none is not kept

    # ------------------------------------------------------------ reading

    def _decisions(self) -> dict[str, dict]:
        """key -> the latest decision for it."""
        try:
            names = [n for n in os.listdir(self.folder) if n.endswith(".yaml") and not n.startswith(".")]
        except OSError:
            names = []
        with self.lock:
            for gone in set(self._read) - set(names):
                del self._read[gone]
            for name in names:
                if name not in self._read:
                    try:
                        data = yaml.safe_load((self.folder / name).read_text(encoding="utf-8"))
                    except (OSError, UnicodeDecodeError, yaml.YAMLError):
                        continue                 # half arrived or unreadable: try again on the next read
                    decision = _valid(data)
                    if decision is not None:     # an empty or cut-short file (git writes in place): read again
                        self._read[name] = decision
            latest: dict[str, dict] = {}
            for name in sorted(names, key=_order):
                data = self._read.get(name)
                if data is not None:
                    latest[data["key"]] = data
            return latest

    def knows(self, key: str) -> bool:
        return key in self._decisions()

    def keys(self) -> set[str]:
        return set(self._decisions())

    def state(self, today: str) -> tuple[set, dict, dict]:
        """One read: the keys the record decides, the hides that last beyond today (key -> the day it
        shows again) and the dismissals (key -> {outcome, at (the day), title}, state.json's shape)."""
        latest = self._decisions()
        hidden = {k: d["until"] for k, d in latest.items() if d["act"] == "hide" and d["until"] > today}
        dismissed = {k: {"outcome": d["outcome"], "at": str(d.get("day") or ""), "title": str(d.get("title") or "")[:200]}
                     for k, d in latest.items() if d["act"] == "dismiss"}
        return set(latest), hidden, dismissed

    def hidden(self, today: str) -> dict:
        return self.state(today)[1]

    def acks(self) -> tuple[set, dict]:
        """(the finding keys the record decides, the findings marked seen: row key -> {fp, day, note, inbox})"""
        latest = {k[len(ACK_PREFIX):]: d for k, d in self._decisions().items() if k.startswith(ACK_PREFIX)}
        return set(latest), {k: {"fp": d["fp"], "day": str(d.get("day") or ""), "note": str(d.get("note") or ""),
                                 "inbox": str(d.get("inbox") or "")} for k, d in latest.items() if d["act"] == "ack"}

    def read_inboxes(self) -> set:
        """Every inbox item a finding was ever marked seen by, in any decision kept, the taken back ones too: its
        close has been read, so an undo on any machine is not taken back by that close again"""
        self._decisions()
        with self.lock:
            return {str(d["inbox"]) for d in self._read.values()
                    if d["key"].startswith(ACK_PREFIX) and isinstance(d.get("inbox"), str) and d["inbox"]}

    def dismissed(self) -> dict:
        return self.state("")[2]

    # ------------------------------------------------------------ writing

    def _write(self, name: str, body: dict) -> bool:
        """Write a new file; never replaces one (os.link refuses an existing name). False when it was there."""
        self.folder.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".", suffix=".tmp", dir=str(self.folder))
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                handle.write(yaml.safe_dump(body, sort_keys=False, allow_unicode=True))
            try:
                os.link(tmp, self.folder / name)
            except FileExistsError:
                return False
            return True
        finally:
            try:
                os.unlink(tmp)
            except OSError:
                pass

    def _record(self, key: str, act: str, **data) -> None:
        now = dt.datetime.fromtimestamp(self.clock() / 1000, dt.timezone.utc)
        stamp = f"{now:%Y%m%dT%H%M%SZ}"
        body = {"schema_version": SCHEMA_VERSION, "key": key, "act": act,
                **{k: v for k, v in data.items() if v is not None},
                "day": iso_date(self.clock()), "at": now.isoformat(timespec="seconds").replace("+00:00", "Z")}
        try:
            seq = sum(1 for n in os.listdir(self.folder) if n.startswith(stamp + "-"))
        except OSError:
            seq = 0
        while not self._write(f"{stamp}-{seq:03d}-{secrets.token_hex(2)}-{act}.yaml", body):
            seq += 1

    def dismiss(self, key: str, outcome: str, title: str) -> None:
        if outcome not in SETTLE_OUTCOMES:
            raise ValueError(f"outcome must be one of {SETTLE_OUTCOMES}")
        self._record(key, "dismiss", outcome=outcome, title=str(title)[:200])

    def hide(self, key: str, until: str, title: str = "") -> None:
        self._record(key, "hide", until=until, title=str(title)[:200] or None)

    def unsettle(self, key: str) -> None:
        self._record(key, "unsettle")

    def ack(self, key: str, fp: str, note: str = "", inbox: str = "") -> None:
        self._record(ACK_PREFIX + key, "ack", fp=fp, note=str(note)[:400] or None, inbox=inbox or None)

    def unack(self, key: str) -> None:
        self._record(ACK_PREFIX + key, "unsettle")

    def migrate(self, hidden: dict, dismissed: dict) -> int:
        """Copy the legacy entries of state.json in, once: a key the record already knows is left to it
        (it may have been taken back on another machine). The file name is the entry's hash, so a second
        run, or a second machine with the same entry, writes nothing new. Returns the files written."""
        known = self.keys()
        written = 0
        entries = [(k, "dismiss", {"outcome": v.get("outcome"), "title": str(v.get("title") or "")[:200],
                                   "day": str(v.get("at") or "")}) for k, v in dismissed.items()]
        entries += [(k, "hide", {"until": v}) for k, v in hidden.items() if k not in dismissed]
        for key, act, data in entries:
            if key in known:
                continue
            body = {"schema_version": SCHEMA_VERSION, "key": key, "act": act, **data, "migrated": True}
            if _valid(body) is None:
                continue
            digest = hashlib.sha256(yaml.safe_dump(body, sort_keys=True, allow_unicode=True).encode("utf-8")).hexdigest()
            if self._write(f"{LEGACY_PREFIX}{digest[:16]}-{act}.yaml", body):
                written += 1
        return written
