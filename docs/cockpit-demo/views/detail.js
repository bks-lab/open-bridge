// SPDX-License-Identifier: MIT
// The cockpit, the center: overview and the detail of a row.
// The rules every component keeps stand at the head of components.js.

import { html, useEffect, useState } from '../vendor/htm-preact-3.1.1.module.js'
import {
  detailNeedsLoad, duration, formatDay, indexRows, short,
  stateToken, canTab, settledRefs, statusSplit, tabNextStep, areaScope, homeAreas,
  skipFixable, skipText, queueLiveKeys, queueView, dayQueue, tabStateKey
} from '../logic.js'
import { T, language } from '../text.js'
import { ReviewBlock } from './check.js'
import { KindTag, RowBar, Skeleton } from './day.js'
import { ReturnChip, ReturnPanel } from './home.js'
import { PageSection } from './pages.js'
import { Btn, SkipFix, Chip, Dot, Empty, LinkView, MarkChip, PrioChip, Spinner, StateLine, WalkBar } from './parts.js'
import { TaskSessions } from './sessions.js'

// ---------------------------------------------------------------- center: overview and detail

function Overview({ s, c }) {
  const t = T()
  const m = s.model
  if (!m) return html`<div class="panel panel-pad"><${Skeleton} lines=${6} /></div>`
  // under an area filter the count is the area's, as its line on the overview has it; the rest of the
  // headline (free time, what comes) is the day's
  const area = s.ui.area ? homeAreas(s.tabs?.tabs, m.sections, [], s.now || Date.now())
    .find(a => !a.none && a.name.toLowerCase() === s.ui.area.trim().toLowerCase()) : null
  const waiting = s.ui.area ? area?.waiting ?? 0 : m.briefing_badge ?? 0
  const head = html`
    <span class="eyebrow">${t.overviewTitle}</span>
    <h2 class="detail-title">${t.forYouNow(waiting)}${m.headline_rest ? ` · ${m.headline_rest}` : ''}</h2>
    ${m.since ? html`<p class="muted">${m.since}</p>` : null}`
  // the day (dates, status, what happened) stands here, with a work tab too: the overview on Start has none.
  // Under an area filter it keeps to the area as the rows beside it do (the star is the rows' own filter)
  const day = areaScope({ ...s, ui: { ...s.ui, pinnedOnly: false } })
  return html`<div class="panel panel-pad overview">${head}
    <${DayView} s=${day} c=${c} />
    <p class="hint muted">${t.detailEmpty}</p>
  </div>`
}

/** The day: dates, status, what is clear, what needs tidying, the workplace and the pages of group day.
 *  In the middle of Today as one panel, or on Start where a work tab exists as one card per block,
 *  where the pages of group day stand as a shelf of their own (DayPages) */
