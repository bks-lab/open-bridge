#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""How the cockpit is used, counted on request, and the candidates it finds left as proposals for /bridge-learn.

    cockpit-usage.py [--root R] [--state-dir D] [--days N | --since YYYY-MM-DD] [--dry-run] [--json]

Reads the click origin log (<state>/usage.jsonl and its older usage.jsonl.1, written by the cockpit: which control
was used from which place, never what about) and audit.log (its page_view lines) for a period, by default since
the last run (kept in <state>/usage-run.json; the first run looks back FIRST_DAYS days). Counts per place, area,
control and verb, and finds five kinds of candidates: a page opened before the period and not in it, an area of a
page in use that nobody clicked (the areas are those of the explain overlay, logic.js HINTS), a control used
before the period and not in it, a page left again at once, and back and forth between two pages. Each candidate
not proposed before (a pending, accepted or rejected file of the same topic) becomes one file in
work/_learning/proposals/, frontmatter per work/_learning/_schema.proposal.yaml, the words in the Bridge's
language (bridge_cockpit/text.py "usage"). --dry-run prints what it would write and keeps no run.

write_note() is the cockpit's writer of "What bothers you here?" from the explain window (verb explain_note): the
sentence with its place as a proposal in the same folder and format. Only reads the logs; writes proposals and
the run file. No model, no network.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from lib.bridge_cockpit.text import T  # noqa: E402

FIRST_DAYS = 14          # the first run, with no run before it, looks back this far
JUDGE_DAYS = 14          # what was not used is judged over at least this many days, whatever the period
MIN_VIEWS = 3            # a page opened fewer times in the period says nothing about its areas
LEAVE_S = 5              # a page left within this many seconds, with nothing done on it, was left at once
LEFT_MIN = 3             # ... this often, and in at least half of its views, makes a candidate
BACK_S = 30              # a step from one page to another and back, each within this many seconds
BACK_MIN = 3             # ... this often makes a candidate
MAX_PROPOSALS = 10       # the most proposals one run writes; the rest wait for the next (the run keeps its start)
KINDS = ("unused_page", "left_at_once", "back_and_forth", "unused_area", "unused_control")
RECOUNT = "python3 scripts/cockpit-usage.py --days 14 --dry-run"
HINTS_RE = re.compile(r"^const HINTS = \{\n(.*?)^\}", re.S | re.M)
HINT_KEY_RE = re.compile(r"^\s*'?(@?[A-Za-z][\w-]*)'?: \[")
HINT_ID_RE = re.compile(r"\['([A-Za-z][\w-]*)', '")
AUDIT_RE = re.compile(r"^(\S+) (\S+) (\S+)(.*)$")


def default_state(root: Path) -> Path:
    return Path(root) / ".bridge" / "cockpit"


def language(root: Path) -> str:
    """cockpit.language, else language.conversation, as the cockpit chooses it"""
    try:
        raw = yaml.safe_load((Path(root) / "bridge-config.yaml").read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError):
        return "en"
    cockpit = raw.get("cockpit") if isinstance(raw.get("cockpit"), dict) else {}
    conv = raw.get("language")
    conv = conv.get("conversation") if isinstance(conv, dict) else conv
    for value in (cockpit.get("language"), conv):
        if isinstance(value, str) and value:
            return value
    return "en"


def place_of(page: str, view: str | None) -> str:
    """The work tab's views are places of their own (briefing/flow); any other page is one place"""
    return f"{page}/{view}" if page == "briefing" and view and view != "-" else page


def slug(text: str) -> str:
    return re.sub(r"-+", "-", re.sub(r"[^a-z0-9]+", "-", text.lower())).strip("-") or "x"


