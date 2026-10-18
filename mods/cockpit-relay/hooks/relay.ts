// SPDX-License-Identifier: MIT
import type { RelaySettings } from '../types'

/**
 * The relay between the cockpit (scripts/bridge-cockpit.py, scripts/lib/bridge_cockpit/relay.py) and
 * this Claude Code session, as pure functions: no `$`, so pure.test.mjs checks them without Claude Code.
 *
 * Files (docs/bridge-cockpit.md section 6), each with exactly one writer:
 *   .bridge/cockpit/relay/inbox/<id>.json           the server: a question, framed, for ONE session
 *   .bridge/cockpit/relay/done/<id>.json            the mod of the target session: what became of it
 *   .bridge/cockpit/relay/heartbeat/<session>.json  the mod of that session: alive, busy, in flight
 *
 * Why only the server's questions are submitted: each inbox record carries `mac`, an HMAC-SHA256 over
 * `id|target_session|text` keyed by relay.key, which the server keeps OUTSIDE the Bridge in a 0700
 * directory ($BRIDGE_COCKPIT_KEY_DIR, else ~/.local/state/bridge-cockpit). A record this session cannot
 * verify is rejected: a process that can only write inside the repo (an agent tab) cannot hand this
 * session a prompt.
 *
 * Why a question is submitted at most once: the server names one target session per record
 * (the heartbeat whose surface is the control tab); every other session ignores the record
 * without writing anything. The target session marks the id as handled (in flight, in its
 * store, in done/) BEFORE it submits, never submits while a turn runs or another question is
 * in flight, and skips every id it has a done file or a store entry for.
 *
 * This file came over from briefing-ui (hooks/relay.ts) when the relay became a mod of its own, so
 * the cockpit keeps reaching the control session after the briefing card retires.
 */

export const RELAY_DIR = '.bridge/cockpit/relay'
export const RELAY_INBOX = `${RELAY_DIR}/inbox`
export const RELAY_DONE = `${RELAY_DIR}/done`
export const RELAY_HEARTBEAT = `${RELAY_DIR}/heartbeat`
/** Store key: the ids this session has handled, newest last */
export const STORE_RELAY_DONE = 'cockpit-relay:relay-done'
/** How many handled ids the store keeps */
export const DONE_KEEP = 200
/** The answer written back is cut to this many characters (relay.py ANSWER_MAX) */
export const ANSWER_MAX = 20000
/** A framed question longer than this is refused (the server caps the text at 4000) */
export const TEXT_MAX = 12000
export const HEARTBEAT_MS = 5000
export const POLL_MS = 2000
/** A turn that starts this soon after the submit, with no text at all, carries the question */
export const CORRELATE_MS = 60000
/** The key file's name in the key directory (relay.py KEY_FILE) */
export const KEY_FILE = 'relay.key'
/** Where the server keeps the key without $BRIDGE_COCKPIT_KEY_DIR, below $HOME (relay.py default_key_dir) */
export const KEY_HOME_DIR = '.local/state/bridge-cockpit'
/** In flight for longer than this: done `stuck`, the slot is free again (relay.py STUCK_MS) */
export const STUCK_MS = 30 * 60000
/** Must equal .claude-plugin/plugin.json version (pure.test.mjs checks it) */
export const MOD_VERSION = '0.1.0'

const ID = /^\d{8}T\d{6}-[0-9a-f]{8}$/
const SESSION = /^[A-Za-z0-9-]{8,64}$/

export type RelayStatus = 'submitted' | 'answered' | 'aborted' | 'error' | 'expired' | 'stuck' | 'rejected'
/** Every status ends the mod's part except `submitted`, which a turn later advances; none allows a second submit */
export const STATUSES: readonly RelayStatus[] = ['submitted', 'answered', 'aborted', 'error', 'expired', 'stuck', 'rejected']

/** inbox/<id>.json as the server writes it */
export type InboxRecord = {
  v: number
  id: string
  created_ms: number
  expires_ms: number
  target_session: string
  kind: string
  text: string
  chars: number
}

/** done/<id>.json as the mod writes it */
export type DoneRecord = {
  v: 1
  id: string
  session: string
  status: RelayStatus
  turn_id: string | null
  answer: string | null
  at_ms: number
}

/** heartbeat/<session>.json as the mod writes it */
export type Heartbeat = {
  v: 1
  session: string
  surface: string | null
  at_ms: number
  busy: boolean
  in_flight: string | null
  mod_version: string
}

