---
summary: "Bring-your-own transcription worker — the contract between /debrief and any transcription pipeline, plus the no-worker manual path"
type: guide
last_updated: 2026-07-14
related:
  - ../skills/debrief/SKILL.md
  - ../infra/transcriptions/README.md
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
    contexts:
      main:                     # → workflow/contexts/main.yaml
        imports: work/imports   # where this context's finished transcripts land
```

Placement — **where** the reference pipeline runs (a remote worker over SSH, or
fully local on one machine) — is **not** in this block; it lives in
[`infra/transcriptions/topology.yaml`](../infra/transcriptions/README.md). This
block stays **registration + routing** (capability on/off, which script, which
contexts). A custom `sync_script` may read placement however it likes.

### Transport modes (reference `debrief_sync.sh`)

The reference sync script picks a transport from `infra/transcriptions/topology.yaml`
`mode` (env `TRANSCRIBE_MODE` overrides):

- **`remote`** — the pipeline lives on `worker.host`; every `pull` / `push` /
  `voiceprints` op runs over `ssh` + `rsync`. An unreachable worker exits
  non-zero and `/debrief` degrades to Path 1.
- **`local`** — bridge and worker are the same machine; every op is a plain
  filesystem `cp` / `mv` and the SSH reachability probe is skipped, so a fresh
  single-machine clone runs with **no SSH**. (Local removes SSH, not the compute
  stack — whisper.cpp + pyannote + an Apple-Silicon GPU are still required.)

`mode` governs only the reference implementation; a custom `sync_script` supplies
its own transport.

**Optional richer output tier (additive, reserved).** A worker MAY deliver its
`.md` already anchored and emit a same-basename `<name>.index.tsv` sidecar
(`anchor ⇥ rel ⇥ speaker ⇥ text`); `pull` fetches it when present, and a minimal
worker that emits only the naked `.md` is unaffected (a `.index.tsv` is not in
the Find-phase transcript glob). The reference pipeline does not emit it today —
anchoring runs bridge-side in `/debrief` — but the contract permits it.

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
provision **or a single local machine** (see Transport modes), per-context voice
libraries for speaker naming, launchd automation,
and `scripts/debrief_sync.sh` as the sync script. Point
`integrations.transcription.sync_script` at it and follow its
`references/deployment.md`. The contract above stays the boundary — any other
worker that honours it plugs in the same way.
