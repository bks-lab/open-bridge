#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Pytest suite for scripts/learning-ledger.py and the proposal schema.

CONTRACT, this file is the authoritative spec for that surface.

WHY THIS EXISTS. The learning loop (`work/_learning/`, `/bridge-learn`) kept
its state in three places that nothing held together: the folder a proposal
file sits in, the `status:` in its own frontmatter, and the row an agent typed
into `audit-trail.md` by hand. `scripts/learning-ledger.py` is the one writer
and checker for that state:

    fingerprint <id>        store `recurrence_fingerprint` on an implemented
                            proposal: `<target.path>#<id without its date>`.
    recurrences [--json]    implemented proposals whose target.path shows up
                            again later (a newer proposal, a postmortem, an
                            audit-history file), listed as `recurred: <date>`.
                            Evidence only; never changes a status.

Tests build a throwaway Bridge root under `tmp_path` and pass it with
`--root`, never touching the real repo's `work/_learning/`.
"""

from __future__ import annotations

import importlib.util
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = REPO_ROOT / "scripts" / "learning-ledger.py"
CANONICAL_SCHEMA = REPO_ROOT / "work" / "_learning" / "_schema.proposal.yaml"
SKILL_SCHEMA = (REPO_ROOT / "skills" / "task-close-postmortem" / "references"
                / "_schema.proposal.yaml")


def _load(path: Path, name: str) -> types.ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # dataclasses resolve their module by name
    previous = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        spec.loader.exec_module(module)
    finally:
        sys.dont_write_bytecode = previous
    return module


ll = _load(SCRIPT, "learning_ledger_under_test")


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def bridge_root(tmp_path: Path) -> Path:
    root = tmp_path / "bridge"
    learning = root / "work" / "_learning"
    for sub in ("proposals/accepted", "proposals/rejected", "postmortems", "audit-history"):
        (learning / sub).mkdir(parents=True)
    (learning / "audit-trail.md").write_text(
        "# Learning Audit-Trail\n\n"
        "| Timestamp | Proposal ID | Transition | Reason | Commit |\n"
        "|---|---|---|---|---|\n",
        encoding="utf-8",
    )
    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.email", "t@example.com"], cwd=root, check=True)
    subprocess.run(["git", "config", "user.name", "T"], cwd=root, check=True)
    return root


def proposal(root: Path, pid: str, *, folder: str = "", status: str = "pending",
             target_path: str = "skills/demo/SKILL.md", target_type: str = "skill",
             created: str | None = None, extra: dict | None = None, body: str = "Body.\n") -> Path:
    data = {
        "id": pid,
        "created": created or pid[:10],
        "source": {"type": "postmortem", "task_slug": "demo-task",
                   "evidence": ["work/done/2026-01/demo-task/STATUS.md"]},
        "severity": "P2",
        "status": status,
        "scope": "core",
        "target": {"type": target_type, "path": target_path, "action": "edit"},
        "proposal_type": "structured",
    }
    data.update(extra or {})
    directory = root / "work" / "_learning" / "proposals" / folder
    path = directory / f"{pid}.md"
    path.write_text("---\n" + yaml.safe_dump(data, sort_keys=False) + "---\n\n" + body,
                    encoding="utf-8")
    return path


def trail_rows(root: Path) -> list[str]:
    text = (root / "work" / "_learning" / "audit-trail.md").read_text(encoding="utf-8")
    return [line for line in text.splitlines()
            if line.startswith("| 2") or line.startswith("| %")]


def frontmatter(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8").split("---", 2)[1])


# ---------------------------------------------------------------------------
# Schema (#202): one definition, verification optional, lifecycle fields
# ---------------------------------------------------------------------------

def _validator():
    # CI installs jsonschema for this suite; a skip here only hides the schema
    # half on a machine without it, never the ledger half below.
    jsonschema = pytest.importorskip("jsonschema")
    schema = yaml.safe_load(CANONICAL_SCHEMA.read_text(encoding="utf-8"))
    return jsonschema.Draft202012Validator(schema)


def _base() -> dict:
    return {
        "id": "2026-01-02-demo-task-tighten-trigger",
        "created": "2026-01-02",
        "source": {"type": "postmortem", "evidence": ["work/done/x/STATUS.md"]},
        "severity": "P2",
        "status": "pending",
        "scope": "core",
        "target": {"type": "skill", "path": "skills/demo/SKILL.md", "action": "edit"},
        "proposal_type": "structured",
    }


def test_schema_accepts_a_proposal_without_verification():
    assert list(_validator().iter_errors(_base())) == []


def test_schema_accepts_a_verification_block():
    data = _base()
    data["verification"] = {"kind": "deterministic", "command": "pytest -q",
                            "before": "3 failed", "after": "0 failed"}
    assert list(_validator().iter_errors(data)) == []


def test_schema_rejects_an_unknown_verification_kind():
    data = _base()
    data["verification"] = {"kind": "vibes"}
    assert list(_validator().iter_errors(data))


def test_schema_accepts_the_lifecycle_fields_the_review_workflow_writes():
    data = _base()
    data.update({"status": "rejected", "rejected_at": "2026-01-03",
                 "reject_reason": "covered elsewhere"})
    assert list(_validator().iter_errors(data)) == []
    data = _base()
    data.update({"status": "implemented", "accepted_at": "2026-01-03",
                 "implemented_commit": "4f3a2b1",
                 "recurrence_fingerprint": "skills/demo/SKILL.md#demo-task-tighten-trigger"})
    assert list(_validator().iter_errors(data)) == []
    data = _base()
    data.update({"status": "deferred", "deferred_at": "2026-01-03",
                 "defer_until": "phase-3", "defer_reason": ""})
    assert list(_validator().iter_errors(data)) == []


def test_schema_accepts_the_capability_gap_source_the_broker_writes():
    data = _base()
    data["source"]["type"] = "capability-gap"
    assert list(_validator().iter_errors(data)) == []


def test_schema_still_refuses_an_undeclared_field():
    data = _base()
    data["mood"] = "optimistic"
    assert list(_validator().iter_errors(data))


def test_the_skill_copy_is_a_pointer_not_a_second_definition():
    pointer = yaml.safe_load(SKILL_SCHEMA.read_text(encoding="utf-8"))
    assert "properties" not in pointer
    assert "verification" not in SKILL_SCHEMA.read_text(encoding="utf-8")
    target = (SKILL_SCHEMA.parent / pointer["$ref"]).resolve()
    assert target == CANONICAL_SCHEMA.resolve()


# ---------------------------------------------------------------------------
# fingerprint / recurrences (#202)
# ---------------------------------------------------------------------------


def test_fingerprint_stores_target_path_and_gap_slug(tmp_path):
    root = bridge_root(tmp_path)
    path = proposal(root, "2026-01-02-demo-task-tighten-trigger", folder="accepted",
                    status="implemented")

    assert ll.main(["--root", str(root), "fingerprint",
                    "2026-01-02-demo-task-tighten-trigger"]) == 0
    assert frontmatter(path)["recurrence_fingerprint"] == \
        "skills/demo/SKILL.md#demo-task-tighten-trigger"
    assert path.read_text(encoding="utf-8").endswith("Body.\n")


def test_fingerprint_is_idempotent(tmp_path):
    root = bridge_root(tmp_path)
    path = proposal(root, "2026-01-02-demo-task-tighten-trigger", folder="accepted",
                    status="implemented")
    for _ in range(2):
        assert ll.main(["--root", str(root), "fingerprint",
                        "2026-01-02-demo-task-tighten-trigger"]) == 0
    assert path.read_text(encoding="utf-8").count("recurrence_fingerprint") == 1


def test_fingerprint_refuses_a_proposal_that_is_not_implemented(tmp_path, capsys):
    root = bridge_root(tmp_path)
    path = proposal(root, "2026-01-02-demo-task-tighten-trigger")

    assert ll.main(["--root", str(root), "fingerprint",
                    "2026-01-02-demo-task-tighten-trigger"]) == 2
    assert "recurrence_fingerprint" not in path.read_text(encoding="utf-8")


def _implemented(root, pid="2026-01-02-demo-task-tighten-trigger", on="2026-01-05"):
    proposal(root, pid, folder="accepted", status="implemented",
             extra={"accepted_at": on,
                    "recurrence_fingerprint": f"skills/demo/SKILL.md#{pid[11:]}"})


def test_recurrences_flags_a_later_proposal_on_the_same_target(tmp_path, capsys):
    root = bridge_root(tmp_path)
    _implemented(root)
    proposal(root, "2026-02-01-other-task-trigger-again")

    capsys.readouterr()
    assert ll.main(["--root", str(root), "recurrences", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data == [{"id": "2026-01-02-demo-task-tighten-trigger",
                     "fingerprint": "skills/demo/SKILL.md#demo-task-tighten-trigger",
                     "recurred": "2026-02-01",
                     "evidence": "work/_learning/proposals/2026-02-01-other-task-trigger-again.md"}]


def test_recurrences_flags_a_later_postmortem_naming_the_target(tmp_path, capsys):
    root = bridge_root(tmp_path)
    _implemented(root)
    (root / "work" / "_learning" / "postmortems" / "2026-03-04-some-task.md").write_text(
        "Burned time in skills/demo/SKILL.md again.\n", encoding="utf-8")

    capsys.readouterr()
    assert ll.main(["--root", str(root), "recurrences"]) == 0
    out = capsys.readouterr().out
    assert "recurred: 2026-03-04" in out
    assert "2026-01-02-demo-task-tighten-trigger" in out


def test_recurrences_ignores_evidence_from_before_the_fix(tmp_path, capsys):
    root = bridge_root(tmp_path)
    _implemented(root)
    proposal(root, "2026-01-01-older-task-same-target", folder="rejected", status="rejected")
    (root / "work" / "_learning" / "audit-history" / "2026-01-04.md").write_text(
        "skills/demo/SKILL.md drift\n", encoding="utf-8")

    capsys.readouterr()
    assert ll.main(["--root", str(root), "recurrences", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_recurrences_ignores_a_different_target(tmp_path, capsys):
    root = bridge_root(tmp_path)
    _implemented(root)
    proposal(root, "2026-02-01-other-task-other-file", target_path="skills/other/SKILL.md")

    capsys.readouterr()
    assert ll.main(["--root", str(root), "recurrences", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_recurrences_never_changes_a_status(tmp_path):
    root = bridge_root(tmp_path)
    _implemented(root)
    later = proposal(root, "2026-02-01-other-task-trigger-again")
    before = sorted(p.read_text(encoding="utf-8")
                    for p in (root / "work" / "_learning").rglob("*.md"))

    assert ll.main(["--root", str(root), "recurrences"]) == 0
    after = sorted(p.read_text(encoding="utf-8")
                   for p in (root / "work" / "_learning").rglob("*.md"))
    assert before == after
    assert frontmatter(later)["status"] == "pending"


# ---------------------------------------------------------------------------
# prior-rejections (#204): writers consult rejected/ before writing
# ---------------------------------------------------------------------------


def test_schema_accepts_prior_rejections_and_the_audit_fingerprint():
    data = _base()
    data["prior_rejections"] = [{"id": "2026-01-01-fixture-topic", "reason": "parent task failed"}]
    data["source"]["fingerprint"] = "3f2a8b1c" * 8
    assert list(_validator().iter_errors(data)) == []
    data["prior_rejections"] = [{"id": "2026-01-01-fixture-topic"}]
    assert list(_validator().iter_errors(data)), "reason is required in a citation"


def _rejected_fixture(root):
    return proposal(root, "2026-01-01-fixture-topic", folder="rejected", status="rejected",
                    target_path="skills/fixture-skill/SKILL.md",
                    extra={"rejected_at": "2026-01-01", "reject_reason": "parent task failed"})


def test_prior_rejections_finds_a_rejection_on_the_same_target_path(tmp_path, capsys):
    root = bridge_root(tmp_path)
    _rejected_fixture(root)

    capsys.readouterr()
    assert ll.main(["--root", str(root), "prior-rejections",
                    "skills/fixture-skill/SKILL.md", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == [
        {"id": "2026-01-01-fixture-topic", "reason": "parent task failed"}]


def test_prior_rejections_ignores_a_different_target_even_with_the_same_task(tmp_path, capsys):
    root = bridge_root(tmp_path)
    _rejected_fixture(root)  # source.task_slug is demo-task

    capsys.readouterr()
    assert ll.main(["--root", str(root), "prior-rejections",
                    "skills/other-skill/SKILL.md", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_prior_rejections_ignores_pending_and_accepted_proposals(tmp_path, capsys):
    root = bridge_root(tmp_path)
    proposal(root, "2026-01-01-pending-topic", target_path="skills/fixture-skill/SKILL.md")
    proposal(root, "2026-01-01-accepted-topic", folder="accepted", status="implemented",
             target_path="skills/fixture-skill/SKILL.md")

    capsys.readouterr()
    assert ll.main(["--root", str(root), "prior-rejections",
                    "skills/fixture-skill/SKILL.md", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_prior_rejections_falls_back_to_the_trail_reason(tmp_path, capsys):
    root = bridge_root(tmp_path)
    proposal(root, "2026-01-01-fixture-topic", folder="rejected", status="rejected",
             target_path="skills/fixture-skill/SKILL.md")
    trail = root / "work" / "_learning" / "audit-trail.md"
    trail.write_text(trail.read_text(encoding="utf-8")
                     + "| 2026-01-01 10:00 | 2026-01-01-fixture-topic | pending → rejected "
                       "| covered by another skill | — |\n", encoding="utf-8")

    capsys.readouterr()
    assert ll.main(["--root", str(root), "prior-rejections",
                    "skills/fixture-skill/SKILL.md", "--json"]) == 0
    assert json.loads(capsys.readouterr().out)[0]["reason"] == "covered by another skill"


def test_prior_rejections_plain_output_says_none_found(tmp_path, capsys):
    root = bridge_root(tmp_path)

    capsys.readouterr()
    assert ll.main(["--root", str(root), "prior-rejections", "skills/x/SKILL.md"]) == 0
    assert "no rejected proposal" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# record / check (#203): the trail is written from git and checked
# ---------------------------------------------------------------------------

TS_RE = r"^\| \d{4}-\d{2}-\d{2} \d{2}:\d{2} \|"


def _commit_all(root: Path, message: str = "c") -> str:
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", message], cwd=root, check=True)
    return subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=root, check=True,
                          capture_output=True, text=True).stdout.strip()


def test_record_accept_writes_a_measured_timestamp_and_no_commit(tmp_path):
    import re
    root = bridge_root(tmp_path)
    proposal(root, "2026-01-02-demo-task-tighten-trigger", folder="accepted", status="accepted")

    assert ll.main(["--root", str(root), "record", "2026-01-02-demo-task-tighten-trigger",
                    "--to", "accepted", "--reason", "narrowed the trigger"]) == 0
    row = trail_rows(root)[-1]
    assert re.match(TS_RE, row)
    assert "2026-05-13 14:30" not in row
    assert "| 2026-01-02-demo-task-tighten-trigger | pending → accepted | narrowed the trigger | — |" in row


def test_record_implemented_uses_the_real_head_sha_and_a_diffstat(tmp_path):
    root = bridge_root(tmp_path)
    (root / "skills" / "demo").mkdir(parents=True)
    (root / "skills" / "demo" / "SKILL.md").write_text("v1\n", encoding="utf-8")
    _commit_all(root, "base")
    proposal(root, "2026-01-02-demo-task-tighten-trigger", folder="accepted", status="accepted")
    assert ll.main(["--root", str(root), "record", "2026-01-02-demo-task-tighten-trigger",
                    "--to", "accepted"]) == 0
    (root / "skills" / "demo" / "SKILL.md").write_text("v2\nmore\n", encoding="utf-8")
    path = root / "work" / "_learning" / "proposals" / "accepted" / \
        "2026-01-02-demo-task-tighten-trigger.md"
    path.write_text(path.read_text(encoding="utf-8").replace("status: accepted",
                                                            "status: implemented"),
                    encoding="utf-8")
    sha = _commit_all(root, "skill(demo): tighten")

    assert ll.main(["--root", str(root), "record", "2026-01-02-demo-task-tighten-trigger",
                    "--to", "implemented"]) == 0
    row = trail_rows(root)[-1]
    assert "| accepted → implemented |" in row
    assert f"| {sha} (" in row and "+" in row
    assert frontmatter(path)["recurrence_fingerprint"] == \
        "skills/demo/SKILL.md#demo-task-tighten-trigger"
    assert frontmatter(path)["implemented_commit"] == sha


def test_record_defer_carries_the_until_marker(tmp_path):
    root = bridge_root(tmp_path)
    proposal(root, "2026-01-02-demo-task-tighten-trigger", status="deferred")

    assert ll.main(["--root", str(root), "record", "2026-01-02-demo-task-tighten-trigger",
                    "--to", "deferred", "--until", "phase-3"]) == 0
    assert "| pending → deferred (phase-3) |" in trail_rows(root)[-1]


def test_record_refuses_when_folder_and_status_disagree(tmp_path, capsys):
    root = bridge_root(tmp_path)
    proposal(root, "2026-01-02-demo-task-tighten-trigger", status="accepted")  # still in root

    before = trail_rows(root)
    assert ll.main(["--root", str(root), "record", "2026-01-02-demo-task-tighten-trigger",
                    "--to", "accepted"]) == 2
    assert trail_rows(root) == before


def test_record_refuses_when_the_file_status_is_not_the_target_state(tmp_path):
    root = bridge_root(tmp_path)
    proposal(root, "2026-01-02-demo-task-tighten-trigger", folder="rejected", status="pending")

    assert ll.main(["--root", str(root), "record", "2026-01-02-demo-task-tighten-trigger",
                    "--to", "rejected", "--reason", "x"]) == 2


def _drift_fixture(root: Path) -> None:
    trail = root / "work" / "_learning" / "audit-trail.md"
    # 1. implemented row without a commit hash
    proposal(root, "2026-01-01-a-task-no-commit", folder="accepted", status="implemented")
    # 2. placeholder timestamp
    proposal(root, "2026-01-01-b-task-bad-ts", folder="accepted", status="accepted")
    # 3. folder and status disagree
    proposal(root, "2026-01-01-c-task-wrong-folder", status="accepted")
    # 4. trail row for a proposal that has no file anywhere
    trail.write_text(trail.read_text(encoding="utf-8")
                     + "| 2026-01-02 10:00 | 2026-01-01-a-task-no-commit | pending → accepted | | — |\n"
                     + "| 2026-01-02 10:05 | 2026-01-01-a-task-no-commit | accepted → implemented | | — |\n"
                     + "| %s | 2026-01-01-b-task-bad-ts | pending → accepted | | — |\n"
                     + "| 2026-01-02 10:10 | 2026-01-01-c-task-wrong-folder | pending → accepted | | — |\n"
                     + "| 2026-01-02 10:20 | 2026-01-01-d-task-ghost | pending → rejected | gone | — |\n",
                     encoding="utf-8")


def test_check_reports_all_four_drift_patterns(tmp_path, capsys):
    root = bridge_root(tmp_path)
    _drift_fixture(root)

    capsys.readouterr()
    assert ll.main(["--root", str(root), "check"]) == 1
    out = capsys.readouterr().out
    assert "2026-01-01-a-task-no-commit" in out and "commit" in out
    assert "2026-01-01-b-task-bad-ts" in out and "timestamp" in out
    assert "2026-01-01-c-task-wrong-folder" in out and "folder" in out
    assert "2026-01-01-d-task-ghost" in out and "no proposal file" in out


def test_check_passes_a_consistent_ledger(tmp_path, capsys):
    root = bridge_root(tmp_path)
    proposal(root, "2026-01-01-a-task-fine", folder="accepted", status="implemented")
    proposal(root, "2026-01-01-b-task-waiting")
    proposal(root, "2026-01-01-c-task-no", folder="rejected", status="rejected")
    trail = root / "work" / "_learning" / "audit-trail.md"
    trail.write_text(trail.read_text(encoding="utf-8")
                     + "| 2026-01-02 10:00 | 2026-01-01-a-task-fine | pending → accepted | | — |\n"
                     + "| 2026-01-02 10:05 | 2026-01-01-a-task-fine | accepted → implemented | "
                       "| 4f3a2b1 (2 files, +5/-1) |\n"
                     + "| 2026-01-02 10:06 | 2026-01-01-c-task-no | pending → rejected | dup | — |\n",
                     encoding="utf-8")

    assert ll.main(["--root", str(root), "check"]) == 0


def test_check_flags_a_hand_moved_proposal(tmp_path, capsys):
    """The issue's negative test: moved into accepted/ without a status edit."""
    root = bridge_root(tmp_path)
    proposal(root, "2026-01-01-a-task-moved", folder="accepted", status="pending")

    capsys.readouterr()
    assert ll.main(["--root", str(root), "check"]) == 1
    assert "2026-01-01-a-task-moved" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# provenance (#205): accepting a skill proposal leaves one line in the skill
