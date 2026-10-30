# SPDX-License-Identifier: MIT
"""Contract for scripts/migrate-entry-file.py.

Upstream removed its root CLAUDE.md: Claude Code reads AGENTS.md natively, and a
root CLAUDE.md (or CLAUDE.local.md, or .claude/CLAUDE.md) beside it makes Claude
Code load only that file. Every fork that edited CLAUDE.md meets a modify/delete
conflict on the next `git merge upstream/main`. This script carries the fork's
own lines to identity/agent/INSTANCE.md, drops what CORE wrote, edits the budget
and removes the file, dry run first.

Every case builds throwaway git repositories and runs the real script.

Run: python3 -m pytest scripts/tests/test_migrate_entry_file.py -q
"""
from __future__ import annotations

import datetime
import hashlib
import os
import pathlib
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "migrate-entry-file.py"
DIVERGENCE = REPO / "scripts" / "bridge-divergence-check.py"
GIT_ID = ["-c", "user.name=t", "-c", "user.email=t@example.invalid",
          "-c", "commit.gpgsign=false", "-c", "core.hooksPath=/dev/null"]
ENV = {**os.environ, "LC_ALL": "C"}
for _k in ("GIT_DIR", "GIT_WORK_TREE", "GIT_INDEX_FILE"):
    ENV.pop(_k, None)

CORE_V1 = (
    "@AGENTS.md\n\n# Claude Code specifics\n\n"
    "The manual lives in AGENTS.md. This file only adds the Claude-Code bits.\n\n"
    "Run the Phase-0 gate before responding.\n"
)
CORE_V2 = (
    "@AGENTS.md\n\n# Claude Code specifics\n\n"
    "The manual lives in AGENTS.md, read natively by other agents.\n\n"
    "Run the Phase-0 session-start gate before responding.\n"
)
GERMAN = "Diese Instanz führt drei Registries. Größe: 30.038 B, Übersicht in Kürze."
IMPORTS = ("## Loaded with this file\n\n@identity/agent/IDENTITY.md\n"
           "@identity/agent/SOUL.md\n@identity/agent/INSTANCE.md\n")
MANUAL = "# Manual\n\n" + IMPORTS + "\nCORE manual text.\n"
OLD_MANUAL = "# Manual\n\nCORE manual text.\n"   # before the import slot existed
FENCE = "```bash\npython3 scripts/context-index.py ecosystem.acme.yaml\n\npython3 scripts/context-index.py ecosystem.yaml\n```"


def git(cwd, *args, check=True):
    p = subprocess.run(["git", *GIT_ID, *args], cwd=cwd, env=ENV,
                       capture_output=True, text=True)
    if check and p.returncode:
        raise AssertionError(f"git {args} -> {p.returncode}\n{p.stdout}\n{p.stderr}")
    return p


def mig(repo, *args):
    return subprocess.run([sys.executable, str(SCRIPT), "--repo-root", str(repo), *args],
                          cwd=repo, env=ENV, capture_output=True, text=True)


def write(repo, path, text):
    f = pathlib.Path(repo) / path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(text, encoding="utf-8")


def commit(repo, msg):
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", msg)


def last_core():
    """The final CORE CLAUDE.md, as the script embeds it."""
    src = SCRIPT.read_text(encoding="utf-8")
    ns: dict = {}
    start = src.index("LAST_CORE_CLAUDE_MD = ")
    end = src.index('"""\n', src.index('"""', start) + 3) + 4
    exec(src[start:end], ns)
    return ns["LAST_CORE_CLAUDE_MD"]


