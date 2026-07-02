---
summary: "Bring-your-own transcription worker — the contract between /debrief and any transcription pipeline, plus the no-worker manual path"
type: guide
last_updated: 2026-07-02
related:
  - ../skills/debrief/SKILL.md
  - work-system.md
---

# Transcription worker — bring your own

`/debrief` processes meeting *transcripts*. How audio becomes a transcript is
deliberately out of scope: open-bridge ships **no transcription pipeline**, and
`/debrief` must never hard-depend on one. Two paths are supported; the manual
path is first-class, not a degraded mode.

## Path 1 — no worker (manual, always works)

Transcribe with any tool you like — whisper.cpp, MacWhisper, a cloud STT
service, your meeting platform's built-in transcript export — and drop the
result where `/debrief` scans:

- put the transcript (`.txt`, `.md`, `.vtt`, `.srt`) into your imports dir
  (`work.imports_dir`, default `work/imports/`), **or**
- keep audio + transcript side by side with the same basename
  (`meeting.mp3` + `meeting.txt`) — the Find phase treats the pair as one item.

That is the whole contract for the manual path. No config needed.

## Path 2 — automated worker (optional)

If you run (or build) a pipeline — say whisper.cpp plus a speaker diarizer on a
spare machine watching a staging folder — wire it up through **one config
block** and **one script**. `/debrief` only ever calls the script; it never
talks to your worker directly.

### Config — `bridge-config.yaml`

```yaml
integrations:
  transcription:
    enabled: true
    sync_script: "skills/meeting-transcription/scripts/debrief_sync.sh"  # repo-relative; swap for your own
    default_context: main       # context for audio handed off without an explicit one
    worker:                     # read by the reference implementation (yours may differ)
      host: worker-host         # SSH/Tailscale alias — see infra/remotes/
      launchd_label: com.openbridge.transcribe-worker
    contexts:
      main:                     # → workflow/contexts/main.yaml
        imports: work/imports   # where this context's finished transcripts land
```

### The sync-script contract

The script is the entire interface. It must implement two verbs:

| Invocation | Contract |
|---|---|
| `BRIDGE_IMPORTS=<abs dir> TRANSCRIBE_CONTEXTS=<ctx> <script> pull` | Fetch every finished transcript for `<ctx>` into `$BRIDGE_IMPORTS` as `<ctx>-<name>.md`. Must be idempotent: mark delivered transcripts as done on the worker side (the reference layout uses a `_debriefed/` folder) so a second `pull` delivers nothing new. |
| `<script> push` | Hand un-transcribed audio (staged by `/debrief`'s Find phase) to the worker. How you stage and transport — SSH, watched folder, queue — is your business. |

Failure semantics (hard rules — `/debrief` relies on these):

- **Disabled** (`enabled: false` or block absent) → `/debrief` skips the
  integration silently and behaves exactly like Path 1.
- **Worker unreachable** → exit non-zero. `/debrief` notes it and proceeds
  with whatever is already in imports — it never blocks and never fails the run.
- **Nothing new** → exit zero, deliver nothing.

### Transcript output expectations

- One markdown/text file per meeting, named `<context>-<name>.md`.
- Speaker labels if your pipeline can produce them (`SPEAKER_00:` or real
  names) — the classification phase applies name corrections either way.
- Timestamps optional.

### Per-context settings (optional)

A context that participates in transcription can declare pipeline hints in its
`workflow/contexts/<slug>.yaml` — see `IntegrationTranscription` in
`workflow/contexts/_schema.yaml` (language, voice-library slug, output folder,
notify, mic_speaker). Your worker's deploy step is free to consume or ignore
them.

## Reference implementation

open-bridge ships a full implementation of this contract:
[`skills/meeting-transcription/`](../skills/meeting-transcription/SKILL.md) —
whisper.cpp large-v3 (Metal) + pyannote diarization (MPS) on a worker host you
provision, per-context voice libraries for speaker naming, launchd automation,
and `scripts/debrief_sync.sh` as the sync script. Point
`integrations.transcription.sync_script` at it and follow its
`references/deployment.md`. The contract above stays the boundary — any other
worker that honours it plugs in the same way.
