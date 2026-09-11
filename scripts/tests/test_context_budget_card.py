#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The CORE card for ecosystem.yaml must not name an instance's sections.

`docs/schemas/context-budget.schema.yaml` states the rule next to the field:

    A name here that the source does not have is a finding
    (`context-index.py --check`), not a silent omission - which is why CORE
    ships `card: {kind: index}` bare: naming sections there would fail on the
    first instance whose registry legitimately lacks one.

`context-budget.yaml` shipped `sections: [base, customers, internal, partners,
workspaces]` anyway. Two of those five, `internal` and `partners`, are not in
`ecosystem.example.yaml` either, so the card was wrong against this repo's own
shipped example and not only against downstream registries.

It stayed invisible because `_check()` skips a card whose target file is absent,
and `ecosystem.yaml` is gitignored, so it is absent in every clone of this repo.
The card was therefore never evaluated here, only downstream, where it cost one
instance two days of red CI.

The second test below is the one that would have caught it, and it runs entirely
on files this repo ships.

Run: python3 -m pytest scripts/tests/test_context_budget_card.py -q
"""
from __future__ import annotations

import importlib.util
import pathlib

import pytest

yaml = pytest.importorskip("yaml")

REPO = pathlib.Path(__file__).resolve().parents[2]
BUDGET = REPO / "context-budget.yaml"
EXAMPLE = REPO / "ecosystem.example.yaml"

_spec = importlib.util.spec_from_file_location(
    "context_index_lib", REPO / "scripts" / "lib" / "context_index.py"
)
assert _spec and _spec.loader, "cannot load scripts/lib/context_index.py"
ci = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ci)


def card() -> dict:
    doc = yaml.safe_load(BUDGET.read_text(encoding="utf-8"))
    return doc["items"]["ecosystem.yaml"]["card"]


def test_core_card_names_no_sections():
    """CORE cannot know an instance's section names, so it must not claim any."""
    assert not card().get("sections"), (
        "context-budget.yaml names sections for ecosystem.yaml. The schema doc "
        "says CORE ships the card bare precisely because a name the source "
        "lacks is a finding, and CORE cannot know which sections an instance's "
        "registry has. Absent means detected."
    )


def test_core_card_holds_against_the_shipped_example():
    """The guard that runs on files this repo ships, not only downstream.

    context-index.py --check skips a card whose target is absent, and
    ecosystem.yaml is gitignored, so the real check never runs here. Pointing
    the same declaration check at ecosystem.example.yaml closes that gap without
    needing instance data.
    """
    findings = ci.check_declaration(EXAMPLE.read_text(encoding="utf-8"), card())
    assert not findings, (
        "the CORE card does not hold against ecosystem.example.yaml: "
        + "; ".join(findings)
    )


def test_a_registry_with_unexpected_sections_is_accepted():
    """An instance is free to shape its registry differently. That is the point.

    A consortium registry with only `base` and `workspaces` is as legitimate as
    an agency one with `customers`. The card must survive both.
    """
    registry = (
        "org: some-org\n"
        "local_root: ~/code\n"
        "work_system:\n"
        "  enabled: true\n"
        "base:\n"
        "  one:\n"
        "    description: a repo\n"
        "workspaces:\n"
        "  main:\n"
        "    description: a workspace\n"
    )
    findings = ci.check_declaration(registry, card())
    assert not findings, "; ".join(findings)
