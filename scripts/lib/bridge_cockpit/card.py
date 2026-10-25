# SPDX-License-Identifier: MIT
"""One card for every item the cockpit shows (docs/bridge-cockpit-dev.md, "One card for every item").

A task, a stream, a closed task, an inbox item, a GitHub issue, pull request or draft, a calendar event, a check,
a command or info row and a tab that asks each reach the page with their own raw fields. `card_of(raw, ctx)` maps
any of them to the one shape card_fields.CARD_FIELDS names, so a page draws every item from the same parts:

- title: the item's own one line, the same in the list, the drawer and the files view (a task's H1);
- summary: the brief's user story as one sentence, else the task's headline or the item's detail (clipped to
  SUMMARY_MAX), else the triage gist; goal, story and acceptance come from the brief only (a STATUS.md `brief:`,
  an inbox item's latest `describe` event, else a proposal the describe hook holds);
- next {what, who, due, from, since}, state {word, blocked_by, since}, owner, priority, due, area, updated;
- source: the origin.classify_row result the row already carries (never classified again here);
- links: [{kind, href | path | key, label, closed?}], a task link `closed: true` when the task lives under
  work/done; progress {done, total} from the checklist of a STATUS.md;
- written: who wrote what the card says. `human` for a brief a person edited, `ai` for a brief a model wrote (or a
  proposal, or the triage gist as summary), `status` (a STATUS.md) or `item` (the item's own detail) for text
  the item carries, `title` when the card has nothing beyond its title;
- gaps: what the card misses, for the page to offer a fix: `no_goal` (a task, stream or inbox item without a
  goal), `no_next` (an open task or stream without a next step), `placeholder_next` (the template's "First step"
  still stands), `task_closed` (an item about a task that is closed), `no_content` (a detail that barely adds to
  the title).

Every field may be None and the keys are always exactly CARD_FIELDS. `probe_text` says an inbox item's
closes_when in words, the same words the page's logic.js probeText uses. `progress` and `placeholder_steps` read a
STATUS.md checklist (workplace.py and details.py both use them).

Pure: no I/O (the inbox facts come through `ctx.inbox`), nothing raises on bad input.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from .card_fields import CARD_FIELDS, NEXT_FIELDS, STATE_FIELDS, validate_brief

SUMMARY_MAX = 140
# a detail that adds fewer characters than this to its title says nothing the title does not
NO_CONTENT_CHARS = 60
# the checklist lines the STATUS.md template and task.py start a task with
PLACEHOLDER_STEPS = ("first step", "first action", "second action")
DOER_OWNER = {"ai": "bridge", "you": "me", "either": "bridge_then_me"}
#: what a card's `owner` can say; a task's next.who may be any person and reaches `owner` only as one of these
OWNERS = ("me", "bridge", "bridge_then_me")
GATE_OWNER = {"only-you": "me", "your-yes": "bridge_then_me", "free": "bridge"}
TASK_KINDS = ("task", "stream", "done_task", "done_stream")
FOLDER_KINDS = {"tasks": "task", "streams": "stream"}

EN = {"story": "As {as}, I want {want}, so that {so_that}.",
      "next": {"decide": "decide", "answer": "answer", "yes": "give your yes", "read": "read",
               "check": "check the result", "closes": "closes by itself when {probe}", "review": "review it",
               "task": "make it a task"},
      "probe": {"and": "and", "or": "or", "unknown": "a check the page cannot describe",
                "gh_pr": "pull request {ref} is {state}", "gh_issue": "issue {ref} is {state}",
                "task_status": "task {slug} reaches {status}", "path_exists": "{path} exists", "after": "after {when}",
                "unseen_for": "its reporter has not seen it for {hours} hours", "command": "the command {cmd} succeeds",
                "pr_states": {"merged": "merged", "green": "green"}, "issue_states": {"closed": "closed"}}}


@dataclass(frozen=True)
class Ctx:
    """What a card is built with besides the raw item; every part may be left out."""
    tx: Mapping | None = None                    # the `card` table of text.py; None: English
    triage: Mapping = field(default_factory=dict)      # key (task:<slug>, inbox:<id>) -> the triage item
    describe: Mapping = field(default_factory=dict)    # key -> a brief proposal ({brief: ...} or the brief)
    tasks: Mapping = field(default_factory=dict)       # slug -> the task as workplace.py tasks lists it
    work: Mapping = field(default_factory=dict)        # slug -> task | stream | done_task | done_stream
    inbox: Callable[[str], Any] | None = None          # inbox id -> details.inbox_facts, or None
    section_kind: str | None = None                    # the kind of the page section an info row stands in


# ---------------------------------------------------------------- small helpers

def _s(value: Any) -> str | None:
    """A text, stripped; None for anything else or an empty one"""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return None
    text = str(value).strip()
    return text or None


def _d(value: Any) -> dict:
    return value if isinstance(value, dict) else {}


def clip(text: Any, limit: int = SUMMARY_MAX) -> str | None:
    """`text` on one line, at most `limit` characters, cut at a word with an ellipsis"""
    text = _s(text)
    if text is None:
        return None
    text = " ".join(text.split())
    if len(text) <= limit:
        return text
    cut = text[:limit - 1].rsplit(" ", 1)[0].rstrip(",:;.")
    return (cut or text[:limit - 1]) + "…"


def _tx(ctx: Ctx) -> Mapping:
    tx = ctx.tx if isinstance(ctx.tx, Mapping) else EN
    return {**EN, **tx}


def _new(**fields: Any) -> dict:
    return {k: fields.get(k) for k in CARD_FIELDS}


def _next(what: Any = None, who: Any = None, due: Any = None, src: Any = None, since: Any = None) -> dict | None:
    what = _s(what)
    if what is None:
        return None
    return dict(zip(NEXT_FIELDS, (what, _s(who), _s(due), _s(src), _s(since))))


def _state(word: Any = None, blocked_by: Any = None, since: Any = None) -> dict | None:
    if _s(word) is None and _s(blocked_by) is None:
        return None
    return dict(zip(STATE_FIELDS, (_s(word), _s(blocked_by), _s(since))))


def _link(link: Any, label: Any) -> dict | None:
    """A row's link ({kind: web, href} or {kind: file, path}) with a label"""
    link = _d(link)
    if link.get("kind") == "web" and _s(link.get("href")):
        return {"kind": "web", "href": link["href"], "label": _s(label)}
    if link.get("kind") == "file" and _s(link.get("path")):
        return {"kind": "file", "path": link["path"], "label": _s(label)}
    return None


