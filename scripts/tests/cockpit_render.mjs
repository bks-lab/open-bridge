// SPDX-License-Identifier: MIT
// The render helper of the cockpit tests: mounts a view of scripts/web/views/ with the vendored Preact
// into a small DOM written here, so a test asserts on what the page shows instead of on its source.
// No npm dependency, no browser.
//
//   const { html, views, text, mock } = await loadCockpit()
//   const el = mount(html`<${views.home.ReturnCard} r=${r} s=${cockpitState(now)} c=${recorder()} />`)
//   el.$('.rcard-title').text(); el.button('Close tab').click()
//
// The DOM covers what Preact's render and the views touch: elements, text nodes, attributes, style,
// listeners with bubbling clicks, and a selector subset for queries (tag, .class, #id, [attr],
// [attr="value"], descendant and > child). It is no browser: no layout, no CSS, no focus. Effects run
// on Preact's own timer; motion reads reduced, so a tween shows its target at once.
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath, pathToFileURL } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const WEB = path.resolve(here, '..', 'web')

// ---------------------------------------------------------------- the DOM

// the event props Preact finds on an element by name, so it listens to `click` and not to `Click`
const EVENTS = ['click', 'dblclick', 'input', 'change', 'submit', 'keydown', 'keyup', 'keypress', 'focus', 'blur', 'focusin',
  'focusout', 'pointerdown', 'pointerup', 'pointermove', 'pointerenter', 'pointerleave', 'mousedown', 'mouseup', 'mouseenter',
  'mouseleave', 'contextmenu', 'scroll', 'wheel', 'toggle', 'load', 'error', 'dragstart', 'dragover', 'dragleave', 'drop',
  'animationend', 'transitionend', 'copy', 'paste']

class Node {
  constructor(nodeType) {
    this.nodeType = nodeType
    this.parentNode = null
    this.childNodes = []
  }

  get firstChild() { return this.childNodes[0] ?? null }

  get nextSibling() {
    const sibs = this.parentNode?.childNodes
    return sibs ? sibs[sibs.indexOf(this) + 1] ?? null : null
  }

  appendChild(child) { return this.insertBefore(child, null) }

  insertBefore(child, ref) {
    child.parentNode?.removeChild(child)
    const at = ref ? this.childNodes.indexOf(ref) : -1
    this.childNodes.splice(at < 0 ? this.childNodes.length : at, 0, child)
    child.parentNode = this
    return child
  }

  removeChild(child) {
    const at = this.childNodes.indexOf(child)
    if (at >= 0) this.childNodes.splice(at, 1)
    child.parentNode = null
    return child
  }

  remove() { this.parentNode?.removeChild(this) }

  contains(other) {
    for (let n = other; n; n = n.parentNode) if (n === this) return true
    return false
  }

  get textContent() { return this.childNodes.map(n => n.textContent).join('') }
}

class Text extends Node {
  constructor(data) {
    super(3)
    this.data = String(data)
  }

  get textContent() { return this.data }
}

class Element extends Node {
  constructor(name, ns = null) {
    super(1)
    this.localName = name
    this.tagName = name.toUpperCase()
    this.namespaceURI = ns
    this.attrs = new Map()
    this.listeners = new Map()
    const style = { cssText: '' }
    Object.defineProperty(style, 'setProperty', { value: (k, v) => { style[k] = v } })
    this.style = style
  }

  get attributes() { return [...this.attrs].map(([name, value]) => ({ name, value })) }
  setAttribute(name, value) { this.attrs.set(name, String(value)) }
  getAttribute(name) { return this.attrs.has(name) ? this.attrs.get(name) : null }
  hasAttribute(name) { return this.attrs.has(name) }
  removeAttribute(name) { this.attrs.delete(name) }

  addEventListener(type, fn, capture = false) {
    const key = `${type.toLowerCase()}:${!!capture}`
    if (!this.listeners.has(key)) this.listeners.set(key, new Set())
    this.listeners.get(key).add(fn)
  }

