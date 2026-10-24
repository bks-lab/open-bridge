#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Pytest suite for scripts/measure-context.py.

CONTRACT, this file is the authoritative spec for that surface.

WHY THIS SCRIPT EXISTS. Every session loads a fixed body of text before the
first answer: the `@`-imports named in CLAUDE.md, the standing orders carrying
`scope: always`, and the Phase 1 reads. Nothing measures it, so it only ever
grows, and it grows invisibly: half of it never appears in a client's context
listing because it arrives through tool reads rather than imports. One file in
this repo has never sprawled, `identity/agent/SOUL.md`, and the only thing that
distinguishes it is a declared cap that a validator enforces. This script
generalises that cap to the whole always-on surface.

    load_budget(repo_root) -> dict
        Reads `context-budget.yaml`, then overlays `context-budget.user.yaml`
        when present. The overlay replaces an item wholesale by key; it is not
        a deep merge, because a half-overridden cap is worse than either cap.
        A missing CORE budget is a hard error: a meter with no policy enforces
        nothing and would report green forever.

    discover_imports(repo_root, entry="CLAUDE.md", max_depth=4) -> list[str]
        The `@`-imports actually loaded, followed recursively, first-seen order,
        deduplicated, cycle-safe. Only a line that STARTS with `@` counts; an
        address inside prose is not an import. A target that does not resolve is
        RETURNED rather than dropped, so it surfaces as `missing` instead of
        quietly leaving the measured set.

    discover_standing_orders(repo_root) -> list[str]
        The orders that are actually always-on: `scope: always` AND
        `load: eager` (the default). An `on-trigger` order is fetched by its
        vocabulary and is not part of the always-on surface, so counting it
        here would overstate the budget and hide the saving. The load contract
        itself lives in `scripts/lib/standing_orders.py`, shared so the meter
        and the index can never disagree about what is always-on.

    count_tokens(text, method, bytes_per_token, model) -> (int, str)
        Returns the count AND the method that actually produced it. `api` is
        exact, via `messages.count_tokens` on the declared model (counts are
        model-specific, so the model travels with the number too); `bytes` is an
        estimate from a declared calibration. A requested
        `api` that cannot run falls back to `bytes` and says `bytes`. It never
        reports an estimate as exact, which is the whole reason the method
        travels with the number.

    COMMAND ITEMS. Some always-on payload is not a file. Phase 1 loads the
    standing-order index and a slice of `bridge-config.yaml`, both computed at
    the moment of use so they can never go stale. A budget item keyed
    `cmd:<command>` is measured by running it and measuring stdout, which is
    what is actually loaded. Only `python3 scripts/...` is accepted: a budget
    file is reviewed, but it is still config, and config that can run anything
    is a different kind of file than the one anybody reviewed it as.

    collect_rows(repo_root, budget, method) -> list[dict]
        One row per always-on item, sorted by (source, path) so an unchanged
        tree renders identically twice.

    HARNESS ITEMS. Some always-on payload is loaded by the harness itself and
    named in no file of this tree. `harness:memory-index` is the auto-memory
    `MEMORY.md` Claude Code loads into every main session, resolved through
    `scripts/memory-location.py` (the directory the harness reads, so
    `autoMemoryDirectory` or its per-project default). Absent when there is no
    index or auto memory is off (setting or `CLAUDE_CODE_DISABLE_AUTO_MEMORY`),
    which is no error. A lookup that RAISES is the failing state `error`, never
    "no index". Counted is what the harness loads: the file cut at its load
    limit, and a cut file is `over` whatever the cap. `cmd:` items run with
    `CLAUDECODE=1`, because the meter measures the session CLAUDE.md opens and
    a command that answers differently inside one must not count a file the
    harness row already counted.

    item_state(row) -> str
        ok          measured, under `max_bytes`
        over        measured, above `max_bytes`               -> FAILS
        uncapped    measured, no cap declared                 -> warns only
        undeclared  discovered on disk, absent from budget    -> FAILS
        absent      declared `optional: true`, not on disk    -> ok
        missing     declared and required, not on disk        -> FAILS
        contradiction  declares a `card:` AND is `@`-imported    -> FAILS
                    (the import loads the file whole, so the full text is
                    measured and the card is reported as a claim nothing
                    honours, whatever the size)
        error       a harness lookup raised                    -> FAILS

        `contradiction` and `error` fail even under `enforce: advisory`:
        advisory excuses a size driven by ongoing work, not a false claim
        about what loads or a meter that cannot see its subject.

        `undeclared` is the load-bearing one. Without it the budget silently
        stops covering the tree the moment somebody adds an import, and a meter
        that cannot see a new file is worse than no meter, because it reports
        green while the thing it watches grows.

    render_report(rows, method, bytes_per_token) -> str
        Deterministic markdown. No timestamp, no host, no absolute path. States
        the method in the header and marks the token column as an estimate
        whenever the method is not exact.

    main(argv) -> int
        0 when no row is in a failing state, 1 otherwise.

    write_user_budget(repo_root, rows) -> Path
        `--init`. An instance adopting this from CORE starts with nine or more
        `undeclared` rows, because CORE cannot know which files a given instance
        loads. Failing on day one with no way forward would be a gate nobody
        adopts, so `--init` writes the undeclared items into
        `context-budget.user.yaml` UNCAPPED: visible in every report, failing
        nothing, and one line each away from a real cap. It refuses to overwrite
        an existing user budget without `--force`, since that file is hand-tuned
        the moment anybody cares about it.

EVERY GATE HAS A FIXTURE THAT TRIPS IT. A control that is never made to fail
proves nothing about the rule it claims to enforce; the same reasoning the
remote-inventory battery states in `infra/remotes/_tests/run.sh --mutate`.
"""

import importlib.util
import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "measure-context.py"


def _load_module():
    """Import the hyphenated script by path (it is not an importable name)."""
    spec = importlib.util.spec_from_file_location("measure_context", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["measure_context"] = mod
    spec.loader.exec_module(mod)
    return mod


mc = _load_module()


# --------------------------------------------------------------- fixtures --

def _write(root: Path, rel: str, text: str) -> Path:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def _order(name: str, scope: str = "always", load: str | None = None) -> str:
    extra = ""
    if load == "on-trigger":
        extra = 'load: on-trigger\ntriggers: ["x"]\nsummary: "s"\n'
    elif load:
        extra = f"load: {load}\n"
    return (
        "---\n"
        f"name: {name}\n"
        f"scope: {scope}\n"
        "enforcement: advisory\n"
        "applies_to: []\n"
        f"{extra}"
        "---\n\n"
        f"# {name}\n\nbody\n"
    )


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A minimal but realistic always-on surface."""
    _write(tmp_path, "CLAUDE.md", "@AGENTS.md\n\n@ecosystem.yaml\n\nprose\n")
    _write(tmp_path, "AGENTS.md", "A" * 500)
    _write(tmp_path, "protocols/standing-orders/task-sync.md", _order("task-sync"))
    _write(tmp_path, "protocols/standing-orders/README.md", "# not an order\n")
    _write(tmp_path, "protocols/standing-orders/_template.md", _order("template"))
    _write(tmp_path, "work/board.md", "B" * 300)
    _write(
        tmp_path,
        "context-budget.yaml",
        "schema_version: 1\n"
        "calibration:\n"
        "  bytes_per_token: 2.4\n"
        "items:\n"
        "  CLAUDE.md:\n"
        "    max_bytes: 1000\n"
        "  AGENTS.md:\n"
        "    max_bytes: 1000\n"
        "  ecosystem.yaml:\n"
        "    optional: true\n"
        "  protocols/standing-orders/task-sync.md:\n"
        "    max_bytes: 1000\n"
        "  work/board.md:\n"
        "    source: phase1\n"
        "    max_bytes: 1000\n",
    )
    return tmp_path


