// SPDX-License-Identifier: MIT
// The cockpit, the tools of a chat, under the head of its field: Stop or Ctrl+C, the commands, a long text in peace, the
// keys as buttons, the whole conversation, the size of the type and the way to the real terminal; in the head the model,
// the context and the cost as the tab's own status line names them (logic.js termStatus), which may click. Everything
// typed goes through tab_keys, as the keyboard of the screen does, so a command is what you would type yourself. A
// command that would land in a question or behind a draft stays off. The history stands over the screen: an agent tab's
// whole conversation from its transcript, a shell's from the terminal (GET /api/tab-history).
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useLayoutEffect, useRef, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { WORKSPACE_COLORS, canTab, termCommands } from '../logic.js'
import { T } from '../text.js'
import { LaunchPick } from './launch.js'
import { Btn } from './parts.js'

const CLICK_KEYS = [['escape', 'Esc'], ['tab', 'Tab'], ['shift+tab', '⇧Tab'], ['up', '↑'], ['down', '↓'], ['left', '←'], ['right', '→'],
  ['home', 'Pos1'], ['end', 'End'], ['ctrl+c', 'Ctrl+C'], ['ctrl+l', 'Ctrl+L'], ['ctrl+r', 'Ctrl+R'], ['enter', 'Enter']]

/** A small menu at its button: fixed, since a field clips what stands in it. Closes on a click beside it and on Esc */
export function Pop({ at, onClose, up = false, cls = '', children }) {
  const box = useRef(null)
  useEffect(() => {
    const out = e => { if (!box.current?.contains(e.target)) onClose() }
    const esc = e => { if (e.key === 'Escape') onClose() }
    document.addEventListener('mousedown', out)
    document.addEventListener('keydown', esc)
    return () => { document.removeEventListener('mousedown', out); document.removeEventListener('keydown', esc) }
  }, [])
  const left = Math.max(8, Math.min(at.left, (globalThis.innerWidth ?? 1200) - 380))
  const style = up ? { left, bottom: (globalThis.innerHeight ?? 800) - at.top + 6 } : { left, top: at.bottom + 4 }
  return html`<div class=${`pop ${cls}`} ref=${box} style=${style}>${children}</div>`
}

/** Which menu of a bar is open, with the place of the button that opened it */
export function usePop() {
  const [pop, setPop] = useState(null)
  return { pop, close: () => setPop(null), open: name => e => {
    const r = e.currentTarget.getBoundingClientRect?.() ?? { left: 0, top: 0, bottom: 0 }
    setPop(p => (p?.name === name ? null : { name, at: r }))
  } }
}

/** The commands with a search; /clear asks once more, on the row itself */
function Commands({ tab, s, send }) {
  const t = T().tools
  const [q, setQ] = useState('')
  const [armed, setArmed] = useState(null)
  const field = useRef(null)
  useEffect(() => { field.current?.focus?.() }, [])
  const word = q.trim().toLowerCase()
  const groups = termCommands(tab, s, t).map(g => ({ ...g, items: g.items.filter(x => `${x.cmd} ${x.say}`.toLowerCase().includes(word)) })).filter(g => g.items.length)
  const pick = x => { if (x.ask && armed !== x.cmd) { setArmed(x.cmd); return } send(x.cmd) }
  return html`<input class="input" type="text" ref=${field} aria-label=${t.search} placeholder=${t.search} value=${q} onInput=${e => setQ(e.currentTarget.value)} />
    ${groups.map(g => html`<section key=${g.title}><h4 class="label-caps">${g.title}</h4>
      ${g.items.map(x => html`<button type="button" key=${x.cmd} class=${`pop-item${x.ask ? ' is-danger' : ''}${armed === x.cmd ? ' is-armed' : ''}`} onClick=${() => pick(x)}>
        <code>${x.cmd}</code><span class="muted">${armed === x.cmd ? t.again : x.say}</span></button>`)}</section>`)}`
}

