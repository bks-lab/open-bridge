# SPDX-License-Identifier: MIT
"""The tokens Claude Code used on this machine in the last seven days, for the Betrieb page.

Every answer of the model stands in the transcript of its session (~/.claude/projects/<slug>/<session>.jsonl,
a subagent's in <session>/subagents/agent-*.jsonl) with its model and `usage`. An answer with several content
blocks stands on several lines with the same message id and request id; it counts once, with the counts of its
last line. `entrypoint` tells who asked: `cli` is a session (a subagent when `isSidechain`), `sdk-*` a program
(`claude -p`, the workers). Measured counts only: the transcripts carry no price, and nothing here estimates one.

Reading is incremental: each file is read on from where the last scan stopped, a line still being written waits
for the next scan, and a file untouched for longer than the week is not opened. A file is read in blocks, so a
large transcript never stands in memory whole. Everything here only reads.

`view()` scans before it answers (the Betrieb page asks for it). `latest()` is for callers on a worker thread
(the collector after each pass): it answers with the last view and starts a scan on its own thread when that view
is missing or older than MAX_AGE, so the first scan after start never holds up a collect pass.
"""
from __future__ import annotations

import datetime as dt
import functools
import json
import os
import statistics
import threading
import time
from pathlib import Path
from typing import Callable

DAYS = 7
SOURCES = ("session", "subagent", "worker")
FIELDS = ("input", "output", "cache_read", "cache_write")
TOP = 8
# a source is named when today is this many times its usual day, and this large
OUTLIER_FACTOR = 3.0
OUTLIER_MIN = 50_000
OUTLIER_DAYS = 3          # usual needs at least this many earlier days with use
BLOCK = 8 << 20           # bytes read at a time from one transcript
MAX_AGE = 180.0           # seconds latest() answers with a view before it starts a new scan


def claude_dir() -> Path:
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")


def _int(v) -> int:
    return int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 else 0


def _source(rec: dict) -> str:
    entry = str(rec.get("entrypoint") or "")
    if entry.startswith("sdk"):
        return "worker"
    return "subagent" if rec.get("isSidechain") is True else "session"


def _day(stamp) -> str | None:
    if not isinstance(stamp, str):
        return None
    try:
        when = dt.datetime.fromisoformat(stamp.replace("Z", "+00:00"))
    except ValueError:
        return None
    return (when.astimezone() if when.tzinfo else when).date().isoformat()



@functools.lru_cache(maxsize=512)
def _project_of(cwd: str) -> str:
    """The repository a session worked in: the nearest folder up from its cwd that holds .git, so a
    session in work/ or a deliverables folder counts for its repo; without one, the cwd's own name."""
    p = Path(cwd)
    for q in (p, *p.parents):
        try:
            if (q / ".git").exists():
                return q.name
        except OSError:
            break
    return p.name

