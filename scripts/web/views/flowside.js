// SPDX-License-Identifier: MIT
// The cockpit, the columns around the middle of Work through (views/flow.js), laid out as cmux lays out a workspace.
// FlowSide, the left column as a table of contents, like a mail app's folders (round 5: it lists no point, the middle
// does). On top Running now as one row with its count (views/flowrun.js RunningRow: what runs is no point; a click shows
// its entries in the middle), at the foot Not now (views/flowleft.js NotNowBlock: the open rows that are no point now,
// by group), both on every side and in every mode. Between them Themes, Areas or Prio where two of them are on offer
// (logic.js flowModes, flowMode), then All themes (or All areas, All squares) and one entry per theme or area that holds
// a point (its colour, its name, how many need you in the warning tone, how many are open), No theme yet or No area
// last; a click enters it. Entered, the list stays the same with the one entered marked and All leads back. Under the
// list Order themes again (a regroup within the day's budget), what the themes run is doing, and Rename while a theme
// is entered. In Prio the list holds Jev's four squares (an empty one too) and Not rated yet, with when Jev ordered and
// Ask Jev again at its foot (views/flowprio.js PrioFoot). On a narrow screen the list is one select over the middle,
// Running now and Not now fold under it.
// FlowAside, the right column of an open point (round 3), as an issue tracker's sidebar: on top What you can do, the AI
// suggestion in one line (on an open point the only place it stands) and the card's verbs under each other, the strong
// one first, every other one in the same style (views/verbbar.js stack): a live tab (at work, asking, or waiting at its
// prompt, logic.js flowLive) gives To tab and View and neither Let AI do it nor Give your yes, a point in progress
// without one Let AI go on, a finished start the verb the AI suggests (else Done and close the tab), the other verbs,
// Improve, Runs on, Open answer and its tab's ways, a lost one Start again, Done, Drop and Forget, the return card Done,
// Later, Drop, Runs on and Not yet, the reports All seen.
// Under it the fields (logic.js flowFields): Theme (to change), Area, Who works on it, Prio (Jev's quadrant and rank,
// else the triage's rank, else the priority), Urgent, Important and Effort as small bars from Jev, Due, Source (its
// chip, STATUS.md to the files view, an issue or a pull request by its ref on the web), Created, Moved. No Status
// field: the card's head says it. In the overview a line says how they come.
// For the mouse: no text names a key.
// The rules every component keeps stand at the head of components.js.

import { html, useState } from '../vendor/htm-preact-3.1.1.module.js'
import {
  activityWhen, canTab, DAY, duration, errorText, flowAction, flowDriver, flowFields, flowLive, flowModes, flowSuggestion, flowTabOf,
  isoDate, meterLevel, refOfUrl, replySend, short,
} from '../logic.js'
import { T, language } from '../text.js'
import { OriginTag } from './day.js'
import { Segmented } from './detail.js'
import { NotNowBlock, NotNowNarrow } from './flowleft.js'
import { Suggestion } from './flowlist.js'
import { PrioFoot } from './flowprio.js'
import { RunningNarrow, RunningRow } from './flowrun.js'
import { TAB_MSG_MAX } from './nav.js'
import { Btn, PrioChip } from './parts.js'
import { VerbBar } from './verbbar.js'

/** The words of a side: its theme or area name, else All or None in the words of the mode */
export function sideName(side, mode) {
  const t = T().flow
  const f = t.side
  if (!side || side.id === 'all') return mode === 'themes' ? f.allThemes : mode === 'prio' ? f.allQuads : f.allAreas
  if (side.id === 'none') return mode === 'themes' ? f.noTheme : mode === 'prio' ? t.prio.none : f.noArea
  if (side.quadrant) return t.fields.quadrant[side.quadrant] ?? side.quadrant
  return side.name
}

