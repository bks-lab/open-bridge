---
name: bridge-greeting
description: >-
  Context-aware terminal greeting (MOTD) for Bridge instances — renders a
  per-instance logo, palette, today's filtered calendar, the instance's
  "Doing" board and uncommitted work, resolved from which org folder the
  terminal was opened in. Includes gen-logo.py (ANSI-Shadow logo generator
  from a word) and the branding convention that feeds every Bridge UI.
  Trigger: "/bridge-greeting", "terminal greeting", "motd", "startup logo",
  "instance logo", "terminal greeting", "fastfetch logo", "branding",
  "generate logo", "per-folder terminal", "folder logo".
metadata:
  scope: core
---

# Bridge Greeting

A login-shell greeting that is **instance-aware**: the org folder you open the
terminal in resolves to a Bridge instance, and the greeting then shows that
instance's identity — logo, colours, calendar tags, task board, and repos.

Home / unknown dirs → the full system dashboard (fastfetch cascade + global
board). Inside an org tree → a focused panel for the resolved instance.

## The model — branding belongs to the Bridge, not the script

The greeting reads its visual identity from the **resolved instance's theme**
(`themes/<theme>.yaml` → `branding:` block), so a logo "comes from" its Bridge
instance the same way `identity/agent/` and vocabulary do. Three layers:

| Layer | Owns | Tier |
|---|---|---|
| **Engine** (`scripts/render-motd.sh`) | discovery, rendering, board parsing — no instance literals | CORE → open-bridge |
| **Theme branding** (`themes/<theme>.yaml` `branding:`) | logo path, `logo_color_1/2`, `calendar_tags` per instance | per-instance |
| **Local override** (`~/.config/fastfetch/bridge-motd.local.sh`) | per-org fallbacks for instances whose theme has no `branding:` yet; the org→instance machine map | USER (machine-local, never committed) |

Discovery scans `~/Developer/*/*/bridge-config.yaml` to build the
org-folder → instance map automatically — no hardcoded instance names in the engine.

## Purpose tagline — the instance's north-star under the logo

