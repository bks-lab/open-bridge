# SPDX-License-Identifier: MIT
"""The day book of the start page: what the model showed, kept per day in <state_dir>/days.json.

A quota (a gauge in percent of a window of a day or more) adds up what it used each day: every reading
adds its rise since the reading before, and a fall is a reset of its window, from which it counts again
from zero. Overnight use counts to the day it is first seen on. A count (what waits on you, the waiting
agent tabs, the number of every page) keeps its last value of each day, so the page can say what it was
the day before. Two weeks are kept, nothing older.

Ids are the ones the page makes (logic.js homeCatalog): `q:<section>:<slug of the label>`, `c:waiting`,
`c:tabs`, `p:<page>`. The week's closed tasks come from work/done/<YYYY-MM>/<slug>/STATUS.md, `closed:`.
"""
from __future__ import annotations

import datetime as dt
import re
import threading
import unicodedata
from pathlib import Path
from typing import Callable

from .model import iso_date
from .store import atomic_write_json, read_json

KEEP_DAYS = 15
SHOW_DAYS = 7
PERCENT_RE = re.compile(r":\s*[\d.,]+\s*%\s*$")
CLOSED_RE = re.compile(r"^closed:\s*[\"']?(\d{4}-\d{2}-\d{2})", re.M)
TITLE_RE = re.compile(r"^#\s+(.+)$", re.M)


def slug(text: str) -> str:
    """A label as part of an id, as logic.js tileSlug makes it"""
    plain = unicodedata.normalize("NFD", str(text or "")).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-")[:60]


def quota_id(section: str, title: str) -> str:
    return f"q:{section}:{slug(PERCENT_RE.sub('', str(title or '')))}"


def quotas(model: dict) -> dict:
    """{id: value} of every gauge in percent of a window of a day or more on the model's pages"""
    out = {}
    for page in model.get("pages") or []:
        for sec in page.get("sections") or []:
            for it in sec.get("items") or []:
                m = it.get("meter") if isinstance(it, dict) else None
                if isinstance(m, dict) and m.get("unit") == "%" and m.get("max") and (m.get("window_h") or 0) >= 24:
                    out[quota_id(sec.get("id", ""), it.get("title", ""))] = float(m.get("value") or 0)
    return out


def counts(model: dict) -> dict:
    c = model.get("counts") or {}
    out = {"c:waiting": int(c.get("now") or 0), "c:tabs": int(c.get("waiting_tabs") or 0)}
    for page in model.get("pages") or []:
        badge = page.get("badge")
        if isinstance(badge, dict) and isinstance(badge.get("n"), int):
            out[f"p:{page.get('id')}"] = badge["n"]
    return out


class DayBook:
    def __init__(self, state_dir: Path, clock: Callable[[], float]):
        self.path = Path(state_dir) / "days.json"
        self.clock = clock
        self.lock = threading.Lock()
        data = read_json(self.path)
        data = data if isinstance(data, dict) else {}
        quota, cnt = data.get("quota"), data.get("counts")
        self.quota: dict = quota if isinstance(quota, dict) else {}
        self.counts: dict = cnt if isinstance(cnt, dict) else {}

    def record(self, model: dict) -> None:
        """Take in a model; writes only when something changed"""
        today = iso_date(self.clock())
        changed = False
        with self.lock:
            for qid, value in quotas(model).items():
                days = self.quota.setdefault(qid, {})
                last = days[max(days)]["last"] if days else None
                if last is not None and value == last:
                    continue
                rise = 0.0 if last is None else value - last if value >= last else value
                day = days.setdefault(today, {"used": 0.0, "last": value})
                day["used"] = round(day["used"] + rise, 2)
                day["last"] = value
                changed = True
            for cid, n in counts(model).items():
                days = self.counts.setdefault(cid, {})
                if days.get(today) != n:
                    days[today] = n
                    changed = True
            if changed:
                for book in (self.quota, self.counts):
                    for days in book.values():
                        for old in sorted(days)[:-KEEP_DAYS]:
                            del days[old]
                atomic_write_json(self.path, {"v": 1, "quota": self.quota, "counts": self.counts})

    def view(self) -> dict:
        """For the page: a quota's use today and on its last seven days, a count's value the day before"""
        today = iso_date(self.clock())
        with self.lock:
            quota = {}
            for qid, days in self.quota.items():
                shown = sorted(days)[-SHOW_DAYS:]
                quota[qid] = {"today": days.get(today, {}).get("used", 0),
                              "days": [{"date": d, "used": days[d]["used"]} for d in shown]}
            before = {}
            for cid, days in self.counts.items():
                earlier = [d for d in days if d < today]
                if earlier:
                    d = max(earlier)
                    before[cid] = {"before": days[d], "date": d}
            return {"quota": quota, "counts": before}


def week_done(root: Path, today: dt.date) -> dict:
    """The tasks closed since this week's Monday, newest first, from work/done/<YYYY-MM>/<slug>/STATUS.md"""
    monday = today - dt.timedelta(days=today.weekday())
    items = []
    months = {monday.strftime("%Y-%m"), today.strftime("%Y-%m")}
    for month in sorted(months):
        base = Path(root) / "work" / "done" / month
        if not base.is_dir():
            continue
        for status in base.glob("*/STATUS.md"):
            try:
                text = status.read_text(encoding="utf-8", errors="replace")[:4000]
            except OSError:
                continue
            m = CLOSED_RE.search(text)
            if not m or not monday.isoformat() <= m.group(1) <= today.isoformat():
                continue
            t = TITLE_RE.search(text)
            # a closed task or an ended stream (task.py keeps was_stream): the page names which
            stream = re.search(r"^was_stream:\s*true\s*$", text.split("\n---", 1)[0], re.M | re.I) is not None
            items.append({"slug": status.parent.name, "title": (t.group(1).strip() if t else status.parent.name)[:160],
                          "closed": m.group(1), "work_kind": "done_stream" if stream else "done_task"})
    items.sort(key=lambda x: (x["closed"], x["slug"]), reverse=True)
    return {"count": len(items), "since": monday.isoformat(), "items": items[:20]}
