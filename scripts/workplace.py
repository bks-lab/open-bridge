#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Workplace: plan the day's work as workspaces with one agent tab per task, and steer the tabs.

The plan is CORE and knows no terminal: which active task gets a tab, in which
workspace, whether its tab is already open, whether an earlier session can be
resumed, and what is blocked or resting. Everything a terminal does (list tabs,
open them, type into one, rename one) goes through a DRIVER, so the same Bridge
works with a terminal multiplexer, with another one, or with none at all.

    python3 scripts/workplace.py propose [--json]      # what /briefing shows
    python3 scripts/workplace.py open [--only A,B] [--resume]        # dry run
    python3 scripts/workplace.py open --yes            # hand the plan to the driver
    python3 scripts/workplace.py launch --items A,B [--mode report|go|context] [--target tab|workspace|area|auto] [--yes] [--json]
    python3 scripts/workplace.py status                # every tab: task, state, last line
    python3 scripts/workplace.py tasks [--json]        # every active task: area, priority, blocked, stale
    python3 scripts/workplace.py teams [--json]        # team recipes; launch --team T --role R opens one role
    python3 scripts/workplace.py send TAB TEXT...      # type into one tab
    python3 scripts/workplace.py adopt TAB SLUG        # name an existing tab after a task
    python3 scripts/workplace.py rename REF -- TITLE   # name one tab (its live ref only)
    python3 scripts/workplace.py rename-workspace WS_REF -- TITLE   # name one workspace (its live ref only)
    python3 scripts/workplace.py move-tab TAB_REF WS_REF [--index N]   # move one tab into another workspace
    python3 scripts/workplace.py workspace-color WS_REF (COLOR | --clear)   # a palette colour (COLORS)
    python3 scripts/workplace.py workspace-description WS_REF (--clear | -- TEXT)   # one line, 120 characters

CONFIG lives in bridge-config.yaml under `workplace:`:

    workplace:
      driver: none                       # or {command: ["python3", "path/to/driver.py"]}
      workspaces:                        # first match wins: a task's area:, slugs, contexts, default
        - {name: Bigcorp, contexts: [bigcorp], color: "#1565C0"}
        - {name: Platform, slugs: ["platform-*"]}
        - {name: Misc, default: true}
      limits: {max_workspaces: 4, max_tabs: 3, stale_days: 10, activity_days: 7}
      tab_names: {payments-incident: Payments}
      agent: {new: "claude -n {slug} {prompt}", resume: "claude --resume {session}"}

DRIVER PROTOCOL. A driver is a command. It gets one JSON object on stdin with a
`verb` and answers one JSON object on stdout, the shape agents/_runtime/approval.py
uses for owner approval:

    {"verb": "tabs"}                       -> {"tabs": [{"name", "workspace", "ref", "ws_ref", "state", "last",
                                                         "state_source"}]}
                                              state: working | waiting | needs-you | shell
                                              state_source (optional): hook | glyph, where the state was read;
                                              a glyph goes once a tab has a title of its own
    {"verb": "sessions"}                   -> {"sessions": {"<tab name>": "<session id>"}}
    {"verb": "open", "plan": {...}, "only": [...] | null, "resume": bool, "here": ref | null}
                                           -> {"report": ["line", ...]}
    {"verb": "launch", "tabs": [{"label", "slug", "command", "workspace", "aliases"}],
     "target": "tab" | "workspace" | "area", "here": ref | null}
                                           -> {"report": ["line", ...]}
    {"verb": "send", "tab": ref, "text": "..."}       -> {"report": [...]}
    {"verb": "rename", "tab": ref, "title": "..."}    -> {"report": [...]}
  optional, a driver names the ones it serves in caps (without an answer: the six above):
    {"verb": "control", "control": {...}, "command": "...", "root": "..."} -> {"report": [...]}
    {"verb": "caps"}                                  -> {"caps": ["tabs", "sessions", ...]}
    {"verb": "focus", "tab": ref}                     -> {"report": [...]}
    {"verb": "key", "tab": ref, "key": "enter" | "escape" | "y" | "n" | "1".."9"} -> {"report": [...]}
    {"verb": "screen", "tab": ref, "lines": n}        -> {"text": "..."}
    {"verb": "close", "tab": ref}                     -> {"report": [...]}
    {"verb": "workspaces"}                            -> {"workspaces": [{"ref", "title", "cwd", ...}]}  (read only)
    {"verb": "rename_workspace", "workspace": ws_ref, "title": "..."} -> {"report": [...]}
    {"verb": "move_tab", "tab": ref, "workspace": ws_ref, "index": n (optional)} -> {"report": [...]}
                                              never the last tab of a workspace (an ERROR line instead)
    {"verb": "set_color", "workspace": ws_ref, "color": "<COLORS name>" | null} -> {"report": [...]}
    {"verb": "set_description", "workspace": ws_ref, "text": "..." | null}   -> {"report": [...]}
                                              null clears it

A workspace in the `workspaces` answer may carry `color` (the hex the terminal reports) and
`color_name`, the COLORS name of that hex (null for any other colour). Colours are compared by name.

A refusal is an `ERROR ...` line in the report (or a non-zero exit with {"error": ...}). Task tab
names and configured workspace names are the workplace's own (managed_names): `rename` and
`rename-workspace` refuse to take them, or to rename a configured workspace.

A driver never closes a tab or a workspace on its own, only on `close`, which a person asked for. A driver that fails or answers
nonsense is reported, never raised, and never read as "no tab is open":
`open --yes` refuses and `status` says the driver failed. Model: docs/workplace.md.
The contract lives in scripts/tests/test_workplace.py.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))
from lib.ai_services import CLAUDE_MODELS    # noqa: E402  the one list of model aliases
ACTIVE = ("doing", "review")
PRIORITY_BONUS = {"P0": 3, "P1": 2, "P2": 1}
ROW_CAP = 10            # a slug named in every log row must not drown the rest
LABEL_MAX = 30
DRIVER_TIMEOUT_SEC = 120
# A router answers within seconds; a hanging one must not hold a dashboard click past its own
# timeout (the click would report a failure while tabs still open, and a second click doubles them).
ROUTER_TIMEOUT_SEC = 45
DEFAULT_LIMITS = {"max_workspaces": 4, "max_tabs": 3, "stale_days": 10, "activity_days": 7}
# Every agent tab carries its slug in this variable, so the session can tell it was opened for one item.
TAB_ENV = "BRIDGE_TAB_SLUG"
DEFAULT_AGENT = {"new": "claude -n {slug} {prompt}", "resume": "claude --resume {session}"}
# What a launch may ask of the agent besides its prompt: claude --model and --effort.
EFFORTS = ("low", "medium", "high", "xhigh")
TASK_READ_PROMPT = (
    "You are the tab for the task {slug}. Get a short overview: read {status_path}, the rows about "
    "{slug} in work/log.md (grep) and its recent commits (git log --oneline -5 -- {task_dir}), and the "
    "open inbox items for it (python3 scripts/inbox.py list). Then print at most eight lines: state, open "
    "points, next step, and whether you could take it without asking.")
# What a tab achieves reaches anyone else (a briefing, any UI or script that reads the inbox) only through the inbox.
FILE_TAIL = (
    " When you reach a result, a question only the person can answer, or a draft, file it once: "
    "python3 scripts/inbox.py add --from tab:{slug} --kind <result|question|draft> --task {slug} "
    "--gate only-you --closer person --key tab-{slug}-<short-topic> --summary '<one line>' "
    "--detail '<what, and where it is>'.")
NEW_TAB_PROMPT = (
    TASK_READ_PROMPT + " Then wait; on 'go on' take the "
    "next step." + FILE_TAIL + " Never close a tab or a workspace.")
GO_TAIL = ("Then start on the next step right away. Before anything that leaves this machine (a push, "
           "a message, a board write) ask first, unless the item itself says the click released exactly that step.")
# An item that is already done or overtaken needs no person: a tab that asks "close it?" there only adds
# a round trip (live 2026-10-21), and a close is one reopen away from undone.
INBOX_OVERTAKEN = (
    " If the item is already done, overtaken, or answered by facts you can check yourself, note the finding "
    "with its sources and close it without asking: python3 scripts/inbox.py close {id} --note '<what settled "
    "it>'. The person undoes that with python3 scripts/inbox.py reopen {id}.")
INBOX_REPORT_PROMPT = (
    "You are the tab for inbox item {id}. Read it with python3 scripts/inbox.py show {id} and the task it "
    "names, if any. Then print at most eight lines: what it is, what would settle it, and whether you "
    "could do that without asking. Note what you found on the item with python3 scripts/inbox.py note {id} "
    "'<finding>'." + INBOX_OVERTAKEN + " Otherwise change nothing; wait, and on 'go on' take the next step. "
    "Never close a tab or a workspace.")
INBOX_GO_PROMPT = (
    "You are the tab for inbox item {id}. Read it with python3 scripts/inbox.py show {id} and the task it "
    "names, if any. " + GO_TAIL + " Whenever you stop to ask or to show a draft, first put the question or "
    "the draft on the item with python3 scripts/inbox.py note {id} '<text>': the cockpit sees the item, not "
    "this chat. When it is settled, close the item with python3 scripts/inbox.py close "
    "{id} --note '<what settled it>'." + INBOX_OVERTAKEN + " Local follow-ups that only write down what is "
    "already decided (a plan, STATUS.md, the log) make yourself and name them in the close note. Ask only for "
    "a decision that is still the person's, for anything that leaves this machine, or for what cannot be "
    "undone. The click that started you releases the close even when the item says gate: only-you or "
    "closer: person, as long as you decide nothing new. Never close a tab or a workspace.")
CONTEXT_PROMPT = (
    "You are the tab that finds the missing context for {what}. Read it first ({read}). Then search for "
    "what a person picking it up would need and cannot see there: its rows in work/log.md (grep), related "
    "open inbox items (python3 scripts/inbox.py list), commits, issues or PRs it names, mails, meeting "
    "notes and transcripts under work/ and the wiki where it points. Keep only facts with their source "
    "(path, link or date). Show them here in at most twelve lines, then write the essentials back with "
    "{write} '<facts with sources>' (one call, short). Change nothing else, send nothing. Never close a "
    "tab or a workspace.")
INBOX_LABEL_MAX = 30