class World:
    """`up` is CORE, `fork` a clone with remote `upstream` on user/me."""

    def __init__(self, tmp: pathlib.Path, core_versions=(CORE_V1, CORE_V2),
                 identity=True, manual=MANUAL):
        self.up, self.fork = tmp / "up", tmp / "fork"
        self.up.mkdir()
        git(self.up, "init", "-q", "-b", "main")
        write(self.up, "AGENTS.md", manual)
        write(self.up, "context-budget.yaml",
              "schema_version: 1\nitems:\n  identity/agent/INSTANCE.md:\n"
              "    max_bytes: 4000\n    optional: true\n")
        for i, v in enumerate(core_versions):
            write(self.up, "CLAUDE.md", v)
            commit(self.up, f"core v{i + 1}")
        git(tmp, "clone", "-q", "-o", "upstream", str(self.up), str(self.fork))
        git(self.fork, "checkout", "-q", "-b", "user/me")
        write(self.fork, "bridge-config.yaml", "identity: {}\n")  # a fork, not CORE
        commit(self.fork, "config")
        if identity:
            write(self.fork, "identity/agent/IDENTITY.md", "# IDENTITY\n\nMe.\n")
            commit(self.fork, "onboard")

    def snapshot(self):
        out = {}
        for p in sorted(self.fork.rglob("*")):
            if ".git" in p.relative_to(self.fork).parts or not p.is_file():
                continue
            out[str(p.relative_to(self.fork))] = hashlib.sha256(p.read_bytes()).hexdigest()
        out["__status__"] = git(self.fork, "status", "--porcelain").stdout
        return out

    def text(self, path):
        return (self.fork / path).read_text(encoding="utf-8")


@pytest.fixture
def w(tmp_path):
    return World(tmp_path)


def heading():
    return f"## Carried over from CLAUDE.md ({datetime.date.today().isoformat()})"


# ---------------------------------------------------------------- basics --

def test_nothing_to_migrate_on_a_clean_tree(w):
    git(w.fork, "rm", "-q", "CLAUDE.md"); commit(w.fork, "gone")
    p = mig(w.fork)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "nothing to migrate" in p.stdout
    assert mig(w.fork, "--check").returncode == 0


def test_check_is_red_while_claude_md_exists(w):
    p = mig(w.fork, "--check")
    assert p.returncode == 1, p.stdout + p.stderr
    assert "CLAUDE.md" in p.stdout


@pytest.mark.parametrize("path", ["CLAUDE.local.md", ".claude/CLAUDE.md"])
def test_check_is_red_for_every_shadow_file(w, path):
    git(w.fork, "rm", "-q", "CLAUDE.md"); commit(w.fork, "gone")
    write(w.fork, path, "local note\n")
    p = mig(w.fork, "--check")
    assert p.returncode == 1 and path in p.stdout, p.stdout + p.stderr


def test_core_only_claude_md_is_removed_and_nothing_carried(w):
    write(w.fork, "CLAUDE.md",
          last_core().rstrip("\n") + "\n@identity/agent/IDENTITY.md\n@identity/agent/SOUL.md\n")
    commit(w.fork, "onboarding imports")
    before = (w.fork / "identity/agent/IDENTITY.md").read_bytes()
    p = mig(w.fork, "--write")
    assert p.returncode == 0, p.stdout + p.stderr
    assert (w.fork / "identity/agent/IDENTITY.md").read_bytes() == before
    assert not (w.fork / "identity/agent/INSTANCE.md").exists()
    assert not (w.fork / "CLAUDE.md").exists()
    assert git(w.fork, "ls-files", "CLAUDE.md").stdout == ""


def test_instance_prose_is_carried_and_imports_dropped(w):
    body = ("@AGENTS.md\n@identity/agent/IDENTITY.md\n@ecosystem.acme.yaml\n@docs/x.md\n\n"
            + CORE_V2.split("\n\n", 1)[1].rstrip("\n") + "\n\n" + GERMAN + "\n\n" + FENCE + "\n")
    write(w.fork, "CLAUDE.md", body); commit(w.fork, "instance prose")
    p = mig(w.fork, "--write")
    assert p.returncode == 0, p.stdout + p.stderr
    raw = (w.fork / "identity/agent/INSTANCE.md").read_bytes()
    out = raw.decode("utf-8")
    assert "führt" in out and "Größe" in out and "&" not in out.split(heading())[1]
    tail = out.split(heading(), 1)[1]
    assert GERMAN in tail and FENCE in tail
    assert "@../../docs/x.md" in tail
    assert "@AGENTS.md" not in tail and "@ecosystem.acme.yaml" not in tail
    assert "Run the Phase-0" not in tail  # CORE text is dropped
    assert tail.index("@../../docs/x.md") < tail.index(GERMAN) < tail.index("```bash")
    assert "indexed by Phase 1: context-index.py --registries" in p.stdout
    assert "superseded by context-index.py --registries" in p.stdout
    assert "WARN" in p.stdout
    assert "git add identity/agent/INSTANCE.md" in p.stdout


