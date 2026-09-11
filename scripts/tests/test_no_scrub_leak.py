#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Regression tests for the leak gate — scripts/no-scrub-leak.py.

This scanner is the hard gate in front of `/promote` and `/contribute`. Its
answer is trusted: a clean exit is read as "these files carry no secrets and no
personal data, ship them". A gate that says clean about a file it never opened
is worse than no gate, because the caller stops looking.

`scan()` swallowed every `OSError` and returned nothing, while `main()` still
counted the path in its "N file(s) scanned" line. A path that does not resolve
therefore produced `clean (1 file(s) scanned)` and exit 0.

That is not theoretical. It fired on 2026-09-11 when four paths were passed
through an unquoted shell variable under zsh, which does not word-split: the
four arrived as one nonsense string, the gate reported clean, and nothing had
been read. The "1" in the count was the only signal, and only because somebody
expected a 4.

The distinction the fix draws:

  * paths named on the command line are ASSERTED by the caller. If one cannot be
    opened, the gate has not done its job and must say so.
  * the repo-wide sweep derives its own list from `git ls-files`, where a file
    deleted in the worktree but not yet staged is an ordinary transient state.
    Those stay skipped.

Run: python3 -m pytest scripts/tests/test_no_scrub_leak.py -q
"""
from __future__ import annotations

import pathlib
import subprocess
import sys

REPO = pathlib.Path(__file__).resolve().parents[2]
SCANNER = REPO / "scripts" / "no-scrub-leak.py"


def run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCANNER), *args],
        capture_output=True, text=True, cwd=REPO,
    )


def test_missing_path_is_an_error_not_a_clean_bill(tmp_path):
    """The whole point: an unopenable path must never read as clean."""
    res = run(str(tmp_path / "does-not-exist.md"))
    assert res.returncode != 0, (
        "a path that cannot be opened exited 0; the caller reads that as "
        "'scanned and clean' for a file the gate never saw"
    )
    assert res.returncode != 1, (
        "exit 1 means 'leak found'; an unreadable path is a gate failure and "
        "needs its own code so overlay.py can tell them apart"
    )
    assert "does-not-exist.md" in (res.stderr + res.stdout)


def test_directory_is_also_an_error(tmp_path):
    """open() on a directory raises OSError too, and was swallowed the same way."""
    res = run(str(tmp_path))
    assert res.returncode not in (0, 1)


def test_one_bad_path_fails_the_batch(tmp_path):
    """A clean file alongside a missing one must not produce a clean exit."""
    good = tmp_path / "clean.md"
    good.write_text("nothing interesting here\n", encoding="utf-8")
    res = run(str(good), str(tmp_path / "missing.md"))
    assert res.returncode not in (0, 1)


def test_readable_clean_file_still_passes(tmp_path):
    good = tmp_path / "clean.md"
    good.write_text("a line of ordinary prose\n", encoding="utf-8")
    res = run(str(good))
    assert res.returncode == 0, res.stderr
    assert "clean" in res.stdout


def test_a_real_hit_still_exits_1(tmp_path):
    """The leak path must keep its own exit code, distinct from the new one.

    The pattern is assembled at runtime on purpose: a literal here would be a
    hit in this very file the next time the repo-wide sweep runs.
    """
    planted = tmp_path / "leaky.md"
    planted.write_text("home is " + "/Users/" + "someone" + "/notes\n", encoding="utf-8")
    res = run(str(planted))
    assert res.returncode == 1, (
        f"expected a leak hit, got {res.returncode}: {res.stdout}{res.stderr}"
    )


def test_scanned_count_excludes_skipped_binaries(tmp_path):
    """"N file(s) scanned" must mean N files were read, not N were handed over."""
    text = tmp_path / "a.md"
    text.write_text("prose\n", encoding="utf-8")
    binary = tmp_path / "b.png"
    binary.write_bytes(b"\x89PNG\r\n\x1a\n")
    res = run(str(text), str(binary))
    assert res.returncode == 0, res.stderr
    assert "1 file(s) scanned" in res.stdout, (
        f"binary was counted as scanned: {res.stdout!r}"
    )
    assert "skip" in res.stdout.lower()
