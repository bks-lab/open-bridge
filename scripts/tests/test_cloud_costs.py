# SPDX-License-Identifier: MIT
"""scripts/cloud-costs.py: what the opted-in cloud accounts and contracts cost per day, read only.
az, aws, bq, the keychain, the provider APIs and the ECB rates are injected: nothing leaves the test."""
from __future__ import annotations

import datetime as dt
import importlib.util
import io
import json
import sys
import types
import urllib.error
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("cloud_costs", ROOT / "scripts" / "cloud-costs.py")
cc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cc)

TODAY = dt.date(2026, 10, 19)


def ok(out="", err="", code=0):
    return types.SimpleNamespace(returncode=code, stdout=out if isinstance(out, str) else json.dumps(out), stderr=err)


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def http_error(url, code):
    return urllib.error.HTTPError(url, code, "x", {}, io.BytesIO(b"{}"))


def bridge(tmp: Path) -> Path:
    acc = tmp / "identity" / "accounts"
    acc.mkdir(parents=True)
    (acc / "_template.yaml").write_text("id: tpl\ncosts: {enabled: true}\n")
    (acc / "azure-example.yaml").write_text(
        "id: azure-example\ndisplay_name: Example Azure\ntenant: {id: t-1}\n"
        "subscriptions: [{id: s1}, {id: s2}]\ncosts: {enabled: true, budget_month: 50}\n")
    (acc / "openai-example.yaml").write_text(
        "id: openai-example\ncloud: {provider: openai}\ncosts: {enabled: true, key_ref: 'keychain://openai-admin/me'}\n")
    (acc / "quiet.yaml").write_text("id: quiet\ncloud: {provider: aws}\n")                       # not opted in
    (acc / "aws-off.yaml").write_text("id: aws-off\nstatus: paused\ncosts: {enabled: true}\n")    # paused
    (acc / "aws-no.yaml").write_text("id: aws-no\ncosts: {enabled: false}\n")                     # switched off
    con = tmp / "identity" / "contracts"
    con.mkdir(parents=True)
    (con / "_template.yaml").write_text("id: tpl\nproduct: x\ncosts: {enabled: true}\n")
    (con / "acme-saas.yaml").write_text(
        "id: acme-saas\nproduct: saas\nstatus: active\npricing: {currency: EUR, monthly_fee: {gross: 36.5, net: 30}}\n"
        "costs: {enabled: true, budget_month: 40}\n")
    (con / "acme-host.yaml").write_text(
        "id: acme-host\nproduct: hosting\nstatus: active\npricing: {currency: EUR, base_per_year: {gross: 120}}\n"
        "costs: {enabled: true}\n")
    (con / "acme-old.yaml").write_text(
        "id: acme-old\nproduct: x\nstatus: cancelled\npricing: {monthly_fee: {gross: 9}}\ncosts: {enabled: true}\n")
    (con / "acme-plain.yaml").write_text("id: acme-plain\nproduct: x\npricing: {monthly_fee: {gross: 9}}\n")
    return tmp


# ---------------------------------------------------------------- discovery

def test_only_active_opted_in_accounts_and_contracts_are_asked(tmp_path):
    root = bridge(tmp_path)
    assert [a["id"] for a in cc.accounts(root)] == ["azure-example", "openai-example"]
    assert [c["id"] for c in cc.contracts(root)] == ["acme-host", "acme-saas"]


def test_an_account_with_costs_host_is_asked_only_by_the_collector_on_that_machine(tmp_path):
    root = bridge(tmp_path)
    (root / "identity" / "accounts" / "aws-laptop.yaml").write_text(
        "id: aws-laptop\ncloud: {provider: aws}\ncosts: {enabled: true, host: my-laptop}\n")
    (root / "identity" / "contracts" / "acme-there.yaml").write_text(
        "id: acme-there\nproduct: saas\npricing: {monthly_fee: {gross: 5}}\ncosts: {enabled: true, host: my-laptop}\n")
    assert [a["id"] for a in cc.accounts(root, "my-server")] == ["azure-example", "openai-example"]
    assert [a["id"] for a in cc.accounts(root, "my-laptop")] == ["aws-laptop", "azure-example", "openai-example"]
    assert [c["id"] for c in cc.contracts(root, "my-server")] == ["acme-host", "acme-saas"]
    assert [a["id"] for a in cc.accounts(root)] == ["aws-laptop", "azure-example", "openai-example"]   # no host: all


def test_provider_comes_from_costs_cloud_azure_shape_or_id_prefix():
    assert cc.provider_of({"id": "x", "costs": {"provider": "gcp"}}) == "gcp"
    assert cc.provider_of({"id": "x", "cloud": {"provider": "anthropic"}}) == "anthropic"
    assert cc.provider_of({"id": "x", "subscriptions": []}) == "azure"
    assert cc.provider_of({"id": "aws-main"}) == "aws"


# ---------------------------------------------------------------- azure

def az_answer(rows, cols=("Cost", "UsageDate", "ServiceName", "Currency"), next_link=None):
    return {"properties": {"columns": [{"name": c} for c in cols], "rows": rows, "nextLink": next_link}}


def test_azure_sums_subscriptions_per_day_and_service():
    seen = []

    def run(argv, **kw):
        seen.append(argv)
        sub = argv[argv.index("--url") + 1].split("/subscriptions/")[1].split("/")[0]
        body = json.loads(argv[argv.index("--body") + 1])
        assert body["type"] == "ActualCost" and body["timeframe"] == "Custom"
        assert body["timePeriod"]["from"].startswith("2026-10-17") and body["timePeriod"]["to"].startswith("2026-10-19")
        assert body["dataset"]["granularity"] == "Daily"
        assert body["dataset"]["aggregation"]["totalCost"] == {"name": "Cost", "function": "Sum"}
        assert body["dataset"]["grouping"] == [{"type": "Dimension", "name": "ServiceName"}]
        rows = {"s1": [[0.8, 20261017, "Functions", "EUR"], [0.43, 20261017, "Storage", "EUR"]],
                "s2": [[1.0, 20261018, "Functions", "EUR"]]}[sub]
        return ok(az_answer(rows))
    acc = {"id": "a", "subscriptions": [{"id": "s1"}, {"id": "s2"}], "costs": {"enabled": True}}
    rows = cc.azure(acc, 3, TODAY, run, None)
    assert len(seen) == 2 and all(a[:4] == ["az", "rest", "--method", "post"] for a in seen)
    assert "--subscription" not in seen[0]
    days = cc.merge_rows(rows)
    assert days["2026-10-17"]["groups"] == {"Functions": 0.8, "Storage": 0.43}
    assert days["2026-10-18"]["amount"] == 1.0 and days["2026-10-17"]["currency"] == "EUR"