/** The bar. `state` is the field's own: which strips stand open and the size of the type */
export function ToolBar({ tab, s, c, poke, keysOn, setKeysOn, writeOn, setWriteOn, histOn, setHistOn, setSize }) {
  const t = T().tools
  const { pop, close, open } = usePop()
  const agent = tab.state !== 'shell'
  const can = canTab(s, 'keys')
  const steps = list => { c.termKeys(tab.ref, list); poke?.() }
  const blocked = tab.state === 'needs-you' ? t.blockedAsk : tab.ask?.draft ? t.blockedDraft : null
  const send = cmd => { close(); steps([{ text: cmd }, { key: 'enter' }]) }
  const Tool = ({ icon, word, on, title, onClick, disabled, cls = '' }) => html`<button type="button" class=${`tool ${cls}${on ? ' is-on' : ''}`} title=${title ?? word} aria-label=${word}
    aria-pressed=${on === undefined ? undefined : String(on)} disabled=${disabled} onClick=${onClick}><span class="tool-ic" aria-hidden="true">${icon}</span><span class="tool-word">${word}</span></button>`
  return html`<div class="tools" role="toolbar" aria-label=${t.bar}>
    ${agent ? html`<${Tool} cls="tool-stop" icon="■" word=${t.stop} title=${t.stopTitle} disabled=${!can || tab.state !== 'working'} onClick=${() => steps([{ key: 'escape' }])} />`
      : html`<${Tool} cls="tool-stop" icon="■" word="Ctrl+C" title=${t.interrupt} disabled=${!can} onClick=${() => steps([{ key: 'ctrl+c' }])} />
        <${Tool} icon="⌫" word=${t.clear} disabled=${!can} onClick=${() => steps([{ key: 'ctrl+l' }])} />`}
    <${Tool} icon="/" word=${t.commands} disabled=${!can || !!blocked} title=${blocked ?? t.commands} on=${pop?.name === 'cmd'} onClick=${open('cmd')} />
    <${Tool} icon="✎" word=${t.write} on=${writeOn} disabled=${!can} onClick=${() => setWriteOn(!writeOn)} />
    <${Tool} icon="⌨" word=${t.keys} on=${keysOn} disabled=${!can} onClick=${() => setKeysOn(!keysOn)} />
    <${Tool} icon="☰" word=${t.history} on=${histOn} onClick=${() => setHistOn(!histOn)} />
    <span class="tools-gap"></span>
    <button type="button" class="tool" title=${t.smaller} aria-label=${t.smaller} onClick=${() => setSize(-1)}>A-</button>
    <button type="button" class="tool" title=${t.larger} aria-label=${t.larger} onClick=${() => setSize(1)}>A+</button>
    ${canTab(s, 'focus') ? html`<${Tool} icon="↗" word=${t.toTerminal} onClick=${() => c.act('tab_jump', { tab_ref: tab.ref })} />` : null}
    ${pop?.name === 'cmd' ? html`<${Pop} at=${pop.at} onClose=${close} cls="pop-cmd"><${Commands} tab=${tab} s=${s} send=${send} /><//>` : null}
  </div>`
}

/** ⋯ of a tab: beside, in the terminal, name, move, pin, branch. Closing stands in its head (TabClose) */
export function TabMenu({ tab, s, c, canName, close }) {
  const t = T().tools
  const [moving, setMoving] = useState(false)
  const act = fn => () => { close(); fn() }
  const spaces = (s.tabs?.workspaces ?? []).filter(w => w.ref !== tab.ws_ref)
  if (moving) return spaces.map(w => html`<button type="button" key=${w.ref} class="pop-item" onClick=${act(() => c.act('tab_move', { tab_ref: tab.ref, ws_ref: w.ref }))}>${w.title}</button>`)
  const free = tab.state === 'waiting' && !tab.ask?.draft && canTab(s, 'keys')
  const item = (word, fn, on = true) => html`<button type="button" class="pop-item" disabled=${!on} onClick=${fn}>${word}</button>`
  return html`${item(t.beside, act(() => c.fieldBeside(tab.ref)))}
    ${canTab(s, 'focus') ? item(t.toTerminal, act(() => c.act('tab_jump', { tab_ref: tab.ref }))) : null}
    ${canName ? item(t.rename, act(() => c.startRename('tab', tab.ref))) : null}
    ${canTab(s, 'move_tab') && spaces.length && !tab.slug && !tab.item && !tab.team ? item(t.move, () => setMoving(true)) : null}
    ${item((s.ui.pins ?? []).includes(tab.ref) ? t.unpin : t.pin, act(() => c.togglePin(tab.ref)))}
    ${tab.state !== 'shell' ? item(t.bell(!!s.ui.bells?.[tab.ref]), act(() => c.toggleBell(tab.ref))) : null}
    ${tab.state !== 'shell' ? item(t.cmd.branch, act(() => c.termKeys(tab.ref, [{ text: '/branch' }, { key: 'enter' }])), free) : null}`
}

/** A new chat in a workspace: an agent with a first sentence or none, a shell, or an earlier session going on */
export function NewChat({ s, c, ws }) {
  const t = T().tools
  const [kind, setKind] = useState('agent')
  const [text, setText] = useState('')
  const [title, setTitle] = useState('')
  const [beside, setBeside] = useState(false)
  const [note, setNote] = useState(null)
  const old = (s.sessions?.sessions ?? []).filter(x => !x.tab && x.sid).slice(0, 8)
  const opened = r => {
    if (!r?.ref) { if (r?.note) setNote(r.note); return }
    c.newChat(null)
    if (beside) c.fieldBeside(r.ref)
    c.pickRoom({ kind: 'tab', id: r.ref })
  }
  const start = async () => {
    if (kind === 'resume') return
    opened(await c.act('tab_new', { ws_ref: ws.ref, kind, ...(text.trim() ? { text: text.trim() } : {}), ...(title.trim() ? { title: title.trim() } : {}) }))
  }
  const resume = async sid => { const r = await c.act('session_resume', { session: sid }); if (r?.ok) c.newChat(null) }
  return html`<div class="overlay overlay-center" onClick=${e => { if (e.target === e.currentTarget) c.newChat(null) }}>
    <div class="dialog term new-chat" role="dialog" aria-modal="true" aria-label=${t.newChatIn(ws.title)}>
      <h2 class="sec-title">${t.newChatIn(ws.title)}</h2>
      <div class="new-kinds" role="group">${[['agent', t.kindAgent], ['shell', t.kindShell], ['resume', t.kindResume]].map(([k, w]) => html`<button type="button" key=${k} class=${`new-kind${kind === k ? ' is-on' : ''}`} aria-pressed=${String(kind === k)} onClick=${() => setKind(k)}>${w}</button>`)}</div>
      ${kind === 'agent' ? html`<label class="new-field">${t.firstLine}<textarea class="input" rows="3" value=${text} onInput=${e => setText(e.currentTarget.value)}></textarea></label>` : null}
      ${kind !== 'resume' ? html`<label class="new-field">${t.nameOptional}<input class="input" type="text" maxlength="80" value=${title} onInput=${e => setTitle(e.currentTarget.value)} /></label>` : null}
      ${kind === 'agent' ? html`<${LaunchPick} s=${s} c=${c} />` : null}
      ${kind === 'resume' ? html`<div class="new-resume">${old.map(x => html`<button type="button" key=${x.sid} class="pop-item" onClick=${() => resume(x.sid)}>${x.name || x.sid.slice(0, 8)}</button>`)}${old.length ? null : html`<p class="muted small">${t.noOld}</p>`}</div>` : null}
      ${kind !== 'resume' ? html`<label class="new-check"><input type="checkbox" checked=${beside} onChange=${e => setBeside(e.currentTarget.checked)} /> ${t.openBeside}</label>` : null}
      ${note ? html`<p class="reply-note small" role="status">${note}</p>` : null}
      <div class="btn-row dialog-acts"><${Btn} size="sm" variant="ghost" onClick=${() => c.newChat(null)}>${T().guide.cancel}<//>
        ${kind !== 'resume' ? html`<${Btn} size="sm" variant="primary" busy=${!!s.ui?.busy?.tab_new} onClick=${start}>${t.start}<//>` : null}</div>
    </div>
  </div>`
}

/** A new workspace: name, colour, folder, and a first chat in it */
export function NewWorkspace({ s, c }) {
  const t = T().tools
  const [title, setTitle] = useState('')
  const [color, setColor] = useState('')
  const [cwd, setCwd] = useState('')
  const [first, setFirst] = useState(true)
  const go = async () => {
    const v = title.trim()
    if (!v) return
    const r = await c.act('workspace_new', { title: v, kind: first ? 'agent' : 'shell', ...(color ? { color } : {}), ...(cwd.trim() ? { cwd: cwd.trim() } : {}) })
    if (r?.ref) { c.newChat(null); c.pickRoom({ kind: 'tab', id: r.ref }) }
  }
  return html`<div class="overlay overlay-center" onClick=${e => { if (e.target === e.currentTarget) c.newChat(null) }}>
    <div class="dialog term new-chat" role="dialog" aria-modal="true" aria-label=${t.newWorkspace}>
      <h2 class="sec-title">${t.newWorkspace}</h2>
      <label class="new-field">${t.name}<input class="input" type="text" maxlength="80" value=${title} onInput=${e => setTitle(e.currentTarget.value)} /></label>
      <label class="new-field">${t.color}<select class="input" value=${color} onChange=${e => setColor(e.currentTarget.value)}><option value="">${t.noColor}</option>${WORKSPACE_COLORS.map(x => html`<option key=${x} value=${x}>${x}</option>`)}</select></label>
      <label class="new-field">${t.folder}<input class="input" type="text" value=${cwd} onInput=${e => setCwd(e.currentTarget.value)} /></label>
      <label class="new-check"><input type="checkbox" checked=${first} onChange=${e => setFirst(e.currentTarget.checked)} /> ${t.firstChat}</label>
      <div class="btn-row dialog-acts"><${Btn} size="sm" variant="ghost" onClick=${() => c.newChat(null)}>${T().guide.cancel}<//>
        <${Btn} size="sm" variant="primary" disabled=${!title.trim()} busy=${!!s.ui?.busy?.workspace_new} onClick=${go}>${t.create}<//></div>
    </div>
  </div>`
}

/** ⋯ of a workspace; closing asks once more on the row, and the server refuses while a tab works or asks */
export function WorkspaceMenu({ w, s, c, canName, close }) {
  const t = T().tools
  const [armed, setArmed] = useState(false)
  const act = fn => () => { close(); fn() }
  const refs = w.tabs.map(x => x.ref)
  const shut = () => { if (!armed) { setArmed(true); return } close(); c.act('workspace_close', { ws_ref: w.ref, tabs: refs }) }
  return html`${canTab(s, 'new_tab') ? html`<button type="button" class="pop-item" onClick=${act(() => c.newChat({ ws: { ref: w.ref, title: w.title } }))}>${t.newChat}</button>` : null}
    ${refs.length > 1 ? html`<button type="button" class="pop-item" onClick=${act(() => c.fieldWall(refs))}>${t.wall}</button>` : null}
    ${canName ? html`<button type="button" class="pop-item" onClick=${act(() => c.startRename('ws', w.ref))}>${t.rename}</button>` : null}
    ${canTab(s, 'close_workspace') ? html`<button type="button" class=${`pop-item is-danger${armed ? ' is-armed' : ''}`} onClick=${shut}>${armed ? t.closeAgain(refs.length) : t.closeWs}</button>` : null}`
}

/** The bar over a selection in the terminal: what the cockpit can do with words you marked */
export function SelectionBar({ sel, tab, s, c, slug, onClose }) {
  const t = T().tools
  const [others, setOthers] = useState(false)
  const done = fn => () => { fn(); onClose() }
  const tabs = (s.tabs?.tabs ?? []).filter(x => x.ref !== tab.ref && x.state !== 'needs-you')
  return html`<div class="selbar" style=${{ left: Math.max(8, sel.x), top: Math.max(8, sel.y - 40) }}>
    <button type="button" onClick=${done(() => c.copy(sel.text))}>${t.selCopy}</button>
    <button type="button" onClick=${done(() => c.askAbout(sel.text))}>${t.selAsk}</button>
    ${slug ? html`<button type="button" onClick=${done(() => c.act('note', { key: `task:${slug}`, text: sel.text.slice(0, 900) }))}>${t.selFile}</button>` : null}
    <button type="button" onClick=${() => setOthers(!others)}>${t.selChat}</button>
    ${others ? html`<div class="selbar-list">${tabs.map(x => html`<button type="button" key=${x.ref} onClick=${done(() => c.termKeys(x.ref, [{ paste: sel.text }]))}>${x.name}</button>`)}</div>` : null}
  </div>`
}

/** The keys a mouse reaches: each goes to the tab as if pressed */
export function KeyStrip({ tab, c, poke }) {
  const t = T().tools
  return html`<div class="key-strip" role="group" aria-label=${t.keys}>${CLICK_KEYS.map(([key, word]) => html`<button type="button" key=${key} class="key-cap"
    onClick=${() => { c.termKeys(tab.ref, [{ key }]); poke?.() }}>${word}</button>`)}</div>`
}

/** A long text in peace: it goes in whole with its lines, and Enter sends it */
export function WriteStrip({ tab, c, poke, onClose }) {
  const t = T().tools
  const [text, setText] = useState('')
  const field = useRef(null)
  useEffect(() => { field.current?.focus?.() }, [])
  const go = async () => {
    const v = text.trim()
    if (!v) return
    await c.termKeys(tab.ref, [{ paste: v }, { key: 'enter' }])
    poke?.()
    setText('')
    onClose()
  }
  return html`<div class="answer"><div class="answer-compose is-row"><textarea class="input" rows="3" ref=${field} aria-label=${t.write} placeholder=${t.writeHint} value=${text} onInput=${e => setText(e.currentTarget.value)}></textarea>
    <span class="btn-row"><${Btn} size="xs" variant="primary" icon="send" disabled=${!text.trim()} onClick=${go}>${T().guide.send}<//><${Btn} size="xs" variant="ghost" onClick=${onClose}>${T().guide.cancel}<//></span></div></div>`
}