# A team is a small, ordered group of role tabs on one task. Each role starts on its own,
# when the person asks for it; roles hand over through <task dir>/team.md. ASCII briefs:
# cmux re-encodes non-ASCII. `team_names` in the config renames teams and roles for display,
# `teams` adds or replaces whole teams.
TEAM_PROMPT = (
    "You are the {role} tab of a small team on the task {slug} (roles in order: {roles}). Read "
    "{status_path} and the handoffs in {task_dir}/team.md (no file means you are first). Your part: "
    "{brief}{tail} When your part is done, append a handoff to {task_dir}/team.md: date, your role, what you "
    "did, what the next role needs. Before anything that leaves this machine (a push, a message, a board "
    "write) ask first." + FILE_TAIL + " Then wait. Never close a tab or a workspace.")
# A role's mode shapes its start: go starts on its part, report reports first and waits.
TEAM_MODE_TAIL = {
    "go": " Start on your part right away.",
    "report": " Report what you find here in at most eight lines; change nothing on your own.",
}
DEFAULT_TEAMS = {
    "build": {"label": "Build", "for_types": ["feature", "bug", "refactor"], "roles": [
        {"id": "implement", "name": "Implement", "mode": "go",
         "brief": "take the next step of the task: test first where the repo has tests, commit on a branch."},
        {"id": "review", "name": "Review", "mode": "report",
         "brief": "review what the implement role changed (its handoff, git log and diff): correctness, "
                  "tests, leftovers. Report findings; change nothing yourself."}]},
    "tdd": {"label": "TDD", "for_types": [], "roles": [
        {"id": "tests", "name": "Tests", "mode": "go",
         "brief": "write failing tests for the acceptance criteria of the next step and commit them red."},
        {"id": "implement", "name": "Implement", "mode": "go",
         "brief": "make the red tests green with the smallest change and commit."},
        {"id": "review", "name": "Review", "mode": "report",
         "brief": "review tests and implementation: do the tests prove the criteria, is the change minimal. "
                  "Report findings; change nothing yourself."}]},
    "research": {"label": "Research", "for_types": ["research"], "roles": [
        {"id": "evidence", "name": "Evidence", "mode": "go",
         "brief": "collect the facts and sources the question needs, each with its link or path."},
        {"id": "counter", "name": "Counter", "mode": "go",
         "brief": "look for the strongest counter-evidence, risks and open gaps in what evidence found."},
        {"id": "summary", "name": "Summary", "mode": "report",
         "brief": "weigh both into a short recommendation with sources and what is still unknown."}]},
    "reply": {"label": "Reply", "for_types": ["customer-comm"], "roles": [
        {"id": "context", "name": "Context", "mode": "go",
         "brief": "read the whole history (mails, wiki, log, issues) and list the facts the answer needs."},
        {"id": "draft", "name": "Draft", "mode": "go",
         "brief": "write the reply as a draft only and show it here. Never send anything."}]},
    "ops": {"label": "Ops", "for_types": ["infra", "ops"], "roles": [
        {"id": "diagnose", "name": "Diagnose", "mode": "report",
         "brief": "diagnose read-only against the live source: state, logs, cause, proposed fix. Change nothing."},
        {"id": "fix", "name": "Fix", "mode": "go",
         "brief": "apply the fix the diagnosis proposed after asking once, then verify against the live source."}]},
}


# ---------------------------------------------------------------- tasks

def frontmatter(text: str) -> dict:
    parts = re.split(r"^---\s*$", text, maxsplit=2, flags=re.M)
    if len(parts) < 3:
        return {}
    try:
        return yaml.safe_load(parts[1]) or {}
    except yaml.YAMLError:
        return {}


def _date(value) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def heading(text: str) -> str:
    parts = re.split(r"^---\s*$", text, maxsplit=2, flags=re.M)
    body = parts[2] if len(parts) == 3 else text
    match = re.search(r"^# (.+)$", body, flags=re.M)
    return match.group(1).strip() if match else ""


def tab_label(task: dict, cfg: dict) -> str:
    override = (cfg.get("tab_names") or {}).get(task["slug"])
    if override:
        return override
    text = re.split(r" [—–] | \(", task.get("heading") or "")[0].strip()
    if not text:
        return task["slug"]
    if len(text) <= LABEL_MAX:
        return text
    return text[:LABEL_MAX].rsplit(" ", 1)[0].rstrip(",:;") + "…"


def collect_tasks(root: Path) -> list:
    tasks = []
    for kind in ("tasks", "streams"):
        for status in sorted((root / "work" / kind).glob("*/STATUS.md")):
            if status.parent.name.startswith("_"):
                continue
            text = status.read_text(encoding="utf-8")
            fm = frontmatter(text)
            if fm.get("status") not in ACTIVE:
                continue
            tasks.append({
                "slug": fm.get("slug") or status.parent.name, "kind": kind, "status": fm.get("status"),
                "context": fm.get("context"), "area": fm.get("area"), "priority": fm.get("priority"), "type": fm.get("type"),
                "blocked_by": fm.get("blocked_by"), "updated": _date(fm.get("last_updated")), "next": fm.get("next"),
                "status_path": str(status.relative_to(root)), "heading": heading(text),
                "origin": fm.get("origin") if isinstance(fm.get("origin"), str) else None,
            })
    return tasks


def workspace_for(task: dict, cfg: dict) -> dict:
    spaces = cfg.get("workspaces") or []
    # an `area:` in the STATUS.md head names the workspace outright, by name or alias, whatever its case;
    # one that names no workspace is ignored and the rules decide
    want = str(task.get("area") or "").strip().casefold()
    if want:
        for ws in spaces:
            if want in [str(n).casefold() for n in [ws.get("name"), *(ws.get("aliases") or [])] if n]:
                return ws
    for ws in spaces:
        if any(fnmatch.fnmatch(task["slug"], p) for p in ws.get("slugs") or []):
            return ws
    for ws in spaces:
        if task.get("context") and task["context"] in (ws.get("contexts") or []):
            return ws
    return next((ws for ws in spaces if ws.get("default")), {"name": "Work"})


ROW_RE = re.compile(r"^\|\s*(\d{4}-\d{2}-\d{2})[ T]\d{2}:\d{2}\s*\|(.*)$")


def log_mentions(log_text: str, slugs: list, today: dt.date, days: int) -> dict:
    since = today - dt.timedelta(days=days)
    pats = {s: re.compile(rf"(?<![\w-]){re.escape(s)}(?![\w-])") for s in slugs}
    out: dict = {}
    for line in log_text.splitlines():
        match = ROW_RE.match(line)
        day = _date(match.group(1)) if match else None
        if not match or not day or day < since:
            continue
        for slug, pat in pats.items():
            if pat.search(match.group(2)):
                entry = out.setdefault(slug, {"rows": 0, "last": day})
                entry["rows"] += 1
                entry["last"] = max(entry["last"], day)
    return out


def _score(task: dict, mention: dict | None, today: dt.date) -> tuple:
    last = max(d for d in (task.get("updated"), (mention or {}).get("last"), dt.date.min) if d)
    age = (today - last).days
    recency = 3 if age <= 1 else 1 if age <= 3 else 0
    rows = min((mention or {}).get("rows", 0), ROW_CAP)
    return rows + recency + PRIORITY_BONUS.get(task.get("priority") or "", 0), age


def agent_run(template: str, model: str | None = None, effort: str | None = None, **fields: str) -> tuple[str, dict]:
    """The agent's command from its template, with the model and effort of this launch.

    A template may hold {model} and {effort}; an empty one goes with its flag. Without the slot the
    flag is appended, but only to a claude command, and never beside a flag the template fixes
    itself (the template wins). Returns the command and what was applied: {model, effort, pick_note}."""
    values = {"model": CLAUDE_MODELS.get(model, model) if model else None, "effort": effort}
    words = shlex.split(template.split("{")[0]) or [""]
    applied: dict = {}
    tail, notes = [], []
    for name, value in values.items():
        slot = "{" + name + "}"
        if slot in template:
            if value is None:
                template = re.sub(rf"\s*--{name}[ =]\{{{name}\}}", "", template).replace(slot, "")
            applied[name] = value
        elif value is None:
            continue
        elif re.search(rf"(^|\s)--{name}([ =]|$)", template):
            applied[name] = None
            notes.append(f"{name} fixed by the agent template")
        elif Path(words[0]).name != "claude":
            applied[name] = None
            notes.append(f"{name} not applied: the agent is not claude")
        else:
            tail.append(f"--{name} {shlex.quote(value)}")
            applied[name] = value
    run = template.format(**fields, **{k: shlex.quote(v) for k, v in values.items() if v})
    if notes:
        applied["pick_note"] = "; ".join(notes)
    return " ".join([run, *tail]), applied


def agent_defaults(agent: dict) -> tuple[str | None, str | None]:
    """agent.model and agent.effort: what a launch that asks for none starts with (a bad value counts as none)."""
    model, effort = agent.get("model"), agent.get("effort")
    return (model if model in CLAUDE_MODELS else None), (effort if effort in EFFORTS else None)


def tab_command(tab: dict, root: Path, cwd: str, cfg: dict) -> str:
    agent = {**DEFAULT_AGENT, **(cfg.get("agent") or {})}
    model, effort = agent_defaults(agent)
    if tab["action"] == "resume":
        run, _ = agent_run(agent["resume"], model, effort, session=shlex.quote(tab["session_id"]),
                           slug=shlex.quote(tab["slug"]))
    else:
        status_path = tab.get("status_path") or ""
        prompt = NEW_TAB_PROMPT.format(slug=tab["slug"], status_path=status_path,
                                       task_dir=str(Path(status_path).parent))
        run, _ = agent_run(agent["new"], model, effort, slug=shlex.quote(tab["slug"]), prompt=shlex.quote(prompt))
    return f"cd -- {shlex.quote(cwd)} && export {TAB_ENV}={shlex.quote(tab['slug'])} && {run}"


# ---------------------------------------------------------------- launch

def teams(cfg: dict) -> list:
    """The teams this Bridge offers: the defaults, replaced or added to by `teams`, named by `team_names`."""
    names = cfg.get("team_names") or {}
    out = []
    for tid, team in {**DEFAULT_TEAMS, **(cfg.get("teams") or {})}.items():
        roles = [{"id": r["id"], "name": names.get(r["id"]) or r.get("name") or r["id"],
                  "mode": r.get("mode") if r.get("mode") in ("report", "go") else "go",
                  "brief": r.get("brief") or ""}
                 for r in team.get("roles") or [] if r.get("id")]
        out.append({"id": tid, "label": names.get(tid) or team.get("label") or tid,
                    "for_types": list(team.get("for_types") or []), "roles": roles})
    return out