# ---------------------------------------------------------------------------


def PROV(root: Path) -> Path:
    """Instance provenance lives under work/, never in the skill folder."""
    return root / "work" / "_learning" / "provenance"


def _skill_accept_to_implemented(root: Path, pid="2026-01-02-demo-task-tighten-trigger",
                                 reason="narrowed the trigger to invoices"):
    skill = root / "skills" / "demo"
    skill.mkdir(parents=True, exist_ok=True)
    (skill / "SKILL.md").write_text("---\nname: demo\n---\nv1\n", encoding="utf-8")
    _commit_all(root, "base")
    path = proposal(root, pid, folder="accepted", status="accepted")
    assert ll.main(["--root", str(root), "record", pid, "--to", "accepted",
                    "--reason", reason]) == 0
    path.write_text(path.read_text(encoding="utf-8").replace("status: accepted",
                                                            "status: implemented"),
                    encoding="utf-8")
    (skill / "SKILL.md").write_text("---\nname: demo\n---\nv2\n", encoding="utf-8")
    _commit_all(root, "skill(demo): tighten")
    return skill


def test_implemented_skill_proposal_appends_one_provenance_line(tmp_path):
    root = bridge_root(tmp_path)
    skill = _skill_accept_to_implemented(root)
    size_before = (skill / "SKILL.md").stat().st_size

    assert ll.main(["--root", str(root), "record", "2026-01-02-demo-task-tighten-trigger",
                    "--to", "implemented"]) == 0
    record = PROV(root) / "demo.md"
    lines = [l for l in record.read_text(encoding="utf-8").splitlines() if l.startswith("- ")]
    assert len(lines) == 1
    import re
    assert re.match(r"^- \d{4}-\d{2}-\d{2} · 2026-01-02-demo-task-tighten-trigger · "
                    r"narrowed the trigger to invoices$", lines[0])
    assert (skill / "SKILL.md").stat().st_size == size_before
    assert not (skill / "references" / "provenance.md").exists()


