---
summary: "Failure modes of the transcription pipeline and how to fix them — diarization, OOM, swap-flap, repetition loop, language, queue stall, bare-pull scope, claude -p, libavutil"
type: reference
last_updated: 2026-07-02
---

# Troubleshooting

Start with the log: `ssh worker-host 'tail -50 ~/Library/Logs/transcribe-worker.log'`
(`worker-host` = your `infra/transcriptions/topology.yaml` `worker.host` alias; env
`TRANSCRIBE_WORKER` overrides). Each bundle leaves flags: `.FAILED` (errored,
will retry), `.PROCESSING` (in flight or crashed mid-run), `.PROCESSED` (done).
A stuck `.lock` dir from a crashed run blocks reprocessing — `rmdir <bundle>/.lock`.

## Diarization bleed — speakers merged or mis-split

**Symptom:** two people share one `SPEAKER_NN`, or one person split across
clusters; talk-time looks wrong (someone with 1.5 min who clearly spoke more).
**Why:** rapid back-and-forth + overlap is hard for pyannote, *especially on a
stereo-mix / single-track recording* where there's no channel separation.
**Fixes, in order:**
1. Use a **true 2-track recording** (Mic on its own channel) — the mic track is
   ASR-only and never competes for diarization, which removes the dominant
   speaker from the clustering problem entirely. This is the biggest lever.
2. Constrain speaker count when known: `--min_speakers N --max_speakers N`
   (the worker doesn't set this by default; for a fixed roster, add it).
3. Add more/cleaner voice-library samples for the confused speakers, then re-run
   naming (`operations.md` § Reprocess) — better embeddings reduce mismatches.
4. Accept residual bleed and fix in the summary: an LLM reading the full
   transcript can often re-attribute an obviously-misassigned block from context
   (observed: a long one-person monologue mislabelled as another speaker was
   correctly re-attributed).

## All speakers stay SPEAKER_NN (no names)

- Library empty or wrong context: `ls speaker-library/<ctx>/`. Bootstrap it
  (`operations.md` § Add a speaker).
- Threshold too high: clusters matched below 0.60. Lower with `--threshold 0.55`
  on `speaker_naming.py`, or add samples.
- `--speaker_embeddings` missing at transcribe time → `apply_speaker_names.py
  --save-embeddings` warns "no embeddings in JSON". The worker always passes it;
  if you ran whisperx manually, add the flag.

## `--save-embeddings` crashes: `ModuleNotFoundError: No module named 'numpy'`

**Symptom:** running a speaker script manually over SSH (`apply_speaker_names.py`,
`speaker_idcard.py`, `speaker_naming.py`) with `--save-embeddings` dies at
`import numpy`.
**Why:** a plain `ssh worker-host '… python3 …'` uses the SSH session's default
`python3`, which has no numpy — the worker scripts need the **worker venv**.
**Fix:** run them with the venv interpreter explicitly —
`~/venvs/whisperx/bin/python ~/transcribe-pipeline/bin/apply_speaker_names.py …`
(the path the launchd plist `com.openbridge.transcribe-worker` puts on PATH). The
crash is in the `if args.save_embeddings` block **before** any write, so it's
non-destructive — nothing was saved, just re-run with the right python. Point
`--library` explicitly at the context dir
(`~/transcribe-pipeline/speaker-library/<ctx>`, e.g. `…/main`; the default is
`…/embeddings`); `--save-embeddings` stacks (`np.vstack`) onto the existing
`<name>.npy` (one file per speaker, N samples), so re-runs add samples, never
overwrite.

## Out of memory / swap thrash during ASR

The reference worker is a 16 GB Apple-silicon box. The hybrid engine is
**memory-disciplined**: whisper.cpp streams the GGML model and pyannote-on-MPS
sits ~3–4 GB, so OOM is rare. The one known trap is **MLX-Whisper**
(`asr_mlx.py`) — its unified-memory Metal buffers thrash swap with large-v3 on a
16 GB box (a 38-min track ran >17 min and never finished). That's exactly why the
default ASR is whisper.cpp, not MLX. Don't run two bundles concurrently (the
worker is sequential; `ThrottleInterval` spaces launchd fires). Legacy CPU path:
lower `--batch_size` 4→2→1 in the whisperx branch.

