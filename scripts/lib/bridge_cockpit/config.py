# SPDX-License-Identifier: MIT
"""Configuration of the cockpit: `cockpit:` in bridge-config.yaml.

A key the block leaves out takes its default; the language falls back to language.conversation.
Resolution rules: docs/bridge-cockpit.md, the cockpit: block.
"""
from __future__ import annotations

from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Any

import json
import re

import yaml

from .. import model_route as mr
from .. import work_find as wf
from . import activity as act
from . import describe as dsc
from . import guide as gd
from . import origin as og
from . import themes as thm
from . import ticker as tk

DEFAULT_PORT = 8797
OPEN_IN = ("auto", "cmux", "system", "none")
TARGETS = ("tab", "workspace", "area", "auto")
CHAT_LAYOUTS = ("classic", "workspaces")   # workspaces: the chat as cmux shows it (workspaces, tabs, Bridges, agents)
# the view the work tab opens on (cockpit.work_view): Due, By source, By Jev, Files or Work through (only while
# cockpit.flow.enabled is on, else Due); the page maps each to its own id
WORK_VIEWS = ("due", "source", "jev", "files", "flow")
# which tasks the files view holds (cockpit.files_scope): the doing and review ones, or every task and stream
FILES_SCOPES = ("active", "all")
# the Work through page (cockpit.flow, page @flow): off unless switched on. drop_reasons are what "Drop because"
# offers to click, keys the page words (text-flow.js) or a reason of the instance's own, shown as written;
# return_after_s is how long after a jump to a tab the page asks how it went, once it is in view again.
# FLOW_INTS: how many cards ahead get their brief prepared (0: none), how many starts may run before Let AI do it
# asks first, how old a Jev rank may be and still order the tasks, how often a day a click may order them anew,
# how many days before its due day a point stands in front (later ones wait under Not now, Later);
# each with its default and minimum (a value below it keeps the default)
FLOW_DROP_REASONS = ("resolves_itself", "not_needed", "someone_else", "not_worth_it")
FLOW_INTS = (("prep_ahead", 2, 0), ("max_running", 4, 1), ("rank_max_age_days", 7, 1), ("rerank_per_day", 3, 0),
             ("ahead_days", 2, 0))
# infer_sessions: a live session in a tab that names one open task in the end of its own transcript runs under
# Running now as work on that task (sessions.py infer), without a link by hand; only while the page is on
# themes: the nested block of the themes the page groups its points by (themes.py, cockpit.flow.themes); summary,
# instruct and attach the nested blocks of the Activity tab and the instruction line (activity.py, instruct.py), each
# off by default, the two that call a model within a budget a day
FLOW_KEYS = ("enabled", "drop_reasons", "return_after_s", *(key for key, _d, _low in FLOW_INTS), "infer_sessions",
             "themes", "summary", "instruct", "attach")
FLOW_REASON_MAX = 80
FLOW_REASONS_MAX = 12
FLOW_RETURN_MAX = 3600


JEV_MODEL_RE = re.compile(r"^jev-[0-9]+(\.[0-9]+){1,2}\Z")
KEYCHAIN_REF_RE = re.compile(r"^keychain://[A-Za-z0-9._-]{1,80}/[A-Za-z0-9._@-]{1,80}\Z")


def parse_keychain_ref(ref: object) -> tuple[str, str] | None:
    """keychain://<service>/<account> as (service, account); anything else None."""
    if not isinstance(ref, str) or not KEYCHAIN_REF_RE.match(ref):
        return None
    service, account = ref[len("keychain://"):].split("/", 1)
    return service, account


class WebConfigError(ValueError):
    """A value is present but invalid (the CLI exits 2 with the message)."""


