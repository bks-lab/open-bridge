#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Briefing profiles: each person's briefing is a file the Bridge executes.

A profile (workflow/briefings/<id>.yaml) is an ordered list of sections: the
inbox, the advice checks, the workplace plan, tasks, recent activity, the
calendar, any tracker (GitHub, a GitHub board, GitLab, Azure Boards, Jira,
Linear) and any program that prints JSON. This script runs the sections
deterministically; the agent advises on and renders what it collected
(skills/briefing/references/control.md). Before profiles the collection steps
were prose an agent re-read every run, and a run could skip one.

    python3 scripts/briefing.py list                 # profiles this Bridge knows
    python3 scripts/briefing.py show [<id>]          # the resolved profile
    python3 scripts/briefing.py offer "<text>"       # profiles whose offer_on matches
    python3 scripts/briefing.py collect [<id>] [--json] [--file] [--no-save]
    python3 scripts/briefing.py render [<id>]        # collect + terminal text
    python3 scripts/briefing.py validate             # every profile, exit 1 on a problem

Which profile: the id given; else bridge-config.yaml `briefing.default`; else
the one with `default: true`; else the only one; several without a
default exit 2 and name them (the agent asks). No profile at all: a built-in
one equal to the briefing before profiles (`show` prints it).

Sections never abort the briefing: a missing CLI, a missing token or a timeout
is `status: error` with the reason. Each run is compared with the last one
(.bridge/briefings/<id>.last.json, per machine) and rows carry `new`/`changed`.
With --file, rows matching a section's `to_inbox` rules become inbox items under
the key `briefing:<profile>:<section>:<item>`; an item whose row is gone closes
on the next run in which that section completed. Model: docs/briefings.md.
Contract: scripts/tests/test_briefing.py.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import datetime as dt
import importlib.util
import json
import os
import random
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.parse
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
# Run as a script the engine is `__main__`; the providers look up SourceError
# under `briefing`, so both names must reach the same module.
sys.modules.setdefault("briefing", sys.modules[__name__])
FAMILY = Path("workflow") / "briefings"
SNAPSHOTS = Path(".bridge") / "briefings"
CACHE = Path(".bridge") / "briefing-cache"   # a section's last answer, for `cache_minutes`
KEY_PREFIX = "briefing:"
DEFAULT_TIMEOUT = 30

SECTION_KINDS = ("inbox", "advise", "workplace", "tasks", "activity", "commits", "calendar", "tracker", "command")
TRACKERS = ("github", "github-board", "github-work", "gitlab", "ado", "jira", "linear")
GITHUB_TRACKERS = ("github", "github-board", "github-work")
CALENDARS = ("auto", "icalbuddy", "ics", "command")
STATES = ("new", "ready", "in_progress", "review", "done", "blocked", "removed")
PROFILE_KEYS = {"schema_version", "scope", "id", "title", "for", "default", "offer_on", "timeout_sec", "sections",
                "view", "mutes", "extends"}
# what a profile never takes over from the one it extends: it is not that briefing, only built on it
NOT_INHERITED = {"id", "title", "default", "offer_on", "extends", "_path"}
SECTION_KEYS = {"kind", "id", "title", "max", "to_inbox", "provider", "query", "account_ref", "state_map",
                "status", "contexts", "days", "path", "argv", "exclude_calendars", "info_calendars", "bucket",
                "repos", "author", "all_branches", "summary", "report_ok", "covers", "kinds", "skip_kinds",
                "deferred", "cache_minutes", "step_headings", "actions_argv", "event_steps", "prepare",
                "row_steps", "default_steps", "link"}
# A profile is committed and often shared: a value under one of these names is
# a credential, and credentials only ever travel as references (account_ref).
SECRET_NAME = re.compile(r"(token|secret|password|passwd|api[_-]?key|private[_-]?key)", re.I)
REF_URI = re.compile(r"^[a-z][a-z0-9+-]*://")


class SourceError(Exception):
    """A section's source could not answer (CLI missing, auth, timeout, bad output)."""


class Skip(Exception):
    """A section that does not apply on this machine (e.g. no calendar tool)."""


class Ambiguous(Exception):
    def __init__(self, ids):
        super().__init__("several profiles and none is the default: " + ", ".join(ids))
        self.ids = list(ids)


class UnknownProfile(Exception):
    pass


# ---------------------------------------------------------------- module loading

_LOADING = threading.RLock()   # sections run side by side: a half-loaded module must not be seen


def _load_module(name: str, path: Path):
    with _LOADING:
        return _load_module_locked(name, path)


def _load_module_locked(name: str, path: Path):
    if name in sys.modules:
        return sys.modules[name]
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:  # pragma: no cover
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    previous, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


def _inbox():
    return _load_module("inbox", ROOT / "scripts" / "inbox.py")


def _view():
    return _load_module("briefing_view", ROOT / "scripts" / "lib" / "briefing_view.py")


def _providers():
    if str(ROOT / "scripts") not in sys.path:
        sys.path.insert(0, str(ROOT / "scripts"))
    previous, sys.dont_write_bytecode = sys.dont_write_bytecode, True
    try:
        import lib.briefing_providers as providers  # noqa: E402  (path set above)
    finally:
        sys.dont_write_bytecode = previous
    return providers


# ---------------------------------------------------------------- context

def _own_python(argv) -> list:
    """A section that says `python3` means this interpreter: the bare name follows the
    package manager to whatever release it last installed, packages or not."""
    argv = list(argv)
    if argv and argv[0] in ("python3", "python"):
        argv[0] = sys.executable
    return argv


def _default_run(argv, timeout=DEFAULT_TIMEOUT, cwd=None) -> str:
    try:
        res = subprocess.run(_own_python(argv),capture_output=True, text=True, timeout=timeout, cwd=cwd)
    except FileNotFoundError:
        raise SourceError(f"{argv[0]} is not installed") from None
    except subprocess.TimeoutExpired:
        raise SourceError(f"{argv[0]} took longer than {timeout:.0f} s") from None
    if res.returncode != 0:
        tail = (res.stderr or res.stdout or "").strip().splitlines()[-1:] or [f"exit {res.returncode}"]
        raise SourceError(f"{Path(argv[0]).name}: {tail[0][:200]}")
    return res.stdout


