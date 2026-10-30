# SPDX-License-Identifier: MIT
"""The whole conversation of a tab, searchable, for the tab view (GET /api/tab-history).

The screen of a tab is what the terminal shows now. A tab that runs an agent session has more: the session's
transcript (~/.claude/projects/<folder>/<session id>.jsonl). The tab is tied to its session by the live
session list (sessions.py): the process of a session carries the CMUX_SURFACE_ID or TMUX_PANE of its tab, the
scan matches that to the tab list, and the newest session of a tab decides. A transcript gives a person's
words, the agent's words and one short line per tool call (`Bash: git status`); never a tool's result,
thinking, the harness's reminders, the turns of a subagent or a meta line. A tab with no session, or whose
file is gone, answers from the terminal: its scrollback read through the driver (HISTORY_LINES lines; a
shell tab keeps it all, an agent repaints its screen and keeps only that), cut into blocks at the blank lines.

A transcript is streamed line by line, never read whole, and its parsed form is kept by path, mtime and size
(CACHE_MAX files). A file that only grew is read from where the last read ended (the 64 bytes before that
point must be the same, else it is read again from the start), and a last line still being written waits
until it is whole. A line that does not parse, or is longer than LINE_MAX, is skipped. At most STORE_MAX
turns are kept per file, the newest; the rest is counted (`dropped`) and flagged `truncated`. Every text goes
through the cockpit's scrub before it is kept, so the search cannot find what the scrub hides.

An answer is the newest matching turns in order, at most `limit` and ANSWER_BYTES of text, `before` pages back
to older ones (a turn's `i` is its place in the conversation). A search is a plain case-insensitive substring
over the text. Everything here reads; nothing is written and no agent runs.
"""
from __future__ import annotations

import collections
import json
import re
import threading
from pathlib import Path
from typing import Any, Callable

from .sessions import NOISE_RE, claude_dir, event_ms, transcript_path

HISTORY_LINES = 5000        # what the terminal is asked for; workplace.py and the drivers let this many through
HISTORY_TIMEOUT = 20
TERMINAL_CACHE_MS = 2000    # a search typed letter by letter reads the scrollback once
TERMINAL_MAX = 2_000_000    # characters of scrollback kept, the end
BLOCK_LINES = 30            # a block of the terminal is at most this long
LINE_MAX = 8 * 1024 * 1024  # a transcript line longer than this is skipped unread
TURN_MAX = 20_000           # characters kept of one turn
TOOL_MAX = 200              # a tool call's line
STORE_MAX = 50_000          # turns kept of one conversation, the newest
CACHE_MAX = 4               # parsed transcripts kept
ANCHOR = 64                 # bytes before the end of the last read that must be unchanged for a read to go on from it
ANSWER_TURNS = 200
ANSWER_TURNS_MAX = 500
ANSWER_BYTES = 256 * 1024   # text in one answer
QUERY_MAX = 200
SID_RE = re.compile(r"[0-9a-f-]{36}")
# what names a tool call best, in this order; else its first text
TOOL_KEYS = ("command", "file_path", "pattern", "query", "url", "path", "description", "skill", "prompt")
COMMAND_RE = re.compile(r"<command-name>(.*?)</command-name>", re.S)
ARGS_RE = re.compile(r"<command-args>(.*?)</command-args>", re.S)


def cut(text: str, cap: int) -> str:
    return text if len(text) <= cap else text[:cap - 1] + "…"


def tool_line(block: dict) -> str:
    """One short line for a tool call: its name and the input that names it best, never its output"""
    name = cut(str(block.get("name") or "tool"), 60)
    data = block.get("input") if isinstance(block.get("input"), dict) else {}
    detail = next((data[k] for k in TOOL_KEYS if isinstance(data.get(k), str) and data[k].strip()), None)
    if detail is None:
        detail = next((v for v in data.values() if isinstance(v, str) and v.strip()), "")
    detail = " ".join(detail.split())
    return cut(f"{name}: {detail}" if detail else name, TOOL_MAX)


def person_text(text: str) -> str:
    """What the person typed: without the harness's reminders and command output; a slash command as typed"""
    command = COMMAND_RE.search(text)
    if command:
        args = ARGS_RE.search(text)
        return " ".join(x for x in (command.group(1).strip(), args.group(1).strip() if args else "") if x)
    return NOISE_RE.sub(" ", text).strip()


