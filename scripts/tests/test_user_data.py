"""Instance data: out of a public clone by default, backed up by a private one, never a secret.

The case behind this file, measured on 2026-09-25. The shipped `.gitignore`
listed the instance folders family by family (open-bridge#245). That kept a
clone of the PUBLIC repo from committing them, and it cost every PRIVATE
instance its backup: a file it already tracked stayed tracked, a NEW one under
`infra/secret-stores/` was left out of every commit without a word. A leak
attempt fails loudly at the push guard. A lost backup fails silently, and is
found the day the file is needed.

The model these tests hold:

* The shipped `.gitignore` ignores instance data with GENERIC patterns
  (`/identity/*/*.yaml`), so any clone is safe before anything has run, and a
  family added tomorrow is covered without editing a list.
* On a private origin, `scripts/user-data.py arm` writes `identity/.gitignore`,
  `infra/.gitignore`, `workflow/.gitignore` and `work/.gitignore`, which negate
  those patterns (a deeper .gitignore wins over the root one). They are USER
  files, committed with the instance, so a fresh clone of the private repo backs
  up correctly before setup has ever run there. Root files have fixed names;
  `arm` stages them once with `git add -f`, after which being ignored no longer
  matters.
* Whatever enters a commit is scanned for credentials first.

Each test builds a throwaway repo and measures a promise against git itself.
Fake credentials are assembled at run time, so this file carries no literal a
leak scanner would have to be taught to skip.
"""

from __future__ import annotations

import importlib.util
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
SCRIPT = REPO / "scripts" / "user-data.py"
CLASSIFIER = REPO / "scripts" / "lib" / "remote-class.sh"
PRE_COMMIT = REPO / "scripts" / "hooks" / "pre-commit"

FAKE_TOKEN = "ghp_" + "A1b2C3d4" * 5          # github-token shape, not a token
FAMILIES = ("identity/personas", "identity/accounts", "infra/secret-stores",
            "infra/object-stores", "workflow/workloads")


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


UD = _load("user_data_under_test", SCRIPT)


def _env(tmp_path: Path) -> dict:
    """Git that reads no global or system config of the machine running this."""
    env = dict(os.environ)
    env.update(GIT_CONFIG_GLOBAL=str(tmp_path / "gitconfig"),
               GIT_CONFIG_NOSYSTEM="1",
               GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.invalid",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@example.invalid",
               # a gh that always fails: classification stays offline
               PATH=f"{tmp_path / 'bin'}{os.pathsep}{env.get('PATH', '')}")
    return env


def _git(repo: Path, *args, env=None, check=True):
    return subprocess.run(["git", "-C", str(repo), *args], env=env,
                          capture_output=True, text=True, check=check)


def _run(repo: Path, *args, env=None, script=SCRIPT):
    return subprocess.run([sys.executable, str(script), *args], cwd=repo, env=env,
                          capture_output=True, text=True)


@pytest.fixture
def bridge(tmp_path):
    """A small Bridge on a user branch, carrying the SHIPPED .gitignore."""
    (tmp_path / "bin").mkdir()
    gh = tmp_path / "bin" / "gh"
    gh.write_text("#!/bin/sh\nexit 1\n")
    gh.chmod(0o755)
    env = _env(tmp_path)
    repo = tmp_path / "bridge"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main", env=env)
    shutil.copy(REPO / ".gitignore", repo / ".gitignore")
    for family in FAMILIES:
        d = repo / family
        d.mkdir(parents=True)
        (d / "_template.yaml").write_text("name: \"\"\n")
        (d / "_schema.yaml").write_text("type: object\n")
        (d / "mine.yaml").write_text("name: mine\n")
    (repo / "infra/remotes/mac").mkdir(parents=True)
    (repo / "infra/remotes/mac/service.yaml").write_text("port: 1\n")
    (repo / "identity/agent").mkdir(parents=True)
    (repo / "identity/agent/README.md").write_text("core\n")
    (repo / "identity/agent/SOUL.md").write_text("user\n")
    (repo / "work/memory").mkdir(parents=True)
    (repo / "work/memory/user_role.md").write_text("fact\n")
    (repo / "bridge-config.yaml").write_text("identity: {}\n")
    (repo / "ecosystem.yaml").write_text("repos: []\n")
    (repo / "ecosystem.example.yaml").write_text("repos: []\n")
    _git(repo, "add", ".gitignore", env=env)
    _git(repo, "commit", "-qm", "core", "--no-verify", env=env)
    _git(repo, "checkout", "-q", "-b", "user/test", env=env)
    return repo, env


