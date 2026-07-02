---
summary: "Playbooks for managing the transcription pipeline — add context, one-off recording, add/re-train speaker, reprocess, source-audio archive/dedupe, extend, re-summarize"
type: reference
last_updated: 2026-07-02
---

# Operations Playbooks

All paths are on the worker host under `~/transcribe-pipeline/` unless noted.
Examples use `worker-host` as the SSH alias — yours comes from
`bridge-config.yaml` `integrations.transcription.worker.host` (env
`TRANSCRIBE_WORKER` overrides). Run Python via the venv:
`source ~/venvs/whisperx/bin/activate` first, or use
`~/venvs/whisperx/bin/python`. Remember the SSH-keychain caveat for `claude -p`
(see troubleshooting.md) — relevant only for the manual summary fallback.

## Transcribe a meeting

**Auto path:** record into `~/Recordings/meetings/<context>/` (one Audio Hijack
session per context). launchd does the rest. Confirm the right context with the
user if ambiguous — that picks the voice library + language.

**Manual path** (e.g. an existing file, or replaying an archive):
```bash
TS=$(date +%Y-%m-%d-%H%M%S)
ssh worker-host "mkdir -p ~/transcribe-inbox/<ctx>/$TS"
rsync recording.mp3 worker-host:~/transcribe-inbox/<ctx>/$TS/meeting.mp3
ssh worker-host "printf 'recorded_at: %s\nduration_s: 0\n' \
   \$(date -u +%Y-%m-%dT%H:%M:%SZ) > ~/transcribe-inbox/<ctx>/$TS/manifest.yaml; \
   touch ~/transcribe-inbox/<ctx>/$TS/.READY"
# Worker fires on the WatchPath; watch ~/Library/Logs/transcribe-worker.log
# (or use the wrapper: debrief_sync.sh push "recording.mp3" <ctx>)
```

**Single-track / stereo-mix input** (not a real 2-track recording, e.g. a Teams
voice-chat download): set `tracks: single` in the bundle's `manifest.yaml`. The
worker then downmixes the whole file to one diarized teams track and skips the
mic path (writes an empty `mic_out/mic.json`), so nobody is hard-labelled as the
mic owner — every speaker, the recording user included, is separated by voice and
matched via the context's library. Diarization quality is lower than true 2-track
but usable. Missing `tracks:` defaults to `dual` (real Audio-Hijack 2-track), so
regular 2-track captures are unaffected. Example manifest:
```yaml
recorded_at: 2026-05-26T11:31:00Z
duration_s: 1219
language: en
tracks: single
source: teams-voicechat-singletrack-downmix
```

## Add a context

A context = bridge yaml + remote inbox + voice library + capture-Mac recording
folder. Source of truth is `workflow/contexts/<name>.yaml`; the worker yamls
are generated from it.

### 1. Add the bridge context yaml

Copy `workflow/contexts/_template.yaml` to `workflow/contexts/<name>.yaml`,
fill in `schema_version`, `scope`, `id`, `description`, and the
`integrations.transcription` block:
```yaml
schema_version: 1
scope: org                       # org for customers/team; user for personal
id: <name>
description: "<one-liner>"
integrations:
  transcription:
    language: de                 # de | en | auto (auto = multi-window vote via detect_language.py)
    library:  <name>             # → speaker-library/<name>/*.npy
    output:   <name>             # → ~/Transcripts/<name>/
    notify:   true
    # mic_speaker: "Alice"       # display name for the dual-track mic channel (default "Me")
    # tracks_default: dual       # default when bundle manifest doesn't set it
```
Validate:
```bash
check-jsonschema --schemafile workflow/contexts/_schema.yaml workflow/contexts/<name>.yaml
```

### 2. Bootstrap remote dirs + recording folder

```bash
bash skills/meeting-transcription/scripts/add_context.sh <name>
```
Runs locally; ssh's `mkdir -p` for `~/transcribe-inbox/<name>/` and
`speaker-library/<name>/` on the worker host, and `~/Recordings/meetings/<name>/`
on the capture Mac (when one is configured).

### 3. Deploy

Extract → rsync runtime yamls (see `deployment.md` § Redeploy):
```bash
python3 skills/meeting-transcription/scripts/extract_runtime_contexts.py \
    --src workflow/contexts --out /tmp/runtime-contexts
rsync -av --delete /tmp/runtime-contexts/ worker-host:transcribe-pipeline/contexts/
```

### 4. Audio Hijack session

On the capture Mac, create a session (duplicate an existing one or run
`build_2track_session_v2.py`) writing to `~/Recordings/meetings/<name>/`.

The first meeting in a new context produces unnamed `SPEAKER_NN` clusters —
bootstrap the library from it (next playbook).

