// SPDX-License-Identifier: MIT
// The cockpit, Markdown read into plain objects: what an answer in a chat says, as blocks and runs the
// page draws as elements (views/prose.js). Nothing here builds HTML, so text can never turn into markup;
// a link keeps http(s) and mailto only. A small reader for chat answers, not CommonMark: headings,
// paragraphs with their line breaks, lists (nested, numbered, ticked), fenced code, quotes, tables,
// rules; inline bold, italic, strike, code, links and bare addresses.

const FENCE_RE = /^( {0,3})(`{3,}|~{3,})\s*([^`\s]*)/
const HEADING_RE = /^ {0,3}(#{1,6})(?:\s+(.*?))?\s*$/
const RULE_RE = /^ {0,3}([-*_])(?:\s*\1){2,}\s*$/
const QUOTE_RE = /^ {0,3}>\s?/
const LIST_RE = /^( {0,3})([-*+]|\d{1,9}[.)])(?:(\s+)(.*))?$/
const TABLE_SEP_RE = /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/
const TASK_RE = /^\[([ xX])\]\s+/

/** A link target the page may follow: http(s) or mailto, else null (javascript:, data: and the rest stay text) */
export function safeHref(href) {
  const v = String(href ?? '').trim()
  return /^(https?:\/\/|mailto:)/i.test(v) ? v : null
}

const blank = line => !line.trim()
const indentOf = line => line.length - line.trimStart().length

function tableStart(lines, i) {
  return i + 1 < lines.length && lines[i].includes('|') && lines[i + 1].includes('|') && TABLE_SEP_RE.test(lines[i + 1])
}

/** Whether a line opens a block of its own, so it ends the paragraph above it */
function opensBlock(lines, i) {
  const l = lines[i]
  return FENCE_RE.test(l) || HEADING_RE.test(l) || RULE_RE.test(l) || QUOTE_RE.test(l) || LIST_RE.test(l) || tableStart(lines, i)
}

/** The cells of a table row: split at a bar that is neither escaped nor inside a code span */
function rowCells(line) {
  let s = line.trim()
  if (s.startsWith('|')) s = s.slice(1)
  if (s.endsWith('|') && !s.endsWith('\\|')) s = s.slice(0, -1)
  const cells = []
  let cur = ''
  let tick = 0
  for (let i = 0; i < s.length; i++) {
    const ch = s[i]
    if (ch === '\\' && s[i + 1] === '|') { cur += '\\|'; i++; continue }
    if (ch === '`') {
      let n = 1
      while (s[i + n] === '`') n++
      tick = tick === 0 ? n : tick === n ? 0 : tick
      cur += '`'.repeat(n)
      i += n - 1
      continue
    }
    if (ch === '|' && !tick) { cells.push(cur.trim()); cur = ''; continue }
    cur += ch
  }
  cells.push(cur.trim())
  return cells
}

function cellAlign(cell) {
  const l = cell.startsWith(':')
  const r = cell.endsWith(':')
  return l && r ? 'center' : r ? 'right' : l ? 'left' : null
}

function parseList(lines, at) {
  const first = LIST_RE.exec(lines[at])
  const ordered = /\d/.test(first[2])
  const base = first[1].length
  const items = []
  let i = at
  while (i < lines.length) {
    const m = LIST_RE.exec(lines[i])
    if (!m || m[1].length !== base || /\d/.test(m[2]) !== ordered) break
    const gap = m[3]?.length ?? 1
    const inner = m[1].length + m[2].length + (gap > 4 ? 1 : gap)
    const near = Math.min(inner, base + 2)
    const body = [m[4] ?? '']
    i++
    while (i < lines.length) {
      const l = lines[i]
      if (blank(l)) {
        let k = i + 1
        while (k < lines.length && blank(lines[k])) k++
        if (k < lines.length && indentOf(lines[k]) >= near) { body.push(''); i++; continue }
        break
      }
      const n = indentOf(l)
      if (n >= near) body.push(l.slice(Math.min(n, inner)))
      else if (opensBlock(lines, i)) break
      else body.push(l.trim())
      i++
    }
    const task = TASK_RE.exec(body[0])
    if (task) body[0] = body[0].slice(task[0].length)
    items.push({ checked: task ? task[1] !== ' ' : null, blocks: parseBlocks(body) })
  }
  return [{ type: 'list', ordered, start: ordered ? parseInt(first[2], 10) : null, items }, i]
}

