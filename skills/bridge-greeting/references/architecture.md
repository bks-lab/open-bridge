---
summary: "Design for the instance-aware terminal greeting + Bridge-wide branding"
type: reference
last_updated: 2026-05-26
related:
  - skills/bridge-greeting/SKILL.md
  - DESIGN.md
  - docs/multi-instance.md
  - docs/extension-model.md
---

# Bridge Greeting — Architecture

## Problem

The terminal greeting started as a personal dotfile (`~/.config/fastfetch/
bridge-motd.sh`, ~900 lines) hardcoded to one user's orgs. To become
a Bridge feature it must (a) carry **per-instance identity** owned by the Bridge,
and (b) feed the **same brand** into every UI surface, not just the terminal.

## Resolution flow

```
$PWD ──▶ org folder (~/Developer/<org>/) ──▶ Bridge instance
                                              (discovered via */bridge-config.yaml)
            │
            ├─▶ instance theme (bridge-config theme:) ─▶ branding: { logo, colors, calendar_tags }
            ├─▶ instance work/board.md  "## Doing"     ─▶ focused task list
            └─▶ org tree git status                    ─▶ uncommitted work
```

Home / unknown dir → neutral mode (full fastfetch cascade + global board),
i.e. exactly the legacy behaviour.

## Layers (and why)

1. **Engine** — generic, no instance literals. Discovers instances, renders,
   parses boards. Promotable to open-bridge unchanged.
2. **Theme `branding:`** — per-instance visual identity. Single source of truth
   when present. Sits in the theme because themes already own the user-facing
   surface; this just extends "words" to "logo + palette".
3. **Local override** — machine-local USER file for the org→instance map and for
   per-org fallbacks (calendar tags) when an instance theme has no `branding:`
   yet. Never committed; keeps PII (folder layout, calendar names) off shared
   repos. See [[pii-tracking-in-private-repo]] reasoning.

## Branding everywhere — one identity, many renderers

`branding.logo_color_1/2` (terminal) and the `DESIGN.md` palette (web) are two
renderings of one brand. Target surfaces and their renderer:

| Surface | Renderer | Brand source |
|---|---|---|
| Terminal MOTD (macOS) | bash + fastfetch, ANSI-Shadow `$1/$2` logo | theme `branding:` |
| Terminal greeting (Windows) | PowerShell + ANSI, same logo asset decoded | instance config (`$BridgeGreetingConfig`) |
| bridge-deck (:8791) | pixel-art header sprite / wordmark | DESIGN.md tokens |
| Ops dashboard (:8790) | HTML wordmark + palette | DESIGN.md tokens |
| Control center (:8793) | HTML wordmark + palette | DESIGN.md tokens |
| bridge-explorer HTMLs | HTML wordmark + palette | DESIGN.md tokens |

Each instance renders its own brand (open-bridge generic, each overlay its own brand, other
instances their own), so "which Bridge am I looking at" is visible everywhere.

## Two engines, one model (cross-platform)

The terminal greeting has two engines because the platforms differ (bash +
fastfetch on macOS; PowerShell on a Windows dev-box) and so do their natural
data sources (GitHub Projects vs Azure DevOps). Both keep the **same three
layers**: a generic engine (no instance literals, promotable), a per-instance
config (USER, local — the macOS `bridge-motd.local.sh` override ⇔ the Windows
`$BridgeGreetingConfig` hashtable), and a branding asset (the *same*
`assets/logos/*.txt`, decoded by each renderer). The Windows engine
(`render-greeting.ps1`) is provider-pluggable via `$cfg.Provider`
(`azure-devops` implemented; `github` an extension point), so an instance picks
its data source without forking the engine.

## Build sequence

1. **Done (step 1)** — skill home, `gen-logo.py`, versioned logo assets, theme
   `branding:` schema + the-bridge branding block, live MOTD reads logo/colour
   from theme branding, org→instance map via discovery. Legacy neutral mode
   untouched. Backup at `~/.config/fastfetch/bridge-motd.sh.bak`.
2. Full engine extraction: move the refactored engine to `scripts/render-motd.sh`
   as the canonical SoT; reduce the dotfile to a deployed copy; move per-org
   calendar tags into the local override.
3. Other instances: add a `branding:` block in that instance's own repo/theme —
   then its branding is theme-driven too, any central logo files retire.
4. open-bridge: generic `OPEN BRIDGE` logo + neutral palette; translate SKILL.md.
5. Web UIs: add `branding`/wordmark tokens to `DESIGN.md`; render the wordmark +
   palette in bridge-deck, :8790, :8793, bridge-explorer headers.
