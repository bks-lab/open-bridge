#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Generate docs/bridge.html from live repo data.

Reads every structured source in the repo and emits a single-file dashboard:
  ecosystem.yaml, bridge-config.yaml (if present),
  .claude/agents/*.md, protocols/standing-orders/*.md,
  skills/*/SKILL.md, remotes/*.yaml (+*-setup.md presence),
  channels/*.yaml, channels/_scheduled.yaml, channels/bots/*/bot.yaml,
  projects/*.yaml, mandants/*.yaml, personas/*.yaml, calendar/entries.yaml,
  themes/*.yaml, trackers/*.md, CLAUDE.md command table.

Run from repo root:  python3 scripts/generate-bridge.py
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
DOCS = ROOT / "docs"
OUT = DOCS / "bridge.html"

FRONTMATTER_RE = re.compile(r"^---\n(.*?)\n---\n(.*)$", re.DOTALL)


def read_frontmatter(path: Path) -> tuple[dict, str]:
    try:
        text = path.read_text(encoding="utf-8")
    except Exception:
        return {}, ""
    m = FRONTMATTER_RE.match(text)
    if not m:
        return {}, text
    try:
        meta = yaml.safe_load(m.group(1)) or {}
    except Exception:
        meta = {}
    return meta, m.group(2)


def read_yaml(path: Path) -> dict:
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except Exception:
        return {}


def short(text: str, n: int = 220) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    return text if len(text) <= n else text[: n - 1] + "…"


def first_sentence(text: str, n: int = 180) -> str:
    text = re.sub(r"\s+", " ", text or "").strip()
    cut = re.split(r"(?<=[.!?])\s", text, maxsplit=1)
    return short(cut[0] if cut else text, n)


def collect_agents() -> list[dict]:
    out = []
    for p in sorted((ROOT / ".claude" / "agents").glob("*.md")):
        meta, _ = read_frontmatter(p)
        if not meta:
            continue
        out.append({
            "name": meta.get("name", p.stem),
            "description": short(meta.get("description", ""), 400),
            "tools": [t.strip() for t in str(meta.get("tools", "")).split(",") if t.strip()],
            "model": meta.get("model", ""),
        })
    return out


def collect_standing_orders() -> list[dict]:
    out = []
    so_dir = ROOT / "protocols" / "standing-orders"
    if not so_dir.exists():
        return out
    for p in sorted(so_dir.glob("*.md")):
        if p.stem.startswith("_") or p.stem.upper() == "README":
            continue
        meta, body = read_frontmatter(p)
        if not meta and not body:
            continue
        name = meta.get("name", p.stem)
        # Skip template placeholders
        if name in ("order-name", "template") or not name:
            continue
        desc = meta.get("description", "")
        if not desc:
            desc = first_sentence(body, 240)
        out.append({
            "name": name,
            "scope": meta.get("scope", "always"),
            "description": short(desc, 240),
        })
    return out


def collect_skills() -> list[dict]:
    out = []
    for d in sorted((ROOT / "skills").iterdir()):
        sk = d / "SKILL.md"
        if not sk.exists():
            continue
        meta, _ = read_frontmatter(sk)
        desc = meta.get("description", "")
        if isinstance(desc, list):
            desc = " ".join(desc)
        out.append({
            "name": meta.get("name", d.name),
            "scope": meta.get("scope", "core"),
            "description": short(desc, 400),
            "trigger_excerpt": first_sentence(desc, 160),
        })
    return out


def collect_remotes() -> list[dict]:
    out = []
    rdir = ROOT / "remotes"
    for p in sorted(rdir.glob("*.yaml")):
        if p.name.startswith("_"):
            continue
        d = read_yaml(p)
        if not d:
            continue
        has_setup = (rdir / f"{p.stem}-setup.md").exists()
        out.append({
            "name": d.get("name", p.stem),
            "type": d.get("type", ""),
            "os": d.get("os", ""),
            "status": d.get("status", ""),
            "capabilities": d.get("capabilities", []) or [],
            "services": [
                s.get("name", s) if isinstance(s, dict) else s
                for s in (d.get("services", []) or [])
            ],
            "tailscale": (d.get("network", {}) or {}).get("tailscale_hostname", ""),
            "has_setup_notes": has_setup,
        })
    return out


def collect_channels() -> list[dict]:
    out = []
    for p in sorted((ROOT / "channels").glob("*.yaml")):
        if p.name.startswith("_"):
            continue
        d = read_yaml(p)
        if not d:
            continue
        out.append({
            "name": d.get("name", p.stem),
            "display_name": d.get("display_name", p.stem),
            "type": d.get("type", ""),
            "skill": (d.get("implementation", {}) or {}).get("skill", ""),
            "remote": (d.get("runtime", {}) or {}).get("remote", ""),
            "status": d.get("status", ""),
        })
    return out


def collect_scheduled() -> list[dict]:
    p = ROOT / "channels" / "_scheduled.yaml"
    if not p.exists():
        return []
    d = read_yaml(p)
    out = []
    for s in d.get("schedules", []) or []:
        cron = s.get("cron", [])
        if isinstance(cron, str):
            cron = [cron]
        rec = s.get("recipient", {}) or {}
        out.append({
            "name": s.get("name", ""),
            "channel": s.get("channel", ""),
            "recipient": rec.get("name", "") or rec.get("chat_id", ""),
            "cron": cron,
        })
    return out


def collect_bots() -> list[dict]:
    out = []
    bdir = ROOT / "channels" / "bots"
    if not bdir.exists():
        return out
    for d in sorted(bdir.iterdir()):
        if not d.is_dir():
            continue
        cfg = d / "bot.yaml"
        meta = read_yaml(cfg) if cfg.exists() else {}
        has_prompt = (d / "prompt.md").exists()
        has_knowledge = (d / "knowledge.md").exists()
        out.append({
            "name": meta.get("name", d.name),
            "display_name": meta.get("display_name", d.name),
            "channel": meta.get("channel", ""),
            "remote": (meta.get("runtime", {}) or {}).get("remote", ""),
            "status": meta.get("status", ""),
            "has_prompt": has_prompt,
            "has_knowledge": has_knowledge,
        })
    return out


def collect_projects() -> list[dict]:
    out = []
    for p in sorted((ROOT / "projects").glob("*.yaml")):
        if p.name.startswith("_"):
            continue
        d = read_yaml(p)
        if not d:
            continue
        out.append({
            "slug": d.get("slug", p.stem),
            "display_name": d.get("display_name", p.stem),
            "github_org": (d.get("github", {}) or {}).get("org", ""),
            "project_number": (d.get("github", {}) or {}).get("project_number", ""),
            "issue_repo": (d.get("github", {}) or {}).get("issue_repo", ""),
            "tracker": d.get("tracker", "github"),
        })
    return out


def collect_mandants() -> list[dict]:
    out = []
    for p in sorted((ROOT / "mandants").glob("*.yaml")):
        if p.name.startswith("_"):
            continue
        d = read_yaml(p)
        if not d:
            continue
        persons = d.get("persons", []) or []
        out.append({
            "id": d.get("id", p.stem),
            "display_name": d.get("display_name", p.stem),
            "type": d.get("type", ""),
            "persons": len(persons),
        })
    return out


def collect_personas() -> list[dict]:
    out = []
    pdir = ROOT / "personas"
    if not pdir.exists():
        return out
    for p in sorted(pdir.glob("*.yaml")):
        if p.name.startswith("_"):
            continue
        d = read_yaml(p)
        if not d:
            continue
        out.append({
            "id": d.get("id", p.stem),
            "display_name": d.get("display_name", p.stem),
            "type": d.get("type", ""),
        })
    return out


def collect_calendar() -> list[dict]:
    p = ROOT / "calendar" / "entries.yaml"
    if not p.exists():
        return []
    d = read_yaml(p)
    out = []
    for e in d.get("entries", []) or []:
        repeat = e.get("repeat", "")
        if isinstance(repeat, dict):
            repeat = repeat.get("spec") or repeat.get("cron") or repeat.get("rrule") or ""
        out.append({
            "id": e.get("id", ""),
            "title": e.get("title", ""),
            "delivery_at": e.get("delivery_at", ""),
            "repeat": repeat,
            "recipients": len(e.get("recipients", []) or []),
        })
    return out


def collect_themes() -> list[dict]:
    out = []
    for p in sorted((ROOT / "themes").glob("*.yaml")):
        if p.name.startswith("_"):
            continue
        d = read_yaml(p)
        if not d:
            continue
        meta = d.get("meta", {}) or {}
        out.append({
            "name": meta.get("name", p.stem),
            "locale": meta.get("locale", ""),
            "description": meta.get("description", ""),
            "extends": meta.get("extends", ""),
        })
    return out


def collect_trackers() -> list[dict]:
    out = []
    tdir = ROOT / "trackers"
    if not tdir.exists():
        return out
    for p in sorted(tdir.glob("*.md")):
        if p.name.upper() == "README.MD":
            continue
        meta, body = read_frontmatter(p)
        out.append({
            "provider": p.stem,
            "description": short(meta.get("description", ""), 240) or first_sentence(body, 200),
        })
    return out


def collect_config() -> dict:
    p = ROOT / "bridge-config.yaml"
    if not p.exists():
        return {}
    d = read_yaml(p)
    identity = d.get("identity", {}) or {}
    language = d.get("language", {}) or {}
    work = d.get("work", {}) or {}
    return {
        "theme": d.get("theme", ""),
        "user": identity.get("name", ""),
        "org": identity.get("org", ""),
        "locale": language.get("primary") or identity.get("locale", ""),
        "projects_root": identity.get("projects_root", ""),
        "home": identity.get("home", ""),
        "onedrive_root": identity.get("onedrive_root", ""),
        "bks_root": identity.get("bks_root", ""),
        "work_enabled": work.get("enabled", False),
        "work_level": work.get("logging_level", ""),
    }


def collect_external_agents() -> list[dict]:
    """Parse CLAUDE.md's 'Sub-agent selection' section for named external agents.

    These are agents not defined in .claude/agents/ (e.g. plugin agents, Claude
    Code built-ins) that the repo treats as part of the dispatch pool.
    """
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    m = re.search(r"### Sub-agent selection.*?\n(.*?)(?:\n###|\n---\s*\n)", text, re.DOTALL)
    if not m:
        return []
    block = m.group(1)
    out = []
    # Look for `**backticked**` names at start of numbered list items
    for line in block.splitlines():
        mm = re.match(r"^\s*\d+\.\s+\*\*`([^`]+)`\*\*\s*(?:\(([^)]*)\))?\s*[—\-–]?\s*(.*)$", line)
        if mm:
            name = mm.group(1).strip()
            meta = mm.group(2) or ""
            desc = mm.group(3).strip()
            out.append({
                "name": name,
                "meta": short(meta, 80),
                "description": short(desc, 280),
            })
    return out


def detect_orchestrator_skills(skills: list[dict]) -> list[str]:
    """Skills whose description indicates they coordinate other agents/skills."""
    out = []
    for s in skills:
        d = s["description"].lower()
        if any(kw in d for kw in ("orchestrates", "coordinates", "dispatches",
                                  "spawns", "fan-out", "multi-agent", "orchestrator")):
            out.append(s["name"])
    return out


def collect_rules() -> list[dict]:
    out = []
    rdir = ROOT / "rules"
    if not rdir.exists():
        return out
    for p in sorted(rdir.glob("*.md")):
        if p.stem.upper() == "README":
            continue
        meta, body = read_frontmatter(p)
        desc = meta.get("description", "")
        if not desc:
            desc = first_sentence(body, 240)
        paths = meta.get("paths", []) or []
        out.append({
            "name": p.stem,
            "description": short(desc, 240),
            "scoped": bool(paths),
            "paths": paths,
        })
    return out


def collect_hooks() -> list[dict]:
    out = []
    hdir = ROOT / ".claude" / "hooks"
    if not hdir.exists():
        return out
    for p in sorted(hdir.iterdir()):
        if p.name.startswith(".") or p.name.upper().startswith("README"):
            continue
        if not p.is_file():
            continue
        # Pull first comment line as description
        desc = ""
        try:
            for line in p.read_text(encoding="utf-8", errors="ignore").splitlines()[:15]:
                s = line.strip().lstrip("#").strip()
                if s and not s.startswith("!/") and not s.startswith("/"):
                    desc = s
                    break
        except Exception:
            pass
        out.append({"name": p.name, "description": short(desc, 200)})
    return out


_COMMAND_SKILL_OVERRIDES = {
    "/bridge": "bridge-status",
    "/onboard": "bridge-onboard",
    "/promote": "bridge-promote",
    "/contribute": "bridge-promote",
    "/crew": "",  # no dedicated skill — handled inline
}


def compute_command_skill_map(commands: list[dict], skills: list[dict]) -> list[dict]:
    """Match each command to the skill most likely to handle it."""
    skill_names = {s["name"] for s in skills}
    out = []
    for c in commands:
        slash = c["command"].strip().strip("`").strip()
        skill = ""
        if slash in _COMMAND_SKILL_OVERRIDES:
            skill = _COMMAND_SKILL_OVERRIDES[slash]
        elif slash.startswith("/") and slash[1:] in skill_names:
            skill = slash[1:]
        out.append({
            "command": slash,
            "skill": skill,
            "action": c["action"],
        })
    return out


def collect_commands() -> list[dict]:
    text = (ROOT / "CLAUDE.md").read_text(encoding="utf-8")
    m = re.search(r"### Commands\s*\n+\|[^\n]+\|\s*\n\|[-| ]+\|\s*\n(.*?)(?:\n\n|\n---)", text, re.DOTALL)
    if not m:
        return []
    rows = []
    for line in m.group(1).splitlines():
        if not line.strip().startswith("|"):
            continue
        cells = [c.strip() for c in line.strip().strip("|").split("|")]
        if len(cells) >= 2:
            rows.append({"command": cells[0].strip("`").strip(), "action": cells[1]})
    return rows


USE_CASES = [
    {
        "id": "morning-briefing",
        "icon": "☀",
        "title": "Morning briefing",
        "when": "Start of day, or any time you need a status check",
        "trigger": "/briefing",
        "skill": "briefing",
        "reads": ["work/log.md", "work/board.md", "ecosystem.yaml", "trackers/*.md"],
        "dispatches": [],
        "streams": ["Local state (log + board)", "Tracker fan-out (GitHub / ADO)",
                    "Companion data (remotes, channels)", "Channel activity"],
        "output": "One concise dashboard: active tasks, yesterday's log, stuck items, CORE upstream deltas.",
        "why": "Walk into the day knowing exactly where you are across every repo and project — without grepping six tools. Parallel 4-stream collection keeps it fast even with many trackers.",
    },
    {
        "id": "meeting-debrief",
        "icon": "📝",
        "title": "Process a meeting transcript",
        "when": "After any meeting with a transcript or recording",
        "trigger": "/debrief <path>",
        "skill": "debrief",
        "reads": ["transcript file", "wiki/", "projects/*.yaml"],
        "dispatches": [],
        "streams": ["Classify meeting type", "7-category insight extraction",
                    "Task proposals with project field mapping", "Wiki routing + GitHub issues"],
        "output": "Structured protocol written to wiki, issues opened in the right repo and project, action items added to the board.",
        "why": "Meetings vanish into the void without this. The skill knows which project board each topic belongs to, so issues land where they're tracked — not in a personal notebook.",
    },
    {
        "id": "document-intake",
        "icon": "📥",
        "title": "Batch document intake",
        "when": "Flagged inbox with PDFs, invoices, contracts to file",
        "trigger": '"process inbox", "process mail attachments"',
        "skill": None,
        "agent": "archivist",
        "reads": ["inbox sources", "routing rules", "audit trail"],
        "dispatches": [],
        "streams": ["Scan filesystem + mail", "Classify against rules",
                    "Preview moves", "Execute approved moves, log"],
        "output": "Documents filed under the right destinations (persona → tax folder, client → contract folder, etc.), audit row appended.",
        "why": "Dumping 40 filenames into the main session context wastes tokens and attention. The archivist runs in isolation, returns a summary, and never floods the conversation.",
    },
    {
        "id": "scheduled-outbound",
        "icon": "📨",
        "title": "Scheduled outbound message",
        "when": "A recurring or one-off message to a mandant",
        "trigger": "cron (launchd) on a remote · calendar entry",
        "skill": "calendar",
        "reads": ["calendar/entries.yaml", "mandants/*.yaml", "channels/_scheduled.yaml"],
        "dispatches": [],
        "streams": ["Fire-loop reads the entry at delivery_at",
                    "Wrapper script resolves mandant → channel → recipient",
                    "Channel (imessage, email, telegram, …) sends",
                    "Entry stays visible in /calendar list"],
        "output": "Message delivered at the scheduled time with full attribution on the calendar timeline.",
        "why": "Identity (personas), recipients (mandants), content (calendar entry), and transport (channels) are separated but composable. Editing one piece never requires touching the others.",
    },
    {
        "id": "weekly-archive",
        "icon": "📦",
        "title": "Weekly archive",
        "when": "End of the working week (Friday) or start of a new one",
        "trigger": "/archive",
        "skill": "archive",
        "reads": ["work/log.md"],
        "dispatches": [],
        "streams": ["Collect the week's log entries",
                    "Generate week summary", "Reset log.md to a fresh template",
                    "Check upstream for CORE updates"],
        "output": "Archived weekly summary + a clean slate log.md. Upstream deltas shown for optional merge.",
        "why": "Clean breaks matter. Without a weekly reset, log.md grows forever and the active board drifts. /archive is the natural checkpoint for upstream hygiene too.",
    },
    {
        "id": "example-customer-health",
        "icon": "🧭",
        "title": "ExampleCustomer health check",
        "when": "Daily status query, weekly report, or a customer escalation",
        "trigger": '"example-customer status", "what is running in outbound"',
        "skill": "example-customer-coordinator",
        "reads": ["Elasticsearch indices", "Azure function status",
                  "SharePoint folder", "GitHub Project board"],
        "dispatches": ["example-customer-log-analyst", "example-customer-deployment-verifier", "example-customer-reconciliation"],
        "streams": [],
        "output": "Tight summary: pre/prod status, failure clusters, invoice deltas, open board items — no raw log dump.",
        "why": "Customer-domain knowledge lives in one orchestrator skill, not in your head. Stakeholder names, failure heuristics, mail templates, and routing all encapsulated and re-entrant.",
    },
    {
        "id": "promote-core",
        "icon": "⬆",
        "title": "Promote CORE change to development",
        "when": "A generic improvement on your user branch that should flow upstream",
        "trigger": "/promote",
        "skill": "bridge-promote",
        "reads": ["git log user/<name>..development", "rules/promote-safety.md"],
        "dispatches": [],
        "streams": ["Analyze commits", "Categorize by CORE / USER paths",
                    "Run content-safety checks (PII, org names)",
                    "Cherry-pick to development", "Offer upstream PR or Issue"],
        "output": "Clean cherry-pick to development with zero personal data leaked. Optional upstream contribution prepared.",
        "why": "The CORE/USER split only works if promotion is disciplined. The skill enforces the path rules and runs PII checks the human brain would miss.",
    },
]


def build_data() -> dict:
    skills = collect_skills()
    commands = collect_commands()
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "config": collect_config(),
        "ecosystem": read_yaml(ROOT / "ecosystem.yaml"),
        "agents": collect_agents(),
        "standing_orders": collect_standing_orders(),
        "skills": skills,
        "remotes": collect_remotes(),
        "channels": collect_channels(),
        "scheduled": collect_scheduled(),
        "bots": collect_bots(),
        "projects": collect_projects(),
        "mandants": collect_mandants(),
        "personas": collect_personas(),
        "calendar": collect_calendar(),
        "themes": collect_themes(),
        "trackers": collect_trackers(),
        "commands": commands,
        "rules": collect_rules(),
        "hooks": collect_hooks(),
        "command_skill_map": compute_command_skill_map(commands, skills),
        "external_agents": collect_external_agents(),
        "orchestrator_skills": detect_orchestrator_skills(skills),
        "use_cases": validate_use_cases(skills),
    }


def validate_use_cases(skills: list[dict]) -> list[dict]:
    """Stamp each use case with whether its referenced skill exists.

    Keeps the rendered cards honest: if a skill gets renamed or removed, the
    UI shows a warning chip instead of silently pointing at something gone.
    """
    skill_names = {s["name"] for s in skills}
    out = []
    for uc in USE_CASES:
        uc = dict(uc)
        uc["skill_ok"] = uc.get("skill") is None or uc["skill"] in skill_names
        out.append(uc)
    return out


TEMPLATE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>The Bridge · Operations Map</title>
<style>
:root {
  --bg: #0a0e14;
  --bg-deep: #070a0f;
  --panel: #131924;
  --panel2: #1a2130;
  --line: #223049;
  --line2: #2d3e5c;
  --text: #d7dfec;
  --muted: #7a8aa3;
  --dim: #4d5c78;
  --accent: #7fb3ff;
  --accent2: #9f7fff;
  --ok: #5fd39a;
  --warn: #f2c14e;
  --danger: #ff6b6b;
  --chip: #1e2738;
  --ring1: #2d3e5c;
  --ring2: #1f2a3d;
}
html[data-theme="light"] {
  --bg: #f5f6f8;
  --bg-deep: #eceef2;
  --panel: #ffffff;
  --panel2: #f8f9fb;
  --line: #dde1e8;
  --line2: #c8cfdb;
  --text: #1d2433;
  --muted: #5b6a82;
  --dim: #8a97ac;
  --accent: #2563eb;
  --accent2: #7c3aed;
  --ok: #16a34a;
  --warn: #d97706;
  --danger: #dc2626;
  --chip: #eef1f6;
  --ring1: #c8cfdb;
  --ring2: #dde1e8;
}
* { box-sizing: border-box; }
html, body { margin: 0; padding: 0; background: var(--bg); color: var(--text);
  font: 14px/1.55 -apple-system, BlinkMacSystemFont, "SF Pro Text", "Segoe UI", system-ui, sans-serif; }
a { color: var(--accent); text-decoration: none; }
a:hover { text-decoration: underline; }
code, .mono { font-family: "SF Mono", ui-monospace, Menlo, monospace; font-size: 12.5px; }

header.top {
  position: sticky; top: 0; z-index: 10;
  backdrop-filter: blur(14px); -webkit-backdrop-filter: blur(14px);
  background: rgba(10,14,20,0.88);
  border-bottom: 1px solid var(--line);
}
.top-inner { max-width: 1400px; margin: 0 auto; padding: 14px 24px; display: flex; align-items: center; gap: 24px; flex-wrap: wrap; }
.brand { display: flex; align-items: center; gap: 10px; }
.brand .mark { width: 22px; height: 22px; border-radius: 6px;
  background: conic-gradient(from 200deg, var(--accent), var(--accent2), var(--accent)); }
.brand h1 { font-size: 17px; margin: 0; font-weight: 600; letter-spacing: -0.01em; }
.brand .sub { color: var(--muted); font-size: 12px; }
.stamp { color: var(--dim); font-size: 11.5px; margin-left: auto; display: flex; gap: 12px; align-items: center; }
.stamp .pill { padding: 2px 8px; border: 1px solid var(--line); border-radius: 999px; }
.theme-toggle { background: none; border: 1px solid var(--line); border-radius: 999px;
  color: var(--muted); cursor: pointer; font: inherit; font-size: 11.5px;
  padding: 2px 10px; display: inline-flex; align-items: center; gap: 4px; }
.theme-toggle:hover { color: var(--text); border-color: var(--accent); }
.kbd { display: inline-block; padding: 0 6px; border: 1px solid var(--line);
  border-radius: 4px; background: var(--chip); color: var(--muted); font-size: 10.5px;
  font-family: "SF Mono", ui-monospace, Menlo, monospace; }

/* ---- Use cases ---- */
.uc-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(440px, 1fr)); gap: 16px; }
.uc { background: var(--panel); border: 1px solid var(--line); border-radius: 14px; padding: 20px 22px;
  display: flex; flex-direction: column; gap: 14px; }
