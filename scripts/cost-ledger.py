#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""A closed month of the cost reports, frozen per cost center, and a cost statement from it.

    cost-ledger.py close --month YYYY-MM --source SRC [--source SRC ...] [--root R] [--dir D] [--replace]
    cost-ledger.py statement --month YYYY-MM [--center ID|all|none] [--persona ID] [--format md|csv] [--lang en|de]

`close` reads the same reports the cockpit reads (scripts/cloud-costs.py, a file or `ssh:<host>:<path>`, one per
collector), merges them by entry, and writes <dir>/YYYY-MM.json (default .bridge/ledger/costs under the root): per
cost center (workflow/cost-centers/) what was paid, what was used before credits, the credits, and each entry with
its groups; what no center names stays apart as `unassigned`. It refuses a month that is not whole and settled in
every report (a day missing, a provisional day, an account that failed), so a frozen month never holds a guess,
and it never overwrites one unless --replace, which keeps the old file beside it.

`statement` turns a frozen month into the lines of an invoice attachment; a month that is not closed comes from the
cockpit's kept view (.bridge/resources/costs-view.json) and says so. It covers one center, every center of a persona,
the entries of no center (`none`) or everything (`all`). For one center it bills by that center's optional
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
             "source": "Closed {at}, from the daily cost reports ({basis}).",
             "live": "Provisional: the month is not closed. From the running cost report of {at}; the last days can "
                     "still change.", "all": "All projects", "none": "No project", "total": "Total"},
      "de": {"title": "Kostennachweis", "period": "Zeitraum", "item": "Position", "amount": "Betrag",
             "subtotal": "Zwischensumme", "markup": "Aufschlag {p} %", "flat": "Pauschale", "net": "Netto",
             "vat": "USt {p} %", "gross": "Brutto", "info": "Kosten hinter der Pauschale (zur Information)",
             "basis": {"paid": "Kosten wie bezahlt", "used": "Verbrauch vor Gutschriften"},
             "source": "Abgeschlossen am {at}, aus den täglichen Kostenberichten ({basis}).",
             "live": "Vorläufig: der Monat ist nicht abgeschlossen. Aus dem laufenden Kostenbericht vom {at}; die "
                     "letzten Tage können sich noch ändern.", "all": "Alle Projekte", "none": "Ohne Projekt",
             "total": "Summe"}}


class LedgerError(RuntimeError):
    """A statement that cannot be made: no closed month and no view that holds it, or no such center."""


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
    # no billing rules at all: the costs and their sum, nothing to tax or mark up
    mode = str(billing.get("mode") or "pass-through") if billing else "none"
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


def _note(ledger: dict, tx: dict, basis: str, live: bool) -> str:
    """The last line: where the figures come from, a closed month or the running report (provisional)."""
    if live:
        return tx["live"].format(at=str(ledger.get("closed_at") or "")[:16].replace("T", " "))
    return tx["source"].format(at=str(ledger.get("closed_at", ""))[:10], basis=tx["basis"][basis])


def render(ledger: dict, center: dict, billing: dict, fmt: str, lang: str, live: bool = False) -> str:
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
    out += ["", _note(ledger, tx, basis, live)]
    return "\n".join(out) + "\n"


def live_month(view: dict, month: str) -> dict | None:
    """A month as `close` would freeze it, from the cockpit's kept view and without its checks: the days of the
    month the view holds, each entry in the cost center the view gave it. None when no entry has a day in it."""
    want = set(month_days(month))
    by_center: dict[str | None, list[dict]] = {}
    for acc in view.get("accounts") or []:
        if not isinstance(acc, dict) or not acc.get("ok"):
            continue
        mine = [d for d in acc.get("days") or [] if isinstance(d, dict) and d.get("day") in want]
        if not mine:
            continue
        paid = sum(float(d.get("amount") or 0) for d in mine)
        credits = sum(float(d.get("credits") or 0) for d in mine)
        groups: dict[str, float] = {}
        for d in mine:
            for g, v in (d.get("groups") or {}).items():
                groups[g] = groups.get(g, 0.0) + float(v or 0)
        by_center.setdefault(acc.get("cost_center"), []).append(
            {"id": str(acc.get("id")), "display_name": acc.get("display_name") or acc.get("id"), "provider": acc.get("provider"),
             "paid": _r2(paid), "credits": _r2(credits), "used": _r2(paid - credits),
             "groups": {g: _r2(v) for g, v in sorted(groups.items(), key=lambda x: -x[1]) if _r2(v)}})
    if not by_center:
        return None
    centers = [{"id": str(c.get("id")), "title": str(c.get("title") or c.get("id")), "persona_ref": c.get("persona_ref"),
                **_sums(sorted(by_center.get(c.get("id"), []), key=lambda e: e["id"]))}
               for c in view.get("cost_centers") or [] if isinstance(c, dict) and c.get("id")]
    return {"month": month, "closed_at": view.get("at"), "currency": view.get("currency") or "EUR", "centers": centers,
            "unassigned": _sums(sorted(by_center.get(None, []), key=lambda e: e["id"]))}


