// SPDX-License-Identifier: MIT
// Talking to the local bridge-cockpit server: fetch wrappers with the CSRF header and the
// contract's error format, and an EventSource wrapper that reconnects.
//
// Every call resolves to {status, ok, data, error}; nothing throws on HTTP errors, so
// the caller can treat 202 and 409 (relay offline) as answers. A network failure gives
// status 0 and error code "network".

const EVENTS = ['hello', 'state', 'view', 'view_pages', 'tabs', 'loading', 'note', 'relay', 'relay_state', 'alert', 'sessions', 'quick', 'quick_live', 'agents', 'triage', 'home', 'launch', 'ticker', 'guide', 'workspaces', 'tour', 'describe', 'acks']

function failure(status, code, message) {
  return { status, ok: false, data: null, error: { code, message, field: null } }
}

async function parse(res) {
  let body = null
  try {
    body = await res.json()
  } catch {
    body = null
  }
  if (res.ok && body && body.ok !== false) return { status: res.status, ok: true, data: body, error: null }
  const error = body && body.error && typeof body.error === 'object'
    ? { code: String(body.error.code ?? 'unknown'), message: String(body.error.message ?? ''), field: body.error.field ?? null }
    : { code: res.status === 401 ? 'unauthorized' : 'unknown', message: res.statusText || '', field: null }
  return { status: res.status, ok: false, data: body, error }
}

/** The real transport: same-origin fetch and EventSource */
function httpTransport() {
  return {
    // the address of a file the page links rather than fetches (a document of a task): the path itself
    href: p => p,
    async get(path) {
      try {
        const res = await fetch(path, { credentials: 'same-origin', headers: { Accept: 'application/json' }, cache: 'no-store' })
        return await parse(res)
      } catch (e) {
        return failure(0, 'network', String(e && e.message ? e.message : e))
      }
    },
    async post(path, body, csrf) {
      try {
        const res = await fetch(path, {
          method: 'POST',
          credentials: 'same-origin',
          cache: 'no-store',
          headers: { 'Content-Type': 'application/json', Accept: 'application/json', 'X-Bridge-Token': csrf ?? '' },
          body: JSON.stringify(body ?? {}),
        })
        return await parse(res)
      } catch (e) {
        return failure(0, 'network', String(e && e.message ? e.message : e))
      }
    },
    events(handlers, onConn) {
      let es = null
      let closed = false
      let timer = null
      let delay = 3000
      const open = () => {
        if (closed) return
        onConn('connecting')
        es = new EventSource('/api/events')
        es.onopen = () => {
          delay = 3000
          onConn('open')
        }
        es.onerror = () => {
          if (closed) return
          // Any error means the data on the page no longer updates: a stopped server leaves the
          // browser in CONNECTING (it retries by itself, retry: 3000), a refusal closes the stream.
          // Both report 'down'; the caller probes /api/bootstrap meanwhile.
          onConn('down')
          if (es.readyState === EventSource.CLOSED) {
            // refused (for example 401 after a restart) or gone for good: reopen with backoff
            es.close()
            clearTimeout(timer)
            timer = setTimeout(open, delay)
            delay = Math.min(delay * 2, 30000)
          }
        }
        for (const name of EVENTS) {
          es.addEventListener(name, ev => {
            let payload = null
            try {
              payload = JSON.parse(ev.data)
            } catch {
              return
            }
            const fn = handlers[name]
            if (fn) fn(payload)
          })
        }
      }
      open()
      return {
        close() {
          closed = true
          clearTimeout(timer)
          if (es) es.close()
        },
      }
    },
  }
}

/** `&from=…&to=…` of a range of days, each where it is set */
const rangeQuery = days => `${days?.from ? `&from=${days.from}` : ''}${days?.to ? `&to=${days.to}` : ''}`

/**
 * The API used by the app. `transport` defaults to the real server; the mock mode
 * passes an in-page stand-in with the same three methods.
 */
