#!/bin/bash
# pr.sh — board-pilot `pr` stage (scope: core). The last stage; `gate: human` stops here.
#
# The draft PR is the file a human merges on, so this stage's product is a DOSSIER:
# every claim carries who made it and how much it is worth. The labels are not
# decoration — they are the deliverable. Softening one is the change that makes this
# pipeline lie, which is why a test pins each of them literally.
#
# What this stage does NOT do, and why:
#   * NO issue comment. The old script posted one: a second comment writer with a
#     different format, a different idempotency mechanism, argv instead of stdin, an
#     emoji badge CLAUDE.md forbids — and unguarded under `set -e`, so its 403 parked
#     the item AFTER the PR was already open. The record has ONE writer: the engine.
#   * NO `--body "$BODY"` on argv. The body carries agent-authored text of unbounded
#     length; it rides stdin via --body-file -.
#   * NO citing its own CI. CI starts after the PR opens and this stage is the last
#     one before the human gate, so the body links the Checks tab and says so.
#     (Opt-in BP_PR_AWAIT_CHECKS=1 waits for those checks AFTER the PR exists and
#     only decides draft vs ready; the body still cites nothing. See the end.)
#
# unset GH_TOKEN: the App installation has issues:write + organization_projects:write
# but NO pull_requests and NO contents (verified live), so `gh pr create` cannot run
# under it. Dropping it falls back to ambient gh — bot-written record, human-written PR.
#
# Env from the runner: ITEM_ID ITEM_TITLE ITEM_URL BRANCH EVIDENCE_DIR BOUNCES.
set -euo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/_lib.sh"

: "${ITEM_ID:?}" "${ITEM_TITLE:?}" "${BRANCH:?}" "${EVIDENCE_DIR:?}"

bp_refuse_protected_branch
unset GH_TOKEN

GH="${BP_GH:-gh}"
command -v "$GH" >/dev/null 2>&1 || bp_die "gh not found (BP_GH='${BP_GH:-}')"

BASE="$(bp_base_branch)"

# Issue number from the trigger URL; empty for a draft card. `require_issue: true`
# means the engine never arms one, so this is a belt to that suspenders.
ISSUE_NUM="$(printf '%s' "${ITEM_URL:-}" | grep -oE 'issues/[0-9]+' | grep -oE '[0-9]+' || true)"

BODY_FILE="$(mktemp)"
trap 'rm -f "$BODY_FILE"' EXIT

# ---- header -----------------------------------------------------------------
REF="${ISSUE_NUM:+#$ISSUE_NUM}"
{
  echo "## Draft — board-pilot run for ${REF:-${ITEM_ID}}. Not merge-ready. You decide."
  echo
  echo "**Asked:** ${ITEM_TITLE}"
  if [ -n "$ISSUE_NUM" ]; then
    echo
    # A closing keyword makes a CONNECTED link (board "Linked pull requests" + the
    # issue's Development panel). A bare URL mention does not.
    echo "Closes #${ISSUE_NUM}"
  fi
} > "$BODY_FILE"

# ---- what changed: the cheapest true statement there is ----------------------
NUMSTAT="$(git diff --numstat "origin/${BASE}...HEAD" || true)"
FILES_N="$(printf '%s' "$NUMSTAT" | grep -c . || true)"
ADDED="$(printf '%s\n' "$NUMSTAT" | awk '{s+=$1} END {print s+0}')"
DELETED="$(printf '%s\n' "$NUMSTAT" | awk '{s+=$2} END {print s+0}')"
{
  echo
  echo "### What changed  [machine — git + GitHub PR-API, independent]"
  echo "\`+${ADDED} −${DELETED}\` across **${FILES_N} file(s)**, \`origin/${BASE}...${BRANCH}\`."
  echo "Cross-checkable independently: \`gh pr view <n> --json additions,deletions,changedFiles\`"
  echo
  printf '%s\n' "$NUMSTAT" | sed 's/^/    /'
} >> "$BODY_FILE"

