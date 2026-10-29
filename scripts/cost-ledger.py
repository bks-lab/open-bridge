#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""A closed month of the cost reports, frozen per cost center, and a cost statement from it.

    cost-ledger.py close --month YYYY-MM --source SRC [--source SRC ...] [--root R] [--dir D] [--replace]
    cost-ledger.py statement --month YYYY-MM --center ID [--format md|csv] [--lang en|de] [--root R] [--dir D]

`close` reads the same reports the cockpit reads (scripts/cloud-costs.py, a file or `ssh:<host>:<path>`, one per
collector), merges them by entry, and writes <dir>/YYYY-MM.json (default .bridge/ledger/costs under the root): per
cost center (workflow/cost-centers/) what was paid, what was used before credits, the credits, and each entry with
its groups; what no center names stays apart as `unassigned`. It refuses a month that is not whole and settled in
every report (a day missing, a provisional day, an account that failed), so a frozen month never holds a guess,
and it never overwrites one unless --replace, which keeps the old file beside it.

`statement` turns one center's frozen month into the lines of an invoice attachment, by the center's optional
`billing:` block: mode pass-through (the default), markup (markup_pct on top), flat (flat_amount; the costs are
listed as information) or none (costs only); basis paid (the default) or used; vat_pct (default 0). It writes
Markdown or CSV to stdout and changes nothing. It is the base of an invoice, not one: number, address and the
legal lines stay with whatever writes the invoice. Guide: docs/cloud-costs.md.
"""
from __future__ import annotations

import argparse
import calendar
import datetime as dt
import importlib.util
import json
import os
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
LEDGER = Path(".bridge") / "ledger" / "costs"
MONTHS = {"en": ["January", "February", "March", "April", "May", "June", "July", "August", "September", "October",
                 "November", "December"],
          "de": ["Januar", "Februar", "März", "April", "Mai", "Juni", "Juli", "August", "September", "Oktober",
                 "November", "Dezember"]}
TX = {"en": {"title": "Cost statement", "period": "Period", "item": "Item", "amount": "Amount", "subtotal": "Subtotal",
             "markup": "Markup {p}%", "flat": "Flat fee", "net": "Net", "vat": "VAT {p}%", "gross": "Gross",
             "info": "Costs behind the flat fee (information)", "basis": {"paid": "costs as paid",
                                                                           "used": "usage before credits"},
             "source": "Closed {at}, from the daily cost reports ({basis})."},
      "de": {"title": "Kostennachweis", "period": "Zeitraum", "item": "Position", "amount": "Betrag",
             "subtotal": "Zwischensumme", "markup": "Aufschlag {p} %", "flat": "Pauschale", "net": "Netto",
             "vat": "USt {p} %", "gross": "Brutto", "info": "Kosten hinter der Pauschale (zur Information)",
             "basis": {"paid": "Kosten wie bezahlt", "used": "Verbrauch vor Gutschriften"},
             "source": "Abgeschlossen am {at}, aus den täglichen Kostenberichten ({basis})."}}


def _resources():
    """scripts/bridge-resources.py, for reading and merging the reports and for the cost centers, exactly as the
    cockpit does, so the ledger and the card can never disagree about which entry belongs where."""
    name = "bridge_resources_for_ledger"
    if name not in sys.modules:
        spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / "bridge-resources.py")
        mod = importlib.util.module_from_spec(spec)
        sys.modules[name] = mod
        spec.loader.exec_module(mod)
    return sys.modules[name]


def _r2(x: float) -> float:
    return round(float(x) + 0.0, 2)


def month_days(month: str) -> list[str]:
    year, mon = (int(x) for x in month.split("-"))
    return [dt.date(year, mon, d).isoformat() for d in range(1, calendar.monthrange(year, mon)[1] + 1)]


def _sums(entries: list[dict]) -> dict:
    return {"paid": _r2(sum(e["paid"] for e in entries)), "used": _r2(sum(e["used"] for e in entries)),
            "credits": _r2(sum(e["credits"] for e in entries)), "entries": entries}


def close(month: str, srcs: list[str], root: Path, now: dt.datetime | None = None) -> tuple[dict | None, list[str]]:
    """The frozen month, or None and why not."""
    br = _resources()
    now = now or dt.datetime.now().astimezone()
    reports, problems = [], []
    for src in srcs:
        data, err = br.read_source(src)
        if data is None or not isinstance(data.get("accounts"), list):
            problems.append(f"{src}: {err or 'no accounts'}")
        else:
            reports.append((src, data))
    if problems:
        return None, problems
    want = month_days(month)
    centers = br.cost_centers(root)
    by_center: dict[str | None, list[dict]] = {}
    for _src, acc, _stale, _age in br._merge_costs(reports, now, 1e9):
        aid = str(acc.get("id"))
        if not acc.get("ok"):
            problems.append(f"{aid}: the account did not answer ({acc.get('error') or '?'})")
            continue
        days = {d.get("day"): d for d in acc.get("days") or [] if isinstance(d, dict)}
        missing = [d for d in want if d not in days]
        late = [d for d in want if d in days and days[d].get("provisional")]
        if missing or late:
            problems.append(f"{aid}: {len(missing)} day(s) of {month} missing, {len(late)} provisional")
            continue
        paid = sum(float(days[d].get("amount") or 0) for d in want)
        credits = sum(float(days[d].get("credits") or 0) for d in want)
        groups: dict[str, float] = {}
        for d in want:
            for g, v in (days[d].get("groups") or {}).items():
                groups[g] = groups.get(g, 0.0) + float(v or 0)
        center = br.cost_center_of(aid, centers)
        entry = {"id": aid, "display_name": acc.get("display_name") or aid, "provider": acc.get("provider"),
                 "kind": acc.get("kind"), "paid": _r2(paid), "credits": _r2(credits), "used": _r2(paid - credits),
                 "groups": {g: _r2(v) for g, v in sorted(groups.items(), key=lambda x: -x[1]) if _r2(v)}}
        by_center.setdefault(str(center["id"]) if center else None, []).append(entry)
    if problems:
        return None, problems
    newest = max(reports, key=lambda r: str(r[1].get("at") or ""))[1]
    out_centers = []
    for c in centers:
        entries = sorted(by_center.get(str(c["id"]), []), key=lambda e: e["id"])
        out_centers.append({"id": str(c["id"]), "title": str(c.get("title") or c["id"]), "persona_ref": c.get("persona_ref"),
                            "mandant_ref": c.get("mandant_ref"), **_sums(entries)})
    loose = sorted(by_center.get(None, []), key=lambda e: e["id"])
    every = [e for es in by_center.values() for e in es]
    return {"schema": 1, "kind": "cost-ledger", "month": month, "closed_at": now.isoformat(timespec="seconds"),
            "currency": newest.get("currency") or "EUR", "fx": newest.get("fx"),
            "sources": [{"source": br.source_name(s), "host": d.get("host"), "at": d.get("at")} for s, d in reports],
            "centers": out_centers, "unassigned": _sums(loose),
            "total": {k: v for k, v in _sums(every).items() if k != "entries"}}, []


def statement_lines(ledger: dict, center: dict, billing: dict) -> list[tuple[str, str, float]]:
    """(kind, label, amount) in order: item lines, then subtotal, markup or flat, net, vat, gross; for flat the
    costs come after as `info` lines."""
    mode = str(billing.get("mode") or "pass-through")
    basis = "used" if billing.get("basis") == "used" else "paid"
    vat = float(billing.get("vat_pct") or 0)
    items = [("item", e["display_name"], float(e[basis])) for e in center["entries"] if _r2(e[basis])]
    sub = sum(a for _k, _l, a in items)
    if mode == "flat":
        net = float(billing.get("flat_amount") or 0)
        lines = [("flat", "flat", net)]
    else:
        lines = items + [("subtotal", "subtotal", sub)]
        net = sub
        if mode == "markup":
            pct = float(billing.get("markup_pct") or 0)
            up = _r2(sub * pct / 100)
            lines.append(("markup", f"{pct:g}", up))
            net = sub + up
    if mode != "none":
        tax = _r2(_r2(net) * vat / 100)
        lines += [("net", "net", net), ("vat", f"{vat:g}", tax), ("gross", "gross", _r2(net) + tax)]
    if mode == "flat":
        lines += [("info", label, a) for _k, label, a in items] + [("info-sum", "subtotal", sub)]
    return [(k, l, _r2(a)) for k, l, a in lines]


def _money(x: float, lang: str) -> str:
    text = f"{x:,.2f}"
    return (text.replace(",", "\0").replace(".", ",").replace("\0", ".") + " €") if lang == "de" else f"€{text}"


def render(ledger: dict, center: dict, billing: dict, fmt: str, lang: str) -> str:
    tx = TX.get(lang, TX["en"])
    lines = statement_lines(ledger, center, billing)
    name = {"subtotal": tx["subtotal"], "net": tx["net"], "gross": tx["gross"], "flat": tx["flat"]}
    label = lambda k, l: (tx["markup"].format(p=l) if k == "markup" else tx["vat"].format(p=l) if k == "vat"  # noqa: E731
                          else name.get(l, l) if k != "item" and k != "info" else l)
    if fmt == "csv":
        csv_label = lambda k, l: (f"markup {l}%" if k == "markup" else f"vat {l}%" if k == "vat"  # noqa: E731
                                  else f"info: {l}" if k == "info" else l)
        return "item;amount_eur\n" + "".join(f"{csv_label(k, l)};{a:.2f}\n" for k, l, a in lines)
    year, mon = (int(x) for x in ledger["month"].split("-"))
    basis = "used" if billing.get("basis") == "used" else "paid"
    out = [f"# {tx['title']}: {center['title']}", "", f"**{tx['period']}:** {MONTHS[lang if lang in MONTHS else 'en'][mon - 1]} {year}",
           "", f"| {tx['item']} | {tx['amount']} |", "|---|---:|"]
    info = False
    for k, l, a in lines:
        if k.startswith("info") and not info:
            out += ["", f"**{tx['info']}**", "", f"| {tx['item']} | {tx['amount']} |", "|---|---:|"]
            info = True
        strong = k in ("net", "gross")
        text = label(k, l) if k != "info-sum" else tx["subtotal"]
        out.append(f"| {'**' + text + '**' if strong else text} | {'**' + _money(a, lang) + '**' if strong else _money(a, lang)} |")
    out += ["", tx["source"].format(at=str(ledger.get("closed_at", ""))[:10], basis=tx["basis"][basis])]
    return "\n".join(out) + "\n"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("close", "statement"):
        p = sub.add_parser(name)
        p.add_argument("--month", required=True, type=lambda s: dt.datetime.strptime(s, "%Y-%m").strftime("%Y-%m"))
        p.add_argument("--root", type=Path, default=ROOT)
        p.add_argument("--dir", type=Path, default=None, help="where closed months live (default .bridge/ledger/costs)")
    sub.choices["close"].add_argument("--source", action="append", required=True)
    sub.choices["close"].add_argument("--replace", action="store_true", help="replace a closed month, keeping the old")
    sub.choices["statement"].add_argument("--center", required=True)
    sub.choices["statement"].add_argument("--format", choices=["md", "csv"], default="md")
    sub.choices["statement"].add_argument("--lang", choices=["en", "de"], default="en")
    args = ap.parse_args(argv)
    root = args.root.resolve()
    folder = (args.dir.expanduser() if args.dir else root / LEDGER)
    path = folder / f"{args.month}.json"
    if args.cmd == "close":
        if path.exists() and not args.replace:
            print(f"cost-ledger: {args.month} is closed already ({path}); --replace keeps the old one beside it",
                  file=sys.stderr)
            return 3
        ledger, problems = close(args.month, args.source, root)
        if ledger is None:
            print(f"cost-ledger: {args.month} cannot be closed yet:\n  " + "\n  ".join(problems), file=sys.stderr)
            return 2
        folder.mkdir(parents=True, exist_ok=True)
        if path.exists():
            stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S")
            os.replace(path, folder / f"{args.month}.replaced-{stamp}.json")
        tmp = path.with_name("." + path.name + ".tmp")
        tmp.write_text(json.dumps(ledger, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, path)
        print(f"cost-ledger: closed {args.month}: {ledger['total']['paid']:.2f} {ledger['currency']} paid, "
              f"{len(ledger['centers'])} center(s), {len(ledger['unassigned']['entries'])} entry(ies) without one")
        return 0
    if not path.exists():
        print(f"cost-ledger: {args.month} is not closed ({path}); run close first", file=sys.stderr)
        return 2
    ledger = json.loads(path.read_text(encoding="utf-8"))
    center = next((c for c in ledger["centers"] if c["id"] == args.center), None)
    if center is None:
        print(f"cost-ledger: no cost center {args.center} in {args.month}", file=sys.stderr)
        return 2
    billing = {}
    src = root / "workflow" / "cost-centers" / f"{args.center}.yaml"
    try:
        data = yaml.safe_load(src.read_text(encoding="utf-8")) if src.exists() else {}
        billing = data.get("billing") if isinstance(data, dict) and isinstance(data.get("billing"), dict) else {}
    except (OSError, yaml.YAMLError):
        billing = {}
    sys.stdout.write(render(ledger, center, billing, args.format, args.lang))
    return 0


if __name__ == "__main__":
    sys.exit(main())