def _task_link(slug: str, ctx: Ctx, label: Any = None) -> dict:
    kind = ctx.work.get(slug)
    title = label or _s(_d(ctx.tasks.get(slug)).get("title")) or slug
    return {"kind": "task", "key": slug, "label": title, "closed": isinstance(kind, str) and kind.startswith("done")}


def _story_sentence(story: Any, ctx: Ctx) -> str | None:
    story = _d(story)
    if not all(_s(story.get(k)) for k in ("as", "want", "so_that")):
        return None
    try:
        return _tx(ctx)["story"].format(**{k: _s(story[k]) for k in ("as", "want", "so_that")})
    except (KeyError, IndexError, ValueError):
        return None


def _brief(stored: Any, key: str | None, ctx: Ctx) -> tuple[dict | None, str | None]:
    """(brief, written) from a stored brief through the gate, else a describe proposal; (None, None) without one"""
    clean = validate_brief(stored)[0] if isinstance(stored, dict) else None
    if clean:
        if clean.get("edited") is True:
            return clean, "human"
        return clean, "ai" if clean.get("by") else None
    proposal = ctx.describe.get(key) if key else None
    if isinstance(proposal, dict):
        clean = validate_brief(proposal.get("brief") if isinstance(proposal.get("brief"), dict) else proposal)[0]
        if clean:
            return clean, "ai"
    return None, None


def _triage(key: str | None, ctx: Ctx) -> dict:
    return _d(ctx.triage.get(key)) if key else {}


def _gaps(*named: tuple[str, bool]) -> list[str]:
    return [name for name, hit in named if hit]


