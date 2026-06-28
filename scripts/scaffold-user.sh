#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# scaffold-user.sh
#
# Idempotently materializes the USER work structure of a Bridge instance.
#
# Background: open-bridge uses a directory-based scope model
# (core / org / user). CORE files (skills, templates, schemas, docs)
# ship with the repo; USER areas are personal and empty on a fresh
# clone (e.g. open-bridge, which carries only CORE templates).
# During onboarding this script lays down the (possibly empty) USER
# structure — ONLY directories + `.gitkeep`, NEVER instance data/PII/`.yaml`.
#
# "Idempotent" means: only create what is missing, never overwrite, and
# report at the end what was created vs. already present.
#
# Usage:
#   ./scripts/scaffold-user.sh            # create missing structure
#   ./scripts/scaffold-user.sh --dry-run  # only show what it would do
#   ./scripts/scaffold-user.sh -n         # short form of --dry-run

set -euo pipefail

# ---------------------------------------------------------------------------
# Flags
# ---------------------------------------------------------------------------
DRY_RUN=0
for arg in "$@"; do
  case "$arg" in
    --dry-run|-n) DRY_RUN=1 ;;
    -h|--help)
      grep '^#' "$0" | sed 's/^# \{0,1\}//'
      exit 0
      ;;
    *)
      echo "scaffold-user.sh: unknown argument '$arg' (allowed: --dry-run, -n, --help)" >&2
      exit 2
      ;;
  esac
done

# ---------------------------------------------------------------------------
# Resolve the repo root robustly: git first, then fall back to the script
# dir (scripts/ sits one level below the repo root).
# ---------------------------------------------------------------------------
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
if REPO_ROOT="$(git -C "$SCRIPT_DIR" rev-parse --show-toplevel 2>/dev/null)"; then
  :
else
  REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
fi
cd "$REPO_ROOT"

# ---------------------------------------------------------------------------
# What gets created.
#
#  GITKEEP_DIRS  — USER work dirs materialized with a `.gitkeep` (empty on a
#                  fresh clone, but they must exist).
#  MKDIR_DIRS    — cluster-wrapper instance dirs. These normally already carry
#                  `_template.yaml` / `_schema.yaml`. Here ONLY `mkdir -p` if
#                  missing — NO `.gitkeep`, NO yaml.
# ---------------------------------------------------------------------------
# NOTE: `rules/org/` (the optional org-overlay tier) is intentionally NOT
# scaffolded — it only exists if you run an org overlay repo. Create it
# manually (or let your overlay ship it) when you adopt that convention.
GITKEEP_DIRS=(
  work/tasks
  work/streams
  work/done
  work/archive
  work/drafts
  work/imports
  rules/user
  protocols/standing-orders
)

MKDIR_DIRS=(
  identity/personas
  identity/mandants
  identity/accounts
  infra/remotes
  infra/channels
  infra/backups
  workflow/contexts
  workflow/projects
  workflow/calendars
  .bridge                # org-overlay sparse cache root (gitignored, scope: user)
  .bridge/overlays       # one .bridge/overlays/<name>/ per applied overlay
)

# ---------------------------------------------------------------------------
# Counters + helpers
# ---------------------------------------------------------------------------
CREATED=0
EXISTING=0

prefix() { [[ "$DRY_RUN" -eq 1 ]] && printf '[dry-run] ' || printf ''; }

# ensure_dir <path> — create the directory if missing, count it.
ensure_dir() {
  local dir="$1"
  if [[ -d "$dir" ]]; then
    EXISTING=$((EXISTING + 1))
    return
  fi
  echo "$(prefix)mkdir  $dir/"
  [[ "$DRY_RUN" -eq 1 ]] || mkdir -p "$dir"
  CREATED=$((CREATED + 1))
}

# ensure_gitkeep <path> — ensure dir + `.gitkeep` inside it.
# Dir and `.gitkeep` are each counted individually (structure granularity in the report).
ensure_gitkeep() {
  local dir="$1"
  local keep="$dir/.gitkeep"

  if [[ -d "$dir" ]]; then
    EXISTING=$((EXISTING + 1))
  else
    echo "$(prefix)mkdir  $dir/"
    [[ "$DRY_RUN" -eq 1 ]] || mkdir -p "$dir"
    CREATED=$((CREATED + 1))
  fi

  if [[ -e "$keep" ]]; then
    EXISTING=$((EXISTING + 1))
  else
    echo "$(prefix)touch  $keep"
    [[ "$DRY_RUN" -eq 1 ]] || : > "$keep"
    CREATED=$((CREATED + 1))
  fi
}

# ---------------------------------------------------------------------------
# Run
# ---------------------------------------------------------------------------
echo "scaffold-user.sh — USER structure in $REPO_ROOT"
[[ "$DRY_RUN" -eq 1 ]] && echo "(dry-run: nothing is written)"
echo

for d in "${GITKEEP_DIRS[@]}"; do
  ensure_gitkeep "$d"
done

for d in "${MKDIR_DIRS[@]}"; do
  ensure_dir "$d"
done

# ---------------------------------------------------------------------------
# Final summary
# ---------------------------------------------------------------------------
echo
if [[ "$DRY_RUN" -eq 1 ]]; then
  echo "Summary (dry-run): would create: $CREATED · already present: $EXISTING"
else
  echo "Summary: created: $CREATED · already present: $EXISTING"
fi