## Large single-track recording flaps the whole box (looks down, isn't)

**Symptom:** during a big single-track job (~70 MB ≈ ~60 min) the box becomes
unreachable — the VPN/tailnet shows the host `active`, but ping, SSH (`:22` and
any emergency port) and even other HTTP services it hosts all time out. Uptime
keeps running. An HTTP-000 *together with* an SSH timeout = whole-box memory
starvation, not a wedged sshd.
**Why:** whisper.cpp large-v3 (Metal) **+** pyannote-on-MPS on the same long
recording over-commits a 16 GB box and it swap-thrashes — flapping in/out, not
down. (Distinct from the asleep/unreachable case below — there the host is idle.)
**Fix — recover patiently, don't storm:**
1. Do **not** hammer-poll. A 15 s SSH loop makes it worse and exhausts local
   sockets (`ssh: Address already in use`); a stale ControlMaster/mux socket then
   throws `mux_client_request_session: read from master failed: Broken pipe` —
   bypass with `-o ControlMaster=no -o ControlPath=none`.
2. A single ping "pong" is just a thrash breath, not recovery — wait for
   **sustained** reachability (2 pings ~90 s apart) before re-trying SSH.
3. Use a low-frequency recovery watcher (ping every 45–90 s). The job **runs
   through** once ASR finishes and memory pressure falls (one incident ran ~57 min
   wall-clock instead of ~8). The bundle stays durable (`.PROCESSED` +
   `transcript-raw.md`); `debrief_sync pull` collects it afterwards. A transiently
   vanishing `worker.log` is a read caught mid-breath, not an OOM kill.
**Avoid:** split/chunk long recordings before the handoff (a size/duration guard
in the worker would prevent it).

## Hybrid engine (whisper.cpp / MPS) issues

The default engine is whisper.cpp (ASR) + pyannote-on-MPS (diarize). Failures
in step 2 leave `.FAILED` (log: `asr-mic` / `asr-teams` / `diarize-teams`).

- **`whisper-cli: command not found`** → `brew install whisper-cpp`; the worker's
  launchd PATH must include `/opt/homebrew/bin` (it does in the shipped plist).
- **`model not found`** → download `~/transcribe-pipeline/models/ggml-large-v3.bin`
  (deployment.md § Provision step 2b).
- **MPS op error** → `diarize_assign.py` sets `PYTORCH_ENABLE_MPS_FALLBACK=1`
  already; if a pyannote op still fails, force CPU diarize: edit the worker's
  `diarize_assign.py … --device mps` → `--device cpu` (slower but safe).
- **Escape hatch — fall back to the proven CPU path entirely:** set
  `TRANSCRIBE_ENGINE=whisperx` in the worker's launchd environment (or export it
  before a manual run). Runs the old WhisperX/CTranslate2 CPU path unchanged.
- **Wrong interleave / one speaker as a giant block** → don't re-introduce
  coalescing in `diarize_assign.py`; merge interleaves by per-segment start time
  (see the NB comment in the script).

## Repetition / hallucination loop (one phrase repeated for minutes)

**Symptom:** the transcript devolves into the same short phrase repeated dozens to
hundreds of times (observed: "I'm just going to be in charge of the whole thing"
×250), usually starting partway in — everything after that point is lost. The raw
`.md` is large but its unique-line count is tiny. **Deterministic:** re-pushing the
same audio reproduces it byte-for-byte, so a plain re-run never helps.

