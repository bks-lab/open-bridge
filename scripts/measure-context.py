#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Measure the always-on context a session loads, and hold it to a declared cap.

Every session loads a fixed body of text before the first answer: the
`@`-imports named in CLAUDE.md, the standing orders carrying `scope: always`,
and the Phase 1 reads. Nothing measured it, so it only ever grew, and it grew
where nobody looks: roughly half arrives through tool reads rather than
imports, so it never appears in a client's context listing at all.

One file in this repo has never sprawled, `identity/agent/SOUL.md`, and the
only thing that distinguishes it is a declared cap that a validator enforces.
This script generalises that cap to the whole always-on surface.

    python3 scripts/measure-context.py                 # report + gate
    python3 scripts/measure-context.py --method api    # exact counts
    python3 scripts/measure-context.py --out FILE      # also write the report

Exit code 0 when every item is within policy, 1 otherwise.

WHAT GATES AND WHAT ONLY INFORMS. The gate is on **bytes**, which are exact,
offline, and identical on every machine. Tokens are reported beside them, and
carry the method that produced them: `api` is exact
(`messages.count_tokens`, model-specific), `bytes` is an estimate from a
declared calibration. An estimate never fails a build, and never wears the
label of an exact count. A budget figure that does not say what counted it is
not a measurement.

