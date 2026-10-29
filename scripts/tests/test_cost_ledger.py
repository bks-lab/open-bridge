# SPDX-License-Identifier: MIT
"""scripts/cost-ledger.py: a closed month of the cost reports, frozen per cost center, and a cost statement from it.
Reports are files written by the test; nothing reaches a provider."""
from __future__ import annotations

import datetime as dt
import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.dont_write_bytecode = True
spec = importlib.util.spec_from_file_location("cost_ledger", ROOT / "scripts" / "cost-ledger.py")
cl = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cl)


def days(month_days: int, amount: float, start="2026-09-28", n=37, credits=0.0, provisional_last=2):
    first = dt.date.fromisoformat(start)
    out = []
    for i in range(n):
        d = first + dt.timedelta(days=i)
        e = {"day": d.isoformat(), "amount": amount, "provisional": i >= n - provisional_last, "groups": {"svc": amount}}
        if credits:
            e.update(credits=credits, used=round(amount - credits, 2))
        out.append(e)
    return out


def report(tmp: Path, today="2026-11-03", accounts=None) -> Path:
    doc = {"schema": 1, "kind": "cloud-costs", "host": "my-server", "at": f"{today}T06:30:00+01:00", "currency": "EUR",
           "days": 37, "today": today, "fx": {"date": "2026-11-02", "source": "ecb", "rates": {"USD": 1.1}},
           "accounts": accounts if accounts is not None else [
               {"id": "openai-x/proj_a", "display_name": "OpenAI X: Customer A", "provider": "openai", "ok": True,
                "days": days(31, 1.0)},
               {"id": "twilio-x", "display_name": "Twilio X", "provider": "twilio", "ok": True, "days": days(31, 0.5)},
               {"id": "aws-x", "display_name": "AWS X", "provider": "aws", "ok": True, "days": days(31, 0.0, credits=-0.2)},
               {"id": "azure-y", "display_name": "Azure Y", "provider": "azure", "ok": True, "days": days(31, 2.0)}]}
    path = tmp / "costs.json"
    path.write_text(json.dumps(doc))
    return path


def bridge(tmp: Path, billing: str = "") -> Path:
    cc = tmp / "workflow" / "cost-centers"
    cc.mkdir(parents=True)
    (cc / "customer-a.yaml").write_text(
        "schema_version: 1\nscope: user\nid: customer-a\ntitle: Customer A\nmandant_ref: customer-a\npersona_ref: me\n"
        "sources: [openai-x/proj_a, twilio-x, aws-x]\n" + billing)
    return tmp


def test_close_freezes_a_month_per_cost_center_with_what_no_center_names(tmp_path):
    root = bridge(tmp_path)
    src = report(tmp_path)
    rc = cl.main(["close", "--month", "2026-10", "--source", str(src), "--root", str(root)])
    assert rc == 0
    led = json.loads((root / ".bridge" / "ledger" / "costs" / "2026-10.json").read_text())
    assert led["kind"] == "cost-ledger" and led["month"] == "2026-10" and led["currency"] == "EUR"
    a = {c["id"]: c for c in led["centers"]}["customer-a"]
    assert a["paid"] == 46.5 and a["used"] == 52.7 and a["credits"] == -6.2     # 31 x (1 + 0.5 + 0), credits 31 x -0.2
    assert [e["id"] for e in a["entries"]] == ["aws-x", "openai-x/proj_a", "twilio-x"]
    assert led["unassigned"]["paid"] == 62.0 and led["unassigned"]["entries"][0]["id"] == "azure-y"
    assert led["total"]["paid"] == 108.5 and led["fx"]["rates"] == {"USD": 1.1}


def test_close_refuses_a_month_that_is_not_settled_or_not_whole(tmp_path):
    root = bridge(tmp_path)
    # today 2026-11-01: the 31st is provisional
    src = report(tmp_path, today="2026-11-01", accounts=[
        {"id": "twilio-x", "display_name": "Twilio X", "ok": True, "days": days(31, 0.5, n=35)}])
    assert cl.main(["close", "--month", "2026-10", "--source", str(src), "--root", str(root)]) == 2
    # the window starts after the 1st
    src = report(tmp_path, accounts=[{"id": "twilio-x", "ok": True, "days": days(31, 0.5, start="2026-10-05", n=30)}])
    assert cl.main(["close", "--month", "2026-10", "--source", str(src), "--root", str(root)]) == 2
    # an account that failed
    src = report(tmp_path, accounts=[{"id": "twilio-x", "ok": False, "error": "no login", "days": []}])
    assert cl.main(["close", "--month", "2026-10", "--source", str(src), "--root", str(root)]) == 2
    assert not (root / ".bridge" / "ledger" / "costs" / "2026-10.json").exists()


def test_a_closed_month_is_replaced_only_on_request_and_the_old_one_kept(tmp_path):
    root = bridge(tmp_path)
    src = report(tmp_path)
    args = ["close", "--month", "2026-10", "--source", str(src), "--root", str(root)]
    assert cl.main(args) == 0
    assert cl.main(args) == 3
    assert cl.main(args + ["--replace"]) == 0
    kept = list((root / ".bridge" / "ledger" / "costs").glob("2026-10.replaced-*.json"))
    assert len(kept) == 1


def test_statement_passes_costs_through_with_a_markup_and_vat(tmp_path, capsys):
    root = bridge(tmp_path, "billing: {mode: markup, markup_pct: 10, basis: used, vat_pct: 19}\n")
    cl.main(["close", "--month", "2026-10", "--source", str(report(tmp_path)), "--root", str(root)])
    capsys.readouterr()
    assert cl.main(["statement", "--month", "2026-10", "--center", "customer-a", "--root", str(root), "--format", "csv"]) == 0
    lines = capsys.readouterr().out.strip().splitlines()
    assert lines[0] == "item;amount_eur"
    rows = dict(line.split(";") for line in lines[1:])
    assert rows["OpenAI X: Customer A"] == "31.00" and rows["Twilio X"] == "15.50" and rows["AWS X"] == "6.20"
    assert rows["subtotal"] == "52.70" and rows["markup 10%"] == "5.27" and rows["net"] == "57.97"
    assert rows["vat 19%"] == "11.01" and rows["gross"] == "68.98"


