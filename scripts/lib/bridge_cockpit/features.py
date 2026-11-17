# SPDX-License-Identifier: MIT
"""The Features area of the settings page: one catalogue of what the page switches, the overrides, presets.

Many keys of the `cockpit:` block switch on a part of the page that a fresh cockpit leaves off (Work through and its
sub switches, the briefs, the daily sort, the chat as cmux, Ask AI in Files). CATALOG names each of them once, with
the key patch it stands for, beside the three switches the settings page already keeps in stores of their own
(launch.py, ticker.py, guide.py). The page changes a config feature on top of the config, in <state>/features.json,
and load_web_config merges that into the block before anything reads it, so bridge-config.yaml is never written and
every consumer sees one effective block. A config feature acts after a restart; a store feature acts at once.

A preset is a named set of values: `basic` and `full` are built in, more are files in workflow/cockpit-presets/
(an org overlay can ship them). Applying one sets exactly the features it names.
"""
from __future__ import annotations

import copy
import re
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from .config import WORK_VIEWS, WebConfigError, _show, load_web_config, read_config_file
from .store import atomic_write_json, read_json as _read_json

FILE = "features.json"
PRESET_DIR = "workflow/cockpit-presets"
PRESET_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{0,63}\Z")
SCOPES = ("user", "org", "personal")
STORE_FILES = {"launch": "launch.json", "ticker": "ticker.json", "guide": "guide.json"}


