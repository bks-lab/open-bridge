#!/usr/bin/env bash
# debrief_sync.sh — bridge between the transcription pipeline and the /debrief
# skill. It implements the sync-script contract of docs/transcription-worker.md.
# Two directions:
#
#   pull               fetch: bring finished transcripts into the bridge imports
#                      dir, where /debrief Phase 1 finds them. Pulled files are
#                      moved to <transcripts>/<ctx>/_debriefed/ so they're pulled
#                      exactly once.
#
#   push <audio> [ctx] deliver: send an audio file to the pipeline inbox for
#                      transcription. Returns immediately; the transcript shows
#                      up in a later `pull` (transcription is async, minutes).
#
#   voiceprints pull   back up: fetch the per-context speaker-library/*.npy into
#                      the bridge under identity/voiceprints/<ctx>/.
#   voiceprints push   restore: send the bridge's voiceprints back onto a (fresh)
#                      worker — rebuild the library after a worker wipe.
#
# TRANSPORT is chosen by the topology mode (infra/transcriptions/topology.yaml):
#   remote — the pipeline lives on a worker host; every pull/push/voiceprints
#            operation runs over ssh + rsync to worker.host. An unreachable worker
#            exits non-zero and /debrief degrades to its manual path.
#   local  — bridge and worker are the SAME machine; every operation is a plain
#            local filesystem cp/mv against the worker's conventional dirs, and
#            the SSH reachability probe is skipped (no sshd / Remote Login needed).
#   Resolution: TRANSCRIBE_MODE env > topology.yaml `mode` > inferred (a worker
#   host resolves ⇒ remote, else local — legacy fallback for pre-topology instances).
#
#   NOTE on voiceprints: these are biometric voice embeddings (GDPR Art. 9), so
#   identity/voiceprints/ is scope:user and NEVER promotes upstream. Git tracking
#   is decided by the bridge's .gitignore, NOT by this script: each context dir
#   is opt-in via a whitelist. This script pulls ALL contexts uniformly; what
#   gets committed is the bridge's policy. A customer-facing instance would
#   route customer voiceprints to that customer's own repo instead of tracking
#   them here.
#
# Config resolution: environment first, then infra/transcriptions/topology.yaml
# (PLACEMENT: mode, worker host, local paths) + bridge-config.yaml (REGISTRATION:
# contexts, default_context), then fail with a clear message. Imports dir defaults
# to this repo's work/imports; override with BRIDGE_IMPORTS. Voiceprint dir:
# BRIDGE_VOICEPRINTS.
#
# Usage:
#   debrief_sync.sh pull
#   debrief_sync.sh push ~/Recordings/foo.m4a customer-x
#   debrief_sync.sh voiceprints pull | voiceprints push

set -euo pipefail

# Repo root resolved from this script's location (scripts/ → skill → skills/ → repo).
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../../.." && pwd)"
CONFIG="$REPO_ROOT/bridge-config.yaml"
TOPO="$REPO_ROOT/infra/transcriptions/topology.yaml"

# Read a dotted key from a YAML file. Prints the scalar value, dict keys
# space-joined for mappings, or nothing when the key (or the file) is absent.
yaml_get() {
  [[ -f "$1" ]] || return 0
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
' "$1" "$2" 2>/dev/null || true
}
cfg_get()  { yaml_get "$CONFIG" "$1"; }   # bridge-config.yaml — registration axis
topo_get() { yaml_get "$TOPO"   "$1"; }   # infra/transcriptions/topology.yaml — placement axis

# Expand a leading ~ to $HOME (topo_get returns the literal string).
_tilde() { printf '%s' "${1/#\~/$HOME}"; }

# --- Topology mode ---------------------------------------------------------
MODE="${TRANSCRIBE_MODE:-$(topo_get mode)}"
if [[ -z "$MODE" ]]; then
  # Legacy fallback (no topology.yaml — pre-2026-07 instances): infer from a host.
  if [[ -n "${TRANSCRIBE_WORKER:-}" || -n "$(cfg_get integrations.transcription.worker.host)" ]]; then
    MODE=remote
  else
    MODE=local
  fi
fi
case "$MODE" in
  local|remote) ;;
  *) echo "invalid transcription mode '$MODE' — set 'mode: local|remote' in infra/transcriptions/topology.yaml (or TRANSCRIBE_MODE)"; exit 1 ;;
esac

# --- Worker host (required only in remote mode) ----------------------------
WORKER="${TRANSCRIBE_WORKER:-$(topo_get worker.host)}"
[[ -z "$WORKER" ]] && WORKER="$(cfg_get integrations.transcription.worker.host)"   # legacy location
if [[ "$MODE" == remote && -z "$WORKER" ]]; then
  echo "mode 'remote' but no worker host — set worker.host in infra/transcriptions/topology.yaml or TRANSCRIBE_WORKER"; exit 1
