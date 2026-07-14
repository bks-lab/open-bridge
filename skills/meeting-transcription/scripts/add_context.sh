#!/usr/bin/env bash
# add_context.sh — bridge-side bootstrap for a transcription context.
#
# Runs LOCALLY (in the bridge repo). Does NOT create any yaml — the bridge
# context yaml at workflow/contexts/<name>.yaml is the single source of
# truth, and the user authors it themselves (copy from _template.yaml,
# fill `integrations.transcription`, validate with check-jsonschema).
# This script bootstraps the pipeline dirs the worker expects, per the
# topology mode (infra/transcriptions/topology.yaml):
#
#   remote — ssh to worker.host and mkdir the inbox + speaker-library there;
#            (optionally) mkdir the capture-host recording folder.
#   local  — mkdir them on THIS machine and deploy the runtime context yaml
#            locally (no SSH).
#
#   <worker|this>:~/transcribe-inbox/<name>/                       (drop-zone)
#   <worker|this>:~/transcribe-pipeline/speaker-library/<name>/    (voice library)
#   <capture>:~/Recordings/meetings/<name>/                        (Audio Hijack target — remote only, optional)
#
# Mode/host/paths resolve exactly as in debrief_sync.sh (env > topology.yaml >
# legacy bridge-config / inferred).
#
# Usage:  add_context.sh <name> [capture_host]
#   name          context slug — MUST match workflow/contexts/<name>.yaml
#   capture_host  (remote mode) SSH/Tailscale host for the recording folder
#                 (default: $CAPTURE_HOST; empty = skip the capture step)
#
# History: an earlier version always ran ssh-to-worker and required a worker
# host. It now honours mode: local so a single-machine instance bootstraps a
# context with no SSH at all.

set -euo pipefail

NAME="${1:?usage: add_context.sh <name> [capture_host]}"
CAPTURE="${2:-${CAPTURE_HOST:-}}"

[[ "$NAME" =~ ^[a-z0-9-]+$ ]] || { echo "name must be [a-z0-9-]+"; exit 1; }

# Resolve bridge repo root from this script's location (scripts/ → skill → repo).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
CONFIG="$REPO_ROOT/bridge-config.yaml"
TOPO="$REPO_ROOT/infra/transcriptions/topology.yaml"
BRIDGE_CTX="$REPO_ROOT/workflow/contexts/$NAME.yaml"

# Read a dotted key from a YAML file (mirrors debrief_sync.sh).
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
cfg_get()  { yaml_get "$CONFIG" "$1"; }
topo_get() { yaml_get "$TOPO"   "$1"; }
_tilde() { printf '%s' "${1/#\~/$HOME}"; }

# --- Topology mode (same resolution as debrief_sync.sh) --------------------
MODE="${TRANSCRIBE_MODE:-$(topo_get mode)}"
if [[ -z "$MODE" ]]; then
  if [[ -n "${TRANSCRIBE_WORKER:-}" || -n "$(cfg_get integrations.transcription.worker.host)" ]]; then MODE=remote; else MODE=local; fi
fi
case "$MODE" in
  local|remote) ;;
  *) echo "invalid transcription mode '$MODE' — set 'mode: local|remote' in infra/transcriptions/topology.yaml"; exit 1 ;;
esac

# Refuse to bootstrap dirs without a bridge yaml. Otherwise we'd create orphan
# dirs the worker has no config for, exactly the drift this refactor prevents.
if [[ ! -f "$BRIDGE_CTX" ]]; then
  cat <<EOF >&2
ERROR: no bridge context yaml at $BRIDGE_CTX

Create it first (copy from workflow/contexts/_template.yaml and fill the
integrations.transcription block), validate:

  check-jsonschema --schemafile workflow/contexts/_schema.yaml $BRIDGE_CTX

THEN re-run this script.
EOF
  exit 2
fi

# Verify the bridge yaml actually has the transcription block, otherwise the
# extract step will skip it and the pipeline won't see this context.
if command -v yq >/dev/null 2>&1; then
  if [[ "$(yq -r '.integrations.transcription // ""' "$BRIDGE_CTX")" == "" ]]; then
    echo "ERROR: $BRIDGE_CTX has no integrations.transcription block — add it first" >&2
    exit 2
  fi
fi

