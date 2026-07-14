---
name: meeting-transcription
description: >-
  Operates and manages a context-aware meeting-transcription pipeline (2-track
  or single-mix recording → whisper.cpp large-v3 + pyannote diarization on a
  worker host → voice-matched speaker names → naked transcript delivered to
  /debrief; the summary is made later by the in-session /debrief, never by the
  worker). The reference implementation of the transcription-worker contract
  (docs/transcription-worker.md). Use this skill WHENEVER the user wants to
  transcribe a meeting, set up or change a transcription context/folder, add
  or re-train a speaker voice, reprocess a recording, extend the pipeline, or
  troubleshoot it — even if they don't name the pipeline explicitly. Triggers:
  "transcribe a meeting", "transcription folder", "new transcription context",
  "add a speaker", "train a voice", "voice library", "speaker recognition",
  "speaker diarization", "who said what", "reprocess recording", "transcribe
  pipeline", "update the whisper model". Also use it to answer "how does my
  transcription system work" — it is the source of truth for that system.
metadata:
  scope: core
---

# Meeting Transcription Pipeline

A pipeline that turns meeting recordings into clean, structured Markdown
transcripts with **named speakers**. It is **context-aware**: each context
(e.g. `main`, `customer-x`) has its own voice library, language default, and
output routing, so the same system serves internal standups and customer calls
in different languages without reconfiguration.

This skill is both the **knowledge base** (how the system works) and the
**operations manual** (how to change it). The canonical scripts live in
`scripts/` here and are deployed to the worker host's `~/transcribe-pipeline/`.
It is the reference implementation of the bring-your-own-worker contract in
[`docs/transcription-worker.md`](../../docs/transcription-worker.md) — `/debrief`
talks to it only through `scripts/debrief_sync.sh` (`pull` / `push`).

## Configuration — the yaml wiring

Three config surfaces, same pattern as every other capability:

**1. `bridge-config.yaml` — the integration block** (is the capability on, which
script, which contexts — registration + routing):

```yaml
integrations:
  transcription:
    enabled: true
    sync_script: "skills/meeting-transcription/scripts/debrief_sync.sh"
    default_context: main        # context for audio handed off without an explicit one
    contexts:
      main:                      # → workflow/contexts/main.yaml
        imports: work/imports    # where this context's transcripts land on pull
```

`BRIDGE_IMPORTS` / `TRANSCRIBE_CONTEXTS` env-override the imports dir + context
list. `/debrief` degrades gracefully to its manual path when the block is absent
(see the contract doc).

**2. `infra/transcriptions/topology.yaml` — placement** (WHERE the pipeline runs):

```yaml
mode: remote                   # local | remote — THE topology switch (env TRANSCRIBE_MODE overrides)
worker:                        # consulted only when mode == remote
  host: worker-host            # SSH/Tailscale alias — see infra/remotes/
  launchd_label: com.openbridge.transcribe-worker
# local:                       # consulted only when mode == local; all keys optional
#   inbox_dir:       ~/transcribe-inbox        # defaults = the worker's own conventions
#   transcripts_dir: ~/Transcripts
#   library_dir:     ~/transcribe-pipeline/speaker-library
#   contexts_dir:    ~/transcribe-pipeline/contexts
```

Resolution: `TRANSCRIBE_MODE` / `TRANSCRIBE_WORKER` env > `topology.yaml` >
inferred (a worker host resolves ⇒ remote, else local). `remote` runs every op
over ssh+rsync; `local` runs plain filesystem cp/mv with **no SSH** (the compute
stack is still required). An unknown mode fails loud. Schema + guide:
[`infra/transcriptions/README.md`](../../infra/transcriptions/README.md).

**3. `workflow/contexts/<ctx>.yaml` — per-context settings.** A context
"participates in transcription" iff it carries an `integrations.transcription:`
block (schema: `IntegrationTranscription` in `workflow/contexts/_schema.yaml`):

```yaml
integrations:
  transcription:
    language: auto        # de | en | auto (multi-window vote)
    library: main         # → speaker-library/<library>/*.npy on the worker
    output: main          # → ~/Transcripts/<output>/ on the worker
    notify: false         # completion ping (e.g. iMessage on macOS)
    # mic_speaker: Alice  # display name for the dual-track mic channel (default "Me")
```

The skill does **not** maintain its own context directory — two files
joined-by-slug drift silently. Discovery rule (codified — run this whenever
you need to know what contexts exist):