def _ignored(repo: Path, path: str, env) -> bool:
    return _git(repo, "check-ignore", "-q", "--no-index", path, env=env,
                check=False).returncode == 0


def _staged(repo: Path, env) -> list:
    return _git(repo, "diff", "--cached", "--name-only", env=env).stdout.split()


def _set_origin(repo: Path, url: str, env, *, private_marker: bool = False):
    _git(repo, "remote", "add", "origin", url, env=env)
    if private_marker:
        slug = re.sub(r"^.*github\.com[:/]|\.git$", "", url)
        (repo / ".bridge-origin").write_text(f"repo: {slug}\nis_public: false\n")


PRIVATE = "git@github.com:someone/their-bridge.git"
PUBLIC = "git@github.com:bks-lab/open-bridge.git"

INSTANCE = [*(f"{f}/mine.yaml" for f in FAMILIES), "identity/agent/SOUL.md",
            "work/memory/user_role.md"]
CORE_COMPANIONS = [*(f"{f}/_template.yaml" for f in FAMILIES),
                   *(f"{f}/_schema.yaml" for f in FAMILIES),
                   "identity/agent/README.md", "ecosystem.example.yaml"]


# ── the shipped .gitignore ────────────────────────────────────────────────────

def test_the_shipped_gitignore_carries_exactly_the_generated_block():
    """One source: user-data.py. The shipped file is its output, not a second list."""
    text = (REPO / ".gitignore").read_text()
    assert UD.BEGIN in text and UD.END in text, "the managed block left the .gitignore"
    block = text.split(UD.BEGIN, 1)[1].split(UD.END, 1)[0]
    rules = [ln for ln in block.splitlines() if ln and not ln.startswith("#")]
    assert rules == UD.shipped_patterns()


def test_no_family_is_named_one_by_one_in_the_shipped_gitignore():
    """The #245 shape: a per-family list falls behind the tree."""
    text = (REPO / ".gitignore").read_text()
    named = re.findall(r"^!?/?(?:identity|infra|workflow)/(?!\*)[a-z-]+/\*\.ya?ml", text, re.M)
    assert named == [], named


def test_every_root_instance_file_the_router_knows_is_covered(bridge):
    """The scope router and the ignore must agree on what a root instance file is."""
    repo, env = bridge
    router = _load("router_for_user_data", REPO / "scripts" / "categorize-commits.py")
    roots = [p[1:-1].replace("\\.", ".") for p in router.USER_PATTERNS
             if re.fullmatch(r"\^[a-z\\.-]+\$", p)]
    roots = [r for r in roots if r not in (".gitignore", ".bridge-origin")]
    assert "bridge-config.yaml" in roots
    for name in roots:
        assert _ignored(repo, name, env), name
        assert UD.is_instance_path(name), name


# ── a clone nothing has run in yet ────────────────────────────────────────────

def test_a_fresh_clone_keeps_instance_data_out_before_anything_ran(bridge):
    repo, env = bridge
    for path in INSTANCE + ["bridge-config.yaml", "ecosystem.yaml", "ecosystem.my_org.yaml"]:
        assert _ignored(repo, path, env), path
    for path in CORE_COMPANIONS:
        assert not _ignored(repo, path, env), path


