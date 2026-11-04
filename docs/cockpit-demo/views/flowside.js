// SPDX-License-Identifier: MIT
// The cockpit, the columns around the middle of Work through (views/flow.js), laid out as cmux lays out a workspace.
// FlowSide, the left column as a table of contents, like a mail app's folders (round 5: it lists no point, the middle
// does). On top Running now as one row with its count (views/flowrun.js RunningRow: what runs is no point; a click shows
// its entries in the middle), under it Finished, to read (views/flowleft.js ReadRow, stage 2: the finished AI runs), at the foot Not now (views/flowleft.js NotNowBlock: the open rows that are no point now,
// by group), under it Check tasks (views/flowleft.js CheckRow, round 6 c: the task check in the middle), all on every
// side and in every mode. Between them Themes, Areas or Prio where two of them are on offer
// (logic.js flowModes, flowMode), then All themes (or All areas, All squares) and one entry per theme or area that holds
// a point (its colour, its name, how many need you in the warning tone, how many are open), No theme yet or No area
// last; a click enters it. Entered, the list stays the same with the one entered marked and All leads back. Under the
// list Order themes again (a regroup within the day's budget), Sort again where By source is off (the daily triage
// asked anew, in every order, round 6 B), what the themes run is doing, and Rename while a theme is entered. In Prio the list holds the four squares (an empty one too) and Not rated yet, with which ranker ordered when and
// Read in with Jev and Read in with Haiku at its foot (views/flowprio.js PrioFoot). On a narrow screen the list is one select over the middle,
// Running now and Not now fold under it.
// FlowAside, the right column of an open point (round 3; round 6 B: only while one is open), as an issue tracker's
// sidebar: on top What you can do, the AI suggestion in one line (on an open point the only place it stands; the task
// check's verdict counts as one), then the verbs under each other in one style (views/verbbar.js stack). Stage 1 of the
// one point view (04.11.2026): every point with a row offers the basic verbs in one order (logic.js basicVerbs: Let AI
// do it, Done, Later until, Drop because, Make it a task on an inbox item or an issue without a task), a verb that
// cannot go now stands off with why under them (an agent works on it, its tab asks, a stream, its yes given); strong is
// only what the AI suggests, as before (a task in review Done, a point in progress Let AI go on with it, the return card
// Done; else a finding's Give your yes where it brings an action; Advise never by itself, 29.10.2026), none while a live
// tab is on it. Under them what the point's kind adds, never in place of them: a live tab's To tab (then the strong
// way) and View, an issue's Open on GitHub and its board's moves (IssueWays), Give your yes, Advise, Improve on a task
// in review, the steps of a row with steps of its own on a page (an application, logic.js pageStepsOf, which open its
// Steps tab, stage 3, where they stand), Runs on on the return card, Not this task for a session, Show in the net for a
// task, Back on for a row of Later (as its list has it, logic.js leftPlan) and a tab already running on a task to
// assign to it (the detail column's Already running?, verb adopt);
// the tab's close (views/detail.js TabClose) apart at the end, and where that close ends the point itself Done in its
// place closes the tab too (Done and close the tab). A start that answered or went quiet, a lost one and a start whose
// tab asks keep their own verbs (FinishedActs: the verb the AI suggests, else Done and close the tab, then View, Open
// answer, Improve and Runs on; a lost one Start again, Done, Drop and Forget); a finished AI run to read (stage 2,
// ReadActs) Read, Analyse further and Make it a task; the reports Done for the ticked ones (All done when every one
// is), a tab alone its ways. A point that is closed (a point of its own, logic.js soloPoint) says
// so and offers nothing.
// Under it the fields (logic.js flowFields): Theme (to change), Area, Urgency (an inbox item's), Who works on it, Prio
// (Jev's quadrant and rank, else the triage's rank, else the priority), Urgent, Important and Effort as small bars from
// Jev, Due, Team and Task check (a task's), Source (its chip, the STATUS.md of the task an item belongs to, an issue or
// a pull request by its ref on the web), Created, Moved; no Status field, the card's head says it. Stage 3: what the
// detail column changed is changed in its field, a select as Theme is one: Area (an inbox item without a task, one of
// the configured areas or none, the owner's), Urgency (verb urgency) and a task's priority beside its Prio (verb
// priority), each through the server's verb as before, no undo as before; Team says how far a task's team is and
// starts its next role or a team that fits (verb team_role), Task check shows the verdict of the last check with Keep
// open and Check again (views/check.js ReviewBlock). Stage 1: at their foot Details ▾ folds open what the item drawer
// held beside them (logic.js pointFacts: an inbox item's kind, approval, who closes it, when it closes on its own,
// what runs on its yes, key and id; a task's type, blocker and file). Where Work through is off (the Files tab of
// a Bridge without it) the fold is the link Details under the verbs, which opens the row's drawer (an inbox item, a
// task) or its detail column (any other row), as before.
// For the mouse: no text names a key.
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useState } from '../vendor/htm-preact-3.1.1.module.js'
import {
  activityWhen, adoptStepOf, basicVerbs, canTab, DAY, rankerName, errorText, flowAction, flowDriver, flowFields, flowLive, flowModes,
  flowRunning, flowSettings, flowSuggestion, flowTabOf, formatDay, isoDate, leftPlan, meterLevel, pageStepsOf, pointFacts,
  pointViewOn, probeText, refOfUrl, replySend, reportsTicked, short, sinceText, tabCloseOffer, triageRunning, workPageOf, workViewsIn, personOf,
  fieldsSplit, pointName, whoBrief
} from '../logic.js'
import { T, language } from '../text.js'
import { ReviewBlock } from './check.js'
import { OriginTag } from './day.js'
import { Segmented, TabClose, TeamBlock } from './detail.js'
import { CheckRow, NotNowBlock, NotNowNarrow, ReadRow } from './flowleft.js'
import { Suggestion } from './flowlist.js'
import { PrioFoot } from './flowprio.js'
import { RunningNarrow, RunningRow } from './flowrun.js'
import { TAB_MSG_MAX } from './nav.js'
import { LaunchPick } from './launch.js'
import { Btn, PrioChip, WhoChip } from './parts.js'
import { VerbBar } from './verbbar.js'
import { OrderMenu, SimpleActs } from './flowsimple.js'

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
export function Rename({ theme, c, onDone }) {
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

/** Sort again: the daily triage asked anew for what changed (c.triageRun, small model, cents), the button By source
 *  carries in its strip (triage.js TriageBar). Only where a work page exists and By source is not on offer (round 6 B) */
export function Resort({ s, c }) {
  if (!workPageOf(s.model?.pages) || workViewsIn(s).includes('area')) return null
  return html`<${Btn} size="xs" variant="ghost" busy=${triageRunning(s)} title=${T().triage.rerunTitle}
    onClick=${() => c.triageRun(false)}>${T().flow.side.resort}<//>`
}

/** The list of the left column, the same on both levels like a mail app's folders: All first (marked at the level
 *  of all, a click leads back to it), then the themes, areas or squares with their counts, the one entered marked
 *  while the middle shows it or one of its points (`marked`); a click enters one. The foot: Order themes again,
 *  Sort again where By source is off (Resort, in every order) and, while a theme is entered, Rename it; in Prio Ask
 *  Jev again */
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
    ${pointViewOn(s) ? html`<${OrderMenu} mode=${mode} keys=${keys} busy=${busy} entered=${entered} naming=${renaming} setNaming=${setRenaming}
        status=${status} s=${s} c=${c} />`
    : mode === 'themes' ? html`<div class="flow-side-foot flow-side-body">
      <${Btn} size="xs" variant="secondary" icon="spark" busy=${busy} disabled=${!keys.length || th?.budget_left === 0}
        onClick=${() => c.flowThemes('regroup', keys.slice(0, 50))}>${f.regroup}<//>
      <${Resort} s=${s} c=${c} />
      ${status ? html`<p class="muted small" role="status">${status}</p>` : null}
      ${entered?.theme ? renaming ? html`<${Rename} key=${entered.theme.id} theme=${entered.theme} c=${c} onDone=${() => setRenaming(false)} />`
        : html`<${Btn} size="xs" variant="ghost" onClick=${() => setRenaming(true)}>${f.rename}<//>` : null}
    </div>` : html`${mode === 'prio' ? html`<${PrioFoot} s=${s} c=${c} />` : null}${Resort({ s, c }) ? html`<div class="flow-side-foot flow-side-body">
      <${Resort} s=${s} c=${c} /></div>` : null}`}`
}


/** The left column, a table of contents (round 5): Running now as one row on top (views/flowrun.js RunningRow, the
 *  entries stand in the middle), the list of themes, areas or squares (logic.js flowSides) with the one entered
 *  marked, Check tasks as a block of its own above Not now at the foot; `running` and `left` the page's (logic.js runningOf, flowParts), `view` what the middle shows, `open` the
 *  group of Not now open there */
export function FlowSide({ sides, entered, mode, all, view, running = null, left = null, run = null, open = null, read = [], s, c }) {
  const f = T().flow.side
  return html`<aside class="flow-side" aria-label=${f.label}>
    <label class="flow-side-select"><span class="sr-only">${f.pick}</span>
      <select class="input" value=${entered?.id ?? ''} onChange=${e => c.flowSide(e.currentTarget.value || null)}>
        <option value="">${sideName(null, mode)} (${sides[0]?.open ?? 0})</option>
        ${sides.filter(x => x.id !== 'all').map(x => html`<option key=${x.id} value=${x.id}>${sideName(x, mode)} (${x.open})</option>`)}
      </select></label>
    <${RunningNarrow} running=${running} s=${s} c=${c} on=${run} />
    <${NotNowNarrow} left=${left} open=${open} c=${c} />
    <${RunningRow} running=${running} on=${view === 'running' || view === 'run'} c=${c} />
    <${ReadRow} read=${read} on=${view === 'read' || view === 'readPoint'} c=${c} />
    <${SideList} sides=${sides} entered=${entered} mode=${mode} points=${all} marked=${view === 'overview' || view === 'point'} s=${s} c=${c} />
    ${personOf(s) ? null : html`<${CheckRow} s=${s} c=${c} on=${view === 'check'} />`}
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

// the verbs while a start's tab asks: nothing that closes or drops what waits for an answer; while it waits at its
// prompt also no start beside it (actions_work.py start_noted)
const ASKING_VERBS = ['advise', 'done', 'later', 'drop']
const ASKS_VERBS = ['advise', 'later']

/** To tab and View for the tab of a point: the jump is remembered for the return card (c.flowJump). `strong`: the
 *  tab is live (logic.js flowLive), so To tab is the strong way; View always in the style of the stack. Round 6d: then
 *  the one close of a tab (views/detail.js TabClose) while it neither works nor asks; `close` 'only' where the card's
 *  own Done closes the tab already, false for none */
export function TabWays({ tab, row, title, s, c, strong = false, close = true }) {
  const f = T().flow
  if (!tab || !flowDriver(s)) return null
  return html`<${Btn} size="sm" variant=${strong ? 'primary' : 'secondary'} onClick=${() => c.flowJump({ key: row?.key ?? null, ref: tab.ref, title: title ?? tab.name })}>${f.toTab}<//>
    <${Btn} size="sm" variant="secondary" onClick=${() => c.openTabView(tab.ref)}>${f.view}<//>
    ${close ? html`<${TabClose} tab=${tab} s=${s} c=${c} size="sm" only=${close === 'only'} />` : null}`
}

/** The verbs of a start beside its tab's close: where the close offers Done and close tab for this very row (what
 *  stands behind the tab is the row), Done leaves the bar, so one Done stands there */
function besideClose(verbs, row, tab, s) {
  const offer = row && tab ? tabCloseOffer(tab, s) : null
  return offer?.done && offer.keys.includes(row.key) ? verbs.filter(v => v !== 'done') : verbs
}

/** Improve on a finished start: what is still to do, as words to the tab while its agent waits there (tab_send
 *  through the reply guard), else as the sentence of a new start (do_it, never without one) */
export function Improve({ row, tab, s, c, onDone }) {
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
  // what stands behind the tab is this row: the server ends it and closes the tab in one (tab_done), else the row
  // settles and the tab closes after it
  const offer = tab ? tabCloseOffer(tab, s) : null
  const doneClose = async by => {
    if (offer?.done && offer.keys.includes(row.key)) return c.act('tab_done', { tab_ref: tab.ref, ...(by ? { by } : {}) })
    const res = await c.act('settle', { keys: [row.key], outcome: 'done', ...(by ? { by } : {}) })
    if (res?.ok) await c.act('tab_close', { tab_ref: tab.ref })
    return res
  }
  const said = ['done', 'later', 'drop'].includes(sug?.verb) ? sug.verb : null
  const ways = !!tab && !!flowDriver(s)
  // what checks the result comes right after Done: View, the answer, Improve, Runs on; the jump to the tab and its
  // close stand apart at the end
  const lead = html`${ways ? html`<${Btn} size="sm" variant="secondary" onClick=${() => c.openTabView(tab.ref)}>${f.view}<//>` : null}
    ${r.result?.key ? html`<${Btn} size="sm" variant="secondary" onClick=${() => c.openItem(r.result.key, null)}>${t.home.returnOpenAnswer}<//>` : null}
    <${Btn} size="sm" variant="secondary" pressed=${fix} onClick=${() => setFix(!fix)}>${f.improve.button} ▾<//>
    <${Btn} size="sm" variant="secondary" onClick=${() => c.act('runs_on', { keys: [row.key], until: tomorrow })}>${f.runsOn}<//>`
  const tail = ways ? html`<${Btn} size="sm" variant="secondary" onClick=${() => c.flowJump({ key: row.key, ref: tab.ref, title: pointName(row) || r.title })}>${f.toTab}<//>
    <${TabClose} tab=${tab} s=${s} c=${c} size="sm" only />` : null
  return html`<${VerbBar} row=${row} s=${s} c=${c} verbs=${['done', 'later', 'drop']} primary=${said ?? 'done'} suggested=${!!said}
      words=${tab ? { done: f.doneClose } : {}} handlers=${tab ? { done: doneClose } : {}} yes=${false} lead=${lead} tail=${tail} stack />
    ${fix ? html`<${Improve} row=${row} tab=${live ? tab : null} s=${s} c=${c} onDone=${() => setFix(false)} />` : null}`
}

// an issue on GitHub, not a pull request: the rows whose board an issue card reads (GET /api/issue)
export const GITHUB_ISSUE = row => /^[\w.-]+\/[\w.-]+#\d+$/.test(String(row?.ref ?? '')) && /^https:\/\/github\.com\/[^/]+\/[^/]+\/issues\/\d+/.test(String(row?.url ?? ''))

/** What Done on an issue does, board by board (issue_transition.py): the review comment and the review state first
 *  on every board that has review states while the issue is not in review there (K1), then the done state, then the
 *  close */
function doneSteps(boards, f) {
  const out = []
  for (const b of boards) {
    if (b.in_done) continue
    if (!b.in_review && b.review_state) out.push(f.comment, b.review_state)
    out.push(b.done_state)
  }
  return [...new Set(out), f.close]
}

/** An issue on a board of workflow/projects/ (GET /api/issue, issue_transition.py plan): its board and status, Set
 *  to review and Done, each opening its sentence first; Done says what the click will do and the board's rules above
 *  Confirm. Only a person's click writes (governance K1): the AI suggests, where it says close the button that fits
 *  is the strong one and its reason stands in the field already. Without a board only Hide, which the bar keeps */
export function IssueWays({ row, s, c, sug }) {
  const f = T().flow.issue
  const [plan, setPlan] = useState({ status: 'loading' })
  const [open, setOpen] = useState(null)
  const [text, setText] = useState('')
  const [round, setRound] = useState(0)
  const [fresh, setFresh] = useState(null)       // the check this click just made (issue_check)
  const [checking, setChecking] = useState(false)
  useEffect(() => {
    let live = true
    setPlan({ status: 'loading' })
    Promise.resolve(c.issuePlan(row.ref)).then(res => { if (live) setPlan(res?.ok ? { status: 'ok', data: res.data } : { status: 'error' }) })
    return () => { live = false }
  }, [row.ref, round])
  const data = plan.status === 'ok' ? plan.data : null
  const boards = data?.boards ?? []
  const on = plan.status === 'loading' ? f.loading : plan.status === 'error' ? f.failed : !boards.length ? f.none
    : boards.map(b => `${b.title}: ${b.status ?? f.noStatus}`).join(' · ')
  // a board of the issue that workflow/projects/ does not know keeps its status: the card names it
  const other = (data?.unmatched ?? []).map(u => u.title || `${u.owner} #${u.number}`)
  const head = html`<p class="muted small flow-issue-on">${on}</p>${boards.length && other.length ? html`<p class="muted small flow-issue-other">${f.other(other.join(', '))}</p>` : null}`
  if (!data || !boards.length) return head
  const canReview = boards.every(b => b.review_state) && !boards.some(b => b.in_review || b.in_done)
  const canDone = data.state === 'OPEN' && boards.every(b => b.done_state)
  // Check with AI (issue_check.py) outweighs the daily triage: its done makes the button that fits strong and puts its
  // comment in the field, its not done or unclear makes none strong
  const check = fresh ?? data.check ?? null
  const fits = canReview ? 'review' : canDone ? 'done' : null
  const strong = check ? (check.verdict === 'done' ? fits : null) : sug?.verb === 'done' ? fits : null
  const prefill = check?.verdict === 'done' ? check.comment || check.reason : sug?.reason
  const rules = [...new Set(boards.flatMap(b => b.rules ?? []))]
  const busy = !!s.ui?.busy?.[row.key]
  const pick = v => {
    setOpen(open === v ? null : v)
    setText(open !== v && strong === v && prefill ? prefill : '')
  }
  const go = async () => {
    const words = text.trim()
    const r = await c.act(open === 'review' ? 'issue_review' : 'issue_done', { key: row.key, ...(words ? { text: words } : {}) })
    // read the board again on every answer: a run that stopped part way changed it too
    setRound(round + 1)
    if (!r?.ok) return
    if (open === 'done') c.flowDecided()
    setOpen(null)
    setText('')
    setFresh(null)                               // the move changed the issue, the check spoke of the one before
  }
  const runCheck = async () => {
    setChecking(true)
    const r = await c.act('issue_check', { key: row.key })
    setChecking(false)
    if (r?.issue_check) setFresh(r.issue_check)
  }
  const id = `flow-issue-${row.key}`
  return html`${head}
    ${canReview ? html`<${Btn} size="sm" variant=${strong === 'review' ? 'primary' : 'secondary'} pressed=${open === 'review'} busy=${busy}
      onClick=${() => pick('review')}>${f.review} ▾<//>` : null}
    ${canDone ? html`<${Btn} size="sm" variant=${strong === 'done' ? 'primary' : 'secondary'} pressed=${open === 'done'} busy=${busy}
      onClick=${() => pick('done')}>${f.done} ▾<//>` : null}
    <${Btn} size="sm" variant="secondary" icon="spark" busy=${checking} onClick=${runCheck}>${checking ? f.checking : f.check}<//>
    ${check ? html`<div class=${`flow-issue-check is-${check.verdict}`} role="status">
      <p class="small"><strong>${f.verdict[check.verdict] ?? check.verdict}</strong>: ${check.reason}</p>
      ${(check.evidence ?? []).length ? html`<p class="muted small">${f.evidence}</p><ul class="small">${check.evidence.map(e => html`<li key=${e}>${e}</li>`)}</ul>` : null}
      ${(check.missing ?? []).length ? html`<p class="muted small">${f.missing}</p><ul class="small">${check.missing.map(e => html`<li key=${e}>${e}</li>`)}</ul>` : null}
      <p class="muted small">${f.by(String(check.model ?? '').replace(/^claude-/, ''), String(check.at ?? '').slice(0, 16).replace('T', ' '))}</p>
    </div>` : null}
    ${open ? html`<div class="verbbar-panel flow-issue-panel">
      <label class="label-caps" for=${id}>${open === 'review' ? f.reviewLabel : f.doneLabel}</label>
      <textarea id=${id} class="input textarea" rows="3" maxlength="2000" value=${text} onInput=${e => setText(e.currentTarget.value)}></textarea>
      <p class="muted small">${f.steps((open === 'review' ? [f.comment, boards[0].review_state] : doneSteps(boards, f)).join(', '))}</p>
      ${rules.length ? html`<p class="muted small">${f.rules(rules.join(', '))}</p>` : null}
      <div class="verbbar-acts">
        <${Btn} size="sm" variant="primary" busy=${busy} disabled=${open === 'review' && !text.trim()} onClick=${go}>${open === 'review' ? f.sendReview : f.confirmDone}<//>
        <${Btn} size="sm" variant="ghost" onClick=${() => { setOpen(null); setText('') }}>${f.cancel}<//>
      </div>
    </div>` : null}`
}

/** The verbs of a point with a row (stage 1, module head): the basic verbs in their one order, off with why where
 *  they cannot go, the strong one by today's rule; under them what the kind adds, the tab's close apart at the end */
function BasicActs({ x, row, s, c, sug }) {
  const t = T()
  const f = t.flow
  const [fix, setFix] = useState(false)
  // the return card asks how the tab went: its answers, not the tab's ways again
  const back = x.kind === 'back'
  const live = back ? null : flowLive(x, s)
  const tab = back ? null : flowTabOf(x, s)
  const near = live || tab
  const asks = live?.state === 'needs-you'
  const title = pointName(row) || x.title || x.start?.title || tab?.name || ''
  // a point in progress whose agent works: a live tab, or a start of the cockpit that runs
  const running = x.group === 'doing' && (!!live || (x.kind === 'start' && ['started', 'working'].includes(x.stage)))
  const adopt = adoptStepOf(row, s)
  const basic = basicVerbs(row, { live: !!live, asks, running, person: !!personOf(s), adopt })
  const off = Object.fromEntries(basic.filter(v => v.off).map(v => [v.id, v.off]))
  // the close of the tab behind it: where it ends this very row, Done in its place closes the tab as well
  const offer = near && !asks ? tabCloseOffer(near, s) : null
  const ends = !!offer?.done && offer.keys.includes(row.key)
  const review = !live && !!row.task && row.status === 'review' && x.group !== 'doing'
  const issue = !!row.ref && !row.task && !row.inbox_id
  const board = issue && !live && GITHUB_ISSUE(row)
  // strong only what the AI suggests (the board's button takes an issue's Done), as before: Done on a task in review
  // and on the return card, Let AI go on with it on a point in progress nobody works on; nothing beside a live tab
  const said = ['do', 'done', 'later', 'drop'].includes(sug?.verb) ? sug.verb : null
  const primary = live ? false : back ? 'done' : review ? said ?? 'done' : x.group === 'doing' ? said ?? (running ? 'done' : 'do')
    : board && said === 'done' ? false : said ?? false
  const words = { ...(issue ? { done: f.hide } : {}), ...(x.group === 'doing' && !running ? { do: f.doing.goOn } : {}), ...(ends ? { done: t.btnDoneCloseTab } : {}) }
  const handlers = ends ? { done: by => c.act('tab_done', { tab_ref: near.ref, ...(by ? { by } : {}) }) } : {}
  const toTask = basic.some(v => v.id === 'task') ? (row.inbox_id
    ? { what: f.basic.taskInbox, run: async () => { const r = await c.act('to_task', { key: row.key }); if (r?.ok && r.task) c.openItem(`task:${r.task}`); return r } }
    : { what: f.basic.taskIssue, run: () => c.act('row_action', { ...adopt, action: 'adopt' }) }) : null
  // what the kind adds: the tab's ways first (To tab the strong way while it lives), an issue's page and its board
  const ways = near && flowDriver(s) ? html`<${TabWays} tab=${near} row=${row} title=${title} s=${s} c=${c} strong=${!!live} close=${false} />` : null
  const web = issue && row.url ? html`<a class="btn btn-secondary btn-sm" href=${row.url} target="_blank" rel="noopener noreferrer">${f.onWeb(row.url)}</a>` : null
  const moves = board ? html`<${IssueWays} key=${row.key} row=${row} s=${s} c=${c} sug=${sug} />` : null
  const improve = review ? html`<${Btn} size="sm" variant="secondary" pressed=${fix} onClick=${() => setFix(!fix)}>${f.improve.button} ▾<//>` : null
  // a row with steps of its own on a page (an application): they stand in its Steps tab (stage 3), one click away
  const page = pageStepsOf(row, s)
  const steps = page ? html`<${Btn} size="sm" variant="secondary" onClick=${() => c.flowTab('steps')}>${t.rowSteps}<//>` : null
  // a row of Later comes back on from its point as from its list (logic.js leftPlan: by why it waits)
  const backOn = x.group === 'left' && x.left === 'later' && x.entry ? leftPlan([x.entry], 'back', s, '', language()) : null
  const back1 = backOn?.counts.back ? html`<${Btn} size="sm" variant="secondary" onClick=${async () => {
    if (backOn.early.length) c.flowEarly({ [row.key]: x.entry.until })
    if (backOn.calls.length) await c.flowBatch(backOn.calls, 'left')
  }}>${f.notnow.back}<//>` : null
  // a tab already running on a task, free in its area: assign it (the detail column's Already running?, verb adopt)
  const adopt1 = !personOf(s) && row.task && !row.inbox_id ? (row.adopt_candidates ?? []).map(a => html`<${Btn} key=${a.ref} size="sm" variant="secondary"
    busy=${!!s.ui.busy?.[row.key]} title=${t.adoptTitle} onClick=${() => c.act('adopt', { key: row.key, tab_ref: a.ref })}>${f.one.adopt(`${a.workspace} / ${a.name}`)}<//>`) : null
  const runsOn = back ? html`<${Btn} size="sm" variant="secondary" onClick=${() => c.flowBack()}>${f.runsOn}<//>` : null
  // an entry of Running now: a session the cockpit linked or recognised can be told it works on something else
  const unlink = x.lane && x.kind === 'session' && x.session?.sid
    ? html`<${Btn} size="sm" variant="secondary" busy=${!!s.ui.busy?.session_unlink} onClick=${() => c.act('session_unlink', { session: x.session.sid })}>${f.run.unlink}<//>` : null
  // the task in the net of the Bridge (the item drawer's Show in the net)
  const slug = row.task && !personOf(s) ? row.task : null
  const net = slug ? html`<${Btn} size="sm" variant="secondary" onClick=${() => c.openInner(`task:${slug}`)}>${f.one.net}<//>` : null
  const closer = offer ? html`<${TabClose} tab=${near} s=${s} c=${c} size="sm" only=${ends} />` : null
  return html`<${VerbBar} row=${row} s=${s} c=${c} fixed stack verbs=${[...basic.map(v => v.id), 'advise']} off=${off} primary=${primary}
      suggested=${!back && !!said && primary === said} words=${words} handlers=${handlers} toTask=${toTask} yes=${!live && !review && !running}
      yesFirst=${!primary} onDone=${back ? () => c.flowBack() : null} lead=${html`${ways}${web}${moves}${improve}`}
      extra=${html`${back1}${steps}${adopt1}${runsOn}${unlink}${net}`} tail=${closer} />
    ${fix ? html`<${Improve} row=${row} tab=${tab && tab.state === 'waiting' && canTab(s, 'send') ? tab : null} s=${s} c=${c} onDone=${() => setFix(false)} />` : null}`
}

/** The verbs of a finished AI run (stage 2), in this order: Read (strong: it leaves Finished, to read, verb
 *  return_read with its undo), Analyse further (a panel with the person's sentence, empty, and the model to start with;
 *  a new run on the same item with this run's result handed in, return_analyse, kept to max_running as Let AI do it
 *  is, off without a terminal driver), Make it a task (a panel: its title from the run's, the area, the result as the
 *  description and the run off the list afterwards, both ticked; return_task, then the new task opens in the same
 *  view). Later and Drop do not apply: the run's item ended. Under them the answer it filed, and the tab's close where
 *  its tab is still there */
function ReadActs({ x, s, c }) {
  const t = T()
  const f = t.flow
  const r = x.start
  const [open, setOpen] = useState(null)
  const [note, setNote] = useState('')
  const [crowd, setCrowd] = useState(0)
  // the new task's H1: the name the row is shown by, which the person may change
  const [title, setTitle] = useState((x.row?.key ? pointName(x.row) : null) || r.title || '')
  const areas = s.boot?.config?.areas ?? []
  const [area, setArea] = useState(() => areas.find(a => a.toLowerCase() === String(x.row?.area ?? '').toLowerCase()) ?? '')
  const [describe, setDescribe] = useState(true)
  const [close, setClose] = useState(true)
  const busy = !!s.ui.busy?.[r.key]
  const driver = flowDriver(s)
  const toggle = v => { setOpen(open === v ? null : v); setCrowd(0) }
  const analyse = async force => {
    const v = note.trim()
    if (!v) return
    const n = force ? 0 : flowRunning(s)
    if (n >= flowSettings(s).max_running) { setCrowd(n); return }
    setCrowd(0)
    const res = await c.act('return_analyse', { key: r.key, note: v })
    if (res?.ok) { setOpen(null); setNote(''); c.flowDecided() }
  }
  const makeTask = async () => {
    const res = await c.act('return_task', { key: r.key, title: title.trim(), ...(area ? { area } : {}), describe, close })
    if (res?.ok) { setOpen(null); if (res.task) c.openItem(`task:${res.task}`) }
  }
  const offer = x.tab ? tabCloseOffer(x.tab, s) : null
  const id = `read-${r.key}`
  return html`<div class="verbbar is-stack is-fixed" role="group" aria-label=${f.title}>
    <div class="verbbar-row verbbar-basic">
      <${Btn} size="sm" variant="primary" busy=${busy} onClick=${() => c.act('return_read', { key: r.key })}>${f.read.read}<//>
      <${Btn} size="sm" variant="secondary" pressed=${open === 'analyse'} disabled=${!driver} onClick=${() => toggle('analyse')}>${f.read.analyse} ▾<//>
      <${Btn} size="sm" variant="secondary" pressed=${open === 'task'} onClick=${() => toggle('task')}>${f.basic.task} ▾<//>
    </div>
    ${driver ? null : html`<div class="verbbar-off"><p class="muted small">${f.read.noDriver}</p></div>`}
    ${r.result?.key ? html`<div class="verbbar-row verbbar-kind">
      <${Btn} size="sm" variant="secondary" onClick=${() => c.openItem(r.result.key, null)}>${t.home.returnOpenAnswer}<//></div>` : null}
    ${offer ? html`<div class="verbbar-row verbbar-tail"><${TabClose} tab=${x.tab} s=${s} c=${c} size="sm" /></div>` : null}
    ${open === 'analyse' ? html`<div class="verbbar-panel">
      <label class="label-caps" for=${`${id}-note`}>${f.read.analyseLabel}</label>
      <textarea id=${`${id}-note`} class="input textarea" rows="3" maxlength="2000" value=${note} onInput=${e => setNote(e.currentTarget.value)}></textarea>
      <${LaunchPick} s=${s} c=${c} items=${[{ key: r.key, title: (x.row?.key ? pointName(x.row) : null) || r.title }]} />
      <p class="muted small">${f.read.analyseNote}</p>
      <div class="verbbar-acts"><${Btn} size="sm" variant="primary" busy=${busy} disabled=${!note.trim()} onClick=${() => analyse(false)}>${f.read.analyseGo}<//></div>
      ${crowd ? html`<div class="verbbar-acts" role="alert"><span class="small">${f.start.busy(crowd)}</span>
        <${Btn} size="sm" variant="secondary" busy=${busy} onClick=${() => analyse(true)}>${f.start.anyway}<//></div>` : null}
    </div>` : null}
    ${open === 'task' ? html`<div class="verbbar-panel">
      <label class="label-caps" for=${`${id}-title`}>${f.read.taskTitle}</label>
      <input id=${`${id}-title`} class="input" type="text" maxlength="200" value=${title} onInput=${e => setTitle(e.currentTarget.value)} />
      ${areas.length ? html`<label class="label-caps" for=${`${id}-area`}>${f.read.taskArea}</label>
        <select id=${`${id}-area`} class="input" value=${area} onChange=${e => setArea(e.currentTarget.value)}>
          <option value="">${f.read.noArea}</option>${areas.map(a => html`<option key=${a} value=${a}>${a}</option>`)}</select>` : null}
      <label class="flow-check"><input type="checkbox" checked=${describe} onClick=${() => setDescribe(!describe)} /><span>${f.read.taskDescribe}</span></label>
      <label class="flow-check"><input type="checkbox" checked=${close} onClick=${() => setClose(!close)} /><span>${f.read.taskClose}</span></label>
      <div class="verbbar-acts"><${Btn} size="sm" variant="primary" busy=${busy} disabled=${!title.trim()} onClick=${makeTask}>${f.read.taskGo}<//></div>
    </div>` : null}
  </div>`
}

/** The verbs of the point in front, by its card, under each other: the reports, a start (its own verbs), a tab alone
 *  (its ways), every other point the basic verbs and what its kind adds (BasicActs) */
function PointActs({ x, s, c, sug }) {
  const t = T()
  const f = t.flow
  const row = x.kind === 'reports' ? null : x.row ?? null
  const live = flowLive(x, s)
  const tab = flowTabOf(x, s)
  const title = (row ? pointName(row) : null) || x.title || x.start?.title || tab?.name || ''
  if (x.kind === 'reports') {
    // only the ticked reports, All seen only when every one is ticked; nothing ticked says how to tick
    const keys = reportsTicked(x, s.ui.flowPicked)
    const all = keys.length === x.rows.length
    return html`<div class="fx-do"><${Btn} size="sm" variant="primary" disabled=${!keys.length} busy=${!!s.ui.busy?.[keys.join(',')]}
      onClick=${() => { if (keys.length) c.act('settle', { keys, outcome: 'done' }) }}>${all ? f.allSeen : f.seenTicked(keys.length)}<//></div>
      ${keys.length ? null : html`<p class="muted small flow-reports-hint">${f.tickReports}</p>`}`
  }
  // a tab without a row (or an entry without one): its ways, its close with them; nothing else acts on it
  const lead = live ? html`<div class="fx-do"><${TabWays} tab=${live} row=${row} title=${title} s=${s} c=${c} strong close=${!row} /></div>` : null
  const ways = tab && !live ? html`<${TabWays} tab=${tab} row=${row} title=${title} s=${s} c=${c} close=${!row} />` : null
  const unlink = x.lane && x.kind === 'session' && x.session?.sid
    ? html`<${Btn} size="sm" variant="secondary" busy=${!!s.ui.busy?.session_unlink} onClick=${() => c.act('session_unlink', { session: x.session.sid })}>${f.run.unlink}<//>` : null
  // a finished AI run to read (stage 2): Read, Analyse further, Make it a task
  if (x.group === 'read') return html`<${ReadActs} key=${x.id} x=${x} s=${s} c=${c} />`
  if (x.kind === 'start' && !x.lane) {
    // a start keeps its own verbs
    const r = x.start
    const asks = live?.state === 'needs-you'
    const near = live || tab
    const offer = row && near && !asks ? tabCloseOffer(near, s) : null
    const ends = !!offer?.done && offer.keys.includes(row.key)
    const closer = offer ? html`<${TabClose} tab=${near} s=${s} c=${c} size="sm" />` : null
    const forget = html`<${Btn} size="sm" variant="secondary" onClick=${() => c.act('return_forget', { key: r.key })}>${t.home.returnForget}<//>`
    if (x.group === 'lost') {
      return row ? html`<${VerbBar} row=${row} s=${s} c=${c} verbs=${['do', 'done', 'drop']} primary="do" words=${{ do: f.verbs.restart }} extra=${forget} stack />`
        : html`<div class="fx-do">${forget}</div>`
    }
    if (x.group === 'result') return html`<${FinishedActs} x=${x} s=${s} c=${c} sug=${sug} forget=${forget} />`
    // a start whose tab asks: its ways, then the verbs that leave the tab its question
    return html`${lead}${row ? html`<${VerbBar} row=${row} s=${s} c=${c} verbs=${asks ? ASKS_VERBS : besideClose(ASKING_VERBS, row, near, s)} primary=${false}
      yes=${false} extra=${ways} first=${ends ? closer : null} tail=${ends ? null : closer} stack />` : ways ? html`<div class="fx-do">${ways}</div>` : null}`
  }
  // the return card of a tab without an item: its one way back
  if (x.kind === 'back' && !row) return html`<div class="fx-do"><${Btn} size="sm" variant="secondary" onClick=${() => c.flowBack()}>${f.runsOn}<//></div>`
  if (!row) return html`${lead ?? (ways ? html`<div class="fx-do">${ways}</div>` : null)}${unlink ? html`<div class="fx-do">${unlink}</div>` : null}`
  // stage 4: with Work through on, one strong button, the four states and More; off, the verbs as before
  if (pointViewOn(s)) return html`<${SimpleActs} key=${x.id} x=${x} row=${row} s=${s} c=${c} sug=${sug} />`
  return html`<${BasicActs} x=${x} row=${row} s=${s} c=${c} sug=${sug} />`
}

/** Who works on a point, in words: its tab and how long, a start of the cockpit, a session by hand, else when it last
 *  moved (logic.js flowDrive). Stage 2: a finished run names its day (AI run of <day>, finished), how long ago reads in
 *  days past a day (logic.js sinceText), and a stage the page has no word for never shows as its raw id */
function whoWords(d, s) {
  const t = T()
  const f = t.flow.doing
  const lang = language()
  const nowMs = s.now || Date.now()
  if (d.by === 'start' && d.stage === 'done' && Number.isFinite(d.since_ms)) return t.flow.read.run(formatDay(isoDate(d.since_ms), lang))
  const ago = d.since_ms ? sinceText(nowMs - d.since_ms, lang) : null
  const word = f.stage[d.stage] ?? t.state[d.stage] ?? ''
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

/** The facts the item drawer held beside the fields (stage 1, logic.js pointFacts), folded under Details at the foot
 *  of the fields: in words, a key, an id or a path as code */
function Facts({ x, item, detail, rest = [], value = null }) {
  const t = T()
  const f = t.flow.one
  const [open, setOpen] = useState(false)
  const facts = pointFacts(x, item, detail)
  if (!facts.length && !rest.length) return null
  const fw = t.flow.fields
  const word = fld => {
    if (fld.id === 'kind') return x.row?.inbox_id ? t.item.kindName[fld.value] ?? fld.value : String(fld.value)
    if (fld.id === 'urgency') return t.urgency[fld.value] ?? fld.value
    if (fld.id === 'gate') return t.gate[fld.value] ?? fld.value
    if (fld.id === 'closer') return fld.value ? t.item.closerKind[fld.value] ?? fld.value : fld.probe ? t.item.closerKind.probe : t.item.none
    if (fld.id === 'closes') return probeText(fld.value, t) ?? t.item.noProbe
    if (['runs', 'key', 'id', 'ref', 'file'].includes(fld.id)) return html`<code class="flow-fact-code">${fld.value}</code>`
    return String(fld.value)
  }
  return html`<button type="button" class="btn-link flow-facts-toggle" aria-expanded=${String(open)} aria-controls="flow-facts"
      onClick=${() => setOpen(!open)}>${f.details} ${open ? '▴' : '▾'}</button>
    ${open ? html`<dl id="flow-facts" class="meta flow-meta flow-facts">
      ${rest.map(fld => html`<div class="meta-item" key=${`f-${fld.id}`} data-field=${fld.id}><dt>${fw[fld.id]}</dt><dd>${fld.id === 'original'
        ? fld.value : value(fld)}</dd></div>`)}
      ${facts.map(fld => html`<div class="meta-item" key=${fld.id} data-fact=${fld.id}>
      <dt>${f.facts[fld.id]}</dt><dd>${word(fld)}</dd></div>`)}</dl>` : null}`
}

/** A field changed in place (stage 3, the detail column's pickers): a select named for a screen reader by its field,
 *  `none` the empty choice (an area taken back, or a value not set yet that cannot be picked again), the server's verb
 *  on a change (`onPick`), off while the row's verb runs */
function FieldPick({ label, value, choices, none = null, busy = false, onPick }) {
  const now = value ?? ''
  return html`<select class="input input-sm flow-field-pick" aria-label=${label} disabled=${busy} value=${now}
    onChange=${e => { const v = e.currentTarget.value; if (v !== now) onPick(v) }}>
    ${none ? html`<option value="" disabled=${!!none.off}>${none.word}</option>` : null}
    ${choices.map(([v, word]) => html`<option key=${v} value=${v}>${word}</option>`)}
  </select>`
}

/** The fields of the point, like an issue tracker's sidebar (logic.js flowFields); with the one point view (stage 1)
 *  the drawer's facts folded under Details at their foot */
function Fields({ x, s, c }) {
  const t = T()
  const f = t.flow.fields
  const lang = language()
  const one = pointViewOn(s)
  const row = x.kind === 'reports' ? null : x.row ?? null
  const feed = row ? s.details?.activity?.[row.key]?.data ?? null : null
  // a closed copy is read by its folder (the point's `file`), any other task by its slug
  const detail = row?.task ? s.details?.task?.[x.file ?? row.task]?.data ?? null : null
  const item = row?.inbox_id ? s.details?.inbox?.[row.inbox_id]?.data?.item ?? null : null
  const none = html`<span class="muted">${f.none}</span>`
  // a link on the web by its ref where it is an issue or a pull request ("repo#12"), else by its address
  const link = href => html`<a href=${href} target="_blank" rel="noopener noreferrer" title=${href}>${refOfUrl(href) ?? short(String(href).replace(/^https?:\/\//, ''), 40)}</a>`
  const busy = !!(row && s.ui.busy?.[row.key])
  const value = fld => {
    if (fld.id === 'theme') return html`<${ThemePick} key=${row.key} row=${row} s=${s} c=${c} compact />`
    if (fld.id === 'area') {
      if (!fld.edit) return fld.value || none
      // stage 3, the detail column's area: one of the configured areas, or none (verb area takes it back)
      const names = fld.value && !fld.edit.includes(fld.value) ? [...fld.edit, fld.value] : fld.edit
      return html`<${FieldPick} label=${f.area} value=${fld.value} none=${{ word: t.areaNone }} choices=${names.map(a => [a, a])} busy=${busy}
        onPick=${v => c.act('area', v ? { key: row.key, value: v } : { key: row.key })} />`
    }
    if (fld.id === 'when') {
      const word = fld.value ? t.urgency[fld.value] ?? fld.value : null
      if (!fld.edit) return word || none
      return html`<${FieldPick} label=${f.when} value=${fld.value} none=${fld.value ? null : { word: f.none, off: true }} busy=${busy}
        choices=${['now', 'today', 'later'].map(v => [v, t.urgency[v]])} onPick=${v => c.act('urgency', { key: row.key, value: v })} />`
    }
    // stage 4: who takes the step as a chip where nobody works on it, else who works on it
    if (fld.id === 'who') {
      if (one && fld.drive?.by === 'none' && fld.step?.who) return html`<${WhoChip} who=${fld.step.who} s=${s} />`
      // stage 4: who and its state in a few words, the whole line on hover
      const brief = one ? whoBrief(fld.drive, lang) : null
      return brief ? html`<span title=${whoWords(fld.drive, s)}>${brief}</span>` : whoWords(fld.drive, s)
    }
    if (fld.id === 'ask') return activityWhen(fld.value, lang)
    if (fld.id === 'prio') {
      // "only you" only where the ranker said so (who: me), never read off the square
      const said = fld.jev ? [fld.jev.quadrant ? f.quadrant[fld.jev.quadrant] ?? fld.jev.quadrant : null, fld.jev.who === 'me' ? f.onlyYou : null,
        fld.jev.rank ? f.jevPlace(fld.jev.rank, rankerName(fld.jev.ranker)) : null].filter(Boolean).join(' · ') : fld.rank != null ? f.rank(fld.rank) : ''
      // stage 3, the detail column's priority of a task, beside what Jev or the triage said
      if (fld.edit) {
        return html`<span class="flow-prio-edit">${said ? html`<span>${said}</span>` : null}<${FieldPick} label=${t.prioPrefix} value=${fld.priority}
          none=${fld.priority ? null : { word: f.none, off: true }} choices=${['P0', 'P1', 'P2', 'P3'].map(v => [v, v])} busy=${busy}
          onPick=${v => c.act('priority', { key: row.key, value: v })} /></span>`
      }
      if (said) return said
      return fld.priority ? html`<${PrioChip} priority=${fld.priority} />` : none
    }
    if (fld.id === 'team') return html`<${TeamBlock} row=${row} s=${s} c=${c} bare />`
    if (fld.id === 'check') return html`<${ReviewBlock} row=${row} s=${s} c=${c} bare />`
    if (['urgency', 'impact', 'effort'].includes(fld.id)) return html`<${Meter} value=${fld.value} />`
    if (fld.id === 'due') return fld.value ? activityWhen(fld.value, lang) : none
    if (fld.id === 'source') {
      const rows = fld.rows ?? (fld.row ? [fld.row] : [])
      // the task's file opens in the files view, where its STATUS.md stands; with the one point view the task an item
      // belongs to opens as its point, and a task's own file stands in Details, never a link to the point itself
      const slug = fld.row?.task && !(one && fld.row.key === `task:${fld.row.task}`) ? fld.row.task : null
      if (!rows.length && !slug && !fld.url && !fld.link) return none
      return html`<span class="flow-source">${rows.map(r => html`<${OriginTag} key=${r.key} row=${r} />`)}
        ${slug ? html`<button type="button" class="btn-link flow-source-file" onClick=${() => c.openFile(slug, null)}>STATUS.md</button>` : null}
        ${fld.url ? link(fld.url) : null}${fld.link ? link(fld.link) : null}</span>`
    }
    if (fld.id === 'created' || fld.id === 'moved') return fld.value ? activityWhen(fld.value, lang) : none
    return none
  }
  // stage 4: Theme, Area, Who and Due (or the day it asks again) on top, every other field folded under Details
  const all = flowFields(x, s, feed, detail)
  const { top, rest } = one ? fieldsSplit(all, x, s) : { top: all, rest: [] }
  return html`<section class="flow-fields flow-aside-part" aria-labelledby="flow-fields">
    <h3 id="flow-fields" class="label-caps">${f.label}</h3>
    <dl class="meta flow-meta">${top.map(fld => html`<div class="meta-item" key=${fld.id} data-field=${fld.id}>
      <dt>${f[fld.id]}</dt><dd>${value(fld)}</dd></div>`)}</dl>
    ${one ? html`<${Facts} key=${x.id} x=${x} item=${item} detail=${detail} rest=${rest} value=${value} />` : null}
  </section>`
}

/** Details of a row where Work through is off (the right column of a record in the Files tab): an inbox item or a
 *  task opens its drawer, any other row its detail column beside the page (Prio, area, urgency, take over a tab). With
 *  the one point view (stage 1) none: what the drawer held stands in the view itself */
const openDetails = (c, row) => (row.inbox_id || String(row.key).startsWith('task:') ? c.openItem(row.key, row) : c.peek(row.key, null))

/** The link Details under the verbs of a row (Work through off only) */
const DetailsLink = ({ row, c }) => html`<button type="button" class="btn-link flow-details" title=${T().flow.detailsTitle}
  onClick=${() => openDetails(c, row)}>${T().flow.details}</button>`

/** The right column: What you can do and the fields of the point open, or of the entry of Running now; nothing while
 *  none is open (round 6 B: no empty Fields card, the middle takes the width). A closed point says so in place of its
 *  verbs. Under the verbs Details only where Work through is off (module head). Stage 4: with Work through on the AI's
 *  suggestion is no line of its own (the point's stand says why, the strong button applies it) */
export function FlowAside({ x, s, c }) {
  const t = T()
  const f = t.flow
  if (!x) return null
  const row = x.kind === 'reports' ? null : x.row ?? null
  const sug = row && !x.readOnly ? flowSuggestion(row, s) : null
  return html`<aside class="flow-aside" aria-label=${f.fields.can}>
    <section class="flow-can flow-aside-part" aria-labelledby="flow-can">
      <h3 id="flow-can" class="label-caps">${f.fields.can}</h3>
      ${sug && !pointViewOn(s) ? html`<p class="flow-can-sug"><span class="label-caps">${f.list.cols.suggestion}</span> <${Suggestion} sug=${sug} s=${s} /></p>` : null}
      ${x.readOnly ? html`<p class="muted small flow-readonly">${f.one.readOnly}</p>` : html`<${PointActs} key=${x.id} x=${x} s=${s} c=${c} sug=${sug} />`}
      ${row?.key && !pointViewOn(s) ? html`<p class="flow-can-more"><${DetailsLink} row=${row} c=${c} /></p>` : null}
    </section>
    <${Fields} x=${x} s=${s} c=${c} />
  </aside>`
}
