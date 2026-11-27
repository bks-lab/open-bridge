#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Attach this Bridge to an agent session that runs in another repo.

A Bridge session starts in the Bridge folder; the work happens in repos. This
script gives a session in any repo exactly one Bridge, the one it lives in:

    bin/bridge-attach claude [args...]     # or codex, copilot

It runs Phase 0 read-only against the Bridge root (never the caller's cwd),
refuses unless the Bridge is in state NORMAL, writes a short attach text and
starts the tool with:

  claude   --add-dir <root> (skills, subagents), --append-system-prompt-file
           (the attach text: no 10,000-char hook cap, survives compaction),
           --plugin-dir <generated plugin> (replays the Bridge's own project
           hooks; plugin hooks merge, `--settings` does not) and, outside a
           cmux-style terminal, --settings with autoMemoryDirectory only.
  codex    --add-dir <root> (writable root) and -c developer_instructions=.
           Codex loads no skills from an added directory: stated, not hidden.
  copilot  --add-dir <root> (skills) and COPILOT_CUSTOM_INSTRUCTIONS_DIRS
           pointing at a generated .github/instructions file.

Env for the agent process: BRIDGE_ROOT, BRIDGE_ATTACH=1, BRIDGE_ATTACH_TAG.
Nothing is written into the caller's repo. Spec: scripts/tests/test_bridge_attach.py,
docs/bridge-attach.md.

    bridge-attach.py check [--root R]
    bridge-attach.py slice [--root R] [--cwd D] [--max-chars N]
    bridge-attach.py plan  <tool> [--root R] [--cwd D] [-- args...]
    bridge-attach.py exec  <tool> [--root R] [--cwd D] [-- args...]
    bridge-attach.py replay-hooks <Event> [--root R]   (hook entry point)

Exit codes: 0 ok, 2 usage, 3 refused (state not NORMAL, unknown tool, self-attach).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOLS = ("claude", "codex", "copilot")
DEFAULT_MAX_CHARS = 6000
HOOK_EVENTS = ("SessionStart", "SessionEnd", "Stop", "UserPromptSubmit", "PreCompact")
# Terminal apps whose agent wrapper passes its own --settings (cmux and cmux-compatible apps).
# Claude Code applies only the last --settings, so the launcher adds none inside them.
WRAPPER_SURFACE_VARS = ("CMUX_SURFACE_ID", "K2A_DESKTOP_SURFACE_ID")
KEEP_DAYS = 7


class Refused(Exception):
    """The attach is refused; the message says why and what to do."""


# ---------------------------------------------------------------- helpers

def _git(root: Path, *args: str) -> str | None:
    try:
        out = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.TimeoutExpired):
        return None
    return out.stdout.strip() if out.returncode == 0 else None


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return ""


def _expand(value: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(value.strip().strip("'\""))))


def _same_or_inside(child: Path, parent: Path) -> bool:
    try:
        child.resolve().relative_to(parent.resolve())
        return True
    except ValueError:
        return False


# ---------------------------------------------------------------- Phase 0

def state(root: Path) -> tuple[str, str]:
    """Phase 0 against the Bridge root, read-only. NORMAL is the only attachable state."""
    root = Path(root)
    if _git(root, "rev-parse", "--git-dir") is None:
        return "NOT_A_REPO", ""
    branch = _git(root, "branch", "--show-current") or ""
    if not branch.startswith("user/"):
        return "CORE_DEV", branch
    if not (root / "bridge-config.yaml").is_file():
        return "NO_CONFIG", branch
    return "NORMAL", branch


# ---------------------------------------------------------------- context tag

def _registry_files(root: Path) -> list[Path]:
    return sorted(p for p in root.glob("ecosystem*.yaml") if p.name != "ecosystem.example.yaml")


def _registry_entries(root: Path) -> list[dict]:
    """(name, github, local_path) per entry, without a YAML dependency: the
    nearest enclosing key of a `github:` or `local_path:` line names the entry."""
    entries: dict[tuple[str, str], dict] = {}
    for path in _registry_files(root):
        stack: list[tuple[int, str]] = []
        for raw in _read(path).splitlines():
            line = raw.split(" #", 1)[0].rstrip()
            if not line.strip() or line.lstrip().startswith(("#", "-")):
                continue
            indent = len(line) - len(line.lstrip())
            m = re.match(r"^\s*([A-Za-z0-9_.-]+):\s*(.*)$", line)
            if not m:
                continue
            key, value = m.group(1), m.group(2).strip()
            while stack and stack[-1][0] >= indent:
                stack.pop()
            if key in ("github", "local_path") and stack:
                owner = stack[-1][1]
                entries.setdefault((path.name, owner), {"name": owner})[key] = value.strip("'\"")
            elif not value:
                stack.append((indent, key))
    return list(entries.values())