def test_an_older_core_version_from_history_counts_as_core(w):
    write(w.fork, "CLAUDE.md", CORE_V1 + "\n@identity/agent/SOUL.md\n")
    commit(w.fork, "kept the older CORE text")
    p = mig(w.fork, "--write")
    assert p.returncode == 0, p.stdout + p.stderr
    assert not (w.fork / "identity/agent/INSTANCE.md").exists(), p.stdout


def test_dry_run_changes_nothing(w):
    write(w.fork, "CLAUDE.md", CORE_V2 + "\n" + GERMAN + "\n")
    write(w.fork, "context-budget.user.yaml", "items:\n  CLAUDE.md:\n    max_bytes: 9000\n")
    commit(w.fork, "prose")
    before = w.snapshot()
    p = mig(w.fork)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "would" in p.stdout
    assert w.snapshot() == before


def test_resolves_a_modify_delete_conflict(w):
    git(w.up, "rm", "-q", "CLAUDE.md"); commit(w.up, "AGENTS.md is the entry")
    write(w.fork, "CLAUDE.md", CORE_V2 + "\n" + GERMAN + "\n"); commit(w.fork, "prose")
    git(w.fork, "fetch", "-q", "upstream")
    m = git(w.fork, "merge", "--no-edit", "upstream/main", check=False)
    assert m.returncode != 0
    p = mig(w.fork, "--write")
    assert p.returncode == 0, p.stdout + p.stderr
    assert git(w.fork, "ls-files", "-u").stdout == ""
    assert GERMAN in w.text("identity/agent/INSTANCE.md")
    assert "Run the Phase-0" not in w.text("identity/agent/INSTANCE.md")
    git(w.fork, "add", "identity/agent/INSTANCE.md")
    git(w.fork, "commit", "-q", "--no-edit")
    assert not (w.fork / "CLAUDE.md").exists()


def test_budget_item_removed_and_rest_identical(w):
    budget = ("schema_version: 1\n"
              "items:\n"
              "  AGENTS.md:\n"
              "    max_bytes: 40000\n"
              "  CLAUDE.md:\n"
              "    max_bytes: 9000\n"
              "    note: >-\n"
              "      grown by onboarding\n"
              "\n"
              "      and overlays\n"
              "\n"
              "  # keep this comment\n"
              "  identity/agent/SOUL.md:\n"
              "    max_bytes: 4096\n")
    want = ("schema_version: 1\n"
            "items:\n"
            "  AGENTS.md:\n"
            "    max_bytes: 40000\n"
            "\n"
            "  # keep this comment\n"
            "  identity/agent/SOUL.md:\n"
            "    max_bytes: 4096\n")
    write(w.fork, "context-budget.user.yaml", budget); commit(w.fork, "budget")
    p = mig(w.fork, "--write")
    assert p.returncode == 0, p.stdout + p.stderr
    assert w.text("context-budget.user.yaml") == want
    assert "context-budget.user.yaml" in p.stdout


def test_missing_target_exits_2(tmp_path):
    w = World(tmp_path, identity=False)
    write(w.fork, "CLAUDE.md", CORE_V2 + "\n" + GERMAN + "\n"); commit(w.fork, "prose")
    for args in ((), ("--write",)):
        p = mig(w.fork, *args)
        assert p.returncode == 2, p.stdout + p.stderr
        assert "run /bridge-onboard D4 first or pass --to <file>" in p.stdout + p.stderr
    assert (w.fork / "CLAUDE.md").exists()


