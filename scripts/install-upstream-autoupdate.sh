#!/usr/bin/env bash
# SPDX-License-Identifier: MIT
# install-upstream-autoupdate.sh — self-locating installer for the daily guarded
# auto-update LaunchAgent. Binds to WHEREVER the repo currently is (no hardcoded
# path — re-run after moving the repo to rebind), generates + loads the job, and
# VERIFIES it actually runs in the launchd context instead of assuming it does.
#
# Two jobs, one installer:
#   (default)    CORE: scripts/upstream-autoupdate.sh      daily 07:00
#   --overlays   org overlays: scripts/overlay-autosync.sh daily 07:15, after
#                the CORE merge. It honours each overlay's pull_interval_days
#                itself, so a daily schedule is correct for any interval.
#   --print      render the plist to stdout and stop: nothing written, nothing
#                loaded (what the tests use; also a dry look before installing)
#
# Env: UPSTREAM_REF (default upstream/main) · AUTOUPDATE_HOUR/MIN (default 7:00)
#      OVERLAY_AUTOSYNC_HOUR/MIN (default 7:15)
#      SIGNAL_ACCOUNT + SIGNAL_RECIPIENT (both → the job sends a Signal summary)
#      AUTOUPDATE_NOTIFY_CMD (argv string, gets the summary on stdin; any notifier)
set -euo pipefail
REPO="$(git -C "$(dirname "$0")" rev-parse --show-toplevel)"
JOB=core; PRINT=0
for arg in "$@"; do
  case "$arg" in
    --overlays) JOB=overlays ;;
    --print)    PRINT=1 ;;
    -h|--help)  sed -n '3,20p' "$0"; exit 0 ;;
    *) echo "unknown argument: $arg (see --help)" >&2; exit 64 ;;
  esac
done
if [ "$JOB" = overlays ]; then
  LABEL="com.openbridge.overlay-autosync"
  SCRIPT="scripts/overlay-autosync.sh"
  STEM="overlay-autosync"
  REPORT="work/overlay-status.md"
  HOUR="${OVERLAY_AUTOSYNC_HOUR:-7}"; MIN="${OVERLAY_AUTOSYNC_MIN:-15}"
else
  LABEL="com.openbridge.upstream-autoupdate"
  SCRIPT="scripts/upstream-autoupdate.sh"
  STEM="upstream-autoupdate"
  REPORT="work/upstream-status.md"
  HOUR="${AUTOUPDATE_HOUR:-7}"; MIN="${AUTOUPDATE_MIN:-0}"
fi
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
UID_="$(id -u)"

xml_esc() { printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g'; }
REPO_XML=$(xml_esc "$REPO")
sig=""
[ -n "${SIGNAL_ACCOUNT:-}" ]   && sig="$sig    <key>SIGNAL_ACCOUNT</key><string>$(xml_esc "$SIGNAL_ACCOUNT")</string>
"
[ -n "${SIGNAL_RECIPIENT:-}" ] && sig="$sig    <key>SIGNAL_RECIPIENT</key><string>$(xml_esc "$SIGNAL_RECIPIENT")</string>
"
if [ -n "${AUTOUPDATE_NOTIFY_CMD:-}" ]; then
  sig="$sig    <key>AUTOUPDATE_NOTIFY_CMD</key><string>$(xml_esc "$AUTOUPDATE_NOTIFY_CMD")</string>
"
fi

render_plist() { cat <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key><array>
    <string>/bin/bash</string><string>$REPO_XML/$SCRIPT</string>
  </array>
  <key>WorkingDirectory</key><string>$REPO_XML</string>
  <key>EnvironmentVariables</key><dict>
    <key>PATH</key><string>/opt/homebrew/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    <key>UPSTREAM_REF</key><string>${UPSTREAM_REF:-upstream/main}</string>
$sig  </dict>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>$HOUR</integer><key>Minute</key><integer>$MIN</integer></dict>
  <key>StandardOutPath</key><string>$REPO_XML/work/$STEM.launchd.out</string>
  <key>StandardErrorPath</key><string>$REPO_XML/work/$STEM.launchd.err</string>
  <key>RunAtLoad</key><false/>
</dict></plist>
PLIST
}

if [ "$PRINT" = 1 ]; then render_plist; exit 0; fi

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

mkdir -p "$(dirname "$PLIST")"
render_plist > "$PLIST"

launchctl bootstrap "gui/$UID_" "$PLIST"
printf 'installed + loaded: %s @ %02d:%02d daily → %s\n' "$LABEL" "$HOUR" "$MIN" "$REPO"

# --- VERIFY in the real launchd context (do not assume) ---
echo "verifying (launchctl kickstart)…"
: > "$REPO/work/$STEM.launchd.err" 2>/dev/null || true
launchctl kickstart -k "gui/$UID_/$LABEL"
sleep 5
err="$REPO/work/$STEM.launchd.err"
if grep -qiE 'not permitted|operation not permitted' "$err" 2>/dev/null; then
  echo "✗ VERIFY FAILED — TCC/permission denied in launchd context:"; tail -3 "$err"; exit 1
elif [ -s "$REPO/$REPORT" ]; then
  echo "✓ VERIFIED — job executed in launchd context and wrote its report:"
  grep -m2 '^-' "$REPO/$REPORT" | sed 's/^/    /'
else
  echo "✗ VERIFY INCONCLUSIVE — no report written; launchd err:"; tail -3 "$err" 2>/dev/null; exit 1
fi
