#!/usr/bin/env bash
# voicememo-bundler.sh — capture-side watcher for the iPhone Voice Memos folder
# (synced to this Mac via iCloud). Watches the flat, non-recursive Recordings/
# folder for new *.m4a files and pushes eligible ones into the "voicememo"
# transcription context via debrief_sync.sh push (async — the transcript shows
# up later via a separate pull, not this script's concern).
#
# Sibling of transcribe-bundler.sh (same idioms: log() style, remote_up()
# reachability probe, idempotent-push marker, launchd WatchPaths debounce) —
# see that script + docs/transcription-worker.md for the wider pipeline.
#
# ─────────────────────────────────────────────────────────────────────────
# SAFETY — READ THIS BEFORE TOUCHING CUTOFF_DATE OR THE BASELINE FILE
# The Recordings folder holds ~15 YEARS of personal voice memos (oldest seen:
# 2011). Two INDEPENDENT gates must both agree a file is new before it is ever
# pushed to the transcription worker — either one alone skipping it is enough
# to exclude it, neither one is "the" authority on its own:
#
#   1. BASELINE — a plain list of every filename that already existed at
#      2026-08-13 (~/Library/Application Support/bridge-voicememo/baseline.txt,
#      one snapshot, taken once, never regenerated). Anything in that file is
#      pre-existing by definition, permanently, regardless of what its own
#      filename date says. This is the PRIMARY signal — chosen specifically to
#      avoid depending on Voice Memos' own iCloud folder-sync (unreliable
#      timing, encrypted folder names, and this script never writes to Apple's
#      database — see the folder note below).
#   2. CUTOFF_DATE — the 8-digit YYYYMMDD filename prefix, string-compared
#      against a hardcoded constant. Kept as a redundant second check even
#      though the baseline already covers this, in case the baseline file is
#      ever lost/corrupted/regenerated wrong — cheap insurance, not the
#      primary mechanism.
#
# No "first run vs. later runs" branch exists in either check, so there is no
# code path that treats an old file differently based on when the script
# happens to run. Getting this wrong means silently exfiltrating over a
# decade of private audio to a remote machine.
# ─────────────────────────────────────────────────────────────────────────
#
# Filenames observed in the wild (both handled — see the match regex below):
#   "20260813 095714-70E08E4C.m4a"   date, space, time, dash, uuid, .m4a
#   "20260718 184700.m4a"            date, space, time, .m4a (no uuid)
# Date = chars 1-8 (YYYYMMDD), time = chars 10-15 (HHMMSS), a literal space
# between them. Only *.m4a is considered — .waveform sidecar files and the
# "Capture" subdirectory are ignored by construction (the glob below is a
# non-recursive *.m4a pattern, so it never matches either).
#
# This folder is Apple's — Voice Memos tracks its exact contents in its own
# CoreData/CloudKit-backed database. This script is READ-ONLY with respect to
# it: it never creates marker/sidecar files, renames, or moves anything
# inside Recordings/, and never writes to CloudRecordings.db (a write from
# outside Voice Memos' own code wouldn't go through Core Data's change-
# tracking, so — separately from any risk to the store itself — it likely
# wouldn't even sync anywhere, defeating the point). All state this script
# needs lives entirely outside that folder:
#   ~/Library/Application Support/bridge-voicememo/baseline.txt        (see SAFETY block)
#   ~/Library/Application Support/bridge-voicememo/pushed/<basename>.done  (already-pushed marker, one empty file per recording)
#
# Drop-in: ~/bin/voicememo-bundler.sh   Logs: ~/Library/Logs/voicememo-bundler.log
# Triggered by launchd WatchPath (com.bks.voicememo-bundler.plist).
#
# NOTE: this script runs on the capture machine (Michael's Mac, where the
# Voice Memos folder lives), but unlike transcribe-bundler.sh it is NOT
# fully decoupled from the Bridge repo: it calls back into it to invoke
# debrief_sync.sh, the repo-side half of the push contract, which has no
# standalone existence outside it. DEBRIEF_SYNC and the WORKER lookup below
# therefore assume this script runs from its own position inside a Bridge
# checkout, the same assumption debrief_sync.sh and add_context.sh already
# make about their own location: resolved from
# ${BASH_SOURCE[0]} at runtime, never a hardcoded path or hostname. A flat
# `cp` deploy away from the repo (see the plist's "Install" step below)
# breaks this; deploy via a symlink into the repo copy instead, or point the
# launchd job directly at the in-repo path.