/** The whole conversation over the screen, the newest at the end; a search asks the server, Older pages back */
export function HistoryPanel({ tab, c, onClose }) {
  const t = T().tools
  const [q, setQ] = useState('')
  const [data, setData] = useState(null)
  const [err, setErr] = useState(null)
  const body = useRef(null)
  const stick = useRef(true)
  useEffect(() => {
    let alive = true
    const id = setTimeout(async () => {
      const r = await c.tabHistory(tab.ref, q.trim())
      if (!alive) return
      if (r.ok) { setData(r.data); setErr(null); stick.current = true } else setErr(r.error?.message ?? '?')
    }, q ? 250 : 0)
    return () => { alive = false; clearTimeout(id) }
  }, [tab.ref, q])
  useLayoutEffect(() => { const el = body.current; if (el && stick.current) { el.scrollTop = el.scrollHeight; stick.current = false } }, [data])
  const older = async () => {
    const first = data.turns[0]?.i
    const r = await c.tabHistory(tab.ref, q.trim(), first)
    if (r.ok) setData({ ...r.data, turns: [...r.data.turns, ...data.turns] })
  }
  const mark = text => {
    const w = q.trim()
    if (!w) return text
    const lo = text.toLowerCase(), wl = w.toLowerCase(), out = []
    let at = 0
    for (let i = lo.indexOf(wl); i >= 0; i = lo.indexOf(wl, at)) { out.push(text.slice(at, i), html`<mark>${text.slice(i, i + w.length)}</mark>`); at = i + w.length }
    out.push(text.slice(at))
    return out
  }
  return html`<div class="hist" role="region" aria-label=${t.history}>
    <div class="hist-head"><input class="input" type="search" aria-label=${t.histSearch} placeholder=${t.histSearch} value=${q} onInput=${e => setQ(e.currentTarget.value)} />
      <${Btn} size="xs" variant="ghost" icon="close" label=${t.histClose} onClick=${onClose} /></div>
    <p class="hist-src muted small">${data ? (data.source === 'session' ? t.fromSession : t.fromTerminal) : t.histLoading}</p>
    <div class="hist-body" ref=${body}>
      ${err ? html`<p class="reply-note small">${err}</p>` : null}
      ${data?.more ?? data?.truncated ? html`<button type="button" class="btn-link small" onClick=${older}>${t.older}</button>` : null}
      ${(data?.turns ?? []).map(x => html`<div key=${x.i} class=${`hist-turn is-${x.role}`}>${mark(x.text)}</div>`)}
      ${data && !data.turns?.length ? html`<p class="muted small">${t.histNone}</p>` : null}
    </div>
  </div>`
}