fi

IMPORTS="${BRIDGE_IMPORTS:-$REPO_ROOT/work/imports}"
CONTEXTS="${TRANSCRIBE_CONTEXTS:-$(cfg_get integrations.transcription.contexts)}"
if [[ -z "$CONTEXTS" ]]; then
  echo "no contexts configured — set TRANSCRIBE_CONTEXTS or add integrations.transcription.contexts to bridge-config.yaml"; exit 1
fi

# launchd label of the worker job — kicked after a push (remote: worker.*, local: local.*).
if [[ "$MODE" == remote ]]; then KICK_LABEL="$(topo_get worker.launchd_label)"; else KICK_LABEL="$(topo_get local.launchd_label)"; fi
[[ -z "$KICK_LABEL" ]] && KICK_LABEL="$(cfg_get integrations.transcription.worker.launchd_label)"   # legacy
KICK_LABEL="${KICK_LABEL:-com.openbridge.transcribe-worker}"

# Voiceprint dir defaults to <repo-root>/identity/voiceprints.
VOICEPRINTS="${BRIDGE_VOICEPRINTS:-$REPO_ROOT/identity/voiceprints}"

# Local worker dirs (mode: local only; defaults = the worker's own conventions).
L_TRANSCRIPTS="$(_tilde "$(topo_get local.transcripts_dir)")"; L_TRANSCRIPTS="${L_TRANSCRIPTS:-$HOME/Transcripts}"
L_INBOX="$(_tilde "$(topo_get local.inbox_dir)")";             L_INBOX="${L_INBOX:-$HOME/transcribe-inbox}"
L_LIBRARY="$(_tilde "$(topo_get local.library_dir)")";         L_LIBRARY="${L_LIBRARY:-$HOME/transcribe-pipeline/speaker-library}"

cmd="${1:-}"; case "$cmd" in pull|push|voiceprints) ;; *)
  echo "usage: debrief_sync.sh pull | push <audio> [context] | voiceprints pull|push"; exit 2 ;; esac

# Remote reachability probe — skipped entirely in local mode.
if [[ "$MODE" == remote ]]; then
  if ! ssh -o ConnectTimeout=5 -o BatchMode=yes "$WORKER" 'true' 2>/dev/null; then
    echo "worker $WORKER unreachable"; exit 1
  fi
fi

