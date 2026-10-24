#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""What the cloud accounts and fixed contracts cost per day, read only, for the cockpit's overview page.

    cloud-costs.py --host H --out FILE [--root R] [--days 35] [--today YYYY-MM-DD] [--inbox]

Runs on the always-on machine, once a day (a workload). Asks only the accounts in
identity/accounts/*.yaml that opt in with

    costs:
      enabled: true
      provider: azure                 # optional, else cloud.provider, the azure shape or the id prefix
      subscriptions: [<id>]           # azure, default every id under `subscriptions:`
      group_by: service               # azure: service | resource_group | tag:<name>
      profile: <name>                 # aws CLI profile
      key_ref: keychain://<service>/<account>     # openai, anthropic: an ADMIN key, in any declared store
      bigquery_table: <project.dataset.table>     # gcp: the Cloud Billing export
      budget_month: 50                # optional, in `currency`
      currency: EUR                   # optional, the currency of budget_month (contracts: pricing.currency)
      login: [argv...]                # optional, overrides the login command below

plus the contracts in identity/contracts/*.yaml with `costs: {enabled: true}`, spread evenly over the
days. Writes one stamped JSON file ({schema, kind, host, at, currency, days, today, fx, accounts})
atomically, which scripts/bridge-resources.py turns into rows (`costs --source`).

Logins: azure, aws and gcp use only their CLIs (az, aws, bq) and the login those hold; openai and
anthropic read an admin key through the secrets skill (skills/secrets), only to make the call, never
stored or printed. A failure says why in its entry and is classified: `auth` (not logged in, expired, no key:
the entry carries the command to run in `login`), `access` (logged in, a permission missing) or
`error`. One failing account never stops the others. Amounts are converted to EUR with the ECB's
daily reference rates; without them an account keeps its own currency and says `fx_missing`.
Guide: docs/cloud-costs.md.
"""
from __future__ import annotations

import argparse
import calendar
import importlib.util
import datetime as dt
import json
import os
import re
import shlex
import subprocess
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

import yaml

ROOT = Path(__file__).resolve().parents[1]
TIMEOUT = 60
ECB_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-daily.xml"
AZURE_API = "https://management.azure.com/subscriptions/{sub}/providers/Microsoft.CostManagement/query?api-version=2023-11-01"
OPENAI_API = "https://api.openai.com/v1/organization/costs"
ANTHROPIC_API = "https://api.anthropic.com/v1/organizations/cost_report"
MAX_GROUPS = 8          # per day, the smallest beyond seven summed into "other"
PROVISIONAL_DAYS = 2    # today and yesterday: providers settle late


class CostError(RuntimeError):
    """A failure that knows its kind: `auth` (log in or store a key) or `access` (a permission is missing)."""

    def __init__(self, message: str, kind: str = "error", replace: bool = False):
        super().__init__(message)
        self.kind = kind
        self.replace = replace      # a key is stored but wrong: storing a new one must replace it


def _load(path: Path) -> dict | None:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError):
        return None
    return data if isinstance(data, dict) else None


def _opted_in(folder: Path, host: str | None = None) -> list[dict]:
    """Every active entry with costs.enabled; with a host, only those whose costs.host is that machine or unset
    (several collectors on several machines each ask the accounts whose login lives there)."""
    out = []
    for path in sorted(folder.glob("*.yaml")):
        if path.name.startswith("_"):
            continue
        data = _load(path)
        costs = data.get("costs") if data else None
        # anything but active (paused, disabled, cancelled) is not asked
        if isinstance(costs, dict) and costs.get("enabled") is True and str(data.get("status") or "active") == "active":
            there = costs.get("host")
            if host is None or not isinstance(there, str) or not there.strip() or there.strip().lower() == host.lower():
                out.append(data)
    return out


def accounts(root: Path, host: str | None = None) -> list[dict]:
    return _opted_in(root / "identity" / "accounts", host)


def contracts(root: Path, host: str | None = None) -> list[dict]:
    return _opted_in(root / "identity" / "contracts", host)


def _costs(acc: dict) -> dict:
    return acc.get("costs") if isinstance(acc.get("costs"), dict) else {}


def provider_of(acc: dict) -> str:
    """costs.provider, else as scripts/cloud-inventory.py: cloud.provider, the azure shape, the id prefix."""
    if _costs(acc).get("provider"):
        return str(_costs(acc)["provider"])
    cloud = acc.get("cloud") if isinstance(acc.get("cloud"), dict) else {}
    if cloud.get("provider"):
        return str(cloud["provider"])
    if isinstance(acc.get("tenant"), dict) or isinstance(acc.get("subscriptions"), list):
        return "azure"
    return str(acc.get("id", "")).split("-")[0]


def window(days: int, today: dt.date) -> tuple[dt.date, dt.date]:
    return today - dt.timedelta(days=max(days, 1) - 1), today


def _row(day: str, amount: float, currency: str, group: str | None) -> dict:
    return {"day": day, "amount": float(amount), "currency": (currency or "USD").upper(),
            "groups": {group or "other": float(amount)}}


def merge_rows(rows: list[dict]) -> dict:
    """Rows of one account (several per day: per group, per subscription) summed per day."""
    out: dict = {}
    for r in rows:
        d = out.setdefault(r["day"], {"amount": 0.0, "currency": r.get("currency") or "USD", "groups": {}})
        d["amount"] += float(r.get("amount") or 0)
        for g, v in (r.get("groups") or {}).items():
            d["groups"][g] = d["groups"].get(g, 0.0) + float(v or 0)
    return out


def _last_line(res) -> str:
    return ((res.stderr or res.stdout or "").strip().splitlines() or ["failed"])[-1][:200]


def _cli(argv: list[str], run: Callable, classify: Callable[[str], CostError | None]) -> Any:
    try:
        res = run(argv, capture_output=True, text=True, timeout=TIMEOUT)
    except FileNotFoundError:
        raise CostError(f"{argv[0]} is not installed on this machine")
    if res.returncode != 0:
        text = (res.stderr or "") + "\n" + (res.stdout or "")
        raise classify(text) or CostError(_last_line(res))
    return json.loads(res.stdout or "null")


# ---------------------------------------------------------------- azure

AZURE_AUTH = re.compile(r"az login|AADSTS|expired|No subscription found", re.I)
AZURE_DENIED = re.compile(r"AuthorizationFailed|does not have authori[sz]ation|Forbidden|\b403\b", re.I)
AZURE_THROTTLED = re.compile(r"\b429\b|Too Many Requests", re.I)


def azure_grouping(group_by: str) -> list[dict]:
    if group_by.startswith("tag:"):
        return [{"type": "TagKey", "name": group_by[4:]}]
    name = {"resource_group": "ResourceGroupName"}.get(group_by, "ServiceName")
    return [{"type": "Dimension", "name": name}]


def azure_subscriptions(acc: dict) -> list[str]:
    subs = _costs(acc).get("subscriptions")
    if not subs:
        subs = [s.get("id") if isinstance(s, dict) else s for s in (acc.get("subscriptions") or [])]
    return [str(s) for s in subs if s]


def azure(acc: dict, days: int, today: dt.date, run: Callable = subprocess.run, opener: Callable | None = None,
          sleep: Callable = time.sleep) -> list[dict]:
    subs = azure_subscriptions(acc)
    if not subs:
        raise CostError("no subscriptions declared (costs.subscriptions or subscriptions:)")
    start, end = window(days, today)
    group_by = str(_costs(acc).get("group_by") or "service")
    body = json.dumps({"type": "ActualCost", "timeframe": "Custom",
                       "timePeriod": {"from": f"{start}T00:00:00Z", "to": f"{end}T23:59:59Z"},
                       "dataset": {"granularity": "Daily", "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}},
                                   "grouping": azure_grouping(group_by)}})
    rows: list[dict] = []
    for sub in subs:
        def classify(text: str, sub=sub) -> CostError | None:
            if AZURE_AUTH.search(text):
                return CostError("the az CLI is not logged in (or its login expired)", "auth")
            if AZURE_DENIED.search(text):
                return CostError(f"needs the Cost Management Reader role on subscription {sub}", "access")
            return None
        url, pages = AZURE_API.format(sub=sub), 0
        while url and pages < 20:
            argv = ["az", "rest", "--method", "post", "--url", url, "--body", body, "--output", "json"]
            try:
                data = _cli(argv, run, lambda t: CostError("throttled", "throttled") if AZURE_THROTTLED.search(t) else classify(t))
            except CostError as e:
                if e.kind != "throttled":
                    raise
                sleep(10)       # the Cost Management API throttles per scope; once, then give up
                data = _cli(argv, run, classify)
            props = (data or {}).get("properties") or {}
            cols = [str(c.get("name")) for c in props.get("columns") or []]
            idx = {c: i for i, c in enumerate(cols)}
            cost_i = idx.get("Cost", idx.get("PreTaxCost", idx.get("CostUSD")))
            group_i = idx.get("TagValue") if group_by.startswith("tag:") else idx.get(
                "ResourceGroupName" if group_by == "resource_group" else "ServiceName")
            if cost_i is None or "UsageDate" not in idx:
                if props.get("rows"):
                    raise CostError("unexpected answer from Cost Management (no Cost or UsageDate column)")
            else:
                for r in props.get("rows") or []:
                    d = str(r[idx["UsageDate"]])
                    day = f"{d[:4]}-{d[4:6]}-{d[6:8]}"
                    group = r[group_i] if group_i is not None else None
                    if group_by.startswith("tag:") and not group:
                        group = "(untagged)"
                    cur = r[idx["Currency"]] if "Currency" in idx else "EUR"
                    rows.append(_row(day, float(r[cost_i] or 0), cur, str(group) if group else None))
            url, pages = props.get("nextLink"), pages + 1
    return rows


# ---------------------------------------------------------------- aws

AWS_AUTH = re.compile(r"Unable to locate credentials|ExpiredToken|SSO|login", re.I)
AWS_DENIED = re.compile(r"AccessDenied|not authorized", re.I)


def aws(acc: dict, days: int, today: dt.date, run: Callable = subprocess.run, opener: Callable | None = None) -> list[dict]:
    start, end = window(days, today)
    profile = _costs(acc).get("profile")

    def classify(text: str) -> CostError | None:
        if AWS_DENIED.search(text):
            return CostError("needs ce:GetCostAndUsage for this identity", "access")
        if AWS_AUTH.search(text):
            return CostError("the aws CLI has no valid login", "auth")
        return None
    rows, token, pages = [], None, 0
    while pages < 20:
        argv = ["aws", "ce", "get-cost-and-usage", "--time-period", f"Start={start},End={end + dt.timedelta(days=1)}",
                "--granularity", "DAILY", "--metrics", "UnblendedCost",
                "--group-by", "Type=DIMENSION,Key=SERVICE", "--output", "json"]
        if profile:
            argv += ["--profile", str(profile)]
        if token:
            argv += ["--next-page-token", token]
        data = _cli(argv, run, classify) or {}
        for period in data.get("ResultsByTime") or []:
            day = (period.get("TimePeriod") or {}).get("Start")
            for g in period.get("Groups") or []:
                m = (g.get("Metrics") or {}).get("UnblendedCost") or {}
                amount = float(m.get("Amount") or 0)
                if day and amount:
                    rows.append(_row(day, amount, m.get("Unit") or "USD", (g.get("Keys") or [None])[0]))
        token, pages = data.get("NextPageToken"), pages + 1
        if not token:
            break
    return rows


# ---------------------------------------------------------------- openai, anthropic

SECRETS = ROOT / "skills" / "secrets"


def _secrets_engine():
    """The CORE secrets skill's engine, loaded under its own name so it cannot clash with another `engine`."""
    name = "bridge_secrets_engine"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, SECRETS / "engine" / "__init__.py",
                                                      submodule_search_locations=[str(SECRETS / "engine")])
        if spec is None or spec.loader is None:
            raise CostError(f"the secrets skill is missing ({SECRETS})", "access")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return importlib.import_module(name + ".resolve"), importlib.import_module(name + ".errors"), \
        importlib.import_module(name + ".exec")


def read_key(ref: Any, run: Callable = subprocess.run, root: Path = ROOT) -> str:
    """The admin key behind `costs.key_ref`, read the way the secrets skill reads it (so every declared store
    works and the keychain is read with `-g`, not the ambiguous `-w`). Only for the call, never kept."""
    if not isinstance(ref, str) or "://" not in ref:
        raise CostError("no costs.key_ref (a secret reference, e.g. keychain://<service>/<account>)", "auth")
    resolve, errors, exec_mod = _secrets_engine()
    runner = None
    if run is not subprocess.run:
        # an injected runner (tests, a wrapper) answers the backend's argv in subprocess.run's shape
        def runner(argv, invocation=None):
            res = run(list(argv), capture_output=True, text=True, timeout=invocation.timeout_sec if invocation else 30)
            return exec_mod.Completed(rc=res.returncode, stdout=res.stdout or "", stderr=res.stderr or "", argv=tuple(argv))
    resolver = resolve.Resolver(resolve.Options(root=str(root)), runner=runner)
    try:
        if runner is not None:
            resolver.backend_for_ref(ref).assume_available = True
        reading = resolver.read(ref)
    except errors.ReferenceError_ as e:
        raise CostError(f"costs.key_ref is not a secret reference: {e}", "auth")
    except errors.SecretMissing:
        raise CostError(f"no key stored under {ref}", "auth")
    except errors.SecretsError as e:
        # the store is there but this machine or session cannot read it (no keychain on Linux, ssh, a vault
        # role): storing the key again would not help, so this is not a login
        raise CostError(f"cannot read {ref} here: {e}" + (f" ({e.hint})" if e.hint else ""), "access")
    if not reading.present or reading.secret is None:
        raise CostError(f"no key stored under {ref}", "auth")
    return reading.secret.expose_text().strip()


def http_json(url: str, headers: dict, opener: Callable) -> Any:
    req = urllib.request.Request(url, headers={**headers, "Accept": "application/json"})
    where = url.split("?")[0]
    try:
        with opener(req, timeout=TIMEOUT) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 401:
            raise CostError(f"{where}: HTTP 401, the key was refused", "auth", replace=True)
        if e.code == 403:
            raise CostError(f"{where}: HTTP 403, the key may not read costs", "access")
        raise CostError(f"{where}: HTTP {e.code}")
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise CostError(f"{where}: {e}")


def _paged(url: str, headers: dict, opener: Callable, cap: int = 20) -> list:
    out, page = [], None
    for _ in range(cap):
        body = http_json(url + (f"&page={urllib.parse.quote(str(page))}" if page else ""), headers, opener) or {}
        out += body.get("data") or []
        page = body.get("next_page")
        if not body.get("has_more") or not page:
            break
    return out


def openai(acc: dict, days: int, today: dt.date, run: Callable = subprocess.run,
           opener: Callable = urllib.request.urlopen, root: Path = ROOT) -> list[dict]:
    key = read_key(_costs(acc).get("key_ref"), run, root)
    if not key.startswith("sk-admin-"):
        raise CostError("needs an admin key (sk-admin-...)", "auth", replace=True)
    start, _ = window(days, today)
    since = int(dt.datetime.combine(start, dt.time(), dt.timezone.utc).timestamp())
    url = f"{OPENAI_API}?start_time={since}&bucket_width=1d&limit={min(days, 180)}&group_by=line_item"
    rows = []
    for bucket in _paged(url, {"Authorization": f"Bearer {key}"}, opener):
        day = dt.datetime.fromtimestamp(int(bucket.get("start_time") or 0), dt.timezone.utc).date().isoformat()
        for r in bucket.get("results") or []:
            amount = r.get("amount") or {}
            if float(amount.get("value") or 0):
                rows.append(_row(day, float(amount["value"]), amount.get("currency") or "usd", r.get("line_item")))
    return rows


def anthropic(acc: dict, days: int, today: dt.date, run: Callable = subprocess.run,
              opener: Callable = urllib.request.urlopen, root: Path = ROOT) -> list[dict]:
    key = read_key(_costs(acc).get("key_ref"), run, root)
    if not key.startswith("sk-ant-admin"):
        raise CostError("needs an Admin API key (sk-ant-admin...)", "auth", replace=True)
    start, end = window(days, today)
    query = urllib.parse.urlencode([("starting_at", f"{start}T00:00:00Z"),
                                    ("ending_at", f"{end + dt.timedelta(days=1)}T00:00:00Z"),
                                    ("bucket_width", "1d"), ("group_by[]", "description"), ("limit", 31)], safe=":")
    rows = []
    for bucket in _paged(f"{ANTHROPIC_API}?{query}", {"x-api-key": key, "anthropic-version": "2023-06-01"}, opener):
        day = str(bucket.get("starting_at") or "")[:10]
        for r in bucket.get("results") or []:
            cents = float(r.get("amount") or 0)          # a decimal string, in cents
            if day and cents:
                rows.append(_row(day, cents / 100, r.get("currency") or "USD", r.get("description")))
    return rows


# ---------------------------------------------------------------- gcp, cloudflare

GCP_AUTH = re.compile(r"gcloud auth|Reauthentication|invalid_grant", re.I)
GCP_DENIED = re.compile(r"Access Denied|permission|403", re.I)
BQ_TABLE = re.compile(r"^[A-Za-z0-9_.:-]+$")
BQ_MAX_ROWS = 100000    # days x services, far above any real window


def gcp(acc: dict, days: int, today: dt.date, run: Callable = subprocess.run, opener: Callable | None = None) -> list[dict]:
    table = _costs(acc).get("bigquery_table")
    if not table:
        raise CostError("needs a Cloud Billing export to BigQuery (costs.bigquery_table)")
    if not BQ_TABLE.match(str(table)):
        raise CostError("costs.bigquery_table must look like project.dataset.table")
    start, end = window(days, today)
    sql = (f"SELECT CAST(DATE(usage_start_time) AS STRING) AS day, service.description AS service, "
           f"SUM(cost) + SUM(IFNULL((SELECT SUM(c.amount) FROM UNNEST(credits) c), 0)) AS cost, ANY_VALUE(currency) AS currency "
           f"FROM `{table}` WHERE DATE(usage_start_time) BETWEEN '{start}' AND '{end}' GROUP BY day, service "
           f"ORDER BY day, service")

    def classify(text: str) -> CostError | None:
        if GCP_AUTH.search(text):
            return CostError("the gcloud login is missing or expired", "auth")
        if GCP_DENIED.search(text):
            return CostError(f"needs read access (BigQuery Data Viewer + Job User) on {table}", "access")
        return None
    rows = []
    # bq prints 100 rows unless told otherwise, and says nothing about the rest: one row per day and service
    answer = _cli(["bq", "query", "--use_legacy_sql=false", "--format=json", f"--max_rows={BQ_MAX_ROWS}", sql], run, classify)
    if not isinstance(answer, list):
        raise CostError("unexpected answer from gcp (bq did not return rows)")
    for r in answer:
        if float(r.get("cost") or 0):
            rows.append(_row(str(r.get("day")), float(r["cost"]), r.get("currency") or "USD", r.get("service")))
    return rows


def cloudflare(acc: dict, days: int, today: dt.date, run: Callable | None = None, opener: Callable | None = None) -> list[dict]:
    raise CostError("Cloudflare has no daily cost API; declare the plan as a contract with costs.enabled")


ADAPTERS = {"azure": azure, "aws": aws, "openai": openai, "anthropic": anthropic, "gcp": gcp, "cloudflare": cloudflare}
GROUPING = {"openai": "line_item", "anthropic": "description", "gcp": "service", "cloudflare": None}


# ---------------------------------------------------------------- what to run when a login is missing

def login_argv(acc: dict, provider: str, root: Path = ROOT, replace: bool = False) -> list[str]:
    """What to run to sign in. A key is stored through this Bridge's own secrets skill, named by absolute path
    and with --root, so the command works from any directory and over ssh on the collecting machine;
    `replace` when a (wrong or refused) key is already stored under the reference."""
    own = _costs(acc).get("login")
    if isinstance(own, list) and own:
        return [str(a) for a in own]
    if provider == "azure":
        tenant = acc.get("tenant")
        tid = tenant.get("id") if isinstance(tenant, dict) else tenant
        return ["az", "login"] + (["--tenant", str(tid)] if tid else [])
    if provider == "aws":
        profile = _costs(acc).get("profile")
        return ["aws", "login"] + (["--profile", str(profile)] if profile else [])
    if provider == "gcp":
        return ["gcloud", "auth", "login", "--update-adc"]
    if provider in ("openai", "anthropic"):
        ref = _costs(acc).get("key_ref") or f"keychain://{provider}-admin/{acc.get('id')}"
        argv = ["bash", str(Path(root) / "skills" / "secrets" / "secrets.sh"), "store", str(ref),
                "--root", str(root), "--from", "prompt"]
        return argv + (["--replace"] if replace else [])
    return []


def login_hint(acc: dict, provider: str, host: str) -> str:
    where = {"openai": "platform.openai.com > Settings > Organization > Admin keys",
             "anthropic": "console.anthropic.com > Settings > Admin keys"}.get(provider)
    if where:
        lead = "" if _costs(acc).get("key_ref") else "Add this key_ref to the account's costs block. "
        kind = "an admin key" if provider == "openai" else "an Admin API key"
        return (f"{lead}Create {kind} at {where}, then store it with this command; the Bridge keeps it in the "
                "declared secret store and reads it only for the call.")
    return f"Log in on {host} with this command; the next run reads the costs."


# ---------------------------------------------------------------- one account

def _round_groups(groups: dict, factor: float) -> dict:
    items = sorted(((g, v * factor) for g, v in groups.items() if round(v * factor, 2)), key=lambda x: -x[1])
    keep = [(g, v) for g, v in items if g != "other"]
    other = sum(v for g, v in items if g == "other")
    if len(keep) + (1 if other else 0) > MAX_GROUPS:
        other += sum(v for _, v in keep[MAX_GROUPS - 1:])
        keep = keep[:MAX_GROUPS - 1]
    return {g: round(v, 2) for g, v in keep + ([("other", other)] if round(other, 2) else [])}


def series(merged: dict, days: int, today: dt.date, factor: float, provisional: bool) -> list[dict]:
    start, _ = window(days, today)
    out = []
    for n in range(max(days, 1)):
        day = start + dt.timedelta(days=n)
        d = merged.get(day.isoformat()) or {}
        out.append({"day": day.isoformat(), "amount": round(float(d.get("amount") or 0) * factor, 2),
                    "provisional": provisional and (today - day).days < PROVISIONAL_DAYS,
                    "groups": _round_groups(d.get("groups") or {}, factor)})
    return out


def month_figures(days_out: list[dict], today: dt.date) -> tuple[float, float]:
    prefix = today.strftime("%Y-%m-")
    mtd = sum(d["amount"] for d in days_out if d["day"].startswith(prefix))
    settled = [d["amount"] for d in days_out if not d["provisional"]][-7:]
    left = calendar.monthrange(today.year, today.month)[1] - today.day
    mean = sum(settled) / len(settled) if settled else 0.0
    return round(mtd, 2), round(mtd + mean * left, 2)


def _base(acc: dict, provider: str, kind: str) -> dict:
    budget = _costs(acc).get("budget_month")
    budget = budget if isinstance(budget, (int, float)) and not isinstance(budget, bool) else None
    return {"id": acc.get("id"), "display_name": acc.get("display_name") or acc.get("id"), "provider": provider,
            "kind": kind, "ok": False, "error": None, "error_kind": None, "login": None,
            "currency": "EUR", "original_currency": None, "group_by": None,
            "budget_month": float(budget) if budget is not None else None,
            "days": [], "month_to_date": None, "forecast_month": None, "last_complete_day": None}


def _factor(currency: str, rates: dict) -> float | None:
    """EUR per unit of `currency` (the ECB quotes units per EUR), None when there is no rate."""
    if currency == "EUR":
        return 1.0
    rate = rates.get(currency)
    return 1.0 / rate if rate else None


def set_budget(entry: dict, currency: str, rates: dict) -> None:
    """budget_month is declared in `currency`; compare it in the entry's currency (EUR, or the account's own
    when its amounts could not be converted). Without a rate the number stays as declared and says so."""
    raw = entry.get("budget_month")
    if raw is None:
        return
    entry["budget_currency"] = currency
    target = entry.get("currency") or "EUR"
    if currency == target:
        entry["budget_month"] = round(float(raw), 2)
        return
    to_eur, from_eur = _factor(currency, rates), _factor(target, rates)
    if to_eur and from_eur:
        entry["budget_month"] = round(float(raw) * to_eur / from_eur, 2)
    else:
        entry["budget_fx_missing"] = True


def _budget_currency(con: dict, fallback: str = "EUR") -> str:
    return str(_costs(con).get("currency") or fallback or "EUR").upper()


def account_entry(acc: dict, days: int, today: dt.date, run: Callable, opener: Callable, rates: dict, host: str,
                  adapter: Callable | None = None, provider: str | None = None, root: Path = ROOT) -> dict:
    prov = provider or provider_of(acc)
    entry = _base(acc, prov, "usage")
    entry["group_by"] = str(_costs(acc).get("group_by") or "service") if prov in ("azure", "aws") else GROUPING.get(prov)
    fn = adapter or ADAPTERS.get(prov)
    try:
        if fn is None:
            raise CostError(f"no cost adapter for provider {prov} yet")
        rows = fn(acc, days, today, run, opener, root=root) if fn in (openai, anthropic) else fn(acc, days, today, run, opener)
        merged = merge_rows(rows)
    except (RuntimeError, OSError, ValueError, subprocess.SubprocessError) as e:
        kind = getattr(e, "kind", "error")
        entry.update(error=str(e)[:300], error_kind=kind if kind in ("auth", "access") else "error")
        if entry["error_kind"] == "auth":
            entry["login"] = {"argv": login_argv(acc, prov, root, replace=bool(getattr(e, "replace", False))),
                              "hint": login_hint(acc, prov, host)}
        set_budget(entry, _budget_currency(acc), rates)
        return entry
    except Exception as e:      # an answer of an unexpected shape fails this account, never the run
        entry.update(error=f"unexpected answer from {prov} ({type(e).__name__})", error_kind="error")
        set_budget(entry, _budget_currency(acc), rates)
        return entry
    currency = next((d["currency"] for d in merged.values() if d.get("currency")), "EUR")
    factor = _factor(currency, rates)
    entry["original_currency"] = currency
    if factor is None:
        entry["currency"], entry["fx_missing"], factor = currency, True, 1.0
    entry["ok"] = True
    entry["days"] = series(merged, days, today, factor, provisional=True)
    entry["last_complete_day"] = (today - dt.timedelta(days=PROVISIONAL_DAYS)).isoformat()
    set_budget(entry, _budget_currency(acc), rates)
    # the provider answered: no rows means nothing cost money in the window, which is 0, not unknown
    entry["month_to_date"], entry["forecast_month"] = month_figures(entry["days"], today)
    return entry


def monthly_amount(con: dict) -> float | None:
    pricing = con.get("pricing") if isinstance(con.get("pricing"), dict) else {}
    fee = pricing.get("monthly_fee") if isinstance(pricing.get("monthly_fee"), dict) else {}
    for value in (fee.get("gross"), fee.get("net")):
        if isinstance(value, (int, float)) and value:
            return float(value)
    year = pricing.get("base_per_year") if isinstance(pricing.get("base_per_year"), dict) else {}
    for value in (year.get("gross"), year.get("net")):
        if isinstance(value, (int, float)) and value:
            return float(value) / 12
    return None


def contract_entry(con: dict, days: int, today: dt.date, rates: dict) -> dict:
    entry = _base(con, "contract", "fixed")
    entry["group_by"] = "product"
    monthly = monthly_amount(con)
    pricing = con.get("pricing") if isinstance(con.get("pricing"), dict) else {}
    currency = str(pricing.get("currency") or "EUR").upper()
    if monthly is None:
        entry.update(error="no pricing.monthly_fee or pricing.base_per_year", error_kind="error")
        set_budget(entry, _budget_currency(con, currency), rates)
        return entry
    factor = _factor(currency, rates)
    entry["original_currency"] = currency
    if factor is None:
        entry["currency"], entry["fx_missing"], factor = currency, True, 1.0
    per_day = monthly * 12 / 365
    group = str(con.get("product") or con.get("id"))
    start, _ = window(days, today)
    merged = {(start + dt.timedelta(days=n)).isoformat(): {"amount": per_day, "groups": {group: per_day}} for n in range(days)}
    entry["days"] = series(merged, days, today, factor, provisional=False)
    entry["ok"] = True
    entry["last_complete_day"] = today.isoformat()
    entry["month_to_date"] = month_figures(entry["days"], today)[0]
    entry["forecast_month"] = round(monthly * factor, 2)
    set_budget(entry, _budget_currency(con, currency), rates)
    return entry


# ---------------------------------------------------------------- currency

def ecb_rates(opener: Callable = urllib.request.urlopen) -> dict:
    try:
        with opener(urllib.request.Request(ECB_URL), timeout=20) as r:
            xml = r.read().decode("utf-8")
        rates = {c: float(v) for c, v in re.findall(r"""currency=['"]([A-Z]{3})['"]\s+rate=['"]([0-9.]+)['"]""", xml)}
        day = re.search(r"""time=['"](\d{4}-\d{2}-\d{2})['"]""", xml)
        if not rates:
            raise ValueError("no rates in the answer")
        return {"date": day.group(1) if day else None, "source": "ecb", "rates": rates}
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {"date": None, "source": "ecb", "rates": {}, "error": str(e)[:200]}


# ---------------------------------------------------------------- the run

def collect(root: Path, host: str, days: int, today: dt.date, run: Callable = subprocess.run,
            opener: Callable = urllib.request.urlopen) -> dict:
    fx = ecb_rates(opener)
    rates = fx["rates"]
    out = [account_entry(acc, days, today, run, opener, rates, host, root=root) for acc in accounts(root, host)]
    out += [contract_entry(con, days, today, rates) for con in contracts(root, host)]
    return {"schema": 1, "kind": "cloud-costs", "host": host,
            "at": dt.datetime.now().astimezone().isoformat(timespec="seconds"),
            "currency": "EUR", "days": days, "today": today.isoformat(), "fx": fx, "accounts": out}


def file_inbox(root: Path, accounts_out: list[dict], run: Callable = subprocess.run) -> None:
    """One inbox item per account that needs a person (auth or access), closed again after a good run.
    The inbox is a courtesy: any failure here is ignored, the cost file is what counts."""
    inbox = [sys.executable, str(root / "scripts" / "inbox.py"), "--root", str(root)]
    try:
        for acc in accounts_out:
            if acc.get("ok") or acc.get("error_kind") not in ("auth", "access"):
                continue
            login = acc.get("login") or {}
            detail = " ".join(x for x in (acc.get("error"), login.get("hint")) if x)
            if login.get("argv"):
                detail += "\n" + shlex.join(login["argv"])
            run(inbox + ["add", "--from", "cloud-costs", "--kind", "question", "--gate", "only-you", "--urgency", "today",
                         "--key", f"cloud-costs-login-{acc.get('id')}", "--closer", "reporter",
                         "--summary", f"{acc.get('display_name') or acc.get('id')}: Anmeldung nötig", "--detail", detail],
                capture_output=True, text=True, timeout=30)
        good = {f"cloud-costs-login-{a.get('id')}" for a in accounts_out if a.get("ok")}
        if not good:
            return
        res = run(inbox + ["list", "--json"], capture_output=True, text=True, timeout=30)
        open_keys = {i.get("key") for i in json.loads(res.stdout or "[]") if isinstance(i, dict)}
        for key in sorted(good & open_keys):
            run(inbox + ["close", "--key", key, "--note", "cloud-costs read this account again"],
                capture_output=True, text=True, timeout=30)
    except (OSError, ValueError, subprocess.SubprocessError):
        pass


def main(argv=None, run: Callable = subprocess.run, opener: Callable = urllib.request.urlopen) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--host", required=True)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--days", type=int, default=35)
    ap.add_argument("--today", type=dt.date.fromisoformat, default=None, help="YYYY-MM-DD (default: today)")
    ap.add_argument("--inbox", action="store_true", help="file an inbox item per account that needs a login")
    args = ap.parse_args(argv)
    root = args.root.resolve()
    data = collect(root, args.host, max(args.days, 1), args.today or dt.date.today(), run, opener)
    out = args.out.expanduser()
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        tmp = out.with_name("." + out.name + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, out)
    except OSError as e:
        print(f"cloud-costs: cannot write {out}: {e}", file=sys.stderr)
        return 1
    if args.inbox:
        file_inbox(root, data["accounts"], run)
    bad = [a["id"] for a in data["accounts"] if not a["ok"]]
    print(f"cloud-costs: {len(data['accounts'])} account(s), {len(bad)} failed" + (f": {', '.join(map(str, bad))}" if bad else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
