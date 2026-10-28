# SPDX-License-Identifier: MIT
"""How a briefing is shown: the `view:` block of a briefing profile.

A profile's sections say where the data comes from; this module decides what the
reader sees. Four styles, chosen per profile (`view.style`) or once on the command
line (`briefing.py render --style <style>`):

  sources  one block per section, in profile order: the briefing as it always was
  triage   every row sorted by what to DO with it: do, plan, delegate, waiting,
           drop; a thing two sources carry is shown once; housekeeping goes last
  brevity  the bottom line, then the top three with why each matters
  plan     the day: your rows laid into the free gaps of today's calendar, what
           the Bridge does meanwhile, and when the day ends

Which bucket a row lands in follows fixed rules (docs/briefings.md § Views), so the
shape never depends on which agent renders it. A section can force its bucket
(`bucket:`), `mutes:` hide rows a person said they never want again, and every word
the reader sees can be relabelled (`view.labels`, bucket titles). Contract:
scripts/tests/test_briefing_view.py.
"""
from __future__ import annotations

import datetime as dt
import re
import string
import textwrap
import urllib.parse
from pathlib import Path

try:
    from lib.inbox_verbs import art_of_kind
except ImportError:  # loaded by path (briefing.py, the tests) with scripts/ not on the path
    import importlib.util as _ilu
    _spec = _ilu.spec_from_file_location("inbox_verbs", Path(__file__).resolve().parent / "inbox_verbs.py")
    assert _spec is not None and _spec.loader is not None
    _verbs = _ilu.module_from_spec(_spec)
    _spec.loader.exec_module(_verbs)
    art_of_kind = _verbs.art_of_kind

STYLES = ("sources", "triage", "brevity", "plan", "report")
BUCKETS = ("do", "plan", "delegate", "waiting", "drop")
VIEW_KEYS = {"style", "headline", "dayline", "agenda", "overview", "report", "since_last", "lookahead_days", "max_items", "answer_keys", "hygiene", "color",
             "width", "labels", "buckets", "plan", "pages", "page_rest", "page_skip", "marks"}
MARK_KEYS = {"label", "match", "color"}
MARK_COLORS = ("red", "green", "yellow", "blue", "magenta", "cyan", "gray", "white")
# Where a mark looks: the row's own words and what names its source, never a body.
MARK_FIELDS = ("id", "project", "url", "task", "context", "area", "repo", "labels")   # never `tracker`: the source's name
BUCKET_KEYS = {"id", "title", "options", "nudge_after_days"}
DEFAULT_BUCKETS = {
    "do": {"title": "Do (you, today)", "options": ["yes", "later", "drop"]},
    "plan": {"title": "Plan", "options": ["schedule", "later"]},
    "delegate": {"title": "I'll do", "options": ["go", "not now"]},
    "waiting": {"title": "Waiting on others", "options": ["nudge", "wait"], "nudge_after_days": 7},
    "drop": {"title": "Park or drop", "options": ["park", "keep"]},
}
LABELS = {
    "yours_today": "{n} for you today",
    "free_until": "free until {time}",
    "free_rest": "free for the rest of the day",
    "busy_until": "in {title} until {time}",
    "next_date": "coming up: {when} {title}",
    "since": "since {time}: {new} new, {changed} changed",
    "today": "today",
    "tomorrow": "tomorrow",
    "due": "due {when}",
    "back_on": "back on {date}",
    "only_you": "only you",
    "collides": "collides with the calendar",
    "waiting_days": "waiting {n} days",
    "look_again": "look again {when}",
    "with": "with {who}",
    "task": "task {slug}",
    "nudge": "nudge?",
    "new": "new",
    "housekeeping": "Housekeeping",
    "no_next": "{n} task(s) without a next step: {slugs}",
    "muted": "{n} muted",
    "hidden": "{n} hidden (bucket not shown: {ids})",
    "error": "{title} failed: {reason}",
    "workplace": "Tabs: {n} proposed ({new} new, {resume} to resume). Open them?",
    "more": "+{n} more",
    "end": "That's all for today.",
    "why": "why",
    "meanwhile": "Meanwhile I do",
    "later": "Later",
    "shutdown": "Day ends {time}",
    "activity_title": "Activity ({days} days)",
    "commits": "{n} commits",
    "boards_title": "Boards",
    "st_new": "new",
    "st_ready": "ready",
    "st_in_progress": "in progress",
    "st_review": "review",
    "st_blocked": "blocked",
    "capped": "(first {n} cards)",
    "repos_skipped": "{n} repositories not readable: {names}",
    "untasked": "{title}: assigned to you without a task: {n}",
    "agenda_title": "Calendar",
    "clashes": "overlaps {title}",
    "clash_row": "{first} and {second} overlap ({when})",
    "parallel": "alongside {title}",
    "info_tag": "info",
    "tag_calendar": "Calendar",
    "step_prepare": "Prepare",
    "prepare_head": "Prepare me for the appointment \u201c{title}\u201d on {when}.",
    "prepare_place": "Place",
    "prepare_people": "With",
    "prepare_tail": ("Look through this Bridge for what bears on it: tasks, inbox, the work log, earlier meeting "
                     "notes, mails and issues that name the title or the people. Then give me a short brief: what "
                     "it is about, what is open, what I should bring or decide. Read only, send nothing."),
    # a GitHub row's steps (briefing.py tracker_steps): each starts an agent tab, none acts on GitHub by itself
    "stale": "the source did not answer, last rows shown",
    "stale_until": "GitHub limit reached, not asked until {until}, last rows shown",
    "stale_refreshing": "last rows, being refreshed",
    "gh_draft": "draft",
    "gh_task": "task {slug}",
    "gh_step_analyze": "Analyse",
    "gh_step_implement": "Implement",
    "gh_step_review": "Review the PR",
    "gh_step_adopt": "Make it a task",
    "gh_step_sync": "Sync status",
    "gh_step_remind": "Remind",
    "gh_head": "GitHub {type} {id}: {title}",
    "gh_type_issue": "issue",
    "gh_type_pr": "pull request",
    "gh_type_draft": "draft card",
    "gh_fact_link": "Link",
    "gh_fact_status": "Status",
    "gh_fact_board": "Board",
    "gh_fact_config": "Board config",
    "gh_fact_task": "Task of this Bridge",
    "gh_fact_prs": "Pull requests that close it",
    "gh_fact_note": "Note",
    "gh_fact_assignee": "Assigned to",
    "gh_do_analyze": ("Read it with its comments (gh issue view or gh pr view with --comments), the board config and the "
                      "code it touches. Answer here: what is asked, what is unclear, and a plan in a few steps. Change "
                      "nothing on GitHub; offer a comment as a draft and post it only after a yes."),
    "gh_do_implement": ("Implement it. First read the repository's AGENTS.md or CLAUDE.md and its branch model, and check "
                        "whether a task of this Bridge already covers it. Work on a feature branch, tests first. Board "
                        "fields only through the github-projects-manager skill with the values of the board config: In "
                        "Progress when you start, In Review once a draft pull request that closes the issue is open. Never "
                        "merge and never push to the default branch: that stays with the person."),
    "gh_do_review": ("Review the pull request (a code review skill if you have one, else gh pr diff): correctness first, "
                     "then tests and fit. Prepare the findings as a pending review with inline comments and submit it "
                     "only after a yes."),
    "gh_do_adopt": ("Make this a task of this Bridge. First look in work/tasks/ and work/streams/ for one that already "
                    "fits; else create it from the template (rules/task-management-workflow.md) with sync.github naming "
                    "the repository, the issue number and the board. Change nothing on GitHub."),
    # a draft card has no issue, no number and no URL; its text may be private, so it stays where it is
    "gh_do_analyze_draft": ("This is a draft card on the board, not an issue: there is no number and no link. Read its "
                            "text on the board (gh project item-list with the board's number and owner, the card with "
                            "this project item id) and the board config. Answer here: what is asked, what is unclear, "
                            "and a plan in a few steps. Change nothing on GitHub and do not turn the card into an issue: "
                            "its text may be meant to stay private."),
    "gh_do_adopt_draft": ("Make this draft card a task of this Bridge. First look in work/tasks/ and work/streams/ for one "
                          "that already fits; else create it from the template (rules/task-management-workflow.md) and "
                          "name the board and this project item id in it, since there is no issue to sync. Keep the "
                          "card's text out of anything that leaves this machine. Change nothing on GitHub."),
    "gh_do_sync": ("Compare the board status, the state of the issue or pull request and the task of this Bridge "
                   "(python3 scripts/tracker-sync.py diff, the tracker-sync skill). List what differs and propose the "
                   "change on each side; apply a board change only through the github-projects-manager skill and only "
                   "after a yes."),
    "gh_do_remind": ("Write a short, friendly reminder to the person it is assigned to: what is open, what is needed from "
                     "them, by when if a date is known, in the language the issue is written in. The click on Remind "
                     "releases exactly this one GitHub comment that mentions them: post it right away (gh issue comment, "
                     "on a pull request gh pr comment, text from a file), without asking again. Then put the comment's "
                     "link on the inbox item (python3 scripts/inbox.py note) and close it. Anything else, a mail or chat "
                     "only as a draft through this Bridge's drafting skill. If posting is refused, note the text and the "
                     "reason on the inbox item instead, so the cockpit shows it."),
    "all_clear": "{title}: all clear",
    "owed": "Not in this profile, still yours to run: {streams} (briefing.py owed)",
    "overview_file": "Boards and activity: {path}",
    "report_title": "Briefing {date}",
    "lage": "Status",
    "first_title": "First",
    "bucket_more": "+{n} more",
    "col_when": "When",
    "col_what": "What",
    "col_note": "Note",
    "col_board": "Board",
    "col_repo": "Repository",
    "col_branch": "Branch",
    "col_days": "{days} days",
    "col_commits": "Commits",
    "page_status": "Status",
    "page_dates": "Dates",
    "page_trackers": "Trackers",
    "page_today": "What happened today",
    "page_more": "More",
    "page_empty": "nothing",
    "page_work": "Work",
    "section_inbox": "Inbox",
    "section_runs_on": "Runs on",
    "section_tasks": "Tasks",
    "section_next_up": "Next up",
    "section_advise": "Hints",
    "section_calendar": "Calendar",
    "section_activity": "Activity",
    "section_workplace": "Workplace",
    "until": "until {time}",
    "commits_today": "{n} today",
}
# The same words in German (rules/language-policy.md section 3: one table per language, identical keys,
# English the default and the fallback). The language is bridge-config.yaml language.conversation; a
# profile's own `view.labels` still win over both.
LABELS_DE = {
    "yours_today": "{n} für dich heute",
    "free_until": "frei bis {time}",
    "free_rest": "frei für den Rest des Tages",
    "busy_until": "in {title} bis {time}",
    "next_date": "demnächst: {when} {title}",
    "since": "seit {time}: {new} neu, {changed} geändert",
    "today": "heute",
    "tomorrow": "morgen",
    "due": "fällig {when}",
    "back_on": "zurück am {date}",
    "only_you": "nur du",
    "collides": "kollidiert mit dem Kalender",
    "waiting_days": "wartet seit {n} Tagen",
    "look_again": "nachsehen {when}",
    "with": "bei {who}",
    "task": "Aufgabe {slug}",
    "nudge": "nachfassen?",
    "new": "neu",
    "housekeeping": "Pflege",
    "no_next": "{n} Aufgaben ohne nächsten Schritt: {slugs}",
    "muted": "{n} stummgeschaltet",
    "hidden": "{n} ausgeblendet (Fach nicht gezeigt: {ids})",
    "error": "{title} fehlgeschlagen: {reason}",
    "workplace": "Tabs: {n} vorgeschlagen ({new} neu, {resume} fortsetzen). Öffnen?",
    "more": "+{n} weitere",
    "end": "Das war's für heute.",
    "why": "warum",
    "meanwhile": "Parallel mache ich",
    "later": "Später",
    "shutdown": "Feierabend {time}",
    "activity_title": "Aktivität ({days} Tage)",
    "commits": "{n} Commits",
    "boards_title": "Boards",
    "st_new": "neu",
    "st_ready": "bereit",
    "st_in_progress": "in Arbeit",
    "st_review": "Review",
    "st_blocked": "blockiert",
    "capped": "(erste {n} Karten)",
    "repos_skipped": "{n} Repos nicht lesbar: {names}",
    "untasked": "{title}: dir zugewiesen, ohne Aufgabe: {n}",
    "agenda_title": "Termine",
    "clashes": "überschneidet sich mit {title}",
    "clash_row": "{first} und {second} überschneiden sich ({when})",
    "parallel": "parallel zu {title}",
    "info_tag": "Info",
    "tag_calendar": "Kalender",
    "step_prepare": "Vorbereiten",
    "prepare_head": "Bereite mich auf den Termin \u201e{title}\u201c am {when} vor.",
    "prepare_place": "Ort",
    "prepare_people": "Mit",
    "prepare_tail": ("Such in dieser Bridge, was dazu gehört: Aufgaben, Posteingang, Arbeitslog, frühere Protokolle, "
                     "Mails und Issues, die den Titel oder die Personen nennen. Gib mir dann eine kurze Vorbereitung: "
                     "worum es geht, was offen ist, was ich mitbringen oder entscheiden sollte. Nur lesen, nichts senden."),
    "stale": "Quelle antwortet nicht, letzter Stand",
    "stale_until": "GitHub-Kontingent erschöpft, Abfrage erst ab {until}, letzter Stand",
    "stale_refreshing": "letzter Stand, wird gerade aktualisiert",
    "gh_draft": "Entwurf",
    "gh_task": "Aufgabe {slug}",
    "gh_step_analyze": "Analysieren",
    "gh_step_implement": "Umsetzen",
    "gh_step_review": "PR prüfen",
    "gh_step_adopt": "Als Aufgabe",
    "gh_step_sync": "Status abgleichen",
    "gh_step_remind": "Erinnern",
    "gh_head": "GitHub-{type} {id}: {title}",
    "gh_type_issue": "Issue",
    "gh_type_pr": "Pull Request",
    "gh_type_draft": "Entwurfskarte",
    "gh_fact_link": "Link",
    "gh_fact_status": "Status",
    "gh_fact_board": "Board",
    "gh_fact_config": "Board-Konfiguration",
    "gh_fact_task": "Aufgabe dieser Bridge",
    "gh_fact_prs": "Pull Requests, die es schließen",
    "gh_fact_note": "Hinweis",
    "gh_fact_assignee": "Zugewiesen an",
    "gh_do_analyze": ("Lies es samt Kommentaren (gh issue view oder gh pr view mit --comments), die Board-Konfiguration "
                      "und den Code, den es berührt. Antworte hier: was verlangt ist, was unklar ist, und ein Plan in "
                      "wenigen Schritten. Ändere nichts auf GitHub; einen Kommentar bietest du als Entwurf an und "
                      "postest ihn erst nach einem Ja."),
    "gh_do_implement": ("Setze es um. Lies zuerst AGENTS.md oder CLAUDE.md des Repos und sein Branch-Modell und prüfe, ob "
                        "eine Aufgabe dieser Bridge es schon abdeckt. Arbeite auf einem Feature-Branch, Tests zuerst. "
                        "Board-Felder nur über den Skill github-projects-manager mit den Werten der Board-Konfiguration: "
                        "In Progress beim Start, In Review, sobald ein Draft-PR offen ist, der das Issue schließt. Nie "
                        "mergen und nie auf den Default-Branch pushen: das bleibt beim Menschen."),
    "gh_do_review": ("Prüfe den Pull Request (ein Code-Review-Skill, wenn du einen hast, sonst gh pr diff): zuerst "
                     "Korrektheit, dann Tests und Passung. Bereite die Befunde als ausstehendes Review mit "
                     "Inline-Kommentaren vor und reiche es erst nach einem Ja ein."),
    "gh_do_adopt": ("Mach daraus eine Aufgabe dieser Bridge. Sieh zuerst in work/tasks/ und work/streams/ nach, ob eine "
                    "schon passt; sonst leg sie nach der Vorlage an (rules/task-management-workflow.md), mit sync.github "
                    "auf Repo, Issue-Nummer und Board. Ändere nichts auf GitHub."),
    "gh_do_analyze_draft": ("Das ist eine Entwurfskarte auf dem Board, kein Issue: es gibt keine Nummer und keinen Link. "
                            "Lies ihren Text auf dem Board (gh project item-list mit Nummer und Owner des Boards, die "
                            "Karte mit dieser Projekt-Item-ID) und die Board-Konfiguration. Antworte hier: was verlangt "
                            "ist, was unklar ist, und ein Plan in wenigen Schritten. Ändere nichts auf GitHub und mach "
                            "aus der Karte kein Issue: ihr Text soll womöglich privat bleiben."),
    "gh_do_adopt_draft": ("Mach aus dieser Entwurfskarte eine Aufgabe dieser Bridge. Sieh zuerst in work/tasks/ und "
                          "work/streams/ nach, ob eine schon passt; sonst leg sie nach der Vorlage an "
                          "(rules/task-management-workflow.md) und nenne darin das Board und diese Projekt-Item-ID, "
                          "denn es gibt kein Issue zum Abgleichen. Der Text der Karte bleibt aus allem heraus, was "
                          "diese Maschine verlässt. Ändere nichts auf GitHub."),
    "gh_do_sync": ("Vergleiche den Board-Status, den Stand des Issues oder PRs und die Aufgabe dieser Bridge "
                   "(python3 scripts/tracker-sync.py diff, der Skill tracker-sync). Nenne, was abweicht, und schlage die "
                   "Änderung je Seite vor; eine Board-Änderung nur über den Skill github-projects-manager und erst nach "
                   "einem Ja."),
    "gh_do_remind": ("Schreib eine kurze, freundliche Erinnerung an die Person, der es zugewiesen ist: was offen ist, was "
                     "von ihr gebraucht wird, bis wann, falls ein Datum bekannt ist, in der Sprache des Issues. Der Klick "
                     "auf Erinnern gibt genau diesen einen GitHub-Kommentar mit Erwähnung frei: poste ihn sofort (gh issue "
                     "comment, bei einem Pull Request gh pr comment, Text aus einer Datei), ohne noch einmal zu fragen. "
                     "Dann den Link des Kommentars als Notiz auf das Posteingang-Item (python3 scripts/inbox.py note) und "
                     "das Item schließen. Alles andere, Mail oder Chat nur als Entwurf über den Entwurfs-Skill dieser "
                     "Bridge. Wird das Posten abgelehnt, schreib Text und Grund als Notiz auf das Item, damit das Cockpit "
                     "es zeigt."),
    "all_clear": "{title}: alles in Ordnung",
    "owed": "Nicht im Profil, noch von Hand: {streams} (briefing.py owed)",
    "overview_file": "Boards und Aktivität: {path}",
    "report_title": "Briefing {date}",
    "lage": "Lage",
    "first_title": "Zuerst",
    "bucket_more": "+{n} weitere",
    "col_when": "Wann",
    "col_what": "Was",
    "col_note": "Hinweis",
    "col_board": "Board",
    "col_repo": "Repository",
    "col_branch": "Branch",
    "col_days": "{days} Tage",
    "col_commits": "Commits",
    "page_status": "Status",
    "page_dates": "Termine",
    "page_trackers": "Tracker",
    "page_today": "Was heute geschah",
    "page_more": "Weitere",
    "page_empty": "nichts",
    "page_work": "Arbeit",
    "section_inbox": "Posteingang",
    "section_runs_on": "Läuft",
    "section_tasks": "Aufgaben",
    "section_next_up": "Als Nächstes",
    "section_advise": "Hinweise",
    "section_calendar": "Termine",
    "section_activity": "Aktivität",
    "section_workplace": "Arbeitsplatz",
    "until": "bis {time}",
    "commits_today": "{n} heute",
}
LABEL_TABLES = {"en": LABELS, "de": LABELS_DE}
# Dashboard pages (`view.pages`): the briefing page itself shows these kinds; every
# other section gets a page by its kind unless the profile places it.
BRIEFING_KINDS = ("inbox", "advise", "tasks")
PAGE_OF_KIND = {"inbox": "work", "tasks": "work", "command": "status", "calendar": "dates", "tracker": "trackers",
                "commits": "today", "activity": "today"}