def test_statement_flat_fee_lists_the_costs_as_information_and_markdown_reads(tmp_path, capsys):
    root = bridge(tmp_path, "billing: {mode: flat, flat_amount: 200, vat_pct: 19}\n")
    cl.main(["close", "--month", "2026-10", "--source", str(report(tmp_path)), "--root", str(root)])
    capsys.readouterr()
    assert cl.main(["statement", "--month", "2026-10", "--center", "customer-a", "--root", str(root), "--lang", "de"]) == 0
    out = capsys.readouterr().out
    assert "Oktober 2026" in out and "Customer A" in out and "200,00 €" in out and "238,00 €" in out
    assert "46,50 €" in out                      # the costs behind the flat fee, paid basis by default


def test_statement_without_a_closed_month_or_center_says_so(tmp_path, capsys):
    root = bridge(tmp_path)
    assert cl.main(["statement", "--month", "2026-10", "--center", "customer-a", "--root", str(root)]) == 2
    cl.main(["close", "--month", "2026-10", "--source", str(report(tmp_path)), "--root", str(root)])
    assert cl.main(["statement", "--month", "2026-10", "--center", "nobody", "--root", str(root)]) == 2


def view(tmp: Path, today="2026-11-03", n=37) -> Path:
    """The cockpit's kept view: the report's entries with their cost_center, as bridge-resources.py writes it."""
    accounts = [{"id": "openai-x/proj_a", "display_name": "OpenAI X: Customer A", "ok": True, "days": days(31, 1.0, n=n)},
                {"id": "twilio-x", "display_name": "Twilio X", "ok": True, "days": days(31, 0.5, n=n)},
                {"id": "azure-y", "display_name": "Azure Y", "ok": True, "days": days(31, 2.0, n=n)}]
    rep = json.loads(report(tmp, today=today, accounts=accounts).read_text())
    centers = {"openai-x/proj_a": "customer-a", "twilio-x": "customer-a", "aws-x": "customer-a"}
    for a in rep["accounts"]:
        a["cost_center"] = centers.get(a["id"])
    rep["cost_centers"] = [{"id": "customer-a", "title": "Customer A", "persona_ref": "me"}]
    folder = tmp / ".bridge" / "resources"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "costs-view.json").write_text(json.dumps(rep))
    return folder / "costs-view.json"


def test_a_statement_of_an_open_month_comes_from_the_live_view_and_says_so(tmp_path):
    root = bridge(tmp_path)
    view(tmp_path, today="2026-10-20", n=23)                 # 28.09. to 20.10.
    st = cl.statement(root, "2026-10", center="customer-a", lang="de")
    assert st["source"] == "live" and st["closed"] is False and st["title"] == "Customer A"
    assert "Vorläufig" in st["markdown"] and st["paid"] == round(20 * 1.5, 2)     # 1st to 20th, provisional last 2
    assert st["csv"].splitlines()[0] == "item;amount_eur"


def test_a_statement_prefers_the_closed_month_and_scopes_by_persona_or_all(tmp_path):
    root = bridge(tmp_path)
    view(tmp_path)
    assert cl.main(["close", "--month", "2026-10", "--source", str(report(tmp_path)), "--root", str(root)]) == 0
    one = cl.statement(root, "2026-10", center="customer-a")
    assert one["source"] == "ledger" and one["closed"] is True and one["paid"] == 46.5
    everything = cl.statement(root, "2026-10")
    assert everything["paid"] == 108.5 and "Azure Y" in everything["markdown"] and "Customer A" in everything["markdown"]
    unassigned = cl.statement(root, "2026-10", center="none")
    assert unassigned["paid"] == 62.0
    mine = cl.statement(root, "2026-10", persona="me")
    assert mine["paid"] == 46.5 and "Azure Y" not in mine["markdown"]


def test_a_statement_without_any_data_for_the_month_says_so(tmp_path):
    root = bridge(tmp_path)
    try:
        cl.statement(root, "2026-10", center="customer-a")
        raise AssertionError("no error")
    except cl.LedgerError as e:
        assert "2026-10" in str(e)


def test_without_billing_rules_a_statement_is_costs_only_and_skips_empty_lines(tmp_path):
    root = bridge(tmp_path)
    accounts = [{"id": "openai-x/proj_a", "display_name": "OpenAI X", "ok": True, "days": days(31, 1.0)},
                {"id": "twilio-x", "display_name": "Twilio X", "ok": True, "days": days(31, 0.0)},
                {"id": "azure-y", "display_name": "Azure Y", "ok": True, "days": days(31, 2.0)}]
    cl.main(["close", "--month", "2026-10", "--source", str(report(tmp_path, accounts=accounts)), "--root", str(root)])
    one = cl.statement(root, "2026-10", center="customer-a", lang="de")
    assert "Netto" not in one["markdown"] and "USt" not in one["markdown"] and "Twilio X" not in one["markdown"]
    every = cl.statement(root, "2026-10")
    rows = every["csv"].strip().splitlines()
    # each project's subtotal right after its own lines, the total last; no empty line
    assert rows == ["project;item;amount_eur", "Customer A;OpenAI X;31.00", "Customer A;subtotal;31.00",
                    "No project;Azure Y;62.00", "No project;subtotal;62.00", ";total;93.00"]
