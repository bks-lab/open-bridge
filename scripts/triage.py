#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""What each open task and inbox item is about, whether it can go, and who does it.

    triage.py run [--fresh] [--json]

For every task under work/tasks/ that is not done (streams never close, so they are left out), every
open inbox item and, with `--view`, every board, application and issue row of the cockpit's view (read
with the issue's text or the application's STATUS.md), one line each:

- `gist`: what it is about, one line;
- `verdict`: for a task close|continue|waiting|stale|unclear (the task check's verdict wins where it
  judged the task), for an inbox item close|keep|waiting|unclear;
- `doer`: ai|you|either, with `effort` small|medium|large for the AI and a short `why`;
- `level`: for what an AI may do, how complex it is (0 to 3, model_route.LEVELS), from the same call, and
  `jev`: Jev's score of the same when cockpit.launch_model.triage_jev is on. The cockpit picks the model
  an agent starts with from these (launch.py), so a start needs no judge of its own.

The evidence is the task check's (`task.py review`: STATUS.md, log rows, GitHub states, the task's open
inbox items) plus each inbox item's own fields. The mechanical model tier answers in batches; an item
reaches a model only when its evidence changed or its answer is older than `work.review.max_age_days`.
Hard rules stand over every answer: an inbox gate `only-you`, a question or decision put to the person,
and anything outbound (send, publish, merge, deploy, pay, credentials) is the person's. Never changes a
task or an item. The cache and the last run live in .bridge/triage.json, which the dashboard reads.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import importlib.util
import json
import re
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = Path(".bridge") / "triage.json"
PROMPT_VERSION = 3              # 2: the level for the model an agent starts with; 3: the topic, a gist beyond the title
CHUNK = 20                     # items per model call: small batches keep a small model reliable
BUDGET_SEC = 280               # the dashboard gives a run 300 s
JEV_MIN_LEFT_SEC = 60          # Jev rates only while this much of the budget is left (the rest waits for the next run)
JEV_TIMEOUT_SEC = 15           # one Jev call; it answers in well under a second
TASK_VERDICTS = ("close", "continue", "waiting", "stale", "unclear")
INBOX_VERDICTS = ("close", "keep", "waiting", "unclear")
DOERS = ("ai", "you", "either")
EFFORTS = ("small", "medium", "large")
# what kind of work an item is, as a label on its row; machine words, the page names them in its language
TOPICS = ("decision", "reply", "research", "bug", "build", "docs", "ops", "review", "admin", "money", "meeting",
          "application", "idea")
GIST_MAX = 90
# outbound or irreversible: never the AI's to do, whatever it answers (rules/, CLAUDE.md). The words cover
# English and German task texts; a fork that writes in another language adds its verbs here. A safety net
# over free text, so it errs towards "yours".
OUTBOUND = re.compile(r"\b(send|senden|versend\w*|abschick\w*|e-?mail an|mail an|publish\w*|veröffentlich\w*|post(en)?\b|"
                      r"merge\w*|mergen|deploy\w*|ausroll\w*|zahl\w*|überweis\w*|bezahl\w*|pay\w*|credential\w*|"
                      r"secret\w*|token anleg\w*|kündig\w*|unterschreib\w*|sign\b)", re.I)

PROMPT = """You sort the open work of one person so they see at a glance what each item is about, whether it can be
closed, and whether an AI coding agent with repository and shell access could do it instead of them. Today is {today}.

For every item answer:
- gist: what it is about, one short line in {language}, at most 80 characters, no ID, no dash as punctuation. Say
  what the title leaves out (the thing concerned, the reason, or the next step) and never repeat the title.
- topic: what kind of work it is, one of {topics}.
  A "tracker item" is a board card, an issue, an application or a date someone else keeps; judge it like an inbox
  item.
- verdict: for a task one of close (the evidence shows it is done or moot), continue, waiting (on a person or an
  event still pending), stale (no activity for {stale_days} days and nothing pending), unclear; for an inbox item
  one of close (what it reports is resolved or answered, its condition holds, or a log row says it is done), keep,
  waiting, unclear.
- doer: ai when an agent can finish it alone (code, docs, analysis, config in the repositories, checks), you when
  it needs the person (a decision, an answer only they have, a meeting, a signature, anything sent to others, any
  merge, deploy, payment or credential), either when an agent can prepare it and the person only confirms.
  Anything that sends, publishes, merges, deploys, pays or creates credentials is never ai.
- effort: for doer ai or either, small (under an hour), medium (a few hours), large (more); else null.
- level: for doer ai or either, how complex the work is for the agent, else null:
{levels}
- why: a few words in {language} why that doer, e.g. "only your yes is missing", "code in the repo, tests exist".
- reason: one sentence in {language} for the verdict, naming the evidence.

Answer with a JSON array only, one object per item, using the item's key:
[{{"key": "<key>", "gist": "...", "topic": "...", "verdict": "...", "doer": "ai|you|either", "effort": "small|medium|large|null", "level": 0, "why": "...", "reason": "..."}}]

Items:

{items}
"""


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules.setdefault(name, mod)
    spec.loader.exec_module(mod)
    return mod


