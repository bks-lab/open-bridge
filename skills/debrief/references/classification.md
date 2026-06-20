# Meeting Classification & Name Corrections

## Meeting Type Classification (priority order)

| Priority | Type | Signal | Protocol Depth |
|----------|------|--------|---------------|
| 1 | Team Weekly | Multiple internal participants + varied topics | Full |
| 2 | Customer Weekly | Known customer contacts present | Full |
| 3 | Workshop | Workshop signals in content (see below) | Workshop (deep) |
| 4 | Strategy | Themes: strategy, roadmap, vision, planning | Full |
| 5 | Customer Meeting | Any customer contact identified | Standard |
| 6 | Short Sync | Only internal + short duration (< 15 min) | Minimal |
| 7 | Internal Sync | Fallback for internal meetings | Standard |

**Workshop signals** (regex):
```
Business Model Canvas|BMC|Value Proposition|Ideation|Brainstorming|Canvas|
Strategy Workshop|Design Thinking|Sprint Planning|Retrospective
```

**Lead/application signals** (regex — separate class, takes precedence over
customer-meeting because thematically separate; relevant if you track an
application/lead pipeline). Keywords may be multilingual — match the
language(s) your meetings happen in. Example set (English + German):
```
hourly rate|daily rate|profile submitted|Probability|
Recruiter|application interview|cover letter|resume|CV|
Key Account Manager|application|interview|
Stundensatz|Tagessatz|Vermittler|Bewerbung|Lebenslauf
```

**Voice-memo signals** (candidate for trash instead of archive):
- File < 1 KB **or** < 60 seconds
- No speaker changes (`Microsoft Teams:` appears only once)
- Content is a waiting note, test ping, empty recording

**Participant detection:** Match names against known contacts from
ecosystem context (wiki, mandants, project teams). If a specialized
`process-transcription` skill exists globally with participant lists,
defer classification to it.

## Target-Repo Routing (NEW)

After meeting-type classification **before archiving**, decide where the transcript belongs. The default is not always the current repo.

| Detection | Repo / Path | Example |
|---|---|---|
| **Customer marker for `<customer-overlay>-bridge`** (recurring customer names, project codenames, key stakeholders specific to that engagement) | `~/Developer/<customer-overlay>-bridge/work/archive/days/{YYYY-MM}/` | Customer sync |
| **Application/lead interview** (see lead signals above) | `wiki/leads/{slug}/meetings/{YYYY-MM-DD}_{HHMM}_{topic}.txt` + update `lead.yaml` | recruiter interview (BigCorp role) |
| **Workshop with its own customer project** | `wiki/customers/{name}/projects/{project}/meetings/...` | CustomerA/CustomerB workshop |
| **Mixed meeting** (two clearly separated topics with timestamp switch) | Run **split phase**, route both parts separately | Org forensics + customer sync in the same file |
| **Voice memo without value** (see voice-memo signals) | `~/.Trash/` with timestamp prefix | "Waiting for Sam" 30s |
| **Default (org-internal meeting)** | `<your-bridge>/work/archive/days/{YYYY-MM}/` | CustomerA weekly, Sam sync, org weekly |

**Split workflow for mixed meetings** (short):
1. Read file, find timestamp markers (`[HH:MM:SS.ms]`) between topics
2. Look for transition phrases: new speakers appearing, language switches DE<->EN, topic cues ("Hi Riley!", "Okay, thanks Dana, on to ...")
3. Split with Python (NOT shell regex — `BASH_REMATCH` is empty in the zsh-based Bash tool)
4. Write two files, each with its own slug + its own repo target
5. Send original to the local `~/.Trash/` with timestamp prefix (NOT trash-CLI on OneDrive volumes)

## Checkpoint 1: Classification Review

## Checkpoint 1: Classification Review

Present results before proceeding:

```
Transcript Classification:

  File              | Type              | Participants    | Depth
  -----------------------------------------------------------------
  2026-04-12.txt    | Customer Weekly   | Alice, Bob, Me  | Full
  sync-morning.m4a  | Short Sync        | Me, Colleague   | Minimal

  ML Corrections applied: "Sammy" -> "Sam" (1 occurrence)

  [y] Confirm  [e] Edit types  [s] Skip file  [c] Add correction
```

## Meeting-Type Configuration

Per meeting type, configure which projects to reconcile against (Phase 5),
which mandant to notify (Phase 7), and the protocol wiki path (Phase 6).
Users can override defaults via `bridge-config.yaml` under `debrief.meeting_types:`.

```yaml
meeting_types:
  team-weekly:
    depth: full
    reconcile_projects: [7]             # primary team project
    distribution:
      email: true
      mandant: team
      exclude_absent: true             # do NOT email people who missed the meeting
    wiki_path: wiki/{org}/protocols/weekly-meetings/
    protocol_slug_template: "{YYYY-MM-DD}-weekly"

  customer-weekly:
    depth: full
    reconcile_projects: [42]           # example: customer project
    distribution:
      email: false                     # customers do not receive bot mail
    wiki_path: wiki/customers/{customer}/protocols/meetings/
    protocol_slug_template: "{YYYY-MM-DD}-{customer}-weekly"

  workshop:
    depth: workshop
    reconcile_projects: []             # workshops produce plans, not task-reconciliation
    distribution:
      email: false
    wiki_path: wiki/{org}/protocols/strategy-meetings/

  short-sync:
    depth: minimal
    reconcile_projects: []             # skip reconciliation for < 15 min syncs
    distribution:
      email: false

  internal-sync:
    depth: standard
    reconcile_projects: [7]
    distribution:
      email: false                     # opt-in via --email flag
```

**Fallback:** if a type has no entry here, use `internal-sync` as safe
default (standard depth, no distribution email, reconciliation against
the primary team project if `bridge-config.yaml` defines one).

## Name Corrections

Before extraction, normalize names, project names, and company names.

### Correction Categories

| Category | Example | Purpose |
|----------|---------|---------|
| People | "Sammy" -> "Sam" | Speech-to-text misrecognition |
| Projects | "Project Beta" -> "ProjectBeta" | Phonetic confusion / boundary errors |
| Companies | "Cust B" -> "CustomerB" | Word boundary errors |
| Roles | "Kierke Manager" -> "Key Account Manager" | Acoustic mishearing of English in DE meeting |

### Frequent corrections (example)

Illustrative only — replace with your own validated misrecognitions from your Whisper output:

| Canonical | Whisper artifacts | Context |
|---|---|---|
| **Sam** | Sammy, Sem, Cem | Org partner (Finance/Ops) |
| **Robin** | Robbie, Robyn | Org partner |
| **Provider** | Provyder, Pro-Vider | Integration service provider |
| **CustomerA** | Custom-A, Cust A | Customer |
| **CustomerB** | Cust B, Customer Bee | Customer |
| **CustomerA-Sub** | Cust-A Sub | CustomerA subsidiary |
| **Network** | Net-Work, Netvork | E-invoicing network standard |
| **Customer contacts** | (varies) | CustomerA counterparts |
| **Key Account Manager** | Kierke Manager | Recruiter role title |

Corrections are cumulative — maintain a correction map that grows over time.
Store in `work/name-corrections.yaml` (USER layer). Format:

```yaml
corrections:
  people:
    Sammy: Sam
    Robbie: Robin
  projects:
    PROJID: ProjectName
  companies:
    "Acme Inc": Acme
    "Example Corp": ExampleCorp
```

When a new correction is discovered during processing, offer to add it.
