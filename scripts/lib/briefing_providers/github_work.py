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
  boards        [slug, ...]  only these boards
  cards         mine (default) | all   board cards: only yours, or every open card
  filter        the boards' own filter (default `is:open`, see github-board)
  board_limit   cards per board, default 200
  links         false: do not ask which pull requests close an issue
"""
from __future__ import annotations

import re
from concurrent.futures import ThreadPoolExecutor

from . import github, github_board, load_json

SEARCH_KEYS = {"assignee", "owners", "repos", "kinds", "state", "labels", "review_requested", "authored",
               "others_prs", "limit"}
ISSUE_ID = re.compile(r"^([\w.-]+)/([\w.-]+)#(\d+)$")
LINK_LIMIT = 80


def _type(value) -> str:
    text = str(value or "issue").lower().replace("_", "")
    return "pr" if text in ("pr", "pullrequest") else "issue"


def collect(section: dict, ctx) -> list:
    query = dict(section.get("query") or {})
    search_q = {k: v for k, v in query.items() if k in SEARCH_KEYS}
    search_q.setdefault("review_requested", True)
    search_q.setdefault("authored", True)
    board_q = {"assigned_to_me": query.get("cards", "mine") != "all", "limit": query.get("board_limit", 200)}
    for key in ("boards", "filter"):
        if key in query:
            board_q[key] = query[key]
    ts = github_board._tracker_sync(ctx)
    has_boards = bool(ts.resolve_boards(ctx.root, ts.load_registries(ctx.root)))
    deadline = getattr(ctx, "deadline", None)

    def run(part: str):
        """The search and the boards side by side: one after another they took longer than a
        section may (about 20 s and 16 s live). The deadline lives per thread, so it is carried."""
        if deadline is not None:
            ctx.deadline = deadline
        if part == "search":
            return github.collect({"query": search_q}, ctx)
        board_section = {"query": board_q, "summary": section.get("summary")}
        rows = github_board.collect(board_section, ctx)
        if "_summary" in board_section:
            section["_summary"] = board_section["_summary"]
        return rows

    parts = ["search", "boards"] if has_boards else ["search"]
    with ThreadPoolExecutor(max_workers=len(parts)) as pool:
        found = dict(zip(parts, pool.map(run, parts)))
    rows = merge(found.get("search") or [], found.get("boards") or [])
    if query.get("links") is not False:
        _links(rows, ctx)
        rows = fold(rows)
    return rows


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
        for key in ("labels", "assignee", "changed_at", "url"):
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