The full contract, including every state and why it exists, lives in
`scripts/tests/test_measure_context.py`, which is the spec for this file.
"""

from __future__ import annotations

import argparse
import functools
import importlib.util
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from lib.standing_orders import (  # noqa: E402  (path setup must precede this import)
    collect_orders,
    eager_paths,
)
from lib.context_index import render_card  # noqa: E402

CORE_BUDGET = "context-budget.yaml"
USER_BUDGET = "context-budget.user.yaml"
ENTRY = "CLAUDE.md"
ORDERS_DIR = Path("protocols") / "standing-orders"

# Only a line that STARTS with `@` is an import. An address in prose is not.
IMPORT_RE = re.compile(r"^@(\S+)\s*$")

# Some always-on payload is not a file. Phase 1 loads the standing-order index
# and a slice of bridge-config.yaml, both computed at the moment of use so they
# can never go stale. A budget item keyed `cmd:<command>` is measured by running
# it and measuring stdout, which is what actually loads.
CMD_PREFIX = "cmd:"
# A budget file is reviewed, but it is still config, and config that can run
# anything is a different kind of file than the one anybody reviewed it as.
CMD_ALLOWED_PREFIX = "python3 scripts/"

LISTING_PREFIX = "listing:"

# The third residency channel, and the only DERIVED one: the harness injects
# `name` + `description` of every skill and every sub-agent into every session
# AND into every sub-agent dispatch, without any of it being a file the budget
# could point at. Measured on a live instance: 111 skills, 73 400 bytes, larger
# than every `@`-import in that tree combined, and declared nowhere.
#
# It is not dead weight. On that same instance 33 config-family paths were named
# ONLY in a skill description, and one family was reachable exclusively through
# one. So this belongs in `always_on_parts` as well as in the table: a surface
# that omits the listing makes the reachability contract report a family
# unreachable that a session can in fact find.
LISTINGS = {
    "skills": ("skills", "*/SKILL.md"),
    "agents": (".claude/agents", "*.md"),
}

FRONTMATTER_RE = re.compile(r"\A---\n(.*?)\n---", re.S)

HARNESS_PREFIX = "harness:"
# The fourth channel: what the HARNESS loads on its own, named in no file this
# tree controls. Claude Code reads the auto-memory index (`MEMORY.md` in the
# configured memory directory) into every main session before the first
# answer. Measured on a live instance at 20 227 bytes, counted nowhere. The
# directory is resolved by `scripts/memory-location.py`, the one place that
# knows the harness's precedence, so the meter cannot drift from it.
HARNESS_MEMORY_INDEX = HARNESS_PREFIX + "memory-index"
MEMORY_LOCATION = Path(__file__).resolve().parent / "memory-location.py"

DEFAULT_BYTES_PER_TOKEN = 2.4
DEFAULT_MODEL = "claude-opus-5"

# The states that fail the build. `uncapped` is deliberately absent: a newly
# declared item must be addable in one line without breaking anyone's CI.
#
# `contradiction` is a file that declares a `card:` AND is `@`-imported. The
# import loads the whole file every session; the card claims only the card
# does. Measuring the card there reported green while the session paid for the
# full text (on a live instance, 3 829 bytes reported for a 24 369 byte
# import). The pair is a false statement about what loads, so it fails at any
# size, and the full text is what gets counted.
FAILING = {"over", "undeclared", "missing", "contradiction"}

# An item may declare `enforce: advisory` to be measured and reported without
# failing the build. It exists for the one class the cap cannot honestly govern:
# an item whose size is driven by ONGOING WORK rather than by a file somebody
# edited. The work log is the case that produced this. It grows all week, resets
# on `/archive`, and a red build says "you worked too much this week", which is
# not a defect report. Everything a human authors and reviews stays hard: a
# CORE always-on file over its cap IS a defect, and staying red is the point.
#
# Advisory is a claim about the ITEM, not a way to quiet a number. An item that
# went advisory to escape a real cap has moved the problem, not solved it, so
# the report still prints the overrun and names it.
ADVISORY_NOTE = "advisory (measured, does not fail the build)"


# ------------------------------------------------------------- the budget --

def load_budget(repo_root: Path) -> dict:
    """Read the CORE budget, then overlay the per-instance one when present.

    The overlay replaces an item wholesale by key. It is not a deep merge,
    because a half-overridden cap is worse than either cap on its own.
    """
    core = Path(repo_root) / CORE_BUDGET
    if not core.is_file():
        sys.exit(
            f"error: {CORE_BUDGET} not found in {repo_root}.\n"
            "       A meter with no policy enforces nothing and would report\n"
            "       green forever, so this is refused rather than skipped."
        )

    budget = yaml.safe_load(core.read_text(encoding="utf-8")) or {}
    budget.setdefault("items", {})
    budget.setdefault("calibration", {})
    budget["calibration"].setdefault("bytes_per_token", DEFAULT_BYTES_PER_TOKEN)
    budget["calibration"].setdefault("model", DEFAULT_MODEL)

    user = Path(repo_root) / USER_BUDGET
    if user.is_file():
        overlay = yaml.safe_load(user.read_text(encoding="utf-8")) or {}
        for key, value in (overlay.get("items") or {}).items():
            budget["items"][key] = value or {}
        budget["calibration"].update(overlay.get("calibration") or {})

    budget["items"] = {k: (v or {}) for k, v in (budget["items"] or {}).items()}
    return budget


# ---------------------------------------------------------- what is loaded --

def discover_imports(repo_root: Path, entry: str = ENTRY, max_depth: int = 4) -> list[str]:
    """The `@`-imports actually loaded, followed recursively, first-seen order.

    An import that does not resolve is RETURNED rather than dropped. Dropping
    it would remove it from the measured set silently, which is the exact
    failure this script exists to prevent.
    """
    root = Path(repo_root)
    found: list[str] = []
    seen: set[str] = set()

    def walk(rel: str, depth: int) -> None:
        if depth > max_depth:
            return
        path = root / rel
        if not path.is_file():
            return
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            match = IMPORT_RE.match(line)
            if not match:
                continue
            target = match.group(1)
            if target in seen:
                continue
            seen.add(target)
            found.append(target)
            walk(target, depth + 1)

    walk(entry, 0)
    return found


def discover_standing_orders(repo_root: Path) -> list[str]:
    """The orders that are actually always-on: `scope: always` AND `load: eager`.

    An `on-trigger` order is fetched by its vocabulary and is not part of the
    always-on surface. Counting it here would overstate the budget and hide the
    saving the load contract buys. The contract lives in
    `scripts/lib/standing_orders.py`, shared so this file and the index can
    never disagree about what is always-on.
    """
    return sorted(eager_paths(collect_orders(Path(repo_root))))


def deferred_standing_orders(repo_root: Path) -> list[tuple[str, int]]:
    """The bodies the contract moved off the always-on surface, and their size.

    Reported rather than dropped: silence about a deferred body reads exactly
    like a file that vanished.
    """
    root = Path(repo_root)
    out = []
    for order in collect_orders(root):
        if order["load"] == "eager":
            continue
        path = root / order["path"]
        size = len(path.read_bytes()) if path.is_file() else 0
        out.append((order["path"], size))
    return sorted(out)


# ------------------------------------------------------------ the counting --

def _api_token_count(text: str, model: str):
    """Exact count via `messages.count_tokens`, or None when unavailable.

    Credentials are left entirely to the SDK: an unset `ANTHROPIC_API_KEY`
    does not mean there are none, since a profile from `ant auth login` also
    authenticates a zero-argument client.
    """
    try:
        import anthropic
    except Exception:
        return None
    try:
        client = anthropic.Anthropic()
        response = client.messages.count_tokens(
            model=model,
            messages=[{"role": "user", "content": text}],
        )
        return int(response.input_tokens)
    except Exception:
        return None


def count_tokens(text: str, method: str, bytes_per_token: float, model: str):
    """Return (count, method_actually_used).

    A requested `api` that cannot run falls back to `bytes` and says `bytes`.
    Reporting an estimate as exact is the one outcome forbidden here.
    """
    if method == "api":
        exact = _api_token_count(text, model)
        if exact is not None:
            return exact, "api"
    size = len(text.encode("utf-8"))
    return int(round(size / float(bytes_per_token))), "bytes"


# ---------------------------------------------------------------- the rows --

def run_command_item(repo_root: Path, key: str):
    """Run a `cmd:` budget item and return its stdout, or None when it failed.

    None is deliberately not an empty string: a payload that cannot be produced
    and one that shrank to nothing look identical at zero bytes, and only one of
    them is a finding.
    """
    command = key[len(CMD_PREFIX):].strip()
    if not command.startswith(CMD_ALLOWED_PREFIX):
        sys.exit(
            f"error: budget item {key!r} is outside the command allowlist.\n"
            f"       Only {CMD_ALLOWED_PREFIX!r} is accepted."
        )
    # The meter enters through CLAUDE.md, so it measures a Claude Code session,
    # and a command that behaves differently inside one has to see one. The
    # case that needs it: `memory-location.py index` prints the whole memory
    # index outside Claude Code and one line inside, because there the harness
    # already loaded the file. Run from CI or a terminal, the command row
    # counted the same index as the `harness:` row, twice.
    env = dict(os.environ)
    env["CLAUDECODE"] = "1"
    env.pop("CLAUDE_CODE_DISABLE_AUTO_MEMORY", None)
    try:
        done = subprocess.run(
            shlex.split(command),
            cwd=str(repo_root),
            capture_output=True,
            text=True,
            timeout=60,
            env=env,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout if done.returncode == 0 else None


def _described(path: Path):
    """(name, one-line description) for one listing entry, or None.

    Parsed with the YAML loader rather than a regex because a description is
    routinely a folded scalar, and a regex that keeps the fold would make the
    listing's line count a lie: one entry would occupy several lines and a
    runaway one could hide in the middle of them.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    match = FRONTMATTER_RE.match(text)
    if not match:
        return None
    try:
        front = yaml.safe_load(match.group(1))
    except yaml.YAMLError:
        return None
    if not isinstance(front, dict):
        return None
    description = front.get("description")
    if not isinstance(description, str) or not description.strip():
        # No description, no listing entry: the harness lists what has one.
        return None
    # The directory carries the identity when frontmatter does not. A skill is
    # addressed by its folder, so dropping one for a missing `name:` would
    # under-report a surface this exists to stop under-reporting.
    stem = path.parent.name if path.name == "SKILL.md" else path.stem
    name = front.get("name")
    name = str(name).strip() if isinstance(name, (str, int, float)) else ""
    return (name or stem, " ".join(description.split()))