def team_tab_names(task_label: str, slug: str, team: dict, role: dict) -> tuple[str, str]:
    """Label and session slug of one role tab. Both carry the team: two teams share role names
    (build and tdd both have implement and review), and status must tell them apart."""
    return f"{task_label} · {team['label']} {role['name']}", f"{slug}--{team['id']}-{role['id']}"


START_NOTE_HEAD = ("The person gave you a sentence for this start: it is the newest note that begins with "
                   "'Start note:' on this item ({where}). Read it before anything else; it comes before everything else "
                   "below when the two disagree. ")


def launch_prompt(kind: str, mode: str, item: str, status_path: str = "", start_note: bool = False) -> str:
    """ASCII-only prompt for one launched tab (cmux re-encodes non-ASCII; the agent reads details itself).
    start_note: the person wrote a sentence for this start onto the item (task.py / inbox.py note, UTF-8);
    the prompt only points at it, so the words reach the agent unchanged."""
    if start_note:
        where = status_path if kind == "task" else f"python3 scripts/inbox.py show {item}"
        return START_NOTE_HEAD.format(where=where) + launch_prompt(kind, mode, item, status_path)
    if mode == "context":
        if kind == "task":
            return CONTEXT_PROMPT.format(what=f"the task {item}", read=status_path,
                                         write=f"python3 scripts/task.py note {item}")
        return CONTEXT_PROMPT.format(what=f"inbox item {item}", read=f"python3 scripts/inbox.py show {item}",
                                     write=f"python3 scripts/inbox.py note {item}")
    if kind == "task":
        read = TASK_READ_PROMPT.format(slug=item, status_path=status_path,
                                       task_dir=str(Path(status_path).parent))
        if mode == "go":
            return f"{read} {GO_TAIL}{FILE_TAIL.format(slug=item)} Never close a tab or a workspace."
        return NEW_TAB_PROMPT.format(slug=item, status_path=status_path,
                                     task_dir=str(Path(status_path).parent))
    return (INBOX_GO_PROMPT if mode == "go" else INBOX_REPORT_PROMPT).format(id=item)


def _inbox_words(item_id: str) -> tuple[str, str]:
    parts = item_id.split("-")
    has_hash = len(parts) > 3 and re.fullmatch(r"[0-9a-f]{4}", parts[-1])
    words = parts[2:-1] if has_hash else parts[2:]
    return re.sub(r"[^a-z0-9-]+", "-", "-".join(words).lower()).strip("-"), parts[-1] if has_hash else ""


def inbox_slug(item_id: str) -> str:
    """The words of an inbox id plus its hash, ASCII, at most INBOX_LABEL_MAX.

    The hash stays: two findings of the same kind (two alerts from the same vendor a day apart)
    share their first thirty characters, and a tab must name exactly one of them.
    """
    text, tail = _inbox_words(item_id)
    if not tail:
        return text[:INBOX_LABEL_MAX].rstrip("-") or "item"
    return f"{text[:INBOX_LABEL_MAX - len(tail) - 1].rstrip('-') or 'item'}-{tail}"


def _legacy_inbox_slug(item_id: str) -> str:
    """The name tabs got before the hash was kept; still read so running tabs stay matched."""
    return _inbox_words(item_id)[0][:INBOX_LABEL_MAX].rstrip("-") or "item"


def _inbox_module():
    import importlib.util
    spec = importlib.util.spec_from_file_location("bridge_inbox", ROOT / "scripts" / "inbox.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault("bridge_inbox", mod)
    spec.loader.exec_module(mod)
    return mod


def _open_inbox_item(root: Path, name: str) -> tuple | None:
    """(full id, linked task or None, area or None) of an open inbox item, or None when there is none (closed,
    dropped, unknown)."""
    box_dir = root / "work" / "inbox"
    if not box_dir.is_dir():
        return None
    mod = _inbox_module()
    box = mod.Inbox(box_dir, actor="workplace")
    try:
        item = box.get(box.resolve(name))
    except (KeyError, ValueError, OSError, yaml.YAMLError):
        return None
    return (item.id, item.task, item.area) if item.state in mod.ACTIVE_STATES else None


INBOX_INDEX_CACHE = Path(".bridge") / "cache" / "workplace-inbox-index.json"
INBOX_INDEX_CACHE_VERSION = 1


def _inbox_entry_key(item_dir: Path) -> list | None:
    """What changes when an item does: its item.yaml and its events folder (events are only ever added)."""
    try:
        events = (item_dir / "events").stat().st_mtime_ns if (item_dir / "events").is_dir() else 0
        return [(item_dir / "item.yaml").stat().st_mtime_ns, events]
    except OSError:
        return None


def _read_inbox_index_cache(path: Path) -> dict:
    """The cached entries by item id; a missing, broken or foreign file is an empty cache."""
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    items = data.get("items") if isinstance(data, dict) and data.get("version") == INBOX_INDEX_CACHE_VERSION else None
    if not isinstance(items, dict):
        return {}
    return {k: v for k, v in items.items()
            if isinstance(v, dict) and isinstance(v.get("key"), list) and isinstance(v.get("state"), str)}


def _write_inbox_index_cache(path: Path, entries: dict) -> None:
    tmp = path.with_name(f"{path.name}.{os.getpid()}.tmp")
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp.write_text(json.dumps({"version": INBOX_INDEX_CACHE_VERSION, "items": entries}), encoding="utf-8")
        os.replace(tmp, path)
    except OSError:
        tmp.unlink(missing_ok=True)   # a cache that cannot be written only costs the next call a re-read


def _inbox_index_states(root: Path, box_dir: Path, mod) -> list:
    """(id, state) of every readable item. Only items whose files changed since the cache are parsed.
    A deferral is stored as its end date, since it lapses with the calendar and not with a file."""
    cache_path = root / INBOX_INDEX_CACHE
    cached = _read_inbox_index_cache(cache_path)
    box = mod.Inbox(box_dir, actor="workplace")
    today = mod._local_date(box.clock())
    entries, rows = {}, []
    for path in sorted(box_dir.iterdir()):
        if path.name.startswith("_") or not (path.is_dir() and (path / "item.yaml").is_file()):
            continue
        key = _inbox_entry_key(path)
        if key is None:
            continue
        entry = cached.get(path.name)
        if not entry or entry["key"] != key:
            try:
                item = box.get(path.name)
            except (OSError, ValueError, yaml.YAMLError):
                continue
            # the state as if nothing were deferred, plus the deferral itself
            base = mod.Item(item.id, item.data, item.events, dt.date.max).state
            entry = {"key": key, "state": base, "deferred_until": (item.deferral or {}).get("until")}
        entries[path.name] = entry
        state = entry["state"]
        until = entry.get("deferred_until")
        if until and state not in mod.TERMINAL.values():
            try:
                if mod._local_date(mod._parse_when(until)) > today:
                    state = "deferred"
            except ValueError:
                pass
        rows.append((path.name, state))
    if entries != cached:
        _write_inbox_index_cache(cache_path, entries)
    return rows


def inbox_tab_index(root: Path) -> dict:
    """Launch label -> id of every open inbox item, so a status row can name the item its tab works on."""
    box_dir = root / "work" / "inbox"
    if not box_dir.is_dir():
        return {}
    mod = _inbox_module()
    try:
        rows = _inbox_index_states(root, box_dir, mod)
    except (OSError, yaml.YAMLError):
        return {}
    active = [i for i, state in rows if state in mod.ACTIVE_STATES]
    settled = [i for i, state in rows if state not in mod.ACTIVE_STATES]
    # A tab shows either the launch label or, once claude names its session, the slug. A settled item
    # keeps its tab named too, so the cockpit can tell the tab is done; an open item with the same
    # label wins, since that is the one a new tab works on.
    index = {}
    for group in (settled, active):
        legacy: dict = {}
        for iid in group:
            legacy.setdefault(_legacy_inbox_slug(iid), []).append(iid)
        for short, ids in legacy.items():
            if len(ids) == 1:   # an old name that two items share names neither
                index[f"Inbox {short}"] = index[f"inbox-{short}"] = ids[0]
        for iid in group:
            short = inbox_slug(iid)
            index[f"Inbox {short}"] = index[f"inbox-{short}"] = iid
    return index


def _task_dir(root: Path, name: str) -> Path | None:
    return next((root / "work" / k / name for k in ("tasks", "streams")
                 if (root / "work" / k / name).is_dir() and not name.startswith("_")), None)


def _task_area(root: Path, slug: str, cfg: dict) -> dict:
    """The workspace workplace open would give this task."""
    task_dir = _task_dir(root, slug)
    status = task_dir / "STATUS.md" if task_dir else None
    fm = frontmatter(status.read_text(encoding="utf-8")) if status and status.is_file() else {}
    return workspace_for({"slug": slug, "context": fm.get("context"), "area": fm.get("area")}, cfg)


SESSION_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}")


