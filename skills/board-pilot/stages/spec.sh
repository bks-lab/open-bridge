#!/bin/bash
# spec.sh — board-pilot `spec` stage (scope: core).
#
# Turns a board item into an implementation plan the `implement` stage reads. The
# plan is the first thing a human can disagree with, so it is a real artefact and
# not a thought the model had once.
#
# READ-ONLY ON THE REPO, by two independent mechanisms: the fence grants no Write or
# Edit tool at all, and the script itself writes the plan from the model's stdout.
# That is tighter than the precedent, which hands over Write and then polices the
# damage with a scoped-dirty check — here there is no write to police.
#
# The plan lands in $EVIDENCE_DIR (durable per item, across ticks) and NOT in the
# repo: a plan committed to the branch would show up in the PR diff, and the diff is
# supposed to be the change, not the paperwork about the change.
#
# Env from the runner: ITEM_ID ITEM_TITLE ITEM_URL ITEM_BODY_FILE BRANCH PROJECT
# EVIDENCE_DIR CRITERIA_FILE. cwd = the target repo clone.
#
# ITEM_BODY_FILE is the REQUIREMENT and this stage's real input — see bp_story_block.
# It is deliberately NOT asserted below: a missing story degrades to a topic hint (the
# behaviour before it existed), it does not kill a live item.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

: "${ITEM_ID:?}" "${ITEM_TITLE:?}" "${BRANCH:?}" "${EVIDENCE_DIR:?}" "${CRITERIA_FILE:?}"

# Everything free and fail-closed FIRST: refuse, resolve, verify. No spend, no git
# mutation until the cheap checks have passed.
bp_refuse_protected_branch
bp_resolve_claude
[ -r "$CRITERIA_FILE" ] || bp_die "criteria file unreadable: $CRITERIA_FILE"

bp_note "criteria read: $(basename "$CRITERIA_FILE")"

PLAN_DIR="$EVIDENCE_DIR/spec"
PLAN="$PLAN_DIR/plan.md"
mkdir -p "$PLAN_DIR"

bp_ensure_branch

PROMPT="You are planning ONE change to THIS repository (the current working directory). Read the actual code, configs and docs with your read tools before you write anything.

Your standard is in the file ${CRITERIA_FILE}. Read it FIRST and hold the plan to it.

$(bp_story_block)

Write an implementation plan as Markdown to STDOUT and nothing else. No preamble, no
commentary, no questions. Cover: what the change is; which real files it touches (cite
paths you actually read); the order of work, tests first; what would make it WRONG; and
what you are unsure about. Assert only what the files support; mark anything uncertain as
such. A plan that only restates the requirement has done nothing — the requirement is
where you start, the analysis is what you deliver. If the task is not doable as
described, say so plainly and explain why — a plan that says 'this cannot be done as
asked' is a valid, useful plan.

$(bp_untrusted_block)"

# Command substitution, not a pipe: the model's exit code stays this script's exit
# code, and `set -e` fails the stage if it dies. A `| tee` here would hand $? to tee
# and report a crashed planner as a clean run.
bp_note "planner started, read only"
PLAN_TEXT="$(bp_claude "Read,Glob,Grep" "$PROMPT")"
printf '%s\n' "$PLAN_TEXT" > "$PLAN"

# Fail-closed against a hollow run: an empty or one-line plan means the model said
# something conversational instead of planning, and `implement` would then build
# against nothing.
[ -s "$PLAN" ] || bp_die "no plan produced at $PLAN"
LINES="$(wc -l < "$PLAN")"
[ "$LINES" -ge 5 ] || bp_die "plan too thin ($LINES lines) — refusing to hand it to implement"

# The backstop for "read-only" — asserted, not assumed. If this ever fires, the fence
# above leaked a write tool and that is a finding, not a warning.
bp_note "plan written, $((LINES)) lines"

DIRTY="$(git status --porcelain)"
[ -z "$DIRTY" ] || bp_die "spec stage modified the repo, which it must never do:
$DIRTY"

echo "[spec] OK: plan written ($LINES lines) for ${ITEM_ID} on ${BRANCH}"