def listing_entries(repo_root: Path, key: str):
    """Every described entry of one listing family, or None when absent.

    None and `[]` are different findings: a family this tree does not have, and
    a family whose every entry lost its description. Only the second is a bug,
    and at zero bytes they would look identical.
    """
    family = key[len(LISTING_PREFIX):].strip()
    known = LISTINGS.get(family)
    if known is None:
        sys.exit(
            f"error: budget item {key!r} names no listing family.\n"
            f"       Known: {', '.join(sorted(LISTINGS))}."
        )
    base, pattern = known
    root = Path(repo_root)
    if not (root / base).is_dir():
        return None
    entries = []
    for path in sorted((root / base).glob(pattern)):
        entry = _described(path)
        if entry:
            entries.append(entry)
    return entries


def _listing_line(name: str, description: str) -> str:
    return f"- **{name}** \u2014 {description}\n"


def render_listing(repo_root: Path, key: str):
    """The listing as the session carries it, or None when the family is absent."""
    entries = listing_entries(repo_root, key)
    if entries is None:
        return None
    return "".join(_listing_line(name, desc) for name, desc in entries)


def discover_listings(repo_root: Path) -> list[str]:
    """The listing families this tree actually has.

    Discovered, never merely declared. An instance that never writes the budget
    entry would otherwise carry the whole listing unmeasured, which is exactly
    the state this feature was written to end.
    """
    root = Path(repo_root)
    return [
        LISTING_PREFIX + family
        for family, (base, _) in sorted(LISTINGS.items())
        if (root / base).is_dir()
    ]


