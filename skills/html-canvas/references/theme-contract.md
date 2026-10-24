---
summary: "The one light/dark contract for every HTML skill: .dark on <html>, color-scheme, pre-paint, <skill>-theme, OS fallback, and how DESIGN.md reaches a consumer through design-to-css.py"
type: reference
last_updated: 2026-10-24
related:
  - skills/html-canvas/SKILL.md
  - skills/html-canvas/assets/shell.html
  - skills/html-canvas/scripts/design-to-css.py
  - DESIGN.md
---

# html-canvas: Theme contract

Every skill that writes an HTML deliverable (pages, decks, dashboards, mails
with a web view) switches light and dark the same way. One contract means one
token generator, one pre-paint snippet and one test, instead of a token file
that has to answer three spellings at once. `assets/shell.html` is the
reference implementation; this file is the rule it implements.

## The contract

1. **State lives in one class.** Dark mode is the class `dark` on `<html>`
   (`document.documentElement`). Light is its absence. No `data-theme`
   attribute, no second class, no class on `<body>`. This is the DESIGN.md
   convention, and `design-to-css.py` emits `html.dark` by default.
2. **`color-scheme` follows the class.** `:root { color-scheme: light; }` and
   `html.dark { color-scheme: dark; }`, so form controls, scrollbars and system
   colours match the page. Print forces `color-scheme: light`.
3. **Pre-paint, before the first stylesheet.** A small inline `<script>` in
   `<head>`, placed above every `<style>` and `<link rel="stylesheet">`, sets the
   class before the first paint. A theme set later flashes the wrong ground.
4. **One storage key per skill: `<skill>-theme`**, with the value `light` or
   `dark` (for example `html-canvas-theme`). Every read and write sits in
   `try`/`catch`: storage throws in some private windows and on `file://` in
   some browsers, and the page must still render.
5. **No saved choice means the OS decides.** Without a stored value, the page
   follows `prefers-color-scheme`, and keeps following it live while nothing is
   stored. Following the OS is not a choice, so it is never written to storage;
   only the user's toggle is.
6. **The toggle.** A real `<button>` whose label names the target mode in the
   page language, plus the key `T` (ignored with a modifier key and inside
   inputs, textareas, selects and contenteditable). A `storage` event on the key
   syncs other open tabs.
7. **Print is light.** Whatever the screen mode, paper gets the light palette.
   The default sheet from `design-to-css.py` carries that `@media print` block,
   and so does `--map` output, in the consumer's own variable names.

A language switch, where a skill has one, mirrors the same shape with
`<skill>-lang` and the `data-lang` attribute on `<html>`.

### Pre-paint snippet

```html
<script>
(function () {
  var KEY = 'html-canvas-theme';            /* <skill>-theme */
  try {
    var t = localStorage.getItem(KEY);
    if (t === 'dark' || (t == null && window.matchMedia &&
        matchMedia('(prefers-color-scheme: dark)').matches)) {
      document.documentElement.classList.add('dark');
    }
  } catch (e) { /* no storage: light, or the OS via CSS below */ }
})();
</script>
```

With scripts disabled the page stays light and fully legible. That is the
intended fallback: a CSS-only `prefers-color-scheme` block would need its own
copy of every dark value and could not be overridden by the toggle.

## DESIGN.md wins when present

When the Bridge has a `DESIGN.md`, its colour roles are the only source of
colour. A deliverable never holds a hand-picked value, and a skill's own palette
(a style preset, a neutral fallback) applies only where DESIGN.md is absent or
the user asked for that look by name.

The values reach a page through `scripts/design-to-css.py`, never by copying:

| Consumer | Command | What it gets |
|---|---|---|
| html-canvas shell | `design-to-css.py --shell --out page.html` | the full sheet in the `design-tokens` region, `:root` and `html.dark` |
| bare CSS | `design-to-css.py --out tokens.css` | the same sheet as a file |
| a consumer with its own variable names | `design-to-css.py --map <consumer>.map.yaml` | exactly the variables the map names, in both groups, plus the same light `@media print` block |
| any file with a marked region | add `--region <name> --shell <file> --out <file>` | the region `/* <name>:begin */ ... /* <name>:end */` rewritten, the rest of the file untouched |

`--region` keeps whatever neutral values the file holds above the generated
block, so a token DESIGN.md lacks keeps its fallback. Running it again gives the
same bytes, which makes it safe for refreshing an existing deliverable.

### Mapping DESIGN.md onto a consumer

A consumer whose engine uses other names (`--bg`, `--text`, `--accent-dim`)
ships a map file next to its own code. The map is the consumer's data; the
generator knows no consumer.

```yaml
# <consumer>/presets/design.map.yaml
selectors:                    # optional; the default is the contract above
  light: ":root"
  dark: "html.dark"
vars:
  bg: surface                 # --bg from the DESIGN.md role `surface`
  text: on-surface
  text-dim: on-surface-muted
  accent: accent
  accent-dim: {role: accent, mix: 15}               # 15 % accent over transparent
  ok-dim: {role: success, mix: 20, with: surface}   # 20 % success over the surface
```

- **Roles are DESIGN.md colour keys** as written in `colors:`, not the shell's
  short names. A role resolves per mode: light from `colors:`, dark from
  `colorsDark:` or a legacy `dark-<role>` key, and from the light value when the
  manifest has no dark one.
- **Derived variants** are `color-mix(in srgb, <role> <mix>%, <with>)`, with
  `with` either another role or `transparent` (the default). Never an `rgba()`
  literal: it would freeze a value DESIGN.md can no longer change.
- **A missing role** is reported on stderr and its variable is left out. Under
  `--strict` the run exits non-zero instead, which is how a build should call it.
- **Selectors** come from `--selectors light=<selector> dark=<selector>`, then
  the map's `selectors:`, then the contract default. An engine that still reads
  an older convention (for example `.theme-light` / `.theme-dark`) is served by
  passing those selectors, which keeps old pages working while it migrates. The
  target is this contract; a compat selector is a bridge, not a second contract.

## Checklist

- `<html>` gets `dark` and nothing else from the theme switch.
- The pre-paint script is the first script in `<head>`, above every stylesheet.
- Storage key `<skill>-theme`, values `light`/`dark`, every access in `try`.
- No stored value: OS preference, followed live, never written back.
- `color-scheme` set for both modes; print is light.
- Colours come from DESIGN.md through `design-to-css.py`; no value in the page
  that the generator did not write.