def _placeholder(what: Any) -> bool:
    text = (_s(what) or "").casefold().rstrip(".")
    return text in PLACEHOLDER_STEPS


def _no_content(title: Any, detail: Any) -> bool:
    """A detail that adds fewer than NO_CONTENT_CHARS characters to the title (or none at all)"""
    detail = " ".join((_s(detail) or "").split())
    title = " ".join((_s(title) or "").split())
    rest = detail.replace(title, "", 1) if title else detail
    return len(rest.strip(" ,.:;")) < NO_CONTENT_CHARS


def _first_sentence(text: Any) -> str | None:
    text = " ".join((_s(text) or "").split())
    if not text:
        return None
    m = re.match(r"(.+?[.!?])(?:\s|$)", text)
    return clip(m.group(1) if m else text)


# ---------------------------------------------------------------- the checklist of a STATUS.md

CHECK_RE = re.compile(r"^\s*[-*] \[([ xX])\]\s*(.*)$")
FENCE_RE = re.compile(r"^\s*(```|~~~)")


def _checks(text: Any) -> list[tuple[str, str]]:
    """(mark, words) of each `- [ ]` / `- [x]` line of the body (nested ones too, none inside a code fence)"""
    if not isinstance(text, str):
        return []
    parts = re.split(r"^---\s*$", text, maxsplit=2, flags=re.MULTILINE)
    marks, fence = [], None
    for line in (parts[2] if len(parts) == 3 else text).splitlines():
        opener = FENCE_RE.match(line)
        if opener:
            fence = None if fence == opener.group(1) else (fence or opener.group(1))
            continue
        mark = None if fence else CHECK_RE.match(line)
        if mark:
            marks.append((mark.group(1), mark.group(2).strip()))
    return marks


def progress(text: Any) -> dict | None:
    """{done, total} from the `- [x]` and `- [ ]` lines of the body (nested ones too, none inside a ``` or ~~~
    code fence, where they are examples); None without any."""
    marks = _checks(text)
    return {"done": sum(m != " " for m, _ in marks), "total": len(marks)} if marks else None


def placeholder_steps(text: Any) -> bool:
    """Whether an open checklist line still reads as the template's ("First step", "First action", ...)"""
    return any(m == " " and _placeholder(words) for m, words in _checks(text))


# ---------------------------------------------------------------- closes_when in words

def _js(value: Any) -> str:
    """A value as JavaScript's String() writes it, so a probe reads here as logic.js reads it"""
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return ",".join("" if x is None else _js(x) for x in value)
    return str(value)


def _or(value: Any, default: str) -> str:
    """`String(value ?? default)`: only a missing value takes the default, an empty one stays empty"""
    return default if value is None else _js(value)


def _probe_date(value: Any) -> str:
    text = _or(value, "")
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})(?:[T ](\d{2}:\d{2}))?", text)
    return f"{m.group(3)}.{m.group(2)}.{m.group(1)}{' ' + m.group(4) if m.group(4) else ''}" if m else text


def probe_text(spec: Any, tx: Mapping | None = None, _depth: int = 0) -> str | None:
    """How an inbox item closes on its own (its closes_when probe) in words; None without a probe. The same
    reading as logic.js probeText with text.js `probe` (test_bridge_cockpit_card runs both on the same probes):
    `all` and `any` join their parts, an unknown probe says so, only a missing state takes the default, and
    the German table names a pull request's merged and green and an issue's closed."""
    if not isinstance(spec, dict) or _depth > 4:
        return None
    p = {**EN["probe"], **_d((tx if isinstance(tx, Mapping) else EN).get("probe"))}
    pr_states, issue_states = _d(p.get("pr_states")), _d(p.get("issue_states"))
    for combine in ("all", "any"):
        if isinstance(spec.get(combine), list):
            joint = f" {p['and']} " if combine == "all" else f" {p['or']} "
            return joint.join(probe_text(x, tx, _depth + 1) or p["unknown"] for x in spec[combine])
    try:
        if "gh_pr" in spec:
            state = _or(spec.get("state"), "merged")
            return p["gh_pr"].format(ref=_js(spec["gh_pr"]), state=pr_states.get(state, state))
        if "gh_issue" in spec:
            state = _or(spec.get("state"), "closed")
            return p["gh_issue"].format(ref=_js(spec["gh_issue"]), state=issue_states.get(state, state))
        if "task_status" in spec:
            return p["task_status"].format(slug=_js(spec["task_status"]), status=_or(spec.get("status"), "done"))
        if "path_exists" in spec:
            return p["path_exists"].format(path=_js(spec["path_exists"]))
        if "after" in spec:
            return p["after"].format(when=_probe_date(spec["after"]))
        if "unseen_for" in spec:
            unseen = spec["unseen_for"]
            return p["unseen_for"].format(hours=_or(unseen.get("hours") if isinstance(unseen, dict) else None, "?"))
        if "command" in spec:
            cmd = spec["command"]
            return p["command"].format(cmd=" ".join("" if x is None else _js(x) for x in cmd)
                                       if isinstance(cmd, list) else _js(cmd))
    except (KeyError, IndexError, ValueError):
        pass
    return p["unknown"]


