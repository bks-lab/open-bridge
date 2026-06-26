# Authoring an Org Overlay

This is the **publisher** side: how an organisation packages its shared Bridge
config into a git repo its members subscribe to with `/overlay add <git-url>`.
The consumer side (sync algorithm, gates) is `references/workflow.md`; the
narrative lives in `docs/org-overlays.md`. Schemas are authoritative:
`docs/schemas/overlay-manifest.schema.yaml` and
`docs/schemas/overlays-lock.schema.yaml`.

> **One golden rule:** an overlay is a **build artifact exported from your
> org's own Bridge**, not a folder you hand-edit per consumer. See *Build-artifact
> discipline* at the bottom — it's the discipline that keeps every member's
> Bridge identical and auditable.

## Repo contract

```
<your-overlay-repo>/
├── overlay.manifest.yaml            REQUIRED  — root declaration (schema-validated)
├── README.md                        REQUIRED  — what this overlay is, who it's for
├── ecosystem.<org>.yaml             OPTIONAL  — ecosystem fragment (@import-wired, never merged)
├── .github/workflows/publish-guard.yml  RECOMMENDED — leak gate before publish
└── tree/                            the mirror — mirrors the Bridge layout
    ├── workflow/contexts/<org>-billing.yaml
    ├── workflow/projects/<org>-platform.yaml
    ├── identity/mandants/<org>-team.yaml
    ├── identity/accounts/<org>-azure.yaml
    ├── skills/<org>-context/SKILL.md
    └── protocols/standing-orders/<org>-routing.md
```

**Materialization:** every `tree/<path>` materializes to `<path>` (the engine
strips the `source_root`, default `tree/`). So
`tree/workflow/contexts/example-org-billing.yaml` lands at
`workflow/contexts/example-org-billing.yaml` in every consumer. Each file is
`scope: org`.

### HARD rules the engine refuses or warns on

The consumer's engine enforces these; author to them so nothing gets dropped on
subscribe:

| Rule | Engine reaction | Why |
|---|---|---|
| **Never ship** `_template.yaml` / `_schema.yaml` | **HARD-REFUSE** | those are CORE — they ship with open-bridge, not your overlay |
| **Never ship** a cluster-wrapper `README.md` | **HARD-REFUSE** | CORE docs; an overlay isn't documentation |
| **Never ship** `identity/personas/**` | **HARD-REFUSE** | a persona is an identity the *user* holds, never org-supplied |
| **Never ship** `work/**` | **HARD-REFUSE** | the consumer's task state, not yours |
| **Never ship** anything that classifies `core` or `_`-prefixed | **HARD-REFUSE** | overlays write `scope: org` only |
| Discoverable instances (contexts / projects / mandants / …) MUST be **flat** `<slug>.yaml` | **WARN** | a nested-folder context is invisible to `discover()` |
| Slugs MUST be **org-namespaced** (`<org>-*`) | **WARN** | a bare slug flat-collides with a user's own files |
| Accounts carry **only** `azure-keyvault://` / `keychain://` / `1password://` URIs | **REFUSE** (raw-secret scan) | never ship a real secret; ship a reference |

## Manifest authoring

The manifest is the **only** declaration file. The common case is a flat mirror;
`files[]` is the **exception list** — list a file there only when it needs a
`kind` tag, a per-file conflict policy, or prompt fields.

### Minimal manifest (flat mirror, everything `scope: org`)

```yaml
# yaml-language-server: $schema=./docs/schemas/overlay-manifest.schema.yaml
schema_version: 1
overlay:
  name: example-org              # lowercase-kebab; = lock key, = subscription name
  org: example-org               # generic, PII-free org slug
  description: "Example-Org shared Bridge config: contexts, projects, mandants."
  homepage: https://github.com/example-org/bridge-overlay
defaults:
  scope: org                     # the mirrored files' promote tier (default)
  source_root: tree/             # prefix stripped on materialize
  on_conflict: prompt            # never silently clobber a consumer file
selection:
  include: ['**']                # mirror everything under tree/
  exclude:                       # belt-and-braces; engine refuses these anyway
    - '_*.yaml'
    - '**/README.md'
    - 'identity/personas/**'
    - 'work/**'
ecosystem_fragment: ecosystem.example-org.yaml
```

### Manifest with exceptions (behavioural file + prompt fields)

```yaml
# yaml-language-server: $schema=./docs/schemas/overlay-manifest.schema.yaml
schema_version: 1
overlay:
  name: example-org
  org: example-org
  description: "Example-Org overlay with an org skill and a prompted account."
defaults:
  scope: org
  source_root: tree/
  on_conflict: prompt
selection:
  include: ['**']
ecosystem_fragment: ecosystem.example-org.yaml
files:
  # A behavioural file — forces a per-file [y] at first materialize regardless
  # of on_conflict. Declaring kind makes the consumer's preview explicit.
  - dest: skills/example-org-context/SKILL.md
    kind: skill

  - dest: protocols/standing-orders/example-org-routing.md
    kind: standing-order
    on_conflict: skip            # keep the consumer's version if they have one

  # An account file the consumer must complete before it's usable. The shipped
  # file carries placeholders; prompt_fields tells the engine which to ask for.
  - dest: identity/accounts/example-org-azure.yaml
    kind: config
    prompt_fields:
      - path: $.subscription_id
        reason: "Your Example-Org Azure subscription GUID"
      - path: $.tenant_id
        reason: "Your Example-Org tenant GUID"
        pii: true               # masked at the prompt; never logged
```