DEFAULT_PAGES = ("work", "status", "dates", "trackers", "today")
# where a default page sits: work and status in front, the rest behind More, today's activity under the day list
DEFAULT_PAGE_GROUP = {"work": "main", "status": "main", "dates": "more", "trackers": "more", "today": "day"}
REST_PAGE = "more"
PAGE_KEYS = {"id", "title", "sections", "group", "overview", "jev", "cards", "under"}
# the cockpit's own pages a profile may place under one of its pages (`{id: "@workers", under: ops}`): an id
# and `under`, never sections; the page then has no tab, the bar of the folder it stands in opens it
PLACED_PAGES = ("@workers",)
# the live cards a dashboard may place after a section of a page (bridge_cockpit.model.CARD_IDS)
PAGE_CARDS = ("costs", "usage", "noise")
JEV_KEYS = {"skip_sections", "private"}
# where a page sits in a dashboard's page bar: in front, or behind a "More" menu
PAGE_GROUPS = ("main", "more", "work", "day")   # day: no tab, its sections stand under the day list;
# work: no tab, it is the "by source" view of the work tab (the briefing), beside "what is due" and "by Jev"
PAGE_SECTION_KEYS = {"id", "when", "detail", "link", "empty", "alarm", "badge", "view", "hide_empty", "actionable", "steps",
                     "hide_ok"}
# how a dashboard offers a row's own steps: one menu (default), or each as a button of its own
PAGE_STEPS = ("menu", "buttons")
# how a dashboard draws a section: rows in a table (default), cards, or a mosaic of every row
# board: the table, its rows under their group; agenda: a calendar by day, with figures and a timeline
PAGE_VIEWS = ("table", "tiles", "mosaic", "groups", "board", "agenda")
BOARD_STATES = ("new", "ready", "in_progress", "review", "blocked")
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
# An id that names its repository is the same thing wherever it comes from; any
# other id (a command's "1", an ADO "1234") is only unique inside its section.
GLOBAL_ID = re.compile(r"^[\w.-]+/[\w.-]+#\d+$")
WHO_BRIDGE = ("bridge", "agent", "ai")
WHO_YOU = ("me", "you", "self")
URGENCY = {b: n for n, b in enumerate(BUCKETS)}


# ---------------------------------------------------------------- choice and validation

def _cfg(profile: dict) -> dict:
    view = profile.get("view")
    return view if isinstance(view, dict) else {}


def style_of(profile: dict, override: str | None = None) -> str:
    if override:
        return override
    style = _cfg(profile).get("style", "sources")
    return style if style in STYLES else "sources"


def _pos_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def _int(value, default: int, minimum: int = 0) -> int:
    """A number from a profile that may not have been validated: bad values fall back."""
    if isinstance(value, bool):
        return default
    try:
        number = int(value)
    except (TypeError, ValueError):
        return default
    return number if number >= minimum else default


def _fields(text: str) -> set:
    """Placeholder names in a label; raises ValueError on a broken brace."""
    return {name for _, name, _, _ in string.Formatter().parse(text) if name is not None}


def problems(view, mutes) -> list:
    """What is wrong with a profile's `view:` block and `mutes:` list (None = not given)."""
    out = []
    if view is not None:
        if not isinstance(view, dict):
            return ["view must be a mapping"]
        for key in sorted(set(view) - VIEW_KEYS):
            out.append(f"unknown view key {key}")
        if view.get("style", "sources") not in STYLES:
            out.append(f"view.style must be one of {', '.join(STYLES)}")
        for key in ("headline", "dayline", "agenda", "since_last", "answer_keys"):
            if key in view and not isinstance(view[key], bool):
                out.append(f"view.{key} must be true or false")
        if "max_items" in view and not _pos_int(view["max_items"]):
            out.append("view.max_items must be a positive integer")
        if "width" in view and not (_pos_int(view["width"]) and view["width"] >= 40):
            out.append("view.width must be a whole number of 40 or more")
        if "lookahead_days" in view and _int(view["lookahead_days"], -1) < 0 or \
                isinstance(view.get("lookahead_days"), (str, bool, float)):
            out.append("view.lookahead_days must be a whole number of days, 0 or more")
        rcfg = view.get("report", {})
        if not isinstance(rcfg, dict) or set(rcfg) - {"top", "per_bucket"} or \
                any(not _pos_int(rcfg[k]) for k in ("top", "per_bucket") if k in rcfg):
            out.append("view.report takes top and per_bucket, each a positive integer")
        if view.get("overview", "inline") not in ("inline", "file"):
            out.append("view.overview must be inline or file")
        if view.get("hygiene", "bottom") not in ("bottom", "hide"):
            out.append("view.hygiene must be bottom or hide")
        if view.get("color", "auto") not in ("auto", "meaning", "none"):
            out.append("view.color must be auto, meaning or none")
        labels = view.get("labels", {})
        if not isinstance(labels, dict) or not all(isinstance(v, str) for v in labels.values()):
            out.append("view.labels must map label names to text")
        else:
            for key, text in sorted(labels.items()):
                if key not in LABELS:
                    out.append(f"view.labels: unknown label {key} (known: {', '.join(sorted(LABELS))})")
                    continue
                try:
                    extra = _fields(text) - _fields(LABELS[key])
                except ValueError:
                    out.append(f"view.labels.{key}: a brace that is not a placeholder (write {{{{ or }}}})")
                    continue
                if extra:
                    allowed = ", ".join(f"{{{f}}}" for f in sorted(_fields(LABELS[key]))) or "none"
                    out.append(f"view.labels.{key}: unknown placeholder {', '.join(sorted(extra))} "
                               f"(allowed: {allowed})")
        buckets = view.get("buckets", [])
        if not isinstance(buckets, list):
            out.append("view.buckets must be a list")
            buckets = []
        seen = set()
        for n, b in enumerate(buckets, 1):
            if not isinstance(b, dict) or b.get("id") not in BUCKETS:
                bid = b.get("id") if isinstance(b, dict) else b
                out.append(f"view.buckets {n}: bucket id {bid!r} is not one of {', '.join(BUCKETS)}")
                continue
            if b["id"] in seen:
                out.append(f"view.buckets {n}: bucket {b['id']} listed twice")
            seen.add(b["id"])
            for key in sorted(set(b) - BUCKET_KEYS):
                out.append(f"view.buckets {n}: unknown key {key}")
            if "title" in b and not isinstance(b["title"], str):
                out.append(f"view.buckets {n}: title must be text")
            if "options" in b and not (isinstance(b["options"], list) and all(isinstance(o, str) for o in b["options"])):
                out.append(f"view.buckets {n}: options must be a list of text")
            if "nudge_after_days" in b and not _pos_int(b["nudge_after_days"]):
                out.append(f"view.buckets {n}: nudge_after_days must be a positive integer")
        plan = view.get("plan", {})
        if not isinstance(plan, dict):
            out.append("view.plan must be a mapping")
        else:
            for key in sorted(set(plan) - {"workday", "default_minutes"}):
                out.append(f"view.plan: unknown key {key}")
            workday = plan.get("workday", {})
            if not isinstance(workday, dict):
                out.append("view.plan.workday must be a mapping with start and end")
            else:
                good = True
                for key in ("start", "end"):
                    if key in workday and not (isinstance(workday[key], str) and HHMM.match(workday[key])):
                        out.append(f"view.plan.workday {key} must be HH:MM")
                        good = False
                if good and _hm(workday.get("start", "08:00")) >= _hm(workday.get("end", "18:00")):
                    out.append("view.plan.workday start must be before its end")
            if "default_minutes" in plan and not _pos_int(plan["default_minutes"]):
                out.append("view.plan.default_minutes must be a positive integer")
        out += _page_problems(view)
        out += _mark_problems(view)
    if mutes is not None:
        if not isinstance(mutes, list):
            out.append("mutes must be a list")
        else:
            for n, m in enumerate(mutes, 1):
                if not isinstance(m, dict) or not isinstance(m.get("section"), str):
                    out.append(f"mutes rule {n} needs a `section:` (a section id)")
                elif not isinstance(m.get("when"), dict) or not m["when"]:
                    out.append(f"mutes rule {n} needs a non-empty `when:` mapping")
                elif set(m) - {"section", "when", "note"}:
                    out.append(f"mutes rule {n}: unknown key {sorted(set(m) - {'section', 'when', 'note'})[0]}")
                elif "note" in m and not isinstance(m["note"], str):
                    out.append(f"mutes rule {n}: note must be text")
    return out


