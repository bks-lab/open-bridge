#!/usr/bin/env bash
# transcribe-worker.sh — context-aware meeting-transcription worker.
# Triggered by launchd WatchPath (com.openbridge.transcribe-worker.plist) on
# the worker host.
#
# Inbox layout (context = subfolder name):
#   ~/transcribe-inbox/<context>/<ts>/meeting.mp3
# Each <context> maps to ~/transcribe-pipeline/contexts/<context>.yaml — a
# flat key:value file written by skills/meeting-transcription/scripts/extract_runtime_contexts.py
# from the bridge's workflow/contexts/<ctx>.yaml `integrations.transcription` block.
# Do NOT edit these yamls on the worker; they get overwritten on every deploy.
#   language:    de|en|auto   Whisper language hint (auto = detect)
#   library:     <dir>        → speaker-library/<dir>/*.npy
#   output:      <dir>        → ~/Transcripts/<dir>/ (worker; optionally pushed
#                              back to $CAPTURE_HOST)
#   notify:      true|false   iMessage on completion
#   mic_speaker: <name>       label for the dedicated mic track (default "Me")
#
# Manifest `tracks:` (default dual) picks the input layout:
#   dual   — real 2-track (Audio Hijack): L=mic (the recording user), R=Teams.
#            The 2-track default.
#   single — stereo mix / mono download: downmix to one diarized teams track,
#            skip the mic path (no false mic-owner labels). Opt-in per bundle.
#
# Per bundle:
#   1. ffmpeg: dual → split L/R; single → downmix to teams.wav (+ empty mic.json)
#   2. HYBRID ASR+diarize (large-v3 quality, GPU/MPS — not the old CPU CTranslate2):
#        mic   : asr_whispercpp.py (whisper.cpp large-v3, Metal)            → mic.json
#        teams : asr_whispercpp.py + diarize_assign.py (pyannote on MPS,
#                same 256-d embedding space as the library)                 → teams.json
#      Set TRANSCRIBE_ENGINE=whisperx to fall back to the old CPU path.
#   3. speaker_naming.py — match clusters to the context's voice library
#   4. merge_transcripts.py → transcript-raw.md  (the NAKED transcript = output)
#   5. deliver transcript-raw.md → ~/Transcripts/<output>/ (+ optional capture
#      machine).  NO summary here — summarizing is the in-session /debrief's
#      job (it has the bridge context a headless worker `claude -p` lacks).
#      Worker = pure transcription; interpretation happens in /debrief. (A
#      worker-side summarizer was removed from this pipeline: it was
#      context-blind; summarize.py is kept only as a manual headless fallback.)
#
# Idempotent: atomic .lock; skips already-.PROCESSED bundles.
# Failure: leaves .FAILED; bundle stays for re-run.
#
# Deploy: ~/transcribe-pipeline/bin/transcribe-worker.sh
# Logs:   ~/Library/Logs/transcribe-worker.log

set -uo pipefail

INBOX="$HOME/transcribe-inbox"
PIPE="$HOME/transcribe-pipeline"
VENV="$HOME/venvs/whisperx"
CAPTURE_HOST="${CAPTURE_HOST:-}"   # SSH/Tailscale name of the capture machine (optional push target; empty = skip)
LOG="$HOME/Library/Logs/transcribe-worker.log"

mkdir -p "$INBOX" "$(dirname "$LOG")"

log()  { printf '%s [worker] %s\n' "$(date -u +'%Y-%m-%dT%H:%M:%SZ')" "$*" >> "$LOG"; }
have() { command -v "$1" >/dev/null 2>&1; }

# Read a flat top-level key from a simple YAML file (no nesting).
cfg() { awk -F': *' -v k="$2" '$1==k {sub(/[ \t]*#.*/,"",$2); gsub(/^[ \t]+|[ \t]+$/,"",$2); print $2; exit}' "$1" 2>/dev/null; }

# ── Pre-flight ──────────────────────────────────────────────────────────────
[[ -d "$VENV" ]] || { log "FATAL: venv missing at $VENV"; exit 1; }
# shellcheck disable=SC1091
source "$VENV/bin/activate"
have ffmpeg   || { log "FATAL: ffmpeg not in PATH"; exit 1; }
have whisperx || { log "FATAL: whisperx not in venv"; exit 1; }