@dataclass(frozen=True)
class WebConfig:
    root: Path
    enabled: bool
    port: int
    open_in: str
    relay: bool
    profile: str | None
    tabs_seconds: int
    language: str
    full_minutes: float
    voice: bool
    target: str
    control: str | None
    # the names of workplace.workspaces, in their order: the areas an inbox item can be given (detail page)
    areas: tuple = ()
    # Jev (TypeSafe): off unless integrations.typesafe.enabled; the key only ever as a keychain reference
    jev_enabled: bool = False
    jev_key_ref: str | None = None
    # who the dashboard belongs to, as Claude and Jev should name them (cockpit.person_name);
    # without it both say "the user", so no name of an instance lives in the code
    person_name: str | None = None
    jev_person: str | None = None        # integrations.typesafe.person: a sentence about them for Jev
    jev_criteria: dict | None = None     # integrations.typesafe.criteria: {urgency|impact|effort: four levels}
    jev_model: str | None = None         # integrations.typesafe.model: a versioned Jev id, else jev.MODEL
    # how often the cmux layout is saved while the cockpit runs, only on change (0: only on Save); was the mod's
    snapshot_minutes: float = 60
    idle_minutes: float = 10      # a waiting tab still this long that asks nothing is done, not waiting (0 = off)
    # the triage sorts every task and inbox item once a day by itself (a model call): only when asked for
    triage_daily: bool = False
    chat_layout: str = "classic"
    # a quick chat untouched this many hours leaves the list into the archive (cockpit.chat_keep_hours, 0: never)
    chat_keep_hours: float = 24
    # the model an agent starts with (cockpit.launch_model, model_route.DEFAULTS): off unless switched on;
    # the settings page may change it on top (launch.py), this is what the config says
    launch_model: dict = field(default_factory=lambda: dict(mr.DEFAULTS))
    # the news ticker of the start page (cockpit.ticker, ticker.DEFAULTS): off unless switched on;
    # the settings page may change it on top (ticker.py), this is what the config says
    ticker: dict = field(default_factory=tk.defaults)
    # the decision guide of waiting tabs (cockpit.session_guide, guide.DEFAULTS): off unless switched on;
    # the settings page may switch it on top (guide.py), this is what the config says
    session_guide: dict = field(default_factory=lambda: dict(gd.DEFAULTS))
    # the first-run tour of the page (cockpit.tour): offered on a first visit unless switched off;
    # Help and Settings start it by hand either way
    tour: bool = True
    # the Setup page (cockpit.setup): what still keeps the cockpit from working well and what can be switched on,
    # collected with `briefing.py collect --setup` (scripts/bridge-setup.py); on unless switched off
    setup: bool = True
    # the view the work tab opens on until a click on its switch picks another (cockpit.work_view); "due" is
    # what the tab always opened on, so a Bridge without the key sees no change
    work_view: str = "due"
    # the calm card of the start page's focus, and its last step, lead on into the files view (cockpit.focus_to_files)
    focus_to_files: bool = False
    # which tasks are files (cockpit.files_scope): "active" the doing and review ones, as the view always had;
    # "all" every task and stream but the closed ones, the queue first and the rest behind it on chips
    files_scope: str = "active"
    # how the work tab names a source the built-in rules cannot tell (cockpit.origin_map, origin.py): pairs of
    # (pattern lower-cased, category) in file order, a tuple since the config is frozen and order matters
    origin_map: tuple = ()
    # each item's brief written and kept by a small model (cockpit.describe, describe.py): {auto, budget_per_hour,
    # kinds, effort}; auto off unless switched on, the button on a card works either way
    describe: dict = field(default_factory=dsc.defaults)
    # the Work through page (cockpit.flow, flow_of): {enabled, drop_reasons, return_after_s, prep_ahead,
    # max_running, rank_max_age_days, rerank_per_day, ahead_days, infer_sessions, ...}; off by default
    flow: dict = field(default_factory=lambda: flow_defaults())
    # the views the work tab's switch offers (cockpit.work_views, work_views_of): all of them unless the config
    # names fewer; files is always among them, every "open the file" link leads there (the files tab, round 6c)
    work_views: tuple = WORK_VIEWS
    # the files tab's question to its records (cockpit.files_search, files_search_of): {enabled, budget_per_day,
    # model, block}; off by default, block empty
    files_search: dict = field(default_factory=lambda: files_search_defaults())
    # what the history search reads besides the work system (history_paths_of): the raw meeting transcripts
    # (work.meetings.raw_record_dir under doc_sensor.onedrive_root), None for none, and the meeting folders below
    # the root (work.meetings.home_dir)
    transcripts: Path | None = None
    meetings: str = wf.MEETINGS_DIR
    # further sources of A2A peers beside infra/a2a-peers/ (cockpit.a2a_sources, agents.py): ({name, script}, ...),
    # each script a skill's own that lists its peers, reads their cards and asks them in a fixed JSON contract
    a2a_sources: tuple = ()
    # the click origin log (cockpit.usage.clicks, store.append_clicks): which control was used from which place,
    # never what it was about, kept in usage.jsonl for scripts/cockpit-usage.py; on unless switched off
    usage_clicks: bool = True
    # what the check of the block found (check_block): unknown keys and values the loader replaced, each
    # naming the key and the value used instead; shown by `status` and on the settings page, never fatal
    config_warnings: tuple = ()


