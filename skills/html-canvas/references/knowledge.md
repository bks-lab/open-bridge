---
summary: "The knowledge panel: terms in a page or deck open their knowledge beside it (no pop-up), from a small knowledge pack (knowledge-pack@1) built by knowledge-pack.py or any adapter"
type: reference
last_updated: 2026-11-07
related:
  - skills/html-canvas/references/sections.md
  - skills/html-canvas/scripts/knowledge-pack.py
  - skills/html-slides/reference/blocks.md
---

# Knowledge panel

Read this when terms in a page or a deck should open their knowledge: what a term
means, how it relates to others, where the sources say so. A click on a marked term
opens a panel on the right; the page reflows to the left, a deck scales its slide to
the left exactly as designed. There is no pop-up and nothing leaves the file: the
knowledge travels with the page as a small JSON pack.

## The parts

| Part | Where | Job |
|---|---|---|
| Term mark | in the text | `<button type="button" class="kp-term" data-know="<id>">latency</button>`: a thin accent underline and a small filled help mark after the word, inside the line box |
| Knowledge pack | `<script type="application/json" id="knowledge-pack">`, between `<!-- knowledge-pack:start -->` and `:end` | every term the page uses, one hop of neighbours, passages, sources |
| Panel | block `knowledge` in `assets/sections.js` and `assets/sections.css` | reads the pack, shows a term, its relations and passages; one code path for pages and decks |
| Build side | `scripts/knowledge-pack.py` | `build` (Markdown adapter), `check`, `mark`, `embed` |

```bash
P=skills/html-canvas/scripts/knowledge-pack.py
python3 skills/html-slides/scripts/new-deck.py --title "Review" --slides slides.html \
    --blocks knowledge --out deck.html               # or: new-page.py --blocks knowledge
uv run --with pyyaml python $P build --terms terms.yaml --corpus docs/ --out pack.json \
    --title "Project knowledge" --revision "$(git -C docs rev-parse --short HEAD)"
python3 $P mark deck.html --pack pack.json           # report what it would mark
python3 $P mark deck.html --pack pack.json --write   # then review the diff
python3 $P embed deck.html --pack pack.json          # one region, replaced on every run
```

`new-deck.py --refresh` leaves the pack region alone (it rewrites only its own
regions), so a refreshed deck keeps its knowledge; run `embed` again after a new build
of the pack.

## The pack: knowledge-pack@1

```json
{
  "schema": "knowledge-pack@1",
  "id": "project-terms", "title": "Project knowledge", "lang": "en",
  "source": {"kind": "markdown", "ref": "docs/", "revision": "a1b2c3d", "generated": "2026-11-07"},
  "terms": [{
    "id": "latency", "label": "Latency", "aliases": ["response time"], "type": "concept",
    "summary": "Time between request and response, measured at the client.",
    "neighbours": [{"id": "queue", "rel": "rises with", "label": "Queue"}],
    "passages": [{"text": "…", "source": {"title": "Basics", "locator": "Latency", "href": "https://…"}}],
    "sources": [{"title": "Basics", "href": "https://…"}]
  }]
}
```

| Rule | Limit | Why |
|---|---|---|
| terms | at most 60 | the terms of one deck or page, not the whole knowledge base |
| summary | at most 400 characters | read aloud in under half a minute |
| passages | at most 4 per term, 280 characters each, each with a source title | evidence, not a copy of the source |
| neighbours | at most 6, each with id and label; `rel` may be empty | one hop; a neighbour outside the pack shows as text |
| size | at most 120 KB | a mail attachment and the artifact viewer stay fast; typical packs are 20 to 60 KB |
| `source.revision` | free text | the panel footer says which state of the knowledge the deck carries |

`check` enforces all of it; `build` and `embed` run it too. Ids are lowercase slugs. A link (`href`) is
http, https, mailto or relative; the panel follows nothing else, whatever wrote the pack.

## Adapters

An adapter is anything that writes this JSON. The panel never talks to a service.

| Adapter | Status | Input |
|---|---|---|
| `markdown` (`knowledge-pack.py build`) | built | a term list (YAML or JSON: `id`, `label`, `aliases`, `type`, `summary`, `summary_source`, `related`) and Markdown folders |
| graph export | contract only | nodes with names, aliases and descriptions, edges with evidence; map each node to a term, its edges to `neighbours`, its evidence to `passages` |
| knowledge service | contract only | resolve a term, ask for its neighbours and the chunks that mention it, write the pack at build time |

The Markdown adapter takes passages from the paragraphs, list items and table rows
that mention a label or alias, the passage in the section the term list names for its
summary first, prose before table rows. A name with a lower-case letter matches in any
case (`Latency` finds "the latency"); a name without one is an acronym and matches only
as written (`IT` never finds "it"). A term may head a compound (`latency-bound`), never
sit inside a word. Neighbours are the relations the
term list names, then the terms that share a paragraph with it, most frequent first.
Passages are clipped at sentence ends.

**Live or snapshot.** A pack is a snapshot with a revision: the deck shows the same
knowledge in every room, offline and in a mail. A live source is an adapter run at
build time, not a call from the page. `data-knowledge-src="pack.json"` on `<html>`
loads a pack next to the page instead (a published copy that is updated in place);
the embedded pack stays the fallback, also when the loaded file holds no terms. For a
copy to send, run `embed` with the current pack: `bundle.py` does not fold a
`data-knowledge-src` file in.

## Marking terms

By hand, or with `mark`: it reads the text as characters (`&amp;` is `&`, `&copy;` is
no word), leaves comments, scripts, styles and quoted attributes alone, and wraps the first mention of every pack term per slide
(per page on a canvas page), never inside headings (`--headings` allows h1 and h2),
code, links, buttons, notes or SVG, and never twice. A term already marked by hand
counts as marked. Without `--write` it only reports, so the author decides; marking
in the browser at view time is deliberately not offered (a deck must look the same
every time and be testable).

## The panel

| Situation | What happens |
|---|---|
| click on a term | the panel opens on the right with the term; the term shows `aria-expanded` |
| click on the same term again, Esc, or the close button | the panel closes. Opened from the keyboard (Enter or Space on the term, or K), the focus returns to where it was; opened with the pointer, no focus stays on the term, so the next Space or Enter moves a deck on instead of reopening the panel |
| Esc with another view open (a deck's reading view, a module) | the panel closes first; the next Esc reaches the view. An open `?` help closes before the panel |
| K | the terms marked on the current slide (or the page), as a list; K again closes |
| a related term in the pack | opens in the panel; Back returns |
| a deck while the panel is open | arrows, Space and the number jump still move the slides; a list follows the slide |
| narrow screen (below 900 px) | the panel is a sheet at the bottom; a deck is not scaled |
| a term the pack does not hold | plain text, disabled |
| print and PDF | panel and marks are hidden; the slide prints as designed |
| light and dark | tokens only (`--raised`, `--line`, `--accent-*`, `--muted`, `--ink`), deck tokens through the alias layer; secondary text in the panel leans toward the ink, so a design with a weak muted colour still reads at 4.5:1 |
| forced colours (Windows high contrast) | the help mark takes the system link colour |

A deck also gets a `?` help row for K. The term view (kind, name, aliases, summary,
relations, passages with source, sources) follows the knowledge view of an
associative podcast player; that player shows it as a separate view, the panel puts
it beside the page.

## Not yet

- A printed appendix of the terms for a deck (a deck prints one page per slide).
- The presenter window shows the slide, not the panel.
- Graph and service adapters: only the contract above.
