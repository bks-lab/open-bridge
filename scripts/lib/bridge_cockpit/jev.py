# SPDX-License-Identifier: MIT
"""Jev page of the cockpit: the rows the dashboard holds right now go to TypeSafe's
Jev model (POST https://api.typesafe.ai/v1/systemone), which answers typed judgments per task:
urgency, impact and effort as Scores, "only the user can do this" as a Noul, and one Choice
across all tasks for what to do first. Code turns those into the plan the page animates.

An integration you switch on: nothing here runs unless bridge-config.yaml says
`integrations.typesafe: {enabled: true, key_ref: keychain://<service>/<account>}`. Without it the
page shows no Jev tab, `POST /api/jev/run` answers 404 jev_off, and everything else works as before.
`status(app)` says enabled and ready (a key is there) for every place that wants to use Jev.

Two endpoints, dispatched from server.py: `POST /api/jev/run` for the Jev tab and `POST /api/jev/rank` for
the order of a page that asks for one (`jev:` in the profile, see rank below); the state lives lazily on the App as
`app._jev`. The API key never reaches the page. It comes from the environment (`TYPESAFE_API_KEY`)
or from the configured keychain reference, read with a fixed argv of /usr/bin/security only when a
rating runs; the readiness check asks the keychain whether the entry exists, without `-w`.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import socket
import subprocess
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any, Callable

from . import prio
from .config import parse_keychain_ref
from .store import atomic_write_json, read_json
from .text import TABLES

API_URL = "https://api.typesafe.ai/v1/systemone"
MODEL = "jev-1.14.0"   # a versioned id, never an alias: an alias moves and the answers with it
# the rows of one request: TypeSafe documents no cap on the questions of a request, only on its body (32 MiB,
# docs.typesafe.ai/api/errors), so a read-in of the work view's points goes in one request; above this many rows
# (four questions each) a read-in still goes in batches of this size, at most MAX_BATCHES, as a guard
MAX_TASKS = 60
TIMEOUT_S = 90
ROW_FIELDS = ("title", "why", "priority", "urgency", "due", "area", "gate", "bucket", "section", "task_type",
              "inbox_state")

# the questions in the dashboard's language; {who} is the person the dashboard belongs to
# (cockpit.person_name), else a neutral word, so no instance's name lives here
TEXT = {code: TABLES[code]["jev"] for code in TABLES}   # the words live in text.py


LEVELS = 3     # every score has four criteria, levels 0 to 3


class JevError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


# ------------------------------------------------------------------ state and questions

def collect_tasks(model: dict | None, limit: int = MAX_TASKS) -> list[dict]:
    """The rows the dashboard shows now (briefing sections, then task rows), each once, trimmed
    to the fields that carry meaning. Ids are short and stable within one request: t1, t2, ..."""
    model = model or {}
    rows: list[dict] = []
    seen: set[str] = set()
    for sec in model.get("sections") or []:
        for r in (sec or {}).get("rows") or []:
            rows.append(r)
    rows.extend(model.get("task_rows") or [])
    out: list[dict] = []
    for r in rows:
        if not isinstance(r, dict) or not r.get("title"):
            continue
        key = str(r.get("key") or r.get("title"))
        if key in seen:
            continue
        seen.add(key)
        item = {"id": f"t{len(out) + 1}", "key": key}
        for f in ROW_FIELDS:
            v = r.get(f)
            if v not in (None, "", [], {}):
                item[f] = v
        out.append(item)
        if len(out) >= limit:
            break
    return out


def build_request(tasks: list[dict], today: str, who: str | None = None, about: str | None = None,
                  lang: str = "en", criteria: dict | None = None, model: str | None = None) -> dict:
    """The questions for Jev; `who` names the person (else a neutral word), `about` describes them,
    `criteria` ({urgency, impact, effort}: four levels each, integrations.typesafe.criteria) replaces
    the neutral defaults below. `model` (integrations.typesafe.model) replaces MODEL."""
    tx = {**TEXT.get(lang, TEXT["en"]), **(criteria or {})}
    names = {"who": who or tx["who"], "who_subject": who or tx["who_subject"]}
    say = lambda key, **kw: tx[key].format(**names, **kw)      # noqa: E731
    state = {tx["today"]: today, "person": about or tx["about"].format(**names).capitalize(),
             tx["tasks"]: [{k: v for k, v in t.items() if k != "key"} for t in tasks]}
    q: dict[str, Any] = {}
    for i, t in enumerate(tasks):
        ref = f"`{tx['tasks']}[{i}]`"
        q[f"{t['id']}.urgency"] = {"type": "score", "criteria": tx["urgency"], "instructions": say("q_urgency", ref=ref)}
        q[f"{t['id']}.impact"] = {"type": "score", "criteria": tx["impact"], "instructions": say("q_impact", ref=ref)}
        q[f"{t['id']}.effort"] = {"type": "score", "criteria": tx["effort"], "instructions": say("q_effort", ref=ref)}
        q[f"{t['id']}.only_me"] = {"type": "noul", "instructions": say("q_only_me", ref=ref),
                                   "criteria": {"true": say("only_me_true"), "false": say("only_me_false")}}
    if tasks:
        q["first"] = {"type": "choice", "instructions": say("q_first"),
                      "criteria": {t["id"]: t.get("title", "")[:160] for t in tasks}}
    return {"model": model or MODEL, "state": state, "questions": q}


def _level(answer: dict | None, top: int) -> float:
    """Score answer to 0..1 (score / top level); a missing answer counts as the middle"""
    if not _rated(answer):
        return 0.5
    return max(0.0, min(1.0, float(answer["score"]) / top))


def _rated(answer: Any) -> bool:
    return isinstance(answer, dict) and isinstance(answer.get("score"), (int, float)) and not isinstance(answer["score"], bool)


def plan_from(tasks: list[dict], response: dict) -> dict:
    """Jev's answers to a plan: per task the judgments plus a priority in code. The weights are
    policy and stay here, the raw judgments go to the page too, so it can show both."""
    ans = (response or {}).get("answers") or {}
    first = ans.get("first") or {}
    probs = first.get("probabilities") or {}
    items = []
    for t in tasks:
        tid = t["id"]
        u = _level(ans.get(f"{tid}.urgency"), LEVELS)
        im = _level(ans.get(f"{tid}.impact"), LEVELS)
        ef = _level(ans.get(f"{tid}.effort"), LEVELS)
        me = ans.get(f"{tid}.only_me") or {}
        only_me = float(me.get("noul", 0.5)) if isinstance(me.get("noul"), (int, float)) else 0.5
        p_first = float(probs.get(tid, 0.0) or 0.0)
        priority = 0.42 * u + 0.38 * im + 0.12 * (1 - ef) + 0.08 * min(1.0, p_first * 3)
        conf = [float(a["confidence"]) for a in (ans.get(f"{tid}.urgency"), ans.get(f"{tid}.impact"))
                if isinstance(a, dict) and isinstance(a.get("confidence"), (int, float))]
        if not (_rated(ans.get(f"{tid}.urgency")) and _rated(ans.get(f"{tid}.impact"))):
            quad = None          # not rated: no square (Not rated yet), never the middle read as urgent and important
        elif u >= 0.5 and im >= 0.5:
            quad = "now"
        elif im >= 0.5:
            quad = "plan"
        elif u >= 0.5:
            quad = "hand"
        else:
            quad = "drop"
        items.append({"id": tid, "key": t["key"], "title": t.get("title", ""), "area": t.get("area"),
                      "urgency": round(u, 3), "impact": round(im, 3), "effort": round(ef, 3),
                      "only_me": round(only_me, 3), "first": round(p_first, 3), "priority": round(priority, 3),
                      "confidence": round(sum(conf) / len(conf), 3) if conf else None, "quadrant": quad,
                      "who": "me" if only_me >= 0.5 else "delegate"})
    # Jev's direct choice of where to start leads; the rest follows the weighted priority
    pick = first.get("choice") if any(t["id"] == first.get("choice") for t in tasks) else None
    ranked = sorted(items, key=lambda x: (x["id"] != pick, -x["priority"], -x["first"]))
    for i, it in enumerate(ranked):
        it["rank"] = i + 1
    return {"items": ranked, "first": pick or (ranked[0]["id"] if ranked else None),
            "first_confidence": first.get("confidence"), "model": (response or {}).get("model"),
            "usage": (response or {}).get("usage")}


# ------------------------------------------------------------------ key and transport

def resolve_key(environ: Any = None, run: Callable[..., Any] = subprocess.run, ref: str | None = None) -> str:
    env = os.environ if environ is None else environ
    if env.get("TYPESAFE_API_KEY"):
        return env["TYPESAFE_API_KEY"].strip()
    found = parse_keychain_ref(ref)
    if found is None:
        raise JevError(503, "jev_no_key", "no key configured: integrations.typesafe.key_ref = keychain://<service>/<account>")
    service, account = found
    try:
        res = run(["/usr/bin/security", "find-generic-password", "-s", service, "-a", account, "-w"],
                  capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        raise JevError(503, "jev_no_key", "the keychain could not be read")
    if res.returncode != 0 or not res.stdout.strip():
        raise JevError(503, "jev_no_key", f"no key in the keychain under {service}/{account}")
    return res.stdout.strip()


def status(app: Any, run: Callable[..., Any] = subprocess.run) -> dict:
    """Whether Jev is switched on and has a key: {enabled, ready, reason off|no_key_ref|no_key|None}.
    Asks the keychain only whether the entry exists (no -w, no secret read); cached for 5 minutes."""
    cfg = getattr(app, "cfg", None)
    if not getattr(cfg, "jev_enabled", False):
        return {"enabled": False, "ready": False, "reason": "off"}
    env = getattr(app, "environ", None)
    env = os.environ if env is None else env
    if env.get("TYPESAFE_API_KEY"):
        return {"enabled": True, "ready": True, "reason": None}
    found = parse_keychain_ref(getattr(cfg, "jev_key_ref", None))
    if found is None:
        return {"enabled": True, "ready": False, "reason": "no_key_ref"}
    cache = getattr(app, "_jev_ready", None)
    now = time.monotonic()
    if run is subprocess.run and cache and cache[0] == found and now - cache[1] < 300:
        ok = cache[2]
    else:
        try:
            res = run(["/usr/bin/security", "find-generic-password", "-s", found[0], "-a", found[1]],
                      capture_output=True, text=True, timeout=10)
            ok = res.returncode == 0
        except (OSError, subprocess.SubprocessError):
            ok = False
        try:
            app._jev_ready = (found, now, ok)
        except AttributeError:
            pass
    return {"enabled": True, "ready": ok, "reason": None if ok else "no_key"}


def call_api(payload: dict, key: str, timeout: float = TIMEOUT_S) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    for attempt in range(3):
        req = urllib.request.Request(API_URL, data=data, method="POST",
                                     headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 529) and attempt < 2:
                time.sleep(1.5 * (attempt + 1))
                continue
            detail = e.read().decode("utf-8", "replace")[:300]
            # the status Jev answered stays: a refusal (400, 401, 403) is no failure of Jev's and never falls back
            if e.code in (429, 529):
                raise JevError(429, "jev_busy", f"Jev is busy, try again shortly: {detail}")
            if 400 <= e.code < 500:
                raise JevError(e.code, "jev_refused", f"Jev refused the request ({e.code}): {detail}")
            raise JevError(502, "jev_upstream", f"Jev answered {e.code}: {detail}")
        except (TimeoutError, socket.timeout) as e:
            raise JevError(504, "jev_timeout", f"Jev did not answer in time: {e}")
        except urllib.error.URLError as e:
            if isinstance(e.reason, (TimeoutError, socket.timeout)):
                raise JevError(504, "jev_timeout", f"Jev did not answer in time: {e.reason}")
            raise JevError(502, "jev_upstream", f"Jev is not reachable: {e}")
        except OSError as e:
            raise JevError(502, "jev_upstream", f"Jev is not reachable: {e}")
    raise JevError(429, "jev_busy", "Jev is busy, try again shortly")


# a failed read-in that a fallback may stand in for: Jev busy (429), failing (5xx), not reachable or slow (502, 504),
# or without its key (503); never a refusal of the request (4xx)
def _jev_failed(e: JevError) -> bool:
    return e.status == 429 or e.status >= 500


# ------------------------------------------------------------------ endpoint

STORE_NAME = "jev.json"


def tokens_of(usage: Any) -> dict:
    """The token counts Jev reports (usage.input_tokens, usage.output_tokens). The API names no
    price, so there is no cost here, and nothing is estimated: a missing count stays None."""
    usage = usage if isinstance(usage, dict) else {}
    out = {}
    for f in ("input_tokens", "output_tokens"):
        v = usage.get(f)
        out[f] = int(v) if isinstance(v, (int, float)) and not isinstance(v, bool) and v >= 0 else None
    return out


class JevState:
    """The last rating and today's token total; kept in jev.json beside state.json when the app has
    a state_dir, so a restart neither forgets the rating nor spends a second automatic one."""

    def __init__(self, path: Path | None = None):
        self.lock = threading.Lock()
        self.path = path
        self.digest: str | None = None
        self.result: dict | None = None
        self.day: str | None = None          # the day of the last rating
        self.today: dict = _empty_day(None)
        data = read_json(path) if path else None
        if isinstance(data, dict) and data.get("v") == 1:
            if isinstance(data.get("result"), dict):
                self.digest, self.result, self.day = data.get("digest"), data["result"], data.get("day")
            if isinstance(data.get("today"), dict):     # a page order counts here too, without a rating
                self.today = {**self.today, **data["today"]}

    def save(self) -> None:
        if self.path:
            atomic_write_json(self.path, {"v": 1, "digest": self.digest, "day": self.day, "result": self.result,
                                          "today": self.today})

    def count(self, day: str, tokens: dict, rating: bool = True, unknown: bool | None = None) -> dict:
        """Add one rating to the day's total; a new day starts from zero. A rating without a count
        is counted as `unknown`, so the total never claims more than it knows. A later batch of the
        same rating passes rating=False and says itself whether it marks the rating unknown."""
        if self.today.get("day") != day:
            self.today = _empty_day(day)
        self.today["ratings"] += 1 if rating else 0
        if unknown is None:
            unknown = tokens.get("input_tokens") is None or tokens.get("output_tokens") is None
        if unknown:
            self.today["unknown"] += 1
        self.today["input_tokens"] += tokens.get("input_tokens") or 0
        self.today["output_tokens"] += tokens.get("output_tokens") or 0
        return dict(self.today)


# the server answers each request on its own thread: two first requests at once must share one state,
# or each passes its own page gate and pays, and the loser's orders and day counter are lost
_INIT_LOCK = threading.Lock()


def _state(app) -> JevState:
    st = getattr(app, "_jev", None)
    if st is None:
        with _INIT_LOCK:
            st = getattr(app, "_jev", None)
            if st is None:
                sd = getattr(app, "state_dir", None)
                st = JevState(Path(sd) / STORE_NAME if sd else None)
                app._jev = st
    return st


def _empty_day(day: str | None) -> dict:
    """A day's counters before its first rating."""
    return {"day": day, "ratings": 0, "input_tokens": 0, "output_tokens": 0, "unknown": 0}