.uc-head { display: flex; align-items: flex-start; gap: 12px; }
.uc-icon { font-size: 22px; line-height: 1; flex: 0 0 auto;
  width: 38px; height: 38px; border-radius: 10px; background: var(--chip);
  display: inline-flex; align-items: center; justify-content: center; }
.uc h3 { margin: 0; font-size: 15px; font-weight: 600; letter-spacing: -0.005em; }
.uc .when { color: var(--muted); font-size: 12px; margin-top: 2px; }
.uc-rows { display: grid; grid-template-columns: minmax(84px, 100px) 1fr; gap: 6px 14px; align-items: baseline; }
.uc-rows .k { color: var(--dim); font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; }
.uc-rows .v { color: var(--text); font-size: 13px; }
.uc-rows .v.mono { font-family: "SF Mono", ui-monospace, Menlo, monospace; color: var(--accent); }
.uc-rows .v ul { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 3px; }
.uc-rows .v ul li { color: var(--muted); font-size: 12.5px; padding-left: 12px; position: relative; }
.uc-rows .v ul li::before { content: "›"; color: var(--dim); position: absolute; left: 0; }
.uc-why { background:
    linear-gradient(135deg, rgba(127,179,255,0.08), rgba(159,127,255,0.08)),
    var(--panel2);
  border-left: 2px solid var(--accent); border-radius: 6px;
  padding: 10px 14px; color: var(--text); font-size: 12.5px; line-height: 1.55; }
