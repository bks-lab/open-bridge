#!/usr/bin/env python3
# SPDX-License-Identifier: MIT
"""Regression tests for the pre-push guard's CONTENT NET.

`scripts/hooks/pre-push` has two independent defences. The destination-branch
rule (`user/*` never reaches a public upstream) is the primary one. The content
net is the backstop: for any OTHER destination — `main`, `feature/*`,
`promote-*`, a renamed user branch — it inspects the pushed files and blocks the
push if they carry USER instance content.

The net is two steps, and BOTH decide the outcome:
  1. an exemption filter that strips paths before matching (line ~149)
  2. the `USER_PATHS` extended regex (line ~123)

A path that step 1 strips can never be blocked, however good the regex is. That
is not hypothetical: on a live instance a blanket `grep -v '/README.md$'` exempted a
freelance client's README and a biometric directory's README, while the sibling
`.yaml` in the same directory was correctly blocked.

These tests read the LIVE hook and replay both steps exactly, so they fail if
someone widens the exemption or narrows the regex.

Run: python3 -m pytest scripts/tests/test_push_guard_content_net.py -q
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys

import pytest

REPO = pathlib.Path(__file__).resolve().parents[2]
HOOK = REPO / "scripts" / "hooks" / "pre-push"


def _extract(var: str) -> str:
    """Pull a single-quoted shell assignment out of the hook, verbatim."""
    text = HOOK.read_text(encoding="utf-8")
    m = re.search(rf"^{re.escape(var)}='([^']*)'", text, re.M)
    assert m, f"{var}= not found in {HOOK} — the hook was restructured, update this test"
    return m.group(1)


def _exemption_filters() -> list[str]:
    """Every `grep -v/-Ev` pattern applied to `changed` before the USER_PATHS match.

    Handles both spellings the hook may use: an inline single-quoted literal, and
    a double-quoted shell variable (`grep -Ev "$CORE_EXEMPT"`), which is resolved
    back to its assignment. Missing the variable form would silently drop the
    exemptions and make every MUST_PASS case look blocked.
    """
    text = HOOK.read_text(encoding="utf-8")
    block = text[text.index("changed=$("):text.index('if [ -n "$changed" ]')]
    out = re.findall(r"grep -(?:v|Ev) '([^']*)'", block)
    for var in re.findall(r'grep -(?:v|Ev) "\$\{?(\w+)\}?"', block):
        out.append(_extract(var))
    return out


def survives_and_blocks(path: str) -> bool:
    """Replay the hook's real pipeline for one path: exempt, then match."""
    for pat in _exemption_filters():
        if subprocess.run(["grep", "-Eq", pat], input=path, text=True).returncode == 0:
            return False                      # stripped before the match — never blocked
    return subprocess.run(
        ["grep", "-Eq", _extract("USER_PATHS")], input=path, text=True
    ).returncode == 0


# ---------------------------------------------------------------------------
# MUST BLOCK — instance content that must never ride to a public upstream.
# ---------------------------------------------------------------------------
MUST_BLOCK = [
    # The README exemption hole found on a live instance: a client bot …
    "infra/channels/bots/client-bot/README.md",
    # … and a biometric directory naming real people (GDPR Art. 9).
    "identity/voiceprints/README.md",
    "identity/voiceprints/alice.json",
    # Bridge-Agent instances — operator identity, calendars, Graph/KeyVault wiring
    "agents/alice/agent.yaml",
    "agents/alice/calendars.json",
    "agents/openbridge/DEPLOY.md",
    # cluster-wrapper types with no guard rule
    "workflow/checks/remotes.yaml",
    "workflow/workspaces/client-a.yaml",
    # declared runs, found by the review of the second A2A migration:
    # the alternation listed five workflow types and not this one, so the whole
    # family was invisible to the content net. A declaration carries an absolute
    # user path, a persona, a person slug in `recipients` and a public hostname.
    "workflow/workloads/alice-agent.yaml",
    "infra/utilities/city-power.yaml",
    "infra/transcriptions/topology.yaml",
    # the agent's own lore file — falls through the (IDENTITY|SOUL) anchor
    "identity/agent/IDENTITY-lore.md",
    # generated root lockfiles naming private clone URLs
    "workspaces.lock.yaml",
    "overlays.lock.yaml",
    # already covered — kept as canaries that the regex was not narrowed
    "infra/channels/client-voice.yaml",
    "identity/mandants/acme.yaml",
    "bridge-config.yaml",
    "work/log.md",
]


