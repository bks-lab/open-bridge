---
summary: "Turn a repo (or its architecture doc) into an html-canvas architecture explainer — deterministic seed, doc-driven shortcut, or offered subagent fan-out"
type: reference
last_updated: 2026-06-01
related:
  - skills/html-canvas/SKILL.md
  - skills/html-canvas/scripts/repo-scan.py
  - skills/html-canvas/references/sections.md
  - skills/html-canvas/references/build-workflow.md
---

# html-canvas — Repo → Architecture Explainer

Produce a sectioned, themeable, bilingual architecture explainer from **either**
an existing architecture doc **or** a
thorough analysis of the actual code. The render half is the section catalog;
this file is the **analysis half** — how to get a faithful Architecture Spec
into those blocks without inventing anything.

> **Verify against code — the hard rule.** Architecture is the easiest thing to
> hallucinate plausibly. Every component, edge, and flow in the spec must trace
> to a real file/symbol path. Anything you can't source goes under an explicit
> **caveat** (SOUL: verify before claim), never stated as fact. On a big repo, say
> what you sampled vs. read exhaustively — no silent caps.

## Step 0 — Deterministic seed (always)
Ground the analysis in facts before reasoning:
```bash
python3 skills/html-canvas/scripts/repo-scan.py <repo> [--json]
```
It reports languages-by-LOC, entry points, parsed dependency manifests
(Cargo/npm/pyproject/go.mod/requirements), top-level structure, and ranked
documentation files. The doc list is your shortcut detector; the entry points +
top-level map are where the code-driven fan-out starts.

## Pick the path

### Path A — Doc-driven scan (cheap default)
If the repo already carries a substantial architecture/design doc (repo-scan
ranks docs by LOC — e.g. a large `docs/architecture.md` or design doc),
**read that doc as the primary source**, extract the Architecture Spec from it,
and render. No subagents needed. This is the doc-driven path.
Still spot-check a few cited files so the doc isn't stale.

### Path B — Code-driven subagent fan-out (OFFER it, opt-in)
For a real **repo scan / project scan** with no doc (or when you want
ground-truth from the code, not a possibly-stale doc), this is a heavy operation
(many subagents / a workflow over a large tree). **Do not run it silently — offer
it** and let the user opt in (the Bridge advises; token cost is real):

> *"This is a large repo (N kLOC). I can analyze the architecture thoroughly via
> a subagent fan-out (one agent each for modules, data model, flows, deps, …) and
> build the explainer from that — it spins up several agents. Go ahead?"*

On opt-in, fan out one agent per facet (mechanics: `references/build-workflow.md`
§ parallel-builder — a Workflow with a barrier, or N `Task` subagents in one
message). Each returns a **structured slice with file citations**:

| # | Facet | The agent maps | Must cite |
|---|-------|----------------|-----------|
| a | Entry & run | entry points, build/run, CLI/commands, config | `main.*`, manifests, README run section |
| b | Module / layer map | top modules, layers, their responsibility + boundaries | dir paths, key mod files |
| c | Data model | entities, fields, relations, storage | type/struct/model files, schema/migrations |
| d | Data & request flows | request paths, pipelines, the agent/event loops | handler/router/pipeline files |
| e | External deps & integrations | 3rd-party services, SDKs, protocols, the manifests | manifest deps, client wrappers |
| f | Existing docs & README | what the repo already says about itself | README, docs/*.md |
| g | Stack & key abstractions | language/runtime, the load-bearing abstractions/traits | core trait/interface files |

## Architecture Spec (the synthesis target)
Merge the slices (or the doc) into one spec — this is what the section blocks consume:
```yaml
name:        # repo / subsystem name
one_liner:   # what it does, one sentence
stack:       [ languages, runtimes, key frameworks ]
layers:      [ { name, role } ]                          # vision → … → tech (for the ladder)
components:  [ { name, role, layer, paths:[...] } ]      # C4 boxes
edges:       [ { from, to, kind, label } ]               # calls / depends-on / data
data_model:  { entities:[ { name, fields?, paths } ], relations:[ { from, to, kind } ] }
flows:       [ { name, steps:[ { actor, action } ] } ]   # request/response, pipelines
use_cases:   [ { id, cluster, title } ]                  # optional (a use-case catalog)
comparisons: [ { axis, option_a, option_b, note } ]      # optional A/B (e.g. two backends)
roadmap:     [ { when, item } ]                          # optional
decisions:   [ { choice, why } ]                         # optional ADR-style
open_questions: [ ... ]                                  # the caveat list
```

## Spec → section mapping
Compose `<main>` from `references/sections.md` blocks:

| Spec field | Section block |
|---|---|
| `one_liner` / `stack` | hero (1 accent word) · KPI-row · chips |
| `layers` | abstraction ladder |
| `components` + `edges` | C4 boxes · theme-adaptive SVG diagram · NOT-vs-IS for "is/isn't" |
| `data_model` | data table · spec card per entity · SVG ER sketch |
| `flows` | pipeline · three-track swimlane · **A→B message-flow** (request/response, agent loops) |
| `comparisons` | comparison matrix (shape glyphs ● ◐ ✗) |
| `use_cases` | matrix · chips · cards |
| `roadmap` | vertical timeline |
| `decisions` / `open_questions` | callout (warn/caveat variant for the unsourced) |

## Render
Build with the shell as usual (`build-workflow.md`): light/dark (T) + DE/EN (L) +
the animation layer. The **A→B message-flow** block is the natural fit for an
agent/request loop (a request→response or agent-loop trace fits here). File the
result under `work/tasks/<slug>/deliverables/`.

## Verify (before "done")
Adversarial pass: every component/edge/flow traces to a cited path; no invented
modules; unsourced claims sit under a caveat; on a large repo, the footer/notes
state what was sampled vs. read in full. Then render light+dark and DE+EN.
