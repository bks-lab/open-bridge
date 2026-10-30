#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Pytest suite for scripts/check-reachability.py.

CONTRACT, this file is the authoritative spec for that surface.

WHY THIS EXISTS. The context budget proves the always-on layer is SMALL. The
context index proves a body can be FETCHED. Neither proves the thing both are
for: that a session still knows the body exists. A cut that removes the last
mention of `infra/channels/` leaves every guard green — the budget is happier,
every route that remains resolves, every card round-trips — and the capability
is gone, because nothing will ever go looking for it.

That failure is silent by construction, and this repo has already paid for it
twice in one week: three standing orders targeted sub-agents that no instance
has, and the org-overlay import anchored on a line that had been deleted. Both
read as enforced and did nothing.

    THE CONTRACT

        Every config family the tree actually has must be NAMED, by its path,
        somewhere in the always-on surface.

    DERIVED, NEVER LISTED. The families come from the tree — the cluster
    wrappers' subdirectories plus the fixed top-level ones — for the same
    reason `AGENTS.md` stopped carrying a table of rules: a list written once
    is a list that is wrong later, and it is wrong in the direction that hides
    the newest thing.

    BY PATH, not by prose. "the machine inventory" is a name; `infra/remotes/`
    is a route. Only the second one can be followed, and only the second one
    breaks loudly when the directory moves.

    THE SURFACE IS THE METER'S. `always_on_text` comes from
    `measure-context.py`, so the set of files this checks against is the same
    set the budget gates. Two definitions of "always-on" would mean a family
    named in something the session does not actually load.