def test_azure_reads_pretax_cost_groups_by_resource_group_or_tag_and_follows_next_link():
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        body = json.loads(argv[argv.index("--body") + 1])
        assert body["dataset"]["grouping"] == [{"type": "TagKey", "name": "team"}]
        if len(calls) == 1:
            return ok(az_answer([[2.0, 20261018, "team", "a", "USD"]], ("PreTaxCost", "UsageDate", "TagKey", "TagValue", "Currency"),
                                next_link="https://management.azure.com/next?x=1"))
        assert argv[argv.index("--url") + 1] == "https://management.azure.com/next?x=1"
        return ok(az_answer([[1.0, 20261018, "team", "", "USD"]], ("PreTaxCost", "UsageDate", "TagKey", "TagValue", "Currency")))
    acc = {"id": "a", "costs": {"enabled": True, "subscriptions": ["s9"], "group_by": "tag:team"}}
    days = cc.merge_rows(cc.azure(acc, 3, TODAY, run, None))
    assert days["2026-10-18"]["groups"] == {"a": 2.0, "(untagged)": 1.0} and days["2026-10-18"]["currency"] == "USD"
    assert cc.azure_grouping("resource_group") == [{"type": "Dimension", "name": "ResourceGroupName"}]


def test_azure_retries_once_on_429():
    calls, slept = [], []

    def run(argv, **kw):
        calls.append(1)
        if len(calls) == 1:
            return ok(err="Too Many Requests(429)", code=1)
        return ok(az_answer([]))
    acc = {"id": "a", "costs": {"subscriptions": ["s1"]}}
    assert cc.azure(acc, 3, TODAY, run, None, sleep=slept.append) == []
    assert len(calls) == 2 and len(slept) == 1


def test_azure_access_and_auth_failures_are_classified():
    acc = {"id": "a", "costs": {"subscriptions": ["s1"]}}
    denied = lambda argv, **kw: ok(err="Forbidden({\"error\":{\"code\":\"AuthorizationFailed\"}})", code=1)  # noqa: E731
    try:
        cc.azure(acc, 3, TODAY, denied, None)
        raise AssertionError("no error")
    except cc.CostError as e:
        assert e.kind == "access" and "Cost Management Reader role on subscription s1" in str(e)
    gone = lambda argv, **kw: ok(err="ERROR: AADSTS700082: The refresh token has expired. Please run 'az login'", code=1)  # noqa: E731
    try:
        cc.azure(acc, 3, TODAY, gone, None)
        raise AssertionError("no error")
    except cc.CostError as e:
        assert e.kind == "auth"


def test_azure_without_subscriptions_says_so():
    try:
        cc.azure({"id": "a", "costs": {}}, 3, TODAY, lambda *a, **k: ok([]), None)
        raise AssertionError("no error")
    except RuntimeError as e:
        assert "subscription" in str(e)


# ---------------------------------------------------------------- aws

def test_aws_reads_daily_cost_per_service_with_profile_and_pages():
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        assert argv[:3] == ["aws", "ce", "get-cost-and-usage"]
        assert "Start=2026-10-17,End=2026-10-20" in argv and argv[argv.index("--profile") + 1] == "p1"
        page = {"ResultsByTime": [{"TimePeriod": {"Start": "2026-10-17", "End": "2026-10-18"},
                                   "Groups": [{"Keys": ["Amazon S3"], "Metrics": {"UnblendedCost": {"Amount": "0.5", "Unit": "USD"}}},
                                              {"Keys": ["Tax"], "Metrics": {"UnblendedCost": {"Amount": "0", "Unit": "USD"}}}]}]}
        if len(calls) == 1:
            page["NextPageToken"] = "tok2"
        else:
            assert argv[argv.index("--next-page-token") + 1] == "tok2"
            page["ResultsByTime"][0]["TimePeriod"]["Start"] = "2026-10-18"
        return ok(page)
    days = cc.merge_rows(cc.aws({"id": "aws-x", "costs": {"profile": "p1"}}, 3, TODAY, run, None))
    assert days["2026-10-17"] == {"amount": 0.5, "currency": "USD", "groups": {"Amazon S3": 0.5}}
    assert "2026-10-18" in days and len(calls) == 2


def test_aws_access_denied_and_missing_login():
    acc = {"id": "aws-x", "costs": {}}
    for err, kind, text in (("An error occurred (AccessDeniedException) when calling", "access", "ce:GetCostAndUsage"),
                            ("Unable to locate credentials. You can configure credentials by running \"aws login\".", "auth", "")):
        try:
            cc.aws(acc, 3, TODAY, lambda argv, **kw: ok(err=err, code=255), None)
            raise AssertionError("no error")
        except cc.CostError as e:
            assert e.kind == kind and text in str(e)


# ---------------------------------------------------------------- openai

def keychain_run(value="sk-admin-abc"):
    """The keychain as the secrets skill reads it: `security ... -g`, the value on stderr."""
    def run(argv, **kw):
        assert argv[:2] == ["security", "find-generic-password"] and argv[-1] == "-g"
        return ok(err=f'keychain: "login"\npassword: "{value}"\n') if value else ok(code=44)
    return run


