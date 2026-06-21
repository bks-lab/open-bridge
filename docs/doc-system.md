---
summary: "Document intake & filing system — concept, folder-method choice (PARA recommended), and how to wire it up"
type: guide
last_updated: 2026-05-14
related:
  - ../skills/doc-system/SKILL.md
  - ../workflow/contexts/_doc-system.template.yaml
  - personas.md
  - extension-model.md
---

# Doc-System

A small, context-driven pipeline for "scan it, name it, tag it, file it,
audit it." You point it at one or more inbox folders, declare routing
rules in YAML, and the `/doc-system` skill walks each new file through
a preview → confirm → file → log cycle.

It is intentionally **agnostic** about how you organize your documents.
The skill reads paths and rules from `workflow/contexts/doc-system.yaml`;
the folder layout is yours to choose.

## Why have this at all

If you have any combination of:

- a scanner or "send to my computer" button on a printer
- a Downloads folder that accretes PDFs faster than you can file them
- a yearly tax bundle you assemble from many small receipts
- multiple roles (private + freelancer + LLC + family) with separate
  filing destinations
- a need to **audit** where each document came from and went to

…then a 90 %-automated intake pipeline is worth more than another
folder-cleanup weekend. The skill never deletes files on its own and
writes every action to `work/doc-system/log.md` in your git repo so
you can recover from any cloud-sync mishap.

## Recommended folder method: **PARA**

