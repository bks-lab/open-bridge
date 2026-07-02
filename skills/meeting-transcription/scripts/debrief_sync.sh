#!/usr/bin/env bash
# debrief_sync.sh — bridge between the transcription pipeline (worker host) and
# the /debrief skill. It implements the sync-script contract of
# docs/transcription-worker.md. Two directions:
#
#   pull               fetch: rsync finished transcripts from
#                      <worker>:~/Transcripts/<ctx>/ into the bridge imports dir,
#                      where /debrief Phase 1 finds them. Pulled files are moved
#                      to ~/Transcripts/<ctx>/_debriefed/ on the worker so they're
#                      pulled exactly once.
#
#   push <audio> [ctx] deliver: send an audio file to the pipeline inbox for
#                      transcription. Returns immediately; the transcript shows
#                      up in a later `pull` (transcription is async, minutes).
#
#   voiceprints pull   back up: rsync the per-context speaker-library/*.npy from
#                      the worker into the bridge under identity/voiceprints/<ctx>/.
#   voiceprints push   restore: rsync the bridge's voiceprints back onto a (fresh)
#                      worker — rebuild the library after a worker wipe.
#
#   NOTE on voiceprints: these are biometric voice embeddings (GDPR Art. 9), so
#   identity/voiceprints/ is scope:user and NEVER promotes upstream. Git tracking
#   is decided by the bridge's .gitignore, NOT by this script: each context dir
#   is opt-in via a whitelist. This script pulls ALL contexts uniformly; what
#   gets committed is the bridge's policy. A customer-facing instance would
#   route customer voiceprints to that customer's own repo instead of tracking
#   them here.
#
# Runs on the machine that hosts the Bridge repo (this direction of SSH —
# bridge machine → worker — works without Remote Login on the local machine).
# Config resolution: environment first, then bridge-config.yaml at the repo
# root, then fail with a clear message. Imports dir defaults to this repo's
# work/imports; override with BRIDGE_IMPORTS. Voiceprint dir: BRIDGE_VOICEPRINTS.
#
# Usage:
#   debrief_sync.sh pull
#   debrief_sync.sh push ~/Recordings/foo.m4a customer-x
#   debrief_sync.sh voiceprints pull | voiceprints push

set -euo pipefail

# Repo root resolved from this script's location (scripts/ → skill → skills/ → repo).
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
CONFIG="$REPO_ROOT/bridge-config.yaml"

# Read a dotted key from bridge-config.yaml. Prints the scalar value, dict keys
# space-joined for mappings, or nothing when the key (or the file) is absent.
cfg_get() {
  [[ -f "$CONFIG" ]] || return 0
  python3 -c '
import sys
try:
    import yaml
    data = yaml.safe_load(open(sys.argv[1])) or {}
except Exception:
    sys.exit(0)
node = data
for part in sys.argv[2].split("."):
    if not isinstance(node, dict) or part not in node:
        sys.exit(0)
    node = node[part]
if isinstance(node, dict):
    print(" ".join(str(k) for k in node))
elif node is not None:
    print(node)
' "$CONFIG" "$1" 2>/dev/null || true
}

WORKER="${TRANSCRIBE_WORKER:-$(cfg_get integrations.transcription.worker.host)}"
if [[ -z "$WORKER" ]]; then
  echo "no worker configured — set TRANSCRIBE_WORKER or integrations.transcription.worker.host in bridge-config.yaml"; exit 1
fi
IMPORTS="${BRIDGE_IMPORTS:-$REPO_ROOT/work/imports}"
CONTEXTS="${TRANSCRIBE_CONTEXTS:-$(cfg_get integrations.transcription.contexts)}"
if [[ -z "$CONTEXTS" ]]; then
  echo "no contexts configured — set TRANSCRIBE_CONTEXTS or add integrations.transcription.contexts to bridge-config.yaml"; exit 1
fi
# launchd label of the worker job — used to kick it after a push.
KICK_LABEL="$(cfg_get integrations.transcription.worker.launchd_label)"
KICK_LABEL="${KICK_LABEL:-com.openbridge.transcribe-worker}"
# Voiceprint dir defaults to <repo-root>/identity/voiceprints.
VOICEPRINTS="${BRIDGE_VOICEPRINTS:-$REPO_ROOT/identity/voiceprints}"

cmd="${1:-}"; case "$cmd" in pull|push|voiceprints) ;; *)
  echo "usage: debrief_sync.sh pull | push <audio> [context] | voiceprints pull|push"; exit 2 ;; esac

if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "$WORKER" 'true' 2>/dev/null; then
  echo "worker $WORKER unreachable"; exit 1
fi

