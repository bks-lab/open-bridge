// SPDX-License-Identifier: MIT
// The cockpit's GitHub work: the figures with a cause above a github-work section (round 6: no tile per board and
// no switch on the page) and the filter bar under them (round 6c: Board, Person, Repository, Kind, Board status, each
// with its counts, combined, kept per viewer, a column spelled two ways one option), its rows under a head per board
// that names the board's facts (or in one list, "Group by board" off), each row with its repo#number (no GitHub chip,
// the ref says it), board and column, people, labels, who opened it and a pull request's draft, review and checks, and the detail of one issue or pull request (briefing.py detail, through /api/github).
// Everything here reads; a row has one start, its lead step with the other steps under ▾ (row_action, an agent tab)
// and Close beside it; a board's switch is the person's own choice, made in the settings, which list every board with
// the mode a new one starts with (github_board, github_board_default).
import { html, useEffect, useState } from '../vendor/htm-preact-3.1.1.module.js'
import { T } from '../text.js'
import { Prose } from './prose.js'
import { Btn, Chip, Icon, PrioChip, Spinner, StateLine } from './parts.js'
import { GH_DIMS, GH_ME, GH_NONE, actionRow, canTab, ghFacets, ghFiltered, ghMyLogin, ghPasses, ghSortRows, ghStatusKey, ghStatusWords, itemRow, pageItemActs, rowActionKey } from '../logic.js'
import { OriginTag, SettleMenu, StartMenu } from './day.js'
import { RowSteps } from './pages.js'
import { rowClickOpens } from './overlays.js'
import { Card } from './settings.js'

/** The chip of the task or stream a board row syncs with: the server's work kind of that place first (a closed task,
 *  an ended stream), the board's stream flag only for an older server */
export function ghPlaceChip(it, g, t) {
  const wk = ['task', 'stream', 'done_task', 'done_stream'].includes(it?.work_kind) ? it.work_kind : g.stream ? 'stream' : 'task'
  return wk === 'stream' ? t.gh.streamChip(g.task) : wk === 'task' ? t.gh.taskChip(g.task) : `${t.kind[wk]} ${g.task}`
}

export const GH_REF = /^[\w.-]+\/[\w.-]+#\d+$/
const BOARD_STATES = ['new', 'ready', 'in_progress', 'review', 'blocked']
const STATE_TOKEN = { new: 'on-surface-muted', ready: 'info', in_progress: 'secondary', review: 'warning', blocked: 'danger' }
// the figures that are a reason to look: shown loud when not zero
const LOUD = { ask_review: 'warning', blocked: 'danger', quiet: 'warning', untasked: 'warning' }

/** A row passes the page's filter: the figure picked and the choice of each field of the bar (logic.js ghPasses) */
export function ghShows(it, filter, me = null) {
  return ghPasses(it, filter, me)
}

function ago(iso) {
  if (!iso) return ''
  const d = new Date(iso)
  if (Number.isNaN(d.getTime())) return ''
  const days = Math.floor((Date.now() - d.getTime()) / 86400000)
  const t = T()
  return days <= 0 ? t.gh.today : days === 1 ? t.gh.yesterday : t.gh.daysAgo(days)
}

/** The filter bar (round 6c): a select per field that has more than one value over all rows (or a choice), each
 *  option with the rows it would show beside the other choices; a field another choice narrowed to one value keeps
 *  its place with that value, so the bar never jumps; with a choice, how many rows show and one reset for every filter */
