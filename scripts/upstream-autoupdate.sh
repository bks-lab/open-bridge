#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# upstream-autoupdate.sh — GUARDED daily auto-merge of upstream CORE updates.
#
# Auto-merges the upstream ref into the current user/* branch ONLY when it is
# provably safe. Otherwise it does NOT merge — it writes a status report and
# (optionally) notifies. Every guard FAILS CLOSED: any error or unknown state
# skips the merge rather than risking a bad one.
#
# Authoritative safety gate = `git merge-tree` (content-based conflict
# prediction). The name-based divergence sentinel is used only for the
# informational report, never as the merge decision (it can flag files that are
# byte-identical after a prior contribution).
#
# Guards (ALL must pass):
#   1. on a user/* branch
#   2. nothing staged, and no uncommitted TRACKED change in a file the merge
#      touches. A dirty file the merge does not touch is no reason to skip:
#      work/log.md is dirty for most of every working day, and treating that as
#      a stop kept the job from ever running on the days it was needed.
#   3. git merge-tree predicts 0 conflicts (read from its EXIT CODE — never
#      from its localized output; see the note at the guard itself) — OR every
#      predicted conflict is one scripts/upstream-resolve.py proves a machine
#      may decide: take upstream's side when the local version of the file is
#      one upstream itself already had (and upstream has not reverted since),
#      keep the local side when upstream's version is one this branch already
#      had (and the branch has not reverted since), or when upstream only added
#      lines the local file already holds. Any other conflict still stops the
#      job, file by file, with the reason and the local commits behind it.
#
# Before the resolver, ONE conflict froze this job for good: nothing ever
# resolved it, so every later morning skipped again. Measured 2026-10-01: 84
# commits behind, 10 conflicting files, 3 of them promoted fixes upstream had
# merely followed up on.
#
# After a successful merge it also FAST-FORWARDS the mirror's core branch, so the
# private origin keeps a copy of the CORE history this job just merged. Without
# that step the mirror falls behind by exactly the commits this job consumes, and
# the next `git push user/<name>` has to carry all of them: measured 1317 objects
# against a 24-day-stale mirror, 83 once it was current. The count also makes the
# user branch LOOK enormous — 161 commits ahead, of which 6 were the user's — and
# that reading has cost real debugging time twice.
#
# After the merge, and before the mirror push, it runs a fast LOCAL CHECK NET
# (run_checks below). The merge itself runs with hooks off, and an instance whose
# CI is off (a billing stop, Actions disabled on a fork, a tree with no remote
# runner) meets no validator after it at all. A check that the merge turned red
# (green before, or red before with a finding it did not have) rolls the merge
# back, skips the mirror and files an inbox item. A check that was already red
# before, saying the same, is reported and does not hold the job. A checker new
# with the merge, or changed by it, that is red keeps the merge and files an
# item: the rule is upstream's, what it finds is local, and rolling back would
# repeat every morning. The post-merge block sorts these three cases.
#
# Env (optional): UPSTREAM_REMOTE (default upstream) · UPSTREAM_REF (default
# upstream/main) · MIRROR_REMOTE (default origin) · MIRROR_CORE=0 disables the
# mirror step · SIGNAL_ACCOUNT + SIGNAL_RECIPIENT (both set → Signal push) ·
# AUTOUPDATE_NOTIFY_CMD (an argv string, e.g. "/path/notify.sh --quiet": run with
# the notification text on stdin, in addition to Signal; its failure is ignored).
# AUTOUPDATE_CHECKS=0 disables the check net (an escape hatch, reported as such).
set -uo pipefail
cd "$(git -C "$(dirname "$0")" rev-parse --show-toplevel)" || exit 1

UPSTREAM_REMOTE="${UPSTREAM_REMOTE:-upstream}"
UPSTREAM_REF="${UPSTREAM_REF:-upstream/main}"
REPORT="work/upstream-status.md"

