#!/usr/bin/env bash
set -euo pipefail

# fetch-project-tasks.sh - Parallel GitHub Project task fetcher
# Usage: ./fetch-project-tasks.sh [--owner ORG] PROJECT_NUM [PROJECT_NUM ...]
#
# Reads project config from projects/*.yaml via the Bridge Project Registry.
# Falls back to CLI args if no config found.

OWNER=""
PROJECTS=()
TMPDIR=$(mktemp -d)
trap 'rm -rf "$TMPDIR"' EXIT

# --- Prerequisites ---
for cmd in gh jq; do
  if ! command -v "$cmd" &>/dev/null; then
    echo "{\"error\": \"Required command '$cmd' not found. Please install it.\"}" >&2
    exit 1
  fi
done

if ! gh auth status &>/dev/null 2>&1; then
  echo '{"error": "Not authenticated with GitHub. Run: gh auth login"}' >&2
  exit 1
fi

# --- Argument Parsing ---
while [[ $# -gt 0 ]]; do
  case "$1" in
    --owner) OWNER="$2"; shift 2 ;;
    --help|-h)
      echo "Usage: fetch-project-tasks.sh [--owner ORG] PROJECT_NUM [PROJECT_NUM ...]" >&2
      echo "  --owner  GitHub org/user (auto-detected from projects/*.yaml if omitted)" >&2
      exit 0
      ;;
    *) PROJECTS+=("$1"); shift ;;
  esac
done

if [[ ${#PROJECTS[@]} -eq 0 ]]; then
  echo '{"error": "No project numbers provided. Usage: fetch-project-tasks.sh [--owner ORG] NUM [NUM ...]"}' >&2
  exit 1
fi

# --- Auto-detect owner from project config if not specified ---
if [[ -z "$OWNER" ]]; then
  # Try to find owner from first project's config
  BRIDGE_ROOT="$(git rev-parse --show-toplevel 2>/dev/null || echo '.')"
  # C-prime: project configs are flat at workflow/projects/<slug>.yaml.
  # Fallback to legacy projects/*.yaml for instances that haven't migrated.
  for cfg in "$BRIDGE_ROOT"/workflow/projects/*.yaml "$BRIDGE_ROOT"/projects/*.yaml; do
    if [[ -f "$cfg" ]] && command -v yq &>/dev/null; then
      cfg_num=$(yq -r '.project.number // empty' "$cfg" 2>/dev/null)
      if [[ "$cfg_num" == "${PROJECTS[0]}" ]]; then
        OWNER=$(yq -r '.project.org // empty' "$cfg" 2>/dev/null)
        break
      fi
    fi
  done
  OWNER="${OWNER:-your-org}"  # Final fallback — set OWNER env or .env to override
fi

# --- Fetch project list for names ---
gh project list --owner "$OWNER" --format json --limit 100 \
  2>/dev/null > "$TMPDIR/projects-list.json" || \
  echo '{"projects":[]}' > "$TMPDIR/projects-list.json"

# --- Parallel fetch items ---
TIMEOUT_CMD=""
if command -v gtimeout &>/dev/null; then
  TIMEOUT_CMD="gtimeout 15"
elif command -v timeout &>/dev/null; then
  TIMEOUT_CMD="timeout 15"
fi

for proj in "${PROJECTS[@]}"; do
  (
    $TIMEOUT_CMD gh project item-list "$proj" \
      --owner "$OWNER" \
      --format json \
      --limit 200 \
      2>/dev/null > "$TMPDIR/project-${proj}.json" || \
      echo '{"items":[],"totalCount":0}' > "$TMPDIR/project-${proj}.json"
  ) &
done
wait

# --- Process each project ---
for proj in "${PROJECTS[@]}"; do
  proj_name=$(jq -r --arg num "$proj" \
    '.projects[] | select(.number == ($num | tonumber)) | .title // empty' \
    "$TMPDIR/projects-list.json" 2>/dev/null) || true
  proj_name="${proj_name:-Project #${proj}}"

  jq --arg num "$proj" --arg name "$proj_name" '
    def strip_emoji:
      if . == null then "Unknown"
      else gsub("^[\\p{So}\\p{Sk}\\p{Sc}\\p{Sm}\\s]+"; "") | gsub("^\\s+"; "")
      end;

    def status_order:
      if . == null then 99
      elif test("[Ii]n [Pp]rogress") then 1
      elif test("[Ii]n [Rr]eview|Review") then 2
      elif test("[Rr]eady") then 3
      elif test("[Nn]ew") then 4
      elif test("[Bb]acklog") then 5
      else 6 end;

    (.items // []) |
    map(select(
      (.status // "" | test("Done|Declined") | not)
    )) |
    sort_by(.status // "" | status_order) |
    . as $filtered |
    {
      number: ($num | tonumber),
      name: $name,
      items: [$filtered[] | {
        id: (if .content.number then (.content.number | tostring) else .id end),
        title: .title,
        status: (.status | strip_emoji),
        priority: (.priority // "Unknown" | strip_emoji),
        assignee: (if (.assignees | length) > 0 then .assignees[0] else null end),
        type: (
          if .["item Type"] then (.["item Type"] | strip_emoji)
          elif .content.type then .content.type
          else "Unknown"
          end
        ),
        url: (.content.url // null)
      }],
      stats: {
        total: ($filtered | length),
        in_progress: ([$filtered[] | select(.status // "" | test("[Pp]rogress"))] | length),
        in_review: ([$filtered[] | select(.status // "" | test("[Rr]eview"))] | length),
        ready: ([$filtered[] | select(.status // "" | test("[Rr]eady"))] | length),
        new: ([$filtered[] | select(.status // "" | test("New"))] | length),
        backlog: ([$filtered[] | select(.status // "" | test("[Bb]acklog"))] | length)
      }
    }
  ' "$TMPDIR/project-${proj}.json" > "$TMPDIR/result-${proj}.json"
done

# --- Combine results ---
RESULT_FILES=()
for proj in "${PROJECTS[@]}"; do
  RESULT_FILES+=("$TMPDIR/result-${proj}.json")
done

jq -n --arg ts "$(date -u +%Y-%m-%dT%H:%M:%SZ)" \
  '{projects: [inputs], timestamp: $ts}' \
  "${RESULT_FILES[@]}"
