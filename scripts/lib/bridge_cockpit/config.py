# SPDX-License-Identifier: MIT
"""Configuration of the cockpit: `cockpit:` in bridge-config.yaml.

Values the block leaves out come from `briefing.claude_code_ui` (the briefing-ui mod's block),
so one switch for language, launch target, voice and full run interval covers both.
Resolution rules: docs/bridge-cockpit.md, the cockpit: block.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import re

import yaml

from .. import model_route as mr

DEFAULT_PORT = 8797
OPEN_IN = ("auto", "cmux", "system", "none")
TARGETS = ("tab", "workspace", "area", "auto")


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
    # the model an agent starts with (cockpit.launch_model, model_route.DEFAULTS): off unless switched on;
    # the settings page may change it on top (launch.py), this is what the config says
    launch_model: dict = field(default_factory=lambda: dict(mr.DEFAULTS))


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


def load_web_config(root: Path | str, data: dict | None = None) -> WebConfig:
    root = Path(root).resolve()
    raw = read_config_file(root) if data is None else data
    b = _dict(raw.get("briefing"))
    where = "cockpit"
    w = _dict(raw.get("cockpit"))
    u = _dict(b.get("claude_code_ui"))

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
    for candidate in (w.get("language"), u.get("language"), conversation):
        if isinstance(candidate, str) and candidate:
            lang_value = candidate
            break
    language = language_of(lang_value)

    full = w.get("full_minutes") if _is_number(w.get("full_minutes")) else (
        u.get("full_minutes") if _is_number(u.get("full_minutes")) else 10)
    full_minutes = max(1, full)

    snap = w.get("snapshot_minutes") if _is_number(w.get("snapshot_minutes")) else (
        u.get("snapshot_minutes") if _is_number(u.get("snapshot_minutes")) else 60)
    snapshot_minutes = max(0, snap)

    voice = w["voice"] if isinstance(w.get("voice"), bool) else (
        u["voice"] if isinstance(u.get("voice"), bool) else False)

    wl = _dict(w.get("launch"))
    ul = _dict(u.get("launch"))
    target = wl.get("target") if "target" in wl else ul.get("target", "area")
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

    return WebConfig(root=root, enabled=w.get("enabled") is True, port=port, open_in=open_in, relay=relay,
                     profile=profile, tabs_seconds=tabs_seconds, language=language, full_minutes=full_minutes,
                     voice=voice, target=target, control=control, jev_enabled=ts.get("enabled") is True,
                     jev_key_ref=jev_key_ref, person_name=text_or_none(w.get("person_name"), 60),
                     jev_person=text_or_none(ts.get("person"), 300), jev_criteria=jev_criteria_of(ts.get("criteria")),
                     jev_model=jev_model, launch_model=launch_model,
                     snapshot_minutes=snapshot_minutes, triage_daily=w.get("triage_daily") is True)
