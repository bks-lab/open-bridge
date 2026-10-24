---
summary: A table of contents for a large declared source, and one block on demand — the progressive disclosure skills always had, applied to registries and config maps.
type: reference
last_updated: 2026-10-24
related:
  - AGENTS.md
  - rules/operations.md
  - context-budget.yaml
  - docs/schemas/context-budget.schema.yaml
---

# Context Index

`context-budget.yaml` measures what a session loads before it answers anything,
and holds each item to a declared ceiling. Measuring cannot make anything
smaller. This is the half that can.

## The problem it solves

A session needs to know **that** a customer called `northwind` exists and
roughly what it is. It does not need that customer's fifteen fields until
somebody names it. Read whole, a registry costs a paragraph per project in
order to establish that the project exists.

Skills have never worked that way: the name and one line stay resident, the
body arrives on invocation. Standing orders got the same split when the load
contract landed. Registries and config maps never did, and every attempt to
fix one of them separately produced another one-off script.

## The contract

An item in `context-budget.yaml` may declare a `card:` — what the session loads
**instead of** the file.

```yaml
ecosystem.yaml:
  optional: true
  source: phase1
  card:
    kind: index          # bare: the shape is detected from the file
```

Declaring the shape is optional and per field:

```yaml
  card:
    kind: index
    keep: [org, local_root, work_system]
    sections: [base, customers, internal, partners, workspaces]
    label: [description, display_name, name]
```

| Field | Meaning |
|---|---|
| `keep` | Top-level keys emitted **verbatim**, comments included. The settings a session needs in front of it, not on request. |
| `sections` | Top-level maps whose children become one index line each. |
| `label` | The child field supplying that line. A list is tried in order. |
| `label_chars` | Where a label is cut, with a visible ellipsis (default 120). |

**Absent is not empty.** An absent `keep:` or `sections:` is detected from the
file's shape; an empty list is a decision and stays empty. Each field defaults
on its own, so declaring only `keep:` does not silently switch indexing off.
CORE ships the bare form, because naming sections there would fail the
`--check` guard on the first instance whose registry legitimately has no
`partners:`.

**A card replaces the import; it never sits beside it.** An `@`-import loads
the whole file into every session, whatever the budget declares, so a file that
carries a `card:` and is still `@`-imported (from `CLAUDE.md` or any file it
imports) is reported `contradiction` by `scripts/measure-context.py`: measured by
its full text, and failing at any size. Measuring the card there would report
green for bytes nobody pays while the session pays for the rest. If sub-agents
need the registry, import a generated card file, not the source.

Everything else present in the file is named under **"also present"**. Kept,
indexed, or merely named — but never absent. A card that silently omits a key
is the same failure as a budget that silently omits a file, one layer down:
the thing does not look missing, it looks like it was never there.

## Using it

```bash
python3 scripts/context-index.py ecosystem.yaml                  # the card
python3 scripts/context-index.py ecosystem.yaml --get customers.northwind
python3 scripts/context-index.py ecosystem.yaml --list           # every path --get takes
python3 scripts/context-index.py --check                         # the guards, CI runs this
```

Phase 1 (`rules/operations.md`) runs the first form. The rest is on demand.

The memory base gets the same split without a `card:`, because its index is
already a table of contents: Phase 1 runs
`python3 scripts/memory-location.py index` and a fact arrives with
`get <name>`, on any harness. Details: [`memory.md`](memory.md) § Reading it on
any harness.

## Three decisions worth knowing

**Slices are raw text, never re-serialized YAML.** A round trip through a YAML
loader is lossy in exactly the direction that matters: comments. In these files
the comments carry the reasoning — which branch is the running one, which board
is closed, why a path is not the obvious one. A reader that strips them answers
the letter of the question and drops the half that stops a wrong action. A
comment touching an entry travels with it; one separated by a blank line stays
with the section.

