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
import shlex
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
WRAPPER_SURFACE_VARS = ("CMUX_SURFACE_ID",)
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


STRUCTURAL_KEYS = {"projects", "partners", "repos", "repositories", "packages", "workspaces", "infra",
                   "customers", "members", "children"}
STOP_WORDS = {"github", "gitlab", "internal", "customer", "partner", "project", "repo", "main", "the"}


def _registry_entries(root: Path) -> list[dict]:
    """One dict per entry that has `github:` or `local_path:`: its name, those two values and
    `ancestors`, the enclosing keys and display names outermost first. No YAML dependency."""
    entries: list[dict] = []
    for path in _registry_files(root):
        stack: list[dict] = []   # {"indent", "key", "attrs"}
        nodes: list[dict] = []
        for raw in _read(path).splitlines():
            line = raw.split(" #", 1)[0].rstrip()
            if not line.strip() or line.lstrip().startswith(("#", "-")):
                continue
            indent = len(line) - len(line.lstrip())
            m = re.match(r"^\s*([A-Za-z0-9_.-]+):\s*(.*)$", line)
            if not m:
                continue
            key, value = m.group(1), m.group(2).strip().strip("'\"")
            while stack and stack[-1]["indent"] >= indent:
                stack.pop()
            if value:
                if stack:
                    stack[-1]["attrs"][key] = value
                continue
            node = {"indent": indent, "key": key, "attrs": {}, "parents": [n for n in stack]}
            stack.append(node)
            nodes.append(node)
        for n in nodes:
            a = n["attrs"]
            if a.get("github") or a.get("local_path"):
                entries.append({
                    "name": n["key"], "github": a.get("github", ""), "local_path": a.get("local_path", ""),
                    "ancestors": [(p["key"], p["attrs"].get("display_name", "")) for p in n["parents"]
                                  if p["key"] not in STRUCTURAL_KEYS],
                })
    return entries


def _find_entry(root: Path, cwd: Path) -> tuple[dict | None, Path]:
    cwd = Path(cwd)
    top = Path(_git(cwd, "rev-parse", "--show-toplevel") or cwd)
    slug = _origin_slug(top)
    entries = _registry_entries(Path(root))
    for e in entries:
        if slug and e.get("github", "").lower() == slug:
            return e, top
    for e in entries:
        if e.get("local_path") and _expand(e["local_path"]).resolve() == top.resolve():
            return e, top
    return None, top


def _stem(word: str) -> str:
    """The first part of a key or a display name, kept only when it is specific enough:
    "reinvent-lab" -> "reinvent", "Contoso Logistics" -> "contoso"; short or generic -> ""."""
    first = re.split(r"[\s\-_(/,]+", word.strip().lower(), maxsplit=1)[0]
    first = re.sub(r"[^\w]", "", first)
    return first if len(first) >= 5 and first not in STOP_WORDS else ""


def context_words(root: Path, cwd: Path) -> list[str]:
    """Words an inbox item must contain (as a whole word) to be shown in this repo's session:
    the tag, the folder name, and the stem of each enclosing project key and display name."""
    entry, top = _find_entry(root, cwd)
    words = {top.name.lower()}
    if entry:
        words.add(entry["name"].lower())
        for key, display in entry["ancestors"]:
            words |= {_stem(key), _stem(display)}
    return sorted(w for w in words if w)


def _origin_slug(repo: Path) -> str:
    url = _git(repo, "remote", "get-url", "origin") or ""
    m = re.search(r"[:/]([^/:]+/[^/]+?)(?:\.git)?/?$", url)
    return m.group(1).lower() if m else ""


def context_tag(root: Path, cwd: Path) -> str:
    entry, top = _find_entry(root, cwd)
    return entry["name"] if entry else top.name.lower()


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
    """Whole-word match of the tag or folder name, so a short name ("ai") never
    matches inside another word ("mail") and lets an unrelated private item through."""
    hay = " ".join(str(item.get(k, "")) for k in ("summary", "task", "area", "from", "context")).lower()
    return any(re.search(rf"(?<![\w-]){re.escape(w)}(?![\w-])", hay) for w in words)


def _contexts(cell: str) -> set[str]:
    """A log row's context cell may name several tags: "acme / widget", "a, b"."""
    return {c.strip().lower() for c in re.split(r"[/,]", cell) if c.strip()}


def log_rows(root: Path, tag: str, hours: int = 48, limit: int = 8) -> list[str]:
    """Rows whose context cell names the tag, within `hours` of the newest row in
    the log. Timestamps decide, not day headings: file order and year boundaries
    do not matter."""
    rows = []
    newest = None
    for line in _read(root / "work/log.md").splitlines():
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) < 4:
            continue
        try:
            at = datetime.strptime(cells[0], "%Y-%m-%d %H:%M")
        except ValueError:
            continue
        newest = at if newest is None or at > newest else newest
        if tag.lower() in _contexts(cells[2]):
            rows.append((at, " | ".join(cells[3:])))
    if newest is None:
        return []
    keep = sorted((r for r in rows if (newest - r[0]).total_seconds() <= hours * 3600), key=lambda r: r[0])
    return [f"{at.strftime('%m-%d %H:%M')} {what[:220]}" for at, what in keep][-limit:]


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
    words = sorted(set(context_words(root, cwd)) | {tag})

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

