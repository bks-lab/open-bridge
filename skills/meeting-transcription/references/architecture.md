---
summary: "Full architecture of the meeting-transcription pipeline — machines, data flow, file layout, per-script roles"
type: reference
last_updated: 2026-07-02
---

# Architecture

## Three roles, one data flow

| Role | Machine | Why there |
|---|---|---|
| **Capture** (optional) | The capture Mac (env `CAPTURE_HOST`) | Audio Hijack license + the meetings happen here. Without a dedicated capture machine, record anywhere and hand audio off via `debrief_sync.sh push`. |
| **Worker** | The worker host (`infra/transcriptions/topology.yaml` → `worker.host`, env `TRANSCRIBE_WORKER` overrides) **or this same machine** when `mode: local` | Apple-silicon box (or your own machine); runs whisper.cpp (Metal) + pyannote (MPS). **Transcription only — no summarizing.** |
| **Summarizer + task-extraction** | in-session `/debrief` | Has the bridge context (name-conventions, board, open issues, contexts) that a headless worker `claude -p` lacks. Worker = mechanical transcription; interpretation lives here. |

Placement is set in `infra/transcriptions/topology.yaml`: `mode: remote` needs a
`worker.host` (SSH/Tailscale alias — no default); `mode: local` runs every stage
on this machine with no SSH. Recordings never block the user: capture writes a
file, launchd notices, the
rest is asynchronous. If the worker is asleep, bundles wait with a `.READY` flag
and a catch-up pass pushes them when it wakes.

## End-to-end flow

```
1. Audio Hijack records a meeting as one stereo MP3 (Mic→Left, Teams→Right)
   via captureEnabled=1 + splitChannels=true, into
   ~/Recordings/meetings/<context>/<date time>.mp3

2. launchd WatchPath (com.openbridge.transcribe-bundler) fires transcribe-bundler.sh:
   - waits until the MP3's mtime is stable (recording finished)
   - skips clips < 120 s (test presses → _short/)
   - bundles into <ts>/meeting.mp3 + manifest.yaml + .READY
   - rsyncs to worker-host:~/transcribe-inbox/<context>/<ts>/

3. launchd WatchPath (com.openbridge.transcribe-worker) fires transcribe-worker.sh:
   for each context subfolder, reads contexts/<ctx>.yaml (flat runtime extract —
   up to 5 keys: language, library, output, notify, mic_speaker), then per bundle:
   a. ffmpeg splits stereo → mic.wav (L) + teams.wav (R), 16 kHz mono
      · language = manifest > context > auto; if auto, detect_language.py votes
        over 3 windows (15/45/75 %) → forces de/en for ASR (else whisper auto)
   b. asr_whispercpp.py: whisper.cpp large-v3 (Metal) on mic.wav
                                           → mic_out/mic.json   (ASR only = the
      recording user, labelled with the context's mic_speaker — default "Me")
   c. teams = asr_whispercpp.py (ASR) then diarize_assign.py:
      pyannote community-1 on MPS (return_embeddings) assigns each phrase
      segment its speaker → teams_out/teams.json (SPEAKER_NN + 256-d vectors).
      Same embedding space as the old WhisperX --speaker_embeddings, so the
      voice library keeps matching. (engine details below; legacy CPU path via
      TRANSCRIBE_ENGINE=whisperx)
   d. speaker_naming.py: cosine-match each cluster's embedding to
      speaker-library/<ctx>/*.npy (≥0.60 → real name, else keep SPEAKER_NN)
   e. merge_transcripts.py: interleave mic + named-teams by timestamp →
      transcript-raw.md = the NAKED transcript (frontmatter records language)
   f. deliver transcript-raw.md → ~/Transcripts/<output>/<ts>.md on the worker
      (mirrored to the capture Mac when CAPTURE_HOST is set, plus a notify ping —
      e.g. iMessage on macOS — when the context sets notify: true; with an empty
      CAPTURE_HOST the sync script pulls from ~/Transcripts/<output>/ instead).
      **No summarizing on the worker** — the summary + task-extraction are done by
      the in-session /debrief (context-aware: name-conventions, board, open issues,
      contexts, prior meetings). A headless worker `claude -p` was context-blind →
      retired (summarize.py kept only as a manual fallback).
```

## Why these choices (so you can reason about changes)

