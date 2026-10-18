// SPDX-License-Identifier: MIT
import { atom, read, update } from 'claude-code'
import type { EngineInterface, Register } from 'claude-code'

import type { RelaySettings } from '../types'
import {
  answerSinceLastUser, doneIdsOf, doneRecord, heartbeat, HEARTBEAT_MS, isFlightTurn, isRelayId, isRelayKey,
  isSessionId, parseRelayConfig, pickNext, POLL_MS, reasonToStatus, RELAY_DONE, RELAY_HEARTBEAT, RELAY_INBOX,
  relayKeyPath, rememberId, STORE_RELAY_DONE, STUCK_MS, surfaceOf, TABLES, verifyMac,
} from './relay'
import type { InboxRecord, RelayEntry, RelayStatus, Strings } from './relay'

/**
 * cockpit-relay: the cockpit (scripts/bridge-cockpit.py) reaches this Claude Code session.
 *
 * The cockpit server writes a signed question for exactly one session into .bridge/cockpit/relay/inbox;
 * this mod heartbeats so the server can pick a session, submits the question as a prompt of its own,
 * and writes what became of it to done/. It does nothing else: no card, no command, no terminal
 * control. It came out of briefing-ui so the relay outlives the briefing card, and it needs no cmux:
 * the heartbeat names the cmux surface or the tmux pane when there is one, and null otherwise.
 *
 * Early access: written against the function hooks API of Claude Code 2.1.291, which may change
 * between versions.
 */

/** The relay settings: null outside a Bridge, in agent tabs, in a -p run and when the config is unreadable */
const settings = atom({ plugin: 'cockpit-relay', key: 'settings' } as const, null as RelaySettings | null)
/** A main turn runs in this session: the relay never submits into it */
const busy = atom({ plugin: 'cockpit-relay', key: 'busy' } as const, false)
/** The one cockpit question in flight in this session */
const flight = atom({ plugin: 'cockpit-relay', key: 'flight' } as const, null)
/** Questions marked stuck while their turn still ran: turn.complete still writes their answer */
const late = atom({ plugin: 'cockpit-relay', key: 'late' } as const, [])
/** The session id this session heartbeats under; null while the relay is off */
const relaySession = atom({ plugin: 'cockpit-relay', key: 'session' } as const, null)

/**
 * Reads only what the relay needs; which block counts is decided in relay.ts (relayBlock), so the rule
 * is tested without Python.
 */
const READ_CONFIG = [
  'import json, yaml',
  "c = yaml.safe_load(open('bridge-config.yaml', encoding='utf-8')) or {}",
  'c = c if isinstance(c, dict) else {}',
  "l = c.get('language')",
  "print(json.dumps({'cockpit': c.get('cockpit'),",
  "  'language': l.get('conversation') if isinstance(l, dict) else l}, default=str))",
].join('\n')

/** The interpreters tried in turn for the config reader */
const PYTHONS = ['python3', 'python3.14', 'python3.13', 'python3.12', 'python3.11', '/opt/homebrew/bin/python3.14', '/usr/bin/python3']

let words: Strings = TABLES.en

/** Feedback as a brief toast: the mod has no surface of its own */
function note($: EngineInterface, text: string): void {
  $.ui.toast(text)
}

/** The relay settings of this Bridge; null outside a Bridge or when the config cannot be read */
async function loadSettings($: EngineInterface): Promise<RelaySettings | null> {
  const cwd = await $.session.cwd()
  const isBridge =
    (await $.fs.exists(`${cwd}/bridge-config.yaml`)) && (await $.fs.exists(`${cwd}/scripts/bridge-cockpit.py`))
  if (!isBridge) return null
  // python3 first; when it has no PyYAML (a new Python version comes without it until it is installed
  // there), the next Python that does reads the config, so the relay does not fall silent on an update
  for (const python of PYTHONS) {
    try {
      const run = await $.process.run([python, '-c', READ_CONFIG], { cwd, timeoutMs: 15000 })
      if (run.exitCode === 0) return parseRelayConfig(JSON.parse(run.stdout))
    } catch {
      // not installed, or no answer: try the next
    }
  }
  return null
}

// ---------------------------------------------------------------- heartbeat and poll

/** A poll is running: a slow file system must not pile polls up */
let polling = false
/** Inbox files addressed to another session: read once, never again */
const foreignRecords = new Set<string>()

/** Where this session runs: the cmux surface, else the tmux pane, else null (relay.ts surfaceOf) */
async function surface($: EngineInterface): Promise<string | null> {
  return surfaceOf(await $.env.get('CMUX_SURFACE_ID'), await $.env.get('TMUX_PANE'))
}