def _bridge_hooks(root: Path, event: str) -> list[tuple[str, dict]]:
    """(matcher, hook) of every command hook the Bridge's project settings declare for
    `event`, settings.json first, a command declared twice kept once (Claude Code dedupes too)."""
    seen: set[str] = set()
    out = []
    for s in _settings(root):
        for group in (s.get("hooks") or {}).get(event, []) or []:
            for h in group.get("hooks", []):
                cmd = h.get("command")
                if h.get("type") == "command" and cmd and cmd not in seen:
                    seen.add(cmd)
                    out.append((group.get("matcher") or "", h))
    return out


def _bridge_hook_events(root: Path) -> dict[str, int]:
    """Events the Bridge hooks, with the SUM of their timeouts: the replay runs them one after another."""
    events = {}
    for event in HOOK_EVENTS:
        hooks = _bridge_hooks(root, event)
        if hooks:
            events[event] = sum(int(h.get("timeout", 60)) for _, h in hooks)
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
            "command": " ".join(shlex.quote(a) for a in
                                (sys.executable, str(script), "replay-hooks", event, "--root", str(root))),
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

MATCH_FIELD = {"SessionStart": "source", "SessionEnd": "reason", "PreCompact": "trigger"}


def _matcher_applies(matcher: str, value: str) -> bool:
    if matcher in ("", "*") or not value:
        return True
    try:
        return re.fullmatch(matcher, value) is not None
    except re.error:
        print(f"bridge-attach: hook matcher {matcher!r} is not a valid pattern, hook skipped", file=sys.stderr)
        return False


def _merge_outputs(outputs: list[str]) -> str:
    """One hook's output passes unchanged. Several are merged into one JSON object:
    additionalContext joined, plain text added to it, other keys from the first that sets them."""
    outputs = [o for o in outputs if o.strip()]
    if len(outputs) <= 1:
        return outputs[0] if outputs else ""
    merged: dict = {}
    contexts = []
    for o in outputs:
        try:
            obj = json.loads(o)
        except ValueError:
            obj = None
        if not isinstance(obj, dict):
            contexts.append(o.strip())
            continue
        spec = obj.get("hookSpecificOutput") or {}
        if spec.get("additionalContext"):
            contexts.append(str(spec["additionalContext"]))
        for k, v in obj.items():
            if k != "hookSpecificOutput":
                merged.setdefault(k, v)
        for k, v in spec.items():
            if k != "additionalContext":
                merged.setdefault("hookSpecificOutput", {}).setdefault(k, v)
    if contexts:
        merged.setdefault("hookSpecificOutput", {})["additionalContext"] = "\n\n".join(contexts)
    return json.dumps(merged, ensure_ascii=False) + "\n"


def replay_hooks(root: Path, event: str, payload: str) -> int:
    """Run the Bridge's own project hooks for `event` as a Bridge session would: cwd and
    CLAUDE_PROJECT_DIR = the Bridge root. Exit 2 of any hook is passed on (a blocking Stop
    hook keeps blocking); the stderr of a failing hook is forwarded."""
    root = Path(root).resolve()
    try:
        value = str(json.loads(payload or "{}").get(MATCH_FIELD.get(event, ""), "") or "")
    except (ValueError, AttributeError):
        value = ""
    env = {**os.environ, "CLAUDE_PROJECT_DIR": str(root), "BRIDGE_ROOT": str(root)}
    rc = 0
    outputs = []
    for matcher, h in _bridge_hooks(root, event):
        if not _matcher_applies(matcher, value):
            continue
        try:
            out = subprocess.run(["bash", "-c", h["command"]], input=payload, env=env, cwd=root,
                                 capture_output=True, text=True, timeout=int(h.get("timeout", 60)))
        except subprocess.TimeoutExpired:
            print(f"bridge-attach: a Bridge {event} hook timed out", file=sys.stderr)
            continue
        outputs.append(out.stdout)
        if out.returncode != 0 and out.stderr:
            sys.stderr.write(out.stderr)
        if out.returncode == 2:
            rc = 2
    sys.stdout.write(_merge_outputs(outputs))
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
    if not shutil.which(pl["argv"][0]):
        print(f"bridge-attach: refused, {pl['argv'][0]} not found on PATH", file=sys.stderr)
        return 3
    os.chdir(pl["cwd"])
    os.execvpe(pl["argv"][0], pl["argv"], {**os.environ, **pl["env"]})
    return 0  # not reached


if __name__ == "__main__":
    sys.exit(main())
