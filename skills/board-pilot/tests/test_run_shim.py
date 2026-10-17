"""The launchd shim and its two identities.

CHANGED 2026-09-02, and the change is deliberate, not a relaxation. MEASURED on the
box: `gh project field-list <n> --owner <org>` under an App installation token fails
with "GraphQL: API rate limit exceeded" while `gh api rate_limit` reports the bucket
FULL with that same token, and the same query through `gh api graphql` succeeds. The
`gh project` subcommands cannot drive an installation token at all. Failing closed on
a credential that can never work is not a guard, it is a permanent outage: it cost
31103 logged failures, every one of them exiting 0, so launchd saw a healthy unit for
weeks while the engine did nothing.

So the shim now has TWO identities, and which one is in force is an EXPLICIT choice:

  <APP_SWITCH>=1      ->  mint the App token, and fail CLOSED if the mint fails.
                           Everything the original guard said still holds here.
  unset (the default)  ->  run under the ambient `gh auth` login, deliberately.
                           No mint is attempted, so there is nothing to fail open from.

The distinction that matters: a SILENT fallback (mint fails, quietly become the human)
is still forbidden, and the tests below still pin it. What is now allowed is a DECLARED
identity, chosen by an operator who typed it.

THE COST OF THE DEFAULT, written down so nobody rediscovers it the hard way: the engine
authenticates its own notes with GitHub's `viewerDidAuthor`. Under the ambient login the
viewer is the human, so the engine can no longer tell its own comments from that human's
on the same issue. A stranger still cannot forge one (GitHub asserts authorship server
side), but the operator must not comment on an issue that is mid-flight.

The original rationale, still true for the App-token path:

A fail-open shim (mint fails -> unset GH_TOKEN -> ambient gh auth) does not merely
lose a rate-limit bucket: it silently swaps the engine's IDENTITY. The tick then runs
as the human, and the reject-note read-back — which authenticates a note by its author
— starts trusting that human's entire comment history on a public issue. Any drive-by
comment carrying the marker would steer the autonomous code writer. A missed tick is
free (the board is durable state; the next tick re-reads it); running as the wrong
identity is not. So: mint fails -> exit 1, and the tick never starts.

These drive the REAL script (never a copy of its logic) with a stubbed mint helper.
The shim resolves the helper as "$HOME/bin/gh-app-token.sh" — an absolute path — and
overrides PATH itself, so a PATH-shadowed stub would NOT intercept it; HOME is the only
honest seam. The real ~/bin/gh-app-token.sh and the real keychain are never touched.
"""
import os
import subprocess
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[3]
# TWO LAYOUTS, ONE FILE. Inside a Bridge the shim is USER-tier and sits under
# infra/remotes/<box>/scripts. In a standalone deployment that carries the engine
# next to the thing it drives, it sits under deploy/shims. Probing both is not a
# convenience: with only one candidate the whole suite SKIPS in the other layout,
# and 5 skipped reads as 5 passed unless somebody looks. Guarding a file the
# deployment does not have is pointless; silently guarding nothing is worse.
# BOARD_PILOT_SHIM_DIR names the directory outright and wins over both probes; the
# Bridge probe uses BOARD_PILOT_SHIM_HOST (default `homeserver`) as the <box>.
_CANDIDATES = tuple(
    [Path(os.environ["BOARD_PILOT_SHIM_DIR"])] if os.environ.get("BOARD_PILOT_SHIM_DIR") else []
) + (
    _REPO / "infra" / "remotes" / os.environ.get("BOARD_PILOT_SHIM_HOST", "homeserver") / "scripts",
    _REPO / "deploy" / "shims",
)
_SCRIPTS = next((k for k in _CANDIDATES if k.is_dir()), _CANDIDATES[0])
SHIM = _SCRIPTS / "board-pilot-run.sh"
# The switch that selects the App identity. The shim is USER-tier, so its variable
# name is the instance's to choose; BOARD_PILOT_SHIM_APP_SWITCH names it.
_APP_SWITCH = os.environ.get("BOARD_PILOT_SHIM_APP_SWITCH", "BOARD_PILOT_USE_APP_TOKEN")

