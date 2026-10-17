#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""The `.env` commit guard — drives the LIVE scripts/hooks/pre-commit.

`.gitignore` already excludes `.env` at every depth, and no `.env` has ever
been committed to this repo (verified 2026-08-01 against every object in every
ref). But `.gitignore` is advisory: `git add -f` walks straight past it, and
that is not hypothetical — this session used exactly that command, legitimately,
to track an empty `.env.template`.

So the rule "a `.env` can never be committed" needs a second layer that does not
depend on anyone remembering. This one BLOCKS, unlike the rest of pre-commit,
which is warn-only by design — the hook's own header draws that line: pre-push
blocks "because it is a leak guard", and a staged `.env` is a leak.

Two properties beyond the obvious, each a real hole in the first draft:

  1. It must run on EVERY branch. The rest of pre-commit is instance-only
     (`user/*` + a work/ tree) and exits 0 immediately elsewhere — so a `.env`
     staged on `main` would have sailed through the entire hook.
  2. `.env.template` / `.env.example` are documentation and must stay
     committable — but only while they are EMPTY. A template someone filled in
     for a quick test is a secrets file wearing a template's name.

Run: python3 -m pytest scripts/tests/test_precommit_env_guard.py -q
"""
from __future__ import annotations

import pathlib
import shutil
import subprocess
import sys
import tempfile

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
HOOK = REPO / "scripts" / "hooks" / "pre-commit"


def _run_hook(files: dict[str, str], branch: str = "user/test") -> subprocess.CompletedProcess:
    """Stage `files` (path -> content) in a throwaway repo and run the real hook."""
    with tempfile.TemporaryDirectory() as td:
        root = pathlib.Path(td)
        subprocess.run(["git", "init", "-q", "-b", branch], cwd=root, check=True)
        subprocess.run(["git", "config", "user.email", "t@t"], cwd=root, check=True)
        subprocess.run(["git", "config", "user.name", "t"], cwd=root, check=True)
        # a work/ tree so the instance-only gates below the guard also engage
        (root / "work").mkdir()
        (root / "work" / "log.md").write_text("# log\n")
        for rel, content in files.items():
            p = root / rel
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(content)
            subprocess.run(["git", "add", "-f", "--", rel], cwd=root, check=True)
        hook = root / "pre-commit"
        shutil.copy2(HOOK, hook)
        return subprocess.run(
            ["sh", str(hook)], cwd=root, capture_output=True, text=True,
        )


SECRET_ENV = (
    "ACME_TENANT_ID=b2c3d4e5-1111-2222-3333-444455556666\n"
    "ACME_CLIENT_SECRET=Abc8Q~verySecretValueGoesRightHere00\n"
)


# ------------------------------------------------------------------- must block
@pytest.mark.parametrize("path", [
    ".env",
    "skills/acme-files/.env",
    "a/b/c/d/.env",
    ".env.local",
    ".env.production",
])
def test_staged_env_is_refused(path: str):
    proc = _run_hook({path: SECRET_ENV})
    assert proc.returncode != 0, (
        f"`git add -f {path}` + commit was allowed. .gitignore does not stop a forced "
        f"add, so the hook is the only thing between a secrets file and a commit.\n"
        f"stderr: {proc.stderr[-400:]}"
    )
    assert path in proc.stderr, f"the hook blocked but never named {path}"


def test_guard_runs_on_core_branches_too():
    """The rest of pre-commit is instance-only and exits 0 on main — this must not."""
    proc = _run_hook({".env": SECRET_ENV}, branch="main")
    assert proc.returncode != 0, (
        "a .env staged on `main` passed. The instance-only branch gate (user/* + work/) "
        "sits above the other checks; the secret guard must run before it, on every branch."
    )


def test_filled_in_template_is_refused():
    """A template with real values is a secrets file wearing a template's name."""
    proc = _run_hook({".env.template": "API_TOKEN=sk-live-realvalue-not-a-placeholder\n"})
    assert proc.returncode != 0, (
        ".env.template with a non-empty value was allowed. The exemption is for EMPTY "
        "documentation, not for the filename."
    )


# --------------------------------------------------------------- must NOT block
def test_empty_template_is_allowed():
    proc = _run_hook({
        ".env.template": "# needed variables\nEXAMPLE_TENANT_ID=\nEXAMPLE_CLIENT_SECRET=\n"
    })
    assert proc.returncode == 0, (
        "the EMPTY template was refused. It is documentation of which variables a skill "
        f"needs, and an overlay consumer needs it.\nstderr: {proc.stderr[-400:]}"
    )


def test_empty_example_is_allowed():
    proc = _run_hook({"tools/.env.example": 'EXAMPLE_SESSION=""\nTOKEN=\n'})
    assert proc.returncode == 0, (
        f".env.example with empty values was refused.\nstderr: {proc.stderr[-400:]}"
    )


def test_ordinary_files_are_untouched():
    proc = _run_hook({"skills/x/SKILL.md": "# hello\n", "scripts/y.py": "print(1)\n"})
    assert proc.returncode == 0, (
        f"an ordinary commit was blocked — the guard over-reaches.\nstderr: {proc.stderr[-400:]}"
    )


def test_a_file_merely_mentioning_env_is_untouched():
    """`.env` in a path segment or a docs filename is not a secrets file."""
    proc = _run_hook({
        "docs/dotenv-setup.md": "copy .env.template to .env\n",
        "skills/x/env/config.yaml": "key: value\n",
    })
    assert proc.returncode == 0, (
        f"a doc about .env was blocked.\nstderr: {proc.stderr[-400:]}"
    )


# ------------------------------------------------------------ the repo is clean
def test_no_env_is_tracked_in_this_repo():
    out = subprocess.run(
        ["git", "ls-files"], cwd=REPO, capture_output=True, text=True,
    ).stdout.splitlines()
    tracked = [p for p in out if pathlib.PurePath(p).name == ".env"]
    assert not tracked, f"a .env is tracked right now: {tracked}"


def test_no_env_has_ever_been_committed():
    """History, not just HEAD — an ignore rule cannot undo a past commit."""
    proc = subprocess.run(
        ["git", "rev-list", "--all", "--objects"],
        cwd=REPO, capture_output=True, text=True,
    )
    ever = {
        line.split(" ", 1)[1]
        for line in proc.stdout.splitlines()
        if " " in line
    }
    hits = sorted(p for p in ever if pathlib.PurePath(p).name == ".env")
    assert not hits, (
        f".env exists in this repo's history: {hits}. Removing it now needs a history "
        "rewrite AND credential rotation — the ignore rule alone does not help."
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