class FeatureError(Exception):
    def __init__(self, status: int, code: str, message: str, field: str | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.field = status, code, message, field


@dataclass(frozen=True)
class Feature:
    id: str
    group: str                     # work, chat, files, helpers, page: the page's card, in this order
    kind: str                      # switch or choice
    values: tuple = ()             # a choice's values, the first is its default
    requires: str | None = None    # a switch that must be on for this one to act
    ai: bool = False               # makes model calls that cost money (within a daily budget)
    store: str | None = None       # None: a key of the cockpit: block; launch, ticker, guide: that store's `enabled`
    area: str | None = None        # the settings area that holds its details
    path: tuple = ()               # the key under cockpit: a config feature stands for (flow_only has two, FLOW_ONLY)

    @property
    def default(self) -> Any:
        return self.values[0] if self.kind == "choice" else False


CATALOG: tuple[Feature, ...] = (
    Feature("flow", "work", "switch", path=("flow", "enabled")),
    Feature("flow_only", "work", "switch", requires="flow"),
    Feature("flow_themes", "work", "switch", requires="flow", ai=True, path=("flow", "themes", "enabled")),
    Feature("flow_summary", "work", "switch", requires="flow", ai=True, path=("flow", "summary", "enabled")),
    Feature("flow_instruct", "work", "switch", requires="flow", ai=True, path=("flow", "instruct", "enabled")),
    Feature("flow_checkin", "work", "switch", requires="flow", ai=True, path=("flow", "checkin", "enabled")),
    Feature("flow_prio_haiku", "work", "switch", requires="flow", ai=True, path=("flow", "prio", "haiku", "enabled")),
    Feature("flow_seen", "work", "switch", requires="flow", path=("flow", "seen", "enabled")),
    Feature("flow_attach", "work", "switch", requires="flow", path=("flow", "attach", "enabled")),
    Feature("describe", "work", "choice", ("off", "missing", "stale"), ai=True, path=("describe", "auto")),
    Feature("triage_daily", "work", "switch", ai=True, path=("triage_daily",)),
    Feature("chat_layout", "chat", "choice", ("classic", "workspaces"), path=("chat_layout",)),
    Feature("files_scope", "files", "choice", ("active", "all"), path=("files_scope",)),
    Feature("files_search", "files", "switch", ai=True, path=("files_search", "enabled")),
    Feature("launch_model", "helpers", "switch", ai=True, store="launch", area="launch"),
    Feature("ticker", "helpers", "switch", store="ticker", area="ticker"),
    Feature("session_guide", "helpers", "switch", ai=True, store="guide", area="guide"),
    Feature("voice", "page", "switch", path=("voice",)),
)
BY_ID = {f.id: f for f in CATALOG}
CONFIG_FEATURES = tuple(f for f in CATALOG if f.store is None)
# flow_only: Work through alone in the work tab, beside the Files tab (docs/bridge-cockpit.md, cockpit.work_views). Off
# is stored only where the config itself has it on, and then gives every view back but keeps the config's work_view
FLOW_ONLY = {True: {"work_view": "flow", "work_views": ["files", "flow"]},
             False: {"work_views": list(WORK_VIEWS)}}
# a served cockpit (serve --served) never sorts by itself (server.served_config): the switch is no switch there
SERVED_OFF = frozenset({"triage_daily"})
FLOW_ONLY_NEEDS = "needs flow (Work through) on"


# ---------------------------------------------------------------- one feature

def valid(f: Feature, value: Any) -> bool:
    return isinstance(value, bool) if f.kind == "switch" else isinstance(value, str) and value in f.values


def wants(f: Feature) -> str:
    return "must be true or false" if f.kind == "switch" else f"must be one of {', '.join(f.values)}"


def patch(fid: str, value: Any) -> dict:
    """The keys under cockpit: a config feature at `value` stands for; KeyError for a store feature"""
    f = BY_ID[fid]
    if f.store is not None:
        raise KeyError(fid)
    if f.id == "flow_only":
        return copy.deepcopy(FLOW_ONLY[bool(value)])
    out: Any = value
    for key in reversed(f.path):
        out = {key: out}
    return out


def value_of(cfg: Any, fid: str) -> Any:
    """What a config feature is in a loaded WebConfig"""
    f = BY_ID[fid]
    if f.id == "flow_only":
        return tuple(getattr(cfg, "work_views", ()) or ()) == ("files", "flow")
    out: Any = getattr(cfg, f.path[0])
    for key in f.path[1:]:
        out = out[key]
    return out


def deep_merge(base: Any, top: dict) -> dict:
    """`top` over `base`, mapping by mapping; any other value of `top` replaces; neither is changed"""
    out = copy.deepcopy(base) if isinstance(base, dict) else {}
    for key, value in top.items():
        out[key] = deep_merge(out.get(key), value) if isinstance(value, dict) else copy.deepcopy(value)
    return out


# ---------------------------------------------------------------- the overrides (load_web_config)

def read_json(path: Path) -> Any:
    """store.read_json, and a file nested too deep for the parser is no JSON either"""
    try:
        return _read_json(path)
    except RecursionError:
        return None


def state_path(root: Path | str, state_dir: Path | str | None = None) -> Path:
    """<state>/features.json; the state dir defaults to <root>/.bridge/cockpit (server.default_state_dir)"""
    return Path(state_dir or Path(root) / ".bridge" / "cockpit") / FILE


def check_overrides(data: Any) -> tuple[dict, list[str]]:
    """What a features.json may change: catalogue ids of config features with a value they take. Anything else
    (another key of the block, a store feature, a bad value) is left out and named. None (no file, or one that is
    no JSON) is no override."""
    if data is None:
        return {}, []
    if not isinstance(data, dict):
        return {}, [f"{FILE}: must be an object of feature ids, got {_show(data)}; ignored"]
    out, warnings = {}, []
    for key, value in data.items():
        at = f"{FILE}.{str(key)[:40]}"
        f = BY_ID.get(key)
        if f is None:
            warnings.append(f"{at}: no feature of the settings page, ignored")
        elif f.store is not None:
            warnings.append(f"{at}: kept in {STORE_FILES[f.store]}, not here; ignored")
        elif not valid(f, value):
            warnings.append(f"{at}: {wants(f)}, got {_show(value)}; ignored")
        else:
            out[key] = value
    return out, warnings


def merged(raw: dict, overrides: Any, base: Any = None) -> tuple[dict, list[str]]:
    """bridge-config with the overrides deep merged into its cockpit: block, and the warnings; `raw` is not changed.
    `base` is the WebConfig of `raw` alone: an override equal to it is none (the config may have changed since it
    was saved, and a stale value must not overwrite keys beside it), and flow_only needs flow on"""
    clean, warnings = check_overrides(overrides)
    if base is not None:
        clean = {k: v for k, v in clean.items() if v != value_of(base, k)}
    if clean.get("flow_only") is True and not clean.get("flow", value_of(base, "flow") if base is not None else False):
        del clean["flow_only"]
        warnings.append(f"{FILE}.flow_only: {FLOW_ONLY_NEEDS}; ignored")
    if not clean:
        return raw, warnings
    block = raw.get("cockpit")
    if block is not None and not isinstance(block, dict):
        return raw, warnings + [f"{FILE}: the cockpit: block is no mapping; ignored"]
    top: dict = {}
    for f in CONFIG_FEATURES:            # catalogue order: one result whatever the file's order
        if f.id in clean:
            top = deep_merge(top, patch(f.id, clean[f.id]))
    return {**raw, "cockpit": deep_merge(block or {}, top)}, warnings


def read_overrides(path: Path) -> dict:
    return check_overrides(read_json(path))[0]


# ---------------------------------------------------------------- presets

def builtin_presets() -> dict[str, dict]:
    """basic: every feature at its default. full: every switch on and the widest choices, except Ask AI in Files
    (it should first get block words) and flow_only (it hides views), which full leaves as they are"""
    full_choices = {"describe": "stale", "chat_layout": "workspaces", "files_scope": "all"}
    return {"basic": {f.id: f.default for f in CATALOG},
            "full": {f.id: full_choices.get(f.id, True) for f in CATALOG if f.id not in ("files_search", "flow_only")}}


def load_presets(root: Path | str) -> tuple[list[dict], list[str]]:
    """The preset files of workflow/cockpit-presets/ (`_` files skipped, rules/discovery.md), each cleaned: an unknown
    feature or a bad value is left out and named, a file that is no preset, names another id or a built-in one is
    skipped and named"""
    folder = Path(root) / PRESET_DIR
    if not folder.is_dir():
        return [], []
    builtin = builtin_presets()
    out, warnings = [], []
    for path in sorted(folder.glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        rel = f"{PRESET_DIR}/{path.name}"
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, ValueError, yaml.YAMLError):      # an impossible date is a ValueError of the loader
            warnings.append(f"{rel}: cannot be read as YAML; skipped")
            continue
        if not isinstance(data, dict) or not isinstance(data.get("features"), dict):
            warnings.append(f"{rel}: no mapping with features; skipped")
            continue
        pid = data.get("id")
        if not isinstance(pid, str) or pid != path.stem or not PRESET_ID_RE.match(pid):
            warnings.append(f"{rel}: the id must be the file name {path.stem}, got {_show(pid)}; skipped")
            continue
        if pid in builtin:
            warnings.append(f"{rel}: {pid} is a built-in preset; skipped")
            continue
        features = {}
        for key, value in data["features"].items():
            f = BY_ID.get(key)
            if f is not None and value is False and "off" in f.values:
                value = "off"            # YAML reads a bare `off` as false, as describe.py takes it in the config
            if f is None:
                warnings.append(f"{rel}: unknown feature {str(key)[:40]}, left out")
            elif not valid(f, value):
                warnings.append(f"{rel}: {key} {wants(f)}, got {_show(value)}; left out")
            else:
                features[key] = value
        if features.get("flow_only") is True and features.get("flow") is not True:
            del features["flow_only"]          # a preset means the same whatever is on: flow_only comes with flow
            warnings.append(f"{rel}: flow_only {FLOW_ONLY_NEEDS} in the same preset (flow: true); left out")
        if not features:
            warnings.append(f"{rel}: no feature left to set; skipped")
            continue
        title, description = data.get("title"), data.get("description")
        out.append({"id": pid, "builtin": False,
                    "title": title.strip()[:80] if isinstance(title, str) and title.strip() else pid,
                    "description": description.strip()[:300] if isinstance(description, str) and description.strip() else None,
                    "scope": data.get("scope") if data.get("scope") in SCOPES else None, "features": features})
    return out, warnings


# ---------------------------------------------------------------- the store

class Features:
    """The overrides of the settings page's Features area, and its presets. Only config features are kept here;
    a store feature is that store's own `enabled` (launch.py, ticker.py, guide.py)."""

    def __init__(self, app: Any):
        self.app = app
        self.path = Path(app.state_dir) / FILE
        self.lock = threading.Lock()
        self._config: tuple[tuple, Any] | None = None     # (stamp of bridge-config.yaml, the config alone)
        # what the server runs with: a value that differs from it later acts only after a restart
        self.at_start = self.values()

    # ------------------------------------------------------------ values

    def config_cfg(self) -> Any:
        """The WebConfig of bridge-config.yaml alone, read again only when the file changed"""
        path = Path(self.app.root) / "bridge-config.yaml"
        try:
            st = path.stat()
            stamp: tuple = (st.st_mtime_ns, st.st_size)
        except OSError:
            stamp = ()
        if self._config is None or self._config[0] != stamp:
            try:
                cfg = load_web_config(self.app.root, data=read_config_file(self.app.root))
            except WebConfigError:          # a file that no longer loads: what the server read at its start
                cfg = self.app.cfg
            self._config = (stamp, cfg)
        return self._config[1]

    def store_of(self, f: Feature) -> Any:
        return {"launch": self.app.launch_model, "ticker": self.app.ticker, "guide": self.app.guide}[f.store]

    def config_values(self) -> dict:
        """Every feature as bridge-config.yaml alone gives it (a store feature: its store's block of the config)"""
        cfg = self.config_cfg()
        return {f.id: bool(self.store_of(f).defaults().get("enabled")) if f.store else value_of(cfg, f.id)
                for f in CATALOG}

    def overrides(self) -> dict:
        return read_overrides(self.path)

    def values(self, config: dict | None = None) -> dict:
        """The config features as they act after a restart: the overrides on top of the config"""
        config = self.config_values() if config is None else config
        over = self.overrides()
        return {f.id: over.get(f.id, config[f.id]) for f in CONFIG_FEATURES}

    def current(self, config: dict | None = None) -> dict:
        """Every feature now: a config one as values() has it, a store one as its store has it"""
        out = self.values(config)
        out.update({f.id: bool(self.store_of(f).settings().get("enabled")) for f in CATALOG if f.store})
        return {f.id: out[f.id] for f in CATALOG}

    def unavailable(self) -> frozenset:
        """Features this cockpit never runs whatever they say: a served one never sorts by itself"""
        return SERVED_OFF if getattr(self.app.cfg, "served", False) else frozenset()

    def pending(self) -> bool:
        """A config feature differs from what the server started with (a change of the page, or of bridge-config.yaml
        by hand): it acts after a restart"""
        off = self.unavailable()
        now = self.values()
        return any(now[k] != self.at_start.get(k) for k in now if k not in off)

    # ------------------------------------------------------------ changes

    @staticmethod
    def check(change: Any) -> None:
        if not isinstance(change, dict) or not change:
            raise FeatureError(400, "invalid_argument", "must be an object of features", "settings")
        for key, value in change.items():
            f = BY_ID.get(key) if isinstance(key, str) else None
            if f is None:
                raise FeatureError(400, "invalid_argument", "unknown feature", str(key)[:40])
            if not valid(f, value):
                raise FeatureError(400, "invalid_argument", wants(f), key)

    def save(self, change: Any) -> dict:
        """Every value checked before anything is written; a config feature into features.json (a value equal to
        the config's is dropped, as launch.py does, so the page can mark what differs), a store feature into its
        store. Returns what changed: {config: whether a config feature's value moved, stores: [store, ...]}"""
        self.check(change)
        off = self.unavailable()
        change = {k: v for k, v in change.items() if k not in off}        # a no-op, never a restart
        config = self.config_values()
        with self.lock:
            before = self.values(config)
            ours = {k: v for k, v in change.items() if BY_ID[k].store is None}
            if ours.get("flow_only") is True and not ours.get("flow", before["flow"]):
                raise FeatureError(400, "invalid_argument", FLOW_ONLY_NEEDS, "flow_only")
            if ours:
                kept = {**self.overrides(), **ours}
                if not kept.get("flow", config["flow"]):
                    kept.pop("flow_only", None)      # Work through off takes its flow_only along: the config's own
                atomic_write_json(self.path, {f.id: kept[f.id] for f in CONFIG_FEATURES
                                              if f.id in kept and kept[f.id] != config[f.id]})
            after = self.values(config)
        stores = []
        for key, value in change.items():
            f = BY_ID[key]
            if f.store and bool(self.store_of(f).settings().get("enabled")) != value:
                self.store_of(f).save({"enabled": value})
                stores.append(f.store)
        return {"config": after != before, "stores": stores}

    def reset(self) -> dict:
        """Back to bridge-config.yaml: features.json empty, and each store's `enabled` saved as the config's own, so
        the store forgets it (its other settings stay)"""
        with self.lock:
            before = self.values()
            atomic_write_json(self.path, {})
            after = self.values()
        stores = []
        for f in CATALOG:
            if f.store:
                store = self.store_of(f)
                base = bool(store.defaults().get("enabled"))
                if bool(store.settings().get("enabled")) != base:
                    store.save({"enabled": base})
                    stores.append(f.store)
        return {"config": after != before, "stores": stores}

    def presets(self) -> tuple[list[dict], list[str]]:
        builtin = [{"id": pid, "builtin": True, "title": None, "description": None, "scope": None, "features": features}
                   for pid, features in builtin_presets().items()]
        files, warnings = load_presets(self.app.root)
        return builtin + files, warnings

    def apply(self, pid: str) -> dict:
        """Set exactly the features the preset names; the others keep their value"""
        preset = next((p for p in self.presets()[0] if p["id"] == pid), None)
        if preset is None:
            raise FeatureError(404, "not_found", "no such preset", "preset")
        return self.save(dict(preset["features"]))

    @staticmethod
    def matches(preset: dict, now: dict, off: frozenset = frozenset()) -> bool:
        """Every feature the preset names has that value now (one this cockpit never runs aside)"""
        return all(now.get(k) == v for k, v in preset["features"].items() if k not in off)

    # ------------------------------------------------------------ the page

    def state(self) -> dict:
        config = self.config_values()
        now = self.current(config)
        off = self.unavailable()
        items = []
        for f in CATALOG:
            item: dict = {"id": f.id, "group": f.group, "kind": f.kind}
            if f.kind == "choice":
                item["values"] = list(f.values)
            item.update({"value": now[f.id], "config": config[f.id], "overridden": now[f.id] != config[f.id],
                         "requires": f.requires, "ai": f.ai, "store": f.store, "area": f.area,
                         "available": f.id not in off})
            items.append(item)
        presets, warnings = self.presets()
        block = (getattr(self.config_cfg(), "files_search", None) or {}).get("block") or []
        return {"items": items,
                "presets": [{**p, "features": dict(p["features"]), "matches": self.matches(p, now, off)} for p in presets],
                "overridden": sum(1 for i in items if i["overridden"]),
                # pending: a config value differs from the start; requested: this process restarts now; can: it is able to;
                # code: newer code lies on disk than it runs (an update, codestamp.py); done_ms: when the restart it
                # came from ran, None after a plain start
                "restart": {"pending": self.pending(), "requested": bool(getattr(self.app, "restart_requested", False)),
                            "can": getattr(self.app, "on_restart", None) is not None,
                            "code": bool(getattr(self.app, "code_newer", False)),
                            "done_ms": getattr(self.app, "restarted_ms", None)},
                "files_block": list(block),
                "warnings": check_overrides(read_json(self.path))[1] + warnings}