/** The relay of one session: a heartbeat every 5 s, a look into the inbox every 2 s. */
function startRelay($: EngineInterface, session: string): void {
  const beat = async () => {
    try {
      const cur = await read($, flight)
      // signed with relay.key, read at every beat: the server may create or renew the key at any start
      await $.fs.write(`${RELAY_HEARTBEAT}/${session}.json`, JSON.stringify(heartbeat(session, await surface($),
        await $.clock.now(), await read($, busy), cur?.id ?? null, await relayKey($))))
    } catch {
      // no heartbeat: the page says the relay is offline and offers the text to copy
    }
  }
  $.clock.after(0, () => void beat())
  $.clock.every(HEARTBEAT_MS, () => void beat())
  $.clock.every(POLL_MS, () => void poll($, session))
}

async function poll($: EngineInterface, session: string): Promise<void> {
  if (polling) return
  polling = true
  try {
    await pollOnce($, session)
  } catch {
    // the next poll tries again
  } finally {
    polling = false
  }
}

/** Writes done/<id>.json (the mod is its only writer) and remembers the id as handled. */
async function relayDone($: EngineInterface, session: string, id: string, status: RelayStatus,
  turnId: string | null, answer: string | null): Promise<void> {
  if (!isRelayId(id)) return
  await $.store.set(STORE_RELAY_DONE, rememberId(await $.store.get(STORE_RELAY_DONE), id))
  try {
    // signed with relay.key: the server shows only what this session wrote
    await $.fs.write(`${RELAY_DONE}/${id}.json`,
      JSON.stringify(doneRecord(id, session, status, turnId, answer, await $.clock.now(), await relayKey($))))
  } catch {
    // the server shows the record as queued until it expires
  }
}

/** relay.key, where the server keeps it (outside the Bridge); null when it cannot be read */
async function relayKey($: EngineInterface): Promise<string | null> {
  const path = relayKeyPath(await $.env.get('BRIDGE_COCKPIT_KEY_DIR'), await $.env.get('HOME'))
  if (!path) return null
  try {
    const key = (await $.fs.read(path)).trim()
    return isRelayKey(key) ? key : null
  } catch {
    return null
  }
}

async function pollOnce($: EngineInterface, session: string): Promise<void> {
  const now = await $.clock.now()
  const cur = await read($, flight)
  if (cur && now - cur.at > STUCK_MS) {
    // Free the slot. A turn that was seen and still runs (a long plan, a permission prompt answered
    // late) keeps its claim: its turn.complete still writes the answer over `stuck`.
    await relayDone($, session, cur.id, 'stuck', cur.turnId, null)
    if (cur.turnId !== null) {
      const claim = { id: cur.id, turnId: cur.turnId }
      await update($, late, list => [...list.filter(x => x.id !== claim.id), claim].slice(-20))
    }
    await update($, flight, f => (f?.id === cur.id ? null : f))
    note($, words.stuck)
  }
  let files: string[]
  try {
    files = (await $.fs.list(RELAY_INBOX)).filter(e => e.kind === 'file' && e.name.endsWith('.json')).map(e => e.name)
  } catch {
    return
  }
  if (files.length === 0) return
  let doneNames: string[] = []
  try {
    doneNames = (await $.fs.list(RELAY_DONE)).map(e => e.name)
  } catch {
    // no done/ yet
  }
  const stored = await $.store.get(STORE_RELAY_DONE)
  const handled = new Set([...doneIdsOf(doneNames), ...(Array.isArray(stored) ? stored.filter(isRelayId) : [])])
  const entries: RelayEntry[] = []
  let key: string | null | undefined
  for (const name of files) {
    if (handled.has(name.slice(0, -5)) || foreignRecords.has(name)) continue
    let record: unknown
    try {
      record = JSON.parse(await $.fs.read(`${RELAY_INBOX}/${name}`))
    } catch {
      continue
    }
    if (typeof record === 'object' && record !== null && (record as { target_session?: unknown }).target_session !== session) {
      foreignRecords.add(name)
      continue
    }
    // Read the key only when a record for this session waits; a record it cannot verify is rejected.
    if (key === undefined) key = await relayKey($)
    entries.push({ name, record, verified: verifyMac(key, record) })
  }
  const inFlight = await read($, flight)
  const pick = pickNext(entries, handled, session, now, await read($, busy), inFlight?.id ?? null)
  for (const r of pick.expire) await relayDone($, session, r.id, 'expired', null, null)
  for (const r of pick.reject) await relayDone($, session, r.id, 'rejected', null, null)
  if (pick.expire.length) note($, words.expired(pick.expire.length))
  if (pick.reject.length) note($, words.rejected(pick.reject.length))
  if (pick.submit) await submit($, session, pick.submit)
}

