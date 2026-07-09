#!/usr/bin/env bash
# board-audit.sh — Board-hygiene audit for a GitHub ProjectV2.
#
# Finds the two drift classes a human cleanup looks for:
#   RECONCILE : board Status disagrees with the backing issue's real
#               state / close-reason (e.g. board says "Declined" but the
#               issue is still OPEN, or was closed as "completed").
#   COVERAGE  : open issues in the project's repo(s) that are NOT on the
#               board at all (orphans).
#
# Generic + config-first: the CALLER (github-projects-manager skill) reads
# workflow/projects/<slug>.yaml and passes the board's terminal Status
# strings via --declined / --done, plus the tracked repos via --repos.
# Without those, Status is classified by language-agnostic keyword heuristics
# (declin|cancel|reject|abgelehnt|storniert|wontfix  vs  done|complete|
# erledigt|fertig|live|shipped) — a fallback, never a substitute for config.
#
# Runs under bash (shebang) so word-splitting is well-defined — do NOT port
# the loops to zsh without `${=var}` (zsh does not split unquoted expansions).
#
# READ-ONLY. Prints a report; changes nothing.
#
# Usage:
#   board-audit.sh --owner <org> --project <num> \
#       [--declined "<board Status = declined>"] \
#       [--done     "<board Status = done>"] \
#       [--repos owner/repo1,owner/repo2,...]   # for the COVERAGE pass
set -euo pipefail

OWNER="" PROJECT="" DECLINED="" DONE="" REPOS=""
while [ $# -gt 0 ]; do
  case "$1" in
    --owner)    OWNER="$2"; shift 2 ;;
    --project)  PROJECT="$2"; shift 2 ;;
    --declined) DECLINED="$2"; shift 2 ;;
    --done)     DONE="$2"; shift 2 ;;
    --repos)    REPOS="$2"; shift 2 ;;
    -h|--help)  grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    *) echo "unknown arg: $1" >&2; exit 2 ;;
  esac
done
[ -n "$OWNER" ] && [ -n "$PROJECT" ] || { echo "need --owner and --project" >&2; exit 2; }

# ── classify a board Status string into: declined | done | active ──────────
classify() {
  local s="$1" low
  [ -n "$DECLINED" ] && [ "$s" = "$DECLINED" ] && { echo declined; return; }
  [ -n "$DONE" ]     && [ "$s" = "$DONE" ]     && { echo done; return; }
  low=$(printf '%s' "$s" | tr '[:upper:]' '[:lower:]')
  case "$low" in
    *declin*|*cancel*|*reject*|*abgelehnt*|*storniert*|*wontfix*|*"won't"*) echo declined ;;
    *done*|*complete*|*erledigt*|*fertig*|*live*|*shipped*|*archiv*)        echo done ;;
    *) echo active ;;
  esac
}

# ── pull ALL board items (paginated) → TSV: status \t type \t repo \t num \t state \t reason \t url
items_tsv() {
  gh api graphql --paginate -f query='
    query($owner:String!,$num:Int!,$endCursor:String){
      organization(login:$owner){ projectV2(number:$num){
        items(first:100, after:$endCursor){
          pageInfo{ hasNextPage endCursor }
          nodes{
            fieldValueByName(name:"Status"){ ... on ProjectV2ItemFieldSingleSelectValue{ name } }
            content{ __typename
              ... on Issue{ number url state stateReason repository{ nameWithOwner } } }
          }
        }
      }}
    }' -f owner="$OWNER" -F num="$PROJECT" \
  | jq -r -s '[.[].data.organization.projectV2.items.nodes[]]
      | .[]
      | select(.content.__typename=="Issue")
      | [ (.fieldValueByName.name // "(no status)"), .content.__typename,
          .content.repository.nameWithOwner, (.content.number|tostring),
          .content.state, (.content.stateReason // "null"), .content.url ]
      | @tsv'
}

echo "══════════════════════════════════════════════════════════════════"
echo " Board-hygiene audit — $OWNER / project #$PROJECT"
[ -n "$DECLINED$DONE" ] && echo " config Status: declined=\"$DECLINED\"  done=\"$DONE\"" \
                        || echo " (no --declined/--done given → keyword heuristics)"
echo "══════════════════════════════════════════════════════════════════"

TSV="$(items_tsv)"
total=$(printf '%s\n' "$TSV" | grep -c . || true)
nostatus=$(printf '%s\n' "$TSV" | awk -F'\t' '$1=="(no status)"' | grep -c . || true)

echo
echo "── RECONCILE: board Status vs issue state/close-reason ──"
mismatch=0
while IFS=$'\t' read -r status typ repo num state reason url; do
  [ -z "${status:-}" ] && continue
  [ "$status" = "(no status)" ] && continue
  cls=$(classify "$status")
  case "$cls" in
    declined)
      if [ "$state" = "OPEN" ]; then
        echo "  ✗ [$repo#$num] board=\"$status\" but issue OPEN → close as not_planned"; mismatch=$((mismatch+1))
      elif [ "$state" = "CLOSED" ] && [ "$reason" != "NOT_PLANNED" ]; then
        echo "  ⚠ [$repo#$num] board=\"$status\" but issue CLOSED/$reason → contradiction (HUMAN: board→done OR reason→not_planned)"; mismatch=$((mismatch+1))
      fi ;;
    done)
      if [ "$state" = "OPEN" ]; then
        echo "  ✗ [$repo#$num] board=\"$status\" but issue OPEN → close (completed) or move board off done"; mismatch=$((mismatch+1))
      fi ;;
    active)
      if [ "$state" = "CLOSED" ]; then
        echo "  ⚠ [$repo#$num] issue CLOSED/$reason but board=\"$status\" (active) → stale board, move to done/declined"; mismatch=$((mismatch+1))
      fi ;;
  esac
done <<< "$TSV"
[ "$mismatch" -eq 0 ] && echo "  ✓ no reconcile mismatches"

echo
echo "── COVERAGE: open issues NOT on the board (orphans) ──"
if [ -z "$REPOS" ]; then
  echo "  (skipped — pass --repos owner/repo1,owner/repo2 to run coverage)"
else
  orphans=0
  IFS=',' read -ra RA <<< "$REPOS"
  for repo in "${RA[@]}"; do
    # NOTE: comm compares lexically → both inputs MUST use plain `sort`
    # (LC_ALL=C), never `sort -n`, or mixed 2-/3-digit numbers mis-diff.
    onboard=$(printf '%s\n' "$TSV" | awk -F'\t' -v r="$repo" '$3==r{print $4}' | grep -E '^[0-9]+$' | LC_ALL=C sort -u || true)
    open=$(gh issue list --repo "$repo" --state open --limit 500 --json number --jq '.[].number' 2>/dev/null | grep -E '^[0-9]+$' | LC_ALL=C sort -u || true)
    miss=$(comm -23 <(printf '%s\n' "$open") <(printf '%s\n' "$onboard") | grep -E '^[0-9]+$' | sort -n || true)
    if [ -n "$miss" ]; then
      cnt=$(printf '%s\n' "$miss" | grep -c .)
      echo "  ✗ $repo: $cnt open issue(s) off-board → #$(printf '%s' "$miss" | tr '\n' ' ')"
      orphans=$((orphans+cnt))
    else
      echo "  ✓ $repo: all open issues on board"
    fi
  done
fi

echo
echo "── SUMMARY ──"
echo "  board issue-items: $total   |   no-status items: $nostatus   |   reconcile mismatches: $mismatch"