# ------------------------------------------------------- discover_imports --

def test_imports_are_found_at_line_start(tree):
    assert mc.discover_imports(tree) == ["AGENTS.md", "ecosystem.yaml"]


def test_the_entry_file_is_itself_measured(tree):
    """CLAUDE.md is loaded every session; a meter blind at its own front door
    would miss the one file every instance is guaranteed to have."""
    rows = mc.collect_rows(tree, mc.load_budget(tree), "bytes")
    assert any(r["path"] == "CLAUDE.md" for r in rows)


def test_an_at_sign_inside_prose_is_not_an_import(tmp_path):
    _write(tmp_path, "CLAUDE.md", "write to someone@example.com about @notanimport.md\n")
    assert mc.discover_imports(tmp_path) == []


def test_imports_are_followed_recursively(tmp_path):
    _write(tmp_path, "CLAUDE.md", "@AGENTS.md\n")
    _write(tmp_path, "AGENTS.md", "@docs/deep.md\n")
    _write(tmp_path, "docs/deep.md", "leaf\n")
    assert mc.discover_imports(tmp_path) == ["AGENTS.md", "docs/deep.md"]


def test_an_import_cycle_terminates(tmp_path):
    _write(tmp_path, "CLAUDE.md", "@a.md\n")
    _write(tmp_path, "a.md", "@b.md\n")
    _write(tmp_path, "b.md", "@a.md\n")
    assert mc.discover_imports(tmp_path) == ["a.md", "b.md"]


def test_an_unresolvable_import_is_returned_not_dropped(tmp_path):
    """A blind spot is the failure this whole script exists to prevent."""
    _write(tmp_path, "CLAUDE.md", "@gone.md\n")
    assert mc.discover_imports(tmp_path) == ["gone.md"]


def test_a_repeated_import_appears_once(tmp_path):
    _write(tmp_path, "CLAUDE.md", "@a.md\n@a.md\n")
    _write(tmp_path, "a.md", "x\n")
    assert mc.discover_imports(tmp_path) == ["a.md"]


def test_no_claude_md_yields_no_imports(tmp_path):
    assert mc.discover_imports(tmp_path) == []


# ----------------------------------------------- discover_standing_orders --

def test_only_scope_always_orders_are_collected(tree):
    _write(
        tree,
        "protocols/standing-orders/sometimes.md",
        _order("sometimes", scope="instance"),
    )
    assert mc.discover_standing_orders(tree) == [
        "protocols/standing-orders/task-sync.md"
    ]


def test_readme_and_underscore_files_are_not_orders(tree):
    found = mc.discover_standing_orders(tree)
    assert not any("README" in p or "_template" in p for p in found)


def test_an_on_trigger_order_is_not_part_of_the_always_on_set(tree):
    """It is fetched by its vocabulary, so counting it would overstate the
    budget and hide the very saving the contract buys."""
    _write(
        tree,
        "protocols/standing-orders/deferred.md",
        _order("deferred", load="on-trigger"),
    )
    assert not any(
        "deferred" in p for p in mc.discover_standing_orders(tree)
    )


def test_the_report_says_what_was_deferred_rather_than_dropping_it(tree):
    """Silence about a deferred body reads as a file that vanished."""
    out = mc.render_report([], "bytes", 2.4, deferred=[("a.md", 10), ("b.md", 20)])
    assert "2" in out
    assert "trigger" in out.lower()


def test_user_tier_orders_are_collected_and_sorted(tree):
    _write(tree, "protocols/standing-orders/user/zeta.md", _order("zeta"))
    _write(tree, "protocols/standing-orders/user/alpha.md", _order("alpha"))
    found = mc.discover_standing_orders(tree)
    assert found == sorted(found)
    assert "protocols/standing-orders/user/alpha.md" in found
    assert "protocols/standing-orders/user/zeta.md" in found


# ------------------------------------------------------------ count_tokens --

def test_bytes_method_estimates_and_reports_itself():
    n, used = mc.count_tokens("x" * 240, "bytes", 2.4, "claude-opus-5")
    assert n == 100
    assert used == "bytes"


def test_api_that_cannot_run_never_reports_itself_as_exact(monkeypatch):
    """An estimate wearing the label `api` is the one outcome forbidden here."""
    monkeypatch.setattr(mc, "_api_token_count", lambda text, model: None)
    n, used = mc.count_tokens("x" * 240, "api", 2.4, "claude-opus-5")
    assert used == "bytes"
    assert n == 100


# --------------------------------------------------------------- the rows --

def test_a_file_under_its_cap_is_ok(tree):
    rows = mc.collect_rows(tree, mc.load_budget(tree), "bytes")
    row = next(r for r in rows if r["path"] == "AGENTS.md")
    assert row["state"] == "ok"
    assert row["bytes"] == 500


def test_a_file_over_its_cap_is_over(tree):
    (tree / "AGENTS.md").write_text("A" * 5000, encoding="utf-8")
    rows = mc.collect_rows(tree, mc.load_budget(tree), "bytes")
    row = next(r for r in rows if r["path"] == "AGENTS.md")
    assert row["state"] == "over"


def test_a_declared_item_without_a_cap_is_uncapped(tree):
    budget = mc.load_budget(tree)
    budget["items"]["AGENTS.md"].pop("max_bytes")
    rows = mc.collect_rows(tree, budget, "bytes")
    row = next(r for r in rows if r["path"] == "AGENTS.md")
    assert row["state"] == "uncapped"


def test_an_always_on_file_missing_from_the_budget_is_undeclared(tree):
    """The meter must not go blind when the tree grows."""
    _write(tree, "protocols/standing-orders/newcomer.md", _order("newcomer"))
    rows = mc.collect_rows(tree, mc.load_budget(tree), "bytes")
    row = next(r for r in rows if r["path"].endswith("newcomer.md"))
    assert row["state"] == "undeclared"


def test_an_optional_item_that_is_absent_is_not_a_failure(tree):
    rows = mc.collect_rows(tree, mc.load_budget(tree), "bytes")
    row = next(r for r in rows if r["path"] == "ecosystem.yaml")
    assert row["state"] == "absent"


def test_a_required_item_that_is_absent_is_missing(tree):
    (tree / "work" / "board.md").unlink()
    rows = mc.collect_rows(tree, mc.load_budget(tree), "bytes")
    row = next(r for r in rows if r["path"] == "work/board.md")
    assert row["state"] == "missing"


def test_the_user_overlay_replaces_an_item_by_key(tree):
    _write(
        tree,
        "context-budget.user.yaml",
        "items:\n  AGENTS.md:\n    max_bytes: 100\n",
    )
    budget = mc.load_budget(tree)
    assert budget["items"]["AGENTS.md"]["max_bytes"] == 100