/** The colour mark of a side: its terminal workspace's colour where it has one, else the tone of its name */
export const SideDot = ({ side }) => html`<span class=${`flow-side-dot tk-${side?.tone ?? 'muted'}`}
  style=${side?.color ? { '--ws-color': side.color } : undefined} aria-hidden="true"></span>`

/** Rename a theme a person picked: a field with Save; the name is a person's from then on (themes.py rename) */
function Rename({ theme, c, onDone }) {
  const f = T().flow.side
  const [name, setName] = useState(theme.name)
  const v = name.trim()
  const save = () => { if (v && v !== theme.name) c.flowThemeRename(theme.id, v); onDone() }
  return html`<form class="flow-side-rename" onSubmit=${e => { e.preventDefault(); save() }}>
    <label class="label-caps" for="flow-rename">${f.renameLabel}</label>
    <input id="flow-rename" class="input" type="text" maxlength="40" value=${name} onInput=${e => setName(e.currentTarget.value)} />
    <span class="verbbar-acts"><${Btn} size="xs" variant="primary" disabled=${!v} onClick=${save}>${f.save}<//>
      <${Btn} size="xs" variant="ghost" onClick=${onDone}>${f.cancel}<//></span>
  </form>`
}

/** The list of the left column, the same on both levels like a mail app's folders: All first (marked at the level
 *  of all, a click leads back to it), then the themes, areas or squares with their counts, the one entered marked
 *  while the middle shows it or one of its points (`marked`); a click enters one. The foot: Order themes again and,
 *  while a theme is entered, Rename it; in Prio Ask Jev again */
function SideList({ sides, entered, mode, points, marked, s, c }) {
  const f = T().flow.side
  const th = s.themes
  const [renaming, setRenaming] = useState(false)
  const keys = points.flatMap(x => (x.kind === 'reports' ? x.rows.map(r => r.key) : x.row?.key ? [x.row.key] : []))
  const busy = !!s.ui.flowThemesBusy || !!th?.running || !!s.ui.busy?.['flow:themes']
  const status = mode !== 'themes' ? null : busy ? f.ordering : th?.budget_left === 0 ? f.budget : th?.last_error ? f.failed : null
  const modes = flowModes(s)
  const word = { themes: f.themes, areas: f.areas, prio: f.prio }
  const on = id => marked && (entered?.id ?? 'all') === id
  const every = sides.find(x => x.id === 'all')
  return html`${modes.length > 1 ? html`<${Segmented} label=${f.label} values=${modes.map(m => [m, word[m]])} current=${mode}
      onPick=${v => c.flowMode(v)} />` : null}
    <ul class="flow-side-list flow-side-body">
      <li key="all"><button type="button" class=${`flow-side-item is-all${on('all') ? ' is-on' : ''}`} aria-current=${on('all') ? 'true' : undefined}
        onClick=${() => c.flowSide(null)}>
        <span class="flow-side-name"><span class="flow-side-label">${sideName(null, mode)}</span></span>
        <span class="flow-side-open mono muted" title=${f.open(every?.open ?? 0)}>${every?.open ?? 0}</span>
      </button></li>
      ${sides.filter(x => x.id !== 'all').map(x => html`<li key=${x.id}>
      <button type="button" class=${`flow-side-item${x.you ? ' is-you' : ''}${on(x.id) ? ' is-on' : ''}`} aria-current=${on(x.id) ? 'true' : undefined}
        title=${x.you ? f.asks : undefined} onClick=${() => c.flowSide(x.id)}>
        <${SideDot} side=${x} />
        <span class="flow-side-name"><span class="flow-side-label">${sideName(x, mode)}</span>
          ${x.you ? html`<span class="flow-side-you">${f.you(x.you)}</span>` : null}</span>
        <span class="flow-side-open mono muted" title=${f.open(x.open)}>${x.open}</span>
      </button></li>`)}</ul>
    ${mode === 'themes' ? html`<div class="flow-side-foot flow-side-body">
      <${Btn} size="xs" variant="secondary" icon="spark" busy=${busy} disabled=${!keys.length || th?.budget_left === 0}
        onClick=${() => c.flowThemes('regroup', keys.slice(0, 50))}>${f.regroup}<//>
      ${status ? html`<p class="muted small" role="status">${status}</p>` : null}
      ${entered?.theme ? renaming ? html`<${Rename} key=${entered.theme.id} theme=${entered.theme} c=${c} onDone=${() => setRenaming(false)} />`
        : html`<${Btn} size="xs" variant="ghost" onClick=${() => setRenaming(true)}>${f.rename}<//>` : null}
    </div>` : mode === 'prio' ? html`<${PrioFoot} s=${s} c=${c} />` : null}`
}