class Usage:
    def __init__(self, base: Path | None = None, now: Callable[[], dt.datetime] = dt.datetime.now,
                 clock: Callable[[], float] = time.monotonic):
        self.base = base
        self.now = now
        self.clock = clock
        self.lock = threading.Lock()
        self.offsets: dict[str, int] = {}
        self.answers: dict[tuple, tuple] = {}   # (message id, request id) -> (day, source, model, project, counts)
        self.last_lock = threading.Lock()       # guards the fields below; never held during a scan
        self.last: dict | None = None
        self.last_at = 0.0
        self.thread: threading.Thread | None = None

    def _read(self, path: Path) -> None:
        key = str(path)
        start = self.offsets.get(key, 0)
        try:
            size = path.stat().st_size
            if size < start:          # rewritten: read it again from the top
                start = 0
            if size == start:
                return
            with path.open("rb") as f:
                f.seek(start)
                pos, rest = start, b""
                while pos < size:
                    block = f.read(min(BLOCK, size - pos))
                    if not block:
                        break
                    pos += len(block)
                    data = rest + block
                    end = data.rfind(b"\n")
                    if end < 0:       # one line longer than the block so far: keep collecting it
                        rest = data
                        continue
                    self._lines(data[: end + 1], path)
                    rest = data[end + 1:]
                    self.offsets[key] = pos - len(rest)
        except OSError:
            return

    def _lines(self, chunk: bytes, path: Path) -> None:
        for raw in chunk.splitlines():
            if b'"usage"' not in raw:
                continue
            try:
                rec = json.loads(raw)
            except ValueError:
                continue
            msg = rec.get("message") if isinstance(rec, dict) else None
            if not isinstance(msg, dict) or not isinstance(msg.get("usage"), dict):
                continue
            model = msg.get("model")
            day = _day(rec.get("timestamp"))
            if not isinstance(model, str) or model.startswith("<") or day is None:
                continue
            u = msg["usage"]
            counts = (_int(u.get("input_tokens")), _int(u.get("output_tokens")),
                      _int(u.get("cache_read_input_tokens")), _int(u.get("cache_creation_input_tokens")))
            cwd = rec.get("cwd")
            project = _project_of(cwd) if isinstance(cwd, str) and cwd else path.parent.name
            self.answers[(msg.get("id") or raw[:64], rec.get("requestId"))] = (day, _source(rec), model, project, counts)

    def scan(self) -> None:
        root = (self.base or claude_dir()) / "projects"
        cutoff = self.now().timestamp() - (DAYS + 1) * 86400
        present: set[str] = set()
        for folder, _dirs, files in os.walk(root):
            for name in files:
                if not name.endswith(".jsonl"):
                    continue
                path = Path(folder) / name
                present.add(str(path))
                try:
                    if path.stat().st_mtime < cutoff:
                        continue
                except OSError:
                    continue
                self._read(path)
        self.offsets = {k: v for k, v in self.offsets.items() if k in present}   # a deleted file is forgotten
        first = (self.now().date() - dt.timedelta(days=DAYS - 1)).isoformat()
        self.answers = {k: v for k, v in self.answers.items() if v[0] >= first}

    def latest(self) -> dict | None:
        """The last view without scanning here (None before the first scan ends). A missing or stale one is
        recomputed on its own thread, one at a time; the answer is the last view meanwhile."""
        with self.last_lock:
            stale = self.last is None or self.clock() - self.last_at >= MAX_AGE
            if stale and (self.thread is None or not self.thread.is_alive()):
                self.thread = threading.Thread(target=self._refresh, name="usage-scan", daemon=True)
                self.thread.start()
            return self.last

    def join(self, timeout: float | None = None) -> None:
        """Wait for a scan latest() started (tests, shutdown)."""
        thread = self.thread
        if thread is not None:
            thread.join(timeout)

    def _refresh(self) -> None:
        try:
            self.view()
        except Exception:  # noqa: BLE001 (the token view is an extra; the next latest() tries again)
            with self.last_lock:
                self.last_at = self.clock()

    def view(self) -> dict:
        with self.lock:
            self.scan()
            answers = list(self.answers.values())
        result = self._build(answers)
        with self.last_lock:
            self.last, self.last_at = result, self.clock()
        return result

    def _build(self, answers: list[tuple]) -> dict:
        today = self.now().date()
        names = [(today - dt.timedelta(days=DAYS - 1 - i)).isoformat() for i in range(DAYS)]
        zero = lambda: dict.fromkeys(FIELDS, 0)  # noqa: E731
        days = {d: {"day": d, "sources": {s: zero() for s in SOURCES}, "models": {}, "projects": {}} for d in names}
        total, models, projects = zero(), {}, {}
        for day, source, model, project, counts in answers:
            d = days.get(day)
            if d is None:
                continue
            for f, n in zip(FIELDS, counts):
                d["sources"][source][f] += n
                total[f] += n
            out = counts[1]
            d["models"][model] = d["models"].get(model, 0) + out
            d["projects"][project] = d["projects"].get(project, 0) + out
            models[model] = models.get(model, 0) + out
            projects[project] = projects.get(project, 0) + out

        def ranked(counts: dict, key: str) -> list[dict]:
            return [{key: k, "output": v} for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:TOP]]

        out_days = []
        for d in names:
            x = days[d]
            out_days.append({"day": d, "sources": x["sources"],
                             "output": sum(s["output"] for s in x["sources"].values()),
                             "models": ranked(x["models"], "model"), "projects": ranked(x["projects"], "project")})
        outliers = []
        for s in SOURCES:
            earlier = [x["sources"][s]["output"] for x in out_days[:-1] if x["sources"][s]["output"] > 0]
            now = out_days[-1]["sources"][s]["output"]
            if len(earlier) < OUTLIER_DAYS or now < OUTLIER_MIN:
                continue
            usual = statistics.median(earlier)
            if now >= OUTLIER_FACTOR * usual:
                outliers.append({"source": s, "today": now, "usual": int(usual), "factor": round(now / usual, 1)})
        return {"days": out_days, "total": total, "models": ranked(models, "model"),
                "projects": ranked(projects, "project"), "outliers": outliers}