def _origin_slug(repo: Path) -> str:
    url = _git(repo, "remote", "get-url", "origin") or ""
    m = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?/?$", url)
    return m.group(1).lower() if m else ""


def context_tag(root: Path, cwd: Path) -> str:
    cwd = Path(cwd)
    top = Path(_git(cwd, "rev-parse", "--show-toplevel") or cwd)
    slug = _origin_slug(top)
    entries = _registry_entries(Path(root))
    for e in entries:
        if slug and e.get("github", "").lower() == slug:
            return e["name"]
    for e in entries:
        if e.get("local_path") and _expand(e["local_path"]).resolve() == top.resolve():
            return e["name"]
    return top.name.lower()


# ---------------------------------------------------------------- slices

def bridge_name(root: Path) -> str:
    ident = _read(root / "identity/agent/IDENTITY.md")
    m = re.search(r"^## Name\s*\n+\s*\*\*(.+?)\*\*", ident, re.M)
    if m:
        return m.group(1).strip()
    m = re.search(r"^identity:\s*\n(?:\s+.*\n)*?\s+name:\s*(\S+)", _read(root / "bridge-config.yaml"), re.M)
    return m.group(1) if m else root.name


def conversation_language(root: Path) -> str:
    m = re.search(r"^language:\s*\n(?:\s+.*\n)*?\s+conversation:\s*(\S+)", _read(root / "bridge-config.yaml"), re.M)
    return m.group(1) if m else ""


def _settings(root: Path) -> list[dict]:
    out = []
    for name in ("settings.json", "settings.local.json"):
        text = _read(root / ".claude" / name)
        if text:
            try:
                out.append(json.loads(text))
            except ValueError:
                pass
    return out


def memory_dir(root: Path) -> Path | None:
    value = None
    for s in _settings(root):
        value = s.get("autoMemoryDirectory") or value
    return _expand(value) if value else None


def inbox_items(root: Path) -> list[dict]:
    script = root / "scripts/inbox.py"
    if not script.is_file():
        return []
    try:
        out = subprocess.run([sys.executable, str(script), "list", "--json"], cwd=root,
                             capture_output=True, text=True, timeout=30)
        data = json.loads(out.stdout or "[]")
    except (OSError, ValueError, subprocess.TimeoutExpired):
        return []
    items = data if isinstance(data, list) else data.get("items", [])
    return [i for i in items if isinstance(i, dict) and i.get("state", "open") in ("open", "waiting")]


def _matches(item: dict, words: list[str]) -> bool:
    hay = " ".join(str(item.get(k, "")) for k in ("summary", "task", "area", "from", "context")).lower()
    return any(w in hay for w in words)


def log_rows(root: Path, tag: str, days: int = 2, limit: int = 8) -> list[str]:
    text = _read(root / "work/log.md")
    blocks = re.split(r"^## .*$", text, flags=re.M)[1:]
    heads = re.findall(r"^## .*$", text, flags=re.M)
    dated = []
    for head, body in zip(heads, blocks):
        m = re.search(r"(\d{1,2})\.(\d{1,2})", head)
        dated.append(((int(m.group(2)), int(m.group(1))) if m else (0, 0), body))
    dated.sort(key=lambda b: b[0])
    rows = []
    for _, body in dated[-days:]:
        for line in body.splitlines():
            cells = [c.strip() for c in line.strip().strip("|").split("|")]
            if len(cells) >= 4 and re.match(r"\d{4}-\d\d-\d\d \d\d:\d\d", cells[0]) and tag in cells[2].lower():
                what = " | ".join(cells[3:])
                rows.append(f"{cells[0][11:]} {what[:220]}")
    return rows[-limit:]


def board_counts(root: Path) -> str:
    text = _read(root / "work/board.md")
    found = re.findall(r"^\| (Doing|Review|Backlog) \(tasks\) \| (\d+)", text, re.M)
    return ", ".join(f"{k} {v}" for k, v in found)