def _dict(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def jev_criteria_of(value: Any) -> dict | None:
    """Own criteria for Jev's scores: per scale exactly four short texts, lowest first; a scale that is
    not that is left to the default, so a typo never breaks the rating."""
    if not isinstance(value, dict):
        return None
    out = {}
    for scale in ("urgency", "impact", "effort"):
        levels = value.get(scale)
        if (isinstance(levels, list) and len(levels) == 4
                and all(isinstance(x, str) and 0 < len(x.strip()) <= 200 for x in levels)):
            out[scale] = [x.strip() for x in levels]
    return out or None


def flow_defaults() -> dict:
    return {"enabled": False, "drop_reasons": list(FLOW_DROP_REASONS), "return_after_s": 20,
            **{key: default for key, default, _low in FLOW_INTS}, "infer_sessions": True, "themes": thm.defaults(),
            "summary": act.ai_defaults(act.SUMMARY_BUDGET), "instruct": act.ai_defaults(act.INSTRUCT_BUDGET),
            "attach": act.attach_defaults()}


def files_search_defaults() -> dict:
    return {**act.ai_defaults(act.FILES_BUDGET), "block": []}


def files_search_of(value: Any) -> dict:
    """cockpit.files_search on top of the defaults, key by key (activity.py ai_of); block keeps the words that fit
    (work_find.block_words)"""
    out = {**act.ai_of(value, act.FILES_BUDGET), "block": []}
    if isinstance(value, dict):
        out["block"] = wf.block_words(value.get("block"))
    return out


VAR_RE = re.compile(r"\$\{([A-Za-z_][A-Za-z0-9_]*)\}")


def history_paths_of(raw: dict) -> tuple[Path | None, str]:
    """(transcripts, meetings) of the history search from bridge-config: the raw transcripts' folder is
    work.meetings.raw_record_dir, relative to doc_sensor.onedrive_root (else identity.onedrive_root), `${var}` from
    `identity:` plus home and a leading ~ expanded; None without one, with an unknown variable or a relative folder
    without a root to stand on. The meeting folders are work.meetings.home_dir when it lies below work/tasks or
    work/streams, else the default"""
    meet = _dict(_dict(raw.get("work")).get("meetings"))
    identity = _dict(raw.get("identity"))
    variables = {"home": str(Path.home()), **{k: str(v) for k, v in identity.items() if isinstance(v, (str, int))}}

    def expand(value: Any) -> Path | None:
        if not isinstance(value, str) or not value.strip():
            return None
        text = VAR_RE.sub(lambda m: variables.get(m.group(1), m.group(0)), value.strip())
        return None if "${" in text else Path(text).expanduser()

    transcripts = expand(meet.get("raw_record_dir"))
    if transcripts is not None and not transcripts.is_absolute():
        base = expand(_dict(raw.get("doc_sensor")).get("onedrive_root")) or expand(identity.get("onedrive_root"))
        transcripts = base / transcripts if base is not None and base.is_absolute() else None
    home = meet.get("home_dir")
    parts = home.strip().strip("/").split("/") if isinstance(home, str) else []
    meetings = ("/".join(parts) if isinstance(home, str) and not home.strip().startswith(("/", "~")) and len(parts) >= 3
                and parts[0] == "work" and parts[1] in ("tasks", "streams") and not any(p in ("", ".", "..") for p in parts)
                else wf.MEETINGS_DIR)
    return transcripts, meetings


def _check_files_search(value: Any, used: dict, where: str) -> list[str]:
    """One warning per unknown key or value files_search_of replaced, naming what is used instead"""
    if not isinstance(value, dict):
        return [f"{where}: must be a mapping, got {_show(value)}; using enabled false"]
    out = act.ai_check({k: v for k, v in value.items() if k != "block"}, used, where, act.FILES_SERVICE)
    words = value.get("block")
    if words is not None and not isinstance(words, list):
        out.append(f"{where}.block: must be a list of words, got {_show(words)}; using none")
    elif isinstance(words, list) and len(wf.block_words(words)) < len(words):
        out.append(f"{where}.block: a word that is no text of 1 to {wf.BLOCK_WORD_MAX} characters, said twice or past "
                   f"the first {wf.BLOCK_MAX} is ignored")
    return out


def _flow_reasons(value: Any) -> tuple[list[str], list[str]]:
    """The reasons of a drop_reasons list that fit (text of 1 to FLOW_REASON_MAX characters, at most
    FLOW_REASONS_MAX, each once), and the ones left out"""
    good, bad = [], []
    for x in value:
        text = " ".join(x.split()) if isinstance(x, str) else ""
        if text and len(text) <= FLOW_REASON_MAX and text not in good and len(good) < FLOW_REASONS_MAX:
            good.append(text)
        else:
            bad.append(x)
    return good, bad


def flow_of(value: Any) -> dict:
    """cockpit.flow on top of the defaults, key by key: a bad value keeps the default of its key, a list of reasons
    keeps the ones that fit (the defaults when none does)"""
    out = flow_defaults()
    if not isinstance(value, dict):
        return out
    if isinstance(value.get("enabled"), bool):
        out["enabled"] = value["enabled"]
    if isinstance(value.get("infer_sessions"), bool):
        out["infer_sessions"] = value["infer_sessions"]
    if isinstance(value.get("drop_reasons"), list):
        out["drop_reasons"] = _flow_reasons(value["drop_reasons"])[0] or out["drop_reasons"]
    after = value.get("return_after_s")
    if _is_int(after) and 0 <= after <= FLOW_RETURN_MAX:
        out["return_after_s"] = after
    for key, _default, low in FLOW_INTS:
        if _is_int(value.get(key)) and value[key] >= low:
            out[key] = value[key]
    out["themes"] = thm.themes_of(value.get("themes"))
    out["summary"] = act.ai_of(value.get("summary"), act.SUMMARY_BUDGET)
    out["instruct"] = act.ai_of(value.get("instruct"), act.INSTRUCT_BUDGET)
    out["attach"] = act.attach_of(value.get("attach"))
    return out


def _check_flow(value: Any, used: dict, where: str) -> list[str]:
    """One warning per unknown key or value flow_of replaced, naming what is used instead"""
    if not isinstance(value, dict):
        return [f"{where}: must be a mapping, got {_show(value)}; using enabled false"]
    lows = {key: low for key, _default, low in FLOW_INTS}
    out = []
    for key, v in value.items():
        at = f"{where}.{str(key)[:40]}"
        if v is None:
            continue
        if key in ("enabled", "infer_sessions") and not isinstance(v, bool):
            out.append(f"{at}: must be true or false, got {_show(v)}; using {_show(used[key])}")
        elif key == "drop_reasons":
            if not isinstance(v, list):
                out.append(f"{at}: must be a list of reasons, got {_show(v)}; using the default reasons")
            else:
                bad = _flow_reasons(v)[1]
                if bad:
                    out.append(f"{at}: {', '.join(_show(x) for x in bad[:3])} is no reason of 1 to {FLOW_REASON_MAX} "
                               f"characters, or one too many; ignored")
        elif key == "return_after_s" and (not _is_int(v) or not 0 <= v <= FLOW_RETURN_MAX):
            out.append(f"{at}: must be a whole number of seconds from 0 to {FLOW_RETURN_MAX}, got {_show(v)}; "
                       f"using {used['return_after_s']}")
        elif key == "themes":
            out += thm.check(v, used["themes"], at)
        elif key in ("summary", "instruct"):
            out += act.ai_check(v, used[key], at, act.SERVICE if key == "summary" else act.INSTRUCT_SERVICE)
        elif key == "attach":
            out += act.attach_check(v, used["attach"], at)
        elif key in lows:
            if not _is_int(v):
                out.append(f"{at}: must be a whole number, got {_show(v)}; using {used[key]}")
            elif v < lows[key]:
                out.append(f"{at}: {_show(v)} is below the minimum {lows[key]}; using {used[key]}")
        elif key not in FLOW_KEYS:
            out.append(f"{at}: unknown key, ignored")
    return out


def language_of(value: Any) -> str:
    """Port of logic.ts languageOf: de... gives de, everything else en."""
    return "de" if isinstance(value, str) and value.lower().startswith("de") else "en"


def read_config_file(root: Path) -> dict:
    path = Path(root) / "bridge-config.yaml"
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def launch_model_of(value: Any, jev_model: str | None = None) -> dict:
    """cockpit.launch_model on top of the defaults, key by key: a bad value keeps the default of its key."""
    out = mr.normalize({"jev_model": jev_model}) if jev_model else dict(mr.DEFAULTS)
    for key, v in _dict(value).items():
        try:
            out = mr.normalize({key: v}, out)
        except mr.SettingsError:
            continue
    return out


# The keys of the cockpit: block and what each takes. The loader below keeps its fallbacks; check_block only
# says when one applied, so a typo shows in `status` and on the settings page instead of nowhere.
# (kind, detail): bool, text, choice (the allowed values), int and number (the minimum the loader clamps to),
# block (the keys of a nested mapping); port is checked by the loader itself (a bad one is an error),
# launch_model, ticker and session_guide by their own modules' rules, key by key.
BLOCK = {
    "enabled": ("bool", "enabled"), "port": ("port", "port"), "open_in": ("choice", "open_in", OPEN_IN),
    "relay": ("bool", "relay"), "person_name": ("text", "person_name"), "profile": ("text", "profile"),
    "tabs_seconds": ("int", "tabs_seconds", 5), "full_minutes": ("number", "full_minutes", 1),
    "snapshot_minutes": ("number", "snapshot_minutes", 0), "idle_minutes": ("number", "idle_minutes", 0),
    "voice": ("bool", "voice"),
    "triage_daily": ("bool", "triage_daily"), "language": ("text", "language"),
    "chat_layout": ("choice", "chat_layout", CHAT_LAYOUTS), "chat_keep_hours": ("number", "chat_keep_hours", 0),
    "launch": ("block", {"target": ("choice", "target", TARGETS)}),
    "launch_model": ("launch_model",), "ticker": ("ticker",), "usage": ("usage",),
    "session_guide": ("session_guide",), "tour": ("bool", "tour"), "setup": ("bool", "setup"),
    "work_view": ("choice", "work_view", WORK_VIEWS), "focus_to_files": ("bool", "focus_to_files"),
    "files_scope": ("choice", "files_scope", FILES_SCOPES),
    "origin_map": ("origin_map",), "describe": ("describe",), "a2a_sources": ("a2a_sources",),
    "flow": ("flow",), "work_views": ("work_views",), "files_search": ("files_search",),
}
USAGE_KEYS = ("remotes", "remote_file", "host", "clicks")   # read by usage.remote_hosts, clicks by the loader
HOST_SLUG_RE = re.compile(r"[A-Za-z0-9._-]{1,64}")
BLOCK_KEYS = tuple(BLOCK)


def _show(value: Any) -> str:
    """A value as the config would spell it, short: true, 7, "auto", none."""
    if value is None:
        return "none"
    if isinstance(value, (list, dict)):
        return "the default"
    text = json.dumps(value, ensure_ascii=False, default=str)
    return text if len(text) <= 60 else text[:57] + "..."


def _check_launch_model(value: Any, cfg: WebConfig, where: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"{where}: must be a mapping, got {_show(value)}; using the defaults"]
    out = []
    for key, v in value.items():
        try:
            mr.normalize({key: v})
        except mr.SettingsError as error:
            fallback = "ignored" if key not in mr.DEFAULTS else f"using {_show(cfg.launch_model.get(key))}"
            out.append(f"{where}.{str(key)[:40]}: {str(error).split(': ', 1)[-1]}; {fallback}")
    return out


def _check_ticker(value: Any, cfg: WebConfig, where: str) -> list[str]:
    if not isinstance(value, dict):
        return [f"{where}: must be a mapping, got {_show(value)}; using the defaults"]
    out = []

    def bad(name: str, change: dict, used: Any) -> None:
        try:
            tk.normalize(change)
        except tk.TickerSettingsError as error:
            out.append(f"{where}.{name}: {error.message}; using {_show(used)}")

    for key, v in value.items():
        if key not in tk.KEYS:
            out.append(f"{where}.{str(key)[:40]}: unknown key, ignored")
        elif key == "feeds" and isinstance(v, list):
            seen = set()
            for i, entry in enumerate(v):
                at = f"{where}.feeds[{i}]"
                if i >= tk.MAX_FEEDS:
                    out.append(f"{at}: more than {tk.MAX_FEEDS} feeds, skipped")
                    continue
                try:
                    feed = tk.normalize({"feeds": [entry]})["feeds"][0]
                except tk.TickerSettingsError as error:
                    out.append(f"{at}{error.field.removeprefix('feeds[0]')}: {error.message}; skipped")
                    continue
                if feed["id"] in seen:
                    out.append(f"{at}.id: this id is taken by an earlier feed; skipped")
                seen.add(feed["id"])
                out += [f"{at}.{str(k)[:40]}: unknown key, ignored" for k in entry
                        if k not in ("id", "name", "url", "enabled")]
        elif key in ("status", "editor", "smart") and isinstance(v, dict):
            for name, x in v.items():
                if name not in tk.DEFAULTS[key]:
                    out.append(f"{where}.{key}.{str(name)[:40]}: unknown key, ignored")
                else:
                    bad(f"{key}.{name}", {key: {name: x}}, cfg.ticker[key][name])
        else:
            bad(key, {key: v}, cfg.ticker.get(key))
    return out


def _check_usage(value: Any, where: str) -> list[str]:
    """cockpit.usage: remotes (infra/remotes slugs; a list, empty for none), remote_file (text) and host (this machine). usage.py
    skips what does not fit, so each warning says what is used instead. clicks (true or false) is the click origin log."""
    if not isinstance(value, dict):
        return [f"{where}: must be a mapping, got {_show(value)}; using the machines of infra/instances"]
    out = []
    for key, v in value.items():
        at = f"{where}.{str(key)[:40]}"
        if key not in USAGE_KEYS:
            out.append(f"{at}: unknown key, ignored")
        elif v is None:
            continue
        elif key == "remotes":
            if not isinstance(v, list):
                out.append(f"{at}: must be a list of infra/remotes names, got {_show(v)}; "
                           "using the machines of infra/instances")
            else:
                bad = [x for x in v if not isinstance(x, str) or not HOST_SLUG_RE.fullmatch(x)]
                if bad:
                    out.append(f"{at}: {', '.join(_show(x) for x in bad[:3])} is no machine name; skipped")
        elif key == "clicks":
            if not isinstance(v, bool):
                out.append(f"{at}: must be true or false, got {_show(v)}; using true")
        elif key == "host":
            if not isinstance(v, str) or not HOST_SLUG_RE.fullmatch(v):
                out.append(f"{at}: {_show(v)} is no machine name; using the infra/remotes entry that matches this machine")
        elif not isinstance(v, str) or not v.strip():
            out.append(f"{at}: must be text, got {_show(v)}; using \"~/.bridge/resources/usage.json\"")
    return out


def origin_map_of(value: Any) -> tuple[tuple, list[str]]:
    """cockpit.origin_map as ((pattern, category), ...) in file order, keys lower-cased, and a warning for each
    entry left out: the value is not a mapping, a key is no text, a category is not one of origin.CATEGORIES, a key
    repeats another but for case."""
    where = "cockpit.origin_map"
    if value is None:
        return (), []
    if not isinstance(value, dict):
        return (), [f"{where}: must be a mapping, got {_show(value)}; using none"]
    out, warnings, seen = [], [], set()
    for key, cat in value.items():
        at = f"{where}.{str(key)[:40]}"
        if not isinstance(key, str) or not key.strip():
            warnings.append(f"{at}: the name must be text, got {_show(key)}; ignored")
            continue
        if cat not in og.CATEGORIES:
            warnings.append(f"{at}: must be one of {', '.join(og.CATEGORIES)}, got {_show(cat)}; ignored")
            continue
        low = key.strip().lower()
        if low in seen:
            warnings.append(f"{at}: duplicate, first one kept")
            continue
        seen.add(low)
        out.append((low, cat))
    return tuple(out), warnings


A2A_SOURCE_NAME_RE = re.compile(r"[a-z0-9][a-z0-9-]{0,31}")
A2A_SOURCE_SCRIPT_RE = re.compile(r"skills/[a-z0-9][a-z0-9-]{0,63}/scripts/[a-z0-9_][a-z0-9_-]{0,63}\.py")
MAX_A2A_SOURCES = 4


def a2a_sources_of(value: Any, root: Path | None) -> tuple[tuple, list[str]]:
    """cockpit.a2a_sources as ({name, script}, ...) in file order, and a warning for each entry left out: not a
    mapping, a name that is no slug or repeats, a script that is not skills/<skill>/scripts/<name>.py or does
    not exist under `root`, more than MAX_A2A_SOURCES."""
    where = "cockpit.a2a_sources"
    if value is None:
        return (), []
    if not isinstance(value, list):
        return (), [f"{where}: must be a list, got {_show(value)}; using none"]
    out, warnings, seen = [], [], set()
    for i, entry in enumerate(value):
        at = f"{where}[{i}]"
        if not isinstance(entry, dict):
            warnings.append(f"{at}: must be a mapping with name and script, got {_show(entry)}; ignored")
            continue
        name, script = entry.get("name"), entry.get("script")
        if not isinstance(name, str) or not A2A_SOURCE_NAME_RE.fullmatch(name) or name in seen:
            warnings.append(f"{at}.name: {_show(name)} is no short lower-case name or repeats; ignored")
            continue
        if not isinstance(script, str) or not A2A_SOURCE_SCRIPT_RE.fullmatch(script):
            warnings.append(f"{at}.script: {_show(script)} is not skills/<skill>/scripts/<name>.py; ignored")
            continue
        if root is not None and not (Path(root) / script).is_file():
            warnings.append(f"{at}.script: {_show(script)} does not exist; ignored")
            continue
        if len(out) >= MAX_A2A_SOURCES:
            warnings.append(f"{at}: more than {MAX_A2A_SOURCES} sources; ignored")
            continue
        seen.add(name)
        out.append({"name": name, "script": script})
    return tuple(out), warnings


def work_views_of(value: Any) -> tuple[tuple, list[str]]:
    """cockpit.work_views as the views kept, in WORK_VIEWS order, and a warning for each word left out or added:
    an unknown word is dropped, files is always kept (added when missing), not a list or nothing left gives all"""
    where = "cockpit.work_views"
    every = ", ".join(WORK_VIEWS)
    if value is None:
        return WORK_VIEWS, []
    if not isinstance(value, list):
        return WORK_VIEWS, [f"{where}: must be a list of {every}, got {_show(value)}; using all of them"]
    warnings = [f"{where}: {_show(x)} is no view of the work tab ({every}); ignored"
                for x in value if x not in WORK_VIEWS]
    known = [x for x in value if x in WORK_VIEWS]
    if not known:
        return WORK_VIEWS, warnings + [f"{where}: nothing left of the list; using all of them"]
    if "files" not in known:
        warnings.append(f"{where}: files is always kept, every link that opens a task's file leads there; added")
    return tuple(v for v in WORK_VIEWS if v in known or v == "files"), warnings


def check_block(block: Any, cfg: WebConfig, where: str = "cockpit", keys: dict = BLOCK) -> tuple:
    """One warning per unknown key, wrong type or value the loader replaced, naming the key and the value
    `cfg` (the loaded config) uses instead. A None value counts as left out, as it does for the loader."""
    if block is None:
        return ()
    if not isinstance(block, dict):
        return (f"{where}: must be a mapping, got {_show(block)}; ignored",)
    out = []
    for key, value in block.items():
        at = f"{where}.{str(key)[:40]}"
        rule = keys.get(key)
        if rule is None:
            out.append(f"{at}: unknown key, ignored")
            continue
        kind = rule[0]
        if value is None or kind == "port":
            continue
        if kind == "launch_model":
            out += _check_launch_model(value, cfg, at)
            continue
        if kind == "ticker":
            out += _check_ticker(value, cfg, at)
            continue
        if kind == "usage":
            out += _check_usage(value, at)
            continue
        if kind == "session_guide":
            out += gd.check(value, cfg.session_guide, at)
            continue
        if kind == "origin_map":
            out += origin_map_of(value)[1]
            continue
        if kind == "describe":
            out += dsc.check(value, cfg.describe, at)
            continue
        if kind == "flow":
            out += _check_flow(value, cfg.flow, at)
            continue
        if kind == "a2a_sources":
            out += a2a_sources_of(value, cfg.root)[1]
            continue
        if kind == "work_views":
            out += work_views_of(value)[1]
            continue
        if kind == "files_search":
            out += _check_files_search(value, cfg.files_search, at)
            continue
        if kind == "block":
            if not isinstance(value, dict):
                used = ", ".join(f"{name} {_show(getattr(cfg, r[1]))}" for name, r in rule[1].items())
                out.append(f"{at}: must be a mapping, got {_show(value)}; using {used}")
            else:
                out += check_block(value, cfg, at, rule[1])
            continue
        used = f"using {_show(getattr(cfg, rule[1]))}"
        if kind == "bool" and not isinstance(value, bool):
            out.append(f"{at}: must be true or false, got {_show(value)}; {used}")
        elif kind == "text" and not isinstance(value, str):
            out.append(f"{at}: must be text, got {_show(value)}; {used}")
        elif kind == "choice" and value not in rule[2]:
            out.append(f"{at}: {_show(value)} is not one of {', '.join(rule[2])}; {used}")
        elif key == "work_view" and where == "cockpit" and value not in cfg.work_views:
            out.append(f"{at}: {_show(value)} is not among cockpit.work_views ({', '.join(cfg.work_views)}); {used}")
        elif kind in ("int", "number"):
            if not (_is_int(value) if kind == "int" else _is_number(value)):
                what = "a whole number" if kind == "int" else "a number"
                out.append(f"{at}: must be {what}, got {_show(value)}; {used}")
            elif value < rule[2]:
                out.append(f"{at}: {_show(value)} is below the minimum {rule[2]}; {used}")
    return tuple(out)


def load_web_config(root: Path | str, data: dict | None = None) -> WebConfig:
    root = Path(root).resolve()
    raw = read_config_file(root) if data is None else data
    where = "cockpit"
    w = _dict(raw.get("cockpit"))

    if "port" in w and w.get("port") is not None:
        port = w["port"]
        if not _is_int(port) or not 1024 <= port <= 65535:
            raise WebConfigError(f"{where}.port must be an integer from 1024 to 65535, got {port!r}")
    else:
        port = DEFAULT_PORT

    open_in = w.get("open_in") if w.get("open_in") in OPEN_IN else "auto"
    relay = w.get("relay") is True      # off unless asked for: it needs the cockpit-relay mod in the control session
    profile = w.get("profile") if isinstance(w.get("profile"), str) and w.get("profile") else None
    tabs_seconds = max(5, w["tabs_seconds"]) if _is_int(w.get("tabs_seconds")) else 10

    lang_value = None
    conv = raw.get("language")
    conversation = _dict(conv).get("conversation") if isinstance(conv, dict) else conv
    for candidate in (w.get("language"), conversation):
        if isinstance(candidate, str) and candidate:
            lang_value = candidate
            break
    language = language_of(lang_value)

    full_minutes = max(1, w["full_minutes"]) if _is_number(w.get("full_minutes")) else 10
    snapshot_minutes = max(0, w["snapshot_minutes"]) if _is_number(w.get("snapshot_minutes")) else 60
    idle_minutes = max(0, w["idle_minutes"]) if _is_number(w.get("idle_minutes")) else 10
    voice = w["voice"] if isinstance(w.get("voice"), bool) else False
    target = _dict(w.get("launch")).get("target", "area")
    if target not in TARGETS:
        target = "area"

    control_block = _dict(_dict(raw.get("workplace")).get("control"))
    control = control_block.get("name") if isinstance(control_block.get("name"), str) and control_block.get("name") else None
    names = (ws.get("name") for ws in _dict(raw.get("workplace")).get("workspaces") or ()
             if isinstance(ws, dict))
    areas = tuple(dict.fromkeys(n.strip() for n in names if isinstance(n, str) and n.strip()))

    ts = _dict(_dict(raw.get("integrations")).get("typesafe"))
    ref = ts.get("key_ref")
    jev_key_ref = ref if isinstance(ref, str) and KEYCHAIN_REF_RE.match(ref) else None
    jev_model = ts.get("model") if isinstance(ts.get("model"), str) and JEV_MODEL_RE.match(ts["model"]) else None
    launch_model = launch_model_of(w.get("launch_model"), jev_model)

    def text_or_none(v: Any, cap: int) -> str | None:
        return v.strip()[:cap] if isinstance(v, str) and v.strip() else None

    work_views = work_views_of(w.get("work_views"))[0]
    work_view = w["work_view"] if w.get("work_view") in WORK_VIEWS else "due"
    flow = flow_of(w.get("flow"))
    # a view the list leaves out opens Work through where it is kept and on (a Bridge that switched the other views
    # off never lands in the files), else the first one kept
    fallback = "flow" if "flow" in work_views and flow["enabled"] else work_views[0]
    transcripts, meetings = history_paths_of(raw)

    cfg = WebConfig(root=root, enabled=w.get("enabled") is True, port=port, open_in=open_in, relay=relay,
                    profile=profile, tabs_seconds=tabs_seconds, language=language, full_minutes=full_minutes,
                    voice=voice, target=target, control=control, areas=areas, jev_enabled=ts.get("enabled") is True,
                    jev_key_ref=jev_key_ref, person_name=text_or_none(w.get("person_name"), 60),
                    jev_person=text_or_none(ts.get("person"), 300), jev_criteria=jev_criteria_of(ts.get("criteria")),
                    jev_model=jev_model, launch_model=launch_model, ticker=tk.ticker_of(w.get("ticker")),
                    session_guide=gd.guide_of(w.get("session_guide")),
                    tour=w["tour"] if isinstance(w.get("tour"), bool) else True,
                    setup=w["setup"] if isinstance(w.get("setup"), bool) else True,
                    work_view=work_view if work_view in work_views else fallback, work_views=work_views,
                    focus_to_files=w.get("focus_to_files") is True,
                    files_scope=w["files_scope"] if w.get("files_scope") in FILES_SCOPES else "active",
                    origin_map=origin_map_of(w.get("origin_map"))[0], describe=dsc.describe_of(w.get("describe")),
                    a2a_sources=a2a_sources_of(w.get("a2a_sources"), root)[0],
                    flow=flow, files_search=files_search_of(w.get("files_search")),
                    transcripts=transcripts, meetings=meetings,
                    snapshot_minutes=snapshot_minutes, idle_minutes=idle_minutes, triage_daily=w.get("triage_daily") is True,
                    chat_layout=w.get("chat_layout") if w.get("chat_layout") in CHAT_LAYOUTS else "classic",
                    chat_keep_hours=max(0, w["chat_keep_hours"]) if _is_number(w.get("chat_keep_hours")) else 24,
                    usage_clicks=_dict(w.get("usage")).get("clicks") is not False)
    return replace(cfg, config_warnings=check_block(raw.get("cockpit"), cfg))