```
for f in workflow/contexts/*.yaml:
    data = yaml.safe_load(f)
    if data.get("integrations", {}).get("transcription"):
        ctx = data["id"]                              # slug, e.g. "main"
        settings = data["integrations"]["transcription"]
        # → this context is live; use settings
```

The worker doesn't parse the bridge yaml directly (its `cfg()` helper is
awk-based and can't read nested keys). The deploy step closes that gap:
`scripts/extract_runtime_contexts.py` reads the bridge yamls, flattens each
`integrations.transcription` block into a flat runtime yaml per context
(language, library, output, notify, mic_speaker), and rsyncs the result to
`~/transcribe-pipeline/contexts/`. The worker keeps its simple parser; the
bridge keeps a single source of truth.

## The 30-second model

```
capture machine (optional)     worker host                        Claude
──────────────────────────     ───────────                        ──────
2-track recorder or any  ──►   ffmpeg split (mic-L / meeting-R)
mixed recording                whisper.cpp large-v3 (Metal GPU)    ASR
~/Recordings/meetings/<ctx>/   + pyannote diarize on MPS (+embeddings)
        │                              │
launchd transcribe-bundler.sh  speaker_naming.py ◄── speaker-library/<ctx>/*.npy
   rsync per context                   │
        ▼                      merge_transcripts.py → transcript-raw.md
worker:~/transcribe-inbox/<ctx>/       │   (the NAKED transcript = worker output)
launchd transcribe-worker.sh   deliver ~/Transcripts/<ctx>/<ts>.md
                                       │
                                       ▼   NO summary on the worker
                          in-session /debrief → context-aware summary + tasks
```

**Key idea — identity comes from voice, not text.** Speakers are matched by
pyannote voice-embedding (cosine ≥ 0.60) against a per-context library, so
"Alice" is always labelled Alice even when Whisper mishears her name.

**Second key idea — transcription is mechanical, interpretation is contextual.**
The worker produces ONLY the naked transcript (ASR + diarization + voice-match —
no bridge context needed). The **summary/tasks are made by the in-session
`/debrief`**, which has the bridge loaded (name conventions, ecosystem, board,
open issues, contexts, prior meetings). A headless worker-side summarizer was
removed for being context-blind: it distorted names and significance.

## When to read which reference

This SKILL.md is the map. For anything beyond the quick operations below, open
the matching reference — they hold the detail so this file stays scannable.

| You need to… | Read |
|---|---|
| Understand data flow, file layout, every script's role | `references/architecture.md` |
| Add a context, add/re-train a speaker, reprocess, extend the pipeline | `references/operations.md` |
| Know what you need first (worker / capture / bridge prerequisites) | `references/deployment.md` § Prerequisites |
| Provision a worker host from scratch (venv, HF token, launchd) | `references/deployment.md` |
| Fix diarization bleed, OOM, language misdetect, delivery failures | `references/troubleshooting.md` |

## Core concepts

- **Context** = the inbox subfolder a recording lands in. Defined by the
  `integrations.transcription` block of `workflow/contexts/<name>.yaml` (see
  Configuration above). To add a context: add the yaml, re-deploy.
- **Voice library** = `speaker-library/<context>/<name>.npy` — 256-dim pyannote
  embeddings, one file per known speaker (can stack multiple samples).
  Bootstrapped once per speaker, then reused forever.
- **Bilingual** = Whisper auto-detects language (or the context forces it); the
  transcript frontmatter records it; the summary prompt
  (`prompts/meeting-summary-{de,en}.md`) is chosen by `/debrief` to match.
- **Summary = NOT here.** The worker does no summarizing — it delivers the
  naked transcript only. Summary + task-extraction happen in the in-session
  `/debrief`. `summarize.py` survives only as a manual headless fallback;
  `prompts/meeting-summary-{de,en}.md` is the `/debrief` summary template. The
  mechanical `scripts/anchor_transcript.py` (per-utterance anchors + `.index.tsv`,
  makes a transcript addressable) is owned here but invoked by `/debrief`'s gold
  path; the interpretive `↪` evidence-linking stays in-session.
- **Engine = hybrid (GPU).** ASR runs on **whisper.cpp** large-v3 (Metal) via
  `asr_whispercpp.py`; diarization + the 256-d embeddings run on
  **pyannote/MPS** via `diarize_assign.py` — the *same* embedding space the
  library was built in, so libraries keep matching. A CPU-only fallback stays
  one env var away: `TRANSCRIBE_ENGINE=whisperx`. Rationale + measurements:
  `references/architecture.md` § Engine.