def test_openai_follows_pagination_with_the_admin_key():
    urls = []

    def opener(req, timeout=0):
        urls.append(req.full_url)
        assert req.headers["Authorization"] == "Bearer sk-admin-abc"
        start = int(dt.datetime(2026, 10, 17, tzinfo=dt.timezone.utc).timestamp())
        if "page=" not in req.full_url:
            assert f"start_time={start}" in req.full_url and "bucket_width=1d" in req.full_url and "group_by=line_item" in req.full_url
            body = {"data": [{"start_time": start, "results": [{"amount": {"value": 1.5, "currency": "usd"}, "line_item": "gpt, input"}]}],
                    "has_more": True, "next_page": "pg2"}
        else:
            assert "page=pg2" in req.full_url
            body = {"data": [{"start_time": start + 86400, "results": [{"amount": {"value": 0.25, "currency": "usd"}, "line_item": None}]}],
                    "has_more": False, "next_page": None}
        return Resp(json.dumps(body).encode())
    acc = {"id": "o", "costs": {"key_ref": "keychain://openai-admin/me"}}
    days = cc.merge_rows(cc.openai(acc, 3, TODAY, keychain_run(), opener))
    assert days["2026-10-17"] == {"amount": 1.5, "currency": "USD", "groups": {"gpt, input": 1.5}}
    assert days["2026-10-18"]["groups"] == {"other": 0.25} and len(urls) == 2


def test_openai_refuses_a_key_that_is_not_an_admin_key_and_a_missing_key():
    acc = {"id": "o", "costs": {"key_ref": "keychain://openai-admin/me"}}
    for run, text in ((keychain_run("sk-proj-xyz"), "admin key (sk-admin-"), (keychain_run(None), "keychain")):
        try:
            cc.openai(acc, 3, TODAY, run, lambda *a, **k: None)
            raise AssertionError("no error")
        except cc.CostError as e:
            assert e.kind == "auth" and text in str(e)


def test_openai_401_is_an_auth_failure():
    def opener(req, timeout=0):
        raise http_error(req.full_url, 401)
    try:
        cc.openai({"id": "o", "costs": {"key_ref": "keychain://a/b"}}, 3, TODAY, keychain_run(), opener)
        raise AssertionError("no error")
    except cc.CostError as e:
        assert e.kind == "auth" and "401" in str(e)


# ---------------------------------------------------------------- anthropic

def test_anthropic_reads_cents_follows_pages_and_sends_the_headers():
    urls = []

    def opener(req, timeout=0):
        urls.append(req.full_url)
        assert req.headers["X-api-key"] == "sk-ant-admin01-k" and req.headers["Anthropic-version"] == "2023-06-01"
        if "page=" not in req.full_url:
            assert "starting_at=2026-10-17T00:00:00Z" in req.full_url and "ending_at=2026-10-20T00:00:00Z" in req.full_url
            assert "bucket_width=1d" in req.full_url and "group_by%5B%5D=description" in req.full_url
            body = {"data": [{"starting_at": "2026-10-17T00:00:00Z",
                              "results": [{"amount": "123.5", "currency": "USD", "description": "Claude usage"}]}],
                    "has_more": True, "next_page": "n2"}
        else:
            body = {"data": [{"starting_at": "2026-10-18T00:00:00Z", "results": [{"amount": "50", "currency": "USD"}]}],
                    "has_more": False}
        return Resp(json.dumps(body).encode())
    acc = {"id": "an", "costs": {"key_ref": "keychain://anthropic-admin/me"}}
    days = cc.merge_rows(cc.anthropic(acc, 3, TODAY, keychain_run("sk-ant-admin01-k"), opener))
    assert days["2026-10-17"] == {"amount": 1.235, "currency": "USD", "groups": {"Claude usage": 1.235}}
    assert days["2026-10-18"]["amount"] == 0.5 and len(urls) == 2


def test_anthropic_refuses_a_key_that_is_not_an_admin_key():
    try:
        cc.anthropic({"id": "an", "costs": {"key_ref": "keychain://a/b"}}, 3, TODAY, keychain_run("sk-ant-api03-x"), None)
        raise AssertionError("no error")
    except cc.CostError as e:
        assert e.kind == "auth" and "Admin API key" in str(e)


# ---------------------------------------------------------------- gcp, cloudflare, unknown

def test_gcp_needs_a_billing_export_and_reads_it_with_bq():
    try:
        cc.gcp({"id": "g", "costs": {}}, 3, TODAY, None, None)
        raise AssertionError("no error")
    except RuntimeError as e:
        assert "costs.bigquery_table" in str(e)

    def run(argv, **kw):
        assert argv[:4] == ["bq", "query", "--use_legacy_sql=false", "--format=json"]
        sql = argv[-1]
        assert "`acme-billing.ds.export_v1`" in sql and "UNNEST(credits)" in sql and "2026-10-17" in sql
        return ok([{"day": "2026-10-18", "service": "Compute Engine", "cost": "2.5", "currency": "EUR"}])
    days = cc.merge_rows(cc.gcp({"id": "g", "costs": {"bigquery_table": "acme-billing.ds.export_v1"}}, 3, TODAY, run, None))
    assert days["2026-10-18"] == {"amount": 2.5, "currency": "EUR", "groups": {"Compute Engine": 2.5}}


def test_gcp_reauthentication_is_an_auth_failure_and_a_strange_table_is_refused():
    try:
        cc.gcp({"id": "g", "costs": {"bigquery_table": "a.b.c"}}, 3, TODAY,
               lambda argv, **kw: ok(err="Reauthentication required, run gcloud auth login", code=1), None)
        raise AssertionError("no error")
    except cc.CostError as e:
        assert e.kind == "auth"
    try:
        cc.gcp({"id": "g", "costs": {"bigquery_table": "a.b`; DROP"}}, 3, TODAY, None, None)
        raise AssertionError("no error")
    except RuntimeError as e:
        assert "bigquery_table" in str(e)


