---
name: a2a
description: 'Talks to other Bridges and A2A agents: ask a peer, check an agent card, probe an endpoint''s auth and topic boundary, and scaffold an A2A agent (public, or a peer endpoint with trust: peer). Peers live in infra/a2a-peers/. Trigger: "a2a", "ask <name>''s bridge", "agent card", "check the card", "probe the agent", "new a2a agent", "peer endpoint".'
metadata:
  scope: core
allowed-tools:
  - Bash(python3:*)
  - Bash(bash:*)
  - Read
  - Grep
  - Glob
---

# a2a

One skill for both directions of A2A: this Bridge calling another agent, and this
Bridge offering an agent of its own. Protocol mechanics only. Who your peers are,
which topics they may ask and in which language lives in data: `infra/a2a-peers/`,
the agent's own `agent.yaml` and `system-prompt.md`, and an org overlay's skill on
top (for example a `<org>-a2a` skill with the org's peer list and probe prompts).

Engine: `skills/a2a/scripts/a2a.py` behind `skills/a2a/a2a.sh`. Stdlib plus PyYAML.
Read the referenced file ONLY when the branch below sends you there.

## Commands

| Command | Does |
|---|---|
| `peers` | list `infra/a2a-peers/*.yaml` |
| `card <peer\|url>` | fetch the card, report endpoint, version, dialect, https, skills, schemes |
| `ask <peer> "<question>" [--context ID] [--wait S] [--json]` | send one question in the peer's dialect; `--wait` polls a held task (a peer waiting for its owner's approval) |
| `get <peer> <task_id> [--json]` | read a held task again (approved meanwhile?) without sending anything new |
| `request <peer> "<what>" [--subject S] [--wait S] [--json]` | ask the peer's OWNER to do something; the owner (or a rule the owner set) decides, the model never sees it. Needs `owner_request` on the card |
| `rules <peer> [--json]` | the owner's rules for you and your request history at that peer (`owner_policy`) |
| `probe <peer> [--prompts FILE]` | no token and wrong token must be refused, then each boundary prompt is checked against its expected refusal or answer |
| `new-agent <name> --trust public\|peer [--port N] [--peer ID:ENV:LOGIN]` | scaffold `agents/<name>/`; `peer` writes agent.yaml with auth, a prompt skeleton with a topic boundary, `share/` and `launch.sh` |

Exit codes: `0` clean, `1` a finding or a task that did not complete, `2` usage or a refused input.

## The token never passes through you

A peer file names its token as a secret reference (`credential_ref:
keychain://...`). `ask` and `probe` re-run themselves under `skills/secrets/secrets.sh
run --env A2A_TOKEN=<ref>`, so the value goes into the child process and nowhere
else. Never ask the user for a token in chat, never put one in a command line.

## Decision tree

```
What does the user want?
├── Ask another Bridge something          → `a2a.sh ask <peer> "..."`; unknown peer →
│                                           `a2a.sh peers`, then references/peers.md
├── Ask another Bridge's owner to DO sth  → `a2a.sh request <peer> "..." --subject a/b/c`,
│                                           then `get`; their rules: `a2a.sh rules <peer>`
├── Let peers request actions from you    → references/peer-agent.md § 4b
├── Per-peer folders, topics on request  → references/peer-agent.md § 4c
├── "Is that agent set up right?"         → `a2a.sh card <peer|url>`, then `probe`
├── Add a peer to call                    → references/peers.md
├── Offer an agent to the public          → `new-agent <name> --trust public`, then
│                                           references/public-agent.md
├── Offer an agent to known Bridges only  → `new-agent <name> --trust peer --peer ...`,
│                                           then references/peer-agent.md
├── Wire details, 1.0 vs 0.3, errors      → references/protocol.md
├── Something behaves oddly               → references/traps.md
└── Identity, delegation, where it goes   → references/security-model.md
```

## Files

| File | Holds |
|---|---|
| `scripts/a2a.py` | the engine |
| `assets/peer-*.tmpl`, `assets/share-README.md` | what `new-agent --trust peer` writes |
| `assets/probe-prompts.yaml` | generic boundary prompts; an overlay ships its own set |
| `tests/test_a2a.py` | hermetic tests, `bash skills/a2a/run-tests.sh` |
| `../../infra/a2a-peers/_template.yaml`, `_schema.yaml` | one peer |
