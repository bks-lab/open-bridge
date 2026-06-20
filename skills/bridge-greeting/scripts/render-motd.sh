#!/bin/bash
# Bridge greeting (MOTD): animated fastfetch cascade + greeting + instance panel.
# Generic engine — all per-machine data (calendars, repos, org trees, GitHub
# tasks org/login/projects, branding) lives in the machine-local override
# ~/.config/fastfetch/bridge-motd.local.sh. A clone without that file greets
# cleanly (empty data → those panels simply don't render).

CACHE_DIR="$HOME/.cache/bridge-motd"
CACHE_FILE="$CACHE_DIR/tasks.cache"
CLAUDE_CACHE="$CACHE_DIR/claude.cache"
CACHE_MAX_AGE=1800  # 30 minutes
CLAUDE_CACHE_MAX_AGE=300  # 5 minutes
REPOS_CACHE="$CACHE_DIR/repos.cache"
PRS_CACHE="$CACHE_DIR/prs.cache"
NOTIF_CACHE="$CACHE_DIR/notif.cache"
STREAK_CACHE="$CACHE_DIR/streak.cache"
REPOS_CACHE_MAX_AGE=300   # 5 minutes
PRS_CACHE_MAX_AGE=1800    # 30 minutes
NOTIF_CACHE_MAX_AGE=600   # 10 minutes
STREAK_CACHE_MAX_AGE=3600 # 1 hour
MEETINGS_CACHE="$CACHE_DIR/meetings.cache"
MEETINGS_CACHE_MAX_AGE=600  # 10 minutes

# ── Per-machine config (USER, never committed) ──────────
# The override defines the BRIDGE_MOTD_* data. Empty defaults keep a generic
# clone working (no calendars/repos/GitHub → those panels just don't render).
BRIDGE_MOTD_OVERRIDES=()        # "org|label|logo|c1|c2|tags|filter" per org
BRIDGE_MOTD_CALENDAR_MAP=()     # "CalendarName:AccountSubstring:Tag" (macOS Calendar Store)
BRIDGE_MOTD_MONITORED_REPOS=()  # "<dir>:<label>" curated repos under the curated tree
BRIDGE_MOTD_ORG_TREES=()        # extra org dirs under ~/Developer to glob-scan for dirty repos
BRIDGE_MOTD_CURATED_TREE=""     # org dir under ~/Developer holding the curated repos
BRIDGE_MOTD_DEFAULT_LOGO=""     # neutral-mode logo path ("" = fastfetch built-in)
BRIDGE_MOTD_USER_NAME=""        # name in the greeting ("" = greet generically, no name)
BRIDGE_GH_ORG=""                # GitHub org for the neutral-mode "Active Tasks" box
BRIDGE_GH_LOGIN=""              # GitHub login to filter assigned tasks by
BRIDGE_GH_PROJECTS=()           # GitHub Project V2 numbers to scan
[[ -r "$HOME/.config/fastfetch/bridge-motd.local.sh" ]] && \
  source "$HOME/.config/fastfetch/bridge-motd.local.sh"

# Calendar map for meetings — see BRIDGE_MOTD_CALENDAR_MAP above.
CALENDAR_MAP=( "${BRIDGE_MOTD_CALENDAR_MAP[@]}" )

# ── Org trees ───────────────────────────────────────────
# Clones live under ~/Developer/<org>/. The org folder is the context switch.
DEV_ROOT="$HOME/Developer"
CURATED_ROOT="$DEV_ROOT/${BRIDGE_MOTD_CURATED_TREE}"

# Curated repos for uncommitted-work & streak (a tree may have too many repos to
# git-status fully): "<dir>:<label>" under CURATED_ROOT. Other trees in
# BRIDGE_MOTD_ORG_TREES are scanned dynamically by glob.
MONITORED_REPOS=( "${BRIDGE_MOTD_MONITORED_REPOS[@]}" )

# Brand colours (True Color / 24-bit) — appearance-aware
if [[ "$(defaults read -g AppleInterfaceStyle 2>/dev/null)" == "Dark" ]]; then
  BRAND_PRIMARY='\033[38;2;102;126;234m'   # #667eea
  BRAND_SECONDARY='\033[38;2;118;75;162m'    # #764ba2
  BRAND_LIGHT='\033[38;2;167;139;250m'    # #a78bfa
  BRAND_ACCENT='\033[38;2;129;140;248m'   # #818cf8
  DIM='\033[2m'
else
  # Darker variants for light backgrounds (Catppuccin Latte #eff1f5)
  BRAND_PRIMARY='\033[38;2;79;96;196m'     # #4f60c4 — contrast ~5:1
  BRAND_SECONDARY='\033[38;2;118;75;162m'    # #764ba2 — already dark enough
  BRAND_LIGHT='\033[38;2;124;95;196m'     # #7c5fc4 — contrast ~4.5:1
  BRAND_ACCENT='\033[38;2;90;100;210m'    # #5a64d2 — contrast ~4.5:1
  DIM='\033[90m'                          # palette 8 instead of dim
fi
BOLD='\033[1m'
RED='\033[0;31m'
RESET='\033[0m'

# ── Context Resolver (discovery + branding override) ────
# Resolves the working context from $PWD at terminal-open time. The org folder
# under ~/Developer/<org>/ is matched against discovered Bridge instances (any
# */bridge-config.yaml). Logo/colours/tags come from a machine-local override
# (if present) else the instance theme's branding: block. No org literals here
# — open-bridge-safe. Home / unknown dir → neutral (full board).
CTX_MODE="neutral"        # neutral | instance
CTX_LABEL=""              # display label (the instance name shown in the header)
CTX_ORG=""                # org-folder key (dirty-repo filter)
CTX_INSTANCE=""           # discovered Bridge instance path (board.md source)
CTX_TASK_FILTER=""        # row-level regex for shared-board contexts
CTX_MEETING_TAGS=""       # space-separated allowed calendar tags ("" = all)
CTX_COLOR=""              # instance accent (SGR fragment from branding; "" / "none" = neutral)

# (BRIDGE_MOTD_OVERRIDES is populated by the machine-local override sourced at top.)

# Echo the override line for an org key (empty if none).
_ovr() {
  local key="$1" line
  [[ -z "$key" ]] && return
  for line in "${BRIDGE_MOTD_OVERRIDES[@]}"; do
    [[ "${line%%|*}" == "$key" ]] && { printf '%s\n' "$line"; return; }
  done
}