def test_a_second_implemented_proposal_appends_a_second_line(tmp_path):
    root = bridge_root(tmp_path)
    _skill_accept_to_implemented(root)
    assert ll.main(["--root", str(root), "record", "2026-01-02-demo-task-tighten-trigger",
                    "--to", "implemented"]) == 0
    skill = _skill_accept_to_implemented(root, pid="2026-01-09-other-task-add-example",
                                         reason="added a worked example")
    assert ll.main(["--root", str(root), "record", "2026-01-09-other-task-add-example",
                    "--to", "implemented"]) == 0
    text = (PROV(root) / "demo.md").read_text(encoding="utf-8")
    assert len([l for l in text.splitlines() if l.startswith("- ")]) == 2


def test_rejecting_a_skill_proposal_writes_no_provenance(tmp_path):
    root = bridge_root(tmp_path)
    (root / "skills" / "demo").mkdir(parents=True)
    proposal(root, "2026-01-02-demo-task-tighten-trigger", folder="rejected", status="rejected")

    assert ll.main(["--root", str(root), "record", "2026-01-02-demo-task-tighten-trigger",
                    "--to", "rejected", "--reason", "no"]) == 0
    assert not (root / "skills" / "demo" / "references").exists()


def test_a_non_skill_target_writes_no_provenance(tmp_path):
    root = bridge_root(tmp_path)
    (root / "rules").mkdir()
    (root / "rules" / "x.md").write_text("x\n", encoding="utf-8")
    _commit_all(root)
    proposal(root, "2026-01-02-demo-task-rule-fix", folder="accepted", status="implemented",
             target_path="rules/x.md", target_type="rule")

    assert ll.main(["--root", str(root), "record", "2026-01-02-demo-task-rule-fix",
                    "--to", "implemented"]) == 0
    assert not list(root.rglob("provenance.md"))