## Quick operations

Most requests map to a playbook in `references/operations.md`. The headlines:

**Transcribe a meeting** — drop the recording into the context's inbox; the
worker auto-runs. Manual: `<worker>:~/transcribe-inbox/<ctx>/<ts>/meeting.mp3`
+ `touch .READY`. No 2-track? A mono/stereo-mix file still works (diarization
separates by voice; set `tracks: single` in the manifest — the sync script's
`push` does this automatically). Always confirm the right context first.

**Add a context** (bridge-side YAML + remote dirs + recording dir):
1. Add `workflow/contexts/<name>.yaml` (copy from `_template.yaml` — fill
   `schema_version`, `scope`, `id`, and an `integrations.transcription`
   block). Validate: `check-jsonschema --schemafile workflow/contexts/_schema.yaml workflow/contexts/<name>.yaml`.
2. Bootstrap the remote dirs + recording folder:
   `bash skills/meeting-transcription/scripts/add_context.sh <name>`.
3. Deploy: extract + rsync (see `references/deployment.md` § Redeploy).
4. Point your recorder at `~/Recordings/meetings/<name>/` (capture machine).

**Add / re-train a speaker** — after a meeting is diarized, show the user who
each cluster is, then persist the voiceprint:
```
python bin/speaker_idcard.py --json <inbox>/<ctx>/<ts>/teams_out/teams.json
python bin/apply_speaker_names.py --json <that.json> --out teams-named.json \
   --map "SPEAKER_00=Alice,SPEAKER_01=Bob" \
   --library speaker-library/<ctx> --save-embeddings
```
Stacking more samples over time sharpens recognition.

**Reprocess** — delete the bundle's `.PROCESSED` flag and `touch .READY`, or
re-run the steps manually. Cached `teams.json` means re-naming is cheap (no
re-transcription). See operations.md § Reprocess.

**Re-summarize only** (manual fallback, e.g. after improving a prompt):
`python bin/summarize.py --raw <bundle>/transcript-raw.md --out <bundle>/transcript.md --prompt-dir prompts`

**Bridge to /debrief** — `scripts/debrief_sync.sh` implements the worker
contract (`docs/transcription-worker.md`):
- `debrief_sync.sh pull` — fetch finished transcripts into the bridge imports
  dir (prefixed `<ctx>-…`) where `/debrief` Phase 1 finds them.
- `debrief_sync.sh push <audio> [ctx]` — hand an audio file to the pipeline;
  the transcript arrives async and is collected on the next `pull`.
`/debrief` runs `pull` at the start of Find and `push` for any audio without a
transcript. Run it from the machine that can SSH into the worker.

**Back up / sync voiceprints** — `debrief_sync.sh voiceprints pull` syncs the
per-context `speaker-library/*.npy` from the worker into the bridge under
`identity/voiceprints/<ctx>/`; `voiceprints push` restores them onto a fresh
worker. These are **biometric embeddings (GDPR Art. 9)**, so
`identity/voiceprints/` is user data — it **never** promotes upstream. Git
tracking is opt-in per context via your `.gitignore`; an instance handling
customer meetings should route customer voiceprints to that customer's own
repo rather than track them here. An optional weekly launchd job keeps the
backup fresh (`scripts/voiceprint_backup.sh` +
`com.openbridge.voiceprint-backup.plist`).

For anything structural (new pipeline stage, model swap, threshold tuning),
read `references/operations.md` § Extend and `references/troubleshooting.md` —
and explain the change to the user before deploying, since the worker runs
unattended via launchd.

## Hard rules

- **Voice libraries are per-context.** Never match one context's meeting
  against another context's voices — that's the whole point of the split. Only
  the recording user legitimately appears in multiple libraries.
- **HF token** lives in the worker's keychain (service `hf-token-pyannote`) or
  `~/.config/open-bridge/hf-token` (chmod 600). Keychain writes over SSH fail
  (audit session) — use the file fallback when provisioning remotely.
- **The worker runs unattended** — validate script changes (`bash -n`, a
  manual bundle run) before relying on the launchd trigger.
- **Customer transcripts route to the customer's repo** at the `/debrief`
  stage; this pipeline only produces the Markdown.
- **Voiceprints are biometric data** — never commit them to a shared repo,
  never promote them upstream.
