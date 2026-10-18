# SPDX-License-Identifier: MIT
"""HTTP side of the cockpit: routing, auth, static files, server-sent events.

Security model (contract section 8.3): bound to 127.0.0.1 only; a key from
secrets.token_urlsafe, kept in <state>/token (mode 0600) so it outlives a restart (a new
one with `bridge-cockpit.py new-token`), in memory and in server.json (mode 0600). The key
itself never leaves those places: `bridge-cockpit.py url` prints a login code made from it
(login_code, good once and for CODE_AGE_S), /?code= turns that into an HttpOnly
SameSite=Strict cookie whose value is derived from the key and dated (good for
COOKIE_AGE_S), so the bare address works from then on in that browser. Every request must
name 127.0.0.1:<port> or localhost:<port> as Host (DNS rebinding); every POST also carries
a second derived value (csrf, handed out by /api/bootstrap) in X-Bridge-Token, a matching
Origin and a JSON body of at most 64 KB. No CORS headers, no access log, static files only from
scripts/web/ with a fixed set of extensions.
"""
from __future__ import annotations

import collections
import hashlib
import hmac
import json
import os
import queue
import re
import secrets
import shutil
import sys
import threading
import time
import traceback
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Callable

from . import VERSION
from . import details
from . import model as m
from .actions import ActionError, Actions
from .collector import Collector
from .daybook import DayBook
from .returns import Launches
from .launch import LaunchError, LaunchModel
from .ticker import Ticker
from .graph import Graph
from .config import WebConfig, load_web_config
from .relay import Relay, default_key_dir, load_key
from .agents import Agents
from .bridges import Bridges
from .triage import Triage
from .history import History
from .quick import Quick
from .review import Review
from .sessions import Sessions
from .usage import Usage
from .runner import Runner, RunnerRefused
from .design import stylesheet
from .store import WebStore, append_log, atomic_write_json
try:                       # Jev is an optional integration: without its file it is simply off
    from . import jev
except ImportError:
    jev = None
JEV_OFF = {"enabled": False, "ready": False, "reason": "off"}
from .tabs import TabPoller
from .text import T
from .watch import Watcher

HOST = "127.0.0.1"
MAX_BODY = 64 * 1024
SSE_QUEUE = 100
SSE_PING_S = 15
INBOX_CACHE_S = 10
NOISE_DAYS = 30         # how far back the Betrieb page counts what each inbox source filed and what was dropped
STATIC_RE = re.compile(r"^/[A-Za-z0-9._/-]{1,200}\Z")
# query switches the page reads itself (scripts/web/app.js, mock.js); the token exchange keeps them
VIEW_PARAMS = ("mock", "lang", "offline", "empty", "auth")
VIEW_VALUE_RE = re.compile(r"^[A-Za-z0-9]{1,8}\Z")
CONTENT_TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
                 ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml; charset=utf-8", ".woff2": "font/woff2",
                 ".png": "image/png", ".ico": "image/x-icon"}