case "$cmd" in
  pull)
    mkdir -p "$IMPORTS"
    pulled=0
    for ctx in $CONTEXTS; do
      if [[ "$MODE" == remote ]]; then
        ssh -o BatchMode=yes "$WORKER" "mkdir -p ~/Transcripts/$ctx/_debriefed" 2>/dev/null || true
        # find (not a glob) avoids the remote zsh "no matches found" on empty dirs
        mapfile -t files < <(ssh -o BatchMode=yes "$WORKER" "find ~/Transcripts/$ctx -maxdepth 1 -name '*.md' 2>/dev/null" || true)
      else
        mkdir -p "$L_TRANSCRIPTS/$ctx/_debriefed" 2>/dev/null || true
        mapfile -t files < <(find "$L_TRANSCRIPTS/$ctx" -maxdepth 1 -name '*.md' 2>/dev/null || true)
      fi
      for f in "${files[@]}"; do
        [[ -n "$f" ]] || continue
        bn="$(basename "$f")"
        # Context-prefix so /debrief can route (e.g. customer-x-* → that
        # customer's own Bridge instance).
        if [[ "$MODE" == remote ]]; then
          if rsync -av "$WORKER:$f" "$IMPORTS/${ctx}-${bn}" >/dev/null 2>&1; then
            ssh -o BatchMode=yes "$WORKER" "mv ~/Transcripts/$ctx/$bn ~/Transcripts/$ctx/_debriefed/" 2>/dev/null || true
            echo "pulled ${ctx}-${bn}"
            pulled=$((pulled+1))
          fi
        else
          if cp "$f" "$IMPORTS/${ctx}-${bn}" 2>/dev/null; then
            mv "$L_TRANSCRIPTS/$ctx/$bn" "$L_TRANSCRIPTS/$ctx/_debriefed/" 2>/dev/null || true
            echo "pulled ${ctx}-${bn}"
            pulled=$((pulled+1))
          fi
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
    ts="$(date +%Y-%m-%d-%H%M%S)"
    # tracks: single — a debrief handoff is always ONE mixed recording, never a
    # real 2-track Audio-Hijack bundle. Without this the worker defaults to dual
    # and runs an ffmpeg channel-split that fails on single-file audio.
    if [[ "$MODE" == remote ]]; then
      if ! ssh -o BatchMode=yes "$WORKER" "test -d ~/transcribe-inbox/$ctx" 2>/dev/null; then
        echo "context '$ctx' not provisioned on $WORKER — run add_context.sh $ctx first"; exit 1
      fi
      ssh -o BatchMode=yes "$WORKER" "mkdir -p ~/transcribe-inbox/$ctx/$ts"
      rsync -av "$audio" "$WORKER:~/transcribe-inbox/$ctx/$ts/meeting.mp3" >/dev/null
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
    else
      if [[ ! -d "$L_INBOX/$ctx" ]]; then
        echo "context '$ctx' not provisioned — run add_context.sh $ctx first"; exit 1
      fi
      mkdir -p "$L_INBOX/$ctx/$ts"
      cp "$audio" "$L_INBOX/$ctx/$ts/meeting.mp3"
      printf 'recorded_at: %s\nduration_s: 0\ncontext: %s\ntracks: single\nsource: debrief-handoff\n' \
          "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$ctx" > "$L_INBOX/$ctx/$ts/manifest.yaml"
      touch "$L_INBOX/$ctx/$ts/.READY"
      launchctl kickstart "gui/$(id -u)/$KICK_LABEL" >/dev/null 2>&1 \
        && echo "worker kicked" || echo "WARN could not kickstart worker (will rely on WatchPath / next run)"
      echo "pushed → $L_INBOX/$ctx/$ts (context=$ctx)"
    fi
    echo "transcription is async — run 'debrief_sync.sh pull' (or /debrief) in a few minutes to collect it"
    ;;

  voiceprints)
    dir="${2:-}"; case "$dir" in
      pull)
        # worker → bridge. Pull each context's .npy embeddings. Only *.npy is
        # synced (the speaker-library/raw/ bootstrap audio is deliberately left
        # in place — it's large + not needed for matching).
        synced=0
        for ctx in $CONTEXTS; do
          if [[ "$MODE" == remote ]]; then
            if ! ssh -o BatchMode=yes "$WORKER" "test -d ~/transcribe-pipeline/speaker-library/$ctx" 2>/dev/null; then
              continue   # context has no library on the worker yet
            fi
            mkdir -p "$VOICEPRINTS/$ctx"
            n=$(rsync -av --include='*.npy' --exclude='*' \
                  "$WORKER:transcribe-pipeline/speaker-library/$ctx/" "$VOICEPRINTS/$ctx/" \
                  2>/dev/null | grep -c '\.npy$' || true)
          else
            [[ -d "$L_LIBRARY/$ctx" ]] || continue   # context has no local library yet
            mkdir -p "$VOICEPRINTS/$ctx"
            n=$(rsync -av --include='*.npy' --exclude='*' \
                  "$L_LIBRARY/$ctx/" "$VOICEPRINTS/$ctx/" \
                  2>/dev/null | grep -c '\.npy$' || true)
          fi
          echo "pulled ${ctx}: ${n} voiceprint(s) → $VOICEPRINTS/$ctx/"
          synced=$((synced + n))
        done
        echo "voiceprints pull done — $synced file(s) into $VOICEPRINTS"
        echo "git tracks only whitelisted contexts (see .gitignore); the rest is offsite-only via your backup pipeline."
        ;;
      push)
        # bridge → worker (restore after a worker wipe). Additive, no --delete.
        [[ -d "$VOICEPRINTS" ]] || { echo "no local voiceprints at $VOICEPRINTS"; exit 1; }
        restored=0
        for ctx in $CONTEXTS; do
          [[ -d "$VOICEPRINTS/$ctx" ]] || continue
          if [[ "$MODE" == remote ]]; then
            ssh -o BatchMode=yes "$WORKER" "mkdir -p ~/transcribe-pipeline/speaker-library/$ctx" 2>/dev/null || true
            n=$(rsync -av --include='*.npy' --exclude='*' \
                  "$VOICEPRINTS/$ctx/" "$WORKER:transcribe-pipeline/speaker-library/$ctx/" \
                  2>/dev/null | grep -c '\.npy$' || true)
          else
            mkdir -p "$L_LIBRARY/$ctx" 2>/dev/null || true
            n=$(rsync -av --include='*.npy' --exclude='*' \
                  "$VOICEPRINTS/$ctx/" "$L_LIBRARY/$ctx/" \
                  2>/dev/null | grep -c '\.npy$' || true)
          fi
          echo "restored ${ctx}: ${n} voiceprint(s)"
          restored=$((restored + n))
        done
        echo "voiceprints push done — $restored file(s) restored"
        ;;
      *) echo "usage: debrief_sync.sh voiceprints pull|push"; exit 2 ;;
    esac
    ;;
esac
