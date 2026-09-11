#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Pytest suite for scripts/context-index.py.

CONTRACT, this file is the authoritative spec for that surface.

WHY THIS EXISTS. `context-budget.yaml` measures what a session loads and holds
it to a ceiling. It cannot make anything smaller. Two always-on sources are
large because they are whole files where only a table of contents is needed
before the work starts: a registry naming every repo, customer and workspace,
and any other declared map an instance keeps. A session needs to know THAT a
customer called `example-customer` exists and roughly what it is. It does not
need the customer's fifteen fields until somebody names it.

Skills have had this split since the beginning: the name and one line stay
resident, the body arrives on invocation. Standing orders got it when the load
contract landed. This adds it to declared map sources, and does it once rather
than a third time in a third shape.

    THE CARD (what stays resident)

        keep       top-level keys emitted VERBATIM, comments and all
        sections   top-level maps whose children become one index line each
        label      the child field that supplies that line (default:
                   `description`), truncated to `label_chars` (default 120)

    Anything else present in the file is named under "also present", never
    dropped. A card that silently omits a key is the exact failure the budget
    was built to stop, one layer down.

    THE BODY (what arrives on demand)

        --get <dotted.path>    the raw text of that block, comments included
        --list                 every path --get accepts

    Slices are RAW TEXT, never re-serialized YAML. Re-serializing drops
    comments, and in these files the comments carry the reasoning: which
    branch is the running one, which board is closed, why a path is what it
    is. A reader that strips them answers the letter of the question and loses
    the part that stops a wrong action.

    FAIL-OPEN. A file with no `card:` declaration is still indexable: every
    top-level map with map children is treated as a section. An instance that
    has never heard of this feature loses nothing by not declaring.
"""

import importlib.util
import os
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "scripts" / "context-index.py"


def _load_lib():
    """Import scripts/lib/context_index.py by path (scripts/ is not a package)."""
    spec = importlib.util.spec_from_file_location(
        "context_index", REPO_ROOT / "scripts" / "lib" / "context_index.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


ci = _load_lib()


# --------------------------------------------------------------- fixtures --

SOURCE = """\
# yaml-language-server: $schema=./docs/schemas/ecosystem.schema.yaml
---
# A header comment about the file as a whole.

org: example-org
local_root: ~/Projects

work_system:
  enabled: true
  path: work/

base:
  # This comment belongs to my-bridge and has to travel with it.
  my-bridge:
    github: example/my-bridge
    description: "Your own Bridge instance."
    type: tool

  wiki:
    github: example/wiki
    description: "Documentation, protocols and customer records, kept in one place so that every instance can point at the same paragraph instead of its own copy."
    type: docs

customers:
  # An orphan comment, separated from the entry below by a blank line.

  example-customer:
    display_name: "Example Customer"
    issue_repo: example/example-wiki

github_projects:
  - number: 1
    name: "Board one"
  - number: 2
    name: "Board two"