- **2-track via splitChannels, not 2 recorders.** AH 4.5.9 captures Mic on L and
  app audio on R in one stereo file when `captureEnabled=1 + splitChannels=true`.
  One file, guaranteed clock-aligned. ffmpeg splits it on the worker. (v1 used 2
  separate recorders + an `onRecordingEnd` JS hook — abandoned because AH's
  automation API has **no shell access**; launchd WatchPath replaced it.)
- **Mic track is ASR-only.** It's always the same person (whoever wears the mic —
  the recording user), so diarization there is wasted work. The context's
  `mic_speaker` supplies the display name. The Teams track carries everyone else
  and gets the full diarization.
- **Identity by voice embedding, not transcription.** pyannote emits a 256-d
  embedding per speaker cluster. Matching that to a library fixes name
  hallucinations at the root (the "Bob → Rob" problem) and is stable across
  recordings where Whisper spells names differently.
- **Per-context libraries.** Voices don't transfer between audiences — your
  team's people ≠ a customer's people. Context = inbox subfolder = which
  library + language + output.
- **The summary lives in-session, not on the worker.** Claude in the bridge
  session is already the LLM and carries the context a headless run lacks; a
  local 32B model would be lower quality and add a machine dependency.
  `summarize.py` (headless `claude -p`) survives only as a manual fallback.

## Engine (ASR + diarization) — hybrid

The heavy compute runs **on the Apple-silicon GPU/MPS**, not the CPU:

