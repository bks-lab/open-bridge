# Output Formats: the send path

Three optional post-generation steps live in `scripts/`. Use them after the deck
HTML is written. Each is independent: run any combination, in any order.

A deck built with `scripts/new-deck.py` already embeds its fonts, tokens and engine
between markers; after an engine or DESIGN.md change, `new-deck.py --refresh deck.html`
rewrites those regions in place and leaves the slides alone. The checks that gate a
deck for sending (`html-canvas/scripts/verify-page.py --deck`, then
`check-anonymity.py`) run on that file.

| Goal | Script | When to run |
|------|--------|-------------|
| Fold remaining local `img/`, `lib/` or `fonts/` references into the file | `inline-assets.py` | Only when the deck still references such files |
| PDF copy of the deck | `render-pdf.cjs` | Whenever the user wants a printable, mailable or archival version |
| Audit for names, identifiers and leftover placeholders | `check-anonymity.py` | Before any external send (mail, customer portal, public link) |

All three scripts run on a *generated* deck, not on the preset YAMLs.

---

## 1. `inline-assets.py`: fold local files into the deck

```bash
python3 scripts/inline-assets.py path/to/deck.html path/to/deck-send.html [bundle.py options]
```

A thin wrapper around the shared bundler `html-canvas/scripts/bundle.py`, found
next to this skill. Options after the two paths go to the bundler unchanged:
`--pages`, `--allow-remote`, `--manifest FILE`, `--design DESIGN.md`, `--font-dir DIR`.

A deck built with `scripts/new-deck.py` already embeds its fonts, so for a deck
without local images or scripts this changes nothing. It earns its place when the
deck still points at files next to it.

**What it does:**
- Local images, stylesheets, scripts and fonts become `data:` URIs or inline blocks
- An `<iframe src>` or `<iframe data-src>` with a local page becomes a base64 payload
  with a UTF-8 safe loader (a lazy frame loads on demand)
- With `--pages`, linked local pages travel along and open from the file
- Fonts named by DESIGN.md that the deck uses but does not declare are embedded
- Remote resources are refused unless `--allow-remote`. A deck generated before
  fonts were self-hosted may link `fonts.bunny.net`: regenerate it with
  `new-deck.py`, or keep the link with `--allow-remote`
- Every missing or refused reference is reported at once, and nothing is written
  until all of them resolve. A sha256 per inlined source goes to stderr
  (or `--manifest`)

Not folded: URLs built in JavaScript, and a stage's `data-src`
(`reference/stage.md`, "Sending a deck with a stage").

Exit codes: 0 done, 1 a reference could not be resolved or the input is missing,
2 wrong usage.

**Output size:** the deck grows by the size of the files it folds in (base64 adds
about a third), nothing more.

---

## 2. `render-pdf.cjs`: PDF export

```bash
node scripts/render-pdf.cjs path/to/deck.html path/to/deck.pdf
node scripts/render-pdf.cjs deck.html deck.pdf --width 210 --height 297  # A4 portrait
node scripts/render-pdf.cjs deck.html deck-dark.pdf --theme dark
node scripts/render-pdf.cjs deck.html handout.pdf --notes      # notes page after each noted slide
node scripts/render-pdf.cjs --probe   # where playwright was found
```

**Page size:** without `--width`/`--height` the deck's own CSS `@page` size wins
(`297mm x 167mm`, 16:9 landscape, from the print block in `slide-engine.css`). An
explicit size wins over the CSS one, orientation included. Every slide is one page.

**Theme:** `--theme light|dark` sets `.theme-light` or `.theme-dark` on `<html>`
for the render, without touching the viewer's saved choice. Without it the deck
renders as it opens: the saved choice, else the OS (headless reports light).

**Handout:** `--notes` sets `data-print-notes` on the deck for the render, and the
engine prints a notes page after every slide that has `<aside class="notes">`.
Putting `data-print-notes` on the deck element (`new-deck.py --deck-attr
data-print-notes=`) makes the browser's own print do the same.

**Why not `chrome --print-to-pdf` directly?**
The slide engine relies on an `IntersectionObserver` to add `.visible` to each
slide as it scrolls into view. Headless Chrome's print mode never scrolls, so
naive `--print-to-pdf` produces a deck where pages 3+ are blank (only page 1
and 2 made it past the threshold). The engine ships with a `beforeprint`
hook that adds `.visible` to all slides, AND this script also adds them
defensively before calling `page.pdf()`: belt and suspenders.

The script also:
- Promotes `loading="lazy"` images to `eager` and waits for them
- Awaits `document.fonts.ready`, then two animation frames, so the embedded fonts
  are in; there is no fixed sleep
- Uses `printBackground: true` so colored backgrounds print

**Requires:** Playwright globally installed.
```bash
npm install -g playwright
npx playwright install chromium
```

