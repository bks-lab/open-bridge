#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The cockpit's Setup page: what still keeps the cockpit from working well, and what can be switched on.

    python3 scripts/bridge-setup.py check --part checks [--json]      # findings only, [] when all is well
    python3 scripts/bridge-setup.py check --part available [--json]   # catalogue features that are off
    python3 scripts/bridge-setup.py check --part on [--json]          # catalogue features that are on
    python3 scripts/bridge-setup.py act <feature-id> later|silence    # the one write, with an undo token
    python3 scripts/bridge-setup.py act <feature-id> restore:<token>  # its undo, checked here

Each part prints the JSON list a briefing `command` section reads (docs/briefings.md): `briefing.py collect
--setup` runs the three parts as the sections setup-checks, setup-available and setup-on, and the cockpit
shows them as its Setup page (docs/bridge-cockpit.md, The Setup page). A finding gets the cockpit's row
steps (Let AI do it, Advise, Close, Later); the catalogue's rows add later and not for me.

What it never does: switch a feature on or write bridge-config.yaml. Each row names the step that does
(`/bridge-onboard --add <feature>` or the config key), and the agent tab Let AI do it opens runs it, where
the person confirms. Checks read only this Bridge's files (discovery.mode confined holds), with two probes
on a short time limit: the terminal driver through the Bridge's own scripts/workplace.py, and the gh CLI
only while integrations.github.enabled is true. The one write is `act`: a feature put off for 30 days
(`deferred`, `remind_after`) or silenced, in work/onboarding-state.yaml in the schema of
skills/bridge-onboard/references/system-discovery.md (Discovery State).

The catalogue is skills/bridge-onboard/references/features.yaml, one entry per heading of feature-catalog.md.
Contract: scripts/tests/test_bridge_cockpit_setup.py.
"""
from __future__ import annotations

import argparse
import base64
import contextlib
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import yaml

try:
    import fcntl
except ImportError:          # Windows: no advisory lock, one click at a time is then the person's
    fcntl = None

CODE = Path(__file__).resolve().parents[1]
if str(CODE / "scripts") not in sys.path:
    sys.path.insert(0, str(CODE / "scripts"))

from lib import briefing_view as bv  # noqa: E402  (path set above)

CATALOG = CODE / "skills" / "bridge-onboard" / "references" / "features.yaml"
TEMPLATE = CODE / "workflow" / "briefings" / "_template.yaml"
STATE = Path("work") / "onboarding-state.yaml"
PARTS = ("checks", "available", "on")
ACTIONS = ("later", "silence")
DEFER_DAYS = 30
PROBE_TIMEOUT = 5            # each probe; a section has 30 s for all of them
# the statuses of Discovery State; `act` writes deferred and silenced, an undo restores any of them
STATUSES = ("accepted", "deferred", "declined", "silenced", "nothing_found", "not_evaluated")
HIDDEN = ("silenced", "declined")      # the person said no: never offered here again
# restore:<key>.<earlier status or none>.<earlier remind_after or _>.<earlier decided_at or _>.<digest of what was written>
UNDO_RE = re.compile(r"^restore:([a-z][a-z0-9_]{0,39})\.([a-z_]{1,20})\.(\d{4}-\d{2}-\d{2}|_)\.([TYS][A-Za-z0-9_-]{1,80}|_)"
                     r"\.([0-9a-f]{10})\Z")


# ---------------------------------------------------------------- reading

def read_yaml(path: Path) -> dict:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return {}
    return data if isinstance(data, dict) else {}


def read_config(root: Path) -> dict:
    return read_yaml(Path(root) / "bridge-config.yaml")


def words_for(cfg: dict) -> dict:
    """The Bridge's language (language.conversation), the way briefing.py picks the words of its sections."""
    lang = cfg.get("language")
    return bv.labels_for(str((lang.get("conversation") if isinstance(lang, dict) else lang) or "en"))


def load_catalog() -> list:
    """Every entry of features.yaml in catalogue order, the skips included."""
    data = read_yaml(CATALOG)
    return [e for e in data.get("features") or [] if isinstance(e, dict)]


def features() -> list:
    return [e for e in load_catalog() if "skip" not in e and isinstance(e.get("id"), str)]