@functools.lru_cache(maxsize=1)
def _memory_location():
    spec = importlib.util.spec_from_file_location("memory_location", MEMORY_LOCATION)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def harness_memory_index(repo_root: Path, home: Path | None = None) -> Path | None:
    """The MEMORY.md the harness loads for this repo, or None when it loads none.

    None covers both "auto memory is switched off" and "no index yet", which
    on a fresh clone is the normal case and not an error. The directory is the
    one the harness READS (`autoMemoryDirectory`, else its per-project default),
    not the reader fallback `work/memory/`: a directory the harness does not
    load costs a session nothing until Phase 1 reads it, and that read is
    measured as its own `cmd:` row.
    """
    home = Path(home) if home is not None else Path.home()
    try:
        ml = _memory_location()
        root = ml.repo_root_for(repo_root)
        enabled, _source = ml._first_setting(root, home, "autoMemoryEnabled")
        if enabled is False:
            return None
        directory, _source, _warnings = ml.resolve_memory_dir(repo_root, home)
    except Exception:
        return None
    index = Path(directory) / "MEMORY.md"
    return index if index.is_file() else None


def discover_harness(repo_root: Path) -> dict[str, Path]:
    """The harness-loaded items that exist for this tree right now, by key.

    Resolved once per run: the directory lookup asks git, and a meter that
    asked it once per row would pay for that on every item.
    """
    index = harness_memory_index(repo_root)
    return {HARNESS_MEMORY_INDEX: index} if index else {}


def read_harness_item(key: str, found: dict[str, Path]):
    """Text of a `harness:` item, or None when the harness loads nothing there."""
    if key != HARNESS_MEMORY_INDEX:
        sys.exit(
            f"error: budget item {key!r} names no harness item.\n"
            f"       Known: {HARNESS_MEMORY_INDEX}."
        )
    index = found.get(key)
    return index.read_text(encoding="utf-8", errors="replace") if index else None


def item_state(row: dict, policy, exists: bool, contradiction: bool = False) -> str:
    """ok | over | uncapped | undeclared | absent | missing | contradiction."""
    if contradiction:
        return "contradiction"
    if policy is None:
        # Discovered on disk (or declared as an import) but absent from the
        # budget. Without this the budget silently stops covering the tree the
        # moment somebody adds an import, and a meter that cannot see a new
        # file is worse than no meter: it reports green while its subject grows.
        return "undeclared"
    if not exists:
        return "absent" if policy.get("optional") else "missing"
    cap = policy.get("max_bytes")
    if cap is None:
        return "uncapped"
    return "over" if row["bytes"] > int(cap) else "ok"