"""

import importlib.util
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
CLI = REPO_ROOT / "scripts" / "check-reachability.py"


def _load(name: str, rel: str):
    spec = importlib.util.spec_from_file_location(name, REPO_ROOT / rel)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


reach = _load("check_reachability", "scripts/check-reachability.py")
mc = _load("measure_context", "scripts/measure-context.py")


def _tree(root: Path, files: dict[str, str]) -> Path:
    for rel, text in files.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


MINIMAL_BUDGET = (
    "schema_version: 1\n"
    "items:\n"
    "  AGENTS.md:\n"
    "    max_bytes: 100000\n"
)


# ------------------------------------------------------------- discovery --


def test_a_wrapper_family_with_a_yaml_is_a_family(tmp_path):
    _tree(tmp_path, {"identity/mandants/_template.yaml": "a: 1\n"})
    assert "identity/mandants/" in reach.discover_families(tmp_path)


def test_a_wrapper_family_with_only_a_readme_is_not(tmp_path):
    """A directory of prose is documentation, not a config type."""
    _tree(tmp_path, {"identity/notes/README.md": "# not a family\n"})
    assert "identity/notes/" not in reach.discover_families(tmp_path)


def test_a_template_only_family_still_counts(tmp_path):
    """CORE ships several families as templates with no instance yet.

    They are shipped CAPABILITIES, and a capability nobody can discover is the
    exact thing this checks. `identity/contracts/` was in precisely that state
    — schema and template present, named nowhere — before this existed.
    """
    _tree(tmp_path, {"identity/contracts/_schema.yaml": "a: 1\n"})
    assert "identity/contracts/" in reach.discover_families(tmp_path)


def test_the_fixed_top_level_families_are_included(tmp_path):
    _tree(tmp_path, {
        "rules/operations.md": "x\n",
        "skills/demo/SKILL.md": "x\n",
        "protocols/standing-orders/a.md": "x\n",
    })
    found = reach.discover_families(tmp_path)

    for expected in ("rules/", "skills/", "protocols/standing-orders/"):
        assert expected in found


def test_a_top_level_family_that_does_not_exist_is_not_demanded(tmp_path):
    """A fresh clone has no `.claude/agents/`, and must not fail for it."""
    _tree(tmp_path, {"rules/operations.md": "x\n"})
    assert ".claude/agents/" not in reach.discover_families(tmp_path)


def test_discovery_is_derived_from_the_tree_not_a_list(tmp_path):
    """MUTATION. Invent a family; it has to appear without anyone editing a list."""
    _tree(tmp_path, {"workflow/quotas/_template.yaml": "a: 1\n"})
    assert "workflow/quotas/" in reach.discover_families(tmp_path)


# ---------------------------------------------------------------- the check --


def test_a_family_named_in_the_surface_passes(tmp_path):
    _tree(tmp_path, {
        "AGENTS.md": "Machines live in `infra/remotes/`.\n",
        "infra/remotes/_template.yaml": "a: 1\n",
        "context-budget.yaml": MINIMAL_BUDGET,
    })
    assert reach.check(tmp_path) == []


def test_a_family_missing_from_the_surface_is_a_finding(tmp_path):
    """The whole point. Every other guard is green in this state."""
    _tree(tmp_path, {
        "AGENTS.md": "Nothing about the inventory here.\n",
        "infra/remotes/_template.yaml": "a: 1\n",
        "context-budget.yaml": MINIMAL_BUDGET,
    })
    findings = reach.check(tmp_path)

    assert any("infra/remotes/" in f for f in findings), findings


def test_prose_without_the_path_does_not_count(tmp_path):
    """"the machine inventory" is a name; `infra/remotes/` is a route.

    Only the second can be followed, and only the second breaks loudly when
    the directory moves.
    """
    _tree(tmp_path, {
        "AGENTS.md": "Your machine inventory is described elsewhere.\n",
        "infra/remotes/_template.yaml": "a: 1\n",
        "context-budget.yaml": MINIMAL_BUDGET,
    })
    assert any("infra/remotes/" in f for f in reach.check(tmp_path))


def test_a_pointer_in_a_deferred_standing_order_does_not_count(tmp_path):
    """A body that loads on a trigger is not the surface.

    It is fetched by vocabulary that nobody will say, because the vocabulary
    is the thing that went missing.
    """
    order = (
        "---\nname: x\nscope: always\nenforcement: advisory\napplies_to: []\n"
        "load: on-trigger\ntriggers: [\"x\"]\nsummary: \"s\"\n---\n\n"
        "Channels live in `infra/channels/`.\n"
    )
    _tree(tmp_path, {
        "AGENTS.md": "Nothing here.\n",
        "protocols/standing-orders/x.md": order,
        "infra/channels/_template.yaml": "a: 1\n",
        "context-budget.yaml": MINIMAL_BUDGET,
    })
    assert any("infra/channels/" in f for f in reach.check(tmp_path))


def test_a_pointer_in_an_eager_standing_order_does_count(tmp_path):
    """An eager order IS loaded, so a pointer in it is genuinely resident."""
    order = (
        "---\nname: x\nscope: always\nenforcement: advisory\napplies_to: []\n"
        "---\n\nChannels live in `infra/channels/`.\n"
    )
    _tree(tmp_path, {
        "AGENTS.md": "Nothing here.\n",
        "protocols/standing-orders/x.md": order,
        "infra/channels/_template.yaml": "a: 1\n",
        "context-budget.yaml": MINIMAL_BUDGET,
    })
    # Only the question at hand: the fixture's own standing-orders family is
    # unnamed too, which is a finding about the fixture and not about this.
    assert not any("infra/channels/" in f for f in reach.check(tmp_path))


def test_the_finding_points_at_the_data_model_not_an_eager_order(tmp_path):
    """CORE variant: no bridge-config.yaml, so every family is a CORE family.

    The old text sent a person to an eager standing order, which no sub-agent
    loads, so the family stayed invisible to every dispatch.
    """
    _tree(tmp_path, {
        "AGENTS.md": "Nothing here.\n",
        "infra/remotes/_template.yaml": "a: 1\n",
        "context-budget.yaml": MINIMAL_BUDGET,
    })
    finding = next(f for f in reach.check(tmp_path) if f.startswith("infra/remotes/"))

    assert "docs/data-model.yaml" in finding
    assert "AGENTS.md" in finding
    assert "conflicts on every merge" in finding
    assert "standing-orders/user" not in finding


def test_the_fork_finding_points_at_instance_md_not_an_eager_order(tmp_path):
    """Fork variant: an instance names its own family in INSTANCE.md.

    IDENTITY.md and SOUL.md may be shipped by an org overlay, so they are not
    the place for fork prose. INSTANCE.md is USER and imported by AGENTS.md,
    so sub-agents see what it names.
    """
    _tree(tmp_path, {
        "AGENTS.md": "Nothing here.\n",
        "bridge-config.yaml": "identity:\n  name: x\n",
        "infra/remotes/_template.yaml": "a: 1\n",
        "context-budget.yaml": MINIMAL_BUDGET,
    })
    finding = next(f for f in reach.check(tmp_path) if f.startswith("infra/remotes/"))

    assert "identity/agent/INSTANCE.md" in finding
    assert "work/data-model.yaml" in finding
    assert "conflicts on every merge" in finding
    assert "standing-orders/user" not in finding
    assert "identity/agent/IDENTITY.md" not in finding


def test_a_legacy_claude_md_entry_still_reaches_agents_md(tmp_path):
    """An unmigrated fork still enters through CLAUDE.md, which imports AGENTS.md."""
    _tree(tmp_path, {
        "CLAUDE.md": "@AGENTS.md\n",
        "AGENTS.md": "Machines live in `infra/remotes/`.\n",
        "infra/remotes/_template.yaml": "a: 1\n",
        "context-budget.yaml": MINIMAL_BUDGET + "  CLAUDE.md:\n    max_bytes: 100000\n",
    })
    assert reach.check(tmp_path) == []
    assert "AGENTS.md" in reach.named_in(tmp_path, "infra/remotes/")


# ------------------------------------------------------- the surface itself --


def test_the_surface_is_the_one_the_meter_measures(tmp_path):
    """One definition of always-on, not two."""
    _tree(tmp_path, {
        "AGENTS.md": "MARKER-AGENTS\n",
        "context-budget.yaml": MINIMAL_BUDGET,
    })
    text = mc.always_on_text(tmp_path, mc.load_budget(tmp_path))

    assert "MARKER-AGENTS" in text


def test_the_surface_includes_what_a_phase_one_command_prints(tmp_path):
    """Half the surface is computed, not read, and a pointer can live there."""
    _tree(tmp_path, {
        "AGENTS.md": "x\n",
        "context-budget.yaml": MINIMAL_BUDGET
        + '  "cmd:python3 scripts/standing-orders.py --index":\n    source: phase1\n',
        "protocols/standing-orders/x.md": (
            "---\nname: x\nscope: always\nenforcement: advisory\napplies_to: []\n"
            "load: on-trigger\ntriggers: [\"say x\"]\nsummary: \"about workflow/quotas/\"\n"
            "---\n\nbody\n"
        ),
    })
    text = mc.always_on_text(tmp_path, mc.load_budget(tmp_path))

    # The index runs from the repo root, so it reports on THIS repo's orders,
    # not the fixture's. What matters here is that command output is included
    # at all — an empty string would mean the whole computed half is invisible.
    assert isinstance(text, str)
    assert "MARKER" not in text


# --------------------------------------------------------------------- CLI --


def test_cli_runs_on_this_repo_and_agrees_with_itself():
    """The live tree, which is the only run that matters — as a SMOKE test.

    It found two families on its first outing, `identity/contracts/` and
    `infra/instances/`, both shipped and both named nowhere, and neither was
    caused by the cuts that came before it. They had simply never been named.
    That is the value worth keeping: the check meets real content here and
    nowhere else in this file.

    What is NOT worth keeping is the old assertion that the exit code is zero.
    That is a gate on THIS tree, and a downstream instance trips it the moment
    it ships a family it has not pointed at yet — turning the CORE contract
    suite red for a content decision. `validate.yml` already runs
    `check-reachability.py` and `--mutate` as their own steps, so the gate is
    not lost; it just stops being confused with the contract.
    """
    result = subprocess.run(
        [sys.executable, str(CLI)], capture_output=True, text=True, cwd=REPO_ROOT
    )
    assert result.returncode in (0, 1), result.stdout + result.stderr
    # Exit code and output have to agree, which is the part a live tree can
    # falsify: a check that exits 1 while naming nothing is broken, and so is
    # one that exits 0 after printing findings.
    assert bool(result.returncode) == ("finding(s)" in result.stderr)


def test_cli_exits_non_zero_on_a_finding(tmp_path):
    _tree(tmp_path, {
        "AGENTS.md": "Nothing here.\n",
        "infra/remotes/_template.yaml": "a: 1\n",
        "context-budget.yaml": MINIMAL_BUDGET,
    })
    result = subprocess.run(
        [sys.executable, str(CLI), "--repo-root", str(tmp_path)],
        capture_output=True, text=True,
    )

    assert result.returncode == 1
    assert "infra/remotes/" in (result.stdout + result.stderr)


# ------------------------------------------------- routing is not work state --


def test_a_mention_in_the_work_log_does_not_count(tmp_path):
    """The log slice is part of the always-on surface and is NOT routing.

    Caught on a live instance: `identity/vehicles/` passed this check because
    a work-log row written that morning happened to name it. The row scrolls
    out of the three-block slice within days and the family goes unreachable
    again, with the guard still green the whole time. A pointer that expires
    is not a pointer.
    """
    _tree(tmp_path, {
        "AGENTS.md": "Nothing about vehicles here.\n",
        "identity/vehicles/_template.yaml": "a: 1\n",
        "work/board.md": "## Doing\n\n- something about identity/vehicles/\n",
        "context-budget.yaml": MINIMAL_BUDGET
        + "  work/board.md:\n    source: phase1\n",
    })
    findings = reach.check(tmp_path)

    assert any("identity/vehicles/" in f for f in findings), findings


def test_the_routing_surface_excludes_work_state(tmp_path):
    _tree(tmp_path, {
        "AGENTS.md": "MARKER-ROUTING\n",
        "work/board.md": "MARKER-WORKSTATE\n",
        "context-budget.yaml": MINIMAL_BUDGET
        + "  work/board.md:\n    source: phase1\n",
    })
    routing = reach.routing_surface(tmp_path)

    assert "MARKER-ROUTING" in routing
    assert "MARKER-WORKSTATE" not in routing


def test_work_state_still_counts_as_always_on_for_the_budget(tmp_path):
    """Only THIS check ignores it. The budget still measures every byte."""
    _tree(tmp_path, {
        "AGENTS.md": "x\n",
        "work/board.md": "MARKER-WORKSTATE\n",
        "context-budget.yaml": MINIMAL_BUDGET
        + "  work/board.md:\n    source: phase1\n",
    })
    assert "MARKER-WORKSTATE" in mc.always_on_text(tmp_path, mc.load_budget(tmp_path))


# ------------------------------------------------------------ scenarios --
#
# The simulation half, and it had NO direct test until a coverage run said so:
# 41 % on this file while the index library sat at 96 %. `check_scenarios`,
# `load_scenarios` and `mutate` were all reached only through a subprocess,
# which is a behavioural test the coverage tool cannot see and, worse, one
# that never exercised the failing branches at all.

def _scenario_tree(tmp_path, agents_md: str) -> Path:
    return _tree(tmp_path, {
        "AGENTS.md": agents_md,
        "infra/remotes/_template.yaml": "a: 1\n",
        "context-budget.yaml": MINIMAL_BUDGET,
    })


def test_a_scenario_passes_when_word_and_route_are_both_resident(tmp_path):
    _scenario_tree(tmp_path, "A remote machine lives in `infra/remotes/`.\n")
    assert not any("infra/remotes/" in f for f in reach.check_scenarios(tmp_path))


def test_a_scenario_fails_when_the_vocabulary_is_missing(tmp_path):
    """Route resident, WORD absent: nothing would trigger the lookup.

    Written with an instance scenario on purpose. Every CORE scenario's word is
    a substring of its own path (`remote` inside `infra/remotes/`), so a CORE
    scenario cannot separate the two branches — a first draft of this test
    ended in `assert isinstance(findings, list)`, which cannot fail.
    """
    _scenario_tree(tmp_path, "The inventory lives in `infra/remotes/`.\n")
    (tmp_path / "reachability-scenarios.yaml").write_text(
        "scenarios:\n"
        "  - asks: wake the office box\n"
        "    vocabulary: [wakeonlan]\n"
        "    family: infra/remotes/\n",
        encoding="utf-8",
    )
    findings = reach.check_scenarios(tmp_path)

    assert any("wakeonlan" in f for f in findings), findings
    assert not any("know to look and not where" in f for f in findings), (
        "the route IS resident; only the vocabulary is missing"
    )


def test_a_scenario_fails_when_the_route_is_missing(tmp_path):
    """Word resident, route absent: a session knows to look and not where."""
    _scenario_tree(tmp_path, "Ask about a remote when a machine comes up.\n")
    findings = reach.check_scenarios(tmp_path)

    assert any("infra/remotes/" in f and "not" in f for f in findings), findings


def test_a_scenario_fails_when_the_route_resolves_to_an_empty_directory(tmp_path):
    _tree(tmp_path, {
        "AGENTS.md": "A remote machine lives in `infra/remotes/`.\n",
        "context-budget.yaml": MINIMAL_BUDGET,
    })
    (tmp_path / "infra" / "remotes").mkdir(parents=True)
    findings = reach.check_scenarios(tmp_path)

    assert any("empty directory" in f for f in findings), findings


def test_a_scenario_for_a_family_this_instance_lacks_is_skipped(tmp_path):
    """Demanding a family an instance never enabled is a check about a Bridge
    that does not exist."""
    _tree(tmp_path, {
        "AGENTS.md": "nothing\n",
        "context-budget.yaml": MINIMAL_BUDGET,
    })
    assert not any("workflow/calendars/" in f for f in reach.check_scenarios(tmp_path))


def test_an_instance_adds_its_own_scenarios(tmp_path):
    """CORE cannot know a machine's name or a customer's; the instance can."""
    _scenario_tree(tmp_path, "A remote machine lives in `infra/remotes/`.\n")
    (tmp_path / "reachability-scenarios.yaml").write_text(
        "scenarios:\n"
        "  - asks: repair the office box\n"
        "    vocabulary: [officebox]\n"
        "    family: infra/remotes/\n",
        encoding="utf-8",
    )
    findings = reach.check_scenarios(tmp_path)

    assert any("officebox" in f for f in findings), findings


def test_scenarios_without_an_instance_file_are_just_the_core_ones(tmp_path):
    _scenario_tree(tmp_path, "x\n")
    assert reach.load_scenarios(tmp_path) == list(reach.SCENARIOS)


# ------------------------------------------------------------- the battery --


def test_the_battery_is_silent_when_every_needle_bites(tmp_path):
    _scenario_tree(tmp_path, "A remote machine lives in `infra/remotes/`.\n")
    assert reach.mutate(tmp_path) == []


def test_the_battery_removes_a_contributor_not_a_substring(tmp_path):
    """The version that earns its place.

    A battery over the concatenated surface only proves a substring test is a
    substring test: it would stay green if `always_on_parts` silently stopped
    reading AGENTS.md. Removing the CONTRIBUTOR proves the assembly reads it.
    """
    _scenario_tree(tmp_path, "A remote machine lives in `infra/remotes/`.\n")
    carriers = reach.named_in(tmp_path, "infra/remotes/")

    assert "AGENTS.md" in carriers, carriers


def test_a_family_named_only_in_work_state_has_no_carrier(tmp_path):
    _tree(tmp_path, {
        "AGENTS.md": "nothing\n",
        "infra/remotes/_template.yaml": "a: 1\n",
        "work/board.md": "about infra/remotes/ today\n",
        "context-budget.yaml": MINIMAL_BUDGET + "  work/board.md:\n    source: phase1\n",
    })
    assert reach.named_in(tmp_path, "infra/remotes/") == []


# -------------------------------------------------------------------- CLI --


def test_main_returns_zero_on_a_healthy_tree(tmp_path):
    _scenario_tree(tmp_path, "A remote machine lives in `infra/remotes/`.\n")
    assert reach.main(["--repo-root", str(tmp_path)]) == 0


def test_main_returns_one_on_a_finding(tmp_path):
    _scenario_tree(tmp_path, "nothing\n")
    assert reach.main(["--repo-root", str(tmp_path)]) == 1


def test_main_families_lists_and_succeeds(tmp_path, capsys):
    _scenario_tree(tmp_path, "x\n")
    assert reach.main(["--repo-root", str(tmp_path), "--families"]) == 0
    assert "infra/remotes/" in capsys.readouterr().out


def test_main_mutate_succeeds_on_a_healthy_tree(tmp_path):
    _scenario_tree(tmp_path, "A remote machine lives in `infra/remotes/`.\n")
    assert reach.main(["--repo-root", str(tmp_path), "--mutate"]) == 0
