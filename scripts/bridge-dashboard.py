#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Bridge Dashboard — operational single-file HTML overview.

Aggregates the live state of:
  * Fleet (remotes/*.yaml with Tailscale reachability)
  * Work board (work/board.md doing/queue/done counts + hero tickets)
  * Calendar (calendar/entries.yaml next 24h)
  * Channels (channels/*.yaml + bridge-deck :8791 /metrics)
  * Git activity (per repo from ecosystem.yaml, last 24h)
  * Upstream (HEAD..development)

Usage:
  python3 scripts/bridge-dashboard.py           # writes work/dashboard.html
  python3 scripts/bridge-dashboard.py --open    # also opens in browser
  python3 scripts/bridge-dashboard.py --serve   # regen every 30s, serves :8790

Zero third-party deps except PyYAML (already used elsewhere in the repo).
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import html
import http.server
import os
import re
import socketserver
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parent.parent
OUT = REPO / "work" / "dashboard.html"
PING_TIMEOUT_MS = 800
HTTP_TIMEOUT_S = 1.5
BRIDGE_DECK_URL = "http://homeserver:8791"
SERVE_PORT = 8790
REFRESH_EVERY_S = 30

# Latency thresholds for slow-probe visualization (ms).
# Anything below SLOW_MS = green; SLOW_MS..NEAR_MS = yellow (slow);
# NEAR_MS..fail = orange (near-timeout); failure = red.
LATENCY_SLOW_MS = 300
LATENCY_NEAR_MS = 700


def latency_class(elapsed_ms: float | None, reachable: bool | None) -> str:
    """Map (elapsed_ms, reachable) to a status class.

    Classes: ok | slow | near | off | unknown.
    """
    if reachable is None:
        return "unknown"
    if reachable is False:
        return "off"
    if elapsed_ms is None:
        return "ok"
    if elapsed_ms < LATENCY_SLOW_MS:
        return "ok"
    if elapsed_ms < LATENCY_NEAR_MS:
        return "slow"
    return "near"


def latency_icon(cls: str) -> str:
    """Lightweight emoji marker for a latency class (HTML-safe; emojis ok per code style)."""
    return {
        "ok": "",
        "slow": "🐢",
        "near": "⚠",
        "off": "❌",
        "unknown": "",
    }.get(cls, "")


# ────────────────────────────────────────────────────────────────────────
# Data collection
# ────────────────────────────────────────────────────────────────────────

def load_yaml(path: Path):
    try:
        with path.open() as f:
            return yaml.safe_load(f) or {}
    except FileNotFoundError:
        return {}
    except yaml.YAMLError:
        return {}


def run(cmd: list[str], cwd: Path | None = None, timeout: float = 5.0) -> str:
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip()
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return ""


def ping(ip: str) -> tuple[bool, float | None]:
    """Ping ip once. Returns (reachable, elapsed_ms_or_None)."""
    if not ip:
        return False, None
    t0 = time.perf_counter()
    r = subprocess.run(
        ["ping", "-c", "1", "-W", str(PING_TIMEOUT_MS), ip],
        capture_output=True,
    )
    elapsed = (time.perf_counter() - t0) * 1000.0
    return r.returncode == 0, elapsed


def http_get(url: str) -> tuple[str, float | None]:
    """HTTP GET. Returns (body, elapsed_ms_or_None). Empty body on failure."""
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "bridge-dashboard"})
        with urllib.request.urlopen(req, timeout=HTTP_TIMEOUT_S) as resp:
            body = resp.read().decode("utf-8", errors="replace")
            return body, (time.perf_counter() - t0) * 1000.0
    except Exception:
        return "", (time.perf_counter() - t0) * 1000.0


# ── Fleet ───────────────────────────────────────────────────────────────

def collect_fleet() -> list[dict]:
    remotes_dir = REPO / "remotes"
    remotes = []
    for p in sorted(remotes_dir.glob("*.yaml")):
        if p.name.startswith("_"):
            continue
        data = load_yaml(p)
        if not data:
            continue
        name = data.get("name", p.stem)
        net = data.get("network", {}) or {}
        ts_ip = net.get("tailscale_ip") or ""
        lan_ip = net.get("lan_ip") or ""
        remotes.append({
            "name": name,
            "type": data.get("type", "unknown"),
            "os": data.get("os") or data.get("firmware") or "",
            "tailscale_ip": ts_ip,
            "lan_ip": lan_ip,
            "services": data.get("services") or [],
            "capabilities": data.get("capabilities") or [],
            "wol_enabled": ((data.get("wake_on_lan") or {}).get("enabled", False)),
            "declared_status": data.get("status", ""),
            "reachable": None,  # filled in by probe
            "ip_used": "",
            "elapsed_ms": None,
        })

    def probe(r):
        for kind in ("tailscale_ip", "lan_ip"):
            ip = r[kind]
            if not ip:
                continue
            reachable, elapsed = ping(ip)
            if reachable:
                r["reachable"] = True
                r["ip_used"] = f"{kind.replace('_ip', '')}:{ip}"
                r["elapsed_ms"] = elapsed
                return
        r["reachable"] = False

    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        list(ex.map(probe, remotes))
    return remotes


# ── Work board ──────────────────────────────────────────────────────────

def collect_board() -> dict:
    board_path = REPO / "work" / "board.md"
    text = board_path.read_text() if board_path.exists() else ""
    sections: dict[str, list[dict]] = {"doing": [], "backlog": [], "done": []}
    current: str | None = None
    headers: list[str] = []
    for line in text.splitlines():
        m = re.match(r"^##\s+(\w+)", line)
        if m:
            name = m.group(1).lower()
            current = name if name in sections else None
            headers = []
            continue
        if not current or not line.startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if line.startswith("|--"):
            continue
        # Capture header row to make column lookup robust
        if not headers and cells and any(c.lower() in {"ticket", "priority", "description"} for c in cells):
            headers = [c.lower() for c in cells]
            continue
        if not cells or len(cells) < 2:
            continue
        row = dict(zip(headers or [f"c{i}" for i in range(len(cells))], cells))
        sections[current].append({
            "ticket": row.get("ticket") or (cells[1] if "priority" in (headers[:1] if headers else []) else cells[0]),
            "summary": row.get("description") or row.get("summary") or (cells[2] if len(cells) > 2 else ""),
            "type": row.get("type") or "",
            "context": row.get("context") or row.get("ctx") or "",
            "since": row.get("since") or "",
            "status": row.get("status") or "",
            "prio": row.get("priority") or "",
        })
    return sections


# ── Log (recent events) ─────────────────────────────────────────────────

def collect_recent_log_events(limit: int = 10) -> list[dict]:
    log = REPO / "work" / "log.md"
    if not log.exists():
        return []
    rows = []
    pattern = re.compile(r"^\|\s*(\d{4}-\d{2}-\d{2}\s\d{2}:\d{2})\s*\|\s*([^|]+?)\s*\|\s*([^|]+?)\s*\|\s*(.+?)\s*\|\s*$")
    for line in log.read_text().splitlines():
        m = pattern.match(line)
        if m:
            rows.append({
                "ts": m.group(1),
                "type": m.group(2).strip(),
                "ctx": m.group(3).strip(),
                "what": m.group(4).strip(),
            })
    return rows[-limit:][::-1]


# ── Calendar ────────────────────────────────────────────────────────────

def collect_calendar_next24h() -> list[dict]:
    data = load_yaml(REPO / "calendar" / "entries.yaml")
    entries = data.get("entries") or []
    now = datetime.now(timezone.utc)
    soon = now + timedelta(hours=24)
    result = []
    for e in entries:
        if e.get("status") == "cancelled":
            continue
        ts = e.get("delivery_at")
        try:
            dt = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue
        # For repeating entries compute next occurrence within 24h
        rrule = (e.get("repeat") or {}).get("rrule")
        next_fire = dt
        if rrule and dt < now:
            next_fire = _rrule_next(rrule, now)
            if next_fire is None:
                continue
        if now <= next_fire <= soon:
            result.append({
                "id": e.get("id"),
                "title": e.get("title"),
                "at": next_fire,
                "recipients": e.get("recipients") or [],
                "duration_min": e.get("duration_estimate_min"),
                "repeat": (e.get("repeat") or {}).get("spec"),
            })
    result.sort(key=lambda x: x["at"])
    return result


def _rrule_next(rrule: str, after: datetime) -> datetime | None:
    """Minimal RRULE expander supporting FREQ=DAILY|WEEKLY|HOURLY + BYHOUR/BYMINUTE/BYDAY (all comma-lists)."""
    parts = dict(kv.split("=", 1) for kv in rrule.split(";") if "=" in kv)

    def _ints(key: str, default: list[int]) -> list[int]:
        raw = parts.get(key)
        if not raw:
            return default
        try:
            return sorted({int(x) for x in raw.split(",") if x.strip().lstrip("-").isdigit()})
        except ValueError:
            return default

    by_hours = _ints("BYHOUR", [0])
    by_mins = _ints("BYMINUTE", [0])
    by_days = parts.get("BYDAY", "")
    day_map = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
    allowed = {day_map[d] for d in by_days.split(",") if d in day_map} if by_days else None

    now_local = datetime.now(after.tzinfo or timezone.utc)
    for offset in range(0, 30):
        day = now_local + timedelta(days=offset)
        if allowed and day.weekday() not in allowed:
            continue
        for h in by_hours:
            for m in by_mins:
                candidate = day.replace(hour=h, minute=m, second=0, microsecond=0)
                if candidate >= now_local:
                    return candidate
    return None


# ── Channels ────────────────────────────────────────────────────────────

def collect_channels() -> list[dict]:
    ch_dir = REPO / "channels"
    channels = []
    for p in sorted(ch_dir.glob("*.yaml")):
        if p.name.startswith("_"):
            continue
        data = load_yaml(p)
        if not data:
            continue
        channels.append({
            "name": p.stem,
            "kind": data.get("kind") or data.get("type") or "",
            "status": data.get("status", ""),
            "description": (data.get("description") or "").split("\n")[0],
        })
    return channels


# ── Bridge-Deck metrics ──────────────────────────────────────────────

def collect_cockpit_office() -> dict:
    text, elapsed = http_get(f"{BRIDGE_DECK_URL}/metrics")
    if not text:
        return {"up": False, "elapsed_ms": elapsed}
    out = {"up": True, "collectors": {}, "uptime_s": 0, "version": "", "elapsed_ms": elapsed}
    for line in text.splitlines():
        if line.startswith("daemon_info{") and "=" in line:
            m = re.search(r'version="([^"]+)"', line)
            if m:
                out["version"] = m.group(1)
        elif line.startswith("daemon_uptime_seconds "):
            try:
                out["uptime_s"] = float(line.split()[1])
            except (ValueError, IndexError):
                pass
        elif line.startswith("collector_polls_total{"):
            m = re.search(r'collector="([^"]+)"\}\s+(\S+)', line)
            if m:
                out["collectors"].setdefault(m.group(1), {})["polls"] = int(float(m.group(2)))
        elif line.startswith("collector_poll_errors_total{"):
            m = re.search(r'collector="([^"]+)"\}\s+(\S+)', line)
            if m:
                out["collectors"].setdefault(m.group(1), {})["errors"] = int(float(m.group(2)))
    return out


# ── Git activity ────────────────────────────────────────────────────────

def collect_git_activity() -> list[dict]:
    eco = load_yaml(REPO / "ecosystem.yaml")
    local_root = Path(os.path.expanduser(eco.get("local_root", "~/Developer/org")))
    candidates = []
    # walk nested repo dicts
    def walk(node):
        if isinstance(node, dict):
            if "github" in node and isinstance(node.get("github"), str):
                slug = node["github"].split("/")[-1]
                local = node.get("local_path")
                if local:
                    candidates.append((slug, Path(os.path.expanduser(local))))
                else:
                    candidates.append((slug, local_root / slug))
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)
    walk(eco.get("base", {}))
    walk(eco.get("customers", {}))
    walk(eco.get("partners", {}))
    walk(eco.get("internal", {}))
    candidates.append(("the-bridge", REPO))
    seen = set()
    uniq = []
    for slug, path in candidates:
        if path in seen or not (path / ".git").exists():
            continue
        seen.add(path)
        uniq.append((slug, path))

    def probe(args):
        slug, path = args
        since = (datetime.now() - timedelta(hours=24)).strftime("%Y-%m-%d %H:%M")
        count = run(["git", "rev-list", "--count", f"--since={since}", "HEAD"], cwd=path, timeout=3)
        dirty = run(["git", "status", "--porcelain"], cwd=path, timeout=3)
        branch = run(["git", "branch", "--show-current"], cwd=path, timeout=3)
        head = run(["git", "log", "-1", "--format=%h %s"], cwd=path, timeout=3)
        return {
            "slug": slug,
            "commits_24h": int(count) if count.isdigit() else 0,
            "dirty": bool(dirty),
            "branch": branch,
            "head": head,
            "path": str(path),
        }

    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        results = list(ex.map(probe, uniq))
    results.sort(key=lambda r: (-r["commits_24h"], -int(r["dirty"]), r["slug"]))
    return results


# ── Upstream ────────────────────────────────────────────────────────────

def collect_upstream() -> dict:
    branch = run(["git", "branch", "--show-current"], cwd=REPO)
    on_user = branch.startswith("user/")
    head = run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO)
    ahead_dev = run(["git", "rev-list", "--count", "HEAD..development"], cwd=REPO)
    behind_dev = run(["git", "rev-list", "--count", "development..HEAD"], cwd=REPO)
    return {
        "branch": branch,
        "head": head,
        "on_user": on_user,
        "core_ahead": int(ahead_dev) if ahead_dev.isdigit() else 0,
        "user_ahead": int(behind_dev) if behind_dev.isdigit() else 0,
    }


# ────────────────────────────────────────────────────────────────────────
# Render
# ────────────────────────────────────────────────────────────────────────

def fmt_uptime(seconds: float) -> str:
    if not seconds:
        return "—"
    td = timedelta(seconds=int(seconds))
    days, rem = divmod(td.total_seconds(), 86400)
    hours = rem // 3600
    if days:
        return f"{int(days)}d {int(hours)}h"
    mins = (rem % 3600) // 60
    return f"{int(hours)}h {int(mins)}m"


def fmt_time_local(dt: datetime) -> str:
    local = dt.astimezone()
    today = datetime.now(local.tzinfo).date()
    if local.date() == today:
        return local.strftime("today %H:%M")
    if local.date() == today + timedelta(days=1):
        return local.strftime("tomorrow %H:%M")
    return local.strftime("%a %d.%m %H:%M")


def status_class(reachable: bool | None) -> str:
    if reachable is True:
        return "ok"
    if reachable is False:
        return "off"
    return "unknown"


def render(data: dict) -> str:
    now = datetime.now().strftime("%a %d.%m.%Y · %H:%M:%S")
    iso_week = datetime.now().isocalendar().week
    config = data["config"]
    board = data["board"]
    fleet = data["fleet"]
    cpo = data["cockpit_office"]
    cal = data["calendar"]
    git = data["git"]
    upstream = data["upstream"]
    channels = data["channels"]
    events = data["events"]

    ok_remotes = sum(1 for r in fleet if r["reachable"])
    doing_count = len(board["doing"])
    queue_count = len(board["backlog"])
    done_count = len(board["done"])

    # ---- Fleet tiles ----
    fleet_html = []
    for r in fleet:
        lat_cls = latency_class(r.get("elapsed_ms"), r["reachable"])
        # Border / dot still distinguish ok vs off; slow/near treated as ok-ish.
        border_cls = "ok" if lat_cls in ("ok", "slow", "near") else status_class(r["reachable"])
        svc_list = []
        for svc in r["services"]:
            label = svc.get("slug") or svc.get("label") or "?"
            svc_type = svc.get("type", "")
            tag_cls = "svc-keepalive" if svc_type == "keepalive" else "svc-other"
            svc_list.append(f'<span class="svc {tag_cls}">{html.escape(label)}</span>')
        svc_html = "".join(svc_list) or '<span class="svc dim">—</span>'
        wol = '<span class="chip chip-wol">WoL</span>' if r["wol_enabled"] else ""
        ip_used = html.escape(r["ip_used"]) if r["ip_used"] else ""
        elapsed = r.get("elapsed_ms")
        if elapsed is not None and r["reachable"]:
            lat_label = f"{int(round(elapsed))}ms"
        else:
            lat_label = ""
        icon = latency_icon(lat_cls)
        lat_html = ""
        if lat_label or icon:
            lat_html = f'<span class="lat lat-{lat_cls}" title="{lat_label or "—"}">{icon} {html.escape(lat_label)}</span>'
        fleet_html.append(f'''
          <div class="fleet-tile fleet-{border_cls} tile-status-{lat_cls}">
            <div class="fleet-head">
              <span class="dot dot-{lat_cls}"></span>
              <strong>{html.escape(r["name"])}</strong>
              <span class="fleet-type">{html.escape(r["type"])}</span>
              {lat_html}
              {wol}
            </div>
            <div class="fleet-os">{html.escape(r["os"])}</div>
            <div class="fleet-ip">{ip_used or "&mdash;"}</div>
            <div class="fleet-services">{svc_html}</div>
          </div>
        ''')

    # ---- Doing rows ----
    doing_rows = []
    for t in board["doing"][:12]:
        # Derive marker from status text (★ counts, emoji prefix)
        doing_rows.append(f'''
          <tr>
            <td><code>{html.escape(t["ticket"])}</code></td>
            <td class="dim">{html.escape(t["context"])}</td>
            <td>{html.escape(t["summary"][:120])}</td>
            <td class="since">{html.escape(t["since"])}</td>
          </tr>
        ''')

    # ---- Calendar ----
    cal_rows = []
    for e in cal:
        recips = ", ".join(
            f'{r.get("mandant","?")}/{r.get("person","?")}'
            for r in e["recipients"][:3]
        )
        extra = f' <span class="dim">+{len(e["recipients"])-3}</span>' if len(e["recipients"]) > 3 else ""
        cal_rows.append(f'''
          <li>
            <span class="cal-time">{fmt_time_local(e["at"])}</span>
            <span class="cal-title">{html.escape(str(e["title"]))}</span>
            <span class="cal-recips dim">{html.escape(recips)}{extra}</span>
          </li>
        ''')
    if not cal_rows:
        cal_rows.append('<li class="empty">No entries in the next 24h.</li>')

    # ---- Git activity ----
    git_rows = []
    for g in git[:10]:
        badge = '<span class="chip chip-dirty">●</span>' if g["dirty"] else ""
        cnt = g["commits_24h"]
        cnt_cls = "ok" if cnt else "dim"
        git_rows.append(f'''
          <tr>
            <td><strong>{html.escape(g["slug"])}</strong> {badge}</td>
            <td class="num {cnt_cls}">{cnt}</td>
            <td class="dim">{html.escape(g["branch"])}</td>
            <td class="dim head">{html.escape(g["head"][:60])}</td>
          </tr>
        ''')
    if not git_rows:
        git_rows.append('<tr><td colspan="4" class="empty">No local repos found.</td></tr>')

    # ---- Bridge-Deck collector summary ----
    cpo_rows = []
    if cpo["up"]:
        cpo_lat_cls = latency_class(cpo.get("elapsed_ms"), True)
        cpo_lat_icon = latency_icon(cpo_lat_cls)
        cpo_lat_label = f"{int(round(cpo['elapsed_ms']))}ms" if cpo.get("elapsed_ms") is not None else ""
        if cpo_lat_cls in ("slow", "near"):
            cpo_rows.append(
                f'<li><span class="dot dot-{cpo_lat_cls}"></span>'
                f'<strong>probe</strong> '
                f'<span class="lat lat-{cpo_lat_cls}">{cpo_lat_icon} {html.escape(cpo_lat_label)}</span></li>'
            )
        for name, stats in sorted(cpo["collectors"].items()):
            errs = stats.get("errors", 0)
            polls = stats.get("polls", 0)
            cls = "warn" if errs else "ok"
            cpo_rows.append(f'''
              <li>
                <span class="dot dot-{cls}"></span>
                <strong>{html.escape(name)}</strong>
                <span class="dim">{polls:,} polls · {errs} err</span>
              </li>
            ''')
    else:
        cpo_rows.append('<li><span class="dot dot-off"></span><strong>offline</strong></li>')

    # ---- Channels ----
    ch_rows = []
    for c in channels:
        ch_rows.append(f'''
          <li>
            <strong>{html.escape(c["name"])}</strong>
            <span class="dim">· {html.escape(c["kind"] or "—")}</span>
          </li>
        ''')

    # ---- Events ----
    event_rows = "".join(
        f'''<tr>
              <td class="ts">{html.escape(e["ts"])}</td>
              <td>{html.escape(e["type"])}</td>
              <td class="dim">{html.escape(e["ctx"])}</td>
              <td>{html.escape(e["what"][:180])}</td>
            </tr>'''
        for e in events
    ) or '<tr><td colspan="4" class="empty">log.md is empty.</td></tr>'

    # ---- Upstream ----
    if upstream["core_ahead"]:
        upstream_body = f'''
          <div class="alert alert-yellow">
            <strong>{upstream["core_ahead"]} CORE commits available.</strong>
            <div class="dim">Recommendation: <code>git merge development</code></div>
          </div>'''
    else:
        upstream_body = '<div class="alert-empty"><span class="dot dot-ok"></span> Up to date with development.</div>'

    # ---- Template ----
    theme_name = config.get("theme", "professional")
    user = (config.get("identity") or {}).get("name", "?")
    return DASHBOARD_HTML.format(
        refresh=REFRESH_EVERY_S,
        now=now,
        kw=iso_week,
        user=html.escape(user),
        theme=html.escape(theme_name),
        head=html.escape(upstream["head"]),
        branch=html.escape(upstream["branch"]),
        ok_remotes=ok_remotes,
        total_remotes=len(fleet),
        doing_count=doing_count,
        queue_count=queue_count,
        done_count=done_count,
        cpo_version=html.escape(cpo.get("version", "")),
        cpo_uptime=fmt_uptime(cpo.get("uptime_s", 0)),
        cpo_class=("warn" if latency_class(cpo.get("elapsed_ms"), True) in ("slow", "near") else "ok") if cpo["up"] else "off",
        cpo_url=BRIDGE_DECK_URL,
        fleet_html="".join(fleet_html),
        doing_rows="".join(doing_rows),
        cal_rows="".join(cal_rows),
        git_rows="".join(git_rows),
        cpo_rows="".join(cpo_rows),
        ch_rows="".join(ch_rows),
        upstream_body=upstream_body,
        event_rows=event_rows,
    )


DASHBOARD_HTML = """<!doctype html>
<html lang="en" data-theme="dark">
<head>
<meta charset="utf-8" />
<meta name="viewport" content="width=device-width, initial-scale=1" />
<meta http-equiv="refresh" content="{refresh}" />
<title>The Bridge · Control Center</title>
<style>
  :root {{
    --bg: #02030a;
    --panel: #0a1628;
    --panel-2: #0e1d35;
    --border: rgba(34,211,238,0.18);
    --border-strong: rgba(34,211,238,0.35);
    --text: #e0f2fe;
    --dim: #64748b;
    --ok: #10f5b3;
    --warn: #f59e0b;
    --err: #ef4444;
    --red: #fca5a5;
    --cyan: #22d3ee;
    --amber: #fbbf24;
    --violet: #a78bfa;
    --mono: ui-monospace, "SF Mono", "Fira Code", Menlo, monospace;
  }}
  * {{ box-sizing: border-box; }}
  html, body {{
    margin: 0; padding: 0;
    background: var(--bg);
    color: var(--text);
    font-family: -apple-system, "Helvetica Neue", Inter, sans-serif;
    font-size: 14px;
    line-height: 1.45;
    min-height: 100vh;
  }}
  body {{
    background:
      radial-gradient(ellipse at 20% -10%, rgba(34,211,238,0.08), transparent 55%),
      radial-gradient(ellipse at 80% 110%, rgba(139,92,246,0.06), transparent 55%),
      var(--bg);
  }}
  a {{ color: var(--cyan); text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  code {{ font-family: var(--mono); font-size: 12px; color: var(--cyan); }}

  /* Header */
  header.top {{
    display: flex; flex-wrap: wrap; align-items: center; gap: 18px;
    padding: 14px 24px;
    background: linear-gradient(180deg, rgba(10,26,48,0.9), rgba(5,12,26,0.85));
    border-bottom: 1px solid var(--border-strong);
    box-shadow: 0 0 24px rgba(34,211,238,0.1);
    position: sticky; top: 0; z-index: 10;
    backdrop-filter: blur(8px);
  }}
  header.top h1 {{
    margin: 0;
    font-size: 15px;
    letter-spacing: 2px;
    text-transform: uppercase;
    color: var(--cyan);
    font-weight: 600;
  }}
  header.top .dot-pulse {{
    width: 8px; height: 8px;
    background: var(--cyan);
    border-radius: 50%;
    box-shadow: 0 0 8px var(--cyan);
    animation: pulse 2s ease-in-out infinite;
    display: inline-block;
    margin-right: 10px;
  }}
  @keyframes pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.4; }} }}
  header.top .sub {{ color: var(--dim); font-size: 13px; font-family: var(--mono); }}
  header.top .spacer {{ flex: 1; }}
  header.top .stat {{
    display: inline-flex; align-items: baseline; gap: 6px;
    padding: 4px 12px;
    border: 1px solid var(--border);
    border-radius: 4px;
    background: rgba(10,26,48,0.5);
    font-family: var(--mono); font-size: 13px;
  }}
  header.top .stat.ok {{ border-color: rgba(16,245,179,0.4); color: var(--ok); }}
  header.top .stat.warn {{ border-color: rgba(245,158,11,0.5); color: var(--warn); }}
  header.top .stat.red {{ border-color: rgba(239,68,68,0.6); color: var(--red); box-shadow: 0 0 14px rgba(239,68,68,0.18); }}
  header.top .stat.off {{ border-color: rgba(239,68,68,0.4); color: var(--red); }}
  header.top .stat strong {{ font-weight: 700; }}
  header.top .stat .unit {{ font-size: 10px; text-transform: uppercase; letter-spacing: 1px; opacity: 0.7; }}

  /* Layout */
  main {{
    display: grid;
    grid-template-columns: repeat(12, 1fr);
    gap: 16px;
    padding: 18px 24px 36px;
    max-width: 1800px;
    margin: 0 auto;
  }}
  .card {{
    background: linear-gradient(180deg, var(--panel), var(--panel-2));
    border: 1px solid var(--border);
    border-radius: 6px;
    padding: 14px 16px;
    min-height: 140px;
  }}
  .card h2 {{
    margin: 0 0 10px 0;
    font-size: 11px;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: var(--cyan);
    font-weight: 600;
    display: flex; align-items: center; gap: 8px;
  }}
  .card h2 .count {{
    margin-left: auto;
    font-family: var(--mono);
    color: var(--dim);
    font-weight: 400;
  }}
  /* Drilldown affordances — header is clickable, future detail view stub */
  .card h2[data-drill] {{
    cursor: pointer;
    user-select: none;
    padding: 2px 6px;
    margin: -2px -6px 8px -6px;
    border-radius: 4px;
    transition: background 120ms ease;
  }}
  .card h2[data-drill]:hover {{
    background: rgba(34,211,238,0.05);
  }}
  .card h2[data-drill]::after {{
    content: "›";
    color: var(--dim);
    font-weight: 400;
    margin-left: 6px;
    opacity: 0.5;
    transition: opacity 120ms ease, transform 120ms ease;
  }}
  .card h2[data-drill]:hover::after {{
    opacity: 1;
    transform: translateX(2px);
  }}

  .col-12 {{ grid-column: span 12; }}
  .col-8  {{ grid-column: span 8; }}
  .col-6  {{ grid-column: span 6; }}
  .col-4  {{ grid-column: span 4; }}
  .col-3  {{ grid-column: span 3; }}

  @media (max-width: 1200px) {{
    .col-8, .col-6 {{ grid-column: span 12; }}
    .col-4, .col-3 {{ grid-column: span 6; }}
  }}
  @media (max-width: 700px) {{
    main {{ grid-template-columns: 1fr; padding: 12px; }}
    .col-12, .col-8, .col-6, .col-4, .col-3 {{ grid-column: span 1; }}
  }}

  /* Fleet */
  .fleet-grid {{
    display: grid;
    grid-template-columns: repeat(auto-fill, minmax(230px, 1fr));
    gap: 10px;
  }}
  .fleet-tile {{
    background: rgba(5,12,26,0.6);
    border: 1px solid var(--border);
    border-radius: 5px;
    padding: 10px 12px;
  }}
  .fleet-tile.fleet-ok {{ border-color: rgba(16,245,179,0.35); }}
  .fleet-tile.fleet-off {{ border-color: rgba(239,68,68,0.35); opacity: 0.85; }}
  .fleet-head {{ display: flex; align-items: center; gap: 6px; margin-bottom: 4px; }}
  .fleet-type {{ color: var(--dim); font-size: 11px; text-transform: uppercase; letter-spacing: 0.5px; }}
  .fleet-os {{ color: var(--dim); font-size: 11px; margin-bottom: 4px; }}
  .fleet-ip {{ font-family: var(--mono); font-size: 11px; color: var(--cyan); margin-bottom: 6px; }}
  .fleet-services {{ display: flex; flex-wrap: wrap; gap: 4px; }}
  .svc {{
    font-size: 10px; padding: 1px 6px;
    border-radius: 10px;
    background: rgba(34,211,238,0.08);
    border: 1px solid rgba(34,211,238,0.18);
    color: var(--cyan);
  }}
  .svc-keepalive {{ background: rgba(16,245,179,0.08); border-color: rgba(16,245,179,0.25); color: var(--ok); }}
  .svc-other {{ color: var(--dim); }}

  .chip {{
    font-size: 9px; padding: 1px 6px;
    border-radius: 10px;
    background: rgba(251,191,36,0.12);
    border: 1px solid rgba(251,191,36,0.35);
    color: var(--amber);
    text-transform: uppercase; letter-spacing: 0.5px;
    margin-left: auto;
  }}
  .chip-dirty {{ background: rgba(245,158,11,0.15); color: var(--warn); border-color: rgba(245,158,11,0.4); }}

  .dot {{
    display: inline-block;
    width: 8px; height: 8px;
    border-radius: 50%;
    flex-shrink: 0;
  }}
  .dot-ok {{ background: var(--ok); box-shadow: 0 0 6px rgba(16,245,179,0.6); }}
  .dot-warn {{ background: var(--warn); box-shadow: 0 0 6px rgba(245,158,11,0.5); }}
  .dot-slow {{ background: var(--amber); box-shadow: 0 0 6px rgba(251,191,36,0.55); }}
  .dot-near {{ background: var(--warn); box-shadow: 0 0 8px rgba(245,158,11,0.7); }}
  .dot-off {{ background: var(--err); box-shadow: 0 0 6px rgba(239,68,68,0.5); }}
  .dot-unknown {{ background: var(--dim); }}

  /* Slow-probe latency markers */
  .lat {{
    margin-left: auto;
    font-family: var(--mono);
    font-size: 10px;
    padding: 1px 6px;
    border-radius: 10px;
    border: 1px solid transparent;
    white-space: nowrap;
  }}
  .lat-ok      {{ color: var(--ok); border-color: rgba(16,245,179,0.25); background: rgba(16,245,179,0.06); }}
  .lat-slow    {{ color: var(--amber); border-color: rgba(251,191,36,0.4); background: rgba(251,191,36,0.10); }}
  .lat-near    {{ color: var(--warn); border-color: rgba(245,158,11,0.5); background: rgba(245,158,11,0.12); }}
  .lat-off     {{ color: var(--red); border-color: rgba(239,68,68,0.5); background: rgba(239,68,68,0.10); }}
  .lat-unknown {{ display: none; }}

  /* Tile status overlays — slow/near tint the border without faking failure */
  .tile-status-slow {{ border-color: rgba(251,191,36,0.45) !important; }}
  .tile-status-near {{ border-color: rgba(245,158,11,0.55) !important; box-shadow: 0 0 10px rgba(245,158,11,0.10); }}

  .dim {{ color: var(--dim); }}

  /* Tables */
  table {{ width: 100%; border-collapse: collapse; font-size: 13px; }}
  table th {{
    text-align: left;
    font-weight: 500;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.5px;
    color: var(--dim);
    padding: 6px 8px;
    border-bottom: 1px solid var(--border);
  }}
  table td {{
    padding: 6px 8px;
    border-bottom: 1px solid rgba(34,211,238,0.06);
    vertical-align: top;
  }}
  table td.num {{ text-align: right; font-family: var(--mono); }}
  table td.num.ok {{ color: var(--ok); font-weight: 600; }}
  table td.num.dim {{ color: var(--dim); }}
  table td.since {{ font-family: var(--mono); font-size: 11px; color: var(--dim); }}
  table td.ts {{ font-family: var(--mono); font-size: 11px; color: var(--cyan); white-space: nowrap; }}
  table td.head {{ font-family: var(--mono); font-size: 11px; }}
  table td.empty {{ color: var(--dim); text-align: center; padding: 18px; }}
  tr:last-child td {{ border-bottom: none; }}

  /* Lists */
  ul.tight {{ list-style: none; margin: 0; padding: 0; }}
  ul.tight li {{
    padding: 5px 0;
    display: flex; align-items: baseline; gap: 8px;
    border-bottom: 1px solid rgba(34,211,238,0.05);
    font-size: 13px;
  }}
  ul.tight li:last-child {{ border-bottom: none; }}
  ul.tight li.empty {{ color: var(--dim); justify-content: center; }}

  .cal-time {{ font-family: var(--mono); font-size: 12px; color: var(--amber); white-space: nowrap; min-width: 100px; }}
  .cal-title {{ flex: 1; }}
  .cal-recips {{ font-size: 11px; }}

  /* Alerts */
  .alert {{
    padding: 10px 12px;
    border-radius: 4px;
    background: rgba(239,68,68,0.08);
    border: 1px solid rgba(239,68,68,0.3);
    margin-bottom: 8px;
  }}
  .alert-yellow {{ background: rgba(245,158,11,0.08); border-color: rgba(245,158,11,0.3); }}
  .alert-empty {{
    padding: 14px 12px;
    color: var(--dim);
    display: flex; align-items: center; gap: 8px;
    text-align: center; justify-content: center;
  }}

  footer {{
    text-align: center;
    color: var(--dim);
    font-size: 11px;
    padding: 20px;
    font-family: var(--mono);
  }}
  footer a {{ color: var(--cyan); }}