# ---------------------------------------------------------------- render

def render(root: Path, cwd: Path, max_chars: int = DEFAULT_MAX_CHARS, tag: str | None = None) -> str:
    root, cwd = Path(root).resolve(), Path(cwd).resolve()
    st, branch = state(root)
    tag = tag or context_tag(root, cwd)
    name = bridge_name(root)
    run = root / "bin/bridge-run"
    mem = memory_dir(root)
    lang = conversation_language(root)
    words = sorted({tag, cwd.name.lower()} - {""})

    head = [
        f"# Bridge attached: {name}",
        "",
        f"The attached Bridge is called {name}. It lives at {root} (branch {branch}, state {st}). "
        f"This session works in {cwd}; its context tag in the Bridge is `{tag}`.",
        "",
        "## How the Bridge works in this session",
        f"- The Bridge's operating manual is {root / 'AGENTS.md'}; its identity and voice are in "
        f"{root / 'identity/agent'} (IDENTITY.md, SOUL.md, INSTANCE.md). The manual's rules on the work "
        "system (log, inbox, tasks, consult before write, push guard, secrets) apply here. For work inside "
        "this repo, the repo's own CLAUDE.md or AGENTS.md wins.",
        f"- Bridge commands (scripts/..., skills/<name>/scripts/..., and every skill step that names a "
        f"Bridge-relative path) run through {run}, which executes them in the Bridge root, "
        f"for example `{run} python3 scripts/inbox.py list`. File tools take absolute paths under {root}.",
        f"- Each unit of work gets one row in the Bridge's work log, written with `{run} python3 "
        f"scripts/worklog.py --append --context {tag} --glyph <glyph> --what \"<what and why>\"`. "
        "This repo has no log of its own.",
        "- Open items go into the Bridge inbox (`scripts/inbox.py add`), not into this repo.",
        "- Phase 0 and Phase 1 already ran for this session against the Bridge root; they do not run in this repo.",
        "- Exactly one Bridge is attached. Other Bridge instances on this machine stay unread.",
    ]
    if mem:
        head.append(f"- The Bridge's memory is {mem} (MEMORY.md is its index).")
    if lang:
        head.append(f"- Conversation language: {lang}.")

    items = inbox_items(root)
    hit = [i for i in items if _matches(i, words)]
    rest = len(items) - len(hit)
    inbox = [f"- {str(i.get('summary', i.get('id', '')))[:200]}" for i in hit]
    rows = [f"- {r}" for r in log_rows(root, tag)]
    board = board_counts(root)

    def assemble(n_inbox: int, n_rows: int) -> str:
        out = head + ["", f"## State at {datetime.now().strftime('%Y-%m-%d %H:%M')}"]
        out.append(f"Inbox: {len(items)} open, {len(hit)} about `{tag}`, {rest} other open items (not shown).")
        out += inbox[:n_inbox]
        if len(inbox) > n_inbox:
            out.append(f"- ... {len(inbox) - n_inbox} more about `{tag}`: `{run} python3 scripts/inbox.py list`")
        if board:
            out.append(f"Board: {board}.")
        if rows[:n_rows]:
            out.append(f"Log, last two days, `{tag}`:")
            out += rows[-n_rows:] if n_rows else []
        return "\n".join(out) + "\n"

    n_inbox, n_rows = len(inbox), len(rows)
    text = assemble(n_inbox, n_rows)
    while len(text) > max_chars and (n_rows or n_inbox):
        if n_rows:
            n_rows -= 1
        else:
            n_inbox -= 1
        text = assemble(n_inbox, n_rows)
    if len(text) > max_chars:
        text = text[: max_chars - 2].rstrip() + "\n"
    return text


# ---------------------------------------------------------------- plan

def _bridge_hook_events(root: Path) -> dict[str, int]:
    """Events the Bridge's own project settings hook, with the longest timeout."""
    events: dict[str, int] = {}
    for s in _settings(root):
        for event, groups in (s.get("hooks") or {}).items():
            if event not in HOOK_EVENTS:
                continue
            for g in groups or []:
                for h in g.get("hooks", []):
                    if h.get("type") == "command":
                        events[event] = max(events.get(event, 0), int(h.get("timeout", 60)))
    return events


