---
summary: "Transcription topology: where/how the meeting-transcription pipeline runs (remote worker over SSH, or fully local on one machine)."
type: readme
last_updated: 2026-07-14
related:
  - ../../skills/meeting-transcription/SKILL.md
  - ../../docs/transcription-worker.md
---

# transcriptions/

Single source of truth for **where** the `meeting-transcription` pipeline runs.
One file, two modes:

| `mode` | Means | Transport |
|---|---|---|
| `remote` | The pipeline lives on a **worker host** (e.g. a Mac mini); the Bridge machine hands audio to it and pulls finished transcripts back. | `ssh` + `rsync` to `worker.host` |
| `local` | The Bridge machine **is** the worker — one machine, no SSH. | plain filesystem `cp` / `mv` |

> **Two axes, kept separate.** This file is **placement** (mode, worker host,
> local paths). The **content** of a context — language, voice library, output
> routing, notify, mic-speaker name — stays in
> `workflow/contexts/<ctx>.yaml → integrations.transcription`. A worker swap never
> forces editing N context files.

> **`local` is transport, not zero-setup.** Local mode removes SSH — it does **not**
> remove the compute stack. The machine still needs whisper.cpp + pyannote, an
> Apple-Silicon GPU (Metal/MPS), the venvs, and an HF token installed, exactly as a
> remote worker would. See `skills/meeting-transcription/references/deployment.md`.

## Files

| File | Purpose | Scope |
|---|---|---|
| `_template.yaml` | Boilerplate with commented defaults (ships in CORE) | core |
| `_schema.yaml` | JSON Schema for `topology.yaml`, validated in CI (ships in CORE) | core |
| `topology.yaml` | Your live config — you create + maintain it | user |
| `README.md` | This file | core |

There is **no `_state.yaml`** here (unlike `infra/backups/`): transcription keeps no
run-state — the worker's inbox/outbox dirs are the state.

## Who writes what

| File | Writer |
|---|---|
| `topology.yaml` | you only (by hand) |
| `_template.yaml` / `_schema.yaml` / `README.md` | open-bridge CORE updates |

## Resolution order (implemented in the skill's `debrief_sync.sh`)

```
mode:        TRANSCRIBE_MODE env  >  topology.yaml `mode`
             >  inferred (worker host resolves ⇒ remote, else local)   ← only when
                                                                          topology.yaml is absent
worker host: TRANSCRIBE_WORKER env  >  topology.yaml `worker.host`
             >  (legacy) bridge-config integrations.transcription.worker.host
```

An **explicit `mode:`** is required in every authored `topology.yaml` (the schema
enforces it). Inference exists only as the back-compat path for instances that
predate this file. An unknown explicit value fails loud rather than falling back.

## Wiring an executor

open-bridge ships the topology + schema; the pipeline itself is the
`meeting-transcription` skill (a reference implementation of the bring-your-own-worker
contract in `docs/transcription-worker.md`). To run it:

1. Copy `_template.yaml` → `topology.yaml`, pick `mode`.
2. `remote`: set `worker.host` (or export `TRANSCRIBE_WORKER`) and provision the
   worker per `skills/meeting-transcription/references/deployment.md`.
3. `local`: leave `mode: local`; install the compute stack on this box; the
   `local:` paths default to the worker conventions, so you usually need none of them.
4. Register the capability + contexts in `bridge-config.yaml → integrations.transcription`
   (enabled, skill, sync_script, contexts, default_context) — that block is the
   on/off + routing; `topology.yaml` is the machine placement.

## Change workflow

1. Edit `topology.yaml` (switch mode, change host, adjust a local path).
2. `check-jsonschema --schemafile infra/transcriptions/_schema.yaml infra/transcriptions/topology.yaml`
3. `git diff infra/transcriptions/topology.yaml` → review.
4. Commit on your user branch. `topology.yaml` is USER-scope and never promotes.
