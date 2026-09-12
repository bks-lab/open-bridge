---
summary: Vibe session entry, explicit completion checks and portable delegation.
type: guide
last_updated: 2026-09-12
related:
  - ../AGENTS.md
  - tool-mapping.md
  - ../rules/session-start.md
---

# Vibe integration

Bridge uses the same configuration, task state and skills across clients.
Vibe discovers `.agents/skills` (a symlink to `../skills`). Do not copy skills
into a second user-level installation or assume `.claude/settings.json` is a
Vibe configuration file.

## Session and work-unit contract

1. Follow Phase 0 in `rules/session-start.md`, including live default-branch
   detection and push-guard setup. The adapter never switches branches.
2. Before a work unit, run `python3 scripts/vibe-bridge.py start --session-id ID`.
   Choose a unique ID per turn/work unit. It preserves a dirty-worktree baseline,
   prints the session config and ecosystem index. On enabled user branches it
   also prints the recent log, board and standing-order index. Continue Phase 1: read identity and eager order bodies, not just their index.
3. For a named project, retrieve its ecosystem entry and linked knowledge profile;
   verify live source/repository state before a consequential recommendation or edit.
   An inventory is navigation, not proof of current runtime health or active use.
4. Before concluding, log substantive work and run
   `python3 scripts/vibe-bridge.py finish --session-id ID`.
   When the work system was enabled at start, a change since the baseline
   without a changed log exits 2. A preexisting dirty
   log no longer masks later work. On enabled user branches the command also executes the existing shared
   status-drift check, with its older whole-worktree log heuristic disabled. A successful finish removes the checkpoint.
5. A failed finish retains its checkpoint. Fix the finding and repeat finish;
   never reset the baseline to suppress a finding.

These are agent-invoked commands, **not automatic Vibe lifecycle hooks**. They
are not a sandbox or a proof that every sentence was logged. Git-ignored files,
other repositories and external actions are outside the snapshot; log those
explicitly. Existing work-system enablement and Phase 1 routing still apply.
Checkpoint files stay under `.bridge/vibe-sessions/`, outside version control.

## Delegation

AGENTS.md requests delegation for useful, bounded independent work. If the host
provides subagents, pass the selected role's instructions, relevant standing
orders, source paths, allowed scope and expected evidence. Do not assume that
`.claude/agents/*.md` registers Vibe agents. No additional model or account
configuration is required by this adapter. If the host cannot delegate, execute
inline and bound tool output. Delegation is not helpful for a single short edit.

## Resume and completion

An intervening question does not complete an active task. Answer it, preserve the
original objective in STATUS.md and continue authorized work unless the user
changes scope. Do not claim onboarding complete while catalogue entries are
missing from the session registry. Report implementation tests separately from
fresh-client behavioral tests; one cannot establish the other.

## Verification

```bash
python3 scripts/vibe-bridge.py doctor
python3 -m unittest discover -s scripts/tests -p 'test_vibe_bridge.py'
```

Doctor checks the skill entry point and, when a repository catalogue exists,
checks every catalogue path is reachable through ecosystem.yaml. Fresh clones
without a catalogue do not need an inventory. Tests cover dirty baselines,
committed changes, deletion, untracked filenames, symlinks, missing routing and
checkpoint reuse. They do not simulate a model obeying instructions.

Client reference: [Mistral Vibe source and CLI documentation](https://github.com/mistralai/mistral-vibe).
The installed Vibe 2.25.0 harness supports AGENTS.md and .agents/skills.
Vibe agent configuration is TOML; existing Claude role files are not native Vibe agents.

## Vibe CLI edition

[Open Bridge Vibe](../VIBE.md) provides `bin/open-bridge-vibe` for interactive
and noninteractive use. The launcher adds a process-boundary checkpoint and
exit check. Per-turn checks still follow the explicit agent contract above.
The shared checker lives in `scripts/worklog-drift-check.sh`; Vibe does not
load `.claude/settings.json` or require the Claude compatibility wrapper.