function GhFilterBar({ items, filter, setFilter, order }) {
  const t = T()
  const b = t.gh.bar
  const me = ghMyLogin(items)
  const facets = ghFacets(items, filter, me, { board: order })
  const columns = ghStatusWords(items)
  const person = d => d === 'assignee' || d === 'author'
  const word = (d, v) => (v === GH_NONE ? (person(d) ? b.nobody : b.noBoard) : v === GH_ME ? b.me
    : person(d) ? `@${v}` : d === 'type' ? b.kind[v] ?? v : d === 'status' ? columns.get(v) ?? v : v)
  const whole = filter ? ghFacets(items, null, me, { board: order }) : facets
  const dims = GH_DIMS.filter(d => whole[d].length > 1 || filter?.[d] != null)
  const on = ghFiltered(filter)
  if (!dims.length && !on) return null
  const pick = (d, v) => setFilter({ ...(filter ?? {}), [d]: v || null })
  return html`<div class="ghf" role="group" aria-label=${b.label}>
    ${dims.map(d => html`<label key=${d} class="ghf-field" data-dim=${d}>
      <span class="ghf-label muted small">${b.dim[d]}</span>
      <select class="input input-sm" value=${filter?.[d] == null ? '' : d === 'status' ? ghStatusKey(filter[d]) : filter[d]} onChange=${e => pick(d, e.currentTarget.value)}>
        <option value="">${b.all(items.filter(it => ghPasses(it, filter, me, d)).length)}</option>
        ${facets[d].map(o => html`<option key=${o.value} value=${o.value}>${word(d, o.value)} (${o.n})</option>`)}
      </select></label>`)}
    ${on ? html`<span class="ghf-count muted small">${b.count(items.filter(it => ghPasses(it, filter, me)).length, items.length)}</span>
      <${Btn} size="xs" variant="ghost" icon="close" cls="ghf-reset" onClick=${() => setFilter(null)}>${b.reset}<//>` : null}
  </div>`
}

/** The figures with a cause above the rows (one a person should look at, not zero), the boards switched off, and the
 *  filter bar; a click on a figure filters the rows below on top of the bar, a second one clears it */
export function GitHubBoard({ section, items = section.items ?? [], filter, setFilter, c }) {
  const t = T()
  const metrics = (section.metrics ?? []).filter(m => LOUD[m.id] && m.n > 0)
  // a board switched off leaves the page: one line names them and leads to the settings, where it comes back
  const hidden = (section.boards ?? []).filter(b => b.mode === 'off')
  const pick = id => setFilter({ ...(filter ?? {}), flag: filter?.flag === id ? null : id })
  return html`<div class="ghb">
    ${metrics.length ? html`<ul class="ghb-figures" aria-label=${t.gh.figuresLabel}>${metrics.map(m => {
      const on = filter?.flag === m.id
      return html`<li key=${m.id}>
        <button type="button" class=${`ghb-figure tk-${LOUD[m.id]} is-loud${on ? ' is-on' : ''}`}
          aria-pressed=${String(on)} title=${t.gh.figureTitle[m.id]?.(m) ?? ''} onClick=${() => pick(m.id)}>
          <span class="ghb-n mono">${m.n}</span>
          <span class="ghb-label">${t.gh.figure[m.id] ?? m.id}</span>
        </button></li>`
    })}</ul>` : null}
    ${section.boards?.length ? html`<p class="ghb-hidden muted small">
      ${hidden.length ? html`<span>${t.gh.hiddenBoards(hidden.map(b => b.name).join(', '))}</span>` : null}
      <${Btn} size="xs" variant="ghost" icon="sliders" onClick=${() => c.openSettings('boards')}>${t.gh.boardsSettings}<//></p>` : null}
    <${GhFilterBar} items=${items} filter=${filter} setFilter=${setFilter} order=${(section.boards ?? []).map(x => x.name)} />
  </div>`
}

/** The mode buttons of one board, or of the default for new ones: a group with the one chosen pressed */
function ModeGroup({ modes, at, label, busy, pick }) {
  const t = T()
  return html`<div class="ghb-mode" role="group" aria-label=${label}>
    ${modes.map(m => html`<button type="button" key=${m} class=${`ghb-mode-btn${at === m ? ' is-on' : ''}`}
      aria-pressed=${String(at === m)} disabled=${busy} onClick=${() => at !== m && pick(m)}>${m === 'profile' ? t.gh.defaultMode.profile : t.gh.mode[m]}</button>`)}
  </div>`
}

/** Settings, area "GitHub boards": every board of every GitHub section, a hidden one too, each with its switch,
 *  and the mode a board takes until it is switched (a new board on the registry, say) */
export function BoardSettings({ s, c }) {
  const t = T()
  const busy = !!(s.ui.busy.github_board || s.ui.busy.github_board_default)
  const seen = new Set()
  const rows = (s.model?.pages ?? []).flatMap(p => p.sections ?? []).flatMap(sec => (sec.boards ?? [])
    .filter(b => b.slug && !seen.has(b.slug) && seen.add(b.slug)).map(b => ({ ...b, section: sec.id })))
  if (!rows.length) return html`<${Card} title=${t.gh.settingsTitle}><p class="muted small">${t.gh.noBoards}</p><//>`
  const fresh = rows.find(b => b.default)?.default ?? 'profile'
  return html`<${Card} title=${t.gh.settingsTitle} intro=${t.gh.settingsIntro}>
      <ul class="board-set">${rows.map(b => html`<li key=${b.slug} class=${`board-set-row${b.mode === 'off' ? ' is-off' : ''}`}>
        <span class="board-set-name">${b.name}</span>
        <${ModeGroup} modes=${['off', 'mine', 'all']} at=${b.mode} label=${t.gh.modeLabel(b.name)} busy=${busy}
          pick=${m => c.act('github_board', { section: b.section, slug: b.slug, mode: m })} />
      </li>`)}</ul>
    <//>
    <${Card} title=${t.gh.defaultTitle} intro=${t.gh.defaultIntro}>
      <div class="board-set-default">
        <${ModeGroup} modes=${['profile', 'off', 'mine', 'all']} at=${fresh} label=${t.gh.defaultTitle} busy=${busy}
          pick=${m => c.act('github_board_default', { mode: m })} />
      </div>
    <//>`
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
 *  card to remind them of, else a look at it; the rest stay in the menu under ▾ beside it */
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
  // a person as the row shows them too: @login
  const hay = [it.title, g.title, g.repo, g.number && `#${g.number}`, g.status, g.priority, ...(g.labels ?? []),
    ...[...(g.people ?? []), g.author].filter(Boolean).map(p => `@${p}`), g.board, g.task]
    .filter(Boolean).join(' ').toLowerCase()
  return q.toLowerCase().split(/\s+/).every(w => hay.includes(w))
}