def event_turns(entry: Any) -> list[tuple[str, str]]:
    """(role, text) of the turns a transcript event makes: user, agent or tool. None from a tool's result,
    thinking, a subagent's or a meta line, and from any event that is no person's or agent's"""
    if not isinstance(entry, dict) or entry.get("type") not in ("user", "assistant"):
        return []
    if entry.get("isSidechain") or entry.get("isMeta") or entry.get("isCompactSummary"):
        return []
    message = entry.get("message") if isinstance(entry.get("message"), dict) else {}
    content = message.get("content")
    blocks = [{"type": "text", "text": content}] if isinstance(content, str) else content if isinstance(content, list) else []
    person = entry["type"] == "user"
    out = []
    for b in blocks:
        if not isinstance(b, dict):
            continue
        if b.get("type") == "text" and isinstance(b.get("text"), str):
            text = person_text(b["text"]) if person else b["text"].strip()
            if text:
                out.append(("user" if person else "agent", text))
        elif b.get("type") == "tool_use" and not person:
            out.append(("tool", tool_line(b)))
    return out


def read_turns(path: Path, start: int = 0, scrub: Callable[[str], str] = str, keep: int | None = None) -> tuple[list[dict], int, int]:
    """(turns, offset, dropped) of a transcript from byte `start`, streamed: the newest `keep` turns (STORE_MAX),
    where the last whole line ended, and how many older turns were let go. A line that does not parse or is too
    long is skipped; a last line without its newline counts only once it parses."""
    keep = STORE_MAX if keep is None else keep
    turns: collections.deque = collections.deque(maxlen=keep)
    seen, offset = 0, start
    try:
        with open(path, "rb") as fh:
            fh.seek(start)
            while True:
                raw = fh.readline(LINE_MAX + 1)
                if not raw:
                    break
                whole = raw.endswith(b"\n")
                if len(raw) > LINE_MAX and not whole:       # too long to read: the rest of it goes unread
                    size = len(raw)
                    while True:
                        rest = fh.readline(LINE_MAX)
                        size += len(rest)
                        if not rest or rest.endswith(b"\n"):
                            break
                    offset += size
                    continue
                entry = None
                if not whole or b'"user"' in raw or b'"assistant"' in raw:
                    try:
                        entry = json.loads(raw.decode("utf-8", errors="replace"))
                    except ValueError:
                        if not whole:
                            break                           # still being written: wait until it is whole
                offset += len(raw)
                found = event_turns(entry)
                at = event_ms(entry) if found else None
                for role, text in found:
                    turns.append({"role": role, "text": cut(scrub(text), TURN_MAX), "at_ms": at})
                    seen += 1
    except OSError:
        pass
    return list(turns), offset, seen - len(turns)


def anchor_of(path: Path, offset: int) -> bytes:
    """The bytes just before `offset`: unchanged, a file that grew is the same file"""
    try:
        with open(path, "rb") as fh:
            fh.seek(max(0, offset - ANCHOR))
            return fh.read(min(offset, ANCHOR))
    except OSError:
        return b""


def find_transcript(base: Path, cwd: Any, sid: str) -> Path | None:
    """The file of a session: where its folder puts it, else the project folder that holds a file of its id"""
    if not SID_RE.fullmatch(sid):
        return None
    if isinstance(cwd, str):
        path = transcript_path(base, cwd, sid)
        if path.is_file():
            return path
    try:
        return next(iter(sorted(base.glob(f"projects/*/{sid}.jsonl"))), None)
    except OSError:
        return None


def blocks_of(text: str) -> list[dict]:
    """The scrollback of a terminal as turns: runs of lines between blank lines, none longer than BLOCK_LINES"""
    out: list[dict] = []
    block: list[str] = []

    def flush() -> None:
        if block:
            out.append({"role": "terminal", "text": "\n".join(block), "at_ms": None})
            block.clear()
    for line in text.splitlines():
        if not line.strip():
            flush()
            continue
        block.append(line.rstrip())
        if len(block) >= BLOCK_LINES:
            flush()
    flush()
    return out


def paging(limit: str, before: str) -> tuple[int, int | None]:
    """(turns wanted, the place the turns must come before) from the two words of the query; the limit is held to
    1..ANSWER_TURNS_MAX. A word that is no number raises ValueError naming itself."""
    try:
        n = int(limit) if limit else ANSWER_TURNS
    except ValueError:
        raise ValueError("limit") from None
    try:
        b = int(before) if before else None
    except ValueError:
        raise ValueError("before") from None
    if b is not None and b < 0:
        raise ValueError("before")
    return max(1, min(n, ANSWER_TURNS_MAX)), b