def test_a_command_item_measures_what_the_command_prints(tree):
    """The payload is the output, not a file, because that is what loads."""
    _write(
        tree,
        "context-budget.user.yaml",
        'items:\n  "cmd:python3 scripts/echo.py":\n    max_bytes: 1000\n',
    )
    _write(tree, "scripts/echo.py", "print('x' * 41)\n")
    rows = mc.collect_rows(tree, mc.load_budget(tree), "bytes")
    row = next(r for r in rows if r["path"].startswith("cmd:"))
    assert row["bytes"] == 42  # 41 x plus the newline
    assert row["state"] == "ok"


def test_a_command_item_over_its_cap_is_over(tree):
    _write(
        tree,
        "context-budget.user.yaml",
        'items:\n  "cmd:python3 scripts/echo.py":\n    max_bytes: 10\n',
    )
    _write(tree, "scripts/echo.py", "print('x' * 41)\n")
    rows = mc.collect_rows(tree, mc.load_budget(tree), "bytes")
    row = next(r for r in rows if r["path"].startswith("cmd:"))
    assert row["state"] == "over"


def test_a_command_outside_the_allowlist_is_refused(tree):
    """A budget file is reviewed, but it is still config. Config that can run
    anything is not the file anybody reviewed it as."""
    _write(
        tree,
        "context-budget.user.yaml",
        'items:\n  "cmd:rm -rf /":\n    max_bytes: 10\n',
    )
    with pytest.raises(SystemExit):
        mc.collect_rows(tree, mc.load_budget(tree), "bytes")


def test_a_command_that_fails_is_a_finding_not_a_zero(tree):
    """A command that cannot run loads nothing, and nothing measured as zero
    reads exactly like a payload that shrank to nothing."""
    _write(
        tree,
        "context-budget.user.yaml",
        'items:\n  "cmd:python3 scripts/boom.py":\n    max_bytes: 1000\n',
    )
    _write(tree, "scripts/boom.py", "import sys; sys.exit(3)\n")
    rows = mc.collect_rows(tree, mc.load_budget(tree), "bytes")
    row = next(r for r in rows if r["path"].startswith("cmd:"))
    assert row["state"] == "missing"


def test_init_writes_the_undeclared_items_uncapped(tree):
    """CORE cannot know an instance's files. Failing on day one with no way
    forward is a gate nobody adopts."""
    _write(tree, "protocols/standing-orders/mine.md", _order("mine"))
    assert mc.main(["--repo-root", str(tree), "--method", "bytes"]) == 1
    mc.main(["--repo-root", str(tree), "--init"])
    written = (tree / "context-budget.user.yaml").read_text(encoding="utf-8")
    assert "protocols/standing-orders/mine.md" in written
    # No ITEM carries a cap. The header comment names the field on purpose,
    # since telling the reader where the value is, is the point of the file.
    assert "max_bytes" not in written.split("items:", 1)[1]


def test_after_init_the_gate_passes(tree):
    _write(tree, "protocols/standing-orders/mine.md", _order("mine"))
    mc.main(["--repo-root", str(tree), "--init"])
    assert mc.main(["--repo-root", str(tree), "--method", "bytes"]) == 0


def test_init_refuses_to_clobber_a_hand_tuned_user_budget(tree):
    _write(tree, "context-budget.user.yaml", "items:\n  AGENTS.md:\n    max_bytes: 1\n")
    with pytest.raises(SystemExit):
        mc.main(["--repo-root", str(tree), "--init"])


def test_init_leaves_an_already_declared_item_alone(tree):
    mc.main(["--repo-root", str(tree), "--init"])
    written = (tree / "context-budget.user.yaml").read_text(encoding="utf-8")
    assert "AGENTS.md" not in written


def test_a_missing_core_budget_is_a_hard_error(tmp_path):
    with pytest.raises(SystemExit):
        mc.load_budget(tmp_path)


# ------------------------------------------------------------- the report --

def test_the_report_is_byte_identical_across_runs(tree):
    budget = mc.load_budget(tree)
    a = mc.render_report(mc.collect_rows(tree, budget, "bytes"), "bytes", 2.4)
    b = mc.render_report(mc.collect_rows(tree, budget, "bytes"), "bytes", 2.4)
    assert a == b


def test_the_report_names_the_method_and_flags_an_estimate(tree):
    budget = mc.load_budget(tree)
    out = mc.render_report(mc.collect_rows(tree, budget, "bytes"), "bytes", 2.4)
    assert "bytes" in out
    assert "estimate" in out.lower()
    assert "2.4" in out


# --------------------------------------------------------------- the gate --

def test_a_clean_tree_exits_zero(tree):
    assert mc.main(["--repo-root", str(tree), "--method", "bytes"]) == 0


def test_an_over_cap_file_trips_the_gate(tree):
    (tree / "AGENTS.md").write_text("A" * 5000, encoding="utf-8")
    assert mc.main(["--repo-root", str(tree), "--method", "bytes"]) == 1


def test_an_undeclared_always_on_file_trips_the_gate(tree):
    _write(tree, "protocols/standing-orders/newcomer.md", _order("newcomer"))
    assert mc.main(["--repo-root", str(tree), "--method", "bytes"]) == 1


def test_a_missing_required_file_trips_the_gate(tree):
    (tree / "work" / "board.md").unlink()
    assert mc.main(["--repo-root", str(tree), "--method", "bytes"]) == 1


def test_uncapped_alone_does_not_trip_the_gate(tree):
    """Warn, never block: a new item must be addable in one line."""
    _write(
        tree,
        "context-budget.user.yaml",
        "items:\n  AGENTS.md: {}\n",
    )
    assert mc.main(["--repo-root", str(tree), "--method", "bytes"]) == 0


# ------------------------------------------------------- indexed sources --
#
# An item may declare a `card:`. The session then loads the card, not the file,
# so the meter has to measure the card — otherwise the gate guards a number
# nobody pays and reports red for content that never reaches a session.

REGISTRY = (
    "org: example-org\n"
    "\n"
    "customers:\n"
    "  one:\n"
    "    description: The first customer.\n"
    "    contact: someone@example.org\n"
    "    notes: a long block of detail nobody needs before the name comes up\n"
    "  two:\n"
    "    description: The second customer.\n"
    "    contact: other@example.org\n"
    "    notes: more detail of the same kind, equally unread until asked for\n"
)


def _declare_card(tree: Path, cap: str = "", keep_import: bool = False) -> Path:
    """Declare a card on `ecosystem.yaml`, and drop its `@`-import with it.

    A card replaces the import; it does not sit beside it. The fixture tree
    imports the registry, so a card test that left the import in place would
    be testing the contradiction below rather than an indexed source.
    """
    if not keep_import:
        entry = tree / "CLAUDE.md"
        entry.write_text(
            entry.read_text(encoding="utf-8").replace("@ecosystem.yaml\n", ""),
            encoding="utf-8",
        )
    budget = (tree / "context-budget.yaml").read_text(encoding="utf-8")
    budget = budget.replace(
        "  ecosystem.yaml:\n    optional: true\n",
        "  ecosystem.yaml:\n"
        "    optional: true\n"
        f"{cap}"
        "    card:\n"
        "      kind: index\n"
        "      keep: [org]\n"
        "      sections: [customers]\n",
    )
    (tree / "context-budget.yaml").write_text(budget, encoding="utf-8")
    return tree


