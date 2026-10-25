// SPDX-License-Identifier: MIT
// The cockpit, the sessions and the background jobs pages.
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useState } from '../vendor/htm-preact-3.1.1.module.js'
import {
  duration, formatClock, indexRows, short, stateToken, agentLane, laneWindow, runToken, serious, scheduleText,
  dayNoteText, weekdayNames, filterWorkers, groupBySystem, stripMark, workerFacets, workerTone, aiGroups, previewText,
} from '../logic.js'
import { T, language } from '../text.js'
import { Skeleton } from './day.js'
import { TabControls } from './detail.js'
import { ReturnCard } from './home.js'
import { TabCard } from './tabs.js'
import { GuideBoard, GuideLine } from './guide.js'
import { StartControl, canStartControl } from './header.js'
import { Btn, Chip, CountNum, Dot, Empty, StateLine, useHits, useTween } from './parts.js'

// ---------------------------------------------------------------- sessions

/** What a session is doing, in one word: its tab's attention state wins over busy or idle */
function sessionState(x) {
  const tabState = x.tab?.state
  if (tabState === 'waiting' && x.tab?.idle) return ['idle', stateToken('idle')]   // finished: done, not waiting
  if (tabState === 'needs-you' || tabState === 'waiting') return [tabState, stateToken(tabState)]
  return [x.status, x.status === 'busy' ? 'success' : 'on-surface-muted']
}

/** One running subagent in the lane: it enters from the right edge and its bar reaches up to now */
function LaneBar({ a }) {
  const x0 = useTween(a.x0, { start: 1 })
  return html`<span class="lane-row"><span class=${`lane-bar${a.older ? ' is-older' : ''}`}
    style=${{ transform: `translateX(${(x0 * 100).toFixed(3)}%) scaleX(${Math.max(0.004, 1 - x0).toFixed(4)})` }}></span></span>`
}

/** The running subagents of a session over the last 10 to 60 minutes (laneWindow), one bar each, in the order of the list */
function AgentLane({ agents, now }) {
  const t = T()
  const span = laneWindow(agents, now)
  const lane = agentLane(agents, now, span)
  if (!lane.length) return null
  return html`<div class="lane" aria-hidden="true">
    ${lane.map(a => html`<${LaneBar} key=${a.id} a=${a} />`)}
    <span class="lane-axis mono"><span>${t.laneFrom(Math.round(span / 60000))}</span><span>${t.laneNow}</span></span>
  </div>`
}

