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
//
// A failing assertion on a node prints it as a tag, never as the page behind it (the comment above class
// Node). A runaway fails its test instead of filling the machine (§ the runaway guard below): a component rendered
// more than RENDER_BURST times without the event loop turning, or more than RENDER_RATE times within a second,
// throws "render loop: <Name>"; a heap past HEAP_CEILING_MB throws "heap ceiling"; and every mounted root is
// unmounted when its file ends, so an effect still ticking cannot keep the process alive.
import fs from 'node:fs'
import os from 'node:os'
import path from 'node:path'
import util from 'node:util'
import { fileURLToPath, pathToFileURL } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const WEB = path.resolve(here, '..', 'web')

// ---------------------------------------------------------------- the DOM

// the event props Preact finds on an element by name, so it listens to `click` and not to `Click`
const EVENTS = ['click', 'dblclick', 'input', 'change', 'submit', 'keydown', 'keyup', 'keypress', 'focus', 'blur', 'focusin',
  'focusout', 'pointerdown', 'pointerup', 'pointermove', 'pointerenter', 'pointerleave', 'mousedown', 'mouseup', 'mouseenter',
  'mouseleave', 'contextmenu', 'scroll', 'wheel', 'toggle', 'load', 'error', 'dragstart', 'dragover', 'dragleave', 'drop',
  'animationend', 'transitionend', 'copy', 'paste']

// What a failing assertion prints of a node must stay small. node's assert prints `actual` with depth 1000,
// sorted, with getters and without custom inspectors, and it marks a cycle only along the current path, so a
// value reached twice is printed twice. A node reaches its parent, its children and, on a mounted root,
// Preact's vnode tree with the whole page state behind it: printed that way it never ended and grew the process
// by gigabytes a second, outside the heap, so neither a heap cap nor the test timeout stopped it (27.10.2026).
// So every link out of a node is non-enumerable, which assert and the reporter skip, the keys Preact writes on
// a DOM node (`__k` the root's vnode, `l` the listeners) land in a hidden slot, and util.inspect, which the
// reporters use, shows a node as its tag, its classes and the start of its text.
const hidden = (obj, key, value) => Object.defineProperty(obj, key, { value, writable: true, configurable: true, enumerable: false })
const TEXT_SHOWN = 60

class Node {
  constructor(nodeType) {
    this.nodeType = nodeType
    hidden(this, 'parentNode', null)
    hidden(this, 'childNodes', [])
  }