def _mark_problems(view: dict) -> list:
    """`view.marks`: a label in front of every row whose words name one of `match`."""
    marks = view.get("marks")
    if marks is None:
        return []
    if not isinstance(marks, list):
        return ["view.marks must be a list of {label, match, color}"]
    out = []
    for i, m in enumerate(marks):
        where = f"view.marks[{i}]"
        if not isinstance(m, dict):
            out.append(f"{where} must be a mapping")
            continue
        for key in sorted(set(m) - MARK_KEYS):
            out.append(f"{where}: unknown key {key}")
        if not (isinstance(m.get("label"), str) and 0 < len(m["label"].strip()) <= 16):
            out.append(f"{where}.label must be text of 1 to 16 characters")
        match = m.get("match")
        words = [match] if isinstance(match, str) else match
        if not (isinstance(words, list) and words and all(isinstance(w, str) and w.strip() for w in words)):
            out.append(f"{where}.match must be text or a list of text")
        if "color" in m and m["color"] not in MARK_COLORS:
            out.append(f"{where}.color must be one of {', '.join(MARK_COLORS)}")
    return out


def marks_of(view: dict) -> list:
    """The usable marks, words lower-cased; a broken entry is left out (validate names it)."""
    out = []
    for m in view.get("marks") or [] if isinstance(view.get("marks"), list) else []:
        if not isinstance(m, dict) or not isinstance(m.get("label"), str) or not m["label"].strip():
            continue
        words = [m["match"]] if isinstance(m.get("match"), str) else m.get("match")
        if not isinstance(words, list):
            continue
        words = [w.strip().lower() for w in words if isinstance(w, str) and w.strip()]
        if words:
            out.append({"label": m["label"].strip(), "color": m.get("color") if m.get("color") in MARK_COLORS else None,
                        "words": words})
    return out


def mark_for(marks: list, title, item: dict):
    """The first mark one of whose words stands in the row's title or in what names its source."""
    if not marks:
        return None
    parts = [str(title or "")]
    for field in MARK_FIELDS:
        value = item.get(field)
        parts += [str(v) for v in value] if isinstance(value, list) else [str(value)] if value else []
    text = " ".join(parts).lower()
    for m in marks:
        if any(w in text for w in m["words"]):
            return {"label": m["label"], "color": m["color"]}
    return None


def _marked(row: dict) -> str:
    """The row's mark in front of its title in the text views, `[ACME] `; nothing without one."""
    mark = row.get("mark")
    return f"[{mark['label']}] " if isinstance(mark, dict) and mark.get("label") else ""


def _page_problems(view: dict) -> list:
    """What is wrong with `view.pages` and `view.page_rest`; section ids are checked by the profile."""
    out = []
    if view.get("page_rest", "show") not in ("show", "hide"):
        out.append("view.page_rest must be show or hide")
    skip = view.get("page_skip", [])
    if not isinstance(skip, list) or not all(isinstance(x, str) for x in skip):
        out.append("view.page_skip must be a list of section ids")
    pages = view.get("pages")
    if pages is None:
        return out
    if not isinstance(pages, list):
        return out + ["view.pages must be a list of pages"]
    seen, placed = set(), {}
    listed = {p["id"]: p for p in pages if isinstance(p, dict) and isinstance(p.get("id"), str) and p["id"]}
    for n, page in enumerate(pages, 1):
        where = f"view.pages {n}"
        if not isinstance(page, dict):
            out.append(f"{where}: must be a mapping with id and sections")
            continue
        pid = page.get("id")
        if not isinstance(pid, str) or not pid:
            out.append(f"{where}: needs an id")
        elif pid == "briefing":
            out.append(f"{where}: briefing is the briefing itself, pick another id")
        elif pid == REST_PAGE:
            out.append(f"{where}: {REST_PAGE} is the page for the rest, pick another id")
        elif pid in seen:
            out.append(f"{where}: page {pid} listed twice")
        seen.add(pid)
        if pid in PLACED_PAGES:
            out += [f"{where}: unknown key {key}" for key in sorted(set(page) - {"id", "under"})]
            out += _under_problems(page, listed, where) if "under" in page else \
                [f"{where}: {pid} needs under (the page it stands under)"]
            continue
        for key in sorted(set(page) - PAGE_KEYS):
            out.append(f"{where}: unknown key {key}")
        if "under" in page:
            out += _under_problems(page, listed, where)
        if "title" in page and not isinstance(page["title"], str):
            out.append(f"{where}: title must be text")
        if "group" in page and page["group"] not in PAGE_GROUPS:
            out.append(f"{where}: group must be main, more, work or day")
        if "overview" in page and not isinstance(page["overview"], bool):
            out.append(f"{where}: overview must be true or false")
        if "jev" in page:
            if not isinstance(page["jev"], dict):
                out.append(f"{where}: jev must be a mapping")
            else:
                for key, what in (("skip_sections", "section ids"), ("private", "words")):
                    v = page["jev"].get(key)
                    if v is not None and not (isinstance(v, list) and all(isinstance(x, str) for x in v)):
                        out.append(f"{where}: jev.{key} must be a list of {what}")
                for key in sorted(set(page["jev"]) - JEV_KEYS):
                    out.append(f"{where}: jev: unknown key {key}")
        sections = page.get("sections")
        if "cards" in page:
            out += _card_problems(page["cards"], sections, where)
        if not isinstance(sections, list) or not sections:
            out.append(f"{where}: sections must be a non-empty list")
            continue
        for entry in sections:
            sid = entry if isinstance(entry, str) else entry.get("id") if isinstance(entry, dict) else None
            if isinstance(sid, str):
                if sid in placed:
                    out.append(f"{where}: section {sid} already stands on page {placed[sid]}")
                placed.setdefault(sid, pid)
            if isinstance(entry, str):
                continue
            if not isinstance(entry, dict) or not isinstance(entry.get("id"), str):
                out.append(f"{where}: a section is a section id or a mapping with id")
                continue
            at = f"{where}, section {entry['id']}"
            for key in sorted(set(entry) - PAGE_SECTION_KEYS):
                out.append(f"{at}: unknown key {key}")
            for key in ("when", "link", "empty"):
                if key in entry and not isinstance(entry[key], str):
                    out.append(f"{at}: {key} must be text")
            detail = entry.get("detail", [])
            if not (isinstance(detail, str) or (isinstance(detail, list) and all(isinstance(d, str) for d in detail))):
                out.append(f"{at}: detail must be a field name or a list of them")
            for key in ("alarm", "badge", "hide_empty", "actionable", "hide_ok"):
                if key in entry and not isinstance(entry[key], bool):
                    out.append(f"{at}: {key} must be true or false")
            if "view" in entry and entry["view"] not in PAGE_VIEWS:
                out.append(f"{at}: view must be one of {', '.join(PAGE_VIEWS)}")
            if "steps" in entry and entry["steps"] not in PAGE_STEPS:
                out.append(f"{at}: steps must be one of {', '.join(PAGE_STEPS)}")
    return out


def _under_problems(page: dict, listed: dict, where: str) -> list:
    """`under:` of a page: another page of view.pages with a tab of its own, standing under none itself."""
    under = page["under"]
    if not isinstance(under, str) or not under:
        return [f"{where}: under must be a page id"]
    if under == page.get("id"):
        return [f"{where}: a page cannot stand under itself"]
    parent = listed.get(under)
    if parent is None or under in PLACED_PAGES:
        return [f"{where}: under names no page of view.pages: {under}"]
    if page.get("group") in ("work", "day"):
        return [f"{where}: under and group work or day exclude each other"]
    if parent.get("group") in ("work", "day"):
        return [f"{where}: under: {under} has no tab of its own (group work or day)"]
    if "under" in parent:
        return [f"{where}: under: {under} stands under {parent['under']} itself, one level only"]
    return []


def page_section_ids(view: dict) -> list:
    """(page number, section id) for every section `view.pages` names."""
    out = []
    for n, page in enumerate(view.get("pages") if isinstance(view.get("pages"), list) else [], 1):
        for entry in (page.get("sections") if isinstance(page, dict) and isinstance(page.get("sections"), list) else []):
            sid = entry if isinstance(entry, str) else entry.get("id") if isinstance(entry, dict) else None
            if isinstance(sid, str):
                out.append((n, sid))
    return out


def labels_for(language: str | None) -> dict:
    """The default words of a language: German for de..., English for everything else."""
    return LABEL_TABLES["de" if str(language or "").lower().startswith("de") else "en"]


def _labels(view: dict, language: str | None = None) -> dict:
    """The profile's words over the defaults of its language; a label that would not format keeps the default."""
    out = dict(labels_for(language))
    given = view.get("labels") if isinstance(view.get("labels"), dict) else {}
    for key, text in given.items():
        if key not in LABELS or not isinstance(text, str):
            continue
        try:
            if _fields(text) <= _fields(LABELS[key]):
                out[key] = text
        except ValueError:
            pass
    return out


# ---------------------------------------------------------------- time

def _when(value):
    """ISO date or datetime as a naive local datetime; a bare date is midnight."""
    if not value:
        return None
    text = str(value).strip()
    try:
        when = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        try:
            when = dt.datetime.combine(dt.date.fromisoformat(text[:10]), dt.time())
        except ValueError:
            return None
    if when.tzinfo is not None:
        when = when.astimezone().replace(tzinfo=None)
    return when


def _has_time(value) -> bool:
    return bool(value) and len(str(value)) > 10


def _fmt_when(value, now: dt.datetime, labels: dict) -> str:
    when = _when(value)
    if when is None:
        return str(value)
    day = (labels["today"] if when.date() == now.date() else
           labels["tomorrow"] if when.date() == now.date() + dt.timedelta(days=1) else f"{when:%d.%m}")
    return f"{day} {when:%H:%M}" if _has_time(value) else day


def _hm(value: str) -> int:
    h, m = value.split(":")
    return int(h) * 60 + int(m)


def _clock(minutes: int) -> str:
    minutes = max(0, min(minutes, 24 * 60 - 1))
    return f"{minutes // 60:02d}:{minutes % 60:02d}"


def _events(raw: list, now: dt.datetime) -> list:
    """Timed events as (start, end, title), sorted by time; no end = 30 minutes."""
    out = []
    for e in raw:
        start = _when(e.get("start"))
        if start is None or not _has_time(e.get("start")):
            continue
        end = _when(e.get("end")) if _has_time(e.get("end")) else None
        if end is None or end <= start:
            end = start + dt.timedelta(minutes=30)
        out.append((start, end, str(e.get("title") or "")))
    return sorted(out, key=lambda e: e[0])