# Echo "logo<TAB>color1<TAB>color2<TAB>calendar_tags" from an instance theme's
# branding: block (logo path repo-relative). Empty fields when absent.
_theme_branding() {
  local inst="$1" cfg theme tf blk label logo c1 c2 tags
  cfg="$inst/bridge-config.yaml"; [[ -f "$cfg" ]] || return
  theme=$(/usr/bin/grep -E '^theme:' "$cfg" | head -1 | sed -E 's/^theme:[[:space:]]*//; s/["'"'"']//g; s/[[:space:]]+#.*$//; s/[[:space:]]*$//')
  [[ -z "$theme" ]] && theme="professional"
  tf="$inst/themes/$theme.yaml"; [[ -f "$tf" ]] || return
  blk=$(awk '/^branding:/{f=1;next} f&&/^[^[:space:]#]/{exit} f' "$tf")
  logo=$(printf '%s\n' "$blk" | /usr/bin/grep 'logo_ascii:'    | head -1 | sed -E 's/.*logo_ascii:[[:space:]]*//;    s/["'"'"']//g; s/[[:space:]]+#.*$//; s/[[:space:]]*$//')
  c1=$(printf '%s\n'   "$blk" | /usr/bin/grep 'logo_color_1:'  | head -1 | sed -E 's/.*logo_color_1:[[:space:]]*//;  s/["'"'"']//g; s/[[:space:]]+#.*$//; s/[[:space:]]*$//')
  c2=$(printf '%s\n'   "$blk" | /usr/bin/grep 'logo_color_2:'  | head -1 | sed -E 's/.*logo_color_2:[[:space:]]*//;  s/["'"'"']//g; s/[[:space:]]+#.*$//; s/[[:space:]]*$//')
  tags=$(printf '%s\n' "$blk" | /usr/bin/grep 'calendar_tags:' | head -1 | sed -E 's/.*calendar_tags:[[:space:]]*//; s/["'"'"']//g; s/[[:space:]]+#.*$//; s/[[:space:]]*$//')
  label=$(printf '%s\n' "$blk" | /usr/bin/grep 'label:' | head -1 | sed -E 's/.*label:[[:space:]]*//; s/["'"'"']//g; s/[[:space:]]+#.*$//; s/[[:space:]]*$//')
  printf '%s\t%s\t%s\t%s\t%s\n' "$label" "$logo" "$c1" "$c2" "$tags"
}