def _task():
    return sys.modules.get("bridge_task") or _load("bridge_task", ROOT / "scripts" / "task.py")


def _clip(text, n: int) -> str:
    text = " ".join(str(text or "").split())
    return text if len(text) <= n else text[: n - 1].rstrip() + "…"


def open_task_slugs(root: Path) -> list:
    """Every task under work/tasks/ whose status is not done; `_` folders skipped."""
    b = _task()._briefing()
    out = []
    for path in sorted((root / "work" / "tasks").glob("*/STATUS.md")):
        if path.parent.name.startswith("_"):
            continue
        fm = b._frontmatter(path.read_text(encoding="utf-8"))
        if str(fm.get("status") or "") != "done":
            out.append(path.parent.name)
    return out


def inbox_evidence(root: Path) -> list:
    try:
        items = _task()._module("inbox", ROOT / "scripts" / "inbox.py").Inbox(
            root / "work" / "inbox", actor="triage").open_items()
    except Exception:  # noqa: BLE001 - no inbox, nothing to sort
        return []
    out = []
    for i in items:
        ev = {"kind": i.kind, "gate": i.gate, "urgency": i.urgency, "created": str(i.created or ""),
              "summary": _clip(i.summary, 200), "detail": _clip(i.detail, 400), "task": i.task, "state": i.state,
              "closes_when": json.dumps(i.closes_when, ensure_ascii=False, default=str)[:200] if i.closes_when else None,
              "action": (i.action or {}).get("label") if isinstance(i.action, dict) else None,
              "events": [e.verb for e in i.events][-6:]}
        out.append({"key": f"inbox:{i.id}", "kind": "inbox", "title": _clip(i.summary, 120) or i.id, "evidence": ev})
    return out


GITHUB_REF = re.compile(r"^([A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+)#(\d+)$")


def tracker_items(root: Path, view: Path | None, run) -> list:
    """The rows of the cockpit's view that come from a tracker (a `ref`, no task, no inbox item): a board card, an
    issue, an application, a date. The evidence is the row itself, the issue's state and the start of its text
    (one GraphQL call for all), and a local STATUS.md the row links to. A missing or broken view is none."""
    try:
        data = json.loads(Path(view).read_text(encoding="utf-8")) if view else {}
        v = data.get("view", data) if isinstance(data, dict) else {}
        rows = [r for b in v.get("buckets") or [] for r in b.get("rows") or [] if isinstance(r, dict)]
    except (OSError, ValueError, AttributeError, TypeError):
        return []
    seen, picked = set(), []
    for r in rows:
        if r.get("ref") and not r.get("task") and not r.get("inbox_id") and r.get("key") and r["key"] not in seen:
            seen.add(r["key"])
            picked.append(r)
    refs = [(m.group(1), int(m.group(2))) for r in picked if (m := GITHUB_REF.match(str(r["ref"])))]
    states = _task().resolve_refs(refs, run, body=True) if refs else {}
    out = []
    for r in picked:
        ev = {"ref": r["ref"], "sources": list(r.get("sources") or []), "why": list(r.get("why") or [])[:4],
              "area": r.get("area"), "priority": r.get("priority"), "due": r.get("due")}
        st = states.get(str(r["ref"]))
        if st and st.get("state") != "unknown":
            ev.update(state=("MERGED" if st.get("merged") else st.get("state")), text=st.get("body") or None)
        url = str(r.get("url") or "")
        if url.endswith(".md") and "://" not in url:
            path = (root / url).resolve()
            if path.is_file() and root.resolve() in path.parents:
                body = re.sub(r"\A---\n.*?\n---\n", "", path.read_text(encoding="utf-8"), flags=re.S)
                ev["text"] = _clip(body, 600)
        out.append({"key": r["key"], "kind": "track", "title": _clip(r.get("title"), 120) or r["key"], "evidence": ev})
    return out