def build_launch(root: Path, cfg: dict, items: list, mode: str, team: str | None = None,
                 role: str | None = None, resume: str | None = None, resume_cwd: str | None = None,
                 model: str | None = None, effort: str | None = None, start_note: bool = False) -> list:
    """One entry per requested item: label + command, or an error. Labels are unique.
    With team and role: the tab of that role of the team on each task (inbox items have no team).
    With resume (a Claude session id): the tab goes on in that session of the task, in the folder it ran in
    (resume_cwd; a session only resumes from its own project folder), with agent.resume as the command.
    model (an alias or id) and effort go to the agent as agent_run says; without them the command is today's.
    start_note: the prompt sends the agent to the person's sentence for this start (see launch_prompt)."""
    if resume is not None and not SESSION_RE.fullmatch(resume):
        return [{"item": ",".join(items), "kind": "unknown", "error": f"not a session id: {resume!r}"}]
    the_team = next((t for t in teams(cfg) if t["id"] == team), None) if team else None
    the_role = next((r for r in (the_team or {}).get("roles", []) if r["id"] == role), None)
    agent = {**DEFAULT_AGENT, **(cfg.get("agent") or {})}
    default_model, default_effort = agent_defaults(agent)
    model, effort = model or default_model, effort or default_effort
    out, used, seen = [], set(), set()
    for name in items:
        name = name.strip()
        if not name or name in seen:
            continue
        seen.add(name)
        task_dir = _task_dir(root, name)
        if team and not (the_team and the_role):
            out.append({"item": name, "kind": "unknown", "error": f"no team {team!r} with a role {role!r}"})
            continue
        if team and not task_dir:
            out.append({"item": name, "kind": "unknown", "error": f"a team works on an active task, not {name!r}"})
            continue
        env_slug = name
        if task_dir:
            status = task_dir / "STATUS.md"
            text = status.read_text(encoding="utf-8") if status.is_file() else ""
            label = tab_label({"slug": name, "heading": heading(text)}, cfg)
            kind, slug = "task", name
            area = _task_area(root, name, cfg)
            prompt = launch_prompt("task", mode, name, str(task_dir.relative_to(root) / "STATUS.md"), start_note)
            if the_team and the_role:
                status_path = str(task_dir.relative_to(root) / "STATUS.md")
                label, slug = team_tab_names(label, name, the_team, the_role)
                prompt = TEAM_PROMPT.format(
                    role=the_role["id"], slug=name, roles=", then ".join(r["id"] for r in the_team["roles"]),
                    status_path=status_path, task_dir=str(task_dir.relative_to(root)), brief=the_role["brief"],
                    tail=TEAM_MODE_TAIL[the_role["mode"]])
        else:
            item = _open_inbox_item(root, name)
            if not item:
                out.append({"item": name, "kind": "unknown", "error": f"no active task and no open inbox item {name!r}"})
                continue
            full, linked, placed = item
            short = inbox_slug(full)
            kind, slug, label = "inbox", f"inbox-{short}", f"Inbox {short}"
            name = env_slug = full
            # an item follows its task; an unlinked one goes to the area it was given (place), else to the
            # default workspace (its summary words are no area: "platform broke" must not match platform-*)
            area = (_task_area(root, linked, cfg) if linked and _task_dir(root, linked)
                    else workspace_for({"slug": "", "context": None, "area": placed}, cfg))
            prompt = launch_prompt("inbox", mode, full, start_note=start_note)
        base, n = label, 1
        while label in used:
            n += 1
            label = f"{base} {n}"
        used.add(label)
        extra = {"team": the_team["id"], "role": the_role["id"]} if the_team and the_role else {}
        if resume:
            run, picked = agent_run(agent["resume"], model, effort, session=shlex.quote(resume), slug=shlex.quote(slug))
            extra["resume"] = resume
        else:
            run, picked = agent_run(agent["new"], model, effort, slug=shlex.quote(slug), prompt=shlex.quote(prompt))
        if model or effort:
            extra.update(picked)
        cwd = resume_cwd if resume and resume_cwd else str(root)
        out.append({"item": name, "kind": kind, "label": label, "slug": slug, "workspace": area["name"],
                    "aliases": list(area.get("aliases") or []), **extra,
                    "command": f"cd -- {shlex.quote(cwd)} && export {TAB_ENV}={shlex.quote(env_slug if team else slug)} && {run}"})
    return out


# ---------------------------------------------------------------- routing (target auto)

ROUTER_PROMPT = """Place each item of work in one workspace.

Workspaces:
{areas}

Items:
{items}

Answer with a JSON array only, one object per item:
[{{"item": "<item id>", "workspace": "<a name from the list>", "own": false, "why": "<at most eight words>"}}]
"own" is true only for a large piece of work over several days that deserves a workspace of its own;
a single finding, question, fix or reply is false and goes into its area's workspace."""


def _describe(root: Path, item: str) -> str:
    """One line a router can place: the task headline (else its heading) or the inbox summary."""
    task_dir = _task_dir(root, item)
    if task_dir:
        status = task_dir / "STATUS.md"
        text = status.read_text(encoding="utf-8") if status.is_file() else ""
        fm = frontmatter(text)
        title = heading(text)
        if re.fullmatch(r"<[^>]*>", title):
            title = ""                       # the template's placeholder says nothing
        return f"task {item}: {fm.get('headline') or title or item} (context {fm.get('context') or 'none'})"
    box_dir = root / "work" / "inbox"
    try:
        found = _inbox_module().Inbox(box_dir, actor="workplace").get(item)
        return f"inbox item: {found.summary}" + (f" (task {found.task})" if found.task else "")
    except (KeyError, ValueError, OSError, yaml.YAMLError, AttributeError):
        return item


def route(root: Path, cfg: dict, entries: list) -> list:
    """Area and own-workspace per entry from the configured router (one call for all entries).

    The router is any command that reads the prompt on stdin and prints the JSON answer,
    e.g. a small model. Without one, or when it fails or names an unknown workspace, the
    configured rules stand and nothing gets its own workspace.
    """
    out = [{**e, "own": False} for e in entries]
    spaces = {ws["name"]: ws for ws in cfg.get("workspaces") or [] if ws.get("name")}
    todo = [e for e in out if "command" in e]
    if not spaces or not todo or not (cfg.get("router") or {}).get("command"):
        return out
    picks = _ask_router(cfg, ROUTER_PROMPT.format(
        areas=_area_lines(spaces), items="\n".join(f"- {e['item']}: {_describe(root, e['item'])}" for e in todo)),
        cwd=root)
    for e in todo:
        pick = picks.get(e["item"]) or {}
        ws = spaces.get(str(pick.get("workspace") or ""))
        if not ws:
            continue
        e.update({"workspace": ws["name"], "aliases": list(ws.get("aliases") or []),
                  "own": pick.get("own") is True, "why": str(pick.get("why") or "")[:80] or "no reason given"})
    return out


def _area_lines(spaces: dict) -> str:
    return "\n".join(f"- {n}: {ws.get('description') or ''}".rstrip(": ") for n, ws in spaces.items())


def _ask_router(cfg: dict, prompt: str, cwd: Path | None = None) -> dict:
    """The configured router's answer, by item id: {item: {"workspace", "why", ...}}. Empty when there is no
    router, or it fails, times out or answers no JSON array; the caller then keeps what it had."""
    command = (cfg.get("router") or {}).get("command")
    if not command:
        return {}
    argv = shlex.split(command) if isinstance(command, str) else [str(c) for c in command]
    try:
        run = subprocess.run(argv, input=prompt, capture_output=True, text=True, timeout=ROUTER_TIMEOUT_SEC,
                             cwd=str(cwd) if cwd else None)
        text = run.stdout if run.returncode == 0 else ""
        start, end = text.find("["), text.rfind("]")
        answer = json.loads(text[start:end + 1]) if 0 <= start < end else []
    except (OSError, subprocess.TimeoutExpired, ValueError):
        answer = []
    return {str(a.get("item")): a for a in answer if isinstance(a, dict)}


# ---------------------------------------------------------------- placing inbox items in an area

PLACE_PROMPT = """Give each inbox item the one area it belongs to.

Areas:
{areas}

Items:
{items}

Answer with a JSON array only, one object per item:
[{{"item": "<item id>", "workspace": "<a name from the list>", "why": "<at most eight words>"}}]
Pick the area whose description fits the item's subject; when none fits, pick the one for everything else."""


def _placeable(root: Path) -> tuple:
    """(the inbox module, the box, the open items that have neither a task nor an area)"""
    mod = _inbox_module()
    box = mod.Inbox(root / "work" / "inbox", actor="router")
    return mod, box, [i for i in box.items() if i.state in mod.ACTIVE_STATES and not i.task and not i.area]


def unplaced(root: Path) -> list:
    """The ids of every open inbox item with neither a task nor an area."""
    return [i.id for i in _placeable(root)[2]]


def place(root: Path, cfg: dict, items: list, write: bool = True) -> list:
    """Ask the router once where the given inbox items belong and write each answer as an `area` event by
    `router` ([{item, area, why}]). Items with a task or an area already, closed ones and unknown ids are
    left out; an answer naming no configured workspace is dropped, so a failing router writes nothing."""
    spaces = {ws["name"]: ws for ws in cfg.get("workspaces") or [] if ws.get("name")}
    if not spaces or not (cfg.get("router") or {}).get("command"):
        return []
    mod, box, open_items = _placeable(root)
    wanted = {box_id for box_id in (_resolve(box, name) for name in items) if box_id}
    todo = [i for i in open_items if i.id in wanted]
    if not todo:
        return []
    picks = _ask_router(cfg, PLACE_PROMPT.format(
        areas=_area_lines(spaces), items="\n".join(f"- {i.id}: {i.summary}" for i in todo)), cwd=root)
    placed = []
    for i in todo:
        pick = picks.get(i.id) or {}
        ws = spaces.get(str(pick.get("workspace") or ""))
        if not ws:
            continue
        why = str(pick.get("why") or "")[:80] or None
        if write:
            # the router took its time: a person may have set an area meanwhile, or the item closed
            try:
                now = box.get(i.id)
                if now.task or now.area or now.state not in mod.ACTIVE_STATES:
                    continue
                box.set_area(i.id, ws["name"], by="router", why=why)
            except (KeyError, ValueError, OSError):
                continue
        placed.append({"item": i.id, "area": ws["name"], "why": why})
    return placed


PLACE_LOCK = Path(".bridge") / "cache" / "inbox-place.lock"
PLACE_SETTLE_SEC = 2.0


def place_pending(root: Path, cfg: dict, settle: float = PLACE_SETTLE_SEC) -> list:
    """What `inbox.py add` starts for a new item: wait a moment so a burst of items arrives, then place every
    open item that has neither a task nor an area, one placer at a time. A second placer that finds the lock
    taken leaves: the one holding it looks again before it lets go, and asks about each item once."""
    time.sleep(settle)
    lock_path = root / PLACE_LOCK
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        import fcntl
    except ImportError:                       # no flock (Windows): one placer per item, as without a lock
        fcntl = None
    with open(lock_path, "a") as lock:
        if fcntl is not None:
            try:
                fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError:
                return []
        placed, asked = [], set()
        while todo := [i for i in unplaced(root) if i not in asked]:
            asked.update(todo)
            placed += place(root, cfg, todo)
        return placed


def _resolve(box, name: str) -> str | None:
    try:
        return box.resolve(name.strip())
    except (KeyError, ValueError):
        return None


# ---------------------------------------------------------------- the plan