  removeEventListener(type, fn, capture = false) { this.listeners.get(`${type.toLowerCase()}:${!!capture}`)?.delete(fn) }

  /** Fires an event here and bubbles it up, the way a browser does without capture */
  dispatch(type, init = {}) {
    let stopped = false
    const ev = { type, target: this, currentTarget: this, defaultPrevented: false, ...init,
      preventDefault() { ev.defaultPrevented = true }, stopPropagation() { stopped = true } }
    for (let n = this; n && !stopped; n = n.parentNode) {
      ev.currentTarget = n
      for (const fn of n.listeners?.get(`${type}:false`) ?? []) fn.call(n, ev)
    }
    return ev
  }

  // ---- for the tests

  /** A click as a person makes it: a disabled button takes none */
  click() {
    if (this.localName === 'button' && this.hasAttribute('disabled')) return null
    return this.dispatch('click')
  }

  /** The visible text, blanks collapsed */
  text() { return this.textContent.replace(/\s+/g, ' ').trim() }

  hasClass(name) { return (this.getAttribute('class') ?? '').split(/\s+/).includes(name) }

  $$(selector) { return descendants(this).filter(el => matches(el, parseSelector(selector), this)) }
  $(selector) { return this.$$(selector)[0] ?? null }

  /** The first button whose text or aria-label is `label`, or null */
  button(label) { return this.$$('button').find(b => b.text() === label || b.getAttribute('aria-label') === label) ?? null }
}

for (const name of EVENTS) Object.defineProperty(Element.prototype, `on${name}`, { value: null, writable: true })

function descendants(root) {
  const out = []
  const walk = n => { for (const c of n.childNodes) if (c.nodeType === 1) { out.push(c); walk(c) } }
  walk(root)
  return out
}

/** A selector as compounds from left to right, each with the combinator before it */
function parseSelector(selector) {
  const parts = []
  let buf = ''
  let comb = ' '
  let quote = null
  let depth = 0
  const flush = () => { if (buf) { parts.push({ comb, ...parseCompound(buf) }); comb = ' '; buf = '' } }
  for (let i = 0; i < selector.length; i++) {
    const ch = selector[i]
    if (quote) { buf += ch; if (ch === quote) quote = null; continue }
    if (ch === '\\') { buf += ch + selector[++i]; continue }
    if (ch === '"' || ch === "'") quote = ch
    if (ch === '[') depth++
    if (ch === ']') depth--
    if (depth === 0 && (ch === ' ' || ch === '>')) { flush(); if (ch === '>') comb = '>'; continue }
    buf += ch
  }
  flush()
  return parts
}

function parseCompound(src) {
  const c = { tag: null, classes: [], attrs: [] }
  const re = /^([a-zA-Z][\w-]*)|\.((?:\\.|[\w-])+)|#((?:\\.|[\w-])+)|\[([\w-]+)(?:=(?:"([^"]*)"|'([^']*)'|([^\]]*)))?\]/y
  const unescape = v => v.replace(/\\(.)/g, '$1')
  for (let at = 0; at < src.length;) {
    re.lastIndex = at
    const m = re.exec(src)
    if (!m) throw new Error(`cockpit_render: selector not supported: ${src}`)
    if (m[1]) c.tag = m[1].toLowerCase()
    else if (m[2]) c.classes.push(unescape(m[2]))
    else if (m[3]) c.attrs.push(['id', unescape(m[3])])
    else c.attrs.push([m[4], m[5] ?? m[6] ?? m[7] ?? null])
    at = re.lastIndex
  }
  return c
}

function matchesCompound(el, c) {
  if (c.tag && el.localName !== c.tag) return false
  if (!c.classes.every(x => el.hasClass(x))) return false
  return c.attrs.every(([k, v]) => (v === null ? el.hasAttribute(k) : el.getAttribute(k) === v))
}

/** Right to left: the last compound is the element, the ones before are its ancestors inside root */
function matches(el, parts, root, i = parts.length - 1) {
  if (!matchesCompound(el, parts[i])) return false
  if (i === 0) return true
  for (let up = el.parentNode; up && up !== root; up = up.parentNode) {
    if (matches(up, parts, root, i - 1)) return true
    if (parts[i].comb === '>') return false
  }
  return false
}