def _get(cfg: dict, dotted: str):
    value = cfg
    for part in dotted.split("."):
        if not isinstance(value, dict):
            return None
        value = value.get(part)
    return value


def _inside(root: Path, rel: str) -> Path | None:
    if not isinstance(rel, str) or not rel or rel.startswith("/") or ".." in Path(rel).parts:
        return None
    return Path(root) / rel


def holds(test: dict, root: Path, cfg: dict) -> bool:
    """One test of the catalogue: a config path that is set (a block with `enabled` counts by that), files of a
    glob inside the Bridge (a path with a `_` part left out; a pattern ending in / counts folders), or one path that exists."""
    if not isinstance(test, dict) or len(test) != 1:
        return False
    kind, arg = next(iter(test.items()))
    if kind == "config":
        value = _get(cfg, str(arg))
        if isinstance(value, dict) and "enabled" in value:
            return value["enabled"] is True
        return value is True or (not isinstance(value, bool) and bool(value))
    if kind == "files":
        if _inside(root, str(arg).rstrip("/")) is None:
            return False
        dirs = str(arg).endswith("/")
        return any(not any(x.startswith("_") for x in p.relative_to(root).parts) and (p.is_dir() if dirs else p.is_file())
                   for p in Path(root).glob(str(arg).rstrip("/")))
    if kind == "exists":
        path = _inside(root, str(arg))
        return path is not None and path.exists()
    return False


def is_on(entry: dict, root: Path, cfg: dict) -> bool:
    return any(holds(t, root, cfg) for t in entry.get("enabled_when") or [])


def offered(entry: dict, root: Path, cfg: dict) -> bool:
    cond = entry.get("offer_only_when", [])
    if cond == "never":
        return False
    return all(holds(t, root, cfg) for t in cond or [])


def suggestions(root: Path) -> dict:
    s = read_yaml(Path(root) / STATE).get("suggestions")
    return s if isinstance(s, dict) else {}


def _date(value) -> dt.date | None:
    if isinstance(value, dt.datetime):
        return value.date()
    if isinstance(value, dt.date):
        return value
    try:
        return dt.date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


# ---------------------------------------------------------------- probes

class Probes:
    """The only two looks beyond this Bridge's files, each within PROBE_TIMEOUT. None means unknown: no finding."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def launch(self) -> bool | None:
        try:
            from lib.bridge_cockpit.launch import can_launch
        except ImportError:
            return None
        return can_launch(self.root, timeout=PROBE_TIMEOUT)

    def gh(self) -> str | None:
        """missing, signed_out or ok; asked only while integrations.github.enabled is true."""
        exe = shutil.which("gh")
        if not exe:
            return "missing"
        try:
            run = subprocess.run([exe, "auth", "status"], capture_output=True, text=True, timeout=PROBE_TIMEOUT,
                                 stdin=subprocess.DEVNULL)
        except (OSError, subprocess.SubprocessError):
            return None
        return "ok" if run.returncode == 0 else "signed_out"


# ---------------------------------------------------------------- the parts

def _row(rid: str, title: str, detail: str, tone: str, url: str | None = None, **extra) -> dict:
    return {"id": rid, "title": title, "detail": detail, "tone": tone, **({"url": url} if url else {}), **extra}


def placeholders() -> set:
    """The template's placeholder values (`your-org`, `your-handle`): a copied profile that still holds one finds nothing."""
    found = set()

    def walk(v):
        if isinstance(v, dict):
            for x in v.values():
                walk(x)
        elif isinstance(v, list):
            for x in v:
                walk(x)
        elif isinstance(v, str) and v.startswith("your-"):
            found.add(v)
    walk(read_yaml(TEMPLATE))
    return found


def _holding(value, marks: set) -> str | None:
    if isinstance(value, dict):
        return next((h for v in value.values() if (h := _holding(v, marks))), None)
    if isinstance(value, list):
        return next((h for v in value if (h := _holding(v, marks))), None)
    if isinstance(value, str):
        return next((m for m in sorted(marks) if m in value), None)
    return None


