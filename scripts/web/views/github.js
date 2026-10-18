// SPDX-License-Identifier: MIT
// The cockpit's GitHub work: the figures and the boards above a github-work section, and the detail of
// one issue or pull request (briefing.py detail, through /api/github). Everything here reads; a step on
// a row starts an agent tab (row_action), a board's switch is the person's own choice (github_board).
import { html, useEffect, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { T } from '../text.js'
import { Prose } from './prose.js'
import { Btn, Chip, Icon, PrioChip, Spinner, StateLine } from './parts.js'
import { actionRow, ghSortRows, pageItemActs, rowActionKey } from '../logic.js'
import { SettleMenu } from './day.js'
import { RowSteps } from './pages.js'
import { rowClickOpens } from './overlays.js'

export const GH_REF = /^[\w.-]+\/[\w.-]+#\d+$/
const BOARD_STATES = ['new', 'ready', 'in_progress', 'review', 'blocked']
const STATE_TOKEN = { new: 'on-surface-muted', ready: 'info', in_progress: 'secondary', review: 'warning', blocked: 'danger' }
// the figures that are a reason to look: shown loud when not zero
const LOUD = { ask_review: 'warning', blocked: 'danger', quiet: 'warning', untasked: 'warning' }

/** A row passes the dashboard's filter: a figure (a flag the row carries) or a board (its group) */
export function ghShows(it, filter) {
  if (!filter) return true
  if (filter.kind === 'flag') return filter.id === 'open' || (it.flags ?? []).includes(filter.id)
  if (filter.kind === 'person') return (it.who ?? '') === filter.id
  return (it.group ?? '') === filter.id
}

function ago(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const days = Math.floor((Date.now() - d.getTime()) / 86400000)
  const t = T()
  return days <= 0 ? t.gh.today : days === 1 ? t.gh.yesterday : t.gh.daysAgo(days)
}

/** The figures and the boards above the rows; a click on either filters the rows below, a second one clears it */
export function GitHubBoard({ section, filter, setFilter, c, s }) {
  const t = T()
  const metrics = (section.metrics ?? []).filter(m => !['closed', 'landed'].includes(m.id) || m.n != null)
  const boards = section.boards ?? []
  const pick = f => setFilter(filter && filter.kind === f.kind && filter.id === f.id ? null : f)
  const busy = !!s.ui.busy.github_board
  // who the rows are with, the busiest first: a chip each, a filter like the figures
  const people = Object.entries((section.items ?? []).reduce((n, it) => (it.who ? { ...n, [it.who]: (n[it.who] ?? 0) + 1 } : n), {}))
    .sort((a, b) => b[1] - a[1] || a[0].localeCompare(b[0])).slice(0, 16)
  return html`<div class="ghb">
    ${metrics.length ? html`<ul class="ghb-figures" aria-label=${t.gh.figuresLabel}>${metrics.map(m => {
      const done = m.id === 'closed' || m.id === 'landed'
      const on = filter?.kind === 'flag' && filter.id === m.id
      const loud = m.n > 0 && LOUD[m.id]
      return html`<li key=${m.id}>
        <button type="button" class=${`ghb-figure${on ? ' is-on' : ''}${loud ? ` tk-${loud} is-loud` : ''}${done ? ' is-done' : ''}`}
          aria-pressed=${String(on)} disabled=${done} title=${t.gh.figureTitle[m.id]?.(m) ?? ''} onClick=${() => pick({ kind: 'flag', id: m.id })}>
          <span class="ghb-n mono">${m.n}</span>
          <span class="ghb-label">${t.gh.figure[m.id] ?? m.id}</span>
          ${m.days != null && (m.id === 'my_pr' || done) ? html`<span class="ghb-sub muted">${t.gh.figureSub[m.id]?.(m.days) ?? ''}</span>` : null}
        </button></li>`
    })}</ul>` : null}
    ${boards.length ? html`<ul class="ghb-boards" aria-label=${t.gh.boardsLabel}>${boards.map(b => {
      const total = BOARD_STATES.reduce((n, k) => n + (b.counts?.[k] ?? 0), 0)
      const on = filter?.kind === 'board' && filter.id === b.name
      const off = b.mode === 'off'
      return html`<li key=${b.slug ?? b.name} class=${`ghb-board${on ? ' is-on' : ''}${off ? ' is-off' : ''}`}>
        <button type="button" class="ghb-board-head" aria-pressed=${String(on)} disabled=${off}
          title=${off ? t.gh.boardOffTitle : t.gh.boardFilterTitle} onClick=${() => pick({ kind: 'board', id: b.name })}>
          <span class="ghb-board-name">${b.name}</span>
          <span class="ghb-n mono">${off ? '' : b.open ?? total}</span>
        </button>
        ${off ? html`<p class="muted small ghb-off">${t.gh.boardOff}</p>` : total ? html`<div class="ghb-bar" role="img"
            aria-label=${BOARD_STATES.filter(k => b.counts?.[k]).map(k => `${b.counts[k]} ${t.gh.state[k]}`).join(', ')}>
          ${BOARD_STATES.filter(k => b.counts?.[k]).map(k => html`<span key=${k} class=${`ghb-seg tk-${STATE_TOKEN[k]}`}
            style=${{ flexGrow: b.counts[k] }} title=${`${b.counts[k]} ${t.gh.state[k]}`}></span>`)}
        </div>
        <p class="ghb-legend muted small">${BOARD_STATES.filter(k => b.counts?.[k]).map(k => html`<span key=${k}>
          <span class=${`ghb-dot tk-${STATE_TOKEN[k]}`}></span>${b.counts[k]} ${t.gh.state[k]}</span>`)}</p>`
        : html`<p class="muted small ghb-off">${t.gh.boardEmpty}</p>`}
        ${b.capped ? html`<p class="muted small">${t.gh.capped(b.capped)}</p>` : null}
        ${b.slug && b.mode ? html`<div class="ghb-mode" role="group" aria-label=${t.gh.modeLabel(b.name)}>
          ${['off', 'mine', 'all'].map(m => html`<button type="button" key=${m} class=${`ghb-mode-btn${b.mode === m ? ' is-on' : ''}`}
            aria-pressed=${String(b.mode === m)} disabled=${busy}
            onClick=${() => b.mode !== m && c.act('github_board', { section: section.id, slug: b.slug, mode: m })}>${t.gh.mode[m]}</button>`)}
        </div>` : null}
      </li>`
    })}</ul>` : null}
    ${people.length > 1 ? html`<p class="ghb-people" role="group" aria-label=${t.gh.peopleLabel}>
      <span class="muted small">${t.gh.peopleLabel}</span>
      ${people.map(([who, n]) => {
        const on = filter?.kind === 'person' && filter.id === who
        return html`<button type="button" key=${who} class=${`fchip${on ? ' is-on' : ''}`} aria-pressed=${String(on)}
          onClick=${() => pick({ kind: 'person', id: who })}>@${who} <span class="mono muted">${n}</span></button>`
      })}</p>` : null}
    ${filter ? html`<p class="ghb-filter small"><span class="muted">${t.gh.filtered}</span>
      <strong>${filter.kind === 'flag' ? t.gh.figure[filter.id] : filter.kind === 'person' ? `@${filter.id}` : filter.id}</strong>
      <${Btn} size="xs" variant="ghost" icon="close" onClick=${() => setFilter(null)}>${t.gh.filterClear}<//></p>` : null}
  </div>`
}

function Person({ login }) {
  return login ? html`<span class="gh-person mono">@${login}</span>` : null
}

function Fact({ label, children }) {
  return html`<div class="meta-item"><dt>${label}</dt><dd>${children}</dd></div>`
}

// open green, closed grey, a pull request that landed in its base the accent
const STATE_OF = { open: 'success', closed: 'on-surface-muted' }
const REVIEW_TOKEN = { approved: 'success', changes_requested: 'danger', review_required: 'warning' }
const CHECKS_TOKEN = { success: 'success', failure: 'danger', error: 'danger', pending: 'warning', expected: 'warning' }

/** The detail of one GitHub row in the info drawer: what it says, who is on it, where it stands; read once
 *  per opening (kept ten minutes on the server), "fresh" asks GitHub again */
export function GitHubDetail({ gref: id, c }) {
  const t = T()
  const [st, setSt] = useState({ status: 'loading', data: null })
  const load = fresh => {
    setSt(x => ({ status: 'loading', data: x.data }))
    c.github(id, fresh).then(res => setSt(res.ok ? { status: 'ok', data: res.data } : { status: 'error', error: res.error, data: null }))
  }
  useEffect(() => { load(false) }, [id])
  const d = st.data
  if (!d) {
    return html`<section class="idrawer-sec gh-detail">${st.status === 'loading'
      ? html`<p class="muted"><${Spinner} /> ${t.gh.loading}</p>`
      : html`<p><${StateLine} token="warning" word=${t.gh.unreadable(st.error?.message ?? st.error ?? '')} /></p>
        <${Btn} size="xs" variant="ghost" onClick=${() => load(true)}>${t.gh.retry}<//>`}</section>`
  }
  const pr = d.pr
  const state = d.state
  const failing = pr?.checks?.failing ?? []
  return html`<section class="idrawer-sec gh-detail">
    <div class="gh-head">
      <${Chip} token=${STATE_OF[state] ?? 'secondary'}>${t.gh.itemState[state] ?? state}${d.draft ? ` · ${t.gh.draft}` : ''}<//>
      ${(d.boards ?? []).map(b => html`<${Chip} key=${b.title} token="info" title=${`#${b.number}`}>${b.title}: ${b.status ?? t.gh.noStatus}<//>`)}
      ${(d.labels ?? []).map(l => html`<span key=${l.name} class="gh-label" style=${l.color ? { '--lc': `#${l.color}` } : undefined}>${l.name}</span>`)}
      <span class="muted small">${st.status === 'loading' ? html`<${Spinner} />` : null}
        ${d.stale ? t.gh.staleDetail : t.gh.fetched(ago(d.fetched_at))}</span>
      <${Btn} size="xs" variant="ghost" icon="reload" busy=${st.status === 'loading'} onClick=${() => load(true)}>${t.gh.refresh}<//>
    </div>
    <dl class="meta gh-facts">
      <${Fact} label=${t.gh.author}><${Person} login=${d.author} /> · ${ago(d.created)}<//>
      ${d.assignees?.length ? html`<${Fact} label=${t.gh.assignees}>${d.assignees.map(a => html`<${Person} key=${a} login=${a} /> `)}<//>` : null}
      <${Fact} label=${t.gh.updated}>${ago(d.updated)}<//>
      ${d.milestone ? html`<${Fact} label=${t.gh.milestone}>${d.milestone}<//>` : null}
      ${pr ? html`<${Fact} label=${t.gh.branch}><span class="mono">${pr.head}</span> → <span class="mono">${pr.base}</span><//>
        <${Fact} label=${t.gh.size}><span class="gh-add mono">+${pr.additions ?? 0}</span> <span class="gh-del mono">−${pr.deletions ?? 0}</span> · ${t.gh.files(pr.files ?? 0)}<//>
        <${Fact} label=${t.gh.review}>${pr.review ? html`<${StateLine} token=${REVIEW_TOKEN[pr.review] ?? 'info'} word=${t.gh.reviewState[pr.review] ?? pr.review} />` : t.gh.noReview}
          ${pr.requested?.length ? html` · ${t.gh.requested} ${pr.requested.map(r => html`<${Person} key=${r} login=${r} /> `)}` : null}<//>
        <${Fact} label=${t.gh.checks}>${pr.checks?.state ? html`<${StateLine} token=${CHECKS_TOKEN[pr.checks.state] ?? 'info'}
            word=${t.gh.checksState(pr.checks.state, pr.checks.total, failing.length, (pr.checks.running ?? []).length)} />` : t.gh.noChecks}<//>` : null}
    </dl>
    ${failing.length ? html`<p class="small"><${StateLine} token="danger" word=${t.gh.failing(failing.join(', '))} /></p>` : null}
    ${(pr?.reviews ?? []).length ? html`<ul class="gh-list small">${pr.reviews.map(r => html`<li key=${`${r.author}${r.at}`}>
      <${Person} login=${r.author} /> <${StateLine} token=${REVIEW_TOKEN[r.state] ?? 'info'} word=${t.gh.reviewState[r.state] ?? r.state} /> <span class="muted">${ago(r.at)}</span></li>`)}</ul>` : null}
    ${(d.prs ?? []).length ? html`<div><h3 class="label-caps">${t.gh.prsTitle}</h3><ul class="gh-list">${d.prs.map(p => html`<li key=${p.number}>
      <a href=${p.url} target="_blank" rel="noopener noreferrer">#${p.number} ${p.title}</a>
      <span class="muted small"> ${t.gh.itemState[p.state] ?? p.state}${p.draft ? ` · ${t.gh.draft}` : ''}</span></li>`)}</ul></div>` : null}
    ${(d.closes ?? []).length ? html`<div><h3 class="label-caps">${t.gh.closesTitle}</h3><ul class="gh-list">${d.closes.map(p => html`<li key=${p.number}>
      <a href=${p.url} target="_blank" rel="noopener noreferrer">#${p.number} ${p.title}</a></li>`)}</ul></div>` : null}
    <div class="gh-body">
      <h3 class="label-caps">${t.gh.bodyTitle}</h3>
      ${d.body ? html`<${Prose} text=${d.body} cls="gh-prose" />` : html`<p class="muted">${t.gh.noBody}</p>`}
      ${d.body_cut ? html`<p class="muted small">${t.gh.bodyCut}</p>` : null}
    </div>
    ${d.comments?.total ? html`<div class="gh-comments">
      <h3 class="label-caps">${t.gh.commentsTitle(d.comments.total, d.comments.items.length)}</h3>
      <ol class="gh-thread">${d.comments.items.map(cm => html`<li key=${cm.url ?? cm.at} class="gh-comment">
        <p class="gh-comment-head small"><${Person} login=${cm.author} /> <span class="muted">${ago(cm.at)}</span>
          ${cm.url ? html` <a class="muted" href=${cm.url} target="_blank" rel="noopener noreferrer"><${Icon} name="external" size=${12} /></a>` : null}</p>
        <${Prose} text=${cm.body} cls="gh-prose" />
      </li>`)}</ol>
    </div>` : null}
  </section>`
}

// ---------------------------------------------------------------- the list: one row per issue or pull request

const FOLD_KEY = 'cockpit.github.folded'

function readFolded() {
  try { return new Set(JSON.parse(localStorage.getItem(FOLD_KEY) ?? '[]')) } catch { return new Set() }
}

function keepFolded(set) {
  try { localStorage.setItem(FOLD_KEY, JSON.stringify([...set])) } catch { /* a convenience, never needed */ }
}

/** The one step a row leads with: a review someone asked you for, your issue to implement, someone else's
 *  card to remind them of, else a look at it; the rest stay in the menu */
export function leadStep(it) {
  const ids = (it.actions ?? []).map(a => a.id)
  const f = it.flags ?? []
  if (f.includes('ask_review') && ids.includes('review')) return 'review'
  if (f.includes('mine') && ids.includes('implement')) return 'implement'
  if (!f.includes('mine') && ids.includes('remind')) return 'remind'
  if (f.includes('my_pr') && ids.includes('review')) return 'review'
  return ids.includes('analyze') ? 'analyze' : ids[0] ?? null
}

function TypeIcon({ type, token }) {
  // an issue: a ring with a dot; a pull request: two branches joining; a draft card: a dashed ring, nothing behind it
  const d = type === 'pr'
    ? 'M6 3a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM6 7v10M6 17a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM18 17a2 2 0 1 0 0 4 2 2 0 0 0 0-4zM18 17V9a3 3 0 0 0-3-3h-4M13 4l-2 2 2 2'
    : type === 'draft' ? 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18z'
      : 'M12 3a9 9 0 1 0 0 18 9 9 0 0 0 0-18zM12 11a1 1 0 1 0 0 2 1 1 0 0 0 0-2z'
  return html`<svg class=${`ghl-icon tk-${token}`} width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor"
    stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" stroke-dasharray=${type === 'draft' ? '3 3' : null}
    aria-hidden="true" focusable="false"><path d=${d} /></svg>`
}

function matches(it, q) {
  if (!q) return true
  const g = it.gh ?? {}
  const hay = [it.title, g.title, g.repo, g.number && `#${g.number}`, g.status, g.priority, ...(g.labels ?? []), ...(g.people ?? []), g.task]
    .filter(Boolean).join(' ').toLowerCase()
  return q.toLowerCase().split(/\s+/).every(w => hay.includes(w))
}

function GhRow({ it, page, section, s, c, byKey }) {
  const t = T()
  const g = it.gh ?? {}
  const lead = leadStep(it)
  const rest = (it.actions ?? []).filter(a => a.id !== lead)
  const leadLabel = (it.actions ?? []).find(a => a.id === lead)?.label
  const token = STATE_TOKEN[g.state] ?? 'info'
  const live = it.tab && it.tab.live
  const settleRow = (pageItemActs(it) || it.inbox || (it.task && byKey.has(`task:${it.task}`))) ? actionRow(it, byKey) : null
  const open = () => c.openInfo(it, page, section)
  const repoName = g.repo ? g.repo.split('/').pop() : ''
  return html`<li class=${`ghl-row${g.quiet ? ' is-quiet' : ''}`} tabindex="0"
    onClick=${e => { if (rowClickOpens(e)) open() }}
    onKeyDown=${e => { if (e.key === 'Enter' && e.target === e.currentTarget) { e.preventDefault(); open() } }}>
    <${TypeIcon} type=${g.type} token=${token} />
    <div class="ghl-main">
      <p class="ghl-title">${g.title || it.title}</p>
      <p class="ghl-meta">
        ${g.number ? html`<span class="mono muted" title=${g.repo ?? ''}>${repoName}#${g.number}</span>` : null}
        ${g.type === 'draft' ? html`<span class="ghl-chip ghl-chip-draft" title=${t.gh.draftCardTitle}>${t.gh.draftCard}</span>` : null}
        <${PrioChip} priority=${g.priority} />
        ${g.status || g.state ? html`<span class=${`ghl-state tk-${token}`}><span class="ghl-dot"></span>${g.status || t.gh.state[g.state] || g.state}</span>` : null}
        ${(g.labels ?? []).map(l => html`<span key=${l} class="gh-label">${l}</span>`)}
        ${(g.prs ?? []).map(p => html`<span key=${p.n} class="ghl-chip">PR #${p.n}${p.draft ? ` · ${t.gh.draft}` : ''}</span>`)}
        ${g.task ? html`<span class="ghl-chip ghl-chip-task" title=${t.gh.taskChipTitle}>${g.stream ? t.gh.streamChip(g.task) : t.gh.taskChip(g.task)}</span>` : null}
        ${g.untasked ? html`<span class="ghl-chip ghl-chip-untasked" title=${t.gh.untaskedChipTitle}>${t.gh.untaskedChip}</span>` : null}
        ${it.tab ? html`<${Chip} token=${it.tab.live ? 'success' : 'on-surface-muted'}>${t.gh.agentChip(t.state?.[it.tab.state] ?? it.tab.state)}<//>` : null}
        ${g.quiet ? html`<span class="ghl-chip ghl-chip-quiet">${t.gh.quietChip(g.quiet)}</span>` : null}
        ${g.note ? html`<span class="muted small">${g.note}</span>` : null}
      </p>
    </div>
    <div class="ghl-side">
      ${(g.people ?? []).length ? html`<span class="ghl-people">${g.people.map(p => html`<span key=${p} class="gh-person mono">@${p}</span>`)}</span>` : null}
      <span class="muted small" title=${g.changed ?? ''}>${ago(g.changed)}</span>
    </div>
    <div class="ghl-acts btn-row">
      ${live ? html`<${Btn} size="xs" variant="primary" busy=${!!s.ui.busy[it.tab.ref]} onClick=${() => c.act('tab_jump', { tab_ref: it.tab.ref })}>${t.btnToTab}<//>`
        : lead ? html`<${Btn} size="xs" variant="primary" busy=${!!s.ui.busy[rowActionKey({ page, section, index: it.index })]}
            onClick=${() => c.act('row_action', { page, section, index: it.index, action: lead })}>${leadLabel}<//>` : null}
      ${rest.length && it.row_id ? html`<${RowSteps} it=${{ ...it, actions: rest }} page=${page} section=${section} s=${s} c=${c} />` : null}
      ${settleRow ? html`<${SettleMenu} rows=${[settleRow]} s=${s} c=${c} />` : null}
      ${it.link?.kind === 'web' ? html`<a class="btn btn-ghost btn-xs" href=${it.link.href} target="_blank" rel="noopener noreferrer"
        title=${t.openLink} aria-label=${t.openLink}><${Icon} name="external" size=${14} /></a>` : null}
    </div>
  </li>`
}

/** The rows of a github-work section under their board: a one-line head per board (its count and a bar of
 *  its rows' states) that folds, the rows in the work's order or newest first, a search over everything a
 *  row names */
export function GitHubList({ items, page, section, s, c, byKey }) {
  const t = T()
  const [q, setQ] = useState('')
  const [by, setBy] = useState('state')
  const [folded, setFolded] = useState(readFolded)
  const shown = items.filter(it => matches(it, q.trim()))
  // the priority order only where a board names its priority field (board.priority_field)
  const sorts = items.some(it => it.gh?.priority) ? ['state', 'priority', 'recent'] : ['state', 'recent']
  const order = (section.boards ?? []).map(b => b.name)
  const groups = [...new Set(shown.map(it => it.group ?? ''))]
    .sort((a, b) => ((order.indexOf(a) + 1) || 999) - ((order.indexOf(b) + 1) || 999) || a.localeCompare(b))
  const fold = key => {
    const next = new Set(folded)
    if (next.has(key)) next.delete(key)
    else next.add(key)
    setFolded(next)
    keepFolded(next)
  }
  const allFolded = groups.length > 0 && groups.every(g => folded.has(g))
  const foldAll = () => {
    const next = allFolded ? new Set() : new Set(groups)
    setFolded(next)
    keepFolded(next)
  }
  return html`<div class="ghl">
    <div class="ghl-tools">
      <input class="ghl-search" type="search" value=${q} placeholder=${t.gh.searchPlaceholder} aria-label=${t.gh.searchPlaceholder}
        onInput=${e => setQ(e.currentTarget.value)} />
      <div class="ghb-mode" role="group" aria-label=${t.gh.sortLabel}>
        ${sorts.map(k => html`<button type="button" key=${k} class=${`ghb-mode-btn${by === k ? ' is-on' : ''}`}
          aria-pressed=${String(by === k)} onClick=${() => setBy(k)}>${t.gh.sort[k]}</button>`)}
      </div>
      ${groups.length > 1 ? html`<${Btn} size="xs" variant="ghost" icon="chevronDown" onClick=${foldAll}>${allFolded ? t.gh.unfoldAll : t.gh.foldAll}<//>` : null}
    </div>
    ${!shown.length ? html`<p class="muted">${t.filterNone}</p>` : groups.map(g => {
      const rows = ghSortRows(shown.filter(it => (it.group ?? '') === g), by)
      const isFolded = folded.has(g)
      const counts = rows.reduce((n, it) => ({ ...n, [it.gh?.state ?? 'new']: (n[it.gh?.state ?? 'new'] ?? 0) + 1 }), {})
      return html`<section class="ghl-group" key=${g}>
        <button type="button" class="ghl-head" aria-expanded=${String(!isFolded)} onClick=${() => fold(g)}>
          <span class=${`ghl-chev${isFolded ? '' : ' is-open'}`} aria-hidden="true">›</span>
          <span class="ghl-head-name">${g || t.groupOther}</span>
          <span class="sec-count mono">${rows.length}</span>
          <span class="ghb-bar ghl-head-bar" aria-hidden="true">${BOARD_STATES.filter(k => counts[k]).map(k => html`<span key=${k}
            class=${`ghb-seg tk-${STATE_TOKEN[k]}`} style=${{ flexGrow: counts[k] }}></span>`)}</span>
        </button>
        ${isFolded ? null : html`<ul class="ghl-rows">${rows.map(it => html`<${GhRow} key=${it.index} it=${it} page=${page}
          section=${section.id} s=${s} c=${c} byKey=${byKey} />`)}</ul>`}
      </section>`
    })}
  </div>`
}