# ── arm ───────────────────────────────────────────────────────────────────────

def test_arm_on_a_private_origin_backs_everything_up(bridge):
    repo, env = bridge
    _set_origin(repo, PRIVATE, env, private_marker=True)
    out = _run(repo, "arm", env=env)
    assert out.returncode == 0, out.stderr
    assert "private" in out.stdout
    for path in INSTANCE + ["infra/remotes/mac/service.yaml"]:
        assert not _ignored(repo, path, env), path
    for path in CORE_COMPANIONS:
        assert not _ignored(repo, path, env), path
    staged = _staged(repo, env)
    assert "bridge-config.yaml" in staged and "ecosystem.yaml" in staged
    for neg in UD.NEGATION_FILES:
        assert (repo / neg).is_file(), neg


def test_a_family_added_later_is_backed_up_without_another_arm(bridge):
    repo, env = bridge
    _set_origin(repo, PRIVATE, env, private_marker=True)
    _run(repo, "arm", env=env)
    (repo / "workflow/meetings").mkdir()
    (repo / "workflow/meetings/weekly.yaml").write_text("x: 1\n")
    assert not _ignored(repo, "workflow/meetings/weekly.yaml", env)


def test_a_clone_of_the_private_repo_backs_up_before_setup_ran(bridge, tmp_path):
    """The negation files travel with the commits, so the next clone is right at once."""
    repo, env = bridge
    _set_origin(repo, PRIVATE, env, private_marker=True)
    _run(repo, "arm", env=env)
    _git(repo, "add", *UD.NEGATION_FILES, env=env)
    _git(repo, "commit", "-qm", "backup", "--no-verify", env=env)
    clone = tmp_path / "clone"
    _git(tmp_path, "clone", "-q", "-b", "user/test", str(repo), str(clone), env=env)
    (clone / "infra/secret-stores").mkdir(parents=True, exist_ok=True)
    (clone / "infra/secret-stores/new.yaml").write_text("x: 1\n")
    assert not _ignored(clone, "infra/secret-stores/new.yaml", env)


@pytest.mark.parametrize("url", [PUBLIC, None, "git@github.com:someone/unverified.git"])
def test_arm_on_a_public_or_unknown_origin_writes_nothing(bridge, url):
    repo, env = bridge
    if url:
        _set_origin(repo, url, env)
    out = _run(repo, "arm", env=env)
    assert out.returncode == 0, out.stderr
    for neg in UD.NEGATION_FILES:
        assert not (repo / neg).exists(), neg
    assert _staged(repo, env) == []
    assert _ignored(repo, "infra/secret-stores/mine.yaml", env)


def test_arm_never_deletes_negation_files_when_the_origin_is_not_confirmed(bridge):
    """gh offline makes a private origin look unknown. Deleting would drop the backup."""
    repo, env = bridge
    _set_origin(repo, PRIVATE, env, private_marker=True)
    _run(repo, "arm", env=env)
    (repo / ".bridge-origin").unlink()
    out = _run(repo, "arm", env=env)
    assert out.returncode == 0
    for neg in UD.NEGATION_FILES:
        assert (repo / neg).is_file(), neg
    assert "not confirmed private" in out.stdout


def test_arm_is_idempotent_and_keeps_lines_it_did_not_write(bridge):
    repo, env = bridge
    _set_origin(repo, PRIVATE, env, private_marker=True)
    (repo / "infra/.gitignore").write_text("*.local\n")
    _run(repo, "arm", env=env)
    first = (repo / "infra/.gitignore").read_text()
    _run(repo, "arm", env=env)
    assert (repo / "infra/.gitignore").read_text() == first
    assert first.count(UD.BEGIN) == 1
    assert "*.local" in first


def test_arm_stages_root_files_only_on_a_user_branch(bridge):
    repo, env = bridge
    _set_origin(repo, PRIVATE, env, private_marker=True)
    _git(repo, "checkout", "-q", "main", env=env)
    _run(repo, "arm", env=env)
    assert _staged(repo, env) == []