def test_to_creates_a_named_target(tmp_path):
    w = World(tmp_path, identity=False)
    write(w.fork, "CLAUDE.md", CORE_V2 + "\n" + GERMAN + "\n"); commit(w.fork, "prose")
    p = mig(w.fork, "--write", "--to", "notes/instance.md")
    assert p.returncode == 0, p.stdout + p.stderr
    assert GERMAN in w.text("notes/instance.md")


def test_runs_from_stdin(w):
    write(w.fork, "CLAUDE.md", CORE_V2 + "\n" + GERMAN + "\n"); commit(w.fork, "prose")
    with open(SCRIPT, "rb") as f:
        p = subprocess.run([sys.executable, "-", "--repo-root", str(w.fork)],
                           stdin=f, cwd=w.fork, env=ENV, capture_output=True, text=True)
    assert p.returncode == 0, p.stdout + p.stderr
    assert "would" in p.stdout


def test_idempotent(w):
    write(w.fork, "CLAUDE.md", CORE_V2 + "\n" + GERMAN + "\n"); commit(w.fork, "prose")
    assert mig(w.fork, "--write").returncode == 0
    p = mig(w.fork, "--write")
    assert p.returncode == 0 and "nothing to migrate" in p.stdout, p.stdout


def test_rerun_after_reintroduced_claude_md_does_not_duplicate(w):
    write(w.fork, "CLAUDE.md", CORE_V2 + "\n" + GERMAN + "\n"); commit(w.fork, "prose")
    assert mig(w.fork, "--write").returncode == 0
    first = w.text("identity/agent/INSTANCE.md")
    write(w.fork, "CLAUDE.md", CORE_V2 + "\n" + GERMAN + "\n")
    p = mig(w.fork, "--write")
    assert p.returncode == 0, p.stdout + p.stderr
    assert w.text("identity/agent/INSTANCE.md") == first
    assert w.text("identity/agent/INSTANCE.md").count(GERMAN) == 1
    assert not (w.fork / "CLAUDE.md").exists()


# ---------------------------------------------------------- shadow files --

def test_dot_claude_claude_md_imports_resolve_from_its_own_folder(w):
    git(w.fork, "rm", "-q", "CLAUDE.md"); commit(w.fork, "gone")
    write(w.fork, ".claude/CLAUDE.md", "@../AGENTS.md\n@../docs/y.md\n\nLokale Notiz für Claude.\n")
    p = mig(w.fork, "--write")
    assert p.returncode == 0, p.stdout + p.stderr
    out = w.text("identity/agent/INSTANCE.md")
    assert "Carried over from .claude/CLAUDE.md" in out
    assert "@../../docs/y.md" in out and "AGENTS.md" not in out.split("Carried over")[1]
    assert "Lokale Notiz für Claude." in out
    assert not (w.fork / ".claude/CLAUDE.md").exists()


def test_claude_local_md_untracked_is_removed(w):
    git(w.fork, "rm", "-q", "CLAUDE.md"); commit(w.fork, "gone")
    write(w.fork, "CLAUDE.local.md", "Meine lokale Zeile.\n")
    p = mig(w.fork, "--write")
    assert p.returncode == 0, p.stdout + p.stderr
    assert not (w.fork / "CLAUDE.local.md").exists()
    assert "Meine lokale Zeile." in w.text("identity/agent/INSTANCE.md")
    assert mig(w.fork, "--check").returncode == 0


# ------------------------------------------------------ target handling --

def test_ignored_target_is_kept_locally_and_not_added(w):
    write(w.fork, ".gitignore", "/identity/agent/*.md\n")
    write(w.fork, "CLAUDE.md", CORE_V2 + "\n" + GERMAN + "\n"); commit(w.fork, "prose")
    p = mig(w.fork, "--write")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "kept locally; tracked after the private-home step" in p.stdout
    assert "git add identity/agent/INSTANCE.md" not in p.stdout


def test_dry_run_reports_projected_size_against_cap(w):
    write(w.fork, "CLAUDE.md", CORE_V2 + "\n" + GERMAN + "\n"); commit(w.fork, "prose")
    p = mig(w.fork)
    assert "cap 4000" in p.stdout, p.stdout
    write(w.fork, "context-budget.user.yaml",
          "items:\n  identity/agent/INSTANCE.md:\n    max_bytes: 50\n")
    p = mig(w.fork)
    assert "cap 50" in p.stdout and "over" in p.stdout, p.stdout