case "$cmd" in
  pull)
    mkdir -p "$IMPORTS"
    pulled=0
    for ctx in $CONTEXTS; do
      ssh -o BatchMode=yes "$WORKER" "mkdir -p ~/Transcripts/$ctx/_debriefed" 2>/dev/null || true
      # find (not a glob) avoids the remote zsh "no matches found" on empty dirs
      mapfile -t files < <(ssh -o BatchMode=yes "$WORKER" "find ~/Transcripts/$ctx -maxdepth 1 -name '*.md' 2>/dev/null" || true)
      for f in "${files[@]}"; do
        [[ -n "$f" ]] || continue
        bn="$(basename "$f")"
        # Context-prefix so /debrief can route (e.g. customer-x-* → that
        # customer's own Bridge instance).
        if rsync -av "$WORKER:$f" "$IMPORTS/${ctx}-${bn}" >/dev/null 2>&1; then
          ssh -o BatchMode=yes "$WORKER" "mv ~/Transcripts/$ctx/$bn ~/Transcripts/$ctx/_debriefed/" 2>/dev/null || true
          echo "pulled ${ctx}-${bn}"
          pulled=$((pulled+1))
        fi
      done
    done
    echo "pull done — $pulled new transcript(s) into $IMPORTS"
    ;;

  push)
    audio="${2:?push needs an audio file path}"
    ctx="${3:-}"
    if [[ -z "$ctx" ]]; then
      ctx="$(cfg_get integrations.transcription.default_context)"
    fi
    if [[ -z "$ctx" ]]; then
      echo "no context given and no integrations.transcription.default_context in bridge-config.yaml — pass one: debrief_sync.sh push <audio> <context>"; exit 1
    fi
    [[ -f "$audio" ]] || { echo "audio not found: $audio"; exit 1; }
    if ! ssh -o BatchMode=yes "$WORKER" "test -d ~/transcribe-inbox/$ctx" 2>/dev/null; then
      echo "context '$ctx' not provisioned on $WORKER — run add_context.sh $ctx first"; exit 1
    fi
    ts="$(date +%Y-%m-%d-%H%M%S)"
    ssh -o BatchMode=yes "$WORKER" "mkdir -p ~/transcribe-inbox/$ctx/$ts"
    rsync -av "$audio" "$WORKER:~/transcribe-inbox/$ctx/$ts/meeting.mp3" >/dev/null
    # tracks: single — a debrief handoff is always ONE mixed recording, never a
    # real 2-track Audio-Hijack bundle. Without this the worker defaults to dual
    # and runs an ffmpeg channel-split that fails on single-file audio.
    ssh -o BatchMode=yes "$WORKER" "printf 'recorded_at: %s\nduration_s: 0\ncontext: %s\ntracks: single\nsource: debrief-handoff\n' \
        \"\$(date -u +%Y-%m-%dT%H:%M:%SZ)\" \"$ctx\" > ~/transcribe-inbox/$ctx/$ts/manifest.yaml; \
        touch ~/transcribe-inbox/$ctx/$ts/.READY"
    # Kick the worker explicitly. The launchd WatchPath on ~/transcribe-inbox
    # only fires for changes to that dir's DIRECT entries — a bundle created
    # inside an already-existing context subfolder (main/<ts>) does NOT trigger
    # it, so the very first push to a new context worked but later ones silently
    # never got processed. kickstart (not -k, so a running transcription isn't
    # killed) makes the handoff reliable regardless of the watch.
    ssh -o BatchMode=yes "$WORKER" "launchctl kickstart gui/\$(id -u)/$KICK_LABEL" >/dev/null 2>&1 \
      && echo "worker kicked" || echo "WARN could not kickstart worker (will rely on WatchPath / next run)"
    echo "pushed → $WORKER:~/transcribe-inbox/$ctx/$ts (context=$ctx)"
    echo "transcription is async — run 'debrief_sync.sh pull' (or /debrief) in a few minutes to collect it"
    ;;

  voiceprints)
    dir="${2:-}"; case "$dir" in
      pull)
        # Worker → bridge. Pull each context's .npy embeddings. Only *.npy is
        # synced (the speaker-library/raw/ bootstrap audio is deliberately left
        # on the worker — it's large + not needed for matching).
        synced=0
        for ctx in $CONTEXTS; do
          if ! ssh -o BatchMode=yes "$WORKER" "test -d ~/transcribe-pipeline/speaker-library/$ctx" 2>/dev/null; then
            continue   # context has no library on the worker yet
          fi
          mkdir -p "$VOICEPRINTS/$ctx"
          n=$(rsync -av --include='*.npy' --exclude='*' \
                "$WORKER:transcribe-pipeline/speaker-library/$ctx/" "$VOICEPRINTS/$ctx/" \
                2>/dev/null | grep -c '\.npy$' || true)
          echo "pulled ${ctx}: ${n} voiceprint(s) → $VOICEPRINTS/$ctx/"
          synced=$((synced + n))
        done
        echo "voiceprints pull done — $synced file(s) into $VOICEPRINTS"
        echo "git tracks only whitelisted contexts (see .gitignore); the rest is offsite-only via your backup pipeline."
        ;;
      push)
        # Bridge → worker (restore after a worker wipe). Additive, no --delete.
        [[ -d "$VOICEPRINTS" ]] || { echo "no local voiceprints at $VOICEPRINTS"; exit 1; }
        restored=0
        for ctx in $CONTEXTS; do
          [[ -d "$VOICEPRINTS/$ctx" ]] || continue
          ssh -o BatchMode=yes "$WORKER" "mkdir -p ~/transcribe-pipeline/speaker-library/$ctx" 2>/dev/null || true
          n=$(rsync -av --include='*.npy' --exclude='*' \
                "$VOICEPRINTS/$ctx/" "$WORKER:transcribe-pipeline/speaker-library/$ctx/" \
                2>/dev/null | grep -c '\.npy$' || true)
          echo "restored ${ctx}: ${n} voiceprint(s) → $WORKER"
          restored=$((restored + n))
        done
        echo "voiceprints push done — $restored file(s) restored to $WORKER"
        ;;
      *) echo "usage: debrief_sync.sh voiceprints pull|push"; exit 2 ;;
    esac
    ;;
esac