## One-off recording (don't provision a context)

A **one-off** recording that doesn't justify its own transcription context (a job
interview, an ad-hoc capture) should **not** get a new
`workflow/contexts/<name>.yaml` + `add_context.sh` deploy — too much ceremony for
a single file. Route it through an existing context instead:

- **Push to your default context:** `debrief_sync.sh push "<audio>" main`. On a
  shared worker, never push into a context that belongs to a sibling Bridge
  instance (see `docs/multi-instance.md`) — only into your own.
- The recording user's voice matches automatically; external speakers come back
  as `SPEAKER_XX` → name them by **content/role** (with confidence). Do **NOT**
  pass `--save-embeddings` for one-off external speakers — that would pollute the
  context's voice library with strangers' voiceprints.
- Note the **bundle-ID → file mapping** in the worklog: the pull prefixes
  everything with `main-`, so you route it to its real home **manually** on pull
  (e.g. the matching `work/tasks/<slug>/` folder for an interview — usually
  `scope: user` material, never a shared knowledge repo).
- On pull, scope `TRANSCRIBE_CONTEXTS=main` if the worker hosts contexts that
  aren't yours — see troubleshooting.md § `debrief_sync.sh pull` without a scope.

## Add or re-train a speaker (voice library)

Voices are matched by embedding, so you teach the system once per person. Two
ways:

**A. Bootstrap from a processed meeting (preferred — real meeting audio).**
After a meeting is diarized, show the user who each cluster is, then persist:
```bash
cd ~/transcribe-pipeline
# 1. Print representative quotes per cluster (the human who attended maps them)
python bin/speaker_idcard.py --json transcribe-inbox/<ctx>/<ts>/teams_out/teams.json
# → user says e.g. "SPEAKER_00=Alice, SPEAKER_01=Bob, SPEAKER_02=Carol"
# 2. Rename + save the voiceprints into the context library
python bin/apply_speaker_names.py \
   --json transcribe-inbox/<ctx>/<ts>/teams_out/teams.json \
   --out  transcribe-inbox/<ctx>/<ts>/teams-named.json \
   --map  "SPEAKER_00=Alice,SPEAKER_01=Bob,SPEAKER_02=Carol" \
   --library speaker-library/<ctx> --save-embeddings
```
`--save-embeddings` reads the `speaker_embeddings` block WhisperX wrote (needs
`--speaker_embeddings` at transcribe time, which the worker always passes) and
stacks each named cluster's vector into `<name>.npy`. Re-running on later
meetings **adds** samples (more samples = more robust matching).

**B. Bootstrap from a clean clip** (a voice memo, an intro where one person
speaks alone):
```bash
python bin/extract_voice_sample.py --audio clip.mp3 --label alice \
   --start-s 5 --end-s 35 --library speaker-library/<ctx>
```
This runs the clip through WhisperX `--diarize --speaker_embeddings` (same path
the worker uses) and keeps the dominant speaker's voiceprint, so the sample
lands in the same 256-dim space as method A — they stack cleanly. Needs the venv
active + the HF token (keychain `hf-token-pyannote` or
`~/.config/open-bridge/hf-token`, auto-discovered). Method A is still preferred
when you already have a diarized meeting.

**Re-train / fix a wrong match:** lower confidence shows as a `SPEAKER_NN` left
in the transcript (frontmatter `unknown_speakers`). Add more samples for that
person via A or B, then reprocess the naming step. If two similar voices get
swapped, raise the threshold (`--threshold 0.65`) or add more distinct samples.
A short fragment of a known speaker that lands just below threshold is absorbed
automatically by the soft-match rule (best ≥ `--soft-floor` 0.45 AND ≥
`--soft-margin` 0.20 ahead of the runner-up); tighten those if a fragment gets
mislabelled.

**Back up the new voiceprint.** Adding/re-training happens on the worker, so the
fresh `.npy` only lives there until you sync it. Run
`bash skills/meeting-transcription/scripts/debrief_sync.sh voiceprints pull` to
capture it into the bridge (`identity/voiceprints/<ctx>/`) — see SKILL.md
§ Back up / sync voiceprints for the git/offsite policy.

## Reprocess a recording

Cached intermediate JSON makes most reprocessing cheap — you rarely re-transcribe.

- **Re-run naming only** (after improving the library):
  ```bash
  python bin/speaker_naming.py --teams-wav <bundle>/teams.wav \
     --teams-json <bundle>/teams_out/teams.json \
     --library speaker-library/<ctx> --out <bundle>/teams-named.json
  python bin/merge_transcripts.py --mic <bundle>/mic_out/mic.json \
     --teams <bundle>/teams-named.json --manifest <bundle>/manifest.yaml \
     --out <bundle>/transcript-raw.md
  ```