.uc-why::before { content: "Why it helps"; display: block;
  color: var(--accent); font-size: 10.5px; letter-spacing: 0.14em;
  text-transform: uppercase; font-weight: 600; margin-bottom: 4px; }
.uc-chip-link { background: var(--chip); border: 1px solid var(--line); border-radius: 999px;
  padding: 1px 8px; font-size: 11px; cursor: pointer; color: var(--muted); font-family: "SF Mono", ui-monospace, Menlo, monospace; }
.uc-chip-link:hover { color: var(--accent); border-color: var(--accent); }
.uc-chip-link.warn { color: var(--warn); border-color: rgba(242,193,78,0.4); cursor: default; }

/* ---- Flow ---- */
.flow-proto { background: var(--panel); border: 1px solid var(--line); border-radius: 12px;
  padding: 16px 18px; margin-bottom: 12px; }
.flow-proto h4 { margin: 0 0 10px; display: flex; align-items: center; gap: 8px;
  font-size: 14px; font-weight: 600; flex-wrap: wrap; }
.flow-chain { display: grid; grid-template-columns: minmax(90px, 120px) 18px 1fr; gap: 6px 10px; align-items: center; }
.flow-chain .role { color: var(--muted); font-size: 12.5px; font-family: -apple-system, sans-serif; }
.flow-chain .arr { color: var(--dim); text-align: center; }
.flow-chain .ag { font-family: "SF Mono", ui-monospace, Menlo, monospace; font-size: 12.5px; color: var(--accent); }
.flow-chain .ag.fallback { color: var(--muted); font-style: italic; }

.cmd-grid { display: grid; grid-template-columns: minmax(140px, auto) minmax(160px, auto) 1fr; gap: 8px 16px; align-items: baseline; }
.cmd-grid .cmd { font-family: "SF Mono", ui-monospace, Menlo, monospace; color: var(--accent); }
.cmd-grid .sk { color: var(--muted); font-size: 12.5px; }
.cmd-grid .sk .chip { font-size: 11px; }
.cmd-grid .ac { color: var(--text); font-size: 12.5px; }
.cmd-grid .hh { color: var(--dim); font-size: 11px; text-transform: uppercase; letter-spacing: 0.1em; padding-bottom: 6px; border-bottom: 1px solid var(--line); margin-bottom: 4px; }
nav.tabs { display: flex; gap: 4px; max-width: 1400px; margin: 0 auto; padding: 0 24px;
  border-bottom: 1px solid var(--line); overflow-x: auto; }
nav.tabs button { background: none; border: none; color: var(--muted); padding: 12px 16px;
  font: inherit; cursor: pointer; border-bottom: 2px solid transparent; white-space: nowrap; }
nav.tabs button:hover { color: var(--text); }
nav.tabs button.active { color: var(--text); border-bottom-color: var(--accent); }
nav.tabs .count { color: var(--dim); margin-left: 6px; font-size: 11.5px; }

main { max-width: 1400px; margin: 0 auto; padding: 24px; }
section[hidden] { display: none; }
.search { width: 100%; max-width: 360px; margin-bottom: 18px;
  background: var(--panel); border: 1px solid var(--line); border-radius: 8px;
  color: var(--text); padding: 8px 12px; font: inherit; }
.search:focus { outline: none; border-color: var(--accent); }

.grid { display: grid; gap: 14px; }
.grid.col-auto { grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); }
.grid.col-wide { grid-template-columns: repeat(auto-fill, minmax(360px, 1fr)); }
.grid.col-narrow { grid-template-columns: repeat(auto-fill, minmax(240px, 1fr)); }

.card { background: var(--panel); border: 1px solid var(--line); border-radius: 10px;
  padding: 14px 16px; transition: border-color 0.15s, background 0.15s; }