[PARA](https://fortelabs.com/blog/para/) (Tiago Forte) is the default
this template ships with. Four top-level buckets:

| Folder | Holds |
|---|---|
| `1_PROJECTS` | Active, time-bound efforts with an outcome |
| `2_AREAS` | Ongoing responsibilities (health, finances, home, family) |
| `3_RESOURCES` | Reference material, branding, knowledge you reuse |
| `4_ARCHIVE` | Inactive, read-only |

PARA fits the doc-system well because **most filed documents land
under `2_AREAS`** — by life domain, not by project — and you rarely
need to reshuffle when a project ends. The template's example areas
(`Tax`, `Family`, `Health`, `Home`, `Bank`, `Insurance`) sit there.

### When *not* to use PARA

Pick something else if any of these apply:

| Method | Good fit when | Trade-off |
|---|---|---|
| **Johnny Decimal** (`10-19_<Area>/11_<sub>/`) | You like numeric encoding, dislike folder rename churn | Slight learning curve; less self-describing on first glance |
| **GTD-flavored** (`@action`, `@waiting`, `@reference`) | You think in *next-action terms*, not life-domain terms | Less useful for archival; better as a working layer on top of PARA |
| **Custom flat** (whatever you already use) | You have an established system that works | The doc-system doesn't care — just update `areas:` in the template |

The skill doesn't care which you pick. It reads paths from
`context.areas[*].path`. **Change the folders, not the skill.**

## How the pieces fit together

```
                    ┌──────────────────────────────────────┐
                    │  bridge-config.yaml                  │
                    │    doc_sensor:                       │
                    │      enabled: true                   │
                    │      onedrive_root: ~/Documents/PARA │
                    │      scan_paths:  [0_Import, …]      │
                    └──────────────┬───────────────────────┘
                                   │
                ┌──────────────────┴──────────────────┐
                │                                     │
                ▼                                     ▼
   workflow/contexts/doc-system.yaml      identity/personas/<id>.yaml
   - areas (folder layout)                - tax data
   - naming pattern                       - destinations (paths)
   - tags                                 - signature
   - routing rules                        - vehicle classification
   - anti-patterns                        - mandant link
                │                                     │
                └─────────────────┬───────────────────┘
                                  │
                                  ▼
                      skills/doc-system/  ─►  work/doc-system/log.md
                      (mechanics: scan, categorize,
                       preview, file, tag, audit)
```

Five layers, each with one job:

| Layer | Concern | Touched by user |
|---|---|---|
| **Skill** (`skills/doc-system/`) | Mechanics: scan, categorize, preview, file, tag, audit | Almost never |
| **Context** (`workflow/contexts/doc-system.yaml`) | Areas, naming, tags, routing rules, anti-patterns | When adding new rules |
| **Personas** (`identity/personas/<id>.yaml`) | Tax data, signature, destination paths per identity | When adding a new role |
| **Config** (`bridge-config.yaml`) | Enable flag, root path, scan/queue paths | Once, at setup |
| **Audit** (`work/doc-system/log.md`) | Append-only history of every move | Never — writes only |

## Personas (optional, powerful)

A persona = "which hat am I wearing right now" — freelancer, LLC
director, private person, employee. Each persona declares its own
**destinations** (filing paths) and its own **tax data** (IDs,
accountant info, vehicle classification).

Why this matters: routing rules don't hardcode paths. They say
"file this with persona X under destination Y", and the skill
resolves Y by reading the persona file. That means:

- You can swap accountants per persona without touching routing rules
- A vehicle plate belongs to *one* persona (business vs private —
  the same expense routes differently)
- Tax bundles auto-split: each persona's receipts land in their own
  outbox, then go to the right preparer

If you don't need this, leave `personas: {}` in the context YAML and
use `target: { area: …, subpath: … }` everywhere. Skill works fine.

## Routing rules — the cookbook

Every rule has:

```yaml
- id: <unique-slug>
  match:
    content_any:   [<string>, ...]   # one must appear in content
    keyword_any:   [<exact>, ...]    # exact match (account #, plate, ID)
    vendor_any:    [<name>, ...]     # sender / supplier name
    not_keyword:   <string>          # skip rule if this is present
    persona_hint:  <persona-alias>   # document self-identifies persona
  target:
    # ONE of:
    persona: <alias>                 # → personas[<alias>] → file → destinations
    dest:    <destination-key>
    # OR:
    area:    <area-id>
    subpath: "<relative path>"
  prefix:  <persona-alias>           # optional — prepends naming.prefixes[<alias>]
  note:    "<rationale or warning>"
```

**Order matters — first match wins.** Put anti-patterns at the top so
they catch edge cases before generic rules. Examples:

```yaml
routing:
  # Anti-pattern: medical bills go to insurance first, not tax
  - id: insurance-before-tax
    match:
      content_any: ["medical bill", "Klinik", "clinic"]
    target: { area: areas, subpath: "Health" }
    note: "Insurance reimbursement first, then maybe tax"

  # Generic: utility bills go to Home
  - id: utility-bill
    match:
      content_any: [Heizkostenabrechnung, "utility bill"]
    target: { area: areas, subpath: "Home" }
```

## Wiring it up

1. **Choose a folder method** (PARA is the default; adapt if needed)
2. **Copy the template:**
   ```bash
   cp workflow/contexts/_doc-system.template.yaml \
      workflow/contexts/doc-system.yaml
   ```
3. **Enable in `bridge-config.yaml`:**
   ```yaml
   doc_sensor:
     enabled: true
     onedrive_root: ~/Documents/PARA      # any local folder — name historical
     scan_paths:    [0_Import, 2_AREAS/Import]
     queue_paths:   []                    # add per-persona outboxes when ready
   ```
4. **Scaffold the folders** (if they don't exist):
   ```bash
   mkdir -p ~/Documents/PARA/{0_Import,1_PROJECTS,2_AREAS,3_RESOURCES,4_ARCHIVE}
   ```
5. **(Optional) Create personas:**
   ```bash
   cp identity/personas/_template.yaml \
      identity/personas/<your-persona-id>.yaml
   # Edit destinations + tax data, then add to context.yaml personas: map
   ```
6. **Test:** drop a PDF in `0_Import/`, run `/doc-system` and check the
   inbox status, then process it. Confirm the suggested rename +
   destination look right before letting it move.

## What the skill will NEVER do

- Delete a file without explicit user OK
- Apply a routing rule from memory — always re-reads `context.yaml`
- Touch a file outside `doc_sensor.scan_paths`
- Rewrite the audit log (append-only)
- Cross persona boundaries (a freelancer rule won't file into a
  private persona's outbox without the rule saying so)

## Cross-references

- Skill: [`skills/doc-system/SKILL.md`](../skills/doc-system/SKILL.md)
- Template: [`workflow/contexts/_doc-system.template.yaml`](../workflow/contexts/_doc-system.template.yaml)
- Persona concept: [`docs/personas.md`](personas.md)
- How this skill is `scope: core` and where it sits in the layered repo:
  [`docs/extension-model.md`](extension-model.md)