"""

CARD = {
    "kind": "index",
    "keep": ["org", "local_root", "work_system"],
    "sections": ["base", "customers"],
    "label": "description",
    "label_chars": 40,
}


@pytest.fixture()
def source() -> str:
    return SOURCE


@pytest.fixture()
def repo(tmp_path: Path) -> Path:
    (tmp_path / "ecosystem.yaml").write_text(SOURCE, encoding="utf-8")
    return tmp_path


def run_cli(repo: Path, *args: str):
    return subprocess.run(
        [sys.executable, str(CLI), "--repo-root", str(repo), *args],
        capture_output=True,
        text=True,
    )


# ------------------------------------------------------- addressing + get --


def test_list_names_every_top_level_key_and_section_child(source):
    """--list is the contract of what --get accepts, and it covers the file."""
    paths = ci.addressable(source, CARD)

    for top in ("org", "local_root", "work_system", "base", "customers",
                "github_projects"):
        assert top in paths, f"top-level key {top} is not addressable"
    assert "base.my-bridge" in paths
    assert "base.wiki" in paths
    assert "customers.example-customer" in paths


def test_get_a_top_level_scalar_returns_its_line(source):
    assert ci.slice_block(source, "org").strip() == "org: example-org"


def test_get_a_section_returns_the_whole_block_verbatim(source):
    block = ci.slice_block(source, "base")

    assert block.startswith("base:")
    assert "my-bridge:" in block and "wiki:" in block
    # Verbatim means the comment inside the block survives.
    assert "This comment belongs to my-bridge" in block
    # And it stops at the next top-level key.
    assert "customers:" not in block


def test_get_an_entry_returns_only_that_entry(source):
    block = ci.slice_block(source, "base.my-bridge")

    assert "my-bridge:" in block
    assert "github: example/my-bridge" in block
    assert "wiki:" not in block


def test_get_carries_the_comment_directly_above_the_entry(source):
    """A comment touching an entry is that entry's, and travels with it.

    This is the whole reason slices are text and not re-serialized YAML. In a
    real registry these lines say things like which branch is actually
    running, and losing them is losing the guardrail, not the prose.
    """
    block = ci.slice_block(source, "base.my-bridge")
    assert "This comment belongs to my-bridge" in block


def test_get_leaves_a_comment_separated_by_a_blank_line(source):
    """Contiguity is the rule; a blank line ends the attachment."""
    block = ci.slice_block(source, "customers.example-customer")

    assert "example-customer:" in block
    assert "An orphan comment" not in block


def test_get_an_unknown_path_says_what_exists(repo):
    result = run_cli(repo, "ecosystem.yaml", "--get", "customers.nope")

    assert result.returncode != 0
    # Naming the neighbours is the difference between a usable error and a
    # traceback: the caller guessed a name and needs the real ones.
    assert "example-customer" in (result.stdout + result.stderr)


def test_every_listed_path_is_retrievable(source):
    """THE ROUND TRIP. An index that points at nothing is worse than none.

    Worse, because a pointer reads as a promise that the content is one call
    away, and the caller stops looking for it anywhere else.
    """
    for path in ci.addressable(source, CARD):
        block = ci.slice_block(source, path)
        assert block.strip(), f"{path} is listed but slices to nothing"


# ---------------------------------------------------------------- the card --


def test_card_names_every_top_level_key(source):
    """NOTHING VANISHES. Kept, sectioned or merely named, but never absent."""
    card = ci.render_card(source, CARD, "ecosystem.yaml")

    for top in ("org", "local_root", "work_system", "base", "customers",
                "github_projects"):
        assert top in card, f"{top} is in the file and not in the card"


def test_kept_keys_are_emitted_as_raw_text(source):
    card = ci.render_card(source, CARD, "ecosystem.yaml")

    assert "org: example-org" in card
    assert "local_root: ~/Projects" in card
    assert "enabled: true" in card


def test_section_entries_appear_with_their_label(source):
    card = ci.render_card(source, CARD, "ecosystem.yaml")

    assert "my-bridge" in card
    assert "Your own Bridge instance." in card


def test_a_long_label_is_truncated_visibly(source):
    card = ci.render_card(source, CARD, "ecosystem.yaml")

    assert "…" in card, "truncation has to be visible, or it reads as the whole label"
    assert "instead of its own copy." not in card


def test_an_entry_without_a_label_still_appears(source):
    """Omitting the unlabelled ones would hide exactly what nobody described."""
    card = ci.render_card(source, CARD, "ecosystem.yaml")
    assert "example-customer" in card


def test_label_falls_back_through_a_list_of_fields():
    """Not every entry family names its one line the same thing.

    Measured against a real 22 KB registry: every customer carries
    `display_name` and no `description`, so a single-field label left a
    quarter of the index reading "(no label)" — an index whose lines are
    blank is a list of names, which is the thing this was supposed to beat.
    """
    text = (
        "customers:\n"
        "  one:\n"
        "    display_name: \"Customer One\"\n"
        "  two:\n"
        "    description: \"The second.\"\n"
    )
    card = ci.render_card(
        text, {"sections": ["customers"], "label": ["description", "display_name"]},
        "e.yaml",
    )

    assert "Customer One" in card
    assert "The second." in card


def test_card_names_the_command_that_fetches_a_body(source):
    """A card that does not say how to get the rest is a card with a dead end."""
    card = ci.render_card(source, CARD, "ecosystem.yaml")

    assert "context-index.py" in card
    assert "--get" in card


def test_card_is_deterministic(source):
    """No timestamp, no host, no dict ordering: it is compared across runs."""
    assert ci.render_card(source, CARD, "ecosystem.yaml") == ci.render_card(
        source, CARD, "ecosystem.yaml"
    )


def test_a_list_valued_key_is_reported_with_its_length(source):
    """Lists are not indexed in this contract, and say so rather than vanish."""
    card = ci.render_card(source, CARD, "ecosystem.yaml")

    assert "github_projects" in card
    assert "2" in card


def test_an_undeclared_file_still_indexes(source):
    """FAIL-OPEN. No card declaration, sections auto-detected, nothing lost."""
    card = ci.render_card(source, None, "ecosystem.yaml")

    assert "my-bridge" in card
    assert "example-customer" in card
    for top in ("org", "local_root", "github_projects"):
        assert top in card


def test_auto_detection_actually_indexes_a_section(source):
    """The name appearing is not proof the section was detected.

    Written after the previous test passed for the wrong reason: entry names
    also appear when a block is kept WHOLE, so an assertion on the name alone
    is green whether detection worked or not. The distinguishing evidence is
    that the entry's fields are gone.
    """
    card = ci.render_card(source, None, "ecosystem.yaml")

    assert "## base" in card, "base is a map of maps and has to be a section"
    assert "github: example/my-bridge" not in card, (
        "an indexed section must not still carry its entries' fields"
    )


def test_a_block_does_not_swallow_the_next_keys_comment():
    """A comment touching the key BELOW it introduces that key, not the one above.

    Found by rendering the registry this repo actually ships: `local_root`
    came back carrying the paragraph that introduces `work_system`. Harmless
    to read, wrong to slice, and wrong in the direction that matters — the
    next key's reasoning shows up filed under its neighbour.
    """
    text = (
        "local_root: ~/Projects\n"
        "\n"
        "# This paragraph introduces work_system.\n"
        "work_system:\n"
        "  enabled: true\n"
    )

    assert "introduces work_system" not in ci.slice_block(text, "local_root")
    assert "introduces work_system" in ci.slice_block(text, "work_system")


def test_auto_detection_keeps_a_mixed_map_whole():
    """A map of settings is configuration, not a section of entries.

    Also found against the shipped registry: `work_system` was detected as a
    section because one of its three children happens to be a map, so
    `enabled: true` stopped being resident. That value decides whether Phase 1
    runs at all. When children are mixed, auto-detection keeps the block —
    the fail-open direction is to carry more, never less.
    """
    text = (
        "work_system:\n"
        "  enabled: true\n"
        "  path: work/\n"
        "  files:\n"
        "    current: work/log.md\n"
        "\n"
        "customers:\n"
        "  one:\n"
        "    description: First.\n"
    )
    card = ci.render_card(text, None, "e.yaml")

    assert "enabled: true" in card, "a settings block has to stay resident"
    assert "## work_system" not in card
    assert "## customers" in card


# ---------------------------------------------- the loss, made measurable --


def test_card_reports_comment_bytes_it_cannot_carry(source):
    """A guardrail written as a YAML comment stops working the day the file
    stops being read whole. That is a real cost of this feature, so the card
    states it rather than letting a migration discover it later."""
    lost = ci.uncarried_comment_bytes(source, CARD)
    assert lost > 0

    card = ci.render_card(source, CARD, "ecosystem.yaml")
    assert str(lost) in card


def test_comment_bytes_ignore_kept_regions(source):
    """A comment inside a kept key travels, so it is not a loss."""
    card_keeping_base = dict(CARD, keep=["org", "local_root", "work_system", "base"],
                             sections=["customers"])
    assert ci.uncarried_comment_bytes(
        source, card_keeping_base
    ) < ci.uncarried_comment_bytes(source, CARD)


# ------------------------------------------------------------------- CLI --


def test_cli_prints_the_card_by_default(repo):
    result = run_cli(repo, "ecosystem.yaml")

    assert result.returncode == 0
    assert "my-bridge" in result.stdout


def test_cli_get_prints_one_block(repo):
    result = run_cli(repo, "ecosystem.yaml", "--get", "base.my-bridge")

    assert result.returncode == 0
    assert "github: example/my-bridge" in result.stdout
    assert "wiki:" not in result.stdout


def test_cli_list_prints_addressable_paths(repo):
    result = run_cli(repo, "ecosystem.yaml", "--list")

    assert result.returncode == 0
    assert "base.my-bridge" in result.stdout


def test_cli_on_a_missing_file_is_quiet_and_succeeds(repo):
    """A registry is instance data. Absent is the normal state of a fresh
    clone, and a session that fails there fails for everyone who has not
    onboarded yet."""
    result = run_cli(repo, "does-not-exist.yaml")

    assert result.returncode == 0
    assert result.stdout.strip() == ""


def test_cli_reads_the_card_from_the_budget(tmp_path):
    """The declaration lives in one place, and both halves read the same one."""
    (tmp_path / "ecosystem.yaml").write_text(SOURCE, encoding="utf-8")
    (tmp_path / "context-budget.yaml").write_text(
        "schema_version: 1\n"
        "items:\n"
        "  ecosystem.yaml:\n"
        "    card:\n"
        "      kind: index\n"
        "      keep: [org]\n"
        "      sections: [customers]\n",
        encoding="utf-8",
    )
    result = run_cli(tmp_path, "ecosystem.yaml")

    assert result.returncode == 0
    assert "org: example-org" in result.stdout
    # `base` is neither kept nor sectioned here, so it is named, not expanded.
    assert "my-bridge" not in result.stdout
    assert "base" in result.stdout


# ------------------------------------------------- the guards, and biting --


def test_round_trip_guard_reports_an_unreachable_name():
    """MUTATION. The guard has to fail on a card that promises a dead path."""
    findings = ci.check_round_trip(SOURCE, CARD, extra_paths=["customers.ghost"])
    assert any("ghost" in f for f in findings)


def test_round_trip_guard_is_silent_on_a_healthy_file():
    assert ci.check_round_trip(SOURCE, CARD) == []


def test_nothing_vanishes_guard_reports_an_omitted_key():
    """MUTATION. A card that drops a top-level key has to be a finding."""
    findings = ci.check_coverage(SOURCE, rendered="org: example-org\n")
    assert any("customers" in f for f in findings)


def test_nothing_vanishes_guard_is_silent_on_the_real_card():
    card = ci.render_card(SOURCE, CARD, "ecosystem.yaml")
    assert ci.check_coverage(SOURCE, rendered=card) == []


# ---------------------------------------------------------- the live tree --


def test_the_shipped_example_registry_round_trips():
    """Run against what this repo actually ships, not only a fixture.

    A contract proven on a hand-written fixture and never on real content is
    the shape that passes CI and fails on the first instance.
    """
    example = REPO_ROOT / "ecosystem.example.yaml"
    if not example.is_file():
        pytest.skip("no ecosystem.example.yaml in this tree")

    text = example.read_text(encoding="utf-8")
    assert ci.check_round_trip(text, None) == []
    card = ci.render_card(text, None, "ecosystem.example.yaml")
    assert ci.check_coverage(text, rendered=card) == []
    assert len(card.encode("utf-8")) < len(text.encode("utf-8")), (
        "a card that is not smaller than its source buys nothing"
    )


# ------------------------------------------- the declaration's own guard --
#
# The declaration is the new failure surface this feature adds. A name in
# `keep:` or `sections:` that does not exist in the source is a typo the card
# absorbs in silence: the real key falls through to "also present" and its
# content stops being resident, and the card still renders and still passes.


def test_a_declared_section_that_does_not_exist_is_a_finding(source):
    findings = ci.check_declaration(source, dict(CARD, sections=["custommers"]))
    assert any("custommers" in f for f in findings)


def test_a_declared_keep_that_does_not_exist_is_a_finding(source):
    findings = ci.check_declaration(source, dict(CARD, keep=["org", "loca_root"]))
    assert any("loca_root" in f for f in findings)


def test_a_correct_declaration_is_silent(source):
    assert ci.check_declaration(source, CARD) == []


def test_an_absent_declaration_is_silent(source):
    """Auto-detection reads the file, so it cannot name something that is not
    in it. Nothing to check, and nothing to complain about."""
    assert ci.check_declaration(source, None) == []


def test_check_runs_every_declared_card_in_the_tree(tmp_path):
    (tmp_path / "ecosystem.yaml").write_text(SOURCE, encoding="utf-8")
    (tmp_path / "context-budget.yaml").write_text(
        "schema_version: 1\n"
        "items:\n"
        "  ecosystem.yaml:\n"
        "    card:\n"
        "      kind: index\n"
        "      sections: [custommers]\n",
        encoding="utf-8",
    )
    result = run_cli(tmp_path, "--check")

    assert result.returncode != 0
    assert "custommers" in (result.stdout + result.stderr)


def test_check_does_not_count_a_card_whose_source_is_absent(tmp_path):
    # A declared card whose target is missing is SKIPPED: it is instance data,
    # absent in a fresh clone, and declared-and-absent is the budget's business.
    # The skip is right; counting it in "N declared card(s) check out" is not.
    # That line is what a human reads to believe the guard ran, and a card
    # nothing was read from has not checked out, it was never looked at. The
    # count must speak only for what was actually verified, and the skipped one
    # must be named so an absent source cannot hide behind a green line.
    (tmp_path / "ecosystem.yaml").write_text(SOURCE, encoding="utf-8")
    (tmp_path / "context-budget.yaml").write_text(
        "schema_version: 1\n"
        "items:\n"
        "  ecosystem.yaml:\n"
        "    card:\n"
        "      kind: index\n"
        "      keep: [org]\n"
        "      sections: [base, customers]\n"
        "  ecosystem.absent.yaml:\n"
        "    card:\n"
        "      kind: index\n"
        "      sections: [invented]\n",
        encoding="utf-8",
    )
    result = run_cli(tmp_path, "--check")
    out = result.stdout + result.stderr

    assert result.returncode == 0, out
    assert "2 declared card(s) check out" not in out, (
        "the absent card was counted as verified: " + out
    )
    assert "1 declared card(s) check out" in out, out
    assert "ecosystem.absent.yaml" in out, (
        "the skipped card is not named, so it hides behind the green line: " + out
    )


def test_check_is_green_on_a_healthy_tree(tmp_path):
    (tmp_path / "ecosystem.yaml").write_text(SOURCE, encoding="utf-8")
    (tmp_path / "context-budget.yaml").write_text(
        "schema_version: 1\n"
        "items:\n"
        "  ecosystem.yaml:\n"
        "    card:\n"
        "      kind: index\n"
        "      keep: [org]\n"
        "      sections: [base, customers]\n",
        encoding="utf-8",
    )
    result = run_cli(tmp_path, "--check")

    assert result.returncode == 0, result.stdout + result.stderr


def test_check_on_a_tree_with_no_cards_is_green(tmp_path):
    (tmp_path / "context-budget.yaml").write_text(
        "schema_version: 1\nitems: {}\n", encoding="utf-8"
    )
    assert run_cli(tmp_path, "--check").returncode == 0


# ------------------------------------------- structure, against an oracle --
#
# The parser is a line scanner, and the whole feature rests on it agreeing with
# YAML about where a block starts and ends. Found by sweeping 120 real files:
# a list item at column zero is legal YAML and was read as a top-level key.

LIST_AT_COLUMN_ZERO = """\
org: example-org