def _task_items(root: Path, run) -> list:
    t = _task()
    slugs = open_task_slugs(root)
    if not slugs:
        return []
    out = []
    for g in t.gather(root, slugs, run):
        out.append({"key": f"task:{g['slug']}", "kind": "task", "title": g["title"], "evidence": g["evidence"],
                    "block": t._task_block(g).replace(f"## {g['slug']}", f"## task:{g['slug']}", 1)})
    return out


def _block(item: dict) -> str:
    if item.get("block"):
        return item["block"]
    ev = item["evidence"]
    if item["kind"] == "track":
        lines = [f"## {item['key']}", f"type: tracker item, title: {item['title']}"]
        for k in ("ref", "state", "area", "priority", "due", "text"):
            if ev.get(k):
                lines.append(f"{k}: {ev[k]}")
        for k in ("sources", "why"):
            if ev.get(k):
                lines.append(f"{k}: " + ", ".join(str(x) for x in ev[k]))
        return "\n".join(lines)
    lines = [f"## {item['key']}", f"type: inbox item, title: {item['title']}"]
    for k in ("kind", "gate", "urgency", "created", "state", "task", "detail", "closes_when", "action"):
        if ev.get(k):
            lines.append(f"{k}: {ev[k]}")
    if ev.get("events"):
        lines.append("events: " + ", ".join(ev["events"]))
    return "\n".join(lines)


# why a hard rule took the item from the AI, in the Bridge's language (rules/language-policy.md section 3:
# one table per language, identical keys, English the fallback)
WHY = {
    "en": {"only_you": "only you: gate only-you", "asked": "a question or decision put to you",
           "outbound": "goes out: your click"},
    "de": {"only_you": "nur du: Tor only-you", "asked": "Frage oder Entscheidung an dich",
           "outbound": "geht nach außen: dein Klick"},
}


def why_words(cfg: dict) -> dict:
    lang = cfg.get("language")
    code = str((lang.get("conversation") if isinstance(lang, dict) else lang) or "en").strip().lower()
    return WHY["de" if code.startswith("de") else "en"]


def _rules(item: dict, got: dict, words: dict | None = None) -> dict:
    words = words or WHY["en"]
    """Hard rules over the model: the person's gate, a question to the person, anything outbound."""
    ev = item["evidence"]
    text = " ".join(str(x) for x in (item["title"], ev.get("summary"), ev.get("detail"), ev.get("next"), ev.get("headline"),
                                     " ".join(ev.get("steps") or []), ev.get("action")) if x)
    if item["kind"] == "inbox" and ev.get("gate") == "only-you":
        return {**got, "doer": "you", "effort": None, "why": got.get("why") if got.get("doer") == "you" else words["only_you"]}
    if item["kind"] == "inbox" and ev.get("kind") in ("question", "decision") and got.get("doer") == "ai":
        return {**got, "doer": "you", "effort": None, "why": words["asked"]}
    if got.get("doer") == "ai" and OUTBOUND.search(text):
        return {**got, "doer": "either", "why": words["outbound"]} if got.get("effort") else \
            {**got, "doer": "you", "why": words["outbound"]}
    return got


def _clean(item: dict, raw: dict | None, model: str | None, words: dict | None = None) -> dict:
    raw = raw or {}
    verdicts = TASK_VERDICTS if item["kind"] == "task" else INBOX_VERDICTS
    verdict = str(raw.get("verdict") or "").lower()
    doer = str(raw.get("doer") or "").lower()
    effort = str(raw.get("effort") or "").lower()
    level = raw.get("level")
    topic = str(raw.get("topic") or "").lower()
    got = {"gist": _clip(raw.get("gist") or item["title"], GIST_MAX),
           "topic": topic if topic in TOPICS else None,
           "level": level if isinstance(level, int) and not isinstance(level, bool) and 0 <= level <= 3 else None,
           "verdict": verdict if verdict in verdicts else "unclear",
           "doer": doer if doer in DOERS else "either",
           "effort": effort if effort in EFFORTS and doer in ("ai", "either") else None,
           "why": _clip(raw.get("why"), 80), "reason": _clip(raw.get("reason"), 300), "model": model if raw else None}
    got = _rules(item, got, words)
    return {**got, "level": got["level"] if got["doer"] in ("ai", "either") else None, "jev": None}