# ---- what was verified: engine-teed, and labelled for what it is worth -------
V_OUT="$EVIDENCE_DIR/verify/stdout"
V_RC="$EVIDENCE_DIR/verify/exit_code"
{
  echo
  echo "### What was verified  [machine-executed, agent-authored]"
  if [ -s "$V_OUT" ] && [ -s "$V_RC" ]; then
    echo "\`verify.sh\` → exit $(tr -d '[:space:]' < "$V_RC"). Read from the pipe by the engine; the stage never authored it:"
    echo
    sed 's/^/    /' < "$V_OUT"
    echo
    # One sentence per line, unwrapped: these are the load-bearing sentences of the
    # whole dossier, and a sentence split across two echo lines is one a reader cannot
    # grep and a test cannot pin. Markdown wraps them for display anyway.
    echo "> pytest ran for real and the exit code belongs to the engine. BUT the assertions were written by the same agent that wrote the code, in the same run."
    echo ">"
    echo "> Green means self-consistent, not correct."
    echo ">"
    echo "> The only independent evidence in this body is the diff numbers above and the CI below."
  else
    # Honest degradation: no sink, no claim. Never a stand-in sentence that reads green.
    echo "No engine-captured verify output exists for this run, so this body claims NO verification."
  fi
  echo
  echo "**TDD order: NOT verified.** The suite is green now; nothing here shows a test was red"
  echo "first. That is not reconstructable after the fact."
  echo
  echo "**Cost: unmeasured.** The engine hardcodes tokens=0, so no number is printed rather"
  echo "than an invented one. Model not reported: none is pinned, so the engine observes none."
} >> "$BODY_FILE"

# ---- what the reviewer said: a claim, labelled ------------------------------
R_VERDICT="$EVIDENCE_DIR/review/verdict.json"
{
  echo
  echo "### What the reviewer said  [agent — an OPINION, not a verification]"
  if [ -s "$R_VERDICT" ]; then
    python3 - "$R_VERDICT" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1], encoding="utf-8"))
except (ValueError, OSError):
    d = {}
print("`review.sh` → verdict **%s**" % (d.get("verdict") or "unknown"))
print()
for line in (d.get("annotation") or "(no annotation)").splitlines() or ["(no annotation)"]:
    print("> " + line)
PY
    echo
    echo "This is a model's self-report on work by the same model family. It is evidence that a"
    echo "review ran and what it concluded — NOT evidence that the code is correct. That is what"
    echo "your review is for."
  else
    echo "No reviewer verdict was captured for this run, so this body reports none."
  fi
} >> "$BODY_FILE"

# ---- rework: the durable counter --------------------------------------------
{
  echo
  echo "### Rework: ${BOUNCES:-0} round(s)  [machine — board Number field \`Bounces\`]"
  echo "Per-round diffs are not recorded; the round-scoped notes on the issue are the full history."
} >> "$BODY_FILE"

# ---- checks: third party, linked not quoted ---------------------------------
{
  echo
  echo "### Checks"
  echo "CI runs **after** this PR opens — this body cannot cite its own CI."
  echo "→ **The Checks tab is authoritative.** Branch protection is enforced by GitHub"
  echo "independently of board-pilot; this gate is not ours to weaken."
} >> "$BODY_FILE"

