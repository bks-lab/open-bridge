#!/usr/bin/env bash
# add_context.sh — bridge-side bootstrap for a transcription context.
#
# Runs LOCALLY (in the bridge repo). Does NOT create any yaml — the bridge
# context yaml at workflow/contexts/<name>.yaml is the single source of
# truth, and the user authors it themselves (copy from _template.yaml,
# fill `integrations.transcription`, validate with check-jsonschema).
# This script only bootstraps the remote dirs that the worker expects:
#
#   <worker>:~/transcribe-inbox/<name>/                       (drop-zone)
#   <worker>:~/transcribe-pipeline/speaker-library/<name>/    (voice library)
#   <capture>:~/Recordings/meetings/<name>/                   (Audio Hijack target, optional)
#
# The extract+rsync that generates ~/transcribe-pipeline/contexts/<name>.yaml
# is a separate step (see references/deployment.md § Redeploy after editing
# a context).
#
# Hosts are env-driven: TRANSCRIBE_WORKER is required; CAPTURE_HOST is
# optional (empty/unset = skip the capture-side dir).
#
# Usage:  TRANSCRIBE_WORKER=worker-host add_context.sh <name> [capture_host]
#   name          context slug — MUST match workflow/contexts/<name>.yaml
#   capture_host  SSH/Tailscale host for the recording folder
#                 (default: $CAPTURE_HOST; empty = skip the capture step)
#
# History: an earlier version ran ON the worker and authored its own
# ~/transcribe-pipeline/contexts/<name>.yaml. That duplicate source-of-truth
# is gone; this script now only does the dir bootstrap.

set -euo pipefail

NAME="${1:?usage: add_context.sh <name> [capture_host]}"
CAPTURE="${2:-${CAPTURE_HOST:-}}"
WORKER="${TRANSCRIBE_WORKER:-}"

if [[ -z "$WORKER" ]]; then
  echo "no worker configured — set TRANSCRIBE_WORKER (should match integrations.transcription.worker.host in bridge-config.yaml)" >&2
  exit 1
fi

# Resolve bridge repo root from this script's location (scripts/ → skill → repo).
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
BRIDGE_CTX="$REPO_ROOT/workflow/contexts/$NAME.yaml"

[[ "$NAME" =~ ^[a-z0-9-]+$ ]] || { echo "name must be [a-z0-9-]+"; exit 1; }

# Refuse to bootstrap remote dirs without a bridge yaml. Otherwise we'd
# create orphan dirs the worker has no config for, exactly the drift this
# refactor exists to prevent.
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
# extract step will skip it and the worker won't see this context.
if command -v yq >/dev/null 2>&1; then
  if [[ "$(yq -r '.integrations.transcription // ""' "$BRIDGE_CTX")" == "" ]]; then
    echo "ERROR: $BRIDGE_CTX has no integrations.transcription block — add it first" >&2
    exit 2
  fi
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

Bootstrap done for context '$NAME'.

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