def _model_route():
    _task()                     # task.py puts scripts/ on the path
    from lib import model_route
    from lib.bridge_cockpit import launch
    return model_route, launch


def _real_jev(root: Path):
    """Jev as the cockpit reaches it, or None when it is off or has no key."""
    try:
        from lib.bridge_cockpit import jev
        from lib.bridge_cockpit.config import load_web_config
        cfg = load_web_config(root)
        if not cfg.jev_enabled:
            return None
        key = jev.resolve_key(ref=cfg.jev_key_ref)
        return lambda payload: jev.call_api(payload, key, timeout=JEV_TIMEOUT_SEC)
    except Exception:      # noqa: BLE001  no Jev is no level of Jev, never a failed check
        return None


def _rate_with_jev(root: Path, items: list, entries: dict, jev, started: float) -> int:
    """Jev's score for every item an AI may do that has none yet, or one of another Jev version; returns the
    calls made. A batch runs only while the check has JEV_MIN_LEFT_SEC of its budget left, and a failing
    batch keeps what the others gave: the Haiku level stays wherever Jev gave nothing."""
    mr, launch = _model_route()
    settings = launch.file_settings(root)
    if not (settings["enabled"] and settings["triage_jev"]):
        return 0
    version = settings["jev_model"]
    todo = [it for it in items if (entries.get(it["key"]) or {}).get("doer") in ("ai", "either")
            and (entries[it["key"]].get("jev") is None or entries[it["key"]].get("jev_model") != version)]
    judge = (jev or _real_jev(root)) if todo else None
    calls = 0
    for i in range(0, len(todo) if judge else 0, mr.MAX_ITEMS):
        if BUDGET_SEC - (time.monotonic() - started) < JEV_MIN_LEFT_SEC:
            break
        batch = todo[i:i + mr.MAX_ITEMS]
        asked = [{"id": f"k{n}", "title": f"{it['title']}: {entries[it['key']].get('gist') or ''}", "kind": it["kind"]}
                 for n, it in enumerate(batch)]
        calls += 1
        try:
            scores = mr.jev_scores(asked, settings, judge)
        except Exception:      # noqa: BLE001  this batch keeps its Haiku level, the next may still answer
            continue
        for n, it in enumerate(batch):
            if f"k{n}" in scores:
                entries[it["key"]].update(jev=scores[f"k{n}"], jev_model=version)
    return calls


def _load_cache(root: Path) -> dict:
    try:
        data = json.loads((root / CACHE).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) and isinstance(data.get("items"), dict) else {"items": {}}
    except (OSError, ValueError):
        return {"items": {}}


def _save_cache(root: Path, cache: dict) -> None:
    path = root / CACHE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps({"version": 1, **cache}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)


def _check_verdicts(root: Path) -> dict:
    """The task check's last verdicts (task.py review): it read GitHub and judged closer."""
    try:
        last = json.loads((root / ".bridge" / "task-review.json").read_text(encoding="utf-8")).get("last") or {}
    except (OSError, ValueError, AttributeError):
        return {}
    return {x["slug"]: x for x in last.get("tasks") or [] if isinstance(x, dict) and x.get("slug") and not x.get("kept")}