def _write_plugin(root: Path, run_dir: Path) -> Path | None:
    events = _bridge_hook_events(root)
    if not events:
        return None
    plugin = run_dir / "plugin"
    (plugin / ".claude-plugin").mkdir(parents=True, exist_ok=True)
    (plugin / "hooks").mkdir(exist_ok=True)
    (plugin / ".claude-plugin/plugin.json").write_text(json.dumps({
        "name": "bridge-attach-hooks", "version": "1.0.0",
        "description": f"Replays the project hooks of the Bridge at {root}",
    }, indent=2) + "\n")
    script = Path(__file__).resolve()
    hooks = {
        event: [{"hooks": [{
            "type": "command",
            "command": f"python3 {json.dumps(str(script))} replay-hooks {event} --root {json.dumps(str(root))}",
            "timeout": timeout + 5,
        }]}]
        for event, timeout in sorted(events.items())
    }
    (plugin / "hooks/hooks.json").write_text(json.dumps({"hooks": hooks}, indent=2) + "\n")
    return plugin


def _prune(state_dir: Path) -> None:
    cutoff = time.time() - KEEP_DAYS * 86400
    for d in state_dir.glob("*-*"):
        try:
            if d.is_dir() and d.stat().st_mtime < cutoff:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass


def plan(tool: str, root: Path, cwd: Path, args: list[str], env: dict, state_dir: Path | None = None) -> dict:
    root, cwd = Path(root).resolve(), Path(cwd).resolve()
    if tool not in TOOLS:
        raise Refused(f"unknown tool {tool!r}; one of {', '.join(TOOLS)}")
    st, branch = state(root)
    if st != "NORMAL":
        raise Refused(f"the Bridge at {root} is in state {st} (branch {branch or '-'}); "
                      "attach needs a user/* branch with bridge-config.yaml")
    if _same_or_inside(cwd, root):
        raise Refused(f"{cwd} is inside the Bridge itself; start the tool there without attach")

    state_dir = Path(state_dir) if state_dir else Path.home() / ".bridge/attach" / root.name
    state_dir.mkdir(parents=True, exist_ok=True)
    _prune(state_dir)
    run_dir = state_dir / f"{datetime.now().strftime('%Y%m%dT%H%M%S')}-{os.getpid()}"
    run_dir.mkdir(parents=True, exist_ok=True)

    tag = context_tag(root, cwd)
    text = render(root, cwd, tag=tag)
    attach = run_dir / "attach.md"
    attach.write_text(text, encoding="utf-8")

    out_env = {"BRIDGE_ROOT": str(root), "BRIDGE_ATTACH": "1", "BRIDGE_ATTACH_TAG": tag}
    notes: list[str] = []
    files = [str(attach)]

    if tool == "claude":
        argv = ["claude", "--add-dir", str(root), "--append-system-prompt-file", str(attach)]
        plugin = _write_plugin(root, run_dir)
        if plugin:
            argv += ["--plugin-dir", str(plugin)]
            files.append(str(plugin))
        mem = memory_dir(root)
        caller_settings = any(a == "--settings" or a.startswith("--settings=") for a in args)
        in_wrapper = any(env.get(v) for v in WRAPPER_SURFACE_VARS)
        if mem and caller_settings:
            notes.append("the caller passes --settings; Claude Code applies only the last one, "
                         "so the Bridge memory is not attached")
        elif mem and in_wrapper:
            notes.append("inside a terminal app that wraps the agent with its own --settings (cmux or compatible) "
                         "no --settings is added, so the Bridge memory is not attached as auto memory")
        elif mem:
            settings = run_dir / "settings.json"
            settings.write_text(json.dumps({"autoMemoryDirectory": str(mem)}, indent=2) + "\n")
            argv += ["--settings", str(settings)]
            files.append(str(settings))
    elif tool == "codex":
        argv = ["codex", "--add-dir", str(root), "-c", f"developer_instructions={text}"]
        notes.append("codex loads no skills from an added directory; Bridge skills are not listed in this "
                     "session, their SKILL.md files stay readable under the Bridge root")
    else:
        inst = run_dir / "copilot"
        (inst / ".github/instructions").mkdir(parents=True, exist_ok=True)
        (inst / ".github/instructions/bridge.instructions.md").write_text(text, encoding="utf-8")
        argv = ["copilot", "--add-dir", str(root)]
        prior = env.get("COPILOT_CUSTOM_INSTRUCTIONS_DIRS")
        out_env["COPILOT_CUSTOM_INSTRUCTIONS_DIRS"] = f"{inst},{prior}" if prior else str(inst)
        if prior:
            notes.append("COPILOT_CUSTOM_INSTRUCTIONS_DIRS was already set; the Bridge folder is put first, "
                         "the comma separator is not verified")
        files.append(str(inst))

    return {"tool": tool, "argv": argv + list(args), "env": out_env, "tag": tag, "root": str(root),
            "cwd": str(cwd), "files": files, "notes": notes, "chars": len(text)}


