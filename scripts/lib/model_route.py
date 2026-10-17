# SPDX-License-Identifier: MIT
"""Which model (and effort) an agent should start with, judged from the item it starts on.

One judgment per item: how complex the work is, on four levels described as situations. Jev
(api.typesafe.ai) answers it as a Score in a fraction of a second; without Jev, Claude Haiku answers
the same question as a whole level. Code maps the answer to a model and effort through the bands of
the settings, never the judge itself (asked for a model name, a judge leans to the first option).

The module holds no state and calls nothing by itself: the caller hands in `jev` (payload -> answer)
and `haiku` (prompt -> stdout), so the cockpit and a test can plug in their own. Only title, kind and
priority of an item leave the machine, never its detail or a path.
"""
from __future__ import annotations

import json
import math
from typing import Any, Callable

from .ai_services import CLAUDE_MODELS

MODELS = tuple(CLAUDE_MODELS)                      # haiku, sonnet, opus: weakest first
EFFORTS = ("low", "medium", "high", "xhigh")
ROUTERS = ("chain", "jev", "haiku")
ITEM_FIELDS = ("title", "kind", "priority")
TITLE_MAX = 300
MAX_ITEMS = 20
HAIKU_PROMPT_MAX = 8000

LEVELS = [
    "a single small edit or a lookup: a typo, a rename, one setting, a question answered by reading one file",
    "a contained change in one or two files with a clear goal: a flag with its test, a small script, a known bug",
    "a change across several files, or debugging that needs investigation before the cause is known",
    "design or architecture across a codebase, goals that are still open, or subtle correctness or security reasoning",
]
QUESTION = ("How complex is the work an AI coding agent has to do for `item`, judged from its title, kind and "
            "priority alone?")

DEFAULTS: dict[str, Any] = {
    "enabled": False, "manual": True, "auto": False, "effort": False,
    "default_model": "sonnet", "default_effort": None, "max_model": "opus",
    "router": "chain", "jev_model": "jev-1.14.0",
    # the score of a level runs from 0 to 3; the first band whose `below` the score stays under wins
    "jev_bands": [{"below": 0.75, "model": "haiku", "effort": "medium"},
                  {"below": 1.3, "model": "sonnet", "effort": "medium"},
                  {"below": 1.9, "model": "sonnet", "effort": "high"},
                  {"below": 2.6, "model": "opus", "effort": "high"},
                  {"below": None, "model": "opus", "effort": "xhigh"}],
    # Haiku answers a whole level; a level of 2 lands on opus under the Jev bands too often (probe 2026-10-17)
    "haiku_map": [{"model": "haiku", "effort": "medium"}, {"model": "sonnet", "effort": "medium"},
                  {"model": "sonnet", "effort": "high"}, {"model": "opus", "effort": "high"}],
}

HAIKU_PROMPT = """Judge how complex each piece of work is for an AI coding agent, from its title, kind and priority alone.

Levels:
{levels}

Items (JSON):
{items}

Answer with a JSON array only, one object per item: [{{"id": "<id>", "level": <0-3>, "why": "<at most eight words>"}}]"""


class SettingsError(ValueError):
    """A settings value fails validation; `field` names it."""

    def __init__(self, field: str, message: str):
        super().__init__(f"{field}: {message}")
        self.field = field


def _pick(value: Any, field: str) -> dict:
    if not isinstance(value, dict) or set(value) - {"model", "effort", "below"}:
        raise SettingsError(field, "must be an object of model and effort")
    if value.get("model") not in MODELS:
        raise SettingsError(field, f"model must be one of {', '.join(MODELS)}")
    if value.get("effort") is not None and value.get("effort") not in EFFORTS:
        raise SettingsError(field, f"effort must be one of {', '.join(EFFORTS)} or empty")
    return {"model": value["model"], "effort": value.get("effort")}


