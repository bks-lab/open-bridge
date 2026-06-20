---
scope: core
description: Config-type resolution helper — Default-to-Folder discovery glob over the cluster wrappers
---

# Discovery — Config-Type Resolution Helper

Bridge follows the Default-to-Folder rule: every config type lives in
`<wrapper>/<types>/`. Skills that need "all mandants" or "all personas"
call `discover()` and get the instances back as a sorted list of paths.
Templates and schemas (`_` prefix) are excluded.

## Config authoring — declare capabilities, not consumers

Discovery only works one direction: a **provider declares WHAT it offers**, a
**skill discovers WHO offers what it needs** — never the reverse. A config
file must never carry a `consumers:` list that names the specific skills using
it.

**The gate** — before adding any config section that more than one skill reads:

1. **Provider declares `provides:`** — a capability list (`provides: [chat,
   calls, calendar, ...]`), describing WHAT it delivers, not WHO consumes it.
2. **Skill discovers by capability** — it asks "who provides capability X?",
   never "who listed me as a consumer?". Same `discover()` direction as the
   contract below.
3. **Skill-specific tuning stays out of the provider block** — `window_min`,
   `formats`, filters live in the skill workflow or namespaced under
   `<skill>.<key>`, never nested inside the provider's section.

**Why** — a `consumers: [briefing, debrief]` field forces every skill author to
patch all provider configs when their skill starts consuming, and forces every
provider author to know its consumers in advance: bidirectional coupling, an
anti-pattern. Capability-based discovery scales O(1) per new skill **and** O(1)
per new provider — other Bridge instances (open-bridge OSS, org overlays,
third-party) add a provider without touching skill code, and add a skill
without patching existing configs.

**Litmus** — for a new shared config section ask: "can a new provider be added
without changing skill code? Can a new skill consume without patching provider
configs?" If either answer is no, the schema couples the wrong way — restructure
it. Reference shape: `integrations.context_sources.{name}.provides: [...]` in
`bridge-config.yaml`. The same logic governs `trackers/{name}.md` playbooks,
channel definitions, and any future data-source slot.

## Contract

```python
def discover(type_singular: str, repo_root: Path | None = None) -> list[Path]:
    """
    Resolve all instances of a config type.

    Parameters:
      type_singular: type name in singular form (e.g. "persona", "mandant", "remote")
      repo_root:     optional. Defaults to env var BRIDGE_ROOT, then cwd.

    Returns:
      sorted list of yaml file Paths matching the type. Excludes _-prefixed
      files (templates, schemas, state).

    Caveats:
      - Plural is hardcoded as `<singular>+s`. Keep type names regular.
      - Searches identity/, infra/, workflow/ wrappers in that order.
        First wrapper containing the folder wins.
    """
    root = Path(repo_root or os.environ.get("BRIDGE_ROOT") or Path.cwd())
    for wrapper in ["identity", "infra", "workflow"]:
        folder = root / wrapper / f"{type_singular}s"
        if folder.is_dir():
            return sorted(f for f in folder.glob("*.yaml") if not f.name.startswith("_"))
    return []
```

## Behavior

Per type, `discover()` checks in order:
1. Does the `<wrapper>/<type>s/` folder exist? → take the `*.yaml` files inside (except `_*`-prefixed).
2. Otherwise: empty list (the folder must exist — if it doesn't, the type is not set up).

Wrapper order: `identity` → `infra` → `workflow`. First non-empty match set wins.

## Example calls

```python
discover('persona')   # ['identity/personas/alice-work.yaml', ...]
discover('account')   # ['identity/accounts/alice-personal.yaml', ...]
discover('mandant')   # ['identity/mandants/acme.yaml', ...]
discover('remote')    # ['infra/remotes/workstation.yaml', ...]
discover('channel')   # ['infra/channels/imessage.yaml', ...]
discover('backup')    # ['infra/backups/topology.yaml']  (Singleton)
discover('calendar')  # ['workflow/calendars/entries.yaml']  (Singleton)
discover('context')   # ['workflow/contexts/doc-system.yaml']
discover('project')   # ['workflow/projects/customer-x.yaml', ...]
```

## Implementation note

A central reference implementation does **not** live as a shared Python package today.
Skills inline the code or use `find`/`ls` from Bash. Once multiple skills
replicate the same logic, an extract to `scripts/discover.py` or
`skills/_shared/discover.py` becomes worthwhile.

## Plural caveat

`<singular> + s` works for **all current types**:
persona/personas, account/accounts, mandant/mandants, remote/remotes,
channel/channels, backup/backups, calendar/calendars, context/contexts,
project/projects.

A hypothetical type with an irregular plural (e.g. "index" → "indices")
would require the helper to map manually. No need today — type names are
chosen to be regular.

## Singletons

Some types have exactly one instance today (calendar as master list,
backup topology). They still live in the plural folder; the filename
describes the content:

- `workflow/calendars/entries.yaml`  — all calendar entries
- `infra/backups/topology.yaml`      — source × target × pipeline definitions

If the type becomes multi-file later, additional files go alongside — no
layout change needed.

## Source

Defined first in the AGENTS.md "Layout — Cluster-Wrappers" section
"Discovery". This file is the external reference linked from there.