The script resolves `playwright` from the working directory, its own folder,
`NODE_PATH`, the global npm root (`npm root -g`), `/opt/homebrew/lib/node_modules`,
`/usr/local/lib/node_modules` and every nvm-installed node, so `NODE_PATH` is usually
not needed. `--probe` prints the module it found.

---

## 3. `check-anonymity.py`: audit for sensitive identifiers

```bash
# Default list plus the instance list from bridge-config.yaml (if any)
python3 scripts/check-anonymity.py path/to/deck.html

# Add lists (repeatable; every list adds to the others)
python3 scripts/check-anonymity.py deck.html --wordlist names.txt --wordlist ids.txt

# Only your own lists
python3 scripts/check-anonymity.py deck.html --wordlist my-list.txt --no-default-wordlist

# Report without failing
python3 scripts/check-anonymity.py deck.html --warn-only
```

**What it does:** scans what a reader sees (text, attribute values such as `alt` and
`title`, comments) against the wordlists. Before the scan, `data:` URIs and the bodies
of `<style>` and `<script>` are blanked, line numbers kept: embedded font data is base64
and would match almost any short term, and the engine code is nobody's reading. Entities
are decoded. A plain term is case-insensitive and matched as a whole word (`todo` hits
`TODO:`, not `mastodon`); a line starting with `re:` is a regular expression.

**Exit codes:** 0 clean, 1 hits (0 with `--warn-only`), 2 usage error (missing input or
wordlist, or no term at all). A hit fails the run by default, so the check can gate a send.

**Output:** a per-term grouped report with line number and about 110 characters of
context. Intentional hits stay in the wordlist as a reminder: flag them as
"intentional" in your shipping checklist rather than removing them from the list
(suppressing entries weakens the next deck's audit).

**Wordlist syntax** (one item per line):
```
# Comments and blank lines are ignored. A comment needs its own line:
# the whole line is the term.
# Plain term, case-insensitive, matched as a whole word:
confidential
# Regex, the rest of the line after re: is the pattern:
re:\bINV-\d{6,}\b
```

**Default wordlist** (`scripts/wordlist-default.txt`) is generic on purpose: placeholder
text (lorem ipsum), drafting markers (TODO, FIXME, TBD), classification labels
(confidential, internal only), placeholder domains (example.com) and an IBAN-shaped
pattern. It names no customer, vendor or person, because it ships with CORE.

**Instance lists** carry the names and identifiers that matter to one organisation:
customers, people, account and invoice number patterns. They live in the instance repo,
never in this skill. Pass one with `--wordlist`, or name it once in
`bridge-config.yaml` under `html_slides.anonymity_wordlist`:

```yaml
html_slides:
  anonymity_wordlist: protocols/anonymity-wordlist.txt   # relative to bridge-config.yaml
  # or a list: [protocols/names.txt, protocols/ids.txt]
```

The check finds that file walking up from the deck (or takes `--config FILE`) and
adds the lists to the default without a flag; `--no-config` skips it. The older key
`html_slides.wordlist` is still read. `--extra-wordlist` is the older spelling of `--wordlist`
and works the same.

---

## Suggested sequence for a package to send

```bash
SKILL=path/to/skill/scripts
DECK=deck.html

VERIFY=path/to/html-canvas/scripts/verify-page.py

# 1. Audit BEFORE any output is generated (fast feedback)
python3 $SKILL/check-anonymity.py $DECK

# 2. Fold in local files, only if the deck references any
python3 $SKILL/inline-assets.py $DECK deck-standalone.html

# 3. The gate on the copy that leaves: opened alone, rendered, one page per slide
python3 $VERIFY deck-standalone.html --deck

# 4. PDF
node $SKILL/render-pdf.cjs deck-standalone.html deck.pdf

# 5. Re-audit the standalone (same wordlist, different file)
python3 $SKILL/check-anonymity.py deck-standalone.html

# 6. Package (HTML + PDF + a small README) as a zip to mail
zip -r package.zip deck-standalone.html deck.pdf README.md
```

If any audit step has hits, decide per term: remove (sensitive), keep with a note
(intentional disclosure), or improve the wordlist (false positive class).

### A copy to be read, not presented

A deck sent to people who will read it alone (no speaker, no keys) can open in the
reading view of the `read` module: every slide of the active track as one scrolling
document, with its speaker notes under each slide. Build or refresh it with the
module and the deck attribute `data-read-default`:

```bash
python3 $SKILL/new-deck.py --with read --deck-attr data-read-default= ...   # or set it on <html>
```

The attribute works on `.deck` or `<html>`; `data-read-default="off"` (or `"false"`)
keeps the slide view, for example in the presenting copy of the same deck. A deep
link (`#<id>`) still picks the slide the view opens at, and R or Esc switches to the
slide view. Print and `render-pdf.cjs` are unaffected: the PDF still has one slide per
page. Details: `reference/modules.md` § Module: read.