def propose(tasks: list, cfg: dict, mentions: dict, sessions: dict, open_tabs: dict,
            today: dt.date, root: Path) -> dict:
    """sessions and open_tabs are keyed by slug; open_tabs values are driver tab dicts."""
    limits = {**DEFAULT_LIMITS, **(cfg.get("limits") or {})}
    blocked, stale, groups = [], [], {}
    for task in tasks:
        score, age = _score(task, mentions.get(task["slug"]), today)
        entry = {**task, "score": score, "age": age, "rows": (mentions.get(task["slug"]) or {}).get("rows", 0)}
        if task.get("blocked_by"):
            blocked.append(entry)
        elif age > limits["stale_days"] and task["slug"] not in open_tabs:
            stale.append(entry)
        else:
            ws = workspace_for(task, cfg)
            groups.setdefault(ws["name"], {"ws": ws, "tasks": []})["tasks"].append(entry)

    ranked = []
    for name, group in groups.items():
        group["tasks"].sort(key=lambda t: (-t["score"], t["age"], t["slug"]))
        top = group["tasks"][: limits["max_tabs"]]
        ranked.append((sum(t["score"] for t in top), name, group, top))
    ranked.sort(key=lambda r: (-r[0], r[1]))

    workspaces, deferred = [], []
    for i, (score, name, group, top) in enumerate(ranked):
        if i >= limits["max_workspaces"]:
            deferred += group["tasks"]
            continue
        ws = group["ws"]
        cwd = str(ws.get("cwd") or root)
        tabs = []
        for t in top:
            action = "open" if t["slug"] in open_tabs else "resume" if t["slug"] in sessions else "new"
            tab = {"slug": t["slug"], "label": tab_label(t, cfg), "action": action, "score": t["score"],
                   "rows": t["rows"], "age": t["age"], "status_path": t.get("status_path")}
            if action == "open":
                tab.update({k: open_tabs[t["slug"]].get(k) for k in ("ref", "workspace", "ws_ref")})
            else:
                if action == "resume":
                    tab["session_id"] = sessions[t["slug"]]
                tab["command"] = tab_command(tab, root, cwd, cfg)
            tabs.append(tab)
        workspaces.append({"name": name, "score": score, "tabs": tabs, "cwd": cwd,
                           **{k: ws[k] for k in ("color", "description", "aliases") if ws.get(k)}})
        deferred += group["tasks"][limits["max_tabs"]:]
    deferred.sort(key=lambda t: (-t["score"], t["slug"]))
    return {"date": today.isoformat(), "control": cfg.get("control") or {"name": "Control"},
            "workspaces": workspaces, "deferred": deferred, "blocked": blocked,
            "stale": sorted(stale, key=lambda t: -t["age"])}


def _next_what(value) -> str | None:
    """The words of a task's `next:`: the string itself, or the `what` of a mapping; None when it names none."""
    if isinstance(value, dict):
        value = value.get("what")
    text = str(value).strip() if isinstance(value, (str, int, float)) else ""
    return text or None


def task_rows(root: Path, cfg: dict, today: dt.date) -> list:
    """Every active task, flat: label, area (its workspace), priority, score, blocked_by, stale.
    The whole list, for any UI or script that drives workplace.py; propose decides which of them get a
    tab today."""
    limits = {**DEFAULT_LIMITS, **(cfg.get("limits") or {})}
    tasks = collect_tasks(root)
    log_path = root / "work" / "log.md"
    log = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    mentions = log_mentions(log, [t["slug"] for t in tasks], today, limits["activity_days"])
    rows = []
    for t in tasks:
        score, age = _score(t, mentions.get(t["slug"]), today)
        area = workspace_for(t, cfg)
        rows.append({"slug": t["slug"], "label": tab_label(t, cfg), "title": (t.get("heading") or "").strip() or t["slug"],
                     "area": area["name"],
                     "area_aliases": list(area.get("aliases") or []),
                     "priority": t.get("priority"), "type": t.get("type"), "status": t.get("status"),
                     "next": _next_what(t.get("next")),
                     "updated": t["updated"].isoformat() if t.get("updated") else None,
                     "score": score, "age": age,
                     "blocked_by": t.get("blocked_by"), "stale": age > limits["stale_days"],
                     "kind": t["kind"],
                     # how it began (STATUS.md origin, free text): the cockpit says where it comes from
                     "origin": (t.get("origin") or "")[:300] or None})
    rank = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    return sorted(rows, key=lambda r: (rank.get(r["priority"] or "", 4), -r["score"], r["slug"]))


DONE_MONTHS = 2    # how many month folders of work/done/ a tab of a closed task is still known by


def done_tasks(root: Path) -> list:
    """The tasks closed in the last DONE_MONTHS month folders of work/done/, as slug and heading"""
    months = sorted((p for p in (root / "work" / "done").glob("*") if p.is_dir()), reverse=True)[:DONE_MONTHS]
    out = []
    for month in months:
        for status in sorted(month.glob("*/STATUS.md")):
            try:
                text = status.read_text(encoding="utf-8")
            except OSError:
                continue
            out.append({"slug": frontmatter(text).get("slug") or status.parent.name, "heading": heading(text)})
    return out


def slug_index(tasks: list, cfg: dict) -> dict:
    index = {}
    for t in tasks:
        index[t["slug"]] = t["slug"]
        index.setdefault(tab_label(t, cfg), t["slug"])
    return index


def build_plan(root: Path, cfg: dict, today: dt.date, driver) -> dict:
    limits = {**DEFAULT_LIMITS, **(cfg.get("limits") or {})}
    tasks = collect_tasks(root)
    log_path = root / "work" / "log.md"
    log = log_path.read_text(encoding="utf-8") if log_path.exists() else ""
    mentions = log_mentions(log, [t["slug"] for t in tasks], today, limits["activity_days"])
    index = slug_index(tasks, cfg)
    # A driver that failed does NOT mean "no tab is open": planning on that would
    # mark every open task as new and open it a second time. The plan records the
    # failure and `open --yes` refuses to act on it.
    tab_list = driver.tabs_or_none()
    session_map = driver.sessions_or_none()
    sessions = {index[name]: sid for name, sid in (session_map or {}).items() if name in index}
    open_tabs = {index[t["name"]]: t for t in (tab_list or []) if t.get("name") in index}
    plan = propose(tasks, cfg, mentions, sessions, open_tabs, today, root)
    if tab_list is None:
        plan["driver_error"] = getattr(driver, "error", "") or f"driver {driver.name} gave no tab list"
    return plan


def render(plan: dict) -> str:
    out = [f"Workplace today ({plan['date']}), steered from “{plan['control']['name']}”", ""]
    for i, ws in enumerate(plan["workspaces"], 1):
        out.append(f"{i}. {ws['name']}")
        for t in ws["tabs"]:
            why = f"{t['rows']} log rows, last {t['age']} d ago"
            out.append(f"     {t['label']:<32} {t['action']:<7} {t['slug']:<34} {why}")
    if plan["deferred"]:
        out += ["", "No tab today: " + ", ".join(t["slug"] for t in plan["deferred"])]
    if plan["blocked"]:
        out.append("Blocked: " + ", ".join(f"{t['slug']} ({str(t['blocked_by'])[:50]})" for t in plan["blocked"]))
    if plan["stale"]:
        out.append("Resting (park?): " + ", ".join(f"{t['slug']} ({t['age']} d)" for t in plan["stale"]))
    return "\n".join(out)


def status_rows(root: Path, cfg: dict, driver) -> list | None:
    """Rows for every tab, or None when the driver could not say (never an empty "all quiet")."""
    tabs = driver.tabs_or_none()
    if tabs is None:
        return None
    tasks = collect_tasks(root)
    index = slug_index(tasks, cfg)
    # a tab of a task that moved to work/done/ keeps its slug, so the cockpit can tell it is done
    for name, slug in slug_index(done_tasks(root), cfg).items():
        index.setdefault(name, slug)
    items = inbox_tab_index(root)
    roles: dict = {}
    for t in tasks:
        for team in teams(cfg):
            for r in team["roles"]:
                # by the label it opens with, and by the session slug claude titles it with later
                for key in team_tab_names(tab_label(t, cfg), t["slug"], team, r):
                    roles.setdefault(key, (t["slug"], team["id"], r["id"]))
    order = {"needs-you": 0, "waiting": 1, "working": 2, "shell": 3}
    rows = []
    for t in tabs:
        name = t.get("name", "")
        slug, team, role = roles.get(name, (index.get(name), None, None))
        rows.append({**t, "slug": slug, "item": items.get(name), "team": team, "role": role})
    return sorted(rows, key=lambda r: (order.get(r.get("state"), 9), r.get("workspace") or ""))


def managed_names(root: Path, cfg: dict) -> dict:
    """The names the workplace gives and finds tabs and workspaces by, casefolded: a tab of a task, an
    inbox item or a team role is known by its name (status_rows), a workspace by its configured name or
    alias (the plan, the drivers). A rename must neither take one of them nor rename a configured workspace."""
    tasks = collect_tasks(root)
    tab_names = set(slug_index(tasks, cfg)) | set(slug_index(done_tasks(root), cfg)) | set(inbox_tab_index(root))
    for t in tasks:
        for team in teams(cfg):
            for r in team["roles"]:
                tab_names.update(team_tab_names(tab_label(t, cfg), t["slug"], team, r))
    spaces = set()
    for ws in cfg.get("workspaces") or []:
        if isinstance(ws, dict):
            spaces.update(str(n) for n in [ws.get("name"), *(ws.get("aliases") or [])] if n)
    spaces.add(str((cfg.get("control") or {}).get("name") or "Control"))
    return {"tab_names": {n.strip().casefold() for n in tab_names if str(n).strip()},
            "workspace_names": {n.strip().casefold() for n in spaces if n.strip()}}


TITLE_MAX = 80
TITLE_BAD = re.compile(r"[\x00-\x1f\x7f]")
DESCRIPTION_MAX = 120
INDEX_MAX = 99

# the portable workspace colours, in the terminal's order: a driver maps a name to its own colour, and a
# reported hex back to the name (cmux uses exactly these hex values for its named colours)
COLORS = {
    "Red": "#C0392B", "Crimson": "#922B21", "Orange": "#A04000", "Amber": "#7D6608",
    "Olive": "#4A5C18", "Green": "#196F3D", "Teal": "#006B6B", "Aqua": "#0E6B8C",
    "Blue": "#1565C0", "Navy": "#1A5276", "Indigo": "#283593", "Purple": "#6A1B9A",
    "Magenta": "#AD1457", "Rose": "#880E4F", "Brown": "#7B3F00", "Charcoal": "#3E4B5E",
}
_BY_HEX = {v.upper(): k for k, v in COLORS.items()}


def color_name(color) -> str | None:
    """The COLORS name of a reported hex (any case), else None"""
    return _BY_HEX.get(color.strip().upper()) if isinstance(color, str) else None


def palette_name(name) -> str | None:
    """A colour name as typed (any case) as its COLORS name, else None"""
    if not isinstance(name, str):
        return None
    return next((k for k in COLORS if k.casefold() == name.strip().casefold()), None)