export function DayView({ s, c, cards = false }) {
  const t = T()
  const m = s.model
  if (!m) return html`<${Skeleton} lines=${6} />`
  const ex = m.extras ?? {}
  // the page that lists the proposed tabs, where they open one by one
  const wpPage = (m.pages ?? []).find(p => (p.sections ?? []).some(x => x.kind === 'workplace'))
  const blocks = [
    { id: 'agenda', title: t.agendaTitle, body: (m.agenda ?? []).length
      ? html`<ul class="agenda">${m.agenda.map((a, i) => html`<li key=${i}><span class="mono agenda-when">${a.when}</span><span>${a.title}</span></li>`)}</ul>`
      : html`<${Empty}>${t.empty}<//>` },
    { id: 'status', title: t.statusTitle, body: html`<${StatusList} rows=${m.status} s=${s} c=${c} />` },
    (ex.clear ?? []).length ? { id: 'clear', title: t.clearTitle,
      body: html`<ul class="plain">${ex.clear.map((x, i) => html`<li key=${i}><${StateLine} token="success" word=${x} /></li>`)}</ul>` } : null,
    (ex.hygiene ?? []).length ? { id: 'hygiene', title: t.hygieneTitle,
      body: html`<ul class="plain">${ex.hygiene.map((x, i) => html`<li key=${i}><${StateLine} token="warning" word=${x} /></li>`)}</ul>` } : null,
    ex.workplace ? { id: 'workplace', title: t.workplaceTitle,
      body: html`<p class="row-in">${ex.workplace.replace(/\s*\S+\?$/, '')}
        ${wpPage ? html`<${Btn} size="xs" variant="secondary" onClick=${() => c.setPage(wpPage.id)}>${t.workplaceOpen}<//>` : null}</p>` } : null,
  ].filter(Boolean)
  if (cards) {
    return blocks.map(b => html`<article key=${b.id} class=${`hcard day-card day-${b.id}`}>
      <div class="hcard-body"><h3 class="label-caps day-card-title">${b.title}</h3>${b.body}</div>
    </article>`)
  }
  const [agenda, status, ...rest] = blocks
  return html`<div class="day-view">
    ${s.ui?.area ? html`<p class="muted small">${t.allAreas}</p>` : null}
    <div class="ov-grid">
      <div class="ov-block"><h3 class="label-caps">${agenda.title}</h3>${agenda.body}</div>
      <div class="ov-block"><h3 class="label-caps">${status.title}</h3>${status.body}</div>
    </div>
    ${rest.map(b => html`<div key=${b.id} class="ov-block"><h3 class="label-caps">${b.title}</h3>${b.body}</div>`)}
    <${DayPages} s=${s} c=${c} />
  </div>`
}

/** The pages of group day (what happened today), one section each */
export function DayPages({ s, c, shelf = false }) {
  return (s.model?.pages ?? []).filter(p => p.group === 'day').map(p => html`<section key=${p.id}
    class=${shelf ? 'home-shelf day-more' : 'day-more'} aria-label=${p.title}>
    ${shelf ? html`<header class="home-shelf-head"><h2 class="home-shelf-title">${p.title}</h2></header>`
      : html`<h3 class="label-caps day-more-title">${p.title}</h3>`}
    ${(p.sections ?? []).map(sec => html`<${PageSection} key=${sec.id} page=${p} section=${sec} s=${s} c=${c} />`)}
  </section>`)
}

/** Status rows: failures and counts in view, the quiet ones (healthy, nothing to count) under one line */
function StatusList({ rows, s, c }) {
  const t = T()
  const { loud, quiet } = statusSplit(rows)
  const line = (x, i) => html`<li key=${i} title=${x.reason ?? undefined}>
    <${StateLine} token=${x.tone === 'neutral' ? 'on-surface-muted' : x.tone} strong=${x.tone === 'danger'} word=${x.title} />
    <span class="mono muted">${x.state === 'error' ? (x.reason || t.tone.bad) : x.state === 'skipped' ? skipText(x, t) : x.count}</span>
    ${c && skipFixable(x) ? html`<${SkipFix} s=${s} c=${c} title=${x.title} reason=${x.reason} />` : null}</li>`
  return html`<ul class="status-list">${loud.map(line)}</ul>
    ${quiet.length ? html`<details class="status-quiet">
      <summary class="muted">${t.statusQuiet(quiet.length)}</summary>
      <ul class="status-list">${quiet.map(line)}</ul>
    </details>` : null}`
}

function MetaList({ row, s }) {
  const t = T()
  // a source is a section id: its title on the dashboard's pages names it in words
  const titles = new Map((s?.model?.pages ?? []).flatMap(p => p.sections ?? []).map(x => [x.id, x.title]))
  const items = [
    ['bucket', row.bucket ? (t.bucket[row.bucket] ?? row.bucket) : null],
    ['section', row.section ? (t.section[row.section] ?? row.section) : null],
    ['gate', row.gate ? (t.gate[row.gate] ?? row.gate) : null],
    ['urgency', row.urgency ? (t.urgency[row.urgency] ?? row.urgency) : null],
    ['priority', row.priority],
    ['area', row.area],
    ['task_type', row.task_type],
    ['due', row.due ? formatDay(row.due, language(), true) : null],
    ['ref', row.ref],
    ['state', row.inbox_state ? (t.item.stateName[row.inbox_state] ?? row.inbox_state) : null],
    ['sources', (row.sources ?? []).map(x => titles.get(x) ?? x).join(', ') || null],
  ].filter(([, v]) => v)
  return html`<dl class="meta">${items.map(([k, v]) => html`<div class="meta-item" key=${k}><dt>${t.meta[k]}</dt><dd>${v}</dd></div>`)}</dl>`
}

export function Segmented({ label, values, current, onPick, busy }) {
  return html`<div class="seg" role="group" aria-label=${label}>
    ${values.map(([v, word]) => html`<button type="button" key=${v} class=${`seg-btn${current === v ? ' is-on' : ''}`}
      aria-pressed=${String(current === v)} disabled=${busy} onClick=${() => current !== v && onPick(v)}>${word}</button>`)}
  </div>`
}

function TeamBlock({ row, s, c }) {
  const t = T()
  const teams = s.model?.teams ?? []
  const busy = !!s.ui.busy[row.key]
  if (row.inbox_id || !row.task) return null
  const team = row.team ? teams.find(x => x.id === row.team.team_id) : null
  const suggestions = (row.team_suggestions ?? []).map(id => teams.find(x => x.id === id)).filter(Boolean)
  if (!team && !suggestions.length) return null
  return html`<div class="block">
    <h3 class="label-caps">${t.teamTitle}</h3>
    ${team ? html`<div class="team-state">
      <span>${t.teamProgress(team.label, row.team.started, team.roles.length)}</span>
      <ol class="roles">${team.roles.map((r, i) => html`<li key=${r.id} class=${i < row.team.started ? 'is-done' : ''}>
        <${Dot} token=${i < row.team.started ? 'success' : 'on-surface-muted'} /><span>${r.name}</span><span class="muted mono">${r.mode}</span></li>`)}</ol>
      ${row.team.next_role
        ? row.team.ready
          ? html`<${Btn} size="xs" variant="primary" busy=${busy} onClick=${() => c.act('team_role', { key: row.key, team: team.id })}>${t.teamNext(row.team.next_role.name)}<//>`
          : html`<p class="muted">${t.waitsForRole(row.team.waiting_for ?? row.team.next_role.name)}</p>`
        : html`<p class="muted">${t.allRolesStarted}</p>`}
    </div>` : null}
    ${suggestions.length ? html`<div class="btn-row">${suggestions.filter(x => !team || x.id !== team.id).map(x => html`
      <${Btn} key=${x.id} size="xs" busy=${busy} title=${x.roles.map(r => r.name).join(', ')}
        onClick=${() => c.act('team_role', { key: row.key, team: x.id })}>${t.teamStart(x.label)}<//>`)}</div>` : null}
  </div>`
}

function ActionsBlock({ row, s, c }) {
  const t = T()
  const busy = !!s.ui.busy[row.key]
  return html`<div class="block block-actions">
    <h3 class="label-caps">${t.actionsTitle}</h3>
    <div class="btn-row"><${RowBar} row=${row} s=${s} c=${c} /></div>
    ${row.task && !row.inbox_id ? html`<${ReviewBlock} row=${row} s=${s} c=${c} />` : null}
    ${row.task && !row.inbox_id ? html`<${TaskSessions} row=${row} s=${s} c=${c} />` : null}
    ${row.inbox_id ? html`<div class="sub-block">
      <h4 class="sub-title">${t.urgencyPrefix}</h4>
      <${Segmented} label=${t.urgencyPrefix} busy=${busy} current=${row.urgency}
        values=${['now', 'today', 'later'].map(v => [v, t.urgency[v]])} onPick=${v => c.act('urgency', { key: row.key, value: v })} />
    </div>` : row.task ? html`<div class="sub-block">
      <h4 class="sub-title">${t.prioPrefix}</h4>
      <${Segmented} label=${t.prioPrefix} busy=${busy} current=${row.priority}
        values=${['P0', 'P1', 'P2', 'P3'].map(v => [v, v])} onPick=${v => c.act('priority', { key: row.key, value: v })} />
    </div>` : null}
    ${(row.adopt_candidates ?? []).length ? html`<div class="sub-block">
      <h4 class="sub-title">${t.adoptTitle}</h4>
      <div class="btn-row">${row.adopt_candidates.map(a => html`<${Btn} key=${a.ref} size="xs" busy=${busy}
        onClick=${() => c.act('adopt', { key: row.key, tab_ref: a.ref })}>${a.workspace} / ${a.name}<//>`)}</div>
    </div>` : null}
  </div>`
}

export function TabControls({ tab, s, c, compact = false, slim = false }) {
  const t = T()
  const busy = !!s.ui.busy[tab.ref]
  const open = s.ui.openMsg === tab.ref
  const [text, setText] = useState('')
  const send = async () => {
    const v = text.trim()
    if (!v) return
    const r = await c.act('tab_send', { tab_ref: tab.ref, text: v })
    if (r) {
      setText('')
      c.setOpenMsg(null)
    }
  }
  const id = `msg-${tab.ref}`
  const settled = !!tab.settled || settledRefs(s.model?.returns, s.tabs?.tabs, s.now || Date.now()).has(tab.ref)
  if (slim) {
    const step = {
      yes: () => html`<${Btn} size="xs" variant="primary" busy=${busy} onClick=${() => c.act('tab_yes', { tab_ref: tab.ref })}>${t.btnYes}<//>`,
      no: () => html`<${Btn} size="xs" variant="secondary" busy=${busy} onClick=${() => c.act('tab_no', { tab_ref: tab.ref })}>${t.btnNo}<//>`,
      go_on: () => html`<${Btn} size="xs" variant="secondary" busy=${busy} onClick=${() => c.act('tab_go_on', { tab_ref: tab.ref })}>${t.btnGoOn}<//>`,
      close: () => html`<${Btn} size="xs" variant="secondary" busy=${busy} onClick=${() => c.act('tab_close', { tab_ref: tab.ref })}>${t.btnCloseTab}<//>`,
      jump: () => html`<${Btn} size="xs" variant="ghost" busy=${busy} onClick=${() => c.act('tab_jump', { tab_ref: tab.ref })}>${t.btnToTab}<//>`,
      view: () => html`<${Btn} size="xs" variant="ghost" onClick=${() => c.openTabView(tab.ref)}>${t.btnTabView}<//>`,
    }
    return tabNextStep(tab, v => canTab(s, v), settled).map(k => step[k]())
  }
  return html`<div class="tab-ctl">
    <div class="btn-row">
      ${tab.state === 'needs-you' && canTab(s, 'key') ? html`
        <${Btn} size="xs" variant="primary" busy=${busy} onClick=${() => c.act('tab_yes', { tab_ref: tab.ref })}>${t.btnYes}<//>
        <${Btn} size="xs" variant="secondary" busy=${busy} onClick=${() => c.act('tab_no', { tab_ref: tab.ref })}>${t.btnNo}<//>` : null}
      ${tab.state === 'waiting' && !tab.filed_by && !settled && !tab.is_control ? html`<${Btn} size="xs" variant="secondary" busy=${busy}
        onClick=${() => c.act('tab_go_on', { tab_ref: tab.ref })}>${t.btnGoOn}<//>` : null}
      ${tab.state === 'waiting' && (tab.filed_by || settled) && !tab.is_control && canTab(s, 'close') ? html`<${Btn} size="xs" variant="secondary" busy=${busy}
        onClick=${() => c.act('tab_close', { tab_ref: tab.ref })}>${t.btnCloseTab}<//>` : null}
      ${canTab(s, 'focus') ? html`<${Btn} size="xs" variant="ghost" busy=${busy} onClick=${() => c.act('tab_jump', { tab_ref: tab.ref })}>${t.btnToTab}<//>` : null}
      ${canTab(s, 'screen') ? html`<${Btn} size="xs" variant="ghost" onClick=${() => c.openTabView(tab.ref)}>${t.btnTabView}<//>` : null}
      ${tab.live ? html`<${Btn} size="xs" variant="ghost" pressed=${open} onClick=${() => c.setOpenMsg(open ? null : tab.ref)}>${t.btnMessage}<//>` : null}
    </div>
    ${open ? html`<div class="field-row">
      <label class="sr-only" for=${id}>${t.msgPlaceholder}</label>
      <input id=${id} class="input" type="text" maxlength="2000" placeholder=${t.msgPlaceholder} value=${text}
        onInput=${e => setText(e.currentTarget.value)} onKeyDown=${e => { if (e.key === 'Enter') send() }} />
      <${Btn} size="xs" variant="primary" icon="send" busy=${busy} disabled=${!text.trim()} onClick=${send}>${t.btnSend}<//>
    </div>` : null}
  </div>`
}

function TabInfo({ row, s, c }) {
  const t = T()
  if (!row.tab) return null
  const tab = (s.tabs?.tabs ?? []).find(x => x.ref === row.tab.ref) ?? { ...row.tab, name: row.task ?? row.tab.ref, workspace: '', last: '' }
  return html`<div class="block tab-info">
    <h3 class="label-caps">${t.tabsTitle}</h3>
    <div class="tab-info-line">
      <${StateLine} token=${stateToken(tabStateKey(tab))} strong=${tab.state === 'needs-you'} word=${t.state[tabStateKey(tab)] ?? tab.state} />
      <span class="muted">${tab.workspace ? `${tab.workspace} / ` : ''}${tab.name}</span>
      ${tab.since_ms ? html`<span class="mono muted">${t.sinceFor(duration(s.now - tab.since_ms))}</span>` : null}
    </div>
    ${tab.last ? html`<p class="tab-last">${tab.last}</p>` : null}
    ${tab.filed_by ? html`<p class="muted"><${StateLine} token="success" word=${t.resultFiledLong} /></p>` : null}
    <${TabControls} tab=${tab} s=${s} c=${c} />
  </div>`
}

/** A failed detail load: what went wrong, and a button that tries again */
export function DetailFailed({ d, onRetry }) {
  const t = T()
  return html`<div class="detail-failed"><${StateLine} token="danger" word=${t.detailFailed(d.error)} />
    <${Btn} size="xs" variant="secondary" icon="reload" onClick=${onRetry}>${t.retry}<//></div>`
}

function InboxDetail({ id, s, c }) {
  const t = T()
  const d = s.details.inbox[id]
  const ver = s.model?.collected_ms ?? 0
  useEffect(() => { if (detailNeedsLoad(d, ver)) c.loadInbox(id) }, [id, ver, d?.stale])
  if (!d || (d.status === 'loading' && !d.data)) return html`<div class="block"><p class="muted"><${Spinner} /> ${t.loadingDetail}</p></div>`
  if (d.status === 'error') return html`<div class="block"><${DetailFailed} d=${d} onRetry=${() => c.loadInbox(id)} /></div>`
  const it = d.data.item ?? {}
  const events = d.data.events ?? []
  return html`<div class="block inbox-detail">
    <h3 class="label-caps">${t.inboxTitle}</h3>
    ${it.summary ? html`<p class="inbox-summary">${it.summary}</p>` : null}
    ${it.detail ? html`<p class="pre">${it.detail}</p>` : null}
    <div class="runs">
      <span class="label-caps">${t.runsLabel}</span>
      ${it.action_display ? html`<code class="runs-cmd">${it.action_display}</code>` : html`<span class="muted">${t.runsNone}</span>`}
    </div>
    ${events.length ? html`<details class="events"><summary>${t.eventsTitle(events.length)}</summary>
      <ol class="event-list">${events.map((e, i) => html`<li key=${i}><span class="mono muted">${String(e.at ?? '').replace('T', ' ').slice(0, 16)}</span>
        <span class="chip">${e.verb}</span><span class="muted">${e.by}</span>${e.until ? html`<span>${t.hiddenUntil(e.until)}</span>` : null}
        ${e.note ? html`<span>${e.note}</span>` : null}</li>`)}</ol></details>` : null}
  </div>`
}

function pageLinesFor(model, slug) {
  for (const p of model?.pages ?? []) for (const sec of p.sections ?? []) for (const it of sec.items ?? []) {
    if (it.task === slug && (it.lines ?? []).length) return it.lines
  }
  return []
}

export function Lines({ lines }) {
  const t = T()
  return html`<ul class="lines">${lines.map((l, i) => html`<li key=${i}><span class="line-kind">${t.lineKind[l.kind] ?? `${l.kind}: `}</span><span>${l.text}</span></li>`)}</ul>`
}

function TaskDetail({ slug, s, c, exclude }) {
  const t = T()
  const d = s.details.task[slug]
  const ver = s.model?.collected_ms ?? 0
  useEffect(() => { if (detailNeedsLoad(d, ver)) c.loadTask(slug) }, [slug, ver, d?.stale])
  const byKey = indexRows(s.model)
  const entries = [...byKey.values()].filter(r => r.task === slug && r.key !== exclude && r.key !== `task:${slug}`)
  const lines = pageLinesFor(s.model, slug)
  let body
  if (!d || (d.status === 'loading' && !d.data)) body = html`<p class="muted"><${Spinner} /> ${t.loadingDetail}</p>`
  else if (d.status === 'error') body = html`<${DetailFailed} d=${d} onRetry=${() => c.loadTask(slug)} />`
  else {
    const f = d.data.front ?? {}
    const facts = ['status', 'priority', 'type', 'created', 'last_updated', 'origin', 'blocked_by'].filter(k => f[k])
    body = html`
      ${f.headline ? html`<p class="task-headline">${f.headline}</p>` : null}
      <dl class="meta">${facts.map(k => html`<div class="meta-item" key=${k}><dt>${t.front[k]}</dt>
        <dd>${k === 'status' ? (t.taskState[f[k]] ?? f[k]) : String(f[k])}</dd></div>`)}</dl>
      <div class="task-sections">
        <h4 class="sub-title">${t.taskSections} <code class="muted">${d.data.path}</code></h4>
        ${(d.data.sections ?? []).map((x, i) => html`<details key=${i} open=${i === 0}><summary>${x.heading}</summary>
          <p class="pre">${x.text}</p>${x.truncated ? html`<p class="muted">${t.truncated}</p>` : null}</details>`)}
      </div>
      ${(d.data.log ?? []).length ? html`<div class="sub-block"><h4 class="sub-title">${t.taskLog}</h4>
        <ol class="log-rows">${d.data.log.map((l, i) => html`<li key=${i}><span class="mono muted">${l.at}</span><span>${l.text}</span></li>`)}</ol></div>` : null}`
  }
  return html`<div class="block task-detail">
    <h3 class="label-caps">${t.taskTitle}: <span class="mono">${slug}</span></h3>
    ${lines.length ? html`<${Lines} lines=${lines} />` : null}
    ${body}
    ${entries.length ? html`<div class="sub-block"><h4 class="sub-title">${t.taskEntries}</h4>
      <ul class="entries">${entries.map(r => html`<li key=${r.key} class="entry">
        <button type="button" class="btn-link" onClick=${() => c.select(r.key)}>${short(r.title, 80)}</button>
        <span class="btn-row"><${RowBar} row=${r} s=${s} c=${c} pin=${false} /></span></li>`)}</ul></div>` : null}
  </div>`
}

function RowDetail({ row, s, c }) {
  const t = T()
  const n = s.model?.numbers?.[row.key] ?? row.number
  const openTask = slug => c.select(`task:${slug}`)
  return html`<article class="panel panel-pad detail" aria-labelledby="detail-title">
    <${DetailBack} s=${s} c=${c} />
    <header class="detail-head">
      <span class="detail-eyebrow">${n ? html`<span class="sec-count mono"><span class="sr-only">${t.numberLabel(n)}</span><span aria-hidden="true">${n}</span></span>` : null}
        <span class="eyebrow">${t.section[row.section] ?? row.section}</span></span>
      <h2 class="detail-title" id="detail-title" tabindex="-1">${row.title}</h2>
      <p class="detail-kind"><${KindTag} row=${row} s=${s} c=${c} link /></p>
      <div class="detail-chips">
        <${ReturnChip} s=${s} rowKey=${[row.key, row.task ? `task:${row.task}` : null]} />
        ${row.tab ? html`<${Chip} token=${stateToken(tabStateKey(row.tab))}>${t.state[tabStateKey(row.tab)] ?? row.tab.state}<//>` : null}
        <${MarkChip} mark=${row.mark} /><${PrioChip} priority=${row.priority} />
        ${row.hidden_until ? html`<span class="chip">${t.hiddenUntil(formatDay(row.hidden_until, language()))}</span>` : null}
      </div>
      <${LinkView} link=${row.link} c=${c} onOpenTask=${openTask} />
      ${row.task ? html`<${Btn} size="xs" variant="ghost" onClick=${() => c.openInner(`task:${row.task}`)}>${t.item.inNet}<//>` : null}
    </header>
    <${ReturnPanel} s=${s} c=${c} keys=${[row.key, row.task ? `task:${row.task}` : null]} />
    <${MetaList} row=${row} s=${s} />
    ${(row.why ?? []).length ? html`<div class="block"><h3 class="label-caps">${t.whyTitle}</h3>
      <ul class="why">${row.why.map((w, i) => html`<li key=${i}>${w}</li>`)}</ul></div>` : null}
    ${row.inbox_id ? html`<${InboxDetail} id=${row.inbox_id} s=${s} c=${c} />` : null}
    <${TabInfo} row=${row} s=${s} c=${c} />
    <${ActionsBlock} row=${row} s=${s} c=${c} />
    ${row.hidden_until ? html`<div class="block"><${Btn} size="xs" onClick=${() => c.act('unhide', { key: row.key })}>${t.btnShowAgain}<//></div>` : null}
    <${TeamBlock} row=${row} s=${s} c=${c} />
    ${row.task ? html`<${TaskDetail} slug=${row.task} s=${s} c=${c} exclude=${row.key} />` : null}
  </article>`
}

/** The walk through the list this detail was opened from, as a small bar that stays at the foot of
 *  the column or drawer however long the detail runs: back, where you stand, the next entry with
 *  "next" (key n), and the two after it as plain links. A settled entry drops out at once */
export function NextUp({ s, c, byKey, current, queue = s.ui.queue }) {
  const t = T()
  const live = queueLiveKeys(s.model, s.more)
  const v = current ? queueView(queue, current, e => live.has(e.key)) : null
  if (!v || v.total < 2) return null
  const look = e => s.triage?.items?.[e.key]?.gist || (byKey.get(e.key)?.why ?? [])[0] || undefined
  const entry = (e, max) => ({ key: e.key, title: short(e.title || byKey.get(e.key)?.title || e.key, max), look: look(e), onOpen: () => c.openNext(e) })
  const [next, ...later] = v.next
  return html`<${WalkBar} label=${t.nextLabel} shortcuts=${s.ui.shortcuts} pos=${[v.pos, v.total]} onPrev=${v.prev ? () => c.openNext(v.prev) : null}
    next=${next ? entry(next, 90) : null} later=${later.map(e => entry(e, 80))} done=${t.nextDone} />`
}

/** Back to the list: "close details" beside a page, "back" on a phone, nothing on a wide briefing */
function DetailBack({ s, c }) {
  const t = T()
  if (s.ui.pageDetail) return html`<${Btn} variant="ghost" size="xs" icon="back" onClick=${c.closePeek}>${t.closeDetail}<//>`
  if (s.layout === 'narrow') return html`<${Btn} variant="ghost" size="xs" icon="back" onClick=${() => c.setPane('day')}>${t.back}<//>`
  return null
}

export function DetailColumn({ s, c, byKey }) {
  const t = T()
  const key = s.ui.selectedKey
  const row = key ? byKey.get(key) : null
  let body
  if (!key) body = html`<${Overview} s=${s} c=${c} />`
  else if (row) body = html`<${RowDetail} key=${row.key} row=${row} s=${s} c=${c} />`
  else if (key.startsWith('task:')) {
    body = html`<article class="panel panel-pad detail">
      <${DetailBack} s=${s} c=${c} />
      <header class="detail-head"><span class="eyebrow">${t.taskTitle}</span><h2 class="detail-title">${key.slice(5)}</h2></header>
      <${TaskDetail} slug=${key.slice(5)} s=${s} c=${c} /></article>`
  } else {
    body = html`<div class="panel panel-pad"><p class="muted">${t.rowGone}</p>
      ${s.ui.pageDetail ? html`<${Btn} size="xs" onClick=${c.closePeek}>${t.closeDetail}<//>`
        : html`<${Btn} size="xs" onClick=${() => c.select(null)}>${t.overviewTitle}<//>`}</div>`
  }
  return html`<div class="col col-detail">
    <div class="detail-scroll">${body}</div>
    ${s.ui.pageDetail ? html`<${NextUp} s=${s} c=${c} byKey=${byKey} current=${key} />`
      : key ? html`<${NextUp} s=${s} c=${c} byKey=${byKey} current=${key} queue=${dayQueue(s.model)} />` : null}
  </div>`
}