/** The left column, a table of contents (round 5): Running now as one row on top (views/flowrun.js RunningRow, the
 *  entries stand in the middle), the list of themes, areas or squares (logic.js flowSides) with the one entered
 *  marked, Not now at the foot; `lane` and `left` the page's (flowParts), `view` what the middle shows, `open` the
 *  group of Not now open there */
export function FlowSide({ sides, entered, mode, all, view, lane = [], left = null, run = null, open = null, s, c }) {
  const f = T().flow.side
  return html`<aside class="flow-side" aria-label=${f.label}>
    <label class="flow-side-select"><span class="sr-only">${f.pick}</span>
      <select class="input" value=${entered?.id ?? ''} onChange=${e => c.flowSide(e.currentTarget.value || null)}>
        <option value="">${sideName(null, mode)} (${sides[0]?.open ?? 0})</option>
        ${sides.filter(x => x.id !== 'all').map(x => html`<option key=${x.id} value=${x.id}>${sideName(x, mode)} (${x.open})</option>`)}
      </select></label>
    <${RunningNarrow} lane=${lane} s=${s} c=${c} on=${run} />
    <${NotNowNarrow} left=${left} open=${open} c=${c} />
    <${RunningRow} lane=${lane} on=${view === 'running' || view === 'run'} c=${c} />
    <${SideList} sides=${sides} entered=${entered} mode=${mode} points=${all} marked=${view === 'overview' || view === 'point'} s=${s} c=${c} />
    <${NotNowBlock} left=${left} open=${open} c=${c} />
  </aside>`
}

/** The theme of the point, by hand: another theme of the list, or a new one with a name of the person's. `compact`
 *  (a field of the right column) names it there, so the select carries its label for a screen reader only */
export function ThemePick({ row, s, c, compact = false }) {
  const f = T().flow.side
  const th = s.themes
  const [making, setMaking] = useState(false)
  const [name, setName] = useState('')
  const now = th?.assign?.[row.key] ?? ''
  const id = `flow-theme-${row.key}`
  if (making) {
    const v = name.trim()
    const save = () => { if (v) c.flowThemeNew(row.key, v); setMaking(false); setName('') }
    return html`<form class="flow-theme-pick" onSubmit=${e => { e.preventDefault(); save() }}>
      <label class="label-caps" for=${id}>${f.newName}</label>
      <input id=${id} class="input" type="text" maxlength="40" value=${name} onInput=${e => setName(e.currentTarget.value)} />
      <span class="verbbar-acts"><${Btn} size="xs" variant="primary" disabled=${!v} onClick=${save}>${f.save}<//>
        <${Btn} size="xs" variant="ghost" onClick=${() => setMaking(false)}>${f.cancel}<//></span>
    </form>`
  }
  return html`<div class=${`flow-theme-pick${compact ? ' is-compact' : ''}`}>
    <label class=${compact ? 'sr-only' : 'label-caps'} for=${id}>${f.moveLabel}</label>
    <span class="field-row"><select id=${id} class="input" value=${now} onChange=${e => {
      const v = e.currentTarget.value
      if (v === '+') setMaking(true)
      else if (v && v !== now) c.flowThemeMove(row.key, v)
    }}>
      ${now ? null : html`<option value="">${f.noTheme}</option>`}
      ${(th?.themes ?? []).map(x => html`<option key=${x.id} value=${x.id}>${x.name}</option>`)}
      <option value="+">${f.newTheme}</option>
    </select></span>
  </div>`
}

