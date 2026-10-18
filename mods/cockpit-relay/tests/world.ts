// SPDX-License-Identifier: MIT
import { mock } from 'claude-code/testing'
import type { MockClock } from 'claude-code/testing'
import type { On } from 'claude-code'

/**
 * A fake Bridge beneath the mod: every call the mod makes on `$` lands here.
 *
 * process.run answers the config reader, files live in an in-memory disk the test and the mod
 * share (the server's inbox and key on one side, the mod's heartbeat and done files on the other),
 * and prompts, toasts and registered commands are recorded. Every fixture is synthetic.
 */

export const CWD = '/fake/bridge'
/** What $.session.id() answers: a UUID, as Claude Code names its sessions */
export const SESSION = 'a1b2c3d4-0000-4000-8000-00000000abcd'
/** 2026-10-09 08:00 local time */
export const NOW = new Date(2026, 9, 9, 8, 0, 0).getTime()

export type Raw = Record<string, unknown>

export type WorldOptions = {
  /** bridge-config.yaml and scripts/bridge-cockpit.py exist at the cwd */
  isBridge?: boolean
  env?: Record<string, string>
  /** the `cockpit:` block of bridge-config.yaml; undefined leaves it out */
  cockpit?: unknown
  /** language.conversation */
  language?: string
  /** what the config reader (`python3 -c`) answers instead of the config, e.g. a YAML error */
  configRun?: { exitCode: number; stdout: string; stderr: string }
  /** per interpreter (`python3.14`, ...): what it answers; one not named here is not installed (exit 127) */
  pythons?: Record<string, { exitCode: number; stdout: string; stderr: string }>
  /** what $.session.id() answers */
  sessionId?: string
  /** what $.session.messages() answers */
  messages?: { role: 'user' | 'assistant'; text: string }[]
  /** prompt.submit answers `{ drop }` with this reason, as a refusing UserPromptSubmit hook would */
  dropPrompt?: string
}

export type World = {
  calls: string[][]
  writes: { path: string; text: string }[]
  prompts: string[]
  toasts: string[]
  registered: string[]
  clock: MockClock
  /** The files the mod wrote, and those a test put, by absolute path: fs.read and fs.list see them */
  disk: Map<string, string>
  /** Puts a file as another program would (the cockpit server writing relay/inbox) */
  put: (path: string, text: string) => void
  /** Every directory the mod listed, in order */
  listed: string[]
}

/**
 * A path as the world files it. The engine resolves a relative path before any hook, against the
 * folder the test session runs in (the mod's own), not against CWD: anything under `.bridge/` is
 * filed under CWD whatever it was resolved against, every other relative path joins CWD.
 */
export function abs(path: string): string {
  const at = path.indexOf('.bridge/')
  if (at === 0 || (at > 0 && path[at - 1] === '/')) return `${CWD}/${path.slice(at)}`
  return path.startsWith('/') ? path : `${CWD}/${path}`
}

export function world(on: On, opts: WorldOptions = {}): World {
  const clock = mock.clock(on, { now: NOW })
  mock.store(on)
  mock.env(on, opts.env ?? { CMUX_SURFACE_ID: 'uuid-1' })
  const isBridge = opts.isBridge ?? true
  // the shape READ_CONFIG in hooks/register.tsx prints
  const config = { cockpit: opts.cockpit ?? null, language: opts.language ?? null }
  const disk = new Map<string, string>()
  const w: World = {
    calls: [], writes: [], prompts: [], toasts: [], registered: [], clock, disk,
    put: (path, text) => void disk.set(abs(path), text),
    listed: [],
  }
  on('session.cwd', () => ({ value: CWD }))
  on('session.start', (_$, e) => ({ cwd: e.cwd }))
  on('fs.exists', (_$, e) => ({ value: isBridge && (e.path === `${CWD}/bridge-config.yaml`
    || e.path === `${CWD}/scripts/bridge-cockpit.py`) }))
  on('fs.read', (_$, e) => {
    const text = disk.get(abs(e.path))
    if (text === undefined) throw new Error(`ENOENT: ${e.path}`)
    return { value: text }
  })
  on('fs.write', (_$, e) => {
    w.writes.push({ path: e.path, text: e.text })
    disk.set(abs(e.path), e.text)
    return { value: undefined }
  })
  on('fs.list', (_$, e) => {
    const dir = `${abs(e.path).replace(/\/$/, '')}/`
    w.listed.push(dir)
    const names = [...disk.keys()].filter(k => k.startsWith(dir) && !k.slice(dir.length).includes('/'))
      .map(k => k.slice(dir.length))
    // never throw here: a hook that throws is skipped and the call would reach the real disk
    return { value: names.map(name => ({ name, kind: 'file' as const, size: (disk.get(dir + name) ?? '').length,
      mtimeMs: 0, isLink: false })) }
  })
  on('session.id', () => ({ value: opts.sessionId ?? SESSION }))
  on('session.messages', () => ({ value: (opts.messages ?? []).map(m => ({ ...m, toolUses: [] })) }))
  // the bottom of the turn events: the core echoes the turn's id, and its answer
  on('turn.start', (_$, e) => ({ turnId: e.turnId }))
  on('turn.complete', (_$, e) => ({ text: e.answer }))
  on('command.register', (_$, e) => {
    w.registered.push(e.name)
    return { value: { command: e.name } }
  })
  on('ui.toast', (_$, e) => {
    w.toasts.push(JSON.stringify(e))
    return { value: undefined }
  })
  on('prompt.submit', (_$, e) => {
    w.prompts.push(e.text)
    return opts.dropPrompt === undefined ? { text: e.text } : { drop: opts.dropPrompt }
  })
  on('session.end', (_$, e) => ({ sessionId: e.sessionId }))
  on('process.run', (_$, e) => {
    const argv = [...e.argv]
    w.calls.push(argv)
    const isPython = /python/.test(argv[0] ?? '') && argv[1] === '-c'
    const out = !isPython ? { exitCode: 0, stdout: '', stderr: '' }
      : opts.pythons?.[argv[0]] ?? (argv[0] === 'python3'
        ? opts.configRun ?? { exitCode: 0, stdout: JSON.stringify(config), stderr: '' }
        : { exitCode: 127, stdout: '', stderr: `${argv[0]}: not found` })
    return { value: { ...out, isStdoutTruncated: false, isStderrTruncated: false } }
  })
  return w
}