# ── check ─────────────────────────────────────────────────────────────────────

def test_check_names_instance_data_a_private_clone_still_ignores(bridge):
    """The other bridge's case: private origin, never armed."""
    repo, env = bridge
    _set_origin(repo, PRIVATE, env, private_marker=True)
    out = _run(repo, "check", env=env)
    assert out.returncode == 1
    assert "infra/secret-stores/mine.yaml" in out.stdout
    assert "bin/setup" in out.stdout


def test_check_is_quiet_once_armed(bridge):
    repo, env = bridge
    _set_origin(repo, PRIVATE, env, private_marker=True)
    _run(repo, "arm", env=env)
    out = _run(repo, "check", env=env)
    assert out.returncode == 0, out.stdout


def test_check_is_quiet_on_a_public_clone(bridge):
    repo, env = bridge
    _set_origin(repo, PUBLIC, env)
    assert _run(repo, "check", env=env).returncode == 0


# ── scan-staged ───────────────────────────────────────────────────────────────

def _stage(repo, path, data, env):
    p = repo / path
    p.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(data, bytes):
        p.write_bytes(data)
    else:
        p.write_text(data, encoding="utf-8")
    _git(repo, "add", "-f", path, env=env)


def test_scan_blocks_a_staged_credential_and_never_prints_it(bridge):
    repo, env = bridge
    _stage(repo, "infra/secret-stores/mine.yaml", f"token: {FAKE_TOKEN}\n", env)
    out = _run(repo, "scan-staged", env=env)
    assert out.returncode == 1
    assert "infra/secret-stores/mine.yaml:1" in out.stdout
    assert "github-token" in out.stdout
    assert FAKE_TOKEN not in out.stdout + out.stderr


def test_scan_passes_a_reference_uri(bridge):
    repo, env = bridge
    _stage(repo, "identity/accounts/mine.yaml",
           "token_ref: keychain://gh-bridge/agent\nvault: azure-keyvault://kv/sp\n", env)
    assert _run(repo, "scan-staged", env=env).returncode == 0


def test_scan_reads_the_index_not_the_working_tree(bridge):
    """A secret typed after `git add` is not in the commit; one removed after is."""
    repo, env = bridge
    _stage(repo, "infra/secret-stores/mine.yaml", f"token: {FAKE_TOKEN}\n", env)
    (repo / "infra/secret-stores/mine.yaml").write_text("token_ref: keychain://x\n")
    assert _run(repo, "scan-staged", env=env).returncode == 1
    _stage(repo, "infra/object-stores/mine.yaml", "root: file:///srv\n", env)
    _git(repo, "reset", "-q", "infra/secret-stores/mine.yaml", env=env)
    (repo / "infra/object-stores/mine.yaml").write_text(f"token: {FAKE_TOKEN}\n")
    assert _run(repo, "scan-staged", env=env).returncode == 0


def test_scan_reaches_nested_instance_data(bridge):
    repo, env = bridge
    _stage(repo, "infra/channels/bots/client/bot.yaml", f"token: {FAKE_TOKEN}\n", env)
    assert _run(repo, "scan-staged", env=env).returncode == 1


def test_scan_skips_shipped_fixtures_but_reads_templates(bridge):
    repo, env = bridge
    _stage(repo, "workflow/workloads/_tests/invalid/leak.yaml", f"t: {FAKE_TOKEN}\n", env)
    assert _run(repo, "scan-staged", env=env).returncode == 0
    _stage(repo, "workflow/workloads/_template.yaml", f"t: {FAKE_TOKEN}\n", env)
    assert _run(repo, "scan-staged", env=env).returncode == 1


def test_scan_handles_a_non_ascii_path(bridge):
    repo, env = bridge
    _stage(repo, "identity/personas/müller.yaml", f"t: {FAKE_TOKEN}\n", env)
    out = _run(repo, "scan-staged", env=env)
    assert out.returncode == 1, out.stdout + out.stderr