/**
 * One file of relay/inbox: its name, what JSON.parse made of it (null when unreadable), and whether
 * its mac verified with the server's key (only true lets it be submitted)
 */
export type RelayEntry = { name: string; record: unknown; verified?: boolean }

/** What one poll does: write `expired` / `rejected` for these, and submit at most one */
export type RelayPick = { expire: InboxRecord[]; reject: InboxRecord[]; submit: InboxRecord | null }

/**
 * The block the relay reads: `cockpit:`, as scripts/lib/bridge_cockpit/config.py load_web_config reads it.
 * `raw` is what the config reader printed.
 */
export function relayBlock(raw: unknown): unknown {
  const r = isObject(raw) ? raw : {}
  return r.cockpit
}

/**
 * The relay's settings: enabled and relay each only when true (the server's rule), and the language
 * of its notes: the block's own, else language.conversation.
 */
export function parseRelayConfig(raw: unknown): RelaySettings {
  const r = isObject(raw) ? raw : {}
  const w = relayBlock(r)
  const b = isObject(w) ? w : {}
  const lang = [b.language, r.language].find(v => typeof v === 'string' && v !== '')
  return { enabled: b.enabled === true, relay: b.relay === true,
    language: typeof lang === 'string' && lang.toLowerCase().startsWith('de') ? 'de' : 'en' }
}

function isObject(v: unknown): v is Record<string, unknown> {
  return typeof v === 'object' && v !== null && !Array.isArray(v)
}

/** A tmux pane id as $TMUX_PANE carries it */
const TMUX_PANE = /^%\d{1,9}$/

/**
 * The terminal place this session runs in, for the heartbeat: the cmux surface when cmux runs it, else
 * the tmux pane ("%3"), else null. The server matches it against the control tab's id; a session it
 * cannot place still heartbeats and is picked when it is the only fresh one.
 */
export function surfaceOf(cmuxSurface: string | null | undefined, tmuxPane: string | null | undefined): string | null {
  if (typeof cmuxSurface === 'string' && cmuxSurface.trim()) return cmuxSurface.trim()
  if (typeof tmuxPane === 'string' && TMUX_PANE.test(tmuxPane.trim())) return tmuxPane.trim()
  return null
}

export function isRelayId(id: unknown): id is string {
  return typeof id === 'string' && ID.test(id)
}

/** A session id the server accepts as a heartbeat file name */
export function isSessionId(id: unknown): id is string {
  return typeof id === 'string' && SESSION.test(id)
}

/** The text carries the marker of exactly this record up front */
export function isFramed(text: unknown, id: string): boolean {
  return typeof text === 'string' && text.startsWith(`[web:${id}]`)
}

/** The marker of any record in a turn's text, or null */
export function markerIn(text: unknown): string | null {
  if (typeof text !== 'string') return null
  const hit = /\[web:(\d{8}T\d{6}-[0-9a-f]{8})\]/.exec(text)
  return hit?.[1] ?? null
}

/**
 * Sort the inbox of this session into what to write and what to submit.
 *
 * Ignored without a trace: files that are not `<id>.json` of a valid id, records for another
 * session (its own mod answers them), ids already handled (`doneIds`: done files and the store).
 * For this session, in file name order: past `expires_ms` gives `expire`; no matching marker,
 * a version other than 1, no expiry, an oversized text or a mac that did not verify gives `reject`; the first remaining record is
 * submitted, but only while no turn runs and nothing is in flight. The rest waits for a later poll.
 */
export function pickNext(entries: readonly RelayEntry[], doneIds: Iterable<string>, session: string, now: number,
  busy: boolean, inFlight: string | null): RelayPick {
  const handled = new Set(doneIds)
  const out: RelayPick = { expire: [], reject: [], submit: null }
  const sorted = [...entries].sort((a, b) => (a.name < b.name ? -1 : a.name > b.name ? 1 : 0))
  for (const { name, record, verified } of sorted) {
    if (typeof record !== 'object' || record === null) continue
    const r = record as Record<string, unknown>
    if (!isRelayId(r.id) || name !== `${r.id}.json`) continue
    if (r.target_session !== session || handled.has(r.id) || r.id === inFlight) continue
    const rec = r as unknown as InboxRecord
    if (typeof r.expires_ms === 'number' && now > r.expires_ms) {
      out.expire.push(rec)
      continue
    }
    if (r.v !== 1 || typeof r.expires_ms !== 'number' || !isFramed(r.text, r.id)
      || (r.text as string).length > TEXT_MAX || verified !== true) {
      out.reject.push(rec)
      continue
    }
    if (out.submit === null && !busy && inFlight === null) out.submit = rec
  }
  return out
}

