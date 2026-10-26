#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Pytest suite for scripts/standing-orders.py.

CONTRACT, this file is the authoritative spec for that surface.

WHY THIS EXISTS. Skills already do progressive disclosure: the name and the
description sit in context permanently, the body arrives on invocation. Standing
orders never got the same treatment. Every order carrying `scope: always` is
read in full at session start and matched against every sub-agent dispatch, so
an advisory order that fires twice a month is paid on every turn and again on
every fan-out. This adds the missing half of the skill contract to orders.

    THE FRONTMATTER GAINS THREE FIELDS

        load      eager | on-trigger      default: eager
        triggers  the vocabulary that fetches the body
        summary   the one line that stays in context

    `load` DEFAULTS TO EAGER, and that direction is the whole safety argument.
    A fork that has never heard of the field keeps every order it has and
    loses nothing; it simply saves nothing either. Fail-closed would mean the
    silent loss of a guardrail, which is the failure this repo spends most of
    its test surface preventing.

    load_order(path) -> dict
        Frontmatter plus the derived load policy, with `path` attached.

    collect_orders(repo_root) -> list[dict]
        Every `protocols/standing-orders/**/*.md` carrying `scope: always`,
        sorted by path. `README.md` and `_`-prefixed files are not orders.

    check_orders(orders) -> list[str]
        Violations, empty when the contract holds:
          - `on-trigger` with no non-empty `triggers`  -> UNREACHABLE
          - `on-trigger` with no `summary`             -> INVISIBLE
          - a `summary` longer than SUMMARY_MAX_CHARS  -> the index is always-on
          - an unknown `load` value

        The first two are the point. An order that loads on a trigger nobody
        can say, or that never announces itself in the index, is present in the
        tree and absent from every session. It reads as enforced and is not.

    render_index(orders) -> str
        The always-on surface after this change: one line per order carrying
        its name, its trigger vocabulary and its summary. Deterministic.
        Eager orders are marked as already loaded so a reader does not fetch a
        body it is holding.

    eager_paths(orders) -> list[str]
        The bodies Phase 1 still reads in full.

    main(argv) -> int
        `--check` validates the contract, `--index` prints the index.