def check_description(text: str) -> str:
    """A workspace description as typed: one line, trimmed, 1 to DESCRIPTION_MAX characters. Refused, never cut."""
    if TITLE_BAD.search(text or ""):
        raise ValueError("refused: control characters in the description")
    out = (text or "").strip()
    if not 1 <= len(out) <= DESCRIPTION_MAX:
        raise ValueError(f"refused: a description has 1 to {DESCRIPTION_MAX} characters")
    return out


def check_title(title: str) -> str:
    """A tab or workspace title as typed: trimmed, 1 to TITLE_MAX characters, no control character
    (no newline, no tab). Refused, never cut. Raises ValueError with the reason."""
    if TITLE_BAD.search(title or ""):
        raise ValueError("refused: control characters in the title")
    text = (title or "").strip()
    if not 1 <= len(text) <= TITLE_MAX:
        raise ValueError(f"refused: a title has 1 to {TITLE_MAX} characters")
    return text


def _ws_fold(name) -> str:
    """A workspace name as compared: casefolded, and `:` and `.` read as `_` (tmux turns them into `_`)."""
    return re.sub(r"[:.]", "_", str(name or "").strip()).casefold()


# ---------------------------------------------------------------- drivers

# the verbs every driver serves; the others it names in its answer to `caps`
BASE_CAPS = ("tabs", "sessions", "open", "launch", "send", "rename")
KEYS = ("enter", "escape", "y", "n", *(str(i) for i in range(1, 10)))


class NoneDriver:
    """No terminal integration: nothing is open, nothing can be typed into, the plan says what to start."""

    name = "none"
    error = ""

    def tabs_or_none(self):
        return self.tabs()

    def sessions_or_none(self):
        return self.sessions()

    def tabs(self) -> list:
        return []

    def sessions(self) -> dict:
        return {}

    def open(self, plan: dict, only, resume: bool, here) -> list:
        lines = ["No driver configured (workplace.driver): start these yourself, one terminal each."]
        for ws in plan["workspaces"]:
            if only and ws["name"] not in only:
                continue
            lines.append(f"{ws['name']}:")
            for t in ws["tabs"]:
                if t.get("command") and (resume or t["action"] != "resume"):
                    lines.append(f"  {t['label']}: {t['command']}")
        return lines

    def launch(self, tabs: list, target: str, here) -> list:
        lines = ["No driver configured (workplace.driver): start these yourself, one terminal each."]
        lines += [f"  {t['label']}: {t['command']}" for t in tabs]
        return lines

    def send(self, tab: str, text: str) -> list:
        return [f"No driver configured: type into {tab} yourself."]

    def rename(self, tab: str, title: str) -> list:
        return [f"No driver configured: name the tab {title!r} yourself."]

    def rename_workspace(self, workspace: str, title: str) -> list:
        return [f"No driver configured: name the workspace {title!r} yourself."]

    def move_tab(self, tab: str, workspace: str, index: int | None = None) -> list:
        return [f"No driver configured: move {tab} into {workspace} yourself."]

    def set_color(self, workspace: str, color: str | None) -> list:
        return [f"No driver configured: colour {workspace} {color or 'plain'} yourself."]

    def set_description(self, workspace: str, text: str | None) -> list:
        return [f"No driver configured: describe {workspace} yourself."]

    def control(self, ctl: dict, command: str, root) -> list:
        return [f"No driver configured: start {command!r} in a terminal named {ctl.get('name')!r} yourself."]

    def caps(self) -> list:
        return []

    def focus(self, tab: str) -> list:
        return [f"No driver configured: switch to {tab} yourself."]

    def key(self, tab: str, key: str) -> list:
        return [f"No driver configured: press {key} in {tab} yourself."]

    def screen(self, tab: str, lines: int) -> str | None:
        return None

    def workspaces(self) -> list | None:
        return None

    def close(self, tab: str) -> list:
        return [f"No driver configured: close {tab} yourself."]


class CommandDriver:
    """A driver behind a command that speaks the JSON protocol in the module docstring."""

    def __init__(self, argv: list):
        self.argv = [str(a) for a in argv]
        self.name = Path(self.argv[-1]).stem if self.argv else "command"
        self.error = ""
        self.failed = False

    def _call(self, payload: dict) -> dict | None:
        try:
            done = subprocess.run(self.argv, input=json.dumps(payload, default=str, ensure_ascii=False),
                                  capture_output=True, text=True, timeout=DRIVER_TIMEOUT_SEC)
        except (OSError, subprocess.SubprocessError) as exc:
            self.error = f"driver {self.name} failed to run: {exc}"
            return None
        if done.returncode != 0:
            self.error = f"driver {self.name} failed (exit {done.returncode}): {done.stderr.strip()[:200]}"
            return None
        try:
            lines = done.stdout.strip().splitlines()
            data = json.loads(lines[-1]) if lines else {}
        except ValueError:
            self.error = f"driver {self.name} failed: no JSON answer"
            return None
        return data if isinstance(data, dict) else None

    def tabs_or_none(self) -> list | None:
        data = self._call({"verb": "tabs"})
        tabs = (data or {}).get("tabs") if data is not None else None
        if not isinstance(tabs, list):
            if data is not None:
                self.error = f"driver {self.name} answered no tab list"
            return None
        return [t for t in tabs if isinstance(t, dict)]

    def sessions_or_none(self) -> dict | None:
        data = self._call({"verb": "sessions"})
        sessions = (data or {}).get("sessions", {}) if data is not None else None
        if not isinstance(sessions, dict):
            if data is not None:
                self.error = f"driver {self.name} answered sessions that are not a mapping"
            return None
        return sessions

    def tabs(self) -> list:
        return self.tabs_or_none() or []

    def sessions(self) -> dict:
        return self.sessions_or_none() or {}

    def _report(self, payload: dict) -> list:
        data = self._call(payload)
        if data is None:
            self.failed = True
            # an ERROR line, like a refused step: a caller must not count anything as started
            return [f"ERROR {getattr(self, 'error', f'driver {self.name} failed')}"]
        lines = [str(line) for line in data.get("report") or []]
        # A step the terminal refused is reported as an ERROR line; the run as a
        # whole then failed, and a script or workload must see that too.
        self.failed = any(line.startswith("ERROR") for line in lines)
        return lines

    def open(self, plan: dict, only, resume: bool, here) -> list:
        return self._report({"verb": "open", "plan": plan, "only": sorted(only) if only else None,
                             "resume": resume, "here": here})

    def launch(self, tabs: list, target: str, here) -> list:
        return self._report({"verb": "launch", "target": target, "here": here,
                             "tabs": [{k: t.get(k) for k in ("label", "slug", "command", "workspace", "aliases")} for t in tabs]})

    def send(self, tab: str, text: str) -> list:
        return self._report({"verb": "send", "tab": tab, "text": text})

    def rename(self, tab: str, title: str) -> list:
        return self._report({"verb": "rename", "tab": tab, "title": title})

    def rename_workspace(self, workspace: str, title: str) -> list:
        return self._report({"verb": "rename_workspace", "workspace": workspace, "title": title})

    def move_tab(self, tab: str, workspace: str, index: int | None = None) -> list:
        payload = {"verb": "move_tab", "tab": tab, "workspace": workspace}
        if index is not None:
            payload["index"] = int(index)
        return self._report(payload)

    def set_color(self, workspace: str, color: str | None) -> list:
        return self._report({"verb": "set_color", "workspace": workspace, "color": color})

    def set_description(self, workspace: str, text: str | None) -> list:
        return self._report({"verb": "set_description", "workspace": workspace, "text": text})

    def control(self, ctl: dict, command: str, root) -> list:
        return self._report({"verb": "control", "control": ctl, "command": command, "root": str(root)})

    def caps(self) -> list:
        """The verbs this driver serves; a driver that names none serves the six base verbs."""
        data = self._call({"verb": "caps"})
        caps = (data or {}).get("caps")
        if isinstance(caps, list) and all(isinstance(c, str) for c in caps):
            return caps
        return list(BASE_CAPS)

    def focus(self, tab: str) -> list:
        return self._report({"verb": "focus", "tab": tab})

    def key(self, tab: str, key: str) -> list:
        # a fixed set: a key outside it never reaches a terminal (no ctrl codes, no text through this door)
        if key not in KEYS:
            self.failed = True
            return [f"ERROR key {key!r} is not one of {', '.join(KEYS)}"]
        return self._report({"verb": "key", "tab": tab, "key": key})

    def screen(self, tab: str, lines: int) -> str | None:
        data = self._call({"verb": "screen", "tab": tab, "lines": int(lines)})
        text = (data or {}).get("text")
        if not isinstance(text, str):
            if data is not None:
                self.error = f"driver {self.name} answered no screen text"
            return None
        return text

    def close(self, tab: str) -> list:
        return self._report({"verb": "close", "tab": tab})

    def workspaces(self) -> list | None:
        """The workspaces as the terminal shows them (read only); None when the driver cannot say."""
        data = self._call({"verb": "workspaces"})
        rows = (data or {}).get("workspaces")
        if not isinstance(rows, list):
            if data is not None:
                self.error = f"driver {self.name} answered no workspaces"
            return None
        return [w for w in rows if isinstance(w, dict) and isinstance(w.get("ref"), str)]


def driver_from(spec):
    if spec in (None, "none"):
        return NoneDriver()
    if isinstance(spec, dict):
        argv = spec.get("command")
        if isinstance(argv, list) and argv and all(isinstance(a, str) for a in argv):
            return CommandDriver([a.replace("${root}", str(ROOT)) for a in argv])
    raise ValueError(f"workplace.driver must be 'none' or {{command: [argv]}}, got {spec!r}")


def open_agent_tab(entry: dict, rows: list) -> dict | None:
    """The open agent tab that already works on this entry, or None. A tab in state shell holds no
    agent (its command never ran, or the agent ended), so it does not count; a team role counts
    only for that role."""
    for r in rows:
        if r.get("state") == "shell":
            continue
        if entry["kind"] == "inbox" and r.get("item") == entry["item"]:
            return r
        if entry["kind"] == "task" and r.get("slug") == entry["item"] \
                and (r.get("team"), r.get("role")) == (entry.get("team"), entry.get("role")):
            return r
    return None


def _destination(entry: dict, target: str) -> str:
    """Where a launched tab would go, in words, for the dry run."""
    if target == "tab":
        return "this workspace"
    if target == "workspace" or (target == "auto" and entry.get("own")):
        where = "new workspace"
    else:
        where = entry.get("workspace") or "the default workspace"
    return f"{where} (router: {entry['why']})" if target == "auto" and entry.get("why") else f"{where} ({target})"


