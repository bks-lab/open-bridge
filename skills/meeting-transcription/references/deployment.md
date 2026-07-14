---
summary: "Provision the worker host + optional capture Mac from scratch; redeploy scripts; what a provisioned install looks like"
type: reference
last_updated: 2026-07-02
---

# Deployment

## Prerequisites

What must exist before the provisioning steps below will work. The pipeline spans
three roles; one machine can play several (the worker host does the transcription,
an optional capture Mac records, both reach the bridge repo).

**Worker** (does the transcription — the heavy machine):
- **macOS on Apple Silicon** (MPS-accelerated) is the tested target. The scripts
  assume `launchd` + `~/.zprofile` + Homebrew. A Linux box works in principle but
  the `.plist` LaunchAgents and zprofile sourcing would need porting (not written
  up).
- **Python 3.11** via Homebrew — **not** 3.14 (torch/ctranslate2 wheels lag the
  newest Python). A venv at `~/venvs/whisperx`.
- **Python packages**: `whisperx` (tested 3.8.5), `pyannote.audio` (4.x), `torch`
  (tested 2.8.0) in `~/venvs/whisperx` — used for **diarization on MPS** + the ASR
  wrapper. A `torchcodec`/libavutil version warning at startup is harmless
  (audio loads via the ffmpeg CLI / in-memory waveform).
- **whisper.cpp** (`brew install whisper-cpp` → `whisper-cli` on PATH, Metal-enabled
  on Apple Silicon) — the **ASR engine** (hybrid default). Plus the model
  `~/transcribe-pipeline/models/ggml-large-v3.bin` (~3 GB) from
  `huggingface.co/ggerganov/whisper.cpp` (`ggml-large-v3.bin`).
  (Optional/alternative: `~/venvs/mlx-asr` with `mlx-whisper` only if you use
  `asr_mlx.py` instead — not the default; it thrashes swap on a 16 GB box.)
- **ffmpeg** on `PATH` (audio load + 2-track channel split).
- **A Hugging Face account + read token**, with these **gated models accepted**
  (one-time, on huggingface.co): `pyannote/speaker-diarization-community-1`,
  `pyannote/segmentation-3.0`, `pyannote/wespeaker-voxceleb-resnet34-LM`.
  Token resolution: macOS keychain service **`hf-token-pyannote`** first, then
  the fallback file `~/.config/open-bridge/hf-token` (chmod 600). Keychain
  writes over SSH fail — when provisioning remotely, use the file.
- **Disk + RAM** for the ggml-large-v3 (~3 GB) + pyannote weights (GB-scale).
  Hybrid GPU transcription ≈ **0.7× the audio length** end-to-end; the legacy
  `TRANSCRIBE_ENGINE=whisperx` CPU path is ~2–4× and was the reason for the
  hybrid (CTranslate2 has no Metal backend — see architecture.md § Engine).
- **Claude Code CLI** (optional — only for the manual `summarize.py` fallback;
  the worker itself never summarizes). Must be **authenticated in the GUI login
  session**. It will **not** authenticate from a plain SSH session (no keychain)
  — validate the fallback via the launchd run, not over SSH.
- **Incoming SSH** reachable from the capture machine (rsync + remote commands).

**Capture machine** (records the meeting — optional):
- **macOS** with `launchd` (the bundler runs as a LaunchAgent).
- **Audio Hijack** (Rogue Amoeba, commercial) for a true 2-track recording
  (mic vs. system). Optional: without it, any mono/stereo-mix recording works via
  `tracks: single` (diarization separates by voice) — see operations.md.
- **SSH client access** to the worker (rsync push of recordings).
- Without a capture machine, leave env `CAPTURE_HOST` empty — the worker keeps
  finished transcripts only locally in `~/Transcripts/<output>/` and the sync
  script (`debrief_sync.sh pull`) fetches them from there.

**Bridge repo** (the orchestration side — where this skill lives):
- Placement in `infra/transcriptions/topology.yaml`. For a **remote** worker the
  alias must resolve in your `~/.ssh/config` (SSH or Tailscale); env
  `TRANSCRIBE_WORKER` overrides it. For a **local** single-machine install set
  `mode: local` — no worker host, no SSH (the compute stack below still applies):
  ```yaml
  # infra/transcriptions/topology.yaml
  mode: remote                 # local | remote
  worker:                      # remote only
    host: worker-host          # SSH/Tailscale alias
    launchd_label: com.openbridge.transcribe-worker
  ```
  Registration stays in `bridge-config.yaml → integrations.transcription`
  (enabled, sync_script, contexts, default_context).
