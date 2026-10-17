// SPDX-License-Identifier: MIT
// Tests of the cockpit's Markdown reader (scripts/web/markdown.js), no npm dependencies.
//
//   node scripts/tests/bridge_cockpit_markdown.test.mjs
//
// The reader turns an answer into plain objects the page draws as elements; it never builds
// HTML, so the only thing that could carry script is a link, and a link keeps http(s) and mailto only.
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'
import test from 'node:test'
import assert from 'node:assert/strict'

const here = path.dirname(fileURLToPath(import.meta.url))
const SRC = path.resolve(here, '..', 'web', 'markdown.js')
const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'bridge-cockpit-markdown-'))
fs.copyFileSync(SRC, path.join(tmp, 'markdown.mjs'))
const { parseMarkdown, parseInline, safeHref } = await import(pathToFileURL(path.join(tmp, 'markdown.mjs')).href)

const txt = v => ({ t: 'text', v })

test('plain text stays one paragraph, a single line break stays a break', () => {
  assert.deepEqual(parseMarkdown('Hallo\nWelt'), [{ type: 'p', inline: [txt('Hallo'), { t: 'br' }, txt('Welt')] }])
})

test('a blank line starts a new paragraph', () => {
  assert.deepEqual(parseMarkdown('eins\n\nzwei').map(b => b.type), ['p', 'p'])
})

test('headings keep their level', () => {
  const b = parseMarkdown('# Eins\n### Drei ###')
  assert.deepEqual(b.map(x => [x.type, x.level]), [['h', 1], ['h', 3]])
  assert.deepEqual(b[1].inline, [txt('Drei')])
})

test('bold, italic, strike and code inline', () => {
  assert.deepEqual(parseInline('a **b** _c_ *d* ~~e~~ `f*g*`'), [
    txt('a '), { t: 'b', c: [txt('b')] }, txt(' '), { t: 'i', c: [txt('c')] }, txt(' '),
    { t: 'i', c: [txt('d')] }, txt(' '), { t: 's', c: [txt('e')] }, txt(' '), { t: 'code', v: 'f*g*' },
  ])
})

test('bold may hold italic', () => {
  assert.deepEqual(parseInline('**a *b***'), [{ t: 'b', c: [txt('a '), { t: 'i', c: [txt('b')] }] }])
})

test('an underscore inside a word is no emphasis', () => {
  assert.deepEqual(parseInline('snake_case_name'), [txt('snake_case_name')])
})

test('a lone star stays a star', () => {
  assert.deepEqual(parseInline('2 * 3'), [txt('2 * 3')])
})

test('a backslash escapes a mark', () => {
  assert.deepEqual(parseInline('\\*kein\\*'), [txt('*kein*')])
})

test('links: markdown, angle and bare, a trailing period stays outside', () => {
  const u = 'https' + '://example.org/a'
  assert.deepEqual(parseInline(`[Seite](${u})`), [{ t: 'a', href: u, c: [txt('Seite')] }])
  assert.deepEqual(parseInline(`<${u}>`), [{ t: 'a', href: u, c: [txt(u)] }])
  assert.deepEqual(parseInline(`siehe ${u}.`), [txt('siehe '), { t: 'a', href: u, c: [txt(u)] }, txt('.')])
})

test('a link that is not http(s) or mailto stays text', () => {
  assert.equal(safeHref('javascript:alert(1)'), null)
  assert.equal(safeHref(' JavaScript:alert(1)'), null)
  assert.equal(safeHref('data:text/html,x'), null)
  assert.equal(safeHref('mailto:a@b.de'), 'mailto:a@b.de')
  assert.deepEqual(parseInline('[x](javascript:alert(1))').some(n => n.t === 'a'), false)
})

test('a fenced code block keeps its text and language, also while still open', () => {
  assert.deepEqual(parseMarkdown('```py\nx = 1\n  y\n```\nnach'), [
    { type: 'code', lang: 'py', text: 'x = 1\n  y' }, { type: 'p', inline: [txt('nach')] },
  ])
  assert.deepEqual(parseMarkdown('```\nhalb'), [{ type: 'code', lang: '', text: 'halb' }])
})

test('bullet and numbered lists, nested by indentation', () => {
  const [l] = parseMarkdown('- a\n- b\n  - b1\n  - b2\n- c')
  assert.equal(l.type, 'list')
  assert.equal(l.ordered, false)
  assert.equal(l.items.length, 3)
  assert.equal(l.items[1].blocks[1].type, 'list')
  assert.equal(l.items[1].blocks[1].items.length, 2)
  const [o] = parseMarkdown('3. drei\n4. vier')
  assert.equal(o.ordered, true)
  assert.equal(o.start, 3)
})

test('a task list item carries its tick', () => {
  const [l] = parseMarkdown('- [x] fertig\n- [ ] offen')
  assert.deepEqual(l.items.map(i => i.checked), [true, false])
  assert.deepEqual(l.items[0].blocks[0].inline, [txt('fertig')])
})

test('a list right after a paragraph line still is a list', () => {
  assert.deepEqual(parseMarkdown('Schritte:\n1. eins\n2. zwei').map(b => b.type), ['p', 'list'])
})

test('a table with alignment', () => {
  const [tb] = parseMarkdown('| A | B |\n|:--|--:|\n| 1 | `2|x` |\n| 3 |')
  assert.equal(tb.type, 'table')
  assert.deepEqual(tb.align, ['left', 'right'])
  assert.deepEqual(tb.head, [[txt('A')], [txt('B')]])
  assert.deepEqual(tb.rows[0][1], [{ t: 'code', v: '2|x' }])
  assert.equal(tb.rows[1].length, 2)
})

test('blockquote and rule', () => {
  const b = parseMarkdown('> zitiert\n> **fett**\n\n---\n')
  assert.equal(b[0].type, 'quote')
  assert.equal(b[0].blocks[0].type, 'p')
  assert.equal(b[1].type, 'hr')
})

test('empty and odd input never throws', () => {
  for (const v of ['', null, undefined, 42, '\n\n', '|', '- ', '#', '**', '`', '[a](', '> ']) {
    assert.ok(Array.isArray(parseMarkdown(v)))
  }
})

test('the reader builds no HTML', () => {
  const src = fs.readFileSync(SRC, 'utf8')
  assert.equal(/innerHTML|dangerouslySetInnerHTML|insertAdjacentHTML/.test(src), false)
})
