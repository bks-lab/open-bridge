#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""What this Bridge owns and runs, as briefing rows: machines, workers, cloud accounts.

    bridge-resources.py overview  [--workloads SRC]   the state of each family in one gauge row each
    bridge-resources.py machines                      infra/remotes/*.yaml, online from `tailscale status`
    bridge-resources.py workloads --source SRC        the workers of a host that are not in order
    bridge-resources.py workers --source SRC          every worker from `workload view --json`, kept for the Workers tab
    bridge-resources.py accounts                      identity/accounts/*.yaml with their resources
    bridge-resources.py cloud --source SRC            what runs in the cloud accounts (cloud-inventory.py)
    bridge-resources.py costs --source SRC            what the accounts cost per day (cloud-costs.py), kept for the cost card
    bridge-resources.py stamp FILE --host H --now T --out OUT   wrap a `workload reconcile --json` report
    bridge-resources.py set-status ID STATUS          an account's `status:` (active, paused, disabled)

Each listing prints the JSON list a briefing `kind: command` section reads (docs/briefings.md), and
keeps the last one in .bridge/resources/<family>.json, so a question to Claude can read what the
dashboard shows. A row may carry `tags` ({label: value}) the dashboard filters by, and an account
row its `account` ({id, status}). Only `set-status` writes, one line of one account file. Else only reads: declarations from the Bridge's own folders (discovery, `_` files
skipped), `tailscale status --json` when tailscale is there, and a worker report from SRC.

Declared is never live (rules/deploy-reconciliation.md): a row says which it is. Machines are live
when tailscale answers; workers are as live as the host's last reconcile (the report carries its
time and gets a warning when it is older than --stale-min); accounts are declarations, with the age
of their last check against the real thing (`snapshot.last_verified`) and the portal link.

SRC is a file, or `ssh:<host>:<path>` read with `ssh -o BatchMode=yes <host> cat <path>`; the host
writes that file itself (`stamp`), on its own schedule, so the dashboard never waits for a reconcile.
"""
from __future__ import annotations

import argparse
import datetime as dt
import fnmatch
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
RESOURCES = Path(".bridge") / "resources"     # what the dashboard showed last, under the Bridge root

# a worker state as a tone, the same table as WORKER_TONE in scripts/web/logic.js; anything else is warn. Red is an
# outage (gone, switched off, stopped, its last run failed), orange the upkeep a declaration and its machine drift into
STATE_TONE = {"in_sync": "none", "observed": "none", "unmanaged": "none", "intentionally_absent": "dim",
              "not reported": "dim", "not_provisioned": "dim", "absent": "bad", "disabled": "bad",
              "stopped": "bad", "last_run_failed": "bad",
              "drifted": "warn", "inventory_missing": "warn", "source_drift": "warn", "inventory_stale": "warn"}
# workers that need a look, worst first; in_sync, unmanaged and observed are not listed one by one
WORKER_RANK = {"absent": 0, "disabled": 1, "stopped": 1, "last_run_failed": 1, "drifted": 2, "inventory_missing": 3,
               "source_drift": 4, "inventory_stale": 5, "not_provisioned": 6, "unknown": 7}
QUIET_STATES = {"in_sync", "unmanaged", "observed", "intentionally_absent"}
# keys whose entries are resources of an account, at the top or under `cloud:`
RESOURCE_KEYS = ("subscriptions", "resource_groups", "keyvaults", "app_registrations", "zones", "workers",
                 "deployments", "domains", "buckets", "projects", "tunnels", "services", "repos")
STALE_DAYS = 90
ACCOUNT_STATUSES = ("active", "paused", "disabled")     # what the dashboard may set
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}\Z")

TX = {
    "en": {
        "online": "online", "offline": "offline", "always_on": "always on", "no_tailscale": "tailscale not readable",
        "seen": "last seen {when}", "verified": "checked {days} d ago", "never_verified": "never checked",
        "inactive": "status {status}", "portal": "portal",
        "res": {"subscriptions": "subscriptions", "resource_groups": "resource groups", "keyvaults": "key vaults",
                "app_registrations": "app registrations", "zones": "zones", "workers": "workers",
                "deployments": "deployments", "domains": "domains", "buckets": "buckets", "projects": "projects",
                "tunnels": "tunnels", "services": "services", "repos": "repos"},
        "worker_state": {"not reported": "not reported", "intentionally_absent": "parked", "absent": "missing", "disabled": "switched off for good", "drifted": "differs from its declaration",
                         "inventory_missing": "runs without an inventory entry", "source_drift": "source changed",
                         "inventory_stale": "inventory out of date", "not_provisioned": "declared, never installed",
                         "unknown": "state unknown"},
        "workers_ok": "{ok} of {total} workers on {host} in order", "workers_all_ok": "all {total} workers on {host} in order",
        "report_age": "as of {at}", "report_old": "the report is {min} min old", "report_missing": "no worker report from {src}: {err}",
        "ov_workers": "Workers in order", "ov_machines": "Always-on machines online", "ov_machines_any": "Machines online", "ov_accounts": "Accounts checked within {days} days",
        "ov_machines_all": "{n} of {total} machines online", "ov_accounts_detail": "{n} of {total} accounts",
        "cloud_head": "{n} resources", "cloud_apps": "{apps} apps: {up} running, {down} stopped",
        "cloud_failed": "not readable: {err}", "cloud_missing": "no cloud report from {src}: {err}",
        "cloud_partly": "partly: {err}",
        "costs_missing": "no cost report from {src}: {err}", "costs_yesterday": "yesterday {amount}",
        "costs_month": "{month} {amount}", "costs_of": "{amount} of {budget}", "costs_login": "{name}: sign-in needed, {hint}",
        "costs_old": "the report is {h} h old",
        "costs_credits": "used {used}, credits {credits}",
        "months": ["January", "February", "March", "April", "May", "June", "July", "August", "September",
                   "October", "November", "December"],
        "g_always": "Always on", "g_online": "Online", "g_offline": "Offline", "g_outside": "Not in the tailnet",
        "g_cloud": "Cloud", "g_mail": "Mail and calendar", "g_other": "Other", "g_inactive": "Inactive",
        "g_ok": "In order",
        "tag_kind": "Kind", "tag_state": "State", "tag_group": "Resource group", "tag_location": "Region",
        "tag_provider": "Provider", "tag_status": "Status", "tag_type": "Device", "tag_project": "Project",
        "tag_declared": "Known from", "declared_nowhere": "nowhere", "registry": "registry",
        "retired_on": "retired {date}, still at the provider",
        "status": {"active": "active", "paused": "paused", "disabled": "switched off", "legacy": "legacy",
                   "decommissioned": "decommissioned", "dormant": "dormant", "provisioning": "being set up"},
        "svc_state": {"running": "running", "stopped": "stopped", "present": "present", "deployed": "deployed",
                      "active": "active", "healthy": "healthy", "success": "deployed", "down": "down",
                      "degraded": "degraded", "failure": "failed", "inactive": "inactive", "pending": "pending"},
        "kinds": {"function app": "Function App", "web app": "Web App", "serverfarms": "App Service plan",
                  "storageaccounts": "Storage", "vaults": "Key Vault", "workspaces": "Log Analytics",
                  "components": "Application Insights", "accounts": "AI services", "userassignedidentities": "Identity",
                  "actiongroups": "Action group", "dashboards": "Dashboard", "namespaces": "Namespace",
                  "activitylogalerts": "Alert", "zone": "Zone", "worker": "Worker", "pages": "Pages", "tunnel": "Tunnel"},
    },
    "de": {
        "online": "online", "offline": "offline", "always_on": "immer an", "no_tailscale": "tailscale nicht lesbar",
        "seen": "zuletzt gesehen {when}", "verified": "geprüft vor {days} Tagen", "never_verified": "nie geprüft",
        "inactive": "Status {status}", "portal": "Portal",
        "res": {"subscriptions": "Subscriptions", "resource_groups": "Ressourcengruppen", "keyvaults": "Key Vaults",
                "app_registrations": "App-Registrierungen", "zones": "Zonen", "workers": "Worker",
                "deployments": "Deployments", "domains": "Domains", "buckets": "Buckets", "projects": "Projekte",
                "tunnels": "Tunnel", "services": "Dienste", "repos": "Repos"},
        "worker_state": {"not reported": "nicht gemeldet", "intentionally_absent": "geparkt", "absent": "fehlt", "disabled": "dauerhaft abgeschaltet", "drifted": "weicht von der Deklaration ab",
                         "inventory_missing": "läuft ohne Inventar-Eintrag", "source_drift": "Quelle geändert",
                         "inventory_stale": "Inventar veraltet", "not_provisioned": "deklariert, nie installiert",
                         "unknown": "Zustand unbekannt"},
        "workers_ok": "{ok} von {total} Workern auf {host} in Ordnung", "workers_all_ok": "alle {total} Worker auf {host} in Ordnung",
        "report_age": "Stand {at}", "report_old": "der Bericht ist {min} min alt", "report_missing": "kein Worker-Bericht von {src}: {err}",
        "ov_workers": "Worker in Ordnung", "ov_machines": "Dauer-Maschinen online", "ov_machines_any": "Maschinen online", "ov_accounts": "Konten geprüft in {days} Tagen",
        "ov_machines_all": "{n} von {total} Maschinen online", "ov_accounts_detail": "{n} von {total} Konten",
        "cloud_head": "{n} Ressourcen", "cloud_apps": "{apps} Apps: {up} laufen, {down} gestoppt",
        "cloud_failed": "nicht lesbar: {err}", "cloud_missing": "kein Cloud-Bericht von {src}: {err}",
        "cloud_partly": "teilweise: {err}",
        "costs_missing": "kein Kostenbericht von {src}: {err}", "costs_yesterday": "gestern {amount}",
        "costs_month": "{month} {amount}", "costs_of": "{amount} von {budget}", "costs_login": "{name}: Anmeldung nötig, {hint}",
        "costs_old": "der Bericht ist {h} h alt",
        "costs_credits": "verbraucht {used}, Gutschrift {credits}",
        "months": ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September",
                   "Oktober", "November", "Dezember"],
        "g_always": "Immer an", "g_online": "Online", "g_offline": "Offline", "g_outside": "Nicht im Tailnet",
        "g_cloud": "Cloud", "g_mail": "Mail und Kalender", "g_other": "Weitere", "g_inactive": "Inaktiv",
        "g_ok": "In Ordnung",
        "tag_kind": "Art", "tag_state": "Zustand", "tag_group": "Ressourcengruppe", "tag_location": "Region",
        "tag_provider": "Anbieter", "tag_status": "Status", "tag_type": "Gerät", "tag_project": "Projekt",
        "tag_declared": "Bekannt aus", "declared_nowhere": "nirgends", "registry": "Registry",
        "retired_on": "ausgemustert {date}, beim Anbieter noch da",
        "status": {"active": "aktiv", "paused": "pausiert", "disabled": "deaktiviert", "legacy": "Altlast",
                   "decommissioned": "abgebaut", "dormant": "ruhend", "provisioning": "im Aufbau"},
        "svc_state": {"running": "läuft", "stopped": "gestoppt", "present": "vorhanden", "deployed": "ausgerollt",
                      "active": "aktiv", "healthy": "gesund", "success": "ausgerollt", "down": "ausgefallen",
                      "degraded": "beeinträchtigt", "failure": "fehlgeschlagen", "inactive": "inaktiv", "pending": "wartet"},
        "kinds": {"function app": "Function App", "web app": "Web App", "serverfarms": "App-Service-Plan",
                  "storageaccounts": "Speicher", "vaults": "Key Vault", "workspaces": "Log Analytics",
                  "components": "Application Insights", "accounts": "KI-Dienste", "userassignedidentities": "Identität",
                  "actiongroups": "Aktionsgruppe", "dashboards": "Dashboard", "namespaces": "Namespace",
                  "activitylogalerts": "Alarm", "zone": "Zone", "worker": "Worker", "pages": "Pages", "tunnel": "Tunnel"},
    },
}


def language(root: Path) -> str:
    try:
        data = yaml.safe_load((root / "bridge-config.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return "en"
    lang = data.get("language")
    lang = lang.get("conversation") if isinstance(lang, dict) else lang
    return "de" if isinstance(lang, str) and lang.lower().startswith("de") else "en"


def declarations(root: Path, family: str) -> list[dict]:
    """Every `<family>/*.yaml` except `_` files (rules/discovery.md); a file that does not parse is skipped."""
    out = []
    for path in sorted((root / family).glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(data, dict):
            out.append({**data, "_file": f"{family}/{path.name}"})
    return out


def row(id_: str, title: str, detail: str = "", tone: str = "none", **extra) -> dict:
    r = {"id": id_, "title": title, "state": "ready", "raw_state": detail, "type": "task", "url": "",
         "tracker": "resources", "category": "open", "tone": tone}
    r.update({k: v for k, v in extra.items() if v is not None})
    return r


def tags(**pairs) -> dict | None:
    """Label -> value for the dashboard's filter chips; empty values left out."""
    out = {str(k): str(v) for k, v in pairs.items() if v not in (None, "", "None")}
    return out or None


def state_tone(state: str | None) -> str:
    return STATE_TONE.get(state or "", "warn")


def state_label(tx: dict, state: str) -> str:
    return tx["g_ok"] if state in ("in_sync", "observed") else tx["worker_state"].get(state, state)


def report_age(tx: dict, at, now: dt.datetime, stale_min: int) -> tuple[list[str], bool]:
    """'as of 14:30', plus how old when older than stale_min; ([], False) when `at` is no time."""
    try:
        t = dt.datetime.fromisoformat(str(at))
    except ValueError:
        return [], False
    parts = [tx["report_age"].format(at=t.astimezone().strftime("%H:%M"))]
    age = int((now - t).total_seconds() // 60) if t.tzinfo else 0
    if age > stale_min:
        parts.append(tx["report_old"].format(min=age))
    return parts, age > stale_min


def source_name(src: str) -> str:
    return src.split(":")[1] if src.startswith("ssh:") else src


def write_atomic(path: Path, text: str) -> None:
    """Write beside the target, then rename over it: a reader sees the old file or the new one, never half."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name("." + path.name + ".tmp")
    tmp.write_text(text, encoding="utf-8")
    os.replace(tmp, path)


def keep(root: Path, family: str, rows: list) -> None:
    """The last listing, for a question to Claude ("what runs where?"); never needed by the rows."""
    try:
        write_atomic(root / RESOURCES / f"{family}.json", json.dumps(rows, ensure_ascii=False, indent=1))
    except OSError:
        pass


# ---------------------------------------------------------------- machines

def tailscale_peers(run=subprocess.run) -> dict | None:
    """hostname (lower case) -> {online, last_seen}; None when tailscale is not there or does not answer."""
    exe = shutil.which("tailscale") or ("/usr/local/bin/tailscale" if Path("/usr/local/bin/tailscale").exists() else None)
    if not exe:
        return None
    try:
        res = run([exe, "status", "--json"], capture_output=True, text=True, timeout=8)
        data = json.loads(res.stdout) if res.returncode == 0 else None
    except (OSError, subprocess.SubprocessError, ValueError):
        return None
    if not isinstance(data, dict):
        return None
    out = {}
    for peer in list((data.get("Peer") or {}).values()) + ([data["Self"]] if isinstance(data.get("Self"), dict) else []):
        if not isinstance(peer, dict):
            continue
        names = {str(peer.get("HostName") or "").lower(), str(peer.get("DNSName") or "").split(".")[0].lower()}
        for name in names - {""}:
            online = bool(peer.get("Online")) or peer is data.get("Self")
            out[name] = {"online": online, "last_seen": peer.get("LastSeen")}
    return out


def machine_rows(root: Path, tx: dict, peers: dict | None) -> list[dict]:
    rows = []
    for m in declarations(root, "infra/remotes"):
        name = str(m.get("name") or Path(m["_file"]).stem)
        net = m.get("network") if isinstance(m.get("network"), dict) else {}
        ts = str(net.get("tailscale_hostname") or name).lower()
        caps = m.get("capabilities") if isinstance(m.get("capabilities"), list) else []
        always = "arm" in caps
        parts = [str(x) for x in (m.get("type"), m.get("os")) if x]
        tone = "none"
        if peers is None:
            # nothing live says it is up: grey like a machine outside the tailnet, never green
            parts.append(tx["no_tailscale"])
            tone = "dim"
        elif ts in peers:
            p = peers[ts]
            parts.append(tx["online"] if p["online"] else tx["offline"])
            if not p["online"]:
                seen = _short_time(p.get("last_seen"))
                if seen:
                    parts.append(tx["seen"].format(when=seen))
                tone = "bad" if always else "dim"
        else:
            tone = "dim"
        if always:
            parts.append(tx["always_on"])
        online = bool(peers and peers.get(ts, {}).get("online"))
        known = peers is not None and ts in peers
        group = tx["g_always"] if always else tx["g_online"] if online else tx["g_offline"] if known else tx["g_outside"]
        rows.append(row(f"machine:{name}", name, " · ".join(parts), tone, live=known, online=online, always_on=always,
                        group=group, icon=str(m.get("type") or "device"), tags=tags(**{tx["tag_type"]: m.get("type")})))
    rows.sort(key=lambda r: (not r["always_on"], not r["online"], r["title"].lower()))
    return rows


def _short_time(value) -> str | None:
    try:
        t = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if t.year < 2000:
        return None
    return t.astimezone().strftime("%d.%m. %H:%M")


# ---------------------------------------------------------------- workers

def read_source(src: str, run=subprocess.run) -> tuple[dict | None, str | None]:
    """The stamped worker report from a file or `ssh:<host>:<path>`; (data, error)."""
    try:
        if src.startswith("ssh:"):
            _, host, path = src.split(":", 2)
            if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", host) or not path or "\n" in path:
                return None, "bad source"
            # ~/ stays outside the quotes so the remote shell expands it; the rest is quoted
            remote = "cat ~/" + shlex.quote(path[2:]) if path.startswith("~/") else "cat " + shlex.quote(path)
            res = run(["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=4", host, remote],
                      capture_output=True, text=True, timeout=12)
            if res.returncode != 0:
                lines = (res.stderr or "").strip().splitlines()
                return None, lines[-1][:120] if lines else "ssh failed"
            text = res.stdout
        else:
            text = Path(os.path.expanduser(src)).read_text(encoding="utf-8")
        data = json.loads(text)
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return None, str(exc)[:120]
    return (data, None) if isinstance(data, dict) else (None, "not a report")


def worker_counts(report: dict, every: bool = False) -> tuple[int, int, list[dict]]:
    """(in order, declared, problems) from the reconcile findings: one entry per workload, its worst state."""
    worst: dict[str, dict] = {}
    for f in report.get("findings") or []:
        if not isinstance(f, dict) or f.get("state") == "unmanaged" or not f.get("workload_id"):
            continue
        wid, state = f["workload_id"], f.get("state")
        rank = WORKER_RANK.get(state, 50 if state in QUIET_STATES else 40)
        if wid not in worst or rank < worst[wid]["_rank"]:
            worst[wid] = {**f, "_rank": rank}
    problems = sorted((f for f in worst.values() if every or f.get("state") in WORKER_RANK),
                      key=lambda f: (f["_rank"], f["workload_id"]))
    ok = sum(1 for f in worst.values() if f.get("state") in QUIET_STATES)
    # an inventory line without a declaration is listed as a problem, but it is no worker of this host
    total = sum(1 for f in worst.values() if f.get("state") != "inventory_stale")
    return ok, total, problems


def worker_rows(tx: dict, src: str, now: dt.datetime, stale_min: int, run=subprocess.run,
                every: bool = False) -> list[dict]:
    wrapped, err = read_source(src, run)
    if wrapped is None:
        return [row("workers:error", tx["report_missing"].format(src=source_name(src), err=err),
                    "", "bad")]
    report = wrapped.get("report") if isinstance(wrapped.get("report"), dict) else wrapped
    host = str(wrapped.get("host") or "?")
    ok, total, problems = worker_counts(report, every)
    head_parts, stale = report_age(tx, wrapped.get("at"), now, stale_min)
    tone = "warn" if stale else "none"
    title = tx["workers_all_ok"].format(total=total, host=host) if ok == total else tx["workers_ok"].format(ok=ok, total=total, host=host)
    rows = [row(f"workers:{host}", title, " · ".join(head_parts), tone,
                meter={"value": ok, "max": max(total, 1), "unit": None})]
    for f in problems:
        state = f.get("state")
        quiet = state in QUIET_STATES
        label = state_label(tx, state)
        detail = " · ".join(x for x in (label, "" if quiet else str(f.get("detail") or "")[:140]) if x)
        rows.append(row(f"worker:{host}:{f['workload_id']}", f["workload_id"], detail, state_tone(state), group=label, icon="worker"))
    return rows


def view_rows(root: Path, tx: dict, src: str, now: dt.datetime, stale_min: int, run=subprocess.run) -> list[dict]:
    """From the full worker view (`workload view --json`, the data of the host's workloads page): one row per
    run for the mosaic, the summary on top, and the whole document kept in .bridge/resources/workers-view.json
    for the dashboard's Workers tab. A missing or unreadable view is one red row."""
    data, err = read_source(src, run)
    if data is None or not isinstance(data.get("runs"), list):
        return [row("workers:error", tx["report_missing"].format(src=source_name(src),
                                                               err=err or "no runs"), "", "bad")]
    try:
        write_atomic(root / RESOURCES / "workers-view.json", json.dumps(data, ensure_ascii=False))
    except OSError:
        pass
    host = str(data.get("host") or "?")
    runs = [r for r in data["runs"] if isinstance(r, dict) and not r.get("retired")]
    ok = sum(1 for r in runs if r.get("state") in QUIET_STATES)
    head_parts, stale = report_age(tx, data.get("generated_at"), now, stale_min)
    tone = "warn" if stale else "none"
    title = tx["workers_all_ok"].format(total=len(runs), host=host) if ok == len(runs) else \
        tx["workers_ok"].format(ok=ok, total=len(runs), host=host)
    rows = [row(f"workers:{host}", title, " · ".join(head_parts), tone, meter={"value": ok, "max": max(len(runs), 1), "unit": None})]
    def rank(r: dict) -> tuple:
        st = r.get("state")
        return WORKER_RANK.get(st, 50 if st in QUIET_STATES else 40), str(r.get("id"))
    for r in sorted(runs, key=rank):
        state = r.get("state") or "unknown"
        quiet = state in QUIET_STATES
        tone_r = state_tone(state)
        label = state_label(tx, state)
        first = next((f for f in r.get("findings") or [] if isinstance(f, dict)), {})
        detail = " · ".join(x for x in (label, str(r.get("purpose") or ""), "" if quiet else str(first.get("detail") or "")[:140]) if x)
        rows.append(row(f"worker:{host}:{r.get('id')}", str(r.get("title") or r.get("id")), detail, tone_r,
                        group=label, icon="worker"))
    return rows


# ---------------------------------------------------------------- accounts

def verified_on(acc: dict) -> dt.date | None:
    for holder in (acc.get("snapshot"), acc, acc.get("cloud")):
        if isinstance(holder, dict):
            v = holder.get("last_verified") or holder.get("verified_at")
            if isinstance(v, dt.date):
                return v
            if isinstance(v, str):
                try:
                    return dt.date.fromisoformat(v[:10])
                except ValueError:
                    continue
    return None


def resource_counts(acc: dict) -> list[tuple[str, int]]:
    out = []
    for key in RESOURCE_KEYS:
        for holder in (acc, acc.get("cloud") if isinstance(acc.get("cloud"), dict) else {}):
            v = holder.get(key)
            if isinstance(v, (list, dict)) and v:
                out.append((key, len(v)))
                break
    return out


def account_rows(root: Path, tx: dict, today: dt.date) -> list[dict]:
    rows = []
    for acc in declarations(root, "identity/accounts"):
        cloud = acc.get("cloud") if isinstance(acc.get("cloud"), dict) else {}
        tenant = acc.get("tenant") if isinstance(acc.get("tenant"), dict) else {}
        mail = acc.get("mail") if isinstance(acc.get("mail"), dict) else {}
        registrar = acc.get("registrar") if isinstance(acc.get("registrar"), dict) else {}
        provider = (cloud.get("provider") or mail.get("provider") or registrar.get("provider")
                    or Path(acc["_file"]).stem.split("-")[0])
        url = next((u for u in (cloud.get("dashboard_url"), tenant.get("portal_url"), registrar.get("dashboard_url"),
                                acc.get("portal_url"))
                    if isinstance(u, str) and u.startswith("https://")), "")
        parts = [str(provider)]
        if acc.get("owner"):
            parts.append(str(acc["owner"]))
        parts += [f"{n} {tx['res'][k]}" for k, n in resource_counts(acc)]
        when = verified_on(acc)
        parts.append(tx["verified"].format(days=(today - when).days) if when else tx["never_verified"])
        status = str(acc.get("status") or "active")
        label = tx["status"].get(status, status)
        tone = "none"
        if status != "active":
            parts.append(tx["inactive"].format(status=label))
            tone = "dim"
        aid = str(acc.get("id") or Path(acc["_file"]).stem)
        rows.append(row(f"account:{aid}", str(acc.get("display_name") or aid),
                        " · ".join(parts), tone, url=url or None, verified=when.isoformat() if when else None,
                        provider=str(provider), active=status == "active", cloud=bool(cloud or tenant),
                        group=(tx["g_inactive"] if status != "active" else tx["g_cloud"] if (cloud or tenant)
                               else tx["g_mail"] if mail else tx["g_other"]), icon=str(provider),
                        tags=tags(**{tx["tag_provider"]: provider, tx["tag_status"]: label}),
                        account={"id": aid, "status": status}))
    # cloud accounts first (Azure, Cloudflare, AWS, Google Cloud), then mail and the rest, inactive last
    rows.sort(key=lambda r: (not r["active"], not r["cloud"], r["provider"].lower(), r["title"].lower()))
    return rows


# ---------------------------------------------------------------- cloud (what runs, from cloud-inventory.py)

GOOD = {"running", "deployed", "active", "healthy", "success", "present"}
BAD = {"down", "degraded", "failure", "failed"}


def known_names(root: Path | None) -> list[tuple[str, str, str | None]]:
    """What this Bridge knows, to place a provider's service: (text, where, retired date) per file of
    workflow/workloads, infra/channels, infra/remotes and the ecosystem registries. A service is known
    from a file when its name stands in it as a whole word; that may be its declaration or only a use
    of it (a vault a script reads from), so the dashboard says "known from", not "declared in"."""
    if root is None:
        return []
    out = []
    for family in ("workflow/workloads", "infra/channels", "infra/remotes"):
        for d in declarations(root, family):
            text = (root / d["_file"]).read_text(encoding="utf-8", errors="replace")
            retired = d.get("retired") if family == "workflow/workloads" and isinstance(d.get("retired"), dict) else None
            out.append((text, str(d.get("id") or Path(d["_file"]).stem), str(retired.get("at") or "")[:10] if retired else None))
    for reg in sorted(root.glob("ecosystem*.yaml")):
        out.append((reg.read_text(encoding="utf-8", errors="replace"), "", None))
    return out


def declared_in(name: str, known: list) -> tuple[str, str | None] | None:
    if len(name) < 4:
        return None
    pat = re.compile(rf"(?<![A-Za-z0-9_-]){re.escape(name)}(?![A-Za-z0-9_-])")
    hits = [(where, retired) for text, where, retired in known if pat.search(text)]
    # a live declaration wins over a retired one, a declaration over the registry
    hits.sort(key=lambda h: (h[1] is not None, h[0] == ""))
    return hits[0] if hits else None


def cloud_rows(tx: dict, src: str, now: dt.datetime, stale_min: int, run=subprocess.run,
               root: Path | None = None) -> list[dict]:
    data, err = read_source(src, run)
    if data is None or not isinstance(data.get("accounts"), list):
        return [row("cloud:error", tx["cloud_missing"].format(src=source_name(src),
                                                            err=err or "no accounts"), "", "bad")]
    age_parts, stale = report_age(tx, data.get("at"), now, stale_min)
    age_text = " · ".join(age_parts)
    rows = []
    known = known_names(root)
    for acc in data["accounts"]:
        if not isinstance(acc, dict):
            continue
        aid, name = str(acc.get("id")), str(acc.get("display_name") or acc.get("id"))
        if not acc.get("ok"):
            rows.append(row(f"cloud:{aid}", name, " · ".join(x for x in (str(acc.get("provider") or ""),
                            tx["cloud_failed"].format(err=acc.get("error") or "?"), age_text) if x), "bad",
                            group=name, icon="account"))
            continue
        svc = [x for x in acc.get("services") or [] if isinstance(x, dict)]
        apps = [x for x in svc if x.get("kind") in ("function app", "web app")]
        parts = [str(acc.get("provider") or ""), tx["cloud_head"].format(n=sum((acc.get("counts") or {}).values()))]
        up = sum(1 for x in apps if x.get("state") == "running")
        if apps:
            parts.append(tx["cloud_apps"].format(apps=len(apps), up=up, down=len(apps) - up))
        if acc.get("missing"):
            parts.append(tx["cloud_partly"].format(err=", ".join(map(str, acc["missing"]))[:120]))
        parts.append(age_text)
        rows.append(row(f"cloud:{aid}", name, " · ".join(x for x in parts if x), "warn" if stale or acc.get("missing") else "none",
                        group=name, icon="account", account={"id": aid},
                        meter={"value": up, "max": len(apps), "unit": None}
                        if apps else None))
        for x in svc:
            state = str(x.get("state") or "?")
            tone = "none" if state in GOOD else "bad" if state in BAD else "dim" if state in ("stopped", "inactive") else "warn"
            kind = str(x.get("kind") or "")
            kind_label = tx["kinds"].get(kind.lower(), kind)
            state_label = tx["svc_state"].get(state, state)
            hit = declared_in(str(x.get("name") or ""), known) if known else None
            declared = (hit[0] or tx["registry"]) if hit else tx["declared_nowhere"] if known else None
            note = ""
            if hit and hit[1] is not None:      # retired here, still standing there: leftover, not an outage
                tone = "dim"
                note = tx["retired_on"].format(date=dt.date.fromisoformat(hit[1]).strftime("%d.%m.") if hit[1] else "?")
            rows.append(row(f"cloud:{aid}:{kind}:{x.get('name')}", str(x.get("name")),
                            " · ".join(v for v in (kind_label, state_label, note, str(x.get("group") or "")) if v),
                            tone, url=x.get("url") if isinstance(x.get("url"), str) and x["url"].startswith("https://") else None,
                            group=name, icon=kind or "service",
                            tags=tags(**{tx["tag_kind"]: kind_label, tx["tag_state"]: state_label,
                                         tx["tag_group"]: x.get("group"), tx["tag_location"]: x.get("location"),
                                         tx["tag_declared"]: declared})))
    return rows


# ---------------------------------------------------------------- costs (what the accounts cost, from cloud-costs.py)

CURRENCY_SIGN = {"EUR": "€", "USD": "$", "GBP": "£", "CHF": "CHF"}


def money(tx: dict, amount, currency: str | None = "EUR", whole: bool = False) -> str:
    """An amount the way the page's language writes it: '€1.23' in English, '1,23 €' in German; `whole`
    drops the cents of a round number (a budget of 50 reads '€50')."""
    value = float(amount or 0)
    text = f"{value:,.0f}" if whole and value == int(value) else f"{value:,.2f}"
    sign = CURRENCY_SIGN.get(str(currency or "EUR").upper(), str(currency or "").upper())
    if tx is TX["de"]:
        return text.replace(",", "\0").replace(".", ",").replace("\0", ".") + f" {sign}"
    return f"{sign}{text}" if len(sign) == 1 else f"{text} {sign}"


def login_command(argv: list, src: str) -> str:
    """What the person runs to sign in again: the collector's argv as is on this machine, and for a report read
    over ssh the same on that host (`ssh -t host '...'`), where `az login` asks for a device code because the
    host has no browser to open."""
    args = [str(a) for a in argv]
    if not src.startswith("ssh:"):
        return shlex.join(args)
    if args[:2] == ["az", "login"] and "--use-device-code" not in args:
        args.append("--use-device-code")
    return f"ssh -t {source_name(src)} {shlex.quote(shlex.join(args))}"


def _amount_on(acc: dict, day: str) -> float:
    return sum(float(d.get("amount") or 0) for d in acc.get("days") or [] if isinstance(d, dict) and d.get("day") == day)


def _age(data: dict, now: dt.datetime, stale_h: float) -> tuple[bool, float | None]:
    """(stale, age in hours) of a report by its `at`; a report without a readable time is stale."""
    try:
        at = dt.datetime.fromisoformat(str(data.get("at")))
    except ValueError:
        return True, None
    if not at.tzinfo:
        return False, None
    age_h = (now - at).total_seconds() / 3600
    return age_h > stale_h, age_h


def _merge_costs(reports: list[tuple[str, dict]], now: dt.datetime, stale_h: float) -> list[tuple[str, dict, bool, float | None]]:
    """(source, account, stale, age) per account id over the reports of several machines: a good answer wins over a
    failed one, then the newer report, so a collector that cannot reach an account never hides one that could."""
    best: dict[str, tuple] = {}
    for src, data in reports:
        stale, age_h = _age(data, now, stale_h)
        for acc in data["accounts"]:
            if not isinstance(acc, dict):
                continue
            acc = {**acc, "host": acc.get("host") or data.get("host"), "measured_at": data.get("at")}
            key = str(acc.get("id"))
            rank = (bool(acc.get("ok")), str(data.get("at") or ""))
            if key not in best or rank > best[key][0]:
                best[key] = (rank, src, acc, stale, age_h)
    return [(src, acc, stale, age_h) for _rank, src, acc, stale, age_h in best.values()]


def cost_centers(root: Path | None) -> list[dict]:
    """workflow/cost-centers/*.yaml in file-name order (the `_` files are not ones): a project that gathers cost
    entries across accounts. `sources` are entry ids or patterns (`openai-x/proj_*`); an account id names its parts
    too. A file that cannot be read is left out, never fatal to the cost card."""
    if root is None:
        return []
    out = []
    for path in sorted((root / "workflow" / "cost-centers").glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError):
            continue
        if isinstance(data, dict) and data.get("id") and isinstance(data.get("sources"), list):
            out.append(data)
    return out


def center_view(center: dict, root: Path, rates: dict) -> dict:
    """What the cost card needs of a cost center: id, title, persona (and its name from identity/personas/), and a
    budget_month converted to EUR with the report's rates (kept as declared, with budget_fx_missing, without one)."""
    out = {"id": str(center["id"]), "title": str(center.get("title") or center["id"]), "persona_ref": center.get("persona_ref")}
    ref = center.get("persona_ref")
    if ref:
        try:
            persona = yaml.safe_load((root / "identity" / "personas" / f"{ref}.yaml").read_text(encoding="utf-8"))
            if isinstance(persona, dict) and persona.get("display_name"):
                out["persona_title"] = str(persona["display_name"])
        except (OSError, yaml.YAMLError):
            pass
    budget = center.get("budget_month")
    if isinstance(budget, (int, float)) and not isinstance(budget, bool) and budget > 0:
        cur = str(center.get("currency") or "EUR").upper()
        rate = 1.0 if cur == "EUR" else rates.get(cur)
        out["budget_month"] = round(float(budget) / rate, 2) if rate else float(budget)
        out["budget_currency"] = cur
        if not rate:
            out["budget_fx_missing"] = True
    return out


def cost_center_of(entry_id: str, centers: list[dict]) -> dict | None:
    """The first cost center whose sources name this entry, or its account (the id before the first `/`)."""
    account = entry_id.split("/", 1)[0]
    for center in centers:
        for pattern in center.get("sources") or []:
            if fnmatch.fnmatchcase(entry_id, str(pattern)) or fnmatch.fnmatchcase(account, str(pattern)):
                return center
    return None


def cost_rows(root: Path | None, tx: dict, srcs: str | list[str], now: dt.datetime, stale_h: float,
              run=subprocess.run) -> list[dict]:
    """One row per account of the cost reports: yesterday, the month so far and the budget, red over the budget,
    amber when the forecast passes it or its report is old. An account that could not sign in asks for it, with
    the command to run on the machine that measures it. Several sources (one collector per machine whose CLI
    logins it uses) merge by account. The merged report is kept in .bridge/resources/costs-view.json for the
    cost card, with where it came from, when it was read and whether it is stale. No report at all is one red
    row; a missing one next to others is an amber row."""
    srcs = [srcs] if isinstance(srcs, str) else list(srcs)
    reports, missing = [], []
    for src in srcs:
        data, err = read_source(src, run)
        if data is None or not isinstance(data.get("accounts"), list):
            missing.append((src, err or "no accounts"))
        else:
            reports.append((src, data))
    rows = [row("costs:error" + ("" if i == 0 else f":{i}"),
                tx["costs_missing"].format(src=source_name(src), err=err), "", "warn" if reports else "bad")
            for i, (src, err) in enumerate(missing)]
    if not reports:
        return rows
    newest = max(reports, key=lambda r: str(r[1].get("at") or ""))[1]
    any_stale = any(_age(d, now, stale_h)[0] for _s, d in reports)
    try:
        today = max(dt.date.fromisoformat(str(d.get("today"))) for _s, d in reports)
    except ValueError:
        today = now.date()
    data = newest
    yesterday = (today - dt.timedelta(days=1)).isoformat()
    month = tx["months"][today.month - 1]
    centers = cost_centers(root)
    kept = []
    for src, acc, stale, age_h in _merge_costs(reports, now, stale_h):
        aid, name = str(acc.get("id")), str(acc.get("display_name") or acc.get("id"))
        provider = str(acc.get("provider") or "")
        center = cost_center_of(aid, centers)
        acc["cost_center"] = str(center["id"]) if center else None
        extra = {"group": name, "icon": provider or "account", "account": {"id": aid},
                 "tags": tags(**{tx["tag_provider"]: provider,
                                 tx["tag_project"]: (center.get("title") or center["id"]) if center else None})}
        login = acc.get("login") if isinstance(acc.get("login"), dict) else {}
        if not acc.get("ok") and acc.get("error_kind") == "auth" and isinstance(login.get("argv"), list) and login["argv"]:
            cmd = login_command(login["argv"], src)
            acc["login_command"] = cmd
            hint = str(login.get("hint") or acc.get("error") or "")
            rows.append(row(f"costs:{aid}", tx["costs_login"].format(name=name, hint=hint), cmd, "warn",
                            action="copy", copy=cmd, **extra))
        elif not acc.get("ok"):
            rows.append(row(f"costs:{aid}", name, str(acc.get("error") or "?")[:200], "warn", **extra))
        else:
            cur = acc.get("currency") or data.get("currency") or "EUR"
            mtd, forecast, budget = acc.get("month_to_date"), acc.get("forecast_month"), acc.get("budget_month")
            budget = float(budget) if isinstance(budget, (int, float)) and not isinstance(budget, bool) and budget > 0 else None
            so_far = money(tx, mtd, cur)
            if budget is not None:
                so_far = tx["costs_of"].format(amount=so_far, budget=money(tx, budget, cur, whole=True))
            parts = [tx["costs_yesterday"].format(amount=money(tx, _amount_on(acc, yesterday), cur)),
                     tx["costs_month"].format(month=month, amount=so_far)]
            if acc.get("credits_month"):
                parts.append(tx["costs_credits"].format(used=money(tx, acc.get("used_month"), cur),
                                                        credits=money(tx, acc["credits_month"], cur)))
            if stale and age_h is not None:
                parts.append(tx["costs_old"].format(h=int(age_h)))
            over = budget is not None and isinstance(mtd, (int, float)) and mtd > budget
            ahead = budget is not None and isinstance(forecast, (int, float)) and forecast > budget
            tone = "bad" if over else "warn" if ahead or stale else "none"
            meter = {"value": float(mtd), "max": budget, "unit": CURRENCY_SIGN.get(str(cur).upper(), str(cur))[:8]} \
                if budget is not None and isinstance(mtd, (int, float)) and mtd >= 0 else None
            rows.append(row(f"costs:{aid}", name, " · ".join(parts), tone, meter=meter, **extra))
        kept.append(acc)
    if root is not None:
        view = {**data, "accounts": kept, "today": today.isoformat(),
                "cost_centers": [center_view(c, root, (data.get("fx") or {}).get("rates") or {}) for c in centers],
                "source": ", ".join(source_name(s) for s, _d in reports),
                "sources": [{"source": source_name(s), "host": d.get("host"), "at": d.get("at"),
                             "stale": _age(d, now, stale_h)[0]} for s, d in reports],
                "read_at": now.isoformat(timespec="seconds"), "stale": any_stale}
        try:
            write_atomic(root / RESOURCES / "costs-view.json", json.dumps(view, ensure_ascii=False))
        except OSError:
            pass
    return rows


# ---------------------------------------------------------------- overview

def overview_rows(root: Path, tx: dict, today: dt.date, now: dt.datetime, src: str | None, stale_min: int,
                  peers: dict | None) -> list[dict]:
    rows = []
    if src:
        wrapped, _ = read_source(src)
        if wrapped is not None:
            report = wrapped.get("report") if isinstance(wrapped.get("report"), dict) else wrapped
            ok, total, _ = worker_counts(report)
            rows.append(row("overview:workers", tx["ov_workers"], str(wrapped.get("host") or ""),
                            meter={"value": ok, "max": max(total, 1), "unit": None}))
    machines = machine_rows(root, tx, peers)
    always = [m for m in machines if m["always_on"]]
    if peers is not None and machines:
        online = sum(1 for m in machines if m["online"])
        base = always or machines
        rows.append(row("overview:machines", tx["ov_machines"] if always else tx["ov_machines_any"],
                        tx["ov_machines_all"].format(n=online, total=len(machines)),
                        meter={"value": sum(1 for m in base if m["online"]), "max": len(base), "unit": None}))
    accounts = [a for a in account_rows(root, tx, today) if a["active"]]
    fresh = sum(1 for a in accounts if a.get("verified") and (today - dt.date.fromisoformat(a["verified"])).days <= STALE_DAYS)
    if fresh:   # where nobody checks accounts against the real thing, a gauge at zero says nothing
        rows.append(row("overview:accounts", tx["ov_accounts"].format(days=STALE_DAYS),
                        tx["ov_accounts_detail"].format(n=fresh, total=len(accounts)),
                        meter={"value": fresh, "max": len(accounts), "unit": None}))
    return rows


# ---------------------------------------------------------------- stamp (runs on the host)

def stamp(path: Path, host: str, now: str, out: Path) -> int:
    """Wrap a `workload reconcile --json` report with its host and time, written atomically."""
    text = path.read_text(encoding="utf-8")
    report, _ = json.JSONDecoder().raw_decode(text.lstrip())     # tolerate a line after the JSON
    if not isinstance(report, dict) or "findings" not in report:
        print("stamp: not a reconcile report", file=sys.stderr)
        return 2
    write_atomic(out, json.dumps({"schema": 1, "host": host, "at": now, "report": report}, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------- set-status (the one write)

STATUS_LINE_RE = re.compile(r"^status:[ \t]*(?P<value>[^#\n]*?)[ \t]*(?:#[ \t]*(?P<note>.*))?$", re.M)


def account_file(root: Path, aid: str) -> Path | None:
    """The account file by its name or its `id:`, never a `_` file."""
    if not ID_RE.match(aid):
        return None
    folder = root / "identity" / "accounts"
    direct = folder / f"{aid}.yaml"
    if direct.is_file():
        return direct
    return next((Path(folder / Path(a["_file"]).name) for a in declarations(root, "identity/accounts")
                 if str(a.get("id")) == aid), None)


def set_status(root: Path, aid: str, status: str, today: dt.date) -> int:
    """Rewrite the top-level `status:` line of one account file (or add one after `id:`), keeping every
    other byte; the old value and its note stay in the line's comment. Checked by parsing it again."""
    if status not in ACCOUNT_STATUSES:
        print(f"set-status: status must be one of {', '.join(ACCOUNT_STATUSES)}", file=sys.stderr)
        return 2
    path = account_file(root, aid)
    if path is None:
        print(f"set-status: no account {aid}", file=sys.stderr)
        return 2
    text = path.read_text(encoding="utf-8")
    m = STATUS_LINE_RE.search(text)
    old = (m.group("value").strip() if m else "") or "active"
    if old == status:
        print(f"{aid}: already {status}")
        return 0
    note = f"# {today.isoformat()} set in the dashboard, was {old}"
    if m and m.group("note"):
        note += f": {m.group('note').strip()}"
    line = f"status: {status}    {note}"
    if m:
        new = text[:m.start()] + line + text[m.end():]
    else:
        idm = re.search(r"^id:.*$", text, re.M)
        at = idm.end() + 1 if idm else 0
        new = text[:at] + line + "\n" + text[at:]
    try:
        data = yaml.safe_load(new)
    except yaml.YAMLError:
        data = None
    if not isinstance(data, dict) or data.get("status") != status:
        print(f"set-status: {path.name} would not parse back to status {status}, left unchanged", file=sys.stderr)
        return 1
    write_atomic(path, new)
    print(f"{aid}: {old} -> {status}")
    return 0


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--root", type=Path, default=ROOT)
    sub = ap.add_subparsers(dest="what", required=True)
    ov = sub.add_parser("overview")
    ov.add_argument("--workloads")
    ov.add_argument("--stale-min", type=int, default=70)
    sub.add_parser("machines")
    wl = sub.add_parser("workloads")
    wl.add_argument("--source", required=True)
    wl.add_argument("--stale-min", type=int, default=70)
    wl.add_argument("--all", action="store_true", help="every worker, also those in order (for a mosaic)")
    wv = sub.add_parser("workers")
    wv.add_argument("--source", required=True)
    wv.add_argument("--stale-min", type=int, default=70)
    sub.add_parser("accounts")
    cl = sub.add_parser("cloud")
    cl.add_argument("--source", required=True)
    cl.add_argument("--stale-min", type=int, default=150)
    co = sub.add_parser("costs")
    co.add_argument("--source", required=True, action="append",
                    help="a collector's report; repeat it for one collector per machine")
    co.add_argument("--stale-h", type=float, default=36, help="hours after which the report counts as old")
    co.add_argument("--stale-min", type=int, help="the same in minutes, like the other listings")
    st = sub.add_parser("stamp")
    st.add_argument("file", type=Path)
    st.add_argument("--host", required=True)
    st.add_argument("--now", required=True)
    st.add_argument("--out", type=Path, required=True)
    ss = sub.add_parser("set-status")
    ss.add_argument("id")
    ss.add_argument("status", choices=ACCOUNT_STATUSES)
    args = ap.parse_args(argv)
    if args.what == "stamp":
        return stamp(args.file, args.host, args.now, args.out.expanduser())
    if args.what == "set-status":
        return set_status(args.root.resolve(), args.id, args.status, dt.date.today())
    root = args.root.resolve()
    tx = TX[language(root)]
    now = dt.datetime.now().astimezone()
    today = now.date()
    if args.what == "machines":
        rows = machine_rows(root, tx, tailscale_peers())
    elif args.what == "workloads":
        rows = worker_rows(tx, args.source, now, args.stale_min, every=args.all)
    elif args.what == "workers":
        rows = view_rows(root, tx, args.source, now, args.stale_min)
    elif args.what == "accounts":
        rows = account_rows(root, tx, today)
    elif args.what == "cloud":
        rows = cloud_rows(tx, args.source, now, args.stale_min, root=root)
    elif args.what == "costs":
        stale_h = args.stale_min / 60 if args.stale_min is not None else args.stale_h
        rows = cost_rows(root, tx, args.source, now, stale_h)
    else:
        rows = overview_rows(root, tx, today, now, args.workloads, args.stale_min, tailscale_peers())
    keep(root, args.what, rows)
    json.dump(rows, sys.stdout, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