def test_cloudflare_and_unknown_providers_say_why():
    root_acc = {"id": "cf", "cloud": {"provider": "cloudflare"}, "costs": {"enabled": True}}
    entry = cc.account_entry(root_acc, 3, TODAY, run=None, opener=None, rates={}, host="my-server")
    assert entry["ok"] is False and "contract with costs.enabled" in entry["error"] and entry["days"] == []
    entry = cc.account_entry({"id": "zz", "cloud": {"provider": "acme"}, "costs": {}}, 3, TODAY, None, None, {}, "my-server")
    assert entry["error"] == "no cost adapter for provider acme yet" and entry["error_kind"] == "error"


# ---------------------------------------------------------------- auth: what to run

def test_an_auth_failure_carries_the_login_command():
    gone = lambda argv, **kw: ok(err="Please run 'az login' to setup account.", code=1)  # noqa: E731
    acc = {"id": "azure-example", "tenant": {"id": "t-1"}, "costs": {"subscriptions": ["s1"]}}
    e = cc.account_entry(acc, 3, TODAY, gone, None, {}, "my-server")
    assert e["ok"] is False and e["error_kind"] == "auth" and e["login"]["argv"] == ["az", "login", "--tenant", "t-1"]
    assert e["login"]["hint"] and e["month_to_date"] is None
    assert cc.login_argv({"id": "a", "tenant": "t-2"}, "azure") == ["az", "login", "--tenant", "t-2"]
    assert cc.login_argv({"id": "a", "costs": {"profile": "p"}}, "aws") == ["aws", "login", "--profile", "p"]
    assert cc.login_argv({"id": "a"}, "gcp") == ["gcloud", "auth", "login", "--update-adc"]
    assert cc.login_argv({"id": "a", "costs": {"key_ref": "keychain://k/a"}}, "openai", Path("/srv/bridge")) == [
        "bash", "/srv/bridge/skills/secrets/secrets.sh", "store", "keychain://k/a", "--root", "/srv/bridge",
        "--from", "prompt"]
    assert cc.login_argv({"id": "a", "costs": {"login": ["my-login", "x"]}}, "azure") == ["my-login", "x"]
    assert "platform.openai.com" in cc.login_hint({"id": "a"}, "openai", "my-server")
    assert "console.anthropic.com" in cc.login_hint({"id": "a"}, "anthropic", "my-server")


def test_an_access_failure_has_no_login():
    denied = lambda argv, **kw: ok(err="AccessDeniedException", code=255)  # noqa: E731
    e = cc.account_entry({"id": "aws-x", "costs": {}}, 3, TODAY, denied, None, {}, "my-server")
    assert e["error_kind"] == "access" and e["login"] is None


# ---------------------------------------------------------------- currency

ECB = b"""<?xml version="1.0" encoding="UTF-8"?>
<gesmes:Envelope xmlns:gesmes="http://www.gesmes.org/xml/2002-08-01" xmlns="http://www.ecb.int/vocabulary/2002-08-01/eurofxref">
<Cube><Cube time='2026-10-17'><Cube currency='USD' rate='1.0800'/><Cube currency="GBP" rate="0.86"/></Cube></Cube>
</gesmes:Envelope>"""


def test_ecb_rates_are_parsed_and_a_failure_is_recorded():
    fx = cc.ecb_rates(lambda req, timeout=0: Resp(ECB))
    assert fx == {"date": "2026-10-17", "source": "ecb", "rates": {"USD": 1.08, "GBP": 0.86}}

    def broken(req, timeout=0):
        raise urllib.error.URLError("down")
    fx = cc.ecb_rates(broken)
    assert fx["rates"] == {} and fx["date"] is None and fx["error"]


def test_usd_is_converted_to_eur_and_kept_when_no_rate():
    rows = [{"day": "2026-10-17", "amount": 1.08, "currency": "USD", "groups": {"x": 1.08}}]
    acc = {"id": "o", "costs": {"enabled": True}}
    fn = lambda *a, **k: rows  # noqa: E731
    e = cc.account_entry(acc, 3, TODAY, None, None, {"USD": 1.08}, "h", adapter=fn, provider="openai")
    assert e["currency"] == "EUR" and e["original_currency"] == "USD" and "fx_missing" not in e
    assert e["days"][0] == {"day": "2026-10-17", "amount": 1.0, "provisional": False, "groups": {"x": 1.0}}
    e = cc.account_entry(acc, 3, TODAY, None, None, {}, "h", adapter=fn, provider="openai")
    assert e["currency"] == "USD" and e["original_currency"] == "USD" and e["fx_missing"] is True
    assert e["days"][0]["amount"] == 1.08


# ---------------------------------------------------------------- the day series

def test_days_are_zero_filled_provisional_and_capped_at_eight_groups():
    groups = {f"g{i}": float(i + 1) for i in range(10)}                       # 1..10, sum 55
    rows = [{"day": "2026-10-18", "amount": 55.0, "currency": "EUR", "groups": groups}]
    e = cc.account_entry({"id": "a", "costs": {}}, 5, TODAY, None, None, {}, "h", adapter=lambda *a, **k: rows, provider="aws")
    assert [d["day"] for d in e["days"]] == ["2026-10-15", "2026-10-16", "2026-10-17", "2026-10-18", "2026-10-19"]
    assert [d["provisional"] for d in e["days"]] == [False, False, False, True, True]
    assert e["days"][0] == {"day": "2026-10-15", "amount": 0.0, "provisional": False, "groups": {}}
    g = e["days"][3]["groups"]
    assert len(g) == 8 and g["other"] == 6.0 and "g2" not in g and g["g9"] == 10.0     # top 7 + other
    assert e["last_complete_day"] == "2026-10-17" and e["kind"] == "usage"