HF_TOKEN="$(security find-generic-password -a "$USER" -s 'hf-token-pyannote' -w 2>/dev/null || true)"
[[ -z "$HF_TOKEN" && -f "$HOME/.config/open-bridge/hf-token" ]] && HF_TOKEN="$(cat "$HOME/.config/open-bridge/hf-token")"
if [[ -z "$HF_TOKEN" ]]; then
  log "FATAL: HF token missing — keychain (hf-token-pyannote) empty AND ~/.config/open-bridge/hf-token absent"
  exit 1
fi

process_bundle() {
  local bundle="$1" ctx="$2" lang="$3" libdir="$4" outdir="$5" ctx_mspk="${6:-}"
  local ts; ts="$(basename "$bundle")"
  [[ "$ts" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}-[0-9]{6}$ ]] || return 0
  [[ -f "$bundle/.READY" ]] || return 0
  [[ -f "$bundle/.PROCESSED" ]] && return 0
  # A prior run left .FAILED → don't auto-retry on every WatchPath fire (that
  # spins on deterministic failures). Clear .FAILED (+ re-touch .READY) to retry.
  [[ -f "$bundle/.FAILED" ]] && { log "skip $ctx/$ts — .FAILED present (clear it to retry)"; return 0; }
  mkdir "$bundle/.lock" 2>/dev/null || { log "skip $ctx/$ts — locked"; return 0; }

  log "── $ctx/$ts (lang=$lang lib=$libdir) ──"
  touch "$bundle/.PROCESSING"
  local start_epoch; start_epoch=$(date +%s)
  local LIB="$PIPE/speaker-library/$libdir"
  local mp3="$bundle/meeting.mp3"

  if [[ ! -f "$mp3" ]]; then
    log "ERROR $ts — meeting.mp3 missing"; touch "$bundle/.FAILED"; rmdir "$bundle/.lock"; return 0
  fi

  # 1. Prepare tracks. Manifest `tracks:` selects the layout; missing → dual,
  #    so Audio-Hijack 2-track bundles (the 2-track default) behave exactly as
  #    before.
  #    dual   = real 2-track: L=mic→always the mic owner, R=Teams (split hard).
  #    single = stereo mix / mono download (no separate mic): downmix everything
  #             to one diarized track, skip the mic path. merge then gets an empty
  #             mic.json and adds no false mic-owner lines — every speaker (incl.
  #             the mic owner) is separated by voice and matched via the library.
  local tracks; tracks=$(cfg "$bundle/manifest.yaml" tracks)
  [[ -z "$tracks" ]] && tracks="dual"
  mkdir -p "$bundle/mic_out" "$bundle/teams_out"

  if [[ "$tracks" == "single" ]]; then
    if [[ ! -f "$bundle/teams.wav" ]]; then
      log "ffmpeg downmix (single-track) → teams.wav"
      ffmpeg -y -hide_banner -loglevel error -i "$mp3" \
        -ar 16000 -ac 1 "$bundle/teams.wav" \
        2>>"$LOG" || { log "ERROR $ts ffmpeg downmix"; touch "$bundle/.FAILED"; rmdir "$bundle/.lock"; return 0; }
    fi
    # Empty mic track: no dedicated mic channel in single-track mode.
    [[ -f "$bundle/mic_out/mic.json" ]] || printf '{"segments": []}\n' > "$bundle/mic_out/mic.json"
  else
    if [[ ! -f "$bundle/mic.wav" || ! -f "$bundle/teams.wav" ]]; then
      log "ffmpeg split (dual-track)"
      # -map_channel was removed in ffmpeg 7+. Use channelsplit to break the
      # stereo input into L=mic / R=teams mono tracks.
      ffmpeg -y -hide_banner -loglevel error -i "$mp3" \
        -filter_complex "[0:a]channelsplit=channel_layout=stereo[L][R]" \
        -map "[L]" -ar 16000 -ac 1 "$bundle/mic.wav" \
        -map "[R]" -ar 16000 -ac 1 "$bundle/teams.wav" \
        2>>"$LOG" || { log "ERROR $ts ffmpeg"; touch "$bundle/.FAILED"; rmdir "$bundle/.lock"; return 0; }
    fi
  fi

  # Language: manifest override > context default > auto. When the resolved value
  # is "auto" (or empty), run a MULTI-WINDOW detect across the recording and force
  # the winner — robust against the opening-smalltalk misdetect that whisper's own
  # single-window auto (first ~30 s) falls into, which is why contexts used to be
  # hard-pinned to one language (and a German daily came out English). See
  # detect_language.py. A forced de/en (manifest or context) is untouched.
  local LANG_OPT=()
  local mlang; mlang=$(cfg "$bundle/manifest.yaml" language)
  [[ -z "$mlang" ]] && mlang="$lang"
  [[ -z "$mlang" ]] && mlang="auto"
  if [[ "$mlang" == "auto" ]]; then
    log "language: auto — multi-window detect on teams.wav"
    local det; det=$(python "$PIPE/bin/detect_language.py" --audio "$bundle/teams.wav" 2>>"$LOG")
    if [[ -n "$det" ]]; then mlang="$det"; log "language: $mlang (multi-window vote)";
    else mlang="auto"; log "language: detect failed → whisper single-window auto"; fi
  else
    log "language: $mlang (forced)"
  fi
  [[ "$mlang" != "auto" ]] && LANG_OPT=(--language "$mlang")

  # 2. ASR + diarize. Hybrid (default): large-v3 quality on the GPU/MPS —
  #    whisper.cpp for ASR (Metal), pyannote on MPS for diarize+embeddings.
  #    The old CPU CTranslate2 path swapped the GPU/ANE idle and was ~2×
  #    slower; it stays available via TRANSCRIBE_ENGINE=whisperx.
  local engine="${TRANSCRIBE_ENGINE:-hybrid}"
  local asr_lang="$mlang"   # concrete de/en (forced or voted) or "auto" if detect failed

  if [[ "$engine" == "hybrid" ]]; then
    # 2a. mic — ASR only (always the mic owner)
    if [[ ! -f "$bundle/mic_out/mic.json" ]]; then
      log "ASR mic (whisper.cpp large-v3)"
      python "$PIPE/bin/asr_whispercpp.py" --audio "$bundle/mic.wav" \
        --out "$bundle/mic_out/mic.json" --language "$asr_lang" \
        >>"$LOG" 2>&1 || { log "ERROR $ts asr-mic"; touch "$bundle/.FAILED"; rmdir "$bundle/.lock"; return 0; }
    fi
    # 2b. teams — ASR (whisper.cpp) then diarize+embeddings on MPS (pyannote).
    if [[ ! -f "$bundle/teams_out/teams.json" ]]; then
      log "ASR teams (whisper.cpp large-v3)"
      python "$PIPE/bin/asr_whispercpp.py" --audio "$bundle/teams.wav" \
        --out "$bundle/teams_out/teams_asr.json" --language "$asr_lang" \
        >>"$LOG" 2>&1 || { log "ERROR $ts asr-teams"; touch "$bundle/.FAILED"; rmdir "$bundle/.lock"; return 0; }
      log "diarize teams (pyannote on MPS) + embeddings"
      python "$PIPE/bin/diarize_assign.py" --asr "$bundle/teams_out/teams_asr.json" \
        --audio "$bundle/teams.wav" --out "$bundle/teams_out/teams.json" \
        --device mps --hf-token "$HF_TOKEN" \
        >>"$LOG" 2>&1 || { log "ERROR $ts diarize-teams"; touch "$bundle/.FAILED"; rmdir "$bundle/.lock"; return 0; }
    fi
  else
    # Legacy CPU path (CTranslate2, no Metal) — kept as a fallback.
    if [[ ! -f "$bundle/mic_out/mic.json" ]]; then
      log "WhisperX mic (CPU fallback)"
      whisperx "$bundle/mic.wav" --model large-v3 "${LANG_OPT[@]}" \
        --compute_type int8 --batch_size 4 --device cpu \
        --output_format json --output_dir "$bundle/mic_out" \
        >>"$LOG" 2>&1 || { log "ERROR $ts WhisperX-mic"; touch "$bundle/.FAILED"; rmdir "$bundle/.lock"; return 0; }
    fi
    if [[ ! -f "$bundle/teams_out/teams.json" ]]; then
      log "WhisperX teams + diarize (CPU fallback)"
      whisperx "$bundle/teams.wav" --model large-v3 "${LANG_OPT[@]}" \
        --compute_type int8 --batch_size 4 --device cpu \
        --diarize --diarize_model "pyannote/speaker-diarization-community-1" \
        --speaker_embeddings --hf_token "$HF_TOKEN" \
        --output_format json --output_dir "$bundle/teams_out" \
        >>"$LOG" 2>&1 || { log "ERROR $ts WhisperX-teams"; touch "$bundle/.FAILED"; rmdir "$bundle/.lock"; return 0; }
    fi
  fi

  # 3. Speaker naming against the context's voice library
  log "speaker naming (lib=$libdir)"
  python "$PIPE/bin/speaker_naming.py" \
    --teams-wav "$bundle/teams.wav" --teams-json "$bundle/teams_out/teams.json" \
    --library "$LIB" --out "$bundle/teams-named.json" --threshold 0.60 \
    >>"$LOG" 2>&1 || log "WARN $ts speaker_naming non-fatal (raw SPEAKER_NN kept)"
  # Guarantee the merge input exists even if naming failed → fall back to raw
  # diarized labels, so step 4 never hard-fails on a missing teams-named.json.
  [[ -f "$bundle/teams-named.json" ]] || cp "$bundle/teams_out/teams.json" "$bundle/teams-named.json"

  # 4. Merge → raw MD
  # Mic-track speaker label: manifest override > context value > "Me".
  local mspk; mspk=$(cfg "$bundle/manifest.yaml" mic_speaker)
  [[ -z "$mspk" ]] && mspk="$ctx_mspk"
  [[ -z "$mspk" ]] && mspk="Me"
  log "merge → raw MD (mic_speaker=$mspk)"
  python "$PIPE/bin/merge_transcripts.py" \
    --mic "$bundle/mic_out/mic.json" --teams "$bundle/teams-named.json" \
    --manifest "$bundle/manifest.yaml" --mic-speaker "$mspk" \
    --out "$bundle/transcript-raw.md" \
    >>"$LOG" 2>&1 || { log "ERROR $ts merge"; touch "$bundle/.FAILED"; rmdir "$bundle/.lock"; return 0; }

  # 5. Deliver the NAKED transcript. NO summary on the worker (no `claude -p`):
  #    summarizing is the job of the in-session /debrief, which has the bridge
  #    context (name-conventions, board, open issues, contexts, prior meetings,
  #    MEMORY) that a headless worker-side `claude -p` lacks. A context-blind
  #    summary distorts names + significance and then propagates as "the record"
  #    — so the worker stays pure transcription; interpretation happens where the
  #    ground truth lives. Canonical store is HERE on the worker (~/Transcripts/).
  local localdest="$HOME/Transcripts/$outdir"
  mkdir -p "$localdest"
  cp "$bundle/transcript-raw.md" "$localdest/${ts}.md"
  log "stored naked transcript $outdir/${ts}.md on the worker host"
  # Best-effort push to the capture machine if CAPTURE_HOST is set and Remote
  # Login is on there (optional convenience; empty CAPTURE_HOST = skip).
  if [[ -n "$CAPTURE_HOST" ]] && ssh -o ConnectTimeout=3 -o BatchMode=yes "$CAPTURE_HOST" "mkdir -p ~/Transcripts/$outdir" 2>/dev/null; then
    rsync -av "$bundle/transcript-raw.md" "$CAPTURE_HOST:~/Transcripts/$outdir/${ts}.md" >>"$LOG" 2>&1 \
      && log "pushed to $CAPTURE_HOST" || log "WARN push to capture machine failed"
  fi

  rm -f "$bundle/mic.wav" "$bundle/teams.wav"
  log "done $ctx/$ts in $(( $(date +%s) - start_epoch ))s"
  touch "$bundle/.PROCESSED"; rm -f "$bundle/.PROCESSING" "$bundle/.FAILED"
  rmdir "$bundle/.lock" 2>/dev/null || true
}

# ── Context loop ──────────────────────────────────────────────────────────────
shopt -s nullglob
for ctxdir in "$INBOX"/*/; do
  ctx="$(basename "$ctxdir")"
  cfgfile="$PIPE/contexts/$ctx.yaml"
  if [[ ! -f "$cfgfile" ]]; then
    log "WARN no context config for '$ctx' ($cfgfile) — skipping. Create via add_context.sh"
    continue
  fi
  lang="$(cfg "$cfgfile" language)";  lang="${lang:-auto}"
  libdir="$(cfg "$cfgfile" library)"; libdir="${libdir:-$ctx}"
  outdir="$(cfg "$cfgfile" output)";  outdir="${outdir:-$ctx}"
  mic_speaker="$(cfg "$cfgfile" mic_speaker)"   # may be empty → resolved in process_bundle
  for bundle in "$ctxdir"*/; do
    process_bundle "$bundle" "$ctx" "$lang" "$libdir" "$outdir" "$mic_speaker"
  done
done
exit 0
