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
from . import guide as gd
from . import ticker as tk

DEFAULT_PORT = 8797
OPEN_IN = ("auto", "cmux", "system", "none")
TARGETS = ("tab", "workspace", "area", "auto")
CHAT_LAYOUTS = ("classic", "workspaces")   # workspaces: the chat as cmux shows it (workspaces, tabs, Bridges, agents)


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
    "snapshot_minutes": ("number", "snapshot_minutes", 0), "voice": ("bool", "voice"),
    "triage_daily": ("bool", "triage_daily"), "language": ("text", "language"),
    "chat_layout": ("choice", "chat_layout", CHAT_LAYOUTS), "chat_keep_hours": ("number", "chat_keep_hours", 0),
    "launch": ("block", {"target": ("choice", "target", TARGETS)}),
    "launch_model": ("launch_model",), "ticker": ("ticker",), "usage": ("usage",),
    "session_guide": ("session_guide",), "tour": ("bool", "tour"),
}
USAGE_KEYS = ("remotes", "remote_file", "host")      # read by usage.remote_hosts, not by the loader
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
    skips what does not fit, so each warning says what is used instead."""
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
        elif key == "host":
            if not isinstance(v, str) or not HOST_SLUG_RE.fullmatch(v):
                out.append(f"{at}: {_show(v)} is no machine name; using the infra/remotes entry that matches this machine")
        elif not isinstance(v, str) or not v.strip():
            out.append(f"{at}: must be text, got {_show(v)}; using \"~/.bridge/resources/usage.json\"")
    return out


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
    voice = w["voice"] if isinstance(w.get("voice"), bool) else False
    target = _dict(w.get("launch")).get("target", "area")
    if target not in TARGETS:
        target = "area"

    control_block = _dict(_dict(raw.get("workplace")).get("control"))
    control = control_block.get("name") if isinstance(control_block.get("name"), str) and control_block.get("name") else None

    ts = _dict(_dict(raw.get("integrations")).get("typesafe"))
    ref = ts.get("key_ref")
    jev_key_ref = ref if isinstance(ref, str) and KEYCHAIN_REF_RE.match(ref) else None
    jev_model = ts.get("model") if isinstance(ts.get("model"), str) and JEV_MODEL_RE.match(ts["model"]) else None
    launch_model = launch_model_of(w.get("launch_model"), jev_model)

    def text_or_none(v: Any, cap: int) -> str | None:
        return v.strip()[:cap] if isinstance(v, str) and v.strip() else None

    cfg = WebConfig(root=root, enabled=w.get("enabled") is True, port=port, open_in=open_in, relay=relay,
                    profile=profile, tabs_seconds=tabs_seconds, language=language, full_minutes=full_minutes,
                    voice=voice, target=target, control=control, jev_enabled=ts.get("enabled") is True,
                    jev_key_ref=jev_key_ref, person_name=text_or_none(w.get("person_name"), 60),
                    jev_person=text_or_none(ts.get("person"), 300), jev_criteria=jev_criteria_of(ts.get("criteria")),
                    jev_model=jev_model, launch_model=launch_model, ticker=tk.ticker_of(w.get("ticker")),
                    session_guide=gd.guide_of(w.get("session_guide")),
                    tour=w["tour"] if isinstance(w.get("tour"), bool) else True,
                    snapshot_minutes=snapshot_minutes, triage_daily=w.get("triage_daily") is True,
                    chat_layout=w.get("chat_layout") if w.get("chat_layout") in CHAT_LAYOUTS else "classic",
                    chat_keep_hours=max(0, w["chat_keep_hours"]) if _is_number(w.get("chat_keep_hours")) else 24)
    return replace(cfg, config_warnings=check_block(raw.get("cockpit"), cfg))