@pytest.mark.parametrize("path", MUST_BLOCK)
def test_content_net_blocks(path: str):
    assert survives_and_blocks(path), (
        f"{path} passes the pre-push content net. Either an exemption filter strips it "
        "before the match, or USER_PATHS does not cover it."
    )


# ---------------------------------------------------------------------------
# MUST NOT BLOCK — genuine CORE content. A false block breaks /promote and
# /contribute, so over-reaching is a real cost, not a safe default.
# ---------------------------------------------------------------------------
MUST_PASS = [
    # cluster-wrapper TYPE-level READMEs are core companions
    "workflow/projects/README.md",
    "infra/transcriptions/README.md",
    "identity/agent/README.md",
    # templates and schemas are core by the `_` split
    "identity/accounts/_schema.yaml",
    "infra/remotes/_template.yaml",
    "workflow/checks/_schema.yaml",
    # the CORE half of the type added to the net later. The `[^_]`
    # suffix is the whole reason a blocking rule can be added without
    # blocking the template and the schema that ship with the skill.
    "workflow/workloads/_schema.yaml",
    "workflow/workloads/_template.yaml",
    "agents/_template/agent.yaml",
    # the generic agents/ half — shipped upstream, must keep flowing
    "agents/tests/test_runner.py",
    "agents/pyproject.toml",
    "agents/README.md",
    # ordinary CORE surfaces
    "rules/operations.md",
    "scripts/overlay.py",
    "skills/briefing/SKILL.md",
    "docs/structure.md",
    "AGENTS.md",
]


@pytest.mark.parametrize("path", MUST_PASS)
def test_content_net_allows_core(path: str):
    assert not survives_and_blocks(path), (
        f"{path} is blocked by the pre-push content net, but it is CORE content. "
        "This false block would break a legitimate /promote or /contribute."
    )


# ---------------------------------------------------------------------------
# Structural: the guard must not hardcode this instance's org token. A public
# guard naming one org silently stops guarding every other org's fragment.
# ---------------------------------------------------------------------------
def test_guard_is_org_token_agnostic():
    """Names nobody could have enumerated must still be blocked.

    A guard that lists one org's or one operator's names covers exactly those
    and nothing else. Random names prove the rule is structural.
    """
    import uuid
    tok = "x" + uuid.uuid4().hex[:8]
    for path in (f"ecosystem.{tok}.yaml", f"agents/{tok}/agent.yaml",
                 f"identity/mandants/{tok}.yaml", f"workflow/workloads/{tok}.yaml"):
        assert survives_and_blocks(path), (
            f"{path} passes the content net. USER_PATHS seems to enumerate instance "
            "tokens instead of matching structurally, so a fork of another org "
            "inherits a guard that does not cover its own files."
        )


def test_ecosystem_fragments_are_covered_generically():
    """Any ecosystem.<org>.yaml must be caught, not just the ones we happen to have."""
    for path in ("ecosystem.acme.yaml", "ecosystem.personal.yaml", "ecosystem.local.yaml"):
        assert survives_and_blocks(path), f"{path} not covered by the content net"
    # …but the shipped generic example must still flow upstream.
    assert not survives_and_blocks("ecosystem.example.yaml"), (
        "ecosystem.example.yaml is the CORE template and must stay pushable"
    )


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