def test_an_indexed_item_is_measured_by_its_card(tree):
    _write(tree, "ecosystem.yaml", REGISTRY)
    _declare_card(tree)
    rows = mc.collect_rows(tree, mc.load_budget(tree), "bytes")
    row = next(r for r in rows if r["path"] == "ecosystem.yaml")

    assert row["bytes"] < len(REGISTRY.encode("utf-8"))
    assert row["body_bytes"] == len(REGISTRY.encode("utf-8"))


def test_an_indexed_item_gates_on_the_card_and_not_the_file(tree):
    """The sharp case: a cap the FILE blows and the CARD clears.

    If this ever reads `over`, the meter is gating a number no session pays,
    and the first thing anybody would do about it is raise the cap — which
    would quietly undo the feature.
    """
    _write(tree, "ecosystem.yaml", REGISTRY)
    _declare_card(tree, cap="    max_bytes: 300\n")
    rows = mc.collect_rows(tree, mc.load_budget(tree), "bytes")
    row = next(r for r in rows if r["path"] == "ecosystem.yaml")

    assert len(REGISTRY.encode("utf-8")) > 300, "the fixture has to blow the cap"
    assert row["state"] == "ok"


def test_an_indexed_item_over_its_cap_is_still_over(tree):
    _write(tree, "ecosystem.yaml", REGISTRY)
    _declare_card(tree, cap="    max_bytes: 10\n")
    rows = mc.collect_rows(tree, mc.load_budget(tree), "bytes")

    assert next(r for r in rows if r["path"] == "ecosystem.yaml")["state"] == "over"


def test_the_report_names_what_an_indexed_source_defers(tree):
    """Same rule as a deferred order body: say it, or it reads as vanished."""
    _write(tree, "ecosystem.yaml", REGISTRY)
    _declare_card(tree)
    rows = mc.collect_rows(tree, mc.load_budget(tree), "bytes")
    report = mc.render_report(rows, "bytes", 2.4)

    assert "ecosystem.yaml" in report
    assert str(len(REGISTRY.encode("utf-8"))) in report
    assert "--get" in report


def test_an_indexed_item_that_is_absent_is_still_not_a_failure(tree):
    """A card declared over instance data absent from a fresh clone."""
    _declare_card(tree)
    rows = mc.collect_rows(tree, mc.load_budget(tree), "bytes")

    assert next(r for r in rows if r["path"] == "ecosystem.yaml")["state"] == "absent"


# A card is a claim that the session loads the card INSTEAD of the file. An
# `@`-import of the same file loads the file whole, every session, whatever the
# budget says. With both in place the meter used to measure the card and report
# green while the session paid for the full text: measured on a live instance,
# a 3 829 byte card stood in for a 24 369 byte import. That pair is neither an
# indexed source nor an imported one, so it gets its own failing state.


def test_a_card_on_an_imported_file_is_a_contradiction(tree):
    _write(tree, "ecosystem.yaml", REGISTRY)
    _declare_card(tree, keep_import=True)
    rows = mc.collect_rows(tree, mc.load_budget(tree), "bytes")
    row = next(r for r in rows if r["path"] == "ecosystem.yaml")

    assert row["state"] == "contradiction"


def test_a_contradiction_is_measured_by_the_full_text(tree):
    """The import is what loads, so the import is what gets counted."""
    _write(tree, "ecosystem.yaml", REGISTRY)
    _declare_card(tree, keep_import=True)
    rows = mc.collect_rows(tree, mc.load_budget(tree), "bytes")
    row = next(r for r in rows if r["path"] == "ecosystem.yaml")

    assert row["bytes"] == len(REGISTRY.encode("utf-8"))
    assert not row["body_bytes"], "a contradiction must not be reported as indexed"


def test_a_contradiction_fails_the_build(tree):
    _write(tree, "ecosystem.yaml", REGISTRY)
    _declare_card(tree, keep_import=True)
    assert mc.main(["--repo-root", str(tree), "--quiet"]) == 1


def test_a_contradiction_fails_even_when_the_full_text_fits_the_cap(tree):
    """The size is not the finding. The claim about what loads is."""
    _write(tree, "ecosystem.yaml", REGISTRY)
    _declare_card(tree, cap="    max_bytes: 100000\n", keep_import=True)
    assert mc.main(["--repo-root", str(tree), "--quiet"]) == 1


def test_a_contradiction_enters_the_surface_whole(tree):
    _write(tree, "ecosystem.yaml", REGISTRY)
    _declare_card(tree, keep_import=True)
    parts = mc.always_on_parts(tree, mc.load_budget(tree))
    assert parts["ecosystem.yaml"] == REGISTRY


def test_the_report_says_what_a_contradiction_is(tree):
    _write(tree, "ecosystem.yaml", REGISTRY)
    _declare_card(tree, keep_import=True)
    rows = mc.collect_rows(tree, mc.load_budget(tree), "bytes")
    report = mc.render_report(rows, "bytes", 2.4)
    assert "contradiction" in report
    assert "@`-import" in report or "@-import" in report


def test_a_card_on_a_file_imported_only_indirectly_is_a_contradiction(tree):
    """An import inside an imported file loads just the same."""
    _write(tree, "ecosystem.yaml", REGISTRY)
    _declare_card(tree)
    _write(tree, "AGENTS.md", "A" * 500 + "\n@ecosystem.yaml\n")
    rows = mc.collect_rows(tree, mc.load_budget(tree), "bytes")
    assert next(r for r in rows if r["path"] == "ecosystem.yaml")["state"] == "contradiction"


def test_init_writes_what_the_shipped_schema_requires(tree):
    """`--init` has to produce a file this repo's own schema accepts.

    It did not. The overlay was written with `items:` alone while
    `docs/schemas/context-budget.schema.yaml` requires `schema_version` as
    well, so `validate-bridge.py` rejected it — and nobody saw that for a day,
    because the file is gitignored by default and no validator ever reached it.
    It surfaced the moment one instance started tracking it.

    The required keys are read FROM the schema rather than listed here, so this
    cannot go stale the way the thing it is guarding did.
    """
    import yaml as _yaml

    mc.main(["--repo-root", str(tree), "--init"])
    written = _yaml.safe_load(
        (tree / "context-budget.user.yaml").read_text(encoding="utf-8")
    )
    schema = _yaml.safe_load(
        (Path(mc.__file__).resolve().parents[1]
         / "docs/schemas/context-budget.schema.yaml").read_text(encoding="utf-8")
    )

    for key in schema.get("required", []):
        assert key in written, f"--init omits {key!r}, which the schema requires"


# ---------------------------------------------------------------- listings --
#
# The third residency channel. `name` + `description` of every skill and every
# sub-agent is injected into EVERY session and every sub-agent dispatch, and
# nothing measured a byte of it. Found on a live instance: 111 skills, 73 400
# bytes, larger than every `@`-import in that tree combined.
#
# It is not dead weight either. 33 config-family paths were named ONLY in a
# skill description there, and one family was reachable exclusively through
# one, so `always_on_parts` has to carry it or the reachability contract calls
# a family unreachable that a session can in fact find.