def normalize(change: Any, base: dict | None = None) -> dict:
    """The settings `base` (else DEFAULTS) with `change` applied; raises SettingsError on any bad value."""
    out = json.loads(json.dumps(base or DEFAULTS))
    if not isinstance(change, dict):
        raise SettingsError("settings", "must be an object")
    for key, value in change.items():
        if key not in DEFAULTS:
            raise SettingsError(str(key)[:40], "unknown setting")
        if key in ("enabled", "manual", "auto", "effort"):
            if not isinstance(value, bool):
                raise SettingsError(key, "must be true or false")
        elif key in ("default_model", "max_model"):
            if value not in MODELS:
                raise SettingsError(key, f"must be one of {', '.join(MODELS)}")
        elif key == "default_effort":
            if value is not None and value not in EFFORTS:
                raise SettingsError(key, f"must be one of {', '.join(EFFORTS)} or empty")
        elif key == "router":
            if value not in ROUTERS:
                raise SettingsError(key, f"must be one of {', '.join(ROUTERS)}")
        elif key == "jev_model":
            if not isinstance(value, str) or not _jev_model_ok(value):
                raise SettingsError(key, "must be a versioned Jev id such as jev-1.14.0")
        elif key == "jev_bands":
            value = _bands(value)
        elif key == "haiku_map":
            if not isinstance(value, list) or len(value) != len(LEVELS):
                raise SettingsError(key, f"must hold {len(LEVELS)} entries, one per level")
            value = [_pick(v, f"{key}[{i}]") for i, v in enumerate(value)]
        out[key] = value
    return out


def _jev_model_ok(value: str) -> bool:
    parts = value.removeprefix("jev-").split(".") if value.startswith("jev-") else []
    return 2 <= len(parts) <= 3 and all(p.isdigit() and len(p) <= 4 for p in parts)


def _bands(value: Any) -> list:
    if not isinstance(value, list) or not 1 <= len(value) <= 8:
        raise SettingsError("jev_bands", "must hold 1 to 8 bands")
    out, last = [], -math.inf
    for i, band in enumerate(value):
        pick = _pick(band, f"jev_bands[{i}]")
        below = band.get("below")
        final = i == len(value) - 1
        if final:
            if below is not None:
                raise SettingsError(f"jev_bands[{i}]", "the last band takes the rest: below must be empty")
        elif isinstance(below, bool) or not isinstance(below, (int, float)) or not last < below <= 3:
            raise SettingsError(f"jev_bands[{i}]", "below must rise from band to band and stay within 0 to 3")
        else:
            last = float(below)
        out.append({"below": None if final else last, **pick})
    return out


def capped(model: str, settings: dict) -> str:
    """The model, at most settings.max_model."""
    top = settings.get("max_model", "opus")
    return model if MODELS.index(model) <= MODELS.index(top) else top


def from_score(score: float, settings: dict) -> dict:
    band = next(b for b in settings["jev_bands"] if b["below"] is None or score < b["below"])
    return {"model": capped(band["model"], settings), "effort": band["effort"]}


def from_level(level: int, settings: dict) -> dict:
    pick = settings["haiku_map"][max(0, min(len(LEVELS) - 1, level))]
    return {"model": capped(pick["model"], settings), "effort": pick["effort"]}


def default_route(settings: dict, why: str) -> dict:
    return {"model": settings["default_model"], "effort": settings["default_effort"], "routed_by": "default",
            "level": None, "confidence": None, "why": why}


def clean_items(items: list[dict]) -> list[dict]:
    """What may leave the machine: id plus title, kind and priority, the title cut short."""
    out = []
    for it in items[:MAX_ITEMS]:
        one = {"id": str(it["id"])}
        for f in ITEM_FIELDS:
            if isinstance(it.get(f), str) and it[f].strip():
                one[f] = it[f].strip()[:TITLE_MAX]
        out.append(one)
    return out


def jev_request(items: list[dict], settings: dict) -> dict:
    items = clean_items(items)
    state = {"items": [{k: v for k, v in it.items() if k != "id"} for it in items]}
    questions = {it["id"]: {"type": "score", "criteria": LEVELS,
                            "instructions": QUESTION.replace("`item`", f"`items[{i}]`")}
                 for i, it in enumerate(items)}
    return {"model": settings["jev_model"], "state": state, "questions": questions}