def check_profiles(root: Path, words: dict) -> list:
    files = [p for p in sorted((Path(root) / "workflow" / "briefings").glob("*.yaml")) if not p.name.startswith("_")]
    if not files:
        return [_row("builtin-profile", words["setup_builtin_profile"], words["setup_builtin_profile_detail"], "warn",
                     "docs/bridge-cockpit.md")]
    marks, out = placeholders(), []
    for path in files:
        data = read_yaml(path)
        pid = path.stem
        spots = [(str(k), v) for k, v in data.items() if k != "sections"]
        sections = data.get("sections") if isinstance(data.get("sections"), list) else []   # validate names the rest
        spots += [(str(s.get("id") or s.get("kind")), s) for s in sections if isinstance(s, dict)]
        for where, value in spots:
            mark = _holding(value, marks)
            if mark:
                out.append(_row(f"placeholder-{pid}-{where}", words["setup_placeholder"].format(profile=pid, value=mark),
                                words["setup_placeholder_detail"].format(profile=pid, where=where, value=mark), "warn",
                                str(path.relative_to(root))))
    return out


def check_cockpit_config(root: Path, words: dict) -> list:
    try:
        from lib.bridge_cockpit.config import WebConfigError, load_web_config
    except ImportError:
        return []
    try:
        warnings = load_web_config(root).config_warnings
    except WebConfigError as error:
        return [_row("config-error", words["setup_config_error"], words["setup_config_error_detail"].format(error=error),
                     "bad", "docs/bridge-cockpit.md")]
    return [_row(f"config-{hashlib.sha1(w.encode('utf-8')).hexdigest()[:10]}", words["setup_config"],
                 words["setup_config_detail"].format(warning=w), "warn", "docs/bridge-cockpit.md") for w in warnings]


def checks(root: Path, cfg: dict, probes, words: dict) -> list:
    """What actually keeps the cockpit from working well; nothing when all is well."""
    out = []
    if _get(cfg, "work.enabled") is not True:
        out.append(_row("work-off", words["setup_work_off"], words["setup_work_off_detail"], "warn", "docs/work-system.md"))
    if probes.launch() is False:          # None: the driver did not answer, which proves nothing
        out.append(_row("no-driver", words["setup_no_driver"], words["setup_no_driver_detail"], "warn", "docs/workplace.md"))
    runner = _get(cfg, "inbox.runner")
    if not (isinstance(runner, str) and runner.strip()):
        out.append(_row("no-runner", words["setup_no_runner"], words["setup_no_runner_detail"], "warn", "docs/inbox.md"))
    out += check_profiles(root, words)
    if _get(cfg, "integrations.github.enabled") is True:     # gh is probed only for an integration that is on
        gh = probes.gh()
        if gh == "missing":
            out.append(_row("gh-missing", words["setup_gh_missing"], words["setup_gh_missing_detail"], "bad"))
        elif gh == "signed_out":
            out.append(_row("gh-signed-out", words["setup_gh_signed_out"], words["setup_gh_signed_out_detail"], "bad"))
    out += check_cockpit_config(root, words)
    return out


def _focus_first(entries: list, cfg: dict) -> list:
    """purpose.focus orders, never removes (feature-catalog.md, Purpose Banding)."""
    focus = _get(cfg, "purpose.focus")
    focus = [f for f in focus if isinstance(f, str)] if isinstance(focus, list) else []
    return sorted(entries, key=lambda e: focus.index(e["group"]) if e.get("group") in focus else len(focus))


def available(root: Path, cfg: dict, words: dict, today: dt.date) -> list:
    """Catalogue features that are off and offered here. One put off shows dim with its date until remind_after;
    one silenced or declined never shows."""
    state, out = suggestions(root), []
    for e in _focus_first(features(), cfg):
        if is_on(e, root, cfg) or not offered(e, root, cfg):
            continue
        entry = state.get(e["state_key"]) if isinstance(state.get(e["state_key"]), dict) else {}
        if entry.get("status") in HIDDEN:
            continue
        until = _date(entry.get("remind_after")) if entry.get("status") == "deferred" else None
        later = until is not None and until > today
        detail = (words["setup_deferred"].format(date=until.isoformat(), when=e["when"], command=e["activate"]) if later
                  else words["setup_activate"].format(when=e["when"], command=e["activate"]))
        steps = [] if later else [{"id": "later", "label": words["setup_later"]}]
        steps.append({"id": "silence", "label": words["setup_silence"]})
        out.append(_row(e["id"], e["title"], detail, "dim" if later else "none", e.get("doc"), actions=steps))
    return out