def _default_http(method: str, url: str, headers: dict | None = None, body=None, timeout=DEFAULT_TIMEOUT):
    import urllib.error
    import urllib.request
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method,
                                 headers={"Accept": "application/json", **({"Content-Type": "application/json"}
                                                                            if data else {}), **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 (URL comes from the account file)
            return json.loads(resp.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as exc:
        raise SourceError(f"HTTP {exc.code} from {url.split('?')[0]}") from None
    except (urllib.error.URLError, TimeoutError, ValueError) as exc:
        raise SourceError(f"{url.split('?')[0]}: {exc}") from None


def _default_secret(ref: str) -> str:
    """The value behind a reference URI, through the secrets engine. Never logged."""
    sys.path.insert(0, str(ROOT / "skills" / "secrets"))
    try:
        from engine.resolve import Resolver  # type: ignore
    except ImportError as exc:  # pragma: no cover
        raise SourceError(f"secrets engine unavailable ({exc})") from None
    try:
        return Resolver().require(ref).expose_text()
    except Exception as exc:  # the engine names what was missing, never the value
        raise SourceError(f"cannot read {ref}: {exc.__class__.__name__}") from None


# A GitHub rate-limit error during a burst (several sessions at once) clears within
# seconds; the token's quota is rarely what ran out. Wait, then try again, twice.
# Each wait is stretched by up to half at random: calls that run side by side (the
# boards of one section) would otherwise all retry in the same second and hit the
# limit again. gh 2.x reports a throttled owner lookup as "unknown owner type".
GH_RETRY_WAITS = (5, 15)
GH_RETRY_SPREAD = 0.5
GH_RATE_LIMIT = re.compile(r"rate limit|secondary rate|abuse detection|unknown owner type", re.I)
# The hour's budget is spent (not a burst): waiting seconds and asking again only spends more of nothing.
GH_BUDGET_SPENT = re.compile(r"API rate limit (already )?exceeded|graphql_rate_limit", re.I)


class Context:
    """What a section may use. Tests replace run/http/secret with recorded answers."""

    def __init__(self, root: Path, *, now: dt.datetime | None = None, run=None, http=None, secret=None,
                 cfg: dict | None = None, timeout: int = DEFAULT_TIMEOUT, sleep=None, rand=None):
        self.root = Path(root)
        self.now = now or dt.datetime.now()
        self._run = run or _default_run
        self._http = http
        self._secret = secret or _default_secret
        self._sleep = sleep or time.sleep
        self._rand = rand or random.random
        self._revealed: list = []
        self.cfg = cfg if cfg is not None else read_config(self.root)
        self.timeout = timeout
        self.calendar: list | None = None   # events of the profile's calendar sections, for advise
        self._local = threading.local()     # sections run side by side: each thread its own deadline
        self.lookahead: int | None = None   # days a view looks ahead; deferred items returning in them show
        self.fresh = False                  # True: ask every source, whatever `cache_minutes` allows

    @staticmethod
    def load_module(name: str, path: Path):
        """Load a helper module under the briefing's lock: sections run side by side, and a
        provider that loads one itself would let another thread see it half-loaded."""
        return _load_module(name, path)

    @property
    def deadline(self) -> float | None:
        """Monotonic end of the section running in this thread."""
        return getattr(self._local, "deadline", None)

    @deadline.setter
    def deadline(self, value: float | None) -> None:
        self._local.deadline = value

    def remaining(self) -> float:
        """Seconds left for the running section: its limit covers ALL its calls together."""
        if self.deadline is None:
            return float(self.timeout)
        left = self.deadline - time.monotonic()
        if left <= 0:
            raise SourceError(f"section time limit of {self.timeout} s reached")
        return min(float(self.timeout), left)

    def run(self, argv, timeout=None, cwd=None) -> str:
        gh = bool(argv) and argv[0] == "gh"
        free = gh and list(argv[:3]) == ["gh", "api", "rate_limit"]      # costs nothing, says when it resets
        waits = [w * (1 + GH_RETRY_SPREAD * self._rand()) for w in GH_RETRY_WAITS] if gh else []
        while True:
            if gh and not free:
                # every call, not only each section: sections run side by side, and one that hit the limit
                # stops the others at their next call
                blocked = github_blocked(self.root, self.now)
                if blocked is not None:
                    raise SourceError(f"GitHub rate limit, not asked until {blocked:%H:%M}")
            limit = self.remaining()
            try:
                return self._run(argv, timeout=min(float(timeout), limit) if timeout else limit, cwd=cwd)
            except SourceError as exc:
                if gh and not free and GH_BUDGET_SPENT.search(str(exc)):
                    block_github(self.root, self, str(exc))
                    raise
                # Only a rate-limit burst, only gh, and only when the wait still fits
                # the section's time limit; anything else fails as before.
                if not (waits and GH_RATE_LIMIT.search(str(exc)) and waits[0] < self.remaining() - 1):
                    raise
                self._sleep(waits.pop(0))

    def http(self, method: str, url: str, headers: dict | None = None, body=None):
        limit = self.remaining()
        if self._http is None:
            return _default_http(method, url, headers, body, timeout=limit)
        return self._http(method, url, headers, body)

    def secret(self, ref: str) -> str:
        value = self._secret(ref)
        if value:
            self._revealed.append(str(value))
        return value

    def redact(self, text: str) -> str:
        """A reason may quote an exception; no value read through `secret` leaves this process."""
        for value in self._revealed:
            if len(value) >= 4:
                text = text.replace(value, "[redacted]")
        return text

    def account(self, section: dict) -> dict:
        ref = section.get("account_ref")
        if not ref:
            raise SourceError("this provider needs account_ref (an identity/accounts/<id>.yaml)")
        path = (self.root / ref).resolve()
        if not path.is_relative_to(self.root.resolve()):
            raise SourceError(f"account_ref {ref} points outside this Bridge")
        if not path.is_file():
            raise SourceError(f"account_ref {ref} does not exist")
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        return data if isinstance(data, dict) else {}


def read_config(root: Path) -> dict:
    path = root / "bridge-config.yaml"
    if not path.is_file():
        return {}
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


# ---------------------------------------------------------------- profiles

def _raw_profiles(root: Path) -> list:
    out = []
    for path in sorted((root / FAMILY).glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue          # validate names it
        if isinstance(data, dict):
            out.append({**data, "_path": str(path.relative_to(root))})
    return out


def _extended(profile: dict, by_id: dict, seen: frozenset = frozenset()) -> tuple[dict, str | None]:
    """`extends: <id>`: the base's sections first (one of the same id is replaced by the profile's own),
    then its own; the view key by key, the profile's own winning; mutes added. id, title, default and
    offer_on stay the profile's: the cockpit's profile builds on the morning briefing without becoming it.
    Returns (profile, problem); an unknown base or a circle leaves the profile as it is and names it."""
    base_id = profile.get("extends")
    if base_id is None:
        return profile, None
    if not isinstance(base_id, str) or base_id not in by_id:
        return profile, f"extends: no profile {base_id!r}"
    if base_id in seen or base_id == profile.get("id"):
        return profile, "extends: a circle"
    base, problem = _extended(by_id[base_id], by_id, seen | {profile.get("id")})
    if problem:
        return profile, "extends: a circle" if "circle" in problem else problem
    own = [x for x in profile.get("sections") or [] if isinstance(x, dict)]
    own_ids = {section_id(x) for x in own}
    sections = [x for x in base.get("sections") or [] if isinstance(x, dict) and section_id(x) not in own_ids] + own
    out = {**{k: v for k, v in base.items() if k not in NOT_INHERITED}, **profile, "sections": sections}
    if isinstance(base.get("view"), dict) or isinstance(profile.get("view"), dict):
        out["view"] = {**(base.get("view") if isinstance(base.get("view"), dict) else {}),
                       **(profile.get("view") if isinstance(profile.get("view"), dict) else {})}
    mutes = [*(base.get("mutes") or []), *(profile.get("mutes") or [])]
    if mutes:
        out["mutes"] = mutes
    return out, None


def load_profiles(root: Path) -> list:
    raw = _raw_profiles(root)
    by_id = {p.get("id"): p for p in raw}
    return [_extended(p, by_id)[0] for p in raw]


def conversation_language(cfg: dict) -> str:
    """bridge-config.yaml language.conversation (a mapping or a plain code); en when unset."""
    lang = cfg.get("language")
    return str((lang.get("conversation") if isinstance(lang, dict) else lang) or "en").strip().lower()


def builtin_profile(cfg: dict) -> dict:
    """The briefing before profiles: inbox, advice, tasks, the enabled trackers, calendar,
    activity, and the workplace plan when a `workplace:` block is configured."""
    words = _view().labels_for(conversation_language(cfg))     # the section names in the Bridge's language
    sections = [{"kind": "inbox", "title": words["section_inbox"]}, {"kind": "advise", "title": words["section_advise"]},
                {"kind": "tasks", "title": words["section_tasks"], "status": ["doing", "review"]},
                # for the dashboard's work page only (bucket none: never counted in the briefing):
                # what runs on until a day, and what comes next
                {"kind": "inbox", "id": "inbox-runs", "title": words["section_runs_on"], "deferred": "runs", "bucket": "none"},
                {"kind": "tasks", "id": "tasks-next", "title": words["section_next_up"], "status": ["backlog"],
                 "bucket": "none"}]
    integrations = cfg.get("integrations") or {}
    if (integrations.get("github") or {}).get("enabled"):
        sections.append({"kind": "tracker", "id": "github", "title": "GitHub", "provider": "github-board"})
    # The keys trackers/gitlab.md and trackers/ado.md documented under integrations.<name>.
    gitlab = integrations.get("gitlab") or {}
    if gitlab.get("enabled") and gitlab.get("repos"):     # enabled without repos listed nothing before either
        query = {"repos": list(gitlab["repos"])}
        if gitlab.get("limit"):
            query["limit"] = gitlab["limit"]
        sections.append({"kind": "tracker", "id": "gitlab", "title": "GitLab", "provider": "gitlab", "query": query})
    ado = integrations.get("ado") or {}
    if ado.get("enabled"):
        query = {k: v for k, v in (("organization", ado.get("org")), ("project", ado.get("project")),
                                   ("wiql", (ado.get("queries") or {}).get("open"))) if v}
        sections.append({"kind": "tracker", "id": "ado", "title": "Azure Boards", "provider": "ado", "query": query})
    sections += [{"kind": "calendar", "title": words["section_calendar"], "provider": "auto", "days": 1},
                 {"kind": "activity", "title": words["section_activity"], "days": 7}]
    # A Bridge that configured a workplace (docs/workplace.md) wants the day's tabs
    # proposed in its briefing, whichever driver opens them.
    if cfg.get("workplace"):
        sections.append({"kind": "workplace", "title": words["section_workplace"]})
    return {"schema_version": 1, "scope": "core", "id": "builtin", "title": "Briefing", "sections": sections,
            "_path": "(built-in)"}


def select(root: Path, cfg: dict, pid: str | None = None) -> dict:
    profiles = load_profiles(root)
    by_id = {p.get("id"): p for p in profiles}
    if pid:
        if pid == "builtin":
            return builtin_profile(cfg)
        if pid not in by_id:
            raise UnknownProfile(f"no profile {pid!r}; known: {', '.join(sorted(by_id)) or 'none'}")
        return by_id[pid]
    if not profiles:
        return builtin_profile(cfg)
    # The config is this person's choice and wins over a flag in a file, which
    # may come from a shared (org) overlay.
    named = (cfg.get("briefing") or {}).get("default")
    if named in by_id:
        return by_id[named]
    flagged = [p for p in profiles if p.get("default") is True]
    if flagged:
        return flagged[0]
    if len(profiles) == 1:
        return profiles[0]
    raise Ambiguous(sorted(by_id))


def offer(profiles: list, text: str) -> list:
    low = (text or "").lower()
    return [p["id"] for p in profiles if any(str(w).lower() in low for w in p.get("offer_on") or [])]


def section_id(section: dict) -> str:
    return str(section.get("id") or section.get("kind"))


def _secret_values(value, path="") -> list:
    found = []
    if isinstance(value, dict):
        for k, v in value.items():
            here = f"{path}.{k}" if path else str(k)
            if SECRET_NAME.search(str(k)) and isinstance(v, str) and v and not REF_URI.match(v) \
                    and not str(k).endswith("_ref"):
                found.append(here)
            found += _secret_values(v, here)
    elif isinstance(value, list):
        for i, v in enumerate(value):
            found += _secret_values(v, f"{path}[{i}]")
    return found


ID_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _is_positive_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _is_str_list(value) -> bool:
    return isinstance(value, list) and all(isinstance(v, str) for v in value)


EVENT_STEP_KEYS = {"id", "label", "match", "calendars", "phase", "prompt"}
EVENT_PHASES = ("before", "after")


def _event_step_problems(steps) -> list:
    """A calendar section's own steps: id, label, a pattern on the title, the prompt of the tab it starts."""
    if not isinstance(steps, list):
        return ["event_steps must be a list of steps"]
    out = []
    for n, step in enumerate(steps, 1):
        where = f"event_steps[{n}]"
        if not isinstance(step, dict):
            out.append(f"{where} must be a mapping")
            continue
        unknown = sorted(set(step) - EVENT_STEP_KEYS)
        if unknown:
            out.append(f"{where}: unknown key(s) {', '.join(unknown)}")
        if not (isinstance(step.get("id"), str) and ACTION_RE.match(step["id"])):
            out.append(f"{where}: id must be lowercase letters, digits, _ and -")
        if not (isinstance(step.get("label"), str) and 0 < len(step["label"].strip()) <= 40):
            out.append(f"{where}: label must be text of 1 to 40 characters")
        if not (isinstance(step.get("prompt"), str) and step["prompt"].strip()):
            out.append(f"{where}: prompt must be text")
        if not isinstance(step.get("match"), str):
            out.append(f"{where}: match must be text, a pattern on the event's title")
        else:
            try:
                re.compile(step["match"])
            except re.error as exc:
                out.append(f"{where}: match is not a pattern ({exc})")
        if "phase" in step and step["phase"] not in EVENT_PHASES:
            out.append(f"{where}: phase must be before or after")
        if "calendars" in step and not _is_str_list(step["calendars"]):
            out.append(f"{where}: calendars must be a list of calendar names")
    return out


ROW_STEP_KEYS = {"id", "label", "match", "types", "states", "boards", "prompt"}
ROW_TYPES = ("issue", "pr")


def _row_step_problems(steps) -> list:
    """A tracker section's own steps: id, label, the prompt of the tab it starts, and which rows offer
    it (a pattern on the title, the row's type, state, board)."""
    if not isinstance(steps, list):
        return ["row_steps must be a list of steps"]
    out = []
    for n, step in enumerate(steps, 1):
        where = f"row_steps[{n}]"
        if not isinstance(step, dict):
            out.append(f"{where} must be a mapping")
            continue
        unknown = sorted(set(step) - ROW_STEP_KEYS)
        if unknown:
            out.append(f"{where}: unknown key(s) {', '.join(unknown)}")
        if not (isinstance(step.get("id"), str) and ACTION_RE.match(step["id"])):
            out.append(f"{where}: id must be lowercase letters, digits, _ and -")
        if not (isinstance(step.get("label"), str) and 0 < len(step["label"].strip()) <= 40):
            out.append(f"{where}: label must be text of 1 to 40 characters")
        if not (isinstance(step.get("prompt"), str) and step["prompt"].strip()):
            out.append(f"{where}: prompt must be text")
        if "match" in step:
            try:
                re.compile(str(step["match"]))
            except re.error as exc:
                out.append(f"{where}: match is not a pattern ({exc})")
        if "types" in step and not (_is_str_list(step["types"]) and set(step["types"]) <= set(ROW_TYPES)):
            out.append(f"{where}: types must be a list of issue, pr")
        if "states" in step and not (_is_str_list(step["states"]) and set(step["states"]) <= set(STATES)):
            out.append(f"{where}: states must be a list of {', '.join(STATES)}")
        if "boards" in step and not _is_str_list(step["boards"]):
            out.append(f"{where}: boards must be a list of board slugs")
    return out


def _section_types(s: dict) -> list:
    """Shapes the JSON schema promises, checked without a jsonschema dependency."""
    out = []
    if "id" in s and not (isinstance(s["id"], str) and ID_PATTERN.match(s["id"])):
        out.append("id must be lowercase letters, digits and hyphens")
    if "max" in s and not _is_positive_int(s["max"]):
        out.append("max must be a positive integer")
    if "cache_minutes" in s and not _is_positive_int(s["cache_minutes"]):
        out.append("cache_minutes must be a positive whole number of minutes")
    if "days" in s and not (isinstance(s["days"], int) and not isinstance(s["days"], bool) and s["days"] >= 0):
        out.append("days must be a whole number of days, 0 or more")
    for key in ("contexts", "exclude_calendars", "info_calendars", "argv", "kinds", "skip_kinds"):
        if key in s and not _is_str_list(s[key]):
            out.append(f"{key} must be a list of text")
    if "actions_argv" in s:
        aa = s["actions_argv"]
        if not (_is_str_list(aa) and aa):
            out.append("actions_argv must be a list of text")
        elif not ({"{id}", "{action}"} <= set(aa)) or \
                any(("{id}" in a or "{action}" in a) and a not in ("{id}", "{action}") for a in aa):
            out.append("actions_argv needs {id} and {action}, each as a whole argument of its own")
    if ("event_steps" in s or "prepare" in s) and s.get("kind") != "calendar":
        out.append("event_steps and prepare belong to a calendar section")
    if "prepare" in s and not isinstance(s["prepare"], bool):
        out.append("prepare must be true or false")
    if "event_steps" in s:
        out += _event_step_problems(s["event_steps"])
    if ("row_steps" in s or "default_steps" in s or "link" in s) and s.get("kind") != "tracker":
        out.append("row_steps, default_steps and link belong to a tracker section")
    for key in ("default_steps", "link"):
        if key in s and not isinstance(s[key], bool):
            out.append(f"{key} must be true or false")
    if "row_steps" in s:
        out += _row_step_problems(s["row_steps"])
    for key in ("kinds", "skip_kinds"):
        unknown = sorted(set(s.get(key) or []) - set(_inbox().KINDS)) if _is_str_list(s.get(key)) else []
        if unknown:
            out.append(f"{key}: unknown inbox kind(s) {', '.join(unknown)}")
    if "deferred" in s and s["deferred"] not in ("all", "runs"):
        out.append("deferred must be `all` (show every put-off item, whatever its return date) or `runs` "
                   "(only the put-off items that run on: wait on someone or something until a day)")
    if "status" in s and not (_is_str_list(s["status"]) and set(s["status"]) <= {"backlog", "doing", "review", "done"}):
        out.append("status must be a list of backlog, doing, review, done")
    for key in ("query", "state_map"):
        if key in s and not isinstance(s[key], dict):
            out.append(f"{key} must be a mapping")
    if "to_inbox" in s and not isinstance(s["to_inbox"], list):
        out.append("to_inbox must be a list of rules")
    for key in ("title", "provider", "account_ref", "path"):
        if key in s and not isinstance(s[key], str):
            out.append(f"{key} must be text")
    if s.get("kind") == "commits" and "days" in s and not _is_positive_int(s["days"]):
        out.append("commits: days must be 1 or more")
    if "repos" in s and not _is_str_list(s["repos"]):
        out.append("repos must be a list of names or paths")
    if "author" in s and not (isinstance(s["author"], str) or _is_str_list(s["author"])):
        out.append("author must be text or a list of text (`me` = this repository's git user.email)")
    for key in ("all_branches", "summary", "report_ok"):
        if key in s and not isinstance(s[key], bool):
            out.append(f"{key} must be true or false")
    if "covers" in s and not (_is_str_list(s["covers"]) and set(s["covers"]) <= set(STREAMS)):
        out.append(f"covers must be a list of {', '.join(STREAMS)}")
    if "bucket" in s and s["bucket"] not in (*_view().BUCKETS, "none"):
        out.append(f"bucket must be one of {', '.join(_view().BUCKETS)} or none")
    return out


def profile_problems(data, stem: str) -> list:
    if not isinstance(data, dict):
        return ["not a mapping"]
    out = []
    for key in ("schema_version", "scope", "id", "sections"):
        if key not in data:
            out.append(f"missing {key}")
    for key in sorted(set(data) - PROFILE_KEYS - {"_path", "_language"}):
        out.append(f"unknown key {key}")
    if data.get("schema_version") not in (None, 1):
        out.append("schema_version must be 1")
    if data.get("scope") not in (None, "core", "org", "personal", "user"):
        out.append("scope must be core, org, personal or user")
    if "id" in data and data["id"] != stem:
        out.append(f"id {data['id']!r} does not match the filename {stem!r}")
    if "id" in data and not (isinstance(data["id"], str) and ID_PATTERN.match(data["id"])):
        out.append("id must be lowercase letters, digits and hyphens")
    if "timeout_sec" in data and not _is_positive_int(data["timeout_sec"]):
        out.append("timeout_sec must be a positive integer")
    if "offer_on" in data and not _is_str_list(data["offer_on"]):
        out.append("offer_on must be a list of phrases")
    for key in ("title", "for"):
        if key in data and not isinstance(data[key], str):
            out.append(f"{key} must be text")
    sections = data.get("sections")
    if "sections" in data and (not isinstance(sections, list) or not sections):
        out.append("sections must be a non-empty list")
        sections = []
    seen = set()
    for n, s in enumerate(sections or [], 1):
        where = f"section {n}"
        if not isinstance(s, dict):
            out.append(f"{where}: not a mapping")
            continue
        kind = s.get("kind")
        if kind not in SECTION_KINDS:
            out.append(f"{where}: kind {kind!r} is not one of {', '.join(SECTION_KINDS)}")
            continue
        sid = section_id(s)
        if sid in seen:
            out.append(f"{where}: id {sid!r} used twice (give one section an `id:`)")
        seen.add(sid)
        for key in sorted(set(s) - SECTION_KEYS):
            out.append(f"{where}: unknown key {key}")
        out += [f"{where}: {p}" for p in _section_types(s)]
        query = s.get("query") if isinstance(s.get("query"), dict) else {}
        if kind == "tracker" and s.get("provider") in ("github", "github-work") and query.get("others_prs") and \
                not (query.get("owners") or query.get("repos")):
            out.append(f"{where}: others_prs needs owners or repos (it would search all of GitHub)")
        if kind == "tracker" and s.get("provider") not in TRACKERS:
            out.append(f"{where}: tracker provider must be one of {', '.join(TRACKERS)}")
        if kind == "calendar" and s.get("provider", "auto") not in CALENDARS:
            out.append(f"{where}: calendar provider must be one of {', '.join(CALENDARS)}")
        if (kind == "command" or (kind == "calendar" and s.get("provider") == "command")) and \
                not (isinstance(s.get("argv"), list) and s["argv"]):
            out.append(f"{where}: needs argv (a list)")
        for state in (s.get("state_map") if isinstance(s.get("state_map"), dict) else {}).values():
            if state not in STATES:
                out.append(f"{where}: state_map value {state!r} is not one of {', '.join(STATES)}")
        for r, rule in enumerate(s.get("to_inbox") if isinstance(s.get("to_inbox"), list) else [], 1):
            if not isinstance(rule, dict) or not isinstance(rule.get("when"), dict) or not rule["when"]:
                out.append(f"{where}: to_inbox rule {r} needs a non-empty `when:` mapping")
            elif rule.get("urgency", "today") not in ("now", "today", "later") or \
                    rule.get("gate", "your-yes") not in ("free", "your-yes", "only-you"):
                out.append(f"{where}: to_inbox rule {r} has a bad urgency or gate")
    if "view" in data and not isinstance(data["view"], dict):
        out.append("view must be a mapping")
    if "mutes" in data and not isinstance(data["mutes"], list):
        out.append("mutes must be a list")
    if isinstance(data.get("view"), dict) or isinstance(data.get("mutes"), list):
        out += _view().problems(data.get("view") if isinstance(data.get("view"), dict) else None,
                                data.get("mutes") if isinstance(data.get("mutes"), list) else None)
        ids = {section_id(s) for s in sections or [] if isinstance(s, dict)}
        for n, sid in _view().page_section_ids(data.get("view") if isinstance(data.get("view"), dict) else {}):
            if sid not in ids:
                out.append(f"view.pages {n}: no section {sid!r} in this profile")
        for n, m in enumerate(data.get("mutes") if isinstance(data.get("mutes"), list) else [], 1):
            if isinstance(m, dict) and isinstance(m.get("section"), str) and m["section"] not in ids:
                out.append(f"mutes rule {n}: no section {m['section']!r} in this profile")
    for name in _secret_values(data):
        out.append(f"{name} holds a credential: use account_ref with a token_ref URI instead")
    defaults = data.get("default")
    if defaults not in (None, True, False):
        out.append("default must be true or false")
    return out


def validate(root: Path) -> list:
    problems, defaults = [], []
    by_id = {p.get("id"): p for p in _raw_profiles(root)}
    for path in sorted((root / FAMILY).glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        rel = path.relative_to(root)
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            problems.append(f"{rel}: unreadable ({exc.__class__.__name__})")
            continue
        # a profile that extends another is checked as it is used: with the sections it takes over
        merged, problem = _extended(data, by_id) if isinstance(data, dict) else (data, None)
        if problem:
            problems.append(f"{rel}: {problem}")
        problems += [f"{rel}: {p}" for p in profile_problems(merged, path.stem)]
        if isinstance(data, dict) and data.get("default") is True:
            defaults.append(str(rel))
    if len(defaults) > 1:
        names = ", ".join(Path(r).stem for r in defaults)
        problems.append(f"{FAMILY}: default: true in {names}; at most one may say it "
                        "(or name one in bridge-config.yaml briefing.default)")
    return problems


# ---------------------------------------------------------------- built-in sections

def _frontmatter(text: str) -> dict:
    parts = re.split(r"^---\s*$", text, maxsplit=2, flags=re.M)
    try:
        data = yaml.safe_load(parts[1]) if len(parts) == 3 else {}
    except yaml.YAMLError:
        return {}
    return data if isinstance(data, dict) else {}


def sec_inbox(section: dict, ctx: Context) -> list:
    box = _inbox().Inbox(ctx.root / "work" / "inbox", actor="briefing", clock=lambda: ctx.now)
    order = {"now": 0, "today": 1, "later": 2}
    kinds, skip = section.get("kinds"), set(section.get("skip_kinds") or ())

    def wanted(item):
        return item.kind not in skip and (not kinds or item.kind in kinds)

    items = []
    runs_only = section.get("deferred") == "runs"
    for item in filter(wanted, () if runs_only else box.open_items()):
        items.append({"id": item.id, "title": item.summary, "state": item.state, "urgency": item.urgency,
                      "kind": item.kind, "gate": item.gate, "task": item.task, "due": item.due,
                      "key": item.key, "changed_at": str(item.created or ""), "has_action": bool(item.action)})
    if runs_only:
        # "runs on" (inbox.py defer --on): every put-off item that names what it waits on, whatever its day
        for item in filter(wanted, box.items()):
            deferral = item.deferral if item.state == "deferred" else None
            if not deferral or not deferral.get("on"):
                continue
            items.append({"id": item.id, "title": item.summary, "state": "deferred", "until": str(deferral["until"]),
                          "waiting_on": deferral["on"], "urgency": item.urgency, "kind": item.kind, "gate": item.gate,
                          "task": item.task, "due": item.due, "key": item.key, "changed_at": str(item.created or ""),
                          "has_action": bool(item.action)})
    elif ctx.lookahead is not None or section.get("deferred") == "all":
        # A view that looks ahead also shows what was put off and comes back within
        # its window: "decide tomorrow" must not vanish until tomorrow. `deferred: all`
        # shows every put-off item: the idea shelf is deferred on purpose and still listed.
        horizon = dt.date.max if section.get("deferred") == "all" else ctx.now.date() + dt.timedelta(days=ctx.lookahead)
        for item in filter(wanted, box.items()):
            if item.state != "deferred":
                continue
            until = next((e.data.get("until") for e in reversed(item.events) if e.verb == "defer"), None)
            try:   # the same local date the inbox itself compares to decide the item is deferred
                back = _inbox()._local_date(_inbox()._parse_when(until))
            except Exception:  # noqa: BLE001 - an unreadable date is not shown, as before
                continue
            if back <= horizon:
                items.append({"id": item.id, "title": item.summary, "state": "deferred", "until": str(until),
                              "urgency": item.urgency, "kind": item.kind, "gate": item.gate, "task": item.task,
                              "due": item.due, "key": item.key, "changed_at": str(item.created or ""),
                              "has_action": bool(item.action)})
    items.sort(key=lambda i: (order.get(i["urgency"], 3), i["id"]))
    return items


def sec_advise(section: dict, ctx: Context) -> list:
    advise = _load_module("briefing_advise", ROOT / "skills" / "briefing" / "scripts" / "advise.py")
    found = advise.advise(ctx.root, now=ctx.now, calendar=ctx.calendar, inbox=_inbox())
    return [{"id": f["key"], "title": f["summary"], "state": "new", "urgency": f["urgency"], "check": f["check"],
             "task": f.get("task"), "file": f.get("file", True)} for f in found]


def sec_workplace(section: dict, ctx: Context) -> list:
    wp = _load_module("workplace", ROOT / "scripts" / "workplace.py")
    cfg = wp.load_cfg(ctx.root)
    plan = wp.build_plan(ctx.root, cfg, ctx.now.date(), wp.driver_from(cfg.get("driver")))
    section["_plan"] = plan
    items = []
    if plan.get("driver_error"):
        # Without the tab list every task looks new; `open --yes` refuses, but the
        # reader must learn why here, not from that refusal.
        items.append({"id": "driver", "title": f"Open tabs unknown, every task shows as new: {plan['driver_error']}",
                      "state": "warning"})
    for ws in plan["workspaces"]:
        for tab in ws["tabs"]:
            items.append({"id": tab["slug"], "title": tab["label"], "state": tab["action"], "project": ws["name"]})
    return items


# Where a STATUS.md lists what comes next, when it has no open checkboxes. CORE knows the English
# headings of work/templates/STATUS.md; a profile adds its own with the section's `step_headings`.
STEP_HEADINGS = ("next steps", "next step", "next", "open points")
TASK_STEPS = 3
TASK_LOG_ROWS = 2
TASK_LINE_MAX = 120


def _clip(text: str, n: int = TASK_LINE_MAX) -> str:
    """One plain line: whitespace folded, the markdown emphasis and code marks a TUI would print raw dropped."""
    line = re.sub(r"\*\*|__|`", "", text)
    line = re.sub(r"\s+", " ", line).strip()
    return line if len(line) <= n else line[: n - 1] + "…"


BULLET = re.compile(r"^\s*(?:[-*+]|\d+\.)\s")
OPEN_BOX = re.compile(r"^\s*[-*] \[ \]\s+(.+)$")
ANY_BULLET = re.compile(r"^\s*(?:[-*]|\d+\.)\s+(.+)$")


def _wrapped(lines: list, i: int, text: str) -> str:
    """A bullet's text with its indented continuation lines (a wrapped bullet), up to the next
    bullet, blank line or heading."""
    for line in lines[i + 1:]:
        if not line.strip() or line.startswith("#") or BULLET.match(line) or line[:1] not in " \t":
            break
        text += " " + line.strip()
    return text


def task_steps(body: str, headings=STEP_HEADINGS) -> list:
    """The first open steps of a task: unchecked boxes, else the bullets under a next-steps heading."""
    lines = body.splitlines()
    boxes = [_wrapped(lines, i, m.group(1)) for i, line in enumerate(lines) if (m := OPEN_BOX.match(line))]
    if boxes:
        return [_clip(b) for b in boxes[:TASK_STEPS]]
    wanted = {h.strip().casefold() for h in headings}
    steps, inside = [], False
    for i, line in enumerate(lines):
        if line.startswith("#"):
            m = re.match(r"^##+\s*(.+?)\s*$", line)
            inside = bool(m) and m.group(1).casefold() in wanted
            continue
        bullet = ANY_BULLET.match(line) if inside else None
        if bullet:
            steps.append(_clip(_wrapped(lines, i, bullet.group(1))))
            if len(steps) == TASK_STEPS:
                break
    return steps


def _log_rows(root: Path) -> list:
    log = root / "work" / "log.md"
    if not log.is_file():
        return []
    rows = []
    for line in log.read_text(encoding="utf-8").splitlines():
        m = LOG_ROW.match(line.strip())
        if m:
            rows.append((m.group(1), m.group(4)))
    return rows


def task_log(rows: list, slug: str) -> list:
    """The latest log rows that name the task, oldest first."""
    word = re.compile(rf"(?<![\w-]){re.escape(slug)}(?![\w-])")
    hits = [f"{when} {what}" for when, what in rows if word.search(what)]
    return [_clip(h) for h in hits[-TASK_LOG_ROWS:]]


def sec_tasks(section: dict, ctx: Context) -> list:
    wanted = section.get("status") or ["doing", "review"]
    contexts = section.get("contexts")
    headings = (*STEP_HEADINGS, *[str(h) for h in section.get("step_headings") or []])
    items = []
    log_rows = None
    for status in sorted((ctx.root / "work" / "tasks").glob("*/STATUS.md")):
        if status.parent.name.startswith("_"):
            continue
        fm = _frontmatter(status.read_text(encoding="utf-8"))
        if fm.get("status") not in wanted or (contexts and fm.get("context") not in contexts):
            continue
        slug = fm.get("slug") or status.parent.name
        text = status.read_text(encoding="utf-8")
        body = re.split(r"^---\s*$", text, maxsplit=2, flags=re.M)[-1]   # never a comment in the frontmatter
        heading = re.search(r"^# (.+)$", body, flags=re.M)
        title = fm.get("title") or (heading.group(1).strip() if heading else slug)
        if log_rows is None:
            log_rows = _log_rows(ctx.root)   # one pass over the log for every task
        items.append({"id": slug, "title": title, "state": fm.get("status"),
                      "project": fm.get("context"), "blocked_by": fm.get("blocked_by"), "next": fm.get("next"),
                      "priority": fm.get("priority"),
                      "blocked_since": str(fm["blocked_since"]) if fm.get("blocked_since") else None,
                      "quiet_until": str(fm["quiet_until"]) if fm.get("quiet_until") else None,
                      "changed_at": str(fm.get("last_updated") or ""), "url": str(status.relative_to(ctx.root)),
                      # what a dashboard shows when the row is opened
                      "origin": _clip(str(fm["origin"]), 200) if fm.get("origin") else None,
                      "type": fm.get("type"), "steps": task_steps(body, headings), "log": task_log(log_rows, slug)})
    return items


LOG_ROW = re.compile(r"^\|\s*(\d{4}-\d{2}-\d{2} \d{2}:\d{2})\s*\|\s*([^|]*)\|\s*([^|]*)\|\s*(.*?)\s*\|?\s*$")


def sec_activity(section: dict, ctx: Context) -> list:
    log = ctx.root / "work" / "log.md"
    if not log.is_file():
        return []
    since = ctx.now - dt.timedelta(days=int(section.get("days", 7)))
    items = []
    for line in log.read_text(encoding="utf-8").splitlines():
        m = LOG_ROW.match(line.strip())
        if not m:
            continue
        stamp = dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M")
        if stamp < since or stamp > ctx.now + dt.timedelta(days=1):
            continue
        item = {"id": f"{m.group(1)} {m.group(3).strip()}", "title": m.group(4).strip(),
                "state": m.group(2).strip(), "project": m.group(3).strip(),
                "changed_at": stamp.isoformat(timespec="minutes")}
        # A row whose context is a task or stream leads there: its STATUS.md, and its tab.
        for kind in ("tasks", "streams"):
            if TASK_NAME.match(item["project"]) and (ctx.root / "work" / kind / item["project"]).is_dir():
                item["task"] = item["project"]
                item["url"] = f"work/{kind}/{item['project']}/STATUS.md"
                break
        items.append(item)
    items.sort(key=lambda i: i["changed_at"], reverse=True)
    return items


SPARK = "▁▂▃▄▅▆▇█"
WEB_REMOTE = re.compile(r"^(?:https?://(?:[^@/]+@)?|ssh://(?:[^@/]+@)?|git@)([\w.-]+?)(?::\d+)?[:/]"
                        r"([\w.-]+/[\w.-]+?)(?:\.git)?/?$")
TASK_NAME = re.compile(r"^[a-z0-9][a-z0-9-]*$")


def _web_url(remote: str) -> str | None:
    """A git remote as the web page of its repository (credentials left out); None for a local path.
    An ssh alias for a second account (`github.com-work`) is the host it stands for."""
    m = WEB_REMOTE.match(remote.strip())
    if not m:
        return None
    host = re.sub(r"^(github\.com|gitlab\.com|bitbucket\.org)-[\w.-]+$", r"\1", m.group(1))
    return f"https://{host}/{m.group(2)}"


VAR = re.compile(r"\$\{([a-z_]+)\}")


def _expand(raw: str, root: Path, variables: dict) -> Path | None:
    """A registry path: `${var}` from bridge-config `identity:` (plus home), `~`, and a
    relative path taken from the Bridge root. None when a variable is unknown."""
    text = VAR.sub(lambda m: str(variables.get(m.group(1), m.group(0))), raw)
    if "${" in text:
        return None
    here = Path(text).expanduser()
    return here if here.is_absolute() else root / here


def _ecosystem_repos(root: Path, cfg: dict | None = None) -> list:
    """(name, path) of every repository the ecosystem files register with a local clone,
    plus this Bridge. A clone is `local_path`, else `<local_root>/<repo name from github:>`,
    else `<local_root>/<key>`; a file without `local_root` uses the one of ecosystem.yaml."""
    cfg = cfg if cfg is not None else read_config(root)
    variables = {"home": str(Path.home()), **{k: v for k, v in (cfg.get("identity") or {}).items()
                                              if isinstance(v, (str, int))}}
    out, seen = [(root.name, root)], {root.resolve()}
    files = ([root / "ecosystem.yaml"] if (root / "ecosystem.yaml").is_file() else []) + \
        [p for p in sorted(root.glob("ecosystem.*.yaml")) if p.name != "ecosystem.example.yaml"]
    base_root = ""
    for path in files:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        if not isinstance(data, dict):
            continue
        if path.name == "ecosystem.yaml":
            base_root = str(data.get("local_root") or "")
        local_root = str(data.get("local_root") or base_root)

        def walk(node):
            if not isinstance(node, dict):
                return
            for name, entry in node.items():
                if not isinstance(entry, dict):
                    continue
                if entry.get("github") or entry.get("local_path"):
                    candidates = []
                    if entry.get("local_path"):
                        candidates.append(str(entry["local_path"]))
                    elif local_root:
                        if isinstance(entry.get("github"), str) and "/" in entry["github"]:
                            candidates.append(f"{local_root}/{entry['github'].rsplit('/', 1)[1]}")
                        candidates.append(f"{local_root}/{name}")
                    for raw in candidates:
                        here = _expand(raw, root, variables)
                        if here is not None and (here / ".git").exists():
                            if here.resolve() not in seen:
                                seen.add(here.resolve())
                                out.append((str(name), here))
                            break
                walk(entry)

        walk(data)
    return out


def sec_commits(section: dict, ctx: Context) -> list:
    """Commits per repository per day over `days`, oldest first, with a sparkline.

    Days are the local committer date, the same date `--since` filters on (an author
    date in another zone, or a rebase, would land on the wrong day). A repository that
    cannot be read is named under `skipped`; reaching the section's time limit fails the
    section rather than hiding the repositories it did not get to."""
    days = max(1, int(section.get("days", 7)))
    first = ctx.now.date() - dt.timedelta(days=days - 1)
    if section.get("repos"):
        known = {name: path for name, path in _ecosystem_repos(ctx.root, ctx.cfg)}
        repos = []
        for entry in section["repos"]:
            if entry in known:
                repos.append((entry, known[entry]))
                continue
            here = _expand(str(entry), ctx.root, {"home": str(Path.home()), **(ctx.cfg.get("identity") or {})})
            if here is not None:
                repos.append((here.name, here))
    else:
        repos = _ecosystem_repos(ctx.root, ctx.cfg)
    names = [n for n, _ in repos]
    repos = [(f"{p.parent.name}/{n}" if names.count(n) > 1 else n, p) for n, p in repos]
    authors = section.get("author") or []
    authors = [authors] if isinstance(authors, str) else list(authors)
    items, skipped = [], []
    for name, path in repos:
        if not (path / ".git").exists():
            continue
        try:
            wanted = []
            for a in authors:
                wanted.append(ctx.run(["git", "-C", str(path), "config", "user.email"]).strip() if a == "me" else a)
            argv = ["git", "-C", str(path), "log", "--since", f"{first.isoformat()} 00:00", "--format=%cd",
                    "--date=short-local"] + (["--branches"] if section.get("all_branches") else []) + \
                [f"--author={a}" for a in wanted if a]
            dates = [line.strip() for line in ctx.run(argv).splitlines() if line.strip()]
            counts = [0] * days
            for d in dates:
                try:
                    n = (dt.date.fromisoformat(d) - first).days
                except ValueError:
                    continue
                if 0 <= n < days:
                    counts[n] += 1
            if not sum(counts):
                continue
            branch = ctx.run(["git", "-C", str(path), "rev-parse", "--abbrev-ref", "HEAD"]).strip()
        except SourceError:
            if ctx.deadline is not None and time.monotonic() >= ctx.deadline:
                raise
            skipped.append(name)
            continue
        last = first + dt.timedelta(days=max(i for i, c in enumerate(counts) if c))
        item = {"id": name, "title": name, "branch": branch, "counts": counts, "total": sum(counts),
                "state": "active", "changed_at": last.isoformat(), "path": str(path)}
        try:   # the commit list on the web, of the branch as pushed; no web remote or no upstream, no link
            web = _web_url(ctx.run(["git", "-C", str(path), "remote", "get-url", "origin"]).strip())
            pushed = ctx.run(["git", "-C", str(path), "rev-parse", "--abbrev-ref", "@{u}"]).strip() if web else ""
        except SourceError:
            web, pushed = None, ""
        if web and "/" in pushed:
            item["url"] = f"{web}/commits/{pushed.split('/', 1)[1]}"
        items.append(item)
    top = max((max(i["counts"]) for i in items), default=0)
    for i in items:   # one scale for all rows, so the busiest repository reads busiest
        i["spark"] = "".join(SPARK[0] if c == 0 else SPARK[max(1, round(c / top * (len(SPARK) - 1)))]
                             for c in i["counts"])
    items.sort(key=lambda i: (-i["total"], i["id"]))
    section["_skipped"] = skipped
    return items


# 2026-10-04 at 09:00 - 09:30 | 2026-10-04 at 23:00 - 2026-10-05 at 01:00 | 2026-10-04 - 2026-10-06 | 2026-10-04
ICAL_WHEN = re.compile(r"^(\d{4}-\d{2}-\d{2})(?: at (\d{1,2}:\d{2}))?"
                       r"(?: - (?:(\d{4}-\d{2}-\d{2})(?: at )?)?(\d{1,2}:\d{2})?)?$")
ICAL_PROPS = ("location", "url", "attendees", "uid", "notes")
# -ss: icalBuddy appends this to each calendar's heading line ("Work:@@calendar@@"), which tells a heading
# from a line of the notes that happens to end in a colon
ICAL_SECTION = "@@calendar@@"
# the hosts whose links join a meeting; any other link in an event (a help page, a document) is not one
MEETING_HOST = re.compile(r"(?:^|\.)(?:teams\.microsoft\.com|teams\.live\.com|zoom\.us|meet\.google\.com|"
                          r"webex\.com|whereby\.com|meet\.jit\.si)$")
LINK = re.compile(r"https://[^\s<>\"'()]+")
BIDI = re.compile("[\u200e\u200f\u202a-\u202e\u2066-\u2069]")   # direction marks a calendar app leaves in names


def _icalbuddy(section: dict, ctx: Context) -> list:
    days = int(section.get("days", 1))
    # -nrd: absolute dates, never "today"/"tomorrow" (those cannot be parsed back). -sc: the events under a
    # line naming their calendar, so `info_calendars` needs no second call. The notes are read only for a
    # meeting link and never leave this function.
    argv = ["icalBuddy", "-nrd", "-nc", "-sc", "-uid", "-b", "", "-ss", ICAL_SECTION, "-ps", "|\t|",
            "-iep", "datetime,title,location,url,attendees,notes,uid",
            "-po", "datetime,title,location,url,attendees,uid,notes", "-nnr", " ",
            "-df", "%Y-%m-%d", "-tf", "%H:%M"]
    if section.get("exclude_calendars"):
        argv += ["-ec", ",".join(str(c) for c in section["exclude_calendars"])]
    return _icalbuddy_events(ctx.run(argv + [f"eventsToday+{days}"], timeout=ctx.timeout))


def _icalbuddy_events(out: str) -> list:
    """Events from icalBuddy's text. A line that begins with a date and a tab starts an event; the lines
    after it until the next event or heading are the rest of that event: -nnr joins the notes' line feeds,
    but a carriage return in them (Outlook writes those) reaches Python as a line break."""
    events, calendar, raw = [], None, []

    def flush():
        if raw:
            event = _icalbuddy_event(" ".join(raw), calendar)
            if event:
                events.append(event)
            raw.clear()

    for line in out.split("\n"):
        line = line.rstrip()
        if line.endswith(":" + ICAL_SECTION):
            flush()
            calendar = BIDI.sub("", line[:-len(ICAL_SECTION) - 1]).strip() or None
        elif "\t" in line and ICAL_WHEN.match(line.split("\t", 1)[0].strip()):
            flush()
            raw.append(line)
        elif raw and line.strip():
            raw.append(line.strip())
    flush()
    return sorted(events, key=lambda e: e["start"])     # -sc lists by calendar; a day reads by time


def _icalbuddy_event(text: str, calendar) -> dict | None:
    when, title, *rest = text.split("\t") + [""]
    m = ICAL_WHEN.match(when.strip())
    if not m or not title.strip():
        return None
    props, last = {}, None
    for part in rest:
        name, sep, value = part.partition(": ")
        if sep and name in ICAL_PROPS and name not in props:
            props[name], last = value, name
        elif last and part:
            props[last] += "\t" + part          # a tab inside a value
    day, start, end_day, end = m.groups()
    stop = f"{end_day or day}T{end:0>5}" if end else end_day
    event = {"title": title.strip(), "start": f"{day}T{start:0>5}" if start else day, "end": stop}
    if calendar:
        event["calendar"] = calendar
    people = (props.get("attendees") or "").split(", ")
    event.update(_event_details(props.get("location"), people,
                                [props.get("url"), props.get("location"), props.get("notes")]))
    return event


def _event_details(location, people, texts) -> dict:
    """Place, attendees and the meeting link of one event, each only when there is one."""
    out = {}
    place = BIDI.sub("", location or "").strip()
    if place:
        out["location"] = place[:160]
    names = [BIDI.sub("", str(p)).strip() for p in people or []]
    if any(names):
        out["attendees"] = [n[:80] for n in names if n][:30]
    for text in texts:
        link = next((u for u in LINK.findall(text or "") if MEETING_HOST.search(urllib.parse.urlsplit(u).hostname or "")),
                    None)
        if link:
            out["url"] = link
            break
    return out


def _ics_date(value: str, params: str = ""):
    """ISO local time. UTC (`Z`) and `TZID=` values are converted to this machine's zone."""
    value = value.strip()
    if len(value) == 8:
        return dt.datetime.strptime(value, "%Y%m%d").date().isoformat()
    when = dt.datetime.strptime(value[:15], "%Y%m%dT%H%M%S")
    zone = None
    if value.endswith("Z"):
        zone = dt.timezone.utc
    else:
        tzid = re.search(r"TZID=([^;:]+)", params)
        if tzid:
            try:
                from zoneinfo import ZoneInfo
                zone = ZoneInfo(tzid.group(1).strip('"'))
            except Exception:  # noqa: BLE001 - an unknown zone name reads as local time
                zone = None
    if zone is not None:
        when = when.replace(tzinfo=zone).astimezone().replace(tzinfo=None)
    return when.isoformat(timespec="minutes")


def _ics(section: dict, ctx: Context) -> list:
    path = Path(str(section.get("path") or ""))
    path = path if path.is_absolute() else ctx.root / path
    if not path.is_file():
        raise SourceError(f"no calendar file at {section.get('path')}")
    text = re.sub(r"\r?\n[ \t]", "", path.read_text(encoding="utf-8"))   # unfold
    start_day = ctx.now.date()
    last_day = start_day + dt.timedelta(days=int(section.get("days", 1)))
    events, current = [], None
    # X-WR-CALNAME: the calendar's own name, which `info_calendars` can list
    calname = next((line.split(":", 1)[1].strip() for line in text.splitlines()
                    if line.startswith("X-WR-CALNAME")), None)
    for line in text.splitlines():
        if line == "BEGIN:VEVENT":
            current = {}
        elif line == "END:VEVENT" and current is not None:
            if current.get("start") and start_day <= dt.date.fromisoformat(current["start"][:10]) <= last_day:
                events.append({"title": current.get("title", ""), "start": current["start"],
                               "end": current.get("end"), **({"calendar": calname} if calname else {}),
                               **_event_details(current.get("location"), current.get("people"),
                                                [current.get("url"), current.get("location"), current.get("notes")])})
            current = None
        elif current is not None and ":" in line:
            head, value = line.split(":", 1)
            name, _, params = head.partition(";")
            if name == "SUMMARY":
                current["title"] = value
            elif name in ("LOCATION", "URL", "DESCRIPTION"):
                current[{"LOCATION": "location", "URL": "url", "DESCRIPTION": "notes"}[name]] = \
                    value.replace("\\,", ",").replace("\\;", ";").replace("\\n", " ")
            elif name == "ATTENDEE":
                cn = re.search(r'CN="?([^";:]+)', params)
                current.setdefault("people", []).append(cn.group(1) if cn else re.sub(r"(?i)^mailto:", "", value))
            elif name in ("DTSTART", "DTEND"):
                try:
                    current["start" if name == "DTSTART" else "end"] = _ics_date(value, params)
                except ValueError:
                    pass
    return sorted(events, key=lambda e: e["start"])


def calendar_events(section: dict, ctx: Context) -> list:
    """Events of one calendar section. An event of an `info_calendars` calendar (or one a
    command marks `info: true`) carries `info: true`: shown, never a clash or a collision."""
    events = _calendar_events(section, ctx)
    names = {str(c) for c in section.get("info_calendars") or []}
    for e in events:
        if e.get("info") is True or (names and str(e.get("calendar")) in names):
            e["info"] = True
        else:
            e.pop("info", None)
    return events


def _calendar_events(section: dict, ctx: Context) -> list:
    provider = section.get("provider", "auto")
    if provider == "auto":
        if not shutil.which("icalBuddy"):
            raise Skip("no calendar tool on this machine (icalBuddy not installed)")
        provider = "icalbuddy"
    if provider == "icalbuddy":
        return _icalbuddy(section, ctx)
    if provider == "ics":
        return _ics(section, ctx)
    if provider == "command":
        return _json_list(ctx.run(section["argv"], timeout=ctx.timeout, cwd=str(ctx.root)))
    raise SourceError(f"unknown calendar provider {provider!r}")


def _event_id(event: dict) -> str:
    return f"{event.get('start')} {event.get('title')}"


def _event_time(value):
    try:
        return dt.datetime.fromisoformat(str(value)) if value else None
    except ValueError:
        return None


def event_steps(section: dict, event: dict, now: dt.datetime, words: dict) -> list:
    """The steps one event offers, each {id, label, prompt}: the section's own `event_steps` whose pattern
    (and calendars) fit and whose phase has come (before: not begun yet; after: over), then the built-in
    `prepare` on an event of the reader's own, unless one of the section's own is called prepare."""
    start = _event_time(event.get("start"))
    end = _event_time(event.get("end")) or start
    if start is None:
        return []
    phase = "after" if end <= now else "before" if start > now else None     # running: neither
    steps = []
    for step in section.get("event_steps") or []:
        if not isinstance(step, dict) or step.get("phase", "before") != phase or not isinstance(step.get("match"), str):
            continue
        if step.get("calendars") and event.get("calendar") not in step["calendars"]:
            continue
        try:
            fits = re.search(step["match"], str(event.get("title") or ""), re.I)
        except re.error:
            continue
        if fits and step.get("id") not in {x["id"] for x in steps}:
            steps.append({"id": step.get("id"), "label": str(step.get("label") or "").strip(), "prompt": step.get("prompt")})
    if phase == "before" and section.get("prepare", True) is not False and not event.get("info") \
            and "prepare" not in {x["id"] for x in steps}:
        steps.append({"id": "prepare", "label": words["step_prepare"], "prompt": None})
    return [x for x in steps if isinstance(x["id"], str) and ACTION_RE.match(x["id"]) and x["label"]][:8]


def sec_calendar(section: dict, ctx: Context) -> list:
    words = _view().labels_for(conversation_language(ctx.cfg))
    out = []
    for e in calendar_events(section, ctx):
        item = {"id": _event_id(e), "title": e.get("title"), "start": e.get("start"), "end": e.get("end"),
                "state": "new", **({"info": True} if e.get("info") else {})}
        for key in ("calendar", "location", "url"):
            if isinstance(e.get(key), str) and e[key].strip():
                item[key] = e[key].strip()
        if _is_str_list(e.get("attendees")) and e["attendees"]:
            item["attendees"] = e["attendees"]
        steps = event_steps(section, e, ctx.now, words)
        if steps:
            item["actions"] = [{"id": x["id"], "label": x["label"]} for x in steps]
        out.append(item)
    return out


def _json_list(text: str) -> list:
    try:
        data = json.loads(text)
    except ValueError:
        try:
            data = [json.loads(line) for line in text.splitlines() if line.strip()]
        except ValueError:
            raise SourceError("output is neither a JSON list nor JSON lines") from None
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        data = data["items"]
    if not isinstance(data, list) or not all(isinstance(x, dict) for x in data):
        raise SourceError("output must be a list of objects")
    return data


def sec_command(section: dict, ctx: Context) -> list:
    items = _json_list(ctx.run(section["argv"], timeout=ctx.timeout, cwd=str(ctx.root)))
    for n, item in enumerate(items):
        item.setdefault("id", str(n + 1))
        item.setdefault("tracker", section_id(section))
    return items


def sec_tracker(section: dict, ctx: Context) -> list:
    module = _providers().get(section.get("provider"))
    items = module.collect(section, ctx)
    smap = section.get("state_map") or {}
    for item in items:
        if item.get("raw_state") in smap:
            item["state"] = smap[item["raw_state"]]
        item.setdefault("tracker", section.get("provider"))
        if "category" not in item or item.get("_category_from_state"):
            item.pop("_category_from_state", None)
            st = item.get("state")
            item["category"] = "done" if st in ("done", "removed") else "qa" if st == "review" else "open"
    if section.get("link", section.get("provider") == "github-work") is True:
        link_local(items, ctx)
    words = None
    for item in items:
        if not (GLOBAL_ROW.match(str(item.get("id") or "")) or DRAFT_ROW.match(str(item.get("id") or ""))):
            continue
        words = words or _view().labels_for(conversation_language(ctx.cfg))
        steps = tracker_steps(section, item, words)
        if steps:
            item["actions"] = [{"id": x["id"], "label": x["label"]} for x in steps]
    items.sort(key=lambda i: str(i.get("changed_at") or ""), reverse=True)
    return items


GLOBAL_ROW = re.compile(r"^([\w.-]+/[\w.-]+)#(\d+)\Z")
# a board's draft card (github-board): no issue behind it, so no number and no URL; the project item id names it
DRAFT_ROW = re.compile(r"^draft:[\w.-]+:[\w-]+\Z")


def _issue_refs(task: dict) -> list:
    """The `owner/repo#n` ids a task's `sync.github` names: a number belongs to its `repo`, a full
    reference or URL names its own."""
    out = []
    for ref in task.get("issues") or []:
        text = str(ref).strip()
        m = re.search(r"github\.com/([\w.-]+/[\w.-]+)/(?:issues|pull)/(\d+)", text) or \
            re.fullmatch(r"([\w.-]+/[\w.-]+)#(\d+)", text)
        if m:
            out.append(f"{m.group(1)}#{m.group(2)}")
        elif re.fullmatch(r"#?\d+", text) and task.get("repo"):
            out.append(f"{task['repo']}#{text.lstrip('#')}")
    return out


def _tracked(item: dict) -> bool:
    """Whether a task or stream that is not done names the row (`link_local`)."""
    linked = item.get("linked_task")
    return isinstance(linked, dict) and linked.get("status") != "done"


def link_local(items: list, ctx: Context) -> None:
    """What this Bridge knows about a GitHub row: the task whose `sync.github` names it (a finite task
    in work/tasks/ becomes the row's task, so a dashboard opens its tab; a stream is named only) and
    the newest active inbox item filed for it (an agent started on the row, Do it, a briefing rule),
    found by the row id at the end of the item's key. An open issue assigned to you that no task or
    stream names is `untasked` (a boolean on every row, so a `to_inbox` rule can ask for it); a task or
    stream that is done tracks nothing, and one that is not wins the link over it. When the tasks
    cannot be read the field is left out and the row says so in `unknown`, since unknown is not the
    same as untracked: an item a rule filed on it stays open until the tasks can be read again."""
    rows = {str(i.get("id")): i for i in items if GLOBAL_ROW.match(str(i.get("id") or ""))}
    drafts = [i for i in items if DRAFT_ROW.match(str(i.get("id") or ""))]
    if not rows and not drafts:
        return
    try:
        ts = _load_module("tracker_sync", ROOT / "scripts" / "tracker-sync.py")
        tasks, scanned = ts.scan_status_tasks(ctx.root), True
    except Exception:  # noqa: BLE001 - a link is a nicety, never a reason to lose the rows
        tasks, scanned = [], False
    for t in tasks:
        live = t.get("status") != "done"
        finite = str(t.get("path") or "").startswith("work/tasks/") and live
        for rid in _issue_refs(t):
            row = rows.get(rid)
            if row is None or (row.get("linked_task") and (not live or row["linked_task"].get("status") != "done")):
                continue          # the first task that names it, unless a live one comes after a done one
            row["linked_task"] = {"slug": t["slug"], "status": t.get("status"), "path": t.get("path"),
                                  "stream": not str(t.get("path") or "").startswith("work/tasks/")}
            if finite:
                row["task"] = t["slug"]
    for row in rows.values():
        if not scanned:
            row["unknown"] = ["untasked"]
            continue
        pr = str(row.get("type") or "").lower().replace("_", "") in ("pr", "pullrequest")   # a board says PullRequest
        row["untasked"] = (not pr and bool(row.get("assigned_to_me"))
                           and row.get("state") not in ("done", "removed") and not _tracked(row))
    try:
        box = _inbox().Inbox(ctx.root / "work" / "inbox", actor="briefing", clock=lambda: ctx.now)
        active = [i for i in box.items() if i.state in _inbox().ACTIVE_STATES and i.key]
    except Exception:  # noqa: BLE001
        active = []
    for item in sorted(active, key=lambda i: str(i.created or "")):
        key = str(item.key)
        for rid, row in rows.items():
            if key.endswith((f":{rid}", f"/{rid}")):
                row["inbox"] = item.id            # the newest wins: sorted oldest first
        for row in drafts:                        # a draft is named by no task, but an agent may run on it
            if key.endswith(f":{row['id']}"):
                row["inbox"] = item.id


BUILTIN_ROW_STEPS = ("analyze", "implement", "review", "adopt", "sync", "remind")


def tracker_steps(section: dict, item: dict, words: dict) -> list:
    """The steps one GitHub row offers, each {id, label, prompt}: the section's own `row_steps` that fit
    the row, then the built-in ones of a GitHub provider (unless `default_steps: false`): Analyse
    always, Implement on an issue without a pull request, Review on a pull request or an issue that has
    one, Make it a task on an issue no live task syncs, Sync status on a row with a board or a task, Remind on a
    row someone else is assigned to. A draft card has no issue and no URL: it offers Analyse and Make it a task
    only, and a section's own step only when its `types` name `draft`. A row
    that is done offers none. Every step starts an agent tab; none acts on GitHub by itself."""
    if item.get("state") in ("done", "removed"):
        return []
    kind = "pr" if item.get("type") == "pr" else "draft" if item.get("type") == "draft" else "issue"
    board = (item.get("board") or {}).get("slug") if isinstance(item.get("board"), dict) else None
    steps = []
    for step in section.get("row_steps") or []:
        if not isinstance(step, dict) or not isinstance(step.get("id"), str):
            continue
        if step.get("types") and kind not in step["types"]:
            continue
        if kind == "draft" and not step.get("types"):
            continue                  # a step for every row may need the issue a draft does not have
        if step.get("states") and item.get("state") not in step["states"]:
            continue
        if step.get("boards") and board not in step["boards"]:
            continue
        try:
            if step.get("match") and not re.search(str(step["match"]), str(item.get("title") or ""), re.I):
                continue
        except re.error:
            continue
        if step["id"] not in {x["id"] for x in steps}:
            steps.append({"id": step["id"], "label": str(step.get("label") or "").strip(), "prompt": step.get("prompt")})
    if section.get("provider") in GITHUB_TRACKERS and section.get("default_steps", True) is not False:
        has_pr = bool(item.get("prs"))
        offer = {"analyze": True, "implement": kind == "issue" and not has_pr, "review": kind == "pr" or has_pr,
                 "adopt": kind in ("issue", "draft") and not _tracked(item) and not item.get("task"),
                 "sync": bool(board or item.get("linked_task")),
                 # someone else's card: a reminder to them, drafted, sent only after a yes
                 "remind": bool(item.get("assignee")) and not item.get("assigned_to_me")}
        if kind == "draft":       # no issue to sync, comment on or remind on
            offer.update(sync=False, remind=False, review=False)
        for sid in BUILTIN_ROW_STEPS:
            if offer[sid] and sid not in {x["id"] for x in steps}:
                steps.append({"id": sid, "label": words[f"gh_step_{sid}"], "prompt": None})
    return [x for x in steps if ACTION_RE.match(x["id"]) and x["label"]][:8]


def tracker_prompt(step: dict, item: dict, words: dict) -> str:
    """The prompt a GitHub row's step starts its tab with: the row's facts, then the step's own prompt
    (its {placeholders} filled in) or the built-in instruction."""
    board = item.get("board") if isinstance(item.get("board"), dict) else {}
    task = item.get("linked_task") if isinstance(item.get("linked_task"), dict) else {}
    prs = ", ".join(f"{p.get('id')}{' (draft)' if p.get('draft') else ''}" for p in item.get("prs") or []
                    if isinstance(p, dict))
    draft = item.get("type") == "draft"
    values = {"id": str(item.get("id") or ""), "title": str(item.get("title") or ""), "url": str(item.get("url") or ""),
              "type": "pull request" if item.get("type") == "pr" else "draft card" if draft else "issue", "state": str(item.get("state") or ""),
              "status": str(item.get("raw_state") or ""), "board": str(board.get("name") or ""),
              "board_slug": str(board.get("slug") or ""), "board_config": str(board.get("config") or ""),
              "task": str(task.get("slug") or ""), "prs": prs, "assignee": str(item.get("assignee") or "")}
    if step.get("prompt"):
        return re.sub(r"\{([a-z_]+)\}", lambda m: values.get(m.group(1), m.group(0)), str(step["prompt"]))
    facts = [(words["gh_fact_link"], values["url"]), (words["gh_fact_status"], values["status"] or values["state"]),
             (words["gh_fact_board"], f"{values['board']} (#{board.get('number')}, {board.get('org')})"
              if values["board"] else ""),
             (words["gh_fact_config"], values["board_config"]),
             (words["gh_fact_task"], str(task.get("path") or "")), (words["gh_fact_prs"], prs),
             (words["gh_fact_assignee"], f"@{values['assignee']}" if values["assignee"] else ""),
             (words["gh_fact_note"], str(item.get("note") or ""))]
    kind = "pr" if item.get("type") == "pr" else "draft" if draft else "issue"
    head = words["gh_head"].format(type=words[f"gh_type_{kind}"], id=values["id"], title=values["title"])
    return "\n".join([head, *[f"{label}: {value}" for label, value in facts if value], "",
                      words[f"gh_do_{step['id']}_draft" if draft else f"gh_do_{step['id']}"]])


KINDS = {"inbox": sec_inbox, "advise": sec_advise, "workplace": sec_workplace, "tasks": sec_tasks,
         "activity": sec_activity, "commits": sec_commits, "calendar": sec_calendar, "tracker": sec_tracker, "command": sec_command}


# ---------------------------------------------------------------- collect

def _fingerprint(item: dict) -> str:
    return json.dumps([item.get("title"), item.get("state"), item.get("raw_state"), item.get("changed_at"),
                       item.get("assignee")], ensure_ascii=False, default=str)


def _positive(value, default: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number > 0 else default


def _cache_file(root: Path, profile: dict, section: dict) -> Path:
    return root / CACHE / str(profile.get("id") or "profile") / f"{section_id(section)}.json"


def _cache_key(section: dict, ctx: Context) -> str:
    """The section as configured and the run's own inputs: a changed query or look-ahead is a
    different answer, so the cache is void."""
    return json.dumps({"section": {k: v for k, v in section.items() if not k.startswith("_")},
                       "lookahead": ctx.lookahead}, sort_keys=True, default=str)


def _cached(root: Path, profile: dict, section: dict, ctx: Context):
    """The section's last answer and when it was taken, while younger than `cache_minutes`;
    None when the section keeps none, the run asks fresh, or the answer is too old."""
    minutes = section.get("cache_minutes")
    if not _is_positive_int(minutes) or ctx.fresh:
        return None
    try:
        data = json.loads(_cache_file(root, profile, section).read_text(encoding="utf-8"))
        at = dt.datetime.fromisoformat(data["at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if data.get("key") != _cache_key(section, ctx) or not isinstance(data.get("items"), list):
        return None
    # "today" is part of many answers (commits today, today's events): never carried past midnight.
    if at.date() != ctx.now.date() or not dt.timedelta(0) <= ctx.now - at < dt.timedelta(minutes=minutes):
        return None
    for name, value in (data.get("extra") or {}).items():   # what the section hands the view beside its rows
        section[name] = value
    return data["items"], data["at"]


# GitHub's limits are one budget for every program on the account (5000 GraphQL points an hour, shared with
# board pollers and agents). A section that hits the limit stops every GitHub section until the reset, and a
# section that cannot answer shows its last kept answer instead of nothing (live 2026-10-18: the cockpit
# asked on through a spent budget and every board went red).
GITHUB_LIMIT = CACHE / "github-limit.json"
LIMIT_WORDS = re.compile(r"rate limit|secondary rate|abuse detection", re.I)
LIMIT_FALLBACK_MIN = 15
LIMIT_CAP_MIN = 65
STALE_HOURS = 12


def _github_section(section: dict) -> bool:
    return section.get("kind") == "tracker" and section.get("provider") in GITHUB_TRACKERS


def github_blocked(root: Path, now: dt.datetime) -> dt.datetime | None:
    """Until when GitHub is not to be asked (local time), or None."""
    try:
        until = dt.datetime.fromisoformat(json.loads((root / GITHUB_LIMIT).read_text(encoding="utf-8"))["until"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return until if now < until <= now + dt.timedelta(minutes=LIMIT_CAP_MIN) else None


def block_github(root: Path, ctx: Context, reason: str) -> dt.datetime:
    """Stop the GitHub sections until the spent budget resets: the reset of every exhausted resource that
    `gh api rate_limit` names (that call costs nothing), else a quarter of an hour; never more than 65 min."""
    now = ctx.now
    until = None
    try:
        # straight to the runner: no retries and no block check for the one call that costs nothing
        data = json.loads(ctx._run(["gh", "api", "rate_limit"], timeout=10)).get("resources") or {}
        resets = [dt.datetime.fromtimestamp(int(r["reset"])) for r in data.values()
                  if isinstance(r, dict) and r.get("remaining") == 0 and r.get("reset")]
        until = max(resets) if resets else None
    except Exception:  # noqa: BLE001 - without the answer the fallback holds
        until = None
    if until is None or until <= now:
        until = now + dt.timedelta(minutes=LIMIT_FALLBACK_MIN)
    until = min(until + dt.timedelta(minutes=1), now + dt.timedelta(minutes=LIMIT_CAP_MIN))
    path = root / GITHUB_LIMIT
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")
        tmp.write_text(json.dumps({"until": until.isoformat(timespec="seconds"), "reason": reason[:200]}), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass
    return until


def _stale(root: Path, profile: dict, section: dict, ctx: Context):
    """The section's last kept answer of the last 12 hours, whatever `cache_minutes` says: what a source
    that cannot answer now still showed then. Only for a tracker, whose rows do not depend on the day."""
    if section.get("kind") != "tracker" or not _is_positive_int(section.get("cache_minutes")):
        return None
    try:
        data = json.loads(_cache_file(root, profile, section).read_text(encoding="utf-8"))
        at = dt.datetime.fromisoformat(data["at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if data.get("key") != _cache_key(section, ctx) or not isinstance(data.get("items"), list) or \
            not dt.timedelta(0) <= ctx.now - at < dt.timedelta(hours=STALE_HOURS):
        return None
    for name, value in (data.get("extra") or {}).items():
        section[name] = value
    return data["items"], data["at"]


def _keep(root: Path, profile: dict, section: dict, ctx: Context, items: list) -> None:
    """Keep a good answer for the next run; a failure is never kept (it raises before here)."""
    if not _is_positive_int(section.get("cache_minutes")):
        return
    path = _cache_file(root, profile, section)
    extra = {k: v for k, v in section.items() if k in ("_summary", "_plan", "_skipped", "_metrics")}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.{threading.get_ident()}.tmp")   # two sessions may write at once
        tmp.write_text(json.dumps({"at": ctx.now.isoformat(timespec="seconds"), "key": _cache_key(section, ctx),
                                   "items": items, "extra": extra}, ensure_ascii=False, default=str),
                       encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass   # without a cache the next run asks again


def collect(root: Path, profile: dict, ctx: Context, previous: dict | None = None, skip=(),
            style: str | None = None, only=()) -> dict:
    """Run every section. `skip` names kinds left out (the briefing's --quick and
    --skip-trackers modes); a skipped section is listed as such and closes nothing.
    `only` names the kinds a `--only` run keeps, so a section it leaves out says so.
    `style` is the view a caller chose for this run (`render --style`)."""
    ctx.timeout = _positive(profile.get("timeout_sec"), ctx.timeout)
    if _view().style_of(profile, style) != "sources":
        view = profile.get("view") if isinstance(profile.get("view"), dict) else {}
        ctx.lookahead = view.get("lookahead_days", 1) if isinstance(view.get("lookahead_days", 1), int) else 1
    sections = [dict(s) for s in profile.get("sections") or [] if isinstance(s, dict)]
    # The advice checks look for calendar collisions wherever the calendar stands.
    calendars = [s for s in sections if s.get("kind") == "calendar" and "calendar" not in skip]
    if calendars and any(s.get("kind") == "advise" for s in sections):
        ctx.calendar = []
        for s in calendars:
            ctx.deadline = time.monotonic() + ctx.timeout
            try:
                ctx.calendar += calendar_events(s, ctx)
            except Exception:  # noqa: BLE001 - its own section reports the failure
                pass
    before = {s["id"]: s for s in (previous or {}).get("sections", [])}

    def run_one(s: dict):
        """One section within its own time limit; the sections run side by side (their
        sources are separate programs and services), the result keeps the profile's order."""
        sid = section_id(s)
        entry = {"id": sid, "kind": s.get("kind"), "title": s.get("title") or sid.replace("-", " ").capitalize(),
                 "status": "ok", "items": [], "total": 0}
        if s.get("provider"):
            entry["provider"] = s["provider"]
        ctx.deadline = time.monotonic() + ctx.timeout
        try:
            if only and s.get("kind") not in only:
                raise Skip(f"left out in this run (--only {', '.join(only)})")
            if s.get("kind") in skip:
                # a quick pass leaves the slow sources out, but what they last said is on disk: shown at once,
                # said to be refreshing, so a page does not open empty and fill half a minute later
                kept = _stale(root, profile, s, ctx)
                if kept is None:
                    raise Skip(f"left out in this mode (--skip {s.get('kind')})")
                items, entry["cached_at"] = kept
                entry["stale"] = {"reason": f"left out in this mode (--skip {s.get('kind')})", "refreshing": True}
                return sid, entry, items
            cached = _cached(root, profile, s, ctx)
            if cached is not None:
                items, entry["cached_at"] = cached
            else:
                blocked = github_blocked(root, ctx.now) if _github_section(s) else None
                if blocked is not None:
                    raise SourceError(f"GitHub rate limit, not asked until {blocked:%H:%M}")
                items = KINDS[s.get("kind")](s, ctx)
                _keep(root, profile, s, ctx, items)
        except Skip as exc:
            entry.update(status="skipped", reason=str(exc))
            items = []
        except SourceError as exc:
            reason = ctx.redact(str(exc))
            until = None
            if _github_section(s):
                until = github_blocked(root, ctx.now)
                if until is None and LIMIT_WORDS.search(reason):
                    until = block_github(root, ctx, reason)
            old = _stale(root, profile, s, ctx)
            if old is not None:
                # the last good answer, said to be old: the page keeps its rows, nothing is closed from it
                items, entry["cached_at"] = old
                entry["stale"] = {"reason": reason, **({"until": until.strftime("%H:%M")} if until else {})}
            else:
                entry.update(status="error", reason=reason)
                items = []
        except Exception as exc:  # noqa: BLE001 - one section never takes the briefing down
            entry.update(status="error", reason=ctx.redact(f"{exc.__class__.__name__}: {exc}"))
            items = []
        finally:
            ctx.deadline = None
        return sid, entry, items

    with concurrent.futures.ThreadPoolExecutor(max_workers=max(1, min(8, len(sections)))) as pool:
        done = list(pool.map(run_one, sections))
    out = []
    for s, (sid, entry, items) in zip(sections, done):
        if "_plan" in s:
            entry["plan"] = s["_plan"]
        if "_summary" in s:
            entry["summary"] = s["_summary"]
        if "_metrics" in s:
            entry["metrics"] = s["_metrics"]
        if s.get("kind") == "commits":
            entry["days"] = max(1, _positive(s.get("days"), 7))
            entry["skipped"] = s.get("_skipped") or []
        old = {i.get("id"): i.get("_fp") for i in (before.get(sid) or {}).get("items", [])}
        old_known = sid in before and before[sid].get("status") == "ok"
        for item in items:
            item["id"] = str(item.get("id"))
            fp = _fingerprint(item)
            item["_fp"] = fp
            item["new"] = not old_known or item["id"] not in old
            item["changed"] = old_known and item["id"] in old and old[item["id"]] != fp
        entry["total"] = len(items)
        entry["all"] = items
        entry["items"] = items[: _positive(s.get("max"), len(items) or 1)] if s.get("max") and not profile.get("_whole") else items
        out.append(entry)
    result = {"profile": profile.get("id"), "title": profile.get("title") or profile.get("id"),
              "collected_at": ctx.now.isoformat(timespec="minutes"), "sections": out}
    if previous and previous.get("collected_at"):
        result["previous_at"] = previous["collected_at"]
    return result


def _public(result: dict) -> dict:
    """The result as shown: no fingerprints, no uncapped item lists."""
    clean = {**result, "sections": []}   # housekeeping travels along
    for s in result["sections"]:
        s = {k: v for k, v in s.items() if k != "all"}
        s["items"] = [{k: v for k, v in i.items() if k != "_fp"} for i in s["items"]]
        clean["sections"].append(s)
    return clean


def save_snapshot(root: Path, result: dict, previous: dict | None = None) -> Path:
    """Remember what each section showed. A section that did not complete keeps its
    last good entry: a failed lookup must not make tomorrow's rows look new."""
    path = root / SNAPSHOTS / f"{result['profile']}.last.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    before = {s.get("id"): s for s in (previous or {}).get("sections", [])}
    sections = []
    for s in result["sections"]:
        if s["status"] != "ok" and s["id"] in before:
            sections.append(before[s["id"]])
            continue
        sections.append({"id": s["id"], "status": s["status"],
                         "items": [{"id": i["id"], "_fp": i.get("_fp")} for i in s.get("all", s["items"])]})
    snap = {**{k: v for k, v in result.items() if k != "sections"}, "sections": sections}
    path.write_text(json.dumps(snap, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    return path


def load_snapshot(root: Path, pid: str) -> dict | None:
    path = root / SNAPSHOTS / f"{pid}.last.json"
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ---------------------------------------------------------------- owed streams

# The playbook's streams a profile section may not cover (skills/briefing/references/
# workflow.md). Each: when it applies to this Bridge, and how to run it by hand.
STREAMS = {
    "prs": ("Open pull requests across the orgs",
            "a github tracker section with `others_prs: N` covers this; else workflow.md § Open PRs"),
    "meetings": ("Meeting obligations and open debrief points",
                 "python3 skills/briefing/scripts/meeting-obligations.py; then work/tasks/_meetings/*/triage.md "
                 "with status: pending-triage (workflow.md Stream A 5, 5b)"),
    "imports": ("Files waiting in the imports directory",
                "list them by type; transcripts are offered to /debrief (workflow.md Stream C 2, 3)"),
    "upstream": ("Inbound drift from CORE and org overlays",
                 "python3 skills/briefing/scripts/upstream_items.py (or make it a command section "
                 "with covers: [upstream]); detail: references/upstream-summary.md"),
    "applications": ("Application pipeline thresholds",
                     "workflow.md Stream C 5, thresholds from the applications standing order"),
    "channels": ("Channel activity", "workflow.md Stream D"),
    "backups": ("Backup health", "the backup executor's health check (infra/backups/README.md)"),
}


def _imports_waiting(root: Path, cfg: dict) -> bool:
    raw = str((cfg.get("work") or {}).get("imports_dir") or "work/imports")
    base = Path(raw).expanduser()
    base = base if base.is_absolute() else root / base
    try:
        return any(p.is_file() and p.name not in (".gitkeep", ".DS_Store") and "_debriefed" not in p.parts
                   for p in base.rglob("*"))
    except OSError:
        return False


def _channels_active(root: Path, cfg: dict) -> bool:
    for p in (root / "infra" / "channels").glob("*.yaml"):
        if p.name.startswith("_"):
            continue
        try:
            data = yaml.safe_load(p.read_text(encoding="utf-8")) or {}
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(data, dict) and (data.get("checkin") or {}).get("enabled") is True:
            return True
    sources = (cfg.get("integrations") or {}).get("context_sources") or {}
    return any(isinstance(v, dict) and v.get("enabled") and {"chat", "calls"} & set(v.get("provides") or [])
               for v in sources.values())


def owed(root: Path, cfg: dict, profile: dict) -> list:
    """Streams that apply to this Bridge and that no section of the profile covers."""
    sections = [s for s in profile.get("sections") or [] if isinstance(s, dict)]
    covered = {c for s in sections for c in (s.get("covers") or []) if isinstance(c, str)}
    for s in sections:
        q = s.get("query") if isinstance(s.get("query"), dict) else {}
        if s.get("kind") == "tracker" and s.get("provider") in ("github", "github-work") and q.get("others_prs"):
            covered.add("prs")
    integrations = cfg.get("integrations") or {}
    applies = {
        "prs": bool((integrations.get("github") or {}).get("enabled")) or any(
            s.get("provider") in GITHUB_TRACKERS for s in sections),
        "meetings": (root / "work" / "tasks" / "_meetings").is_dir(),
        "imports": _imports_waiting(root, cfg),
        "upstream": bool(cfg.get("upstreams")),
        "applications": bool((cfg.get("applications") or {}).get("enabled")),
        "channels": _channels_active(root, cfg),
        "backups": (root / "infra" / "backups" / "topology.yaml").is_file(),
    }
    return [{"id": sid, "title": title, "how": how} for sid, (title, how) in STREAMS.items()
            if applies[sid] and sid not in covered]


# ---------------------------------------------------------------- housekeeping

# The same day heading scripts/worklog.py reads: any token, then DD.MM at the end.
DAY_HEADING = re.compile(r"^## .*?(\d{2})\.(\d{2})\s*$")
ROW_TIME = re.compile(r"^\| (\d{4}-\d{2}-\d{2} \d{2}:\d{2}) \|")


def _weekday(now: dt.datetime) -> str:
    """Today's weekday as `date '+%a'` writes it on this machine; the header is cosmetic.
    No setlocale: that would change the whole process."""
    if now.date() == dt.date.today():
        try:
            out = subprocess.run(["date", "+%a"], capture_output=True, text=True, timeout=5).stdout.strip()
            if out:
                return out
        except (OSError, subprocess.SubprocessError):
            pass
    return now.strftime("%a")


def _new_day_block(root: Path, now: dt.datetime, weekday: str) -> str:
    template = root / "work" / "templates" / "day.md"
    try:
        body = re.sub(r"<!--.*?-->", "", template.read_text(encoding="utf-8"), flags=re.S).strip()
    except OSError:
        body = ""
    if "{Weekday} DD.MM" not in body:
        body = ("## {Weekday} DD.MM\n\n| Timestamp | Glyph | Context | What |\n|---|---|---|---|")
    return body.replace("{Weekday} DD.MM", f"{weekday} {now:%d.%m}")


def log_row(text: str, now: dt.datetime, row: str, marker: str, block: str) -> str:
    """Put `row` into today's day block: after its last table row, inside <details> when
    the block has one, wherever the block stands (newest first or last). A row carrying
    `marker` written less than 30 minutes ago is replaced, so a run that files twice
    leaves one row. A missing block is `block`, appended."""
    lines = text.rstrip("\n").split("\n")
    heads = [i for i, line in enumerate(lines) if DAY_HEADING.match(line)]
    today = next((i for i in heads if DAY_HEADING.match(lines[i]).groups() == (f"{now:%d}", f"{now:%m}")), None)
    if today is None:
        lines += ["", *block.split("\n")]
        heads = [i for i, line in enumerate(lines) if DAY_HEADING.match(line)]
        today = heads[-1]
    end = next((i for i in heads if i > today), len(lines))
    for i in range(today, end):
        m = ROW_TIME.match(lines[i])
        if m and marker in lines[i]:
            then = dt.datetime.strptime(m.group(1), "%Y-%m-%d %H:%M")
            if dt.timedelta(0) <= now - then < dt.timedelta(minutes=30):
                lines[i] = row
                return "\n".join(lines) + "\n"
    table = [i for i in range(today, end) if lines[i].startswith("|")]
    if table:
        at = table[-1] + 1
    else:
        close = next((i for i in range(today, end) if lines[i].strip() == "</details>"), end)
        lines[close:close] = ["| Timestamp | Glyph | Context | What |", "|---|---|---|---|"]
        at, end = close + 2, end + 2
    lines.insert(at, row)
    end += 1
    count = sum(1 for i in range(today, end) if ROW_TIME.match(lines[i]))
    for i in range(today, end):
        lines[i] = re.sub(r"<summary>Worklog \(\d+\)</summary>", f"<summary>Worklog ({count})</summary>", lines[i])
    return "\n".join(lines) + "\n"


def housekeep(root: Path, now: dt.datetime, *, summary: str, profile_id: str, run=None,
              weekday: str | None = None) -> list:
    """The briefing's own bookkeeping, done by the engine so a run cannot skip it:
    today's day block, the log row, a regenerated board, an overdue archive named.
    Returns notes for housekeeping; a step that fails is a note, never an abort."""
    run = run or _default_run
    notes = []
    log = root / "work" / "log.md"
    if log.is_file():
        try:
            marker = f"/briefing ({profile_id})"
            row = f"| {now:%Y-%m-%d %H:%M} | 📋 | bridge | {marker}: {summary.replace('|', '/')} |"
            text = log_row(log.read_text(encoding="utf-8"), now, row, marker,
                           _new_day_block(root, now, weekday or _weekday(now)))
            log.write_text(text, encoding="utf-8")
        except OSError as exc:
            notes.append(f"work/log.md not written: {exc}")
    board = root / "scripts" / "gen-board.py"
    if board.is_file() and (root / "work").is_dir():
        try:
            run([sys.executable, str(board)], timeout=60, cwd=str(root))
        except Exception as exc:  # noqa: BLE001 - bookkeeping never takes the briefing down
            notes.append(f"gen-board.py failed, work/board.md may be stale: {exc}")
    plan_script = root / "scripts" / "archive-buckets.py"
    if plan_script.is_file():
        try:
            plan = json.loads(run([sys.executable, str(plan_script), "--json"], timeout=30, cwd=str(root)) or "{}")
            due = [b.get("label") for b in plan.get("buckets", []) if b.get("archive")]
            if due:
                notes.append(f"work/log.md holds {len(due)} closed period(s) ({', '.join(map(str, due))}): /archive")
        except Exception:  # noqa: BLE001 - no plan, no claim either way
            pass
    return notes


# ---------------------------------------------------------------- inbox

def rule_matches(when: dict, item: dict) -> bool:
    for field, want in when.items():
        have = item.get(field)
        wants = want if isinstance(want, list) else [want]
        if isinstance(have, list):
            if not any(w in have for w in wants):
                return False
        elif have not in wants:
            return False
    return True


def file_to_inbox(box, profile: dict, result: dict) -> tuple:
    """File rows matching to_inbox rules; close this profile's items whose row is gone.

    Only a section that completed may close: an errored or skipped section did not
    look, so it cannot know a row is gone (the advise `checks_run` rule). Likewise a row
    whose `unknown` names a field a rule asks about keeps its item: the run could not tell."""
    sections = {section_id(s): s for s in profile.get("sections") or [] if isinstance(s, dict)}
    filed, wanted, closable = 0, set(), set()
    present: set = set()          # every row id each section shows now, for the items the cockpit filed
    pid = profile.get("id")
    own = f"{KEY_PREFIX}{pid}:"
    for entry in result["sections"]:
        prefix = f"{own}{entry['id']}:"
        if entry["status"] == "ok" and not entry.get("stale"):
            closable.add(prefix)      # also when its rules were removed: nothing is wanted any more
            present.update(prefix + str(i["id"]) for i in entry.get("all", entry["items"]) if "id" in i)
        rules = (sections.get(entry["id"]) or {}).get("to_inbox") or []
        if not rules or entry.get("stale"):      # old rows file nothing: what they showed may be settled since
            continue
        for item in entry.get("all", entry["items"]):
            unknown = set(item.get("unknown") or [])
            if unknown and any(unknown & set(r["when"]) for r in rules):
                wanted.add(prefix + str(item["id"]))   # a field this run could not work out: keep what it filed
            rule = next((r for r in rules if rule_matches(r["when"], item)), None)
            if rule is None:
                continue
            key = prefix + item["id"]
            wanted.add(key)
            label = item.get("raw_state") or item.get("state") or ""
            summary = f"{entry['title']}: {item['id']} {item.get('title') or ''}".strip()
            existing = [i for i in box.items() if i.key == key and i.state not in ("done",)]
            box.add(source=f"briefing/{pid}", kind="finding", summary=summary + (f" ({label})" if label else ""),
                    detail=item.get("url"), urgency=rule.get("urgency", "today"), gate=rule.get("gate", "your-yes"),
                    key=key, closer="reporter")      # this function closes it when the row is gone
            if not existing:
                filed += 1
    closed = 0
    for item in box.open_items():
        key = str(item.key or "")
        if not key.startswith(own) or key in wanted:
            continue
        if key[len(own):].split(":", 1)[0] not in sections:
            box.close(item.id, note="its section was removed from the profile")
            closed += 1
        elif item.source == "bridge-cockpit" and key in present:
            continue      # filed by Do it on a page row: no rule wants it, the row's presence does
        elif any(key.startswith(p) for p in closable):
            box.close(item.id, note="no longer in the briefing source")
            closed += 1
    return filed, closed


# ---------------------------------------------------------------- render

def _line(kind: str, i: dict) -> str:
    mark = " (new)" if i.get("new") else " (changed)" if i.get("changed") else ""
    title = str(i.get("title") or "")
    if kind == "inbox":
        return f"  {str(i.get('urgency') or ''):<6} {title[:90]}{mark}"
    if kind == "calendar":
        start = str(i.get("start") or "")
        when = f"{start[8:10]}.{start[5:7]}" + (" " + start[11:16] if len(start) > 10 else " all day")
        return f"  {when:<12} {title[:80]}"
    if kind == "advise":
        return f"  {str(i.get('check') or ''):<10} {title[:90]}{mark}"
    if kind == "activity":
        at = str(i.get("changed_at") or "")
        return f"  {at[8:10]}.{at[5:7]} {at[11:16]:<6} {str(i.get('project') or '')[:18]:<18} " \
               f"{title[:70]}"
    if kind == "commits":
        return f"  {str(i['id'])[:24]:<24} {str(i.get('branch') or '')[:12]:<12} {i.get('spark', '')}  " \
               f"{i.get('total', 0)} commits"
    if kind in ("tasks", "workplace"):
        extra = f"  blocked: {str(i['blocked_by'])[:40]}" if i.get("blocked_by") else ""
        return f"  {str(i.get('state') or ''):<7} {str(i['id'])[:34]:<34} {title[:50]}{extra}{mark}"
    state = str(i.get("raw_state") or i.get("state") or "")
    return f"  {str(i['id'])[:30]:<30} {title[:56]:<56} {state[:16]}{mark}".rstrip()


def _summary(result: dict, profile: dict, style: str | None) -> str:
    """One line for the log: rows per bucket (counted as triage, whatever the style
    shows), or rows per section without a view."""
    if _view().style_of(profile, style) != "sources":
        v = _view().build(result, profile, "triage")
        parts = [f"{b['title']} {b.get('total', len(b['items']))}" for b in v["buckets"]]
        parts += [f"{len(v.get('agenda') or [])} events"] if v.get("agenda") else []
    else:
        parts = [f"{s['title']} {s['total']}" for s in result["sections"] if s.get("status") == "ok" and s["total"]]
    errors = [s["title"] for s in result["sections"] if s.get("status") == "error"]
    return ", ".join(parts or ["nothing open"]) + (f"; failed: {', '.join(errors)}" if errors else "")


def render(result: dict) -> str:
    out = [f"{result.get('title') or result['profile']}  ({result.get('collected_at', '')})"]
    for s in result["sections"]:
        count = f"{len(s['items'])} of {s['total']}" if s["total"] > len(s["items"]) else str(s["total"])
        out += ["", f"── {s['title']} ({count}) " + "─" * max(4, 50 - len(s['title']) - len(count))]
        if s["status"] != "ok":
            out.append(f"  {s['status']}: {s.get('reason', '')}")
            continue
        if s.get("stale"):
            out.append(f"  stale, as of {s.get('cached_at', '')}: {s['stale'].get('reason', '')}")
        out += [_line(str(s.get("kind")), i) for i in s["items"]]
        untracked = sum(1 for i in s.get("all") or s["items"] if i.get("untasked") is True)
        if untracked:
            out.append(f"  {untracked} assigned issue{'s' if untracked != 1 else ''} without a task")
        for b in [b for b in s.get("summary") or [] if b.get("open")]:
            counts = " · ".join(f"{n} {st.replace('_', ' ')}" for st, n in b["counts"].items() if n)
            out.append(f"  #{b.get('number')} {b['name']}: {counts or 'empty'}")
    notes = list(result.get("housekeeping") or [])
    if result.get("owed"):
        notes.append(f"not in this profile, still yours to run: {', '.join(result['owed'])} (briefing.py owed)")
    if notes:
        out += ["", "── Housekeeping"] + [f"  · {n}" for n in notes]
    return "\n".join(out)


def render_view(result: dict, profile: dict, style: str | None = None, color: bool = False) -> str:
    """The briefing as the profile's `view:` (or a one-off `style`) wants it shown."""
    view = _view()
    chosen = view.style_of(profile, style)
    if chosen == "sources":
        return render(_public(result))
    return view.draw(view.build(result, profile, chosen), color=color)


# ---------------------------------------------------------------- CLI

ACTION_RE = re.compile(r"^[a-z][a-z0-9_-]{0,39}\Z")
UNDO_RE = re.compile(r"^restore:[A-Za-z0-9._~-]{1,120}\Z")
ROW_ID_RE = re.compile(r"^[A-Za-z0-9][^\x00-\x1f]{0,199}\Z")
ACT_TIMEOUT = 60


def act(root: Path, cfg: dict, profile: dict, section_ref: str, row_id: str, action: str) -> tuple[int, str]:
    """Run one step of one row: the section must declare actions_argv, and the row, asked for again,
    must still offer the step. An undo token a step returned goes to the command unchecked here
    (the row may be gone by then); the command checks it. Returns (exit code, output or reason)."""
    section = next((s for s in profile.get("sections") or [] if section_id(s) == section_ref), None)
    if section and section.get("kind") == "calendar":
        return _act_calendar(root, cfg, section, row_id, action)
    if section and section.get("kind") == "tracker":
        return _act_tracker(root, cfg, profile, section, row_id, action)
    if not section or section.get("kind") != "command" or not _is_str_list(section.get("actions_argv")):
        return 2, f"section {section_ref} has no actions"
    if not ROW_ID_RE.match(row_id or ""):
        return 2, "not a row id"
    if not UNDO_RE.match(action):
        if not ACTION_RE.match(action):
            return 2, "not an action"
        try:
            rows = sec_command(section, Context(root, cfg=cfg))
        except (SourceError, Skip) as exc:
            return 2, f"section {section_ref} did not answer: {exc}"
        row = next((r for r in rows if str(r.get("id")) == row_id), None)
        offered = {a.get("id") for a in (row or {}).get("actions") or [] if isinstance(a, dict)}
        if action not in offered:
            return 2, f"row {row_id} does not offer {action}"
    argv = [row_id if a == "{id}" else action if a == "{action}" else a for a in section["actions_argv"]]
    try:
        res = subprocess.run(_own_python(argv), cwd=str(root), capture_output=True, text=True, timeout=ACT_TIMEOUT)
    except (OSError, subprocess.SubprocessError) as exc:
        return 1, str(exc)
    if res.returncode != 0:
        return res.returncode, (res.stderr or res.stdout).strip()[-300:]
    return 0, res.stdout.strip()


def _act_calendar(root: Path, cfg: dict, section: dict, row_id: str, action: str) -> tuple[int, str]:
    """A calendar row's step runs nothing here: asked for again, the event hands back the tab to start
    (summary, prompt, the inbox key that keeps a second click on the same event from filing it twice)."""
    if not ROW_ID_RE.match(row_id or "") or not ACTION_RE.match(action or ""):
        return 2, "not a row id or not an action"
    ctx = Context(root, cfg=cfg)
    try:
        events = calendar_events(section, ctx)
    except (SourceError, Skip) as exc:
        return 2, f"section {section_id(section)} did not answer: {exc}"
    event = next((e for e in events if _event_id(e) == row_id), None)
    words = _view().labels_for(conversation_language(cfg))
    step = next((x for x in event_steps(section, event, ctx.now, words) if x["id"] == action), None) if event else None
    if step is None:
        return 2, f"row {row_id} does not offer {action}"
    start = str(event.get("start") or "")
    when = f"{start[:10]} {start[11:16]}".strip()
    people = ", ".join(event.get("attendees") or [])
    if step["prompt"]:
        values = {"title": str(event.get("title") or ""), "start": start, "date": start[:10], "time": start[11:16],
                  "end": str(event.get("end") or ""), "calendar": str(event.get("calendar") or ""),
                  "location": str(event.get("location") or ""), "attendees": people}
        prompt = re.sub(r"\{([a-z]+)\}", lambda m: values.get(m.group(1), m.group(0)), step["prompt"])
    else:
        facts = [(words["tag_calendar"], event.get("calendar")), (words["prepare_place"], event.get("location")),
                 (words["prepare_people"], people)]
        prompt = "\n".join([words["prepare_head"].format(title=event.get("title"), when=when),
                            *[f"{label}: {value}" for label, value in facts if value], words["prepare_tail"]])
    return 0, json.dumps({"ok": True, "did": step["label"], "launch": {
        "summary": f"{step['label']}: {event.get('title')} ({when})"[:200], "prompt": prompt[:3500],
        "key": f"event:{action}:{row_id}"[:240]}}, ensure_ascii=False)


def _tracker_rows(root: Path, cfg: dict, profile: dict, section: dict) -> list:
    """The rows a tracker section showed: its kept answer of today (the one the page was drawn from,
    whatever its age, since GitHub takes half a minute), else asked again."""
    try:
        data = json.loads(_cache_file(root, profile, section).read_text(encoding="utf-8"))
        if dt.datetime.fromisoformat(data["at"]).date() == dt.date.today() and isinstance(data.get("items"), list):
            return data["items"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    ctx = Context(root, cfg=cfg)
    ctx.deadline = time.monotonic() + _positive(profile.get("timeout_sec"), ctx.timeout)
    return sec_tracker(dict(section), ctx)


def _act_tracker(root: Path, cfg: dict, profile: dict, section: dict, row_id: str, action: str) -> tuple[int, str]:
    """A GitHub row's step runs nothing here either: it hands back the tab to start, keyed
    `tracker:<step>:<row id>`, so a second click finds the same inbox item and the row names it."""
    if not (GLOBAL_ROW.match(row_id or "") or DRAFT_ROW.match(row_id or "")) or not ACTION_RE.match(action or ""):
        return 2, "not a row id or not an action"
    try:
        rows = _tracker_rows(root, cfg, profile, section)
    except (SourceError, Skip) as exc:
        return 2, f"section {section_id(section)} did not answer: {exc}"
    item = next((r for r in rows if str(r.get("id")) == row_id), None)
    words = _view().labels_for(conversation_language(cfg))
    step = next((x for x in tracker_steps(section, item, words) if x["id"] == action), None) if item else None
    if step is None:
        return 2, f"row {row_id} does not offer {action}"
    prompt = tracker_prompt(step, item, words)
    return 0, json.dumps({"ok": True, "did": step["label"], "launch": {
        "summary": f"{step['label']}: {row_id} {item.get('title') or ''}".strip()[:200], "prompt": prompt[:3500],
        "key": f"tracker:{action}:{row_id}"[:240]}}, ensure_ascii=False)


# ---------------------------------------------------------------- the detail of one GitHub row

DETAIL_DIR = CACHE / "github-detail"
DETAIL_MINUTES = 10
BODY_MAX = 12000
COMMENT_MAX = 4000
_PEOPLE = "assignees(first: 10) { nodes { login } } labels(first: 15) { nodes { name color } }"
_COMMENTS = "comments(last: 5) { totalCount nodes { author { login } body createdAt url } }"
_BOARDS = ('projectItems(first: 5) { nodes { project { title number } fieldValueByName(name: "Status") '
           '{ ... on ProjectV2ItemFieldSingleSelectValue { name } } } }')
DETAIL_QUERY = (
    "query($owner: String!, $name: String!, $number: Int!) { repository(owner: $owner, name: $name) { "
    "issueOrPullRequest(number: $number) { __typename "
    f"... on Issue {{ number title url state stateReason body createdAt updatedAt closedAt author {{ login }} {_PEOPLE} "
    f"milestone {{ title dueOn }} {_COMMENTS} {_BOARDS} "
    "closedByPullRequestsReferences(first: 5, includeClosedPrs: true) { nodes { number title url state isDraft } } } "
    f"... on PullRequest {{ number title url state isDraft body createdAt updatedAt mergedAt closedAt author {{ login }} "
    f"{_PEOPLE} {_COMMENTS} {_BOARDS} headRefName baseRefName additions deletions changedFiles reviewDecision mergeable "
    "reviewRequests(first: 10) { nodes { requestedReviewer { ... on User { login } ... on Team { name } } } } "
    "latestReviews(first: 10) { nodes { author { login } state submittedAt } } "
    "commits(last: 1) { nodes { commit { statusCheckRollup { state contexts(first: 40) { totalCount nodes { "
    "... on CheckRun { name conclusion status } ... on StatusContext { context state } } } } } } } "
    "closingIssuesReferences(first: 5) { nodes { number title url state } } } } } }")
FAILED_CHECKS = {"FAILURE", "ERROR", "TIMED_OUT", "CANCELLED", "ACTION_REQUIRED", "STARTUP_FAILURE"}


def _nodes(value) -> list:
    return [n for n in ((value or {}).get("nodes") or []) if isinstance(n, dict)] if isinstance(value, dict) else []


def _login(value) -> str | None:
    return value.get("login") if isinstance(value, dict) else None


def detail_of(node: dict, ref: str) -> dict:
    """One issue or pull request as a dashboard opens it: what it says, who is on it, where it stands."""
    kind = "pr" if node.get("__typename") == "PullRequest" else "issue"
    comments = node.get("comments") if isinstance(node.get("comments"), dict) else {}
    out = {"ok": True, "ref": ref, "type": kind, "number": node.get("number"), "title": node.get("title"),
           "url": node.get("url"), "state": str(node.get("state") or "").lower(),
           "state_reason": str(node.get("stateReason") or "").lower() or None, "draft": bool(node.get("isDraft")),
           "author": _login(node.get("author")), "created": node.get("createdAt"), "updated": node.get("updatedAt"),
           "closed": node.get("closedAt"), "landed_at": node.get("mergedAt"),
           "body": str(node.get("body") or "")[:BODY_MAX], "body_cut": len(str(node.get("body") or "")) > BODY_MAX,
           "assignees": [x for x in (_login(n) for n in _nodes(node.get("assignees"))) if x],
           "labels": [{"name": n.get("name"), "color": n.get("color")} for n in _nodes(node.get("labels")) if n.get("name")],
           "milestone": (node.get("milestone") or {}).get("title") if isinstance(node.get("milestone"), dict) else None,
           "comments": {"total": comments.get("totalCount") or 0,
                        "items": [{"author": _login(n.get("author")), "at": n.get("createdAt"), "url": n.get("url"),
                                   "body": str(n.get("body") or "")[:COMMENT_MAX]} for n in _nodes(comments)]},
           "boards": [{"title": (n.get("project") or {}).get("title"), "number": (n.get("project") or {}).get("number"),
                       "status": (n.get("fieldValueByName") or {}).get("name")} for n in _nodes(node.get("projectItems"))]}
    if kind == "issue":
        out["prs"] = [{"number": n.get("number"), "title": n.get("title"), "url": n.get("url"),
                       "state": str(n.get("state") or "").lower(), "draft": bool(n.get("isDraft"))}
                      for n in _nodes(node.get("closedByPullRequestsReferences"))]
        return out
    rollup = {}
    for c in _nodes(node.get("commits")):
        rollup = ((c.get("commit") or {}).get("statusCheckRollup") or {}) if isinstance(c.get("commit"), dict) else {}
    contexts = rollup.get("contexts") if isinstance(rollup.get("contexts"), dict) else {}
    failing = [n.get("name") or n.get("context") for n in _nodes(contexts)
               if str(n.get("conclusion") or n.get("state") or "").upper() in FAILED_CHECKS]
    running = [n.get("name") for n in _nodes(contexts) if str(n.get("status") or "").upper() in ("IN_PROGRESS", "QUEUED")]
    out["pr"] = {"head": node.get("headRefName"), "base": node.get("baseRefName"), "additions": node.get("additions"),
                 "deletions": node.get("deletions"), "files": node.get("changedFiles"),
                 "review": str(node.get("reviewDecision") or "").lower() or None,
                 "mergeable": str(node.get("mergeable") or "").lower() or None,
                 "requested": [x for x in ((n.get("requestedReviewer") or {}).get("login") or
                                           (n.get("requestedReviewer") or {}).get("name") for n in _nodes(node.get("reviewRequests"))) if x],
                 "reviews": [{"author": _login(n.get("author")), "state": str(n.get("state") or "").lower(),
                              "at": n.get("submittedAt")} for n in _nodes(node.get("latestReviews"))],
                 "checks": {"state": str(rollup.get("state") or "").lower() or None,
                            "total": contexts.get("totalCount") or 0, "failing": [f for f in failing if f][:10],
                            "running": [r for r in running if r][:10]}}
    out["closes"] = [{"number": n.get("number"), "title": n.get("title"), "url": n.get("url"),
                      "state": str(n.get("state") or "").lower()} for n in _nodes(node.get("closingIssuesReferences"))]
    return out


def github_detail(root: Path, ref: str, fresh: bool = False, ctx: Context | None = None) -> tuple[int, dict]:
    """The detail of one GitHub row, kept for ten minutes: one GraphQL call of a few points, under the same
    block as every section (a spent budget asks nothing and shows the last kept detail, said to be old)."""
    m = GLOBAL_ROW.match(ref or "")
    if not m:
        return 2, {"ok": False, "error": "not an owner/repo#number"}
    owner, name = m.group(1).split("/", 1)
    path = root / DETAIL_DIR / f"{owner}__{name}__{m.group(2)}.json"
    ctx = ctx or Context(root)
    kept = None
    try:
        kept = json.loads(path.read_text(encoding="utf-8"))
        at = dt.datetime.fromisoformat(kept["fetched_at"])
        if not fresh and dt.timedelta(0) <= ctx.now - at < dt.timedelta(minutes=DETAIL_MINUTES):
            return 0, kept
    except (OSError, ValueError, KeyError, TypeError):
        kept = None
    ctx.deadline = time.monotonic() + ctx.timeout
    try:
        data = json.loads(ctx.run(["gh", "api", "graphql", "-f", f"query={DETAIL_QUERY}", "-f", f"owner={owner}",
                                   "-f", f"name={name}", "-F", f"number={m.group(2)}"], timeout=ctx.timeout))
        node = ((data.get("data") or {}).get("repository") or {}).get("issueOrPullRequest")
        if not isinstance(node, dict):
            raise SourceError("GitHub knows no issue or pull request by that number")
    except (SourceError, ValueError) as exc:
        if kept:
            return 0, {**kept, "stale": ctx.redact(str(exc))[:200]}
        return 1, {"ok": False, "error": ctx.redact(str(exc))[:300]}
    finally:
        ctx.deadline = None
    out = {**detail_of(node, ref), "fetched_at": ctx.now.isoformat(timespec="seconds")}
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
        tmp.replace(path)
    except OSError:
        pass
    return 0, out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--root", type=Path, default=ROOT)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    p_show = sub.add_parser("show")
    p_show.add_argument("id", nargs="?")
    p_offer = sub.add_parser("offer")
    p_offer.add_argument("text")
    p_owed = sub.add_parser("owed", help="streams this profile does not cover, and how to run them")
    p_owed.add_argument("id", nargs="?")
    p_owed.add_argument("--json", action="store_true")
    for name in ("collect", "render"):
        p = sub.add_parser(name)
        p.add_argument("id", nargs="?")
        p.add_argument("--file", action="store_true", help="file to_inbox rows as inbox items")
        p.add_argument("--no-save", action="store_true", help="do not update the last-run snapshot")
        p.add_argument("--fresh", action="store_true",
                       help="ask every source now, whatever a section's cache_minutes allows")
        p.add_argument("--skip", action="append", default=[], choices=SECTION_KINDS, metavar="KIND",
                       help="leave out sections of this kind (repeatable; the quick mode of /briefing is "
                            "--skip tracker --skip calendar)")
        p.add_argument("--only", action="append", default=[], choices=SECTION_KINDS, metavar="KIND",
                       help="run only sections of this kind (repeatable); the rest are listed as skipped")
        p.add_argument("--max-items", type=int, metavar="N",
                       help="show up to N rows in this run's view instead of the profile's view.max_items "
                            "(for a dashboard that pages itself)")
        p.add_argument("--style", choices=("sources", "triage", "brevity", "plan", "report"),
                       help="show this run in another view than the profile's view.style")
        if name == "collect":
            p.add_argument("--json", action="store_true")
        else:
            p.add_argument("--color", choices=("auto", "always", "never"), default="auto")
    sub.add_parser("validate")
    p_act = sub.add_parser("act", help="run one step a row of a command section offers (actions_argv)")
    p_act.add_argument("id")
    p_act.add_argument("section")
    p_act.add_argument("row")
    p_act.add_argument("action")
    p_detail = sub.add_parser("detail", help="the detail of one GitHub issue or pull request (owner/repo#n), as JSON")
    p_detail.add_argument("ref")
    p_detail.add_argument("--fresh", action="store_true", help="ask GitHub now, whatever was kept")
    args = ap.parse_args(argv)
    root = args.root.resolve()
    cfg = read_config(root)

    if args.cmd == "validate":
        problems = validate(root)
        for p in problems:
            print(p)
        print(f"briefing profiles: {len(load_profiles(root))} checked, {len(problems)} problem(s)")
        return 1 if problems else 0

    if args.cmd == "list":
        profiles = load_profiles(root)
        try:
            chosen = select(root, cfg)["id"]
        except Ambiguous:
            chosen = None
        if not profiles:
            print("builtin  (no workflow/briefings/*.yaml; `show` prints the built-in profile) [default]")
        for p in profiles:
            kinds = ", ".join(section_id(s) for s in p.get("sections") or [])
            tag = " [default]" if p.get("id") == chosen else ""
            print(f"{p.get('id')}{tag}  {p.get('title') or ''}  for: {p.get('for') or '-'}")
            print(f"    sections: {kinds}")
            if p.get("offer_on"):
                print(f"    offered on: {', '.join(p['offer_on'])}")
        return 0

    if args.cmd == "offer":
        print("\n".join(offer(load_profiles(root), args.text)))
        return 0

    if args.cmd == "detail":
        code, data = github_detail(root, args.ref, fresh=args.fresh)
        print(json.dumps(data, ensure_ascii=False), file=sys.stdout if code == 0 else sys.stderr)
        return code

    try:
        # the profile carries the Bridge's language, so its default words come in it (briefing_view.labels_for)
        profile = {**select(root, cfg, getattr(args, "id", None)), "_language": conversation_language(cfg)}
    except Ambiguous as exc:
        print(f"briefing: choose a profile: {', '.join(exc.ids)} (or set default: true in one)", file=sys.stderr)
        return 2
    except UnknownProfile as exc:
        print(f"briefing: {exc}", file=sys.stderr)
        return 2

    if args.cmd == "act":
        code, text = act(root, cfg, profile, args.section, args.row, args.action)
        print(text, file=sys.stdout if code == 0 else sys.stderr)
        return code

    if args.cmd == "show":
        print(yaml.safe_dump({k: v for k, v in profile.items() if k != "_path"}, sort_keys=False,
                             allow_unicode=True), end="")
        print(f"# from {profile.get('_path')}")
        return 0

    if args.cmd == "owed":
        found = owed(root, cfg, profile)
        if args.json:
            print(json.dumps(found, ensure_ascii=False, indent=1))
        else:
            for o in found:
                print(f"{o['id']}: {o['title']}\n    {o['how']}")
            if not found:
                print("nothing owed: the profile covers every stream that applies here")
        return 0

    if getattr(args, "max_items", None):
        view_cfg = profile.get("view") if isinstance(profile.get("view"), dict) else {}
        # a dashboard that pages itself wants every row of a section, not the first `max:` of them:
        # a cut row would vanish from its page without a trace (an inbox item set to later, 14.10.)
        profile = {**profile, "view": {**view_cfg, "max_items": max(1, args.max_items)}, "_whole": True}
    ctx = Context(root, cfg=cfg)
    ctx.fresh = bool(getattr(args, "fresh", False))
    previous = load_snapshot(root, profile["id"])
    skip = set(getattr(args, "skip", None) or [])
    only = tuple(dict.fromkeys(getattr(args, "only", None) or []))
    if only:
        skip |= set(SECTION_KINDS) - set(only)
    result = collect(root, profile, ctx, previous=previous, skip=tuple(sorted(skip)), style=args.style, only=only)
    result["owed"] = [o["id"] for o in owed(root, cfg, profile)]
    if args.file:
        box = _inbox().Inbox(root / "work" / "inbox", actor="briefing")
        filed, closed = file_to_inbox(box, profile, result)
        result["inbox"] = {"filed": filed, "closed": closed}
        result["housekeeping"] = housekeep(root, ctx.now, summary=_summary(result, profile, args.style),
                                           profile_id=profile["id"])
    if args.cmd == "render" and _view().style_of(profile, args.style) != "sources":
        view_cfg = profile.get("view") if isinstance(profile.get("view"), dict) else {}
        if view_cfg.get("overview") == "file":
            # Long blocks are where a hand copy into the chat goes wrong: they live in a file.
            path = root / SNAPSHOTS / f"{profile['id']}.overview.txt"
            path.parent.mkdir(parents=True, exist_ok=True)
            built = _view().build(result, profile, args.style)
            path.write_text(_view().draw_overview(built), encoding="utf-8")
            note = built["labels"]["overview_file"].format(path=path.relative_to(root))
            result["housekeeping"] = list(result.get("housekeeping") or []) + [note]
    if not args.no_save:
        save_snapshot(root, result, previous)
    if args.cmd == "collect":
        data = _public(result)
        if _view().style_of(profile, args.style) != "sources":
            data["view"] = _view().build(result, profile, args.style)
        data["pages"] = _view().pages(result, profile, root=root)
        if args.json:
            print(json.dumps(data, ensure_ascii=False, indent=1, default=str))
        else:
            print(render_view(result, profile, args.style))
    else:
        color = args.color == "always" or (args.color == "auto" and sys.stdout.isatty())
        print(render_view(result, profile, args.style, color=color))
    return 0


if __name__ == "__main__":
    sys.exit(main())