def test_check_provenance_flags_both_directions(tmp_path, capsys):
    root = bridge_root(tmp_path)
    _skill_accept_to_implemented(root)
    assert ll.main(["--root", str(root), "record", "2026-01-02-demo-task-tighten-trigger",
                    "--to", "implemented"]) == 0
    record = PROV(root) / "demo.md"
    # trail row without a line: remove the line
    record.write_text("# Provenance\n", encoding="utf-8")
    # a line without a trail row
    other = PROV(root)
    other.mkdir(parents=True, exist_ok=True)
    (other / "other.md").write_text("- 2026-01-03 · 2026-01-03-x-task-ghost · why\n",
                                         encoding="utf-8")

    capsys.readouterr()
    assert ll.main(["--root", str(root), "check", "--provenance"]) == 1
    out = capsys.readouterr().out
    assert "2026-01-02-demo-task-tighten-trigger" in out and "provenance" in out
    assert "2026-01-03-x-task-ghost" in out
    assert (PROV(root) / "demo.md").read_text(
        encoding="utf-8") == "# Provenance\n", "check never edits"


def test_check_without_the_flag_ignores_provenance(tmp_path):
    root = bridge_root(tmp_path)
    other = PROV(root)
    other.mkdir(parents=True, exist_ok=True)
    (other / "other.md").write_text("- 2026-01-03 · 2026-01-03-x-task-ghost · why\n",
                                         encoding="utf-8")
    assert ll.main(["--root", str(root), "check"]) == 0