def collect_rows(repo_root: Path, budget: dict, method: str) -> list[dict]:
    """One row per always-on item, sorted by (source, path)."""
    root = Path(repo_root)
    items = budget.get("items") or {}
    calibration = budget.get("calibration") or {}
    bytes_per_token = float(calibration.get("bytes_per_token", DEFAULT_BYTES_PER_TOKEN))
    model = str(calibration.get("model", DEFAULT_MODEL))

    discovered: dict[str, str] = {}
    if (root / ENTRY).is_file():
        discovered[ENTRY] = "import"
    for rel in discover_imports(root):
        discovered.setdefault(rel, "import")
    for rel in discover_standing_orders(root):
        discovered.setdefault(rel, "standing-order")
    for rel in discover_listings(root):
        discovered.setdefault(rel, "listing")
    harness = discover_harness(root)
    for rel in harness:
        discovered.setdefault(rel, "harness")

    rows = []
    for path in sorted(set(discovered) | set(items)):
        policy = items.get(path)
        source = discovered.get(path) or (policy or {}).get("source") or "phase1"
        body_bytes = None
        largest = None
        contradiction = False
        if path.startswith(HARNESS_PREFIX):
            text = read_harness_item(path, harness)
            exists = text is not None
            source = (policy or {}).get("source") or "harness"
        elif path.startswith(LISTING_PREFIX):
            entries = listing_entries(root, path)
            exists = entries is not None
            text = render_listing(root, path) if exists else None
            source = (policy or {}).get("source") or "listing"
            if entries:
                largest = sorted(
                    (
                        (name, len(_listing_line(name, desc).encode("utf-8")))
                        for name, desc in entries
                    ),
                    key=lambda pair: (-pair[1], pair[0]),
                )[:5]
        elif path.startswith(CMD_PREFIX):
            text = run_command_item(root, path)
            exists = text is not None
            source = (policy or {}).get("source") or "command"
        else:
            target = root / path
            exists = target.is_file()
            text = (
                target.read_text(encoding="utf-8", errors="replace")
                if exists
                else None
            )
            # A declared card is what the session actually loads, so it is what
            # the gate has to measure. Measuring the file instead would report
            # red for content no session pays for, and the obvious response to
            # that red — raise the cap — would quietly undo the feature.
            #
            # Unless the file is ALSO `@`-imported. Then the import loads it
            # whole and the card is a claim nothing honours: measure the full
            # text and fail, whatever its size.
            if exists and (policy or {}).get("card") and discovered.get(path) == "import":
                contradiction = True
            elif exists and (policy or {}).get("card"):
                body_bytes = len(text.encode("utf-8"))
                text = render_card(text, policy["card"], path)

        row = {
            "path": path,
            "source": source,
            "bytes": 0,
            "tokens": 0,
            "method": method,
            "max_bytes": (policy or {}).get("max_bytes"),
            "body_bytes": body_bytes,
            "largest": largest,
            "advisory": (policy or {}).get("enforce") == "advisory",
        }
        if exists:
            row["bytes"] = len(text.encode("utf-8"))
            row["tokens"], row["method"] = count_tokens(
                text, method, bytes_per_token, model
            )
        row["state"] = item_state(row, policy, exists, contradiction)
        rows.append(row)

    rows.sort(key=lambda r: (r["source"], r["path"]))
    return rows


def always_on_parts(repo_root: Path, budget: dict) -> dict[str, str]:
    """Everything a session loads before it answers, KEYED BY WHERE IT CAME FROM.

    Same discovery as `collect_rows`, on purpose. A second definition of
    always-on would let something claim residency in a file no session reads,
    which is the failure the budget exists to make impossible.

    Keyed rather than concatenated so a caller can say WHICH file carries a
    thing, and so a mutation battery can remove one contributor at a time. A
    battery over the concatenation only proves that a substring test is a
    substring test.
    """
    root = Path(repo_root)
    parts: dict[str, str] = {}
    harness = discover_harness(root)
    for row in collect_rows(root, budget, "bytes"):
        path = row["path"]
        if path.startswith(HARNESS_PREFIX):
            text = read_harness_item(path, harness)
        elif path.startswith(LISTING_PREFIX):
            text = render_listing(root, path)
        elif path.startswith(CMD_PREFIX):
            text = run_command_item(root, path)
        else:
            target = root / path
            text = (
                target.read_text(encoding="utf-8", errors="replace")
                if target.is_file()
                else None
            )
            # The CARD is what a session loads for a declared source, so it is
            # what the surface has to be. Handing over the file body would put
            # ~25 KB of never-read registry into the reachability contract and
            # let a family claim a route through text nobody sees — the second
            # definition of always-on this function exists to prevent.
            # A contradiction loads whole, so it enters the surface whole.
            policy = (budget.get("items") or {}).get(path) or {}
            if text and policy.get("card") and row["state"] != "contradiction":
                text = render_card(text, policy["card"], path)
        if text:
            parts[path] = text
    return parts


def always_on_text(repo_root: Path, budget: dict) -> str:
    """The same surface as one string."""
    return "\n".join(always_on_parts(repo_root, budget).values())


# -------------------------------------------------------------- the report --

def effective_method(rows: list[dict], requested: str) -> str:
    """`api` only when every measured row really got an exact count."""
    measured = [r for r in rows if r["bytes"] > 0]
    if requested == "api" and measured and all(r["method"] == "api" for r in measured):
        return "api"
    return "bytes"


def _cell(value) -> str:
    return "-" if value is None else f"{value:,}".replace(",", " ")