class Document extends Element {
  constructor() { super('#document') }
  createElement(name) { return new Element(name) }
  createElementNS(ns, name) { return new Element(name, ns) }
  createTextNode(data) { return new Text(data) }
}

/** Puts the DOM on globalThis once; before the vendored Preact loads, which reads it at import */
function installDom() {
  if (globalThis.document instanceof Document) return
  globalThis.document = new Document()
  globalThis.document.body = globalThis.document.appendChild(new Element('body'))
  globalThis.matchMedia = query => ({ matches: /prefers-reduced-motion:\s*reduce/.test(query), media: query,
    addEventListener() {}, removeEventListener() {} })
  globalThis.requestAnimationFrame = fn => setTimeout(() => fn(Date.now()), 0)
  globalThis.cancelAnimationFrame = id => clearTimeout(id)
}

// ---------------------------------------------------------------- the cockpit modules

let loaded = null

/** The page's modules from a temp copy of scripts/web, marked as ES modules so every Node version loads
 *  them; the copy goes when the process ends */
export async function loadCockpit() {
  if (loaded) return loaded
  installDom()
  const tmp = fs.mkdtempSync(path.join(os.tmpdir(), 'bridge-cockpit-render-'))
  process.on('exit', () => fs.rmSync(tmp, { recursive: true, force: true }))
  const web = path.join(tmp, 'web')
  fs.cpSync(WEB, web, { recursive: true })
  fs.writeFileSync(path.join(web, 'package.json'), '{ "type": "module" }\n')
  const load = rel => import(pathToFileURL(path.join(web, rel)).href)
  const vendor = await load('vendor/htm-preact-3.1.1.module.js')
  const views = {}
  for (const name of ['home', 'detail', 'sessions', 'header', 'tabs', 'day', 'github', 'rooms', 'reply', 'organize', 'chat', 'agents', 'pages', 'costs', 'guide', 'tour', 'hints', 'overlays', 'list', 'focus', 'stage', 'dossier', 'check', 'parts', 'nav', 'card', 'flow', 'verbbar', 'flowside', 'flowtabs', 'flowinstruct']) views[name] = await load(`views/${name}.js`)
  loaded = { ...vendor, views, text: await load('text.js'), logic: await load('logic.js'), mock: await load('mock.js'),
    jev: await load('jev/page.js') }
  return loaded
}

/** Renders a vnode into a fresh detached element and hands that element back for queries */
export function mount(vnode) {
  if (!loaded) throw new Error('cockpit_render: await loadCockpit() before mount()')
  const root = document.createElement('div')
  loaded.render(vnode, root)
  return root
}

/** The whole page state as the store holds it, from the invented data of mock.js; `over` replaces keys,
 *  `ui` is merged into the default ui */
export function cockpitState(now, over = {}) {
  if (!loaded) throw new Error('cockpit_render: await loadCockpit() before cockpitState()')
  const { ui = {}, ...rest } = over
  return {
    ...loaded.mock.buildState(now),
    boot: { status: 'ok', error: null, version: '0.1.0', config: {}, scratch: null },
    now, layout: 'wide', mock: false, conn: 'open', driver: { caps: null },
    home: { tiles: null, seen: null, pins: [] }, details: { inbox: {}, task: {} }, more: {},
    ui: { page: 'briefing', busy: {}, openMsg: null, drawer: null, theme: 'auto', expanded: {}, picked: [], ...ui },
    ...rest,
  }
}

/** A stand-in for the page's controller: every method call is kept in `calls` as [name, ...args] */
export function recorder() {
  const calls = []
  return new Proxy({}, {
    get(_, prop) {
      if (prop === 'calls') return calls
      if (typeof prop === 'symbol' || prop === 'then') return undefined
      return (...args) => { calls.push([prop, ...args]); return undefined }
    },
  })
}
