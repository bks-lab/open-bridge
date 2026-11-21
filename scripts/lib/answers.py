# SPDX-License-Identifier: MIT
"""The four answers every point takes, in one place.

Every point answers two questions: who is on the move, and when. The buckets say the first (you today, you
without a day, the Bridge, anyone else); the answers move a point between them. There are exactly four, the
same on every card, every view, every page that shows a point and in the printed briefing, in this order:

  do        "Do it" / "Mach das", the primary one: the Bridge takes the next step, the one the card's
            "next" sentence names. An agent tab that asks puts its own answers in this place; a task gets
            an agent on its next step and moves to "I'll do" as running; a waiting point gets a nudge
            written as a DRAFT, never sent, and stands in Do as a ready draft; an inbox item gets its yes
            and runs as the briefing runs it.
  later     "Later" / "Später": tomorrow, Monday, in a week, a picked day, or the watch list. A day puts the
            point off until that day (it comes back by itself); the watch list parks it without a day (a
            task: status backlog). On a waiting point Later keeps it with the same person.
  done      "Done" / "Erledigt". A stream is done for this time and runs on.
  obsolete  "Obsolete" / "Veraltet", quiet and last, confirmed in place: closed as not done with a note.

Under "More" only: who has it (sets next.who), the tab, the fields, a free question.

The briefing's answer words ("3 do", "3 später montag") and the words of the answers before them (ja, los,
nachfassen, einplanen, nicht jetzt, warten, parken, behalten, streichen) are parsed here (`parse`), and
what an answer does to a row of each kind is a table here (`effect`): the briefing agent reads its commands
(skills/briefing/references/control.md), the cockpit its verb, so neither derives them again. Contract:
scripts/tests/test_answers.py.
"""
from __future__ import annotations

import datetime as dt
import re

ANSWERS = ("do", "later", "done", "obsolete")
PRIMARY = "do"
LATER_CHOICES = ("tomorrow", "monday", "week", "pick", "list")
MORE = ("owner", "tab", "fields", "ask")
#: the day a point on the watch list is put off to: a day nobody reaches, so it never comes back by itself
LIST_DAY = "9999-12-31"
#: the answer a letter picks ("3b"), the same for every bucket
LETTERS = dict(zip("abcd", ANSWERS))

WORDS = {
    "en": {
        "answer_do": "Do it", "answer_later": "Later", "answer_done": "Done", "answer_obsolete": "Obsolete",
        "say_do": "do", "say_later": "later", "say_done": "done", "say_obsolete": "obsolete",
        "later_tomorrow": "tomorrow", "later_monday": "Monday", "later_week": "in a week",
        "later_pick": "pick a day", "later_list": "watch list",
        "more_owner": "With …", "more_tab": "To the tab", "more_fields": "Fields", "more_ask": "Ask",
        "more": "More", "done_stream": "done for this time", "obsolete_confirm": "Really obsolete?",
    },
    "de": {
        "answer_do": "Mach das", "answer_later": "Später", "answer_done": "Erledigt", "answer_obsolete": "Veraltet",
        "say_do": "mach", "say_later": "später", "say_done": "erledigt", "say_obsolete": "veraltet",
        "later_tomorrow": "morgen", "later_monday": "Montag", "later_week": "in einer Woche",
        "later_pick": "Tag wählen", "later_list": "Merkliste",
        "more_owner": "Liegt bei …", "more_tab": "Zum Tab", "more_fields": "Felder", "more_ask": "Fragen",
        "more": "Mehr", "done_stream": "für diesmal erledigt", "obsolete_confirm": "Wirklich veraltet?",
    },
}


def words(lang: str | None) -> dict:
    """Every word of the answers in a language; one this table does not know speaks English."""
    return dict(WORDS.get(str(lang or "en").lower()[:2], WORDS["en"]))


def answer_defs(lang: str | None) -> list:
    """The four answers as a page draws them: [{id, label, say, primary, quiet, confirm}], in their order"""
    w = words(lang)
    return [{"id": a, "label": w[f"answer_{a}"], "say": w[f"say_{a}"], "primary": a == PRIMARY,
             "quiet": a == "obsolete", "confirm": a == "obsolete"} for a in ANSWERS]


def later_defs(lang: str | None) -> list:
    w = words(lang)
    return [{"id": c, "label": w[f"later_{c}"]} for c in LATER_CHOICES]


def more_defs(lang: str | None) -> list:
    w = words(lang)
    return [{"id": c, "label": w[f"more_{c}"]} for c in MORE]


def defs(lang: str | None) -> dict:
    """Everything a page needs to offer the answers, the view's `answers` block"""
    return {"answers": answer_defs(lang), "later": later_defs(lang), "more": more_defs(lang),
            "list_day": LIST_DAY, "words": words(lang)}


def is_list_day(value) -> bool:
    """Whether a put-off day is the watch list's (any day of its year: nobody reaches it)"""
    return str(value or "")[:4] == LIST_DAY[:4]


# ---------------------------------------------------------------- the day of a Later