def test_month_to_date_and_forecast():
    rows = [{"day": (TODAY - dt.timedelta(days=n)).isoformat(), "amount": 2.0, "currency": "EUR", "groups": {}} for n in range(30)]
    e = cc.account_entry({"id": "a", "costs": {"budget_month": 50}}, 35, TODAY, None, None, {}, "h",
                         adapter=lambda *a, **k: rows, provider="aws")
    assert e["month_to_date"] == 38.0                                        # 19 days of October at 2
    assert e["forecast_month"] == 38.0 + 2.0 * 12                            # 12 days left in October
    assert e["budget_month"] == 50.0
    empty = cc.account_entry({"id": "a", "costs": {}}, 35, TODAY, None, None, {}, "h", adapter=lambda *a, **k: [], provider="aws")
    # an answer without rows is a month at zero (the account cost nothing), not an unknown one
    assert empty["ok"] and empty["month_to_date"] == 0.0 and empty["forecast_month"] == 0.0


def test_contracts_are_spread_evenly_and_are_fixed(tmp_path):
    root = bridge(tmp_path)
    by = {c["id"]: c for c in cc.contracts(root)}
    e = cc.contract_entry(by["acme-saas"], 35, TODAY, {})
    assert e["kind"] == "fixed" and e["provider"] == "contract" and e["group_by"] == "product" and e["ok"]
    assert e["days"][-1] == {"day": "2026-10-19", "amount": 1.2, "provisional": False, "groups": {"saas": 1.2}}
    assert e["forecast_month"] == 36.5 and e["budget_month"] == 40.0 and e["last_complete_day"] == "2026-10-19"
    assert e["month_to_date"] == round(36.5 * 12 / 365 * 19, 2)
    h = cc.contract_entry(by["acme-host"], 35, TODAY, {})
    assert h["forecast_month"] == 10.0 and h["days"][0]["groups"] == {"hosting": round(120 / 365, 2)}
    assert cc.monthly_amount({"pricing": {"monthly_fee": {"net": 5}}}) == 5.0
    assert cc.monthly_amount({"pricing": {}}) is None


# ---------------------------------------------------------------- the whole run

def test_collect_writes_the_document_and_main_reports(tmp_path, capsys):
    root = bridge(tmp_path)

    def run(argv, **kw):
        if "find-generic-password" in argv:
            return ok(err='password: "sk-admin-abc"\n')
        return ok(err="Please run 'az login' to setup account.", code=1)

    def opener(req, timeout=0):
        if "ecb.europa.eu" in req.full_url:
            return Resp(ECB)
        return Resp(json.dumps({"data": [{"start_time": int(dt.datetime(2026, 10, 18, tzinfo=dt.timezone.utc).timestamp()),
                                          "results": [{"amount": {"value": 1.08, "currency": "usd"}, "line_item": "x"}]}],
                                "has_more": False}).encode())
    out = tmp_path / "res" / "costs.json"
    rc = cc.main(["--root", str(root), "--host", "my-server", "--out", str(out), "--today", "2026-10-19", "--days", "7"],
                 run=run, opener=opener)
    assert rc == 0 and not list(out.parent.glob(".*.tmp"))
    doc = json.loads(out.read_text())
    assert doc["schema"] == 1 and doc["kind"] == "cloud-costs" and doc["host"] == "my-server"
    assert doc["currency"] == "EUR" and doc["days"] == 7 and doc["today"] == "2026-10-19"
    assert doc["fx"] == {"date": "2026-10-17", "source": "ecb", "rates": {"USD": 1.08, "GBP": 0.86}}
    by = {a["id"]: a for a in doc["accounts"]}
    assert set(by) == {"azure-example", "openai-example", "acme-host", "acme-saas"}
    assert by["openai-example"]["ok"] and by["openai-example"]["days"][-2]["amount"] == 1.0
    assert by["azure-example"]["error_kind"] == "auth" and by["azure-example"]["login"]["argv"][:2] == ["az", "login"]
    assert capsys.readouterr().out.strip() == "cloud-costs: 4 account(s), 1 failed: azure-example"


def test_inbox_files_one_item_per_login_failure_and_closes_it_after_a_good_run(tmp_path):
    calls = []

    def run(argv, **kw):
        calls.append(argv)
        if "list" in argv:
            return ok([{"id": "x", "key": "cloud-costs-login-good"}, {"id": "y", "key": "other"}])
        return ok("")
    accounts = [{"id": "bad", "display_name": "Bad", "ok": False, "error_kind": "auth", "error": "not logged in",
                 "login": {"argv": ["az", "login"], "hint": "Log in."}},
                {"id": "denied", "display_name": "Denied", "ok": False, "error_kind": "access", "error": "needs a role", "login": None},
                {"id": "broken", "ok": False, "error_kind": "error", "error": "boom", "login": None},
                {"id": "good", "ok": True}, {"id": "good2", "ok": True}]
    cc.file_inbox(tmp_path, accounts, run=run)
    adds = [a for a in calls if "add" in a]
    assert len(adds) == 2
    bad = adds[0]
    assert bad[bad.index("--key") + 1] == "cloud-costs-login-bad" and bad[bad.index("--gate") + 1] == "only-you"
    assert bad[bad.index("--summary") + 1] == "Bad: Anmeldung nötig" and "az login" in bad[bad.index("--detail") + 1]
    assert bad[bad.index("--from") + 1] == "cloud-costs" and bad[bad.index("--closer") + 1] == "reporter"
    closes = [a for a in calls if "close" in a]
    assert len(closes) == 1 and closes[0][closes[0].index("--key") + 1] == "cloud-costs-login-good"


def test_inbox_errors_never_stop_the_run(tmp_path):
    def run(argv, **kw):
        raise OSError("no python")
    cc.file_inbox(tmp_path, [{"id": "a", "ok": False, "error_kind": "auth", "error": "x", "login": {"argv": ["a"], "hint": "h"}}], run=run)


# ---------------------------------------------------------------- review findings

def test_gcp_asks_bq_for_every_row_in_day_order():
    seen = {}

    def run(argv, **kw):
        seen["argv"] = argv
        return ok([])
    cc.gcp({"id": "g", "costs": {"bigquery_table": "a.b.c"}}, 35, TODAY, run, None)
    rows_flag = [a for a in seen["argv"] if a.startswith("--max_rows=")]
    assert rows_flag and int(rows_flag[0].split("=")[1]) >= 35 * 1000       # bq stops at 100 rows by default
    assert "ORDER BY day" in seen["argv"][-1]