// the verbs on a card whose tab asks: no start, the tab takes no sentence while it asks (actions_work.py start_noted)
const ASKING_VERBS = ['advise', 'done', 'later', 'drop']

/** To tab and View for the tab of a point: the jump is remembered for the return card (c.flowJump). `strong`: the
 *  tab is live (logic.js flowLive), so To tab is the strong way; View always in the style of the stack */
export function TabWays({ tab, row, title, s, c, strong = false }) {
  const f = T().flow
  if (!tab || !flowDriver(s)) return null
  return html`<${Btn} size="sm" variant=${strong ? 'primary' : 'secondary'} onClick=${() => c.flowJump({ key: row?.key ?? null, ref: tab.ref, title: title ?? tab.name })}>${f.toTab}<//>
    <${Btn} size="sm" variant="secondary" onClick=${() => c.openTabView(tab.ref)}>${f.view}<//>`
}

/** Improve on a finished start: what is still to do, as words to the tab while its agent waits there (tab_send
 *  through the reply guard), else as the sentence of a new start (do_it, never without one) */
function Improve({ row, tab, s, c, onDone }) {
  const t = T()
  const f = t.flow.improve
  const [text, setText] = useState('')
  const [note, setNote] = useState(null)
  const busy = !!s.ui?.busy?.[tab ? tab.ref : row.key]
  const v = text.trim()
  const go = async () => {
    if (!v) return
    setNote(null)
    if (tab) {
      const { verb, args } = replySend(tab, v)
      const r = await c.reply(verb, args)
      if (r?.refused) { setNote(errorText(r.error, t)); return }
      if (!r?.ok) { if (r?.note) setNote(r.note); return }
    } else {
      const a = flowAction('do', row, v)
      if (!a || !(await c.act(a.verb, a.args))?.ok) return
      c.flowDecided()
    }
    setText('')
    onDone?.()
  }
  const id = `flow-improve-${row.key}`
  return html`<div class="flow-improve verbbar-panel">
    <label class="label-caps" for=${id}>${tab ? f.toTab : f.anew}</label>
    <textarea id=${id} class="input textarea" rows="2" maxlength=${TAB_MSG_MAX} value=${text} onInput=${e => setText(e.currentTarget.value)}></textarea>
    <div class="verbbar-acts">
      <${Btn} size="sm" variant="primary" busy=${busy} disabled=${!v} onClick=${go}>${tab ? f.send : f.restart}<//>
      ${note ? html`<span class="small verbbar-err" role="status">${note}</span>` : null}
    </div>
  </div>`
}

/** What a finished or quiet start offers, under each other in one style: the verb the AI suggests strong where it is
 *  Done, Later or Drop, else Done; Done closes its tab too where it has one (Done and close the tab); then the other
 *  two, Improve, Runs on, Open answer and the tab's ways. Whose item is not in the list: its tab's ways and Forget */