WEEKDAYS = {"monday": 0, "montag": 0, "tuesday": 1, "dienstag": 1, "wednesday": 2, "mittwoch": 2,
            "thursday": 3, "donnerstag": 3, "friday": 4, "freitag": 4, "saturday": 5, "samstag": 5,
            "sunday": 6, "sonntag": 6}


def _next_weekday(today: dt.date, wd: int) -> dt.date:
    return today + dt.timedelta(days=(wd - today.weekday() - 1) % 7 + 1)


def later_until(choice: str | None, today: dt.date, day=None) -> str:
    """The day a Later puts a point off to, as YYYY-MM-DD; the watch list is LIST_DAY. No choice is tomorrow.
    A picked day must lie after today."""
    choice = choice or "tomorrow"
    if choice == "tomorrow":
        return (today + dt.timedelta(days=1)).isoformat()
    if choice == "monday":
        return _next_weekday(today, 0).isoformat()
    if choice == "week":
        return (today + dt.timedelta(days=7)).isoformat()
    if choice == "list":
        return LIST_DAY
    if choice == "pick":
        try:
            when = dt.date.fromisoformat(str(day)[:10])
        except ValueError:
            raise ValueError(f"no day to put it off to: {day!r}") from None
        if when <= today:
            raise ValueError(f"{when} is not after today")
        return when.isoformat()
    raise ValueError(f"no such Later: {choice!r}")


DOTTED = re.compile(r"^(\d{1,2})\.(\d{1,2})\.?(\d{4})?$")


def _day_of(text: str, today: dt.date) -> tuple | None:
    """(choice, until) of the words after a Later ("montag", "in einer woche", "3.12.", "2026-12-03"), else None"""
    t = " ".join(text.lower().split())
    if not t:
        return None
    if t in ("morgen", "tomorrow"):
        return "tomorrow", later_until("tomorrow", today)
    if t in ("montag", "monday"):
        return "monday", later_until("monday", today)
    if t in ("woche", "week", "in einer woche", "in a week", "nächste woche", "next week"):
        return "week", later_until("week", today)
    if t in ("merkliste", "liste", "list", "watch list", "watchlist"):
        return "list", LIST_DAY
    if t in WEEKDAYS:
        return "pick", _next_weekday(today, WEEKDAYS[t]).isoformat()
    m = DOTTED.match(t)
    try:
        if m:
            year = int(m.group(3)) if m.group(3) else today.year
            when = dt.date(year, int(m.group(2)), int(m.group(1)))
            if not m.group(3) and when <= today:
                when = when.replace(year=year + 1)
            return "pick", later_until("pick", today, when.isoformat())
        if re.match(r"^\d{4}-\d{2}-\d{2}$", t):
            return "pick", later_until("pick", today, t)
    except ValueError:
        return None
    return None


# ---------------------------------------------------------------- the answer words

#: word -> (answer, the Later it means). The four in both languages, then the words of the answers before them.
OWN = {"mach": "do", "mach das": "do", "do": "do", "do it": "do", "später": "later", "spaeter": "later",
       "later": "later", "erledigt": "done", "done": "done", "veraltet": "obsolete", "obsolete": "obsolete"}
ALIASES = {
    "ja": ("do", None), "yes": ("do", None), "los": ("do", None), "go": ("do", None),
    "nachfassen": ("do", None), "nudge": ("do", None),
    "einplanen": ("later", "pick"), "schedule": ("later", "pick"),
    "nicht jetzt": ("later", "tomorrow"), "not now": ("later", "tomorrow"),
    "warten": ("later", "tomorrow"), "wait": ("later", "tomorrow"),
    "parken": ("later", "list"), "park": ("later", "list"),
    "behalten": ("later", "tomorrow"), "keep": ("later", "tomorrow"),
    "streichen": ("obsolete", None), "drop": ("obsolete", None),
}
_PHRASES = sorted(set(OWN) | set(ALIASES), key=len, reverse=True)
# a number that starts an answer: at the start or after a space or separator, a word after it ("3 später", "1a");
# the digits of a day ("3.12.", "2026-12-03") start none
_START = re.compile(r"(?:^|(?<=[\s,;]))(\d+)(?=\s*[^\W\d_])")


def _one(nr: int, said: str, today: dt.date) -> dict:
    said = " ".join(said.strip(" .,;:").split())
    low = said.lower()
    out = {"nr": nr, "answer": None, "word": said, "choice": None, "until": None, "alias": False}
    if len(low) == 1 and low in LETTERS:
        out["answer"] = LETTERS[low]
    else:
        word = next((p for p in _PHRASES if low == p or low.startswith(p + " ")), None)
        if word is None:
            return out
        rest = low[len(word):].strip()
        if word in OWN:
            out["answer"] = OWN[word]
        else:
            out["answer"], out["choice"] = ALIASES[word]
            out["alias"] = True
        if out["answer"] == "later":
            day = _day_of(rest, today)
            if day:
                out["choice"], out["until"] = day
        out["word"] = word
    if out["answer"] == "later" and out["until"] is None:
        if out["choice"] in (None, "pick"):
            out["choice"] = "tomorrow"
        out["until"] = later_until(out["choice"], today)
    return out