notify() {  # $1 = message
  { [ -n "${SIGNAL_ACCOUNT:-}" ] && [ -n "${SIGNAL_RECIPIENT:-}" ] \
    && command -v signal-cli >/dev/null 2>&1 \
    && signal-cli -a "$SIGNAL_ACCOUNT" send -m "$1" "$SIGNAL_RECIPIENT" >/dev/null 2>&1; } || true
  # Generic notifier: any command that reads a message on stdin (a chat bot, a
  # mail drafter, a desktop toast). Word-split on purpose, it is an argv string.
  # A broken notifier must never turn a finished merge into a failed run.
  if [ -n "${AUTOUPDATE_NOTIFY_CMD:-}" ]; then
    # Globbing off (no pathname expansion of argv words) and a 30 s alarm so a
    # hanging notifier cannot stall the job (macOS has no timeout(1)).
    # shellcheck disable=SC2086
    ( set -f; printf '%s\n' "$1" | perl -e 'alarm 30; exec @ARGV' $AUTOUPDATE_NOTIFY_CMD ) >/dev/null 2>&1 || true
  fi
}
report() { mkdir -p work; { echo "# Upstream Auto-Update — $(date '+%F %T')"; echo; printf '%s\n' "$@"; } > "$REPORT"; }
is_int() { case "$1" in ''|*[!0-9]*) return 1;; *) return 0;; esac; }

