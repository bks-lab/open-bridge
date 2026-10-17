// SPDX-License-Identifier: MIT
// The cockpit, an answer drawn from its Markdown: the blocks and runs markdown.js reads, as elements.
// The rules every component keeps stand at the head of components.js.

import { html, useMemo } from '../vendor/htm-preact-3.1.1.module.js'
import { parseMarkdown } from '../markdown.js'

// ---------------------------------------------------------------- prose

// a chat sits under the page's h2, so its headings start one level lower
const HEADING_TAG = ['h3', 'h3', 'h4', 'h5', 'h6', 'h6']

function Runs({ nodes }) {
  return nodes.map((n, i) => {
    switch (n.t) {
      case 'text': return n.v
      case 'br': return html`<br key=${i} />`
      case 'code': return html`<code key=${i} class="md-code-run">${n.v}</code>`
      case 'b': return html`<strong key=${i}><${Runs} nodes=${n.c} /></strong>`
      case 'i': return html`<em key=${i}><${Runs} nodes=${n.c} /></em>`
      case 's': return html`<del key=${i}><${Runs} nodes=${n.c} /></del>`
      case 'a': return html`<a key=${i} href=${n.href} target="_blank" rel="noopener noreferrer"><${Runs} nodes=${n.c} /></a>`
      default: return null
    }
  })
}

function Blocks({ blocks }) {
  return blocks.map((b, i) => {
    switch (b.type) {
      case 'h': return html`<${HEADING_TAG[b.level - 1]} key=${i} class=${`md-h md-h${b.level}`}><${Runs} nodes=${b.inline} /><//>`
      case 'p': return html`<p key=${i}><${Runs} nodes=${b.inline} /></p>`
      case 'code': return html`<pre key=${i} class="md-pre" data-lang=${b.lang || undefined}><code>${b.text}</code></pre>`
      case 'quote': return html`<blockquote key=${i}><${Blocks} blocks=${b.blocks} /></blockquote>`
      case 'hr': return html`<hr key=${i} />`
      case 'list': {
        const items = b.items.map((it, k) => html`<li key=${k} class=${it.checked === null ? undefined : 'md-task'}>
          ${it.checked === null ? null : html`<input type="checkbox" checked=${it.checked} disabled aria-hidden="true" />`}<${Blocks} blocks=${it.blocks} /></li>`)
        return b.ordered ? html`<ol key=${i} start=${b.start !== 1 ? b.start : undefined}>${items}</ol>` : html`<ul key=${i}>${items}</ul>`
      }
      case 'table': return html`<div key=${i} class="md-table" tabindex="0"><table>
        <thead><tr>${b.head.map((c, k) => html`<th key=${k} style=${b.align[k] ? { textAlign: b.align[k] } : undefined}><${Runs} nodes=${c} /></th>`)}</tr></thead>
        <tbody>${b.rows.map((r, j) => html`<tr key=${j}>${r.map((c, k) => html`<td key=${k} style=${b.align[k] ? { textAlign: b.align[k] } : undefined}><${Runs} nodes=${c} /></td>`)}</tr>`)}</tbody>
      </table></div>`
      default: return null
    }
  })
}

/** An answer as formatted text: headings, lists, tables, code. Read once per text, so an answer that
 *  grows while it is written is read again only when it changed */
export function Prose({ text, cls = '', children }) {
  const blocks = useMemo(() => parseMarkdown(text), [text])
  return html`<div class=${`md ${cls}`}><${Blocks} blocks=${blocks} />${children}</div>`
}