function FinishedActs({ x, s, c, sug, forget }) {
  const t = T()
  const f = t.flow
  const r = x.start
  const row = x.row
  const tab = x.tab
  const [fix, setFix] = useState(false)
  // words to the tab while its agent waits there, else a new start with them (a quiet tab is back at its shell)
  const live = !!tab && tab.state === 'waiting' && canTab(s, 'send')
  const tomorrow = isoDate((s.now || Date.now()) + DAY)
  if (!row) return html`<div class="fx-do"><${TabWays} tab=${tab} row=${null} title=${r.title} s=${s} c=${c} />${forget}</div>`
  const doneClose = async by => {
    const res = await c.act('settle', { keys: [row.key], outcome: 'done', ...(by ? { by } : {}) })
    if (res?.ok) await c.act('tab_close', { tab_ref: tab.ref })
    return res
  }
  const said = ['done', 'later', 'drop'].includes(sug?.verb) ? sug.verb : null
  const more = html`<${Btn} size="sm" variant="secondary" pressed=${fix} onClick=${() => setFix(!fix)}>${f.improve.button} ▾<//>
    <${Btn} size="sm" variant="secondary" onClick=${() => c.act('runs_on', { keys: [row.key], until: tomorrow })}>${f.runsOn}<//>
    ${r.result?.key ? html`<${Btn} size="sm" variant="secondary" onClick=${() => c.openItem(r.result.key, null)}>${t.home.returnOpenAnswer}<//>` : null}
    <${TabWays} tab=${tab} row=${row} title=${r.title} s=${s} c=${c} />`
  return html`<${VerbBar} row=${row} s=${s} c=${c} verbs=${['done', 'later', 'drop']} primary=${said ?? 'done'} suggested=${!!said}
      words=${tab ? { done: f.doneClose } : {}} handlers=${tab ? { done: doneClose } : {}} yes=${false} extra=${more} stack />
    ${fix ? html`<${Improve} row=${row} tab=${live ? tab : null} s=${s} c=${c} onDone=${() => setFix(false)} />` : null}`
}

/** The verbs of the point in front, by its card, under each other, the strong one first */
function PointActs({ x, s, c, sug }) {
  const t = T()
  const f = t.flow
  const row = x.kind === 'reports' ? null : x.row ?? null
  const live = flowLive(x, s)
  const tab = flowTabOf(x, s)
  const title = row?.title ?? x.title ?? x.start?.title ?? tab?.name ?? ''
  // a live tab, at work, asking or at its prompt: its ways first, To tab the strong one, and no second agent started
  // beside it (no Let AI do it, no Give your yes)
  const lead = live ? html`<div class="fx-do"><${TabWays} tab=${live} row=${row} title=${title} s=${s} c=${c} strong /></div>` : null
  const ways = tab && !live ? html`<${TabWays} tab=${tab} row=${row} title=${title} s=${s} c=${c} />` : null
  if (x.kind === 'reports') {
    const keys = x.rows.map(r => r.key)
    return html`<div class="fx-do"><${Btn} size="sm" variant="primary" busy=${!!s.ui.busy?.[keys.join(',')]}
      onClick=${() => c.act('settle', { keys, outcome: 'done' })}>${f.allSeen}<//></div>`
  }
  if (x.kind === 'back') {
    const back = () => c.flowBack()
    const rest = html`<${Btn} size="sm" variant="secondary" onClick=${back}>${f.runsOn}<//>
      <${Btn} size="sm" variant="secondary" onClick=${back}>${f.notYet}<//>`
    return row ? html`<${VerbBar} row=${row} s=${s} c=${c} verbs=${['done', 'later', 'drop']} primary="done" onDone=${back} extra=${rest} stack />`
      : html`<div class="fx-do">${rest}</div>`
  }
  // an entry of Running now: a session the cockpit linked or recognised can be told it works on something else
  const unlink = x.lane && x.kind === 'session' && x.session?.sid
    ? html`<${Btn} size="sm" variant="secondary" busy=${!!s.ui.busy?.session_unlink} onClick=${() => c.act('session_unlink', { session: x.session.sid })}>${f.run.unlink}<//>` : null
  if (x.group === 'doing') {
    if (!row) return html`${lead ?? (ways ? html`<div class="fx-do">${ways}</div>` : null)}${unlink ? html`<div class="fx-do">${unlink}</div>` : null}`
    // at work: Done, Later, Drop beside its tab; without an agent at work Let AI go on with it. The strong one: the way
    // to a live tab, else the verb the AI suggests where the card has it, else Let AI go on (Done while a start runs)
    const running = !!live || (x.kind === 'start' && ['started', 'working'].includes(x.stage))
    const verbs = running ? ['done', 'later', 'drop'] : ['do', 'done', 'later', 'drop']
    const said = verbs.includes(sug?.verb) ? sug.verb : null
    return html`${lead}<${VerbBar} row=${row} s=${s} c=${c} verbs=${verbs} primary=${live ? false : said ?? (running ? 'done' : 'do')} suggested=${!live && !!said}
      words=${running ? {} : { do: f.doing.goOn }} yes=${!running} extra=${html`${ways}${unlink}`} stack />`
  }
  if (x.kind === 'start') {
    const r = x.start
    const forget = html`<${Btn} size="sm" variant="secondary" onClick=${() => c.act('return_forget', { key: r.key })}>${t.home.returnForget}<//>`
    if (x.group === 'lost') {
      return row ? html`<${VerbBar} row=${row} s=${s} c=${c} verbs=${['do', 'done', 'drop']} primary="do" words=${{ do: f.verbs.restart }} extra=${forget} stack />`
        : html`<div class="fx-do">${forget}</div>`
    }
    if (x.group === 'result') return html`<${FinishedActs} x=${x} s=${s} c=${c} sug=${sug} forget=${forget} />`
    // a start whose tab asks: its ways, then the verbs that leave the tab its question
    return html`${lead}${row ? html`<${VerbBar} row=${row} s=${s} c=${c} verbs=${ASKING_VERBS} primary=${false} yes=${false} extra=${ways} stack />`
      : ways ? html`<div class="fx-do">${ways}</div>` : null}`
  }
  if (x.kind === 'tab') return html`${lead ?? (ways ? html`<div class="fx-do">${ways}</div>` : null)}${row
    ? html`<${VerbBar} row=${row} s=${s} c=${c} verbs=${ASKING_VERBS} primary=${false} yes=${false} stack />` : null}`
  // a question or a task: its verbs, the one the AI suggests the strong one where the card has it
  const verb = sug?.verb
  const primary = live ? false : ['do', 'done', 'later', 'drop'].includes(verb) ? verb : null
  return html`${lead}<${VerbBar} row=${row} s=${s} c=${c} verbs=${live ? ASKING_VERBS : null} primary=${primary} suggested=${!!primary} yes=${!live}
    extra=${ways} stack />`
}