.card:hover { border-color: var(--line2); background: var(--panel2); }
.card h3 { margin: 0 0 6px 0; font-size: 14px; font-weight: 600; display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.card p { margin: 0; color: var(--muted); font-size: 12.5px; }
.card .meta { margin-top: 10px; display: flex; gap: 6px; flex-wrap: wrap; }

.chip { display: inline-flex; align-items: center; gap: 4px; padding: 2px 8px;
  background: var(--chip); border: 1px solid var(--line);
  border-radius: 999px; font-size: 11px; color: var(--muted); }
.chip.ok { color: var(--ok); border-color: rgba(95,211,154,0.35); }
.chip.warn { color: var(--warn); border-color: rgba(242,193,78,0.35); }
.chip.danger { color: var(--danger); border-color: rgba(255,107,107,0.35); }
.chip.accent { color: var(--accent); border-color: rgba(127,179,255,0.35); }

.dot { width: 8px; height: 8px; border-radius: 50%; display: inline-block; }
.dot.red { background: var(--danger); box-shadow: 0 0 8px var(--danger); }
.dot.yellow { background: var(--warn); box-shadow: 0 0 6px var(--warn); }
.dot.green { background: var(--ok); box-shadow: 0 0 6px var(--ok); }

.group-h { margin: 22px 0 10px; color: var(--muted); font-size: 11px;
  text-transform: uppercase; letter-spacing: 0.12em; font-weight: 600; }
.group-h:first-child { margin-top: 0; }

.stats { display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 12px; margin: 0 0 22px; }
.stat { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 14px 16px; }
.stat .n { font-size: 26px; font-weight: 600; letter-spacing: -0.02em; }
.stat .l { color: var(--muted); font-size: 12px; margin-top: 2px; }
.stat .n .accent { background: linear-gradient(135deg, var(--accent), var(--accent2));
  -webkit-background-clip: text; background-clip: text; color: transparent; }

.hero { background:
    radial-gradient(ellipse at top right, rgba(159,127,255,0.12), transparent 60%),
    radial-gradient(ellipse at bottom left, rgba(127,179,255,0.10), transparent 60%),
    var(--panel);
  border: 1px solid var(--line); border-radius: 14px;
  padding: 26px; margin-bottom: 22px; }
.hero h2 { margin: 0 0 6px; font-size: 20px; letter-spacing: -0.01em; }
.hero p { margin: 0; color: var(--muted); max-width: 80ch; }
.hero .how { display: grid; grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
  gap: 12px; margin-top: 18px; }
.how .step { border-left: 2px solid var(--accent); padding: 2px 0 2px 12px; }
.how .step b { display: block; font-size: 12px; color: var(--accent); letter-spacing: 0.08em;
  text-transform: uppercase; margin-bottom: 2px; }
.how .step span { color: var(--muted); font-size: 12.5px; }

table.matrix { width: 100%; border-collapse: collapse; font-size: 12.5px; }
table.matrix th, table.matrix td { padding: 8px 12px; text-align: left; border-bottom: 1px solid var(--line); }
table.matrix th { color: var(--muted); font-weight: 500; font-size: 11.5px;
  text-transform: uppercase; letter-spacing: 0.08em; }
table.matrix td.cmd { font-family: "SF Mono", ui-monospace, Menlo, monospace; color: var(--accent); }

/* ---- Map connection overlays ---- */
.map-conn { fill: none; stroke: var(--line2); stroke-width: 1; stroke-dasharray: 4 4; opacity: 0.7; }
.map-conn-label { fill: var(--dim); font-size: 10px; letter-spacing: 0.06em;
  text-transform: uppercase; font-family: -apple-system, sans-serif; }

/* ---- Map ---- */
.map-layout { display: grid; grid-template-columns: 1fr 340px; gap: 18px; align-items: start; }
@media (max-width: 960px) { .map-layout { grid-template-columns: 1fr; } }
.map-stage { background:
    radial-gradient(circle at center, rgba(127,179,255,0.06), transparent 70%),
    var(--bg-deep);
  border: 1px solid var(--line); border-radius: 14px; padding: 10px; }
.map-stage svg { width: 100%; height: 620px; display: block; }
.map-detail { background: var(--panel); border: 1px solid var(--line); border-radius: 14px;
  padding: 18px; position: sticky; top: 96px; max-height: calc(100vh - 120px); overflow: auto; }
.map-detail h3 { margin: 0 0 4px; font-size: 15px; }
.map-detail .sub { color: var(--muted); font-size: 12.5px; margin-bottom: 14px; }
.map-detail ul { list-style: none; padding: 0; margin: 0; }
.map-detail li { padding: 6px 0; border-bottom: 1px dashed var(--line); color: var(--text); font-size: 13px; }
.map-detail li:last-child { border-bottom: none; }
.map-detail li .small { color: var(--muted); font-size: 11.5px; display: block; }
.map-detail .cta { display: inline-block; margin-top: 14px; color: var(--accent);
  font-size: 12.5px; cursor: pointer; }

.hub { cursor: pointer; transition: transform 0.2s; }
.hub circle { transition: stroke 0.2s, filter 0.2s; }
.hub:hover circle, .hub.active circle { stroke: var(--accent); stroke-width: 2;
  filter: drop-shadow(0 0 10px rgba(127,179,255,0.35)); }
.hub text.label { fill: var(--text); font-size: 12.5px; font-weight: 600;
  text-anchor: middle; pointer-events: none; font-family: -apple-system, sans-serif; }
.hub text.count { fill: var(--accent); font-size: 14px; font-weight: 700;
  text-anchor: middle; pointer-events: none; font-family: -apple-system, sans-serif; }
.hub text.sub { fill: var(--muted); font-size: 10.5px; text-anchor: middle;
  pointer-events: none; font-family: -apple-system, sans-serif; }
.center-circ { fill: url(#bridgeGrad); stroke: none; }
.center-ring { fill: none; stroke: var(--ring1); stroke-width: 1; stroke-dasharray: 3 5; }
.center-ring2 { fill: none; stroke: var(--ring2); stroke-width: 1; }
.center-label { fill: #0a0e14; font-weight: 700; text-anchor: middle;
  font-family: -apple-system, sans-serif; pointer-events: none; }
.spoke { stroke: var(--ring2); stroke-width: 1; fill: none; }
.spoke.active { stroke: var(--accent); stroke-width: 2; }
.band-label { fill: var(--dim); font-size: 10.5px; letter-spacing: 0.18em;
  text-transform: uppercase; font-family: -apple-system, sans-serif; }

footer { max-width: 1400px; margin: 30px auto; padding: 20px 24px; border-top: 1px solid var(--line);
  color: var(--dim); font-size: 12px; display: flex; justify-content: space-between; flex-wrap: wrap; gap: 8px; }

.empty { color: var(--dim); font-style: italic; padding: 8px 0; }
</style>
</head>
<body>
<header class="top">
  <div class="top-inner">
    <div class="brand"><span class="mark"></span>
      <div><h1>The Bridge</h1><div class="sub" id="brand-sub">Operations Map · auto-generated</div></div>
    </div>
    <div class="stamp" id="stamp"></div>
    <button class="theme-toggle" id="theme-toggle" title="Toggle theme (t)">◐ theme</button>
  </div>
  <nav class="tabs" id="tabs"></nav>
</header>
<main>
  <section id="view-overview"></section>
  <section id="view-usecases" hidden></section>
  <section id="view-map" hidden></section>
  <section id="view-flow" hidden></section>
  <section id="view-agents" hidden></section>
  <section id="view-skills" hidden></section>
  <section id="view-ecosystem" hidden></section>
  <section id="view-infra" hidden></section>
  <section id="view-identity" hidden></section>
</main>
<footer>
  <div>Single-file dashboard · vanilla JS · offline-safe · <code>python3 scripts/generate-bridge.py</code></div>
  <div id="foot-stamp"></div>
</footer>
<script id="data" type="application/json">__DATA__</script>
<script>
(() => {
  const DATA = JSON.parse(document.getElementById("data").textContent);
  const $ = (s, r=document) => r.querySelector(s);
  const h = (tag, attrs={}, kids=[]) => {
    const el = document.createElement(tag);
    for (const [k,v] of Object.entries(attrs)) {
      if (k === "class") el.className = v;
      else if (k === "html") el.innerHTML = v;
      else if (k.startsWith("on") && typeof v === "function") el.addEventListener(k.slice(2), v);
      else if (v !== undefined && v !== null) el.setAttribute(k, v);
    }
    for (const kid of [].concat(kids)) {
      if (kid == null) continue;
      el.append(kid instanceof Node ? kid : document.createTextNode(kid));
    }
    return el;
  };
  const ns = "http://www.w3.org/2000/svg";
  const svgEl = (tag, attrs={}, kids=[]) => {
    const el = document.createElementNS(ns, tag);
    for (const [k,v] of Object.entries(attrs)) {
      if (v == null) continue;
      el.setAttribute(k, v);
    }
    for (const kid of [].concat(kids)) if (kid) el.append(kid instanceof Node ? kid : document.createTextNode(kid));
    return el;
  };
  const fmtDate = iso => { try { return new Date(iso).toLocaleString(); } catch { return iso; } };

  // Header stamp + config
  const stamp = document.getElementById("stamp");
  if (DATA.config && DATA.config.user) stamp.append(h("span", { class: "pill" }, "user/" + DATA.config.user));
  if (DATA.config && DATA.config.theme) stamp.append(h("span", { class: "pill" }, "theme: " + DATA.config.theme));
  stamp.append(h("span", {}, "generated " + fmtDate(DATA.generated_at)));
  document.getElementById("foot-stamp").textContent = DATA.generated_at;

  const TABS = [
    { id: "overview", label: "Overview" },
    { id: "usecases", label: "Use cases", count: (DATA.use_cases||[]).length },
    { id: "map", label: "Map" },
    { id: "flow", label: "Flow" },
    { id: "agents", label: "Agents", count: DATA.agents.length },
    { id: "skills", label: "Skills", count: DATA.skills.length },
    { id: "ecosystem", label: "Ecosystem" },
    { id: "infra", label: "Infrastructure" },
    { id: "identity", label: "Identity" },
  ];

  const tabsEl = document.getElementById("tabs");
  TABS.forEach(t => {
    const btn = h("button", { "data-tab": t.id },
      [t.label, t.count != null ? h("span", { class: "count" }, String(t.count)) : null]);
    btn.addEventListener("click", () => activate(t.id));
    tabsEl.append(btn);
  });

  function activate(id) {
    document.querySelectorAll("nav.tabs button").forEach(b =>
      b.classList.toggle("active", b.dataset.tab === id));
    document.querySelectorAll("main > section").forEach(s =>
      s.hidden = s.id !== "view-" + id);
    history.replaceState(null, "", "#" + id);
    if (id === "map") renderMap();
  }

  // Utility: repo counter for ecosystem
  function countRepos(eco) {
    let n = 0;
    const visit = o => {
      if (!o || typeof o !== "object") return;
      if (o.github && typeof o.github === "string") n++;
      for (const v of Object.values(o)) if (v && typeof v === "object") visit(v);
    };
    visit(eco);
    return n;
  }

  // =====================================================================
  // OVERVIEW
  // =====================================================================
  const repoCount = countRepos(DATA.ecosystem);

  $("#view-overview").append(
    h("div", { class: "hero" }, [
      h("h2", {}, "The Bridge · Operations Map"),
      h("p", {}, "Live view of this Bridge instance. Everything below is read from the repo — agents, skills, ecosystem, and infrastructure. Regenerate with \u2318 python3 scripts/generate-bridge.py."),
      h("div", { class: "how" }, [
        step("1 · Config", "bridge-config.yaml + ecosystem.yaml define identity, theme, tracked repos, workspaces."),
        step("2 · Load", "Session start: Phase 0 detection, work log + board, theme vocabulary, standing orders."),
        step("3 · Dispatch", "Commands and skills spawn sub-agents via Task; skills carry the domain knowledge."),
        step("4 · Observe", "Work is logged in work/."),
      ]),
    ]),
    h("div", { class: "stats" }, [
      stat(DATA.agents.length, "Sub-agents"),
      stat(DATA.skills.length, "Skills"),
      stat(repoCount, "Repos tracked"),
      stat(DATA.remotes.length, "Remotes"),
      stat(DATA.channels.length, "Channels"),
      stat(DATA.projects.length, "Projects"),
      stat(DATA.commands.length, "Commands"),
    ]),
    h("h3", { class: "group-h" }, "Commands"),
    renderCommands(DATA.commands),
    h("h3", { class: "group-h" }, "Themes"),
    h("div", { class: "grid col-auto" }, DATA.themes.map(t => h("div", { class: "card" }, [
      h("h3", {}, [t.name || "(unnamed)", t.locale ? h("span", { class: "chip" }, t.locale) : null]),
      h("p", {}, t.description || ""),
      t.extends ? h("div", { class: "meta" }, h("span", { class: "chip" }, "extends " + t.extends)) : null,
    ]))),
  );

  function step(label, text) {
    return h("div", { class: "step" }, [h("b", {}, label), h("span", {}, text)]);
  }
  function stat(n, l) {
    return h("div", { class: "stat" }, [
      h("div", { class: "n" }, [h("span", { class: "accent" }, String(n))]),
      h("div", { class: "l" }, l),
    ]);
  }
  function renderCommands(cmds) {
    if (!cmds.length) return h("div", { class: "empty" }, "No commands parsed from CLAUDE.md.");
    const tbody = h("tbody", {}, cmds.map(c => h("tr", {}, [
      h("td", { class: "cmd" }, c.command), h("td", {}, c.action),
    ])));
    return h("table", { class: "matrix" }, [
      h("thead", {}, h("tr", {}, [h("th", {}, "Command"), h("th", {}, "Action")])), tbody,
    ]);
  }

  // =====================================================================
  // USE CASES  —  what each scenario reads, dispatches, produces, and why
  // =====================================================================
  const uc = $("#view-usecases");
  uc.append(h("div", { class: "hero" }, [
    h("h2", {}, "What this Bridge is actually for"),
    h("p", {}, "Concrete scenarios showing how commands, skills and agents work together — and why the information each piece produces is useful. References link to the real named components; if one goes missing on regeneration, the card flags it."),
  ]));

  const ucGrid = h("div", { class: "uc-grid" });
  (DATA.use_cases || []).forEach(u => {
    const rows = [];
    const addRow = (k, v, mono=false) => rows.push(
      h("div", { class: "k" }, k),
      h("div", { class: "v" + (mono ? " mono" : "") }, v),
    );
    addRow("Trigger", u.trigger, true);
    if (u.skill) {
      addRow("Skill", chipLink(u.skill, u.skill_ok ? "skills" : null, u.skill_ok));
    }
    if (u.agent) {
      const exists = (DATA.agents||[]).some(a => a.name === u.agent);
      addRow("Agent", chipLink(u.agent, exists ? "agents" : null, exists));
    }
    if ((u.dispatches || []).length) {
      addRow("Dispatches", h("div", {}, u.dispatches.map(name => {
        const isAgent = (DATA.agents||[]).some(a => a.name === name);
        const isSkill = (DATA.skills||[]).some(s => s.name === name);
        const tab = isAgent ? "agents" : isSkill ? "skills" : null;
        return chipLink(name, tab, isAgent || isSkill);
      }).reduce((a, el) => (a.push(el, document.createTextNode(" ")), a), [])));
    }
    if ((u.reads || []).length) {
      addRow("Reads", h("ul", {}, u.reads.map(r => h("li", {}, r))));
    }
    if ((u.streams || []).length) {
      addRow("Flow", h("ul", {}, u.streams.map(s => h("li", {}, s))));
    }
    if (u.output) addRow("Output", u.output);

    const card = h("div", { class: "uc" }, [
      h("div", { class: "uc-head" }, [
        h("div", { class: "uc-icon" }, u.icon),
        h("div", {}, [h("h3", {}, u.title), h("div", { class: "when" }, u.when)]),
      ]),
      h("div", { class: "uc-rows" }, rows),
      h("div", { class: "uc-why" }, u.why),
    ]);
    ucGrid.append(card);
  });
  uc.append(ucGrid);

  function chipLink(name, targetTab, ok) {
    const cls = "uc-chip-link" + (ok ? "" : " warn");
    const el = h("span", { class: cls, title: ok ? "open tab" : "referenced but not found" }, name);
    if (ok && targetTab) el.addEventListener("click", () => activate(targetTab));
    return el;
  }

  // =====================================================================
  // FLOW  —  commands → skills
  // =====================================================================
  const flow = $("#view-flow");
  flow.append(h("div", { class: "hero" }, [
    h("h2", {}, "Orchestration flow"),
    h("p", {}, "How intent turns into action: a slash command routes through a skill, which spawns sub-agents by name (general-purpose fallback when no named sub-agent exists). Everything here is derived from CLAUDE.md and skill frontmatter — regenerate to refresh."),
  ]));

  flow.append(h("h3", { class: "group-h" }, "Commands → Skills"));
  const cmdWrap = h("div", { class: "card" });
  const cmdGrid = h("div", { class: "cmd-grid" });
  cmdGrid.append(
    h("div", { class: "hh" }, "Command"),
    h("div", { class: "hh" }, "Skill"),
    h("div", { class: "hh" }, "Action"),
  );
  (DATA.command_skill_map || []).forEach(row => {
    cmdGrid.append(
      h("div", { class: "cmd" }, row.command),
      h("div", { class: "sk" }, row.skill
        ? h("span", { class: "chip accent" }, row.skill)
        : h("span", { class: "chip" }, "inline")),
      h("div", { class: "ac" }, row.action),
    );
  });
  cmdWrap.append(cmdGrid);
  flow.append(cmdWrap);

  // =====================================================================
  // AGENTS  —  three layers: native, external, orchestrator skills
  // =====================================================================
  const agentsView = $("#view-agents");
  agentsView.append(h("div", { class: "hero" }, [
    h("h2", {}, "Sub-agents"),
    h("p", {}, "Most agentic work in this Bridge lives inside skills — orchestrator skills coordinate, specialized skills do the work. Below: the three layers that Claude can reach."),
  ]));
  agentsView.append(
    h("h3", { class: "group-h" }, "Native sub-agents · " + DATA.agents.length + " · .claude/agents/"),
    h("div", { class: "grid col-wide" }, DATA.agents.map(a => h("div", { class: "card" }, [
      h("h3", {}, [a.name, a.model ? h("span", { class: "chip accent" }, a.model) : null]),
      h("p", {}, a.description),
      h("div", { class: "meta" }, (a.tools.length ? a.tools : ["inherits tools"]).map(t => h("span", { class: "chip" }, t))),
    ]))),
  );
  const ext = DATA.external_agents || [];
  if (ext.length) agentsView.append(
    h("h3", { class: "group-h" }, "Referenced external sub-agents · " + ext.length + " · from CLAUDE.md"),
    h("div", { class: "grid col-wide" }, ext.map(a => h("div", { class: "card" }, [
      h("h3", {}, [a.name, a.meta ? h("span", { class: "chip" }, a.meta) : null]),
      h("p", {}, a.description),
    ]))),
  );
  const orchNames = DATA.orchestrator_skills || [];
  const orchSkills = DATA.skills.filter(s => orchNames.includes(s.name));
  if (orchSkills.length) agentsView.append(
    h("h3", { class: "group-h" }, "Orchestrator skills · " + orchSkills.length + " · skills that dispatch others"),
    h("div", { class: "grid col-wide" }, orchSkills.map(s => h("div", { class: "card" }, [
      h("h3", {}, [s.name, h("span", { class: "chip" }, s.scope)]),
      h("p", {}, s.trigger_excerpt || s.description),
    ]))),
  );

  // =====================================================================
  // SKILLS
  // =====================================================================
  function skillGroup(name) {
    if (name.startsWith("bridge-") || name === "project-advisor")
      return "bridge-core";
    if (/^(briefing|archive|dashboard|debrief|schedule)$/.test(name))
      return "workflow";
    if (/^(channel|remote|doc-system)$/.test(name))
      return "infra";
    if (/^(calendar|mandants)$/.test(name))
      return "communication";
    if (name.startsWith("example-customer"))
      return "example-customer";
    return "other";
  }
  renderFilterable("#view-skills", DATA.skills, "Search skills…", (s, q) => {
    const hay = (s.name + " " + s.description + " " + s.scope).toLowerCase();
    return hay.includes(q);
  }, s => h("div", { class: "card" }, [
    h("h3", {}, [s.name, h("span", { class: "chip" }, s.scope)]),
    h("p", {}, s.trigger_excerpt || s.description),
  ]), {
    groupBy: s => skillGroup(s.name),
    groupOrder: ["bridge-core", "workflow", "infra", "communication", "example-customer", "other"],
    groupLabel: g => ({
      "bridge-core": "Bridge core",
      workflow: "Workflow",
      infra: "Infrastructure",
      communication: "Communication",
      example-customer: "ExampleCustomer",
      other: "Other",
    }[g] || g),
  });

  // =====================================================================
  // ECOSYSTEM
  // =====================================================================
  const eco = DATA.ecosystem;
  const ecoView = $("#view-ecosystem");
  ecoView.append(h("input", { class: "search", type: "search", placeholder: "Search repos…",
    oninput: (e) => renderEcosystem(e.target.value.toLowerCase()) }));
  const ecoContainer = h("div", {});
  ecoView.append(ecoContainer);
  function renderEcosystem(q="") {
    ecoContainer.innerHTML = "";
    const sections = [
      ["Base", eco.base || {}],
      ...Object.entries(eco.customers || {}).map(([k,v]) => [`Customer · ${v.display_name || k}`, v.repos || {}]),
      ...Object.entries(eco.partners || {}).map(([k,v]) => [`Partner · ${v.display_name || k}`, v.repos || {}]),
      ["Internal", eco.internal || {}],
      ["Personal", eco.personal || {}],
      ["References", eco.references || {}],
    ];
    for (const [title, repos] of sections) {
      const entries = Object.entries(repos).filter(([name, r]) => {
        if (!r || typeof r !== "object") return false;
        if (!q) return true;
        return (name + " " + (r.description||"") + " " + (r.github||"")).toLowerCase().includes(q);
      });
      if (!entries.length) continue;
      ecoContainer.append(h("h3", { class: "group-h" }, `${title} · ${entries.length}`));
      const grid = h("div", { class: "grid col-wide" });
      for (const [name, r] of entries) {
        grid.append(h("div", { class: "card" }, [
          h("h3", {}, [name,
            r.type ? h("span", { class: "chip" }, r.type) : null,
            r.language ? h("span", { class: "chip accent" }, r.language) : null,
            r.status ? h("span", { class: "chip warn" }, r.status) : null]),
          h("p", {}, r.description || ""),
          r.github ? h("div", { class: "meta" }, [
            h("a", { href: "https://github.com/" + r.github, target: "_blank", rel: "noopener", class: "chip" }, r.github),
          ]) : null,
        ]));
      }
      ecoContainer.append(grid);
    }
    const wsEntries = Object.entries(eco.workspaces || {});
    if (wsEntries.length) {
      ecoContainer.append(h("h3", { class: "group-h" }, "Workspaces"));
      const grid = h("div", { class: "grid col-wide" });
      for (const [name, ws] of wsEntries) {
        grid.append(h("div", { class: "card" }, [
          h("h3", {}, name),
          h("p", {}, ws.description || ""),
          h("div", { class: "meta" }, (ws.repos || []).map(r => h("span", { class: "chip" }, r))),
        ]));
      }
      ecoContainer.append(grid);
    }
    if ((DATA.projects || []).length) {
      ecoContainer.append(h("h3", { class: "group-h" }, "Project registry"));
      const grid = h("div", { class: "grid col-wide" });
      for (const p of DATA.projects) {
        grid.append(h("div", { class: "card" }, [
          h("h3", {}, [p.display_name, p.tracker ? h("span", { class: "chip" }, p.tracker) : null]),
          h("p", {}, p.issue_repo ? `Issues → ${p.issue_repo}` : ""),
          h("div", { class: "meta" }, [
            p.github_org ? h("span", { class: "chip" }, p.github_org) : null,
            p.project_number ? h("span", { class: "chip accent" }, "#" + p.project_number) : null,
          ]),
        ]));
      }
      ecoContainer.append(grid);
    }
  }
  renderEcosystem();

  // =====================================================================
  // INFRASTRUCTURE
  // =====================================================================
  const infra = $("#view-infra");
  infra.append(h("h3", { class: "group-h" }, "Remotes"),
    h("div", { class: "grid col-auto" }, DATA.remotes.map(r => h("div", { class: "card" }, [
      h("h3", {}, [r.name,
        r.type ? h("span", { class: "chip" }, r.type) : null,
        r.status ? h("span", { class: "chip " + (r.status === "active" || r.status === "online" ? "ok" : "") }, r.status) : null,
        r.has_setup_notes ? h("span", { class: "chip" }, "setup notes") : null]),
      h("p", {}, r.os || ""),
      h("div", { class: "meta" }, (r.capabilities || []).map(c => h("span", { class: "chip" }, c))),
      r.services.length ? h("div", { class: "meta" }, (r.services || []).map(s => h("span", { class: "chip accent" }, s))) : null,
    ]))),
    h("h3", { class: "group-h" }, "Channels"),
    h("div", { class: "grid col-auto" }, DATA.channels.map(c => h("div", { class: "card" }, [
      h("h3", {}, [c.display_name, c.type ? h("span", { class: "chip" }, c.type) : null]),
      h("p", {}, c.skill ? "skill: " + c.skill : ""),
      h("div", { class: "meta" }, [
        c.remote ? h("span", { class: "chip" }, "runs on " + c.remote) : null,
        c.status ? h("span", { class: "chip " + (c.status === "active" ? "ok" : "")}, c.status) : null,
      ]),
    ]))),
  );
  if ((DATA.scheduled || []).length) infra.append(
    h("h3", { class: "group-h" }, "Scheduled messages"),
    h("div", { class: "grid col-wide" }, DATA.scheduled.map(s => h("div", { class: "card" }, [
      h("h3", {}, [s.name, h("span", { class: "chip accent" }, s.channel)]),
      h("p", {}, s.recipient ? "→ " + s.recipient : ""),
      h("div", { class: "meta" }, (s.cron || []).map(c => h("span", { class: "chip mono" }, c))),
    ]))),
  );
  if ((DATA.bots || []).length) infra.append(
    h("h3", { class: "group-h" }, "Bots"),
    h("div", { class: "grid col-auto" }, DATA.bots.map(b => h("div", { class: "card" }, [
      h("h3", {}, [b.display_name || b.name,
        b.channel ? h("span", { class: "chip accent" }, b.channel) : null,
        b.status ? h("span", { class: "chip " + (b.status === "active" ? "ok" : "")}, b.status) : null]),
      h("p", {}, b.remote ? "runs on " + b.remote : ""),
      h("div", { class: "meta" }, [
        b.has_prompt ? h("span", { class: "chip" }, "prompt") : null,
        b.has_knowledge ? h("span", { class: "chip" }, "knowledge") : null,
      ]),
    ]))),
  );
  if ((DATA.standing_orders || []).length) infra.append(
    h("h3", { class: "group-h" }, "Standing orders"),
    h("div", { class: "grid col-wide" }, DATA.standing_orders.map(o => h("div", { class: "card" }, [
      h("h3", {}, [o.name, h("span", { class: "chip" }, "scope: " + o.scope)]),
      h("p", {}, o.description),
    ]))),
  );
  if ((DATA.rules || []).length) infra.append(
    h("h3", { class: "group-h" }, "Rules"),
    h("div", { class: "grid col-wide" }, DATA.rules.map(r => h("div", { class: "card" }, [
      h("h3", {}, [r.name, r.scoped ? h("span", { class: "chip" }, "scoped") : h("span", { class: "chip accent" }, "always")]),
      h("p", {}, r.description),
      r.paths && r.paths.length
        ? h("div", { class: "meta" }, r.paths.map(p => h("span", { class: "chip mono" }, p)))
        : null,
    ]))),
  );
  if ((DATA.hooks || []).length) infra.append(
    h("h3", { class: "group-h" }, "Hooks"),
    h("div", { class: "grid col-auto" }, DATA.hooks.map(k => h("div", { class: "card" }, [
      h("h3", {}, [k.name, h("span", { class: "chip" }, ".claude/hooks")]),
      h("p", {}, k.description || ""),
    ]))),
  );
  const trackers = DATA.trackers || [];
  if (trackers.length) infra.append(
    h("h3", { class: "group-h" }, "Trackers"),
    h("div", { class: "grid col-auto" }, trackers.map(t => h("div", { class: "card" }, [
      h("h3", {}, t.provider), h("p", {}, t.description),
    ]))),
  );
  const example-customer = ((DATA.ecosystem.customers || {}).example-customer || {}).infra || {};
  if (example-customer.azure_functions) infra.append(
    h("h3", { class: "group-h" }, "ExampleCustomer · Azure Functions"),
    h("div", { class: "grid col-auto" }, example-customer.azure_functions.map(f => h("div", { class: "card" }, [
      h("h3", {}, f.name),
      h("p", {}, f.description || ""),
      h("div", { class: "meta" }, h("span", { class: "chip" }, f.resource_group)),
    ]))),
  );
  if (example-customer.azure_keyvault || example-customer.elasticsearch || example-customer.sharepoint) {
    infra.append(h("h3", { class: "group-h" }, "ExampleCustomer · Other infrastructure"));
    const cards = [];
    if (example-customer.azure_keyvault) {
      const kv = example-customer.azure_keyvault;
      cards.push(h("div", { class: "card" }, [
        h("h3", {}, ["Key Vault", h("span", { class: "chip accent" }, "azure")]),
        h("p", {}, kv.name || ""),
        kv.url ? h("div", { class: "meta" }, h("a", { href: kv.url, target: "_blank", class: "chip" }, kv.url)) : null,
      ]));
    }
    (example-customer.elasticsearch || []).forEach(e => cards.push(h("div", { class: "card" }, [
      h("h3", {}, ["Elasticsearch", h("span", { class: "chip accent" }, "index")]),
      h("p", {}, e.description || ""),
      h("div", { class: "meta" }, h("span", { class: "chip mono" }, e.index)),
    ])));
    if (example-customer.sharepoint) cards.push(h("div", { class: "card" }, [
      h("h3", {}, ["SharePoint", h("span", { class: "chip accent" }, "host")]),
      h("p", {}, example-customer.sharepoint.host || ""),
    ]));
    infra.append(h("div", { class: "grid col-auto" }, cards));
  }

  // =====================================================================
  // IDENTITY (mandants, personas, calendar)
  // =====================================================================
  const identity = $("#view-identity");
  identity.append(
    h("div", { class: "hero" }, [
      h("h2", {}, "Identity & recipients"),
      h("p", {}, "Who you are (self + personas), who you reach (mandants), and what's scheduled to go out (calendar)."),
    ]),
  );

  // Self — the user behind this Bridge instance (from bridge-config.yaml)
  const cfg = DATA.config || {};
  if (cfg.user) {
    identity.append(h("h3", { class: "group-h" }, "Self · this Bridge instance"));
    const pairs = [
      ["user", cfg.user],
      ["org", cfg.org],
      ["locale", cfg.locale],
      ["theme", cfg.theme],
      ["projects_root", cfg.projects_root],
      ["onedrive_root", cfg.onedrive_root],
      ["bks_root", cfg.bks_root],
      ["home", cfg.home],
      ["work tracking", cfg.work_enabled ? cfg.work_level || "enabled" : "disabled"],
    ].filter(([, v]) => v !== "" && v !== null && v !== undefined);
    identity.append(h("div", { class: "card" }, [
      h("h3", {}, [cfg.user, cfg.org ? h("span", { class: "chip accent" }, cfg.org) : null,
        h("span", { class: "chip" }, "self")]),
      h("p", {}, "Identity block from bridge-config.yaml — drives theme, paths, work system and agent dispatch defaults."),
      h("div", { class: "meta" }, pairs.map(([k, v]) => h("span", { class: "chip" }, k + ": " + v))),
    ]));
  }
  const mandants = DATA.mandants || [];
  identity.append(
    h("h3", { class: "group-h" }, "Mandants · recipient groups"),
    mandants.length
      ? h("div", { class: "grid col-narrow" }, mandants.map(m => h("div", { class: "card" }, [
          h("h3", {}, [m.display_name, h("span", { class: "chip" }, m.type)]),
          h("p", {}, m.persons + " person" + (m.persons === 1 ? "" : "s")),
        ])))
      : h("div", { class: "empty" }, "No mandants configured."),
  );
  const personas = DATA.personas || [];
  identity.append(
    h("h3", { class: "group-h" }, "Personas · your identities"),
    personas.length
      ? h("div", { class: "grid col-narrow" }, personas.map(p => h("div", { class: "card" }, [
          h("h3", {}, [p.display_name || p.id, p.type ? h("span", { class: "chip" }, p.type) : null]),
          h("p", {}, "id: " + p.id),
        ])))
      : h("div", { class: "empty" }, "No personas configured. See personas/_template.yaml to add one."),
  );
  const cal = DATA.calendar || [];
  identity.append(
    h("h3", { class: "group-h" }, "Calendar entries"),
    cal.length
      ? h("div", { class: "grid col-wide" }, cal.map(e => h("div", { class: "card" }, [
          h("h3", {}, [e.title || e.id, e.recipients ? h("span", { class: "chip" }, e.recipients + " recipients") : null]),
          h("p", {}, e.delivery_at ? "delivery: " + e.delivery_at : ""),
          e.repeat ? h("div", { class: "meta" }, h("span", { class: "chip mono" }, e.repeat)) : null,
        ])))
      : h("div", { class: "empty" }, "No calendar entries yet. See calendar/_template.yaml."),
  );

  // =====================================================================
  // MAP  —  hub-only radial + detail side-panel
  // =====================================================================
  let mapRendered = false;
  function renderMap() {
    if (mapRendered) return;
    mapRendered = true;
    const root = $("#view-map");
    root.innerHTML = "";

    const extAgents = DATA.external_agents || [];
    const orchSkills = DATA.skills.filter(s => (DATA.orchestrator_skills||[]).includes(s.name));
    const allDispatchable = [
      ...DATA.agents.map(a => ({ name: a.name, sub: "native · " + (a.model || "inherit") })),
      ...extAgents.map(a => ({ name: a.name, sub: "external" })),
      ...orchSkills.map(s => ({ name: s.name, sub: "orchestrator skill" })),
    ];
    const hubs = [
      { id: "agents",    label: "Sub-agents",
        count: DATA.agents.length + extAgents.length + orchSkills.length,
        sub: "native + external + orchestrator", band: "orchestration",
        leaves: allDispatchable },
      { id: "standing-orders", label: "Standing orders", count: (DATA.standing_orders||[]).length,
        sub: "always-on rules", band: "orchestration", targetTab: "infra",
        leaves: (DATA.standing_orders||[]).map(o => ({ name: o.name, sub: "scope: " + o.scope })) },
      { id: "skills",    label: "Skills",    count: DATA.skills.length,
        sub: "domain knowledge", band: "orchestration",
        leaves: DATA.skills.map(s => ({ name: s.name, sub: s.scope })) },

      { id: "ecosystem", label: "Ecosystem", count: countRepos(DATA.ecosystem),
        sub: "repos tracked", band: "execution",
        leaves: flattenRepos(DATA.ecosystem).slice(0, 20).map(r => ({ name: r.name, sub: r.section })) },
      { id: "infra",     label: "Remotes",   count: DATA.remotes.length,
        sub: "machines", band: "execution", targetTab: "infra",
        leaves: DATA.remotes.map(r => ({ name: r.name, sub: r.type })) },
      { id: "channels",  label: "Channels",  count: DATA.channels.length,
        sub: "messaging", band: "execution", targetTab: "infra",
        leaves: DATA.channels.map(c => ({ name: c.display_name || c.name, sub: c.remote || c.type })) },

      { id: "identity-self", label: "Self",
        count: (DATA.config && DATA.config.user) ? 1 : 0,
        sub: "this instance", band: "identity", targetTab: "identity",
        leaves: (DATA.config && DATA.config.user) ? [
          { name: DATA.config.user, sub: "user branch" },
          DATA.config.org ? { name: DATA.config.org, sub: "org" } : null,
          DATA.config.locale ? { name: DATA.config.locale, sub: "locale" } : null,
          DATA.config.theme ? { name: DATA.config.theme, sub: "theme" } : null,
        ].filter(Boolean) : [] },
      { id: "identity-mandants", label: "Mandants", count: DATA.mandants.length,
        sub: "recipient groups", band: "identity", targetTab: "identity",
        leaves: DATA.mandants.map(m => ({ name: m.display_name, sub: m.type })) },
      { id: "identity-calendar", label: "Calendar", count: (DATA.calendar||[]).length + (DATA.scheduled||[]).length,
        sub: "scheduled", band: "identity", targetTab: "identity",
        leaves: [...(DATA.scheduled||[]).map(s => ({ name: s.name, sub: s.channel })),
                 ...(DATA.calendar||[]).map(c => ({ name: c.title || c.id, sub: c.repeat || c.delivery_at }))] },
    ];

    const W = 900, H = 620, cx = W/2, cy = H/2;
    const hubR = 270;
    const nodeR = 48;

    const svg = svgEl("svg", { viewBox: `0 0 ${W} ${H}`, preserveAspectRatio: "xMidYMid meet" });
    const defs = svgEl("defs");
    const grad = svgEl("radialGradient", { id: "bridgeGrad", cx: "50%", cy: "50%", r: "50%" });
    grad.append(svgEl("stop", { offset: "0%", "stop-color": "#9f7fff" }));
    grad.append(svgEl("stop", { offset: "100%", "stop-color": "#7fb3ff" }));
    defs.append(grad);
    svg.append(defs);

    // Orbit rings
    svg.append(svgEl("circle", { cx, cy, r: hubR, class: "center-ring" }));
    svg.append(svgEl("circle", { cx, cy, r: hubR - 80, class: "center-ring2" }));

    // Band labels (top = orchestration, right = execution, bottom-left = identity)
    const bandPositions = {
      orchestration: { x: cx, y: cy - hubR - 18, anchor: "middle" },
      execution:     { x: cx + hubR + 28, y: cy, anchor: "start" },
      identity:      { x: cx - hubR - 28, y: cy + 4, anchor: "end" },
    };
    Object.entries(bandPositions).forEach(([name, p]) => {
      svg.append(svgEl("text", { x: p.x, y: p.y, "text-anchor": p.anchor, class: "band-label" }, [name]));
    });

    // Hubs positioned on a circle — orchestration top, execution right, identity lower-left
    // Angles chosen so hubs don't overlap and bands cluster visually
    const layout = [
      // orchestration (top arc)
      { id: "agents",          angle: -130 },
      { id: "standing-orders", angle:  -90 },
      { id: "skills",          angle:  -50 },
      // execution (right arc)
      { id: "ecosystem", angle:  -10 },
      { id: "infra",     angle:   30 },
      { id: "channels",  angle:   70 },
      // identity (lower-left arc)
      { id: "identity-calendar", angle:  130 },
      { id: "identity-mandants", angle:  170 },
      { id: "identity-self",     angle: -150 },
    ];
    const byId = Object.fromEntries(hubs.map(h => [h.id, h]));

    // Spokes first so hubs paint on top
    const spokes = {};
    const hubPos = {};
    layout.forEach(({ id, angle }) => {
      const a = angle * Math.PI / 180;
      const hx = cx + Math.cos(a) * hubR;
      const hy = cy + Math.sin(a) * hubR;
      hubPos[id] = { x: hx, y: hy, angle: a };
      const line = svgEl("line", { x1: cx, y1: cy, x2: hx, y2: hy, class: "spoke" });
      spokes[id] = line;
      svg.append(line);
    });

    // Connection overlay — real data-driven relationships, drawn as curved arcs
    const connections = [
      ["skills",    "agents",           "dispatches"],
      ["channels",  "infra",            "runs on"],
      ["identity-calendar", "identity-mandants", "delivers to"],
    ];
    connections.forEach(([a, b, label]) => {
      const pa = hubPos[a], pb = hubPos[b];
      if (!pa || !pb) return;
      // Bend outward away from center for readability
      const mx = (pa.x + pb.x) / 2;
      const my = (pa.y + pb.y) / 2;
      const dx = mx - cx, dy = my - cy;
      const len = Math.hypot(dx, dy) || 1;
      const bend = 32;
      const bx = mx + (dx / len) * bend;
      const by = my + (dy / len) * bend;
      const path = svgEl("path", {
        d: `M${pa.x},${pa.y} Q${bx},${by} ${pb.x},${pb.y}`,
        class: "map-conn",
      });
      svg.append(path);
      // Label at midpoint of the quadratic curve (≈ bx, by shifted toward chord)
      const lx = (pa.x + 2*bx + pb.x) / 4;
      const ly = (pa.y + 2*by + pb.y) / 4;
      svg.append(svgEl("text", {
        x: lx, y: ly, "text-anchor": "middle", class: "map-conn-label",
      }, [label]));
    });

    // Center
    svg.append(svgEl("circle", { cx, cy, r: 66, class: "center-circ" }));
    svg.append(svgEl("text", { x: cx, y: cy - 4, "font-size": 15, class: "center-label" }, ["The Bridge"]));
    svg.append(svgEl("text", { x: cx, y: cy + 14, "font-size": 10.5, class: "center-label", fill: "#0a0e14", opacity: 0.7 },
      ["CLAUDE.md · ecosystem.yaml"]));

    // Hubs
    layout.forEach(({ id, angle }) => {
      const hub = byId[id];
      if (!hub) return;
      const a = angle * Math.PI / 180;
      const hx = cx + Math.cos(a) * hubR;
      const hy = cy + Math.sin(a) * hubR;

      const g = svgEl("g", { class: "hub", "data-hub": id, transform: `translate(${hx},${hy})` });
      g.append(svgEl("circle", { cx: 0, cy: 0, r: nodeR,
        fill: "var(--panel2)", stroke: "var(--line2)", "stroke-width": 1.5 }));
      g.append(svgEl("text", { x: 0, y: -8, class: "label" }, [hub.label]));
      g.append(svgEl("text", { x: 0, y: 10, class: "count" }, [String(hub.count)]));
      g.append(svgEl("text", { x: 0, y: 26, class: "sub" }, [hub.sub]));
      g.addEventListener("mouseenter", () => selectHub(id));
      g.addEventListener("click", () => {
        selectHub(id);
        const tab = hub.targetTab || hub.id;
        if (["agents","skills","ecosystem","infra","identity"].includes(tab)) activate(tab);
      });
      svg.append(g);
    });

    // Layout
    const layoutEl = h("div", { class: "map-layout" }, [
      h("div", { class: "map-stage" }, svg),
      h("div", { class: "map-detail", id: "map-detail" }, [
        h("h3", { id: "md-title" }, "Hover a hub"),
        h("div", { class: "sub", id: "md-sub" }, "Click to open the full tab."),
        h("ul", { id: "md-list" }),
      ]),
    ]);
    root.append(layoutEl);

    function selectHub(id) {
      document.querySelectorAll(".hub").forEach(el =>
        el.classList.toggle("active", el.dataset.hub === id));
      Object.entries(spokes).forEach(([k, el]) => el.classList.toggle("active", k === id));
      const hub = byId[id];
      if (!hub) return;
      $("#md-title").textContent = hub.label + " · " + hub.count;
      $("#md-sub").textContent = hub.sub + (hub.leaves.length > 0 ? " · hover a hub to preview, click to open tab" : "");
      const ul = $("#md-list"); ul.innerHTML = "";
      const leaves = hub.leaves.slice(0, 12);
      if (!leaves.length) { ul.append(h("li", { class: "empty" }, "(none)")); return; }
      leaves.forEach(l => ul.append(h("li", {}, [l.name, l.sub ? h("span", { class: "small" }, l.sub) : null])));
      if (hub.leaves.length > leaves.length) {
        ul.append(h("li", { class: "empty" }, "+ " + (hub.leaves.length - leaves.length) + " more"));
      }
    }
    selectHub("agents");
  }

  function flattenRepos(eco) {
    const out = [];
    const sec = [
      ["base", eco.base || {}],
      ...Object.entries(eco.customers || {}).map(([k,v]) => [v.display_name || k, v.repos || {}]),
      ...Object.entries(eco.partners || {}).map(([k,v]) => [v.display_name || k, v.repos || {}]),
      ["internal", eco.internal || {}],
      ["personal", eco.personal || {}],
    ];
    for (const [section, repos] of sec)
      for (const [name, r] of Object.entries(repos || {}))
        if (r && typeof r === "object") out.push({ name, section });
    return out;
  }

  // =====================================================================
  // Filterable helper
  // =====================================================================
  function renderFilterable(rootSel, items, placeholder, match, card, opts = {}) {
    const root = $(rootSel);
    const input = h("input", { class: "search", type: "search", placeholder,
      oninput: (e) => render(e.target.value.toLowerCase().trim()) });
    const container = h("div", {});
    root.append(input, container);
    function render(q) {
      container.innerHTML = "";
      const filtered = q ? items.filter(x => match(x, q)) : items.slice();
      if (!filtered.length) { container.append(h("div", { class: "empty" }, "No matches.")); return; }
      if (opts.groupBy) {
        const groups = {};
        filtered.forEach(x => { const g = opts.groupBy(x); (groups[g] = groups[g] || []).push(x); });
        const order = (opts.groupOrder || Object.keys(groups)).filter(g => groups[g]);
        const tail = Object.keys(groups).filter(g => !order.includes(g));
        [...order, ...tail].forEach(g => {
          container.append(h("h3", { class: "group-h" }, (opts.groupLabel ? opts.groupLabel(g) : g) + " · " + groups[g].length));
          const grid = h("div", { class: "grid col-wide" });
          groups[g].forEach(x => grid.append(card(x)));
          container.append(grid);
        });
      } else {
        const grid = h("div", { class: "grid col-wide" });
        filtered.forEach(x => grid.append(card(x)));
        container.append(grid);
      }
    }
    render("");
  }

  // ---- Theme toggle ----
  const THEME_KEY = "bridge-theme";
  function applyTheme(t) {
    document.documentElement.setAttribute("data-theme", t);
    localStorage.setItem(THEME_KEY, t);
    const btn = document.getElementById("theme-toggle");
    if (btn) btn.textContent = t === "light" ? "☀ light" : "◐ dark";
  }
  applyTheme(localStorage.getItem(THEME_KEY) || "dark");
  document.getElementById("theme-toggle").addEventListener("click", () => {
    const cur = document.documentElement.getAttribute("data-theme") || "dark";
    applyTheme(cur === "light" ? "dark" : "light");
  });

  // ---- Keyboard shortcuts ----
  document.addEventListener("keydown", (e) => {
    if (e.metaKey || e.ctrlKey || e.altKey) return;
    const tag = (e.target.tagName || "").toLowerCase();
    if (tag === "input" || tag === "textarea") {
      if (e.key === "Escape") e.target.blur();
      return;
    }
    if (e.key === "t") applyTheme(
      (document.documentElement.getAttribute("data-theme") || "dark") === "light" ? "dark" : "light");
    else if (e.key === "/") {
      const sec = document.querySelector("main > section:not([hidden])");
      const inp = sec && sec.querySelector("input.search");
      if (inp) { inp.focus(); inp.select(); e.preventDefault(); }
    } else if (/^[1-9]$/.test(e.key)) {
      const idx = parseInt(e.key, 10) - 1;
      if (TABS[idx]) activate(TABS[idx].id);
    }
  });

  // init
  const initial = (location.hash || "#overview").slice(1);
  activate(TABS.find(t => t.id === initial) ? initial : "overview");
})();
</script>
</body>
</html>
"""


def main() -> None:
    data = build_data()
    payload = json.dumps(data, ensure_ascii=False, default=str)
    payload = payload.replace("</script>", "<\\/script>")
    html = TEMPLATE.replace("__DATA__", payload)
    OUT.write_text(html, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}  ({len(html):,} bytes)")
    print(
        f"  agents={len(data['agents'])} "
        f"standing_orders={len(data['standing_orders'])} skills={len(data['skills'])} "
        f"remotes={len(data['remotes'])} channels={len(data['channels'])} "
        f"scheduled={len(data['scheduled'])} bots={len(data['bots'])} "
        f"projects={len(data['projects'])} mandants={len(data['mandants'])} "
        f"personas={len(data['personas'])} calendar={len(data['calendar'])} "
        f"themes={len(data['themes'])}"
    )


if __name__ == "__main__":
    main()