def triage(root: Path, *, fresh: bool = False, run=None, now: dt.datetime | None = None, save: bool = True,
           jev=None, view: Path | None = None) -> dict:
    t = _task()
    run = run or t.default_run
    now = now or dt.datetime.now()
    started = time.monotonic()
    cfg = t._config(root)
    rcfg = t._review_cfg(cfg)
    language = t._language(cfg)
    words = why_words(cfg)
    model = t.service_model(root, "triage", t.tier_model(cfg, "mechanical"))
    items = _task_items(root, run) + inbox_evidence(root) + tracker_items(root, view, run)
    settings = json.dumps([language, model, rcfg["stale_days"], PROMPT_VERSION,
                           t.ai.load(root, "triage"), rcfg["command"]], sort_keys=True)
    for it in items:
        it["hash"] = hashlib.sha256((json.dumps(it["evidence"], sort_keys=True, default=str) + settings)
                                    .encode("utf-8")).hexdigest()[:16]
    cache = _load_cache(root)
    entries = cache["items"]
    need = []
    for it in items:
        old = entries.get(it["key"])
        try:
            age = (now - dt.datetime.fromisoformat(str((old or {}).get("at")))).days
        except ValueError:
            age = rcfg["max_age_days"] + 1
        if fresh or not old or old.get("hash") != it["hash"] or age > rcfg["max_age_days"]:
            need.append(it)
    cost, cost_known, calls, answered = 0.0, True, 0, {}
    for i in range(0, len(need), CHUNK):
        left = BUDGET_SEC - (time.monotonic() - started)
        if left < 15:
            break
        chunk = need[i:i + CHUNK]
        prompt = PROMPT.format(today=now.date().isoformat(), language=language, stale_days=rcfg["stale_days"],
                               topics=", ".join(TOPICS),
                               levels="\n".join(f"  {n}: {d}" for n, d in enumerate(_model_route()[0].LEVELS)),
                               items="\n\n".join(_block(x) for x in chunk))
        res = t.ask_service(root, "triage", rcfg["command"], model, prompt, run, int(min(left, 150)))
        calls += 1
        if res["cost"] is None:
            cost_known = False
        else:
            cost += float(res["cost"])
        used = (res["used"] or [model])[0]
        keys = {x["key"]: x for x in chunk}
        for raw in res["items"]:
            key = str(raw.get("key") or "")
            if key in keys:
                answered[key] = _clean(keys[key], raw, used, words)
        for x in chunk:
            if x["key"] in answered:
                entries[x["key"]] = {**answered[x["key"]], "hash": x["hash"], "at": now.isoformat(timespec="seconds")}
        if save:
            _save_cache(root, cache)
    jev_calls = _rate_with_jev(root, items, entries, jev, started)
    if jev_calls and save:
        _save_cache(root, cache)
    checked = _check_verdicts(root)
    out = []
    for it in items:
        if it["key"] in answered:
            got, cached = {**answered[it["key"]], "jev": (entries.get(it["key"]) or {}).get("jev")}, False
        elif it not in need and it["key"] in entries:
            got, cached = {k: v for k, v in entries[it["key"]].items() if k not in ("hash", "at")}, True
        else:
            got, cached = _clean(it, None, None, words), False
        row = {"key": it["key"], "kind": it["kind"], "title": it["title"], **got, "cached": cached, "verdict_from": "triage"}
        slug = it["key"].split(":", 1)[1]
        if it["kind"] == "task" and slug in checked:      # the check read GitHub: its verdict stands
            c = checked[slug]
            row.update(verdict=c.get("verdict") or row["verdict"], reason=c.get("reason") or row["reason"],
                       verdict_from="check")
            if c.get("resolved"):
                row["verdict"] = "close"
        out.append(row)
    counts = {"close": sum(1 for x in out if x["verdict"] == "close"),
              "ai": sum(1 for x in out if x["doer"] == "ai"),
              "you": sum(1 for x in out if x["doer"] == "you"),
              "unclear": sum(1 for x in out if x["verdict"] == "unclear")}
    result = {"items": out, "counts": counts, "cost_usd": round(cost, 6), "cost_known": cost_known, "calls": calls,
              "model": model, "jev_calls": jev_calls, "at": now.isoformat(timespec="seconds"), "duration_sec": round(time.monotonic() - started, 1)}
    if save:
        cache["last"] = result
        _save_cache(root, cache)
    return result


def last(root: Path) -> dict | None:
    data = _load_cache(root).get("last")
    return data if isinstance(data, dict) else None


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--view", type=Path, default=None,
                    help="the cockpit's view.json: its board, application and issue rows are sorted too")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="sort every open task and inbox item (cached per item)")
    r.add_argument("--fresh", action="store_true", help="ask again for every item")
    r.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    result = triage(args.root.resolve(), fresh=args.fresh, view=args.view)
    if args.json:
        json.dump(result, sys.stdout, ensure_ascii=False)
        print()
    else:
        for x in result["items"]:
            print(f"{x['verdict']:<9} {x['doer']:<6} {x['effort'] or '':<6} {x['key']:<60} {x['gist']}")
        c = result["counts"]
        print(f"{len(result['items'])} items: {c['close']} closable, {c['ai']} for the AI, {c['you']} need you, "
              f"{c['unclear']} unclear; {result['calls']} call(s), {result['cost_usd']:.4f} USD")
    return 0


if __name__ == "__main__":
    sys.exit(main())