# a bookmark, a Safari favourite or a home-screen tile fetches its picture without the session cookie
PUBLIC_ICONS = frozenset({"/favicon.ico", "/apple-touch-icon.png", "/icon-192.png", "/icon-512.png"})
CSP = ("default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; "
       "base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
SCREEN_LINES = 400          # the tab view reads this much of a tab's scrollback
SCREEN_TIMEOUT = 4
GITHUB_REF_RE = re.compile(r"^[\w.-]{1,100}/[\w.-]{1,100}#\d{1,9}\Z")
GITHUB_DETAIL_TIMEOUT = 40
SCREEN_MAX = 120_000
SCREEN_CACHE_MS = 1000      # several pages on one tab share one read of its screen within this window
SCREEN_HASH_RE = re.compile(r"^[0-9a-f]{1,64}\Z")
CAPS_TTL_S = 300
CAPS_TIMEOUT = 20
TAB_REF_RE = re.compile(r"^[A-Za-z0-9%][A-Za-z0-9:%_.@/-]{0,63}\Z")   # the terminal driver's name for a tab
ERROR_STATUS = {"unauthorized": 401, "forbidden_origin": 403, "bad_host": 403, "bad_fetch_site": 403, "not_found": 404,
                "method_not_allowed": 405, "unsupported_media_type": 415, "payload_too_large": 413,
                "unknown_verb": 400, "invalid_argument": 400, "invalid_json": 400, "stale_row": 409, "stale_tab": 409,
                "not_applicable": 409, "relay_offline": 409, "cmux_unavailable": 503, "cli_unavailable": 503,
                "driver_cannot": 503, "unreadable": 502, "internal": 500}
UNAUTHORIZED_PAGE = ("<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\"><title>Bridge Cockpit</title></head>"
                     "<body><p>Open the cockpit once with a fresh link from <code>python3 scripts/bridge-cockpit.py url</code> "
                     "(it works once, for a minute); after that the plain address works in this browser for a few days.</p>"
                     "</body></html>")


def instance_id(root: Path) -> str:
    return hashlib.sha256(str(Path(root).resolve()).encode("utf-8")).hexdigest()[:12]


class SSEClient:
    def __init__(self):
        self.queue: queue.Queue = queue.Queue(maxsize=SSE_QUEUE)
        self.closed = False
        self.id = secrets.token_hex(8)   # sent in `hello`; the page names itself with it on /api/presence
        self.visible = True              # a page in a background browser tab says so and stops counting


class SSEHub:
    def __init__(self):
        self.lock = threading.Lock()
        self.clients: set[SSEClient] = set()

    def add(self) -> SSEClient:
        client = SSEClient()
        with self.lock:
            self.clients.add(client)
        return client

    def remove(self, client: SSEClient) -> None:
        with self.lock:
            self.clients.discard(client)

    def count(self, visible_only: bool = False) -> int:
        with self.lock:
            return sum(1 for c in self.clients if c.visible or not visible_only)

    def set_visible(self, client_id: str, visible: bool) -> bool | None:
        """Flags one page as shown or hidden; True when it just came back, None when no such page is open."""
        with self.lock:
            client = next((c for c in self.clients if c.id == client_id), None)
            if client is None:
                return None
            back = visible and not client.visible
            client.visible = visible
            return back

    def publish(self, event: str, payload: Any) -> None:
        data = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        with self.lock:
            clients = list(self.clients)
        for client in clients:
            try:
                client.queue.put_nowait((event, data))
            except queue.Full:
                client.closed = True  # it reconnects and receives `state`


class App:
    """Everything one server holds: config, runner, store, collector, tabs, relay, verbs."""

    def __init__(self, root: Path, cfg: WebConfig, runner: Runner, state_dir: Path, clock: Callable[[], float],
                 token: str, key_dir: Path | None = None, code_root: Path | None = None):
        self.root = Path(root).resolve()
        self.code_root = Path(code_root).resolve() if code_root else self.root   # where the page's files come from
        self._caps_lock = threading.Lock()
        self._caps: tuple[float, list[str]] | None = None
        self._screen_lock = threading.Lock()
        self._screens: dict[str, tuple[float, str, str]] = {}   # ref -> (read at ms, text, hash), each under its ref's lock
        self._screen_locks: dict[str, threading.Lock] = {}
        self.cfg = cfg
        self.runner = runner
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.clock = clock
        self.token = token
        self.csrf = derived(token, "csrf")      # what the page sends back in X-Bridge-Token, never the key
        self._codes_lock = threading.Lock()
        self._codes_used: dict[str, int] = {}   # nonce of a redeemed login code -> its second, until it expires
        self.tx = T(cfg.language, cfg.control)
        self.started_ms = int(clock())
        self.instance = instance_id(self.root)
        self.port = 0
        self.hub = SSEHub()
        self.notes: collections.deque = collections.deque(maxlen=20)
        self.store = WebStore(self.state_dir, clock)
        self.daybook = DayBook(self.state_dir, clock)     # the start page's day by day (daybook.py)
        self.launches = Launches(self.state_dir, clock)   # every start handed to a tab, for the return channel (returns.py)
        self.graph = Graph(self.root)                       # the inner room's knowledge graph (graph.py)
        self.tabs = TabPoller(self)
        self.review = Review(self)
        self.sessions = Sessions(self)
        self.usage = Usage(root=self.root)
        self.quick = Quick(self, claude=self.runner.claude)
        self.agents = Agents(self)
        self.bridges = Bridges(self.root)
        self.triage = Triage(self)
        self.history = History(self.state_dir, self.clock)
        self.collector = Collector(self)
        self.relay = Relay(self.state_dir, cfg, clock, self.tx, key=load_key(key_dir or default_key_dir()))
        self.actions = Actions(self)
        self.launch_model = LaunchModel(self)         # the model an agent starts with (launch.py)
        self.ticker = Ticker(self)                     # the news ticker of the start page (ticker.py)
        self.watcher = Watcher(self)
        self.last_tabs_json: str | None = None
        self.last_model_tabs_json: str | None = None   # the tabs without their last line: what the model reads
        self.inbox_cache: tuple[float, list | None] = (0.0, None)
        self.threads: list[threading.Thread] = []
        self.stopping = False

    # ------------------------------------------------------------ plumbing

    def run(self, argv: list[str], timeout: float, on_line=None):
        return self.runner.run(argv, timeout, on_line) if on_line else self.runner.run(argv, timeout)

    def workplace(self, *args: str) -> list[str]:
        import sys
        return [sys.executable, self.runner.script("scripts/workplace.py"), "--root", str(self.root), *args]

    def broadcast(self, event: str, payload: Any) -> None:
        self.hub.publish(event, payload)

    def client_count(self) -> int:
        """The pages someone can see: the tab poll, the full pass and the ticker run for these only."""
        return self.hub.count(visible_only=True)

    def connected_count(self) -> int:
        """Every open page, a background one included (it still wants the waiting count in its title)."""
        return self.hub.count()

    def note(self, text: str, tone: str = "info") -> None:
        if not text:
            return
        entry = {"at": m.clock_time(self.clock()), "text": self.scrub(text), "tone": tone}
        self.notes.append(entry)
        self.broadcast("note", entry)

    @property
    def cookie_name(self) -> str:
        """Cookies ignore the port: one name per port keeps two servers on 127.0.0.1 apart."""
        return f"bw_token_{self.port}"

    def now_s(self) -> int:
        return int(self.clock() // 1000)

    def redeem(self, code: str) -> bool:
        """A login code from login_code(): made with this key, at most CODE_AGE_S old, and not seen before."""
        nonce, ts = parse_signed(self.token, "code", code, parts=3)
        if nonce is None:
            return False
        now = self.now_s()
        if not (-CLOCK_SKEW_S <= now - ts <= CODE_AGE_S):
            return False
        with self._codes_lock:
            for old, at in list(self._codes_used.items()):
                if now - at > CODE_AGE_S + CLOCK_SKEW_S:
                    del self._codes_used[old]
            if nonce in self._codes_used:
                return False
            self._codes_used[nonce] = ts
        return True

    def session_value(self, now_s: int | None = None) -> str:
        """The cookie: its second of issue and a MAC over it with the key, so it ends after COOKIE_AGE_S."""
        ts = self.now_s() if now_s is None else now_s
        return f"{ts}.{mac(self.token, f'session|{ts}')}"

    def session_ok(self, value: str) -> bool:
        _, ts = parse_signed(self.token, "session", value, parts=2)
        return ts is not None and -CLOCK_SKEW_S <= self.now_s() - ts <= COOKIE_AGE_S

    def scrub(self, text: str) -> str:
        return text.replace(self.token, "[token]") if self.token else text

    def scrub_tree(self, value):
        """scrub() over every string of a JSON-able value (a detail read straight from disk)"""
        if isinstance(value, str):
            return self.scrub(value)
        if isinstance(value, dict):
            return {k: self.scrub_tree(v) for k, v in value.items()}
        if isinstance(value, list):
            return [self.scrub_tree(v) for v in value]
        return value

    def log_error(self, message: str) -> None:
        stamp = time.strftime("%Y-%m-%dT%H:%M:%S")
        append_log(self.state_dir / "server.log", f"{stamp} {self.scrub(message)}")

    # ------------------------------------------------------------ state

    def tabs_state(self) -> dict:
        return self.tabs.state(self.collector.view)

    def driver_caps(self, fresh: bool = False) -> list[str]:
        """The verbs the terminal driver serves (workplace.py caps): what the page may offer for a tab.
        Asked once and then every few minutes; a driver that cannot be asked serves nothing."""
        now = time.monotonic()
        with self._caps_lock:
            if not fresh and self._caps is not None and now - self._caps[0] < CAPS_TTL_S:
                return list(self._caps[1])
        run = self.run(self.workplace("caps", "--json"), CAPS_TIMEOUT)
        caps: list[str] = []
        if run.ok:
            try:
                data = json.loads(run.out)
                caps = [c for c in data.get("caps") or [] if isinstance(c, str)]
            except (ValueError, AttributeError):
                caps = []
        with self._caps_lock:
            self._caps = (now, caps)
        return list(caps)

    def tab_screen(self, ref: str) -> tuple[str | None, str, str]:
        """The last lines of a tab's terminal as (text, hash, error), read through the terminal driver.
        A read is kept for a second per tab, and a second page asking meanwhile waits for the read under
        way instead of starting its own; a read that failed is not kept."""
        with self._screen_lock:
            lock = self._screen_locks.setdefault(ref, threading.Lock())
        with lock:
            hit = self._screens.get(ref)
            if hit and 0 <= self.clock() - hit[0] < SCREEN_CACHE_MS:
                return hit[1], hit[2], ""
            run = self.run(self.workplace("screen", ref, "--lines", str(SCREEN_LINES), "--json"), SCREEN_TIMEOUT)
            try:
                raw = json.loads(run.out).get("text") if run.ok else None
            except (ValueError, AttributeError):
                raw = None
            if not isinstance(raw, str):
                self._screens.pop(ref, None)
                return None, "", (run.err or run.out or "the tab could not be read").strip()
            text = "\n".join(line.rstrip() for line in raw.splitlines()).strip("\n")[-SCREEN_MAX:]
            digest = hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]
            self._screens[ref] = (self.clock(), text, digest)
            return text, digest, ""

    def names_tabs(self) -> bool:
        """Whether a terminal driver lists the tabs, so the control session can be told apart by its tab
        (cmux, tmux); without one only a single session heartbeating counts."""
        return bool(self.runner.cmux) or "tabs" in self.driver_caps()

    def cmux_state(self) -> dict:
        return {"ok": bool(self.runner.cmux), "error": None if self.runner.cmux else "cmux CLI not found"}

    def relay_state(self, with_records: bool = True) -> dict:
        return self.relay.state(self.tabs.control_tab(), self.names_tabs(), with_records)

    def state_payload(self) -> dict:
        return {"ok": True, "server": {"version": VERSION, "started_ms": self.started_ms,
                                       "person": getattr(self.cfg, "person_name", None)},   # the start page greets by it
                "model": self.collector.model, "tabs": self.tabs_state(), "loading": self.collector.loading_state(),
                "notes": list(self.notes), "relay": self.relay_state(), "cmux": self.cmux_state(),
                "driver": {"caps": self.driver_caps()}, "home": self.store.home(),
                "sessions": self.sessions_state(), "quick": self.quick.state(), "quick_live": self.quick.live_state(), "agents": self.agents.state(), "triage": self.triage.state(), "jev": jev.status(self) if jev else dict(JEV_OFF),
                "launch": self.launch_model.state(), "ticker": self.ticker.state(),
                "rooms": {"layout": self.cfg.chat_layout, "root": str(self.root), "control": self.cfg.control,
                          "bridges": self.bridges.state()}}

    def task_open(self, slug: str) -> bool:
        return bool(slug) and (self.root / "work" / "tasks" / slug / "STATUS.md").is_file()

    def link_tab_sessions(self) -> bool:
        """A session in a task tab (BRIDGE_TAB_SLUG names an open task) is linked to that task by itself;
        True when a link is new. A team tab names its task too; an inbox tab names no task."""
        changed = False
        for x in self.sessions.state():
            slug = x.get("tab_slug") or ""
            if x.get("sid") and self.task_open(slug):
                changed = self.store.link_session(x["sid"], slug, x.get("name") or "", x.get("cwd") or "", "tab") or changed
        return changed

    def sessions_state(self) -> dict:
        """The live sessions, each with the task it is linked to, and every kept link: the page shows a
        task's sessions, the live ones with their tab, the ended ones to go on in"""
        links = self.store.session_links()
        # copies: the scan's own list is what the next scan compares with
        live = [{**x, "task": (links.get(x.get("sid") or "") or {}).get("task")} for x in self.sessions.state()]
        sids = {x.get("sid") for x in live}
        kept = [{"sid": sid, **v, "live": sid in sids} for sid, v in links.items() if self.task_open(v.get("task", ""))]
        kept.sort(key=lambda v: -v.get("at_ms", 0))
        return {"at_ms": self.tabs.at_ms, "sessions": live, "links": kept}

    def on_tabs(self, alerts: list[dict]) -> None:
        state = self.tabs_state()
        compare = json.dumps({k: v for k, v in state.items() if k != "at_ms"}, sort_keys=True)
        if compare != self.last_tabs_json:
            self.last_tabs_json = compare
            # A busy tab's last line changes on almost every poll and the model does not show it (the
            # evening text reads the live tabs when asked): it goes out in the narrow tabs event only.
            model_side = json.dumps({**{k: v for k, v in state.items() if k != "at_ms"},
                                     "tabs": [{k: v for k, v in t.items() if k != "last"} for t in state["tabs"]]},
                                    sort_keys=True)
            if model_side != self.last_model_tabs_json:
                self.last_model_tabs_json = model_side
                self.collector.rebuild()
            self.broadcast("tabs", state)
        for alert in alerts:
            self.broadcast("alert", alert)
        try:
            relay = frozenset(h["session"] for h in self.relay.heartbeats(self.clock()))
            changed = self.sessions.refresh(self.tabs.tab_list(), self.clock(), self.tabs.control_ref(), relay)
            if self.link_tab_sessions() or changed:
                self.broadcast("sessions", self.sessions_state())
        except Exception as exc:  # noqa: BLE001 - the sessions page is an extra, never a reason for the tabs to stop
            self.log_error(f"sessions: {exc!r}")

    def relay_scan(self) -> None:
        changed, state = self.relay.scan(self.tabs.control_tab(), self.names_tabs())
        for record in changed:
            self.broadcast("relay", record)
        if state is not None:
            self.broadcast("relay_state", state)

    def on_client_connect(self) -> None:
        self.tabs.schedule(0)
        self.collector.on_connect()

    def inbox_listing(self) -> list | None:
        at, cached = self.inbox_cache
        if cached is not None and time.monotonic() - at < INBOX_CACHE_S:
            return cached
        argv = self.actions.inbox("list", "--all", "--json")
        run = self.run(argv, 20)
        listing = None
        if run.ok:
            try:
                data = json.loads(run.out)
                listing = data if isinstance(data, list) else None
            except ValueError:
                listing = None
        self.inbox_cache = (time.monotonic(), listing)
        return listing

    def inbox_noise(self, days: int = NOISE_DAYS) -> dict | None:
        """What the Betrieb page shows about the inbox: the loudest sources of the last `days` and the
        mute rules in force. None when either read fails: half a picture would read as all quiet."""
        out = {"days": days}
        for name, argv in (("sources", self.actions.inbox("stats", "--days", str(days), "--json")),
                           ("mutes", self.actions.inbox("mute", "list", "--json"))):
            run = self.run(argv, 20)
            try:
                data = json.loads(run.out) if run.ok else None
            except ValueError:
                data = None
            if not isinstance(data, list):
                return None
            out[name] = data
        return self.scrub_tree(out)

    def server_json(self) -> dict:
        now = int(self.clock())
        return {"v": 1, "pid": os.getpid(), "port": self.port, "token": self.token, "started_ms": self.started_ms,
                "root": str(self.root), "instance": self.instance, "version": VERSION, "clients": self.connected_count(),
                "relay_online": bool(self.relay_state(with_records=False)["online"]), "updated_ms": now}

    def write_server_json(self) -> None:
        try:
            atomic_write_json(self.state_dir / "server.json", self.server_json(), mode=0o600)
        except OSError:
            self.log_error("could not write server.json")

    # ------------------------------------------------------------ lifecycle

    def backup_layout(self) -> bool:
        """Save the cmux layout once (cmux_layout.py snapshot writes only when it changed). A Bridge without
        cmux has no layout to save. A failure is logged and tried again at the next turn."""
        if not self.runner.cmux:
            return False
        run = self.run(self.actions.layout_script("snapshot"), 60)
        if not run.ok:
            self.log_error(f"layout backup: {(run.err or run.out or '').strip()[:200]}")
        return run.ok

    def start_layout_backup(self) -> None:
        """The backup the briefing-ui mod made while a session was open, now while the cockpit runs: a minute
        after the start, then every snapshot_minutes (the configured interval, not a new one)."""
        minutes = self.cfg.snapshot_minutes
        if not self.runner.cmux or minutes <= 0:
            return

        def loop() -> None:
            time.sleep(60)
            while True:
                try:
                    self.backup_layout()
                except Exception as exc:  # noqa: BLE001 - a backup never takes the server down
                    self.log_error(f"layout backup: {exc!r}")
                time.sleep(minutes * 60)
        threading.Thread(target=loop, name="bridge-cockpit-layout", daemon=True).start()

    def start(self) -> None:
        self.collector.load_stale()
        self.collector.request("both")
        self.tabs.schedule(0)
        if self.cfg.triage_daily:
            self.triage.start_daily()  # what each task and inbox item is, once a day by itself (cockpit.triage_daily)
        self.start_layout_backup()     # the cmux layout, every snapshot_minutes, only on change
        self.history.backfill(self.root, self.state_dir / "audit.log")   # closes from before the history
        for target, name in ((self.collector.worker, "collect"), (self.tabs.loop, "tabs"), (self.watcher.loop, "watch"),
                             (self.ticker.loop, "ticker-loop")):
            thread = threading.Thread(target=target, name=f"bridge-cockpit-{name}", daemon=True)
            thread.start()
            self.threads.append(thread)

    def stop(self) -> None:
        self.stopping = True
        self.collector.shutdown()
        self.tabs.shutdown()
        self.watcher.shutdown()


USAGE_RANGES = (7, 30, 90)


def usage_days(value: str) -> int:
    """The range the usage card asks for, as one of 7, 30 or 90 days: a number between becomes the nearest
    (the lower one on a tie), anything that is no positive number the default of seven."""
    try:
        n = int(value)
    except (TypeError, ValueError):
        return USAGE_RANGES[0]
    if n <= 0:
        return USAGE_RANGES[0]
    return min(USAGE_RANGES, key=lambda r: (abs(r - n), r))


def static_etag(mtime_ns: int, size: int) -> str:
    """A strong validator from the file's (mtime, size): changes with every write that a reload must see."""
    return f'"{mtime_ns:x}-{size:x}"'


def etag_matches(header: str | None, etag: str) -> bool:
    """If-None-Match uses the weak comparison (RFC 9110 13.1.2): a W/ prefix does not matter, * matches."""
    if not header:
        return False
    for part in header.split(","):
        tag = part.strip()
        if tag == "*" or (tag[2:] if tag.startswith("W/") else tag) == etag:
            return True
    return False


class Handler(BaseHTTPRequestHandler):
    server_version = "bridge-cockpit"
    sys_version = ""
    protocol_version = "HTTP/1.1"
    # a request that declares a body it never sends must not hold a handler thread forever
    timeout = 30

    @property
    def app(self) -> App:
        return self.server.app  # type: ignore[attr-defined]

    def log_message(self, format: str, *args: Any) -> None:  # access log off
        return

    def log_error(self, format: str, *args: Any) -> None:  # errors go to server.log by the app
        return

    # ------------------------------------------------------------ responses

    def security_headers(self, html: bool = False, static: bool = False) -> None:
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Cache-Control", "no-cache" if static else "no-store")
        if html:
            self.send_header("Content-Security-Policy", CSP)

    def send_bytes(self, status: int, body: bytes, content_type: str, html: bool = False, static: bool = False,
                   extra: dict | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.security_headers(html=html, static=static)
        for key, value in (extra or {}).items():
            self.send_header(key, value)
        self.end_headers()
        if self.command != "HEAD":
            self.wfile.write(body)

    def send_json(self, status: int, payload: Any) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_bytes(status, body, "application/json; charset=utf-8")

    def send_error_json(self, code: str, message: str, field: str | None = None, status: int | None = None,
                        extra: dict | None = None) -> None:
        self.send_json(status or ERROR_STATUS[code],
                       {"ok": False, "error": {"code": code, "message": message, "field": field}, **(extra or {})})

    def send_unauthorized(self, path: str) -> None:
        if path.startswith("/api/"):
            self.send_error_json("unauthorized", "missing or wrong token")
        else:
            self.send_bytes(401, UNAUTHORIZED_PAGE.encode("utf-8"), "text/html; charset=utf-8", html=True)

    # ------------------------------------------------------------ checks

    def host_ok(self) -> bool:
        host = self.headers.get("Host", "")
        port = self.app.port
        return host in (f"127.0.0.1:{port}", f"localhost:{port}")

    def origin_ok(self, origin: str | None) -> bool:
        port = self.app.port
        return origin in (f"http://127.0.0.1:{port}", f"http://localhost:{port}")

    def fetch_site_ok(self) -> bool:
        site = self.headers.get("Sec-Fetch-Site")
        return site is None or site in ("same-origin", "none")

    def csrf_ok(self, value: str | None) -> bool:
        return bool(value) and hmac.compare_digest(value.encode("utf-8"), self.app.csrf.encode("utf-8"))

    def cookie_ok(self) -> bool:
        """Any cookie of our name holding a valid session value. Parsed by hand: SimpleCookie drops every cookie
        after one it cannot parse, and another app on 127.0.0.1 (any port) may have set such one."""
        name = self.app.cookie_name
        for header in self.headers.get_all("Cookie") or []:
            for part in header.split(";"):
                key, sep, value = part.strip().partition("=")
                if sep and key.strip() == name and self.app.session_ok(value.strip().strip('"')):
                    return True
        return False

    def precheck(self) -> bool:
        if not self.host_ok():
            self.send_error_json("bad_host", "the Host header must name this server")
            return False
        if not self.fetch_site_ok():
            self.send_error_json("bad_fetch_site", "cross-site requests are refused")
            return False
        return True

    # ------------------------------------------------------------ methods

    def handle_safely(self, fn: Callable[[], None]) -> None:
        try:
            fn()
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self.app.log_error(f"{self.command} handler failed:\n{traceback.format_exc()}")
            try:
                self.send_error_json("internal", "internal error")
            except OSError:
                pass

    def do_GET(self) -> None:
        self.handle_safely(self.get)

    def do_POST(self) -> None:
        self.handle_safely(self.post)

    def not_allowed(self) -> None:
        self.close_connection = True

        def run() -> None:
            if self.precheck():
                self.send_error_json("method_not_allowed", "method not allowed")
        self.handle_safely(run)

    do_PUT = do_DELETE = do_PATCH = do_OPTIONS = do_HEAD = not_allowed  # type: ignore[assignment]

    def get(self) -> None:
        if not self.precheck():
            return
        parsed = urllib.parse.urlsplit(self.path)
        path, query = parsed.path, urllib.parse.parse_qs(parsed.query, keep_blank_values=True)
        app = self.app
        if path == "/api/health":
            self.send_json(200, {"ok": True, "version": VERSION, "instance": app.instance})
            return
        if path in PUBLIC_ICONS:
            self.get_static(path)
            return
        if path == "/" and "code" in query:
            given = query["code"][0] if query["code"] else ""
            if self.app.redeem(given):
                # keep the page's own switches (mock mode, language) so `url` plus &mock=1 still works
                keep = [(k, query[k][0]) for k in VIEW_PARAMS if query.get(k) and VIEW_VALUE_RE.match(query[k][0])]
                location = "/" + (f"?{urllib.parse.urlencode(keep)}" if keep else "")
                self.send_bytes(303, b"", "text/plain; charset=utf-8", extra={
                    "Location": location, "Set-Cookie": f"{app.cookie_name}={app.session_value()}; HttpOnly; SameSite=Strict; Path=/; Max-Age={COOKIE_AGE_S}"})
            else:
                self.send_unauthorized(path)
            return
        if not self.cookie_ok():
            self.send_unauthorized(path)
            return
        if path.startswith("/api/"):
            self.get_api(path, query)
        elif path == "/colors.css":
            # the Bridge's own colours and fonts, from its DESIGN.md (design.py): every fork shows its brand
            self.send_bytes(200, stylesheet(app.root).encode("utf-8"), "text/css; charset=utf-8")
        else:
            self.get_static(path)

    def get_api(self, path: str, query: dict) -> None:
        app = self.app
        one = lambda name: (query.get(name) or [""])[0]  # noqa: E731
        if path == "/api/bootstrap":
            cfg = app.cfg
            self.send_json(200, {"ok": True, "csrf": app.csrf, "language": cfg.language, "version": VERSION,
                                 "scratch": scratch_of(app.root, app.state_dir),
                                 # what the check of the cockpit: block found; the settings page shows it (#402)
                                 "config_warnings": list(getattr(cfg, "config_warnings", ())),
                                 "config": {"port": app.port, "relay": cfg.relay, "tabs_seconds": cfg.tabs_seconds,
                                            "full_minutes": cfg.full_minutes, "voice": cfg.voice, "target": cfg.target,
                                            "control": cfg.control, "profile": cfg.profile}})
        elif path == "/api/state":
            self.send_json(200, app.state_payload())
        elif path == "/api/events":
            origin = self.headers.get("Origin")
            if origin is not None and not self.origin_ok(origin):
                self.send_error_json("forbidden_origin", "wrong origin")
                return
            self.events()
        elif path == "/api/page":
            found = app.collector.page_items(one("page"), one("section"))
            if found is None:
                self.send_error_json("not_found", "unknown page or section")
            else:
                self.send_json(200, {"ok": True, "items": found[0], "total": found[1]})
        elif path == "/api/history":
            # what the dashboard closed, dropped, settled or hid, newest first, each with its undo
            self.send_json(200, {"ok": True, "entries": app.history.state()})
        elif path == "/api/agents":
            # the A2A peers with what their cards say (fetched in the background) and the conversations
            app.agents.refresh_cards()
            self.send_json(200, {"ok": True, **app.agents.state()})
        elif path == "/api/workers":
            # the full worker view the Resources section keeps (scripts/bridge-resources.py workers), read only
            # a Bridge without one (no workers declared) is no error: view null, and the page shows no Worker tab
            path_ = app.root / ".bridge" / "resources" / "workers-view.json"
            try:
                data = json.loads(path_.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = None
            ok = isinstance(data, dict) and isinstance(data.get("runs"), list)
            self.send_json(200, {"ok": True, "view": data if ok else None})
        elif path == "/api/ticker":
            # the news ticker as the page gets it in the state payload and the `ticker` event (ticker.py)
            self.send_json(200, {"ok": True, "ticker": app.ticker.state()})
        elif path == "/api/costs":
            # what the cloud accounts cost per day, as `bridge-resources.py costs` kept it from the collector's
            # report (scripts/cloud-costs.py), read only; none yet is no error: view null, and the card says what
            # to declare
            path_ = app.root / ".bridge" / "resources" / "costs-view.json"
            try:
                data = json.loads(path_.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                data = None
            ok = isinstance(data, dict) and isinstance(data.get("accounts"), list)
            self.send_json(200, {"ok": True, "view": data if ok else None})
        elif path == "/api/usage":
            # the tokens of the last 7, 30 or 90 days, counted from the Claude Code transcripts of this machine,
            # the kept history and the other machines (usage.py), read only; any other range becomes the nearest
            self.send_json(200, {"ok": True, "usage": app.usage.view(days=usage_days(one("days")))})
        elif path == "/api/inbox/noise":
            # per source what was filed and what a person dropped, and the mute rules in force (inbox.py), read only
            self.send_json(200, {"ok": True, "noise": app.inbox_noise()})
        elif path == "/api/tab/screen":
            ref = one("ref")
            if not TAB_REF_RE.match(ref):
                self.send_error_json("invalid_argument", "not a tab ref", "ref")
                return
            since = one("since")
            if since and not SCREEN_HASH_RE.match(since):
                self.send_error_json("invalid_argument", "not a screen hash", "since")
                return
            tab = app.tabs.find(ref)
            if not tab:
                self.send_error_json("not_found", "no such tab")
                return
            # read only: the last lines of the tab's terminal, for the tab view (a CLI chat in the page),
            # through the terminal driver like everything else done to a tab. A page that names the hash
            # it holds (since) gets unchanged and no text while the screen stays the same
            text, digest, err = app.tab_screen(ref)
            if text is None:
                self.send_error_json("unreadable", app.scrub(err)[:200])
                return
            head = {"ok": True, "ref": ref, "name": tab.get("name"), "state": tab.get("state"),
                    "workspace": tab.get("workspace"), "hash": digest, "at_ms": int(app.clock())}
            self.send_json(200, {**head, "unchanged": True} if since == digest else {**head, "text": text})
        elif path == "/api/task":
            slug = one("slug")
            if not details.SLUG_RE.match(slug):
                self.send_error_json("invalid_argument", "not a task slug", "slug")
                return
            result = details.task_detail(app.root, slug, app.inbox_listing())
            if result is None:
                self.send_error_json("not_found", "no such task")
            else:
                self.send_json(200, app.scrub_tree(result))
        elif path == "/api/inbox":
            item_id = one("id")
            if not details.INBOX_ID_RE.match(item_id):
                self.send_error_json("invalid_argument", "not an inbox id", "id")
                return
            result = details.inbox_detail(app.root, item_id, app.inbox_listing())
            if result is None:
                self.send_error_json("not_found", "no such inbox item")
            else:
                self.send_json(200, app.scrub_tree(result))
        elif path == "/api/github":
            # the detail of one GitHub row (briefing.py detail): kept ten minutes, under the GitHub block
            ref = one("ref")
            if not GITHUB_REF_RE.match(ref):
                self.send_error_json("invalid_argument", "not an owner/repo#number", "ref")
                return
            argv = [app.runner.python, app.runner.script("scripts/briefing.py"), "--root", str(app.root), "detail", ref]
            if one("fresh") == "1":
                argv.append("--fresh")
            run = app.run(argv, GITHUB_DETAIL_TIMEOUT)
            try:
                data = json.loads((run.out if run.ok else run.err).strip().splitlines()[-1])
            except (ValueError, IndexError):
                data = {"ok": False, "error": (run.err or run.out or "no answer").strip()[-200:]}
            if run.ok and isinstance(data, dict):
                self.send_json(200, app.scrub_tree(data))
            else:
                self.send_error_json("unreadable", app.scrub(str((data or {}).get("error") or "GitHub did not answer"))[:200])
        elif path == "/api/relay":
            self.send_json(200, app.relay_state())
        elif path == "/api/graph":
            # the knowledge graph of the config entries, tasks and the files they name (graph.py), read only
            self.send_json(200, {"ok": True, **app.scrub_tree(app.graph.view())})
        elif path == "/api/graph/node":
            found = app.graph.node(one("id"))
            if found is None:
                self.send_error_json("not_found", "no such node")
            else:
                self.send_json(200, {"ok": True, **app.scrub_tree(found)})
        else:
            self.send_error_json("not_found", "unknown endpoint")

    def get_static(self, path: str) -> None:
        if path == "/":
            path = "/index.html"
        if not STATIC_RE.match(path):
            self.send_error_json("not_found", "not found")
            return
        segments = path[1:].split("/")
        if any(s in ("", ".", "..") or s.startswith(".") for s in segments):
            self.send_error_json("not_found", "not found", status=403)
            return
        ext = os.path.splitext(path)[1].lower()
        if ext not in CONTENT_TYPES:
            self.send_error_json("not_found", "not found")
            return
        base = (self.app.code_root / "scripts" / "web").resolve()
        try:
            target = (base / Path(*segments)).resolve()
            target.relative_to(base)
        except (ValueError, OSError):
            self.send_error_json("not_found", "not found", status=403)
            return
        if not target.is_file():
            self.send_error_json("not_found", "not found")
            return
        if ext == ".html":
            self.send_bytes(200, target.read_bytes(), CONTENT_TYPES[ext], html=True)
            return
        # no-cache makes the browser revalidate every load; the tag lets it keep the body it has (304)
        st = target.stat()
        etag = static_etag(st.st_mtime_ns, st.st_size)
        if etag_matches(self.headers.get("If-None-Match"), etag):
            self.send_response(304)
            self.send_header("ETag", etag)
            self.security_headers(static=True)
            self.end_headers()
            return
        self.send_bytes(200, target.read_bytes(), CONTENT_TYPES[ext], static=True, extra={"ETag": etag})

    def events(self) -> None:
        app = self.app
        client = app.hub.add()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream; charset=utf-8")
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("X-Frame-Options", "DENY")
            self.send_header("Connection", "close")
            self.end_headers()
            self.close_connection = True
            self.wfile.write(b"retry: 3000\n\n")
            self.write_event("hello", json.dumps({"version": VERSION, "started_ms": app.started_ms,
                                                  "language": app.cfg.language, "client": client.id},
                                                 separators=(",", ":")))
            self.write_event("state", json.dumps(app.state_payload(), ensure_ascii=False, separators=(",", ":")))
            app.on_client_connect()
            idle = 0.0
            while not client.closed and not app.stopping:
                try:
                    event, data = client.queue.get(timeout=1.0)
                except queue.Empty:
                    idle += 1.0
                    if idle >= SSE_PING_S:
                        idle = 0.0
                        self.wfile.write(b": ping\n\n")
                    continue
                idle = 0.0
                self.write_event(event, data)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            app.hub.remove(client)

    def write_event(self, event: str, data: str) -> None:
        self.wfile.write(f"event: {event}\ndata: {data}\n\n".encode("utf-8"))
        self.wfile.flush()

    def post(self) -> None:
        # Every refusal below answers before the body is read: close the connection, or the unread
        # body would be parsed as the next request on it, with headers its sender chose.
        keep_open = not self.close_connection
        self.close_connection = True
        if not self.precheck():
            return
        path = urllib.parse.urlsplit(self.path).path
        if not self.cookie_ok() or not self.csrf_ok(self.headers.get("X-Bridge-Token")):
            self.send_unauthorized("/api/")
            return
        if not self.origin_ok(self.headers.get("Origin")):
            self.send_error_json("forbidden_origin", "wrong or missing Origin")
            return
        ctype = (self.headers.get("Content-Type") or "").split(";")[0].strip().lower()
        if ctype != "application/json":
            self.send_error_json("unsupported_media_type", "the body must be application/json")
            return
        try:
            length = int(self.headers.get("Content-Length") or "0")
        except ValueError:
            length = -1
        if length > MAX_BODY:
            self.send_error_json("payload_too_large", "the body is larger than 64 KB")
            self.close_connection = True
            return
        if length < 0:
            self.send_error_json("invalid_json", "missing Content-Length")
            return
        raw = self.rfile.read(length) if length else b""
        self.close_connection = not keep_open
        try:
            body = json.loads(raw.decode("utf-8")) if raw else None
        except (ValueError, UnicodeDecodeError):
            body = None
        if not isinstance(body, dict):
            self.send_error_json("invalid_json", "the body must be a JSON object")
            return
        app = self.app
        try:
            if path == "/api/action":
                self.send_json(200, app.actions.execute(body.get("verb"), body.get("args")))
            elif path == "/api/ask":
                for name in body:
                    if name not in ("kind", "args", "via", "model", "conv", "place"):
                        raise ActionError(400, "invalid_argument", "unknown field", str(name)[:40])
                status, payload = app.actions.ask(body.get("kind"), body.get("args"), via=body.get("via", "control"),
                                                  model=body.get("model"), conv=body.get("conv"), place=body.get("place"))
                self.send_json(status, payload)
            elif path == "/api/reload":
                for name in body:
                    if name != "fresh":
                        raise ActionError(400, "invalid_argument", "unknown field", str(name)[:40])
                fresh = body.get("fresh", False)
                if not isinstance(fresh, bool):
                    raise ActionError(400, "invalid_argument", "fresh must be true or false", "fresh")
                app.collector.request("both", fresh=fresh)
                self.send_json(202, {"ok": True, "loading": app.collector.loading_state()})
            elif path == "/api/route":
                try:
                    self.send_json(200, app.launch_model.handle_route(body))
                except LaunchError as error:
                    self.send_error_json(error.code, error.message, error.field, status=error.status)
            elif path == "/api/presence":
                for name in body:
                    if name not in ("client", "visible"):
                        raise ActionError(400, "invalid_argument", "unknown field", str(name)[:40])
                visible = body.get("visible")
                if not isinstance(visible, bool):
                    raise ActionError(400, "invalid_argument", "visible must be true or false", "visible")
                back = app.hub.set_visible(str(body.get("client") or "")[:40], visible)
                if back is None:
                    raise ActionError(404, "not_found", "no such page is connected", "client")
                if back:
                    app.on_client_connect()   # a page that comes back sees fresh tabs at once
                self.send_json(200, {"ok": True})
            elif path == "/api/triage/run":
                app.triage.handle_post(self, body)
            elif path.startswith("/api/jev/") and jev is None:
                self.send_json(404, {"ok": False, "error": {"code": "jev_off", "message": "Jev is not installed here"}})
            elif path.startswith("/api/jev/"):
                jev.handle_post(self, app, path, body)
            else:
                self.send_error_json("not_found", "unknown endpoint")
        except ActionError as error:
            self.send_error_json(error.code, error.message, error.field, status=error.status, extra=error.extra)
        except RunnerRefused:
            app.log_error("runner refused a program:\n" + traceback.format_exc())
            self.send_error_json("internal", "internal error")


class WebServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True
    app: App

    def handle_error(self, request: Any, client_address: Any) -> None:
        """A browser that drops a connection mid-read (a reload, a closed tab) is no error worth a traceback"""
        if isinstance(sys.exc_info()[1], (ConnectionResetError, BrokenPipeError, ConnectionAbortedError)):
            return
        super().handle_error(request, client_address)


def default_state_dir(root: Path | str) -> Path:
    """<root>/.bridge/cockpit: the server file, the key, the log and what the page keeps."""
    return Path(root) / ".bridge" / "cockpit"


def scratch_of(root: Path | str, state_dir: Path | str) -> dict | None:
    """Whether this cockpit runs on something other than the Bridge itself, so the page can say so on every
    screen: a linked worktree (its .git is a file) is a copy whose inbox, tasks and starts go when it goes,
    and a state folder of its own keeps the starts made here out of the real cockpit."""
    root, state_dir = Path(root), Path(state_dir)
    if (root / ".git").is_file():
        return {"kind": "copy", "root": str(root)}
    if state_dir.resolve() != default_state_dir(root).resolve():
        return {"kind": "state", "state_dir": str(state_dir)}
    return None


COOKIE_AGE_S = 3 * 86400    # a browser logs in again after a few days
CODE_AGE_S = 60             # a login code from `url` works once, within this minute
CLOCK_SKEW_S = 5
TOKEN_RE = re.compile(r"[A-Za-z0-9_-]{32,}")


def mac(token: str, message: str) -> str:
    return hmac.new(token.encode("utf-8"), message.encode("utf-8"), hashlib.sha256).hexdigest()


def derived(token: str, purpose: str) -> str:
    """A value made from the key for one purpose: it proves the key without being it."""
    return mac(token, f"derived|{purpose}")


def login_code(token: str, now_ms: float, nonce: str | None = None) -> str:
    """A one-time login code `<nonce>.<second>.<mac>`: what `url` prints instead of the key."""
    nonce = nonce or secrets.token_hex(8)
    ts = int(now_ms // 1000)
    return f"{nonce}.{ts}.{mac(token, f'code|{nonce}|{ts}')}"


def parse_signed(token: str, kind: str, value: str, parts: int) -> tuple[str | None, int | None]:
    """(nonce, second) of a code (parts 3) or session value (parts 2) whose mac checks out, else (None, None)."""
    fields = (value or "").split(".")
    if len(fields) != parts or not all(fields) or not fields[-2].isdigit() or len(fields[-2]) > 12:
        return None, None
    nonce, ts, given = (fields[0] if parts == 3 else ""), int(fields[-2]), fields[-1]
    message = f"code|{nonce}|{ts}" if kind == "code" else f"session|{ts}"
    if not hmac.compare_digest(given.encode("utf-8"), mac(token, message).encode("utf-8")):
        return None, None
    return nonce, ts


def stable_token(state_dir: Path) -> str:
    """The key of this cockpit: read from <state>/token, made once (0600) when missing or damaged."""
    path = Path(state_dir) / "token"
    try:
        value = path.read_text(encoding="utf-8").strip()
        if TOKEN_RE.fullmatch(value):
            return value
    except OSError:
        pass
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    value = secrets.token_urlsafe(32)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(value + "\n")
    os.chmod(path, 0o600)
    return value


def forget_token(state_dir: Path) -> None:
    """A new key on the next start: every browser has to come through `url` once more."""
    try:
        (Path(state_dir) / "token").unlink()
    except FileNotFoundError:
        pass


def make_server(root: Path | str, port: int | None = None, runner: Runner | None = None,
                state_dir: Path | str | None = None, cfg: WebConfig | None = None,
                clock: Callable[[], float] | None = None, background: bool = True,
                write_json: bool = True, key_dir: Path | str | None = None,
                code_root: Path | str | None = None) -> WebServer:
    """Bind 127.0.0.1:<port> (0 = ephemeral) and wire the app; `background` starts its threads."""
    root = Path(root).resolve()
    cfg = cfg or load_web_config(root)
    state_dir = Path(state_dir) if state_dir else default_state_dir(root)
    runner = runner or Runner(root, code=code_root)
    clock = clock or (lambda: time.time() * 1000)
    token = stable_token(state_dir)
    app = App(root, cfg, runner, state_dir, clock, token, Path(key_dir) if key_dir else None, code_root=code_root)
    server = WebServer((HOST, cfg.port if port is None else port), Handler)
    server.app = app
    app.port = server.server_address[1]
    if write_json:
        app.write_server_json()
    if background:
        app.start()
    return server