EVERY GATE HAS A FIXTURE THAT TRIPS IT.
"""

import importlib.util
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
SCRIPT = REPO_ROOT / "scripts" / "standing-orders.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("standing_orders", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["standing_orders"] = mod
    spec.loader.exec_module(mod)
    return mod


so = _load_module()


# --------------------------------------------------------------- fixtures --

def _order(root: Path, rel: str, **fm) -> Path:
    front = {
        "name": Path(rel).stem,
        "scope": "always",
        "enforcement": "advisory",
        "applies_to": [],
    }
    front.update(fm)
    lines = ["---"]
    for key, value in front.items():
        if value is None:
            continue
        if isinstance(value, list):
            rendered = "[" + ", ".join(str(v) for v in value) + "]"
        else:
            rendered = str(value)
        lines.append(f"{key}: {rendered}")
    lines += ["---", "", f"# {front['name']}", "", "body", ""]
    path = root / "protocols" / "standing-orders" / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines), encoding="utf-8")
    return path


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    _order(tmp_path, "always-on.md")  # no `load:` at all
    _order(
        tmp_path,
        "on-demand.md",
        load="on-trigger",
        triggers=["close a task", "STATUS.md"],
        summary="How a task closes and what it syncs.",
    )
    _order(tmp_path, "README.md", scope="always")
    _order(tmp_path, "_template.md", scope="always")
    _order(tmp_path, "elsewhere.md", scope="per-repo")
    return tmp_path


# ------------------------------------------------------------ the default --

def test_load_defaults_to_eager_when_the_field_is_absent(tree):
    """A fork that never heard of the field keeps every order it has."""
    order = so.load_order(tree / "protocols/standing-orders/always-on.md")
    assert order["load"] == "eager"


def test_an_explicit_on_trigger_is_read_as_written(tree):
    order = so.load_order(tree / "protocols/standing-orders/on-demand.md")
    assert order["load"] == "on-trigger"
    assert order["triggers"] == ["close a task", "STATUS.md"]


# ------------------------------------------------------------ what counts --

def test_readme_and_underscore_files_are_not_orders(tree):
    paths = [o["path"] for o in so.collect_orders(tree)]
    assert not any("README" in p or "_template" in p for p in paths)


def test_only_scope_always_is_collected(tree):
    paths = [o["path"] for o in so.collect_orders(tree)]
    assert not any("elsewhere" in p for p in paths)


def test_user_tier_orders_are_collected_and_sorted(tree):
    _order(tree, "user/zeta.md")
    _order(tree, "user/alpha.md")
    paths = [o["path"] for o in so.collect_orders(tree)]
    assert paths == sorted(paths)
    assert any(p.endswith("user/alpha.md") for p in paths)


# ------------------------------------------------------------ the checks --

def test_a_clean_tree_has_no_violations(tree):
    assert so.check_orders(so.collect_orders(tree)) == []


def test_on_trigger_without_triggers_is_unreachable(tree):
    """An order nobody can say the trigger for never loads. It reads as
    enforced in the tree and is absent from every session."""
    _order(tree, "mute.md", load="on-trigger", summary="x")
    violations = so.check_orders(so.collect_orders(tree))
    assert any("mute.md" in v for v in violations)
    assert any("trigger" in v.lower() for v in violations)


def test_on_trigger_with_empty_triggers_is_unreachable(tree):
    _order(tree, "mute.md", load="on-trigger", triggers=[], summary="x")
    assert any("mute.md" in v for v in so.check_orders(so.collect_orders(tree)))


def test_on_trigger_without_a_summary_is_invisible(tree):
    """Nothing announces it in the index, so nothing ever asks for it."""
    _order(tree, "silent.md", load="on-trigger", triggers=["a"])
    violations = so.check_orders(so.collect_orders(tree))
    assert any("silent.md" in v for v in violations)
    assert any("summary" in v.lower() for v in violations)


def test_an_over_long_summary_is_a_violation(tree):
    _order(
        tree,
        "verbose.md",
        load="on-trigger",
        triggers=["a"],
        summary="x" * (so.SUMMARY_MAX_CHARS + 1),
    )
    assert any("verbose.md" in v for v in so.check_orders(so.collect_orders(tree)))


def test_an_unknown_load_value_is_a_violation(tree):
    _order(tree, "typo.md", load="lazy")
    assert any("typo.md" in v for v in so.check_orders(so.collect_orders(tree)))


def test_an_eager_order_needs_no_triggers(tree):
    """Triggers are what fetches a body. An eager body is already there."""
    _order(tree, "plain.md", load="eager")
    assert so.check_orders(so.collect_orders(tree)) == []


# ------------------------------------------------------------- the index --

def test_the_index_lists_every_collected_order(tree):
    orders = so.collect_orders(tree)
    index = so.render_index(orders)
    for order in orders:
        assert order["name"] in index


def test_the_index_is_byte_identical_across_runs(tree):
    orders = so.collect_orders(tree)
    assert so.render_index(orders) == so.render_index(orders)


def test_the_index_carries_the_trigger_vocabulary(tree):
    index = so.render_index(so.collect_orders(tree))
    assert "STATUS.md" in index


def test_the_index_marks_which_bodies_are_already_loaded(tree):
    index = so.render_index(so.collect_orders(tree))
    assert "eager" in index.lower()


def test_eager_paths_are_exactly_the_eager_orders(tree):
    paths = so.eager_paths(so.collect_orders(tree))
    assert any(p.endswith("always-on.md") for p in paths)
    assert not any(p.endswith("on-demand.md") for p in paths)


# -------------------------------------------------------------- the gate --

def test_check_exits_zero_on_a_clean_tree(tree):
    assert so.main(["--check", "--repo-root", str(tree)]) == 0


def test_check_exits_one_on_an_unreachable_order(tree):
    _order(tree, "mute.md", load="on-trigger", summary="x")
    assert so.main(["--check", "--repo-root", str(tree)]) == 1


def test_index_exits_zero_and_prints(tree, capsys):
    assert so.main(["--index", "--repo-root", str(tree)]) == 0
    assert "on-demand" in capsys.readouterr().out


# ------------------------------------------------- unreadable frontmatter --
#
# A file under protocols/standing-orders/ IS an order by convention: that is
# exactly what collect_orders globs. When its frontmatter cannot be read,
# `_frontmatter` returns {} and `scope` becomes "", so `collect_orders` drops it
# for not being `scope: always` — the same silent exit an org-scoped order takes
# on purpose. The two are indistinguishable downstream, and only one of them is
# somebody's guardrail going missing.
#
# Found 2026-08-30 by an adversarial audit, with two fixtures that both declare
# `scope: always, enforcement: blocking`: one carrying a single comment line
# above the fence, one with an unquoted colon inside a value. Both vanished from
# --index, and --check reported "1 order(s) valid" and exited 0.
#
# The CI backstop could not have caught it either: it extracts frontmatter with
# awk (which reads both fixtures happily) and globs -maxdepth 1, so it never
# enters user/ — the one directory AGENTS.md designates for hand-written orders.


def _order_file(root, rel, body):
    p = root / "protocols" / "standing-orders" / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    return p


def test_a_fence_that_does_not_start_the_file_is_unreadable(tmp_path):
    _order_file(
        tmp_path,
        "user/leading-comment.md",
        "<!-- a note -->\n---\nname: x\nscope: always\nenforcement: blocking\n---\n# body\n",
    )
    assert so.unreadable_orders(tmp_path) == ["protocols/standing-orders/user/leading-comment.md"]


def test_frontmatter_that_does_not_parse_is_unreadable(tmp_path):
    _order_file(
        tmp_path,
        "user/typo.md",
        "---\nname: x\nscope: always\nsummary: Rule: never push a user branch\n---\n# body\n",
    )
    assert so.unreadable_orders(tmp_path) == ["protocols/standing-orders/user/typo.md"]


def test_a_well_formed_order_is_not_unreadable(tmp_path):
    _order_file(tmp_path, "user/fine.md", "---\nname: fine\nscope: always\n---\n# body\n")
    assert so.unreadable_orders(tmp_path) == []


def test_a_file_with_no_frontmatter_at_all_is_not_a_finding(tmp_path):
    # Prose that never claimed to be an order. Demanding frontmatter of it would
    # be a check about somebody's notes.
    _order_file(tmp_path, "user/notes.md", "# just prose\n\nno fence anywhere\n")
    assert so.unreadable_orders(tmp_path) == []


def test_readme_and_underscore_files_are_exempt(tmp_path):
    _order_file(tmp_path, "user/README.md", "<!-- x -->\n---\nbad: [\n---\n")
    _order_file(tmp_path, "user/_template.md", "<!-- x -->\n---\nbad: [\n---\n")
    assert so.unreadable_orders(tmp_path) == []


def test_the_check_reports_an_unreadable_order(tmp_path):
    _order_file(tmp_path, "user/typo.md", "---\nscope: always\nsummary: a: b\n---\n")
    violations = so.check_orders([], so.unreadable_orders(tmp_path))
    assert violations and "typo.md" in violations[0]


def test_the_check_is_silent_when_nothing_is_unreadable():
    assert so.check_orders([], []) == []


# ------------------------------------------------------ fires_unprompted --
#
# The reason an order stays eager used to live in a comment beside `load:`.
# One order lost it: it moved to on-trigger behind phrases that are only
# spoken once the question it answers has already been asked, and it loaded
# in none of the sessions it existed for, for two weeks, with every guard
# green. The trigger check passed, because the triggers were there. The
# field makes the reason checkable.

def test_fires_unprompted_is_read_and_defaults_to_false(tree):
    _order(tree, "duty.md", fires_unprompted="true")
    duty = so.load_order(tree / "protocols/standing-orders/duty.md")
    plain = so.load_order(tree / "protocols/standing-orders/always-on.md")
    assert duty["fires_unprompted"] is True
    assert plain["fires_unprompted"] is False


def test_an_order_that_fires_unprompted_may_not_wait_for_a_trigger(tree):
    _order(
        tree,
        "duty.md",
        fires_unprompted="true",
        load="on-trigger",
        triggers=["new task", "create a task"],
        summary="Decides whether work is a task.",
    )
    violations = so.check_orders(so.collect_orders(tree))
    assert any("duty.md" in v and "fires_unprompted" in v for v in violations)


def test_an_eager_order_that_fires_unprompted_is_fine(tree):
    _order(tree, "duty.md", fires_unprompted="true", load="eager")
    assert so.check_orders(so.collect_orders(tree)) == []


def test_a_non_boolean_fires_unprompted_is_a_violation(tree):
    _order(tree, "duty.md", fires_unprompted="sometimes")
    assert any("duty.md" in v for v in so.check_orders(so.collect_orders(tree)))


SHIPPED_UNPROMPTED = (
    "board-task-criteria.md",
    "document-work.md",
    "inbox.md",
    "security-baseline.md",
)


@pytest.mark.parametrize("name", SHIPPED_UNPROMPTED)
def test_the_shipped_orders_that_fire_unprompted_say_so(name):
    """Each of these carried the reason as a comment; the flag keeps it."""
    order = so.load_order(REPO_ROOT / "protocols" / "standing-orders" / name)
    assert order["fires_unprompted"] is True
    assert order["load"] == "eager"