def from_jev(items: list[dict], answer: Any, settings: dict) -> dict:
    out = {}
    answers = answer.get("answers") if isinstance(answer, dict) else None
    for it in clean_items(items):
        a = answers.get(it["id"]) if isinstance(answers, dict) else None
        if not isinstance(a, dict):
            continue
        score = a.get("score")
        if isinstance(score, bool) or not isinstance(score, (int, float)) or not 0 <= score <= 3:
            continue
        conf = a.get("confidence")
        out[it["id"]] = {**from_score(float(score), settings), "routed_by": "jev", "level": round(float(score), 2),
                         "confidence": round(float(conf), 2) if isinstance(conf, (int, float)) else None,
                         "why": LEVELS[min(3, int(round(score)))]}
    return out


def haiku_prompt(items: list[dict]) -> str:
    levels = "\n".join(f"{i}: {d}" for i, d in enumerate(LEVELS))
    body = json.dumps(clean_items(items), ensure_ascii=False)
    return HAIKU_PROMPT.format(levels=levels, items=body)[:HAIKU_PROMPT_MAX]


def from_haiku(items: list[dict], stdout: str, settings: dict) -> dict:
    """Haiku's answer: the claude -p JSON envelope (its `result`) or the bare array."""
    text = stdout or ""
    try:
        envelope = json.loads(text)
        if isinstance(envelope, dict) and isinstance(envelope.get("result"), str):
            text = envelope["result"]
    except ValueError:
        pass
    start, end = text.find("["), text.rfind("]")
    try:
        answer = json.loads(text[start:end + 1]) if 0 <= start < end else []
    except ValueError:
        answer = []
    picks = {str(a.get("id")): a for a in answer if isinstance(a, dict)}
    out = {}
    for it in clean_items(items):
        a = picks.get(it["id"]) or {}
        level = a.get("level")
        if isinstance(level, bool) or not isinstance(level, int) or not 0 <= level < len(LEVELS):
            continue
        out[it["id"]] = {**from_level(level, settings), "routed_by": "haiku", "level": level, "confidence": None,
                         "why": str(a.get("why") or "")[:80] or LEVELS[level]}
    return out


def route(items: list[dict], settings: dict, jev: Callable[[dict], Any] | None = None,
          haiku: Callable[[str], str] | None = None) -> dict:
    """{item id: {model, effort, routed_by, level, confidence, why}} for every item.

    settings.router chain asks Jev, then Haiku for what Jev left open; jev or haiku asks only that one.
    A judge that is not handed in, fails or leaves an item open hands it on; the last word is the default."""
    items = clean_items(items)
    out: dict = {}
    order = {"chain": ("jev", "haiku"), "jev": ("jev",), "haiku": ("haiku",)}[settings.get("router", "chain")]
    for judge in order:
        todo = [it for it in items if it["id"] not in out]
        if not todo:
            break
        try:
            if judge == "jev" and jev is not None:
                out.update(from_jev(todo, jev(jev_request(todo, settings)), settings))
            elif judge == "haiku" and haiku is not None:
                out.update(from_haiku(todo, haiku(haiku_prompt(todo)), settings))
        except Exception:      # noqa: BLE001  a judge that fails hands on; the start must never break here
            continue
    for it in items:
        out.setdefault(it["id"], default_route(settings, "no judge answered"))
    return out


def haiku_argv(claude: str, prompt: str) -> list[str]:
    """The one call Haiku makes as judge: no tools, no settings, no session, JSON out."""
    return [claude, "-p", "--model", CLAUDE_MODELS["haiku"], "--output-format", "json", "--no-session-persistence",
            "--setting-sources", "", "--tools", "", "--", prompt]


def haiku_argv_ok(argv: list[str], claude: str | None) -> bool:
    return (bool(claude) and len(argv) == 13 and argv[:12] == haiku_argv(claude, "")[:12]
            and isinstance(argv[12], str) and 0 < len(argv[12]) <= HAIKU_PROMPT_MAX)
