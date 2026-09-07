#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# install-upstream-autoupdate.sh — self-locating installer for the daily guarded
# auto-update LaunchAgent. Binds to WHEREVER the repo currently is (no hardcoded
# path — re-run after moving the repo to rebind), generates + loads the job, and
# VERIFIES it actually runs in the launchd context instead of assuming it does.
#
# Env: UPSTREAM_REF (default upstream/main) · AUTOUPDATE_HOUR/MIN (default 7:00)
#      SIGNAL_ACCOUNT + SIGNAL_RECIPIENT (both → the job sends a Signal summary)
set -euo pipefail
REPO="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
LABEL="com.openbridge.upstream-autoupdate"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
HOUR="${AUTOUPDATE_HOUR:-7}"; MIN="${AUTOUPDATE_MIN:-0}"
UID_="$(id -u)"

# --- TCC-protection preflight (the launchd-can't-read-~/Documents trap) ---
case "$REPO/" in
  "$HOME/Documents/"*|"$HOME/Desktop/"*|"$HOME/Downloads/"*)
    echo "⚠ WARNING: repo is under a TCC-protected folder:"
    echo "    $REPO"
    echo "  A LaunchAgent will likely be DENIED access (Operation not permitted)."
    echo "  Fix: move the repo to a non-protected path (e.g. ~/Developer/…) and re-run,"
    echo "  or grant this job's runner Full Disk Access. Continuing, but verify below." ;;
  *) echo "✓ repo is in a non-protected location: $REPO" ;;
esac

launchctl bootout "gui/$UID_/$LABEL" 2>/dev/null || true

sig=""
[ -n "${SIGNAL_ACCOUNT:-}" ]   && sig="$sig    <key>SIGNAL_ACCOUNT</key><string>${SIGNAL_ACCOUNT}</string>
"
[ -n "${SIGNAL_RECIPIENT:-}" ] && sig="$sig    <key>SIGNAL_RECIPIENT</key><string>${SIGNAL_RECIPIENT}</string>
"

cat > "$PLIST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>/bin/bash</string><string>$REPO/scripts/upstream-autoupdate.sh</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO</string>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>UPSTREAM_REF</key><string>${UPSTREAM_REF:-upstream/main}</string>
$sig  </dict>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>$HOUR</integer><key>Minute</key><integer>$MIN</integer></dict>
  <key>StandardOutPath</key><string>$REPO/work/upstream-autoupdate.launchd.out</string>
  <key>StandardErrorPath</key><string>$REPO/work/upstream-autoupdate.launchd.err</string>
  <key>RunAtLoad</key><false/>
</dict></plist>
PLIST

launchctl bootstrap "gui/$UID_" "$PLIST"
printf 'installed + loaded: %s @ %02d:%02d daily → %s\n' "$LABEL" "$HOUR" "$MIN" "$REPO"

# --- VERIFY in the real launchd context (do not assume) ---
echo "verifying (launchctl kickstart)…"
: > "$REPO/work/upstream-autoupdate.launchd.err" 2>/dev/null || true
launchctl kickstart -k "gui/$UID_/$LABEL"
sleep 5
err="$REPO/work/upstream-autoupdate.launchd.err"
if grep -qiE 'not permitted|operation not permitted' "$err" 2>/dev/null; then
  echo "✗ VERIFY FAILED — TCC/permission denied in launchd context:"; tail -3 "$err"; exit 1
elif [ -s "$REPO/work/upstream-status.md" ]; then
  echo "✓ VERIFIED — job executed in launchd context and wrote its report:"
  grep -m2 '^-' "$REPO/work/upstream-status.md" | sed 's/^/    /'
else
  echo "✗ VERIFY INCONCLUSIVE — no report written; launchd err:"; tail -3 "$err" 2>/dev/null; exit 1
fi