/** Who works on a point, in words: its tab and how long, a start of the cockpit, a session by hand, else when it last
 *  moved (logic.js flowDrive) */
function whoWords(d, s) {
  const t = T()
  const f = t.flow.doing
  const nowMs = s.now || Date.now()
  const ago = d.since_ms ? duration(nowMs - d.since_ms) : null
  const word = f.stage[d.stage] ?? t.state[d.stage] ?? d.stage
  return d.by === 'tab' ? f.tab(d.tab.name, word, ago) : d.by === 'start' ? f.start(word, ago ?? '') : d.by === 'session'
    ? f.session(d.tab?.name ?? '', ago) : f.none(d.days)
}

/** A bar of Jev, 0 to 1, with its level in a word */
function Meter({ value }) {
  const f = T().flow.fields
  return html`<span class="flow-meter"><span class="meter-track" aria-hidden="true">
    <span class="meter-fill tk-info" style=${{ transform: `scaleX(${Math.max(0, Math.min(1, value)).toFixed(3)})` }}></span></span>
    <span>${f.level[meterLevel(value)]}</span></span>`
}

/** The fields of the point, like an issue tracker's sidebar (logic.js flowFields) */
function Fields({ x, s, c }) {
  const t = T()
  const f = t.flow.fields
  const lang = language()
  const row = x.kind === 'reports' ? null : x.row ?? null
  const feed = row ? s.details?.activity?.[row.key]?.data ?? null : null
  const detail = row?.task ? s.details?.task?.[row.task]?.data ?? null : null
  const none = html`<span class="muted">${f.none}</span>`
  // a link on the web by its ref where it is an issue or a pull request ("repo#12"), else by its address
  const link = href => html`<a href=${href} target="_blank" rel="noopener noreferrer" title=${href}>${refOfUrl(href) ?? short(String(href).replace(/^https?:\/\//, ''), 40)}</a>`
  const value = fld => {
    if (fld.id === 'theme') return html`<${ThemePick} key=${row.key} row=${row} s=${s} c=${c} compact />`
    if (fld.id === 'area') return fld.value || none
    if (fld.id === 'who') return whoWords(fld.drive, s)
    if (fld.id === 'prio') {
      if (fld.jev) return [fld.jev.quadrant ? f.quadrant[fld.jev.quadrant] ?? fld.jev.quadrant : null, fld.jev.rank ? f.jevPlace(fld.jev.rank) : null].filter(Boolean).join(' · ') || none
      if (fld.rank != null) return f.rank(fld.rank)
      return fld.priority ? html`<${PrioChip} priority=${fld.priority} />` : none
    }
    if (['urgency', 'impact', 'effort'].includes(fld.id)) return html`<${Meter} value=${fld.value} />`
    if (fld.id === 'due') return fld.value ? activityWhen(fld.value, lang) : none
    if (fld.id === 'source') {
      const rows = fld.rows ?? (fld.row ? [fld.row] : [])
      // the task's file opens in the files view, where its STATUS.md stands
      const slug = fld.row?.task ?? null
      if (!rows.length && !slug && !fld.url && !fld.link) return none
      return html`<span class="flow-source">${rows.map(r => html`<${OriginTag} key=${r.key} row=${r} />`)}
        ${slug ? html`<button type="button" class="btn-link flow-source-file" onClick=${() => c.openFile(slug, null)}>STATUS.md</button>` : null}
        ${fld.url ? link(fld.url) : null}${fld.link ? link(fld.link) : null}</span>`
    }
    if (fld.id === 'created' || fld.id === 'moved') return fld.value ? activityWhen(fld.value, lang) : none
    return none
  }
  return html`<section class="flow-fields flow-aside-part" aria-labelledby="flow-fields">
    <h3 id="flow-fields" class="label-caps">${f.label}</h3>
    <dl class="meta flow-meta">${flowFields(x, s, feed, detail).map(fld => html`<div class="meta-item" key=${fld.id} data-field=${fld.id}>
      <dt>${f[fld.id]}</dt><dd>${value(fld)}</dd></div>`)}</dl>
  </section>`
}

