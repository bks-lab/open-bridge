# SPDX-License-Identifier: MIT
"""The standing-order load contract, in one place.

Two callers read it and must never disagree about what is always-on:
`scripts/standing-orders.py` (the index and the check) and
`scripts/measure-context.py` (the budget). The contract itself is specified by
`scripts/tests/test_standing_orders.py`.
"""

from __future__ import annotations

from pathlib import Path

import yaml

ORDERS_DIR = Path("protocols") / "standing-orders"
VALID_LOAD = ("eager", "on-trigger")
DEFAULT_LOAD = "eager"

# The index is always-on, so every summary in it is paid on every turn. This is
# the same reasoning behind the SOUL.md line cap: a ceiling is what keeps a
# always-on surface from growing one reasonable-looking line at a time.
SUMMARY_MAX_CHARS = 200


def _frontmatter(path: Path) -> dict:
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.startswith("---"):
        return {}
    parts = text.split("\n---", 1)
    if len(parts) < 2:
        return {}
    try:
        loaded = yaml.safe_load(parts[0][3:])
    except yaml.YAMLError:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _is_order_candidate(path: Path) -> bool:
    """A `.md` under the orders dir that is not a README or `_`-prefixed."""
    return path.suffix == ".md" and path.name != "README.md" and not path.name.startswith("_")


def _unreadable_reason(path: Path):
    """Why this file's frontmatter cannot be read, or None when it can.

    A file with NO fence at all is prose that never claimed to be an order, and
    demanding frontmatter of it would be a check about somebody's notes. A file
    that HAS a fence and still yields nothing is the finding: it looks enforced
    in the tree and is loaded by nobody.
    """
    text = Path(path).read_text(encoding="utf-8", errors="replace")
    fenced = any(line.strip() == "---" for line in text.split("\n"))
    if not text.startswith("---"):
        if fenced:
            return "a `---` fence exists but the file does not start with it"
        return None
    parts = text.split("\n---", 1)
    if len(parts) < 2:
        return "the frontmatter fence is never closed"
    try:
        loaded = yaml.safe_load(parts[0][3:])
    except yaml.YAMLError as exc:
        return f"the frontmatter is not valid YAML ({str(exc).splitlines()[0]})"
    if not isinstance(loaded, dict):
        return "the frontmatter is not a mapping"
    return None


def unreadable_orders(repo_root: Path) -> list[str]:
    """Order files whose frontmatter cannot be read, as repo-relative paths.

    Without this they are INVISIBLE. `_frontmatter` returns `{}`, `scope`
    becomes `""`, and `collect_orders` drops them for not being `scope: always`
    — the same silent exit an org-scoped order takes on purpose. Downstream the
    two are indistinguishable, and only one of them is a guardrail going
    missing. Verified on two files carrying `enforcement: blocking`: both left
    the index, and `--check` reported the survivors as valid and exited 0.
    """
    base = Path(repo_root) / ORDERS_DIR
    if not base.is_dir():
        return []
    return sorted(
        path.relative_to(repo_root).as_posix()
        for path in base.rglob("*.md")
        if _is_order_candidate(path) and _unreadable_reason(path)
    )


def load_order(path: Path) -> dict:
    """Frontmatter plus the derived load policy, with the path attached."""
    front = _frontmatter(Path(path))
    triggers = front.get("triggers") or []
    if isinstance(triggers, str):
        triggers = [triggers]
    return {
        "path": Path(path).as_posix(),
        "name": str(front.get("name") or Path(path).stem),
        "scope": str(front.get("scope") or ""),
        "enforcement": str(front.get("enforcement") or ""),
        "load": str(front.get("load") or DEFAULT_LOAD),
        "triggers": [str(t) for t in triggers],
        "summary": str(front.get("summary") or ""),
        # Kept raw when it is not a boolean, so the check can name the typo.
        "fires_unprompted": front.get("fires_unprompted", False),
    }


def collect_orders(repo_root: Path) -> list[dict]:
    """Every `scope: always` order, sorted by path."""
    base = Path(repo_root) / ORDERS_DIR
    if not base.is_dir():
        return []
    orders = []
    for path in base.rglob("*.md"):
        if path.name == "README.md" or path.name.startswith("_"):
            continue
        order = load_order(path)
        if order["scope"] != "always":
            continue
        order["path"] = path.relative_to(repo_root).as_posix()
        orders.append(order)
    return sorted(orders, key=lambda o: o["path"])


def check_orders(orders: list[dict], unreadable=()) -> list[str]:
    """Contract violations, empty when it holds."""
    violations = [
        f"{path}: frontmatter cannot be read, so this file is in the tree and "
        f"in no session. An order that reads as enforced and loads never is the "
        f"one failure this contract exists to make impossible."
        for path in unreadable
    ]
    for order in orders:
        where = order["path"]
        unprompted = order.get("fires_unprompted", False)
        if not isinstance(unprompted, bool):
            violations.append(
                f"{where}: fires_unprompted is {unprompted!r}, expected true or false"
            )
        elif unprompted and order["load"] == "on-trigger":
            violations.append(
                f"{where}: fires_unprompted: true with load: on-trigger. The order "
                f"has to act while nobody says its vocabulary, and a trigger only "
                f"fetches it once somebody does, so it would load in none of the "
                f"sessions it exists for. Keep it eager."
            )
            continue
        if order["load"] not in VALID_LOAD:
            violations.append(
                f"{where}: unknown load value {order['load']!r} "
                f"(expected one of {', '.join(VALID_LOAD)})"
            )
            continue
        if order["load"] != "on-trigger":
            continue
        if not order["triggers"]:
            violations.append(
                f"{where}: load: on-trigger with no triggers. Nothing can fetch "
                f"this body, so the order is unreachable while still reading as "
                f"enforced in the tree."
            )
        if not order["summary"]:
            violations.append(
                f"{where}: load: on-trigger with no summary. Nothing announces "
                f"it in the index, so nothing ever asks for it."
            )
        elif len(order["summary"]) > SUMMARY_MAX_CHARS:
            violations.append(
                f"{where}: summary is {len(order['summary'])} chars, over the "
                f"{SUMMARY_MAX_CHARS} cap. The index is always-on."
            )
    return violations


def eager_paths(orders: list[dict]) -> list[str]:
    """The bodies Phase 1 still reads in full."""
    return [o["path"] for o in orders if o["load"] == "eager"]


def render_index(orders: list[dict]) -> str:
    """The always-on surface. Deterministic; no timestamp, no host."""
    out = [
        "# Standing orders",
        "",
        "Orders marked `eager` are already loaded. For the rest, read the file "
        "named when its vocabulary comes up.",
        "",
    ]
    for order in orders:
        if order["load"] == "eager":
            out.append(f"- **{order['name']}** (eager, loaded) `{order['path']}`")
            continue
        triggers = ", ".join(order["triggers"])
        summary = order["summary"] or ""
        out.append(
            f"- **{order['name']}** — {summary} "
            f"Triggers: {triggers}. Read `{order['path']}`."
        )
    out.append("")
    return "\n".join(out)