# ---------------------------------------------------------------- adapters, one per kind

def task_card(slug: str, title: Any, ctx: Ctx, *, kind: str | None = None, row: Mapping | None = None,
              facts: Mapping | None = None, origin: Any = None, link: Any = None, no_content: bool = False) -> dict:
    """A task, a stream or a closed one: `facts` is the task as workplace.py tasks lists it (else ctx.tasks),
    `row` the model row it stands in (its derived next and state win over the list)."""
    row = row or {}
    t = dict(facts) if isinstance(facts, Mapping) else _d(ctx.tasks.get(slug))
    kind = kind if kind in TASK_KINDS else ctx.work.get(slug) if ctx.work.get(slug) in TASK_KINDS \
        else FOLDER_KINDS.get(t.get("kind"), "task")
    closed = kind.startswith("done")
    key = f"task:{slug}"
    brief, written = _brief(t.get("brief"), key, ctx)
    tri = _triage(key, ctx)
    summary, from_text = None, None
    if brief and _story_sentence(brief.get("story"), ctx):
        summary, from_text = _story_sentence(brief.get("story"), ctx), "brief"
    elif clip(t.get("headline")):
        summary, from_text = clip(t.get("headline")), "status"
    elif clip(tri.get("gist")):
        summary, from_text = clip(tri.get("gist")), "ai"
    if written is None:
        written = "status" if brief or from_text in ("status", "brief") else from_text or "title"
    nxt_row = _d(row.get("next"))
    if _s(nxt_row.get("what")):
        status_next = nxt_row.get("from") == "status"
        nxt = _next(nxt_row["what"], t.get("next_who") if status_next else None,
                    t.get("next_due") if status_next else None, nxt_row.get("from"), nxt_row.get("since"))
    else:
        nxt = _next(t.get("next"), t.get("next_who"), t.get("next_due"), "status", t.get("updated"))
    word = "done" if closed else _s(row.get("status")) or _s(t.get("status"))
    # the owner words only (me, bridge, bridge_then_me): a person named as next.who stays in next.who
    who = _s(t.get("next_who"))
    owner = who if who in OWNERS else DOER_OWNER.get(tri.get("doer"))
    links = [{**_task_link(slug, ctx, _s(title)), "closed": closed}]
    extra = _link(link, title)
    if extra:
        links.append(extra)
    gaps = [] if closed else _gaps(
        ("no_goal", not (brief or {}).get("goal")),
        ("no_next", nxt is None),
        ("placeholder_next", (nxt is not None and _placeholder(nxt["what"])) or t.get("placeholder") is True),
        ("no_content", no_content and not summary))
    return _new(kind=kind, title=_s(title) or _s(t.get("title")) or slug, summary=summary,
                goal=(brief or {}).get("goal"), story=(brief or {}).get("story"),
                acceptance=(brief or {}).get("acceptance"), next=nxt,
                state=_state(word, t.get("blocked_by")), owner=owner,
                priority=_s(row.get("priority")) or _s(t.get("priority")),
                due=_s(row.get("due")) or _s(t.get("next_due")), area=_s(row.get("area")) or _s(t.get("area")),
                updated=_s(t.get("updated")), source=origin, links=links,
                progress=t.get("progress") if isinstance(t.get("progress"), dict) else None,
                written=written, gaps=gaps)