if [[ "$MODE" == remote ]]; then
  WORKER="${TRANSCRIBE_WORKER:-$(topo_get worker.host)}"
  [[ -z "$WORKER" ]] && WORKER="$(cfg_get integrations.transcription.worker.host)"   # legacy location
  if [[ -z "$WORKER" ]]; then
    echo "mode 'remote' but no worker host — set worker.host in infra/transcriptions/topology.yaml or TRANSCRIBE_WORKER" >&2; exit 1
  fi

  echo "→ $WORKER: mkdir transcribe-inbox/$NAME/, speaker-library/$NAME/"
  ssh -o BatchMode=yes "$WORKER" "mkdir -p ~/transcribe-inbox/$NAME ~/transcribe-pipeline/speaker-library/$NAME"

  if [[ -n "$CAPTURE" ]]; then
    echo "→ $CAPTURE: mkdir Recordings/meetings/$NAME/"
    if ssh -o ConnectTimeout=3 -o BatchMode=yes "$CAPTURE" "mkdir -p ~/Recordings/meetings/$NAME" 2>/dev/null; then
      echo "   ok"
    else
      echo "   WARN: could not reach $CAPTURE — create ~/Recordings/meetings/$NAME/ there manually"
    fi
  else
    echo "→ capture host: skipped (CAPTURE_HOST not set) — create ~/Recordings/meetings/$NAME/ on your capture machine if you record there"
  fi

  cat <<EOF

Bootstrap done for context '$NAME' (remote worker $WORKER).

Next steps:
  1. Generate + deploy the worker runtime yaml:
       python3 skills/meeting-transcription/scripts/extract_runtime_contexts.py \\
         --src workflow/contexts --out /tmp/runtime-contexts
       rsync -av --delete /tmp/runtime-contexts/ $WORKER:transcribe-pipeline/contexts/
  2. (Capture) Make an Audio Hijack session writing to ~/Recordings/meetings/$NAME/
     on ${CAPTURE:-your capture machine} — or drop an MP3 into $WORKER:~/transcribe-inbox/$NAME/<ts>/meeting.mp3 + touch .READY
  3. (First meeting) Bootstrap voices:
       python bin/speaker_idcard.py --json <ctx>/<ts>/teams_out/teams.json
       python bin/apply_speaker_names.py --json ... --map "SPEAKER_00=Name,..." \\
              --library speaker-library/$NAME --save-embeddings
EOF

else
  # --- local: bootstrap dirs on THIS machine + deploy runtime yaml, no SSH ---
  L_INBOX="$(_tilde "$(topo_get local.inbox_dir)")";       L_INBOX="${L_INBOX:-$HOME/transcribe-inbox}"
  L_LIBRARY="$(_tilde "$(topo_get local.library_dir)")";   L_LIBRARY="${L_LIBRARY:-$HOME/transcribe-pipeline/speaker-library}"
  L_CONTEXTS="$(_tilde "$(topo_get local.contexts_dir)")"; L_CONTEXTS="${L_CONTEXTS:-$HOME/transcribe-pipeline/contexts}"

  echo "→ local: mkdir $L_INBOX/$NAME/, $L_LIBRARY/$NAME/"
  mkdir -p "$L_INBOX/$NAME" "$L_LIBRARY/$NAME"

  echo "→ local: deploy runtime context yaml(s) into $L_CONTEXTS/"
  mkdir -p "$L_CONTEXTS"
  python3 "$SCRIPT_DIR/extract_runtime_contexts.py" --src "$REPO_ROOT/workflow/contexts" --out "$L_CONTEXTS" \
    || echo "   WARN: extract emitted nothing — is $NAME's integrations.transcription block complete?"

  cat <<EOF

Bootstrap done for context '$NAME' (local — this machine, no SSH).

Next steps:
  1. Record anywhere and hand off via /debrief (or:
       skills/meeting-transcription/scripts/debrief_sync.sh push <audio> $NAME).
  2. (First meeting) Bootstrap voices:
       python bin/speaker_idcard.py --json <ctx>/<ts>/teams_out/teams.json
       python bin/apply_speaker_names.py --json ... --map "SPEAKER_00=Name,..." \\
              --library "$L_LIBRARY/$NAME" --save-embeddings
  NOTE: local mode still needs the compute stack (whisper.cpp + pyannote + venvs +
  HF token) installed on this machine — see references/deployment.md.
EOF
fi
