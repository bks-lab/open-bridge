# SPDX-License-Identifier: MIT
"""The tokens Claude Code used, per Bridge and per machine, over 7, 30 or 90 days, for the overview page.

Every answer of the model stands in the transcript of its session (~/.claude/projects/<slug>/<session>.jsonl,
a subagent's in <session>/subagents/agent-*.jsonl) with its model and `usage`. An answer with several content
blocks stands on several lines with the same message id and request id; it counts once, with the counts of its
last line. `entrypoint` tells who asked: `cli` is a session (a subagent when `isSidechain`), `sdk-*` a program
(`claude -p`, the workers). Measured counts only: the transcripts carry no price, and nothing here estimates one.

Reading is incremental: each file is read on from where the last scan stopped, a line still being written waits
for the next scan, and a file untouched for longer than the week is not opened. A file is read in blocks, so a
large transcript never stands in memory whole. Everything here only reads.

`view()` scans before it answers (the overview page asks for it). `latest()` is for callers on a worker thread
(the collector after each pass): it answers with the last view and starts a scan on its own thread when that view
is missing or older than MAX_AGE, so the first scan after start never holds up a collect pass.

Bridges: given the Bridge root, a record belongs to the instance in infra/instances/*.yaml whose location.path is
the longest prefix of its cwd (on a path boundary); none fits, no Bridge. History: transcripts are read for the
last WINDOW days only; closed days are kept in <root>/.bridge/resources/usage-days.json (pruned to KEEP_DAYS), so
30 and 90 days come from there. Other machines: `ssh:<host>:<file>` written by scripts/usage-export.py, the hosts
from cockpit.usage.remotes or the instances that run elsewhere; read on a thread of their own, cached REMOTE_TTL
seconds, and a machine that does not answer is listed as such and never breaks the local view.
"""
from __future__ import annotations

import datetime as dt
import functools
import json
import os
import re
import shlex
import socket
import statistics
import subprocess
import tempfile
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
WINDOW = 8                # days of transcripts a scan keeps (today included); older days come from the store
KEEP_DAYS = 120           # days the store keeps
RANGES = (7, 30, 90)
REMOTE_TTL = 600.0        # seconds a remote machine's file is kept before it is read again
REMOTE_FILE = "~/.bridge/resources/usage.json"
STORE = Path(".bridge") / "resources" / "usage-days.json"
HOST_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")


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