</style>
</head>
<body>

<header class="top">
  <span class="dot-pulse"></span>
  <h1>THE BRIDGE · Control Center</h1>
  <span class="sub">Week {kw} · user/{user} · {theme} · @{head} on {branch}</span>
  <span class="spacer"></span>
  <span class="stat ok"><strong>{ok_remotes}</strong>/<span>{total_remotes}</span><span class="unit">fleet</span></span>
  <span class="stat"><strong>{doing_count}</strong><span class="unit">doing</span></span>
  <span class="stat"><strong>{queue_count}</strong><span class="unit">queue</span></span>
  <span class="stat {cpo_class}"><a href="{cpo_url}/" target="_blank"><strong>bridge-deck</strong> {cpo_version}</a> <span class="unit">{cpo_uptime}</span></span>
  <span class="sub">{now}</span>
</header>

<main>

  <!-- FLEET -->
  <section class="card col-8">
    <h2 data-drill="fleet" title="Click for details">Fleet <span class="count">{ok_remotes}/{total_remotes} online</span></h2>
    <div class="fleet-grid">{fleet_html}</div>
  </section>

  <!-- UPSTREAM -->
  <section class="card col-4">
    <h2 data-drill="upstream" title="Click for details">Upstream</h2>
    {upstream_body}
  </section>

  <!-- WORK BOARD -->
  <section class="card col-8">
    <h2 data-drill="board" title="Click for details">Work Board <span class="count">{doing_count} doing · {queue_count} queue · {done_count} done</span></h2>
    <table>
      <thead><tr><th>Ticket</th><th>Context</th><th>Description</th><th>Since</th></tr></thead>
      <tbody>{doing_rows}</tbody>
    </table>
  </section>

  <!-- CALENDAR -->
  <section class="card col-4">
    <h2 data-drill="calendar" title="Click for details">Calendar · next 24h</h2>
    <ul class="tight">{cal_rows}</ul>
  </section>

  <!-- COCKPIT-OFFICE METRICS -->
  <section class="card col-4">
    <h2 data-drill="bridge-deck" title="Click for details">Bridge-Deck <span class="count"><a href="{cpo_url}/" target="_blank">open →</a></span></h2>
    <ul class="tight">{cpo_rows}</ul>
  </section>

  <!-- CHANNELS -->
  <section class="card col-4">
    <h2 data-drill="channels" title="Click for details">Channels</h2>
    <ul class="tight">{ch_rows}</ul>
  </section>

  <!-- GIT ACTIVITY -->
  <section class="card col-4">
    <h2 data-drill="git" title="Click for details">Git Activity · last 24h</h2>
    <table>
      <thead><tr><th>Repo</th><th class="num">Commits</th><th>Branch</th><th>HEAD</th></tr></thead>
      <tbody>{git_rows}</tbody>
    </table>
  </section>

  <!-- RECENT EVENTS -->
  <section class="card col-12">
    <h2 data-drill="events" title="Click for details">Recent Events · work/log.md</h2>
    <table>
      <thead><tr><th>When</th><th>Type</th><th>Context</th><th>What</th></tr></thead>
      <tbody>{event_rows}</tbody>
    </table>
  </section>