def test_scan_skips_a_binary_blob(bridge):
    repo, env = bridge
    _stage(repo, "infra/remotes/mac/firmware.yaml", b"\x00\x01" + FAKE_TOKEN.encode(), env)
    assert _run(repo, "scan-staged", env=env).returncode == 0


def test_scan_honours_the_fixture_pragma(bridge):
    repo, env = bridge
    _stage(repo, "workflow/workloads/mine.yaml",
           f"example: {FAKE_TOKEN}  # pragma: allowlist secret\n", env)
    assert _run(repo, "scan-staged", env=env).returncode == 0


def test_scan_does_not_block_personal_data(bridge):
    """A persona carries a tax id and an IBAN by design; that is not a credential."""
    repo, env = bridge
    _stage(repo, "identity/personas/mine.yaml",
           "iban: DE89370400440532013000\nemail: someone@example.invalid\n", env)
    assert _run(repo, "scan-staged", env=env).returncode == 0


def test_scan_does_not_mistake_an_id_for_a_key(bridge):
    """`sk-task-close-postmortem` is a skill id in a real instance file, not a key."""
    repo, env = bridge
    _stage(repo, "infra/remotes/mac/regions.yaml",
           '- {"id": "sk-task-close-postmortem-and-more-words"}\n', env)
    assert _run(repo, "scan-staged", env=env).returncode == 0


@pytest.mark.parametrize("path", ["bridge-config.yaml", "work/memory/reference_api.md",
                                  "ecosystem.my_org.yaml"])
def test_scan_covers_root_files_and_memory(bridge, path):
    repo, env = bridge
    _stage(repo, path, f"the key was {FAKE_TOKEN}\n", env)
    assert _run(repo, "scan-staged", env=env).returncode == 1


def test_scan_says_so_when_it_cannot_scan(bridge, tmp_path):
    """No skill, no scan: that is exit 3 and a sentence, never a silent pass."""
    repo, env = bridge
    lone = tmp_path / "lone" / "scripts"
    lone.mkdir(parents=True)
    shutil.copy(SCRIPT, lone / "user-data.py")
    _stage(repo, "infra/secret-stores/mine.yaml", f"t: {FAKE_TOKEN}\n", env)
    out = _run(repo, "scan-staged", env=env, script=lone / "user-data.py")
    assert out.returncode == 3
    assert "NOT scanned" in out.stdout + out.stderr


# ── the hooks that call it ────────────────────────────────────────────────────

def _pre_commit(repo, env):
    return subprocess.run(["sh", str(PRE_COMMIT)], cwd=repo, env=env,
                          capture_output=True, text=True)


def test_pre_commit_blocks_a_staged_credential_on_any_branch(bridge):
    repo, env = bridge
    _git(repo, "checkout", "-q", "main", env=env)
    _stage(repo, "infra/secret-stores/mine.yaml", f"token: {FAKE_TOKEN}\n", env)
    out = _pre_commit(repo, env)
    assert out.returncode == 1, out.stderr
    assert "infra/secret-stores/mine.yaml" in out.stderr
    assert FAKE_TOKEN not in out.stderr


def test_pre_commit_lets_a_clean_instance_file_through(bridge):
    repo, env = bridge
    _stage(repo, "infra/secret-stores/mine.yaml", "path_ref: keychain://x\n", env)
    assert _pre_commit(repo, env).returncode == 0


def test_pre_commit_warns_about_the_backup_gap_on_an_instance_branch(bridge):
    """The gap is a file that is never staged, so the warning cannot wait for one."""
    repo, env = bridge
    _set_origin(repo, PRIVATE, env, private_marker=True)
    (repo / "work/log.md").write_text("| row |\n")
    _git(repo, "add", "work/log.md", env=env)          # a routine commit, nothing else
    out = _pre_commit(repo, env)
    assert out.returncode == 0                          # warn, never block
    assert "BACKUP" in out.stderr
    assert "infra/secret-stores/mine.yaml" in out.stderr