resolve_context() {
  case "$PWD" in "$DEV_ROOT"/?*) ;; *) CTX_MODE="neutral"; return ;; esac
  local rel="${PWD#$DEV_ROOT/}"
  local org="${rel%%/*}"   # bash 3.2: must be a separate statement so $rel resolves
  [[ -z "$org" ]] && { CTX_MODE="neutral"; return; }

  # Discover the instance: first dir under ~/Developer/<org>/* with a config
  local d
  for d in "$DEV_ROOT/$org"/*/; do
    [[ -f "${d}bridge-config.yaml" ]] && { CTX_INSTANCE="${d%/}"; break; }
  done

  CTX_MODE="instance"; CTX_ORG="$org"

  local ovr; ovr="$(_ovr "$org")"
  if [[ -n "$ovr" ]]; then
    local _o _logo _c1 _c2 _flt
    IFS='|' read -r _o CTX_LABEL _logo _c1 _c2 CTX_MEETING_TAGS _flt <<< "$ovr"
    CTX_TASK_FILTER="$(printf '%s' "$_flt" | tr ',' '|')"
    CTX_COLOR="$_c1"
  else
    CTX_LABEL="$org"
    if [[ -n "$CTX_INSTANCE" ]]; then
      local _lbl _lg _c1 _c2 _tags
      IFS=$'\t' read -r _lbl _lg _c1 _c2 _tags < <(_theme_branding "$CTX_INSTANCE")
      [[ -n "$_lbl" ]] && CTX_LABEL="$_lbl"
      CTX_MEETING_TAGS="$_tags"
      CTX_COLOR="$_c1"
    fi
  fi
}

# ── Skip Animation on Keypress ────────────────────────────

SKIP_ANIM=0
KEYPRESS_PID=""

start_keypress_listener() {
  # Read a single keypress in background; sets flag file when detected
  local flag="$CACHE_DIR/.skip_anim"
  rm -f "$flag"
  (
    read -rsn1 -t 30 2>/dev/null
    touch "$flag"
  ) &
  KEYPRESS_PID=$!
}

stop_keypress_listener() {
  [[ -n "$KEYPRESS_PID" ]] && kill "$KEYPRESS_PID" 2>/dev/null
  wait "$KEYPRESS_PID" 2>/dev/null
  KEYPRESS_PID=""
  rm -f "$CACHE_DIR/.skip_anim"
}

check_skip() {
  [[ -f "$CACHE_DIR/.skip_anim" ]] && SKIP_ANIM=1
  return $SKIP_ANIM
}

# Animated sleep -- skips if key was pressed
anim_sleep() {
  (( SKIP_ANIM )) && return
  check_skip && return
  sleep "$1"
}

# ── Animation Helpers ───────────────────────────────────

type_text() {
  local text="$1" delay="${2:-0.03}"
  if (( SKIP_ANIM )) || check_skip; then
    printf '%s' "$text"
    return
  fi
  for (( i=0; i<${#text}; i++ )); do
    printf '%s' "${text:$i:1}"
    (( SKIP_ANIM )) || check_skip && { printf '%s' "${text:$((i+1))}"; return; }
    sleep "$delay"
  done
}

draw_hline() {
  local width="$1" char="${2:-─}" delay="${3:-0.006}"
  if (( SKIP_ANIM )) || check_skip; then
    printf "%0.s${char}" $(seq 1 "$width")
    return
  fi
  for (( i=0; i<width; i++ )); do
    printf '%s' "$char"
    (( SKIP_ANIM )) || check_skip && {
      local remaining=$(( width - i - 1 ))
      (( remaining > 0 )) && printf "%0.s${char}" $(seq 1 "$remaining")
      return
    }
    sleep "$delay"
  done
}

# ── Fastfetch Cascade ─────────────────────────────────────

show_fastfetch() {
  # Logo + colours: machine-local override → resolved instance theme branding →
  # engine default. The logo follows the resolved Bridge instance.
  local logo="" c1="" c2=""
  local ovr; ovr="$(_ovr "$CTX_ORG")"
  if [[ -n "$ovr" ]]; then
    local _o _l _tags _flt
    IFS='|' read -r _o _l logo c1 c2 _tags _flt <<< "$ovr"
  fi
  if [[ -z "$logo" && -n "$CTX_INSTANCE" ]]; then
    local _lbl _t
    IFS=$'\t' read -r _lbl logo c1 c2 _t < <(_theme_branding "$CTX_INSTANCE")
    [[ -n "$logo" && "${logo:0:1}" != "/" ]] && logo="$CTX_INSTANCE/$logo"
  fi
  [[ -z "$logo" ]] && logo="$BRIDGE_MOTD_DEFAULT_LOGO"   # neutral-mode default (set in override)

  # --pipe false forces colours even when captured via $(...) (a plain --pipe
  # strips all SGR, which is why the logo was never actually coloured before).
  # "none"/empty → monochrome: pass SGR 39 (default fg) to override any logo
  # colour from config.jsonc, so the logo renders in the terminal's own colour.
  [[ -z "$c1" || "$c1" == "none" ]] && c1="39"
  [[ -z "$c2" || "$c2" == "none" ]] && c2="39"
  local args=(--pipe false)
  [[ -f "$logo" ]] && args+=(--logo-type file --logo "$logo" \
                             --logo-color-1 "$c1" --logo-color-2 "$c2")

  local ff_output
  ff_output=$(fastfetch "${args[@]}" 2>/dev/null) || return

  local ff_lines=()
  while IFS= read -r line; do
    ff_lines+=("$line")
  done <<< "$ff_output"

  local total=${#ff_lines[@]}
  for (( i=0; i<total; i++ )); do
    printf '%s\n' "${ff_lines[$i]}"
    if (( SKIP_ANIM )) || check_skip; then
      # Dump remaining lines instantly
      for (( j=i+1; j<total; j++ )); do
        printf '%s\n' "${ff_lines[$j]}"
      done
      break
    fi
    if (( i < 7 )); then
      anim_sleep 0.05
    elif (( i == 7 )); then
      anim_sleep 0.08
    else
      anim_sleep 0.025
    fi
  done
}

# ── Greeting ──────────────────────────────────────────────

greeting() {
  local hour
  hour=$(date +%H)
  if (( 10#$hour >= 5 && 10#$hour < 12 )); then
    echo "Good morning"
  elif (( 10#$hour >= 12 && 10#$hour < 18 )); then
    echo "Good afternoon"
  else
    echo "Good evening"
  fi
}

# ── GitHub Tasks (cached) ────────────────────────────────

fetch_tasks() {
  # Neutral-mode "Active Tasks" box. Org / login / project numbers come from the
  # machine-local override (BRIDGE_GH_*). No config → feature off (clean default).
  [[ -n "$BRIDGE_GH_ORG" && -n "$BRIDGE_GH_LOGIN" && ${#BRIDGE_GH_PROJECTS[@]} -gt 0 ]] || return 0

  # Build the projectV2 fragments from the configured project numbers.
  local frags="" n
  for n in "${BRIDGE_GH_PROJECTS[@]}"; do
    frags+="
      p${n}: projectV2(number: ${n}) {
        title
        items(first: 50) { nodes {
          status: fieldValueByName(name: \"Status\") { ... on ProjectV2ItemFieldSingleSelectValue { name } }
          assignment: fieldValueByName(name: \"Assignment\") { ... on ProjectV2ItemFieldSingleSelectValue { name } }
          content { ... on Issue { number title assignees(first: 5) { nodes { login } } } }
        } }
      }"
  done

  local result
  result=$(gh api graphql -f query="{ organization(login: \"$BRIDGE_GH_ORG\") {$frags } }" 2>/dev/null) || return 1

  echo "$result" | jq -r --arg login "$BRIDGE_GH_LOGIN" '
    [
      .data.organization | to_entries[] |
      .value as $proj |
      .value.items.nodes[] |
      select(.status.name != null) |
      select(.content.number != null) |
      select(.content.assignees.nodes | any(.login == $login)) |
      select(
        .status.name == "🏗 In progress" or
        .status.name == "🏗 In Progress" or
        .status.name == "🔖 Ready for Dev"
      ) |
      (.assignment.name // "") as $asgn |
      {
        line: "\($proj.title)|\(.content.number)|\(.content.title)|\(.status.name)|\($asgn)",
        sort: (
          if ($asgn != "" and ($asgn | test("Accepted") | not)) then -1
          elif (.status.name | test("In [Pp]rogress")) then 0
          else 1 end
        )
      }
    ] | sort_by(.sort) | .[].line
  ' 2>/dev/null
}

update_cache() {
  mkdir -p "$CACHE_DIR"
  local tasks
  tasks=$(fetch_tasks)
  if [[ -n "$tasks" ]]; then
    echo "$tasks" > "$CACHE_FILE"
  fi
}

cache_is_stale() {
  [[ ! -f "$CACHE_FILE" ]] && return 0
  local age
  age=$(( $(date +%s) - $(stat -f %m "$CACHE_FILE" 2>/dev/null || echo 0) ))
  (( age > CACHE_MAX_AGE ))
}

show_tasks() {
  [[ ! -f "$CACHE_FILE" ]] && return

  local lines=()
  while IFS= read -r line; do
    [[ -n "$line" ]] && lines+=("$line")
  done < "$CACHE_FILE"

  local count=${#lines[@]}
  (( count == 0 )) && return

  local term_lines
  term_lines=$(tput lines 2>/dev/null || echo 40)
  local used=25
  local max=$(( term_lines - used ))
  (( max < 3 )) && max=3
  (( max > 7 )) && max=7
  (( count > max )) && count=$max

  local inner=56

  printf "\n  ${DIM}┌─${RESET}"
  printf "${BRAND_PRIMARY}${BOLD} Active Tasks ${RESET}"
  printf "${DIM}"
  draw_hline $(( inner - 15 )) "─" 0.008
  printf "┐${RESET}\n"

  for (( i=0; i<count; i++ )); do
    IFS='|' read -r project num title status assignment <<< "${lines[$i]}"

    local indicator
    if [[ "$project" == *"Operations"* && "$assignment" != *"Accepted"* ]]; then
      indicator="${RED}⚠${RESET}"
    else
      case "$status" in
        *"In progress"*|*"In Progress"*)  indicator="${BRAND_LIGHT}●${RESET}" ;;
        *"Ready for Dev"*)                indicator="${BRAND_ACCENT}◆${RESET}" ;;
        *)                                indicator="${BRAND_SECONDARY}○${RESET}" ;;
      esac
    fi

    title=$(echo "$title" | sed 's/^\[[^]]*\] *//g;s/^[^[:alnum:]]*//;s/^[[:space:]]*//')

    # Short 3-char project tag from the project title.
    local short_proj
    short_proj=$(printf "%3s" "${project:0:3}")

    local usable=$(( inner - 2 ))
    local fixed_part=$(( 1 + 1 + 1 + ${#num} + 2 + 1 + 3 ))
    local max_title=$(( usable - fixed_part ))
    (( max_title < 10 )) && max_title=10

    if (( ${#title} > max_title )); then
      title="${title:0:$(( max_title - 1 ))}…"
    fi

    # UTF-8 multi-byte compensation (macOS printf counts bytes, not chars)
    local byte_len=${#title}
    local real_bytes
    real_bytes=$(printf '%s' "$title" | LC_ALL=C wc -c | tr -d ' ')
    local pad_width=$(( max_title + real_bytes - byte_len ))

    anim_sleep 0.04
    printf "  ${DIM}│${RESET} %b ${DIM}#${RESET}${BOLD}%s${RESET}  %-${pad_width}s ${BRAND_SECONDARY}%s${RESET} ${DIM}│${RESET}\n" \
      "$indicator" "$num" "$title" "$short_proj"
  done

  if (( ${#lines[@]} > max )); then
    local remaining=$(( ${#lines[@]} - max ))
    anim_sleep 0.04
    printf "  ${DIM}│  +%d more%*s│${RESET}\n" "$remaining" $(( inner - 8 - ${#remaining} )) ""
  fi

  anim_sleep 0.04
  printf "  ${DIM}└"
  draw_hline "$inner" "─" 0.006
  printf "┘${RESET}\n"
}

# ── Claude Usage (cached) ───────────────────────────────

fetch_claude_usage() {
  # Token is stored in macOS Keychain (since Claude Code ~1.x, no more .credentials.json)
  local raw
  raw=$(security find-generic-password -s "Claude Code-credentials" -a "$(whoami)" -w 2>/dev/null) || return 1
  local token
  token=$(echo "$raw" | python3 -c "import json,sys; print(json.load(sys.stdin)['claudeAiOauth']['accessToken'])" 2>/dev/null) || return 1
  [[ -z "$token" ]] && return 1

  curl -s --max-time 3 "https://api.anthropic.com/api/oauth/usage" \
    -H "Authorization: Bearer $token" \
    -H "anthropic-beta: oauth-2025-04-20" 2>/dev/null
}

update_claude_cache() {
  mkdir -p "$CACHE_DIR"
  local data
  data=$(fetch_claude_usage)
  if [[ -n "$data" ]] && echo "$data" | jq -e '.seven_day' >/dev/null 2>&1; then
    echo "$data" > "$CLAUDE_CACHE"
  fi
}

claude_cache_is_stale() {
  [[ ! -f "$CLAUDE_CACHE" ]] && return 0
  local age
  age=$(( $(date +%s) - $(stat -f %m "$CLAUDE_CACHE" 2>/dev/null || echo 0) ))
  (( age > CLAUDE_CACHE_MAX_AGE ))
}

show_claude_usage() {
  [[ ! -f "$CLAUDE_CACHE" ]] && return

  local data
  data=$(<"$CLAUDE_CACHE")

  local week_pct five_pct reset_at
  read -r week_pct five_pct reset_at < <(
    echo "$data" | jq -r '[
      (.seven_day.utilization // empty | tostring | split(".")[0]),
      (.five_hour.utilization // empty | tostring | split(".")[0]),
      (.seven_day.resets_at // empty)
    ] | join(" ")' 2>/dev/null
  )

  [[ -z "$week_pct" || "$week_pct" == "null" ]] && return

  # Format reset date
  local reset_str=""
  if [[ -n "$reset_at" ]]; then
    reset_str=$(python3 -c "
from datetime import datetime, timezone
import sys
try:
    dt = datetime.fromisoformat('$reset_at')
    local_dt = dt.astimezone()
    print(f'Resets {local_dt.strftime(\"%b %-d at %-I:%M%p\").replace(\"AM\",\"am\").replace(\"PM\",\"pm\")}')
except:
    pass
" 2>/dev/null)
  fi

  local inner=56

  # Progress bar (week)
  local bar_width=30
  local filled=$(( week_pct * bar_width / 100 ))
  (( filled > bar_width )) && filled=$bar_width
  local empty=$(( bar_width - filled ))

  local bar=""
  local color="$BRAND_PRIMARY"
  if (( week_pct >= 80 )); then
    color="$RED"
  elif (( week_pct >= 50 )); then
    color='\033[38;2;255;165;0m'  # orange
  fi

  printf -v bar '%*s' "$filled" ''; bar=${bar// /█}
  # Half block for fractional part
  local frac=$(( (week_pct * bar_width) % 100 ))
  if (( frac >= 50 && filled < bar_width )); then
    bar+="▌"
    empty=$(( empty - 1 ))
  fi
  printf -v pad_space '%*s' "$empty" ''; bar+="$pad_space"

  printf "\n  ${DIM}┌─${RESET}"
  printf "${BRAND_ACCENT}${BOLD} Claude Usage ${RESET}"
  printf "${DIM}"
  draw_hline $(( inner - 15 )) "─" 0.008
  printf "┐${RESET}\n"

  # Shared label width for alignment
  local lbl_w=9  # "5h window" is longest at 9 chars

  # Week usage line
  local pct_str
  printf -v pct_str "%3d%%" "$week_pct"
  local label
  printf -v label "%-${lbl_w}s" "Weekly"
  local visible_len=$(( lbl_w + 1 + bar_width + 1 + 4 ))
  local pad=$(( inner - 2 - visible_len ))
  (( pad < 0 )) && pad=0

  anim_sleep 0.04
  printf "  ${DIM}│${RESET} ${DIM}%s${RESET} ${color}%s${RESET} ${BOLD}%s${RESET}%*s ${DIM}│${RESET}\n" \
    "$label" "$bar" "$pct_str" "$pad" ""

  # 5h window line
  if [[ -n "$five_pct" && "$five_pct" != "null" ]]; then
    local five_str
    printf -v five_str "%3d%%" "$five_pct"
    local five_label
    printf -v five_label "%-${lbl_w}s" "5h window"
    local five_filled=$(( five_pct * bar_width / 100 ))
    (( five_filled > bar_width )) && five_filled=$bar_width
    local five_empty=$(( bar_width - five_filled ))

    local five_bar=""
    local five_color="$BRAND_PRIMARY"
    if (( five_pct >= 80 )); then
      five_color="$RED"
    elif (( five_pct >= 50 )); then
      five_color='\033[38;2;255;165;0m'
    fi

    printf -v five_bar '%*s' "$five_filled" ''; five_bar=${five_bar// /█}
    local five_frac=$(( (five_pct * bar_width) % 100 ))
    if (( five_frac >= 50 && five_filled < bar_width )); then
      five_bar+="▌"
      five_empty=$(( five_empty - 1 ))
    fi
    printf -v five_pad '%*s' "$five_empty" ''; five_bar+="$five_pad"

    anim_sleep 0.04
    printf "  ${DIM}│${RESET} ${DIM}%s${RESET} ${five_color}%s${RESET} ${BOLD}%s${RESET}%*s ${DIM}│${RESET}\n" \
      "$five_label" "$five_bar" "$five_str" "$pad" ""
  fi

  # Reset date line
  if [[ -n "$reset_str" ]]; then
    local reset_visible=${#reset_str}
    local reset_pad=$(( inner - 2 - reset_visible ))
    (( reset_pad < 0 )) && reset_pad=0
    anim_sleep 0.04
    printf "  ${DIM}│${RESET} ${DIM}%s%*s${RESET} ${DIM}│${RESET}\n" \
      "$reset_str" "$reset_pad" ""
  fi

  anim_sleep 0.04
  printf "  ${DIM}└"
  draw_hline "$inner" "─" 0.006
  printf "┘${RESET}\n"
}

# ── Today's Meetings (cached, icalBuddy) ───────────────

fetch_today_meetings() {
  # Pure Swift EventKit: fetches today's events with calendar source info in one pass
  local raw
  raw=$(swift -e '
import EventKit
import Foundation
let store = EKEventStore()
let cal = Calendar.current
let s = cal.startOfDay(for: Date())
guard let e = cal.date(byAdding: .day, value: 1, to: s) else { exit(0) }
let fmt = DateFormatter(); fmt.dateFormat = "HH:mm"
for ev in store.events(matching: store.predicateForEvents(withStart: s, end: e, calendars: nil))
  .sorted(by: { $0.startDate < $1.startDate }) {
    let t = ev.title ?? ""
    let cn = ev.calendar.title
    let src = ev.calendar.source.title
    print("\(fmt.string(from: ev.startDate))|\(t)|\(cn)|\(src)")
}' 2>/dev/null) || return

  [[ -z "$raw" ]] && return

  # Map each event's calendar+source to a tag via CALENDAR_MAP
  while IFS='|' read -r time title cal_title source_title; do
    [[ -z "$time" ]] && continue
    local tag=""
    for mapping in "${CALENDAR_MAP[@]}"; do
      local map_name="${mapping%%:*}"
      local rest="${mapping#*:}"
      local acct_match="${rest%%:*}"
      local map_tag="${rest##*:}"

      [[ "$cal_title" == "$map_name" ]] || continue
      if [[ -z "$acct_match" ]] || [[ "$source_title" == *"$acct_match"* ]]; then
        tag="$map_tag"
        break
      fi
    done
    [[ -z "$tag" ]] && continue  # Skip calendars not in CALENDAR_MAP
    echo "${time}|${title}|${tag}"
  done <<< "$raw"
}

update_meetings_cache() {
  mkdir -p "$CACHE_DIR"
  fetch_today_meetings > "$MEETINGS_CACHE"
}

meetings_cache_is_stale() {
  [[ ! -f "$MEETINGS_CACHE" ]] && return 0
  local age
  age=$(( $(date +%s) - $(stat -f %m "$MEETINGS_CACHE" 2>/dev/null || echo 0) ))
  (( age > MEETINGS_CACHE_MAX_AGE ))
}

show_today_meetings() {
  [[ ! -f "$MEETINGS_CACHE" ]] && return

  local lines=()
  while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    # Context filter: in instance mode only show this context's calendar tags
    local mtag="${line##*|}"
    if [[ -n "$CTX_MEETING_TAGS" && " $CTX_MEETING_TAGS " != *" $mtag "* ]]; then
      continue
    fi
    lines+=("$line")
  done < "$MEETINGS_CACHE"

  local count=${#lines[@]}
  (( count == 0 )) && return

  local inner=56

  printf "\n  ${DIM}┌─${RESET}"
  printf "${BRAND_PRIMARY}${BOLD} Today ${RESET}"
  printf "${DIM}"
  draw_hline $(( inner - 8 )) "─" 0.008
  printf "┐${RESET}\n"

  for (( i=0; i<count; i++ )); do
    IFS='|' read -r time title tag <<< "${lines[$i]}"

    # Right-aligned tag (like tasks: SS, Ops, AI)
    local short_tag
    printf -v short_tag "%3s" "${tag:-""}"

    # Truncate title to fit box (account for tag column)
    local usable=$(( inner - 2 ))
    local fixed=$(( 2 + 5 + 2 + 1 + 3 ))  # icon + HH:MM + spaces + space + tag
    local max_title=$(( usable - fixed ))
    (( max_title < 10 )) && max_title=10
    (( ${#title} > max_title )) && title="${title:0:$(( max_title - 1 ))}…"

    # UTF-8 multi-byte compensation
    local byte_len=${#title}
    local real_bytes
    real_bytes=$(printf '%s' "$title" | LC_ALL=C wc -c | tr -d ' ')
    local pad_width=$(( max_title + real_bytes - byte_len ))

    anim_sleep 0.04
    printf "  ${DIM}│${RESET} ${BRAND_PRIMARY}◆${RESET} ${BOLD}%s${RESET}  %-${pad_width}s ${BRAND_SECONDARY}%s${RESET} ${DIM}│${RESET}\n" \
      "$time" "$title" "$short_tag"
  done

  anim_sleep 0.04
  printf "  ${DIM}└"
  draw_hline "$inner" "─" 0.006
  printf "┘${RESET}\n"
}

# ── Dirty Repos (cached) ───────────────────────────────

# Emits "org|short|branch|count" for repos with uncommitted changes.
_emit_dirty() {
  local org="$1" path="$2" short="$3"
  [[ -d "$path/.git" ]] || return
  local count branch
  count=$(git -C "$path" status --porcelain 2>/dev/null | wc -l | tr -d ' ')
  (( count > 0 )) || return
  branch=$(git -C "$path" branch --show-current 2>/dev/null)
  echo "${org}|${short}|${branch}|${count}"
}

fetch_dirty_repos() {
  # Curated list (a tree may have too many repos to scan fully)
  local entry
  for entry in "${MONITORED_REPOS[@]}"; do
    _emit_dirty "$BRIDGE_MOTD_CURATED_TREE" "$CURATED_ROOT/${entry%%:*}" "${entry##*:}"
  done
  # Other org trees: glob-scan; org tag = the tree dir name (matches CTX_ORG)
  local tree d
  for tree in "${BRIDGE_MOTD_ORG_TREES[@]}"; do
    for d in "$DEV_ROOT/$tree"/*/; do
      [[ -d "$d/.git" ]] || continue
      _emit_dirty "$tree" "${d%/}" "$(basename "${d%/}")"
    done
  done
}

update_repos_cache() {
  mkdir -p "$CACHE_DIR"
  fetch_dirty_repos > "$REPOS_CACHE"
}

repos_cache_is_stale() {
  [[ ! -f "$REPOS_CACHE" ]] && return 0
  local age
  age=$(( $(date +%s) - $(stat -f %m "$REPOS_CACHE" 2>/dev/null || echo 0) ))
  (( age > REPOS_CACHE_MAX_AGE ))
}

show_dirty_repos() {
  [[ ! -f "$REPOS_CACHE" ]] && return
  local filter="$1"   # org key to keep ("" = all)

  local lines=()
  while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    local org="${line%%|*}"
    [[ -z "$filter" || "$org" == "$filter" ]] && lines+=("$line")
  done < "$REPOS_CACHE"

  local count=${#lines[@]}
  (( count == 0 )) && return

  local inner=56

  printf "\n  ${DIM}┌─${RESET}"
  printf "${BRAND_LIGHT}${BOLD} Uncommitted Work ${RESET}"
  printf "${DIM}"
  draw_hline $(( inner - 19 )) "─" 0.008
  printf "┐${RESET}\n"

  for (( i=0; i<count; i++ )); do
    IFS='|' read -r org repo branch filecount <<< "${lines[$i]}"

    local files_str="${filecount} file"
    (( filecount > 1 )) && files_str+="s"

    # Truncate repo (glob-derived names can be long) + branch to keep box aligned
    (( ${#repo} > 13 ))   && repo="${repo:0:12}…"
    (( ${#branch} > 20 )) && branch="${branch:0:19}…"

    # Padding: fill space between branch and files_str
    local usable=$(( inner - 2 ))
    local content_len=$(( 1 + 1 + 13 + 2 + ${#branch} + 2 + ${#files_str} ))
    local pad=$(( usable - content_len ))
    (( pad < 0 )) && pad=0

    anim_sleep 0.04
    printf "  ${DIM}│${RESET} ${RED}⚠${RESET} ${BOLD}%-13s${RESET}  ${DIM}%s${RESET}%*s  ${BRAND_LIGHT}%s${RESET} ${DIM}│${RESET}\n" \
      "$repo" "$branch" "$pad" "" "$files_str"
  done

  anim_sleep 0.04
  printf "  ${DIM}└"
  draw_hline "$inner" "─" 0.006
  printf "┘${RESET}\n"
}

# ── Open PRs (cached) ──────────────────────────────────

fetch_open_prs() {
  gh api graphql -f query='{
    viewer {
      pullRequests(first: 10, states: OPEN, orderBy: {field: UPDATED_AT, direction: DESC}) {
        nodes {
          number
          title
          repository { name }
          isDraft
        }
      }
    }
  }' --jq '.data.viewer.pullRequests.nodes[] | "\(.repository.name)|\(.number)|\(.title)|\(.isDraft)"' 2>/dev/null
}

update_prs_cache() {
  mkdir -p "$CACHE_DIR"
  fetch_open_prs > "$PRS_CACHE"
}

prs_cache_is_stale() {
  [[ ! -f "$PRS_CACHE" ]] && return 0
  local age
  age=$(( $(date +%s) - $(stat -f %m "$PRS_CACHE" 2>/dev/null || echo 0) ))
  (( age > PRS_CACHE_MAX_AGE ))
}

show_open_prs() {
  [[ ! -f "$PRS_CACHE" ]] && return

  local lines=()
  while IFS= read -r line; do
    [[ -n "$line" ]] && lines+=("$line")
  done < "$PRS_CACHE"

  local count=${#lines[@]}
  (( count == 0 )) && return

  local inner=56

  printf "\n  ${DIM}┌─${RESET}"
  printf "${BRAND_ACCENT}${BOLD} Open PRs ${RESET}"
  printf "${DIM}"
  draw_hline $(( inner - 11 )) "─" 0.008
  printf "┐${RESET}\n"

  for (( i=0; i<count; i++ )); do
    IFS='|' read -r repo num title is_draft <<< "${lines[$i]}"

    local indicator="${BRAND_LIGHT}●${RESET}"
    [[ "$is_draft" == "true" ]] && indicator="${DIM}◇${RESET}"

    # Map to short repo name via MONITORED_REPOS
    local short_repo="$repo"
    for entry in "${MONITORED_REPOS[@]}"; do
      [[ "$repo" == "${entry%%:*}" ]] && { short_repo="${entry##*:}"; break; }
    done
    (( ${#short_repo} > 13 )) && short_repo="${short_repo:0:12}…"

    # Compute available title space (same approach as tasks box)
    local usable=$(( inner - 2 ))
    local fixed=$(( 1 + 1 + 13 + 1 + 1 + ${#num} + 2 ))
    local max_title=$(( usable - fixed ))
    (( max_title < 10 )) && max_title=10
    (( ${#title} > max_title )) && title="${title:0:$(( max_title - 1 ))}…"

    # UTF-8 multi-byte compensation
    local byte_len=${#title}
    local real_bytes
    real_bytes=$(printf '%s' "$title" | LC_ALL=C wc -c | tr -d ' ')
    local pad_width=$(( max_title + real_bytes - byte_len ))

    anim_sleep 0.04
    printf "  ${DIM}│${RESET} %b %-13s ${DIM}#${RESET}${BOLD}%s${RESET}  %-${pad_width}s ${DIM}│${RESET}\n" \
      "$indicator" "$short_repo" "$num" "$title"
  done

  anim_sleep 0.04
  printf "  ${DIM}└"
  draw_hline "$inner" "─" 0.006
  printf "┘${RESET}\n"
}

# ── Notifications (cached) ─────────────────────────────

fetch_notifications() {
  gh api notifications --jq 'length' 2>/dev/null
}

update_notif_cache() {
  mkdir -p "$CACHE_DIR"
  local count
  count=$(fetch_notifications)
  [[ -n "$count" ]] && echo "$count" > "$NOTIF_CACHE"
}

notif_cache_is_stale() {
  [[ ! -f "$NOTIF_CACHE" ]] && return 0
  local age
  age=$(( $(date +%s) - $(stat -f %m "$NOTIF_CACHE" 2>/dev/null || echo 0) ))
  (( age > NOTIF_CACHE_MAX_AGE ))
}

# ── Commit Streak (cached) ─────────────────────────────

fetch_streak() {
  local all_dates
  all_dates=$( {
    for entry in "${MONITORED_REPOS[@]}"; do
      path="$CURATED_ROOT/${entry%%:*}"
      [[ -d "$path/.git" ]] && git -C "$path" log --all --format='%ad' --date=short --since="90 days ago" 2>/dev/null
    done
    local tree d
    for tree in "${BRIDGE_MOTD_ORG_TREES[@]}"; do
      for d in "$DEV_ROOT/$tree"/*/; do
        [[ -d "$d/.git" ]] && git -C "$d" log --all --format='%ad' --date=short --since="90 days ago" 2>/dev/null
      done
    done
  } | sort -u -r)

  local streak=0
  local expected
  expected=$(date +%Y-%m-%d)

  while IFS= read -r d; do
    [[ -z "$d" ]] && continue
    if [[ "$d" == "$expected" ]]; then
      (( streak++ ))
      expected=$(date -v-1d -j -f "%Y-%m-%d" "$expected" +%Y-%m-%d 2>/dev/null)
    elif (( streak == 0 )) && [[ "$d" == $(date -v-1d +%Y-%m-%d) ]]; then
      # Grace: no commits today yet, start counting from yesterday
      expected="$d"
      (( streak++ ))
      expected=$(date -v-1d -j -f "%Y-%m-%d" "$expected" +%Y-%m-%d 2>/dev/null)
    else
      break
    fi
  done <<< "$all_dates"

  echo "$streak"
}

update_streak_cache() {
  mkdir -p "$CACHE_DIR"
  local count
  count=$(fetch_streak)
  [[ -n "$count" ]] && echo "$count" > "$STREAK_CACHE"
}

streak_cache_is_stale() {
  [[ ! -f "$STREAK_CACHE" ]] && return 0
  local age
  age=$(( $(date +%s) - $(stat -f %m "$STREAK_CACHE" 2>/dev/null || echo 0) ))
  (( age > STREAK_CACHE_MAX_AGE ))
}

# ── Battery (live, ~11ms) ──────────────────────────────

get_battery_pct() {
  pmset -g batt 2>/dev/null | grep -o '[0-9]*%' | tr -d '%'
}

# ── Greeting line + inline badges (shared by both modes) ─

print_greeting_line() {
  local greet
  greet=$(greeting)
  printf "  ${BRAND_PRIMARY}⚡${RESET} "
  type_text "${greet}${BRIDGE_MOTD_USER_NAME:+, $BRIDGE_MOTD_USER_NAME}." 0.04

  local badges=""
  local streak=0
  [[ -f "$STREAK_CACHE" ]] && streak=$(<"$STREAK_CACHE")
  (( streak > 1 )) && badges+="  ${BRAND_LIGHT}🔥 ${streak}d${RESET}"

  local notif=0
  [[ -f "$NOTIF_CACHE" ]] && notif=$(<"$NOTIF_CACHE")
  (( notif > 0 )) && badges+="  ${BRAND_ACCENT}🔔 ${notif}${RESET}"

  local batt
  batt=$(get_battery_pct)
  if [[ -n "$batt" ]] && (( batt <= 20 )); then
    badges+="  ${RED}🪫 ${batt}%${RESET}"
  fi

  [[ -n "$badges" ]] && printf "%b" "$badges"
  printf "\n"
}

# ── Instance context header + current-repo git status ───

show_context_header() {
  # Accent from the instance branding (CTX_COLOR); neutral when monochrome/unset.
  local color="$DIM"
  [[ -n "$CTX_COLOR" && "$CTX_COLOR" != "none" ]] && color="\033[${CTX_COLOR}m"

  local inst_branch=""
  [[ -d "$CTX_INSTANCE/.git" ]] && inst_branch=$(git -C "$CTX_INSTANCE" branch --show-current 2>/dev/null)

  printf "  ${color}▸${RESET} ${BOLD}%s${RESET}" "$CTX_LABEL"
  [[ -n "$CTX_INSTANCE" ]] && printf " ${DIM}·${RESET} ${DIM}%s${RESET}" "$(basename "$CTX_INSTANCE")"
  [[ -n "$inst_branch" ]]  && printf " ${DIM}·${RESET} ${DIM}%s${RESET}" "$inst_branch"
  printf "\n"

  # Current-repo git status (only if cwd is inside a git repo)
  git -C "$PWD" rev-parse --git-dir >/dev/null 2>&1 || return
  local repo branch dirty ab behind ahead last ago
  repo=$(basename "$(git -C "$PWD" rev-parse --show-toplevel 2>/dev/null)")
  branch=$(git -C "$PWD" branch --show-current 2>/dev/null)
  dirty=$(git -C "$PWD" status --porcelain 2>/dev/null | wc -l | tr -d ' ')
  ab=$(git -C "$PWD" rev-list --left-right --count '@{u}...HEAD' 2>/dev/null)
  behind=$(awk '{print $1}' <<< "$ab")
  ahead=$(awk '{print $2}' <<< "$ab")
  last=$(git -C "$PWD" log -1 --format='%s' 2>/dev/null)
  ago=$(git -C "$PWD" log -1 --format='%cr' 2>/dev/null)

  printf "    ${color}%s${RESET} ${DIM}%s${RESET}" "$repo" "$branch"
  [[ -n "$ahead"  && "$ahead"  != "0" ]] && printf " ${BRAND_LIGHT}↑%s${RESET}" "$ahead"
  [[ -n "$behind" && "$behind" != "0" ]] && printf " ${BRAND_ACCENT}↓%s${RESET}" "$behind"
  (( dirty > 0 )) && printf " ${RED}±%s${RESET}" "$dirty"
  printf "\n"

  if [[ -n "$last" ]]; then
    local maxl=44
    (( ${#last} > maxl )) && last="${last:0:$(( maxl - 1 ))}…"
    printf "    ${DIM}⟳ %s (%s)${RESET}\n" "$last" "$ago"
  fi
}

# ── Instance Tasks (live from the instance's board.md "Doing") ──

# Prints one ticket-title per line from the "## Doing" table of a board.md.
parse_board_doing() {
  local board="$1" flt="$2"
  [[ -f "$board" ]] || return
  awk -F'|' -v flt="$flt" '
    /^## Doing/ { f=1; next }
    f && /^## /  { exit }
    f && /^\|/ {
      t=$2; gsub(/^[ \t]+|[ \t]+$/,"",t)
      if (t=="Ticket" || t ~ /^[- ]+$/ || t=="") next
      if (flt!="" && tolower($0) !~ tolower(flt)) next
      print t
    }
  ' "$board"
}

show_instance_tasks() {
  local board="$CTX_INSTANCE/work/board.md"
  [[ -f "$board" ]] || return

  local lines=()
  while IFS= read -r t; do
    [[ -n "$t" ]] && lines+=("$t")
  done < <(parse_board_doing "$board" "$CTX_TASK_FILTER")

  local total=${#lines[@]}
  (( total == 0 )) && return

  local max=6 count=$total
  (( count > max )) && count=$max

  local inner=56
  local lbl=" Doing — ${CTX_LABEL} "
  local lblw
  lblw=$(printf '%s' "$lbl" | wc -m | tr -d ' ')

  printf "\n  ${DIM}┌─${RESET}${BRAND_PRIMARY}${BOLD}%s${RESET}${DIM}" "$lbl"
  draw_hline $(( inner - 1 - lblw )) "─" 0.008
  printf "┐${RESET}\n"

  for (( i=0; i<count; i++ )); do
    local t="${lines[$i]}"
    # Strip markdown link "[text](url)" → "text", trim
    t=$(printf '%s' "$t" | sed 's/\[\([^]]*\)\]([^)]*)/\1/g; s/^[[:space:]]*//; s/[[:space:]]*$//')

    local usable=$(( inner - 2 ))
    local fixed=3                       # "● " + leading space
    local max_title=$(( usable - fixed ))
    (( max_title < 10 )) && max_title=10
    (( ${#t} > max_title )) && t="${t:0:$(( max_title - 1 ))}…"

    # UTF-8 multi-byte compensation (macOS printf pads by bytes)
    local byte_len=${#t} real_bytes
    real_bytes=$(printf '%s' "$t" | LC_ALL=C wc -c | tr -d ' ')
    local pad_width=$(( max_title + real_bytes - byte_len ))

    anim_sleep 0.04
    printf "  ${DIM}│${RESET} ${BRAND_LIGHT}●${RESET} %-${pad_width}s ${DIM}│${RESET}\n" "$t"
  done

  if (( total > max )); then
    local rem=$(( total - max ))
    anim_sleep 0.04
    printf "  ${DIM}│  +%d more%*s│${RESET}\n" "$rem" $(( inner - 8 - ${#rem} )) ""
  fi

  anim_sleep 0.04
  printf "  ${DIM}└"
  draw_hline "$inner" "─" 0.006
  printf "┘${RESET}\n"
}

# ── Main ─────────────────────────────────────────────────

main() {
  mkdir -p "$CACHE_DIR"
  resolve_context              # Decide neutral vs instance from $PWD

  if [[ "$CTX_MODE" == "instance" ]]; then
    # ── Focused panel: opened inside a project/org tree ──
    SKIP_ANIM=1                # Render instantly — no animation in focus mode
    show_fastfetch             # logo + system info (instant, no cascade)
    echo ""
    print_greeting_line        # Greeting + global badges (streak/notif/batt)
    printf "\n"
    show_context_header        # Instance + current-repo git status
    show_today_meetings        # Meetings filtered to this context's tags
    show_claude_usage          # Claude usage is global — always useful
    show_instance_tasks        # "Doing" board of the matching Bridge instance
    show_dirty_repos "$CTX_ORG"  # Uncommitted work in this org tree only
  else
    # ── Full dashboard: home / unknown dir (unchanged behavior) ──
    tput civis 2>/dev/null     # Hide cursor during animation
    start_keypress_listener    # Any keypress skips remaining animations
    show_fastfetch             # Phase 1: Cascading system info
    echo ""
    print_greeting_line        # Phase 2: Greeting with badges
    show_today_meetings        # Phase 3: Today's meetings (all calendars)
    show_claude_usage          # Phase 4: Claude usage bar
    show_tasks                 # Phase 4: Active GitHub-assigned tasks
    show_dirty_repos ""        # Phase 5: Uncommitted work (all org trees)
    show_open_prs              # Phase 6: Open PRs
    stop_keypress_listener     # Clean up listener
    tput cnorm 2>/dev/null     # Restore cursor
  fi

  # Background refresh stale caches (nohup to survive terminal close)
  # Lock prevents parallel updates; 60s cooldown between attempts
  local lock="$CACHE_DIR/.update.lock"
  if [[ ! -f "$lock" ]] || (( $(date +%s) - $(stat -f %m "$lock" 2>/dev/null || echo 0) > 60 )); then
    if cache_is_stale || claude_cache_is_stale || repos_cache_is_stale || \
       prs_cache_is_stale || notif_cache_is_stale || streak_cache_is_stale || \
       meetings_cache_is_stale; then
      touch "$lock"
      local script_path
      script_path="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)/$(basename "${BASH_SOURCE[0]:-$0}")"
      nohup bash "$script_path" --update >/dev/null 2>&1 &
      disown 2>/dev/null
    fi
  fi
}

if [[ "$1" == "--update" ]]; then
  update_cache
  update_claude_cache
  update_meetings_cache
  update_repos_cache
  update_prs_cache
  update_notif_cache
  update_streak_cache
  rm -f "$CACHE_DIR/.update.lock"
  exit 0
fi

main