- **ASR = whisper.cpp large-v3 (Metal)** — `asr_whispercpp.py` shells out to
  `whisper-cli` (brew `whisper-cpp`) with the `ggml-large-v3.bin` model and
  `-ml 50 -sow` (phrase-level segments, so a segment rarely straddles a speaker
  turn) plus `-mc 0` (no prior-text context — prevents the repetition loop
  whisper.cpp's unbounded default falls into; see troubleshooting.md). It is the
  *full* large-v3, not turbo.
- **Diarization + 256-d embeddings = pyannote on MPS** — `diarize_assign.py`
  uses WhisperX's `DiarizationPipeline(device="mps", return_embeddings=True)`
  (community-1) and assigns each ASR segment the max-overlap speaker. Reusing
  WhisperX's pipeline keeps the embedding space identical to the library, so
  existing `*.npy` voiceprints keep matching (verified: an existing voiceprint
  matched @ 0.90 against the unchanged library). `PYTORCH_ENABLE_MPS_FALLBACK=1`
  covers any op without an MPS kernel.

**Why not the old path / MLX:** WhisperX → faster-whisper → **CTranslate2 has no
Metal backend** (`cuda_count=0`, CPU-only on Apple Silicon) → the GPU + ANE
sat idle and a 38-min meeting took ~58 min. **MLX-Whisper** large-v3 thrashes
swap on a 16 GB box (unified-memory Metal buffers). whisper.cpp loads the GGML
model memory-disciplined → stable, real GPU use. **Measured (38-min 2-track
meeting):** hybrid total **26m37s** (mic ASR 12m01s + teams ASR 10m42s +
diarize 3m50s) vs old ~58 min ≈ **2.2×**, same large-v3 quality, speakers + order
correct. Fallback: `TRANSCRIBE_ENGINE=whisperx` in `transcribe-worker.sh` runs
the old CPU path unchanged. (`asr_mlx.py` is kept as the explored-but-rejected
MLX alternative; it needs a separate `~/venvs/mlx-asr`.)

## File layout

### This skill (source of truth, version-controlled)
```
skills/meeting-transcription/
  SKILL.md
  references/{architecture,operations,deployment,troubleshooting}.md
  prompts/                         DATA: language-keyed LLM prompts (peer to scripts/)
    meeting-summary-{de,en}.md
  scripts/                         CODE only — no data files here
    build_2track_session_v2.py     capture: generate AH .ah4session
    transcribe-bundler.sh          capture: launchd watch + bundle + rsync (context-aware)
    com.openbridge.transcribe-bundler.plist
    transcribe-worker.sh           worker: context loop + pipeline orchestration
    com.openbridge.transcribe-worker.plist
    asr_whispercpp.py              worker: ASR via whisper.cpp large-v3 (Metal) — default engine
    detect_language.py             worker: multi-window language vote when ctx/bundle = auto
    diarize_assign.py              worker: pyannote diarize on MPS + assign + embeddings
    asr_mlx.py                     (alternative ASR via MLX — explored, not used; see § Engine)
    voiceprint_backup.sh           weekly voiceprint pull wrapper (launchd)
    com.openbridge.voiceprint-backup.plist (Sun 09:00 voiceprint backup → identity/voiceprints/)
    merge_transcripts.py           interleave mic+teams → raw MD (+ language, mic_speaker label)
    speaker_naming.py              cosine-match clusters → library names
    speaker_idcard.py              print per-cluster quotes for human labelling
    apply_speaker_names.py         rename + persist embeddings (library bootstrap)
    extract_voice_sample.py        bootstrap a library entry from an audio clip
    summarize.py                   claude -p → structured summary (manual fallback only)
    extract_runtime_contexts.py    deploy: bridge contexts → flat worker yamls
    add_context.sh                 bridge-side bootstrap (remote OR local mkdirs + runtime-yaml deploy)
    debrief_sync.sh                bridge ↔ /debrief handoff (pull, push, voiceprints); remote or local transport per topology
    anchor_transcript.py           mechanical per-utterance anchors + .index.tsv (invoked by /debrief's gold path)
```

The `.plist` files ship with `REPLACE_ME_HOME` placeholders — the deploy step
substitutes the real `$HOME` (see deployment.md). `debrief_sync.sh` implements
the repo's documented worker contract (`docs/transcription-worker.md`):
`pull` / `push <audio> [ctx]` / `voiceprints pull|push`, driven by env
`BRIDGE_IMPORTS` + `TRANSCRIBE_CONTEXTS`.

**Contexts are NOT under `scripts/`.** They live in the bridge cluster-wrapper
at `workflow/contexts/<ctx>.yaml` under the `integrations.transcription:`
sub-block (schema: `IntegrationTranscription` in `workflow/contexts/_schema.yaml`).
See `SKILL.md` § Context discovery.

### Worker host (deployed runtime)
```
~/transcribe-pipeline/
  bin/            ← all *.py + *.sh from scripts/ (chmod +x)
  contexts/       ← <ctx>.yaml (flat runtime extracts — up to 5 keys:
                    language, library, output, notify, mic_speaker)
  prompts/        ← meeting-summary-{de,en}.md
  models/         ← ggml-large-v3.bin (whisper.cpp ASR model, ~3 GB)
  speaker-library/
    main/        alice.npy bob.npy carol.npy
    customer-x/  alice.npy (+ that audience's people as bootstrapped)
~/transcribe-inbox/
  main/       <ts>/{meeting.mp3, manifest.yaml, .READY, mic_out/, teams_out/,
                    teams-named.json, transcript-raw.md, transcript.md, .PROCESSED}
  customer-x/ <ts>/...
~/Transcripts/<output>/<ts>.md  (final delivery on the worker; mirrored to the
                                 capture Mac when CAPTURE_HOST is set)
HF token: keychain service hf-token-pyannote, fallback
  ~/.config/open-bridge/hf-token   (chmod 600, pyannote gate)
~/venvs/whisperx/               (Python 3.11 + whisperx 3.8.5 + pyannote.audio 4.x + torch 2.8 — runs ASR-wrapper + diarize on MPS)
/opt/homebrew/bin/whisper-cli   (brew whisper-cpp — the ASR engine, Metal)
# ~/venvs/mlx-asr/  exists only if the MLX alternative (asr_mlx.py) is used — not the default
~/Library/Logs/transcribe-{bundler,worker}.log
```

### Bundle state flags
`.READY` (capture done, ready for worker) · `.lock` (worker processing, atomic
mkdir) · `.PROCESSING` (in flight) · `.PROCESSED` (done) · `.FAILED` (error, will
retry) · `.PUSHED` (capture side: rsynced).

## launchd jobs

| Label | Machine | Trigger | Runs |
|---|---|---|---|
| `com.openbridge.transcribe-bundler` | capture Mac | WatchPath `~/Recordings/meetings` | bundler |
| `com.openbridge.transcribe-worker` | worker host | WatchPath `~/transcribe-inbox` | worker |

WatchPaths fire on changes within the watched directory (including context
subfolders). `ThrottleInterval` debounces AH's incremental fragment writes.