/** The one start of a row (round 6): its lead step, or To tab while an agent works on it, with the other steps under
 *  ▾ (RowSteps); a row with no step of its own starts through the general start (StartMenu). Never two starts */
function GhStart({ it, row, page, section, s, c }) {
  const t = T()
  const live = it.tab && it.tab.live
  const lead = leadStep(it)
  const steps = (it.actions ?? []).filter(a => live || a.id !== lead)
  const head = live ? html`<${Btn} size="xs" variant="primary" busy=${!!s.ui.busy[it.tab.ref]}
      onClick=${() => (canTab(s, 'focus') ? c.act('tab_jump', { tab_ref: it.tab.ref }) : c.openTabView(it.tab.ref))}>${t.btnToTab}<//>`
    : lead ? html`<${Btn} size="xs" variant="primary" busy=${!!s.ui.busy[rowActionKey({ page, section, index: it.index })]}
      onClick=${() => c.act('row_action', { page, section, index: it.index, action: lead })}>${(it.actions ?? []).find(a => a.id === lead)?.label}<//>`
      : null
  if (head && steps.length && it.row_id) return html`<${RowSteps} it=${{ ...it, actions: steps }} page=${page} section=${section} s=${s} c=${c} head=${head} />`
  return head ?? (row ? html`<${StartMenu} row=${row} s=${s} c=${c} />` : null)
}

// a pull request's state on its row: a draft, its review, the checks of its last commit
const PR_TOKEN = { ...REVIEW_TOKEN, ...CHECKS_TOKEN }
const SHOWN_LABELS = 3
const SHOWN_PEOPLE = 3

/** A login on a row: you as you; with a filter to set (round 6d), a button that filters the rows by it */
function RowPerson({ login, me, dim, pick }) {
  const t = T()
  const mine = login === me
  const word = mine ? t.gh.you : `@${login}`
  return pick ? html`<button type="button" class="gh-person mono ghl-pick" title=${t.gh.pickTitle[dim]}
    onClick=${e => { e.stopPropagation(); pick(dim, mine ? GH_ME : login) }}>${word}</button>` : html`<span class="gh-person mono">${word}</span>`
}