# ---- where to look first: mechanical, not agent-framed -----------------------
# Ranked OUTSIDE the block, in a command substitution: `sort | head -3` sends SIGPIPE
# to sort as soon as head has its three lines, and under `set -o pipefail` that 141
# fails the whole pipeline. It only bites once a diff has more than three files —
# i.e. never in a smoke test, always in production.
TOP_FILES="$(printf '%s\n' "$NUMSTAT" | sort -rn | head -3 || true)"
{
  echo
  echo "### Where to look first  [computed from the diff, not framed by the agent]"
  while read -r a d f; do
    # An empty NUMSTAT still yields one empty line; `[ -n ]` as the loop's last
    # command would return 1 and take the whole `set -e` script down with it.
    [ -n "${f:-}" ] || continue
    echo "- \`${f}\` — +${a} −${d} (largest change)"
  done <<< "$TOP_FILES"
  # A mechanical signal that points at what the reviewer may have MISSED, rather than
  # at what it liked. An agent-written "start here" would be the model grading its own
  # reviewer, in the one section without a label.
  TESTS_TOUCHED="$(printf '%s\n' "$NUMSTAT" | awk '{print $3}' | grep -cE '(^|/)tests?/|test_|_test\.' || true)"
  if [ "${TESTS_TOUCHED:-0}" -eq 0 ]; then
    echo "- **No test file changed in this diff.** Whatever this change does is untested by it."
  fi
} >> "$BODY_FILE"

# ---- the gate: fail-closed scan BEFORE anything is transported ---------------
# Fail-closed, not redact-and-post: the record sink may redact, but the dossier is the
# artefact a human merges on, and a suspect body is not emitted even redacted.
if ! bp_scan_file "$BODY_FILE"; then
  bp_die "potential secret in the PR body — refusing to open a PR (fail-closed). Nothing was posted."
fi

# ---- transport --------------------------------------------------------------
# Idempotent: this stage is re-dispatched on any tick that still finds the item at
# pr-ready, and a second PR for one branch is not a recoverable state.
PR_URL="$("$GH" pr list --head "$BRANCH" --state open --json url --jq '.[0].url // empty' 2>/dev/null || true)"
if [ -n "$PR_URL" ]; then
  echo "[pr] reusing open PR: $PR_URL" >&2
else
  # --draft: board-pilot never opens a ready PR; only the opt-in check wait below
  # may mark it ready, and only on green. --body-file - : the body rides stdin,
  # never argv.
  PR_URL="$("$GH" pr create --draft --head "$BRANCH" --base "$BASE" \
    --title "$ITEM_TITLE" --body-file - < "$BODY_FILE")"
  bp_note "pull request opened as draft"
  echo "[pr] created draft PR: $PR_URL" >&2
fi

# ---- optional: the checks, and only then the handover ------------------------
# OFF by default. With BP_PR_AWAIT_CHECKS unset (or anything but 1) the stage ends
# here: the PR stays a draft, exit 0, and the human reads the Checks tab. That is
# the shipped contract, and a pipeline that never asked for more keeps it.
#
# OPT-IN (BP_PR_AWAIT_CHECKS=1, set in the unit env like BP_VERIFY_CMD) is for a
# pipeline whose human gate downstream is a single tap, e.g. a chat button. There
# a draft is no longer enough protection: a tap on an untested change is exactly
# the accident the draft was guarding against. So the stage waits for the run the
# PR triggered and says one of three things, only one of which takes the flag off:
#
#   every check green   -> `pr ready`, the human may act on it;
#   any check red       -> stays a draft, stage FAILS naming the check;
#   still running at the -> stays a draft, stage FAILS saying so. Unknown is not
#   budget, or no checks   green, and no checks at all is not green either.
#
# A failure here leaves an OPEN DRAFT PR behind. The engine does NOT re-run this
# stage to retry the wait: on the next dispatch tick.py finds the open PR
# (`pr_exists`) and hands the item to the human gate without dispatching. The PR
# then stays a draft, and the human reads its checks and marks it ready by hand.
if [ "${BP_PR_AWAIT_CHECKS:-0}" != "1" ]; then
  echo "$PR_URL"
  exit 0
fi

