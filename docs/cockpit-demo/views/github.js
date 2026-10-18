// SPDX-License-Identifier: MIT
// The cockpit's GitHub work: the figures and the boards above a github-work section, and the detail of
// one issue or pull request (briefing.py detail, through /api/github). Everything here reads; a step on
// a row starts an agent tab (row_action), a board's switch is the person's own choice (github_board).
import { html, useEffect, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { T } from '../text.js'
import { Prose } from './prose.js'
import { Btn, Chip, Icon, Spinner, StateLine } from './parts.js'

export const GH_REF = /^[\w.-]+\/[\w.-]+#\d+$/
const BOARD_STATES = ['new', 'ready', 'in_progress', 'review', 'blocked']
const STATE_TOKEN = { new: 'on-surface-muted', ready: 'info', in_progress: 'secondary', review: 'warning', blocked: 'danger' }
// the figures that are a reason to look: shown loud when not zero
const LOUD = { ask_review: 'warning', blocked: 'danger', quiet: 'warning' }

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