def load_cfg(root: Path) -> dict:
    path = root / "bridge-config.yaml"
    if not path.is_file():
        return {}
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    return data.get("workplace") or {}


def find_tab(tabs: list, name: str, index: dict) -> dict:
    # a caller that addresses tabs by live ref (surface:91) gets that tab; people use a name or task slug
    by_ref = [t for t in tabs if t.get("ref") == name]
    if len(by_ref) == 1:
        return by_ref[0]
    want = name.lower()
    exact = [t for t in tabs if str(t.get("name", "")).lower() == want or str(index.get(t.get("name"))) == name]
    if len(exact) == 1:
        return exact[0]
    part = [t for t in tabs if want in str(t.get("name", "")).lower()]
    if len(part) == 1:
        return part[0]
    raise LookupError(f"no single tab for {name!r} ({len(exact) or len(part)} matches)")


# ---------------------------------------------------------------- CLI

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(prog="workplace.py", description="Plan and steer the day's agent tabs.")
    ap.add_argument("--root", type=Path, default=ROOT)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("propose").add_argument("--json", action="store_true")
    pl = sub.add_parser("place", help="give inbox items without a task or an area their area (the router, one call)")
    which = pl.add_mutually_exclusive_group(required=True)
    which.add_argument("--items", help="inbox ids, comma separated")
    which.add_argument("--unplaced", action="store_true", help="every open item with neither a task nor an area")
    which.add_argument("--pending", action="store_true",
                       help="as --unplaced, after a short wait and one placer at a time (inbox.py add starts it)")
    pl.add_argument("--dry-run", action="store_true", help="show the answer, write nothing")
    pl.add_argument("--quiet", action="store_true", help="print nothing (inbox.py add starts it this way)")
    pl.add_argument("--json", action="store_true")
    op = sub.add_parser("open")
    op.add_argument("--only", help="only these workspaces, comma separated")
    op.add_argument("--yes", action="store_true", help="hand the plan to the driver (default: dry run)")
    op.add_argument("--resume", action="store_true", help="also reopen tabs of earlier sessions")
    op.add_argument("--here", help="driver ref of the calling tab, which becomes the control tab")
    ct = sub.add_parser("control", help="start a new agent tab in the control workspace (created when missing)")
    ct.add_argument("--yes", action="store_true", help="start it (default: dry run)")
    ln = sub.add_parser("launch", help="one new agent tab (or workspace) per task slug or inbox id")
    ln.add_argument("--items", required=True, help="task slugs or open inbox ids, comma separated")
    ln.add_argument("--mode", choices=("report", "go", "context"),
                    help="report (default): read and wait · go: start working · context: find what is missing "
                         "and note it. Ignored with --team: a role's mode comes from its team")
    ln.add_argument("--target", choices=("tab", "workspace", "area", "auto"), default="tab",
                    help="tab: caller's workspace; workspace: one new each; area: the workspace of the item's area; "
                         "auto: workplace.router decides area and own workspace per item")
    ln.add_argument("--here", help="driver ref of the calling tab; its workspace receives the tabs")
    ln.add_argument("--yes", action="store_true", help="hand the tabs to the driver (default: dry run)")
    ln.add_argument("--json", action="store_true")
    ln.add_argument("--team", help="a team id (workplace.py teams); with --role opens that role's tab")
    ln.add_argument("--role", help="the role of --team to open")
    ln.add_argument("--resume", metavar="SESSION", help="go on in this Claude session of the one named task")
    ln.add_argument("--cwd", help="with --resume: the folder the session ran in")
    ln.add_argument("--model", choices=tuple(CLAUDE_MODELS), help="the model the agent starts with")
    ln.add_argument("--effort", choices=EFFORTS, help="the agent's effort level")
    ln.add_argument("--start-note", action="store_true",
                    help="the person noted a sentence for this start on the item ('Start note: ...'); the agent reads it first")
    ln.add_argument("--again", action="store_true",
                    help="open a tab even when an agent tab for the item is open already")
    sub.add_parser("teams", help="the team recipes: ordered role tabs on one task").add_argument(
        "--json", action="store_true")
    sub.add_parser("status").add_argument("--json", action="store_true")
    sub.add_parser("tasks", help="every active task with area, priority and flags").add_argument(
        "--json", action="store_true")
    sd = sub.add_parser("send")
    sd.add_argument("tab")
    sd.add_argument("text", nargs="+")
    ad = sub.add_parser("adopt")
    ad.add_argument("tab")
    ad.add_argument("slug")
    rn = sub.add_parser("rename", help="name one tab, addressed by its live ref only: rename REF -- TITLE")
    rn.add_argument("ref")
    rn.add_argument("title", nargs="+")
    rw = sub.add_parser("rename-workspace", help="name one workspace, addressed by its live ref only: "
                                                  "rename-workspace WS_REF -- TITLE")
    rw.add_argument("ws_ref")
    rw.add_argument("title", nargs="+")
    mv = sub.add_parser("move-tab", help="move one tab into another workspace, both by their live refs only: "
                                          "move-tab TAB_REF WS_REF [--index N]")
    mv.add_argument("tab")
    mv.add_argument("ws_ref")
    mv.add_argument("--index", type=int, help="its place in that workspace, from 0")
    wc = sub.add_parser("workspace-color", help="colour one workspace (its live ref only): "
                                                 f"workspace-color WS_REF (COLOR | --clear), COLOR one of {', '.join(COLORS)}")
    wc.add_argument("ws_ref")
    wc.add_argument("color", nargs="?")
    wc.add_argument("--clear", action="store_true", help="take the colour off")
    wd = sub.add_parser("workspace-description", help="describe one workspace (its live ref only): "
                                                       "workspace-description WS_REF (--clear | -- TEXT)")
    wd.add_argument("ws_ref")
    wd.add_argument("--clear", action="store_true", help="take the description off")
    wd.add_argument("text", nargs="*")
    sub.add_parser("caps", help="the verbs the configured driver serves").add_argument("--json", action="store_true")
    sub.add_parser("workspaces", help="the workspaces as the terminal shows them (read only)").add_argument(
        "--json", action="store_true")
    for name, what in (("focus", "bring a tab to the front"), ("close", "close one tab (only when you ask)")):
        sub.add_parser(name, help=what).add_argument("tab")
    ky = sub.add_parser("key", help="one key into a tab: " + ", ".join(KEYS))
    ky.add_argument("tab")
    ky.add_argument("key")
    sc = sub.add_parser("screen", help="the last lines a tab shows (read only)")
    sc.add_argument("tab")
    sc.add_argument("--lines", type=int, default=40)
    sc.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    cfg = load_cfg(args.root)
    if args.cmd == "place":
        if args.pending:
            placed = place_pending(args.root, cfg)
            items = placed
        else:
            items = unplaced(args.root) if args.unplaced else [x for x in args.items.split(",") if x.strip()]
            placed = place(args.root, cfg, items, write=not args.dry_run)
        if args.json:
            print(json.dumps(placed, ensure_ascii=False, indent=1))
        elif not args.quiet:
            for p in placed:
                print(f"{p['item']}  -> {p['area']}" + (f"  ({p['why']})" if p["why"] else ""))
            print(f"{len(placed)} of {len(items)} placed" + (" (dry run, nothing written)" if args.dry_run else ""))
        return 0
    try:
        driver = driver_from(cfg.get("driver"))
    except ValueError as exc:
        print(exc, file=sys.stderr)
        return 1
    today = dt.date.today()

    if args.cmd == "propose":
        plan = build_plan(args.root, cfg, today, driver)
        print(json.dumps(plan, default=str, ensure_ascii=False, indent=1) if args.json else render(plan))
        if plan.get("driver_error"):
            print(f"Warning: open tabs unknown ({plan['driver_error']}); every task shows as new.",
                  file=sys.stderr)
        return 0
    if args.cmd == "open":
        plan = build_plan(args.root, cfg, today, driver)
        only = set(args.only.split(",")) if args.only else None
        if plan.get("driver_error"):
            print(f"Open tabs are unknown ({plan['driver_error']}): not opening anything, "
                  "it could open a task a second time.", file=sys.stderr)
            return 1 if args.yes else 0
        if not args.yes:
            print(f"Dry run with driver {driver.name}; add --yes to open:")
            for ws in plan["workspaces"]:
                if only and ws["name"] not in only:
                    continue
                for t in ws["tabs"]:
                    if t["action"] == "open":
                        print(f"  {ws['name']}: {t['label']} is open already")
                    elif args.resume or t["action"] != "resume":
                        print(f"  {ws['name']}: {t['action']} {t['label']}")
            return 0
        print("\n".join(driver.open(plan, only, args.resume, args.here)))
        return 1 if getattr(driver, "failed", False) else 0
    if args.cmd == "control":
        ctl = dict(cfg.get("control") or {"name": "Control"})
        # the control session is a plain agent in the repo; workplace.control.command overrides it
        command = str(ctl.get("command") or "claude").strip()
        if not args.yes:
            print(f"Dry run with driver {driver.name}; add --yes to start {command!r} in {ctl['name']}")
            return 0
        print("\n".join(driver.control(ctl, command, args.root)))
        return 1 if getattr(driver, "failed", False) else 0
    if args.cmd == "tasks":
        rows = task_rows(args.root, cfg, today)
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=1))
        else:
            for r in rows:
                flag = " blocked" if r["blocked_by"] else " stale" if r["stale"] else ""
                print(f"{r['priority'] or '--':<3} {r['area']:<12} {r['label']}{flag}")
        return 0
    if args.cmd == "teams":
        rows = teams(cfg)
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=1))
        else:
            for t in rows:
                print(f"{t['id']:<10} {t['label']:<12} {' → '.join(r['name'] for r in t['roles'])}"
                      f"  ({', '.join(t['for_types']) or 'any task'})")
        return 0
    if args.cmd == "launch":
        if bool(args.team) != bool(args.role):
            print("--team and --role go together", file=sys.stderr)
            return 2
        if args.team and args.mode:
            # not refused: a caller may pass its usual --mode along; the role's own mode decides
            print("note: --mode is ignored with --team; each role runs in the mode its team gives it",
                  file=sys.stderr)
        if args.resume and ("," in args.items or args.team):
            print("--resume goes on in one session of one task, without a team", file=sys.stderr)
            return 2
        entries = build_launch(args.root, cfg, args.items.split(","), args.mode or "report", args.team, args.role,
                               resume=args.resume, resume_cwd=args.cwd, model=args.model, effort=args.effort,
                               start_note=args.start_note)
        if args.resume:
            args.again = True     # going on in an ended session is asked for, even beside an open tab
        good = [e for e in entries if "command" in e]
        report: list = []
        failed = any("error" in e for e in entries)
        if args.target == "auto":
            entries = route(args.root, cfg, entries)
            good = [e for e in entries if "command" in e]
        if args.yes and good and not args.again:
            # Never a second agent on the same item: a double click, or a click from a second session.
            rows = status_rows(args.root, cfg, driver)
            if rows is None:
                print(f"note: open tabs unknown ({getattr(driver, 'error', '') or 'no tab list'}), "
                      "not checked for tabs already open", file=sys.stderr)
            for e in good:
                hit = open_agent_tab(e, rows or [])
                if hit:
                    e.update({"skipped": "open", "ref": hit.get("ref"), "tab": hit.get("name"),
                              "tab_workspace": hit.get("workspace")})
                    report.append(f"already open: {e['label']} ({hit.get('ref')}) in {hit.get('workspace')}")
            good = [e for e in good if "skipped" not in e]
        if args.yes and good:
            groups = ([("workspace", [e for e in good if e["own"]]), ("area", [e for e in good if not e["own"]])]
                      if args.target == "auto" else [(args.target, good)])
            for target, batch in groups:
                if batch:
                    report += driver.launch(batch, target, args.here)
                    failed = failed or getattr(driver, "failed", False)
        if args.json:
            print(json.dumps({"ok": not failed, "items": [{k: v for k, v in e.items() if k != "slug"}
                                                          for e in entries], "report": report},
                             ensure_ascii=False, indent=1))
        else:
            if not args.yes:
                print(f"Dry run with driver {driver.name}; add --yes to open:")
                for e in good:
                    print(f"  {e['label']} -> {_destination(e, args.target)}")
                    print(f"    {e['command']}")
            for e in entries:
                if "error" in e:
                    print(f"ERROR {e['item']}: {e['error']}")
            if report:
                print("\n".join(report))
        return 1 if failed else 0
    if args.cmd == "status":
        rows = status_rows(args.root, cfg, driver)
        if rows is None:
            print(getattr(driver, "error", "") or f"driver {driver.name} failed", file=sys.stderr)
            return 1
        if args.json:
            print(json.dumps(rows, ensure_ascii=False, indent=1))
        elif not rows:
            print(f"No tabs known to driver {driver.name}.")
        else:
            for i, r in enumerate(rows, 1):
                print(f"{i:>2}  {str(r.get('workspace'))[:12]:<12} {str(r.get('name'))[:34]:<34} "
                      f"{str(r.get('state')):<9} {str(r.get('last') or '')[:80]}")
        return 0
    if args.cmd == "caps":
        caps = driver.caps()
        print(json.dumps({"caps": caps}) if args.json else "\n".join(caps))
        return 0
    if args.cmd == "workspaces":
        if isinstance(driver, NoneDriver):
            print(f"driver {driver.name} serves no workspaces", file=sys.stderr)
            return 2
        rows = driver.workspaces()
        if rows is None:
            print(getattr(driver, "error", "") or "the driver cannot list the workspaces", file=sys.stderr)
            return 1
        print(json.dumps(rows, ensure_ascii=False) if args.json else "\n".join(f"{w.get('title')}  {w.get('cwd') or ''}" for w in rows))
        return 0
    if args.cmd in ("rename", "rename-workspace"):
        return rename_cli(args, cfg, driver)
    if args.cmd in ("move-tab", "workspace-color", "workspace-description"):
        return layout_cli(args, cfg, driver)
    tasks = collect_tasks(args.root)
    index = slug_index(tasks, cfg)
    tabs = driver.tabs()
    try:
        tab = find_tab(tabs, args.tab, index) if tabs else {"name": args.tab, "ref": args.tab}
    except LookupError as exc:
        print(exc, file=sys.stderr)
        return 1
    if args.cmd == "adopt":
        task = next((t for t in tasks if t["slug"] == args.slug), None)
        if not task:
            print(f"no active task {args.slug}", file=sys.stderr)
            return 1
        print("\n".join(driver.rename(tab.get("ref") or tab["name"], tab_label(task, cfg))))
        return 1 if getattr(driver, "failed", False) else 0
    ref = tab.get("ref") or tab["name"]
    if args.cmd == "screen":
        text = driver.screen(ref, max(1, min(args.lines, 500)))
        if text is None:
            print(getattr(driver, "error", "") or "the driver cannot read this tab", file=sys.stderr)
            return 1
        print(json.dumps({"text": text}, ensure_ascii=False) if args.json else text)
        return 0
    if args.cmd in ("focus", "close"):
        lines = getattr(driver, args.cmd)(ref)
    elif args.cmd == "key":
        lines = driver.key(ref, args.key)
    else:
        lines = driver.send(ref, " ".join(args.text))
    print("\n".join(lines))
    return 1 if getattr(driver, "failed", False) else 0


