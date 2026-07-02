#!/usr/bin/env bash
# voiceprint_backup.sh — weekly backup of the per-context speaker voiceprints
# (speaker-library/*.npy) from the worker host into the Bridge repo under
# identity/voiceprints/<ctx>/. Driven by com.openbridge.voiceprint-backup
# (launchd, weekly) on the machine where the Bridge repo lives. Pull-only: it
# refreshes the working tree; the .npy are git-tracked (whitelisted) so a later
# commit + your backup pipeline carry them offsite. Idempotent — a no-drift
# week pulls 0 files.
set -uo pipefail

# Repo root: BRIDGE_ROOT env wins; otherwise resolve from this script's
# location (works when run from the repo checkout; a copy deployed to ~/bin
# needs BRIDGE_ROOT set — the launchd plist provides it).
BRIDGE="${BRIDGE_ROOT:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)}"
LOG="$HOME/Library/Logs/voiceprint-backup.log"
ts() { date '+%Y-%m-%dT%H:%M:%S'; }

cd "$BRIDGE" 2>/dev/null || { echo "$(ts) FATAL: no bridge at $BRIDGE" >>"$LOG"; exit 1; }
[[ -f skills/meeting-transcription/scripts/debrief_sync.sh ]] \
  || { echo "$(ts) FATAL: $BRIDGE is not a Bridge repo (debrief_sync.sh missing) — set BRIDGE_ROOT" >>"$LOG"; exit 1; }
echo "$(ts) voiceprint pull start (bridge=$BRIDGE)" >>"$LOG"
skills/meeting-transcription/scripts/debrief_sync.sh voiceprints pull >>"$LOG" 2>&1
rc=$?
echo "$(ts) voiceprint pull done (rc=$rc)" >>"$LOG"
exit "$rc"