/**
 * Submits one cockpit question as a prompt of its own, framed (never asUser: the model reads that the
 * cockpit-relay plugin sent it, and the text says it came from the cockpit). Everything that marks it
 * as handled happens BEFORE the submit: a reload or crash in between can lose a question, never ask it twice.
 */
async function submit($: EngineInterface, session: string, rec: InboxRecord): Promise<void> {
  const at = await $.clock.now()
  await update($, flight, () => ({ id: rec.id, at, turnId: null }))
  await relayDone($, session, rec.id, 'submitted', null, null)
  let refused = false
  try {
    // A hook that refuses the prompt resolves with { drop }: the question never entered.
    const res = await $.prompt.submit({ text: rec.text })
    refused = typeof res === 'object' && res !== null && typeof (res as { drop?: unknown }).drop === 'string'
  } catch {
    refused = true
  }
  if (refused) {
    await relayDone($, session, rec.id, 'error', null, null)
    await update($, flight, f => (f?.id === rec.id ? null : f))
  }
}

/**
 * What the cockpit turn itself said, when turn.complete brought no answer: the last assistant text after
 * the last user message (the cockpit prompt), never an earlier answer of the conversation.
 */
async function lastAnswer($: EngineInterface): Promise<string> {
  try {
    return answerSinceLastUser(await $.session.messages())
  } catch {
    return ''
  }
}

/** The relay runs in this session (settings is null wherever it must not) */
async function relayOn($: EngineInterface): Promise<boolean> {
  const s = await read($, settings)
  return s !== null && s.enabled && s.relay
}

// ---------------------------------------------------------------- Module

export const register: Register = on => {
  on('session.start', async ($, e, next) => {
    const started = await next(e)
    // A tab the Bridge started for an item never relays: the cockpit addresses the control session.
    // A -p or SDK run is never addressed either: it inherits the control tab's surface and would
    // claim its questions.
    if (!e.isInteractive || (await $.env.get('BRIDGE_TAB_SLUG'))) return started
    const found = await loadSettings($)
    if (!found) return started
    words = TABLES[found.language]
    await update($, settings, () => found)
    if (!found.enabled || !found.relay) return started
    // The server addresses a question to one session by this id; one it cannot name gets none.
    const session = await $.session.id().catch(() => '')
    if (!isSessionId(session)) return started
    await update($, relaySession, () => session)
    startRelay($, session)
    return started
  })

  // The relay follows the main loop: busy from its turn.start to its turn.complete (a subagent
  // raises no turn.start, and its turn.complete carries agentId).
  on('turn.start', async ($, e, next) => {
    try {
      if (await relayOn($)) {
        await update($, busy, () => true)
        const cur = await read($, flight)
        if (cur && cur.turnId === null) {
          // The marker, when the turn shows the text; else a turn with no text right after the submit.
          // A turn with other text is never the cockpit turn (docs/bridge-cockpit.md, known limits).
          const isOurs = isFlightTurn(e.text, cur.id, cur.at, await $.clock.now())
          if (isOurs) await update($, flight, f => (f?.id === cur.id ? { ...f, turnId: e.turnId } : f))
        }
      }
    } catch {
      // bookkeeping only: the turn runs either way
    }
    return next(e)
  })

  on('turn.complete', async ($, e, next) => {
    try {
      if (e.agentId === undefined && (await relayOn($))) {
        await update($, busy, () => false)
        const cur = await read($, flight)
        const held = (await read($, late)).find(x => x.turnId === e.turnId)
        const claim = cur && cur.turnId !== null && cur.turnId === e.turnId
          ? { id: cur.id, turnId: cur.turnId } : held ?? null
        if (claim) {
          // The transcript only stands in for a turn that ended with an answer; an aborted or failed
          // turn has none of its own.
          const answer = e.answer.trim() ? e.answer : e.reason === 'answer' ? await lastAnswer($) : ''
          if (cur?.id === claim.id) await update($, flight, () => null)
          if (held) await update($, late, list => list.filter(x => x.id !== held.id))
          await relayDone($, await $.session.id(), claim.id, reasonToStatus(e.reason), claim.turnId, answer)
        }
      }
    } catch {
      // bookkeeping only
    }
    return next(e)
  })

  // The session ends: its heartbeat says so at once (at_ms 0), so the server stops addressing it
  // instead of waiting 15 s for the heartbeat to go stale. The mod stays its only writer.
  on('session.end', async ($, e, next) => {
    try {
      const session = await read($, relaySession)
      if (session !== null) {
        await update($, relaySession, () => null)
        await $.fs.write(`${RELAY_HEARTBEAT}/${session}.json`,
          JSON.stringify(heartbeat(session, null, 0, false, null, await relayKey($))))
      }
    } catch {
      // the heartbeat goes stale after 15 s anyway
    }
    return next(e)
  })
}
