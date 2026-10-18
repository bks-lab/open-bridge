# SPDX-License-Identifier: MIT
"""GitHub Projects (V2) boards, through the same code as scripts/tracker-sync.py.

Boards come from `github_projects:` in the ecosystem files, state maps from
workflow/projects/<slug>.yaml: the registry tracker-sync already reads, so a
board is configured once. Done and removed cards are left out unless asked.

query keys (all optional):
  boards          [slug, ...]  only these boards (default: every registered board)
  assigned_to_me  true: only cards assigned to you (bridge-config
                  integrations.github.assignee_me, else your gh login)
  states          [normalized state, ...]  only these
  include_done    true: keep done/removed cards
  filter          the board's own filter syntax, applied by GitHub before the limit
                  (default `is:open`; "" asks for every card). Without it a board with
                  more cards than the limit lost its newest ones: gh lists the oldest
                  first, so 393 cards behind a limit of 200 showed none of the 10 open
                  (live 2026-10-17). With include_done or a done/removed state no
                  filter is applied.
  limit           per board, default 200
"""
from __future__ import annotations

import importlib.util
import re
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from . import load_json, source_error


_LOADING = threading.Lock()
# Boards asked at once. Eight one after another took 64 s live (2026-10-09) against the
# section's 30 s, the two largest 16 s each; side by side the section takes the slowest one.
# Four, not all eight: eight in one burst tripped GitHub's secondary rate limit.
BOARD_WORKERS = 4
DEFAULT_FILTER = "is:open"
# One board through `gh project item-list` cost about 100 GraphQL points whatever its size (it asks every field
# of every card); this query asks only what a row needs and cost 2 (live 2026-10-18: 721 points a pass for eight
# boards, against an hourly budget of 5000 that every program of the account shares).
# The lifecycle column is the registry's `board.status_field` (default Status) and goes in as a variable; a
# `board.priority_field` adds one aliased field value, and only then, so a board without one asks nothing more.
LEAN_QUERY = """query($login: String!, $number: Int!, $q: String!, $after: String, $status: String!PRIORITY_VAR) {
  repositoryOwner(login: $login) { ... on ProjectV2Owner { projectV2(number: $number) {
    items(first: 100, after: $after, query: $q) { pageInfo { hasNextPage endCursor } nodes {
      id
      fieldValueByName(name: $status) { ... on ProjectV2ItemFieldSingleSelectValue { name } }PRIORITY_FIELD
      content { __typename
        ... on Issue { number title url updatedAt repository { nameWithOwner }
                       assignees(first: 5) { nodes { login } } labels(first: 5) { nodes { name } } }
        ... on PullRequest { number title url updatedAt repository { nameWithOwner }
                             assignees(first: 5) { nodes { login } } labels(first: 5) { nodes { name } } }
        ... on DraftIssue { title updatedAt assignees(first: 5) { nodes { login } } } }
    } } } } } }"""
PRIORITY_FIELD = """
      priority: fieldValueByName(name: $priority) { ... on ProjectV2ItemFieldSingleSelectValue { name } }"""


def board_fields(board: dict) -> tuple:
    """The board's lifecycle field and its priority field (None when the registry names none):
    `board.status_field` and `board.priority_field` of workflow/projects/<slug>.yaml, the keys board-pilot reads."""
    block = (board.get("registry") or {}).get("board") or {}
    status = block.get("status_field") if isinstance(block, dict) else None
    priority = block.get("priority_field") if isinstance(block, dict) else None
    return (status.strip() if isinstance(status, str) and status.strip() else "Status",
            priority.strip() if isinstance(priority, str) and priority.strip() else None)


def lean_query(priority: bool) -> str:
    return (LEAN_QUERY.replace("PRIORITY_VAR", ", $priority: String!" if priority else "")
            .replace("PRIORITY_FIELD", PRIORITY_FIELD if priority else ""))


def _listed_field(raw: dict, name: str):
    """A field of a `gh project item-list` row: gh keys each field by its lower-cased name."""
    for key in (name, name.lower(), name.lower().replace(" ", "")):
        value = raw.get(key)
        if value not in (None, ""):
            return value if isinstance(value, str) else (value.get("name") if isinstance(value, dict) else None)
    return None


def _listed(payload, board: dict):
    """An item-list answer read through the board's fields, as the lean query reads them."""
    status, priority = board_fields(board)
    if not isinstance(payload, dict):
        return payload
    for raw in payload.get("items") or []:
        if not isinstance(raw, dict):
            continue
        if status != "Status":
            raw["status"] = _listed_field(raw, status) or ""
        raw["priority"] = _listed_field(raw, priority) if priority else None
    return payload


class _Unexpected(Exception):
    """The lean query answered, but not in the shape asked for: the board is listed the old way."""