**Fail-open, twice.** A file with no `card:` stays always-on in full, so an
instance that has never heard of this feature loses nothing. And a file that is
indexed without a declaration gets its sections detected from its own shape,
where a map counts as a section only when **all** its children are maps — a
block of mixed settings is configuration and stays resident, because
`work.enabled` decides whether Phase 1 runs at all.

**A YAML comment stops being a guardrail the day its file stops being read
whole.** The card cannot carry comments that sit inside indexed sections, so it
reports how many bytes those are rather than letting a migration discover it
later. If such a comment is load-bearing, it belongs in a rule, a standing
order, or a field — all three of which travel.

## What the guards catch

`--check` runs four, over every declared card, and CI runs `--check`:

- **The declaration** — a name in `keep:` or `sections:` that the source does
  not have, or one declared in both. This is the failure surface the feature
  adds: the typo is absorbed in silence, the real key falls through to "also
  present", its content stops being resident, and the card still renders and
  still passes its cap.
- **The structure** — the line scanner's answer against `yaml.compose`, which
  already knows it. This is the strongest of the four, and it exists because
  the other three could not see the worst bug the feature has had: a list item
  at column zero (`- name: public`, legal YAML) was read as a top-level key,
  which ended its neighbour's block at that line. The real key then sliced to
  its header alone — eleven bytes on a live `bridge-config.yaml` — and the
  round trip called it clean, because one line is still something.
  `compose` rather than `safe_load` on purpose: `safe_load` resolves `on:` to
  the boolean `True`, and it hides whether a value was written in flow style,
  so `required: [a, b]` looks like a truncation. Without both distinctions this
  guard's first outing produced 54 findings over 255 real files, none of them
  real.
- **The round trip** — every path the index advertises has to slice to
  something. A pointer reads as a promise that the content is one call away,
  and the caller stops looking anywhere else.
- **Coverage** — every top-level key of the source is findable in the card,
  matched as a heading, a kept key line or a name in "also present" — never as
  a substring, since `org` occurs inside `example-org`.

The suite also runs all three content guards over **every YAML file in the
repo** on each CI run. The fixture is what the author imagined; the tree is
what actually exists, and the difference has been this feature's whole yield.

## The other two checks in this family

`context-budget.yaml` says how much the always-on layer may weigh and this file
says how a large source is cut down. Two more guards cover what neither can see,
and CI runs both:

| Check | Question |
|---|---|
| `scripts/check-reachability.py` | does a session still KNOW the body is there — every config family named by its path in the routing surface, plus eleven scenarios walked end to end |
| `scripts/check-edges.py` | do the references BETWEEN entries still resolve — `ok` / `moved` (mechanical, `--fix`) / `external` / `dead`, with per-instance exceptions declared in `edges.yaml`, each carrying a reason |

The reachability check runs against the **routing** surface, which is the
always-on layer minus `work/` and the log slice. Work state is measured to the
byte by the budget and cannot satisfy a routing claim: a family named only in a
work-log row is unreachable again within days, and the guard would stay green
throughout.

The `listing:skills` row in `measure-context.py` counts what the harness lists,
not what `skills/` holds: user-level and enabled plugin skills join it, and
`skillOverrides` from user, project and local settings (local wins) applies to
every non-plugin entry, so `"off"` and `"user-invocable-only"` drop out and
`"name-only"` counts the name alone. The meter merges those files per skill
name, because the settings reference defines the value per name and states no
whole-object replacement. Managed settings are not read. The harness cuts
descriptions at 1 % of the context window. The meter cannot know the window, so it names
`skillListingBudgetFraction`, `skillListingMaxDescChars` or
`SLASH_COMMAND_TOOL_CHAR_BUDGET` in the report when one is set, and guesses
nothing. The guards keep reading the tree's own listing, so their verdict never
depends on the machine.

## The cost

An `@`-import is resident for the whole session; a Phase 1 read is ordinary
conversation and can be compacted away later. Indexing a source moves it from
the first kind to the second. The card is small enough to re-run and `--get` is
always there, but the trade is real and is the reason this is declared per item
rather than applied to everything that looks large.