- **Re-summarize** — done **in-session via `/debrief`**, not on the worker. The
  worker delivers only the naked transcript (`transcript-raw.md`); the summary is
  context-aware (name-conventions, board, open issues, contexts) and belongs where
  that context is loaded. `bin/summarize.py` (the old worker `claude -p`) survives
  only as a **manual headless fallback** — it is context-blind, so prefer /debrief:
  ```bash
  # fallback only (context-blind): python bin/summarize.py --raw <bundle>/transcript-raw.md --out /tmp/sum.md --prompt-dir prompts
  ```
- **Full re-run** (re-transcribe from the MP3): `rm <bundle>/.PROCESSED
  <bundle>/mic_out/*.json <bundle>/teams_out/*.json; touch <bundle>/.READY` —
  the worker redoes everything. On the hybrid GPU engine ≈ **0.7× the audio
  length** end-to-end (e.g. a 38-min 2-track meeting ≈ 27 min: mic ASR + teams
  ASR + diarize); the old `TRANSCRIBE_ENGINE=whisperx` CPU path is ~2× slower.

## Source audio — keep it, archive it, dedupe before re-transcribing

**Never trash a source recording.** The mp3 of a meeting is archived, not deleted
— even after the worker has a copy. Transcript and audio split at the `/debrief`
archive step:
- **Transcript** → `work/archive/days/{YYYY-MM}/{DD}_{HHMM}_<slug>.md` (git-tracked).
- **Audio** → your audio archive **outside the repo**, `bridge-config.yaml`
  `work.audio_archive_dir` (e.g. `~/Archive/audio/processed/`), named
  `{YYYY-MM-DD}_{HHMM}_<slug>.{ext}`. `processed/` is skipped by the
  scanners, so it never re-processes.
- **Move, don't copy** (collision-check on bulk, never overwrite). Delete a worker
  bundle (`~/transcribe-inbox/<ctx>/<ts>/`) **only** once the audio sits
  byte-identical in the archive — the archive entry is the truth.

**Dedupe an orphan before re-transcribing.** An mp3 found loose in your imports
dir (`work.imports_dir`, default `work/imports/`) is often a re-push of an
already-debriefed recording, not a new meeting. Before sending it through the
pipeline, `md5` + byte-size it against the archive (`work.audio_archive_dir`).
A match = already processed → trash the dupe, don't re-run it. **Two traps that
hide dupes:**
- **Bundle / transcript name = push date, not recording date** — `manifest.yaml
  recorded_at` is also just push time. Truth = the `meeting.mp3` mtime + md5, never
  the bundle date.
- **Audio Hijack stamps start time ≠ meeting time**, so the same bytes can carry
  different timestamps in the filename.
Already-debriefed worker bundles live under `~/Transcripts/<ctx>/_debriefed/*.md` —
never re-pull those; only true orphans (no md5 match, no `_debriefed/` entry) go to
the worker.

## Extend the pipeline (add a stage)

The worker is a linear bash function `process_bundle`. To add a stage (e.g.
auto-filing into your knowledge repo, a sentiment pass, a glossary correction):
1. Write the stage as a standalone script in `scripts/` that reads/writes files
   in the bundle dir (keep it idempotent + guarded by an output-exists check, so
   reprocessing skips finished stages — mirror how steps 2a/2b guard on their
   JSON).
2. Insert the call in `transcribe-worker.sh` `process_bundle` at the right point
   (before delivery if it changes the transcript; after if it's a side-effect).
3. `bash -n` it, deploy (`rsync scripts/<new>.sh worker-host:~/transcribe-pipeline/bin/`),
   test on one bundle manually before trusting the launchd trigger.

Prefer small composable scripts over growing the worker — the worker should stay
a readable orchestrator. Explain the change to the user before deploying, since
it runs unattended.

## Inventory / health

```bash
# Bridge-side source of truth — which contexts participate in transcription:
yq '. | select(.integrations.transcription) | {(.id // ""): .integrations.transcription}' \
   workflow/contexts/*.yaml

# Worker-side runtime + libraries + recent runs:
ssh worker-host 'ls ~/transcribe-pipeline/contexts/;           # generated runtime yamls
   for d in ~/transcribe-pipeline/speaker-library/*/; do echo "$d:"; ls "$d"; done;  # libraries
   tail -30 ~/Library/Logs/transcribe-worker.log'              # recent runs
```

The two surfaces should be in sync: every yaml under
`~/transcribe-pipeline/contexts/` corresponds to a `workflow/contexts/*.yaml`
with `integrations.transcription`. Drift = something other than `extract_runtime_contexts.py`
wrote the runtime yamls (delete + re-extract to fix).