def test_check_provenance_on_the_shipped_tree_reports_nothing(capsys):
    """The issue's negative test: current CORE carries no provenance yet."""
    capsys.readouterr()
    assert ll.main(["--root", str(REPO_ROOT), "check", "--provenance"]) == 0


# ---------------------------------------------------------------------------
# Review follow-ups
# ---------------------------------------------------------------------------


def test_record_refuses_to_record_the_same_state_twice(tmp_path):
    root = bridge_root(tmp_path)
    proposal(root, "2026-01-02-demo-task-tighten-trigger", folder="accepted", status="accepted")
    assert ll.main(["--root", str(root), "record", "2026-01-02-demo-task-tighten-trigger",
                    "--to", "accepted"]) == 0
    rows = trail_rows(root)
    assert ll.main(["--root", str(root), "record", "2026-01-02-demo-task-tighten-trigger",
                    "--to", "accepted"]) == 2
    assert trail_rows(root) == rows


def test_record_allows_a_second_defer(tmp_path):
    root = bridge_root(tmp_path)
    proposal(root, "2026-01-02-demo-task-tighten-trigger", status="deferred")
    for until in ("next-week", "phase-3"):
        assert ll.main(["--root", str(root), "record", "2026-01-02-demo-task-tighten-trigger",
                        "--to", "deferred", "--until", until]) == 0
    assert "| deferred → deferred (phase-3) |" in trail_rows(root)[-1]