def _inbox_next(kind: Any, gate: Any, facts: Mapping, ctx: Ctx) -> dict | None:
    words = _d(_tx(ctx).get("next")) or EN["next"]
    owner = GATE_OWNER.get(gate)
    who = "me" if owner in ("me", "bridge_then_me") else owner
    closes = probe_text(facts.get("closes_when"), _tx(ctx))
    if gate == "free" and closes:
        return _next(words["closes"].format(probe=closes), who, facts.get("due"), "probe",
                     facts.get("state_at") or facts.get("created"))
    if kind == "decision":
        what = words["decide"]
    elif kind == "question":
        what = words["answer"]
    elif gate == "your-yes":
        what = words["yes"]
    elif kind in ("result", "draft"):
        what = words["check"]
    else:
        what = words["read"]
    return _next(what, who, facts.get("due"), "item", facts.get("state_at") or facts.get("created"))


def inbox_card(item_id: str, title: Any, ctx: Ctx, *, facts: Mapping | None = None, row: Mapping | None = None,
               origin: Any = None, state: Any = None) -> dict:
    """An inbox item: `facts` as details.inbox_facts reads them (else ctx.inbox), `row` the model row"""
    row = row or {}
    # a copy: ctx.inbox hands out the dict details.inbox_facts keeps for every thread, which the lines below
    # complete from the row
    f = dict(facts) if isinstance(facts, Mapping) else dict(_d(ctx.inbox(item_id) if callable(ctx.inbox) else None))
    key = f"inbox:{item_id}"
    kind = _s(f.get("kind")) or _s(row.get("inbox_kind"))
    gate = _s(f.get("gate")) or _s(row.get("gate"))
    # without the item's facts (not readable) nothing says its detail is empty
    empty = _no_content(title, f.get("detail")) if f else False
    f["due"] = f.get("due") or row.get("due")
    f["created"] = f.get("created") or row.get("created")
    brief, written = _brief(f.get("brief"), key, ctx)
    tri = _triage(key, ctx)
    summary, from_text = None, None
    if brief and _story_sentence(brief.get("story"), ctx):
        summary, from_text = _story_sentence(brief.get("story"), ctx), "brief"
    elif not empty and _first_sentence(f.get("detail")):
        summary, from_text = _first_sentence(f.get("detail")), "item"
    elif clip(tri.get("gist")):
        summary, from_text = clip(tri.get("gist")), "ai"
    if written is None:
        written = "item" if brief or from_text in ("item", "brief") else from_text or "title"
    slug = _s(f.get("task")) or _s(row.get("task"))
    links = [{"kind": "inbox", "key": item_id, "label": _s(title)}]
    if slug:
        links.append(_task_link(slug, ctx))
    extra = _link(row.get("link"), title)
    if extra:
        links.append(extra)
    closed_task = any(x.get("closed") for x in links if x["kind"] == "task")
    return _new(kind="inbox", subkind=kind, title=_s(title), summary=summary, goal=(brief or {}).get("goal"),
                story=(brief or {}).get("story"), acceptance=(brief or {}).get("acceptance"),
                next=_inbox_next(kind, gate, f, ctx),
                state=_state(_s(state) or _s(row.get("inbox_state")) or "open", None,
                             f.get("state_at") or f.get("created")),
                owner=GATE_OWNER.get(gate), priority=_s(row.get("priority")), due=_s(f.get("due")),
                area=_s(row.get("area")) or _s(f.get("area")), updated=_s(f.get("updated")) or _s(f.get("created")),
                source=origin, links=links, written=written,
                gaps=_gaps(("no_goal", not (brief or {}).get("goal")), ("task_closed", closed_task),
                           ("no_content", empty and not brief)))