When the resolved instance's `bridge-config.yaml` has a non-empty
`purpose.statement`, render it as the **subtitle / tagline directly under the
logo**, alongside the theme-derived identity the greeting already shows — so the
terminal opens reading as *what this Bridge is for*, not a bare wordmark. Empty
`purpose.statement` → no tagline line (today's behaviour). This is display only; the
purpose never changes what the greeting can show.

## gen-logo.py — make an instance its logo

```bash
uv run --with pyfiglet python scripts/gen-logo.py --top ACME --bottom CORP > assets/logos/acme.txt
uv run --with pyfiglet python scripts/gen-logo.py --top ACME --umlaut 1   > assets/logos/acme.txt
```

`--umlaut N` re-adds a diaeresis over the N-th letter of `--top` (figlet drops
non-ASCII glyphs, so an umlaut would otherwise be lost). Output carries fastfetch
`$1`/`$2` colour placeholders; the actual colours are applied at render time
from the theme's `logo_color_1/2`.

`--pipe false` is mandatory when fastfetch output is captured — a plain
`--pipe` strips every SGR code, leaving the logo uncoloured.

## Setup — advise, don't assume

Branding is taste. When setting up (or reconfiguring) an instance's greeting —
during onboarding or on `/bridge-greeting` — **consult the user, propose,
let them decide** (Bridge house style: advise, don't act). Ask, per instance:

- **Wordmark + subtitle** — top word, optional second line (e.g. a unit/role).
- **Colour mode** — one of:
  - `monochrome` — no colour, renders in the terminal's own foreground
    (set `logo_color_1/2: none`). For users who want a plain, uncoloured logo.
  - `single` — one uniform colour, no two-tone alternation
    (`logo_color_1` == `logo_color_2`).
  - `two-tone` — distinct `logo_color_1`/`logo_color_2` (gradient feel).
- **Calendar tags** — which calendars surface for this instance.

Write the chosen values into that instance's theme `branding:` block (or the
machine-local override). Never hardcode a palette — default to asking.

## Deploy (thin-shim pattern)

`scripts/render-motd.sh` is the single source of truth. `.zshrc` calls a
one-line shim at `~/.config/fastfetch/bridge-motd.sh` that `exec`s the repo engine
— so it auto-follows `git pull`, no copy to re-deploy:

```bash
ENGINE="$HOME/Developer/<org>/<your-bridge>/skills/bridge-greeting/scripts/render-motd.sh"
[[ -r "$ENGINE" ]] && exec bash "$ENGINE" "$@"   # silent skip if repo absent → login never fails
```

Per-machine data stays out of the repo: logo files in
`~/.config/fastfetch/logos/`, per-org overrides in
`~/.config/fastfetch/bridge-motd.local.sh` (USER, never committed).

## Two renderers, one concept (macOS + Windows)

The greeting is **platform- and provider-pluggable**. The same three-layer
model (generic engine · instance config · branding asset) has two engines:

| | macOS arm | Windows arm |
|---|---|---|
| Engine | `scripts/render-motd.sh` (bash + fastfetch) | `scripts/render-greeting.ps1` (PowerShell + ANSI) |
| Data source | GitHub Projects V2 (`gh`) | Azure DevOps — WIQL / pipelines / commits (`az`) |
| Instance config | `bridge-motd.local.sh` (`BRIDGE_MOTD_*`) | `$BridgeGreetingConfig` hashtable |
| Branding | theme `branding:` block | same `assets/logos/*.txt` + colour |
| Deploy | `.zshrc` shim → repo engine | `$PROFILE` shim → dot-source engine + config |

`render-greeting.ps1` is generic — no instance literals. A profile dot-sources
it plus an instance config, then calls `Show-BridgeGreeting -Config $cfg`. The
config is a hashtable: `Label`, `Logo` (a `assets/logos/*.txt` reused as-is —
the PS renderer decodes the same `$1/$2` + `\u{}` format), `Color1/Color2`,
`Provider`, an `Ado` block (`Org`, `Project`, `RepoId`, `ResourceId`, `Branch`),
and an ordered `Sections` array (`Kind` ∈ `workitems`/`pipelines`/`commits`,
with per-section `Wiql`, `Title`, `Empty`). No config → it greets with just the
header. Results cache to JSON (default 1 h TTL).

`Provider = 'azure-devops'` is implemented; `github` is a documented extension
point (add a `Get-GhSection` dispatch — the rest of the engine is
provider-agnostic).

**Windows deploy** mirrors the thin-shim idea but dot-sources by `$PSScriptRoot`
(a dev-box typically has no Bridge clone, so the engine + config + profile ship
as siblings in the PowerShell profile folder, e.g. a cloud-synced one):

```powershell
# Microsoft.PowerShell_profile.ps1 (thin shim)
. "$PSScriptRoot\render-greeting.ps1"
. "$PSScriptRoot\bridge-greeting.config.ps1"   # defines $BridgeGreetingConfig
Show-BridgeGreeting -Config $BridgeGreetingConfig
```

The instance config + its logo + the deployed profile are **USER scope** and
live in that instance's own Bridge repo, never here — exactly like the macOS
local override. The engine is the only CORE/promotable piece.

## Branding everywhere

`branding.logo_*` is the terminal rendering of one brand identity that also
feeds the web UIs (bridge-deck, the :8790 ops dashboard, the :8793 control
center, bridge-explorer). The shared SoT for web surfaces is `DESIGN.md`
(palette + wordmark tokens). See `references/architecture.md`.

## Layering (core / org overlay / instance)

- **open-bridge**: engine + `gen-logo.py` + a generic `OPEN BRIDGE` logo + neutral palette. Discovery, no literals.
- **your org overlay** (`<your-org>/<your-bridge>`): a sample logo + palette as the default `branding:`.
- **per-instance (USER)**: each instance's own logo, org→instance map, calendar tags — local, never promoted.