def parse(text: str, today: dt.date) -> list:
    """The answers in a reply to the briefing: "1 mach, 3 später montag 5 veraltet", "1a 3b". Each numbered
    part is {nr, answer (one of ANSWERS, None for a word that is none), word, choice, until, alias}; a Later
    without a day is tomorrow. Text without a number answers nothing."""
    text = str(text or "")
    starts = list(_START.finditer(text))
    out = []
    for n, m in enumerate(starts):
        end = starts[n + 1].start() if n + 1 < len(starts) else len(text)
        said = text[m.end():end].strip(" \t\n,;")
        if said:
            out.append(_one(int(m.group(1)), said, today))
    return out


# ---------------------------------------------------------------- what an answer does

KINDS = ("tab", "inbox", "task", "stream", "waiting", "issue", "other")


def row_kind(row: dict) -> str:
    """What a point is, as the answers tell it apart: an agent tab, a point waiting on someone else, an inbox
    item, a stream, a task, an issue or pull request, anything else"""
    if row.get("tab"):
        return "tab"
    if row.get("bucket") == "waiting":
        return "waiting"
    if row.get("inbox_id"):
        return "inbox"
    if row.get("task"):
        return "stream" if row.get("stream") else "task"
    if row.get("ref"):
        return "issue"
    return "other"


OBSOLETE_NOTE = "veraltet"
OBSOLETE_REASON = "Wird nicht gemacht: veraltet"


def effect(answer: str, row: dict, until: str | None = None) -> dict:
    """What `answer` does to `row`: {answer, kind, cockpit: {verb, args}, cli: [briefing commands], then: the
    bucket or place the point stands in afterwards} and the facts a page says beside it (running, draft_only,
    own_answers, stream_continues, github). `until` is a Later's day (later_until), LIST_DAY for the watch list."""
    if answer not in ANSWERS:
        raise ValueError(f"no such answer: {answer!r}")
    kind = row_kind(row)
    item, slug = row.get("inbox_id"), row.get("task")
    who = row.get("who")
    out: dict = {"answer": answer, "kind": kind, "cli": []}

    def be(verb, then, cli=(), **args):
        out.update(cockpit={"verb": verb, "args": args}, then=then, cli=list(cli))
        return out

    if answer == "do":
        if kind == "tab":
            out["own_answers"] = True           # the tab's own answers stand in this place
            return be("tab_answer", "delegate")
        if kind == "waiting":
            out["draft_only"] = True            # never sent: the draft stands in Do for the person
            return be("nudge", "do")
        if item:
            return be("do_it", "delegate", [f"inbox.py approve {item}", "inbox.py run"], yes=True)
        out["running"] = True
        return be("do_it", "delegate")
    if answer == "later":
        until = until or ""
        parked = is_list_day(until)
        if kind == "waiting":
            # stays with the same person until the day
            if item:
                return be("runs_on", "waiting", [f"inbox.py defer {item} --until {until}" + (f" --on {who}" if who else "")],
                          until=until, **({"on": who} if who else {}))
            if slug:
                return be("runs_on", "waiting", [f"task.py wait {slug} --until {until}"], until=until,
                          **({"on": who} if who else {}))
            return be("hide", "waiting", until=until)
        if item:
            return be("later", "list" if parked else "later", [f"inbox.py defer {item} --until {until}"], until=until)
        if kind == "task" and parked:
            return be("task_park", "list", [f'task.py status {slug} backlog --note "Parked: on the watch list"'])
        if kind in ("task", "stream"):
            return be("later", "list" if parked else "later", until=until)
        return be("hide", "list" if parked else "later", until=until)
    if answer == "done":
        if kind == "stream":
            out["stream_continues"] = True
            return be("note", "done", [f'task.py note {slug} "done for this time"'])
        if item:
            return be("settle", "done", [f'inbox.py close {item} --note "done"'], outcome="done")
        if slug:
            return be("settle", "done", [f"task.py close {slug}"], outcome="done")
        if kind == "issue":
            out["github"] = "untouched"         # hidden here, never closed on GitHub
        return be("settle", "done", outcome="done")
    # obsolete: closed as not done, with a note
    if item:
        return be("settle", "done", [f'inbox.py drop {item} --note "{OBSOLETE_NOTE}" --reason outdated'],
                  outcome="not_doing", reason="outdated")
    if kind == "stream" or (row.get("stream") and slug):
        return be("settle", "done", [f'task.py close {slug} --stream --declined --reason "{OBSOLETE_REASON}"'],
                  outcome="not_doing", stream=True)
    if slug:
        return be("settle", "done", [f'task.py close {slug} --declined --reason "{OBSOLETE_REASON}"'], outcome="not_doing")
    if kind == "issue":
        out["github"] = "untouched"
    return be("settle", "done", outcome="not_doing")