def github_card(it: Mapping, ctx: Ctx) -> dict:
    gh = _d(it.get("gh"))
    words = _d(_tx(ctx).get("next")) or EN["next"]
    flags = it.get("flags") if isinstance(it.get("flags"), list) else []
    ref = f"{gh['repo']}#{gh['number']}" if _s(gh.get("repo")) and isinstance(gh.get("number"), int) else None
    summary = clip(gh.get("note")) or clip(", ".join(x for x in gh.get("labels") or [] if isinstance(x, str)))
    tri = _triage(it.get("key"), ctx)
    written = "item" if summary else None
    if summary is None and clip(tri.get("gist")):
        summary, written = clip(tri.get("gist")), "ai"
    nxt = None
    if "ask_review" in flags:
        nxt = _next(words["review"], "me", None, "item", gh.get("changed"))
    elif "untasked" in flags:
        nxt = _next(words["task"], "me", None, "item", gh.get("changed"))
    people = [p for p in gh.get("people") or [] if isinstance(p, str)]
    links = []
    web = _link(it.get("link"), ref or it.get("title"))
    if web:
        links.append(web)
    if _s(gh.get("task")):
        links.append(_task_link(gh["task"], ctx))
    return _new(kind="github", subkind=gh.get("type") if gh.get("type") in ("issue", "pr", "draft") else "issue",
                title=_s(gh.get("title")) or _s(it.get("title")), summary=summary, next=nxt,
                state=_state(_s(gh.get("status")) or _s(gh.get("state")), None,
                             gh.get("changed") if gh.get("quiet") else None),
                owner=_s(it.get("who")) or (people[0] if people else None),
                priority=_s(gh.get("priority")) or _s(it.get("priority")), due=_s(it.get("due_at")),
                updated=_s(gh.get("changed")), source=it.get("origin"), links=links, written=written or "title",
                gaps=_gaps(("task_closed", any(x.get("closed") for x in links if x["kind"] == "task"))))


def event_card(it: Mapping, ctx: Ctx) -> dict:
    cal = _d(it.get("cal"))
    people = [p for p in cal.get("people") or [] if isinstance(p, str)]
    parts = [x for x in (_s(cal.get("where")), ", ".join(people[:6]) or None) if x]
    word = "running" if cal.get("running") else "past" if cal.get("past") else "upcoming"
    link = _link(it.get("link"), it.get("title"))
    return _new(kind="event", title=_s(it.get("title")), summary=clip(" · ".join(parts)),
                state=_state(word), due=_s(cal.get("start")) or _s(it.get("due_at")), source=it.get("origin"),
                links=[link] if link else [], written="item" if parts else "title", gaps=[])


def info_card(it: Mapping, ctx: Ctx) -> dict:
    """A check (a command row with a tone or a meter), or any other command or info row"""
    tone = it.get("tone")
    section = _s(ctx.section_kind)
    is_check = section == "command" and (tone in ("bad", "warn") or bool(it.get("meter")))
    summary = clip(it.get("detail"))
    tri = _triage(it.get("key"), ctx)
    written = "item" if summary else None
    if summary is None and clip(tri.get("gist")):
        summary, written = clip(tri.get("gist")), "ai"
    link = _link(it.get("link"), it.get("title"))
    word = ({"bad": "bad", "warn": "warn"}.get(tone, "ok") if is_check else _s(it.get("state")))
    return _new(kind="check" if is_check else "info", subkind=None if is_check else section,
                title=_s(it.get("title")), summary=summary, state=_state(word), owner=_s(it.get("who")),
                priority=_s(it.get("priority")), due=_s(it.get("due_at")), updated=_s(it.get("at")),
                source=it.get("origin"), links=[link] if link else [], written=written or "title", gaps=[])


def ask_card(tab: Mapping, ctx: Ctx) -> dict:
    """A tab that asks: its name, the question, the options as the next step, always for the person"""
    ask = _d(tab.get("ask"))
    options = [_s(o.get("label")) for o in ask.get("options") or [] if isinstance(o, dict) and _s(o.get("label"))]
    slug = _s(tab.get("slug"))
    return _new(kind="ask", title=_s(tab.get("name")) or _s(tab.get("ref")), summary=clip(ask.get("text")),
                next=_next(" / ".join(options), "me", None, "tab", None) if options else None,
                state=_state(tab.get("state")), owner="me", area=_s(tab.get("workspace")),
                links=[_task_link(slug, ctx)] if slug else [], written="item" if _s(ask.get("text")) else "title",
                gaps=[])