set -euo pipefail
export LC_ALL=C   # deterministic byte-wise string comparison for the date filter below

# --- Constants ---------------------------------------------------------------
SOURCE="$HOME/Library/Group Containers/group.com.apple.VoiceMemos.shared/Recordings"
CUTOFF_DATE="20260813"          # YYYYMMDD — see the SAFETY block above. Never lower this without re-reading it.
MIN_DURATION_SECS=5             # accidental button-taps confirmed at 3.3s / 3.77s on this phone
STABLE_SECS=5                   # mtime must be at least this old — still-syncing files are skipped, not retried in a loop
CONTEXT="voicememo"             # transcription context on the worker (already provisioned)

# Repo root resolved from this script's own location (mirrors debrief_sync.sh
# and add_context.sh), never a hardcoded path or username. Only DEBRIEF_SYNC
# is load-bearing at runtime (WORKER falls back to legacy bridge-config.yaml
# and ultimately fails loud below, so a broken REPO_ROOT there just means an
# empty WORKER, not a wrong one).
#
# The location is resolved THROUGH symlinks. The launcher execs a link such as
# ~/bin/voicememo-bundler.sh, and dirname of the link itself would put
# REPO_ROOT three levels above ~/bin, where neither topology.yaml nor
# debrief_sync.sh exists. A plain readlink loop rather than `readlink -f` or
# `realpath`, because older macOS ships neither.
SCRIPT_PATH="${BASH_SOURCE[0]}"
while [[ -L "$SCRIPT_PATH" ]]; do
  link_target="$(readlink "$SCRIPT_PATH")"
  case "$link_target" in
    /*) SCRIPT_PATH="$link_target" ;;
    *)  SCRIPT_PATH="$(dirname "$SCRIPT_PATH")/$link_target" ;;
  esac
done
SCRIPT_DIR="$(cd "$(dirname "$SCRIPT_PATH")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/../../.." && pwd)"
CONFIG="$REPO_ROOT/bridge-config.yaml"
TOPOLOGY="$REPO_ROOT/infra/transcriptions/topology.yaml"
DEBRIEF_SYNC="$SCRIPT_DIR/debrief_sync.sh"

# Read a dotted key from a YAML file (mirrors debrief_sync.sh / add_context.sh).
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
if node is not None and not isinstance(node, (dict, list)):
    print(node)
' "$1" "$2" 2>/dev/null || true
}

# Worker host: same three-tier resolution as debrief_sync.sh, env override >
# infra/transcriptions/topology.yaml (placement SoT) > legacy bridge-config.yaml
# location. No hardcoded hostname fallback: an unconfigured worker fails loud
# below instead of silently defaulting to some other instance's machine.
WORKER="${TRANSCRIBE_WORKER:-$(yaml_get "$TOPOLOGY" worker.host)}"
[[ -z "$WORKER" ]] && WORKER="$(yaml_get "$CONFIG" integrations.transcription.worker.host)"

LOG="$HOME/Library/Logs/voicememo-bundler.log"
# Per-file marker files, not one shared log: a lost/corrupted marker only
# affects the one recording it names (a harmless resend), instead of a single
# flat pushed.log loss/corruption resending the ENTIRE post-cutoff history.
# touch is atomic at the filesystem level, so there's no read-then-write race
# between already_pushed() and mark_pushed() either.
PUSHED_DIR="$HOME/Library/Application Support/bridge-voicememo/pushed"
# One-time snapshot of every filename that existed at 2026-08-13 — see the
# SAFETY block above. Deliberately never regenerated by this script (a script
# that could silently move its own baseline forward would defeat the point).
BASELINE="$HOME/Library/Application Support/bridge-voicememo/baseline.txt"
# Liveness stamp, touched only by a run that could actually SEE the folder. A
# liveness check must read this file, never the log's freshness: a blind run
# has nothing to count and so logs nothing, and a variant that logged an ERROR
# on every run would keep the log fresh for the whole outage.
HEARTBEAT="$HOME/Library/Application Support/bridge-voicememo/last-scan-ok"
# Present exactly while an outage lasts and holds the UTC time it began, so the
# blind line is written once per outage instead of once per run.
BLIND_MARKER="$HOME/Library/Application Support/bridge-voicememo/scan-blind-since"

mkdir -p "$(dirname "$LOG")"
mkdir -p "$PUSHED_DIR"

log() { printf '%s [voicememo] %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*" >> "$LOG"; }

# Same-machine deployments (TRANSCRIBE_MODE=local — see com.bks.voicememo-bundler.plist's
# "SAME-MACHINE DEPLOYMENT" note) never need this: debrief_sync.sh's own local
# mode never shells out to ssh either, and self-ssh to $WORKER's own hostname
# has no standing key on a machine that never needed to log into itself.
remote_up() {
  [[ "${TRANSCRIBE_MODE:-}" == local ]] && return 0
  ssh -o ConnectTimeout=3 -o BatchMode=yes "$WORKER" 'true' 2>/dev/null
}

already_pushed() { [[ -f "$PUSHED_DIR/$(basename "$1").done" ]]; }
mark_pushed() { touch "$PUSHED_DIR/$(basename "$1").done"; }

# grep, not an associative array: macOS ships bash 3.2 by default (no
# `declare -A`), and this script must run under whatever bash launchd finds
# first on PATH, not necessarily a homebrew bash 4+. 166 lines makes the
# per-file grep cost irrelevant either way.
in_baseline() { grep -Fxq "$(basename "$1")" "$BASELINE" 2>/dev/null; }

# Fail loud rather than silently default to the wrong machine: WORKER is only
# actually dereferenced outside local mode (remote_up() short-circuits true
# under TRANSCRIBE_MODE=local and never touches it), so only require it then.
if [[ -z "$WORKER" && "${TRANSCRIBE_MODE:-}" != local ]]; then
  log "ERROR no transcription worker configured: set worker.host in infra/transcriptions/topology.yaml (or TRANSCRIBE_WORKER)"
  exit 0
fi

if [[ ! -d "$SOURCE" ]]; then
  log "ERROR source dir missing: $SOURCE"
  exit 0
fi

if [[ ! -f "$BASELINE" ]]; then
  # Fail closed: no baseline means we cannot tell old from new, so treat
  # EVERYTHING as unpushable rather than risk the opposite mistake.
  log "ERROR baseline missing: $BASELINE — refusing to process anything until it exists"
  exit 0
fi

# --- Scan (flat, non-recursive — never descends into Recordings/Capture) ----
shopt -s nullglob

baseline_count=0
precutoff_count=0
unrecognized_count=0
short_count=0
wait_count=0
# Every *.m4a the glob could see, whichever gate skips it afterwards. Zero
# while the baseline names files means this run was blind (see the end).
seen_count=0

for file in "$SOURCE"/*.m4a; do
  [[ -f "$file" ]] || continue
  seen_count=$((seen_count + 1))
  base="$(basename "$file")"

  # Parse "YYYYMMDD HHMMSS" or "YYYYMMDD HHMMSS-<uuid>" prefix. Anything that
  # doesn't match this shape is left alone (never pushed) rather than guessed at.
  if [[ "$base" =~ ^([0-9]{8})\ ([0-9]{6})(-[0-9A-Za-z]+)?\.m4a$ ]]; then
    date_part="${BASH_REMATCH[1]}"
  else
    unrecognized_count=$((unrecognized_count + 1))
    continue
  fi

  # THE primary gate — is this filename in the one-time snapshot of what
  # already existed? Checked first since it's the authoritative signal (see
  # SAFETY block); the date check right after is redundant-on-purpose backup.
  if in_baseline "$file"; then
    baseline_count=$((baseline_count + 1))
    continue
  fi

  # Second, independent gate — plain string comparison of two equal-length,
  # zero-padded 8-digit numeric strings (LC_ALL=C above makes this byte-wise,
  # so it is exactly numeric comparison, not locale-dependent collation).
  if [[ "$date_part" < "$CUTOFF_DATE" ]]; then
    precutoff_count=$((precutoff_count + 1))
    continue
  fi

  already_pushed "$file" && continue

  # Still-syncing guard: skip quietly, next WatchPath fire catches it once stable.
  # Guarded (not a bare assignment): a file that vanishes/gets evicted between
  # glob-expansion and here must not kill the whole run under set -e — that
  # would silently stall every later file in this batch, indefinitely if the
  # same offending file persists across runs.
  mtime=$(stat -f %m "$file" 2>/dev/null) || { log "skip vanished: $base"; continue; }
  now=$(date +%s)
  age=$(( now - mtime ))
  if (( age < STABLE_SECS )); then
    wait_count=$((wait_count + 1))
    continue
  fi

  # Duration filter — leave short files in place, untouched (this is Apple's
  # folder, not ours; no _short/ move here unlike the meetings bundler).
  # `|| true` on the pipeline: under pipefail, a non-zero afinfo (unreadable/
  # evicted file) would otherwise kill the whole script here too — same class
  # of bug as the stat guard above, so the fallback below must actually be
  # reachable instead of set -e firing first.
  dur=$(afinfo "$file" 2>/dev/null | awk -F': ' '/estimated duration/ {print int($2)}') || true
  dur="${dur:-0}"
  if (( dur < MIN_DURATION_SECS )); then
    short_count=$((short_count + 1))
    continue
  fi

  if ! remote_up; then
    log "deferred $base — $WORKER unreachable"
    continue
  fi

  log "pushing $base (${dur}s)"
  if "$DEBRIEF_SYNC" push "$file" "$CONTEXT" >> "$LOG" 2>&1; then
    mark_pushed "$file"
    log "ok $base"
  else
    log "ERROR push $base (exit $?)"
  fi
done

# Batched summaries — thousands of old files must never produce thousands of
# log lines. Only genuine push attempts (above) get their own line.
if (( baseline_count > 0 )); then
  log "skipped-baseline $baseline_count file(s) present in the pre-existing snapshot"
fi
if (( precutoff_count > 0 )); then
  log "skipped-precutoff $precutoff_count file(s) older than $CUTOFF_DATE"
fi
if (( unrecognized_count > 0 )); then
  log "skipped-unrecognized $unrecognized_count file(s) — filename did not match expected pattern"
fi
if (( short_count > 0 )); then
  log "skipped-short $short_count file(s) under ${MIN_DURATION_SECS}s"
fi
if (( wait_count > 0 )); then
  log "skipped-unstable $wait_count file(s) — mtime under ${STABLE_SECS}s old, will retry"
fi

# --- Blind-scan guard + liveness stamp --------------------------------------
# A folder that stats fine but lists nothing is the failure this block exists
# for: a privacy or container-protection denial looks exactly like that, and
# before this guard every such run exited 0 without a single log line. The
# baseline makes the case decidable. It names recordings this script never
# removes, so seeing none of them means the run could not look, not that there
# was nothing to find. An empty baseline (fresh machine) keeps zero legitimate.
# Known edge: deleting every recording on the phone also lands here, which the
# log line names as "or was emptied".
baseline_entries=$(grep -c . "$BASELINE" 2>/dev/null || true)
if (( seen_count == 0 && ${baseline_entries:-0} > 0 )); then
  if [[ ! -f "$BLIND_MARKER" ]]; then
    date -u +'%Y-%m-%dT%H:%M:%SZ' > "$BLIND_MARKER"
    log "ERROR scan-blind: 0 *.m4a visible in $SOURCE although the baseline lists $baseline_entries; the folder is unreadable (privacy or container protection) or was emptied, nothing can be collected until this clears"
  fi
  # Non-zero so the service manager's last exit code shows the outage as well.
  # The heartbeat stamp is deliberately left untouched.
  exit 1
fi

if [[ -f "$BLIND_MARKER" ]]; then
  log "recovered: $seen_count *.m4a visible again, blind since $(cat "$BLIND_MARKER")"
  rm -f "$BLIND_MARKER"
fi
touch "$HEARTBEAT"