# ── the one classifier ────────────────────────────────────────────────────────

@pytest.mark.parametrize("url,marker,expect", [
    (PUBLIC, False, "public"),
    ("https://github.com/BKS-Lab/open-bridge", False, "public"),
    (PRIVATE, True, "private"),
    (PRIVATE, False, "unknown"),
])
def test_the_classifier_answers_what_the_push_guard_answers(bridge, url, marker, expect):
    repo, env = bridge
    _set_origin(repo, url, env, private_marker=marker)
    out = subprocess.run(["sh", str(CLASSIFIER), url], cwd=repo, env=env,
                         capture_output=True, text=True)
    assert out.returncode == 0, out.stderr
    assert out.stdout.strip() == expect


def test_a_stale_private_marker_does_not_vouch_for_another_remote(bridge):
    repo, env = bridge
    (repo / ".bridge-origin").write_text("repo: someone/old-home\nis_public: false\n")
    out = subprocess.run(["sh", str(CLASSIFIER), "git@github.com:someone/new-home.git"],
                         cwd=repo, env=env, capture_output=True, text=True)
    assert out.stdout.strip() == "unknown"


def test_scan_refuses_content_it_could_not_read(bridge):
    """An index entry whose blob is missing: not a pass, exit 2."""
    repo, env = bridge
    _git(repo, "update-index", "--add", "--info-only", "--cacheinfo",
         "100644," + "1" * 40 + ",infra/secret-stores/ghost.yaml", env=env)
    out = _run(repo, "scan-staged", env=env)
    assert out.returncode == 2, out.stdout + out.stderr
    assert "ghost.yaml" in out.stdout


@pytest.mark.parametrize("path", [*UD.NEGATION_FILES, "ecosystem.my_org.yaml",
                                  "ecosystem.acme.eu.yaml", "edges.yaml"])
def test_the_scope_router_never_promotes_instance_data(path):
    router = _load("router_never_promotes", REPO / "scripts" / "categorize-commits.py")
    assert router.classify_file(path) != "core", path


def test_check_ignores_what_was_ignored_on_purpose(bridge):
    """.DS_Store, caches and firmware blobs are ignored by their own rules, not by the
    instance-data block. Measured on the first private instance after #253: 22 such
    files, and a warning on every commit teaches its reader to skip it."""
    repo, env = bridge
    _set_origin(repo, PRIVATE, env, private_marker=True)
    _run(repo, "arm", env=env)
    with open(repo / ".gitignore", "a") as fh:
        fh.write(".DS_Store\n.pytest_cache/\ninfra/remotes/mac/firmware/\n")
    (repo / "infra/remotes/.DS_Store").write_bytes(b"\0")
    (repo / "infra/remotes/mac/.pytest_cache").mkdir()
    (repo / "infra/remotes/mac/.pytest_cache/README.md").write_text("cache\n")
    (repo / "infra/remotes/mac/firmware").mkdir()
    (repo / "infra/remotes/mac/firmware/blob.yaml").write_text("x: 1\n")
    out = _run(repo, "check", env=env)
    assert out.returncode == 0, out.stdout



def test_designs_are_covered_like_the_agent_files():
    """A design is Markdown: the shipped block ignores it, the template still ships, arm re-allows it."""
    assert UD.covered("identity/designs/brand.md")
    assert UD.is_instance_path("identity/designs/brand.md")
    assert not UD.covered("identity/designs/_template.md")
    assert not UD.covered("identity/designs/_schema.yaml")
    assert "/identity/designs/*.md" in UD.shipped_patterns()
    assert "!/identity/designs/_*.md" in UD.shipped_patterns()
    assert "!/designs/*.md" in UD.NEGATIONS["identity/.gitignore"]