- A context yaml per transcription target under `workflow/contexts/<ctx>.yaml`
  carrying an `integrations.transcription` block (the source of truth; schema:
  `IntegrationTranscription` in `workflow/contexts/_schema.yaml`).
- CLI tools: `rsync`, `ssh`, `check-jsonschema` (context validation), `yq`
  (inventory queries), `python3` (runs `extract_runtime_contexts.py` locally).

## What a provisioned install looks like

- **Source of truth split**: bridge yaml (`workflow/contexts/<ctx>.yaml`)
  carries the rich context; worker yamls under
  `~/transcribe-pipeline/contexts/` are generated extracts. Edit on the
  bridge, redeploy to update.
- **Worker host**: Python 3.11 venv `~/venvs/whisperx` with whisperx 3.8.5 +
  pyannote.audio (torch 2.8.0). HF token in the keychain (`hf-token-pyannote`)
  or `~/.config/open-bridge/hf-token`. Scripts in `~/transcribe-pipeline/bin/`,
  generated runtime configs in `contexts/`, prompts in `prompts/`. Libraries:
  `speaker-library/main/` (alice, bob, carol), one folder per additional
  context. Inboxes: `~/transcribe-inbox/<ctx>/` per context.
- **launchd**: `com.openbridge.transcribe-worker` **loaded** (`launchctl
  bootstrap gui/$(id -u)`, RunAtLoad + WatchPath `~/transcribe-inbox`) — verify
  with a live bundle run, `last exit code = 0`. The bundler plist
  (`com.openbridge.transcribe-bundler`) is loaded on the capture Mac (when used).
- **Track modes**: the worker honors a manifest `tracks:` field — `dual`
  (default, real Audio-Hijack 2-track) or `single` (stereo-mix / mono download:
  downmix to one diarized track, skip the mic path). See operations.md.
- **Known caveat**: `torchcodec`/libavutil version-mismatch warning at startup —
  harmless (WhisperX loads audio via the ffmpeg CLI). Verified by smoke test.

## Provision the worker host from scratch

Examples use `worker-host` — replace with your alias from `infra/transcriptions/topology.yaml`
`worker.host` (env `TRANSCRIBE_WORKER` overrides). **Skip this whole section for
`mode: local`** — the pipeline runs on this machine; `add_context.sh` bootstraps
the local dirs and deploys the runtime contexts for you (no SSH).

```bash
# 1. Skeleton
ssh worker-host 'mkdir -p ~/transcribe-pipeline/{bin,contexts,prompts} \
   ~/transcribe-pipeline/speaker-library ~/transcribe-inbox ~/Library/LaunchAgents'

# 2. venv — Python 3.11 (NOT 3.14: torch/ctranslate2 wheels lag the newest Python)
ssh worker-host 'source ~/.zprofile && \
   /opt/homebrew/bin/python3.11 -m venv ~/venvs/whisperx && \
   ~/venvs/whisperx/bin/pip install --upgrade pip wheel && \
   ~/venvs/whisperx/bin/pip install whisperx pyannote.audio'

# 2b. whisper.cpp (ASR engine, hybrid default) + the large-v3 GGML model
ssh worker-host 'export PATH=/opt/homebrew/bin:$PATH && brew install whisper-cpp && \
   mkdir -p ~/transcribe-pipeline/models && \
   curl -L -o ~/transcribe-pipeline/models/ggml-large-v3.bin \
     https://huggingface.co/ggerganov/whisper.cpp/resolve/main/ggml-large-v3.bin'

# 3. HF token — user accepts the pyannote license + creates a read token, then:
#    (keychain writes over SSH fail — no unlocked keychain — so use the file)
printf '%s' 'hf_XXXX' | ssh worker-host \
   'umask 077; mkdir -p ~/.config/open-bridge && cat > ~/.config/open-bridge/hf-token'
#    Provisioning locally on the worker instead? The keychain works there:
#    security add-generic-password -a "$USER" -s hf-token-pyannote -w 'hf_XXXX'
#    Gated models to accept: pyannote/speaker-diarization-community-1,
#    pyannote/segmentation-3.0, pyannote/wespeaker-voxceleb-resnet34-LM

# 4. Deploy scripts + prompts (from this skill's source folders)
cd <bridge-repo-root>
rsync -av --exclude='com.openbridge.*.plist' \
   skills/meeting-transcription/scripts/*.py \
   skills/meeting-transcription/scripts/*.sh \
   worker-host:transcribe-pipeline/bin/
rsync -av skills/meeting-transcription/prompts/ worker-host:transcribe-pipeline/prompts/
ssh worker-host 'chmod +x ~/transcribe-pipeline/bin/*.{sh,py}'

# 5. Extract + deploy runtime contexts from the bridge SoT.
#    Each workflow/contexts/<ctx>.yaml with an `integrations.transcription`
#    block becomes ONE flat <ctx>.yaml on the worker (up to 5 keys:
#    language, library, output, notify, mic_speaker).
python3 skills/meeting-transcription/scripts/extract_runtime_contexts.py \
   --src workflow/contexts --out /tmp/runtime-contexts
rsync -av --delete /tmp/runtime-contexts/ worker-host:transcribe-pipeline/contexts/
#    `--delete` is intentional: it removes obsolete runtime yamls
#    (e.g. a .bak left from a past edit) so worker state matches the bridge.

# 6. Bootstrap remote dirs for each context (idempotent; runs locally + ssh's).
bash skills/meeting-transcription/scripts/add_context.sh main
#    (repeat per context, e.g. `add_context.sh customer-x`)

# 7. launchd worker — plists ship with a REPLACE_ME_HOME placeholder;
#    substitute the worker's real $HOME before bootstrapping.
rsync -av skills/meeting-transcription/scripts/com.openbridge.transcribe-worker.plist \
   worker-host:Library/LaunchAgents/
ssh worker-host 'sed -i "" "s|REPLACE_ME_HOME|$HOME|g" \
   ~/Library/LaunchAgents/com.openbridge.transcribe-worker.plist && \
   launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.openbridge.transcribe-worker.plist'
#    Optional: to mirror finished transcripts to a capture machine, set
#    CAPTURE_HOST in the plist's EnvironmentVariables (empty/unset = worker
#    keeps transcripts locally in ~/Transcripts/<output>/; the sync script
#    pulls from there).

# 8. Verify
ssh worker-host 'source ~/venvs/whisperx/bin/activate && whisperx --help | head -3
   launchctl print gui/$(id -u)/com.openbridge.transcribe-worker | grep -E "state|last exit"'
```