def render_report(
    rows: list[dict],
    method: str,
    bytes_per_token: float,
    deferred: list[tuple[str, int]] | None = None,
) -> str:
    """Deterministic markdown. No timestamp, no host, no absolute path."""
    out = ["# Context budget", ""]
    if method == "api":
        out.append("Token counts are exact (`messages.count_tokens`).")
    else:
        out.append(
            f"Token counts are an **estimate** (method `bytes`, "
            f"{bytes_per_token} bytes per token). Bytes are exact, and the caps "
            f"gate on bytes."
        )
    out += [
        "",
        "| Source | Path | Bytes | Cap | Tokens | State |",
        "|---|---|---:|---:|---:|---|",
    ]
    for row in rows:
        out.append(
            f"| {row['source']} | `{row['path']}` | {_cell(row['bytes'])} | "
            f"{_cell(row['max_bytes'])} | {_cell(row['tokens'])} | {row['state']} |"
        )

    total_bytes = sum(r["bytes"] for r in rows)
    total_tokens = sum(r["tokens"] for r in rows)
    out.append(
        f"| | **total** | **{_cell(total_bytes)}** | | "
        f"**{_cell(total_tokens)}** | |"
    )

    if deferred:
        total = sum(size for _, size in deferred)
        out += [
            "",
            f"{len(deferred)} standing order(s) load on trigger and are not part "
            f"of the always-on surface ({_cell(total)} bytes, fetched by "
            f"vocabulary). They are listed here so a deferred body is never "
            f"mistaken for a file that vanished:",
            "",
        ]
        for path, size in deferred:
            out.append(f"- `{path}` ({_cell(size)} bytes)")

    indexed = [r for r in rows if r.get("body_bytes")]
    if indexed:
        out += [
            "",
            f"{len(indexed)} source(s) are indexed: the card above is always-on, "
            f"the rest arrives when somebody names an entry. Listed so a "
            f"deferred body is never mistaken for a file that shrank:",
            "",
        ]
        for row in indexed:
            deferred_bytes = row["body_bytes"] - row["bytes"]
            out.append(
                f"- `{row['path']}` — card {_cell(row['bytes'])} of "
                f"{_cell(row['body_bytes'])} bytes, {_cell(deferred_bytes)} "
                f"reachable with `context-index.py {row['path']} --get <path>`"
            )

    listings = [r for r in rows if r.get("largest")]
    if listings:
        out += [
            "",
            f"{len(listings)} listing(s) are DERIVED, not read: the harness "
            f"injects one line per entry into every session and every sub-agent "
            f"dispatch. There is no file to cap, so the cap is on the sum and "
            f"the heaviest entries are named here \u2014 a listing grows one "
            f"description at a time, and that is the growth nobody notices:",
            "",
        ]
        for row in listings:
            entries = ", ".join(f"{n} ({_cell(b)} B)" for n, b in row["largest"])
            out.append(f"- `{row['path']}` \u2014 heaviest: {entries}")

    contradicted = [r for r in rows if r["state"] == "contradiction"]
    if contradicted:
        out += [
            "",
            f"{len(contradicted)} source(s) declare a `card:` and are also "
            f"`@`-imported. The import loads the whole file every session, so "
            f"the full text is counted above and the card is not. Remove the "
            f"`@`-import (and import a generated card file instead, if "
            f"sub-agents need the registry), or drop the `card:`:",
            "",
        ]
        for row in contradicted:
            out.append(f"- `{row['path']}` ({_cell(row['bytes'])} bytes loaded in full)")

    outside = [r for r in rows if r["state"] in FAILING]
    failing = [r for r in outside if not r["advisory"]]
    advisory = [r for r in outside if r["advisory"]]
    out.append("")
    if outside:
        out.append(f"{len(outside)} item(s) outside policy:")
        out.append("")
        for row in outside:
            suffix = f" — {ADVISORY_NOTE}" if row["advisory"] else ""
            out.append(f"- `{row['path']}` — {row['state']}{suffix}")
        if advisory and not failing:
            out.append("")
            out.append(
                "All of them are advisory, so the build stays green. They are "
                "still over: read the note on each item before ignoring it."
            )
    else:
        out.append("Every item is within policy.")
    out.append("")
    return "\n".join(out)