# mirror_core_branch — fast-forward the mirror's CORE branch to $UPSTREAM_REF.
#
# Echoes ONE report line and always returns 0: the merge already succeeded, so a
# mirror that cannot be updated is a note, never a failure that masks it.
#
# Deliberately NOT a second push-guard. The push runs with the repo's hooks
# ACTIVE (no core.hooksPath override), so scripts/hooks/pre-push classifies the
# target with the one classifier there is — config push_guard.*, then the
# .bridge-origin marker — and refuses a target it cannot vouch for. Re-deriving
# that judgement here would be a copy that drifts.
#
# Three conditions, all conservative:
#   · the mirror remote exists
#   · the core branch ALREADY exists there — this step keeps an existing mirror
#     current, it never creates a branch on somebody's remote
#   · the update is a true fast-forward, checked before pushing, so no mirror
#     history is ever rewritten
# It pushes $UPSTREAM_REF, never HEAD and never the user branch, so only CORE
# commits travel; USER content is not in the pushed ref by construction.
#
# The TARGET may never be a `user/*` branch either. A private mirror whose
# default branch is the user branch (common: the instance repo was created from
# the user branch) would otherwise receive CORE history on top of the user's
# branch name, and a fast-forward from an ancestor would even succeed. In that
# case the core branch is the branch part of $UPSTREAM_REF; if the mirror has no
# such branch the step is skipped like any other missing branch.
mirror_core_branch() {
  [ "${MIRROR_CORE:-1}" = 0 ] && { echo "- mirror: skipped (MIRROR_CORE=0)"; return 0; }
  local remote="${MIRROR_REMOTE:-origin}" branch cur
  git remote get-url "$remote" >/dev/null 2>&1 || { echo "- mirror: skipped (no \`$remote\` remote)"; return 0; }

  # Target branch = the mirror's OWN default, never hardcoded; fall back to the
  # branch part of UPSTREAM_REF when the remote publishes no HEAD.
  branch=$(git symbolic-ref --quiet "refs/remotes/${remote}/HEAD" 2>/dev/null | sed "s|^refs/remotes/${remote}/||")
  case "$branch" in ''|user/*) branch="${UPSTREAM_REF#*/}" ;; esac
  case "$branch" in user/*) echo "- mirror: skipped (core branch \`$branch\` is a user branch)"; return 0 ;; esac

  git fetch "$remote" -q "$branch" 2>/dev/null || true
  cur=$(git rev-parse --verify --quiet "refs/remotes/${remote}/${branch}") \
    || { echo "- mirror: skipped (\`$remote/$branch\` does not exist yet — push it once by hand)"; return 0; }

  [ "$cur" = "$(git rev-parse "$UPSTREAM_REF")" ] && { echo "- mirror: \`$remote/$branch\` already current"; return 0; }
  git merge-base --is-ancestor "$cur" "$UPSTREAM_REF" 2>/dev/null \
    || { echo "- ⚠ mirror: \`$remote/$branch\` has diverged from \`$UPSTREAM_REF\` — NOT fast-forwardable, left alone"; return 0; }

  local n; n=$(git rev-list --count "${cur}..${UPSTREAM_REF}" 2>/dev/null || echo "?")
  if git push "$remote" "${UPSTREAM_REF}:refs/heads/${branch}" >/tmp/ob-autoupdate-mirror.log 2>&1; then
    echo "- ✅ mirror: \`$remote/$branch\` fast-forwarded $n commit(s) ($(git rev-parse --short "$cur") → $(git rev-parse --short "$UPSTREAM_REF"))"
  else
    echo "- ⚠ mirror: push to \`$remote/$branch\` failed (see /tmp/ob-autoupdate-mirror.log) — merge itself is fine"
  fi
  return 0
}

git fetch "$UPSTREAM_REMOTE" -q 2>/dev/null || true

behind=$(git rev-list --count "HEAD..$UPSTREAM_REF" 2>/dev/null || echo x)
is_int "$behind" || { report "- 🔴 cannot resolve \`$UPSTREAM_REF\` (fetch failed?)"; echo "autoupdate: no upstream ref"; exit 1; }
if [ "$behind" -eq 0 ]; then
  # The mirror still has to be asked, and this is the path where it matters most.
  # mirror_core_branch() used to be reachable ONLY after a successful auto-merge,
  # so an instance whose HEAD was brought up to date by hand — the case where a
  # human had to resolve a conflict — left origin/main behind for good: every
  # later run took this early exit and never looked. Measured on 2026-09-24,
  # seven days after the mirror step shipped: HEAD current, mirror 36 commits
  # behind, and the next user-branch push would have carried all of it again.
  # The call is idempotent (it checks ancestry and no-ops when already current),
  # so running it here costs nothing on a genuinely quiet day.
  mirror_line=$(mirror_core_branch)
  report "- ✓ up to date (0 behind \`$UPSTREAM_REF\`)" "$mirror_line"
  echo "autoupdate: up to date"
  echo "autoupdate: mirror — ${mirror_line#- }"
  exit 0
fi

# informational divergence count for the report (NOT a gate; unknown → '?')
risk=$(python3 scripts/bridge-divergence-check.py --upstream "$UPSTREAM_REF" --json 2>/dev/null \
       | python3 -c 'import sys,json;print(len(json.load(sys.stdin).get("conflict_risk",[])))' 2>/dev/null)
is_int "$risk" || risk="?"

# resolve_plan — ask scripts/upstream-resolve.py which conflicts a machine may decide.
# Sets take_theirs and take_ours (paths, newline-separated) and held (one
# "path (reason)" per unresolved file, '; '-joined). Any failure sets reason
# instead: fail closed.
take_theirs=""; take_ours=""; held=""
resolve_plan() {
  local plan
  plan=$(python3 scripts/upstream-resolve.py --theirs "$UPSTREAM_REF" 2>/tmp/ob-autoupdate-resolve.log) \
    || { reason="conflict resolver failed (see /tmp/ob-autoupdate-resolve.log), failing closed"; return; }
  take_theirs=$(printf '%s' "$plan" | python3 -c 'import sys,json
for t in json.load(sys.stdin)["take_theirs"]: print(t["path"])') \
    || { reason="conflict resolver output unreadable, failing closed"; return; }
  take_ours=$(printf '%s' "$plan" | python3 -c 'import sys,json
for t in json.load(sys.stdin)["take_ours"]: print(t["path"])') \
    || { reason="conflict resolver output unreadable, failing closed"; return; }
  held=$(printf '%s' "$plan" | python3 -c 'import sys,json
u=json.load(sys.stdin)["unresolved"]
def one(x):
    shas = ", ".join(c.split()[0] for c in x.get("local_commits") or [])
    return "%s (%s%s)" % (x["path"], x["reason"], ": " + shas if shas else "")
print("; ".join(one(x) for x in u))') \
    || { reason="conflict resolver output unreadable, failing closed"; return; }
}

# ---- the local check net ----
# The fast checks the pre-commit always-on gate runs (edges, standing orders,
# card index, reachability, the context budget), plus the two validators every
# commit on main meets in CI. Each is skipped when absent: a fork that has not
# taken a checker is not failing it. Measured on a live instance: under 2 s for
# all seven, so the job pays twice that (before and after the merge).
CHECKS=(
  "validate-bridge.py"
  "validate-skill-scope.py"
  "check-edges.py"
  "standing-orders.py --check"
  "context-index.py --check"
  "check-reachability.py"
  "measure-context.py"
)
CHECKS_LOG=/tmp/ob-autoupdate-checks.log
CHECKS_DIR=""
checks_ran=0
now_s() { perl -MTime::HiRes=time -e 'printf "%.1f", time'; }

# run_checks <phase>: sets red (the failing checks, one per line), present (the
# checks that exist in this tree, one per line) and checks_ran. Each check's
# output is kept per phase under $CHECKS_DIR, so a check red on both sides can
# be compared by what it says, not only by its exit code.
# Globals, not output: a $(...) caller would lose them in its subshell.
# Every check gets a 120 s alarm, so a hanging one fails rather than stalls.
red=""; present=""
run_checks() {
  local c s out
  checks_ran=0; red=""; present=""
  [ -n "$CHECKS_DIR" ] || CHECKS_DIR=$(mktemp -d /tmp/ob-autoupdate-checks.XXXXXX)
  mkdir -p "$CHECKS_DIR/$1"
  for c in "${CHECKS[@]}"; do
    s=${c%% *}
    [ -f "scripts/$s" ] || continue
    checks_ran=$((checks_ran + 1)); present="${present}${c}"$'\n'
    out="$CHECKS_DIR/$1/${s}.out"
    # shellcheck disable=SC2086
    perl -e 'alarm 120; exec @ARGV' python3 scripts/$c </dev/null >"$out" 2>&1 \
      || red="${red}${c}"$'\n'
    { echo "== $1: $c"; cat "$out"; } >>"$CHECKS_LOG"
  done
}

in_list() { printf '%s\n' "$2" | grep -qxF -- "$1"; }   # $1 a line of the list $2
words() { printf '%s' "$1" | sed '/^$/d' | tr '\n' ' ' | sed 's/ $//'; }

# A check's findings, normalised: digits folded (a count, a line number or a
# duration is not a new finding), blank lines dropped, order ignored.
findings_of() { sed -E 's/[0-9]+/N/g' "$1" 2>/dev/null | sed '/^[[:space:]]*$/d' | sort -u; }
has_new_findings() {  # $1 = check; true when the after-run says a line the before-run did not
  local s=${1%% *}
  [ -n "$(comm -13 <(findings_of "$CHECKS_DIR/before/$s.out") <(findings_of "$CHECKS_DIR/after/$s.out"))" ]
}

# closes_when for an inbox item: every named check green again, and with $1=1
# the upstream ref on the user branch too. Pinned to refs/heads/<branch>, never
# HEAD (an inbox check may run in a worktree on another branch), and to the
# moving $UPSTREAM_REF, never a SHA (a repeat add keeps the first item's probe).
probe_json() {
  python3 - "$UPSTREAM_REF" "refs/heads/$branch" "$@" <<'PY'
import json, sys
up, ref, need, *checks = sys.argv[1:]
parts = [{"command": ["git", "merge-base", "--is-ancestor", up, ref]}] if need == "1" else []
parts += [{"command": ["python3", "scripts/" + c.split()[0], *c.split()[1:]]} for c in checks if c]
print(json.dumps({"all": parts}))
PY
}

INBOX_KEY="upstream-autoupdate-checks"
RULES_KEY="upstream-autoupdate-rules"
inbox() {  # argv for scripts/inbox.py; a missing or failing inbox never fails the run
  [ -f scripts/inbox.py ] || return 0
  python3 scripts/inbox.py "$@" >/dev/null 2>&1 || true
}

# ---- GUARDS (fail closed) ----
reason=""
branch=$(git branch --show-current 2>/dev/null || echo "")
case "$branch" in user/*) ;; *) reason="not on a user/* branch (on '${branch:-detached}')";; esac

if [ -z "$reason" ] && ! git diff --cached --quiet; then
  reason="the index has staged changes"
fi
if [ -z "$reason" ] && ! git diff --quiet; then
  # Only a dirty file the merge would touch stops it. git itself refuses such a
  # merge too, but refusing here keeps the report precise and the tree untouched.
  base=$(git merge-base HEAD "$UPSTREAM_REF" 2>/dev/null) \
    || reason="cannot find the merge base with \`$UPSTREAM_REF\` (failing closed)"
  if [ -z "$reason" ]; then
    overlap=$(comm -12 <(git diff --name-only | sort -u) \
                       <(git diff --name-only "$base" "$UPSTREAM_REF" | sort -u) | tr '\n' ' ' | sed 's/ $//')
    [ -n "$overlap" ] && reason="uncommitted changes in files the merge touches: $overlap"
  fi
fi

if [ -z "$reason" ]; then
  # Authoritative signal is merge-tree's EXIT CODE, not its prose:
  #   0 = clean · 1 = conflicts · >1 = the command itself failed.
  # This used to grep the output for "conflict", which is a LOCALE-DEPENDENT
  # string and silently returned 0 on any non-English git. On de_DE the output
  # reads "KONFLIKT (Inhalt): Merge-Konflikt in <file>" — no match, so the
  # gate that exists to fail closed reported "safe" and the merge went ahead
  # and failed. That is exactly what happened on 2026-09-07 (.gitignore).
  # LC_ALL=C is belt-and-braces: it pins any output we or a human read.
  LC_ALL=C git merge-tree --write-tree HEAD "$UPSTREAM_REF" >/dev/null 2>&1
  mt_rc=$?
  case "$mt_rc" in
    0) : ;;                                                    # provably clean
    1) resolve_plan          # sets take_theirs / held, or reason on any doubt
       [ -z "$reason" ] && [ -n "$held" ] \
         && reason="conflict(s) a machine must not decide — $held" ;;
    *) reason="merge-tree could not verify safety (exit $mt_rc, failing closed)" ;;
  esac
fi

if [ -n "$reason" ]; then
  report "- ⚠ auto-update SKIPPED: $reason" \
         "- $behind commit(s) behind \`$UPSTREAM_REF\` · sentinel conflict-risk: $risk" \
         "${held:+- each held file: \`/promote\` the local change, or drop it in favour of upstream; the next run merges the rest}"
  notify "⚠ open-bridge auto-update SKIPPED: $reason ($behind behind). Manual merge needed."
  echo "autoupdate: skipped — $reason"; exit 0
fi

# ---- SAFE → auto-merge (skip the local pre-commit hook for the headless merge) ----
before=$(git rev-parse --short HEAD)
before_full=$(git rev-parse HEAD)

# Baseline BEFORE the merge, so a check that is already red locally (a dead edge
# in work/, a half-finished config) is told apart from one the merge broke. Without
# it, one unrelated local break would freeze this job for good, the very failure
# the resolver above was built to end.
red_before=""; red_after=""; present_before=""; checks_line=""
if [ "${AUTOUPDATE_CHECKS:-1}" = 0 ]; then
  checks_line="- checks: skipped (AUTOUPDATE_CHECKS=0)"
else
  : > "$CHECKS_LOG"
  run_checks before; red_before=$red; present_before=$present
fi

# resolve_merge — finish a merge that stopped on exactly the planned conflicts by
# taking upstream's side of each take_theirs path and the local side of each
# take_ours path. Anything else unmerged, or any step failing, returns non-zero
# and the caller aborts the merge.
resolve_merge() {
  local unmerged planned theirs ours p
  theirs=$(printf '%s\n' "$take_theirs" | sed '/^$/d' | sort -u)
  ours=$(printf '%s\n' "$take_ours" | sed '/^$/d' | sort -u)
  unmerged=$(git diff --name-only --diff-filter=U | sort -u)
  planned=$(printf '%s\n%s\n' "$theirs" "$ours" | sed '/^$/d' | sort -u)
  [ -n "$unmerged" ] && [ "$unmerged" = "$planned" ] || return 1
  if [ -n "$theirs" ]; then
    while IFS= read -r p; do
      if git cat-file -e "$UPSTREAM_REF:$p" 2>/dev/null; then
        git checkout --theirs -- "$p" && git add -- "$p" || return 1
      else
        git rm -q -- "$p" || return 1
      fi
    done <<< "$theirs"
  fi
  if [ -n "$ours" ]; then
    while IFS= read -r p; do
      git checkout --ours -- "$p" && git add -- "$p" || return 1
    done <<< "$ours"
  fi
  [ -z "$(git diff --name-only --diff-filter=U)" ] || return 1
  git -c core.hooksPath=/dev/null commit -q --no-edit \
    -m "Merge $UPSTREAM_REF into $branch (auto-update)" \
    ${theirs:+-m "Conflicts resolved to upstream by scripts/upstream-resolve.py (local version already seen upstream):"} \
    ${theirs:+-m "$(printf '%s\n' "$theirs" | sed 's/^/  /')"} \
    ${ours:+-m "Conflicts kept local by scripts/upstream-resolve.py (upstream version already seen locally, or already contained):"} \
    ${ours:+-m "$(printf '%s\n' "$ours" | sed 's/^/  /')"}
}

merged=0
if git -c core.hooksPath=/dev/null merge --no-edit "$UPSTREAM_REF" >/tmp/ob-autoupdate-merge.log 2>&1; then
  merged=1
elif [ -n "$take_theirs$take_ours" ] && resolve_merge >>/tmp/ob-autoupdate-merge.log 2>&1; then
  merged=1
fi

if [ "$merged" = 1 ] && [ -z "$checks_line" ]; then
  t0=$(now_s)
  run_checks after; red_after=$red
  secs=$(perl -e 'printf "%.1f", $ARGV[1] - $ARGV[0]' "$t0" "$(now_s)")
  # Sort every red check into one of three piles:
  #   rules  the checker is new with the merge, or the merge changed it. What it
  #          finds is instance content measured by a new rule; rolling back would
  #          repeat every morning and freeze the job, so the merge is kept and the
  #          finding filed. A rule upstream tightened in a file other than the
  #          checker itself (a schema, a budget) is not seen here and lands in
  #          broke: rollback plus an item, the safe side.
  #   broke  green before and red after, or red on both sides with a finding the
  #          before-run did not have (normalised output, see findings_of): the
  #          merge broke it. Rolled back.
  #   still  red on both sides, saying the same: a local break the merge did not
  #          cause. Reported, never a reason to hold the job.
  broke=""; rules=""; still=""
  while IFS= read -r c; do
    [ -n "$c" ] || continue
    if ! in_list "$c" "$present_before" || ! git diff --quiet "$before_full" HEAD -- "scripts/${c%% *}"; then
      rules="${rules}${c}"$'\n'
    elif ! in_list "$c" "$red_before" || has_new_findings "$c"; then
      broke="${broke}${c}"$'\n'
    else
      still="${still}${c}"$'\n'
    fi
  done <<<"$red_after"
  if [ -n "$broke" ]; then
    # ROLL BACK, do not keep. A kept merge would leave the branch 0 behind, and
    # the next run would take the up-to-date exit, push the mirror and report
    # green: the red would vanish from every report. Rolling back loses nothing:
    # the upstream commits stay in $UPSTREAM_REF, the local commits were never
    # touched, and `reset --keep` refuses rather than overwrite a local change
    # (the dirty files guard 2 let through are files the merge does not touch).
    # The merge commit itself stays reachable through the reflog. If the reset
    # is refused all the same, the item's probe still reruns the named checks,
    # so it stays open while the merge it could not undo is red.
    merge_sha=$(git rev-parse --short HEAD)
    if git reset -q --keep "$before_full" >>"$CHECKS_LOG" 2>&1; then
      undo="rolled back to \`$before\` (merge \`$merge_sha\` stays in the reflog)"
    else
      undo="could NOT be rolled back, merge \`$merge_sha\` left in place, do not push it"
    fi
    b=$(words "$broke")
    report "- 🔴 auto-update merge turned check(s) red: $b. The merge $undo." \
           "- $behind commit(s) behind \`$UPSTREAM_REF\` · checks ran in ${secs}s · output: $CHECKS_LOG" \
           "- mirror: skipped (checks red)" \
           "- reproduce: \`git merge $UPSTREAM_REF\`, then run each named check"
    # One argument per check line: IFS is a newline and globbing is off, in the
    # subshell only.
    # shellcheck disable=SC2086
    probe=$(set -f; IFS=$'\n'; probe_json 1 $broke)
    inbox add --from upstream-autoupdate --kind finding --urgency today \
      --summary "Upstream merge turned checks red: $b" \
      --detail "The daily auto-update merged $behind upstream commit(s), and these checks then failed, or gained findings, that the tree before the merge did not have: $b. The merge $undo. Merge $UPSTREAM_REF by hand, fix what the checks name, then commit. Output of the run: $CHECKS_LOG" \
      --key "$INBOX_KEY" --closes-when-json "$probe"
    notify "🔴 open-bridge auto-update: merge turned checks red ($b), $undo. Manual merge needed."
    echo "autoupdate: checks red after merge ($b), $undo"; exit 1
  fi
  ran_after=$checks_ran
  n_red=$(printf '%s' "$red_after" | sed '/^$/d' | wc -l | tr -d ' ')
  checks_line="- checks: $((ran_after - n_red)) passed in ${secs}s"
  [ "$ran_after" = 0 ] && checks_line="- checks: none present"
  [ -n "$still" ] && checks_line="$checks_line · already red before the merge: $(words "$still")"
  if [ -n "$rules" ]; then
    r=$(words "$rules")
    # shellcheck disable=SC2086
    rprobe=$(set -f; IFS=$'\n'; probe_json 0 $rules)
    checks_line="$checks_line · ⚠ red, checker new or changed with the merge (merge kept, the finding is instance content to fix): $r"
    inbox add --from upstream-autoupdate --kind finding --urgency today \
      --summary "A new or changed upstream check is red on this instance: $r" \
      --detail "The daily auto-update merged $behind upstream commit(s) that brought or changed these checkers, and they fail on this tree: $r. The merge was kept, since the rule is upstream's and what it finds is local. Run each named check and fix what it reports. Output of the run: $CHECKS_LOG" \
      --key "$RULES_KEY" --closes-when-json "$rprobe"
  fi
  inbox close --key "$INBOX_KEY" --note "the next upstream merge passed the checks"
  [ -z "$red_after" ] && inbox close --key "$RULES_KEY" --note "every check is green after the next upstream merge"
fi

if [ "$merged" = 1 ]; then
  after=$(git rev-parse --short HEAD)
  mirror_line=$(mirror_core_branch)
  resolved_line=""
  [ -n "$take_theirs" ] && resolved_line="- auto-resolved to upstream: $(printf '%s' "$take_theirs" | tr '\n' ' ')"
  kept_line=""
  [ -n "$take_ours" ] && kept_line="- kept local: $(printf '%s' "$take_ours" | tr '\n' ' ')"
  report "- ✅ auto-updated \`$before\` → \`$after\` ($behind commit(s) merged from \`$UPSTREAM_REF\`)" \
         ${resolved_line:+"$resolved_line"} ${kept_line:+"$kept_line"} "$checks_line" "$mirror_line"
  notify "✅ open-bridge auto-updated: $behind commit(s) merged ($before→$after)"
  echo "autoupdate: merged $behind commit(s) ($before→$after)"
  echo "autoupdate: mirror — ${mirror_line#- }"
else
  git merge --abort 2>/dev/null || true
  report "- 🔴 auto-update merge FAILED and was aborted — $behind behind, manual merge needed"
  notify "🔴 open-bridge auto-update merge FAILED (aborted). Manual merge needed."
  echo "autoupdate: merge failed, aborted"; exit 1
fi