def test_a_repeated_implemented_record_keeps_the_first_commit_and_one_provenance_line(tmp_path):
    root = bridge_root(tmp_path)
    skill = _skill_accept_to_implemented(root)
    assert ll.main(["--root", str(root), "record", "2026-01-02-demo-task-tighten-trigger",
                    "--to", "implemented"]) == 0
    path = root / "work" / "_learning" / "proposals" / "accepted" / \
        "2026-01-02-demo-task-tighten-trigger.md"
    first = frontmatter(path)["implemented_commit"]
    _commit_all(root, "chore(learning): record")

    assert ll.main(["--root", str(root), "record", "2026-01-02-demo-task-tighten-trigger",
                    "--to", "implemented"]) == 2
    assert frontmatter(path)["implemented_commit"] == first
    text = (PROV(root) / "demo.md").read_text(encoding="utf-8")
    assert len([l for l in text.splitlines() if l.startswith("- ")]) == 1


def test_record_implemented_refuses_a_head_that_does_not_touch_the_proposal(tmp_path, capsys):
    root = bridge_root(tmp_path)
    (root / "unrelated.txt").write_text("x\n", encoding="utf-8")
    _commit_all(root, "unrelated")
    proposal(root, "2026-01-02-demo-task-tighten-trigger", folder="accepted", status="implemented")
    (root / "unrelated.txt").write_text("y\n", encoding="utf-8")
    subprocess.run(["git", "add", "unrelated.txt"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "other work"], cwd=root, check=True)

    capsys.readouterr()
    assert ll.main(["--root", str(root), "record", "2026-01-02-demo-task-tighten-trigger",
                    "--to", "implemented"]) == 2
    assert "HEAD" in capsys.readouterr().err