/** The right column: What you can do and the fields of the point open, or of the entry of Running now; in the overview
 *  a line how they come (`hint`: Prio's at its level of all squares, a list of Not now its own) */
export function FlowAside({ x, s, c, hint = null }) {
  const t = T()
  const f = t.flow
  if (!x) return html`<aside class="flow-aside" aria-label=${f.fields.label}>
    <section class="flow-aside-part"><p class="label-caps">${f.fields.label}</p><p class="muted small flow-aside-hint">${hint ?? f.fields.overview}</p></section>
  </aside>`
  const row = x.kind === 'reports' ? null : x.row ?? null
  const sug = row ? flowSuggestion(row, s) : null
  return html`<aside class="flow-aside" aria-label=${f.fields.can}>
    <section class="flow-can flow-aside-part" aria-labelledby="flow-can">
      <h3 id="flow-can" class="label-caps">${f.fields.can}</h3>
      ${sug ? html`<p class="flow-can-sug"><span class="label-caps">${f.list.cols.suggestion}</span> <${Suggestion} sug=${sug} s=${s} /></p>` : null}
      <${PointActs} key=${x.id} x=${x} s=${s} c=${c} sug=${sug} />
    </section>
    <${Fields} x=${x} s=${s} c=${c} />
  </aside>`
}