def test_a_key_login_runs_the_secrets_skill_of_this_bridge_and_replaces_a_wrong_key(tmp_path):
    acc = {"id": "o", "cloud": {"provider": "openai"}, "costs": {"key_ref": "keychain://openai-admin/me"}}
    store = cc.login_argv(acc, "openai", tmp_path)
    assert store[1] == str(tmp_path / "skills" / "secrets" / "secrets.sh")         # absolute: works from any cwd and over ssh
    assert store[store.index("--root") + 1] == str(tmp_path) and "--replace" not in store
    assert cc.login_argv(acc, "openai", tmp_path, replace=True)[-1] == "--replace"
    # no key yet: store it; a project key or a refused key is already there: replace it
    missing = cc.account_entry(acc, 3, TODAY, keychain_run(None), None, {}, "h", root=tmp_path)
    assert missing["error_kind"] == "auth" and "--replace" not in missing["login"]["argv"]
    wrong = cc.account_entry(acc, 3, TODAY, keychain_run("sk-proj-x"), None, {}, "h", root=tmp_path)
    assert wrong["error_kind"] == "auth" and wrong["login"]["argv"][-1] == "--replace"

    def refused(req, timeout=0):
        raise http_error(req.full_url, 401)
    gone = cc.account_entry(acc, 3, TODAY, keychain_run(), refused, {}, "h", root=tmp_path)
    assert gone["error_kind"] == "auth" and gone["login"]["argv"][-1] == "--replace"


def test_the_key_is_read_through_the_secrets_skill_from_any_declared_store():
    def run(argv, **kw):
        assert argv[:4] == ["az", "keyvault", "secret", "show"]
        return ok("sk-admin-vault\n")
    assert cc.read_key("azure-keyvault://example-vault/openai-admin", run, ROOT) == "sk-admin-vault"
    # a keychain value the -w form would have hex encoded comes back as written
    hexed = lambda argv, **kw: ok(err='password: 0x736B2D61646D696E2DC3A4  "sk-admin-\\303\\244"\n')  # noqa: E731
    assert cc.read_key("keychain://openai-admin/me", hexed, ROOT) == "sk-admin-ä"
    for ref in (None, "", "not a reference"):
        try:
            cc.read_key(ref, run, ROOT)
            raise AssertionError("no error")
        except cc.CostError as e:
            assert e.kind == "auth" and "key_ref" in str(e)


def test_a_key_store_this_machine_cannot_read_is_an_access_failure_not_a_traceback():
    absent = lambda argv, **kw: ok(err="security: not found", code=127)  # noqa: E731
    try:
        cc.read_key("keychain://openai-admin/me", absent, ROOT)
        raise AssertionError("no error")
    except cc.CostError as e:
        assert e.kind == "access" and "keychain://openai-admin/me" in str(e) and "Errno" not in str(e)


def test_the_budget_is_converted_from_its_own_currency():
    rows = [{"day": "2026-10-17", "amount": 1.08, "currency": "USD", "groups": {}}]
    fn = lambda *a, **k: rows  # noqa: E731
    acc = {"id": "o", "costs": {"budget_month": 108, "currency": "USD"}}
    e = cc.account_entry(acc, 3, TODAY, None, None, {"USD": 1.08}, "h", adapter=fn, provider="openai")
    assert e["currency"] == "EUR" and e["budget_month"] == 100.0 and e["budget_currency"] == "USD"
    # no rate: amounts stay in USD, and so does a USD budget, unflagged
    e = cc.account_entry(acc, 3, TODAY, None, None, {}, "h", adapter=fn, provider="openai")
    assert e["currency"] == "USD" and e["budget_month"] == 108.0 and "budget_fx_missing" not in e
    # a GBP budget against EUR amounts without a GBP rate keeps its number and says so
    e = cc.account_entry({"id": "o", "costs": {"budget_month": 50, "currency": "GBP"}}, 3, TODAY, None, None,
                         {"USD": 1.08}, "h", adapter=fn, provider="openai")
    assert e["budget_month"] == 50.0 and e["budget_currency"] == "GBP" and e["budget_fx_missing"] is True
    # EUR stays as it is
    e = cc.account_entry({"id": "o", "costs": {"budget_month": 50}}, 3, TODAY, None, None, {}, "h", adapter=fn, provider="aws")
    assert e["budget_month"] == 50.0 and e["budget_currency"] == "EUR"
    # a contract's budget is in pricing.currency unless costs.currency says otherwise
    con = {"id": "c", "product": "p", "pricing": {"currency": "USD", "monthly_fee": {"gross": 10.8}},
           "costs": {"enabled": True, "budget_month": 21.6}}
    c = cc.contract_entry(con, 35, TODAY, {"USD": 1.08})
    assert c["budget_month"] == 20.0 and c["budget_currency"] == "USD" and c["forecast_month"] == 10.0


def test_an_unexpected_answer_fails_only_its_own_account(tmp_path):
    acc = tmp_path / "identity" / "accounts"
    acc.mkdir(parents=True)
    (acc / "gcp-odd.yaml").write_text("id: gcp-odd\ncloud: {provider: gcp}\ncosts: {enabled: true, bigquery_table: a.b.c}\n")
    (acc / "aws-good.yaml").write_text("id: aws-good\ncloud: {provider: aws}\ncosts: {enabled: true}\n")

    def run(argv, **kw):
        if argv[0] == "bq":
            return ok({"error": "x"})                                     # exit 0, but not a list of rows
        return ok({"ResultsByTime": [{"TimePeriod": {"Start": "2026-10-18"},
                                      "Groups": [{"Keys": ["EC2"], "Metrics": {"UnblendedCost": {"Amount": "2", "Unit": "EUR"}}}]}]})
    doc = cc.collect(tmp_path, "my-server", 3, TODAY, run, lambda req, timeout=0: Resp(ECB))
    by = {a["id"]: a for a in doc["accounts"]}
    assert by["aws-good"]["ok"] and by["aws-good"]["days"][1]["amount"] == 2.0
    odd = by["gcp-odd"]
    assert odd["ok"] is False and odd["error_kind"] == "error" and "unexpected answer from gcp" in odd["error"]