**Why:** whisper.cpp carries decoded text as context into the next decode window.
With unbounded context (`-mc -1`, whisper.cpp's *own* default) a quiet / low-speech
stretch lets the decoder feed its last output back into itself and lock into a
loop; the phrase-level `-ml/-sow` segmentation makes the loop especially tight.

**Fix (shipped in `asr_whispercpp.py`):** the ASR step now runs with
**`-mc 0`** (no prior-text context) via the `--max-context` arg, which breaks
the feedback path. Temperature fallback stays on (no `-nf`). `-mc 0` is safe here
because segments are already phrase-level, so cross-window text context bought
little. If you ever need *some* continuity, raise it (`--max-context 64`) — but
expect loop risk to return.

**Detect** an old/looped transcript:
```bash
grep -E '^\[[0-9]' <md> | sed -E 's/^\[[^]]*\] \*\*[^*]+\*\* //' \
  | sort | uniq -c | sort -rn | head      # a top count in the dozens+ = loop
```
**Recover** a loop transcript that predates the fix: re-transcribe the audio with
the fix in place (re-push, or run `asr_whispercpp.py` directly) — `-mc 0` clears
it. Verified: a 23-min track that looped from min ~7 came back full
(00:00–18:27) once `-mc 0` was set.

## Wrong language detected

Whisper's own auto-detect keys off the opening ~30 s only, so a meeting that
starts in the "wrong" language (English smalltalk before a German daily) can
misdetect — which is why contexts used to be hard-pinned per language, quietly
breaking the other half of a bilingual surface (observed: a German daily that
opened in English came out fully English, with hallucinated
"Team Dark Salmon Daily"-style artefacts).

The worker now resolves `language: auto` via **`detect_language.py`** — a
multi-window vote: it samples 3 short clips at 15/45/75 % of the recording, runs
`whisper-cli -dl` (detect-then-exit) on each, and forces the majority language
for the full ASR. Immune to an unrepresentative opening and to a brief
code-switch, at ~10-15 s overhead. Pick per context: a monolingual context gets
a pin (e.g. main=de), a bilingual one gets `auto` (multi-window). Override
anytime: set `language: de|en|auto` in `contexts/<ctx>.yaml`, or per-recording
in the bundle's `manifest.yaml` (manifest wins) — a forced `de`/`en` skips the
vote. If every clip fails to detect, the worker falls back to whisper's own
single-window auto rather than guessing.

**Re-transcribe a recording in the right language** (e.g. a bundle that ran
under a wrong pin): set `language: de` in `<bundle>/manifest.yaml`, then the
full re-run from operations.md § Reprocess (`rm .PROCESSED mic_out/*.json
teams_out/*.json teams-named.json transcript-raw.md teams.wav; touch .READY`)
+ `launchctl kickstart gui/$(id -u)/com.openbridge.transcribe-worker`. Only
bundles without `.PROCESSED` re-run, so clear it on just the ones you mean.

## Manual summary fallback fails (`summarize.py`)

By design the worker delivers only the naked transcript — a "missing summary" is
normal, the summary happens in-session via `/debrief`. This section applies only
when you run the optional `summarize.py` fallback and it errors:
- **claude CLI not found**: check `~/.claude/local/claude` or PATH on the worker.
- **Not authenticated**: only an issue when run from a plain SSH session. The
  launchd worker runs in the GUI session where `claude` is logged in. Re-run via
  `launchctl kickstart -k gui/$(id -u)/com.openbridge.transcribe-worker` rather
  than SSH.
- Re-summarize a finished bundle cheaply: `operations.md` § Reprocess
  → "Re-summarize".

## libavutil / torchcodec warning at startup

```
Library not loaded: @rpath/libavutil.5x.dylib ... [libtorchcodec loading traceback]
```
**Harmless.** brew ffmpeg is v7 (libavutil.59); torchcodec ships shims for v4–6.
WhisperX loads audio via the ffmpeg **CLI**, not torchcodec, so transcription is
unaffected (verified by smoke test). Ignore unless audio loading itself fails —
then check `ffmpeg` is on PATH (`source ~/.zprofile`).

## Bundle never processes

- Worker not triggered: `launchctl print gui/$(id -u)/com.openbridge.transcribe-worker`
  — confirm it's loaded and the WatchPath is `~/transcribe-inbox`.
- No context config: log says "no context config for '<ctx>'". The inbox
  subfolder name must have a matching `contexts/<ctx>.yaml`. Run `add_context.sh`.
- Missing `.READY`: the worker only picks up bundles flagged ready. `touch
  <bundle>/.READY`.

## Back-to-back bundles — the second one stalls at `.READY`

**Symptom:** you push several recordings to the worker in quick succession; the
first processes, a later one sits at `.READY` and never reaches `.PROCESSING`.
**Why:** the launchd WatchPath fires only on changes to **direct** entries of
`~/transcribe-inbox` — a bundle dropped into an *existing* context subfolder
(`main/<ts>`) doesn't trigger it. `debrief_sync.sh push` works around that with a
`launchctl kickstart`, but if the worker is still **busy** with the first bundle
when the second is pushed, that kick is a **no-op** and the worker does **not**
re-scan its inbox when it finishes → the second bundle stalls. (Timing-dependent:
five can run through by luck; two can stall the next day.)
**Fix:** when /debrief pushes 2+ recordings, **poll each bundle** and re-kick any
stalled `.READY` one — `ssh worker-host 'launchctl kickstart
gui/$(id -u)/com.openbridge.transcribe-worker'` (no `-k`, so it never kills a
running ASR). Per-bundle done-marker = `~/transcribe-inbox/<ctx>/<ts>/.PROCESSED`
(flat transcript lands in `~/Transcripts/<ctx>/<ts>.md`, fallback
`transcript-raw.md` in the bundle).
**Never fire-and-forget a push.** A raw `debrief_sync.sh push` + walk-away leaves
worker failures invisible — the next pull finds nothing and the audio silently
never transcribes. This skill owns the whole handoff (copy, kickoff, status,
troubleshoot); drive it through to `.PROCESSED` rather than ad-hoc SSH-debugging
the worker.

## `debrief_sync.sh pull` without a scope grabs sibling-instance contexts

**Symptom:** a bare `debrief_sync.sh pull` pulls a transcript from a context that
belongs to **another Bridge instance** sharing the same worker (say `customer-x`,
operated by a sibling instance — see `docs/multi-instance.md`) into this
instance's imports.
**Why:** without `TRANSCRIBE_CONTEXTS` the script defaults to **every**
provisioned context, so an unscoped pull takes them all. Worse, the pull
**moves** every fetched transcript worker-side into
`~/Transcripts/<ctx>/_debriefed/` (so it's pulled exactly once); `_debriefed/` is
outside the next pull's `maxdepth 1` scan → the sibling instance can then no
longer pull its own transcript (it's stuck in the "consumed" graveyard).
**Fix:** pull **only** your own contexts. Always scope a manual pull:
`TRANSCRIBE_CONTEXTS=main bash skills/meeting-transcription/scripts/debrief_sync.sh pull`.
The `/debrief` pickup already does this right (per-context, own contexts only) —
the footgun is only the bare manual pull.
**Recover** an accidentally-grabbed foreign transcript: trash the local copy, then
on the worker `mv ~/Transcripts/<ctx>/_debriefed/<file> ~/Transcripts/<ctx>/` (a
worker write on a shared host — get the user's explicit OK first).

## Worker host asleep / unreachable

Capture side defers (bundle keeps `.READY`, no `.PUSHED`); the bundler's
catch-up pass pushes it next run once the host is back. Workers are normally
always-on; for a Wake-on-LAN-capable box see the `remote` skill. No data is
lost — recordings sit in `~/Recordings/meetings/<ctx>/<ts>/` until pushed.