/** The answer as the done file carries it: cut to ANSWER_MAX characters, null when there is none */
export function clipAnswer(text: unknown): string | null {
  if (typeof text !== 'string' || !text.trim()) return null
  return text.length > ANSWER_MAX ? text.slice(0, ANSWER_MAX) : text
}

/** turn.complete's reason as a done status */
export function reasonToStatus(reason: unknown): RelayStatus {
  if (reason === 'answer') return 'answered'
  if (reason === 'aborted') return 'aborted'
  return 'error'
}

export function doneRecord(id: string, session: string, status: RelayStatus, turnId: string | null,
  answer: unknown, now: number): DoneRecord {
  return { v: 1, id, session, status, turn_id: turnId, answer: clipAnswer(answer), at_ms: now }
}

export function heartbeat(session: string, surface: string | null, now: number, busy: boolean,
  inFlight: string | null): Heartbeat {
  return { v: 1, session, surface: surface || null, at_ms: now, busy, in_flight: inFlight, mod_version: MOD_VERSION }
}

/** The ids of a done/ listing: `<id>.json` of valid ids only */
export function doneIdsOf(names: readonly string[]): string[] {
  return names.filter(n => n.endsWith('.json')).map(n => n.slice(0, -5)).filter(isRelayId)
}

/** Remember an id as handled: newest last, at most DONE_KEEP, no duplicates */
export function rememberId(list: unknown, id: string): string[] {
  const prev = Array.isArray(list) ? list.filter((x): x is string => typeof x === 'string' && x !== id) : []
  return [...prev, id].slice(-DONE_KEEP)
}

// ---------------------------------------------------------------- authenticity (the server's key)

/** Where the server keeps relay.key: $BRIDGE_COCKPIT_KEY_DIR, else ~/.local/state/bridge-cockpit; null without either */
export function relayKeyPath(keyDir: string | null | undefined, home: string | null | undefined): string | null {
  if (keyDir) return `${keyDir.replace(/\/$/, '')}/${KEY_FILE}`
  if (home) return `${home.replace(/\/$/, '')}/${KEY_HOME_DIR}/${KEY_FILE}`
  return null
}

/** The key as relay.key holds it: 64 lowercase hex characters */
export function isRelayKey(key: unknown): key is string {
  return typeof key === 'string' && /^[0-9a-f]{64}$/.test(key)
}

const BLOCK = 64
const K = new Uint32Array([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2,
])

/**
 * SHA-256 (FIPS 180-4) of the concatenated parts, synchronous: crypto.subtle.digest would settle
 * outside the session's clock, and a poll has to finish within it.
 */
export function sha256(...parts: Uint8Array[]): Uint8Array {
  const len = parts.reduce((n, p) => n + p.length, 0)
  const total = Math.ceil((len + 9) / BLOCK) * BLOCK
  const msg = new Uint8Array(total)
  let at = 0
  for (const p of parts) {
    msg.set(p, at)
    at += p.length
  }
  msg[len] = 0x80
  const bits = len * 8
  const view = new DataView(msg.buffer)
  view.setUint32(total - 8, Math.floor(bits / 0x100000000))
  view.setUint32(total - 4, bits >>> 0)
  const h = new Uint32Array([0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a, 0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19])
  const w = new Uint32Array(64)
  const rot = (x: number, n: number) => (x >>> n) | (x << (32 - n))
  for (let off = 0; off < total; off += BLOCK) {
    for (let i = 0; i < 16; i++) w[i] = view.getUint32(off + i * 4)
    for (let i = 16; i < 64; i++) {
      const a = w[i - 15] ?? 0
      const b = w[i - 2] ?? 0
      const s0 = rot(a, 7) ^ rot(a, 18) ^ (a >>> 3)
      const s1 = rot(b, 17) ^ rot(b, 19) ^ (b >>> 10)
      w[i] = ((w[i - 16] ?? 0) + s0 + (w[i - 7] ?? 0) + s1) >>> 0
    }
    let [a, b, c, d, e, f, g, hh] = [h[0] ?? 0, h[1] ?? 0, h[2] ?? 0, h[3] ?? 0, h[4] ?? 0, h[5] ?? 0, h[6] ?? 0, h[7] ?? 0]
    for (let i = 0; i < 64; i++) {
      const t1 = (hh + (rot(e, 6) ^ rot(e, 11) ^ rot(e, 25)) + ((e & f) ^ (~e & g)) + (K[i] ?? 0) + (w[i] ?? 0)) >>> 0
      const t2 = ((rot(a, 2) ^ rot(a, 13) ^ rot(a, 22)) + ((a & b) ^ (a & c) ^ (b & c))) >>> 0
      hh = g
      g = f
      f = e
      e = (d + t1) >>> 0
      d = c
      c = b
      b = a
      a = (t1 + t2) >>> 0
    }
    const add = [a, b, c, d, e, f, g, hh]
    for (let i = 0; i < 8; i++) h[i] = ((h[i] ?? 0) + (add[i] ?? 0)) >>> 0
  }
  const out = new Uint8Array(32)
  const ov = new DataView(out.buffer)
  for (let i = 0; i < 8; i++) ov.setUint32(i * 4, h[i] ?? 0)
  return out
}