def _skill(tree: Path, slug: str, description: str, name: str | None = None) -> None:
    front = f"name: {name or slug}\ndescription: {description}\n"
    _write(tree, f"skills/{slug}/SKILL.md", f"---\n{front}---\n\nbody\n")


def _declare_listing(tree: Path, key: str, body: str) -> None:
    budget = tree / "context-budget.yaml"
    budget.write_text(
        budget.read_text(encoding="utf-8") + f"  {key}:\n{body}", encoding="utf-8"
    )


@pytest.fixture
def listed(tree: Path) -> Path:
    _skill(tree, "remote", "Wake, reach and repair a machine in infra/remotes/.")
    _skill(tree, "channel", "Outbound transports declared in infra/channels/.")
    _write(tree, "skills/README.md", "not a skill\n")
    _write(
        tree,
        ".claude/agents/archivist.md",
        "---\nname: archivist\ndescription: Batches document intake.\n---\n\nbody\n",
    )
    return tree


def test_a_described_skill_becomes_one_line(listed):
    text = mc.render_listing(listed, "listing:skills")
    assert "**remote** — Wake, reach and repair a machine in infra/remotes/." in text


def test_a_skill_without_a_description_is_not_listed(listed):
    _write(listed, "skills/quiet/SKILL.md", "---\nname: quiet\n---\n\nbody\n")
    assert "quiet" not in mc.render_listing(listed, "listing:skills")


def test_a_file_without_frontmatter_is_skipped_not_fatal(listed):
    _write(listed, "skills/raw/SKILL.md", "no frontmatter here\n")
    text = mc.render_listing(listed, "listing:skills")
    assert "raw" not in text and "remote" in text


def test_a_folded_description_collapses_to_one_line(listed):
    _write(
        listed,
        "skills/folded/SKILL.md",
        "---\nname: folded\ndescription: >-\n  first line\n  second line\n---\n\nbody\n",
    )
    text = mc.render_listing(listed, "listing:skills")
    assert "**folded** — first line second line" in text
    # One entry, one line. A description that kept its newlines would make the
    # listing's line count a lie and hide a runaway entry in the middle of it.
    assert len([ln for ln in text.splitlines() if ln.startswith("- **")]) == 3


def test_the_name_falls_back_to_the_directory(listed):
    _write(listed, "skills/unnamed/SKILL.md", "---\ndescription: has no name key.\n---\n")
    assert "**unnamed** — has no name key." in mc.render_listing(listed, "listing:skills")


def test_an_absent_family_renders_none_not_empty(tree):
    # None and "" are different findings: a family nobody has yet, versus a
    # family whose every entry lost its description. Only the second is a bug.
    assert mc.render_listing(tree, "listing:skills") is None


def test_listings_are_discovered_from_the_tree(listed):
    assert mc.discover_listings(listed) == ["listing:agents", "listing:skills"]


def test_an_absent_family_is_not_discovered(tree):
    assert mc.discover_listings(tree) == []


def test_an_undeclared_listing_is_measured_and_flagged(listed):
    rows = {r["path"]: r for r in mc.collect_rows(listed, mc.load_budget(listed), "bytes")}
    assert rows["listing:skills"]["state"] == "undeclared"
    assert rows["listing:skills"]["bytes"] > 0


def test_a_declared_listing_gates_on_its_cap(listed):
    _declare_listing(listed, "listing:skills", "    source: listing\n    max_bytes: 10\n")
    rows = {r["path"]: r for r in mc.collect_rows(listed, mc.load_budget(listed), "bytes")}
    assert rows["listing:skills"]["state"] == "over"


def test_a_listing_within_its_cap_is_ok(listed):
    _declare_listing(listed, "listing:skills", "    source: listing\n    max_bytes: 5000\n")
    rows = {r["path"]: r for r in mc.collect_rows(listed, mc.load_budget(listed), "bytes")}
    assert rows["listing:skills"]["state"] == "ok"


def test_the_listing_is_part_of_the_always_on_surface(listed):
    # The reachability contract reads exactly this. A family named only in a
    # skill description is findable, and a surface that omits the listing would
    # report it unreachable.
    parts = mc.always_on_parts(listed, mc.load_budget(listed))
    assert "infra/channels/" in parts["listing:skills"]


def test_a_listing_row_carries_its_largest_entries(listed):
    _skill(listed, "huge", "H" * 400)
    rows = {r["path"]: r for r in mc.collect_rows(listed, mc.load_budget(listed), "bytes")}
    assert rows["listing:skills"]["largest"][0][0] == "huge"


def test_the_report_names_the_largest_entries(listed):
    _skill(listed, "huge", "H" * 400)
    rows = mc.collect_rows(listed, mc.load_budget(listed), "bytes")
    assert "huge" in mc.render_report(rows, "bytes", 2.4)


# ------------------------------------- skills the harness adds on its own --
#
# The harness lists more than this tree's skills/: the user-level skills in
# the config dir and the skills and commands of every ENABLED plugin. Measured
# on a live instance at 5 420 bytes on top of a listing already at its cap,
# counted nowhere. Where they live is read from the harness's own files
# (`CLAUDE_CONFIG_DIR` or ~/.claude, `plugins/installed_plugins.json`,
# `enabledPlugins` in settings), never a hardcoded install path, and a missing
# piece is simply nothing to count.


def _plugin(home: Path, key: str, skills=(), commands=(), scope="user", project=None):
    """Install a synthetic plugin under the isolated config dir."""
    name, _, market = key.partition("@")
    install = home / ".claude" / "plugins" / "cache" / market / name / "1.0.0"
    for slug, desc in skills:
        _write(install, f"skills/{slug}/SKILL.md", f"---\nname: {slug}\ndescription: {desc}\n---\n")
    for slug, desc in commands:
        _write(install, f"commands/{slug}.md", f"---\ndescription: {desc}\n---\nbody\n")
    registry = home / ".claude" / "plugins" / "installed_plugins.json"
    data = json.loads(registry.read_text()) if registry.is_file() else {"version": 2, "plugins": {}}
    entry = {"scope": scope, "installPath": str(install)}
    if project is not None:
        entry["projectPath"] = str(project)
    data["plugins"].setdefault(key, []).append(entry)
    registry.parent.mkdir(parents=True, exist_ok=True)
    registry.write_text(json.dumps(data))
    return install


def _enable(settings: Path, key: str, on: bool = True) -> None:
    data = json.loads(settings.read_text()) if settings.is_file() else {}
    data.setdefault("enabledPlugins", {})[key] = on
    settings.parent.mkdir(parents=True, exist_ok=True)
    settings.write_text(json.dumps(data))


def test_user_level_skills_join_the_listing(listed, _isolated_home):
    _write(_isolated_home, ".claude/skills/helper/SKILL.md", "---\nname: helper\ndescription: A user-level helper.\n---\n")
    assert "**helper** — A user-level helper." in mc.render_listing(listed, "listing:skills", include_harness=True)


def test_a_user_level_skill_shadows_the_project_skill_of_the_same_name(listed, _isolated_home):
    _write(_isolated_home, ".claude/skills/remote/SKILL.md", "---\nname: remote\ndescription: The user copy.\n---\n")
    text = mc.render_listing(listed, "listing:skills", include_harness=True)
    assert text.count("**remote**") == 1 and "The user copy." in text