def _today_of(st: JevState, day: str) -> dict:
    t = st.today if st.today.get("day") == day else _empty_day(day)
    return dict(t)


def run(app, body: dict, call: Callable[[dict, str], dict] | None = None,
        key: Callable[[], str] | None = None) -> dict:
    """POST /api/jev/run {force?, cache_only?}: rates what the dashboard holds now.

    Without flags Jev runs by itself at most once per day: a rating from today answers every
    later request, also after a restart (jev.json), with `changed: true` when the rows differ
    since; the first request of a new day rates once. force always rates (the button).
    cache_only never calls Jev: rows the cache does not know answer {stale: true}.
    Every answer carries `usage` (this rating's tokens), `today` (the day's total) and
    `price: null`: the API reports tokens, not money, and nothing here estimates a price."""
    for name in body:
        if name not in ("force", "cache_only"):
            raise JevError(400, "invalid_argument", f"unknown field {str(name)[:40]}")
    force = body.get("force", False)
    cache_only = body.get("cache_only", False)
    if not isinstance(force, bool) or not isinstance(cache_only, bool):
        raise JevError(400, "invalid_argument", "force and cache_only must be true or false")
    tasks = collect_tasks(app.collector.model)
    if not tasks:
        return {"ok": True, "cached": False, "empty": True, "plan": {"items": [], "first": None}}
    day = time.strftime("%Y-%m-%d", time.localtime(app.clock() / 1000))
    cfg = getattr(app, "cfg", None)
    payload = build_request(tasks, day, who=getattr(cfg, "person_name", None), about=getattr(cfg, "jev_person", None),
                            lang=getattr(cfg, "language", "en") or "en", criteria=getattr(cfg, "jev_criteria", None),
                            model=getattr(cfg, "jev_model", None))
    digest = hashlib.sha256(json.dumps(payload, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16]
    st = _state(app)
    with st.lock:
        if not force and st.result and (st.digest == digest or st.day == day):
            # today's rating stands until the button; a changed dashboard only says so
            return {**st.result, "cached": True, "changed": st.digest != digest, "today": _today_of(st, day)}
        if cache_only and not force:
            return {"ok": True, "stale": True, "cached": False, "empty": False, "digest": digest}
        started = time.monotonic()
        response = (call or call_api)(payload, (key or resolve_key)())
        plan = plan_from(tasks, response)
        tokens = tokens_of((response or {}).get("usage"))
        result = {"ok": True, "empty": False, "digest": digest, "at_ms": int(app.clock()),
                  "took_ms": int((time.monotonic() - started) * 1000), "questions": len(payload["questions"]),
                  "plan": plan, "usage": tokens, "price": None}
        st.digest, st.result, st.day = digest, result, day
        today = st.count(day, tokens)
        st.save()
        return {**result, "cached": False, "changed": False, "today": today}


def _asks_jev(path: str, body: dict) -> bool:
    """Whether a request may call Jev: the Jev tab's run, and a page order that orders now (force or daily) with
    Jev as its ranker. Reading the kept order, or reading in with Haiku, works with Jev switched off"""
    if path != "/api/jev/rank":
        return True
    return body.get("ranker", "jev") == "jev" and (body.get("force") is True or body.get("daily") is True)


def handle_post(handler, app, path: str, body: dict, prio_call: Callable | None = None) -> None:
    if path not in ("/api/jev/run", "/api/jev/rank"):
        handler.send_error_json("not_found", "unknown endpoint")
        return
    if not getattr(app.cfg, "jev_enabled", False) and _asks_jev(path, body):
        handler.send_json(404, {"ok": False, "error": {"code": "jev_off", "message":
                                "Jev is not switched on: integrations.typesafe.enabled in bridge-config.yaml"}})
        return
    sent = {"calls": 0, "rows": 0, "model": getattr(app.cfg, "jev_model", None) or MODEL}

    def counted(payload: dict, key: str) -> dict:
        # what really leaves the machine, for the audit line: requests, rows, model
        sent["calls"] += 1
        sent["rows"] += sum(1 for q in payload.get("questions") or {} if q.endswith(".urgency"))
        sent["model"] = payload.get("model") or sent["model"]
        return call_api(payload, key)

    verb = "jev_rank" if path == "/api/jev/rank" else "jev_run"
    try:
        secret = lambda: resolve_key(ref=app.cfg.jev_key_ref)       # noqa: E731
        if path == "/api/jev/rank":
            handler.send_json(200, rank(app, body, call=counted, key=secret, prio_call=prio_call))
        else:
            handler.send_json(200, run(app, body, call=counted, key=secret))
    except JevError as e:
        handler.send_json(e.status, {"ok": False, "error": {"code": e.code, "message": e.message}})
        if not sent["calls"]:
            return                      # refused before anything left: no line
    if not sent["calls"]:
        return                          # answered from the store: nothing left the machine, no line (review C31)
    page = body.get("page") if isinstance(body.get("page"), str) else "-"
    app.actions.audit_line(verb, page[:80] if verb == "jev_rank" else "-", **sent)


# ------------------------------------------------------------------ order of a work page

# A page with `jev:` in the briefing profile (view.pages[].jev: {skip_sections, private}) gets an order on a click.
# Prio's read-in (Work through) names the points its work view shows by key (`rows`, every kind: tasks, inbox items,
# tabs, issues, meeting references, also what the triage marked); the server looks each up itself (_lookup), drops a
# key it cannot place, and holds back the sections named in skip_sections and rows whose title, detail, task, source
# (who filed an inbox item) or gist hold a `private` word (prio.rows_of). Without `rows` (the Jev view of the work tab)
# the page's own rows go, under the same two rules (pick_rows). Either way only the fields of prio.wire leave the
# machine, from the server's items; never a detail text, a path or an item id. Two rankers answer the same fields: Jev,
# or Haiku (`ranker: haiku`, prio.py, off unless cockpit.flow.prio.haiku.enabled), which needs no Jev; with
# cockpit.flow.prio.fallback haiku a Jev read-in on a click that fails (busy, 5xx, a timeout, no key; never a 4xx
# refusal) runs Haiku instead and the order says so. A point a ranker left without urgency or impact stays out of the
# order (Not rated yet). The order is kept per page in jev-pages.json, names its ranker, and the newest one wins; only a
# click (force) or the first ask of a day (daily, Jev only, never a fallback) orders anew: Haiku never runs by itself. A
# daily order that failed is kept as failed for the day, so a reload does not ask again; a click does.
PAGES_STORE = "jev-pages.json"
MAX_BATCHES = 3


def _row_key(it: dict) -> str | None:
    """The key the triage uses: an inbox row is its item, else its task"""
    if it.get("inbox"):
        return f"inbox:{it['inbox']}"
    if it.get("task"):
        return f"task:{it['task']}"
    return None


def _label(title: str) -> str:
    """A section title as a short label: what stands before a bracket"""
    return (title or "").split(" (")[0].strip()[:40]


def pick_rows(sections: list[dict], triage: dict | None, cfg: dict | None) -> tuple[list[dict], dict]:
    """The rows of a work page that go to Jev, each once (one without an inbox item or a task by its page key), and
    how many were left out and why: a skipped section, a private word. What the triage marked goes too"""
    cfg = cfg or {}
    triage = triage or {}
    skip = set(cfg.get("skip_sections") or [])
    words = [w.lower() for w in cfg.get("private") or [] if isinstance(w, str) and w.strip()]
    rows: list[dict] = []
    seen: set[str] = set()
    skipped = {"private": 0, "section": 0}
    for sec in sections or []:
        for it in sec.get("items") or []:
            if not isinstance(it, dict) or not it.get("title"):
                continue
            key = _row_key(it) or (it["key"] if isinstance(it.get("key"), str) and it["key"] else None) \
                or f"item:{sec.get('id')}:{str(it.get('title'))[:60]}"
            if key in seen:
                continue
            seen.add(key)
            if sec.get("id") in skip:
                skipped["section"] += 1
                continue
            tri = triage.get(key) or {}
            hay = " ".join(str(x or "") for x in (it.get("title"), it.get("detail"), it.get("task"), it.get("source"),
                                                   tri.get("gist"))).lower()
            if any(w in hay for w in words):
                skipped["private"] += 1
                continue
            row = {"key": key, "title": str(it["title"])[:160], "label": _label(sec.get("title") or sec.get("id") or ""),
                   "kind": "inbox" if it.get("inbox") else "task" if it.get("task") else "item"}
            row["gist"] = str(tri.get("gist") or "")[:160] or None
            if it.get("priority"):
                row["priority"] = it["priority"]
            if isinstance(it.get("state"), str) and it["state"]:
                row["status"] = it["state"]
            rows.append({k: v for k, v in row.items() if v is not None})
    return rows, skipped


def _source_of(root, item_id: str) -> str | None:
    """Who filed an inbox item (`from:` in its item.yaml)"""
    from .details import inbox_detail
    return ((inbox_detail(root, item_id, None) or {}).get("item") or {}).get("from")


def _work_page(app, page_id: str) -> tuple[dict, list[dict]] | None:
    """(jev config, sections with all their rows) of a page that asks for an order, else None"""
    view = getattr(app.collector, "view", None) or {}
    for pg in view.get("pages") or []:
        if pg.get("id") != page_id or not isinstance(pg.get("jev"), dict):
            continue
        sections = []
        for s in pg.get("sections") or []:
            found = app.collector.page_items(page_id, s["id"])
            items = found[0] if found else []
            root = getattr(app, "root", None)
            if root is not None:     # who filed an inbox item is not on its row, a private word may name it
                items = [{**it, "source": _source_of(root, it["inbox"])} if it.get("inbox") else it for it in items]
            sections.append({"id": s["id"], "kind": s.get("kind"), "title": s.get("title"), "items": items})
        return pg["jev"], sections
    return None


class PagesState:
    """The last order per page, kept beside state.json so a restart keeps it. One order runs per page
    at a time: `running` holds a lock per page, so a second request waits instead of paying again."""

    def __init__(self, path: Path | None = None):
        self.lock = threading.Lock()
        self.running: dict[str, threading.Lock] = {}
        self.path = path
        data = read_json(path) if path else None
        self.orders: dict = data["orders"] if isinstance(data, dict) and isinstance(data.get("orders"), dict) else {}
        # the day a page's daily order failed: no reload asks again that day, only a click does
        self.failed: dict = data["failed"] if isinstance(data, dict) and isinstance(data.get("failed"), dict) else {}

    def save(self) -> None:
        if self.path:
            atomic_write_json(self.path, {"v": 1, "orders": self.orders, "failed": self.failed})

    def gate(self, page_id: str) -> threading.Lock:
        """The lock an order of this page runs under; called with self.lock held"""
        return self.running.setdefault(page_id, threading.Lock())


def _pages_state(app) -> PagesState:
    st = getattr(app, "_jev_pages", None)
    if st is None:
        with _INIT_LOCK:
            st = getattr(app, "_jev_pages", None)
            if st is None:
                sd = getattr(app, "state_dir", None)
                st = PagesState(Path(sd) / PAGES_STORE if sd else None)
                app._jev_pages = st
    return st


# title and confidence stay for the matrix of the Jev view (a dot is named and ringed by them), reason for Haiku's
# half sentence of why; the order lives only in jev-pages.json beside the state, and a title is what left the machine
ORDER_FIELDS = ("key", "rank", "title", "urgency", "impact", "effort", "only_me", "first", "priority", "confidence",
                "quadrant", "who", "reason")


def rank(app, body: dict, call: Callable[[dict, str], dict] | None = None,
         key: Callable[[], str] | None = None, prio_call: Callable | None = None) -> dict:
    """POST /api/jev/rank {page, force?, daily?, ranker?, rows?}: the last order of a work page; with force it is
    ordered anew by the ranker (jev, the default, or haiku) over the page's `rows` (Prio's read-in), else over the
    page's own rows. daily is the Jev view of the work tab: the first request of a day orders by itself with Jev,
    every later one that day answers the kept order, as the Jev tab's run does; Haiku never orders by itself"""
    for name in body:
        if name not in ("page", "force", "daily", "ranker", "rows"):
            raise JevError(400, "invalid_argument", f"unknown field {str(name)[:40]}")
    page_id, force, daily = body.get("page"), body.get("force", False), body.get("daily", False)
    ranker, rows = body.get("ranker", "jev"), body.get("rows")
    if not isinstance(page_id, str) or not isinstance(force, bool) or not isinstance(daily, bool):
        raise JevError(400, "invalid_argument", "page must be text, force and daily true or false")
    if ranker not in prio.RANKERS:
        raise JevError(400, "invalid_argument", f"ranker must be one of {', '.join(prio.RANKERS)}")
    if rows is not None and not isinstance(rows, list):
        raise JevError(400, "invalid_argument", "rows must be a list")
    found = _work_page(app, page_id)
    if found is None:
        raise JevError(404, "not_found", "no page with jev: under that id")
    st = _pages_state(app)
    day = time.strftime("%Y-%m-%d", time.localtime(app.clock() / 1000))
    auto = daily and ranker == "jev"
    with st.lock:
        kept = st.orders.get(page_id)
        failed = st.failed.get(page_id) == day
        if not force and (not auto or failed or (kept and kept.get("day") == day)):
            return {"ok": True, "page": page_id, "order": kept, "today": _today_of(_state(app), day),
                    "failed_today": failed}
        gate = st.gate(page_id)
    with gate:      # another tab or a reconnect asking meanwhile waits here and takes the fresh order
        with st.lock:
            fresh = st.orders.get(page_id)
        if fresh is not kept and _fresh_fits(fresh, ranker, force, day):
            return {"ok": True, "page": page_id, "order": fresh, "today": _today_of(_state(app), day)}
        try:
            return _rank_now(app, page_id, found, day, call, key, ranker, rows, prio_call, click=force)
        except JevError:
            if not force:           # the daily order failed: a reload that day reads what there is, a click asks
                with st.lock:
                    st.failed[page_id] = day
                    st.save()
            raise


def _fresh_fits(fresh: dict | None, ranker: str, force: bool, day: str) -> bool:
    """Whether an order that landed while a request waited at the gate answers it: on a click only one of the ranker
    clicked (a Haiku click is never answered by Jev's order), else today's"""
    if fresh is None:
        return False
    if force:
        return fresh.get("ranker", "jev") == ranker
    return fresh.get("day") == day


REF_RE = re.compile(r"^[\w.-]+/[\w.-]+#\d+\Z")
INBOX_DAY_RE = re.compile(r"^(\d{4})(\d{2})(\d{2})-")


def _kind_of(row: dict) -> str:
    """The kind of a server row as a read-in names it (the page's prioKind)"""
    if row.get("inbox_id") or row.get("inbox"):
        return "report" if row.get("art") == "report" else "inbox"
    if REF_RE.match(str(row.get("ref") or "")):
        return "issue"
    if row.get("task"):
        return "stream" if row.get("stream") or row.get("work_kind") == "stream" else "task"
    return "item"


def _lookup(app, sections: list[dict]) -> Callable[[str], dict | None]:
    """The server's item behind a key a page names (prio.rows_of `lookup`): a row the collector holds, an item of the
    work page's sections, or one of its tabs (`tab:<ref>`, a tab that works on a task of its own is that task); None
    for a key the server cannot place. Its text is the server's own, never what the page sent"""
    page: dict[str, tuple[dict, dict]] = {}
    for sec in sections or []:
        for it in sec.get("items") or []:
            if isinstance(it, dict):
                for k in (_row_key(it), it.get("key")):
                    if isinstance(k, str) and k:
                        page.setdefault(k, (sec, it))
    tabs_of = getattr(getattr(app, "tabs", None), "tab_list", None)
    tabs = {t.get("ref"): t for t in (tabs_of() if tabs_of else []) if isinstance(t, dict)}
    resolve = getattr(app.collector, "resolve", None)
    root = getattr(app, "root", None)

    def lookup(key: str) -> dict | None:
        if key.startswith("tab:"):
            t = tabs.get(key[len("tab:"):])
            if not t:
                return None
            own = lookup(f"task:{t['slug']}") if t.get("slug") else None
            return own or {"key": key, "title": t.get("name"), "kind": "tab", "status": t.get("state")}
        found = resolve(key) if resolve else None
        sec, it = page.get(key, (None, {}))
        if not found and not it:
            return None
        row = {**((found or {}).get("row") or {}), **((found or {}).get("out") or {})} if found else {}
        both = {**it, **row}
        inbox = both.get("inbox_id") or both.get("inbox")
        m = INBOX_DAY_RE.match(str(inbox or ""))
        created = str(both.get("created") or "")
        source = it.get("source") or (_source_of(root, inbox) if inbox and root is not None else None)
        return {"key": key, "title": both.get("title"), "kind": _kind_of(both),
                "status": both.get("status") or both.get("inbox_state") or both.get("state"), "due": both.get("due"),
                "since": f"{m[1]}-{m[2]}-{m[3]}" if m else created[:10] or None,
                "detail": " ".join(str(x) for x in (it.get("detail"), row.get("detail")) if x),
                "task": both.get("task"), "source": source, "section": sec.get("id") if sec else None,
                "label": _label(sec.get("title") or sec.get("id") or "") if sec else None, "priority": both.get("priority")}
    return lookup


def _rows_for(app, found: tuple[dict, list[dict]], day: str, rows: list | None) -> tuple[list[dict], dict]:
    """The rows of this read-in, each once, and what was left out: {private, section, same, unknown, over}. The
    page's rows (Prio's read-in) are keys the server looks up itself (_lookup) and holds to the page's private words
    and skip_sections; without them the page's own rows go (pick_rows)"""
    cfg, sections = found
    cfg = cfg or {}
    tri = getattr(app, "triage", None)
    triage = (tri.state().get("items") if tri else None) or {}
    if rows is not None:
        out, skipped = prio.rows_of(rows, day, triage, cfg.get("private"), _lookup(app, sections), cfg.get("skip_sections"))
    else:
        picked, sk1 = pick_rows(sections, triage, cfg)
        mine = {r["key"]: {**r, "since": None} for r in picked}
        out, sk = prio.rows_of([{"key": k} for k in mine], day, triage, [], mine.get)
        skipped = {**sk, **sk1}
    limit = MAX_TASKS * MAX_BATCHES
    skipped["over"] = max(0, len(out) - limit)
    return out[:limit], skipped


def _ask_jev(app, rows: list[dict], day: str, call, key) -> tuple[list[dict], list[str], dict, int]:
    """Jev's plan over the rows, batch by batch: (items, the keys Jev picked to start with, tokens, calls). Each
    batch's tokens are booked as soon as it answers, so a failing later batch keeps what was already spent"""
    js = _state(app)
    conf = getattr(app, "cfg", None)
    items, picks, tokens, calls = [], [], {"input_tokens": 0, "output_tokens": 0}, 0
    secret = (key or (lambda: resolve_key(ref=getattr(conf, "jev_key_ref", None))))() if rows else None
    for i in range(0, len(rows), MAX_TASKS):
        chunk = rows[i:i + MAX_TASKS]
        batch = [{**w, "key": r["key"]} for w, r in zip(prio.wire(chunk), chunk)]
        payload = build_request(batch, day, who=getattr(conf, "person_name", None), about=getattr(conf, "jev_person", None),
                                lang=getattr(conf, "language", "en") or "en", criteria=getattr(conf, "jev_criteria", None),
                                model=getattr(conf, "jev_model", None))
        response = (call or call_api)(payload, secret)
        calls += 1
        plan = plan_from(batch, response)
        items.extend(plan["items"])
        picks.extend(x["key"] for x in plan["items"] if x["id"] == plan["first"])
        used = tokens_of((response or {}).get("usage"))
        was_known = all(tokens[f] is not None for f in tokens)
        for f in tokens:
            tokens[f] = None if tokens[f] is None or used[f] is None else tokens[f] + used[f]
        with js.lock:
            js.count(day, used, rating=calls == 1, unknown=was_known and any(tokens[f] is None for f in tokens))
            js.save()
    return items, picks, tokens, calls


def _ask_haiku(app, rows: list[dict], day: str, prio_call, prior: dict | None = None
               ) -> tuple[list[dict], list[str], str | None, int]:
    """Haiku's plan over the rows in one call, in Jev's shape (prio.ask): (items with their reason, the pick, model,
    how many rows the prompt had no room for)"""
    if not rows:
        return [], [], None, 0
    batch = [{**w, "key": r["key"]} for w, r in zip(prio.wire(rows), rows)]
    response, kept, over = prio.ask(app, batch, day, call=prio_call, prior=prior)
    ids = {t["id"]: f"t{n + 1}" for n, t in enumerate(kept)}
    sent = [{**t, "id": ids[t["id"]]} for t in kept]          # the numbers Haiku saw: the rows that went, in order
    plan = plan_from(sent, response)
    for it in plan["items"]:
        it["reason"] = response["reasons"].get(it["id"])
    return plan["items"], [x["key"] for x in plan["items"] if x["id"] == plan["first"]], response.get("model"), over


def _rank_now(app, page_id: str, found: tuple[dict, list[dict]], day: str, call, key, ranker: str,
              rows_in: list | None, prio_call, click: bool = True) -> dict:
    """Ask the ranker for the order of one page; runs under the page's gate (module notes above). Only a click falls
    back to Haiku: the daily order never runs Haiku by itself"""
    st, js = _pages_state(app), _state(app)
    with st.lock:
        prior = {x.get("key"): x.get("priority") for x in (st.orders.get(page_id) or {}).get("items") or []
                 if isinstance(x, dict) and isinstance(x.get("priority"), (int, float))}
    rows, skipped = _rows_for(app, found, day, rows_in)
    twins = {r["key"]: r.get("keys") or [r["key"]] for r in rows}
    conf = getattr(app, "cfg", None)
    started = time.monotonic()
    tokens, calls, fallback = {"input_tokens": None, "output_tokens": None}, 0, None
    model = getattr(conf, "jev_model", None) or MODEL
    if ranker == "jev":
        try:
            items, picks, tokens, calls = _ask_jev(app, rows, day, call, key)
        except JevError as e:
            # a failed read-in on a click (busy, 5xx, a timeout, no key) runs Haiku where the fallback says so and
            # Haiku is on; a refusal of the request (4xx) stays one, and the daily order never falls back
            if not click or not _jev_failed(e) or prio.block(app).get("fallback") != "haiku" or not prio.ready(app):
                raise
            ranker, fallback = "haiku", {"from": "jev", "code": e.code}
    if ranker == "haiku":
        items, picks, model, over = _ask_haiku(app, rows, day, prio_call, prior)
        skipped["over"] += over
        rows = [r for r in rows if any(x["key"] == r["key"] for x in items)] if over else rows
    # a row the ranker left without urgency or impact has no square: it stays out of the order (Not rated yet)
    rated = [x for x in items if x.get("quadrant")]
    skipped["unrated"] = len(items) - len(rated)
    items = rated
    items.sort(key=lambda x: (-x["priority"], -x["first"]))
    lead = max((x for x in items if x["key"] in picks), key=lambda x: x["priority"], default=None)
    if lead is not None:
        items.remove(lead)
        items.insert(0, lead)
    # a row that stands for two keys (the same title twice) gives both its rank
    out = [{f: x.get(f) for f in ORDER_FIELDS} | {"key": k, "rank": n + 1}
           for n, x in enumerate(items) for k in twins.get(x["key"], [x["key"]])]
    order = {"at_ms": int(app.clock()), "day": day, "took_ms": int((time.monotonic() - started) * 1000), "calls": calls,
             "sent": len(rows), "skipped": skipped, "first": items[0]["key"] if items else None, "items": out,
             "ranker": ranker, "model": model, "fallback": fallback, "usage": tokens, "price": None}
    with st.lock:
        st.orders[page_id] = order
        st.failed.pop(page_id, None)
        st.save()
    with js.lock:
        today = _today_of(js, day)
    return {"ok": True, "page": page_id, "order": order, "today": today}