/** HMAC-SHA256 (RFC 2104, hex) over `id|session|text` with the key's ASCII bytes, as the server computes it */
export function relayMac(key: string, id: string, session: string, text: string): string {
  const enc = new TextEncoder()
  let k = enc.encode(key)
  if (k.length > BLOCK) k = sha256(k)
  const ipad = new Uint8Array(BLOCK)
  const opad = new Uint8Array(BLOCK)
  for (let i = 0; i < BLOCK; i++) {
    const b = k[i] ?? 0
    ipad[i] = b ^ 0x36
    opad[i] = b ^ 0x5c
  }
  const inner = sha256(ipad, enc.encode(`${id}|${session}|${text}`))
  const outer = sha256(opad, inner)
  return [...outer].map(b => b.toString(16).padStart(2, '0')).join('')
}

/** The record's mac matches the server's key (compared in full, without an early exit) */
export function verifyMac(key: string | null, record: unknown): boolean {
  if (!isRelayKey(key) || typeof record !== 'object' || record === null) return false
  const r = record as Record<string, unknown>
  if (typeof r.mac !== 'string' || typeof r.id !== 'string' || typeof r.target_session !== 'string'
    || typeof r.text !== 'string') return false
  const want = relayMac(key, r.id, r.target_session, r.text)
  if (want.length !== r.mac.length) return false
  let diff = 0
  for (let i = 0; i < want.length; i++) diff |= want.charCodeAt(i) ^ r.mac.charCodeAt(i)
  return diff === 0
}

// ---------------------------------------------------------------- which turn carries the question

/**
 * The turn that starts now carries the question in flight: its text shows the record's marker, or it
 * has no text at all and starts within CORRELATE_MS of the submit. A turn with any other text is never
 * the web turn (the plugin's prompt always carries the marker): a prompt typed in that moment keeps
 * its own answer.
 */
export function isFlightTurn(text: unknown, flightId: string, flightAt: number, now: number): boolean {
  const marker = markerIn(text)
  if (marker !== null) return marker === flightId
  const empty = typeof text !== 'string' || text.trim() === ''
  return empty && now - flightAt <= CORRELATE_MS
}

/** The last assistant text after the last user message: what the web turn itself said, '' when nothing */
export function answerSinceLastUser(rows: readonly { role: string; text: string }[]): string {
  for (let i = rows.length - 1; i >= 0; i--) {
    const row = rows[i]
    if (!row) continue
    if (row.role === 'user' && row.text.trim()) return ''
    if (row.role === 'assistant' && row.text.trim()) return row.text
  }
  return ''
}

// ---------------------------------------------------------------- words

/** The mod's own words: one table per language, identical keys, English the default */
export type Strings = {
  expired: (n: number) => string
  rejected: (n: number) => string
  stuck: string
}

const en: Strings = {
  expired: n => `Cockpit: ${n} question(s) expired, not asked`,
  rejected: n => `Cockpit: ${n} question(s) without a valid signature refused`,
  stuck: 'Cockpit: a question has had no answer for 30 min, the next one may come',
}

const de: Strings = {
  expired: n => `Cockpit: ${n} Frage(n) abgelaufen, nicht gestellt`,
  rejected: n => `Cockpit: ${n} Frage(n) ohne gültige Signatur abgewiesen`,
  stuck: 'Cockpit: eine Frage hängt seit 30 Min. ohne Antwort, die nächste darf kommen',
}

export const TABLES: Record<'de' | 'en', Strings> = { de, en }