def test_an_enabled_plugin_lists_its_skills_and_commands_namespaced(listed, _isolated_home):
    _plugin(_isolated_home, "kit@market", skills=[("draw", "Draws things.")], commands=[("help", "Explains kit.")])
    _enable(_isolated_home / ".claude" / "settings.json", "kit@market")
    text = mc.render_listing(listed, "listing:skills", include_harness=True)
    assert "**kit:draw** — Draws things." in text
    assert "**kit:help** — Explains kit." in text


def test_a_disabled_or_unlisted_plugin_is_not_counted(listed, _isolated_home):
    _plugin(_isolated_home, "off@market", skills=[("x", "Disabled one.")])
    _plugin(_isolated_home, "quiet@market", skills=[("y", "Never enabled.")])
    _enable(_isolated_home / ".claude" / "settings.json", "off@market", on=False)
    text = mc.render_listing(listed, "listing:skills", include_harness=True)
    assert "Disabled one." not in text and "Never enabled." not in text


def test_project_settings_enable_a_plugin_for_this_tree(listed, _isolated_home):
    _plugin(_isolated_home, "kit@market", skills=[("draw", "Draws things.")])
    _enable(_isolated_home / ".claude" / "settings.json", "kit@market", on=False)
    _enable(listed / ".claude" / "settings.local.json", "kit@market")
    assert "Draws things." in mc.render_listing(listed, "listing:skills", include_harness=True)


def test_a_local_install_counts_only_for_its_own_project(listed, _isolated_home, tmp_path):
    _plugin(_isolated_home, "mine@market", skills=[("m", "Mine here.")], scope="local", project=listed)
    _plugin(_isolated_home, "theirs@market", skills=[("t", "Elsewhere.")], scope="local", project=tmp_path / "other")
    _enable(_isolated_home / ".claude" / "settings.json", "mine@market")
    _enable(_isolated_home / ".claude" / "settings.json", "theirs@market")
    text = mc.render_listing(listed, "listing:skills", include_harness=True)
    assert "Mine here." in text and "Elsewhere." not in text


def test_the_config_dir_override_is_honoured(listed, tmp_path, monkeypatch):
    cfg = tmp_path / "cfg"
    _write(cfg, "skills/elsewhere/SKILL.md", "---\nname: elsewhere\ndescription: From the override.\n---\n")
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(cfg))
    assert "From the override." in mc.render_listing(listed, "listing:skills", include_harness=True)


def test_a_broken_plugin_registry_is_nothing_not_an_error(listed, _isolated_home):
    _write(_isolated_home, ".claude/plugins/installed_plugins.json", "{not json")
    _write(_isolated_home, ".claude/settings.json", "[]")
    assert "**remote**" in mc.render_listing(listed, "listing:skills", include_harness=True)


def test_harness_skills_never_enter_the_agents_listing(listed, _isolated_home):
    _write(_isolated_home, ".claude/skills/helper/SKILL.md", "---\nname: helper\ndescription: A user-level helper.\n---\n")
    assert "helper" not in mc.render_listing(listed, "listing:agents", include_harness=True)


def test_user_level_commands_join_the_listing(listed, _isolated_home):
    _write(_isolated_home, ".claude/commands/tidy.md", "---\ndescription: Tidies the tree.\n---\nbody\n")
    assert "**tidy** — Tidies the tree." in mc.render_listing(listed, "listing:skills", include_harness=True)


def test_a_plugin_manifest_can_point_at_its_own_skill_and_command_dirs(listed, _isolated_home):
    install = _plugin(_isolated_home, "kit@market")
    _write(install, "extra/paint/SKILL.md", "---\nname: paint\ndescription: Paints things.\n---\n")
    _write(install, "cmds/hint.md", "---\ndescription: Gives a hint.\n---\nbody\n")
    _write(install, ".claude-plugin/plugin.json", json.dumps({"name": "kit", "skills": "./extra", "commands": ["./cmds"]}))
    _enable(_isolated_home / ".claude" / "settings.json", "kit@market")
    text = mc.render_listing(listed, "listing:skills", include_harness=True)
    assert "**kit:paint** — Paints things." in text
    assert "**kit:hint** — Gives a hint." in text


def test_harness_skills_count_in_the_meter_row(listed, _isolated_home):
    before = {r["path"]: r for r in mc.collect_rows(listed, mc.load_budget(listed), "bytes")}
    _write(_isolated_home, ".claude/skills/helper/SKILL.md", "---\nname: helper\ndescription: A user-level helper.\n---\n")
    after = {r["path"]: r for r in mc.collect_rows(listed, mc.load_budget(listed), "bytes")}
    assert after["listing:skills"]["bytes"] > before["listing:skills"]["bytes"]


def test_harness_skills_stay_out_of_the_always_on_surface_the_guards_read(listed, _isolated_home):
    # check-reachability and check-object-grammar read always_on_parts. A
    # private plugin naming a family would make it reachable on one machine
    # and not in CI, so the guards see the tree's own listing only.
    plain = mc.always_on_parts(listed, mc.load_budget(listed))
    _write(_isolated_home, ".claude/skills/helper/SKILL.md", "---\nname: helper\ndescription: Names infra/secret-stores/.\n---\n")
    _plugin(_isolated_home, "kit@market", skills=[("draw", "Names workflow/meetings/.")])
    _enable(_isolated_home / ".claude" / "settings.json", "kit@market")
    assert mc.always_on_parts(listed, mc.load_budget(listed)) == plain


# ------------------------------------- one definition of the always-on surface --
#
# `always_on_parts` re-read the raw file for a `card:`-indexed source while
# `collect_rows` measured the rendered card. Two definitions of always-on, which
# is precisely what this module's docstring says a second definition would cause:
# something claims residency in text no session ever loads.
#
# Measured on a live instance: check-reachability was crediting 25 365 bytes of
# registry body that Phase 1 never reads. The 26/26 headline survived only
# because no family happened to depend on that text — it held by luck, not by
# construction, which is the definition of a guard that is not doing its job.


def test_an_indexed_source_enters_the_surface_as_its_card(tree):
    _declare_card(tree)
    # The description IS the card label, so the needle has to be a field the
    # card never carries: the body detail that only `--get` reaches.
    _write(
        tree,
        "ecosystem.yaml",
        "org: acme\ncustomers:\n  one:\n    description: a label\n    secret_detail: only in the body\n",
    )
    parts = mc.always_on_parts(tree, mc.load_budget(tree))
    assert "only in the body" not in parts["ecosystem.yaml"]
    assert "**one** — a label" in parts["ecosystem.yaml"]


def test_the_surface_and_the_gate_agree_byte_for_byte(tree):
    _declare_card(tree)
    _write(tree, "ecosystem.yaml", "org: acme\ncustomers:\n  one:\n    description: body text\n")
    budget = mc.load_budget(tree)
    parts = mc.always_on_parts(tree, budget)
    rows = {r["path"]: r for r in mc.collect_rows(tree, budget, "bytes")}
    assert len(parts["ecosystem.yaml"].encode("utf-8")) == rows["ecosystem.yaml"]["bytes"]


