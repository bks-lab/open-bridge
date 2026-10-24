#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Pytest suite for scripts/overlay-export.py — the single-owner overlay
AUTHORING tool (Direction A: export scope-tagged live files UP into an overlay
repo's tree/ mirror + regenerate its manifest files[]).

CONTRACT — this file is the authoritative spec for the exporter's public
surface. It reuses scripts/categorize-commits.py classify_file() (imported via
importlib, the same hyphenated-module pattern the sibling suites use) and
produces the tree/ + overlay.manifest.yaml shape scripts/overlay.py consumes.

    is_excluded(relpath) -> bool
        True for the three contract exclusions regardless of scope: any path
        under work/** or identity/agent/**, and any _-prefixed basename.

    discover_scoped_files(repo_root, scope="personal") -> list[str]
        SORTED repo-relative paths whose classify_file() == scope, minus the
        exclusions above. classify_file reads frontmatter relative to CWD, so
        discovery runs from inside repo_root; the live repo tree is only READ.

    manifest_files_entries(relpaths, scope="personal") -> list[dict]
        files[] EXCEPTIONS: exactly {"dest": r, "kind": "rule"} for every
        rules/<scope>/*.md in relpaths; every other file is a verbatim mirror
        handled by defaults (NO files[] entry). Sorted by dest. Single-owner =>
        NO prompt_fields ever.

    build_manifest(existing, files_entries, scope="personal") -> dict
        Regenerate the manifest: preserve an existing scaffold's VALUES (overlay
        identity, defaults, selection, ecosystem_fragment) and replace only
        files[]. Absent/empty existing => a schema-valid bootstrap scaffold
        (defaults.scope=scope, source_root=tree/, on_conflict=prompt).

    export_overlay(repo_root, target, *, scope="personal", dry_run=False,
                   prune_foreign=False) -> dict
        (1) copy each discovered file VERBATIM to <target>/tree/<relpath>,
        (2) prune stale files under tree/ (only what this bridge once owned;
        the rest is reported as foreign, test_overlay_export_foreign.py),
        (3) regenerate <target>/overlay.manifest.yaml files[]. Deterministic +
        idempotent. Runs git read-only, and only in a git checkout. NEVER
        modifies the live repo. --dry-run writes nothing.

    main(argv) -> int
        argparse CLI (--repo-root default '.', --target required, --scope
        default personal, --dry-run). Non-dir --repo-root => non-zero, no
        traceback. Success => 0.

Hermetic: every test builds a synthetic mini-repo + a separate overlay target
under tmp_path, never the real repo. Only the --check-ref and prune tests run git, in a
throwaway repo under tmp_path with global config switched off.
"""
from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
import types
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = REPO_ROOT / "scripts" / "overlay-export.py"
SCHEMA_PATH = REPO_ROOT / "docs" / "schemas" / "overlay-manifest.schema.yaml"


@pytest.fixture(scope="module")
def oe() -> types.ModuleType:
    """Load scripts/overlay-export.py via importlib (hyphenated filename)."""
    spec = importlib.util.spec_from_file_location("overlay_export", MODULE_PATH)
    assert spec and spec.loader, f"could not build an import spec for {MODULE_PATH}"
    module = importlib.util.module_from_spec(spec)
    sys.modules["overlay_export"] = module
    spec.loader.exec_module(module)
    return module


# ---------------------------------------------------------------------------
# Synthetic mini-repo builder
# ---------------------------------------------------------------------------

def _write(root: Path, relpath: str, scope: str | None = None, body: str = "x: 1\n") -> None:
    p = root / relpath
    p.parent.mkdir(parents=True, exist_ok=True)
    if scope is None:
        p.write_text(body, encoding="utf-8")
    else:
        p.write_text(f"---\nscope: {scope}\n---\n{body}", encoding="utf-8")


# PII deliberately embedded to prove single-owner verbatim export (no scrubbing).
_PII_BODY = (
    "owner: alice-example\n"
    "customer_number: 4711\n"
    "mail: alice@example.org\n"
    "note: Acme Clinic, multibyte äöü € kept verbatim\n"
)

# The exact set of paths the exporter must discover from the mini-repo below.
EXPECTED_PERSONAL = [
    "ecosystem.personal.yaml",
    "identity/accounts/webmail.yaml",
    "identity/contracts/energy.yaml",
    "identity/mandants/familie.yaml",
    "identity/personas/freelancer.yaml",
    "identity/personas/privat.yaml",
    "rules/personal/applications.md",
    "rules/personal/finance.md",
]

EXPECTED_RULE_DESTS = [
    "rules/personal/applications.md",
    "rules/personal/finance.md",
]


@pytest.fixture
def mini_repo(tmp_path: Path) -> Path:
    """A synthetic Bridge instance exercising every classify/exclude branch."""
    root = tmp_path / "mini-bridge"

    # --- PERSONAL, exportable ------------------------------------------------
    _write(root, "identity/personas/freelancer.yaml", scope="personal", body=_PII_BODY)
    _write(root, "identity/personas/privat.yaml", scope="personal")
    _write(root, "identity/mandants/familie.yaml", scope="personal")
    _write(root, "identity/accounts/webmail.yaml", scope="personal")
    _write(root, "identity/contracts/energy.yaml", scope="personal")
    _write(root, "rules/personal/applications.md", scope=None, body="# applications\n")
    _write(root, "rules/personal/finance.md", scope=None, body="# finance\n")
    _write(root, "ecosystem.personal.yaml", scope=None, body="freelance: {}\n")

    # --- PERSONAL by classify, but EXCLUDED ---------------------------------
    #     identity/agent/** stays user even when someone mis-tags it personal
    _write(root, "identity/agent/SOUL.md", scope="personal", body="# soul\n")
    #     _-prefixed reserved file under a personal folder
    _write(root, "rules/personal/_draft.md", scope=None, body="# draft\n")

    # --- NOT personal (must never be discovered) ----------------------------
    _write(root, "identity/personas/work.yaml", scope="user")
    _write(root, "identity/mandants/acme.yaml", scope="org")
    _write(root, "identity/personas/_schema.yaml", scope=None)
    _write(root, "rules/org/wiki.md", scope=None, body="# org\n")
    _write(root, "rules/user/playbook.md", scope=None, body="# user\n")
    _write(root, "work/log.md", scope=None, body="# log\n")
    _write(root, "work/tasks/sample/STATUS.md", scope=None, body="# status\n")
    _write(root, "docs/structure.md", scope=None, body="# docs\n")
    _write(root, "ecosystem.acme.yaml", scope=None, body="org: acme\n")
    _write(root, "ecosystem.yaml", scope=None, body="org: acme\n")
    _write(root, "bridge-config.yaml", scope=None, body="theme: professional\n")
    return root


def _target(tmp_path: Path) -> Path:
    return tmp_path / "overlay-out"


def _load_manifest(target: Path) -> dict:
    return yaml.safe_load((target / "overlay.manifest.yaml").read_text(encoding="utf-8"))


def _tree_bytes(target: Path) -> dict[str, bytes]:
    tree = target / "tree"
    out: dict[str, bytes] = {}
    if not tree.is_dir():
        return out
    for p in tree.rglob("*"):
        if p.is_file():
            out[p.relative_to(tree).as_posix()] = p.read_bytes()
    return out


# ---------------------------------------------------------------------------
# is_excluded
# ---------------------------------------------------------------------------

def test_is_excluded_work(oe):
    assert oe.is_excluded("work/log.md")
    assert oe.is_excluded("work/tasks/x/STATUS.md")


def test_is_excluded_identity_agent(oe):
    assert oe.is_excluded("identity/agent/SOUL.md")
    assert oe.is_excluded("identity/agent/IDENTITY.md")


def test_is_excluded_underscore_basename(oe):
    assert oe.is_excluded("rules/personal/_draft.md")
    assert oe.is_excluded("identity/personas/_schema.yaml")


def test_is_not_excluded_normal(oe):
    assert not oe.is_excluded("identity/personas/freelancer.yaml")
    assert not oe.is_excluded("rules/personal/finance.md")
    assert not oe.is_excluded("ecosystem.personal.yaml")


# ---------------------------------------------------------------------------
# discover_scoped_files
# ---------------------------------------------------------------------------

def test_discover_finds_exactly_the_personal_set(oe, mini_repo):
    assert oe.discover_scoped_files(str(mini_repo)) == EXPECTED_PERSONAL


def test_discover_is_sorted(oe, mini_repo):
    found = oe.discover_scoped_files(str(mini_repo))
    assert found == sorted(found)


def test_discover_excludes_identity_agent_even_when_tagged_personal(oe, mini_repo):
    # SOUL.md carries `scope: personal` in the fixture; the exclusion must win.
    found = oe.discover_scoped_files(str(mini_repo))
    assert "identity/agent/SOUL.md" not in found


def test_discover_excludes_underscore_prefixed_personal_file(oe, mini_repo):
    found = oe.discover_scoped_files(str(mini_repo))
    assert "rules/personal/_draft.md" not in found


def test_discover_excludes_work(oe, mini_repo):
    found = oe.discover_scoped_files(str(mini_repo))
    assert not any(f.startswith("work/") for f in found)


def test_discover_omits_non_personal(oe, mini_repo):
    found = set(oe.discover_scoped_files(str(mini_repo)))
    for f in ("identity/personas/work.yaml", "identity/mandants/acme.yaml",
              "rules/org/wiki.md", "rules/user/playbook.md", "docs/structure.md",
              "ecosystem.acme.yaml", "ecosystem.yaml", "bridge-config.yaml"):
        assert f not in found


def test_discover_reads_frontmatter_scope(oe, mini_repo):
    # Proves the chdir/frontmatter path works end-to-end through the exporter:
    # a persona is personal ONLY because of its `scope: personal` frontmatter.
    found = oe.discover_scoped_files(str(mini_repo))
    assert "identity/personas/freelancer.yaml" in found
    # the same-folder persona tagged `scope: user` must NOT be discovered
    assert "identity/personas/work.yaml" not in found


def test_discover_restores_cwd(oe, mini_repo):
    before = Path.cwd()
    oe.discover_scoped_files(str(mini_repo))
    assert Path.cwd() == before


# ---------------------------------------------------------------------------
# manifest_files_entries
# ---------------------------------------------------------------------------

def test_files_entries_only_rules(oe):
    entries = oe.manifest_files_entries(EXPECTED_PERSONAL)
    assert [e["dest"] for e in entries] == EXPECTED_RULE_DESTS


def test_files_entries_all_kind_rule(oe):
    entries = oe.manifest_files_entries(EXPECTED_PERSONAL)
    assert all(e["kind"] == "rule" for e in entries)


def test_files_entries_have_no_prompt_fields(oe):
    # Single-owner => verbatim mirror; entries carry ONLY dest + kind.
    entries = oe.manifest_files_entries(EXPECTED_PERSONAL)
    for e in entries:
        assert set(e.keys()) == {"dest", "kind"}


def test_files_entries_sorted(oe):
    shuffled = list(reversed(EXPECTED_PERSONAL))
    entries = oe.manifest_files_entries(shuffled)
    dests = [e["dest"] for e in entries]
    assert dests == sorted(dests)


def test_files_entries_empty_when_no_rules(oe):
    non_rules = [f for f in EXPECTED_PERSONAL if not f.startswith("rules/")]
    assert oe.manifest_files_entries(non_rules) == []


# ---------------------------------------------------------------------------
# build_manifest
# ---------------------------------------------------------------------------

def test_build_manifest_default_scaffold(oe):
    entries = oe.manifest_files_entries(EXPECTED_PERSONAL)
    m = oe.build_manifest(None, entries, "personal")
    assert m["schema_version"] == 1
    assert m["overlay"]["name"] == "personal"
    assert m["overlay"]["org"] == "personal"
    assert m["defaults"]["scope"] == "personal"
    assert m["defaults"]["source_root"] == "tree/"
    assert m["defaults"]["on_conflict"] == "prompt"
    assert m["selection"]["include"] == ["**"]
    assert m["files"] == entries


def test_build_manifest_preserves_existing_scaffold(oe):
    existing = {
        "schema_version": 1,
        "overlay": {"name": "personal", "org": "personal",
                    "description": "hand-authored — keep me"},
        "defaults": {"scope": "personal", "source_root": "tree/", "on_conflict": "prompt"},
        "selection": {"include": ["**"], "exclude": ["work/**"]},
        "ecosystem_fragment": "ecosystem.personal.yaml",
        "files": [{"dest": "rules/personal/stale.md", "kind": "rule"}],
    }
    entries = oe.manifest_files_entries(EXPECTED_PERSONAL)
    m = oe.build_manifest(existing, entries, "personal")
    assert m["overlay"]["description"] == "hand-authored — keep me"
    assert m["ecosystem_fragment"] == "ecosystem.personal.yaml"
    # only files[] is regenerated — the stale entry is gone
    assert m["files"] == entries


def test_build_manifest_scope_is_parametric(oe):
    m = oe.build_manifest(None, [], "org")
    assert m["defaults"]["scope"] == "org"
    assert m["overlay"]["name"] == "org"


# ---------------------------------------------------------------------------
# export_overlay — copy + manifest
# ---------------------------------------------------------------------------

def test_export_copies_every_personal_file_to_tree(oe, mini_repo, tmp_path):
    target = _target(tmp_path)
    oe.export_overlay(str(mini_repo), str(target))
    for rel in EXPECTED_PERSONAL:
        assert (target / "tree" / rel).is_file(), rel


def test_export_tree_holds_only_the_personal_set(oe, mini_repo, tmp_path):
    target = _target(tmp_path)
    oe.export_overlay(str(mini_repo), str(target))
    assert sorted(_tree_bytes(target).keys()) == EXPECTED_PERSONAL


def test_export_is_verbatim_no_scrubbing(oe, mini_repo, tmp_path):
    target = _target(tmp_path)
    oe.export_overlay(str(mini_repo), str(target))
    src = (mini_repo / "identity/personas/freelancer.yaml").read_bytes()
    dst = (target / "tree/identity/personas/freelancer.yaml").read_bytes()
    assert dst == src
    text = dst.decode("utf-8")
    for token in ("alice-example", "4711", "alice@example.org", "äöü", "€"):
        assert token in text


def test_export_ecosystem_fragment_lands_under_tree(oe, mini_repo, tmp_path):
    target = _target(tmp_path)
    oe.export_overlay(str(mini_repo), str(target))
    assert (target / "tree/ecosystem.personal.yaml").is_file()


def test_export_manifest_files_are_the_rules(oe, mini_repo, tmp_path):
    target = _target(tmp_path)
    oe.export_overlay(str(mini_repo), str(target))
    manifest = _load_manifest(target)
    assert [e["dest"] for e in manifest["files"]] == EXPECTED_RULE_DESTS
    assert all(e["kind"] == "rule" for e in manifest["files"])
    for e in manifest["files"]:
        assert set(e.keys()) == {"dest", "kind"}


def test_export_manifest_defaults(oe, mini_repo, tmp_path):
    target = _target(tmp_path)
    oe.export_overlay(str(mini_repo), str(target))
    manifest = _load_manifest(target)
    assert manifest["defaults"]["scope"] == "personal"
    assert manifest["defaults"]["source_root"] == "tree/"
    assert manifest["schema_version"] == 1


def test_export_no_prompt_fields_anywhere(oe, mini_repo, tmp_path):
    # Single-owner => verbatim mirror: the manifest must carry no prompt_fields
    # KEY anywhere in its structure (the header comment may mention the word).
    target = _target(tmp_path)
    oe.export_overlay(str(mini_repo), str(target))
    manifest = _load_manifest(target)

    def _has_key(node, key) -> bool:
        if isinstance(node, dict):
            return key in node or any(_has_key(v, key) for v in node.values())
        if isinstance(node, list):
            return any(_has_key(v, key) for v in node)
        return False

    assert not _has_key(manifest, "prompt_fields")


def test_export_result_shape(oe, mini_repo, tmp_path):
    target = _target(tmp_path)
    result = oe.export_overlay(str(mini_repo), str(target))
    assert result["copied"] == EXPECTED_PERSONAL
    assert result["pruned"] == []
    assert [e["dest"] for e in result["files_entries"]] == EXPECTED_RULE_DESTS
    assert result["dry_run"] is False


def test_export_writes_gitignore(oe, mini_repo, tmp_path):
    target = _target(tmp_path)
    oe.export_overlay(str(mini_repo), str(target))
    gi = (target / ".gitignore").read_text(encoding="utf-8")
    assert "__pycache__" in gi


# ---------------------------------------------------------------------------
# determinism / idempotency
# ---------------------------------------------------------------------------

def test_export_idempotent(oe, mini_repo, tmp_path):
    target = _target(tmp_path)
    oe.export_overlay(str(mini_repo), str(target))
    tree1 = _tree_bytes(target)
    manifest1 = (target / "overlay.manifest.yaml").read_bytes()

    result2 = oe.export_overlay(str(mini_repo), str(target))
    tree2 = _tree_bytes(target)
    manifest2 = (target / "overlay.manifest.yaml").read_bytes()

    assert tree1 == tree2
    assert manifest1 == manifest2
    assert result2["pruned"] == []
    assert result2["copied"] == EXPECTED_PERSONAL


def _owned_once(repo: Path, relpaths: list[str]) -> None:
    """Give `repo` a git history that once held `relpaths` and then dropped them.

    The prune deletes only what this bridge once owned, and its git history is
    the evidence (test_overlay_export_foreign.py). Without it a mirror file is
    foreign and kept.
    """
    env = dict(os.environ, GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
    git = ["git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
           "-c", "commit.gpgsign=false"]
    subprocess.run([*git, "init", "-q"], cwd=repo, check=True, env=env)
    for rel in relpaths:
        _write(repo, rel)
    subprocess.run([*git, "add", "-A"], cwd=repo, check=True, env=env)
    subprocess.run([*git, "commit", "-q", "-m", "seed"], cwd=repo, check=True, env=env)
    subprocess.run([*git, "rm", "-q", *relpaths], cwd=repo, check=True, env=env)
    subprocess.run([*git, "commit", "-q", "-m", "drop"], cwd=repo, check=True, env=env)


def test_export_prunes_stale_tree_files(oe, mini_repo, tmp_path):
    target = _target(tmp_path)
    _owned_once(mini_repo, ["identity/personas/GONE.yaml", "oldstuff/removed.yaml"])
    # seed a prior tree/ with files that are no longer personal
    stale1 = target / "tree/identity/personas/GONE.yaml"
    stale2 = target / "tree/oldstuff/removed.yaml"
    stale1.parent.mkdir(parents=True, exist_ok=True)
    stale2.parent.mkdir(parents=True, exist_ok=True)
    stale1.write_text("stale: 1\n", encoding="utf-8")
    stale2.write_text("stale: 2\n", encoding="utf-8")

    result = oe.export_overlay(str(mini_repo), str(target))

    assert not stale1.exists()
    assert not stale2.exists()
    # an emptied directory is cleaned up, a still-populated one survives
    assert not (target / "tree/oldstuff").exists()
    assert (target / "tree/identity/personas").is_dir()
    assert "identity/personas/GONE.yaml" in result["pruned"]
    assert "oldstuff/removed.yaml" in result["pruned"]


# ---------------------------------------------------------------------------
# dry-run
# ---------------------------------------------------------------------------

def test_dry_run_writes_nothing(oe, mini_repo, tmp_path):
    target = _target(tmp_path)
    result = oe.export_overlay(str(mini_repo), str(target), dry_run=True)
    assert not (target / "tree").exists()
    assert not (target / "overlay.manifest.yaml").exists()
    assert not (target / ".gitignore").exists()
    assert result["dry_run"] is True
    assert result["copied"] == EXPECTED_PERSONAL
    assert [e["dest"] for e in result["files_entries"]] == EXPECTED_RULE_DESTS


# ---------------------------------------------------------------------------
# safety: never touch the live repo, never run git
# ---------------------------------------------------------------------------

def test_export_does_not_modify_repo(oe, mini_repo, tmp_path):
    def snapshot(root: Path) -> dict[str, bytes]:
        return {p.relative_to(root).as_posix(): p.read_bytes()
                for p in root.rglob("*") if p.is_file()}

    before = snapshot(mini_repo)
    oe.export_overlay(str(mini_repo), str(_target(tmp_path)))
    after = snapshot(mini_repo)
    assert before == after
    # nothing was written INTO the repo (no stray tree/ or manifest)
    assert not (mini_repo / "tree").exists()
    assert not (mini_repo / "overlay.manifest.yaml").exists()


def test_export_does_not_run_git(oe, mini_repo, tmp_path, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("overlay-export must not shell out (git/subprocess)")

    monkeypatch.setattr(subprocess, "run", boom)
    monkeypatch.setattr(subprocess, "check_output", boom)
    monkeypatch.setattr(subprocess, "Popen", boom)

    target = _target(tmp_path)
    result = oe.export_overlay(str(mini_repo), str(target))
    assert result["copied"] == EXPECTED_PERSONAL
    assert not (target / ".git").exists()


# ---------------------------------------------------------------------------
# schema conformance (real schema, when the validator is installed)
# ---------------------------------------------------------------------------

@pytest.mark.skipif(shutil.which("check-jsonschema") is None,
                    reason="check-jsonschema not installed")
def test_generated_manifest_validates_against_real_schema(oe, mini_repo, tmp_path):
    target = _target(tmp_path)
    oe.export_overlay(str(mini_repo), str(target))
    proc = subprocess.run(
        ["check-jsonschema", "--schemafile", str(SCHEMA_PATH),
         str(target / "overlay.manifest.yaml")],
        stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
    )
    assert proc.returncode == 0, proc.stdout


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def test_main_exports(oe, mini_repo, tmp_path, capsys):
    target = _target(tmp_path)
    rc = oe.main(["--repo-root", str(mini_repo), "--target", str(target)])
    assert rc == 0
    assert (target / "overlay.manifest.yaml").is_file()
    assert sorted(_tree_bytes(target).keys()) == EXPECTED_PERSONAL


def test_main_dry_run_writes_nothing(oe, mini_repo, tmp_path, capsys):
    target = _target(tmp_path)
    rc = oe.main(["--repo-root", str(mini_repo), "--target", str(target), "--dry-run"])
    assert rc == 0
    assert not (target / "tree").exists()
    out = capsys.readouterr().out
    assert "DRY-RUN" in out
    assert "tree/rules/personal/finance.md" in out


def test_main_bad_repo_root_returns_nonzero(oe, tmp_path, capsys):
    rc = oe.main(["--repo-root", str(tmp_path / "nope"), "--target", str(tmp_path / "o")])
    assert rc != 0
    assert "ERROR" in capsys.readouterr().err


def test_main_scope_flag(oe, mini_repo, tmp_path):
    # exporting the `org` scope picks up the org files, not the personal ones
    target = _target(tmp_path)
    oe.main(["--repo-root", str(mini_repo), "--target", str(target), "--scope", "org"])
    keys = set(_tree_bytes(target).keys())
    assert "identity/mandants/acme.yaml" in keys
    assert "identity/personas/freelancer.yaml" not in keys


# ---------------------------------------------------------------------------
# Cherry-pick gate: /promote and /bridge-sync refuse a flat-mirror overlay
# ---------------------------------------------------------------------------
#
#   flat_mirror_source_root(target) -> str | None
#       The source_root a flat-mirror overlay reads from, or None when a
#       same-path cherry-pick into <target> would land where a consumer looks.
#       <target> is an overlay checkout dir or a manifest file. A checkout
#       without a manifest => None. A manifest without defaults.source_root
#       resolves to scripts/overlay.py's default (tree/). source_root "", "."
#       or "./" => None. An empty or unreadable manifest, or source_root null,
#       fails CLOSED (refuse). A target that does not exist raises
#       TargetUnverifiable.
#
#   main(["--target", T, "--check-target"]) -> 0 (cherry-pick is safe),
#       3 (refuse: flat mirror) or 2 (refuse: cannot verify), writing nothing
#       and naming `overlay-export.py --dry-run`.

OVERLAY_PATH = REPO_ROOT / "scripts" / "overlay.py"


def _manifest(target: Path, body: str) -> Path:
    target.mkdir(parents=True, exist_ok=True)
    p = target / "overlay.manifest.yaml"
    p.write_text(body, encoding="utf-8")
    return p


_MANIFEST_HEAD = "schema_version: 1\noverlay: {name: example-org, org: example-org}\n"


def test_gate_no_manifest_allows_cherry_pick(oe, tmp_path):
    target = tmp_path / "plain"
    target.mkdir()
    assert oe.flat_mirror_source_root(str(target)) is None


def test_gate_explicit_source_root_refuses(oe, tmp_path):
    target = tmp_path / "ov"
    _manifest(target, _MANIFEST_HEAD + "defaults: {source_root: tree/}\n")
    assert oe.flat_mirror_source_root(str(target)) == "tree/"


def test_gate_custom_source_root_refuses(oe, tmp_path):
    target = tmp_path / "ov"
    _manifest(target, _MANIFEST_HEAD + "defaults: {source_root: mirror}\n")
    assert oe.flat_mirror_source_root(str(target)) == "mirror/"


def test_gate_missing_source_root_uses_engine_default(oe, tmp_path):
    # overlay.py reads tree/ when the manifest is silent, so the gate must too
    target = tmp_path / "ov"
    _manifest(target, _MANIFEST_HEAD + "defaults: {scope: org}\n")
    assert oe.flat_mirror_source_root(str(target)) == "tree/"


@pytest.mark.parametrize("root", ['""', '"."', '"./"'])
def test_gate_repo_root_source_root_allows(oe, tmp_path, root):
    target = tmp_path / "ov"
    _manifest(target, _MANIFEST_HEAD + f"defaults: {{source_root: {root}}}\n")
    assert oe.flat_mirror_source_root(str(target)) is None


def test_gate_accepts_a_manifest_file(oe, tmp_path):
    # /promote checks a fetched ref via `git show <ref>:overlay.manifest.yaml > f`
    m = _manifest(tmp_path / "ov", _MANIFEST_HEAD + "defaults: {source_root: tree/}\n")
    assert oe.flat_mirror_source_root(str(m)) == "tree/"


def test_gate_empty_manifest_file_fails_closed(oe, tmp_path):
    # an empty manifest is a broken overlay, not "no manifest": refuse
    m = _manifest(tmp_path / "ov", "")
    assert oe.flat_mirror_source_root(str(m)) == "tree/"


def test_gate_null_source_root_fails_closed(oe, tmp_path):
    # overlay.py would crash on None.rstrip: a broken overlay, not a repo root
    target = tmp_path / "ov"
    _manifest(target, _MANIFEST_HEAD + "defaults: {source_root: null}\n")
    assert oe.flat_mirror_source_root(str(target)) == "tree/"


def test_gate_missing_target_is_unverifiable(oe, tmp_path):
    # a typo in the checkout path must never read as "safe to cherry-pick"
    with pytest.raises(oe.TargetUnverifiable):
        oe.flat_mirror_source_root(str(tmp_path / "no-such-checkout"))


def test_main_check_target_missing_target_refuses(oe, tmp_path, capsys):
    rc = oe.main(["--target", str(tmp_path / "typo"), "--check-target"])
    assert rc == 2
    assert "REFUSE" in capsys.readouterr().err


def test_gate_unreadable_manifest_fails_closed(oe, tmp_path):
    target = tmp_path / "ov"
    _manifest(target, "defaults: [unclosed\n")
    assert oe.flat_mirror_source_root(str(target)) == "tree/"


def test_gate_default_matches_the_consumer_engine(oe):
    spec = importlib.util.spec_from_file_location("overlay_engine", OVERLAY_PATH)
    assert spec and spec.loader
    engine = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(engine)
    assert oe.SOURCE_ROOT == engine.DEFAULT_SOURCE_ROOT


def test_main_check_target_refuses_flat_mirror(oe, tmp_path, capsys):
    target = tmp_path / "ov"
    _manifest(target, _MANIFEST_HEAD + "defaults: {source_root: tree/}\n")
    before = sorted(p.name for p in target.iterdir())
    rc = oe.main(["--target", str(target), "--check-target"])
    assert rc == 3
    err = capsys.readouterr().err
    assert "REFUSE" in err
    assert "overlay-export.py" in err and "--dry-run" in err
    assert sorted(p.name for p in target.iterdir()) == before  # wrote nothing


def test_main_check_target_allows_normal_layout(oe, tmp_path, capsys):
    target = tmp_path / "plain"
    target.mkdir()
    rc = oe.main(["--target", str(target), "--check-target"])
    assert rc == 0
    assert list(target.iterdir()) == []  # no tree/, no manifest, no .gitignore
    assert "OK" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# Cherry-pick gate against a fetched ref: --check-ref
# ---------------------------------------------------------------------------
#
#   flat_mirror_source_root_at_ref(ref, repo=".") -> str | None
#       Same answer as flat_mirror_source_root, read from <ref> in the git repo
#       <repo>. A ref that does not resolve to a commit (fetch failed, typo)
#       raises TargetUnverifiable: it fails CLOSED. A resolved ref without
#       overlay.manifest.yaml => None.
#
#   main(["--repo-root", R, "--check-ref", REF]) -> 0 / 3 / 2 (unverifiable).


def _git(cwd: Path, *args: str) -> None:
    subprocess.run(["git", *args], cwd=cwd, check=True, capture_output=True,
                   env={"GIT_CONFIG_GLOBAL": "/dev/null", "GIT_CONFIG_NOSYSTEM": "1",
                        "GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@example.org",
                        "GIT_COMMITTER_NAME": "t", "GIT_COMMITTER_EMAIL": "t@example.org",
                        "PATH": "/usr/bin:/bin:/usr/local/bin:/opt/homebrew/bin"})


@pytest.fixture
def ref_repo(tmp_path):
    """A git repo with branch `flat` (manifest, source_root tree/) and branch
    `plain` (no manifest), standing in for fetched overlay refs."""
    repo = tmp_path / "bridge"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "plain")
    (repo / "README.md").write_text("x\n", encoding="utf-8")
    _git(repo, "add", "README.md")
    _git(repo, "commit", "-q", "-m", "plain")
    _git(repo, "checkout", "-q", "-b", "flat")
    _manifest(repo, _MANIFEST_HEAD + "defaults: {source_root: tree/}\n")
    _git(repo, "add", "overlay.manifest.yaml")
    _git(repo, "commit", "-q", "-m", "flat")
    return repo


def test_ref_gate_flat_mirror_refuses(oe, ref_repo):
    assert oe.flat_mirror_source_root_at_ref("flat", str(ref_repo)) == "tree/"


def test_ref_gate_no_manifest_allows(oe, ref_repo):
    assert oe.flat_mirror_source_root_at_ref("plain", str(ref_repo)) is None


def test_ref_gate_missing_ref_is_unverifiable(oe, ref_repo):
    # the fetch never ran, or the remote name is mistyped
    with pytest.raises(oe.TargetUnverifiable):
        oe.flat_mirror_source_root_at_ref("nosuch/branch", str(ref_repo))


def test_main_check_ref_exit_codes(oe, ref_repo, capsys):
    root = ["--repo-root", str(ref_repo)]
    assert oe.main(root + ["--check-ref", "flat"]) == 3
    assert oe.main(root + ["--check-ref", "plain"]) == 0
    assert oe.main(root + ["--check-ref", "nosuch/branch"]) == 2
    err = capsys.readouterr().err
    assert err.count("REFUSE") == 2