def switched_on(root: Path, cfg: dict) -> list:
    return [_row(e["id"], e["title"], e["when"], "dim", e.get("doc")) for e in features() if is_on(e, root, cfg)]


def check_part(root: Path, part: str, cfg: dict | None = None, probes=None, today: dt.date | None = None) -> list:
    root = Path(root)
    cfg = read_config(root) if cfg is None else cfg
    words = words_for(cfg)
    if part == "checks":
        return checks(root, cfg, probes or Probes(root), words)
    if part == "available":
        return available(root, cfg, words, today or dt.date.today())
    if part == "on":
        return switched_on(root, cfg)
    raise ValueError(f"unknown part {part!r}")


# ---------------------------------------------------------------- act: the one write

LOCK = Path(".bridge") / "setup.lock"     # beside the state, so two clicks side by side lose no decision


@contextlib.contextmanager
def _locked(root: Path):
    """One step at a time: read, change and replace work/onboarding-state.yaml under an exclusive lock."""
    path = Path(root) / LOCK
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "a", encoding="utf-8") as fh:
        if fcntl is not None:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            if fcntl is not None:
                fcntl.flock(fh.fileno(), fcntl.LOCK_UN)


def _write_state(root: Path, data: dict) -> None:
    """Replace the file whole (its comments are not kept), with the mode it had."""
    path = Path(root) / STATE
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        mode = path.stat().st_mode & 0o777
    else:
        mask = os.umask(0)
        os.umask(mask)
        mode = 0o666 & ~mask
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".onboarding-state.", suffix=".yaml")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            yaml.safe_dump(data, fh, sort_keys=False, allow_unicode=True)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _state_doc(root: Path) -> tuple[dict, dict] | str:
    """The state file as it stands, read strictly: missing is empty, anything it cannot read is a refusal (a reason),
    never an empty file to write over."""
    path = Path(root) / STATE
    if not path.exists():
        data: object = {}
    else:
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, yaml.YAMLError) as exc:
            return f"{STATE} cannot be read ({exc.__class__.__name__}): nothing written"
        data = {} if data is None else data
    if not isinstance(data, dict):
        return f"{STATE} is not a mapping: nothing written"
    sugg = data.get("suggestions")
    if sugg is None:
        sugg = data["suggestions"] = {}
    if not isinstance(sugg, dict):
        return f"{STATE}: suggestions is not a mapping: nothing written"
    return data, sugg


def _stamp(value) -> str:
    """An earlier decided_at as one token part: _ for none, else its kind (T a timestamp, Y a date, S text) and the
    text in base64url, so the undo writes back exactly what stood there."""
    if value is None:
        return "_"
    kind = "T" if isinstance(value, dt.datetime) else "Y" if isinstance(value, dt.date) else "S"
    text = value.isoformat() if kind != "S" else str(value)
    return kind + base64.urlsafe_b64encode(text.encode("utf-8")).decode("ascii").rstrip("=")


def _unstamp(part: str):
    if part == "_":
        return None
    raw = base64.urlsafe_b64decode(part[1:] + "=" * (-len(part[1:]) % 4)).decode("utf-8")
    return dt.datetime.fromisoformat(raw) if part[0] == "T" else dt.date.fromisoformat(raw) if part[0] == "Y" else raw


def _digest(key: str, prev: str, entry: dict) -> str:
    """Binds an undo to the entry its step wrote and to the earlier values it carries: any change refuses it."""
    body = json.dumps({"key": key, "prev": prev, "entry": entry}, sort_keys=True, default=str, ensure_ascii=False)
    return hashlib.sha1(body.encode("utf-8")).hexdigest()[:10]