def clamp_range(value) -> int:
    """7, 30 or 90 days: anything else goes to the nearest of them, something that is no number to 7."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return RANGES[0]
    return min(RANGES, key=lambda r: (abs(r - n), r))


def _usage_conf(root: Path | None) -> dict:
    """The `cockpit.usage` block of bridge-config.yaml ({} without a root or block)."""
    if root is None:
        return {}
    cockpit = _read_yaml(Path(root) / "bridge-config.yaml").get("cockpit")   # as config.read_config_file
    return cockpit["usage"] if isinstance(cockpit, dict) and isinstance(cockpit.get("usage"), dict) else {}


def local_host(root: Path | None = None, gethostname: Callable[[], str] = socket.gethostname,
               run: Callable | None = None) -> str:
    """This machine's name: `cockpit.usage.host` if set, else the infra/remotes slug one of its names matches
    (the short hostname, or on macOS the Bonjour LocalHostName, since `hostname` may give a router's name),
    else the short hostname, lowercase."""
    conf = _usage_conf(root)
    if isinstance(conf.get("host"), str) and conf["host"].strip():
        return conf["host"].strip().lower()
    short = gethostname().split(".")[0].lower() or "localhost"
    if root is None:
        return short
    names = {short}
    try:
        res = (run or subprocess.run)(["scutil", "--get", "LocalHostName"], capture_output=True, text=True, timeout=5)
        if res is not None and res.returncode == 0 and res.stdout.strip():
            names.add(res.stdout.strip().split(".")[0].lower())
    except (OSError, subprocess.SubprocessError):
        pass
    for path, data in _yaml_files(Path(root) / "infra" / "remotes"):
        if names & _names_of(path.stem, data):
            return path.stem
    return short


def _read_yaml(path: Path) -> dict:
    import yaml
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def _yaml_files(folder: Path):
    """(path, data) of every *.yaml in folder that holds a mapping, `_`-files skipped."""
    for path in sorted(folder.glob("*.yaml")) if folder.is_dir() else []:
        if not path.name.startswith("_") and (data := _read_yaml(path)):
            yield path, data


def _location(data: dict) -> dict:
    return data["location"] if isinstance(data.get("location"), dict) else {}


def bridges(root: Path) -> list[tuple[str, str]]:
    """(path, name) of every instance in infra/instances/ with a location.path, longest path first."""
    out = []
    for path, data in _yaml_files(Path(root) / "infra" / "instances"):
        where = _location(data).get("path")
        if not isinstance(where, str) or not where.strip():
            continue
        name = data.get("name") if isinstance(data.get("name"), str) and data["name"].strip() else path.stem
        out.append((os.path.normpath(os.path.expanduser(where.strip())), name.strip()))
    return sorted(out, key=lambda pn: -len(pn[0]))


def _names_of(slug: str, data: dict) -> set[str]:
    """What a remote machine may be called: its slug, name, hostname and tailscale names, short and lowercase."""
    names = {slug, data.get("name"), data.get("hostname")}
    for block in ("network", "ssh", "tailscale"):
        sub = data.get(block) if isinstance(data.get(block), dict) else {}
        names.update(sub.get(k) for k in ("hostname", "host", "tailscale_hostname", "tailscale_name", "name"))
    return {n.split(".")[0].lower() for n in names if isinstance(n, str) and n.strip()}


def remote_hosts(root: Path, local: str) -> tuple[list[str], str]:
    """(hosts, remote file) to read token use from: cockpit.usage.remotes, else every location.host of the
    instances that has an infra/remotes/<host>.yaml; never the local machine."""
    conf = _usage_conf(root)
    remote_file = conf.get("remote_file") if isinstance(conf.get("remote_file"), str) and conf["remote_file"].strip() \
        else REMOTE_FILE
    machines = {p.stem: d for p, d in _yaml_files(Path(root) / "infra" / "remotes")}
    local = local.lower()

    def is_local(slug: str) -> bool:
        return local in _names_of(slug, machines.get(slug, {}))
    if isinstance(conf.get("remotes"), list):
        wanted = [h for h in conf["remotes"] if isinstance(h, str)]
    else:
        wanted = [_location(d).get("host") for _p, d in _yaml_files(Path(root) / "infra" / "instances")]
        wanted = [h for h in wanted if isinstance(h, str) and h in machines]
    hosts: list[str] = []
    for h in wanted:
        if HOST_RE.fullmatch(h) and h not in hosts and not is_local(h):
            hosts.append(h)
    return hosts, remote_file.strip()


def read_remote(host: str, path: str, run=None) -> tuple[dict | None, str | None]:
    """The export file of another machine over ssh, like bridge-resources.read_source; (data, error)."""
    run = run or subprocess.run
    if not HOST_RE.fullmatch(host) or not path or "\n" in path:
        return None, "bad source"
    # ~/ stays outside the quotes so the remote shell expands it; the rest is quoted
    remote = "cat ~/" + shlex.quote(path[2:]) if path.startswith("~/") else "cat " + shlex.quote(path)
    try:
        res = run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=5", host, remote],
                  capture_output=True, text=True, timeout=15)
        if res.returncode != 0:
            lines = (res.stderr or "").strip().splitlines()
            return None, lines[-1][:120] if lines else "ssh failed"
        data = json.loads(res.stdout)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return None, str(exc)[:120] or type(exc).__name__
    if not isinstance(data, dict) or not isinstance(data.get("rows"), dict):
        return None, "no usage export (scripts/usage-export.py) in that file"
    return data, None


def _rows(entries) -> dict[str, list[list]]:
    """day -> [[source, model, project, bridge, in, out, cr, cw], ...], one row per kind of answer."""
    acc: dict[str, dict[tuple, list[int]]] = {}
    for day, source, model, project, bridge, counts in entries:
        row = acc.setdefault(day, {}).setdefault((source, model, project, bridge), [0, 0, 0, 0])
        for i, n in enumerate(counts):
            row[i] += n
    return {d: [[*k, *v] for k, v in sorted(rows.items(), key=lambda kv: tuple(str(x) for x in kv[0]))]
            for d, rows in acc.items()}


def _valid_row(r) -> bool:
    return (isinstance(r, list) and len(r) == 8 and all(isinstance(x, str) for x in r[:3])
            and (r[3] is None or isinstance(r[3], str)) and r[0] in SOURCES)

class Usage:
    def __init__(self, base: Path | None = None, now: Callable[[], dt.datetime] = dt.datetime.now,
                 clock: Callable[[], float] = time.monotonic, root: Path | None = None, host: str | None = None,
                 run: Callable | None = None, remotes: bool = True):
        self.base = base
        self.now = now
        self.clock = clock
        self.root = Path(root) if root is not None else None
        self.host = (host or local_host(self.root)).lower()
        self.run = run                          # runs ssh for the other machines (tests pass a fake)
        self.remotes = remotes and self.root is not None   # an export never follows other machines
        self.lock = threading.Lock()
        self.offsets: dict[str, int] = {}
        # (message id, request id) -> (day, source, model, project, bridge, counts)
        self.answers: dict[tuple, tuple] = {}
        self.bridge_paths: list[tuple[str, str]] = []
        self.bridge_of: dict[str, str | None] = {}
        self.store: dict | None = None          # the closed days, loaded on the first scan
        self.last_lock = threading.Lock()       # guards the fields below; never held during a scan
        self.last: dict | None = None
        self.last_at = 0.0
        self.thread: threading.Thread | None = None
        self.remote_lock = threading.Lock()     # guards the remote cache; never held while ssh runs
        self.remote: dict[str, tuple[float, dict | None, str | None]] = {}
        self.remote_thread: threading.Thread | None = None

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
            has_cwd = isinstance(cwd, str) and bool(cwd)
            project = _project_of(cwd) if has_cwd else path.parent.name
            bridge = self._bridge(cwd) if has_cwd else None
            self.answers[(msg.get("id") or raw[:64], rec.get("requestId"))] = (day, _source(rec), model, project,
                                                                               bridge, counts)

    def _bridge(self, cwd: str) -> str | None:
        """The instance whose path is the longest prefix of cwd on a path boundary, cached for this scan."""
        if cwd not in self.bridge_of:
            norm = os.path.normpath(cwd)
            self.bridge_of[cwd] = next((name for p, name in self.bridge_paths
                                        if norm == p or norm.startswith(p.rstrip(os.sep) + os.sep)), None)
        return self.bridge_of[cwd]

    def scan(self) -> None:
        root = (self.base or claude_dir()) / "projects"
        self.bridge_paths = bridges(self.root) if self.root is not None else []
        self.bridge_of = {}
        cutoff = self.now().timestamp() - WINDOW * 86400
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
        first = (self.now().date() - dt.timedelta(days=WINDOW - 1)).isoformat()
        self.answers = {k: v for k, v in self.answers.items() if v[0] >= first}
        if self.root is not None:
            self._keep(first)

    # ---- history ----------------------------------------------------------------------------------------

    def _store_path(self) -> Path:
        return self.root / STORE

    def _load_store(self) -> dict:
        """The stored days. A file that is there but cannot be read (cut off, edited by hand, another schema)
        is moved aside as usage-days.json.bad-<stamp>, so the next write never replaces the history with the
        scan window; a missing file is simply an empty history."""
        path = self._store_path()
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError):
            data = None
        days = data.get("days") if isinstance(data, dict) and data.get("schema") == 1 else None
        if not isinstance(days, dict):
            try:
                os.replace(path, path.with_name(f"{path.name}.bad-{self.now().strftime('%Y%m%d-%H%M%S')}"))
            except OSError:
                pass
            return {}
        return {d: [r for r in rows if _valid_row(r)] for d, rows in days.items()
                if isinstance(d, str) and isinstance(rows, list)}

    def _keep(self, first: str) -> None:
        """Merge the closed days of the scan window into the store (they replace what it held for them), prune
        it to KEEP_DAYS and write it, atomically, when something changed."""
        if self.store is None:
            self.store = self._load_store()
        today = self.now().date()
        oldest = (today - dt.timedelta(days=KEEP_DAYS - 1)).isoformat()
        fresh = _rows(v for v in self.answers.values() if v[0] < today.isoformat())
        days = {d: rows for d, rows in self.store.items() if oldest <= d and not (first <= d < today.isoformat())}
        days.update({d: rows for d, rows in fresh.items() if oldest <= d})
        days = dict(sorted(days.items()))
        if days == self.store and self._store_path().is_file():
            return
        self.store = days
        path = self._store_path()
        tmp = None
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            # a temp file of its own: the cockpit and usage-export.py may write the same store at once
            fd, tmp = tempfile.mkstemp(prefix="." + path.name + ".", suffix=".tmp", dir=path.parent)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump({"schema": 1, "host": self.host, "days": days}, f, ensure_ascii=False)
            os.replace(tmp, path)
            tmp = None
        except OSError:
            pass   # the history is an extra: the view still answers from the scan
        finally:
            if tmp is not None:
                try:
                    os.unlink(tmp)
                except OSError:
                    pass

    # ---- other machines ---------------------------------------------------------------------------------

    def _remote_hosts(self) -> tuple[list[str], str]:
        return remote_hosts(self.root, self.host) if self.remotes else ([], REMOTE_FILE)

    def refresh_remotes(self) -> None:
        """Read every remote machine whose file is missing here or older than REMOTE_TTL (on the caller's thread:
        call it from a scan thread, never while a request waits)."""
        hosts, path = self._remote_hosts()
        for host in hosts:
            with self.remote_lock:
                got = self.remote.get(host)
                if got is not None and self.clock() - got[0] < REMOTE_TTL:
                    continue
            data, error = read_remote(host, path, self.run)
            with self.remote_lock:
                self.remote[host] = (self.clock(), data, error)

    def _remote_due(self, hosts: list[str]) -> bool:
        with self.remote_lock:
            return any(h not in self.remote or self.clock() - self.remote[h][0] >= REMOTE_TTL for h in hosts)

    def _start_remote_refresh(self) -> None:
        with self.remote_lock:
            if self.remote_thread is not None and self.remote_thread.is_alive():
                return
            self.remote_thread = threading.Thread(target=self._refresh_remotes_quietly, name="usage-remotes",
                                                  daemon=True)
            self.remote_thread.start()

    def _refresh_remotes_quietly(self) -> None:
        try:
            self.refresh_remotes()
        except Exception:  # noqa: BLE001 (other machines are an extra; the local view never depends on them)
            pass

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
        """Wait for a scan latest() or a remote read view() started (tests, shutdown)."""
        for thread in (self.thread, self.remote_thread):
            if thread is not None:
                thread.join(timeout)

    def _refresh(self) -> None:
        try:
            if self.remotes:
                self._refresh_remotes_quietly()     # this is the scan thread: other machines are read here
            self.view()
        except Exception:  # noqa: BLE001 (the token view is an extra; the next latest() tries again)
            with self.last_lock:
                self.last_at = self.clock()

    def view(self, days: int = DAYS) -> dict:
        """The last `days` days (7, 30 or 90): stored closed days, the scan window and the other machines'
        files as last read. A remote file that is due is read on a thread of its own, never here."""
        n = clamp_range(days)
        result = self._view(n)[0]
        if n == DAYS:
            with self.last_lock:
                self.last, self.last_at = result, self.clock()
        return result

    def export(self, days: int = 90) -> dict:
        """What scripts/usage-export.py writes: the view of this machine plus its rows per day, so another
        cockpit adds them in exactly. Never reads other machines."""
        view, rows = self._view(clamp_range(days), remotes=False)
        return {"schema": 1, "kind": "usage-export", "host": self.host, "at": view["at"], **view, "rows": rows}

    def _view(self, n: int, remotes: bool = True) -> tuple[dict, dict]:
        with self.lock:
            self.scan()
            answers = list(self.answers.values())
            stored = dict(self.store or {})
        today = self.now().date()
        names = [(today - dt.timedelta(days=n - 1 - i)).isoformat() for i in range(n)]
        first = (today - dt.timedelta(days=WINDOW - 1)).isoformat()
        live = _rows(answers)
        local = {d: (live.get(d, []) if d >= first else stored.get(d, [])) for d in names}
        local = {d: rows for d, rows in local.items() if rows}
        hosts, remote = [], []
        if remotes and self.remotes:
            wanted, _path = self._remote_hosts()
            if wanted and self._remote_due(wanted):
                self._start_remote_refresh()
            with self.remote_lock:
                cache = {h: self.remote.get(h) for h in wanted}
            for h in wanted:
                got = cache[h]
                if got is None:     # its first read runs on its own thread: being read, not unreachable
                    hosts.append({"host": h, "ok": False, "pending": True, "error": None, "at": None, "local": False})
                    continue
                _t, data, error = got
                at = data.get("at") if data and isinstance(data.get("at"), str) else None
                hosts.append({"host": h, "ok": data is not None, "error": error, "at": at, "local": False})
                if data is not None:
                    remote.append((h, data["rows"]))
        result = self._build(names, local, remote)
        result["hosts"] = [{"host": self.host, "ok": True, "error": None, "at": result["at"], "local": True}, *hosts]
        return result, local

    def _build(self, names: list[str], local: dict, remote: list[tuple[str, dict]]) -> dict:
        zero = lambda: dict.fromkeys(FIELDS, 0)  # noqa: E731
        days = {d: {"sources": {s: zero() for s in SOURCES}, "models": {}, "projects": {}, "bridges": {}}
                for d in names}
        total, models, projects = zero(), {}, {}
        per: dict[tuple, dict] = {}      # (bridge, host) -> output, all, models, output per day
        local_out = {d: dict.fromkeys(SOURCES, 0) for d in names}     # outliers look at this machine only
        index = {d: i for i, d in enumerate(names)}
        sets = [(self.host, local)] + [(h, {d: [r for r in rows if _valid_row(r)] for d, rows in rs.items()
                                            if isinstance(rows, list)}) for h, rs in remote]
        for host, by_day in sets:
            for day, rows in by_day.items():
                d = days.get(day)
                if d is None:
                    continue
                for source, model, project, bridge, *counts in rows:
                    counts = [_int(c) for c in counts]
                    for f, c in zip(FIELDS, counts):
                        d["sources"][source][f] += c
                        total[f] += c
                    out = counts[1]
                    if host == self.host and by_day is local:
                        local_out[day][source] += out
                    for bucket, key in ((d["models"], model), (d["projects"], project), (models, model),
                                        (projects, project), (d["bridges"], (bridge, host))):
                        bucket[key] = bucket.get(key, 0) + out
                    b = per.setdefault((bridge, host), {"output": 0, "all": 0, "models": {}, "days": [0] * len(names)})
                    b["output"] += out
                    b["all"] += sum(counts)
                    b["models"][model] = b["models"].get(model, 0) + out
                    b["days"][index[day]] += out

        def ranked(counts: dict, key: str, top: int = TOP) -> list[dict]:
            return [{key: k, "output": v} for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))[:top]]

        def order(kv):
            (bridge, host), out = kv
            return (-out, bridge is None, bridge or "", host)

        out_days = []
        for d in names:
            x = days[d]
            out_days.append({"day": d, "sources": x["sources"],
                             "output": sum(s["output"] for s in x["sources"].values()),
                             "models": ranked(x["models"], "model"), "projects": ranked(x["projects"], "project"),
                             "bridges": [{"bridge": b, "host": h, "output": o}
                                         for (b, h), o in sorted(x["bridges"].items(), key=order)[:TOP] if o > 0]})
        outliers = []
        week = names[-DAYS:]
        for s in SOURCES:
            earlier = [local_out[d][s] for d in week[:-1] if local_out[d][s] > 0]
            now = local_out[week[-1]][s]
            if len(earlier) < OUTLIER_DAYS or now < OUTLIER_MIN:
                continue
            usual = statistics.median(earlier)
            if now >= OUTLIER_FACTOR * usual:
                outliers.append({"source": s, "today": now, "usual": int(usual), "factor": round(now / usual, 1)})
        rows = [{"bridge": b, "host": h, "output": v["output"], "all": v["all"],
                 "models": ranked(v["models"], "model", 5), "days": v["days"]}
                for (b, h), v in sorted(per.items(), key=lambda kv: order((kv[0], kv[1]["output"]))) if v["all"] > 0]
        return {"days": out_days, "total": total, "models": ranked(models, "model"),
                "projects": ranked(projects, "project"), "outliers": outliers,
                "range": len(names), "at": self.now().astimezone().isoformat(timespec="seconds"),
                "host": self.host, "bridges": rows}