# ---------------------------------------------------------------- the one entry point

def _row_card(r: Mapping, ctx: Ctx) -> dict:
    if _s(r.get("inbox_id")):
        return inbox_card(r["inbox_id"], r.get("title"), ctx, row=r, origin=r.get("origin"))
    slug = _s(r.get("task"))
    if slug:
        return task_card(slug, r.get("title"), ctx, kind=r.get("work_kind"), row=r, origin=r.get("origin"),
                         link=r.get("link") if _d(r.get("link")).get("kind") == "web" else None)
    # a tracker row without a task: its own title and link
    link = _link(r.get("link"), r.get("title"))
    return _new(kind="info", subkind="tracker" if _s(r.get("ref")) else None, title=_s(r.get("title")),
                state=_state(r.get("status")), priority=_s(r.get("priority")), due=_s(r.get("due")),
                area=_s(r.get("area")), source=r.get("origin"), links=[link] if link else [], written="title", gaps=[])


def _info_item_card(it: Mapping, ctx: Ctx) -> dict:
    if isinstance(it.get("gh"), dict):
        return github_card(it, ctx)
    if isinstance(it.get("cal"), dict):
        return event_card(it, ctx)
    if _s(it.get("inbox")) and not _s(it.get("task")):
        return inbox_card(it["inbox"], it.get("title"), ctx, row={"link": it.get("link"), "due": it.get("due_at"),
                                                                  "priority": it.get("priority")},
                          origin=it.get("origin"))
    if _s(it.get("task")):
        return task_card(it["task"], it.get("title"), ctx, kind=it.get("work_kind"), origin=it.get("origin"),
                         row={"priority": it.get("priority"), "due": it.get("due_at")})
    return info_card(it, ctx)


def _task_detail_card(d: Mapping, ctx: Ctx) -> dict:
    slug = d["slug"]
    front = _d(d.get("front"))
    facts = {**_d(ctx.tasks.get(slug)), **{k: v for k, v in _d(d.get("facts")).items() if v is not None}}
    sections = d.get("sections") if isinstance(d.get("sections"), list) else []
    body = sum(len(_s(s.get("text")) or "") for s in sections if isinstance(s, dict))
    return task_card(slug, facts.get("title") or slug, ctx, kind=d.get("work_kind"), facts=facts,
                     origin=d.get("origin"), row={"status": front.get("status"), "priority": front.get("priority")},
                     no_content=body < NO_CONTENT_CHARS and not _s(front.get("headline")))


def _inbox_detail_card(d: Mapping, ctx: Ctx) -> dict:
    item = _d(d.get("item"))
    facts = _d(d.get("facts")) or {**item}
    return inbox_card(d["id"], item.get("summary"), ctx, facts=facts, origin=d.get("origin"), state=item.get("state"),
                      row={"task": item.get("task")})


def card_of(raw: Any, ctx: Ctx | None = None) -> dict:
    """The card of any item: a model row (collector.row_out), a page item (collector.info_out), a task or inbox
    detail (details.task_detail, details.inbox_detail) or a tab with a question. Never raises: whatever it cannot
    read gives a card of None fields."""
    ctx = ctx if isinstance(ctx, Ctx) else Ctx()
    if not isinstance(raw, dict):
        return _new()
    try:
        if isinstance(raw.get("front"), dict) and _s(raw.get("slug")):
            return _task_detail_card(raw, ctx)
        if isinstance(raw.get("item"), dict) and _s(raw.get("id")):
            return _inbox_detail_card(raw, ctx)
        if isinstance(raw.get("ask"), dict) and _s(raw.get("ref")):
            return ask_card(raw, ctx)
        if "bucket" in raw and _s(raw.get("key")):
            return _row_card(raw, ctx)
        if "bucket" in raw:
            return _new(title=_s(raw.get("title")))
        return _info_item_card(raw, ctx)
    except (AttributeError, KeyError, TypeError, ValueError):     # input is data: a broken one is no card
        return _new(title=_s(raw.get("title")))