def test_refuses_an_overlay_owned_target(w):
    write(w.fork, "overlays.lock.yaml",
          "schema_version: 1\noverlays:\n  acme:\n    files:\n"
          "      - src: identity/agent/INSTANCE.md\n"
          "        dest: identity/agent/INSTANCE.md\n")
    write(w.fork, "CLAUDE.md", CORE_V2 + "\n" + GERMAN + "\n"); commit(w.fork, "prose")
    p = mig(w.fork, "--write")
    assert p.returncode == 2, p.stdout + p.stderr
    assert "overlay" in p.stdout + p.stderr
    assert (w.fork / "CLAUDE.md").exists()


# -------------------------------------------------------- AGENTS.md mode --

def test_agents_md_mode_carries_fork_lines_and_restores_core(w):
    git(w.fork, "rm", "-q", "CLAUDE.md"); commit(w.fork, "gone")
    write(w.fork, "AGENTS.md", MANUAL + "\nEigene Regel für diese Instanz.\n")
    commit(w.fork, "edited the manual")
    assert mig(w.fork, "--check", "--file", "AGENTS.md").returncode == 1
    p = mig(w.fork, "--write", "--file", "AGENTS.md")
    assert p.returncode == 0, p.stdout + p.stderr
    assert w.text("AGENTS.md") == MANUAL
    out = w.text("identity/agent/INSTANCE.md")
    assert "Eigene Regel für diese Instanz." in out and "CORE manual text." not in out
    assert "Carried over from AGENTS.md" in out
    assert mig(w.fork, "--check", "--file", "AGENTS.md").returncode == 0


def test_plain_check_on_an_edited_agents_md_is_advisory(w):
    """A fork AGENTS.md can be a CORE change headed upstream or one the local
    ref has not fetched yet: plain --check (bridge-audit) warns, never fails."""
    git(w.fork, "rm", "-q", "CLAUDE.md"); commit(w.fork, "gone")
    write(w.fork, "AGENTS.md", MANUAL.replace("text.", "text, the next version."))
    commit(w.fork, "core: a manual change waiting on /bridge-promote")
    p = mig(w.fork, "--check")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "AGENTS.md" in p.stdout and "upstream/main" in p.stdout
    assert "git fetch" in p.stdout


def test_core_merged_from_a_second_remote_counts_as_core(w):
    """upstream/main is stale; the fork merged a newer CORE through another
    remote with the same URL. Nothing is diverged and --write changes nothing."""
    git(w.fork, "rm", "-q", "CLAUDE.md"); commit(w.fork, "gone")
    git(w.fork, "remote", "add", "open-bridge", str(w.up))
    write(w.up, "AGENTS.md", MANUAL + "\nA CORE paragraph added in v2.\n")
    commit(w.up, "core v2 manual")
    git(w.fork, "fetch", "-q", "open-bridge")
    git(w.fork, "merge", "-q", "--no-edit", "open-bridge/main")
    assert "v2" in w.text("AGENTS.md")
    assert mig(w.fork, "--check", "--file", "AGENTS.md").returncode == 0
    before = w.snapshot()
    p = mig(w.fork, "--write", "--file", "AGENTS.md")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "nothing to migrate" in p.stdout
    assert w.snapshot() == before


def test_restore_uses_the_merge_base_not_the_ref_tip(w):
    """The ref is ahead of what the fork merged: restoring from its tip would
    give AGENTS.md a different CORE version from the rest of the tree."""
    git(w.fork, "rm", "-q", "CLAUDE.md"); commit(w.fork, "gone")
    write(w.fork, "AGENTS.md", MANUAL + "\nEigene Regel.\n")
    commit(w.fork, "local rule in the manual")
    write(w.up, "AGENTS.md", MANUAL.replace("text.", "text, rewritten in v2."))
    commit(w.up, "core v2 manual")
    git(w.fork, "fetch", "-q", "upstream")
    dry = mig(w.fork, "--file", "AGENTS.md")
    assert "local rule in the manual" in dry.stdout, dry.stdout
    p = mig(w.fork, "--write", "--file", "AGENTS.md")
    assert p.returncode == 0, p.stdout + p.stderr
    assert w.text("AGENTS.md") == MANUAL
    assert "Eigene Regel." in w.text("identity/agent/INSTANCE.md")