function GhRow({ it, page, section, s, c, byKey, grouped = true, me = null, pick = null }) {
  const t = T()
  const g = it.gh ?? {}
  const labels = g.labels ?? []
  const people = g.people ?? []
  // who opened it, always beside who it is assigned to (round 6d); you as you
  const byMe = g.by_me === true || (!!me && g.author === me)
  const token = STATE_TOKEN[g.state] ?? 'info'
  const found = (pageItemActs(it) || it.inbox || (it.task && byKey.has(`task:${it.task}`))) ? actionRow(it, byKey) : null
  // the row the close door acts on, with the agent tab the page item names
  const settleRow = found && it.tab && !found.tab ? { ...found, tab: { ref: it.tab.ref, state: it.tab.state, live: it.tab.live ?? it.tab.state !== 'shell' } } : found
  const open = () => c.openInfo(it, page, section)
  const repoName = g.repo ? g.repo.split('/').pop() : ''
  return html`<li class=${`ghl-row${g.quiet ? ' is-quiet' : ''}`} tabindex="0"
    onClick=${e => { if (rowClickOpens(e)) open() }}
    onKeyDown=${e => { if (e.key === 'Enter' && e.target === e.currentTarget) { e.preventDefault(); open() } }}>
    <${TypeIcon} type=${g.type} token=${token} />
    <div class="ghl-main">
      <p class="ghl-title">${g.title || it.title}</p>
      <p class="ghl-meta">
        ${it.origin && it.origin.category !== 'github' ? html`<${OriginTag} row=${itemRow(it)} origin=${it.origin} />` : null}
        ${g.number ? html`<span class="ghl-ref mono muted" title=${g.repo ?? ''}>${repoName}#${g.number}</span>` : null}
        ${!grouped && g.board ? html`<span class="ghl-chip ghl-chip-board" title=${g.also_on?.length ? t.gh.alsoOn(g.also_on.join(', ')) : g.board}>${g.board}</span>` : null}
        ${g.type === 'draft' ? html`<span class="ghl-chip ghl-chip-draft" title=${t.gh.draftCardTitle}>${t.gh.draftCard}</span>` : null}
        <${PrioChip} priority=${g.priority} />
        ${g.status || g.state ? html`<span class=${`ghl-state tk-${token}`}><span class="ghl-dot"></span>${g.status || t.gh.state[g.state] || g.state}</span>` : null}
        ${labels.slice(0, SHOWN_LABELS).map(l => html`<span key=${l} class="gh-label">${l}</span>`)}
        ${labels.length > SHOWN_LABELS ? html`<span class="ghl-more muted" title=${labels.slice(SHOWN_LABELS).join(', ')}>+${labels.length - SHOWN_LABELS}</span>` : null}
        ${g.pr ? [g.pr.draft ? ['draft', t.gh.draft, 'on-surface-muted'] : null,
          g.pr.review ? [g.pr.review, t.gh.reviewState[g.pr.review] ?? g.pr.review, PR_TOKEN[g.pr.review]] : null,
          g.pr.checks ? [`checks-${g.pr.checks}`, t.gh.checksShort[g.pr.checks] ?? g.pr.checks, PR_TOKEN[g.pr.checks]] : null]
          .filter(Boolean).map(([k, word, token]) => html`<span key=${k} class=${`ghl-chip ghl-pr tk-${token ?? 'info'}`}>${word}</span>`) : null}
        ${(g.prs ?? []).map(p => html`<span key=${p.n} class="ghl-chip">PR #${p.n}${p.draft ? ` · ${t.gh.draft}` : ''}</span>`)}
        ${g.task ? html`<span class="ghl-chip ghl-chip-task" title=${t.gh.taskChipTitle}>${ghPlaceChip(it, g, t)}</span>` : null}
        ${g.untasked ? html`<span class="ghl-chip ghl-chip-untasked" title=${t.gh.untaskedChipTitle}>${t.gh.untaskedChip}</span>` : null}
        ${it.tab ? html`<${Chip} token=${it.tab.live ? 'success' : 'on-surface-muted'}>${t.gh.agentChip(t.state?.[it.tab.state] ?? it.tab.state)}<//>` : null}
        ${g.quiet ? html`<span class="ghl-chip ghl-chip-quiet">${t.gh.quietChip(g.quiet)}</span>` : null}
        ${g.author ? html`<span class="ghl-author muted">${byMe ? (pick ? html`<button type="button" class="gh-person ghl-pick"
          title=${t.gh.pickTitle.author} onClick=${e => { e.stopPropagation(); pick('author', GH_ME) }}>${t.gh.byYou}</button>` : t.gh.byYou)
          : html`${t.gh.openedBy} <${RowPerson} login=${g.author} me=${me} dim="author" pick=${pick} />`}</span>` : null}
        ${g.note ? html`<span class="muted small">${g.note}</span>` : null}
      </p>
    </div>
    <div class="ghl-side">
      ${people.length ? html`<span class="ghl-people"><span class="ghl-people-label muted small">${t.gh.assigned}</span> ${people.slice(0, SHOWN_PEOPLE)
          .map((p, i) => html`${i ? ', ' : ''}<${RowPerson} key=${p} login=${p} me=${me} dim="assignee" pick=${pick} />`)}${people.length > SHOWN_PEOPLE
          ? html`, <span class="gh-person mono muted" title=${people.slice(SHOWN_PEOPLE).map(p => `@${p}`).join(', ')}>+${people.length - SHOWN_PEOPLE}</span>` : null}</span>`
        : html`<span class="ghl-people ghl-nobody muted small">${t.gh.nobodyAssigned}</span>`}
      <span class="muted small" title=${g.changed ?? ''}>${ago(g.changed)}</span>
    </div>
    <div class="ghl-acts btn-row">
      <${GhStart} it=${it} row=${settleRow} page=${page} section=${section} s=${s} c=${c} />
      ${settleRow ? html`<${SettleMenu} rows=${[settleRow]} s=${s} c=${c} />` : null}
      ${it.link?.kind === 'web' ? html`<a class="btn btn-ghost btn-xs" href=${it.link.href} target="_blank" rel="noopener noreferrer"
        title=${t.openLink} aria-label=${t.openLink}><${Icon} name="external" size=${14} /></a>` : null}
    </div>
  </li>`
}

/** What a board says of itself under its head in the list (round 6: the tile per board is gone): which cards it
 *  shows (its switch, chosen in the settings), how many are open on it, by state, and where it was cut */
function BoardFacts({ b }) {
  const t = T()
  const states = BOARD_STATES.filter(k => b.counts?.[k])
  const open = b.open ?? states.reduce((n, k) => n + b.counts[k], 0)
  return html`<p class="ghb-legend ghl-facts muted small">
    ${t.gh.boardMode[b.mode] ? html`<span>${t.gh.boardMode[b.mode]}</span>` : null}
    <span>${t.gh.boardOpen(open)}</span>
    ${states.map(k => html`<span key=${k}><span class=${`ghb-dot tk-${STATE_TOKEN[k]}`}></span>${b.counts[k]} ${t.gh.state[k]}</span>`)}
    ${b.capped ? html`<span>${t.gh.capped(b.capped)}</span>` : null}
  </p>`
}

/** The rows of a github-work section under their board: a one-line head per board (its count and a bar of
 *  its rows' states) that folds, the board's facts under it, the rows in the work's order or newest first, a
 *  search over everything a row names. "Group by board" off (kept per viewer): one list, each row names its board */
export function GitHubList({ items, page, section, s, c, byKey, filter = null, setFilter = null, me = ghMyLogin(items) }) {
  const t = T()
  // a click on a name on a row sets that filter beside the choices made (round 6d)
  const pick = setFilter ? (d, v) => setFilter({ ...(filter ?? {}), [d]: v }) : null
  const grouped = s.ui?.ghGroup !== false
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
      <${Btn} size="xs" variant="ghost" cls="ghl-group-toggle" pressed=${grouped} onClick=${() => c.setGhGroup(!grouped)}>${t.gh.groupByBoard}<//>
      ${grouped && groups.length > 1 ? html`<${Btn} size="xs" variant="ghost" icon="chevronDown" onClick=${foldAll}>${allFolded ? t.gh.unfoldAll : t.gh.foldAll}<//>` : null}
    </div>
    ${!shown.length ? html`<p class="muted">${t.filterNone}</p>` : !grouped ? html`<ul class="ghl-rows">${ghSortRows(shown, by).map(it => html`<${GhRow}
      key=${it.index} it=${it} page=${page} section=${section.id} s=${s} c=${c} byKey=${byKey} grouped=${false} me=${me} pick=${pick} />`)}</ul>` : groups.map(g => {
      const rows = ghSortRows(shown.filter(it => (it.group ?? '') === g), by)
      const isFolded = folded.has(g)
      const counts = rows.reduce((n, it) => ({ ...n, [it.gh?.state ?? 'new']: (n[it.gh?.state ?? 'new'] ?? 0) + 1 }), {})
      const board = (section.boards ?? []).find(b => b.name === g && b.mode !== 'off')
      return html`<section class="ghl-group" key=${g}>
        <button type="button" class="ghl-head" aria-expanded=${String(!isFolded)} onClick=${() => fold(g)}>
          <span class=${`ghl-chev${isFolded ? '' : ' is-open'}`} aria-hidden="true">›</span>
          <span class="ghl-head-name">${g || t.groupOther}</span>
          <span class="sec-count mono">${rows.length}</span>
          <span class="ghb-bar ghl-head-bar" aria-hidden="true">${BOARD_STATES.filter(k => counts[k]).map(k => html`<span key=${k}
            class=${`ghb-seg tk-${STATE_TOKEN[k]}`} style=${{ flexGrow: counts[k] }}></span>`)}</span>
        </button>
        ${board ? html`<${BoardFacts} b=${board} />` : null}
        ${isFolded ? null : html`<ul class="ghl-rows">${rows.map(it => html`<${GhRow} key=${it.index} it=${it} page=${page}
          section=${section.id} s=${s} c=${c} byKey=${byKey} me=${me} pick=${pick} />`)}</ul>`}
      </section>`
    })}
  </div>`
}