# The shim is USER-tier (infra/remotes/<box>/) while this suite is a scope:core skill
# that ships to the OSS upstream, where that box's scripts do not exist. Skip only when
# the whole per-box script dir is absent (= not this instance). If the dir IS here but
# the shim is not, FAIL — that means the guarded file was renamed or deleted out from
# under this test, and a silent skip is exactly how a guard evaporates unnoticed.
pytestmark = pytest.mark.skipif(
    not _SCRIPTS.is_dir(), reason="shim script dir absent (USER-tier; not this instance)"
)


def _env(home, probe_out, app_token: bool):
    env = {"HOME": str(home), "PROBE_OUT": str(probe_out), "PATH": os.environ["PATH"]}
    if app_token:
        env[_APP_SWITCH] = "1"
    return env


def _drive(tmp_path, mint: str | None, app_token: bool = True):
    """Run the real shim with a stubbed mint helper; return (proc, what the exec'd child saw).

    The child is a probe standing in for the plist's python tick. If the shim fails
    closed it is never exec'd, so the ABSENCE of its output file is the proof that no
    token reached the tick — and that no tick ran at all.
    """
    home = tmp_path / "home"
    (home / "bin").mkdir(parents=True)
    if mint is not None:
        helper = home / "bin" / "gh-app-token.sh"
        helper.write_text(mint)
        helper.chmod(0o755)

    probe_out = tmp_path / "probe-saw.txt"
    probe = tmp_path / "probe.sh"
    probe.write_text(
        '#!/bin/bash\nprintf "token=%s\\nargv=%s\\n" "${GH_TOKEN-<unset>}" "$*" > "$PROBE_OUT"\n'
    )
    probe.chmod(0o755)

    proc = subprocess.run(
        [str(SHIM), str(probe), "-m", "engine.cli", "--once"],
        env=_env(home, probe_out, app_token),
        capture_output=True,
        text=True,
        timeout=30,
    )
    return proc, (probe_out.read_text() if probe_out.exists() else None)


def test_run_shim_exits_when_mint_fails(tmp_path):
    proc, child_saw = _drive(tmp_path, '#!/bin/bash\necho "mint boom" >&2\nexit 1\n')
    assert proc.returncode != 0, "mint failed but the shim exited 0 — launchd records success"
    assert child_saw is None, f"the tick RAN despite a failed mint; it saw: {child_saw!r}"


def test_run_shim_exits_when_mint_helper_is_missing(tmp_path):
    """An absent helper (fresh box, botched deploy) is a mint failure, not a green light."""
    proc, child_saw = _drive(tmp_path, None)
    assert proc.returncode != 0
    assert child_saw is None


def test_run_shim_exits_when_mint_returns_empty_token(tmp_path):
    """Exit 0 with an empty token is the nastiest case: it LOOKS like a successful mint,
    and the old `[ -n "$TOK" ] &&` guard degraded it into a silent identity swap."""
    proc, child_saw = _drive(tmp_path, "#!/bin/bash\nprintf ''\nexit 0\n")
    assert proc.returncode != 0
    assert child_saw is None


def test_run_shim_execs_tick_with_minted_token_on_success(tmp_path):
    """The control: proves the failure tests above are not vacuously green, and pins the
    argv contract the plist depends on (it passes the python invocation THROUGH the shim)."""
    proc, child_saw = _drive(tmp_path, "#!/bin/bash\nprintf 'ghs_faketoken123'\n")
    assert proc.returncode == 0, f"clean mint must still tick; stderr={proc.stderr!r}"
    assert child_saw is not None, "the shim did not exec the tick after a successful mint"
    assert "token=ghs_faketoken123" in child_saw
    assert "argv=-m engine.cli --once" in child_saw


def test_run_shim_uses_the_ambient_login_when_the_app_token_is_not_asked_for(tmp_path):
    """The default path: no mint is attempted, and the tick runs WITHOUT GH_TOKEN.

    This is the counterpart to the four tests above, and it is what makes them mean
    something. Without it they would all be green against a shim that simply never
    mints, and the fail-closed contract would be vacuous. Here the mint helper is
    absent on purpose: the shim must not care, because it must not look.
    """
    proc, child_saw = _drive(tmp_path, None, app_token=False)
    assert proc.returncode == 0, f"the default path must tick; stderr={proc.stderr!r}"
    assert child_saw is not None, "the shim did not exec the tick on the default path"
    assert "token=<unset>" in child_saw, (
        "GH_TOKEN reached the tick on the default path, so some identity was forced "
        f"after all: {child_saw!r}"
    )
    assert "argv=-m engine.cli --once" in child_saw