def test_one_added_table_row_carries_exactly_that_row(w):
    table = ("# Manual\n\n" + IMPORTS + "\n## Layout\n\n| Family | When |\n|---|---|\n"
             "| `a/` | first |\n| `b/` | second |\n| `c/` | third |\n\nCORE manual text.\n")
    write(w.up, "AGENTS.md", table)
    commit(w.up, "core table")
    git(w.fork, "fetch", "-q", "upstream")
    git(w.fork, "merge", "-q", "--no-edit", "upstream/main")
    git(w.fork, "rm", "-q", "CLAUDE.md"); commit(w.fork, "gone")
    write(w.fork, "AGENTS.md", table.replace("| `c/` | third |\n",
                                             "| `c/` | third |\n| `mine/` | my own family |\n"))
    commit(w.fork, "my row")
    p = mig(w.fork, "--write", "--file", "AGENTS.md")
    assert p.returncode == 0, p.stdout + p.stderr
    assert w.text("AGENTS.md") == table
    out = w.text("identity/agent/INSTANCE.md")
    assert "| `mine/` | my own family |" in out
    assert "## Layout" in out          # names where the row sat
    for core_row in ("first", "second", "third", "CORE manual text"):
        assert core_row not in out, out


def test_check_is_green_on_a_core_agents_md(w):
    git(w.fork, "rm", "-q", "CLAUDE.md"); commit(w.fork, "gone")
    assert mig(w.fork, "--check").returncode == 0


# ---------------------------------------------------- divergence pointer --

def test_divergence_check_points_at_the_migration(w):
    git(w.up, "rm", "-q", "CLAUDE.md"); commit(w.up, "AGENTS.md is the entry")
    write(w.fork, "CLAUDE.md", CORE_V2 + "\n" + GERMAN + "\n"); commit(w.fork, "prose")
    git(w.fork, "fetch", "-q", "upstream")
    p = subprocess.run([sys.executable, str(DIVERGENCE), "--upstream", "upstream/main"],
                       cwd=w.fork, env=ENV, capture_output=True, text=True)
    assert "upstream removed CLAUDE.md: run python3 scripts/migrate-entry-file.py" in p.stdout, p.stdout


# ------------------------------------------------ mid-merge AGENTS.md --

def test_mid_merge_agents_md_diffs_against_the_merge_base_not_theirs(w):
    """Upstream rewrote the CORE line the fork wrote beside: only the fork's
    own line is carried; the stale CORE line is not."""
    git(w.fork, "rm", "-q", "CLAUDE.md"); commit(w.fork, "gone")
    v1 = MANUAL.replace("CORE manual text.\n", "old core line one\nCORE manual text.\n")
    write(w.up, "AGENTS.md", v1); commit(w.up, "c1")
    git(w.fork, "fetch", "-q", "upstream")
    git(w.fork, "merge", "-q", "--no-edit", "upstream/main")
    write(w.fork, "AGENTS.md", v1.replace("old core line one\n",
                                          "old core line one\nfork added line\n"))
    commit(w.fork, "fork line")
    v2 = v1.replace("old core line one", "NEW core line one")
    write(w.up, "AGENTS.md", v2); commit(w.up, "c2")
    git(w.fork, "fetch", "-q", "upstream")
    m = git(w.fork, "merge", "--no-edit", "upstream/main", check=False)
    assert m.returncode != 0 and "AGENTS.md" in git(w.fork, "ls-files", "-u").stdout
    p = mig(w.fork, "--write", "--file", "AGENTS.md")
    assert p.returncode == 0, p.stdout + p.stderr
    out = w.text("identity/agent/INSTANCE.md")
    assert "fork added line" in out
    assert "old core line one" not in out and "NEW core line one" not in out, out
    assert w.text("AGENTS.md") == v2
    assert git(w.fork, "ls-files", "-u").stdout == ""