# ---------------------------------------------------------------- aws credits, split accounts, twilio

def test_aws_keeps_credits_apart_from_what_was_used():
    def run(argv, **kw):
        i = argv.index("--group-by")
        assert argv[i + 1:i + 3] == ["Type=DIMENSION,Key=SERVICE", "Type=DIMENSION,Key=RECORD_TYPE"]
        assert argv.count("--group-by") == 1         # a second flag would replace the first
        return ok({"ResultsByTime": [{"TimePeriod": {"Start": "2026-10-17"}, "Groups": [
            {"Keys": ["Claude (Bedrock Edition)", "Usage"], "Metrics": {"UnblendedCost": {"Amount": "1.25", "Unit": "USD"}}},
            {"Keys": ["Claude (Bedrock Edition)", "Credit"], "Metrics": {"UnblendedCost": {"Amount": "-1.25", "Unit": "USD"}}},
            {"Keys": ["Tax", "Tax"], "Metrics": {"UnblendedCost": {"Amount": "0.25", "Unit": "USD"}}}]}]})
    day = cc.merge_rows(cc.aws({"id": "aws-x", "costs": {}}, 3, TODAY, run, None))["2026-10-17"]
    # paid is what is left after the credits; the groups say what was used, before them
    assert day["amount"] == 0.25 and day["credits"] == -1.25
    assert day["groups"] == {"Claude (Bedrock Edition)": 1.25, "Tax": 0.25}
    e = cc.account_entry({"id": "aws-x", "costs": {}}, 3, TODAY, run, None, {}, "h")
    d = next(x for x in e["days"] if x["day"] == "2026-10-17")
    assert d["amount"] == 0.25 and d["credits"] == -1.25 and d["used"] == 1.5
    assert e["month_to_date"] == 0.25 and e["used_month"] == 1.5 and e["credits_month"] == -1.25
    assert "credits" not in e["days"][1] and "credits_month" in e


def test_an_account_without_credits_carries_no_credit_fields():
    rows = [{"day": "2026-10-17", "amount": 1.0, "currency": "EUR", "groups": {"x": 1.0}}]
    e = cc.account_entry({"id": "a", "costs": {}}, 3, TODAY, None, None, {}, "h", adapter=lambda *a, **k: rows, provider="aws")
    assert "credits_month" not in e and "used_month" not in e and "credits" not in e["days"][0]


def test_openai_split_by_project_answers_one_entry_per_project():
    start = int(dt.datetime(2026, 10, 17, tzinfo=dt.timezone.utc).timestamp())

    def opener(req, timeout=0):
        if "/organization/projects" in req.full_url:
            return Resp(json.dumps({"data": [{"id": "proj_a", "name": "Customer A"}, {"id": "proj_b", "name": "Default"}],
                                    "has_more": False}).encode())
        assert "group_by=project_id" in req.full_url and "group_by=line_item" in req.full_url
        return Resp(json.dumps({"data": [{"start_time": start, "results": [
            {"amount": {"value": 2.16, "currency": "usd"}, "line_item": "realtime", "project_id": "proj_a"},
            {"amount": {"value": 1.08, "currency": "usd"}, "line_item": "tts", "project_id": "proj_b"},
            {"amount": {"value": 1.08, "currency": "usd"}, "line_item": "tts", "project_id": "proj_c"}]}],
            "has_more": False}).encode())
    acc = {"id": "openai-x", "display_name": "OpenAI X",
           "costs": {"key_ref": "keychain://openai-admin/me", "split": "project", "parts": {"proj_c": "Lab"},
                     "budgets": {"proj_a": 30}}}
    entries = cc.account_entries(acc, 3, TODAY, keychain_run(), opener, {"USD": 1.08}, "h")
    by = {e["id"]: e for e in entries}
    assert set(by) == {"openai-x/proj_a", "openai-x/proj_b", "openai-x/proj_c"}
    a = by["openai-x/proj_a"]
    assert a["display_name"] == "OpenAI X: Customer A" and a["parent"] == "openai-x" and a["part"] == "proj_a"
    assert a["ok"] and a["month_to_date"] == 2.0 and a["budget_month"] == 30.0 and a["days"][0]["groups"] == {"realtime": 2.0}
    assert by["openai-x/proj_c"]["display_name"] == "OpenAI X: Lab" and by["openai-x/proj_c"]["budget_month"] is None


def test_a_split_account_that_fails_is_one_failed_entry():
    acc = {"id": "openai-x", "costs": {"key_ref": "keychain://openai-admin/me", "split": "project"}}
    entries = cc.account_entries(acc, 3, TODAY, keychain_run(None), lambda *a, **k: None, {}, "h")
    assert len(entries) == 1 and entries[0]["id"] == "openai-x" and entries[0]["error_kind"] == "auth"


def test_a_split_without_project_names_keeps_the_ids():
    start = int(dt.datetime(2026, 10, 17, tzinfo=dt.timezone.utc).timestamp())

    def opener(req, timeout=0):
        if "/organization/projects" in req.full_url:
            raise http_error(req.full_url, 403)
        return Resp(json.dumps({"data": [{"start_time": start, "results": [
            {"amount": {"value": 1.0, "currency": "usd"}, "line_item": "x", "project_id": None}]}], "has_more": False}).encode())
    acc = {"id": "openai-o", "costs": {"key_ref": "keychain://openai-admin/me", "split": "project"}}
    (e,) = cc.account_entries(acc, 3, TODAY, keychain_run(), opener, {}, "h")
    assert e["id"] == "openai-o/none" and e["display_name"] == "openai-o: no project" and e["ok"]