def test_record_supersede_is_recorded(tmp_path):
    root = bridge_root(tmp_path)
    proposal(root, "2026-01-02-demo-task-tighten-trigger", status="superseded",
             extra={"superseded_by": "2026-01-03-x-task-better"})
    assert ll.main(["--root", str(root), "record", "2026-01-02-demo-task-tighten-trigger",
                    "--to", "superseded"]) == 0
    assert "| pending → superseded |" in trail_rows(root)[-1]


def test_check_flags_a_self_transition_row(tmp_path, capsys):
    root = bridge_root(tmp_path)
    proposal(root, "2026-01-01-a-task-twice", folder="accepted", status="accepted")
    trail = root / "work" / "_learning" / "audit-trail.md"
    trail.write_text(trail.read_text(encoding="utf-8")
                     + "| 2026-01-02 10:00 | 2026-01-01-a-task-twice | accepted → accepted | | — |\n",
                     encoding="utf-8")
    capsys.readouterr()
    assert ll.main(["--root", str(root), "check"]) == 1
    assert "accepted → accepted" in capsys.readouterr().out


def test_check_reports_unparseable_and_duplicated_proposals(tmp_path, capsys):
    root = bridge_root(tmp_path)
    broken = root / "work" / "_learning" / "proposals" / "2026-01-01-a-task-broken.md"
    broken.write_text("---\nid: [unclosed\n---\nbody\n", encoding="utf-8")
    proposal(root, "2026-01-01-b-task-twice")
    proposal(root, "2026-01-01-b-task-twice", folder="rejected", status="rejected")

    capsys.readouterr()
    assert ll.main(["--root", str(root), "check"]) == 1
    out = capsys.readouterr().out
    assert "2026-01-01-a-task-broken" in out and "frontmatter" in out
    assert "2026-01-01-b-task-twice" in out and "more than one folder" in out


def test_check_reports_a_truncated_trail_row(tmp_path, capsys):
    root = bridge_root(tmp_path)
    trail = root / "work" / "_learning" / "audit-trail.md"
    trail.write_text(trail.read_text(encoding="utf-8")
                     + "| 2026-01-02 10:00 | 2026-01-01-a-task | accepted → implemented |\n",
                     encoding="utf-8")
    capsys.readouterr()
    assert ll.main(["--root", str(root), "check"]) == 1
    assert "audit-trail.md:" in capsys.readouterr().out


def test_set_frontmatter_key_keeps_backslashes_and_replaces_a_folded_value(tmp_path):
    path = tmp_path / "p.md"
    path.write_text("---\nid: x\nreject_reason: >\n  long\n  folded\nstatus: rejected\n---\nBody\n",
                    encoding="utf-8")
    ll.set_frontmatter_key(path, "reject_reason", "a\\b short")
    data = frontmatter(path)
    assert data == {"id": "x", "reject_reason": "a\\b short", "status": "rejected"}
    assert path.read_text(encoding="utf-8").endswith("Body\n")