function parseBlocks(lines) {
  const out = []
  let i = 0
  while (i < lines.length) {
    const line = lines[i]
    if (blank(line)) { i++; continue }
    const fence = FENCE_RE.exec(line)
    if (fence) {
      const [, pad, mark, lang] = fence
      const close = new RegExp(`^ {0,3}${mark[0] === '`' ? '`' : '~'}{${mark.length},}\\s*$`)
      const body = []
      i++
      while (i < lines.length && !close.test(lines[i])) {
        const l = lines[i]
        body.push(l.slice(Math.min(pad.length, indentOf(l))))
        i++
      }
      i++
      out.push({ type: 'code', lang, text: body.join('\n') })
      continue
    }
    const head = HEADING_RE.exec(line)
    if (head) {
      out.push({ type: 'h', level: head[1].length, inline: parseInline((head[2] ?? '').replace(/\s+#+$/, '').replace(/^#+$/, '')) })
      i++
      continue
    }
    if (RULE_RE.test(line)) { out.push({ type: 'hr' }); i++; continue }
    if (QUOTE_RE.test(line)) {
      const body = []
      while (i < lines.length && QUOTE_RE.test(lines[i])) { body.push(lines[i].replace(QUOTE_RE, '')); i++ }
      out.push({ type: 'quote', blocks: parseBlocks(body) })
      continue
    }
    if (LIST_RE.test(line)) {
      const [list, next] = parseList(lines, i)
      out.push(list)
      i = next
      continue
    }
    if (tableStart(lines, i)) {
      const head = rowCells(line)
      const align = rowCells(lines[i + 1]).map(cellAlign)
      const rows = []
      i += 2
      while (i < lines.length && !blank(lines[i]) && lines[i].includes('|')) {
        const cells = rowCells(lines[i])
        rows.push(head.map((_, k) => parseInline(cells[k] ?? '')))
        i++
      }
      out.push({ type: 'table', head: head.map(c => parseInline(c)), align: head.map((_, k) => align[k] ?? null), rows })
      continue
    }
    const para = [line.trim()]
    i++
    while (i < lines.length && !blank(lines[i]) && !opensBlock(lines, i)) { para.push(lines[i].trim()); i++ }
    out.push({ type: 'p', inline: parseInline(para.join('\n')) })
  }
  return out
}

/** Blocks of a Markdown text: h (level, inline), p (inline), code (lang, text), quote (blocks),
 *  list (ordered, start, items of { checked, blocks }), table (head, align, rows), hr. A fence still
 *  open at the end (an answer being written) holds the rest as code */
export function parseMarkdown(text) {
  if (typeof text !== 'string' || !text) return []
  return parseBlocks(text.replace(/\r\n?/g, '\n').replace(/\t/g, '    ').split('\n'))
}

// ---------------------------------------------------------------- inline

// the runs an inline text may hold; at one position the first in this list wins (bold before italic)
const INLINE = [
  ['esc', /\\([\\`*_{}[\]()#+\-.!~|<>])/g],
  ['code', /(`+)(?!`)([\s\S]*?[^`])\1(?!`)/g],
  ['link', /\[([^\]\n]*)\]\(\s*<?([^\s()<>]*(?:\([^\s()<>]*\)[^\s()<>]*)*)>?(?:\s+"[^"\n]*")?\s*\)/g],
  ['auto', /<((?:https?:\/\/|mailto:)[^\s<>]+)>/g],
  ['url', /\bhttps?:\/\/[^\s<>"'`]+/g],
  ['b', /\*\*(?=\S)([\s\S]*?\S)\*\*(?!\*)/g],
  ['b', /(?<![\p{L}\p{N}_])__(?=\S)([\s\S]*?\S)__(?![\p{L}\p{N}_])/gu],
  ['s', /~~(?=\S)([\s\S]*?\S)~~/g],
  ['i', /\*(?![\s*])([^*\n]*?[^\s*])\*(?!\*)/g],
  ['i', /(?<![\p{L}\p{N}_])_(?![\s_])([^_\n]*?[^\s_])_(?![\p{L}\p{N}_])/gu],
]

function pushText(out, s) {
  s.split('\n').forEach((part, k) => {
    if (k) out.push({ t: 'br' })
    if (!part) return
    const last = out[out.length - 1]
    if (last?.t === 'text') last.v += part
    else out.push({ t: 'text', v: part })
  })
}

function pushAll(out, nodes) {
  for (const n of nodes) {
    if (n.t === 'text') pushText(out, n.v)
    else out.push(n)
  }
}

/** Runs of one inline text: text, br, code (v), b / i / s (c), a (href, c) */
export function parseInline(text) {
  const out = []
  const s = typeof text === 'string' ? text : ''
  // each pattern's next match is kept until the reading passes it, and a pattern that found nothing is
  // asked no more: one pass over the text, not one per run
  const next = INLINE.map(() => undefined)
  let pos = 0
  while (pos < s.length) {
    let best = null
    INLINE.forEach(([kind, re], k) => {
      if (next[k] === null) return
      if (next[k] === undefined || next[k].index < pos) {
        re.lastIndex = pos
        next[k] = re.exec(s)
        if (next[k] === null) return
      }
      if (!best || next[k].index < best.m.index) best = { kind, m: next[k] }
    })
    if (!best) { pushText(out, s.slice(pos)); break }
    const { kind, m } = best
    let used = m[0]
    if (m.index > pos) pushText(out, s.slice(pos, m.index))
    if (kind === 'esc') pushText(out, m[1])
    else if (kind === 'code') {
      const v = m[2].replace(/\n/g, ' ')
      out.push({ t: 'code', v: /^ .*[^ ].* $/.test(v) ? v.slice(1, -1) : v })
    } else if (kind === 'link') {
      const href = safeHref(m[2])
      const c = parseInline(m[1])
      if (href) out.push({ t: 'a', href, c })
      else pushAll(out, c)
    } else if (kind === 'auto') {
      const href = safeHref(m[1])
      if (href) out.push({ t: 'a', href, c: [{ t: 'text', v: m[1] }] })
      else pushText(out, m[0])
    } else if (kind === 'url') {
      while (/[.,;:!?)\]}*_~]$/.test(used)) used = used.slice(0, -1)
      out.push({ t: 'a', href: used, c: [{ t: 'text', v: used }] })
    } else out.push({ t: kind, c: parseInline(m[1]) })
    pos = m.index + used.length
  }
  return out
}