# ------------------------------------------------------ symlinked entry --

@pytest.mark.skipif(not hasattr(os, "symlink"), reason="no symlinks")
def test_a_claude_md_linked_to_agents_md_is_left_alone(w):
    """One manual for both tools: nothing to carry, --check green."""
    git(w.fork, "rm", "-q", "CLAUDE.md"); commit(w.fork, "gone")
    os.symlink("AGENTS.md", w.fork / "CLAUDE.md")
    before = w.snapshot()
    assert mig(w.fork, "--check").returncode == 0
    p = mig(w.fork, "--write")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "link to AGENTS.md" in p.stdout and "nothing to migrate" in p.stdout
    assert w.snapshot() == before
    assert not (w.fork / "identity/agent/INSTANCE.md").exists()


# ------------------------------------------- an AGENTS.md without slots --

def test_pre_import_agents_md_refuses_write_and_says_merge_first(tmp_path):
    """Migrating before the merge would drop IDENTITY/SOUL and park the carried
    text in a file nothing loads."""
    w = World(tmp_path, manual=OLD_MANUAL)
    write(w.fork, "CLAUDE.md", CORE_V2 + "\n@identity/agent/IDENTITY.md\n\n" + GERMAN + "\n")
    commit(w.fork, "prose")
    before = w.snapshot()
    dry = mig(w.fork)
    assert dry.returncode == 0, dry.stdout + dry.stderr
    assert "merge upstream first, then migrate mid-merge" in dry.stdout
    assert "(AGENTS.md imports it)" not in dry.stdout
    p = mig(w.fork, "--write")
    assert p.returncode == 2, p.stdout + p.stderr
    assert "merge upstream first, then migrate mid-merge" in p.stdout + p.stderr
    assert w.snapshot() == before


def test_mid_merge_reads_the_incoming_agents_md(tmp_path):
    """The fork is on a pre-import AGENTS.md; the merge brings the slot in.
    Mid-merge the incoming version is the one in force, so --write proceeds."""
    w = World(tmp_path, manual=OLD_MANUAL)
    write(w.up, "AGENTS.md", MANUAL); git(w.up, "rm", "-q", "CLAUDE.md")
    commit(w.up, "AGENTS.md is the entry, with the import slot")
    write(w.fork, "CLAUDE.md", CORE_V2 + "\n@identity/agent/IDENTITY.md\n\n" + GERMAN + "\n")
    commit(w.fork, "prose")
    git(w.fork, "fetch", "-q", "upstream")
    assert git(w.fork, "merge", "--no-edit", "upstream/main", check=False).returncode != 0
    p = mig(w.fork, "--write")
    assert p.returncode == 0, p.stdout + p.stderr
    assert "(AGENTS.md imports it)" in p.stdout
    assert GERMAN in w.text("identity/agent/INSTANCE.md")


def test_agents_md_mode_refuses_to_restore_a_pre_import_version(tmp_path):
    w = World(tmp_path, manual=OLD_MANUAL)
    git(w.fork, "rm", "-q", "CLAUDE.md"); commit(w.fork, "gone")
    write(w.fork, "AGENTS.md", OLD_MANUAL + "\nEigene Regel.\n"); commit(w.fork, "rule")
    before = w.snapshot()
    p = mig(w.fork, "--write", "--file", "AGENTS.md")
    assert p.returncode == 2, p.stdout + p.stderr
    assert "merge upstream first, then migrate mid-merge" in p.stdout + p.stderr
    assert w.snapshot() == before


def test_divergence_check_counts_instance_md_as_user():
    """The migration's default target is USER, as the promote router says;
    the sentinel must not report a fork that migrated as diverged CORE."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("divergence", DIVERGENCE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    for rel in ("identity/agent/INSTANCE.md", "identity/agent/IDENTITY.md",
                "identity/agent/SOUL.md"):
        assert mod.is_user(rel), rel
    assert not mod.is_user("identity/agent/README.md")
