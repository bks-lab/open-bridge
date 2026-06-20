#!/usr/bin/env bash
# session-start-phase0.sh — Claude Code SessionStart hook
#
# Runs the Bridge's Phase 0 branch/config detection deterministically
# at every session start, instead of relying on Claude to remember
# rules/session-start.md. Emits a structured markdown block to stdout
# which Claude Code injects as additional context.
#
# Enable via .claude/settings.local.json:
#
#   {
#     "hooks": {
#       "SessionStart": [
#         {
#           "hooks": [
#             {"type": "command",
#              "command": "${CLAUDE_PROJECT_DIR}/.claude/hooks/session-start-phase0.sh"}
#           ]
#         }
#       ]
#     }
#   }
#
# Exit codes:
#   0 — always (this is informational, never blocks)

set -u

cd "${CLAUDE_PROJECT_DIR:-$(pwd)}" 2>/dev/null || exit 0

# Not a git repo → nothing to detect
git rev-parse --git-dir >/dev/null 2>&1 || exit 0

branch=$(git branch --show-current 2>/dev/null || echo "")
user_branches=$(git branch --list 'user/*' --format='%(refname:short)' 2>/dev/null | tr '\n' ' ' | sed 's/ $//')
has_config=no
[ -f "bridge-config.yaml" ] && has_config=yes

# State machine (mirrors rules/session-start.md decision matrix)
state="UNKNOWN"
hint=""

case "$branch" in
  user/*)
    if [ "$has_config" = "yes" ]; then
      state="NORMAL"
      hint="Proceed to Phase 1 (rules/operations.md § Session Start)."
    else
      state="BROKEN_USER_BRANCH"
      hint="Config missing on user branch. Offer /onboard or check git status."
    fi
    ;;
  main)
    if [ -n "$user_branches" ] && [ "$has_config" = "yes" ]; then
      state="WRONG_BRANCH"
      default_user=$(echo "$user_branches" | awk '{print $1}')
      hint="Your work branch exists: $default_user. Suggest: git checkout $default_user"
    elif [ -z "$user_branches" ] && [ "$has_config" = "no" ]; then
      state="NEW_USER"
      hint="Fresh clone. Greet as the orchestrator per rules/session-start.md § NEW USER, offer onboarding."
    elif [ -z "$user_branches" ] && [ "$has_config" = "yes" ]; then
      state="ORPHAN"
      hint="Config present, no user branch. Offer: (a) recreate user/<name>, (b) reset config + onboard, (c) CORE-only."
    elif [ -n "$user_branches" ] && [ "$has_config" = "no" ]; then
      state="BROKEN_CONFIG"
      default_user=$(echo "$user_branches" | awk '{print $1}')
      hint="Config likely lives on the user branch. Suggest: git checkout $default_user"
    fi
    ;;
  master|feature/*|fix/*|chore/*|docs/*|refactor/*)
    state="CORE_DEV"
    hint="Working on CORE directly. Skip work-system load. Answer normally."
    ;;
  *)
    state="CORE_DEV"
    hint="Non-user branch '$branch'. Skip work-system load unless user indicates otherwise."
    ;;
esac

# Optional upstream drift hint (cheap, no fetch)
upstream_ahead=""
if [ "$state" = "NORMAL" ]; then
  ahead=$(git log "${branch}..main" --oneline 2>/dev/null | wc -l | tr -d ' ')
  if [ "$ahead" != "0" ] && [ -n "$ahead" ]; then
    upstream_ahead=" · ${ahead} CORE commits ahead — offer \`git merge main\` when convenient"
  fi
fi

# Work-log freshness (only in NORMAL)
worklog_hint=""
if [ "$state" = "NORMAL" ] && [ -f work/log.md ]; then
  mtime_epoch=$(stat -f %m work/log.md 2>/dev/null || stat -c %Y work/log.md 2>/dev/null || echo 0)
  now_epoch=$(date +%s)
  age_hours=$(( (now_epoch - mtime_epoch) / 3600 ))
  if [ "$age_hours" -gt 24 ]; then
    worklog_hint=" · work/log.md stale (${age_hours}h) — consider a day-block entry"
  fi
fi

cat <<EOF
<bridge-phase0>
**Phase 0 detection (automatic):** state=**${state}** · branch=\`${branch:-<none>}\` · bridge-config.yaml=${has_config} · user branches: ${user_branches:-<none>}${upstream_ahead}${worklog_hint}

**Next action:** ${hint}

(This block replaces manual Phase 0 per rules/session-start.md. Override with "skip state check".)
</bridge-phase0>
EOF

exit 0