def write_user_budget(repo_root: Path, rows: list[dict], force: bool = False) -> Path:
    """`--init`: declare the undeclared, uncapped, in the per-instance overlay.

    An instance adopting this from CORE starts with every file CORE cannot know
    about reported `undeclared`, which fails the run. That is correct (a meter
    that cannot see a new file reports green while its subject grows) and it is
    also unusable as a first experience. So the first run can declare them,
    uncapped: visible in every report, failing nothing, and one line each away
    from a real cap.

    It refuses to overwrite an existing overlay without `--force`, because that
    file is hand-tuned the moment anybody cares about it.
    """
    target = Path(repo_root) / USER_BUDGET
    if target.exists() and not force:
        sys.exit(
            f"error: {USER_BUDGET} already exists.\n"
            "       It is hand-tuned once anybody has cared about a cap, so it\n"
            "       is not overwritten. Add the items by hand, or pass --force."
        )
    undeclared = [r["path"] for r in rows if r["state"] == "undeclared"]
    lines = [
        "# Per-instance context budget, layered over the CORE `context-budget.yaml`.",
        "#",
        "# Written by `measure-context.py --init` from what this instance actually",
        "# loads. Every entry starts UNCAPPED: reported in each run, failing",
        "# nothing. Add `max_bytes:` to the ones whose growth you want to hear",
        "# about, which is the entire value of the file.",
        "",
        "# The shipped schema (docs/schemas/context-budget.schema.yaml) validates",
        "# this overlay as well as the CORE file, and requires this key. It was",
        "# missing here for a day, unnoticed, because the file is gitignored by",
        "# default and no validator ever reached it.",
        "schema_version: 1",
        "",
        "items:",
    ]
    for path in undeclared:
        lines.append(f'  "{path}": {{}}')
    if not undeclared:
        lines.append("  {}")

    # A file that already exists is APPENDED to, never replaced. `--init` writes
    # the UNDECLARED items, so on a file that already declares things those items
    # are by definition no longer undeclared — and the rewrite wrote their
    # COMPLEMENT. Measured against a live instance: 162 lines, 8 380 bytes and 13
    # declarations became 15 lines, 629 bytes and none. Every cap gone, and with
    # them 147 lines explaining why each cap has its number, which is the half
    # nobody can reconstruct. One command, no confirmation, no backup.
    #
    # `--force` therefore means "add what is missing", which is what the
    # docstring above always said this was for.
    if target.exists():
        if not undeclared:
            return target
        existing = target.read_text(encoding="utf-8").rstrip("\n")
        added = [
            "",
            "  # Appended by `measure-context.py --init --force`: items this",
            "  # instance loads and had not declared. Uncapped on purpose —",
            "  # visible in every report, failing nothing. Give the ones whose",
            "  # growth should be heard about a `max_bytes:` AND a reason.",
        ]
        added += [f'  "{path}": {{}}' for path in undeclared]
        target.write_text(existing + "\n" + "\n".join(added) + "\n", encoding="utf-8")
        return target

    target.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return target


# ------------------------------------------------------------------ main --

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        description="Measure the always-on context and hold it to its budget."
    )
    parser.add_argument("--repo-root", default=None, help="defaults to this repo")
    parser.add_argument("--method", choices=("bytes", "api"), default="bytes")
    parser.add_argument("--out", default=None, help="also write the report here")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument(
        "--init",
        action="store_true",
        help="declare this instance's undeclared items, uncapped, in "
             "context-budget.user.yaml",
    )
    parser.add_argument("--force", action="store_true", help="with --init: overwrite")
    args = parser.parse_args(argv)

    root = (
        Path(args.repo_root).resolve()
        if args.repo_root
        else Path(__file__).resolve().parents[1]
    )
    budget = load_budget(root)
    rows = collect_rows(root, budget, args.method)

    bytes_per_token = float(
        (budget.get("calibration") or {}).get("bytes_per_token", DEFAULT_BYTES_PER_TOKEN)
    )
    if args.init:
        target = write_user_budget(root, rows, force=args.force)
        undeclared = sum(1 for r in rows if r["state"] == "undeclared")
        if not args.quiet:
            print(
                f"measure-context: declared {undeclared} item(s) uncapped in "
                f"{target.name}. Add a cap to the ones whose growth you want to "
                f"hear about."
            )
        return 0

    report = render_report(
        rows,
        effective_method(rows, args.method),
        bytes_per_token,
        deferred=deferred_standing_orders(root),
    )

    if not args.quiet:
        print(report)
    if args.out:
        Path(args.out).write_text(report, encoding="utf-8")

    return 1 if any(r["state"] in FAILING and not r["advisory"] for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