export function createApi(line = httpTransport()) {
  let csrf = null
  // a person's page (access.py): bootstrap names the routes and verbs that are theirs, the rest never leaves. It
  // answers as a route an older server does not have, which every loader takes for "nothing here"
  let routes = null
  let verbs = null
  const notHere = () => Promise.resolve({ status: 404, ok: false, data: null, error: { code: 'not_here', message: '', field: null } })
  const open = path => !routes || routes.has(String(path).split('?')[0])
  const transport = { ...line,
    get: path => (open(path) ? line.get(path) : notHere()),
    post: (path, body, token) => (open(path) ? line.post(path, body, token) : notHere()) }
  return {
    setCsrf(token) {
      csrf = token
    },
    setAccess(person) {
      routes = person ? new Set(person.routes ?? []) : null
      verbs = person ? new Set(person.verbs ?? []) : null
    },
    get: path => transport.get(path),
    post: (path, body) => transport.post(path, body, csrf),
    bootstrap: () => transport.get('/api/bootstrap'),
    state: () => transport.get('/api/state'),
    action: (verb, args) => (verbs && !verbs.has(verb) ? notHere() : transport.post('/api/action', { verb, args: args ?? {} }, csrf)),
    ask: (kind, args, extra) => transport.post('/api/ask', { kind, args: args ?? {}, ...(extra ?? {}) }, csrf),
    // the recommended model for each row an agent may start with (launch, Auto); at most 20 keys
    route: keys => transport.post('/api/route', { keys }, csrf),
    reload: fresh => transport.post('/api/reload', { fresh: !!fresh }, csrf),
    // which page or view was opened: one audit line on the server (page_view), the files view's measure
    seen: (page, view) => transport.post('/api/seen', view ? { page, view } : { page }, csrf),
    // the click origin log: a batch of {kind, page, view, area, control, verb, n}, never content (usage.jsonl)
    clicks: events => transport.post('/api/clicks', { events }, csrf),
    inbox: id => transport.get(`/api/inbox?id=${encodeURIComponent(id)}`),
    // path: one folder of the slug (work/done/<month>/<slug>, a closed copy the search found), else the open one first
    task: (slug, path) => transport.get(`/api/task?slug=${encodeURIComponent(slug)}${path ? `&path=${encodeURIComponent(path)}` : ''}`),
    // one file of a task's folder as /api/task lists it (files), read in place in the files view
    taskFile: (slug, file, path) => transport.get(`/api/task?slug=${encodeURIComponent(slug)}&file=${encodeURIComponent(file)}${path ? `&path=${encodeURIComponent(path)}` : ''}`),
    // the files view's search over every task, stream and closed task, the log and its archive (work-find.py)
    find: q => transport.get(`/api/find?q=${encodeURIComponent(q)}`),
    // when it was done or discussed: every line of the log and its archive, the meetings, the closed tasks and the raw
    // transcripts that holds every word, by day (work-find.py --history)
    // days: {from, to} of a log page's time range, which narrows it before the list is cut
    timeline: (q, days) => transport.get(`/api/timeline?q=${encodeURIComponent(q)}${rangeQuery(days)}`),
    // a log page's time range (bridge_cockpit/logrange.py): the rows of the log for {from, to} (days, null for the log's
    // first day and today) with the own commits of the rail's commits section; with sources 'other' and q the meetings,
    // closed tasks and transcripts one entry each
    // the rows come compact, without their text: `ids` with the answer's `rev` fetch the text of some, `q` with `rev`
    // the ids of the rows that hold every word
    logRange: ({ from = null, to = null, commits = null, sources = null, q = null, ids = null, rev = null } = {}) => transport.get(`/api/logrange?${[
      from ? `from=${from}` : '', to ? `to=${to}` : '', commits ? `commits=${encodeURIComponent(commits)}` : '',
      sources ? `sources=${encodeURIComponent(sources)}` : '', q ? `q=${encodeURIComponent(q)}` : '',
      ids ? `ids=${ids.join(',')}` : '', rev ? `rev=${encodeURIComponent(rev)}` : ''].filter(Boolean).join('&')}`),
    // the records of the files tab's start: every task, stream and closed task with its state, area and last change
    records: () => transport.get('/api/records'),
    github: (ref, fresh) => transport.get(`/api/github?ref=${encodeURIComponent(ref)}${fresh ? '&fresh=1' : ''}`),
    // the boards of one issue and what Set to review and Done would set there (issue_transition.py plan)
    issue: ref => transport.get(`/api/issue?ref=${encodeURIComponent(ref)}`),
    page: (page, section) => transport.get(`/api/page?page=${encodeURIComponent(page)}&section=${encodeURIComponent(section)}`),
    relay: () => transport.get('/api/relay'),
    // since: the hash of the screen the page holds; the server then answers unchanged without the text
    tabHistory: (ref, q, before) => transport.get(`/api/tab-history?ref=${encodeURIComponent(ref)}${q ? `&q=${encodeURIComponent(q)}` : ''}${before != null ? `&before=${before}` : ''}`),
    tabScreen: (ref, since, fast) => transport.get(`/api/tab/screen?ref=${encodeURIComponent(ref)}${since ? `&since=${encodeURIComponent(since)}` : ''}${fast ? '&fast=1' : ''}`),
    // Work through, the Activity of a point (cached 20 s on the server; fresh skips it, after a note or an attachment)
    activity: (key, fresh) => transport.get(`/api/flow/activity?key=${encodeURIComponent(key)}${fresh ? '&fresh=1' : ''}`),
    // a document attached to the task of a point, its bytes as standard base64 (the one POST with a larger body cap)
    attach: (key, name, data) => transport.post('/api/flow/attach', { key, name, data }, csrf),
    // the link of a document in a task's deliverables/, opened in a new tab and never fetched by the page; the demo's
    // transport gives a Blob of invented text in its place
    docHref: (slug, path) => {
      const p = `/api/flow/doc?slug=${encodeURIComponent(slug)}&path=${encodeURIComponent(path)}`
      return transport.href ? transport.href(p) : p
    },
    events: (handlers, onConn) => {
      // A page in a background browser tab tells the server so, and the server stops polling the
      // agent tabs, the full pass and the ticker for it; coming back asks for one poll at once.
      let client = null
      const doc = globalThis.document
      const hidden = () => doc?.visibilityState === 'hidden'
      const tell = visible => { if (client) transport.post('/api/presence', { client, visible }, csrf) }
      doc?.addEventListener?.('visibilitychange', () => tell(!hidden()))
      const hello = p => {
        client = p?.client ?? null      // a new id on every reconnect
        if (hidden()) tell(false)
        if (handlers.hello) handlers.hello(p)
      }
      return transport.events({ ...handlers, hello }, onConn)
    },
  }
}