Notes:
- `prompt_fields[].path` is **JSONPath-lite** — `$.a.b` and `$.arr[*].c`
  (whole-array wildcard only). The consumer's lock records the **path only**,
  never the value the user typed.
- Ship the file in `tree/` with the field set to a **recognisable placeholder**
  (e.g. `subscription_id: "<your-subscription-guid>"`). The engine prompts only
  where the staged value **still equals** that placeholder — so a consumer who
  already filled it on a prior sync isn't re-asked.
- `kind: skill|agent|standing-order` = **behavioural** → the consumer sees an
  explicit per-file `[y]`; `--yes` can't auto-accept it. `kind: config|rule` =
  batch-confirmable.

### The ecosystem fragment

Name it `ecosystem.<org>.yaml`. The consumer copies it **verbatim** to its root
and adds an idempotent `@ecosystem.<org>.yaml` `@import` line to `CLAUDE.md` —
it is **never block-merged** into the consumer's `ecosystem.yaml`. Keep it a
self-contained fragment (your org's repos / workspaces / projects), generic and
PII-free, exactly like the main `ecosystem.yaml` it sits beside.

## The publish-guard CI idea

An overlay is config a fleet of Bridges will trust. Gate it **before** publish so
a stray secret or CORE-tier file never reaches a consumer. A
`.github/workflows/publish-guard.yml` should, on every push/PR to the overlay's
default branch:

1. **Schema-validate the manifest:**
   `check-jsonschema --schemafile <pinned overlay-manifest.schema.yaml> overlay.manifest.yaml`
2. **Leak + secret scan over `tree/`** — the same classes the consumer enforces:
   no raw secrets (accounts must be `*://` URI refs only), no personal PII, no
   absolute user paths. Reuse `no-scrub-leak.py` (the consumer runs it per-file
   on subscribe; running it at publish is the *first* line of defence).
3. **Refuse-list lint** — fail if `tree/` contains any `_*.yaml`, a
   cluster-wrapper `README.md`, `identity/personas/**`, or `work/**` (the engine
   would refuse them anyway; failing at publish keeps the artifact honest).
4. **Namespacing + flatness lint** — warn (or fail, your call) on bare
   (non-`<org>-`) slugs and on nested-folder discoverable instances.

The guard is the publisher's mirror of the consumer's Step-3/Step-9 gates:
catching it at publish means every subscriber gets a clean artifact and the
per-file leak gate on the consumer side stays a backstop, not the only net.

## Build-artifact discipline

**Export the overlay from your org's own Bridge; never hand-edit `tree/` per
consumer.** The whole point is that every member materializes the *same* files.

- Maintain the canonical config on **your org's Bridge instance** (its own
  `user/*` branch, contexts/projects/mandants/accounts you actually run).
- **Export** the `scope: org` subset into the overlay repo's `tree/` as a build
  step — a script that copies the live files, strips any user-specific values
  back to placeholders (the ones you list in `prompt_fields`), and regenerates
  the manifest's `files[]` exceptions. Commit that as one reviewable diff.
- **Treat `tree/` as generated.** Don't fix a typo directly in the overlay repo
  and let the source drift — fix it in your org Bridge and re-export. Otherwise
  consumers' 3-way merges start fighting an artifact that no longer matches any
  real Bridge.
- **Version with the manifest, pin with the lock.** Consumers pin to a
  `resolved_sha`; tag releases so a member can subscribe to a stable ref
  (`/overlay add <url> --ref v1.4`) instead of a moving `main`.
- **One overlay = one org's shared layer.** If two teams need different bundles,
  ship two overlays (different `overlay.name`, org-namespaced slugs) and let
  consumers subscribe to both with distinct `precedence` — don't fork the tree
  into per-team conditionals.

## Checklist before you publish

- [ ] `overlay.manifest.yaml` validates against the pinned schema
- [ ] Every `tree/<path>` is `scope: org`, org-namespaced, and flat where discoverable
- [ ] No `_*.yaml`, wrapper `README.md`, `identity/personas/**`, or `work/**` in `tree/`
- [ ] Accounts carry only `azure-keyvault://` / `keychain://` / `1password://` refs
- [ ] Behavioural files (`skill`/`agent`/`standing-order`) tagged in `files[]`
- [ ] Placeholders + `prompt_fields[]` set for anything a consumer must complete
- [ ] `ecosystem.<org>.yaml` present iff `ecosystem_fragment` is declared
- [ ] `publish-guard.yml` green
- [ ] `tree/` was **exported** from the org Bridge, not hand-edited