def _lean_cards(board: dict, wanted: str, limit: int, ctx) -> dict:
    """A board's cards in the shape of `gh project item-list --format json`, page by page up to `limit`."""
    items, after = [], None
    status, priority = board_fields(board)
    while len(items) < limit:
        argv = ["gh", "api", "graphql", "-f", f"query={lean_query(bool(priority))}", "-f", f"login={board['org']}",
                "-F", f"number={board['number']}", "-f", f"q={wanted}", "-f", f"status={status}"]
        if priority:
            argv += ["-f", f"priority={priority}"]
        if after:
            argv += ["-f", f"after={after}"]
        data = load_json(ctx.run(argv, timeout=ctx.timeout), f"board {board['slug']}")
        try:
            page = data["data"]["repositoryOwner"]["projectV2"]["items"]
            nodes, info = page["nodes"], page["pageInfo"]
        except (KeyError, TypeError):
            raise _Unexpected() from None
        for node in nodes or []:
            if not isinstance(node, dict):
                continue
            content = node.get("content") or {}
            people = [a.get("login") for a in ((content.get("assignees") or {}).get("nodes") or []) if isinstance(a, dict)]
            labels = [x.get("name") for x in ((content.get("labels") or {}).get("nodes") or []) if isinstance(x, dict)]
            card = {"id": node.get("id"), "status": (node.get("fieldValueByName") or {}).get("name") or "",
                    "priority": (node.get("priority") or {}).get("name") or None,
                    "title": content.get("title"), "assignees": people, "labels": labels,
                    "content": {"type": content.get("__typename"), "title": content.get("title"),
                                "updatedAt": content.get("updatedAt")}}
            if content.get("number") is not None:
                card["content"].update(number=content["number"], url=content.get("url"),
                                       repository=(content.get("repository") or {}).get("nameWithOwner"))
            items.append(card)
        if not info.get("hasNextPage"):
            break
        after = info.get("endCursor")
    return {"items": items[:limit]}


def _tracker_sync(ctx):
    """scripts/tracker-sync.py, loaded once. Board sections run side by side, so the load
    goes through the briefing's lock (`ctx.load_module`); a caller without one gets a
    lock of this module, and a load that fails leaves nothing behind."""
    name = "tracker_sync"
    here = Path(__file__).resolve().parents[2] / "tracker-sync.py"
    load = getattr(ctx, "load_module", None)
    if callable(load):
        return load(name, here)
    with _LOADING:
        if name in sys.modules:
            return sys.modules[name]
        spec = importlib.util.spec_from_file_location(name, here)
        if spec is None or spec.loader is None:  # pragma: no cover
            raise source_error("scripts/tracker-sync.py is missing")
        module = importlib.util.module_from_spec(spec)
        sys.modules[name] = module
        try:
            spec.loader.exec_module(module)
        except BaseException:
            sys.modules.pop(name, None)
            raise
        return module


def engine_limited(exc: Exception) -> bool:
    """A rate limit or a block of the engine: the old way would only ask a spent budget again."""
    import sys
    engine = sys.modules.get("briefing")
    pattern = getattr(engine, "GH_RATE_LIMIT", None)
    text = str(exc)
    return "not asked until" in text or bool(pattern and pattern.search(text))


