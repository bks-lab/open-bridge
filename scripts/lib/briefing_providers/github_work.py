# SPDX-License-Identifier: MIT
"""One row per piece of GitHub work: your issues and pull requests (the `github` provider) and the
cards of the registered boards (the `github-board` provider), merged by their id.

Two sections showed the same card twice and disagreed (an issue `open` in one, `In Progress` in the
other, live 2026-10-17). Here the board's status wins, the search adds what only it knows (asked to
review, your own pull request), and each row names the board it sits on and the pull requests that
close it. briefing.py adds the Bridge task that syncs the issue and the inbox item an agent was
started on (`link`), and the steps a person can start on the row (`tracker_steps`).

query keys (all optional):
  everything the github provider takes: assignee, owners, repos, kinds, labels,
                review_requested, authored, others_prs, limit
  boards        [slug, ...]  only these boards (the others start switched off)
  cards         mine (default) | all   board cards: only yours, or every open card
                A person switches each board on a dashboard (off, mine, all); that choice is kept
                in .bridge/github-boards.json, beside the profile, never in it, and wins over both.
  filter        the boards' own filter (default `is:open`, see github-board)
  board_limit   cards per board, default 200
  links         false: do not ask which pull requests close an issue
  done_days     N (default 7): also count your issues closed and your pull requests merged in the
                last N days, two searches (GitHub's search budget, not its GraphQL points); 0 asks none
"""
from __future__ import annotations

import datetime as dt
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import github, github_board, load_json

SEARCH_KEYS = {"assignee", "owners", "repos", "kinds", "state", "labels", "review_requested", "authored",
               "others_prs", "limit"}
ISSUE_ID = re.compile(r"^([\w.-]+)/([\w.-]+)#(\d+)$")
LINK_LIMIT = 80
BOARDS_FILE = Path(".bridge") / "github-boards.json"
MODES = ("off", "mine", "all")
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}\Z")


