#!/usr/bin/env bash
# transcribe-bundler.sh — context-aware capture-side bundler.
# Watches ~/Recordings/meetings/<context>/ for finished Audio Hijack recordings,
# bundles each (mtime stable for N s = AH stopped writing), and rsyncs to
# <worker>:~/transcribe-inbox/<context>/<ts>/.
#
# Context = the subfolder under ~/Recordings/meetings/ a recording lands in
# (e.g. .../meetings/main/, .../meetings/customer-x/). One Audio Hijack session
# per context, each writing into its own folder. Loose MP3s directly under
# meetings/ are treated as context "main" (back-compat default).
#
# Triggered by launchd WatchPath (com.openbridge.transcribe-bundler.plist).
# Replaces v1's AH onRecordingEnd JS hook (AH automation has no shell access).
#
# Idempotent (.PUSHED). Defers gracefully when the worker is unreachable.
# Drop-in: ~/bin/transcribe-bundler.sh   Logs: ~/Library/Logs/transcribe-bundler.log
#
# NOTE: this script runs on the capture machine, OUTSIDE the Bridge repo — so
# the worker target comes from the environment (set TRANSCRIBE_WORKER in the
# launchd plist) or is hardcoded at deploy time; there is no bridge-config.yaml
# to read here.

set -euo pipefail

ROOT="$HOME/Recordings/meetings"
WORKER="${TRANSCRIBE_WORKER:-worker-host}"   # SSH/Tailscale name of the worker host
REMOTE_INBOX_REL="transcribe-inbox"
STABLE_SECS=5
MIN_DURATION_SECS=120
DEFAULT_CONTEXT="main"   # context for loose MP3s directly under meetings/ — edit at deploy if yours differs
LOG="$HOME/Library/Logs/transcribe-bundler.log"

mkdir -p "$ROOT" "$(dirname "$LOG")"
log() { printf '%s [bundler] %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*" >> "$LOG"; }

remote_up() { ssh -o ConnectTimeout=3 -o BatchMode=yes "$WORKER" 'true' 2>/dev/null; }
remote_ctx_ready() { ssh -o BatchMode=yes "$WORKER" "test -d \"\$HOME/$REMOTE_INBOX_REL/$1\"" 2>/dev/null; }

push_bundle() {  # <bundle-dir> <context>
  local bundle="$1" ctx="$2" ts; ts="$(basename "$bundle")"
  [[ -f "$bundle/.PUSHED" ]] && return 0
  remote_up || { log "deferred $ctx/$ts — $WORKER unreachable"; return 0; }
  if ! remote_ctx_ready "$ctx"; then
    log "deferred $ctx/$ts — remote inbox/$ctx missing (run add_context.sh $ctx from bridge repo, then redeploy)"; return 0
  fi
  log "pushing $ctx/$ts"
  if rsync -av --partial --inplace "$bundle/" "$WORKER:~/$REMOTE_INBOX_REL/$ctx/$ts/" >> "$LOG" 2>&1; then
    ssh -o BatchMode=yes "$WORKER" "touch ~/$REMOTE_INBOX_REL/$ctx/$ts/.READY" 2>/dev/null || true
    touch "$bundle/.PUSHED"; log "ok $ctx/$ts"
  else
    log "ERROR rsync $ctx/$ts (exit $?)"
  fi
}

bundle_loose_mp3s() {  # <dir> <context>
  local dir="$1" ctx="$2" now; now=$(date +%s)
  shopt -s nullglob
  for mp3 in "$dir"/*.mp3; do
    local base mtime age dur ts bundle size
    base="$(basename "$mp3" .mp3)"; mtime=$(stat -f %m "$mp3"); age=$(( now - mtime ))
    (( age < STABLE_SECS )) && { log "wait $ctx/$base (age ${age}s)"; continue; }
    dur=$(afinfo "$mp3" 2>/dev/null | awk -F': ' '/estimated duration/ {print int($2)}'); dur="${dur:-0}"
    if (( dur < MIN_DURATION_SECS )); then
      log "skip $ctx/$base — ${dur}s < ${MIN_DURATION_SECS}s"; mkdir -p "$dir/_short"; mv "$mp3" "$dir/_short/"; continue
    fi
    ts="$(date -r "$mtime" +%Y-%m-%d-%H%M%S)"; bundle="$dir/$ts"
    [[ -d "$bundle" && -f "$bundle/.PUSHED" ]] && continue
    mkdir -p "$bundle"; mv "$mp3" "$bundle/meeting.mp3"; size=$(stat -f %z "$bundle/meeting.mp3")
    cat > "$bundle/manifest.yaml" <<EOF
bundle: $ts
context: $ctx
recorded_at: $(date -r "$mtime" -u +'%Y-%m-%dT%H:%M:%SZ')
bundled_at: $(date -u +'%Y-%m-%dT%H:%M:%SZ')
host: $(scutil --get LocalHostName 2>/dev/null || hostname)
source: audio-hijack-2track-splitchannels
duration_s: $dur
size_bytes: $size
channels:
  L: mic
  R: app-teams
EOF
    touch "$bundle/.READY"; log "bundled $ctx/$ts (${dur}s, $((size/1024/1024)) MB)"
    push_bundle "$bundle" "$ctx"
  done
}

# Context subfolders under meetings/
shopt -s nullglob
for ctxdir in "$ROOT"/*/; do
  ctx="$(basename "$ctxdir")"
  [[ "$ctx" == "_short" ]] && continue
  bundle_loose_mp3s "$ctxdir" "$ctx"
  # catch-up: ready-but-unpushed bundles in this context
  for bundle in "$ctxdir"*/; do
    b="$(basename "$bundle")"
    [[ "$b" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{6}$ ]] || continue
    [[ -f "$bundle/.READY" && ! -f "$bundle/.PUSHED" && -f "$bundle/meeting.mp3" ]] && push_bundle "$bundle" "$ctx"
  done
done

# Back-compat: loose MP3s directly under meetings/ → default context
bundle_loose_mp3s "$ROOT" "$DEFAULT_CONTEXT"