CHECK_TIMEOUT="${BP_PR_CHECK_TIMEOUT:-600}"
CHECK_PAUSE="${BP_PR_CHECK_PAUSE:-10}"
# How long "no checks at all" is treated as "not attached YET" rather than as the
# answer. The two are indistinguishable in a single sample, and which one it is
# depends on a race: GitHub attaches the run started by opening the PR a moment
# after `pr create` returns. This mattered from the day the duplicate push-run was
# removed (2026-09-03) — until then a run from the engine's own push had been
# alive for minutes, so the first sample was never empty. Kept SHORT, because the
# other case is a repo with no workflow, and that must fail fast rather than in
# ten minutes.
NONE_GRACE="${BP_PR_CHECK_NONE_GRACE:-90}"
WAITED=0
CHECK_STATE=""

while :; do
  CHECKS_JSON="$("$GH" pr checks "$PR_URL" --json name,state 2>/dev/null || echo "[]")"
  CHECK_STATE="$(printf '%s' "$CHECKS_JSON" | python3 -c '
import json, sys

try:
    rows = json.loads(sys.stdin.read() or "[]")
except json.JSONDecodeError:
    rows = []
if not isinstance(rows, list):
    rows = []

# GitHub says PENDING/QUEUED/IN_PROGRESS while a run is alive, and SKIPPED for a
# job whose condition excluded it. SKIPPED is not a pass and not a failure: it is
# a job that never claimed anything, so it may not hold the gate either way.
LIVE = {"PENDING", "QUEUED", "IN_PROGRESS", "EXPECTED", "REQUESTED", "WAITING"}
OK = {"SUCCESS", "SKIPPED", "NEUTRAL"}

live = [r for r in rows if str(r.get("state", "")).upper() in LIVE]
bad = [r for r in rows if str(r.get("state", "")).upper() not in LIVE | OK]
if bad:
    parts = []
    for r in bad:
        parts.append(str(r.get("name", "?")) + "=" + str(r.get("state", "?")))
    print("RED " + "; ".join(parts))
elif live:
    print("LIVE " + str(len(live)))
elif rows:
    print("GREEN " + str(len(rows)))
else:
    # No checks at all is NOT green. A repo with no workflow, a run that never
    # started, a gh that answered nothing: all three look identical here, and
    # calling any of them "tested" would be the lie this whole block exists to
    # prevent.
    print("NONE")
')"
  # Only on CHANGE, and never for NONE. This loop polls every few seconds, so a
  # note per poll would post the same card twenty times while nothing happened,
  # and "checks NONE" is not news — it is the absence of news.
  if [ "$CHECK_STATE" != "${CHECK_LAST:-}" ] && [ "$CHECK_STATE" != "NONE" ]; then
    bp_note "checks $CHECK_STATE"
    CHECK_LAST="$CHECK_STATE"
  fi
  case "$CHECK_STATE" in
    LIVE*) : ;;
    NONE)
      # Not attached yet, or none at all. Wait out the grace, then let the case
      # below say the honest thing.
      [ "$WAITED" -ge "$NONE_GRACE" ] && break
      ;;
    *) break ;;
  esac
  [ "$WAITED" -ge "$CHECK_TIMEOUT" ] && break
  sleep "$CHECK_PAUSE"
  WAITED=$((WAITED + CHECK_PAUSE))
done

case "$CHECK_STATE" in
  GREEN*)
    "$GH" pr ready "$PR_URL" >/dev/null 2>&1 || bp_die "could not mark $PR_URL ready for review"
    bp_note "pull request ready: $PR_URL"
    echo "[pr] checks green (${CHECK_STATE#GREEN }), handed over ready: $PR_URL" >&2
    ;;
  RED*)
    bp_die "the suite is red on $PR_URL, the PR stays a draft: ${CHECK_STATE#RED }"
    ;;
  LIVE*)
    bp_die "checks on $PR_URL were still running after ${CHECK_TIMEOUT}s, the PR stays a draft. Unknown is not green."
    ;;
  *)
    bp_die "no checks reported on $PR_URL, the PR stays a draft. An untested change is not ready for a one-tap merge."
    ;;
esac

echo "$PR_URL"