upstreams:
- name: public
  url: https://example.org/a
- name: private
  url: https://example.org/b

customers:
  one:
    description: The first.
"""


def test_a_column_zero_list_item_is_not_a_top_level_key():
    blocks = ci.parse_source(LIST_AT_COLUMN_ZERO)

    assert "- name" not in blocks, "a list item was read as a key"
    assert set(blocks) == {"org", "upstreams", "customers"}


def test_a_key_owning_a_column_zero_list_slices_whole():
    """The damaging half. The invented key ENDS the real one's block, so the
    real key slices to its header line alone — 11 bytes on a live
    bridge-config.yaml — while the round-trip guard reported clean, because
    one line is still 'something'."""
    block = ci.slice_block(LIST_AT_COLUMN_ZERO, "upstreams")

    assert "name: public" in block
    assert "name: private" in block
    assert "customers:" not in block


def test_structure_guard_agrees_with_yaml(source):
    """An independent oracle. PyYAML already knows the answer, so the cheapest
    honest check of a hand-written scanner is to ask both and compare."""
    assert ci.check_structure(source) == []
    assert ci.check_structure(LIST_AT_COLUMN_ZERO) == []


def test_structure_guard_reports_an_invented_key(source):
    """MUTATION. Feed it the wrong answer and it has to say so."""
    wrong = dict(ci.parse_source(source))
    wrong["- name"] = {"kind": "map", "start": 0, "end": 1, "children": {}}
    findings = ci.check_structure(source, blocks=wrong)

    assert any("- name" in f for f in findings)


def test_structure_guard_reports_a_missing_key(source):
    wrong = {k: v for k, v in ci.parse_source(source).items() if k != "customers"}
    findings = ci.check_structure(source, blocks=wrong)

    assert any("customers" in f for f in findings)


def test_structure_guard_reports_a_block_truncated_to_its_header():
    """The span half. A key whose value is a map or a list has to slice to more
    than its own line; anything less is a truncation the round trip cannot
    see, because a header line is still non-empty."""
    wrong = dict(ci.parse_source(LIST_AT_COLUMN_ZERO))
    start = wrong["upstreams"]["start"]
    wrong["upstreams"] = dict(wrong["upstreams"], end=start + 1)
    findings = ci.check_structure(LIST_AT_COLUMN_ZERO, blocks=wrong)

    assert any("upstreams" in f for f in findings)


# ------------------------------------------- declaration and card defaults --


def test_a_bare_kind_index_auto_detects(source):
    """`card: {kind: index}` means INDEX THIS, shape detected.

    Empty keep and empty sections would put every key under "also present" and
    render a card that is a list of names — the thing this feature exists to
    beat — while still passing its cap and every guard. CORE ships exactly this
    bare form, because naming sections there would fire on the first instance
    whose registry legitimately lacks one."""
    card = ci.render_card(source, {"kind": "index"}, "ecosystem.yaml")

    assert "org: example-org" in card, "settings have to be kept"
    assert "## base" in card, "entry families have to be indexed"
    assert "Your own Bridge instance." in card


def test_an_explicitly_empty_sections_list_stays_empty(source):
    """Absent is not the same as empty. Declaring `sections: []` is a choice."""
    card = ci.render_card(source, {"kind": "index", "keep": ["org"], "sections": []},
                          "ecosystem.yaml")

    assert "## base" not in card
    assert "base" in card  # named under "also present", never dropped


def test_a_key_in_both_keep_and_sections_is_a_finding(source):
    """Kept whole AND indexed is two answers to one question."""
    findings = ci.check_declaration(source, {"keep": ["base"], "sections": ["base"]})
    assert any("base" in f for f in findings)


def test_coverage_does_not_accept_a_substring_match():
    """`org` occurs inside `example-org`, so a substring test finds a key that
    is not there. A guard that cannot fail is not a guard."""
    text = "org: example-org\ncustomers:\n  one:\n    description: x\n"
    rendered = "# e.yaml — index\n\nSomething about example-org.\n"

    assert any("org" == f.split(":")[0] for f in ci.check_coverage(text, rendered=rendered))


def test_the_user_overlay_replaces_a_card_wholesale(tmp_path):
    """Same semantics the meter uses. If the two halves disagreed, the gate
    would measure one card and the session would get another."""
    (tmp_path / "ecosystem.yaml").write_text(SOURCE, encoding="utf-8")
    (tmp_path / "context-budget.yaml").write_text(
        "schema_version: 1\n"
        "items:\n"
        "  ecosystem.yaml:\n"
        "    card:\n"
        "      kind: index\n",
        encoding="utf-8",
    )
    (tmp_path / "context-budget.user.yaml").write_text(
        "items:\n  ecosystem.yaml:\n    max_bytes: 99999\n", encoding="utf-8"
    )

    assert ci.card_for(tmp_path, "ecosystem.yaml") is None


# --------------------------------- the structure guard's own false alarms --
#
# Both found by sweeping 255 real files with the guard freshly written. A guard
# whose first outing is 54 false alarms teaches its reader to ignore it, which
# is a worse state than not having written it.


def test_a_flow_list_on_one_line_is_not_a_truncation():
    """`required: [a, b]` has content AND lives on one line, legitimately.

    Every `_schema.yaml` in both trees tripped this — the guard was reading
    "the value has content" as "the value needs more than one line".
    """
    text = "required: [schema_version, items]\nother: 1\n"
    assert ci.check_structure(text) == []


def test_a_flow_mapping_on_one_line_is_not_a_truncation():
    text = "runtime: {host: box, port: 8791}\nother: 1\n"
    assert ci.check_structure(text) == []


def test_a_yaml_1_1_boolean_key_is_not_an_invented_key():
    """`on:` is the GitHub-workflow trigger and YAML 1.1 resolves it to True.

    Comparing against `safe_load` made the scanner look like it invented a key
    it read perfectly well. The oracle has to be asked for the source spelling,
    not for the resolved value.
    """
    text = "name: ci\non:\n  push:\n    branches: [main]\njobs:\n  a:\n    runs-on: x\n"
    findings = ci.check_structure(text)

    assert not any("invented" in f for f in findings), findings


def test_a_block_mapping_truncated_to_its_header_is_still_caught():
    """The true positive has to survive both corrections."""
    text = "upstreams:\n  a:\n    url: x\nother: 1\n"
    wrong = dict(ci.parse_source(text))
    wrong["upstreams"] = dict(wrong["upstreams"], end=wrong["upstreams"]["start"] + 1)

    assert any("upstreams" in f for f in ci.check_structure(text, blocks=wrong))


# ------------------------------------------------ the whole tree as corpus --


def test_every_yaml_in_this_repo_parses_consistently():
    """Run all three guards over every YAML this repo ships.

    The fixture above is what the author imagined; this is what the tree
    actually contains, and the difference has been the whole yield of this
    feature so far. A sweep like this found the column-zero list item that a
    hand-written fixture never would have, and it found it in files that were
    already in production.

    Kept in the suite rather than run once, because the corpus grows: the next
    file with an unusual shape arrives as a normal commit, not as a bug report.
    """
    import yaml as _yaml

    checked = 0
    problems: list[str] = []
    for path in sorted(REPO_ROOT.rglob("*.y*ml")):
        if ".git/" in str(path) or "/node_modules/" in str(path):
            continue
        try:
            text = path.read_text(encoding="utf-8")
            if not isinstance(_yaml.safe_load(text), dict):
                continue
        except (UnicodeDecodeError, _yaml.YAMLError):
            continue  # a template with placeholders is not this guard's business
        checked += 1
        rel = str(path.relative_to(REPO_ROOT))
        card = ci.render_card(text, None, rel)
        for finding in (
            ci.check_structure(text)
            + ci.check_round_trip(text, None)
            + ci.check_coverage(text, rendered=card)
        ):
            problems.append(f"{rel}: {finding}")

    assert checked > 50, f"corpus too small to mean anything ({checked} files)"
    assert problems == [], "\n".join(problems[:15])


# -------------------------------------------------- quoted keys, and depth --
#
# Found on a live context-budget.user.yaml. A key that needs quoting in YAML
# — a path, anything with a colon — was carried into the index WITH its quotes,
# so the index advertised a name that `yaml.safe_load` does not report and
# `--get` refused the name that it does.

QUOTED = '''\
items:
  "ecosystem.bks.yaml":
    max_bytes: 24000
  plain.md:
    max_bytes: 100
'''


def test_a_quoted_key_name_matches_what_yaml_reports():
    children = ci.parse_source(QUOTED)["items"]["children"]

    assert "ecosystem.bks.yaml" in children, f"got {list(children)}"
    assert '"ecosystem.bks.yaml"' not in children


def test_get_accepts_the_name_yaml_reports():
    """The quoted form worked and the plain form did not, which is backwards:
    the plain form is the one a caller gets from a YAML reader."""
    block = ci.slice_block(QUOTED, "items.ecosystem.bks.yaml")

    assert "max_bytes: 24000" in block
    assert "plain.md" not in block


def test_the_index_shows_the_name_without_its_quotes():
    card = ci.render_card(QUOTED, None, "b.yaml")

    assert "**ecosystem.bks.yaml**" in card
    assert '**"ecosystem.bks.yaml"**' not in card


def test_structure_guard_compares_children_too(source):
    """It only ever looked at top-level keys, which is why the quoted-name
    defect sat in a live file with every guard green."""
    assert ci.check_structure(QUOTED) == []

    wrong = dict(ci.parse_source(QUOTED))
    items = dict(wrong["items"])
    items["children"] = dict(items["children"])
    items["children"]["ghost"] = items["children"].pop("plain.md")
    wrong["items"] = items
    findings = ci.check_structure(QUOTED, blocks=wrong)

    assert any("ghost" in f for f in findings), findings
    assert any("plain.md" in f for f in findings), findings


def test_a_quoted_key_containing_a_colon_is_seen():
    """`"cmd:python3 scripts/worklog.py --recent 3":` is a key in this repo's
    own context-budget.yaml, and the scanner could not see it at all: the name
    pattern stopped at the first colon, which sits inside the quotes.

    Found by the whole-tree sweep on its second outing, in a shipped file.
    """
    text = (
        'items:\n'
        '  "cmd:python3 scripts/worklog.py --recent 3":\n'
        '    max_bytes: 10\n'
        '  plain:\n'
        '    max_bytes: 20\n'
    )
    children = ci.parse_source(text)["items"]["children"]

    assert "cmd:python3 scripts/worklog.py --recent 3" in children, list(children)
    assert ci.check_structure(text) == []
    assert "max_bytes: 10" in ci.slice_block(
        text, "items.cmd:python3 scripts/worklog.py --recent 3"
    )


def test_a_quoted_key_with_a_colon_is_still_a_block():
    """Third sighting of one mistake: splitting a key line at the FIRST colon.

    The regex learned about quotes; the shape test did not, so
    `"cmd:python3 …":` read as a scalar whose value is `python3 …":`. One such
    child was enough to stop its parent being detected as a section, and the
    live context-budget.user.yaml came back with its whole `items:` block kept
    verbatim instead of indexed. Nothing is lost that way, which is exactly why
    it needs a test rather than a reader noticing.
    """
    text = (
        'items:\n'
        '  "cmd:python3 scripts/worklog.py --recent 3":\n'
        '    max_bytes: 130000\n'
        '  plain:\n'
        '    max_bytes: 20\n'
    )
    keep, sections = ci._detect(text)

    assert sections == ["items"], f"keep={keep} sections={sections}"
    assert "## items" in ci.render_card(text, None, "b.yaml")


def test_structure_guard_reports_a_kind_disagreement():
    """A scanner that calls a block mapping a scalar has misread the line."""
    text = "runtime:\n  host: box\n  port: 1\n"
    wrong = dict(ci.parse_source(text))
    wrong["runtime"] = dict(wrong["runtime"], kind="scalar")

    assert any("runtime" in f for f in ci.check_structure(text, blocks=wrong))


# ------------------------------------------------------------ file header --
#
# A card is a table of contents, and a table of contents that omits what the
# BOOK is is incomplete. Measured on a live instance: slicing three registries
# into cards dropped 24 comment lines, ALL of them the leading header block and
# none of them attached to a key. Among them:
#
#     # scope: bks — org/customer registry, routet zu bks-bridge, NIE open-bridge.
#     # PERSONAL-tier ecosystem extension (NEVER promoted to public/bks)
#     # ... so this content never reaches an upstream
#
# Promote routing is structural, so nothing was UNSAFE. But a session that only
# ever sees the card had no way to learn that the file it is holding is PII that
# must never be published, and that is the one sentence a header exists to say.
# 2 018 bytes across those three files, 0.63 % of that instance's always-on
# surface, and it is bounded by the item's own max_bytes like everything else.
#
# The split rule is free: `_with_leading_comments` already decides, by
# contiguity, which comments belong to the first key. The header is what is left
# ABOVE that, so the two can never overlap and nothing is carried twice.


def _hdr(body: str) -> str:
    return ci.render_card(body, {"kind": "index"}, "f.yaml")


def test_the_leading_comment_block_reaches_the_card():
    card = _hdr("# what this file is\n# and its scope\n\nalpha:\n  a: 1\n")
    assert "# what this file is" in card
    assert "# and its scope" in card


def test_a_comment_touching_the_first_key_is_not_header():
    # No blank line, so it belongs to `alpha` by the contiguity rule and must
    # not be duplicated into the header.
    body = "# real header\n\n# belongs to alpha\nalpha:\n  a: 1\n"
    card = ci.render_card(body, {"kind": "index", "keep": ["alpha"]}, "f.yaml")
    assert card.count("# belongs to alpha") == 1
    assert "# real header" in card


def test_the_header_is_not_emitted_twice_when_the_first_key_is_kept():
    body = "# header\n\nalpha:\n  a: 1\n"
    card = ci.render_card(body, {"kind": "index", "keep": ["alpha"]}, "f.yaml")
    assert card.count("# header") == 1


def test_a_file_that_starts_with_a_key_has_no_header():
    assert ci.file_header("alpha:\n  a: 1\n") == ""


def test_a_file_with_no_header_gains_no_stray_blank_block():
    card = _hdr("alpha:\n  a: 1\n")
    assert not card.startswith("\n")
    assert "\n\n\n" not in card


def test_a_file_with_no_top_level_key_yields_no_header():
    # Degenerate: without a key there is nothing to be the header OF, and
    # returning the whole file would put an entire document in the card.
    assert ci.file_header("# just a comment\n# and another\n") == ""


def test_the_language_server_directive_is_dropped():
    body = "# yaml-language-server: $schema=./_schema.yaml\n# real prose\n\nalpha:\n  a: 1\n"
    header = ci.file_header(body)
    assert "yaml-language-server" not in header
    assert "# real prose" in header


def test_a_document_marker_is_dropped():
    body = "---\n# real prose\n\nalpha:\n  a: 1\n"
    header = ci.file_header(body)
    assert header.strip().splitlines() == ["# real prose"]


def test_the_header_survives_on_a_real_registry_shape():
    body = (
        "# ecosystem.personal.yaml — PERSONAL tier\n"
        "# scope: personal — NEVER promoted to public\n"
        "\n"
        "freelance:\n"
        "  praxis:\n"
        "    description: a customer\n"
    )
    card = ci.render_card(body, {"kind": "index", "sections": ["freelance"]}, "e.yaml")
    assert "NEVER promoted to public" in card
    assert "**praxis**" in card


def test_the_header_does_not_confuse_the_declaration_check():
    # The header is prose, not a key. It must not make `keep`/`sections`
    # validation think a declared name is present, nor an absent one missing.
    body = "# alpha: this looks like a key but is a comment\n\nbeta:\n  b: 1\n"
    assert ci.check_declaration(body, {"kind": "index", "keep": ["alpha"]})
    assert not ci.check_declaration(body, {"kind": "index", "keep": ["beta"]})


# ------------------------------------------ a section that is not a mapping --
#
# `sections:` names top-level MAPS, whose children become the card's one-line
# entries. Declare a name whose value is a SEQUENCE and render_card iterates
# `children`, which parse_source leaves empty for a list: a bare `## name`
# heading, zero rows, the entries missing from the count, and absent from "Also
# present" too — while all four guards stay green.
#
# Live on an instance on 2026-08-30: `github_projects` (8 boards) declared as a
# section rendered as an empty heading. Removing the declaration restored a
# working pointer, `Also present, fetch by name: github_projects (list of 8).`
# So the declaration was strictly WORSE than no declaration, which is the one
# direction a fail-open design must never be able to go.


def test_a_sequence_declared_as_a_section_is_a_finding():
    body = "alpha:\n  - one\n  - two\n"
    findings = ci.check_declaration(body, {"kind": "index", "sections": ["alpha"]})
    assert findings and "alpha" in findings[0]


def test_a_scalar_declared_as_a_section_is_a_finding():
    findings = ci.check_declaration("alpha: 1\n", {"kind": "index", "sections": ["alpha"]})
    assert findings and "alpha" in findings[0]


def test_a_mapping_declared_as_a_section_is_fine():
    body = "alpha:\n  one:\n    description: x\n"
    assert ci.check_declaration(body, {"kind": "index", "sections": ["alpha"]}) == []


def test_a_sequence_in_keep_is_not_a_finding():
    # `keep:` slices the block whole, so a list is perfectly valid there. Only
    # `sections:` needs children to render anything.
    body = "alpha:\n  - one\n"
    assert ci.check_declaration(body, {"kind": "index", "keep": ["alpha"]}) == []


# ------------------------------------------------ a card without PyYAML --
#
# `import yaml` is guarded by `try/except ImportError: yaml = None`, and
# `_label_for` skips its whole body when yaml is None — so every entry renders
# as `(no label)` and the CLI exits 0. Reproduced: 3 154 B of card became
# 1 885 B, 24 entries all unlabelled, stderr empty.
#
# The label IS the routing signal. `- **ryze** — (no label)` tells a session a
# name exists and nothing about whether it is the one it wants, which is the
# failure this module's own docstring names twelve lines above the guard:
# "the thing does not look missing, it looks like it was never there".
#
# Reachable from a venv without PyYAML, a shadowed `yaml` module, or a fresh
# clone before install. Refusing is the only honest answer: a degraded card is
# worse than no card, because no card sends you to the file.


def _run_without_yaml(tmp_path, *args):
    stub = tmp_path / "stub"
    stub.mkdir(exist_ok=True)
    (stub / "yaml.py").write_text('raise ImportError("no yaml")\n', encoding="utf-8")
    env = dict(os.environ, PYTHONPATH=str(stub))
    return subprocess.run(
        [sys.executable, str(CLI), "--repo-root", str(tmp_path), *args],
        capture_output=True, text=True, env=env,
    )


def test_the_cli_refuses_without_pyyaml_instead_of_degrading(tmp_path):
    (tmp_path / "ecosystem.yaml").write_text(
        "org: acme\ncustomers:\n  ryze:\n    description: a real label\n", encoding="utf-8"
    )
    result = _run_without_yaml(tmp_path, "ecosystem.yaml")
    assert result.returncode != 0
    assert "(no label)" not in result.stdout
    assert "PyYAML" in result.stderr


def test_the_check_also_refuses_without_pyyaml(tmp_path):
    # The gate must not report "0 declared card(s) check out" and exit 0 when it
    # could not read a declaration in the first place.
    result = _run_without_yaml(tmp_path, "--check")
    assert result.returncode != 0
    assert "PyYAML" in result.stderr


def test_the_cli_works_normally_with_pyyaml(tmp_path):
    (tmp_path / "ecosystem.yaml").write_text(
        "org: acme\ncustomers:\n  ryze:\n    description: a real label\n", encoding="utf-8"
    )
    result = subprocess.run(
        [sys.executable, str(CLI), "--repo-root", str(tmp_path), "ecosystem.yaml"],
        capture_output=True, text=True,
    )
    assert result.returncode == 0
    assert "a real label" in result.stdout