def test_an_undeclared_source_still_enters_whole(tree):
    # Fail-open: no card means the file stays always-on in full, and the surface
    # has to say so or the two halves disagree in the other direction.
    _write(tree, "ecosystem.yaml", "alpha: 1\nbeta: 2\n")
    parts = mc.always_on_parts(tree, mc.load_budget(tree))
    assert parts["ecosystem.yaml"] == "alpha: 1\nbeta: 2\n"


# ------------------------------------------- --init --force must not destroy --
#
# `--init` writes the UNDECLARED items. With `--force` on a file that already
# declares things, those items are by definition no longer undeclared — so the
# rewrite wrote their COMPLEMENT and deleted every declaration it found.
#
# Measured against a copy of a live instance's file: 162 lines / 8 380 bytes /
# 13 declarations became 15 lines / 629 bytes / 0 declarations. Every cap gone,
# and 147 lines of German prose explaining WHY each cap has its number — the
# part nobody can reconstruct. One command, no confirmation, no backup.
#
# `--force` now means "add what is missing", never "replace with the
# complement". That is what the docstring always said it was for.


def test_force_keeps_every_existing_declaration(tree):
    _write(
        tree,
        "context-budget.user.yaml",
        "schema_version: 1\nitems:\n"
        '  "AGENTS.md":\n'
        "    max_bytes: 999\n"
        "    note: the reasoning nobody can reconstruct\n",
    )
    mc.write_user_budget(tree, mc.collect_rows(tree, mc.load_budget(tree), "bytes"), force=True)
    body = (tree / "context-budget.user.yaml").read_text(encoding="utf-8")
    assert "max_bytes: 999" in body
    assert "the reasoning nobody can reconstruct" in body


def test_force_appends_only_what_is_undeclared(tree):
    _write(tree, "context-budget.user.yaml", 'schema_version: 1\nitems:\n  "AGENTS.md": {}\n')
    _write(tree, "brandnew.md", "x" * 10)
    _declare_import(tree, "brandnew.md")
    mc.write_user_budget(tree, mc.collect_rows(tree, mc.load_budget(tree), "bytes"), force=True)
    body = (tree / "context-budget.user.yaml").read_text(encoding="utf-8")
    assert body.count('"AGENTS.md"') == 1, "an existing declaration was duplicated"
    assert "brandnew.md" in body


def test_force_changes_nothing_when_all_is_declared(tree):
    _write(tree, "context-budget.user.yaml", 'schema_version: 1\nitems:\n  "AGENTS.md": {}\n')
    before = (tree / "context-budget.user.yaml").read_text(encoding="utf-8")
    rows = [r for r in mc.collect_rows(tree, mc.load_budget(tree), "bytes") if r["state"] != "undeclared"]
    mc.write_user_budget(tree, rows, force=True)
    assert (tree / "context-budget.user.yaml").read_text(encoding="utf-8") == before


def test_a_fresh_file_is_still_written_whole(tree):
    rows = mc.collect_rows(tree, mc.load_budget(tree), "bytes")
    mc.write_user_budget(tree, rows, force=False)
    body = (tree / "context-budget.user.yaml").read_text(encoding="utf-8")
    assert "schema_version: 1" in body and "items:" in body


def _declare_import(tree, rel):
    entry = tree / "CLAUDE.md"
    entry.write_text(entry.read_text(encoding="utf-8") + f"\n@{rel}\n", encoding="utf-8")


# ------------------------------------------------- the harness memory index --
#
# Claude Code loads the auto-memory index (`MEMORY.md` in the configured memory
# directory) into every main session, before the first answer, and nothing
# measured it. Measured on a live instance: 20 227 bytes, uncounted. It is not
# a file CLAUDE.md names, so no import discovery can find it; the directory is
# resolved the way the harness resolves it, by `scripts/memory-location.py`,
# rather than by a second copy of that precedence here.

HARNESS_KEY = "harness:memory-index"


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path, monkeypatch):
    """No test may read the developer's real ~/.claude."""
    home = tmp_path / "_home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.delenv("CLAUDE_CONFIG_DIR", raising=False)
    return home


def _legacy_index(tree: Path, home: Path, text: str) -> Path:
    encoded = str(tree.resolve()).replace("/", "-")
    return _write(home, f".claude/projects/{encoded}/memory/MEMORY.md", text)


def _declare_harness(tree: Path, body: str = "    optional: true\n") -> None:
    budget = tree / "context-budget.yaml"
    budget.write_text(
        budget.read_text(encoding="utf-8") + f'  "{HARNESS_KEY}":\n    source: harness\n{body}',
        encoding="utf-8",
    )


def _row(tree: Path, key: str):
    rows = mc.collect_rows(tree, mc.load_budget(tree), "bytes")
    return next((r for r in rows if r["path"] == key), None)


def test_the_harness_memory_index_is_counted(tree, _isolated_home):
    _legacy_index(tree, _isolated_home, "- [a](feedback_a.md): hook\n" * 10)
    _declare_harness(tree)
    row = _row(tree, HARNESS_KEY)

    assert row is not None
    assert row["source"] == "harness"
    assert row["bytes"] == len(("- [a](feedback_a.md): hook\n" * 10).encode("utf-8"))
    assert row["state"] == "uncapped"


def test_the_harness_index_follows_auto_memory_directory(tree, _isolated_home):
    """The configured directory, not a hardcoded one."""
    _write(tree, "work/memory/MEMORY.md", "M" * 77)
    _legacy_index(tree, _isolated_home, "L" * 5)
    _write(
        tree,
        ".claude/settings.local.json",
        '{"autoMemoryDirectory": "%s"}' % (tree.resolve() / "work" / "memory"),
    )
    _declare_harness(tree)
    assert _row(tree, HARNESS_KEY)["bytes"] == 77


def test_a_missing_harness_index_is_no_failure(tree):
    _declare_harness(tree)
    assert _row(tree, HARNESS_KEY)["state"] == "absent"
    assert mc.main(["--repo-root", str(tree), "--quiet"]) == 0


def test_a_missing_and_undeclared_harness_index_adds_no_row(tree):
    assert _row(tree, HARNESS_KEY) is None
    assert mc.main(["--repo-root", str(tree), "--quiet"]) == 0


def test_an_existing_harness_index_is_discovered_without_a_declaration(tree, _isolated_home):
    """Discovered, never merely declared, same as every other channel."""
    _legacy_index(tree, _isolated_home, "x\n")
    assert _row(tree, HARNESS_KEY)["state"] == "undeclared"


def test_a_harness_index_over_its_cap_fails(tree, _isolated_home):
    _legacy_index(tree, _isolated_home, "x" * 200)
    _declare_harness(tree, "    optional: true\n    max_bytes: 100\n")
    assert _row(tree, HARNESS_KEY)["state"] == "over"
    assert mc.main(["--repo-root", str(tree), "--quiet"]) == 1


def test_auto_memory_off_means_nothing_is_loaded(tree, _isolated_home):
    _legacy_index(tree, _isolated_home, "x" * 200)
    _write(tree, ".claude/settings.json", '{"autoMemoryEnabled": false}')
    _declare_harness(tree)
    assert _row(tree, HARNESS_KEY)["state"] == "absent"


