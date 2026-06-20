#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""render_dashboard.py — turn dashboard JSON into a styled view (HTML or terminal).

The deterministic render half of /dashboard. Consumes the SAME JSON schema that
fetch-project-tasks.sh (GitHub projects) and fetch_board.py (local work board)
emit, so one renderer serves every data source — for BOTH the terminal text view
(`--terminal`, default) and the single-file HTML view (`--html`). The LLM never
hand-writes either.

Input JSON (stdin or path arg):
  {
    "title":     "Customer-A Dashboard",         # optional, derived if absent
    "badge":     "live" | "local",               # optional
    "timestamp": "2026-05-24T23:15:00Z",         # optional, now() if absent
    "projects": [
      {
        "number": 18 | null,
        "name":   "Customer-A",
        "items":  [ {id, title, status, priority?, assignee?, type?, url?}, ... ],
        "stats":  { total, in_progress, in_review?, ready?, new?, backlog? },  # optional
        "repos":  [ {short_name, branch, sparkline_values:[..7..], commit_count, last_commit_time?} ],  # optional
        "deployments": [ {name, status:"ok"|"error"|"pending", time?} ]        # optional
      }
    ]
  }

Usage:
  render_dashboard.py [data.json] --html [--out PATH] [--no-open] [--title T] [--badge B]
  render_dashboard.py [data.json] --terminal        # default when neither flag given
  cat data.json | render_dashboard.py
