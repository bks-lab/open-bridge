#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# Claude Code Stop hook entry point, wired in the tracked .claude/settings.json.
# The check lives in scripts/worklog-drift-check.sh, shared with the Codex and
# Mistral Vibe hooks; this path stays so no instance has to edit its settings.
set -eu
root="$(cd "$(dirname "$0")/../.." && pwd)"
check="$root/scripts/worklog-drift-check.sh"
if [ ! -f "$check" ]; then
  echo "worklog-drift-check: $check is missing, so the Stop hook cannot run." >&2
  exit 1
fi
exec bash "$check"