def test_the_harness_index_enters_the_surface(tree, _isolated_home):
    _legacy_index(tree, _isolated_home, "see infra/example-family/\n")
    _declare_harness(tree)
    parts = mc.always_on_parts(tree, mc.load_budget(tree))
    assert parts[HARNESS_KEY] == "see infra/example-family/\n"


def test_command_items_run_as_a_claude_code_session(tree, monkeypatch):
    """The meter enters through CLAUDE.md, so it measures a Claude Code session.

    `memory-location.py index` prints the whole index outside Claude Code and
    one line inside it, because there the harness already loaded the file.
    Run from a plain terminal or CI, the command row would count the same
    index the harness row counts, twice.
    """
    monkeypatch.delenv("CLAUDECODE", raising=False)
    _write(
        tree,
        "scripts/env_probe.py",
        "import os\nprint(os.environ.get('CLAUDECODE', 'unset'))\n",
    )
    key = "cmd:python3 scripts/env_probe.py"
    budget = tree / "context-budget.yaml"
    budget.write_text(
        budget.read_text(encoding="utf-8") + f'  "{key}":\n    source: phase1\n',
        encoding="utf-8",
    )
    parts = mc.always_on_parts(tree, mc.load_budget(tree))
    assert parts[key].strip() == "1"


# ---------------------------------------------- review follow-up: no quiet green --
#
# `enforce: advisory` exempts an item from the exit code because its SIZE is
# driven by ongoing work. A contradiction is not a size: it is a false claim
# about what loads. The same holds for a harness lookup that broke. Neither may
# hide behind advisory.


def test_a_contradiction_fails_even_when_the_item_is_advisory(tree):
    _write(tree, "ecosystem.yaml", REGISTRY)
    _declare_card(tree, cap="    enforce: advisory\n", keep_import=True)
    row = _row(tree, "ecosystem.yaml")
    assert row["state"] == "contradiction"
    assert not row["advisory"]
    assert mc.main(["--repo-root", str(tree), "--quiet"]) == 1


# A lookup that raises is not "no index". Reported as absent, a renamed or
# broken memory-location.py turned the harness row green, the false green this
# meter exists to remove.


def _broken_memory_location(monkeypatch):
    def boom():
        raise AttributeError("module 'memory_location' has no attribute 'resolve_memory_dir'")

    monkeypatch.setattr(mc, "_memory_location", boom)


def test_a_broken_harness_lookup_is_an_error_and_fails(tree, monkeypatch):
    _declare_harness(tree)
    _broken_memory_location(monkeypatch)
    row = _row(tree, HARNESS_KEY)
    assert row["state"] == "error"
    assert "resolve_memory_dir" in row["error"]
    assert mc.main(["--repo-root", str(tree), "--quiet"]) == 1


def test_a_broken_harness_lookup_fails_even_when_undeclared(tree, monkeypatch):
    """An undeclared row must not vanish just because the lookup broke."""
    _broken_memory_location(monkeypatch)
    assert _row(tree, HARNESS_KEY)["state"] == "error"


def test_a_harness_error_fails_even_when_advisory(tree, monkeypatch):
    _declare_harness(tree, "    optional: true\n    enforce: advisory\n")
    _broken_memory_location(monkeypatch)
    assert mc.main(["--repo-root", str(tree), "--quiet"]) == 1


def test_the_report_names_a_harness_error(tree, monkeypatch):
    _declare_harness(tree)
    _broken_memory_location(monkeypatch)
    rows = mc.collect_rows(tree, mc.load_budget(tree), "bytes")
    report = mc.render_report(rows, "bytes", 2.4)
    assert "resolve_memory_dir" in report


def test_the_memory_location_interface_the_meter_uses_exists():
    """Pins the coupling: the meter calls these, so a rename has to fail here."""
    ml = mc._memory_location()
    for name in ("repo_root_for", "resolve_memory_dir", "_first_setting"):
        assert callable(getattr(ml, name)), name
    assert isinstance(ml.LOAD_LIMIT_LINES, int)
    assert isinstance(ml.LOAD_LIMIT_BYTES, int)


def test_auto_memory_disabled_by_env_means_nothing_is_loaded(tree, _isolated_home, monkeypatch):
    """Same switch the harness honours, and `memory-location.py` with it."""
    _legacy_index(tree, _isolated_home, "x" * 200)
    _declare_harness(tree)
    monkeypatch.setenv("CLAUDE_CODE_DISABLE_AUTO_MEMORY", "1")
    assert _row(tree, HARNESS_KEY)["state"] == "absent"


def test_command_items_keep_the_auto_memory_switch(tree, monkeypatch):
    """With auto memory off the harness row is empty, so the command row has to
    see the switch too and print the index itself: counted once, not zero times."""
    monkeypatch.setenv("CLAUDE_CODE_DISABLE_AUTO_MEMORY", "1")
    _write(
        tree,
        "scripts/env_probe.py",
        "import os\nprint(os.environ.get('CLAUDE_CODE_DISABLE_AUTO_MEMORY', 'unset'))\n",
    )
    key = "cmd:python3 scripts/env_probe.py"
    budget = tree / "context-budget.yaml"
    budget.write_text(
        budget.read_text(encoding="utf-8") + f'  "{key}":\n    source: phase1\n',
        encoding="utf-8",
    )
    parts = mc.always_on_parts(tree, mc.load_budget(tree))
    assert parts[key].strip() == "1"


def test_an_oversized_harness_index_counts_only_what_the_harness_loads(tree, _isolated_home):
    """The harness truncates MEMORY.md at its load limit. The tail is not in the
    session through this channel (Phase 1 then prints it whole, counted there)."""
    ml = mc._memory_location()
    line = "- [a](feedback_a.md): hook\n"
    _legacy_index(tree, _isolated_home, line * (ml.LOAD_LIMIT_LINES + 50))
    _declare_harness(tree)
    assert _row(tree, HARNESS_KEY)["bytes"] == len(line) * ml.LOAD_LIMIT_LINES


def test_an_oversized_harness_index_is_cut_at_the_byte_limit(tree, _isolated_home):
    ml = mc._memory_location()
    _legacy_index(tree, _isolated_home, "y" * (ml.LOAD_LIMIT_BYTES + 999))
    _declare_harness(tree)
    assert _row(tree, HARNESS_KEY)["bytes"] == ml.LOAD_LIMIT_BYTES


def test_an_oversized_harness_index_still_fails(tree, _isolated_home):
    """Counting only the loaded part must not hide the defect: past the load
    limit the tail is silently dropped, so the row is `over` and names the
    full size, whatever the declared cap."""
    ml = mc._memory_location()
    _legacy_index(tree, _isolated_home, "y" * (ml.LOAD_LIMIT_BYTES + 999))
    _declare_harness(tree, "    optional: true\n    max_bytes: 999999\n")
    row = _row(tree, HARNESS_KEY)
    assert row["state"] == "over"
    assert row["truncated_from"] == ml.LOAD_LIMIT_BYTES + 999
    assert mc.main(["--repo-root", str(tree), "--quiet"]) == 1
    report = mc.render_report(mc.collect_rows(tree, mc.load_budget(tree), "bytes"), "bytes", 2.4)
    assert "load limit" in report