def test_recurrences_scan_undated_postmortems_by_their_commit_date(tmp_path, capsys):
    root = bridge_root(tmp_path)
    _implemented(root)
    trail = root / "work" / "_learning" / "audit-trail.md"
    trail.write_text(trail.read_text(encoding="utf-8")
                     + "| 2026-01-05 10:00 | 2026-01-02-demo-task-tighten-trigger | accepted → "
                       "implemented | | 4f3a2b1 (1 files, +1/-0) |\n", encoding="utf-8")
    pm = root / "work" / "_learning" / "postmortems" / "some-task.md"
    pm.write_text("Burned time in skills/demo/SKILL.md again.\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=root, check=True)
    subprocess.run(["git", "commit", "-q", "-m", "pm"], cwd=root, check=True,
                   env={**__import__("os").environ, "GIT_COMMITTER_DATE": "2026-03-04T10:00:00",
                        "GIT_AUTHOR_DATE": "2026-03-04T10:00:00"})

    capsys.readouterr()
    assert ll.main(["--root", str(root), "recurrences", "--json"]) == 0
    data = json.loads(capsys.readouterr().out)
    assert data and data[0]["recurred"] == "2026-03-04"


def test_recurrences_count_from_the_implemented_row_not_from_acceptance(tmp_path, capsys):
    root = bridge_root(tmp_path)
    _implemented(root, on="2026-01-05")
    trail = root / "work" / "_learning" / "audit-trail.md"
    trail.write_text(trail.read_text(encoding="utf-8")
                     + "| 2026-01-20 10:00 | 2026-01-02-demo-task-tighten-trigger | accepted → "
                       "implemented | | 4f3a2b1 (1 files, +1/-0) |\n", encoding="utf-8")
    proposal(root, "2026-01-10-other-task-before-the-fix-landed")

    capsys.readouterr()
    assert ll.main(["--root", str(root), "recurrences", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_recurrences_need_the_whole_path_not_a_substring(tmp_path, capsys):
    root = bridge_root(tmp_path)
    _implemented(root)
    (root / "work" / "_learning" / "audit-history" / "2026-03-01.md").write_text(
        "x/skills/demo/SKILL.md.bak changed\n", encoding="utf-8")

    capsys.readouterr()
    assert ll.main(["--root", str(root), "recurrences", "--json"]) == 0
    assert json.loads(capsys.readouterr().out) == []


def test_prior_rejections_normalises_the_path(tmp_path, capsys):
    root = bridge_root(tmp_path)
    _rejected_fixture(root)
    capsys.readouterr()
    assert ll.main(["--root", str(root), "prior-rejections",
                    "./skills/fixture-skill/SKILL.md", "--json"]) == 0
    assert len(json.loads(capsys.readouterr().out)) == 1


def test_provenance_why_falls_back_to_the_proposal_body(tmp_path):
    root = bridge_root(tmp_path)
    skill = _skill_accept_to_implemented(root, reason="")
    assert ll.main(["--root", str(root), "record", "2026-01-02-demo-task-tighten-trigger",
                    "--to", "implemented"]) == 0
    text = (PROV(root) / "demo.md").read_text(encoding="utf-8")
    assert "· Body." in text and "(no reason recorded)" not in text


def test_a_real_proposal_file_validates_through_the_documented_pipeline(tmp_path):
    """Unquoted YAML dates become date objects; extract-frontmatter stringifies them."""
    jsonschema = pytest.importorskip("jsonschema")
    referencing = pytest.importorskip("referencing")
    root = bridge_root(tmp_path)
    path = proposal(root, "2026-01-02-demo-task-tighten-trigger", folder="rejected",
                    status="rejected")
    path.write_text(path.read_text(encoding="utf-8").replace(
        "status: rejected", "status: rejected\nrejected_at: 2026-01-03\nreject_reason: dup"),
        encoding="utf-8")
    out = subprocess.run([sys.executable, str(REPO_ROOT / "scripts" / "extract-frontmatter.py"),
                          str(path)], capture_output=True, text=True, check=True).stdout
    data = json.loads(out)

    def retrieve(uri):
        return referencing.Resource.from_contents(
            yaml.safe_load(Path(uri.removeprefix("file://")).read_text(encoding="utf-8")))

    pointer = yaml.safe_load(SKILL_SCHEMA.read_text(encoding="utf-8"))
    registry = referencing.Registry(retrieve=retrieve)
    pointer["$id"] = SKILL_SCHEMA.resolve().as_uri()
    validator = jsonschema.Draft202012Validator(pointer, registry=registry)
    assert list(validator.iter_errors(data)) == []
    data["status"] = "shelved"
    assert list(validator.iter_errors(data))
