#!/bin/bash
# verify.sh — board-pilot `verify` stage (scope: core).
#
# THE EXIT-CODE CONTRACT, which is the single most load-bearing thing in this chain:
#
#   red tests   (suite rc 1..125)      -> write {"verdict":"reject", ...} to $VERDICT_FILE and EXIT 0
#   green       (suite rc 0)           -> write nothing and EXIT 0
#   cannot run  (no/vacuous BP_VERIFY_CMD, or suite rc >= 126) -> EXIT non-zero
#
# A red test is a REVIEW VERDICT, not an infra crash. The stage RAN CLEANLY; it has
# a finding. Exiting non-zero on red would mean ok=False, which takes the on_fail
# edge (retry/park/rewind) instead of the capped reject edge — and the engine only
# consults the verdict sidecar `if stage.reject_to and result.ok`, so a non-zero exit
# also throws the verdict away unread. Rework would then ride an edge whose counter
# `attempts.reset()` wipes: the unbounded-spend loop, measured at 40 paid runs in 40
# ticks. This exit 0 is why the delivered chain needs no rewind edge at all.
#
# NO MODEL RUNS HERE. This stage is the only [machine] evidence in the dossier; a
# model anywhere in it would make the one independent signal an opinion again.
#
# Env from the runner: ITEM_ID BRANCH VERDICT_FILE EVIDENCE_DIR. Declares
# `evidence: true`, so the ENGINE tees this script's stdout/stderr/exit code — that
# is why the output goes to stdout plainly and is never piped.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

: "${ITEM_ID:?}" "${BRANCH:?}" "${VERDICT_FILE:?}"

# Resolve the suite BEFORE touching git: a repo this stage cannot verify must fail
# loudly and immediately, not after a fetch. Fail-closed is the whole point — a
# verify stage that cannot find a suite and reports green is worse than no stage.
#
# There is deliberately NO fallback heuristic. Guessing a suite from the CWD ties
# the verdict to the runner box's environment: a live run guessed `python3 -m
# pytest -q` on a box whose python3 has no pytest, the rc=1 became a reject note
# reading "No module named pytest", and a paid rework round was spent proving that
# no repo change can install a module on the runner. The operator names the suite,
# or the stage refuses.
VERIFY_CMD="${BP_VERIFY_CMD:-}"
[ -n "$VERIFY_CMD" ] || bp_die "no verify command configured — set BP_VERIFY_CMD in the unit env. A stage that cannot verify must never report green."

# A whitespace-only or comment-only command line satisfies -n, yet `bash -c " "`
# and `bash -c "#anything"` exit 0 without running any suite — a PERMANENT vacuous
# green that even the deploy-time baseline gate confirms (it runs the same nothing).
# Judged on the stripped form; the ORIGINAL string is what runs below.
VERIFY_CMD_TRIMMED="${VERIFY_CMD#"${VERIFY_CMD%%[![:space:]]*}"}"
case "$VERIFY_CMD_TRIMMED" in
  ""|"#"*)
    bp_die "BP_VERIFY_CMD is blank or a comment ('${VERIFY_CMD}') — set a real verify command in the unit env. A stage that cannot verify must never report green."
    ;;
esac

bp_ensure_branch

# Operator-provided command line (env, not board data), so a shell is what it expects.
# Output goes to a file and is then cat'd: the engine tees stdout, and a `| tee` here
# would hand $? to tee and report every red suite as green.
OUT_FILE="$(mktemp)"
trap 'rm -f "$OUT_FILE"' EXIT

bp_note "suite started"

set +e
bash -c "$VERIFY_CMD" > "$OUT_FILE" 2>&1
RC=$?
set -e

cat "$OUT_FILE"

# rc >= 126 means the suite never judged the diff: 126/127 from `bash -c` are
# cannot-execute (not executable / not found), and rc >= 128 is a suite KILLED by
# signal rc-128 (the OOM killer's SIGKILL = 137, SIGTERM = 143) — no repo change
# prevents a kill, and the header contract caps red at rc 125. Non-zero exit
# routes the engine to on_fail (park), never the reject edge: a reject here hands
# the implement agent a failure no repo change can fix. A missing python module
# INSIDE the suite still exits 1 and rides the reject edge — the real guard for
# that is the deploy-time baseline gate in the deploy script.
if [ "$RC" -ge 126 ]; then
  SIGNAL_NOTE=""
  [ "$RC" -ge 128 ] && SIGNAL_NOTE=", signal $((RC - 128))"
  bp_die "verify command could not run to completion (rc=${RC}${SIGNAL_NOTE}) — fix the runner environment, not the diff: ${VERIFY_CMD}"
fi

if [ "$RC" -ne 0 ]; then
  # The annotation carries the real failure text back to `implement` via the
  # round-scoped reject note. Written by python3 so the JSON is escaped by a real
  # encoder — hand-rolled JSON in bash breaks on the first quote or newline in a
  # traceback, which is exactly what test output is made of.
  python3 - "$OUT_FILE" "$VERDICT_FILE" <<'PY'
import json, sys

CAP = 4000  # what the rework prompt is asked to read; failures live at the END
out = open(sys.argv[1], encoding="utf-8", errors="replace").read()
if len(out) > CAP:
    out = "...[truncated: showing the last %d bytes]...\n%s" % (CAP, out[-CAP:])
with open(sys.argv[2], "w", encoding="utf-8") as f:
    json.dump({"verdict": "reject", "annotation": out}, f)
PY
  bp_note "suite red: $(grep -oE '[0-9]+ (failed|error)[^,]*' "$OUT_FILE" | tail -1)"
  echo "[verify] tests RED (rc=${RC}) -> reject verdict written; the stage itself ran cleanly" >&2
  exit 0
fi

bp_note "suite green: $(grep -oE '[0-9]+ passed[^,]*' "$OUT_FILE" | tail -1)"
echo "[verify] OK: suite green for ${ITEM_ID} on ${BRANCH}"
