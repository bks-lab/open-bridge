// SPDX-License-Identifier: MIT
// Talking to the local bridge-cockpit server: fetch wrappers with the CSRF header and the
// contract's error format, and an EventSource wrapper that reconnects.
//
// Every call resolves to {status, ok, data, error}; nothing throws on HTTP errors, so
// the caller can treat 202 and 409 (relay offline) as answers. A network failure gives
// status 0 and error code "network".

const EVENTS = ['hello', 'state', 'view', 'tabs', 'loading', 'note', 'relay', 'relay_state', 'alert', 'sessions', 'quick', 'quick_live', 'agents', 'triage', 'home', 'launch', 'ticker']

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

/**
 * The API used by the app. `transport` defaults to the real server; the mock mode
 * passes an in-page stand-in with the same three methods.
 */
export function createApi(transport = httpTransport()) {
  let csrf = null
  return {
    setCsrf(token) {
      csrf = token
    },
    get: path => transport.get(path),
    post: (path, body) => transport.post(path, body, csrf),
    bootstrap: () => transport.get('/api/bootstrap'),
    state: () => transport.get('/api/state'),
    action: (verb, args) => transport.post('/api/action', { verb, args: args ?? {} }, csrf),
    ask: (kind, args, extra) => transport.post('/api/ask', { kind, args: args ?? {}, ...(extra ?? {}) }, csrf),
    // the recommended model for each row an agent may start with (launch, Auto); at most 20 keys
    route: keys => transport.post('/api/route', { keys }, csrf),
    reload: fresh => transport.post('/api/reload', { fresh: !!fresh }, csrf),
    inbox: id => transport.get(`/api/inbox?id=${encodeURIComponent(id)}`),
    task: slug => transport.get(`/api/task?slug=${encodeURIComponent(slug)}`),
    github: (ref, fresh) => transport.get(`/api/github?ref=${encodeURIComponent(ref)}${fresh ? '&fresh=1' : ''}`),
    page: (page, section) => transport.get(`/api/page?page=${encodeURIComponent(page)}&section=${encodeURIComponent(section)}`),
    relay: () => transport.get('/api/relay'),
    // since: the hash of the screen the page holds; the server then answers unchanged without the text
    tabScreen: (ref, since) => transport.get(`/api/tab/screen?ref=${encodeURIComponent(ref)}${since ? `&since=${encodeURIComponent(since)}` : ''}`),
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