def window(turns: list[dict], dropped: int, q: str, limit: int, before: int | None) -> dict:
    """The answer over kept turns: those whose text holds `q` (case-insensitive, plain), the newest `limit` of the
    ones before place `before`, as many as fit ANSWER_BYTES (at least one), oldest first. `total` counts the turns
    of the conversation, `matched` those that match; `truncated` says older turns are left out or no longer kept."""
    needle = q.casefold()
    numbered = [(dropped + k, t) for k, t in enumerate(turns)]
    if needle:
        numbered = [(i, t) for i, t in numbered if needle in t["text"].casefold()]
    matched = len(numbered)
    if before is not None:
        numbered = [(i, t) for i, t in numbered if i < before]
    picked, size = [], 0
    for i, t in reversed(numbered[-limit:]):
        size += len(t["text"].encode("utf-8"))
        if picked and size > ANSWER_BYTES:
            break
        picked.append({"i": i, **t})
    picked.reverse()
    return {"turns": picked, "total": dropped + len(turns), "matched": matched,
            "truncated": len(picked) < len(numbered) or dropped > 0}


class TabHistory:
    def __init__(self, app: Any):
        self.app = app
        self.lock = threading.Lock()
        self.cache: collections.OrderedDict[str, dict] = collections.OrderedDict()   # path -> the parsed transcript
        self.screen_lock = threading.Lock()
        self.screens: dict[str, tuple[float, list[dict]]] = {}                       # ref -> (read at ms, blocks)

    def transcript_of(self, ref: str) -> Path | None:
        """The transcript of the newest live session in a tab; None where the tab runs none or its file is gone"""
        base = Path(self.app.sessions.base or claude_dir())
        live = [x for x in self.app.sessions.state() if (x.get("tab") or {}).get("ref") == ref and x.get("sid")]
        live.sort(key=lambda x: -(x.get("started_ms") or 0))
        for x in live:
            path = find_transcript(base, x.get("cwd"), x["sid"])
            if path:
                return path
        return None

    def session_turns(self, path: Path) -> tuple[list[dict], int] | None:
        """(turns, dropped) of a transcript, read once while it stays as it is and from where it ended once it
        grew; None when the file cannot be read"""
        key = str(path)
        try:
            st = path.stat()
        except OSError:
            with self.lock:
                self.cache.pop(key, None)
            return None
        stamp = (st.st_mtime_ns, st.st_size)          # taken before the read: a file that grows meanwhile is read on
        with self.lock:
            got = self.cache.get(key)
            if got and got["stamp"] == stamp:
                self.cache.move_to_end(key)
                return list(got["turns"]), got["dropped"]
            start, kept, dropped = 0, [], 0
            if got and got["offset"] <= st.st_size and anchor_of(path, got["offset"]) == got["anchor"]:
                start, kept, dropped = got["offset"], got["turns"], got["dropped"]
            new, offset, cut_ = read_turns(path, start, self.app.scrub)
            turns, dropped = kept + new, dropped + cut_
            over = len(turns) - STORE_MAX
            if over > 0:
                turns, dropped = turns[over:], dropped + over
            self.cache[key] = {"stamp": stamp, "offset": offset, "anchor": anchor_of(path, offset),
                               "turns": turns, "dropped": dropped}
            self.cache.move_to_end(key)
            while len(self.cache) > CACHE_MAX:
                self.cache.popitem(last=False)
            return list(turns), dropped

    def terminal_turns(self, ref: str) -> tuple[list[dict] | None, str]:
        """(blocks, error) of a tab's scrollback through the terminal driver, kept for TERMINAL_CACHE_MS"""
        with self.screen_lock:
            now = self.app.clock()
            hit = self.screens.get(ref)
            if hit and 0 <= now - hit[0] < TERMINAL_CACHE_MS:
                return hit[1], ""
            run = self.app.run(self.app.workplace("screen", ref, "--lines", str(HISTORY_LINES), "--json"), HISTORY_TIMEOUT)
            try:
                raw = json.loads(run.out).get("text") if run.ok else None
            except (ValueError, AttributeError):
                raw = None
            if not isinstance(raw, str):
                self.screens.pop(ref, None)
                return None, (run.err or run.out or "the tab could not be read").strip()
            text = self.app.scrub("\n".join(line.rstrip() for line in raw.splitlines()).strip("\n")[-TERMINAL_MAX:])
            blocks = blocks_of(text)
            self.screens = {k: v for k, v in self.screens.items() if 0 <= now - v[0] < TERMINAL_CACHE_MS}
            self.screens[ref] = (now, blocks)
            return blocks, ""

    def read(self, ref: str, q: str = "", limit: int = ANSWER_TURNS, before: int | None = None) -> tuple[dict | None, str]:
        """(answer, error) for a tab: {source, turns, total, matched, truncated}, from the transcript of its session,
        else from the terminal; None and why when the terminal cannot be read either"""
        path = self.transcript_of(ref)
        got = self.session_turns(path) if path else None
        if got:
            return {"source": "session", **window(got[0], got[1], q, limit, before)}, ""
        blocks, err = self.terminal_turns(ref)
        if blocks is None:
            return None, err
        return {"source": "terminal", **window(blocks, 0, q, limit, before)}, ""