</main>

<footer>
  Regenerated {now} · auto-refresh {refresh}s ·
  <a href="{cpo_url}/">bridge-deck :8791</a> ·
  served from <code>the-bridge/scripts/bridge-dashboard.py</code>
</footer>

<script>
  // Drilldown stubs — wire each [data-drill] header to a placeholder action.
  // Future: route to a detail view per topic.
  document.querySelectorAll('[data-drill]').forEach(el => {{
    el.addEventListener('click', (ev) => {{
      // Allow inner <a href> clicks to pass through (e.g. Bridge-Deck "open →")
      if (ev.target.closest('a')) return;
      alert('Drill: ' + el.dataset.drill + '\\n(future detail view)');
    }});
  }});
</script>

</body>
</html>
"""


# ────────────────────────────────────────────────────────────────────────
# Orchestration
# ────────────────────────────────────────────────────────────────────────

def collect_all() -> dict:
    config = load_yaml(REPO / "bridge-config.yaml")
    # Run independent probes in parallel
    with cf.ThreadPoolExecutor(max_workers=8) as ex:
        futures = {
            "fleet": ex.submit(collect_fleet),
            "board": ex.submit(collect_board),
            "cockpit_office": ex.submit(collect_cockpit_office),
            "calendar": ex.submit(collect_calendar_next24h),
            "git": ex.submit(collect_git_activity),
            "upstream": ex.submit(collect_upstream),
            "channels": ex.submit(collect_channels),
            "events": ex.submit(collect_recent_log_events),
        }
        out = {k: f.result() for k, f in futures.items()}
    out["config"] = config
    return out


def write_dashboard() -> Path:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    data = collect_all()
    html_text = render(data)
    OUT.write_text(html_text)
    return OUT


class _Handler(http.server.SimpleHTTPRequestHandler):
    def log_message(self, *_args, **_kwargs):
        pass

    def do_GET(self):
        # Do NOT regenerate on every GET — background thread handles refresh
        # every 30s. Regen takes ~4s (parallel probes) and stalls the iframe.
        if self.path in ("/", "/index.html", "/dashboard.html"):
            self.path = "/work/dashboard.html"
        return super().do_GET()


def serve():
    os.chdir(REPO)
    write_dashboard()

    def regen_loop():
        while True:
            time.sleep(REFRESH_EVERY_S)
            try:
                write_dashboard()
            except Exception as e:
                print(f"[regen error] {e}", file=sys.stderr)

    threading.Thread(target=regen_loop, daemon=True).start()
    with socketserver.TCPServer(("0.0.0.0", SERVE_PORT), _Handler) as httpd:
        print(f"Bridge Dashboard serving http://0.0.0.0:{SERVE_PORT}/")
        print(f"  regenerating every {REFRESH_EVERY_S}s · Ctrl-C to stop")
        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            print("\nBye.")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--open", action="store_true", help="open in default browser")
    ap.add_argument("--serve", action="store_true", help=f"serve on :{SERVE_PORT} and regen every {REFRESH_EVERY_S}s")
    args = ap.parse_args()
    if args.serve:
        serve()
        return
    out = write_dashboard()
    print(f"Wrote {out}")
    if args.open:
        subprocess.run(["open", str(out)])


if __name__ == "__main__":
    main()