def rename_cli(args, cfg: dict, driver) -> int:
    """`rename` and `rename-workspace`: a live ref only (never a name, never a part of one: a ref that
    vanished must not land on a tab found by name), a checked title, no managed name and no name in use.
    A refusal is exit 2 with its reason on stderr; a driver that failed is exit 1."""
    def refuse(why: str) -> int:
        print(why, file=sys.stderr)
        return 2
    try:
        title = check_title(" ".join(args.title))
    except ValueError as exc:
        return refuse(str(exc))
    tabs = driver.tabs_or_none()
    if tabs is None:
        print(getattr(driver, "error", "") or f"driver {driver.name} gave no tab list", file=sys.stderr)
        return 1
    managed = managed_names(args.root, cfg)
    if args.cmd == "rename":
        tab = next((t for t in tabs if t.get("ref") == args.ref), None)
        if tab is None:
            return refuse(f"no open tab with the ref {args.ref!r}")
        if str(tab.get("name") or "").strip().casefold() in managed["tab_names"]:
            return refuse("refused: a task, inbox or team tab keeps its name")
        want = title.casefold()
        if want in managed["tab_names"]:
            return refuse("refused: a task, inbox or team tab is known by this name")
        if any(str(t.get("name") or "").strip().casefold() == want for t in tabs if t.get("ref") != args.ref):
            return refuse("refused: name in use")
        lines = driver.rename(args.ref, title)
    else:
        listed = driver.workspaces() if "workspaces" in driver.caps() else None
        # live is what a tab or the driver's own list names by this ref, with or without a title
        here = [t.get("workspace") for t in tabs if t.get("ws_ref") == args.ws_ref] \
            + [w.get("title") for w in listed or [] if w.get("ref") == args.ws_ref]
        if not here:
            return refuse(f"no open workspace with the ref {args.ws_ref!r}")
        current = next((n for n in here if n), "")
        configured = {_ws_fold(n) for n in managed["workspace_names"]}
        if _ws_fold(current) in configured or _ws_fold(title) in configured:
            return refuse("refused: configured workspace, rename it in workplace.workspaces")
        others = {_ws_fold(t.get("workspace")) for t in tabs if t.get("ws_ref") != args.ws_ref and t.get("workspace")}
        others |= {_ws_fold(w.get("title")) for w in listed or [] if w.get("ref") != args.ws_ref and w.get("title")}
        if _ws_fold(title) in others:
            return refuse("refused: name in use")
        lines = driver.rename_workspace(args.ws_ref, title)
    print("\n".join(lines))
    return 1 if getattr(driver, "failed", False) else 0


LAYOUT_CAPS = {"move-tab": "move_tab", "workspace-color": "set_color", "workspace-description": "set_description"}


def layout_cli(args, cfg: dict, driver) -> int:
    """`move-tab`, `workspace-color` and `workspace-description`: live refs only (never a name, never a part
    of one), the driver's verb announced in its caps, a palette colour, a checked description. A configured
    workspace keeps the colour and description its config gives it (the plan sets them again). A refusal is
    exit 2 with its reason on stderr; a driver that failed or refused (an ERROR line) is exit 1."""
    def refuse(why: str) -> int:
        print(why, file=sys.stderr)
        return 2
    verb = LAYOUT_CAPS[args.cmd]
    if verb not in driver.caps():
        return refuse(f"refused: driver {driver.name} cannot {verb.replace('_', ' ')}")
    if args.cmd == "workspace-color":
        if bool(args.color) == bool(args.clear):
            return refuse("refused: give one colour or --clear")
        color = None if args.clear else palette_name(args.color)
        if not args.clear and color is None:
            return refuse(f"refused: not a palette colour, one of {', '.join(COLORS)}")
    if args.cmd == "workspace-description":
        if bool(args.text) == bool(args.clear):
            return refuse("refused: give a text after -- or --clear")
        try:
            text = None if args.clear else check_description(" ".join(args.text))
        except ValueError as exc:
            return refuse(str(exc))
    if args.cmd == "move-tab" and args.index is not None and not 0 <= args.index <= INDEX_MAX:
        return refuse(f"refused: an index is 0 to {INDEX_MAX}")
    tabs = driver.tabs_or_none()
    if tabs is None:
        print(getattr(driver, "error", "") or f"driver {driver.name} gave no tab list", file=sys.stderr)
        return 1
    listed = driver.workspaces() if "workspaces" in driver.caps() else None
    titles = {t.get("ws_ref"): t.get("workspace") for t in tabs if t.get("ws_ref")}
    titles.update({w.get("ref"): w.get("title") for w in listed or [] if w.get("ref")})
    if args.ws_ref not in titles:
        return refuse(f"no open workspace with the ref {args.ws_ref!r}")
    if args.cmd == "move-tab":
        tab = next((t for t in tabs if t.get("ref") == args.tab), None)
        if tab is None:
            return refuse(f"no open tab with the ref {args.tab!r}")
        if tab.get("ws_ref") == args.ws_ref:
            return refuse("refused: the tab is in that workspace already")
        lines = driver.move_tab(args.tab, args.ws_ref, args.index)
    else:
        configured = {_ws_fold(n) for n in managed_names(args.root, cfg)["workspace_names"]}
        if _ws_fold(titles[args.ws_ref]) in configured:
            return refuse("refused: configured workspace, set it in workplace.workspaces")
        lines = (driver.set_color(args.ws_ref, color) if args.cmd == "workspace-color"
                 else driver.set_description(args.ws_ref, text))
    print("\n".join(lines))
    return 1 if getattr(driver, "failed", False) else 0


if __name__ == "__main__":
    sys.exit(main())