"""
from __future__ import annotations

import argparse
import datetime as _dt
import html
import json
import os
import re
import shutil
import subprocess
import sys

TEMPLATE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "assets", "dashboard-template.html")

_WARNED_STATUS: set[str] = set()

# ── status text → CSS data-status (also used by terminal view) ───────────────
def status_class(text: str) -> str:
    # strip emoji / non-ASCII so a stray prefix can't defeat matching (portable,
    # avoids depending on jq PCRE in the fetcher)
    t = re.sub(r"[^\x00-\x7F]+", "", text or "").lower().strip()
    if "progress" in t or "doing" in t:        return "in-progress"
    if "review" in t:                          return "review"
    if "ready" in t:                           return "ready"
    if t == "new" or t.endswith(" new") or t.startswith("new "): return "new"
    if "waiting" in t or "block" in t:         return "blocked"
    if "backlog" in t:                         return "backlog"
    if t and text not in _WARNED_STATUS:
        _WARNED_STATUS.add(text)
        print(f"render_dashboard: unrecognized status {text!r} → backlog", file=sys.stderr)
    return "backlog"  # neutral default — never mis-flag unknowns as actively worked

_SORT = {"in-progress": 0, "review": 1, "ready": 2, "new": 3, "blocked": 4, "backlog": 5}

def esc(s) -> str:
    return html.escape(str(s if s is not None else ""))

def _first_name(assignee) -> str:
    if not assignee:
        return ""
    if isinstance(assignee, dict):
        assignee = assignee.get("login") or assignee.get("name") or ""
    return str(assignee).split()[0] if assignee else ""

def _rel_time(iso: str) -> str:
    if not iso:
        return ""
    try:
        ts = _dt.datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso
    now = _dt.datetime.now(ts.tzinfo) if ts.tzinfo else _dt.datetime.now()
    mins = int((now - ts).total_seconds() // 60)
    if mins < 1:   return "gerade eben"
    if mins < 60:  return f"vor {mins}min"
    hrs = mins // 60
    if hrs < 24:   return f"vor {hrs}h"
    days = hrs // 24
    if days < 7:   return f"vor {days}d"
    return ts.strftime("%d.%m.")

# ════════════════════════════════════════════════════════════════════════════
# HTML view
# ════════════════════════════════════════════════════════════════════════════
def task_row(item: dict) -> str:
    cls = status_class(item.get("status", ""))
    tid = esc(item.get("id", ""))
    url = item.get("url")
    id_html = f'<a href="{esc(url)}">{tid}</a>' if url else tid
    title = esc(item.get("title", "(no title)"))
    status_label = esc(item.get("status", cls.replace("-", " ").title()))
    assignee = esc(_first_name(item.get("assignee")))
    return (f'<div class="task" data-status="{cls}">'
            f'<span class="task-id">{id_html}</span>'
            f'<span class="task-title">{title}</span>'
            f'<span class="task-status">{status_label}</span>'
            f'<span class="task-assignee">{assignee}</span></div>')

def project_card(p: dict, visible_limit: int = 5) -> str:
    name = esc(p.get("name", "Project"))
    items = list(p.get("items", []))
    items.sort(key=lambda it: _SORT.get(status_class(it.get("status", "")), 9))

    active = [it for it in items if status_class(it.get("status", "")) != "backlog"]
    backlog = [it for it in items if status_class(it.get("status", "")) == "backlog"]
    visible = active[:visible_limit]
    hidden = active[visible_limit:] + backlog

    stats = p.get("stats", {})
    total = stats.get("total", len(items))
    in_prog = stats.get("in_progress",
                         sum(1 for it in items if status_class(it.get("status", "")) == "in-progress"))

    rows = "".join(task_row(it) for it in visible) or '<div class="no-data">Keine offenen Tasks</div>'
    toggle = ""
    if hidden:
        toggle = (f'<button class="backlog-toggle">▾ + {len(hidden)} weitere</button>'
                  f'<div class="backlog-tasks">{"".join(task_row(it) for it in hidden)}</div>')

    git_html = ""
    repos = p.get("repos", [])
    if repos:
        lines = []
        for r in repos:
            vals = ",".join(str(int(v)) for v in r.get("sparkline_values", []))
            cc = r.get("commit_count", 0)
            lc = r.get("last_commit_time", "")
            tail = (f'{cc} commits (7d) · <span data-timestamp="{esc(lc)}">{esc(lc)}</span>'
                    if lc else f'{cc} commits (7d)')
            lines.append(
                '<div class="repo-sparkline">'
                f'<span class="repo-name">{esc(r.get("short_name", "repo"))}</span>'
                f'<span class="branch">{esc(r.get("branch", ""))}</span>'
                f'<svg class="sparkline" data-values="{vals}"></svg>'
                f'<span class="commit-count">{tail}</span></div>')
        git_html = ('<div class="card-section"><div class="section-label">Git Activity</div>'
                    f'<div class="git-activity">{"".join(lines)}</div></div>')

    dep_html = ""
    deps = p.get("deployments", [])
    if deps:
        lines = []
        for d in deps:
            st = (d.get("status") or "pending").lower()
            cls = {"ok": "deploy-ok", "healthy": "deploy-ok",
                   "error": "deploy-error", "unhealthy": "deploy-error"}.get(st, "deploy-pending")
            label = {"deploy-ok": "OK", "deploy-error": "ERROR"}.get(cls, "PENDING")
            t = d.get("time", "")
            tspan = f'<span class="deploy-time" data-timestamp="{esc(t)}">{esc(t)}</span>' if t else "<span></span>"
            lines.append(f'<div class="deploy-item {cls}"><span class="deploy-name">{esc(d.get("name",""))}</span>'
                         f'<span class="deploy-status">{label}</span>{tspan}</div>')
        dep_html = ('<div class="card-section"><div class="section-label">Deployments</div>'
                    f'<div class="deployments">{"".join(lines)}</div></div>')

    return (f'<section class="project-card" data-project="{esc(name.lower())}">'
            f'<div class="card-header"><h2>{name}</h2>'
            f'<div class="card-stats"><span class="stat-highlight">{in_prog}</span> in progress | {total} open</div></div>'
            f'<div class="card-section"><div class="section-label">Tasks</div>'
            f'<div class="tasks">{rows}{toggle}</div></div>'
            f'{git_html}{dep_html}</section>')

def summary_bar(projects: list) -> str:
    total_open = sum(p.get("stats", {}).get("total", len(p.get("items", []))) for p in projects)
    total_ip = sum(p.get("stats", {}).get("in_progress",
                   sum(1 for it in p.get("items", []) if status_class(it.get("status", "")) == "in-progress"))
                   for p in projects)
    total_commits = sum(r.get("commit_count", 0) for p in projects for r in p.get("repos", []))

    def stat(v, label):
        return f'<div class="summary-stat"><span class="summary-value">{v}</span><span class="summary-label">{label}</span></div>'

    div = '<div class="summary-divider"></div>'
    parts = [stat(total_open, "Open"), stat(total_ip, "In Progress")]
    if len(projects) > 1:
        parts.append(stat(len(projects), "Projects"))
    if total_commits:
        parts.append(stat(total_commits, "Commits 7d"))
    return div.join(parts)

def render_html(projects: list, title: str, badge: str, ts: str, footer: str) -> str:
    if not os.path.exists(TEMPLATE):
        sys.exit(f"render_dashboard: template not found at {os.path.abspath(TEMPLATE)} "
                 f"(expected skills/dashboard/assets/dashboard-template.html)")
    with open(TEMPLATE, encoding="utf-8") as f:
        tpl = f.read()
    single = len(projects) == 1
    repl = {
        "TITLE": esc(title), "BADGE": esc(badge), "TIMESTAMP": esc(ts), "FOOTER": esc(footer),
        "SUMMARY_HTML": summary_bar(projects),
        "PROJECTS_HTML": "\n".join(project_card(p, 5 if single else 3) for p in projects),
    }
    # Single pass over the ORIGINAL template — substituted content (which may itself
    # contain a literal "{{...}}" from a task title) is never re-scanned/expanded.
    return re.sub(r"\{\{(\w+)\}\}", lambda m: repl.get(m.group(1), m.group(0)), tpl)

# ════════════════════════════════════════════════════════════════════════════
# Terminal view (76-char layout per references/terminal-rendering.md)
# ════════════════════════════════════════════════════════════════════════════
W = 76
_BLOCKS = "▁▂▃▄▅▆▇█"
_TERM_LABEL = {"in-progress": "In Progress", "review": "In Review", "ready": "Ready",
               "new": "New", "blocked": "Waiting", "backlog": "Backlog"}

def _trunc(s: str, n: int) -> str:
    s = s or ""
    return s if len(s) <= n else s[:n - 2] + ".."

def _divider(title: str, count=None) -> str:
    head = f"── {title}" + (f" ({count})" if count is not None else "") + " "
    return head + "─" * max(0, W - len(head))

def _spark(vals: list) -> str:
    if not vals:
        return ""
    mx = max(vals + [1])
    return "".join(_BLOCKS[min(7, round(v / mx * 7))] for v in vals)

def _focus_box(line1: str, line2: str) -> list:
    out = ["╭" + "─" * (W - 2) + "╮"]
    for ln in (line1, line2):
        out.append("│  " + _trunc(ln, W - 6).ljust(W - 6) + "  │")
    out.append("╰" + "─" * (W - 2) + "╯")
    return out

def _task_line(it: dict) -> str:
    cls = status_class(it.get("status", ""))
    tid = _trunc(str(it.get("id", "")), 22).ljust(22)
    title = _trunc(it.get("title", ""), 40).ljust(40)
    status = _TERM_LABEL.get(cls, cls).ljust(12)
    who = _first_name(it.get("assignee")) or it.get("assignee") or ""
    return f"  {tid}  {title}  {status}  {who}"

def render_terminal(projects: list, title: str, single: bool) -> str:
    out: list[str] = [title, ""]
    if single:
        p = projects[0]
        items = sorted(p.get("items", []), key=lambda it: _SORT.get(status_class(it.get("status", "")), 9))
        repos = p.get("repos", [])
        focus = next((it["title"] for it in items if status_class(it.get("status", "")) == "in-progress"), None)
        if not focus and repos:
            focus = f'{repos[0].get("commit_count", 0)} commits letzte 7 Tage'
        line2 = ""
        if repos:
            r = repos[0]
            line2 = f'Letzter Commit {_rel_time(r.get("last_commit_time", ""))} auf {r.get("branch", "")}'.strip()
        out += _focus_box(focus or p.get("name", ""), line2)
        out.append("")
        active = [it for it in items if status_class(it.get("status", "")) != "backlog"]
        backlog = [it for it in items if status_class(it.get("status", "")) == "backlog"]
        out.append(_divider("Tasks", len(items)))
        out.append("")
        for it in active[:5]:
            out.append(_task_line(it))
        rest = len(active[5:]) + len(backlog)
        if rest:
            out.append(f"       + {rest} weitere / im Backlog")
        out.append("")
        if repos:
            out.append(_divider("Git"))
            out.append("")
            for r in repos:
                out.append(f'  {_trunc(r.get("short_name", "repo"), 25).ljust(25)}  '
                           f'{_trunc(r.get("branch", ""), 18).ljust(18)}  {_spark(r.get("sparkline_values", []))}  '
                           f'{r.get("commit_count", 0)} commits (7d)')
            out.append("")
        deps = p.get("deployments", [])
        if deps:
            out.append(_divider("Deployment"))
            out.append("")
            for d in deps:
                out.append(f'  {_trunc(d.get("name", ""), 30).ljust(30)}  {(d.get("status") or "pending").upper()}'
                           + (f'   {d.get("time", "")}' if d.get("time") else ""))
            out.append("")
    else:
        n_open = sum(p.get("stats", {}).get("total", len(p.get("items", []))) for p in projects)
        n_ip = sum(p.get("stats", {}).get("in_progress",
                   sum(1 for it in p.get("items", []) if status_class(it.get("status", "")) == "in-progress"))
                   for p in projects)
        out += _focus_box(f"{len(projects)} Projekte aktiv  |  {n_open} offene Tasks  |  {n_ip} In Progress", "")
        out.append("")
        for p in projects:
            items = sorted(p.get("items", []), key=lambda it: _SORT.get(status_class(it.get("status", "")), 9))
            out.append(_divider(p.get("name", "Project"), len(items)))
            out.append("")
            for it in items[:3]:
                out.append(_task_line(it))
            if len(items) > 3:
                out.append(f"       + {len(items) - 3} weitere")
            out.append("")
    return "\n".join(out)

# ── open the HTML file appropriately for the host terminal ───────────────────
def open_view(path: str) -> str:
    term = os.environ.get("TERM_PROGRAM", "")
    venv = "/tmp/iterm2-env/bin/python3"
    if sys.platform == "darwin" and term == "iTerm.app" and os.path.exists(venv):
        # path is passed via env (DASH_PATH), never interpolated into source — no
        # quoting/escaping risk from paths containing quotes or backslashes.
        snippet = (
            'import iterm2, json, os\n'
            'PD = os.path.expanduser("~/Library/Application Support/iTerm2/DynamicProfiles")\n'
            'os.makedirs(PD, exist_ok=True)\n'
            'async def main(connection):\n'
            '    url = "file://" + os.environ["DASH_PATH"]\n'
            '    with open(os.path.join(PD, "web-browser.json"), "w") as f:\n'
            '        json.dump({"Profiles":[{"Name":"Web Browser","Guid":"WEB-BROWSER-PROFILE-001",\n'
            '            "Custom Command":"Browser","Initial URL":url,"Dynamic Profile Parent Name":"Default"}]}, f, indent=2)\n'
            '    app = await iterm2.async_get_app(connection)\n'
            '    s = app.current_terminal_window.current_tab.current_session\n'
            '    await s.async_split_pane(vertical=True, profile="Web Browser")\n'
            'iterm2.run_until_complete(main)\n'
        )
        try:
            subprocess.run([venv, "-c", snippet], check=True, timeout=15,
                           env={**os.environ, "DASH_PATH": path},
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return "iTerm2 split-pane (Web Browser profile)"
        except Exception:
            pass  # fall through to plain open
    if sys.platform == "darwin" and shutil.which("open"):
        subprocess.run(["open", path], check=False)
        return "default browser (open)"
    if shutil.which("xdg-open"):
        subprocess.run(["xdg-open", path], check=False)
        return "default browser (xdg-open)"
    return "not opened — open the file manually"

# ── main ──────────────────────────────────────────────────────────────────────
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("data", nargs="?", help="JSON file (default: stdin)")
    ap.add_argument("--html", action="store_true", help="render HTML (default: terminal)")
    ap.add_argument("--terminal", action="store_true", help="render terminal text (default)")
    ap.add_argument("--out", default=os.path.join(os.getcwd(), ".dashboard-view.html"))
    ap.add_argument("--no-open", action="store_true")
    ap.add_argument("--title")
    ap.add_argument("--badge")
    args = ap.parse_args()

    if args.data:
        with open(args.data, encoding="utf-8") as fh:
            raw = fh.read()
    else:
        raw = sys.stdin.read()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"render_dashboard: invalid JSON: {e}", file=sys.stderr)
        return 1
    if isinstance(data, dict) and data.get("error"):
        print(f"render_dashboard: upstream error: {data['error']}", file=sys.stderr)
        return 1

    projects = data.get("projects", [])
    if not projects:
        print("render_dashboard: no projects in input", file=sys.stderr)
        return 1

    single = len(projects) == 1
    title = args.title or data.get("title") or (
        f'{projects[0].get("name","Project")} Dashboard' if single else "Dashboard (Global)")
    badge = args.badge or data.get("badge") or ("local" if any(p.get("number") is None for p in projects) else "live")
    ts = data.get("timestamp") or _dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    footer = projects[0].get("name", "") if single else f'{len(projects)} Projekte'

    if args.html:
        out_html = render_html(projects, title, badge, ts, footer)
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(out_html)
        how = "" if args.no_open else open_view(args.out)
        print(f"Dashboard → {args.out}")
        if how:
            print(f"Opened in: {how}")
    else:
        print(render_terminal(projects, title, single))
    return 0

if __name__ == "__main__":
    sys.exit(main())