## Provision the capture Mac (optional)

```bash
mkdir -p ~/Recordings/meetings/main ~/bin ~/Library/LaunchAgents ~/Transcripts
cp skills/meeting-transcription/scripts/transcribe-bundler.sh ~/bin/ && chmod +x ~/bin/transcribe-bundler.sh
cp skills/meeting-transcription/scripts/com.openbridge.transcribe-bundler.plist ~/Library/LaunchAgents/
sed -i '' "s|REPLACE_ME_HOME|$HOME|g" ~/Library/LaunchAgents/com.openbridge.transcribe-bundler.plist
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.openbridge.transcribe-bundler.plist

# Audio Hijack sessions (one per context):
python3 skills/meeting-transcription/scripts/build_2track_session_v2.py   # → ~/Desktop/Teams 2-Track.ah4session
# Import in AH, set the Recorder folder to ~/Recordings/meetings/main
# (and one copy per additional context).
# Grant Microphone permission to Audio Hijack on first run.
```

## Redeploy after editing a script

The skill's `scripts/` is the source of truth. After editing:
```bash
bash -n skills/meeting-transcription/scripts/<script>.sh    # or python3 -m py_compile <s>.py
rsync -av skills/meeting-transcription/scripts/<script> worker-host:transcribe-pipeline/bin/
ssh worker-host 'chmod +x ~/transcribe-pipeline/bin/<script>'
```
launchd picks up the new script on the next WatchPath fire — no reload needed
unless you changed the `.plist` itself (then `launchctl bootout` + `bootstrap`,
re-applying the `REPLACE_ME_HOME` substitution).

## Redeploy after editing a context

```bash
# Validate first
check-jsonschema --schemafile workflow/contexts/_schema.yaml workflow/contexts/<ctx>.yaml
# Extract → deploy
python3 skills/meeting-transcription/scripts/extract_runtime_contexts.py \
   --src workflow/contexts --out /tmp/runtime-contexts
rsync -av --delete /tmp/runtime-contexts/ worker-host:transcribe-pipeline/contexts/
```
No worker restart needed — the worker re-reads context yamls on every
WatchPath fire.

## The claude -p summary fallback on the worker

`summarize.py` shells out to `claude` (found at `~/.claude/local/claude` or via
PATH). It works from the launchd GUI session (like any launchd-scheduled claude
job). It will **not** authenticate from a plain SSH session (no keychain) — so
when testing manually over SSH, expect an auth error on the summary step; that's
a test artifact, not a worker bug. Validate the summary path via the launchd run
or `launchctl kickstart`. Remember it is a **manual fallback** — the normal
summary path is the in-session `/debrief` (see architecture.md).