# ---------------------------------------------------------------- replay-hooks

def replay_hooks(root: Path, event: str, payload: str) -> int:
    """Run the Bridge's own project hooks for `event` with CLAUDE_PROJECT_DIR = the Bridge root.
    Exit 2 of any hook is passed on (a blocking Stop hook keeps blocking)."""
    root = Path(root).resolve()
    try:
        source = json.loads(payload or "{}").get("source", "")
    except ValueError:
        source = ""
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(root), "BRIDGE_ROOT": str(root)}
    rc = 0
    for s in _settings(root):
        for group in (s.get("hooks") or {}).get(event, []) or []:
            matcher = group.get("matcher") or ""
            if matcher and source and not re.fullmatch(matcher, source):
                continue
            for h in group.get("hooks", []):
                if h.get("type") != "command":
                    continue
                try:
                    out = subprocess.run(["bash", "-c", h["command"]], input=payload, env=env,
                                         capture_output=True, text=True, timeout=int(h.get("timeout", 60)))
                except subprocess.TimeoutExpired:
                    print(f"bridge-attach: a Bridge {event} hook timed out", file=sys.stderr)
                    continue
                if out.stdout:
                    sys.stdout.write(out.stdout)
                if out.returncode == 2:
                    sys.stderr.write(out.stderr)
                    rc = 2
    return rc


# ---------------------------------------------------------------- CLI

def _split_args(argv: list[str]) -> tuple[list[str], list[str]]:
    if "--" in argv:
        i = argv.index("--")
        return argv[:i], argv[i + 1:]
    return argv, []


def main(argv: list[str] | None = None) -> int:
    own, passthrough = _split_args(list(sys.argv[1:] if argv is None else argv))
    p = argparse.ArgumentParser(prog="bridge-attach.py", description=(__doc__ or "").split("\n\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("check", "slice", "plan", "exec", "replay-hooks"):
        s = sub.add_parser(name)
        s.add_argument("--root", default=str(ROOT))
        if name in ("plan", "exec"):
            s.add_argument("tool")
        if name == "replay-hooks":
            s.add_argument("event")
        if name in ("slice", "plan", "exec"):
            s.add_argument("--cwd", default=os.getcwd())
        if name == "slice":
            s.add_argument("--max-chars", type=int, default=DEFAULT_MAX_CHARS)
    a = p.parse_args(own)
    root = Path(a.root)

    if a.cmd == "check":
        st, branch = state(root)
        print(f"{st} {branch}".strip())
        return 0 if st == "NORMAL" else 3
    if a.cmd == "replay-hooks":
        return replay_hooks(root, a.event, sys.stdin.read() if not sys.stdin.isatty() else "{}")
    if a.cmd == "slice":
        st, branch = state(root)
        if st != "NORMAL":
            print(f"bridge-attach: refused, the Bridge is in state {st} ({branch or '-'})", file=sys.stderr)
            return 3
        sys.stdout.write(render(root, Path(a.cwd), max_chars=a.max_chars))
        return 0
    try:
        pl = plan(a.tool, root, Path(a.cwd), passthrough, dict(os.environ))
    except Refused as e:
        print(f"bridge-attach: refused, {e}", file=sys.stderr)
        return 3
    if a.cmd == "plan":
        print(json.dumps(pl, ensure_ascii=False, indent=2))
        return 0
    for n in pl["notes"]:
        print(f"bridge-attach: {n}", file=sys.stderr)
    print(f"bridge-attach: {pl['tool']} with the Bridge at {pl['root']}, tag {pl['tag']}", file=sys.stderr)
    os.chdir(pl["cwd"])
    os.execvpe(pl["argv"][0], pl["argv"], {**os.environ, **pl["env"]})
    return 0  # not reached


if __name__ == "__main__":
    sys.exit(main())