def twilio_records():
    rec = lambda day, cat, price: {"category": cat, "startDate": day, "price": price, "priceUnit": "usd"}  # noqa: E731
    return [rec("2026-10-17", "totalprice", "1.5"), rec("2026-10-17", "trunking-origination", "1.0"),
            rec("2026-10-17", "trunking-origination-local", "1.0"), rec("2026-10-17", "phonenumbers", "0.25"),
            rec("2026-10-17", "phonenumbers-local", "0"), rec("2026-10-18", "totalprice", "0"),
            rec("2026-10-18", "calls", "0")]


def test_twilio_reads_the_daily_usage_records_through_the_logged_in_cli():
    seen = {}

    def run(argv, **kw):
        seen["argv"], seen["timeout"] = argv, kw.get("timeout")
        return ok(twilio_records())
    rows = cc.twilio({"id": "tw", "costs": {"profile": "work"}}, 3, TODAY, run, None)
    argv = seen["argv"]
    assert argv[:2] == ["twilio", "api:core:usage:records:daily:list"]
    assert argv[argv.index("--start-date") + 1] == "2026-10-17" and argv[argv.index("--end-date") + 1] == "2026-10-19"
    assert argv[argv.index("-p") + 1] == "work" and seen["timeout"] >= 300
    day = cc.merge_rows(rows)["2026-10-17"]
    # the total is totalprice; the groups are the deepest priced categories, the rest of the total is "other"
    assert day == {"amount": 1.5, "currency": "USD",
                   "groups": {"trunking-origination-local": 1.0, "phonenumbers": 0.25, "other": 0.25}}
    assert "2026-10-18" not in cc.merge_rows(rows)


def test_twilio_without_a_login_asks_for_one():
    gone = lambda argv, **kw: ok(err="Could not find profile. To create the profile, run: twilio login", code=1)  # noqa: E731
    e = cc.account_entry({"id": "twilio", "messaging": {"provider": "twilio"}, "costs": {"provider": "twilio"}},
                         3, TODAY, gone, None, {}, "h")
    assert e["error_kind"] == "auth" and e["login"]["argv"] == ["twilio", "login"]
    assert cc.login_argv({"id": "t", "costs": {"profile": "p"}}, "twilio") == ["twilio", "login", "-p", "p"]


def test_azure_split_by_resource_group_answers_one_entry_per_project_and_merges_named_groups():
    def run(argv, **kw):
        body = json.loads(argv[argv.index("--body") + 1])
        assert body["dataset"]["grouping"] == [{"type": "Dimension", "name": "ResourceGroupName"},
                                               {"type": "Dimension", "name": "ServiceName"}]
        cols = ("Cost", "UsageDate", "ResourceGroupName", "ServiceName", "Currency")
        return ok(az_answer([[2.0, 20261017, "rg-shop-pre", "Functions", "EUR"],
                             [3.0, 20261017, "rg-shop-prod", "Functions", "EUR"],
                             [1.0, 20261017, "rg-shop-prod", "Storage", "EUR"],
                             [0.5, 20261017, "rg-internal", "Key Vault", "EUR"]], cols))
    acc = {"id": "azure-x", "display_name": "Azure X", "subscriptions": [{"id": "s1"}],
           "costs": {"split": "resource_group", "parts": {"rg-shop-pre": "Shop", "rg-shop-prod": "Shop"},
                     "budgets": {"Shop": 100}}}
    by = {e["id"]: e for e in cc.account_entries(acc, 3, TODAY, run, None, {}, "h")}
    assert set(by) == {"azure-x/shop", "azure-x/rg-internal"}
    shop = by["azure-x/shop"]
    assert shop["display_name"] == "Azure X: Shop" and shop["parts"] == ["rg-shop-pre", "rg-shop-prod"]
    assert shop["days"][0]["groups"] == {"Functions": 5.0, "Storage": 1.0} and shop["budget_month"] == 100.0
    assert by["azure-x/rg-internal"]["part"] == "rg-internal" and by["azure-x/rg-internal"]["month_to_date"] == 0.5


def test_elastic_cloud_reads_the_daily_charts_of_the_organization_with_its_key():
    urls = []
    ts = int(dt.datetime(2026, 10, 17, tzinfo=dt.timezone.utc).timestamp())

    def opener(req, timeout=0):
        urls.append(req.full_url)
        assert req.headers["Authorization"] == "ApiKey ec-key"
        if req.full_url.endswith("/api/v1/organizations"):
            return Resp(json.dumps({"organizations": [{"id": "org-1", "name": "Acme"}]}).encode())
        assert "/api/v2/billing/organizations/org-1/charts" in req.full_url and "bucketing_strategy=daily" in req.full_url
        return Resp(json.dumps({"data": [{"timestamp": ts, "values": [
            {"id": "d1", "name": "main", "type": "deployment", "value": 3.5},
            {"id": "d2", "name": "lab", "type": "deployment", "value": 0}]},
            {"timestamp": (ts + 86400) * 1000, "values": [{"id": "d1", "name": "main", "value": 1.25}]}]}).encode())
    acc = {"id": "elastic-x", "costs": {"provider": "elastic", "key_ref": "keychain://elastic/me"}}
    days = cc.merge_rows(cc.elastic(acc, 3, TODAY, keychain_run("ec-key"), opener))
    assert days["2026-10-17"] == {"amount": 3.5, "currency": "USD", "groups": {"main": 3.5}}
    assert days["2026-10-18"]["amount"] == 1.25          # a timestamp in milliseconds reads as well
    assert len(urls) == 2
    urls.clear()
    acc["costs"]["organization_id"] = "org-1"
    cc.elastic(acc, 3, TODAY, keychain_run("ec-key"), opener)
    assert len(urls) == 1                                # a declared organization skips the lookup


def test_elastic_without_a_key_asks_for_one_through_the_secrets_skill():
    e = cc.account_entry({"id": "elastic-x", "costs": {"provider": "elastic", "key_ref": "keychain://elastic/me"}},
                         3, TODAY, keychain_run(None), None, {}, "h")
    assert e["error_kind"] == "auth" and e["login"]["argv"][2:4] == ["store", "keychain://elastic/me"]
    assert "cloud.elastic.co" in e["login"]["hint"]