def rel(root: Path, path: Path) -> str:
    try:
        return Path(path).resolve().relative_to(Path(root).resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


# ---------------------------------------------------------------- reading

def _lines(state: Path, name: str):
    for path in (Path(state) / f"{name}.1", Path(state) / name):
        try:
            yield from path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue


def read_clicks(state: Path) -> list[dict]:
    """The click origin log, the older file first; a line that is no event is skipped"""
    out = []
    for line in _lines(state, "usage.jsonl"):
        try:
            row = json.loads(line)
            row["t"] = dt.datetime.fromisoformat(row["at"])
        except (ValueError, KeyError, TypeError):
            continue
        if isinstance(row.get("page"), str):
            out.append(row)
    return out


def read_audit(state: Path) -> list[dict]:
    """audit.log as {t, verb, subject, fields}, the older file first, in the order written"""
    out = []
    for line in _lines(state, "audit.log"):
        m = AUDIT_RE.match(line)
        if not m:
            continue
        try:
            t = dt.datetime.fromisoformat(m.group(1))
        except ValueError:
            continue
        fields = dict(x.split("=", 1) for x in m.group(4).split() if "=" in x)
        out.append({"t": t, "verb": m.group(2), "subject": m.group(3), "fields": fields})
    return out


def known_areas(root: Path) -> dict[str, list[str]]:
    """The areas of each page as the explain overlay names them (scripts/web/logic.js HINTS), by place: the work
    tab's day columns are briefing/due, Work through briefing/flow"""
    try:
        text = (Path(root) / "scripts" / "web" / "logic.js").read_text(encoding="utf-8")
    except OSError:
        return {}
    block = HINTS_RE.search(text)
    if not block:
        return {}
    out: dict[str, list[str]] = {}
    place = None
    for line in block.group(1).splitlines():
        if line.strip().startswith("//"):
            continue
        key = HINT_KEY_RE.match(line)
        if key:
            place = {"briefing": "briefing/due", "@flow": "briefing/flow"}.get(key.group(1), key.group(1))
            out[place] = []
        if place:
            out[place] += HINT_ID_RE.findall(line)
    return out


def period(state: Path, days: int | None, since: str | None, now: dt.datetime) -> tuple[dt.datetime, dt.datetime]:
    """--days, else --since, else the last run, else FIRST_DAYS back"""
    if days is not None:
        return now - dt.timedelta(days=days), now
    if since:
        return dt.datetime.fromisoformat(since), now
    try:
        last = json.loads((Path(state) / "usage-run.json").read_text(encoding="utf-8"))["last"]
        return dt.datetime.fromisoformat(last), now
    except (OSError, ValueError, KeyError, TypeError):
        return now - dt.timedelta(days=FIRST_DAYS), now


# ---------------------------------------------------------------- counting

def count(clicks: list[dict], views: list[dict], start: dt.datetime, end: dt.datetime) -> tuple[dict, Counter, Counter]:
    """(places, views per place before start, clicks per place and control before start) for start to end"""
    inside = lambda t: start <= t <= end  # noqa: E731
    places: dict = defaultdict(lambda: {"views": 0, "clicks": 0, "areas": Counter(), "controls": Counter(),
                                        "verbs": Counter()})
    before_views, before_controls = Counter(), Counter()
    for c in clicks:
        place, n = place_of(c["page"], c.get("view")), int(c.get("n") or 1)
        control = f"{c.get('area', '-')}/{c.get('control', '-')}"
        if not inside(c["t"]):
            if c["t"] < start and c.get("kind") == "click":
                before_controls[(place, control)] += n
            continue
        p = places[place]
        if c.get("kind") == "verb":
            p["verbs"][c.get("verb", "-")] += n
        else:
            p["clicks"] += n
            p["areas"][c.get("area", "-")] += n
            p["controls"][control] += n
    for a in views:
        place = place_of(a["subject"], a["fields"].get("view"))
        if inside(a["t"]):
            places[place]["views"] += 1
        elif a["t"] < start:
            before_views[place] += 1
    return places, before_views, before_controls


def report(root: Path, state: Path, start: dt.datetime, end: dt.datetime) -> dict:
    """{start, end, places: {place: {views, clicks, areas, controls, verbs}}, candidates: [...]}. The counts, a page
    left at once and back and forth are of the period; what was not used is judged over JUDGE_DAYS at least, so a
    run soon after the last one does not call everything unused, and an area only once the click log covers them"""
    clicks, audit = read_clicks(state), read_audit(state)
    inside = lambda t: start <= t <= end  # noqa: E731
    views = [a for a in audit if a["verb"] == "page_view"]
    places = count(clicks, views, start, end)[0]
    since = min(start, end - dt.timedelta(days=JUDGE_DAYS))
    wide, before_views, before_controls = count(clicks, views, since, end)
    day = since.date().isoformat()

    found = []
    for place, n in sorted(before_views.items()):
        if not wide.get(place, {}).get("views"):
            found.append({"kind": "unused_page", "place": place, "before": n, "from": day})
    # left at once: the next line of the audit log is another page, within LEAVE_S, so nothing was done there
    period_audit = [a for a in audit if inside(a["t"])]
    left = Counter()
    for a, b in zip(period_audit, period_audit[1:]):
        if a["verb"] == b["verb"] == "page_view" and (b["t"] - a["t"]).total_seconds() <= LEAVE_S:
            here, there = place_of(a["subject"], a["fields"].get("view")), place_of(b["subject"], b["fields"].get("view"))
            if here != there:
                left[here] += 1
    for place, n in sorted(left.items()):
        if n >= LEFT_MIN and n * 2 >= places[place]["views"]:
            found.append({"kind": "left_at_once", "place": place, "views": places[place]["views"], "left": n})
    seq = [(a["t"], place_of(a["subject"], a["fields"].get("view"))) for a in views if inside(a["t"])]
    pairs = Counter()
    for (t1, a), (t2, b), (t3, c) in zip(seq, seq[1:], seq[2:]):
        if a == c != b and (t2 - t1).total_seconds() <= BACK_S and (t3 - t2).total_seconds() <= BACK_S:
            pairs["+".join(sorted((a, b)))] += 1
    for pair, n in sorted(pairs.items()):
        if n >= BACK_MIN:
            found.append({"kind": "back_and_forth", "place": pair, "times": n})
    # an area or control unused only says so where the click log ran the whole window: a new log knows no clicks yet
    covered = bool(clicks) and min(c["t"] for c in clicks) <= since
    for place, areas in sorted(known_areas(root).items() if covered else ()):
        p = wide.get(place)
        if not p or p["views"] < MIN_VIEWS:
            continue
        for area in areas:
            if not p["areas"].get(area):
                found.append({"kind": "unused_area", "place": place, "area": area, "views": p["views"], "from": day})
    for (place, control), n in sorted(before_controls.items()):
        p = wide.get(place)
        area, name = control.split("/", 1)
        if p and p["views"] >= MIN_VIEWS and p["areas"].get(area) and not p["controls"].get(control):
            found.append({"kind": "unused_control", "place": place, "area": area, "control": name, "before": n,
                          "clicks": p["areas"][area], "from": day})
    found.sort(key=lambda c: KINDS.index(c["kind"]))
    plain = {k: {**v, "areas": dict(v["areas"]), "controls": dict(v["controls"]), "verbs": dict(v["verbs"])}
             for k, v in sorted(places.items())}
    return {"start": start.isoformat(timespec="seconds"), "end": end.isoformat(timespec="seconds"),
            "places": plain, "candidates": found}


# ---------------------------------------------------------------- proposals

def topic_of(c: dict) -> str:
    return "-".join([c["kind"].replace("_", "-"), slug(c["place"]), *(slug(c[k]) for k in ("area", "control") if c.get(k))])


def proposed(proposals: Path, topic: str) -> bool:
    """Whether a proposal of this topic stands anywhere in the folder: pending, accepted or rejected"""
    pattern = re.compile(rf"^\d{{4}}-\d{{2}}-\d{{2}}-cockpit-usage-{re.escape(topic)}(-\d+)?$")
    return any(pattern.match(p.stem) for p in Path(proposals).rglob("*.md"))


def free_id(proposals: Path, base: str) -> str:
    """base, or base-2, base-3 ... when a file of that name stands already"""
    n, name = 1, base
    while (Path(proposals) / f"{name}.md").exists():
        n += 1
        name = f"{base}-{n}"
    return name


def render(pid: str, created: dt.date, severity: str, evidence: list[str], title: str, body: str,
           verification: dict | None = None) -> str:
    """One proposal file: the frontmatter /bridge-learn validates (work/_learning/_schema.proposal.yaml), then the body"""
    data = {"id": pid, "created": created, "source": {"type": "cockpit-usage", "evidence": evidence},
            "severity": severity, "status": "pending", "scope": "user",
            "target": {"type": "config", "path": "bridge-config.yaml", "action": "edit"},
            "proposal_type": "needs-triage"}
    if verification:
        data["verification"] = verification
    head = yaml.safe_dump(data, sort_keys=False, allow_unicode=True, width=1000)
    return f"---\n{head}---\n\n# {title}\n\n{body.rstrip()}\n"


def _where(c: dict) -> dict:
    page, _, view = c["place"].partition("/")
    if c["kind"] == "back_and_forth":
        page, view = ", ".join(c["place"].split("+")), "-"
    return {"page": page, "view": view or "-", "area": c.get("area", "-"), "control": c.get("control", "-")}


def proposal_of(c: dict, rep: dict, created: dt.date, lang: str, evidence: list[str]) -> tuple[str, str]:
    """(topic, text) of one candidate"""
    words = T(lang)["usage"]
    start, end = rep["start"][:10], rep["end"][:10]
    shown = {**c, "place": c["place"].replace("+", " / "), "start": c.get("from", start), "end": end,
             "seconds": LEAVE_S if c["kind"] == "left_at_once" else BACK_S}
    finding = words["finding"][c["kind"]].format(**shown)
    body = (f"## {words['finding_head']}\n\n{finding}\n\n## {words['next_head']}\n\n{words['next'][c['kind']]}\n\n"
            f"## {words['where_head']}\n\n{words['where'].format(**_where(c))}\n\n{words['recount']} `{RECOUNT}`\n")
    verification = {"kind": "deterministic", "command": RECOUNT, "before": finding}
    topic = topic_of(c)
    pid = f"{created.isoformat()}-cockpit-usage-{topic}"
    return topic, render(pid, created, "P3", evidence, words["title"][c["kind"]].format(**shown), body, verification)


def write_note(root: Path, text: str, page: str, view: str | None, area: str | None, today: dt.date, lang: str,
               state: Path | None = None) -> Path:
    """"What bothers you here?" of the explain window as a pending proposal: the sentence, the page, view and area
    it was written on. A file of its own every time (a second note on one place is -2)"""
    root = Path(root)
    words = T(lang)["usage"]
    place = place_of(page, view)
    proposals = root / "work" / "_learning" / "proposals"
    proposals.mkdir(parents=True, exist_ok=True)
    quoted = "\n".join(f"> {line}".rstrip() for line in text.strip().splitlines())
    where = words["where"].format(page=page, view=view or "-", area=area or "-", control="-")
    body = f"{quoted}\n\n## {words['where_head']}\n\n{where}\n\n{words['note_from'].format(date=today.isoformat())}\n"
    audit = rel(root, Path(state or default_state(root)) / "audit.log")
    base = f"{today.isoformat()}-cockpit-usage-note-{slug(place)}" + (f"-{slug(area)}" if area else "")
    pid = free_id(proposals, base)
    path = proposals / f"{pid}.md"
    while True:
        # two notes on one place in the same instant: the one that finds its name taken picks the next one
        try:
            with open(path, "x", encoding="utf-8") as handle:
                handle.write(render(pid, today, "P2", [f"{audit}#explain_note"], words["note_title"].format(place=place), body))
            return path
        except FileExistsError:
            pid = free_id(proposals, base)
            path = proposals / f"{pid}.md"


# ---------------------------------------------------------------- the command

def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    ap.add_argument("--root", type=Path, default=ROOT)
    ap.add_argument("--state-dir", type=Path, default=None)
    when = ap.add_mutually_exclusive_group()
    when.add_argument("--days", type=int, default=None, help="the last N days instead of since the last run")
    when.add_argument("--since", default=None, help="from this day (YYYY-MM-DD) instead of since the last run")
    ap.add_argument("--dry-run", action="store_true", help="print what would be written, write nothing")
    ap.add_argument("--json", action="store_true", help="print the counts and candidates as JSON")
    ap.add_argument("--now", default=None, help=argparse.SUPPRESS)      # the tests' clock
    args = ap.parse_args(argv)
    root = args.root.resolve()
    state = (args.state_dir or default_state(root)).resolve()
    now = dt.datetime.fromisoformat(args.now) if args.now else dt.datetime.now().replace(microsecond=0)
    start, end = period(state, args.days, args.since, now)
    rep = report(root, state, start, end)
    lang = language(root)
    proposals = root / "work" / "_learning" / "proposals"
    evidence = [rel(root, state / "usage.jsonl"), rel(root, state / "audit.log")]
    planned, seen = [], set()
    for c in rep["candidates"]:
        topic, text = proposal_of(c, rep, now.date(), lang, evidence)
        if topic in seen or proposed(proposals, topic):
            continue
        seen.add(topic)
        planned.append((f"{now.date().isoformat()}-cockpit-usage-{topic}", text))
    cut = len(planned) > MAX_PROPOSALS
    planned = planned[:MAX_PROPOSALS]
    if args.json:
        print(json.dumps({**rep, "proposals": [pid for pid, _ in planned]}, ensure_ascii=False, indent=2))
    else:
        print(f"cockpit-usage: {rep['start']} to {rep['end']}, {len(rep['places'])} place(s), "
              f"{len(rep['candidates'])} candidate(s)")
        for place, p in rep["places"].items():
            print(f"  {place}: {p['views']} views, {p['clicks']} clicks, {sum(p['verbs'].values())} verbs")
    if args.dry_run:
        for pid, text in planned:
            print(f"would write work/_learning/proposals/{pid}.md\n{text}")
        return 0
    proposals.mkdir(parents=True, exist_ok=True)
    for pid, text in planned:
        (proposals / f"{pid}.md").write_text(text, encoding="utf-8")
        print(f"wrote work/_learning/proposals/{pid}.md")
    state.mkdir(parents=True, exist_ok=True)
    # with candidates cut by the cap the next run counts from the same start, so the ones counted over this period
    # alone (left at once, back and forth) come back; the ones written stay proposed and are not written again
    last = start if cut else now
    (state / "usage-run.json").write_text(json.dumps({"last": last.isoformat(timespec="seconds")}) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