export function SessionCard({ x, i = 0, s, c }) {
  const t = T()
  // the session list names its tab slim; the tab list has the rest (last line, filed result, settled)
  const tab = x.tab ? (s.tabs?.tabs ?? []).find(y => y.ref === x.tab.ref) ?? x.tab : null
  const [state, token] = sessionState(x)
  const title = x.tab?.name || x.name
  const jump = x.tab ? () => c.act('tab_jump', { tab_ref: x.tab.ref }) : null
  const agents = x.agents ?? { running: [], running_count: 0, done_recent: 0 }
  const busy = x.tab ? !!s.ui.busy[x.tab.ref] : false
  const newAgent = useHits(agents.running_count, (a, b) => b > a)
  const alert = useHits(state, (a, b) => b === 'needs-you')
  return html`<li class=${`sess row-in${state === 'needs-you' ? ' is-alert' : state === 'busy' ? ' is-busy' : ''}`} style=${{ '--i': Math.min(i, 12) }}>
    ${alert ? html`<span class="hit hit-alert" key=${`a${alert}`} aria-hidden="true"></span>` : null}
    ${newAgent ? html`<span class="hit" key=${`n${newAgent}`} aria-hidden="true"></span>` : null}
    <div class="sess-head">
      <${StateLine} token=${token} strong=${state === 'needs-you'} word=${t.sessionStatus[state] ?? state} />
      <span class="muted small">${t.sessionSince(duration(s.now - (x.since_ms || s.now)))}</span>
      ${x.tab?.is_control ? html`<span class="chip">${t.sessionControl}</span>` : null}
      ${x.remote ? html`<span class="chip" title=${t.sessionRemote}>claude.ai</span>` : null}
      ${x.relay ? html`<${Chip} token="success" title=${t.sessionRelayTitle}>${t.sessionRelay}<//>` : null}
    </div>
    ${x.tab?.is_control && !x.relay ? html`<p class="small"><${StateLine} token="warning" word=${t.sessionControlNoRelay} /></p>` : null}
    ${jump ? html`<button type="button" class="sess-title btn-link" title=${t.sessionJumpTitle(title)} onClick=${jump}>${short(title, 70)}</button>`
      : html`<span class="sess-title">${short(title, 70)}</span>`}
    <div class="sess-where muted small">
      ${x.tab ? html`<span>${x.tab.workspace}</span>` : html`<span>${t.sessionNoTab}</span>`}
      <span class="mono">${x.id}</span>
      <span>${t.sessionStarted(duration(s.now - (x.started_ms || s.now)))}</span>
    </div>
    ${agents.running_count || agents.done_recent ? html`<div class="sess-agents">
      ${agents.running_count ? html`<span class="sess-count is-on"><${CountNum} value=${agents.running_count} cls="mono" /> ${t.agentsWord(agents.running_count)}</span>` : null}
      ${agents.done_recent ? html`<span class="muted small">${t.agentsDone(agents.done_recent)}</span>` : null}
    </div>` : null}
    <${AgentLane} agents=${agents.running} now=${s.now} />
    ${agents.running.length ? html`<ul class="sess-agent-list">${agents.running.map(a => html`<li key=${a.id} class="row-in">
        <${Dot} token="success" pulse />
        <span class="mono small">${a.type}</span>
        <span class="sess-agent-desc">${a.description ?? ''}</span>
        <span class="muted small">${t.agentFor(duration(s.now - a.since_ms))}${a.background ? ` · ${t.agentBackground}` : ''}</span>
      </li>`)}${agents.running_count > agents.running.length ? html`<li class="muted small">${t.moreAgents(agents.running_count - agents.running.length)}</li>` : null}</ul>` : null}
    ${(x.workflows ?? []).map((w, i) => html`<div class="small" key=${i}><${StateLine} token="info" word=${t.workflowLine(w.name, w.agents)} /></div>`)}
    ${tab && previewText(tab.last) ? html`<p class="tab-last clamp2" title=${tab.last}>${previewText(tab.last)}</p>` : null}
    ${tab ? html`<${GuideLine} tab=${tab} s=${s} />` : null}
    ${tab?.settled ? html`<p class="small"><${StateLine} token="success" word=${t.tabSettled[tab.settled] ?? tab.settled} /></p>` : null}
    <div class="btn-row sess-foot">
      ${tab ? html`<${TabControls} tab=${tab} s=${s} c=${c} slim />`
        : jump ? html`<${Btn} size="xs" variant="secondary" busy=${busy} onClick=${jump}>${t.sessionJump}<//>` : null}
      <${SessionTask} x=${x} s=${s} c=${c} />
    </div>
  </li>`
}

/** The open tasks a session can belong to: every task row of the briefing and of the pages, by slug */
function openTasks(s) {
  const out = new Map()
  for (const r of indexRows(s.model).values()) if (r.task && !r.inbox_id && !out.has(r.task)) out.set(r.task, r.title)
  for (const p of s.model?.pages ?? []) for (const sec of p.sections ?? []) {
    if (sec.kind !== 'tasks') continue
    for (const it of sec.items ?? []) if (it.task && !out.has(it.task)) out.set(it.task, it.title)
  }
  return [...out].map(([slug, title]) => ({ slug, title })).sort((a, b) => a.slug.localeCompare(b.slug))
}

/** Which task a session works on: a task tab links itself, any other is linked here by hand */
function SessionTask({ x, s, c }) {
  const t = T()
  if (!x.sid) return null
  const tasks = openTasks(s)
  return html`<span class="sess-task small">
    ${x.task ? html`<span class="chip chip-task" title=${t.sessionTaskTitle}>${t.sessionTask(x.task)}</span>
      <button type="button" class="btn-link small" onClick=${() => c.act('session_unlink', { session: x.sid })}>${t.sessionUnlink}</button>`
      : html`<select class="input input-sm sess-task-pick" aria-label=${t.sessionLinkLabel} title=${t.sessionLinkLabel}
          onChange=${e => { const slug = e.currentTarget.value; if (slug) c.act('session_link', { session: x.sid, slug }) }}>
          <option value="">${t.sessionLinkLabel}</option>
          ${tasks.map(k => html`<option key=${k.slug} value=${k.slug}>${short(k.title || k.slug, 48)}</option>`)}
        </select>`}
  </span>`
}

/** A task's sessions: the live ones lead to their tab, an ended one goes on in a new tab (claude --resume) */
export function TaskSessions({ row, s, c }) {
  const t = T()
  if (!row.task) return null
  const links = (s.sessions?.links ?? []).filter(l => l.task === row.task)
  if (!links.length) return null
  const live = new Map((s.sessions?.sessions ?? []).map(x => [x.sid, x]))
  return html`<div class="sub-block">
    <h4 class="sub-title">${t.taskSessions(links.length)}</h4>
    <ul class="plain task-sessions">${links.slice(0, 6).map(l => {
      const x = live.get(l.sid)
      return html`<li key=${l.sid} class="row-in">
        <${StateLine} token=${x ? 'success' : 'on-surface-muted'} word=${x ? t.sessionLive : t.sessionEnded} />
        <span class="task-session-name">${short(l.name || l.sid.slice(0, 8), 60)}</span>
        ${x?.tab ? html`<${Btn} size="xs" variant="secondary" onClick=${() => c.act('tab_jump', { tab_ref: x.tab.ref })}>${t.btnToTab}<//>`
          : x ? null : html`<${Btn} size="xs" variant="secondary" busy=${!!s.ui.busy[row.key]} onClick=${() => c.act('session_resume', { session: l.sid })}>${t.sessionResume}<//>`}
      </li>`
    })}</ul>
  </div>`
}

/** What the AI was handed from the cockpit this week, by what it wants of you: done and to check (a
 *  settled one offers to close its tab), a question, at work, gone without a word. Older tabs that no
 *  start of the cockpit names stay below as sessions */
function AiReturns({ s, c }) {
  const t = T()
  const g = aiGroups(s.model?.returns, s.tabs?.tabs, s.now || Date.now())
  const order = ['check', 'asks', 'working', 'lost']
  // tabs whose item or task is settled without a start of the cockpit naming them: done as well
  const named = new Set((s.model?.returns ?? []).map(r => r.tab?.ref).filter(Boolean))
  const loose = (s.tabs?.tabs ?? []).filter(x => x.settled && x.state === 'waiting' && !x.is_control && !named.has(x.ref))
  const count = k => g[k].length + (k === 'check' ? loose.length : 0)
  if (!order.some(k => count(k))) return null
  return html`<section class="panel panel-pad psec ai-returns" aria-labelledby="ai-returns-title">
    <header class="psec-head"><h3 class="sec-title" id="ai-returns-title">${t.home.returnsTitle}</h3></header>
    ${order.filter(k => count(k)).map(k => html`<div class="ai-group" key=${k}>
      <h4 class="label-caps">${t.aiGroup[k]} <span class="sec-count mono">${count(k)}</span></h4>
      <div class="ai-cards">${g[k].map(r => html`<${ReturnCard} key=${r.key} r=${r} s=${s} c=${c} />`)}
        ${k === 'check' ? loose.map(x => html`<${TabCard} key=${x.ref} tab=${x} s=${s} c=${c} byKey=${indexRows(s.model)} />`) : null}</div>
    </div>`)}
  </section>`
}

/** Every running Claude Code session, grouped by project, this Bridge first */
export function SessionsPage({ s, c }) {
  const t = T()
  const list = s.sessions?.sessions ?? []
  const groups = []
  for (const x of list) {
    const g = groups.find(g => g.project === x.project && g.here === x.here)
    if (g) g.items.push(x)
    else groups.push({ project: x.project, here: x.here, items: [x] })
  }
  const busy = list.filter(x => x.status === 'busy').length
  const agents = list.reduce((n, x) => n + (x.agents?.running_count ?? 0), 0)
  return html`<div class="col col-page">
    <header class="page-head">
      <h2 class="detail-title">${t.sessionsTitle}</h2>
      <${StartControl} s=${s} c=${c} size="sm" />
    </header>
    ${list.length ? html`<dl class="stats" aria-label=${t.sessionsSummary(list.length, busy, agents)}>
      <div><dt>${t.statSessions}</dt><dd><${CountNum} value=${list.length} /></dd></div>
      <div><dt>${t.statBusy}</dt><dd><${CountNum} value=${busy} /></dd></div>
      <div><dt>${t.statAgents}</dt><dd><${CountNum} value=${agents} /></dd></div>
    </dl>` : null}
    ${canStartControl(s) ? html`<p class="sess-intro"><${StateLine} token="warning" word=${t.relayReason[s.relay.reason]} /></p>` : null}
    <p class="muted small sess-intro">${t.sessionsIntro}</p>
    <${GuideBoard} s=${s} c=${c} />
    <${AiReturns} s=${s} c=${c} />
    ${!list.length ? html`<div class="panel panel-pad"><${Empty}>${t.sessionsEmpty}<//></div>` : html`<div class="sess-groups">${groups.map(g => html`<section class="panel panel-pad psec" key=${`${g.here}/${g.project}`}
      style=${{ flex: `${g.items.length} 1 ${Math.min(g.items.length, 3) * 330}px` }}>
      <header class="psec-head"><h3 class="sec-title">${g.project}${g.here ? html` <span class="chip">${t.sessionHere}</span>` : null}
        <span class="sec-count mono">${g.items.length}</span></h3></header>
      <ul class="sess-grid">${g.items.map((x, i) => html`<${SessionCard} key=${x.pid} x=${x} i=${i} s=${s} c=${c} />`)}</ul>
    </section>`)}</div>`}
  </div>`
}

// ---------------------------------------------------------------- workers (workload view --json)

/** The run's day on a 24 hour line: its appointments as dots, the last recorded run as a triangle,
 *  now as a line. A run without appointments (a daemon, a watcher) says what it is instead */
function DayAxis({ day, nowPct }) {
  const marks = day?.marks ?? []
  if (!marks.length && day?.trace_pct == null) return html`<span class="dayaxis-note">${dayNoteText(day?.note, language())}</span>`
  return html`<span class="dayaxis" aria-hidden="true">
    <span class="dayaxis-line"></span>
    ${[25, 50, 75].map(q => html`<span class="dayaxis-q" key=${q} style=${{ '--p': q / 100 }}></span>`)}
    ${marks.slice(0, 48).map((m, i) => html`<span class="dayaxis-m" key=${i} title=${m.label} style=${{ '--p': (m.at_pct ?? 0) / 100 }}></span>`)}
    ${day?.trace_pct != null ? html`<span class="dayaxis-t" title=${dayNoteText(day.trace_label, language())} style=${{ '--p': day.trace_pct / 100 }}></span>` : null}
    <span class="dayaxis-now" style=${{ '--p': nowPct }}></span>
  </span>`
}

function RunStrip({ strip, continuous }) {
  const t = T()
  const last = (strip ?? []).slice(-14)
  if (!last.length) return html`<span class="muted small">${t.workerNoRuns}</span>`
  return html`<span class="strip" title=${continuous ? t.workerContinuous : t.workerStrip(last.length)}>
    ${last.map((e, i) => { const [shape, tone] = stripMark(e); return html`<span key=${i} class=${`strip-m sm-${tone}`} title=${`${e.at ?? ''} ${e.verdict ?? ''}`}>${shape}</span>` })}</span>`
}

function WorkerRow({ r, nowPct, c, i }) {
  const t = T()
  const [open, setOpen] = useState(false)
  const tone = workerTone(r)
  const top = (r.findings ?? []).find(serious) ?? (r.findings ?? [])[0]
  const days = weekdayNames(language())
  const week = r.week?.length === 7 ? [...r.week.slice(1), r.week[0]] : []
  return html`<li class=${`wrow rt-${tone} row-in${open ? ' is-open' : ''}`} style=${{ '--i': Math.min(i, 16) }}>
    <button type="button" class="wrow-main" aria-expanded=${String(open)} onClick=${() => setOpen(!open)}>
      <span class=${`rdot rdot-${tone}`} aria-hidden="true"></span>
      <span class="wrow-name"><strong>${r.title || r.id}</strong><span class="muted small">${r.purpose ?? ''}</span></span>
      <span class="wrow-when"><span class="small" title=${r.when ?? ''}>${scheduleText(r.when, language())}</span><${DayAxis} day=${r.day} nowPct=${nowPct} /></span>
      <span class="wrow-strip"><${RunStrip} strip=${r.strip} continuous=${r.continuous} /></span>
      <span class="wrow-state"><span class=${`chip chip-tk tk-${runToken(tone)}`}>
        <${Dot} token=${runToken(tone)} /><span>${t.workerState[r.state] ?? r.state}</span></span></span>
    </button>
    ${open ? html`<div class="wrow-detail">
      <dl class="wmeta">
        ${[['unit', r.unit], ['host', r.host], ['kind', t.workerKind[r.kind] ?? r.kind], ['runtime', r.runtime], ['sphere', r.sphere], ['owner', r.owner],
          ['program', r.program ? `${r.program}${r.program_where ? ` (${r.program_where})` : ''}` : ''], ['log', r.log]]
          .filter(([, v]) => v).map(([k, v]) => html`<div key=${k}><dt>${t.workerField[k]}</dt><dd class="mono small">${v}</dd></div>`)}
      </dl>
      ${week.length ? html`<div class="wweek" role="group" aria-label=${t.workerWeek}>${week.map((on, k) => html`<span key=${k} class=${`wday${on ? ' is-on' : ''}`}>${days[k]}</span>`)}
        ${(r.ran_days ?? []).length ? html`<span class="muted small">${t.workerRanDays(r.ran_days.length)}</span>` : null}</div>` : null}
      ${(r.findings ?? []).some(f => f.severity !== 'info') ? html`<ul class="wfind">${r.findings.filter(f => f.severity !== 'info').map((f, k) => html`<li key=${k}>
        <${StateLine} token=${f.severity === 'high' ? 'danger' : f.severity === 'medium' ? 'warning' : 'info'} strong=${f.severity === 'high'}
          word=${`${t.workerState[f.state] ?? f.state}: ${f.detail ?? ''}`} />
        ${f.hint ? html`<p class="muted small wfind-hint">${t.workerHint(f.hint)}</p>` : null}</li>`)}</ul>` : null}
      <div class="btn-row">
        <${Btn} size="xs" variant="secondary" onClick=${() => c.ask('free', { text: t.workerAsk(r.id, r.host, t.workerState[r.state] ?? r.state, top?.detail ?? '') })}>${t.btnAsk}<//>
      </div>
    </div>` : null}
  </li>`
}

/** Every declared run of the always-on machines, drawn by this page from `workload view --json` */
export function WorkersPage({ s, c }) {
  const t = T()
  const w = s.workers ?? {}
  useEffect(() => { c.loadWorkers() }, [s.model?.seq ?? 0])
  const [flt, setFlt] = useState(() => ({ q: '', kind: null, sphere: null, state: null, host: null, attention: false, ...(s.ui.workersFilter ?? {}) }))
  const view = w.data
  const runs = (view?.runs ?? []).filter(r => !r.retired)
  const shown = filterWorkers(runs, flt)
  const facets = workerFacets(runs, flt)
  const groups = groupBySystem(shown, view?.systems)
  const now = new Date()
  const nowPct = (now.getHours() * 60 + now.getMinutes()) / 1440
  const at = Date.parse(view?.generated_at ?? '')
  const set = patch => setFlt(f => ({ ...f, ...patch }))
  const facetRow = name => {
    const vals = Object.entries(facets[name] ?? {}).sort((a, b) => b[1] - a[1])
    if (vals.length < 2 && !flt[name]) return null
    return html`<div class="wfacet"><span class="label-caps">${t.workerFacet[name]}</span>
      <span class="fbar-chips">${vals.map(([v, n]) => html`<button type="button" key=${v} class=${`fchip${flt[name] === v ? ' is-on' : ''}`}
        aria-pressed=${String(flt[name] === v)} onClick=${() => set({ [name]: flt[name] === v ? null : v })}>
        ${name === 'state' ? html`<span class=${`fdot fdot-${workerTone({ state: v })}`} aria-hidden="true"></span>` : null}
        ${name === 'state' ? (t.workerState[v] ?? v) : name === 'kind' ? (t.workerKind[v] ?? v) : v} <span class="mono">${n}</span></button>`)}</span></div>`
  }
  return html`<div class="col col-page">
    <header class="page-head">
      <h2 class="detail-title">${t.workersTab}</h2>
      ${view ? html`<span class="muted small">${t.workersFrom(view.host, Number.isFinite(at) ? formatClock(at, language()).slice(0, 5) : '?')}</span>` : null}
      <button type="button" class="btn-link small" onClick=${() => c.loadWorkers()}>${t.reload}</button>
    </header>
    ${w.status === 'none' ? html`<div class="panel panel-pad"><p class="muted">${t.workersNone}</p></div>` : !view
      ? html`<div class="panel panel-pad"><${Skeleton} lines=${6} /></div>` : html`
      <dl class="stats">
        <div><dt>${t.workerStat.in_service}</dt><dd><${CountNum} value=${view.stats?.in_service ?? runs.length} /></dd></div>
        <div><dt>${t.workerStat.with_findings}</dt><dd><${CountNum} value=${view.stats?.with_findings ?? 0} /></dd></div>
        <div><dt>${t.workerStat.not_reported}</dt><dd><${CountNum} value=${view.stats?.not_reported ?? 0} /></dd></div>
        <div><dt>${t.workerStat.retired}</dt><dd><${CountNum} value=${view.stats?.retired ?? 0} /></dd></div>
      </dl>
      <section class="panel panel-pad wfilters">
        <div class="fbar">
          <input class="input fbar-q" type="search" placeholder=${t.filterSearch} aria-label=${t.filterSearch} value=${flt.q}
            onInput=${e => set({ q: e.currentTarget.value })} />
          <button type="button" class=${`fchip${flt.attention ? ' is-on' : ''}`} aria-pressed=${String(flt.attention)}
            onClick=${() => set({ attention: !flt.attention })}><span class="fdot fdot-warn" aria-hidden="true"></span>${t.workerAttention}</button>
          <span class="muted small">${t.workersShown(shown.length, runs.length)}</span>
        </div>
        ${['state', 'kind', 'sphere', 'host'].map(facetRow)}
      </section>
      ${!shown.length ? html`<div class="panel panel-pad"><${Empty}>${t.filterNone}<//></div>` : groups.map(g => {
        const n = k => g.runs.filter(r => workerTone(r) === k).length
        return html`<section class="panel panel-pad wgroup" key=${g.id}>
          <header class="rgroup-head"><h3 class="rgroup-title">${g.id === '_standalone' || !g.title ? t.workerAlone : g.id === '_undecided' ? t.workerUndecided : g.title}</h3>
            <span class="sec-count mono">${g.runs.length}</span>
            <span class="rgroup-count">${['ok', 'warn', 'bad', 'dim'].filter(k => n(k)).map(k => html`
              <span key=${k} class="rgroup-n"><span class=${`fdot fdot-${k}`} aria-hidden="true"></span><span class="mono">${n(k)}</span></span>`)}</span>
          </header>
          <ul class="wlist rview">${g.runs.map((r, i) => html`<${WorkerRow} key=${r.id} r=${r} i=${i} nowPct=${nowPct} c=${c} />`)}</ul>
        </section>`
      })}
      ${(view.elsewhere?.undeclared?.counted ?? 0) ? html`<p class="muted small">${t.workersElsewhere(view.elsewhere.undeclared.counted)}</p>` : null}`}
  </div>`
}
