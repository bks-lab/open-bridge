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


# small words before a day ("am montag", "bis montag", "next monday") and after it ("montag bitte"): no day of their own
DAY_LEAD = ("am", "bis", "auf", "zum", "ab", "nächsten", "naechsten", "kommenden", "on", "until", "by", "next", "this")
DAY_TAIL = ("und", "and", "bitte", "please", "danke", "thanks")


def _day_of(text: str, today: dt.date) -> tuple | None:
    """(choice, until) of the words after a Later ("montag", "am montag", "in einer woche", "3.12.", "2026-12-03"), else
    None. A small word before the day or after it is no part of it (round 2 of the four answers: "am montag" fell
    back to tomorrow)"""
    words = " ".join(text.lower().replace(",", " ").split()).split()
    while words and words[-1] in DAY_TAIL:
        words.pop()
    while len(words) > 1 and words[0] in DAY_LEAD:
        words.pop(0)
    t = " ".join(words)
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
_START = re.compile(r"(?:^|(?<=[\s,;]))(\d+)(?!\s*(?:und|and)\s+\d)(?=\s*[:)]?\s*[^\W\d_])", re.I)
# a number that shares the answer of the next one ("3, 5 erledigt"): digits alone between separators
_SHARED = re.compile(r"(?:^|(?<=[\s,;]))(\d+)(?=\s*(?:,|\bund\b|\band\b)\s*\d)")


def _one(nr: int, said: str, today: dt.date) -> dict:
    said = " ".join(said.strip(" .,;:").split())
    low = said.lower()
    out = {"nr": nr, "answer": None, "word": said, "choice": None, "until": None, "alias": False}
    if len(low) == 1 and low in LETTERS:
        out["answer"] = LETTERS[low]
    else:
        # a word ends at a blank or a mark ("erledigt, danke"), never inside a longer word
        word = next((p for p in _PHRASES if low == p or (low.startswith(p) and not low[len(p)].isalnum())), None)
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
        said = text[m.end():end].strip(" \t\n,;:)")
        # "3 later monday and 4 done": the joining word belongs to neither answer
        said = re.sub(r"(?:\s+(?:und|and))+\s*$", "", said, flags=re.I)
        if said:
            # the numbers just before it that have no word of their own share this one ("3, 5 erledigt")
            before = text[(starts[n - 1].end() if n else 0):m.start()]
            joined = before + m.group(1)
            shared = [int(x.group(1)) for x in _SHARED.finditer(joined)
                      if x.end() <= len(before) and not _START.match(joined, x.start())]
            for nr in shared:
                out.append(_one(nr, said, today))
            out.append(_one(int(m.group(1)), said, today))
    return out


# ---------------------------------------------------------------- what an answer does

KINDS = ("tab", "inbox", "task", "stream", "waiting", "issue", "other")


def row_kind(row: dict) -> str:
    """What a point is, as the answers tell it apart: an agent tab, a stream (also one that waits: Done is done for
    this time and Obsolete ends it, whatever bucket it stands in), a point waiting on someone else, an inbox item, a
    task, an issue or pull request, anything else"""
    if row.get("tab"):
        return "tab"
    if _is_stream(row):
        return "stream"
    if row.get("bucket") == "waiting":
        return "waiting"
    if row.get("inbox_id"):
        return "inbox"
    if row.get("task"):
        return "task"
    if row.get("ref"):
        return "issue"
    return "other"


def _is_stream(row: dict) -> bool:
    """A stream's own row (never an inbox item about one): briefing_view sets `stream` on it, the cockpit too"""
    return bool(row.get("task") and not row.get("inbox_id") and (row.get("stream") or row.get("work_kind") == "stream"))


OBSOLETE_NOTE = "veraltet"
OBSOLETE_REASON = "Wird nicht gemacht: veraltet"
#: the note a task parked on the watch list gets (task.py status backlog --note)
PARK_NOTE = "Parked: on the watch list"


PREPARE_NOTE = "Do it: prepare it, the person does the last step"
NUDGE_NOTE = ("Write a short, friendly follow-up to the person this waits on, as a DRAFT only with the mail-draft "
              "skill. Never send it: the person sends it.")


def settled_key(row: dict) -> str | None:
    """The key the cockpit records a decision under (briefing_view._settled_key): an inbox item, a task, an issue"""
    if row.get("inbox_id"):
        return f"inbox:{row['inbox_id']}"
    if row.get("task"):
        return f"task:{row['task']}"
    return f"ref:{row['ref']}" if row.get("ref") else None


def _launch(item: str, note: bool = False) -> str:
    """An agent tab on one task or inbox item, at work at once: what the cockpit's start runs (workplace.py launch)"""
    return f"workplace.py launch --items {item} --mode go --yes" + (" --start-note" if note else "")