def _billing(root: Path, center_id: str) -> dict:
    src = root / "workflow" / "cost-centers" / f"{center_id}.yaml"
    try:
        data = yaml.safe_load(src.read_text(encoding="utf-8")) if src.exists() else {}
    except (OSError, yaml.YAMLError):
        return {}
    return data.get("billing") if isinstance(data, dict) and isinstance(data.get("billing"), dict) else {}


def _render_groups(ledger: dict, title: str, groups: list[tuple[str, list[dict]]], fmt: str, lang: str,
                   live: bool = False) -> str:
    """Several centers (a persona, everything): each with its entries and subtotal, then the total; costs only."""
    tx = TX.get(lang, TX["en"])
    groups = [(t, [e for e in es if _r2(e["paid"])]) for t, es in groups]
    groups = [(t, es) for t, es in groups if es]
    total = sum(e["paid"] for _t, es in groups for e in es)
    if fmt == "csv":
        rows = []
        for t, es in groups:
            rows += [f"{t};{e['display_name']};{e['paid']:.2f}" for e in es]
            rows.append(f"{t};subtotal;{sum(e['paid'] for e in es):.2f}")
        return "project;item;amount_eur\n" + "\n".join(rows + [f";total;{total:.2f}"]) + "\n"
    year, mon = (int(x) for x in ledger["month"].split("-"))
    out = [f"# {tx['title']}: {title}", "", f"**{tx['period']}:** {MONTHS[lang if lang in MONTHS else 'en'][mon - 1]} {year}"]
    for t, es in groups:
        out += ["", f"## {t}", "", f"| {tx['item']} | {tx['amount']} |", "|---|---:|"]
        out += [f"| {e['display_name']} | {_money(e['paid'], lang)} |" for e in es]
        out.append(f"| {tx['subtotal']} | {_money(sum(e['paid'] for e in es), lang)} |")
    out += ["", f"**{tx['total']}: {_money(total, lang)}**", "", _note(ledger, tx, "paid", live)]
    return "\n".join(out) + "\n"


def statement(root: Path, month: str, center: str | None = "all", persona: str | None = "all", lang: str = "en",
              ledger_dir: Path | None = None) -> dict:
    """The cost statement of a month for one center, a persona's centers, the unassigned entries or everything:
    from the closed month when there is one, else from the cockpit's kept view (provisional). The figures, the
    Markdown and the CSV, so a page and a terminal show the same."""
    tx = TX.get(lang, TX["en"])
    center, persona = center or "all", persona or "all"
    path = (ledger_dir or root / LEDGER) / f"{month}.json"
    view: dict = {}
    try:
        view = json.loads((root / ".bridge" / "resources" / "costs-view.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        view = {}
    if path.exists():
        led, source = json.loads(path.read_text(encoding="utf-8")), "ledger"
    else:
        led, source = (live_month(view, month) if isinstance(view, dict) else None), "live"
        if led is None:
            raise LedgerError(f"no costs for {month}: the month is not closed and the cost report holds no day of it")
    centers = [c for c in led["centers"] if persona == "all" or c.get("persona_ref") == persona]
    if center == "none":
        groups, title = [(tx["none"], led["unassigned"]["entries"])], tx["none"]
    elif center != "all":
        one = next((c for c in centers if c["id"] == center), None)
        if one is None:
            raise LedgerError(f"no cost center {center} in {month}")
        groups, title = [(one["title"], one["entries"])], one["title"]
    else:
        groups = [(c["title"], c["entries"]) for c in centers if c["entries"]]
        if persona == "all" and led["unassigned"]["entries"]:
            groups.append((tx["none"], led["unassigned"]["entries"]))
        names = {c.get("persona_ref"): c.get("persona_title") for c in view.get("cost_centers") or [] if isinstance(c, dict)}
        title = tx["all"] if persona == "all" else str(names.get(persona) or persona)
    entries = [e for _t, es in groups for e in es]
    live = source == "live"
    if center not in ("all", "none"):
        one = next(c for c in centers if c["id"] == center)
        md = render(led, one, _billing(root, center), "md", lang, live)
        csv = render(led, one, _billing(root, center), "csv", lang)
    else:
        md, csv = _render_groups(led, title, groups, "md", lang, live), _render_groups(led, title, groups, "csv", lang)
    return {"month": month, "source": source, "closed": source == "ledger", "title": title,
            "scope": {"center": center, "persona": persona}, "currency": led.get("currency") or "EUR",
            "paid": _r2(sum(e["paid"] for e in entries)), "used": _r2(sum(e["used"] for e in entries)),
            "credits": _r2(sum(e["credits"] for e in entries)), "markdown": md, "csv": csv}


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
    sub.choices["statement"].add_argument("--center", default="all", help="a cost center id, all (default) or none")
    sub.choices["statement"].add_argument("--persona", default="all", help="only the centers of this persona_ref")
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
    try:
        st = statement(root, args.month, args.center, args.persona, args.lang, folder)
    except LedgerError as e:
        print(f"cost-ledger: {e}", file=sys.stderr)
        return 2
    sys.stdout.write(st["markdown"] if args.format == "md" else st["csv"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
