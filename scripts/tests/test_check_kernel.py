"""scripts/check-kernel.py: the kernel manifest must say the truth.

`kernel/manifest.yaml` names every file, command and injected listing a session
reads before its first answer, plus the files that define that set: where each
lives (and at which tier), when it is read, which file links or instructs it,
and who sees it (session, sub-agent). The specification is `docs/kernel.md`.

Each test below breaks one promise on a small synthetic tree and expects the
checker to name it. A contradiction the project already knows about is not
hidden: an entry carries a `debt:` that the report prints on every run, and a
debt whose contradiction is gone is itself a finding, so the list only shrinks.

Run: python3 -m pytest scripts/tests/test_check_kernel.py -q
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]


def _load():
    spec = importlib.util.spec_from_file_location("check_kernel", REPO / "scripts" / "check-kernel.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["check_kernel"] = mod  # dataclasses resolve their module through sys.modules
    spec.loader.exec_module(mod)
    return mod


ck = _load()

FAMILIES = [
    {"path": "identity/agent/", "read": "start"},
    {"path": "rules/", "read": "start"},
    {"path": "docs/", "read": "named"},
    {"path": "work/", "read": "start"},
]

TIERS = {
    "AGENTS.md": "core",
    "docs/index.md": "core",
    "identity/agent/SOUL.md": "user",
    "rules/session-start.md": "core",
    "work/board.md": "user",
    "kernel/manifest.yaml": "core",
}


def _write(root: pathlib.Path, rel: str, text: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _tree(tmp_path: pathlib.Path) -> pathlib.Path:
    _write(tmp_path, "AGENTS.md",
           "# Manual\n\n@docs/index.md\n@identity/agent/SOUL.md\n\n"
           "Run Phase 0 from `rules/session-start.md`, then read `work/board.md`\n"
           "and run `python3 scripts/worklog.py --recent 3`.\n")
    _write(tmp_path, "docs/index.md", "# Index\n")
    _write(tmp_path, "rules/session-start.md", "# Phase 0\n")
    _write(tmp_path, "kernel/manifest.yaml", "schema_version: 1\n")
    _write(tmp_path, "scripts/meter.py", "MANIFEST = 'kernel/manifest.yaml'\n")
    return tmp_path


def _entries() -> list[dict]:
    return [
        {"path": "AGENTS.md", "tier": "core", "role": "entry", "read": "import",
         "via": ["harness"], "reaches": ["session", "subagent"]},
        {"path": "docs/index.md", "tier": "core", "role": "index", "read": "import",
         "via": ["AGENTS.md"], "reaches": ["session", "subagent"],
         "debt": {"kind": "placement", "reason": "an always-on file in a named folder",
                  "until": "step 2"}},
        {"path": "identity/agent/SOUL.md", "tier": "user", "role": "voice", "read": "import",
         "via": ["AGENTS.md"], "reaches": ["session", "subagent"], "optional": True},
        {"path": "rules/session-start.md", "tier": "core", "role": "gate", "read": "start",
         "via": ["AGENTS.md"], "reaches": ["session"],
         "debt": {"kind": "unmeasured", "reason": "not in the budget", "until": "step 2"}},
        {"path": "work/board.md", "tier": "user", "role": "state", "read": "start",
         "via": ["AGENTS.md"], "reaches": ["session"], "optional": True},
        {"command": "python3 scripts/worklog.py --recent 3", "tier": "user", "role": "state",
         "read": "command", "via": ["AGENTS.md"], "reaches": ["session"]},
        {"harness": "listing:skills", "tier": "mixed", "role": "listing", "read": "harness",
         "via": ["harness"], "reaches": ["session", "subagent"]},
        {"path": "kernel/manifest.yaml", "tier": "core", "role": "manifest", "read": "tool",
         "via": ["scripts/meter.py"], "reaches": []},
    ]


def _ctx(root, entries=None, **over):
    base = dict(
        root=root,
        entries=_entries() if entries is None else entries,
        meter={"AGENTS.md": "import", "docs/index.md": "import", "identity/agent/SOUL.md": "import",
               "work/board.md": "phase1", "cmd:python3 scripts/worklog.py --recent 3": "phase1",
               "listing:skills": "listing"},
        instance_declared=set(),
        imports={"docs/index.md", "identity/agent/SOUL.md"},
        families=FAMILIES,
        tier_of=lambda p: TIERS.get(p, "user"),
        kernel_files=["kernel/manifest.yaml"],
        core_checkout=True,
    )
    base.update(over)
    return ck.Context(**base)


def _problems(ctx) -> list[str]:
    return ck.evaluate(ctx).problems


def test_a_true_manifest_is_clean_and_prints_its_debts(tmp_path):
    report = ck.evaluate(_ctx(_tree(tmp_path)))
    assert report.problems == []
    assert any("docs/index.md" in d and "placement" in d for d in report.debts)
    assert any("rules/session-start.md" in d and "unmeasured" in d for d in report.debts)


# -------------------------------------------------------------- schema --

@pytest.mark.parametrize("broken,needle", [
    ({"path": "AGENTS.md", "command": "x"}, "exactly one of"),
    ({"tier": "public"}, "tier"),
    ({"read": "sometimes"}, "read"),
    ({"reaches": ["everyone"]}, "reaches"),
    ({"colour": "blue"}, "unknown key"),
])
def test_a_malformed_entry_is_named(tmp_path, broken, needle):
    entries = _entries()
    entries[0] = {**entries[0], **broken}
    found = _problems(_ctx(_tree(tmp_path), entries))
    assert any(needle in p for p in found), found


@pytest.mark.parametrize("index", [1, 4])  # a path entry, then another path entry
def test_mixed_is_only_for_what_is_assembled_at_run_time(tmp_path, index):
    # A file has exactly one tier. Only a listing or a command's output, built
    # from several tiers when the session starts, may say `mixed`.
    entries = _entries()
    entries[index]["tier"] = "mixed"
    found = _problems(_ctx(_tree(tmp_path), entries))
    assert any("mixed" in p for p in found), found


def test_a_glob_has_one_tier_too(tmp_path):
    entries = _entries() + [{"glob": "protocols/standing-orders/*.md", "tier": "mixed",
                             "role": "order", "read": "start", "via": ["AGENTS.md"],
                             "reaches": ["session"]}]
    assert any("mixed" in p for p in _problems(_ctx(_tree(tmp_path), entries)))


def test_an_entry_without_via_is_named(tmp_path):
    entries = _entries()
    del entries[4]["via"]
    assert any("via" in p for p in _problems(_ctx(_tree(tmp_path), entries)))


# ----------------------------------------------------- where it lives --

def test_a_missing_required_file_is_named(tmp_path):
    root = _tree(tmp_path)
    (root / "rules" / "session-start.md").unlink()
    assert any("rules/session-start.md" in p and "missing" in p for p in _problems(_ctx(root)))


def test_an_absent_optional_file_is_fine(tmp_path):
    assert _problems(_ctx(_tree(tmp_path))) == []


def test_a_file_expected_absent_that_exists_is_named(tmp_path):
    root = _tree(tmp_path)
    _write(root, "CLAUDE.md", "# legacy\n")
    entries = _entries() + [{"path": "CLAUDE.md", "tier": "user", "role": "legacy entry",
                             "read": "import", "via": ["harness"], "reaches": ["session"],
                             "expect": "absent"}]
    found = _problems(_ctx(root, entries))
    assert any("CLAUDE.md" in p and "absent" in p for p in found), found


def test_a_tier_the_router_disagrees_with_is_named(tmp_path):
    entries = _entries()
    entries[1]["tier"] = "user"
    found = _problems(_ctx(_tree(tmp_path), entries))
    assert any("docs/index.md" in p and "router" in p for p in found), found


def test_a_user_tier_file_present_in_a_core_checkout_is_named(tmp_path):
    root = _tree(tmp_path)
    _write(root, "work/board.md", "# Board\n")
    found = _problems(_ctx(root))
    assert any("work/board.md" in p and "CORE checkout" in p for p in found), found


def test_the_same_file_in_an_instance_is_fine(tmp_path):
    root = _tree(tmp_path)
    _write(root, "work/board.md", "# Board\n")
    assert _problems(_ctx(root, core_checkout=False)) == []


def test_a_stray_file_in_kernel_is_named(tmp_path):
    found = _problems(_ctx(_tree(tmp_path), kernel_files=["kernel/manifest.yaml", "kernel/notes.md"]))
    assert any("kernel/notes.md" in p for p in found), found


# ------------------------------------------------ when it is read --

def test_an_import_the_manifest_does_not_know_is_named(tmp_path):
    found = _problems(_ctx(_tree(tmp_path), imports={"docs/index.md", "identity/agent/SOUL.md",
                                                     "docs/extra.md"}))
    assert any("docs/extra.md" in p and "import" in p for p in found), found


def test_a_declared_import_that_nothing_imports_is_named(tmp_path):
    root = _tree(tmp_path)
    _write(root, "identity/agent/SOUL.md", "# Soul\n")
    found = _problems(_ctx(root, imports={"docs/index.md"}, core_checkout=False))
    assert any("identity/agent/SOUL.md" in p and "@-line" in p for p in found), found


def test_an_always_on_item_the_manifest_does_not_describe_is_named(tmp_path):
    ctx = _ctx(_tree(tmp_path))
    ctx.meter["cmd:python3 scripts/other.py"] = "phase1"
    found = _problems(ctx)
    assert any("cmd:python3 scripts/other.py" in p for p in found), found


def test_an_item_the_instance_declares_itself_is_not_a_finding(tmp_path):
    ctx = _ctx(_tree(tmp_path), core_checkout=False)
    ctx.meter["cmd:python3 scripts/own.py"] = "phase1"
    ctx.instance_declared.add("cmd:python3 scripts/own.py")
    assert _problems(ctx) == []


def test_an_import_the_instance_adds_and_caps_itself_is_not_a_finding(tmp_path):
    # AGENTS.md lets INSTANCE.md import more; the instance caps those files in
    # context-budget.user.yaml and never edits the CORE manifest.
    root = _tree(tmp_path)
    ctx = _ctx(root, core_checkout=False,
               imports={"docs/index.md", "identity/agent/SOUL.md", "identity/agent/TEAM.md"})
    ctx.meter["identity/agent/TEAM.md"] = "import"
    ctx.instance_declared.add("identity/agent/TEAM.md")
    assert _problems(ctx) == []
    ctx.instance_declared.discard("identity/agent/TEAM.md")
    assert any("identity/agent/TEAM.md" in p for p in _problems(ctx))


def test_a_glob_match_of_another_tier_in_a_core_checkout_is_named(tmp_path):
    root = _tree(tmp_path)
    _write(root, "ecosystem.acme.yaml", "x: 1\n")
    _write(root, "AGENTS.md", (root / "AGENTS.md").read_text() + "Fragments: `ecosystem.<name>.yaml`.\n")
    glob = {"glob": "ecosystem.*.yaml", "tier": "org", "role": "fragments", "read": "start",
            "via": ["AGENTS.md"], "reaches": ["session"], "optional": True}
    ctx = _ctx(root, _entries() + [glob],
               tier_of=lambda p: "org" if p.startswith("ecosystem.") else TIERS.get(p, "user"))
    ctx.meter["ecosystem.acme.yaml"] = "phase1"
    found = _problems(ctx)
    assert any("ecosystem.acme.yaml" in p and "CORE checkout" in p for p in found), found
    ctx.core_checkout = False
    assert _problems(ctx) == []


def test_a_hard_linked_legacy_entry_file_is_not_a_shadow_either(tmp_path):
    import os
    root = _tree(tmp_path)
    os.link(root / "AGENTS.md", root / "CLAUDE.md")
    entries = _entries() + [{"path": "CLAUDE.md", "tier": "user", "role": "legacy entry",
                             "read": "import", "via": ["harness"], "reaches": ["session", "subagent"],
                             "expect": "absent"}]
    assert not any("CLAUDE.md" in p for p in _problems(_ctx(root, entries)))


def test_a_legacy_entry_file_that_links_to_agents_md_is_not_a_shadow(tmp_path):
    root = _tree(tmp_path)
    (root / "CLAUDE.md").symlink_to("AGENTS.md")
    entries = _entries() + [{"path": "CLAUDE.md", "tier": "user", "role": "legacy entry",
                             "read": "import", "via": ["harness"], "reaches": ["session", "subagent"],
                             "expect": "absent"}]
    found = _problems(_ctx(root, entries))
    assert not any("CLAUDE.md" in p for p in found), found


def test_a_glob_entry_covers_what_it_matches_and_nothing_deeper(tmp_path):
    root = _tree(tmp_path)
    _write(root, "protocols/standing-orders/a.md", "x")
    entries = _entries() + [{"glob": "protocols/standing-orders/*.md", "tier": "core",
                             "role": "order", "read": "start", "via": ["AGENTS.md"],
                             "reaches": ["session"]}]
    ctx = _ctx(root, entries, tier_of=lambda p: "core" if p.startswith("protocols/") else TIERS.get(p, "user"))
    ctx.meter["protocols/standing-orders/a.md"] = "standing-order"
    ctx.meter["protocols/standing-orders/user/b.md"] = "standing-order"
    found = _problems(ctx)
    assert not any("standing-orders/a.md" in p for p in found), found
    assert any("standing-orders/user/b.md" in p for p in found), found


def test_an_optional_file_the_instance_has_must_be_counted(tmp_path):
    root = _tree(tmp_path)
    _write(root, "work/board.md", "# Board\n")
    ctx = _ctx(root, core_checkout=False)
    del ctx.meter["work/board.md"]
    found = _problems(ctx)
    assert any("work/board.md" in p and "unmeasured" in p for p in found), found


def test_an_always_on_entry_the_meter_does_not_count_is_unmeasured(tmp_path):
    entries = _entries()
    del entries[3]["debt"]
    found = _problems(_ctx(_tree(tmp_path), entries))
    assert any("rules/session-start.md" in p and "unmeasured" in p for p in found), found


def test_an_always_on_file_in_a_named_folder_is_a_placement_finding(tmp_path):
    entries = _entries()
    del entries[1]["debt"]
    found = _problems(_ctx(_tree(tmp_path), entries))
    assert any("docs/index.md" in p and "placement" in p for p in found), found


# ------------------------------------------------- how it is linked --

def test_a_via_file_that_never_names_the_entry_is_named(tmp_path):
    entries = _entries()
    entries[5]["command"] = "python3 scripts/worklog.py --recent 9"
    ctx = _ctx(_tree(tmp_path), entries)
    ctx.meter["cmd:python3 scripts/worklog.py --recent 9"] = "phase1"
    found = _problems(ctx)
    assert any("--recent 9" in p and "AGENTS.md" in p for p in found), found


def test_an_import_whose_via_has_no_at_line_is_named(tmp_path):
    entries = _entries()
    entries[1]["via"] = ["rules/session-start.md"]
    found = _problems(_ctx(_tree(tmp_path), entries))
    assert any("docs/index.md" in p and "@-line" in p for p in found), found


def test_a_via_file_that_does_not_exist_is_named(tmp_path):
    entries = _entries()
    entries[7]["via"] = ["scripts/gone.py"]
    found = _problems(_ctx(_tree(tmp_path), entries))
    assert any("scripts/gone.py" in p for p in found), found


# ------------------------------------------------------ who sees it --

def test_a_phase_read_that_claims_to_reach_sub_agents_is_named(tmp_path):
    entries = _entries()
    entries[4]["reaches"] = ["session", "subagent"]
    found = _problems(_ctx(_tree(tmp_path), entries))
    assert any("work/board.md" in p and "sub-agent" in p for p in found), found


def test_an_import_that_hides_from_sub_agents_is_named(tmp_path):
    entries = _entries()
    entries[1]["reaches"] = ["session"]
    found = _problems(_ctx(_tree(tmp_path), entries))
    assert any("docs/index.md" in p and "sub-agent" in p for p in found), found


def test_exclude_keeps_a_template_out_of_a_glob(tmp_path):
    root = _tree(tmp_path)
    _write(root, "ecosystem.example.yaml", "x: 1\n")
    _write(root, "AGENTS.md", (root / "AGENTS.md").read_text() + "Registries: `ecosystem.yaml`.\n")
    glob = {"glob": "ecosystem.*.yaml", "tier": "org", "role": "fragments", "read": "start",
            "via": ["AGENTS.md"], "reaches": ["session"], "optional": True}
    without = _problems(_ctx(root, _entries() + [glob]))
    assert any("ecosystem.*.yaml" in p and "unmeasured" in p for p in without), without
    assert _problems(_ctx(root, _entries() + [{**glob, "exclude": ["ecosystem.example.yaml"]}])) == []


def test_exclude_on_a_path_entry_is_named(tmp_path):
    entries = _entries()
    entries[4]["exclude"] = ["x"]
    assert any("exclude" in p for p in _problems(_ctx(_tree(tmp_path), entries)))


# --------------------------------------------------------------- debts --

def test_a_debt_whose_contradiction_is_gone_is_stale(tmp_path):
    # docs/ read at start: the placement contradiction no longer exists.
    families = [dict(r, read="start") if r["path"] == "docs/" else r for r in FAMILIES]
    found = _problems(_ctx(_tree(tmp_path), families=families))
    assert any("stale" in p and "placement" in p and "docs/index.md" in p for p in found), found


def test_an_unknown_debt_kind_is_named(tmp_path):
    entries = _entries()
    entries[1]["debt"]["kind"] = "whatever"
    assert any("debt" in p for p in _problems(_ctx(_tree(tmp_path), entries)))


def test_a_debt_needs_a_reason_and_an_until(tmp_path):
    entries = _entries()
    entries[1]["debt"] = {"kind": "placement"}
    found = _problems(_ctx(_tree(tmp_path), entries))
    assert any("reason" in p for p in found) and any("until" in p for p in found), found


# ---------------------------------------------------------- live tree --

def test_the_live_manifest_is_true():
    report = ck.evaluate(ck.gather(REPO))
    assert report.problems == [], "\n".join(report.problems)


def test_the_live_manifest_lists_the_families_index_as_a_debt_until_it_moves():
    report = ck.evaluate(ck.gather(REPO))
    assert any("docs/families.md" in d for d in report.debts) or not (REPO / "docs" / "families.md").exists()