def _today(events: list, now: dt.datetime) -> list:
    """Events overlapping today, as minute ranges clipped to today."""
    day0 = dt.datetime.combine(now.date(), dt.time())
    day1 = day0 + dt.timedelta(days=1)
    out = []
    for start, end, title in events:
        if start < day1 and end > day0:
            s = max(start, day0)
            e = min(end, day1)
            out.append((int((s - day0).total_seconds() // 60), int((e - day0).total_seconds() // 60), title))
    return out


# ---------------------------------------------------------------- build

def _matches(when: dict, item: dict) -> bool:
    for field, want in when.items():
        have = item.get(field)
        wants = want if isinstance(want, list) else [want]
        if isinstance(have, list):
            if not any(w in have for w in wants):
                return False
        elif have not in wants:
            return False
    return True


def _bucket_cfg(view: dict) -> tuple:
    """(shown bucket configs in order, ids hidden). No list = all five in the default order."""
    listed = view.get("buckets")
    if not isinstance(listed, list) or not listed:
        listed = [{"id": b} for b in BUCKETS]
    shown = []
    for b in listed:
        if isinstance(b, dict) and b.get("id") in BUCKETS:
            shown.append({"id": b["id"], **DEFAULT_BUCKETS[b["id"]], **{k: v for k, v in b.items() if k != "id"}})
    ids = [b["id"] for b in shown]
    return shown, [b for b in BUCKETS if b not in ids]


def _shortened(short: str, full: str) -> bool:
    """`short` is `full` cut off with an ellipsis (a tab label such as "A2A: Anfragen an den…")."""
    stem = short[:-1] if short.endswith("…") else short[:-3] if short.endswith("...") else None
    return bool(stem) and len(full) > len(stem) and full.startswith(stem.rstrip())


def _short(text, limit: int) -> str:
    """At most `limit` characters, marked with an ellipsis; cut at a word when the text has one."""
    text = " ".join(str(text or "").split())
    if len(text) <= limit:
        return text
    cut = text[: limit - 1]
    if " " in cut and not text[limit - 1].isspace():
        cut = cut.rsplit(" ", 1)[0]
    return cut.rstrip(" ,.;:") + "…"


def _days_since(value, now: dt.datetime):
    when = _when(value)
    return (now.date() - when.date()).days if when else None


def _item_key(sid, iid) -> str:
    iid = str(iid)
    return f"item:{iid}" if GLOBAL_ID.match(iid) else f"item:{sid}:{iid}"


def _rows(result: dict, profile: dict, view: dict, labels: dict, now: dt.datetime) -> dict:
    sections_cfg = {}
    for s in profile.get("sections") or []:
        if isinstance(s, dict):
            sections_cfg[str(s.get("id") or s.get("kind"))] = s
    marks = marks_of(view)
    mutes = [m for m in (profile.get("mutes") or []) if isinstance(m, dict) and isinstance(m.get("when"), dict)]
    you = set(WHO_YOU) | ({str(profile["for"]).lower()} if profile.get("for") else set())
    horizon = now.date() + dt.timedelta(days=_int(view.get("lookahead_days"), 1))
    nudge_days = DEFAULT_BUCKETS["waiting"]["nudge_after_days"]
    for b in view.get("buckets") or []:
        if isinstance(b, dict) and b.get("id") == "waiting":
            nudge_days = _int(b.get("nudge_after_days"), nudge_days, 1)

    out = {"rows": {}, "order": [], "hygiene": [], "no_next": [], "muted": 0, "events": [], "workplace": None,
           "activity": [], "boards": [], "clear": [], "status": []}

    def items_of(s):
        # The section's own `max:` still caps what it contributes.
        return s.get("items") or []

    def muted(sid, item):
        return any(m.get("section") == sid and _matches(m["when"], item) for m in mutes)

    def usable(s):
        return s.get("status") == "ok" and sections_cfg.get(s.get("id"), {}).get("bucket") != "none"

    # First pass: what the advice says about tasks (a quiet task is shown once, under drop).
    quiet, blocked = set(), set()
    for s in result.get("sections") or []:
        if s.get("kind") != "advise" or not usable(s):
            continue
        for item in items_of(s):
            if muted(s["id"], item):
                continue
            if item.get("check") == "quiet" and item.get("task"):
                quiet.add(item["task"])
            if item.get("check") == "blocked" and item.get("task"):
                blocked.add(item["task"])

    def add(key, row):
        if key in out["rows"]:
            have = out["rows"][key]
            for sid in row["sources"]:
                if sid not in have["sources"]:
                    have["sources"].append(sid)
            # A section's own `bucket:` is the person's word and wins; otherwise the
            # more urgent reading of the same thing wins over profile order.
            if (row["forced"], -URGENCY[row["bucket"]]) > (have["forced"], -URGENCY[have["bucket"]]):
                have["bucket"], have["forced"] = row["bucket"], row["forced"]
            have["rank"] = min(have["rank"], row["rank"])
            have["why"] += [w for w in row["why"] if w not in have["why"]]
            for k in ("due", "nudge", "estimate", "inbox_id", "inbox_state", "inbox_key", "created", "gate", "urgency", "priority",
                      "has_action", "mark", "area", "origin_raw", "inbox_kind", "origin_provider", "about_task", "about_kind",
                      "ref", "url"):
                if row.get(k) and not have.get(k):
                    have[k] = row[k]
            if have.get("filed") and not row.get("filed"):
                have["title"] = row["title"]   # the source's wording today, not the day it was filed
                have["filed"] = False
            elif _shortened(have["title"], row["title"]):
                have["title"] = row["title"]   # a short tab label gives way to the full title of the same thing
            have["new"] = have["new"] or row["new"]
            have["changed"] = have["changed"] or row["changed"]
            return
        out["rows"][key] = row
        out["order"].append(key)

    # the kind and provider of each section, so a row says where it came from (cockpit origin.py)
    kinds_of = {s.get("id"): (s.get("kind"), s.get("provider")) for s in result.get("sections") or [] if isinstance(s, dict)}

    def row(sid, item, bucket, title, why=(), rank=5, **extra):
        kind, provider = kinds_of.get(sid, (None, None))
        r = {"title": str(title or ""), "bucket": bucket, "forced": sid in forced_ids,
             "mark": mark_for(marks, title, item),
             "why": [w for w in why if w], "sources": [sid],
             "rank": rank, "url": item.get("url"), "task": item.get("task"), "new": bool(item.get("new")),
             "changed": bool(item.get("changed")),
             "origin_section_kind": kind, "origin_provider": item.get("tracker") or provider}
        if _pos_int(item.get("estimate_min")):
            r["estimate"] = item["estimate_min"]
        return {**r, **extra}

    carried = []      # advice that only stands when no other row carries it
    forced_ids = {sid for sid, c in sections_cfg.items() if c.get("bucket") in BUCKETS}
    for s in result.get("sections") or []:
        sid, kind = s.get("id"), s.get("kind")
        cfg = sections_cfg.get(sid, {})
        # the kinds without status rows of their own still get one when they cannot run on this machine: a calendar
        # skipped for want of icalBuddy was otherwise just missing, with no word why (18.10.)
        quiet_kind = kind in ("calendar", "activity", "commits", "workplace", "advise")
        if s.get("status") in ("error", "skipped") and not (quiet_kind and s.get("left_out")):
            out["status"].append({"title": s.get("title") or sid, "status": s["status"],
                                  "reason": s.get("reason", ""),
                                  "health": sections_cfg.get(sid, {}).get("report_ok") is True,
                                  **({"left_out": True} if s.get("left_out") else {})})
        if s.get("status") == "error":
            out["hygiene"].append(labels["error"].format(title=s.get("title") or sid, reason=s.get("reason", "")))
            continue
        if not usable(s):
            continue
        forced = cfg.get("bucket") if cfg.get("bucket") in BUCKETS else None
        if kind not in ("calendar", "activity", "commits", "workplace", "advise"):
            title = s.get("title") or sid
            if title == sid:
                title = str(sid).replace("-", " ").capitalize()
            n = sum(1 for i in items_of(s) if not muted(sid, i) and i.get("state") not in ("done", "removed"))
            out["status"].append({"title": title, "count": n, "health": cfg.get("report_ok") is True})
            # issues assigned to you that no task tracks: counted over every row, not only the capped ones
            untracked = sum(1 for i in s.get("all") or items_of(s) if i.get("untasked") is True and not muted(sid, i))
            if untracked:
                out["hygiene"].append(labels["untasked"].format(title=title, n=untracked))
        if cfg.get("report_ok") is True and not any(
                not muted(sid, i) and i.get("state") not in ("done", "removed") for i in items_of(s)):
            # Green says so: an empty source is otherwise indistinguishable from one that never ran.
            out["clear"].append(labels["all_clear"].format(title=s.get("title") or sid))
        if kind == "calendar":
            out["events"] += items_of(s)
            continue
        if kind == "activity":
            continue
        if kind == "commits":
            # What moved, not what to do: one block of sparklines, never a bucket.
            # One block per section, titled by its own window.
            rows = items_of(s)
            days = len(rows[0].get("counts") or []) if rows else _int(s.get("days") or cfg.get("days"), 7, 1)
            if rows:
                out["activity"].append({"days": days or 7, "rows": rows})
            if s.get("skipped"):
                out["hygiene"].append(labels["repos_skipped"].format(n=len(s["skipped"]),
                                                                     names=", ".join(s["skipped"])))
            continue
        if s.get("summary"):
            have = {(b.get("org"), b.get("number")) for b in out["boards"]}
            for b in s["summary"]:
                if isinstance(b, dict) and b.get("open") and (b.get("org"), b.get("number")) not in have:
                    out["boards"].append(b)
                    have.add((b.get("org"), b.get("number")))
        if kind == "workplace":
            tabs = [i for i in items_of(s) if i.get("state") != "warning"]
            for i in items_of(s):
                if i.get("state") == "warning":
                    out["hygiene"].append(str(i.get("title")))
            if tabs:
                out["workplace"] = labels["workplace"].format(
                    n=len(tabs), new=sum(1 for t in tabs if t.get("state") == "new"),
                    resume=sum(1 for t in tabs if t.get("state") == "resume"))
            continue
        for item in items_of(s):
            if muted(sid, item):
                out["muted"] += 1
                continue
            iid = str(item.get("id"))
            if kind == "inbox":
                due = _when(item.get("due"))
                why = []
                if item.get("state") == "deferred":
                    back = _when(item.get("until"))
                    if back:
                        why.append(labels["back_on"].format(date=f"{back:%d.%m}"))
                if item.get("due"):
                    why.append(labels["due"].format(when=_fmt_when(item["due"], now, labels)))
                if item.get("gate") == "only-you":
                    why.append(labels["only_you"])
                soon = due is not None and due.date() <= horizon
                if item.get("state") == "deferred":
                    bucket = "do" if soon or item.get("gate") == "only-you" else "plan"
                else:
                    bucket = "do" if item.get("urgency") in ("now", "today") or soon else "plan"
                rank = 0 if item.get("urgency") == "now" else 1 if soon else 2
                # An item the briefing filed from a tracker row is that row: one line, not two.
                key = f"inbox:{iid}"
                filed = str(item.get("key") or "").split(":", 3)
                if filed[0] == "briefing" and len(filed) == 4:
                    key = _item_key(filed[2], filed[3])
                add(key, row(sid, item, forced or bucket, item.get("title"), why, rank, due=item.get("due"),
                             filed=key != f"inbox:{iid}", inbox_id=iid, gate=item.get("gate"),
                             urgency=item.get("urgency"), has_action=bool(item.get("has_action")),
                             inbox_state=item.get("state"), inbox_key=item.get("key"),
                             # the area it was given (inbox.py area, or the router on add); a task's area wins later
                             area=item.get("area") or None,
                             # who filed it (inbox.py `from`) and what it is (decision, finding ...): the page names both
                             origin_raw=item.get("from") or None, inbox_kind=item.get("kind") or None,
                             # what a person sees it as (ask, report, idea): only an ask counts as "for you"
                             art=art_of_kind(item.get("kind")),
                             # an inbox item's changed_at is when it was filed (briefing.py sec_inbox: item.created)
                             created=item.get("changed_at") or None))
            elif kind == "advise":
                check = item.get("check")
                if check == "wip":
                    out["hygiene"].append(str(item.get("title")))
                elif check == "quiet":
                    add(f"task:{item.get('task')}", row(sid, item, forced or "drop", item.get("title"), (), 5))
                elif check == "collision":
                    add(f"advise:{iid}", row(sid, item, forced or "do", item.get("title"), [labels["collides"]], 0))
                elif check in ("blocked", "waiting", "due"):
                    carried.append((sid, item, forced))
                else:
                    add(f"advise:{iid}", row(sid, item, forced or "plan", item.get("title")))
            elif kind == "tasks":
                if iid in quiet:
                    continue
                nxt = item.get("next")
                if isinstance(nxt, str):
                    nxt = {"what": nxt}
                age = _days_since(item.get("changed_at"), now)
                if item.get("blocked_by"):
                    age = _days_since(item.get("blocked_since"), now) if item.get("blocked_since") else age
                    why = [labels["waiting_days"].format(n=age) if age is not None else "",
                           _short(item["blocked_by"], 60)]
                    nudge = iid in blocked or (age is not None and age >= nudge_days)
                    look = _when(item.get("quiet_until"))
                    if look is not None:
                        # "runs on" (task.py wait): quiet until the day it names, from that day on it asks
                        why.append(labels["look_again"].format(when=_fmt_when(item["quiet_until"], now, labels)))
                        nudge = look.date() <= now.date()
                    add(f"task:{iid}", row(sid, item, forced or "waiting", item.get("title"), why, 3, nudge=nudge,
                                           task=iid, priority=item.get("priority"), origin_raw=item.get("origin")))
                elif isinstance(nxt, dict) and nxt.get("what"):
                    who = str(nxt.get("who") or "me").lower()
                    due = _when(nxt.get("due"))
                    why = [labels["task"].format(slug=iid)]
                    if nxt.get("due"):
                        why.append(labels["due"].format(when=_fmt_when(nxt["due"], now, labels)))
                    extra = {"task": iid, "due": nxt.get("due"), "priority": item.get("priority"), "origin_raw": item.get("origin")}
                    if _pos_int(nxt.get("estimate_min")):
                        extra["estimate"] = nxt["estimate_min"]
                    if who in WHO_BRIDGE:
                        bucket = "delegate"
                    elif who in you:
                        bucket = "do" if due is not None and due.date() <= horizon else "plan"
                    else:
                        bucket = "waiting"
                        why = [labels["with"].format(who=nxt.get("who")),
                               labels["waiting_days"].format(n=age) if age is not None else ""] + why
                        extra["nudge"] = age is not None and age >= nudge_days
                    add(f"task:{iid}", row(sid, item, forced or bucket, nxt["what"], why,
                                           1 if bucket == "do" else 4, **extra))
                else:
                    out["no_next"].append(iid)
            else:   # tracker, command
                state = item.get("state")
                if state in ("done", "removed"):
                    continue
                if item.get("category") == "qa" or state == "review":
                    bucket = "do"
                elif state == "blocked":
                    bucket = "waiting"
                else:
                    bucket = "plan"
                label = item.get("raw_state") or state
                add(_item_key(sid, iid), row(sid, item, forced or bucket, item.get("title"),
                                             [iid, str(label) if label else ""], 2 if bucket == "do" else 4,
                                             ref=iid, about_task=item.get("about_task"), about_kind=item.get("about_kind")))

    # blocked / waiting / due advice repeats what a task or inbox row already says;
    # it stands on its own only when no such row is in the view.
    for sid, item, forced in carried:
        check = item.get("check")
        subject = str(item.get("id") or "").split(":", 2)[-1]
        carrier = f"task:{item.get('task')}" if check == "blocked" else f"inbox:{subject}"
        if carrier in out["rows"]:
            continue
        bucket = {"blocked": "waiting", "due": "do", "waiting": "plan"}[check]
        add(f"advise:{item.get('id')}", row(sid, item, forced or bucket, item.get("title"), (), 2))
    return out


def build(result: dict, profile: dict, style: str | None = None) -> dict:
    """The view of one collected briefing: plain data, drawn by `draw`, read by an agent."""
    style = style_of(profile, style)
    view = _cfg(profile)
    labels = _labels(view, profile.get("_language"))
    now = _when(result.get("collected_at")) or dt.datetime.now()
    data = _rows(result, profile, view, labels, now)
    shown, hidden_ids = _bucket_cfg(view)
    titles = {b: DEFAULT_BUCKETS[b]["title"] for b in BUCKETS} | {b["id"]: b["title"] for b in shown}

    # An info event (an `info_calendars` calendar, e.g. a family one) is someone else's:
    # it is listed, but it neither makes the reader busy nor raises a clash.
    events = _events([e for e in data["events"] if e.get("info") is not True], now)
    real = set(events)
    agenda = []
    if view.get("agenda", True) is not False:
        horizon = dt.datetime.combine(now.date() + dt.timedelta(days=_int(view.get("lookahead_days"), 1) + 1),
                                      dt.time())
        seen = set()
        for s_, e_, t_ in _events(data["events"], now):
            if e_ > now and s_ < horizon and (s_, e_, t_) not in seen:   # one event from two calendars
                seen.add((s_, e_, t_))
                agenda.append({"start": s_, "end": e_, "title": t_,
                               **({"info": True} if (s_, e_, t_) not in real else {})})
        # Overlaps as clusters: A-B-C overlapping is one decision, not three.
        cluster, reach = [], None
        for a in agenda + [None]:
            if a is not None and reach is not None and a["start"] < reach:
                cluster.append(a)
                reach = max(reach, a["end"])
                continue
            names = [c["title"] for c in cluster if not c.get("info")]
            if len(cluster) > 1:
                side = [c["title"] for c in cluster if c.get("info")]
                for c in cluster:
                    if c.get("info") or len(names) < 2:
                        others = [c_["title"] for c_ in cluster if c_ is not c]
                        c["parallel"] = ", ".join(others)
                    else:
                        c["clash"] = ", ".join(n for n in names if n != c["title"]) or c["title"]
                        if side:
                            c["parallel"] = ", ".join(side)
            if len(names) > 1:
                key = f"clash:{cluster[0]['start']:%Y%m%d%H%M}:" + "|".join(names)
                if style != "plan" and key not in data["rows"]:
                    data["rows"][key] = {
                        "title": labels["clash_row"].format(
                            first=", ".join(names[:-1]), second=names[-1],
                            when=_fmt_when(cluster[0]["start"].isoformat(timespec="minutes"), now, labels)),
                        "bucket": "do", "forced": False, "why": [], "sources": ["calendar"],
                        "rank": 0, "url": None, "task": None, "new": False, "changed": False}
                    data["order"].append(key)
            cluster, reach = ([a], a["end"]) if a is not None else ([], None)

        def day(when):
            return _fmt_when(when.date().isoformat(), now, labels)
        for a in agenda:
            tail = f"{a['end']:%H:%M}" if a["end"].date() == a["start"].date() else f"{day(a['end'])} {a['end']:%H:%M}"
            a["when"] = f"{day(a['start'])} {a['start']:%H:%M}-{tail}"
            a["start"], a["end"] = a["start"].isoformat(timespec="minutes"), a["end"].isoformat(timespec="minutes")

    rows = [data["rows"][k] for k in data["order"]]
    if not result.get("previous_at"):
        # A first run has nothing to compare with: every row would say "new".
        for r in rows:
            r["new"] = r["changed"] = False
    rows.sort(key=lambda r: (URGENCY[r["bucket"]], r["rank"], str(_when(r.get("due")) or "9999")))

    hygiene = list(data["hygiene"]) + [str(n) for n in result.get("housekeeping") or []]
    if result.get("owed"):
        hygiene.append(labels["owed"].format(streams=", ".join(result["owed"])))
    if data["no_next"]:
        hygiene.append(labels["no_next"].format(n=len(data["no_next"]), slugs=", ".join(data["no_next"])))
    if data["muted"]:
        hygiene.append(labels["muted"].format(n=data["muted"]))
    hidden = [r for r in rows if r["bucket"] in hidden_ids]
    if hidden:
        ids = sorted({r["bucket"] for r in hidden}, key=lambda b: URGENCY[b])
        hygiene.append(labels["hidden"].format(n=len(hidden), ids=", ".join(ids)))
    visible = [r for r in rows if r["bucket"] not in hidden_ids]

    plan_cfg: dict = view["plan"] if isinstance(view.get("plan"), dict) else {}
    workday: dict = plan_cfg["workday"] if isinstance(plan_cfg.get("workday"), dict) else {}
    day_start, day_end = workday.get("start", "08:00"), workday.get("end", "18:00")
    if not (isinstance(day_start, str) and HHMM.match(day_start) and isinstance(day_end, str)
            and HHMM.match(day_end) and _hm(day_start) < _hm(day_end)):
        day_start, day_end = "08:00", "18:00"

    width = view.get("width")
    out = {"style": style, "collected_at": result.get("collected_at"), "headline": None, "since": None,
           "buckets": [], "hygiene": hygiene, "workplace": data["workplace"], "more": 0, "titles": titles,
           "answer_keys": view.get("answer_keys", True) is not False,
           "show_hygiene": view.get("hygiene", "bottom") != "hide",
           "color": view.get("color", "auto"), "width": width if _pos_int(width) and width >= 40 else 100,
           "labels": labels,
           "activity": data["activity"],
           "boards": data["boards"], "overview": view.get("overview", "inline"), "status": data["status"],
           "report": view.get("report") if isinstance(view.get("report"), dict) else {}, "agenda": agenda if style != "plan" else [], "clear": data["clear"]}

    if view.get("headline", True) is not False:
        out["headline"] = _headline(visible, events, now, labels, day_end)
    out["dayline"] = None
    if view.get("dayline", True) is not False and style != "brevity":
        out["dayline"] = _dayline(events, now, day_start, day_end)
    if view.get("since_last", True) is not False and result.get("previous_at"):
        prev = _when(result["previous_at"])
        if prev:
            stamp = f"{prev:%H:%M}" if prev.date() == now.date() else f"{prev:%d.%m %H:%M}"
            out["since"] = labels["since"].format(time=stamp, new=sum(1 for r in visible if r["new"]),
                                                   changed=sum(1 for r in visible if r["changed"] and not r["new"]))

    cap = _int(view.get("max_items"), 3 if style == "brevity" else 12, 1)
    if style == "brevity":
        cap = min(cap, 3)
        pick = ([r for r in visible if r["bucket"] == "do"] +
                [r for r in visible if r["bucket"] == "waiting" and r.get("nudge")] +
                [r for r in visible if r["bucket"] in ("plan", "delegate")] +
                [r for r in visible if r["bucket"] == "waiting" and not r.get("nudge")] +
                [r for r in visible if r["bucket"] == "drop"])
        out["top"] = [{**r, "why": r["why"] or [titles[r["bucket"]]]} for r in pick[:cap]]
        out["more"] = max(0, len(visible) - len(out["top"]))
        return out

    if style == "plan":
        # The plan shows every row (laid out, meanwhile, waiting, drop, later): nothing is "more".
        out["plan"] = _plan(visible, events, now, plan_cfg, day_start, day_end)
        return out

    left = cap
    for b in shown:
        mine = [r for r in visible if r["bucket"] == b["id"]]
        take = mine[:max(0, left)]
        left -= len(take)
        out["more"] += len(mine) - len(take)
        if take:
            out["buckets"].append({"id": b["id"], "title": b["title"], "options": list(b.get("options") or []),
                                   "items": take, "total": len(mine)})
    return out


def asks_you(row: dict) -> bool:
    """Whether a row counts as waiting for you: every row that is no inbox item (a task, a board item), and of
    the inbox only the asks. An idea or a report due today still stands in Do, it just asks nothing of you. Read
    from the kind, so the cockpit (bridge_cockpit/model.py) counts its rows by the same rule."""
    return not row.get("inbox_id") or art_of_kind(row.get("inbox_kind")) == "ask"


def _headline(rows: list, events: list, now: dt.datetime, labels: dict, day_end: str) -> str:
    parts = [labels["yours_today"].format(n=sum(1 for r in rows if r["bucket"] == "do" and asks_you(r)))]
    current = next((e for e in events if e[0] <= now < e[1]), None)
    upcoming = next((e for e in events if e[0] > now and e[0].date() == now.date()), None)
    if current:
        parts.append(labels["busy_until"].format(title=_short(current[2], 40),
                                                 time=_fmt_when(current[1].isoformat(timespec="minutes"),
                                                                now, labels).replace(f"{labels['today']} ", "")))
    elif upcoming:
        parts.append(labels["free_until"].format(time=f"{upcoming[0]:%H:%M}"))
    elif now.hour * 60 + now.minute < _hm(day_end):
        parts.append(labels["free_rest"])
    dated = [(_when(r["due"]), r["title"], r["due"]) for r in rows if r.get("due") and _when(r["due"])]
    dated += [(e[0], e[2], e[0].isoformat(timespec="minutes")) for e in events if e[0].date() > now.date()]
    dated = sorted((d for d in dated if d[0] > now), key=lambda d: d[0])
    if dated:
        _, title, raw = dated[0]
        parts.append(labels["next_date"].format(when=_fmt_when(raw, now, labels), title=_short(title, 48)))
    return " · ".join(parts)


DAYLINE_CELLS = 40


def _dayline(events, now, day_start, day_end) -> str:
    """The workday as one line: · free, █ busy, ▲ now. Read at a glance, no legend needed."""
    start, end = _hm(day_start), _hm(day_end)
    span = end - start
    busy = _today(events, now)
    now_min = now.hour * 60 + now.minute
    cells = []
    for i in range(DAYLINE_CELLS):
        t = start + i * span / DAYLINE_CELLS
        cells.append("█" if any(s <= t < e for s, e, _ in busy) else "·")
    if start <= now_min < end:
        cells[int((now_min - start) / span * DAYLINE_CELLS)] = "▲"
    return f"{day_start} {''.join(cells)} {day_end}"


def _plan(rows, events, now, cfg, day_start, day_end) -> dict:
    """Lay your rows (do, then plan) into today's free gaps between start and end of day.

    Each row takes the earliest free gap long enough for it, so a long row that does not
    fit early never pushes a short one past a gap it would have fitted."""
    minutes = _int(cfg.get("default_minutes"), 30, 1)
    busy = sorted(_today(events, now))
    now_min = now.hour * 60 + now.minute
    first = max(_hm(day_start), -(-now_min // 15) * 15)
    stop = _hm(day_end)
    free, cursor = [], first
    for s, e, _ in busy:
        if s > cursor:
            free.append([cursor, min(s, stop)])
        cursor = max(cursor, e)
    if cursor < stop:
        free.append([cursor, stop])
    free = [f for f in free if f[1] > f[0]]
    slots = [{"start": _clock(s), "end": _clock(e), "title": t, "kind": "event"} for s, e, t in busy]
    later = []
    for r in [r for r in rows if r["bucket"] == "do"] + [r for r in rows if r["bucket"] == "plan"]:
        length = r.get("estimate") or minutes
        gap = next((f for f in free if f[1] - f[0] >= length), None)
        if gap is None:
            later.append(r["title"])
            continue
        slots.append({"start": _clock(gap[0]), "end": _clock(gap[0] + length), "title": r["title"],
                      "kind": "work", "why": r["why"]})
        gap[0] += length
    slots.sort(key=lambda s: (s["start"], s["kind"] != "event"))
    return {"slots": slots, "parallel": [r["title"] for r in rows if r["bucket"] == "delegate"],
            "waiting": [r["title"] for r in rows if r["bucket"] == "waiting"],
            "drop": [r["title"] for r in rows if r["bucket"] == "drop"], "later": later, "shutdown": day_end}


# ---------------------------------------------------------------- draw

def _agenda_title(a: dict, labels: dict) -> str:
    """An agenda entry's title, an info event's tagged as such."""
    return f"{a['title']} [{labels['info_tag']}]" if a.get("info") else a["title"]


def draw(view: dict, color: bool = False, width: int | None = None) -> str:
    """Terminal text. Colour carries meaning only (due now, waiting, scaffolding dimmed)."""
    if view.get("style") == "report":
        return draw_report(view)
    use = color and view.get("color", "auto") != "none"
    width = width or _int(view.get("width"), 100, 40)
    labels = view["labels"]
    titles = view.get("titles") or {b: DEFAULT_BUCKETS[b]["title"] for b in BUCKETS}

    def c(code, text):
        return f"\x1b[{code}m{text}\x1b[0m" if use else text

    def wrap(text, indent="", hang=None, style=None):
        lines = textwrap.wrap(text, width=width, initial_indent=indent, subsequent_indent=hang or indent,
                              break_long_words=False, break_on_hyphens=False) or [indent]
        return [c(style, line) if style else line for line in lines]

    out = []
    if view.get("headline"):
        out += wrap(view["headline"], style="1")
    if view.get("since"):
        out += wrap(view["since"], style="2")
    if view.get("dayline"):
        out.append(c("2", view["dayline"]) if use else view["dayline"])
    for line in view.get("clear") or []:
        out += wrap(f"✓ {line}", style="2")
    if view.get("agenda"):
        out.append("")
        out += wrap(f"── {labels['agenda_title']} ──", style="1")
        for a in view["agenda"]:
            clash = f"  ({labels['clashes'].format(title=a['clash'])})" if a.get("clash") else ""
            side = f"  ({labels['parallel'].format(title=a['parallel'])})" if a.get("parallel") else ""
            out += wrap(f"{a['when']}  {_agenda_title(a, labels)}{clash}{side}", indent="  ", hang="    ",
                        style="31" if clash else "2" if a.get("info") else None)

    if view["style"] == "brevity":
        for r in view.get("top", []):
            out.append("")
            out += wrap(_marked(r) + r["title"], style="1")
            out += wrap(f"{labels['why']}: " + " · ".join(r["why"]), indent="  ", hang="  ", style="2")
    elif view["style"] == "plan" and view.get("plan"):
        plan = view["plan"]
        out.append("")
        for s in plan["slots"]:
            line = f"  {s['start']}-{s['end']}  {s['title']}"
            out += wrap(line, hang=" " * 15, style="2" if s["kind"] == "event" else None)
        for key, title, style in (("parallel", labels["meanwhile"], None), ("waiting", titles["waiting"], "2"),
                                  ("drop", titles["drop"], "2"), ("later", labels["later"], "2")):
            if plan.get(key):
                out += wrap(f"{title}: " + " · ".join(plan[key]), indent="  ", hang="    ", style=style)
        out += wrap(labels["shutdown"].format(time=plan["shutdown"]), indent="  ", style="1")
    else:
        n = 0
        for b in view["buckets"]:
            out.append("")
            head = f"── {b['title']} · {b.get('total', len(b['items']))} ──"
            if view.get("answer_keys") and b.get("options"):
                letters = "abcdefghij"
                head += " " + " · ".join(f"{letters[i]} {o}" for i, o in enumerate(b["options"][:10]))
            out += wrap(head, style="1;31" if b["id"] == "do" else "2" if b["id"] in ("waiting", "drop") else "1")
            for r in b["items"]:
                n += 1
                num = f"{n:>3}  " if view.get("answer_keys") else "  -  "
                extras = list(r["why"])
                if len(r["sources"]) > 1:
                    extras.append("+".join(r["sources"]))
                if r.get("nudge"):
                    extras.append(labels["nudge"])
                if r["new"]:
                    extras.append(labels["new"])
                text = _marked(r) + r["title"] + (f"  ({' · '.join(extras)})" if extras else "")
                lines = textwrap.wrap(text, width=width, initial_indent=num, subsequent_indent=" " * len(num),
                                      break_long_words=False, break_on_hyphens=False)
                urgent = b["id"] == "do" and r["rank"] <= 1
                dim = b["id"] in ("waiting", "drop") and not r.get("nudge")
                lines = [c("31", line) if urgent else c("2", line) if dim else line for line in lines]
                ref, url = r.get("ref"), str(r.get("url") or "")
                if use and ref and url.startswith(("https://", "http://")):
                    # OSC 8: the id itself is the link, in terminals that support it; others show the id.
                    link = f"\x1b]8;;{url}\x1b\\{ref}\x1b]8;;\x1b\\"
                    lines = [line.replace(ref, link, 1) if ref in line else line for line in lines]
                out += lines

    if view.get("overview", "inline") != "file":
        out += _overview_lines(view, width, c, wrap)
    if view.get("workplace") and view["style"] != "brevity":
        out.append("")
        out += wrap(view["workplace"])
    # Housekeeping in every style: a failed source or a muted row is never silent.
    if view.get("show_hygiene", True) and view.get("hygiene"):
        out.append("")
        out += wrap(f"── {labels['housekeeping']} ──", style="2")
        for h in view["hygiene"]:
            out += wrap(h, indent="  · ", hang="    ", style="2")
    out.append("")
    if view.get("more"):
        out += wrap(labels["more"].format(n=view["more"]), style="2")
    out += wrap(labels["end"], style="2")
    return "\n".join(out)


def _overview_lines(view: dict, width: int, c, wrap) -> list:
    """Boards and Activity: what moved, never what to do."""
    labels = view["labels"]
    out = []
    if view["style"] != "brevity" and view.get("boards"):
        out.append("")
        out += wrap(f"── {labels['boards_title']} ──", style="1")
        for b in view["boards"]:
            counts = b.get("counts") or {}
            parts = [f"{counts[st]} {labels['st_' + st]}" for st in BOARD_STATES if counts.get(st)]
            capped = f" {labels['capped'].format(n=b['capped'])}" if b.get("capped") else ""
            out += wrap(f"#{b.get('number')} {b.get('name')}: " + (" · ".join(parts) or "0") + capped,
                        indent="  ", hang="    ")
    for act in (view.get("activity") or []) if view["style"] != "brevity" else []:
        out.append("")
        out += wrap(f"── {labels['activity_title'].format(days=act['days'])} ──", style="1")
        rows = act["rows"]
        spark_w = max(len(str(r.get("spark", ""))) for r in rows)
        tail_w = max(len(labels["commits"].format(n=r.get("total", 0))) for r in rows)
        name_w = min(24, max(len(str(r.get("id"))) for r in rows))
        branch_w = min(14, max(len(str(r.get("branch") or "")) for r in rows))
        room = width - (2 + 2 + spark_w + 2 + tail_w)
        if name_w + 2 + branch_w > room:          # narrow: the branch goes first, then the name shortens
            branch_w = 0
            name_w = max(8, min(name_w, room))
        for r in rows:
            branch = f"{str(r.get('branch') or '')[:branch_w]:<{branch_w}}  " if branch_w else ""
            out.append(f"  {str(r.get('id'))[:name_w]:<{name_w}}  {branch}"
                       f"{r.get('spark', '')}  {labels['commits'].format(n=r.get('total', 0))}")
    return out


def draw_overview(view: dict, color: bool = False, width: int | None = None) -> str:
    """Boards and Activity on their own, for `overview: file`."""
    use = color and view.get("color", "auto") != "none"
    width = width or _int(view.get("width"), 100, 40)

    def c(code, text):
        return f"\x1b[{code}m{text}\x1b[0m" if use else text

    def wrap(text, indent="", hang=None, style=None):
        lines = textwrap.wrap(text, width=width, initial_indent=indent, subsequent_indent=hang or indent,
                              break_long_words=False, break_on_hyphens=False) or [indent]
        return [c(style, line) if style else line for line in lines]
    return "\n".join(_overview_lines(view, width, c, wrap)).lstrip("\n") + "\n"


# ---------------------------------------------------------------- report (markdown)

def _cell(text) -> str:
    return " ".join(str(text if text is not None else "").split()).replace("|", "\\|")


def _table(head: list, rows: list) -> list:
    out = ["| " + " | ".join(_cell(h) for h in head) + " |", "|" + "---|" * len(head)]
    out += ["| " + " | ".join(_cell(c) for c in r) + " |" for r in rows]
    return out


def _why(r: dict, labels: dict) -> str:
    """The reason, not the plumbing: an id that names nothing a person can open goes,
    an issue or PR id becomes its link."""
    ref, url = r.get("ref"), str(r.get("url") or "")
    extras = []
    for w in r["why"]:
        if w and w == ref:
            if GLOBAL_ID.match(str(ref)):
                extras.append(f"[{ref}]({url})" if url.startswith(("https://", "http://")) else ref)
            continue
        extras.append(w)
    if r.get("nudge"):
        extras.append(labels["nudge"])
    if r["new"]:
        extras.append(labels["new"])
    return " · ".join(e for e in extras if e)


def _mix(rows: list, k: int) -> list:
    """The first k rows taken in turn from each source, order kept within a source:
    a capped bucket shows a mix instead of k rows of whichever source came first."""
    queues: dict = {}
    for r in rows:
        queues.setdefault(r["sources"][0] if r.get("sources") else "", []).append(r)
    picked = []
    while len(picked) < k and any(queues.values()):
        for q in queues.values():
            if q and len(picked) < k:
                picked.append(q.pop(0))
    order = {id(r): i for i, r in enumerate(rows)}
    return sorted(picked, key=lambda r: order[id(r)])


def draw_report(view: dict) -> str:
    """Markdown that reads like a report, by exception: one status line naming only
    what failed or needs a look, the first few things in bold, short lists per bucket
    with the rest counted, tables only where rows compare (calendar, boards, activity)."""
    labels = view["labels"]
    rcfg = view.get("report") or {}
    top, per_bucket = _int(rcfg.get("top"), 3, 1), _int(rcfg.get("per_bucket"), 5, 1)
    when = _when(view.get("collected_at"))
    out = [f"## {labels['report_title'].format(date=f'{when:%d.%m. %H:%M}' if when else '')}".rstrip(), ""]
    if view.get("headline"):
        out += [f"**{view['headline']}**", ""]

    failed = [st for st in view.get("status") or [] if st.get("status") == "error"]
    warn = [st for st in view.get("status") or [] if st.get("health") and not st.get("status") and st["count"]]
    clear = [st["title"] for st in view.get("status") or [] if st.get("health") and not st.get("status")
             and not st["count"]]
    parts = [f"✗ {st['title']} ({_short(st.get('reason', ''), 50)})" for st in failed]
    parts += [f"⚠ {st['title']} ({st['count']})" for st in warn]
    if clear:
        parts.append("✓ " + ", ".join(clear))
    if parts:
        out += [f"**{labels['lage']}:** " + " · ".join(parts), ""]

    agenda = view.get("agenda") or []
    if len(agenda) == 1:
        a = agenda[0]
        out += [f"**{labels['agenda_title']}:** {a['when']} {_agenda_title(a, labels)}", ""]
    elif agenda:
        out += _table([labels["col_when"], labels["col_what"], labels["col_note"]],
                      # the do row explains a clash; the table only marks it. A parallel
                      # info event has no do row, so the note names it.
                      [[a["when"], _agenda_title(a, labels),
                        " · ".join(([("⚠")] if a.get("clash") else []) +
                                   ([labels["parallel"].format(title=a["parallel"])] if a.get("parallel") else []))]
                       for a in agenda]) + [""]

    rows = [(b, r) for b in view.get("buckets") or [] for r in b["items"]]
    n = 0
    if rows:
        out += [f"### {labels['first_title']}", ""]
        for b, r in rows[:top]:
            n += 1
            why = _why(r, labels)
            out.append(f"{n}. {_marked(r)}**{_short(r['title'], 120)}**" + (f" ({why})" if why else ""))
        out.append("")
    shown_first = {id(r) for _, r in rows[:top]}
    for b in view.get("buckets") or []:
        rest = [r for r in b["items"] if id(r) not in shown_first]
        if not rest:
            continue
        head = f"### {b['title']} · {b.get('total', len(b['items']))}"
        if view.get("answer_keys") and b.get("options"):
            head += "  *(" + " · ".join(f"{'abcdefghij'[i]} {o}" for i, o in enumerate(b["options"][:10])) + ")*"
        out += [head, ""]
        for r in _mix(rest, per_bucket):
            n += 1
            why = _why(r, labels)
            out.append(f"{n}. {_marked(r)}{_short(r['title'], 120)}" + (f" ({why})" if why else ""))
        hidden = len(rest) - per_bucket + (b.get("total", len(b["items"])) - len(b["items"]))
        if hidden > 0:
            out.append(f"\n*{labels['bucket_more'].format(n=hidden)}*")
        out.append("")

    if view.get("overview", "inline") != "file":
        if view.get("boards"):
            out += [f"### {labels['boards_title']}", ""]
            out += _table([labels["col_board"]] + [labels["st_" + st] for st in BOARD_STATES],
                          [[f"#{b.get('number')} {b.get('name')}" + (f" {labels['capped'].format(n=b['capped'])}"
                                                                    if b.get("capped") else "")]
                           + [str((b.get("counts") or {}).get(st) or "") for st in BOARD_STATES]
                           for b in view["boards"]]) + [""]
        for act in view.get("activity") or []:
            out += [f"### {labels['activity_title'].format(days=act['days'])}", ""]
            out += _table([labels["col_repo"], labels["col_branch"], labels["col_days"].format(days=act["days"]),
                           labels["col_commits"]],
                          [[r.get("id"), r.get("branch") or "", r.get("spark", ""), str(r.get("total", 0))]
                           for r in act["rows"]]) + [""]
    if view.get("workplace"):
        out += [view["workplace"], ""]
    if view.get("show_hygiene", True) and view.get("hygiene"):
        out += [f"*{labels['housekeeping']}:* " + " · ".join(view["hygiene"]), ""]
    out.append(f"*{labels['end']}*")
    return "\n".join(out)


# ---------------------------------------------------------------- dashboard pages

def _page_when(value, now: dt.datetime, labels: dict) -> str:
    """Today as its time alone, an earlier day as its date, a later one as `_fmt_when`
    says it; nothing for no date."""
    when = _when(value)
    if when is None:
        return ""
    if when.date() == now.date():
        return f"{when:%H:%M}" if _has_time(value) else labels["today"]
    if when.date() < now.date():   # the hour of an earlier change is noise
        return f"{when:%d.%m}"
    return _fmt_when(value, now, labels)


def _text(value) -> str:
    if isinstance(value, list):
        return ", ".join(str(v) for v in value if v not in (None, ""))
    return "" if value in (None, "") else str(value)


def _today_count(item: dict) -> int:
    counts = item.get("counts")
    return counts[-1] if isinstance(counts, list) and counts and isinstance(counts[-1], int) else 0


SECRET_QUERY = re.compile(r"(?:^|&)(?:code|token|access_token|sig|signature|key|apikey|api_key|password|secret)=",
                          re.I)


def _safe_link(link, root: Path | None) -> str | None:
    """A link a dashboard may show and hand to the agent: a web address without
    credentials (none at all when its query carries a key), or a file inside the Bridge."""
    if not isinstance(link, str) or not link:
        return None
    if link.startswith(("http://", "https://")):
        parts = urllib.parse.urlsplit(link)
        if SECRET_QUERY.search(parts.query):
            return None
        host = parts.hostname or ""
        netloc = host + (f":{parts.port}" if parts.port else "")
        return urllib.parse.urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))
    if root is None:
        return None
    base = root.resolve()
    path = (Path(link) if Path(link).is_absolute() else base / link).resolve()
    if path != base and base not in path.parents:   # never a file outside the Bridge
        return None
    return path.as_uri() if path.exists() else None


def meter_of(value) -> dict | None:
    """A row's optional gauge, as a source hands it: `value` (a number from 0), `max` (above 0; without
    it a dashboard scales the rows of a section against each other), `unit` (up to 8 characters) and
    `elapsed` (0 to 1: how much of the time window behind the value has passed), `window_h` (how long
    that window is, in hours, up to a year: with it a dashboard reckons the share per day), and against a max
    `warn` and `bad`, where those ranges begin. A dashboard draws it as
    a bar; a field it cannot trust becomes None, a value it cannot read drops the whole gauge."""
    if not isinstance(value, dict):
        return None
    def num(x):
        return float(x) if isinstance(x, (int, float)) and not isinstance(x, bool) and x == x and abs(x) != float("inf") else None
    v = num(value.get("value"))
    if v is None or v < 0:
        return None
    top, elapsed, unit = num(value.get("max")), num(value.get("elapsed")), value.get("unit")
    window = num(value.get("window_h"))
    top = top if top is not None and top > 0 else None
    # where warning and bad begin, in the value's unit: only against a max, inside it, warn before bad
    warn, bad = (num(value.get(k)) for k in ("warn", "bad"))
    warn, bad = (x if top is not None and x is not None and 0 <= x <= top else None for x in (warn, bad))
    if warn is not None and bad is not None and bad <= warn:
        warn = bad = None
    return {"value": v, "max": top,
            "unit": unit if isinstance(unit, str) and 0 < len(unit) <= 8 else None,
            "elapsed": elapsed if elapsed is not None and 0 <= elapsed <= 1 else None,
            "warn": warn, "bad": bad, "window_h": window if window is not None and 0 < window <= 24 * 366 else None}


def _page_row(kind: str, item: dict, entry: dict, now: dt.datetime, labels: dict, root: Path | None = None,
              marks: list = ()) -> dict:
    """One row as every page draws it: when, title, detail, tone, url; plus what it leads to:
    the task (its tab) and whether it is worth asking about (a finding, an issue)."""
    iid = _text(item.get("id"))
    title = (_text(item.get("title")) or iid).replace("**", "")   # a log line's bold is markup, not text
    if kind == "tracker" and GLOBAL_ID.match(iid) and not title.startswith(iid):
        title = f"{iid} {title}"
    state = _text(item.get("raw_state")) or _text(item.get("state"))

    if "when" in entry:
        when = _page_when(item.get(entry["when"]), now, labels)
    elif kind == "commits":
        when = labels["commits_today"].format(n=_today_count(item))
    elif kind == "calendar":
        when = _page_when(item.get("start"), now, labels)
    elif kind == "command":
        when = _page_when(item.get("due"), now, labels)   # a probe stamps every row with the run time
    else:
        when = _page_when(item.get("due") or item.get("changed_at"), now, labels)

    if "detail" in entry:
        fields = [entry["detail"]] if isinstance(entry["detail"], str) else entry["detail"]
        parts = [_text(item.get(f)) for f in fields]
    elif kind == "calendar":
        end = _when(item.get("end"))
        start = _when(item.get("start"))
        parts = [labels["until"].format(time=f"{end:%H:%M}") if end and start and end.date() == start.date() else "",
                 _text(item.get("calendar")), labels["info_tag"] if item.get("info") is True else ""]
    elif kind == "tracker":
        project = _text(item.get("project"))
        linked = item.get("linked_task") if isinstance(item.get("linked_task"), dict) else {}
        prs = [p for p in item.get("prs") or [] if isinstance(p, dict) and _text(p.get("id"))]
        parts = ["PR" if item.get("type") == "pr" else "", state,
                 "" if project and iid.startswith(project) or entry.get("view") == "board" else project,
                 _text(item.get("priority")), _text(item.get("note")),
                 " ".join(f"PR #{_text(p['id']).rsplit('#', 1)[-1]}" + (f" ({labels['gh_draft']})" if p.get("draft") else "")
                          for p in prs),
                 labels["gh_task"].format(slug=_text(linked.get("slug"))) if _text(linked.get("slug")) else ""]
    elif kind == "commits":
        parts = [f"{_text(item.get('spark'))} {_text(item.get('branch'))}".strip()]
    elif kind in ("activity", "workplace"):
        parts = [_text(item.get("project"))]
    elif kind == "inbox" and _text(item.get("waiting_on")):
        # runs on: what it waits on and the day to look again say more than kind and gate
        parts = [_short(_text(item["waiting_on"]), 40), labels["look_again"].format(
            when=_fmt_when(item.get("until"), now, labels)) if _text(item.get("until")) else ""]
    elif kind == "inbox":
        parts = [_text(item.get("kind")), _text(item.get("gate"))]
    elif kind == "tasks":
        parts = [_text(item.get("priority")), _text(item.get("project")), _short(_text(item.get("blocked_by")), 40)]
    else:
        parts = [state, _text(item.get("project"))]
    detail = " · ".join(p for p in parts if p)

    url = _safe_link(item.get(entry.get("link", "url")), root)
    # The task a row belongs to: a dashboard jumps to its tab, or opens one.
    task = item.get("task") if isinstance(item.get("task"), str) else iid if kind in ("workplace", "tasks") else None

    stamp = _when(item.get("start") if kind == "calendar" else item.get("changed_at"))
    own = item.get("tone")
    if entry.get("alarm") is True:
        tone = "bad"
    elif own in ("bad", "warn", "dim", "none"):   # the source knows best what its row means
        tone = None if own == "none" else own
    elif item.get("state") == "blocked":
        tone = "bad"
    elif kind == "inbox" and item.get("urgency") == "now" or kind == "tasks" and item.get("blocked_by"):
        tone = "warn"
    elif kind == "command":
        tone = "warn"
    elif kind == "calendar" and stamp is not None and stamp < now:
        tone = "dim"
    elif kind == "activity" and stamp is not None and stamp.date() != now.date():
        tone = "dim"
    elif kind == "commits" and _today_count(item) == 0:
        tone = "dim"
    else:
        tone = None
    row = {"title": title, "when": when, "detail": detail, "tone": tone, "url": url, "task": task or None,
           "ask": tone in ("bad", "warn") or kind in ("tracker", "inbox"), "mark": mark_for(list(marks), title, item)}
    if kind == "tasks":
        row.update(priority=_text(item.get("priority")) or None, state=_text(item.get("state")) or None,
                   lines=_task_lines(item))
    elif kind == "calendar":
        # where and with whom, in full when the event is opened (a tag would cut a list of people)
        people = ", ".join(_text(p) for p in item.get("attendees") or [] if _text(p))
        lines = [{"kind": k, "text": v} for k, v in (("where", _text(item.get("location"))), ("people", people)) if v]
        if lines:
            row["lines"] = lines
    elif kind == "inbox" and _text(item.get("waiting_on")):
        row.update(lines=[{"kind": "blocked", "text": _text(item["waiting_on"])},
                                        {"kind": "look", "text": _text(item.get("until"))}])
    meter = meter_of(item.get("meter"))
    if meter:
        row["meter"] = meter
    if kind == "calendar" and stamp is not None:     # when it begins, for a countdown
        row["at"] = stamp.isoformat(timespec="minutes")
    if kind == "calendar":
        row["cal"] = calendar_facts(item, now)       # one field each, for the agenda view
    elif kind == "command":
        # the date of the first column as a date, so a dates page can count what is due or overdue
        due = _when(item.get(entry["when"]) if "when" in entry else item.get("due"))
        if due is not None:
            row["due_at"] = due.date().isoformat()
    # optional hints for a drawn section: which group a row belongs to, which symbol it wears
    for key, cap in (("group", 80), ("icon", 24)):
        if isinstance(item.get(key), str) and item[key].strip():
            row[key] = item[key].strip()[:cap]
    # a log row belongs to its context (task or repository): `view: groups` lists the rows under it
    if kind == "activity" and "group" not in row and _text(item.get("project")):
        row["group"] = _text(item.get("project"))[:80]
    if kind == "inbox" and iid:      # the item's id: a dashboard joins its triage and its close by it
        row["inbox"] = iid[:160]
    elif kind == "tracker" and not task and _text(item.get("inbox")):
        row["inbox"] = _text(item["inbox"])[:160]      # an agent was started on the row: its inbox item stands for it
    # whether a person can hand this row on (Do it, Advise, Later, Settle): a finding or a tracker row by
    # default, whatever the page entry says otherwise; a row with an inbox item or a task has its own path
    row["actionable"] = not (row.get("inbox") or row["task"]) and (
        entry["actionable"] if isinstance(entry.get("actionable"), bool) else tone in ("bad", "warn") or kind == "tracker")
    if iid:      # the source's own id: the cockpit keys the row by it, the inbox item it files too
        row["id"] = iid[:200]
    # a command row's own steps (docs/briefings.md, actions_argv); the row id says which row they act on
    steps = [{"id": a["id"], "label": a["label"].strip()[:40]} for a in item.get("actions") or []
             if isinstance(item.get("actions"), list) and isinstance(a, dict) and isinstance(a.get("id"), str)
             and ACTION_ID_RE.match(a["id"]) and isinstance(a.get("label"), str) and a["label"].strip()][:8]
    if kind in ("command", "calendar", "tracker") and steps and isinstance(item.get("id"), str):
        row["actions"], row["row_id"] = steps, item["id"][:200]
    if kind == "tracker" and isinstance(item.get("id"), str) and (
            re.match(r"^[\w.-]+/[\w.-]+#\d+\Z", item["id"]) or item.get("type") == "draft"):
        row["row_id"] = item["id"]           # a GitHub row: the dashboard asks for its detail by it (not a draft's)
        row["flags"] = github_flags(item, now)
        if _text(item.get("assignee")):
            row["who"] = _text(item["assignee"])[:60]     # the person filter
        row["gh"] = github_facts(item, now)
    # an event's calendar: a fact when it is opened, a filter on the dates page
    tags = tags_of({labels["tag_calendar"]: _text(item["calendar"])}) if kind == "calendar" and _text(item.get("calendar")) \
        else tags_of(item.get("tags"))
    if tags:
        row["tags"] = tags
    account = item.get("account")
    if isinstance(account, dict) and isinstance(account.get("id"), str) and ACCOUNT_ID_RE.match(account["id"]):
        row["account"] = {"id": account["id"]}
        if isinstance(account.get("status"), str) and 0 < len(account["status"]) <= 24:
            row["account"]["status"] = account["status"]
    return row


ACTION_ID_RE = re.compile(r"^[a-z][a-z0-9_-]{0,39}\Z")      # the same rule as briefing.py ACTION_RE
BOARD_STATES = ("new", "ready", "in_progress", "review", "blocked")
BOARD_MODES = ("off", "mine", "all")
QUIET_DAYS = 14
PR_AGE_RE = re.compile(r"(\d+) day")


def boards_of(summary: list) -> list:
    """The board summary as a dashboard draws it: name, slug, open cards per state, the switch."""
    out = []
    for b in summary[:40]:
        if not isinstance(b, dict) or not _text(b.get("name")):
            continue
        counts = b.get("counts") if isinstance(b.get("counts"), dict) else {}
        out.append({"name": _text(b["name"])[:80], "slug": _text(b.get("slug"))[:64] or None,
                    "number": b.get("number") if isinstance(b.get("number"), int) else None,
                    "org": _text(b.get("org"))[:80] or None,
                    "open": b.get("open") if isinstance(b.get("open"), int) else None,
                    "counts": {k: int(counts[k]) for k in BOARD_STATES if isinstance(counts.get(k), int)},
                    "capped": b.get("capped") if isinstance(b.get("capped"), int) else None,
                    **({"mode": b["mode"]} if b.get("mode") in BOARD_MODES else {})})
    return out


def github_flags(item: dict, now: dt.datetime) -> list:
    """What a GitHub row is, as the words a dashboard's figures filter by."""
    flags = []
    if item.get("assigned_to_me"):
        flags.append("mine")
    if item.get("category") == "qa" and item.get("type") == "pr":
        flags.append("ask_review")
    # your own pull request: the search says so in raw_state, or in note once a board card took the row over
    if item.get("type") == "pr" and (_text(item.get("note")) or _text(item.get("raw_state"))).startswith("your PR"):
        flags.append("my_pr")
    if item.get("state") in ("in_progress", "review", "blocked"):
        flags.append(item["state"])
    if item.get("untasked") is True:          # assigned to you, and no task or stream names it
        flags.append("untasked")
    changed = _when(item.get("changed_at"))
    if changed is not None and (now - changed).days >= QUIET_DAYS:      # _when gives local, naive times
        flags.append("quiet")
    return flags


GH_ID_RE = re.compile(r"^([\w.-]+/[\w.-]+)#(\d+)\Z")


CAL_DAY_START = 8          # the working day a free block is looked for in, and a dashboard's timeline spans
CAL_DAY_END = 20


def calendar_facts(item: dict, now: dt.datetime) -> dict:
    """An event's facts as a dashboard draws them, one field each: start and end (local, to the minute),
    its day, how long it takes, whether it fills the day, its calendar, whether it is information only
    (`info_calendars`), where it is and whether it is online (a meeting link), the people, and whether it is
    over or running now. `overlaps` (the titles it collides with) is added by the section."""
    start = _when(item.get("start"))
    end = _when(item.get("end")) or start
    all_day = bool(start and (len(_text(item.get("start"))) <= 10 or (end and (end - start) >= dt.timedelta(hours=23))))
    minutes = int((end - start).total_seconds() // 60) if start and end and end > start else 0
    people = [_text(x)[:80] for x in item.get("attendees") or [] if _text(x)][:20]
    return {"start": start.isoformat(timespec="minutes") if start else None,
            "end": end.isoformat(timespec="minutes") if end else None,
            "day": start.date().isoformat() if start else None, "minutes": minutes, "all_day": all_day,
            "calendar": _text(item.get("calendar"))[:60] or None, "info": item.get("info") is True,
            "where": _text(item.get("location"))[:160] or None, "online": bool(_text(item.get("url"))),
            "people": people, "past": bool(end and end <= now),
            "running": bool(start and end and start <= now < end and not all_day), "overlaps": []}


def _intervals(cals: list) -> list:
    """The busy time of the events that count (not information, not all day), as (start, end) pairs."""
    out = []
    for c in cals:
        if c.get("info") or c.get("all_day") or not c.get("start") or not c.get("end"):
            continue
        a, b = dt.datetime.fromisoformat(c["start"]), dt.datetime.fromisoformat(c["end"])
        if b > a:
            out.append((a, b))
    return sorted(out)


def _merged(spans: list) -> list:
    out: list = []
    for a, b in sorted(spans):
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def mark_overlaps(rows: list) -> None:
    """Each event that collides with another that counts names the other (up to three titles)."""
    timed = [(r, dt.datetime.fromisoformat(r["cal"]["start"]), dt.datetime.fromisoformat(r["cal"]["end"]))
             for r in rows if isinstance(r.get("cal"), dict) and r["cal"].get("start") and r["cal"].get("end")
             and not r["cal"].get("info") and not r["cal"].get("all_day")]
    for i, (r, a, b) in enumerate(timed):
        for j, (o, c, d) in enumerate(timed):
            if i != j and a < d and c < b and len(r["cal"]["overlaps"]) < 3:
                r["cal"]["overlaps"].append(o["title"][:80])


def calendar_figures(cals: list, now: dt.datetime) -> dict:
    """The figures above an agenda: today, tomorrow and the next seven days (events that count), today's busy
    minutes, how many events collide, the next event, and the longest free block left today between
    CAL_DAY_START and CAL_DAY_END. Information calendars are counted apart (`info_week`)."""
    today = now.date()
    mine = [c for c in cals if not c.get("info") and c.get("day")]

    def on(c, d):
        return c["day"] == d.isoformat()
    week = [c for c in mine if today <= dt.date.fromisoformat(c["day"]) < today + dt.timedelta(days=7)]
    busy_today = sum(int((b - a).total_seconds() // 60)
                     for a, b in _merged([x for x in _intervals([c for c in mine if on(c, today)])]))
    upcoming = sorted((c for c in mine if c.get("start") and not c.get("all_day")
                       and dt.datetime.fromisoformat(c["start"]) > now), key=lambda c: c["start"])
    first = upcoming[0] if upcoming else None
    day_end = dt.datetime.combine(today, dt.time(CAL_DAY_END))
    cursor = max(now.replace(second=0, microsecond=0), dt.datetime.combine(today, dt.time(CAL_DAY_START)))
    free, free_at = 0, None
    for a, b in _merged(_intervals([c for c in mine if on(c, today)])) + [(day_end, day_end)]:
        if b <= cursor:
            continue
        gap = int((min(a, day_end) - cursor).total_seconds() // 60)
        if gap > free:
            free, free_at = gap, cursor.isoformat(timespec="minutes")
        cursor = max(cursor, b)
        if cursor >= day_end:
            break
    return {"today": sum(1 for c in mine if on(c, today)), "busy_today": busy_today,
            "tomorrow": sum(1 for c in mine if on(c, today + dt.timedelta(days=1))), "week": len(week),
            "overlaps": sum(1 for c in mine if c.get("overlaps")),
            "next": {"start": first["start"], "title": first.get("title") or ""} if first else None,
            "free_today": {"minutes": free, "from": free_at} if free_at else None,
            "info_week": sum(1 for c in cals if c.get("info") and c.get("day")
                             and today <= dt.date.fromisoformat(c["day"]) < today + dt.timedelta(days=7)),
            "day_start": CAL_DAY_START, "day_end": CAL_DAY_END}


def github_facts(item: dict, now: dt.datetime) -> dict:
    """A GitHub row's facts as a dashboard draws them, one field each instead of a detail line: the plain
    title, repository and number, the normalized state and the board's own word for it, the board's priority
    (board.priority_field), labels, people, the pull requests that close it, the task that syncs it (or that none
    does), when it last changed and how long it has been quiet. Round 6c, for the page's filters and its rows: the
    board it stands on and the others that hold it too, who opened it (and whether you did), every assignee and
    label (the page shows a few and counts the rest), and a pull request's draft flag, review and checks."""
    m = GH_ID_RE.match(_text(item.get("id")))
    people = [p for p in (item.get("assignees") or [item.get("assignee")]) if isinstance(p, str) and p][:10]
    board = item.get("board") if isinstance(item.get("board"), dict) else {}
    pr = item.get("pr_status") if isinstance(item.get("pr_status"), dict) and item.get("type") == "pr" else None
    linked = item.get("linked_task") if isinstance(item.get("linked_task"), dict) else {}
    changed = _when(item.get("changed_at"))
    quiet = (now - changed).days if changed is not None else None
    status = re.sub(r"^[^0-9A-Za-zÄÖÜäöü]+", "", _text(item.get("raw_state"))).strip()   # without its emoji
    return {"title": _text(item.get("title"))[:300], "repo": m.group(1) if m else None,
            "number": int(m.group(2)) if m else None,
            "type": item["type"] if item.get("type") in ("pr", "draft") else "issue",
            "state": _text(item.get("state")) or None, "status": status[:40] or None,
            "priority": _text(item.get("priority"))[:20] or None,
            "labels": [_text(x)[:40] for x in item.get("labels") or [] if _text(x)][:10], "people": people,
            "author": _text(item.get("author"))[:60] or None, "by_me": item.get("by_me") is True,
            "board": _text(board.get("name"))[:80] or None,
            "also_on": [_text(x)[:80] for x in item.get("also_on") or [] if _text(x)][:3],
            "pr": {"draft": pr.get("draft") is True, "review": _text(pr.get("review"))[:24] or None,
                   "checks": _text(pr.get("checks"))[:24] or None} if pr else None,
            "prs": [{"n": int(str(p["id"]).rsplit("#", 1)[-1]), "draft": bool(p.get("draft"))}
                    for p in item.get("prs") or [] if isinstance(p, dict) and str(p.get("id", "")).rsplit("#", 1)[-1].isdigit()][:3],
            "task": _text(linked.get("slug")) or None,
            "stream": bool(linked.get("stream")) and str(linked.get("path") or "work/streams/").startswith("work/streams/"),
            "untasked": item.get("untasked") is True,
            "changed": changed.isoformat(timespec="minutes") if changed else None,
            "quiet": quiet if quiet is not None and quiet >= QUIET_DAYS else None,
            "note": _text(item.get("note")) or None}


def github_metrics(items: list, done: object, now: dt.datetime) -> list:
    """The figures above a github-work section: each {id, n} (and `days` for the oldest of your pull
    requests or the window of what you finished), in the order a dashboard shows them."""
    flags = [github_flags(i, now) for i in items]
    count = lambda flag: sum(1 for f in flags if flag in f)   # noqa: E731
    ages = [int(m.group(1)) for i in items if i.get("type") == "pr"
            for m in [PR_AGE_RE.search(_text(i.get("note")) or _text(i.get("raw_state")))] if m]
    out = [{"id": "open", "n": len(items)}, {"id": "mine", "n": count("mine")},
           {"id": "ask_review", "n": count("ask_review")},
           {"id": "my_pr", "n": count("my_pr"), **({"days": max(ages)} if ages else {})},
           {"id": "in_progress", "n": count("in_progress")}, {"id": "review", "n": count("review")},
           {"id": "blocked", "n": count("blocked")}, {"id": "quiet", "n": count("quiet"), "days": QUIET_DAYS}]
    if any("untasked" in i for i in items):    # left out when the tasks could not be read: no confident 0
        out.append({"id": "untasked", "n": count("untasked")})
    done = done if isinstance(done, dict) else {}
    for key in ("closed", "landed"):           # landed: your pull requests merged in the window
        if isinstance(done.get(key), int):
            out.append({"id": key, "n": done[key], "days": done.get("days") if isinstance(done.get("days"), int) else None})
    return out
ACCOUNT_ID_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{0,79}\Z")


def tags_of(value: object) -> dict | None:
    """A row's {label: value} for a dashboard's filter chips: up to 6 short strings, the rest dropped."""
    if not isinstance(value, dict):
        return None
    out = {}
    for k, v in value.items():
        if isinstance(k, str) and isinstance(v, str) and 0 < len(k.strip()) <= 24 and v.strip():
            out[k.strip()] = v.strip()[:60]
        if len(out) == 6:
            break
    return out or None


def _task_lines(item: dict) -> list:
    """What a dashboard shows when a task row is opened, each line with its kind (the dashboard
    labels it in its own language): origin, next, blocked, open steps, latest log rows."""
    lines = []
    if _text(item.get("origin")):
        lines.append({"kind": "origin", "text": _text(item["origin"])})
    nxt = item.get("next")
    if isinstance(nxt, dict):
        text = " · ".join(_text(nxt.get(k)) for k in ("what", "who", "due") if _text(nxt.get(k)))
    else:
        text = _text(nxt)
    if text:
        lines.append({"kind": "next", "text": text})
    if _text(item.get("blocked_by")):
        since = _text(item.get("blocked_since"))
        lines.append({"kind": "blocked", "text": _text(item["blocked_by"]) + (f" · {since}" if since else "")})
    if _text(item.get("quiet_until")):
        lines.append({"kind": "look", "text": _text(item["quiet_until"])})
    lines += [{"kind": "step", "text": _text(x)} for x in item.get("steps") or [] if _text(x)]
    lines += [{"kind": "log", "text": _text(x)} for x in item.get("log") or [] if _text(x)]
    return lines


def _page_section(section: dict, entry: dict, now: dt.datetime, labels: dict, root: Path | None = None,
                  marks: list = ()) -> dict:
    kind = section.get("kind") or ""
    # Every row: a page pages itself; `items` is only the briefing's first few.
    items = [i for i in section.get("all") or section.get("items") or [] if isinstance(i, dict)]
    if kind == "commits":   # whoever committed today first
        items = sorted(items, key=_today_count, reverse=True)
    rows = [_page_row(kind, i, entry, now, labels, root, marks) for i in items]
    for r, i in zip(rows, items):
        # where the row comes from (cockpit origin.py): an inbox item's `from`, a task's origin, the section
        r["origin_raw"] = _text(i.get("from") if kind == "inbox" else i.get("origin") if kind == "tasks" else None)[:300] or None
        r["origin_section_kind"] = kind or None
        # an inbox item's key: a cockpit filing names its section there, a ref lives there too
        r["inbox_key"] = (_text(i.get("key")) or None) if kind == "inbox" else None
        r["origin_provider"] = _text(i.get("tracker") or section.get("provider")) or None
        if kind == "tracker" and i.get("about_task"):
            r["about_task"], r["about_kind"] = _text(i["about_task"]), _text(i.get("about_kind")) or None
    if kind == "calendar":
        mark_overlaps(rows)
    weight = sum(_today_count(i) for i in items) if kind == "commits" else \
        sum(1 for r in rows if r["tone"] != "dim")
    if entry.get("badge") is False:   # listed, but not what the tab's number counts
        weight = 0
    return {"id": section["id"], "kind": kind, "title": section.get("title") or section["id"],
            "status": section.get("status") or "ok", "reason": _text(section.get("reason")),
            "alarm": entry.get("alarm") is True,
            "empty": entry.get("empty") or labels["page_empty"], "items": rows,
            "total": section.get("total", len(rows)), "weight": weight,
            "bad": sum(1 for r in rows if r["tone"] == "bad"),
            # From the section's cache (`cache_minutes`): the time its source last answered.
            "as_of": _page_when(section["cached_at"], now, labels) if section.get("cached_at") else None,
            # a source that could not answer: its last kept rows, and why they are old
            **({"stale": (labels["stale_refreshing"] if section["stale"].get("refreshing")
                          else labels["stale_until"].format(until=section["stale"]["until"]) if section["stale"].get("until")
                          else labels["stale"])} if isinstance(section.get("stale"), dict) else {}),
            # a board summary (github-board, github-work): one entry per board, its open cards per state and,
            # for github-work, the person's switch (off, mine, all)
            **({"boards": boards_of(section["summary"])} if kind == "tracker" and isinstance(section.get("summary"), list)
               else {}),
            **({"metrics": github_metrics(items, section.get("metrics"), now)}
               if section.get("provider") == "github-work" else {}),
            **({"cal_figures": calendar_figures([{**r["cal"], "title": r["title"]} for r in rows], now)}
               if kind == "calendar" else {}),
            **({"view": entry["view"]} if entry.get("view") in PAGE_VIEWS[1:] else {}),
            # a row's steps as buttons of their own (a machine's power switches), not behind one menu
            **({"steps": "buttons"} if entry.get("steps") == "buttons" else {}),
            # nothing to say when it is empty: a dashboard leaves the section out instead of "nothing"
            **({"hide_empty": True} if entry.get("hide_empty") is True else {}),
            # kept on its page for what reads it there (an account's services, the badge, the alarm), drawn
            # only while one of its rows is a finding
            **({"hide_ok": True} if entry.get("hide_ok") is True else {})}



def _jev_of(page: dict) -> dict | None:
    """`jev:` of a page as {skip_sections, private}, text only; None when the page asks for no order"""
    jev = page.get("jev")
    if not isinstance(jev, dict):
        return None
    return {k: [x for x in jev.get(k) or [] if isinstance(x, str)] if isinstance(jev.get(k), list) else []
            for k in ("skip_sections", "private")}

def _card_problems(cards, sections, where: str) -> list:
    """`cards:` of a page: a list of {id, after}, every id a known card, every `after` a section of the page."""
    if not isinstance(cards, list) or not all(isinstance(c, dict) for c in cards):
        return [f"{where}: cards must be a list of {{id, after}}"]
    ids = {e if isinstance(e, str) else e.get("id") for e in sections or [] if isinstance(e, (str, dict))}
    out = []
    for c in cards:
        if c.get("id") not in PAGE_CARDS:
            out.append(f"{where}: cards: unknown card {c.get('id')} (costs, usage or noise)")
        elif c.get("after") is not None and c["after"] not in ids:
            out.append(f"{where}: cards: {c['id']} stands after {c['after']}, which is not a section of this page")
    return out


def pages(result: dict, profile: dict, root: Path | None = None) -> list:
    """The dashboard's pages beside the briefing: which section on which page, every row
    in the same columns. `view.pages` decides; without it a section's kind does, and a
    section no page names lands on the rest page, so nothing collected goes unseen. A page
    may stand under another (`under:`, no tab of its own); the parent names its sub pages
    in `subs`, the cockpit's own pages a profile places there (PLACED_PAGES) among them."""
    view = _cfg(profile)
    labels = _labels(view, profile.get("_language"))
    marks = marks_of(view)
    now = _when(result.get("collected_at")) or dt.datetime.now()
    sections = {s.get("id"): s for s in result.get("sections") or [] if isinstance(s, dict) and s.get("id")}
    plan = []   # (id, title, [entry], group, overview, jev)
    cards = {}  # page id -> its `cards:`, passed through as written (the dashboard places them)
    unders = []  # (id, under) in the listed order: a page, or one of the cockpit's (PLACED_PAGES), under another
    configured = view.get("pages") if isinstance(view.get("pages"), list) else None
    if configured is not None:
        for page in configured:
            if not isinstance(page, dict) or not isinstance(page.get("id"), str):
                continue
            if isinstance(page.get("under"), str) and page["under"]:
                unders.append((page["id"], page["under"]))
            if page["id"] in PLACED_PAGES:
                continue
            entries = [{"id": e} if isinstance(e, str) else e for e in page.get("sections") or []
                       if isinstance(e, str) or (isinstance(e, dict) and isinstance(e.get("id"), str))]
            title = page.get("title") if isinstance(page.get("title"), str) else \
                labels.get(f"page_{page['id']}", page["id"])
            plan.append((page["id"], title, entries, page.get("group") if page.get("group") in PAGE_GROUPS else "main",
                         page.get("overview") is True, _jev_of(page)))
            if isinstance(page.get("cards"), list):
                cards[page["id"]] = page["cards"]
    else:
        for pid in DEFAULT_PAGES:
            plan.append((pid, labels[f"page_{pid}"],
                         [{"id": sid} for sid, s in sections.items() if PAGE_OF_KIND.get(s.get("kind")) == pid],
                         DEFAULT_PAGE_GROUP[pid], False, None))
    # collected for something else (a file another page reads), shown nowhere
    skip = view.get("page_skip") if isinstance(view.get("page_skip"), list) else []
    placed = {e["id"] for _, _, entries, _, _, _ in plan for e in entries} | {x for x in skip if isinstance(x, str)}
    if configured is None or view.get("page_rest", "show") != "hide":
        rest = [{"id": sid} for sid, s in sections.items()
                if sid not in placed and s.get("kind") not in BRIEFING_KINDS]
        plan.append((REST_PAGE, labels["page_more"], rest, "more", False, None))
    out = []
    for pid, title, entries, group, overview, jev in plan:
        built = [_page_section(sections[e["id"]], e, now, labels, root, marks) for e in entries if e["id"] in sections]
        if built:
            out.append({"id": pid, "title": title, "sections": built, "group": group, **({"overview": True} if overview else {}),
                        **({"jev": jev} if jev is not None else {}), **({"cards": cards[pid]} if pid in cards else {})})
    # a page under another has no tab: the parent names its sub pages in the listed order (`subs`), a sub page
    # without a section of its own is none, and neither side may be a page without a tab (group work or day)
    shown = {p["id"]: p for p in out if p["group"] not in ("work", "day")}
    below = {pid for pid, _ in unders}
    for pid, under in unders:
        if under in shown and under not in below and (pid in PLACED_PAGES or pid in shown) \
                and pid not in shown[under].get("subs", []):
            if pid in shown:
                shown[pid]["under"] = under
            shown[under].setdefault("subs", []).append(pid)
    return out