def act(root: Path, fid: str, action: str, today: dt.date | None = None) -> tuple[int, dict | str]:
    """later (deferred, remind_after in 30 days) or silence (silenced) for one catalogue feature, or the undo
    of one. Returns (exit code, result or reason); the result carries `undo: restore:...`."""
    root = Path(root)
    today = today or dt.date.today()
    feature = next((e for e in features() if e["id"] == fid), None)
    if feature is None:
        return 2, f"no feature {fid!r} in the catalogue"
    if action.startswith("restore:"):
        with _locked(root):
            return _restore(root, feature, action)
    if action not in ACTIONS:
        return 2, f"not a step of the Setup page: {action!r}"
    key = feature["state_key"]
    with _locked(root):
        doc = _state_doc(root)
        if isinstance(doc, str):
            return 2, doc
        data, sugg = doc
        if key in sugg and not isinstance(sugg[key], dict):
            return 2, f"{STATE}: suggestions.{key} is not a mapping: nothing written"
        before = sugg.get(key)
        entry = dict(before or {})
        entry["status"] = "deferred" if action == "later" else "silenced"
        entry["decided_at"] = dt.datetime.now().astimezone().isoformat(timespec="seconds")
        if action == "later":
            entry["remind_after"] = today + dt.timedelta(days=DEFER_DAYS)
        else:
            entry.pop("remind_after", None)
        undo = None
        status = (before or {}).get("status")
        if before is None or status in STATUSES:
            until = _date((before or {}).get("remind_after"))
            prev = (f"{status if before is not None else 'none'}.{until.isoformat() if until else '_'}."
                    f"{_stamp((before or {}).get('decided_at'))}")
            token = f"restore:{key}.{prev}.{_digest(key, prev, entry)}"
            undo = token if UNDO_RE.match(token) and len(token) <= 128 else None
        sugg[key] = entry
        _write_state(root, data)
    return 0, {"ok": True, "did": action, "id": fid, **({"undo": undo} if undo else {})}


def _restore(root: Path, feature: dict, token: str) -> tuple[int, dict | str]:
    """The token says what stood there before (status or none, remind_after, decided_at) and carries a digest of
    the entry its step wrote. It is taken only while the entry is exactly that, so neither a later decision nor a
    token with other earlier values is ever written."""
    found = UNDO_RE.match(token)
    if not found or found.group(1) != feature["state_key"]:
        return 2, "not an undo of this feature"
    key, status, date, stamp, digest = found.groups()
    if status != "none" and status not in STATUSES:
        return 2, f"not a status: {status!r}"
    until = None if date == "_" else _date(date)
    if date != "_" and until is None:
        return 2, f"not a date: {date!r}"
    try:
        decided = _unstamp(stamp)
    except (ValueError, UnicodeDecodeError):
        return 2, "not an undo of this feature"
    doc = _state_doc(root)
    if isinstance(doc, str):
        return 2, doc
    data, sugg = doc
    now = sugg.get(key) if isinstance(sugg.get(key), dict) else None
    if now is None or _digest(key, f"{status}.{date}.{stamp}", now) != digest:
        return 2, "the entry changed since this step: nothing restored"
    if status == "none":
        del sugg[key]
    else:
        entry = dict(now)
        entry["status"] = status
        for field, value in (("remind_after", until), ("decided_at", decided)):
            if value is None:
                entry.pop(field, None)
            else:
                entry[field] = value
        sugg[key] = entry
    _write_state(root, data)
    return 0, {"ok": True, "did": "restored", "id": feature["id"]}


# ---------------------------------------------------------------- command line

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--root", type=Path, default=CODE)
    sub = ap.add_subparsers(dest="cmd", required=True)
    p_check = sub.add_parser("check", help="print one part of the Setup page")
    p_check.add_argument("--part", choices=PARTS, required=True)
    p_check.add_argument("--json", action="store_true")
    p_act = sub.add_parser("act", help="later or silence one feature, or the undo of one")
    p_act.add_argument("id")
    p_act.add_argument("action")
    args = ap.parse_args(argv)
    root = args.root.resolve()
    if args.cmd == "check":
        rows = check_part(root, args.part)
        if args.json:
            print(json.dumps(rows, ensure_ascii=False))
        else:
            for r in rows:
                print(f"{r['id']}: {r['title']}\n    {r['detail']}")
        return 0
    code, out = act(root, args.id, args.action)
    if code == 0:
        print(json.dumps(out, ensure_ascii=False))
    else:
        print(f"bridge-setup: {out}", file=sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