def board_modes(root: Path) -> dict:
    """The person's own choice per board ({slug: off | mine | all}); nothing chosen is an empty choice."""
    try:
        data = json.loads((Path(root) / BOARDS_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    boards = data.get("boards") if isinstance(data, dict) else None
    return {k: v for k, v in (boards or {}).items() if isinstance(k, str) and SLUG_RE.match(k) and v in MODES}


def save_board_mode(root: Path, slug: str, mode: str) -> dict:
    """Keep one board's choice; the file is written whole and swapped in, so a reader never sees half."""
    if not SLUG_RE.match(slug or "") or mode not in MODES:
        raise ValueError("a board slug and one of off, mine, all")
    modes = {**board_modes(root), slug: mode}
    path = Path(root) / BOARDS_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(f".{os.getpid()}.tmp")
    tmp.write_text(json.dumps({"boards": modes}, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    tmp.replace(path)
    return modes


def _type(value) -> str:
    text = str(value or "issue").lower().replace("_", "")
    return "pr" if text in ("pr", "pullrequest") else "issue"


def collect(section: dict, ctx) -> list:
    query = dict(section.get("query") or {})
    search_q = {k: v for k, v in query.items() if k in SEARCH_KEYS}
    search_q.setdefault("review_requested", True)
    search_q.setdefault("authored", True)
    ts = github_board._tracker_sync(ctx)
    boards = ts.resolve_boards(ctx.root, ts.load_registries(ctx.root))
    default = "all" if query.get("cards") == "all" else "mine"
    named = set(query.get("boards") or [])
    saved = board_modes(ctx.root)
    mode_of = {b["slug"]: saved.get(b["slug"]) or (default if not named or b["slug"] in named else "off")
               for b in boards}
    asked = [b["slug"] for b in boards if mode_of[b["slug"]] != "off"]
    # every open card of the boards switched on, in one listing: a board's cost does not depend on whose cards
    # are kept, and two listings side by side would ask eight boards at once (GitHub's burst limit)
    board_q = {"assigned_to_me": False, "limit": query.get("board_limit", 200), "boards": asked}
    if "filter" in query:
        board_q["filter"] = query["filter"]
    has_boards = bool(asked)
    deadline = getattr(ctx, "deadline", None)

    def run(part: str):
        """The search and the boards side by side: one after another they took longer than a
        section may (about 20 s and 16 s live). The deadline lives per thread, so it is carried."""
        if deadline is not None:
            ctx.deadline = deadline
        if part == "search":
            search = {"query": search_q}
            rows = github.collect(search, ctx)
            section["_metrics"] = _done(query, ctx)
            return rows, search.get("_me")
        board_section = {"query": board_q, "summary": True}
        rows = github_board.collect(board_section, ctx)
        return rows, board_section.get("_summary") or []

    parts = ["search", "boards"] if has_boards else ["search"]
    with ThreadPoolExecutor(max_workers=len(parts)) as pool:
        found = dict(zip(parts, pool.map(run, parts)))
    searched, me = found["search"]
    carded, counted = found.get("boards") or ([], [])
    # a card knows it is yours only from integrations.github.assignee_me; the login the search asked for
    # covers the rest, so an assigned card the search did not reach (another owner, past its limit) stays
    for card in carded:
        if me and me in (card.get("assignees") or []):
            card["assigned_to_me"] = True
    me_only = {b["slug"] for b in boards if mode_of[b["slug"]] == "mine"}
    carded = [c for c in carded if c["board"]["slug"] not in me_only or c.get("assigned_to_me")]
    # one entry per registered board, in the registry's order, each with its mode: a dashboard draws them as
    # the switches, a board switched off included (without counts: it was not asked)
    by_slug = {b.get("slug"): b for b in counted}
    section["_summary"] = [{**(by_slug.get(b["slug"]) or {"name": b["name"], "number": b["number"], "org": b["org"],
                                                         "slug": b["slug"], "counts": {}, "open": None, "capped": None}),
                            "mode": mode_of[b["slug"]]} for b in boards]
    rows = merge(searched or [], carded)
    if query.get("links") is not False:
        _links(rows, ctx)
        rows = fold(rows)
    return rows


def _done(query: dict, ctx) -> dict:
    """What you finished lately, as two numbers: issues assigned to you closed, pull requests you wrote merged,
    each in the last `done_days` days within the query's owners and repos. A search that fails leaves its number
    out; the rows never wait on it."""
    days = query.get("done_days", 7)
    if not isinstance(days, int) or isinstance(days, bool) or days <= 0:
        return {}
    since = (ctx.now.date() - dt.timedelta(days=days)).isoformat()
    scope = [*[a for o in query.get("owners") or [] for a in ("--owner", str(o))],
             *[a for r in query.get("repos") or [] for a in ("--repo", str(r))]]
    out = {"days": days}
    for name, argv in (("closed", ["gh", "search", "issues", "--assignee", "@me", "--closed", f">={since}"]),
                       ("landed", ["gh", "search", "prs", "--author", "@me", "--merged", f">={since}"])):
        try:
            found = load_json(ctx.run([*argv, *scope, "--limit", "100", "--json", "number"], timeout=ctx.timeout), name)
            out[name] = len(found) if isinstance(found, list) else None
        except Exception:  # noqa: BLE001 - a number is a nicety
            continue
    return out


def merge(searched: list, carded: list) -> list:
    """One row per id: the board's card first (its status is where the work stands), the search's
    knowledge on top. A card on two boards (a theme board and a person's board) keeps the first
    board of the registry and names the others."""
    out: dict = {}
    for card in carded:
        rid = card["id"]
        if rid in out:
            out[rid].setdefault("also_on", []).append(card["board"]["name"])
            continue
        out[rid] = {**card, "type": _type(card.get("type")), "tracker": "github-work",
                    "group": card["board"]["name"]}
    for hit in searched:
        rid = hit["id"]
        row = out.get(rid)
        if row is None:
            out[rid] = {**hit, "type": _type(hit.get("type")), "tracker": "github-work",
                        "group": hit.get("project") or rid.split("#")[0]}
            continue
        row["assigned_to_me"] = bool(row.get("assigned_to_me") or hit.get("assigned_to_me"))
        for key in ("labels", "assignee", "assignees", "changed_at", "url"):
            if not row.get(key) and hit.get(key):
                row[key] = hit[key]
        if hit.get("category") == "qa":            # asked to review it: the reading that needs you
            row["category"] = "qa"
            row["state"] = "review"
            row.pop("_category_from_state", None)
        if str(hit.get("raw_state") or "").startswith(("your PR", "by ")):
            row["note"] = hit["raw_state"]
    return list(out.values())


def fold(rows: list) -> list:
    """A pull request that closes an issue in the list stands in that issue's row, not in one of its
    own: one row per piece of work. A pull request someone asked you to review keeps its row."""
    ids = {r["id"] for r in rows}
    kept = []
    for row in rows:
        closes = [c for c in row.get("closes") or [] if c in ids]
        if row.get("type") == "pr" and closes and row.get("category") != "qa":
            continue
        kept.append(row)
    return kept


def _links(rows: list, ctx) -> None:
    """Which open pull requests close each issue, and which issues each pull request closes: one
    GraphQL call for all rows, split in halves when one row cannot be answered (as the board dates)."""
    wanted = [(i, ISSUE_ID.match(str(r.get("id")))) for i, r in enumerate(rows[:LINK_LIMIT])]
    wanted = [(i, m) for i, m in wanted if m]
    _ask_halving(wanted, rows, ctx)


def _ask_halving(wanted: list, rows: list, ctx) -> None:
    if not wanted or _ask(wanted, rows, ctx) or len(wanted) == 1:
        return
    half = len(wanted) // 2
    _ask_halving(wanted[:half], rows, ctx)
    _ask_halving(wanted[half:], rows, ctx)


def _ask(wanted: list, rows: list, ctx) -> bool:
    parts = [f'i{i}: repository(owner: "{m[1]}", name: "{m[2]}") {{ issueOrPullRequest(number: {m[3]}) {{ '
             f'... on Issue {{ closedByPullRequestsReferences(first: 3, includeClosedPrs: false) '
             f'{{ nodes {{ number url isDraft repository {{ nameWithOwner }} }} }} }} '
             f'... on PullRequest {{ closingIssuesReferences(first: 3) '
             f'{{ nodes {{ number repository {{ nameWithOwner }} }} }} }} }} }}' for i, m in wanted]
    try:
        data = load_json(ctx.run(["gh", "api", "graphql", "-f", "query={ " + " ".join(parts) + " }"],
                                 timeout=ctx.timeout), "linked pull requests").get("data") or {}
    except Exception:  # noqa: BLE001 - a link is a nicety, never a reason to lose the rows
        return False
    for i, _ in wanted:
        node = (data.get(f"i{i}") or {}).get("issueOrPullRequest") or {}
        prs = ((node.get("closedByPullRequestsReferences") or {}).get("nodes")) or []
        issues = ((node.get("closingIssuesReferences") or {}).get("nodes")) or []
        if prs:
            rows[i]["prs"] = [{"id": f"{(p.get('repository') or {}).get('nameWithOwner')}#{p.get('number')}",
                               "url": p.get("url"), "draft": bool(p.get("isDraft"))}
                              for p in prs if isinstance(p, dict) and p.get("number")]
        if issues:
            rows[i]["closes"] = [f"{(x.get('repository') or {}).get('nameWithOwner')}#{x.get('number')}"
                                 for x in issues if isinstance(x, dict) and x.get("number")]
    return True