/** Model, context and cost as the tab's status line names them; the model and the context open their commands */
export function StatusChips({ st, tab, s, c, poke }) {
  const t = T().tools
  const { pop, close, open } = usePop()
  if (!st) return null
  const free = tab.state === 'waiting' && !tab.ask?.draft && canTab(s, 'keys')
  const send = cmd => { close(); c.termKeys(tab.ref, [{ text: cmd }, { key: 'enter' }]); poke?.() }
  return html`<span class="chips-st">
    ${st.model ? html`<button type="button" class="st-chip st-model" disabled=${!free} title=${t.modelTitle} onClick=${open('model')}>${st.model}</button>` : null}
    ${st.context != null ? html`<button type="button" class=${`st-chip st-ctx${st.context >= 80 ? ' is-hot' : ''}`} disabled=${!free} title=${t.contextTitle(st.context)} onClick=${open('ctx')}>
      <i aria-hidden="true" style=${{ '--p': `${st.context}%` }}></i>${st.context} %</button>` : null}
    ${st.cost ? html`<span class="st-chip st-cost" title=${t.costTitle}>${st.cost}</span>` : null}
    ${pop?.name === 'model' ? html`<${Pop} at=${pop.at} onClose=${close}><h4 class="label-caps">${t.model}</h4>
      ${['haiku', 'sonnet', 'opus'].map(m => html`<button type="button" key=${m} class="pop-item" onClick=${() => send(`/model ${m}`)}>${m}</button>`)}
      <h4 class="label-caps">${t.effort}</h4>${['low', 'medium', 'high'].map(m => html`<button type="button" key=${m} class="pop-item" onClick=${() => send(`/effort ${m}`)}>${m}</button>`)}<//>` : null}
    ${pop?.name === 'ctx' ? html`<${Pop} at=${pop.at} onClose=${close}>
      <button type="button" class="pop-item" onClick=${() => send('/compact')}><code>/compact</code><span class="muted">${t.cmd.compact}</span></button>
      <button type="button" class="pop-item" onClick=${() => send('/branch')}><code>/branch</code><span class="muted">${t.cmd.branch}</span></button><//>` : null}
  </span>`
}