def collect(section: dict, ctx) -> list:
    query = dict(section.get("query") or {})
    ts = _tracker_sync(ctx)
    boards = ts.resolve_boards(ctx.root, ts.load_registries(ctx.root))
    if query.get("boards"):
        boards = [b for b in boards if b["slug"] in query["boards"]]
    if not boards:
        raise source_error("no boards: add `github_projects:` to an ecosystem file")
    me = ((ctx.cfg.get("integrations") or {}).get("github") or {}).get("assignee_me")
    if not me and query.get("assigned_to_me"):
        try:
            me = load_json(ctx.run(["gh", "api", "user"], timeout=ctx.timeout), "gh api user").get("login")
        except Exception:  # noqa: BLE001
            raise source_error("assigned_to_me needs integrations.github.assignee_me or a gh login") from None
    states = set(query.get("states") or [])
    keep_done = query.get("include_done") or bool(states & {"done", "removed"})
    out, summary = [], []
    order = ("new", "ready", "in_progress", "review", "blocked")
    section_map = section.get("state_map") or {}
    default_keys = {re.sub(r"^[^0-9A-Za-z]+", "", k).strip().lower(): v for k, v in ts.DEFAULT_GH_STATE_MAP.items()}

    def known_state(raw_state: str, board: dict):
        """The state a board's count uses: the section's state_map first (as the rows get
        it), then the registry's, then the default. A status none of them knows (Parked,
        Canceled) is not counted as open work."""
        if not raw_state:
            return "new"
        if raw_state in section_map:
            return section_map[raw_state]
        reg_map = (board.get("registry") or {}).get("state_map") or {}
        if raw_state in reg_map:
            return reg_map[raw_state]
        return default_keys.get(re.sub(r"^[^0-9A-Za-z]+", "", raw_state).strip().lower())

    deadline = getattr(ctx, "deadline", None)
    wanted = "" if keep_done else query.get("filter", DEFAULT_FILTER)
    wanted = wanted.strip() if isinstance(wanted, str) else DEFAULT_FILTER

    def fetch(board: dict):
        """One board's cards, on a helper thread. The section's deadline lives per thread,
        so it is carried over: the board ends with its section, not with a limit of its own.
        A gh that does not know --query (before 2.70) lists without it."""
        if deadline is not None:
            ctx.deadline = deadline
        try:
            return _lean_cards(board, wanted, int(query.get("limit", 200)), ctx)
        except Exception as exc:  # noqa: BLE001 - a spent budget fails here; anything else lists the old way
            if engine_limited(exc):
                raise
        argv = ["gh", "project", "item-list", str(board["number"]), "--owner", str(board["org"]),
                "--format", "json", "--limit", str(query.get("limit", 200))]
        if wanted:
            try:
                return _listed(load_json(ctx.run([*argv, "--query", wanted], timeout=ctx.timeout),
                                         f"board {board['slug']}"), board)
            except Exception as exc:  # noqa: BLE001 - only an unknown flag falls back, anything else fails
                if "unknown flag" not in str(exc):
                    raise
        return _listed(load_json(ctx.run(argv, timeout=ctx.timeout), f"board {board['slug']}"), board)

    # Asked side by side, read back in the registry's order; the first board that fails
    # (in that order) fails the section, as it did one after another.
    with ThreadPoolExecutor(max_workers=min(BOARD_WORKERS, len(boards))) as pool:
        payloads = list(pool.map(fetch, boards))
    for board, payload in zip(boards, payloads):
        counts = dict.fromkeys(order, 0)
        raws = payload.get("items", []) if isinstance(payload, dict) else []
        for raw in raws:
            state = known_state(str(raw.get("status") or ""), board)
            if state in counts:              # every open card, drafts too, before the person's filters
                counts[state] += 1
            # a draft card is a row too (type draft, no number, no link): the count above has it
            item = ts.normalize_gh_item(raw, board, me, drafts=True)
            if not item:
                continue
            if query.get("assigned_to_me") and not item["assigned_to_me"]:
                continue
            if states and item["state"] not in states:
                continue
            if not keep_done and item["state"] in ("done", "removed"):
                continue
            out.append({**{k: v for k, v in item.items() if k not in ("number", "repo")},
                        "id": item["id"] if item.get("type") == "draft"
                        else f"{item.get('repo') or board['org']}#{item['number']}",
                        "type": str(item.get("type") or "issue").lower(),
                        "project": board["name"], "tracker": "github-board",
                        "priority": raw.get("priority") if isinstance(raw.get("priority"), str) else None,
                        "board": {"slug": board["slug"], "name": board["name"], "number": board["number"],
                                  "org": board["org"],
                                  **({"config": board["registry"]["_file"]}
                                     if (board.get("registry") or {}).get("_file") else {})},
                        "_category_from_state": True})
        limit = int(query.get("limit", 200))
        summary.append({"name": board["name"], "number": board["number"], "org": board["org"],
                        "slug": board["slug"], "counts": counts, "open": sum(counts.values()),
                        # gh returned as many cards as asked for: there may be more it did not.
                        "capped": limit if len(raws) >= limit else None})
    if section.get("summary"):
        # `summary: true`: the whole board as counts per state, beside the person's own rows.
        section["_summary"] = summary
    _stamp_changes(out, ctx)
    return out


ISSUE_ID = re.compile(r"^([\w.-]+)/([\w.-]+)#(\d+)$")
STAMP_LIMIT = 100


def _stamp_changes(items: list, ctx) -> None:
    """When each card's issue or PR last changed: a board list carries no date, so one
    GraphQL call asks for all kept rows at once. One card GitHub cannot answer (a deleted
    issue, a private repo) fails the whole call, so a failed call is split in halves until
    only the unanswerable cards are left without a date: every other row keeps its date,
    since a date that comes and goes would mark rows as changed. The section's time limit
    (ctx.run) bounds the splitting."""
    wanted = [(i, ISSUE_ID.match(str(item.get("id")))) for i, item in enumerate(items[:STAMP_LIMIT])
              if not item.get("changed_at")]
    wanted = [(i, m) for i, m in wanted if m]
    _ask_halving(wanted, items, ctx)


def _ask_halving(wanted: list, items: list, ctx) -> None:
    if not wanted or _ask_dates(wanted, items, ctx) or len(wanted) == 1:
        return
    half = len(wanted) // 2
    _ask_halving(wanted[:half], items, ctx)
    _ask_halving(wanted[half:], items, ctx)


def _ask_dates(wanted: list, items: list, ctx) -> bool:
    parts = [f'i{i}: repository(owner: "{m[1]}", name: "{m[2]}") {{ issueOrPullRequest(number: {m[3]}) '
             f'{{ ... on Issue {{ updatedAt }} ... on PullRequest {{ updatedAt }} }} }}' for i, m in wanted]
    try:
        data = load_json(ctx.run(["gh", "api", "graphql", "-f", "query={ " + " ".join(parts) + " }"],
                                 timeout=ctx.timeout), "board dates").get("data") or {}
    except Exception:  # noqa: BLE001 - a date is a nicety, never a reason to lose the rows
        return False
    for i, _ in wanted:
        node = (data.get(f"i{i}") or {}).get("issueOrPullRequest") or {}
        if node.get("updatedAt"):
            items[i]["changed_at"] = node["updatedAt"]
    return True