def effect(answer: str, row: dict, until: str | None = None, today: str | None = None) -> dict:
    """What `answer` does to `row`: {answer, kind, cockpit: {verb, args} or None, cli: [briefing commands], then:
    the bucket or place the point stands in afterwards} and the facts a page says beside it (running, draft_only,
    own_answers, stream_continues, github). `cockpit` is the act the cockpit's card sends for the same answer
    (scripts/web/buckets.js bucketAnswers, its words aside: a note's or a reason's text is the page's language);
    scripts/tests/fixtures/answers/effects.json holds the two to the same act, a test on each side. A tab that asks
    has none: its own answers stand in the place of Do it. `until` is a Later's day (later_until), LIST_DAY for the
    watch list; `today` the day a stream's "done for this time" counts on (it is back tomorrow)."""
    if answer not in ANSWERS:
        raise ValueError(f"no such answer: {answer!r}")
    kind = row_kind(row)
    item, slug = row.get("inbox_id"), row.get("task")
    stream = _is_stream(row)
    waiting = row.get("bucket") == "waiting"
    who = row.get("who")
    key = settled_key(row)
    out: dict = {"answer": answer, "kind": kind, "cli": []}

    def be(verb, then, cli=(), **args):
        out.update(cockpit={"verb": verb, "args": args} if verb else None, then=then, cli=list(cli))
        return out

    keys = [key] if key else []
    if answer == "do":
        if kind == "tab":
            out["own_answers"] = True           # the tab's own answers stand in this place
            return be(None, "delegate")
        if waiting:
            # never sent: while the agent writes it the point is the Bridge's, running; the draft it leaves stands in
            # Do for the person to send (`ready`; round 2 of the four answers: the table said Do at once)
            out["draft_only"] = True
            out["ready"] = "do"
            out["running"] = True
            note = f"Start note: {NUDGE_NOTE}"
            cli = ([f'inbox.py note {item} "{note}"', _launch(item, True)] if item else
                   [f'task.py note {slug} --quiet "{note}"', _launch(slug, True)] if slug else [])
            return be("do_it", "delegate", cli, keys=keys, note=NUDGE_NOTE)
        if item and row.get("inbox_state") == "approved":
            # the yes is given: Do it starts it now instead of on the next pass (round 3 of the four answers); one
            # without an action of its own gets an agent, as the cockpit's start (round 4: the chat ran nothing)
            out["running"] = True
            return be("do_it", "delegate", ["inbox.py run"] if row.get("has_action") else [_launch(item)], keys=keys, yes=True)
        if item and row.get("gate") == "only-you":
            # only the person does its last step (send, publish, pay): no yes, the Bridge prepares it as the cockpit
            # does (round 3: "5 mach" approved an only-you item the page's Do it left open)
            out["prepare_only"] = True
            out["running"] = True
            return be("do_it", "delegate", [f'inbox.py note {item} "{PREPARE_NOTE}"', _launch(item)], keys=keys, yes=True)
        if item:
            # the yes, then the run of its own action, or an agent where it has none (actions_work.py v_do_it)
            return be("do_it", "delegate", [f"inbox.py approve {item}", "inbox.py run" if row.get("has_action") else _launch(item)],
                      keys=keys, yes=True)
        out["running"] = True
        # a task gets an agent on its next step; any other row the cockpit files as an inbox item first, which the
        # chat leaves to the person's word (no command here)
        return be("do_it", "delegate", [_launch(slug)] if slug else [], keys=keys)
    if answer == "later":
        until = until or ""
        parked = is_list_day(until)
        hide = [f"briefing.py hide {key} --until {until}"] if key else []
        if parked:
            # the watch list, whoever has the point: a task to the backlog, anything else put off to the list's day
            if slug and not item and not stream:
                return be("task_park", "list", [f'task.py status {slug} backlog --note "{PARK_NOTE}"'], key=key)
            if item:
                return be("later", "list", [f"inbox.py defer {item} --until {until}"], key=key, until=until)
            return be("later", "list", hide, key=key, until=until)
        if waiting:
            # out of sight until the day and counted as later, still with the same person when it is back (round 2)
            on = {"on": str(who)} if who else {}
            if item:
                return be("runs_on", "later", [f"inbox.py defer {item} --until {until}" + (f" --on {who}" if who else "")],
                          keys=keys, until=until, **on)
            if slug and not stream:
                return be("runs_on", "later", [f"task.py wait {slug} --until {until}"], keys=keys, until=until, **on)
            return be("runs_on", "later", hide, keys=keys, until=until, **on)
        plan = {"plan": True} if row.get("bucket") == "plan" else {}
        if item:
            return be("later", "later", [f"inbox.py defer {item} --until {until}"], key=key, until=until, **plan)
        return be("later", "later", hide, key=key, until=until, **plan)
    if answer == "done":
        if stream:
            # done for this time: out of sight until tomorrow and counted as done today; the stream runs on
            out["stream_continues"] = True
            day = (dt.date.fromisoformat(today) if today else dt.date.today()) + dt.timedelta(days=1)
            return be("later", "done", [f"briefing.py hide {key} --until {day.isoformat()} --done"], key=key,
                      until=day.isoformat(), done=True)
        if item:
            return be("settle", "done", [f'inbox.py close {item} --note "done"'], keys=keys, outcome="done")
        if slug:
            return be("settle", "done", [f"task.py close {slug}"], keys=keys, outcome="done")
        if kind == "issue":
            out["github"] = "untouched"         # hidden here, never closed on GitHub
        return be("settle", "done", [f"briefing.py dismiss {key} --outcome done"] if key else [], keys=keys, outcome="done")
    # obsolete: closed as not done, with a note
    if item:
        return be("settle", "done", [f'inbox.py drop {item} --note "{OBSOLETE_NOTE}" --reason outdated'],
                  keys=keys, outcome="not_doing", reason="outdated")
    if stream:
        return be("settle", "done", [f'task.py close {slug} --stream --declined --reason "{OBSOLETE_REASON}"'],
                  keys=keys, outcome="not_doing", stream=True)
    if slug:
        return be("settle", "done", [f'task.py close {slug} --declined --reason "{OBSOLETE_REASON}"'], keys=keys,
                  outcome="not_doing")
    if kind == "issue":
        out["github"] = "untouched"
    return be("settle", "done", [f"briefing.py dismiss {key} --outcome not_doing"] if key else [], keys=keys,
              outcome="not_doing")