  [util.inspect.custom]() {
    if (this.nodeType === 3) return `#text ${JSON.stringify(clip(this.data))}`
    if (this.localName === '#document') return '#document'
    const cls = this.getAttribute('class')
    return `<${this.localName}${cls ? ` class="${cls}"` : ''}>${clip(this.text())}</${this.localName}>`
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
    hidden(this, 'listeners', new Map())
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

/** A text cut to what a failure message needs */
const clip = t => (t.length > TEXT_SHOWN ? `${t.slice(0, TEXT_SHOWN)}…` : t)

// the keys Preact sets on a DOM node, kept off the node's own enumerable properties (see above)
for (const key of ['__k', 'l']) {
  const slot = Symbol(key)
  Object.defineProperty(Node.prototype, key, { configurable: true, get() { return this[slot] }, set(v) { hidden(this, slot, v) } })
}

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
  createElement(name) { checkHeap(); return new Element(name) }
  createElementNS(ns, name) { checkHeap(); return new Element(name, ns) }
  createTextNode(data) { checkHeap(); return new Text(data) }
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

// ---------------------------------------------------------------- the runaway guard

// Why a guard and not a timeout: Preact drains its render queue in one microtask and runs layout effects inside
// that drain, so a component that sets state from a layout effect or from its own render renders again before
// any timer can fire. The test timeout is a timer, so it never fires, and the process grows until the heap cap
// or the machine ends it. An effect loop goes through requestAnimationFrame (a timer here) instead: the timeout
// fires, but the root is never unmounted, so the loop keeps rendering and the file never ends. Both are counted
// here, on every render, which needs no timer to run.
//
// The real suites stay far below each budget: measured with COCKPIT_RENDER_STATS=1 on 27.10.2026 over every
// bridge_cockpit_*.test.mjs, the most renders of one component were 4 in a burst and 7 in a second, and the heap
// peaked at 81 MB (209 MB resident). An effect loop renders some 350 times a second here, so the rate budget
// trips it within a third of a second; the ceiling sits below the 512 MB heap cap CI runs with, so the guard
// speaks before V8 aborts.

/** Renders of one component instance without the event loop turning in between */
export const RENDER_BURST = 100
/** Renders of one component instance within one second */
export const RENDER_RATE = 100
/** The heap a cockpit test may use, in MB; COCKPIT_RENDER_HEAP_MB overrides it */
export const HEAP_CEILING_MB = Number(process.env.COCKPIT_RENDER_HEAP_MB) || 384
const HEAP_EVERY = 1000          // renders or created nodes between two heap checks

const sites = new WeakMap()      // mounted root -> where the test mounted it
const roots = new Set()          // WeakRefs of every mounted root, unmounted when the file ends
const counts = new WeakMap()     // component instance -> { burst, turn, second, since }
let burstTurn = 0                // bumped once per turn of the event loop that rendered anything
let turnArmed = false
let ticks = 0
const stats = process.env.COCKPIT_RENDER_STATS ? { burst: 0, rate: 0, heap: 0 } : null

/** The component's name as a person reads it in a test */
const nameOf = vnode => vnode.type?.displayName || vnode.type?.name || 'an anonymous component'

/** Where the root this instance renders into was mounted, from the stack mount() kept */
function siteOf(inst) {
  let n = inst?.__P
  while (n?.parentNode) n = n.parentNode
  return (n && sites.get(n)) || 'an unknown place'
}

function checkHeap() {
  if (++ticks % HEAP_EVERY) return
  const used = process.memoryUsage().heapUsed / 1048576
  if (stats) stats.heap = Math.max(stats.heap, used)
  if (used > HEAP_CEILING_MB) {
    throw new Error(`cockpit_render: heap ceiling: ${Math.round(used)} MB used, more than ${HEAP_CEILING_MB} MB; `
      + 'an unbounded list or a state that grows on every render (COCKPIT_RENDER_HEAP_MB moves the ceiling)')
  }
}

/** Counts one render of the component of `vnode` and throws once it renders without end */
function countRender(vnode) {
  const inst = vnode.__c
  if (!turnArmed) { turnArmed = true; setImmediate(() => { burstTurn++; turnArmed = false }) }
  const now = Date.now()
  let c = counts.get(inst)
  if (!c) counts.set(inst, c = { burst: 0, turn: burstTurn, second: 0, since: now })
  if (c.turn !== burstTurn) { c.turn = burstTurn; c.burst = 0 }
  if (now - c.since >= 1000) { c.since = now; c.second = 0 }
  c.burst++
  c.second++
  if (stats) { stats.burst = Math.max(stats.burst, c.burst); stats.rate = Math.max(stats.rate, c.second) }
  const over = c.burst > RENDER_BURST ? `${c.burst} times without the event loop turning (budget ${RENDER_BURST})`
    : c.second > RENDER_RATE ? `${c.second} times within a second (budget ${RENDER_RATE})` : null
  if (over) {
    // Preact's queue counter stays raised after a throw from its drain; a fresh scheduler makes the next update
    // flush again, so the tests after this one still render
    loaded.options.debounceRendering = fn => Promise.resolve().then(fn)
    throw new Error(`cockpit_render: render loop: ${nameOf(vnode)} rendered ${over}; a state update in its render, `
      + `in an effect or in a layout effect schedules it again on every render. Mounted at ${siteOf(inst)}`)
  }
  checkHeap()
}

async function installGuard(options) {
  const before = options.__r          // Preact's mangled options._render, called before every component render
  options.__r = vnode => { countRender(vnode); before?.(vnode) }
  if (stats) process.on('exit', () => process.stderr.write(`cockpit_render stats: most renders of one component in a burst `
    + `${stats.burst}, in a second ${stats.rate}, heap peak ${Math.round(stats.heap)} MB\n`))
  // only under `node --test`: a hook registered from a plain script starts a test run of its own, whose report
  // lands in that script's output (test_cockpit_costs_contract.py renders through this file that way)
  if (!process.env.NODE_TEST_CONTEXT) return
  const { after } = await import('node:test')
  after(() => {
    for (const ref of roots) { const root = ref.deref(); if (root) try { loaded.render(null, root) } catch { /* torn down anyway */ } }
    roots.clear()
  })
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
  // the copy also exports Preact's options object (`n` in the minified bundle), which the guard hooks into;
  // the page's own file stays as vendored
  const bundle = path.join(web, 'vendor', 'htm-preact-3.1.1.module.js')
  const src = fs.readFileSync(bundle, 'utf8')
  if (!src.includes('export{a as h,')) throw new Error('cockpit_render: the vendored Preact changed its exports; update the guard')
  fs.writeFileSync(bundle, src.replace('export{a as h,', 'export{n as options,a as h,'))
  const load = rel => import(pathToFileURL(path.join(web, rel)).href)
  const vendor = await load('vendor/htm-preact-3.1.1.module.js')
  if (typeof vendor.options?.__e !== 'function') throw new Error('cockpit_render: `n` is no longer Preact\'s options object')
  const views = {}
  for (const name of ['home', 'detail', 'sessions', 'header', 'tabs', 'day', 'github', 'rooms', 'reply', 'organize', 'chat', 'agents', 'pages', 'costs', 'guide', 'tour', 'hints', 'overlays', 'list', 'focus', 'stage', 'dossier', 'check', 'parts', 'nav', 'card', 'flow', 'verbbar', 'flowside', 'flowtabs', 'flowinstruct', 'flowlist', 'flowleft', 'flowrun', 'flowprio', 'settings']) views[name] = await load(`views/${name}.js`)
  await installGuard(vendor.options)
  loaded = { ...vendor, views, text: await load('text.js'), logic: await load('logic.js'), mock: await load('mock.js'),
    jev: await load('jev/page.js') }
  return loaded
}

/** Renders a vnode into a fresh detached element and hands that element back for queries */
export function mount(vnode) {
  if (!loaded) throw new Error('cockpit_render: await loadCockpit() before mount()')
  const root = document.createElement('div')
  // the first frame outside this file is the test that mounts
  const site = new Error().stack.split('\n').slice(2).find(l => !l.includes('cockpit_render.mjs'))
  sites.set(root, site ? site.trim().replace(/^at /, '') : 'an unknown place')
  roots.add(new WeakRef(root))
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
