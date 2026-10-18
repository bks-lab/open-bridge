// SPDX-License-Identifier: MIT
// Mock mode for frontend development: open index.html?mock=1 (optionally &lang=de, which
// also puts the invented data in German,
// &offline=1 for a relay that is offline, &empty=1 for an empty briefing, &auth=0 for
// the sign-in panel). Everything here is invented example data in the shape of the
// contract's /api/state payload (section 11). No request leaves the page, nothing runs.

// the Jev tab's mock comes with the optional Jev files; without them the demo shows Jev as off
const createMockJev = await import('./jev/logic.js').then(m => m.createMockJev, () => null)

const MIN = 60000
const DAY = 24 * 60 * MIN

// The invented words in German, for &lang=de (rules/language-policy.md section 3: the English text is
// the source and the key, German is data beside it, any text without an entry stays English).
// Only words a reader sees: never an id, a key, a state or a name the page compares.
const WORDS = {
  de: {
    // Today: rows, reasons, headline
    'Review the demo report': 'Den Demo-Bericht prüfen',
    'Prepare the alpha release notes': 'Die Notizen zur Alpha-Version vorbereiten',
    'Tidy the issue labels on the demo board': 'Die Issue-Labels auf dem Demo-Board aufräumen',
    'Update the setup docs after the config change': 'Die Einrichtungs-Doku nach der Config-Änderung nachziehen',
    'Sweep old log files in the scratch folder': 'Alte Logdateien im Scratch-Ordner wegräumen',
    'Write the onboarding guide for the demo project': 'Die Einstiegsanleitung für das Demo-Projekt schreiben',
    'Tidy the old setup notes': 'Die alten Einrichtungsnotizen aufräumen',
    'Settle the invoice format with the vendor': 'Das Rechnungsformat mit dem Anbieter klären',
    'Fix the flaky test in example/repo#12': 'Den wackligen Test in example/repo#12 reparieren',
    'Refresh the docs index': 'Den Doku-Index auffrischen',
    'Clean up the old example fixtures': 'Die alten Beispiel-Fixtures aufräumen',
    'Waiting for the reply on the license question': 'Warten auf die Antwort zur Lizenzfrage',
    'Idea: dark mode for the weekly report': 'Idee: dunkles Design für den Wochenbericht',
    'Renew the test certificate': 'Das Testzertifikat erneuern',
    'due tomorrow': 'fällig morgen',
    'only you': 'nur du',
    'tab asks for permission': 'Tab fragt nach Erlaubnis',
    'needs your yes': 'braucht dein Ja',
    'changed since 08:40': 'geändert seit 08:40',
    'may run alone': 'darf allein laufen',
    '1 in the inbox': '1 im Posteingang',
    'assigned to you': 'dir zugewiesen',
    'quiet for 3 days': 'seit 3 Tagen ruhig',
    'quiet for 12 days': 'seit 12 Tagen ruhig',
    'asked 2 days ago': 'vor 2 Tagen gefragt',
    'Nothing waits for you': 'Nichts wartet auf dich',
    '2 for you today, next: Review the demo report': '2 für dich heute, als Nächstes: Den Demo-Bericht prüfen',
    'since 08:40: 1 new': 'seit 08:40: 1 neu',
    'Team call': 'Team-Call',
    'Review of the demo project': 'Durchsicht des Demo-Projekts',
    'Inbox': 'Posteingang',
    'Services: all running': 'Dienste: alle laufen',
    '2 tasks without a log row for 7 days': '2 Aufgaben seit 7 Tagen ohne Logzeile',
    'Tabs: 3 suggested': 'Tabs: 3 vorgeschlagen',
    'Yes given, runs on the next pass: Sweep old log files': 'Ja gegeben, läuft beim nächsten Durchlauf: Alte Logdateien wegräumen',
    // task checks
    'The linked issue example/repo#7 was closed as completed on 07.10, every step is checked.':
      'Das verknüpfte Issue example/repo#7 wurde am 07.10 als erledigt geschlossen, jeder Schritt ist abgehakt.',
    'No log row, commit or note for 34 days and nothing blocks it.': 'Seit 34 Tagen keine Logzeile, kein Commit, keine Notiz, und nichts blockiert sie.',
    'The vendor has not answered the question from 02.10 yet (example/repo#9 open).':
      'Der Anbieter hat die Frage vom 02.10 noch nicht beantwortet (example/repo#9 offen).',
    // the pages of the briefing profile
    'Systems': 'Systeme', 'Checks': 'Prüfungen', 'Services': 'Dienste', 'all running': 'alle laufen', 'nothing': 'nichts',
    'Backup older than 2 days': 'Backup älter als 2 Tage', 'last copy on the external disk is from Tuesday': 'die letzte Kopie auf der externen Platte ist von Dienstag',
    'Disk space below 15 percent': 'Speicherplatz unter 15 Prozent', 'scratch volume': 'Scratch-Volume',
    'Trackers': 'Tracker', 'Assigned to me': 'Mir zugewiesen', 'Bridge tasks': 'Bridge-Aufgaben',
    'example/repo#12 Flaky test in the parser suite': 'example/repo#12 Wackliger Test in der Parser-Suite',
    'example/repo#15 Add a config switch for the report': 'example/repo#15 Einen Config-Schalter für den Bericht ergänzen',
    'example/tools#4 Release checklist': 'example/tools#4 Release-Checkliste',
    'Draft the first two chapters': 'Die ersten zwei Kapitel entwerfen', 'Outline agreed with the team': 'Gliederung mit dem Team abgestimmt',
    'Outline written, examples collected': 'Gliederung geschrieben, Beispiele gesammelt', 'waits for the new folder layout': 'wartet auf die neue Ordnerstruktur',
    'Usage': 'Verbrauch', 'Quota': 'Kontingent', 'no account': 'kein Konto', 'Sessions': 'Sitzungen', 'no session': 'keine Sitzung',
    'Session (5 h): 22 %': 'Sitzung (5 h): 22 %', 'Week, all models: 84 %': 'Woche, alle Modelle: 84 %',
    'opus · busy · 25 turns · $42.10': 'opus · arbeitet · 25 Züge · $42.10', 'sonnet · idle · 9 turns · $6.80': 'sonnet · ruht · 9 Züge · $6.80',
    'sonnet · waiting · 4 turns · $1.95': 'sonnet · wartet · 4 Züge · $1.95',
    'Demo dashboard': 'Demo-Dashboard', 'Docs refresh': 'Doku auffrischen', 'Release notes': 'Release-Notizen',
    'Dates': 'Termine', 'Calendar': 'Kalender', 'no dates': 'keine Termine', 'Mail': 'Mail', 'mail account token expired': 'Token des Mailkontos abgelaufen',
    // agent tabs and sessions
    'Allow edit of RELEASE_NOTES.md?': 'Bearbeiten von RELEASE_NOTES.md erlauben?',
    'Draft written to the inbox as a result. Anything else?': 'Entwurf als Ergebnis in den Posteingang gelegt. Noch etwas?',
    'I found three sources. Should I summarise them in team.md?': 'Ich habe drei Quellen gefunden. Soll ich sie in team.md zusammenfassen?',
    'Running the link check (12 of 40 pages)': 'Linkprüfung läuft (12 von 40 Seiten)', 'Reading the meeting notes': 'Lese die Besprechungsnotizen',
    'Review the dashboard change': 'Die Dashboard-Änderung prüfen', 'Find where sessions are stored': 'Finden, wo Sitzungen gespeichert werden',
    'Run the migration tests': 'Die Migrationstests laufen lassen',
    // chat and relay
    'My briefing state from the dashboard (09:10): 2 for you today, next: Review the demo report':
      'Mein Briefing-Stand aus dem Dashboard (09:10): 2 für dich heute, als Nächstes: Den Demo-Bericht prüfen',
    '1. Review the demo report first, it is due tomorrow and only you can do it.\n2. Give your yes to the two label and docs items, they run alone.\n3. The flaky test can wait until after the team call.':
      '1. Prüf zuerst den Demo-Bericht, er ist morgen fällig und nur du kannst ihn machen.\n2. Gib den beiden Einträgen zu Labels und Doku dein Ja, sie laufen allein.\n3. Der wacklige Test kann bis nach dem Team-Call warten.',
    'Example answer from the mock. Seven of eleven steps are done; the next one is the yaml change in this repository.\nNothing was asked for real.':
      'Beispielantwort aus der Demo. Sieben von elf Schritten sind erledigt, als Nächstes kommt die yaml-Änderung in diesem Repository.\nNichts wurde wirklich gefragt.',
    'Example answer from the mock: nothing was sent to a real session.\nThe real answer shows here as plain text.':
      'Beispielantwort aus der Demo: nichts ging an eine echte Sitzung.\nDie echte Antwort steht hier als einfacher Text.',
    // details behind a row
    'Invented example detail.\nThe item came from a demo check and carries no real data.':
      'Erfundenes Beispieldetail.\nDer Eintrag stammt aus einer Demo-Prüfung und enthält keine echten Daten.',
    'looked at it, fine': 'angesehen, passt',
    'Onboarding guide for the demo project': 'Einstiegsanleitung für das Demo-Projekt', 'team call on 2026-09-30': 'Team-Call am 2026-09-30',
    'Goal': 'Ziel', 'Next': 'Als Nächstes', 'Log': 'Log',
    'A new team member sets up the demo project in under an hour, with every step written down.':
      'Ein neues Teammitglied richtet das Demo-Projekt in unter einer Stunde ein, jeder Schritt ist aufgeschrieben.',
    '- Draft the first two chapters\n- Collect screenshots from the example setup': '- Die ersten zwei Kapitel entwerfen\n- Screenshots aus dem Beispiel-Setup sammeln',
    '2026-10-08: outline written, examples collected\n2026-10-03: task opened': '2026-10-08: Gliederung geschrieben, Beispiele gesammelt\n2026-10-03: Aufgabe angelegt',
    'Task opened after the team call': 'Aufgabe nach dem Team-Call angelegt',
    'Mock: 3 snapshots, latest 09:00': 'Demo: 3 Abzüge, der neueste von 09:00',
    // the news ticker: invented feeds and items, the editor's invented short titles
    'Demo AI News': 'Demo-KI-Nachrichten', 'Demo Research Blog': 'Demo-Forschungsblog', 'Demo Tools Weekly': 'Demo-Werkzeuge der Woche',
    'A new example model reads long documents twice as fast': 'Ein neues Beispielmodell liest lange Dokumente doppelt so schnell',
    'How the demo team cut its test time in half': 'Wie das Demo-Team seine Testzeit halbiert hat',
    'Example study: agents that ask before they act make fewer mistakes': 'Beispielstudie: Agenten, die vor dem Handeln fragen, machen weniger Fehler',
    'Release notes of the example toolkit 3.0': 'Versionshinweise des Beispiel-Werkzeugkastens 3.0',
    'Five patterns for small, safe automation': 'Fünf Muster für kleine, sichere Automatisierung',
    'Agents that ask first make fewer mistakes': 'Agenten, die zuerst fragen, irren seltener',
    'Example model reads long texts twice as fast': 'Beispielmodell liest lange Texte doppelt so schnell',
    'Test time cut in half': 'Testzeit halbiert',
    'Mock: ticker setting saved': 'Demo: Einstellung des Bands gespeichert',
    'Mock: ticker settings from the config again': 'Demo: Band wieder nach Config',
    'Mock: reading the feeds': 'Demo: Feeds werden gelesen',
    'Mock: the editor is at work, nothing is asked for real': 'Demo: die Redaktion arbeitet, nichts wird wirklich gefragt',
  },
}

/** Every string in `value` that has an entry in the table, swapped for it; anything else unchanged */
function localize(value, words) {
  if (!words) return value
  if (typeof value === 'string') return Object.hasOwn(words, value) ? words[value] : value
  if (Array.isArray(value)) return value.map(v => localize(v, words))
  if (value && typeof value === 'object') return Object.fromEntries(Object.entries(value).map(([k, v]) => [k, localize(v, words)]))
  return value
}

function row(over) {
  return {
    key: '', bucket: 'do', section: 'now', number: 0, title: '', why: [], sources: [],
    inbox_id: null, gate: null, task: null, ref: null, url: null, link: null,
    priority: null, urgency: null, area: null, area_names: [], task_type: null, due: null,
    has_action: false, inbox_state: null, inbox_key: null, mark: null, is_new: false, is_changed: false,
    tab: null, actions: [{ id: 'ask', primary: false, dim: false }], selectable: false, starting: false,
    adopt_candidates: [], team: null, team_suggestions: [], closable: false, settle: ['done', 'not_doing'], review: null,
    ...over,
  }
}

const A = (id, primary = false, dim = false) => ({ id, primary, dim })

// the model an agent tab starts with: what bridge-config.yaml would say, and the state block the server builds from it
const LAUNCH_CONFIG = {
  enabled: true, manual: true, auto: true, effort: true, default_model: 'sonnet', default_effort: null, max_model: 'opus',
  router: 'chain', jev_model: 'jev-1.14.0', triage_jev: false,
  jev_bands: [{ below: 0.75, model: 'haiku', effort: 'medium' }, { below: 1.3, model: 'sonnet', effort: 'medium' },
    { below: 1.9, model: 'sonnet', effort: 'high' }, { below: 2.6, model: 'opus', effort: 'high' }, { below: null, model: 'opus', effort: 'xhigh' }],
  haiku_map: [{ model: 'haiku', effort: 'medium' }, { model: 'sonnet', effort: 'medium' }, { model: 'sonnet', effort: 'high' }, { model: 'opus', effort: 'high' }],
}

function launchState(settings, jevOn) {
  const st = JSON.parse(JSON.stringify(settings))
  return {
    enabled: st.enabled, manual: st.manual, auto: st.auto, effort: st.effort,
    models: ['haiku', 'sonnet', 'opus'], efforts: ['low', 'medium', 'high', 'xhigh'],
    default_model: st.default_model, default_effort: st.default_effort,
    router: !st.enabled || !st.auto ? 'off' : st.router === 'chain' ? (jevOn ? 'jev' : 'haiku') : st.router,
    settings: st, defaults: JSON.parse(JSON.stringify(LAUNCH_CONFIG)),
    overridden: Object.keys(LAUNCH_CONFIG).filter(k => JSON.stringify(st[k]) !== JSON.stringify(LAUNCH_CONFIG[k])),
  }
}

// the news ticker: what bridge-config.yaml would say (cockpit.ticker), and the state block the server builds
const TICKER_CONFIG = {
  enabled: true, max_items: 30, per_feed: 8, refresh_minutes: 30, speed: 'normal',
  feeds: [
    { id: 'demo-ai', name: 'Demo AI News', url: 'https://example.org/ai/feed.xml', enabled: true },
    { id: 'demo-research', name: 'Demo Research Blog', url: 'https://example.org/research/atom.xml', enabled: true },
    { id: 'demo-tools', name: 'Demo Tools Weekly', url: 'https://example.org/tools/rss', enabled: true },
  ],
  status: { enabled: true, kinds: ['running', 'waiting', 'slow', 'failing', 'quota', 'offline', 'notes'] },
  editor: { enabled: true, interests: '', max_picks: 12, shorten: true },
  smart: { cluster: true, max_age_hours: 72, mark_new: true, mute: [] },
}

function tickerItemsOf(now) {
  const it = (id, feed, source, title, ago, sources = []) => ({ id, feed, source, title, short: null, url: `https://example.org/${feed}/${id}`,
    published_ms: now - ago * MIN, fresh: false, sources })
  return [
    it('a1', 'demo-ai', 'Demo AI News', 'A new example model reads long documents twice as fast', 35,
      [{ feed: 'demo-research', source: 'Demo Research Blog', url: 'https://example.org/demo-research/a1' }]),
    it('r1', 'demo-research', 'Demo Research Blog', 'Example study: agents that ask before they act make fewer mistakes', 80),
    it('t1', 'demo-tools', 'Demo Tools Weekly', 'How the demo team cut its test time in half', 150),
    it('a2', 'demo-ai', 'Demo AI News', 'Release notes of the example toolkit 3.0', 300),
    it('t2', 'demo-tools', 'Demo Tools Weekly', 'Five patterns for small, safe automation', 600),
  ]
}

/** Raised on every change of the ticker block, like the server's Ticker.rev: the page keeps the newer state */
let tickerRev = 0

/** The ticker block after a change: the patch over the current block, with the next rev */
function tickerNext(current, patch) {
  return { ...current, ...patch, rev: ++tickerRev }
}

/** The ticker block of the state: settings over the config, the items, how each feed stands, the last passes */
function tickerState(settings, now, extra = {}) {
  const st = JSON.parse(JSON.stringify(settings))
  return {
    rev: ++tickerRev,
    enabled: st.enabled, settings: st, defaults: JSON.parse(JSON.stringify(TICKER_CONFIG)),
    overridden: Object.keys(TICKER_CONFIG).filter(k => JSON.stringify(st[k]) !== JSON.stringify(TICKER_CONFIG[k])),
    items: st.enabled ? tickerItemsOf(now) : [],
    feeds: st.feeds.map(f => ({ id: f.id, name: f.name, ok: true, error: null, fetched_ms: now - 4 * MIN, count: 2 })),
    fetched_ms: now - 4 * MIN, refreshing: false,
    editor: { available: st.editor.enabled, running: null, error: null, last: null },
    profile: { running: null, last: null, tasks: 4 },
    // one slow pass, so the band shows the slow item in the demo
    perf: { passes: [{ kind: 'quick', took_ms: 8000, ok: true, at_ms: now - 30 * MIN }, { kind: 'full', took_ms: 95000, ok: true, at_ms: now - 4 * MIN }],
      outliers: [] },
    limits: { timeout_ms: 120000 },
    ...extra,
  }
}

/** An invented recommendation for a row: a level from its key, the bands or the Haiku levels turn it into a model */
function mockRoute(key, launch) {
  const st = launch.settings
  const n = [...String(key)].reduce((a, ch) => (a * 31 + ch.charCodeAt(0)) % 997, 7)
  if (launch.router === 'jev') {
    const level = Math.round((n % 30)) / 10
    const band = st.jev_bands.find(b => b.below == null || level < b.below)
    return { model: band.model, effort: band.effort, routed_by: 'jev', level, confidence: 0.7, why: 'Example rating from the demo, nothing was asked' }
  }
  const pick = st.haiku_map[n % 4]
  return { model: pick.model, effort: pick.effort, routed_by: 'haiku', level: n % 4, confidence: null, why: 'Example level from the demo, nothing was asked' }
}

function isoIn(days, now) {
  const d = new Date(now + days * 86400000)
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}-${String(d.getDate()).padStart(2, '0')}`
}

// a local time as the server writes it (2026-10-18T14:30), and the facts of a made-up event
function localIso(ms) {
  const d = new Date(ms)
  const two = n => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${two(d.getMonth() + 1)}-${two(d.getDate())}T${two(d.getHours())}:${two(d.getMinutes())}`
}

function localDay(days) {
  return localIso(Date.now() + days * 86400000).slice(0, 10)
}

function dayAt(days, hour) {
  const d = new Date()
  d.setDate(d.getDate() + days)
  d.setHours(hour, 0, 0, 0)
  return d.getTime()
}

function calFacts(startMs, minutes, more) {
  const start = typeof startMs === 'number' ? startMs : Date.parse(startMs)
  const end = start + minutes * 60000
  return { start: localIso(start), end: localIso(end), day: localIso(start).slice(0, 10), minutes, all_day: false, calendar: null,
    info: false, where: null, online: false, people: [], past: end <= Date.now(), running: start <= Date.now() && Date.now() < end,
    overlaps: [], ...more }
}

function hhmm(ms) {
  const d = new Date(ms)
  return `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`
}

export function buildState(now = Date.now(), opts = {}) {
  const empty = !!opts.empty
  const rows = {
    review: row({
      key: 'inbox:20261009-0900-review-demo-a1b2', bucket: 'do', section: 'now', title: 'Review the demo report',
      why: ['due tomorrow', 'only you'], sources: ['inbox'], inbox_id: '20261009-0900-review-demo-a1b2', gate: 'only-you',
      task: 'demo-task', urgency: 'today', area: 'Demo', area_names: ['Demo'], task_type: 'feature', due: isoIn(1, now),
      inbox_state: 'open', inbox_key: 'demo-review', mark: { label: 'Demo', color: 'blue' }, is_new: true,
      actions: [A('done', true), A('advise')], selectable: true,
    }),
    release: row({
      key: 'task:alpha-release', bucket: 'do', section: 'now', title: 'Prepare the alpha release notes',
      why: ['tab asks for permission'], sources: ['tasks'], task: 'alpha-release', priority: 'P0', urgency: 'now',
      area: 'Ops', area_names: ['Ops'], task_type: 'ops', mark: { label: 'Ops', color: 'red' },
      tab: { ref: 'surface:7', state: 'needs-you', live: true, waiting: true },
      actions: [A('to_tab', true)], team: { team_id: 'build', started: 1, next_role: { id: 'review', name: 'Review' }, ready: false, waiting_for: 'Implement' },
    }),
    labels: row({
      key: 'inbox:20261009-0910-tidy-labels-c3d4', bucket: 'delegate', section: 'give', title: 'Tidy the issue labels on the demo board',
      why: ['needs your yes'], sources: ['inbox'], inbox_id: '20261009-0910-tidy-labels-c3d4', gate: 'your-yes', has_action: true,
      priority: 'P2', area: 'Demo', area_names: ['Demo'], inbox_state: 'open', inbox_key: 'tidy-labels',
      actions: [A('do', true), A('drop', false, true)], selectable: true,
    }),
    docs: row({
      key: 'inbox:20261009-0915-update-docs-e5f6', bucket: 'delegate', section: 'give', title: 'Update the setup docs after the config change',
      why: ['needs your yes', 'changed since 08:40'], sources: ['inbox'], inbox_id: '20261009-0915-update-docs-e5f6', gate: 'your-yes',
      has_action: true, area: 'Docs', area_names: ['Docs'], inbox_state: 'open', inbox_key: 'update-docs',
      mark: { label: 'Docs', color: 'green' }, is_changed: true, actions: [A('do', true), A('drop', false, true)], selectable: true,
    }),
    sweep: row({
      key: 'inbox:20261009-0920-sweep-logs-0a0b', bucket: 'plan', section: 'give', title: 'Sweep old log files in the scratch folder',
      why: ['may run alone'], sources: ['inbox'], inbox_id: '20261009-0920-sweep-logs-0a0b', gate: 'free', has_action: true,
      area: 'Ops', area_names: ['Ops'], inbox_state: 'approved', inbox_key: 'sweep-logs',
      actions: [A('approved', false, true), A('drop', false, true)],
    }),
    demo: row({
      key: 'task:demo-task', bucket: 'tasks', section: 'work', title: 'Write the onboarding guide for the demo project',
      why: ['1 in the inbox'], sources: ['tasks'], task: 'demo-task', priority: 'P1', area: 'Demo', area_names: ['Demo'],
      task_type: 'feature', actions: [A('do', true), A('advise')], selectable: true, closable: true,
      adopt_candidates: [{ ref: 'surface:9', name: 'notes', workspace: 'Demo' }], team_suggestions: ['build', 'research'],
      link: { kind: 'file', path: 'work/tasks/demo-task/STATUS.md' },
      review: { verdict: 'close', reason: 'The linked issue example/repo#7 was closed as completed on 07.10, every step is checked.',
        confidence: 'medium', model: 'claude-haiku-5-5', kept: false, resolved: true, changed: true, previous_verdict: 'continue',
        days_since_activity: 3, cached: false, chips: [{ kind: 'ref', ref: 'example/repo#7', state: 'closed' }, { kind: 'steps', count: 1 }],
        closed_refs: ['example/repo#7'], title: 'Write the onboarding guide for the demo project', status: 'doing', priority: 'P1' },
    }),
    quiet: row({
      key: 'task:quiet-docs', bucket: 'tasks', section: 'work', title: 'Tidy the old setup notes',
      sources: ['tasks'], task: 'quiet-docs', priority: 'P3', area: 'Docs', area_names: ['Docs'], closable: true,
      actions: [A('do', true), A('advise')],
      review: { verdict: 'stale', reason: 'No log row, commit or note for 34 days and nothing blocks it.', confidence: 'high',
        model: 'claude-haiku-5-5', kept: false, resolved: false, changed: false, days_since_activity: 34, cached: true,
        chips: [{ kind: 'steps', count: 4 }], closed_refs: [], title: 'Tidy the old setup notes', status: 'doing', priority: 'P3' },
    }),
    waits: row({
      key: 'task:vendor-reply', bucket: 'tasks', section: 'work', title: 'Settle the invoice format with the vendor',
      sources: ['tasks'], task: 'vendor-reply', priority: 'P2', area: 'Demo', area_names: ['Demo'], closable: true,
      actions: [A('do', true), A('advise')],
      review: { verdict: 'waiting', reason: 'The vendor has not answered the question from 02.10 yet (example/repo#9 open).',
        confidence: 'low', model: 'claude-sonnet-5-5', kept: false, resolved: false, changed: false, days_since_activity: 8, cached: false,
        chips: [{ kind: 'ref', ref: 'example/repo#9', state: 'open' }, { kind: 'blocked' }], closed_refs: [],
        title: 'Settle the invoice format with the vendor', status: 'doing', priority: 'P2' },
    }),
    flaky: row({
      key: 'ref:example/repo#12', bucket: 'do', section: 'work', title: 'Fix the flaky test in example/repo#12',
      why: ['assigned to you', 'quiet for 3 days'], sources: ['github'], ref: 'example/repo#12', priority: 'P2',
      url: 'https://example.org/repo/issues/12', link: { kind: 'web', href: 'https://example.org/repo/issues/12' },
      mark: { label: 'Demo', color: 'blue' }, actions: [A('ask')],
    }),
    index: row({
      key: 'task:docs-refresh', bucket: 'tasks', section: 'work', title: 'Refresh the docs index', sources: ['tasks'],
      task: 'docs-refresh', priority: 'P2', area: 'Docs', area_names: ['Docs'], task_type: 'docs',
      tab: { ref: 'surface:8', state: 'working', live: true, waiting: false }, actions: [A('to_tab', true)],
    }),
    cleanup: row({
      key: 'task:old-cleanup', bucket: 'tasks', section: 'work', title: 'Clean up the old example fixtures', sources: ['tasks'],
      task: 'old-cleanup', priority: 'P3', area: 'Ops', area_names: ['Ops'], actions: [A('do', true), A('advise')], selectable: true,
    }),
    vendor: row({
      key: 'inbox:20261008-1400-vendor-reply-9f9f', bucket: 'waiting', section: 'later', title: 'Waiting for the reply on the license question',
      why: ['asked 2 days ago'], sources: ['inbox'], inbox_id: '20261008-1400-vendor-reply-9f9f', gate: 'only-you', area: 'Demo',
      area_names: ['Demo'], inbox_state: 'open', inbox_key: 'license-reply', actions: [A('follow_up')],
    }),
    idea: row({
      key: 'task:report-dark-mode', bucket: 'resting', section: 'later', title: 'Idea: dark mode for the weekly report',
      why: ['quiet for 12 days'], sources: ['tasks'], task: 'report-dark-mode', priority: 'P3', area: 'Docs', area_names: ['Docs'],
      actions: [A('do', true), A('advise')], selectable: true,
    }),
  }
  const sec = (id, list, compact) => ({ id, total: list.length, rows: list, compact: compact.map(r => r.key) })
  const sections = empty ? [sec('now', [], []), sec('give', [], []), sec('work', [], []), sec('later', [], [])] : [
    sec('now', [rows.review, rows.release], [rows.review, rows.release]),
    sec('give', [rows.labels, rows.docs, rows.sweep], [rows.labels, rows.docs, rows.sweep]),
    sec('work', [rows.demo, rows.flaky, rows.index, rows.cleanup], [rows.demo, rows.flaky, rows.index]),
    sec('later', [rows.vendor, rows.idea], []),
  ]
  const numbers = {}
  let n = 0
  for (const s of sections) for (const r of s.rows) { n += 1; r.number = n; numbers[r.key] = n }
  const hidden = empty ? [] : [row({
    key: 'title:Renew the test certificate', bucket: 'plan', section: 'later', title: 'Renew the test certificate', sources: ['calendar'],
    hidden_until: isoIn(5, now), actions: [A('ask')],
  })]

  const item = (index, over) => ({
    index, title: '', detail: '', when: '', tone: null, link: null, task: null, ask: false, mark: null,
    priority: null, state: null, lines: [], meter: null, starting: false, tab: null, ...over,
  })
  const pages = empty ? [] : [
    {
      id: 'systems', title: 'Systems', badge: { kind: 'bad', n: 1 }, sections: [
        { id: 'checks', kind: 'command', title: 'Checks', status: 'ok', reason: '', alarm: true, empty: 'nothing', count: 2, total: 2,
          weight: 1, bad: 1, as_of: hhmm(now - 4 * MIN), more: 0, items: [
            item(0, { title: 'Backup older than 2 days', detail: 'last copy on the external disk is from Tuesday', when: '08:55', tone: 'bad', link: { kind: 'web', href: 'https://example.org/backup' }, ask: true }),
            item(1, { title: 'Disk space below 15 percent', detail: 'scratch volume', when: '08:55', tone: 'warn', ask: true }),
          ] },
        { id: 'services', kind: 'command', title: 'Services', status: 'ok', reason: '', alarm: true, empty: 'all running', count: 0, total: 0,
          weight: 0, bad: 0, as_of: hhmm(now - 4 * MIN), more: 0, items: [] },
      ],
    },
    {
      id: 'trackers', title: 'Trackers', badge: { kind: 'count', n: 5, warn: true }, jev: { skip_sections: [], private: [] }, sections: [
        // github-work in the board view: one row per issue or PR under its board, with the steps an agent starts on it
        { id: 'mine', kind: 'tracker', view: 'board', title: 'GitHub work', status: 'ok', reason: '', alarm: false, empty: 'nothing', count: 3, total: 5,
          weight: 3, bad: 0, as_of: hhmm(now - 22 * MIN), more: 2,
          metrics: [{ id: 'open', n: 5 }, { id: 'mine', n: 3 }, { id: 'ask_review', n: 1 }, { id: 'my_pr', n: 1, days: 4 },
            { id: 'in_progress', n: 1 }, { id: 'review', n: 1 }, { id: 'blocked', n: 0 }, { id: 'quiet', n: 1, days: 14 }, { id: 'untasked', n: 1 },
            { id: 'closed', n: 4, days: 7 }, { id: 'landed', n: 2, days: 7 }],
          boards: [{ name: 'Demo board', slug: 'demo-board', open: 9, mode: 'mine', counts: { new: 3, ready: 2, in_progress: 2, review: 1, blocked: 1 } },
            { name: 'Docs board', slug: 'docs-board', open: 4, mode: 'all', counts: { new: 1, ready: 2, review: 1 } },
            { name: 'Old roadmap', slug: 'old-roadmap', open: null, mode: 'off', counts: {} }],
          items: [
            item(0, { title: 'example/repo#12 Flaky test in the parser suite', detail: 'In Progress · PR #14', when: 'Tue', tone: 'warn', link: { kind: 'web', href: 'https://example.org/repo/issues/12' }, ask: true, mark: { label: 'Demo', color: 'blue' }, priority: 'P2',
              group: 'Demo board', flags: ['mine', 'in_progress', 'untasked'], who: 'demo-user',
              gh: { title: 'Flaky test in the parser suite', repo: 'example/repo', number: 12, type: 'issue', state: 'in_progress', status: 'In Progress', priority: 'P2', labels: ['bug', 'ci'], people: ['demo-user'], prs: [{ n: 14, draft: true }], task: null, stream: false, untasked: true, changed: new Date(now - 2 * DAY).toISOString(), quiet: null, note: null },
              row_id: 'example/repo#12', actions: [{ id: 'analyze', label: 'Analyse' }, { id: 'review', label: 'Review the PR' }, { id: 'adopt', label: 'Make it a task' }, { id: 'sync', label: 'Sync status' }] }),
            item(1, { title: 'example/repo#15 Add a config switch for the report', detail: 'Backlog', when: 'Mon', link: { kind: 'web', href: 'https://example.org/repo/issues/15' }, ask: true, priority: 'P3', actionable: true,
              group: 'Demo board', flags: ['mine', 'quiet'], who: 'demo-user',
              gh: { title: 'Add a config switch for the report', repo: 'example/repo', number: 15, type: 'issue', state: 'new', status: 'Backlog', priority: 'P3', labels: ['enhancement'], people: ['demo-user'], prs: [], task: 'demo-task', stream: false, changed: new Date(now - 18 * DAY).toISOString(), quiet: 18, note: null },
              row_id: 'example/repo#15', actions: [{ id: 'analyze', label: 'Analyse' }, { id: 'implement', label: 'Implement' }, { id: 'sync', label: 'Sync status' }] }),
            item(2, { title: 'example/tools#4 Release checklist', detail: 'In Review', when: '08:10', link: { kind: 'web', href: 'https://example.org/tools/issues/4' }, ask: true, mark: { label: 'Ops', color: 'red' },
              group: 'example/tools', inbox: 'demo-inbox-4', tab: { ref: 'surface:9', state: 'working', live: true, waiting: false },
              flags: ['review'], who: 'teammate',
              gh: { title: 'Release checklist', repo: 'example/tools', number: 4, type: 'pr', state: 'review', status: 'In Review', labels: [], people: ['teammate'], prs: [], task: null, stream: false, changed: new Date(now - 3 * 3600000).toISOString(), quiet: null, note: null },
              row_id: 'example/tools#4', actions: [{ id: 'analyze', label: 'Analyse' }, { id: 'implement', label: 'Implement' }, { id: 'remind', label: 'Remind' }] }),
          ] },
        { id: 'tasks', kind: 'tasks', title: 'Bridge tasks', status: 'ok', reason: '', alarm: false, empty: 'nothing', count: 2, total: 2,
          weight: 2, bad: 0, as_of: null, more: 0, items: [
            item(0, { title: 'Write the onboarding guide for the demo project', detail: 'Demo', when: '', task: 'demo-task', priority: 'P1', state: 'doing',
              lines: [{ kind: 'next', text: 'Draft the first two chapters' }, { kind: 'step', text: 'Outline agreed with the team' }, { kind: 'log', text: 'Outline written, examples collected' }] }),
            item(1, { title: 'Refresh the docs index', detail: 'Docs', task: 'docs-refresh', priority: 'P2', state: 'doing',
              tab: { ref: 'surface:8', state: 'working', live: true, waiting: false }, lines: [{ kind: 'blocked', text: 'waits for the new folder layout' }] }),
          ] },
      ],
    },
    {
      id: 'usage', title: 'Usage', badge: { kind: 'none' }, overview: true, sections: [
        { id: 'quota', kind: 'command', title: 'Quota', status: 'ok', reason: '', alarm: false, empty: 'no account', count: 2, total: 2,
          weight: 0, bad: 0, as_of: hhmm(now - 2 * MIN), more: 0, items: [
            item(0, { title: 'Session (5 h): 22 %', when: '16:00', meter: { value: 22, max: 100, unit: '%', elapsed: 0.4, warn: 80, bad: 95 } }),
            item(1, { title: 'Week, all models: 84 %', when: 'Mon 04:00', tone: 'warn', meter: { value: 84, max: 100, unit: '%', elapsed: 0.55, warn: 80, bad: 95 } }),
          ] },
        { id: 'runs', kind: 'command', title: 'Sessions', status: 'ok', reason: '', alarm: false, empty: 'no session', count: 3, total: 3,
          weight: 0, bad: 0, as_of: hhmm(now - 2 * MIN), more: 0, items: [
            item(0, { title: 'Demo dashboard', detail: 'opus · busy · 25 turns · $42.10', when: '08:12', meter: { value: 42.1, unit: '$' } }),
            item(1, { title: 'Docs refresh', detail: 'sonnet · idle · 9 turns · $6.80', when: '09:40', tone: 'dim', meter: { value: 6.8, unit: '$' } }),
            item(2, { title: 'Release notes', detail: 'sonnet · waiting · 4 turns · $1.95', when: '10:05', tone: 'warn', meter: { value: 1.95, unit: '$' } }),
          ] },
      ],
    },
    {
      id: 'dates', title: 'Dates', badge: { kind: 'none' }, sections: [
        // the dates lie ahead of the moment the demo opens, so the start page always has a next one
        // the agenda view (views/dates.js): every event carries its facts (`cal`), the section its figures
        { id: 'calendar', kind: 'calendar', view: 'agenda', title: 'Calendar', status: 'ok', reason: '', alarm: false, empty: 'no dates', count: 8, total: 8,
          weight: 0, bad: 0, as_of: hhmm(now - 2 * MIN), more: 0,
          cal_figures: { today: 2, busy_today: 105, tomorrow: 1, week: 6, overlaps: 2, info_week: 2, day_start: 8, day_end: 20,
            next: { start: localIso(now + 70 * MIN), title: 'Team call' }, free_today: { minutes: 120, from: localIso(now + 130 * MIN) } },
          items: [
            item(0, { title: 'Team call', when: hhmm(now + 70 * MIN), at: new Date(now + 70 * MIN).toISOString(),
              link: { kind: 'web', href: 'https://example.org/meet/team' }, row_id: 'team-call', actions: [{ id: 'prepare', label: 'Prepare' }],
              cal: calFacts(now + 70 * MIN, 60, { calendar: 'Work', online: true, people: ['Alex', 'Sam', 'Kim'] }) }),
            item(1, { title: 'Review of the demo project', when: hhmm(now + 250 * MIN), at: new Date(now + 250 * MIN).toISOString(),
              row_id: 'review', actions: [{ id: 'prepare', label: 'Prepare' }],
              cal: calFacts(now + 250 * MIN, 45, { calendar: 'Work', where: 'Room 2', overlaps: ['Pick up from football'] }) }),
            item(2, { title: 'Pick up from football', when: hhmm(now + 260 * MIN),
              cal: calFacts(now + 260 * MIN, 30, { calendar: 'Family', info: true, overlaps: ['Review of the demo project'] }) }),
            item(3, { title: 'Weekly', when: 'tomorrow 10:00', row_id: 'weekly', actions: [{ id: 'prepare', label: 'Prepare the weekly' }],
              cal: calFacts(dayAt(1, 10), 90, { calendar: 'Work', online: true, people: ['Alex', 'Sam', 'Kim', 'Lee'] }) }),
            item(4, { title: 'Conference', when: hhmm(dayAt(2, 0)), cal: calFacts(dayAt(2, 0), 1440, { calendar: 'Work', all_day: true }) }),
            item(5, { title: 'Customer workshop', when: hhmm(dayAt(3, 9)), cal: calFacts(dayAt(3, 9), 180, { calendar: 'Work', where: 'Customer office' }) }),
            item(6, { title: 'Dentist', when: hhmm(dayAt(3, 15)), cal: calFacts(dayAt(3, 15), 60, { calendar: 'Private' }) }),
            item(7, { title: 'School evening', when: hhmm(dayAt(5, 19)), cal: calFacts(dayAt(5, 19), 90, { calendar: 'Family', info: true }) }),
          ] },
        { id: 'deadlines', kind: 'command', title: 'Deadlines', status: 'ok', reason: '', alarm: false, empty: 'nothing due', count: 2, total: 2,
          weight: 2, bad: 0, as_of: null, more: 0, items: [
            item(0, { title: 'Send the slides from the review', detail: 'overdue', tone: 'warn', when: 'Mon', due_at: localDay(-2) }),
            item(1, { title: 'Answer the offer', detail: 'due', when: 'Fri', due_at: localDay(3) }),
          ] },
        { id: 'mail', kind: 'mail', title: 'Mail', status: 'error', reason: 'mail account token expired', alarm: false, empty: 'nothing', count: 0, total: 0,
          weight: 0, bad: 0, as_of: null, more: 0, items: [] },
      ],
    },
  ]

  const tabs = empty ? [] : [
    { ref: 'surface:3', ws_ref: 'workspace:1', name: 'Control', workspace: 'Control', state: 'waiting', last: '', slug: null, item: null,
      team: null, role: null, live: true, waiting: false, is_control: true, filed_by: null, since_ms: now - 15 * MIN, long: null },
    { ref: 'surface:7', ws_ref: 'workspace:2', name: 'alpha-release', workspace: 'Ops', state: 'needs-you', last: 'Allow edit of RELEASE_NOTES.md?',
      slug: 'alpha-release', item: null, team: 'build', role: 'implement', live: true, waiting: true, is_control: false, filed_by: null,
      since_ms: now - 3 * MIN, long: null },
    { ref: 'surface:10', ws_ref: 'workspace:3', name: 'report-draft', workspace: 'Demo', state: 'waiting',
      last: 'Draft written to the inbox as a result. Anything else?', slug: 'report-draft', item: null, team: null, role: null, live: true,
      waiting: false, is_control: false, filed_by: 'inbox:20261009-0910-tidy-labels-c3d4', since_ms: now - 74 * MIN, long: 'waiting' },
    { ref: 'surface:12', ws_ref: 'workspace:3', name: 'demo-task research', workspace: 'Demo', state: 'waiting',
      last: 'I found three sources. Should I summarise them in team.md?', slug: 'demo-task', item: null, team: 'research', role: 'evidence',
      live: true, waiting: true, is_control: false, filed_by: null, since_ms: now - 11 * MIN, long: null },
    { ref: 'surface:8', ws_ref: 'workspace:4', name: 'docs-refresh', workspace: 'Docs', state: 'working', last: 'Running the link check (12 of 40 pages)',
      slug: 'docs-refresh', item: null, team: null, role: null, live: true, waiting: false, is_control: false, filed_by: null,
      since_ms: now - 26 * MIN, long: null },
    { ref: 'surface:9', ws_ref: 'workspace:3', name: 'notes', workspace: 'Demo', state: 'working', last: 'Reading the meeting notes',
      slug: null, item: null, team: null, role: null, live: true, waiting: false, is_control: false, filed_by: null, since_ms: now - 6 * MIN, long: null },
    { ref: 'surface:11', ws_ref: 'workspace:4', name: 'zsh', workspace: 'Docs', state: 'shell', last: '', slug: null, item: null,
      team: null, role: null, live: false, waiting: false, is_control: false, filed_by: null, since_ms: now - 140 * MIN, long: null },
  ]

  const relayOnline = !opts.offline
  return localize({
    ok: true,
    server: { version: '0.1.0', started_ms: now - 50 * MIN },
    model: {
      seq: 3, stale: false, profile: 'morning', title: 'Morning',
      collected_at: hhmm(now - 2 * MIN), collected_ms: now - 2 * MIN, full_ms: now - 2 * MIN, is_full: true,
      headline: empty ? 'Nothing waits for you' : '2 for you today, next: Review the demo report',
      since: empty ? null : 'since 08:40: 1 new', skipped: [],
      agenda: empty ? [] : [{ when: hhmm(now + 70 * MIN), title: 'Team call' }, { when: hhmm(now + 250 * MIN), title: 'Review of the demo project' }],
      status: [{ title: 'Systems', count: empty ? 0 : 1, probe: true, state: 'ok' }, { title: 'Inbox', count: empty ? 0 : 6, probe: false, state: 'ok' }],
      extras: { clear: ['Services: all running'], hygiene: empty ? [] : ['2 tasks without a log row for 7 days'], workplace: empty ? null : 'Tabs: 3 suggested' },
      counts: { waiting_tabs: empty ? 0 : 2, long_tabs: empty ? 0 : 1, working_tabs: empty ? 0 : 2, now: sections[0].total, give: sections[1].total, work: sections[2].total, later: sections[3].total, hidden: hidden.length },
      sections, numbers, hidden,
      approvable: empty ? [] : [rows.labels.key, rows.docs.key],
      task_rows: empty ? [] : [rows.quiet, rows.waits],
      review: empty ? { running: null, error: null, last: null, keys: [] } : {
        running: null, error: null, keys: [rows.demo.key, rows.quiet.key, rows.waits.key],
        last: { reviewed_at: new Date(now - 20 * MIN).toISOString().slice(0, 19), reviewed: 3, to_close: 1, cost_ct: 2.22,
          cost_known: true, models: ['haiku-5-5', 'sonnet-5-5'], duration_sec: 24.5, escalate_ct: 2.1, mismatch: false,
          tiers: [{ model: 'haiku-5-5', answered: 2, cost_ct: 0.12 }, { model: 'sonnet-5-5', answered: 1, cost_ct: 2.1 }], cached: 0 },
      },
      pages,
      alarms: empty ? [] : [{ page_id: 'systems', page_title: 'Systems', section_title: 'Checks', count: 1 }],
      teams: [
        { id: 'build', label: 'Build', for_types: ['feature'], roles: [{ id: 'implement', name: 'Implement', mode: 'go' }, { id: 'review', name: 'Review', mode: 'report' }] },
        { id: 'research', label: 'Research', for_types: ['research'], roles: [{ id: 'evidence', name: 'Evidence', mode: 'report' }, { id: 'counter', name: 'Counter', mode: 'report' }, { id: 'summary', name: 'Summary', mode: 'report' }] },
      ],
      // what the server sends: the Now section's total, the same number as counts.now
      briefing_badge: sections[0].total,
    },
    tabs: { at_ms: now - 8000, error: null, control: { name: 'Control', ref: 'surface:3' }, tabs },
    quick: { available: true, default: 'haiku', models: ['haiku', 'sonnet', 'opus'], convs: [] },
    jev: createMockJev ? { enabled: true, ready: true, reason: null } : { enabled: false, ready: false, reason: 'off' },
    agents: empty ? { peers: [], convs: [] } : agentsState(now),
    triage: empty ? { running: null, error: null, last: null, items: {} } : triageState(now),
    launch: launchState(LAUNCH_CONFIG, !!createMockJev),
    ticker: tickerState(TICKER_CONFIG, now),
    loading: { pass: null, fresh: false, started_ms: 0, eta_ms: 0, queued: null, last_error: null },
    notes: [
      { at: hhmm(now - 9 * MIN), text: 'Yes given, runs on the next pass: Sweep old log files', tone: 'ok' },
    ],
    relay: {
      enabled: true, online: relayOnline, reason: relayOnline ? null : 'no_heartbeat',
      session: relayOnline ? { id_short: 'a1b2c3d4', surface_ok: true, busy: false, at_ms: now - 2000 } : null,
      records: empty ? [] : [
        { id: '20261009T071000-1a2b3c4d', kind: 'overview', created_ms: now - 30 * MIN, status: 'answered',
          preview: 'My briefing state from the dashboard (09:10): 2 for you today, next: Review the demo report',
          answer: '1. Review the demo report first, it is due tomorrow and only you can do it.\n2. Give your yes to the two label and docs items, they run alone.\n3. The flaky test can wait until after the team call.',
          answered_ms: now - 29 * MIN },
      ],
    },
    cmux: { ok: true, error: null },
    sessions: { at_ms: now - 8000, sessions: empty ? [] : [
      { id: '7a16c7b2', pid: 101, name: 'demo-bridge-fc', project: 'demo-bridge', cwd: '/demo/bridge', here: true, status: 'busy',
        since_ms: now - 4 * MIN, started_ms: now - 95 * MIN, kind: 'interactive', version: '2.1.0', remote: true,
        tab: { ref: 'surface:3', name: 'Control', workspace: 'Control', state: 'working', is_control: true },
        agents: { running_count: 2, done_recent: 3, running: [
          { id: 'a1efe80', type: 'code-reviewer', description: 'Review the dashboard change', since_ms: now - 2 * MIN, background: true },
          { id: 'b77c012', type: 'Explore', description: 'Find where sessions are stored', since_ms: now - 40000, background: false }] },
        workflows: [{ name: 'demo-build', status: 'running', agents: 6, since_ms: now - 12 * MIN }] },
      { id: 'd8db96ad', pid: 102, name: 'demo-bridge-4b', project: 'demo-bridge', cwd: '/demo/bridge', here: true, status: 'idle',
        since_ms: now - 31 * MIN, started_ms: now - 5 * 60 * MIN, kind: 'interactive', version: '2.1.0', remote: false,
        tab: { ref: 'surface:7', name: 'alpha-release', workspace: 'Ops', state: 'needs-you', is_control: false },
        agents: { running_count: 0, done_recent: 0, running: [] }, workflows: [] },
      { id: '3c9a1e44', pid: 103, name: 'other-repo-2a', project: 'other-repo', cwd: '/demo/other-repo', here: false, status: 'busy',
        since_ms: now - 9 * MIN, started_ms: now - 20 * MIN, kind: 'interactive', version: '2.1.0', remote: false,
        tab: null, agents: { running_count: 1, done_recent: 0, running: [
          { id: 'c03f9aa', type: 'general-purpose', description: 'Run the migration tests', since_ms: now - 6 * MIN, background: true }] },
        workflows: [] },
    ] },
  }, WORDS[opts.lang])
}

function inboxDetail(id, state) {
  const r = [...(state.model?.sections ?? []).flatMap(s => s.rows)].find(x => x.inbox_id === id)
  const hasAction = !!r?.has_action
  return {
    ok: true, id,
    item: {
      summary: r?.title ?? 'Example item', detail: 'Invented example detail.\nThe item came from a demo check and carries no real data.',
      kind: hasAction ? 'approval' : 'todo', gate: r?.gate ?? 'only-you', urgency: r?.urgency ?? null, state: r?.inbox_state ?? 'open',
      task: r?.task ?? null, due: r?.due ?? null, key: r?.inbox_key ?? 'example', from: 'demo-check', created: '2026-10-09T09:00:00',
      action_display: hasAction ? 'python3 scripts/example-tool.py --apply demo' : null, has_closes_when: hasAction,
    },
    events: [
      { verb: 'add', by: 'demo-check', at: '2026-10-09T09:00:00' },
      { verb: 'note', by: 'web', at: '2026-10-09T09:05:00', note: 'looked at it, fine' },
    ],
  }
}

// an opened GitHub row (briefing.py detail): made up, in the shape the server sends
function githubDetail(ref) {
  const pr = /#14$/.test(ref ?? '')
  const ago = d => new Date(Date.now() - d * 86400000).toISOString()
  return {
    ok: true, ref, type: pr ? 'pr' : 'issue', title: pr ? 'Retry the flaky parser test' : 'Flaky test in the parser suite',
    url: 'https://example.org/repo/issues/12', state: 'open', draft: false, author: 'demo-user', created: ago(6), updated: ago(1),
    body: '## What happens\n\nThe parser suite fails about one run in ten on CI.\n\n- only on the slow runner\n- never locally\n\n```\nAssertionError: expected 3 tokens, got 2\n```',
    assignees: ['demo-user'], labels: [{ name: 'bug', color: 'd73a4a' }, { name: 'ci', color: '0e8a16' }], milestone: null,
    comments: { total: 2, items: [
      { author: 'teammate', at: ago(2), url: null, body: 'Seen it twice this week, both on the slow runner.' },
      { author: 'demo-user', at: ago(1), url: null, body: 'A retry would hide it. **Fix the timing** instead?' }] },
    boards: [{ title: 'Demo board', number: 3, status: 'In Progress' }],
    ...(pr ? { pr: { head: 'fix/parser-timing', base: 'main', additions: 42, deletions: 7, files: 3, review: 'review_required',
      requested: ['teammate'], reviews: [], checks: { state: 'pending', total: 6, failing: [], running: ['tests'] } }, closes: [] }
      : { prs: [{ number: 14, title: 'Retry the flaky parser test', url: 'https://example.org/repo/pull/14', state: 'open', draft: true }] }),
    fetched_at: new Date().toISOString(),
  }
}

function taskDetail(slug) {
  return {
    ok: true, slug, kind: 'task', path: `work/tasks/${slug}/STATUS.md`,
    front: { type: 'feature', status: 'doing', priority: 'P1', created: '2026-10-01', last_updated: '2026-10-08',
      headline: 'Onboarding guide for the demo project', origin: 'team call on 2026-09-30', blocked_by: null },
    sections: [
      { heading: 'Goal', text: 'A new team member sets up the demo project in under an hour, with every step written down.', truncated: false },
      { heading: 'Next', text: '- Draft the first two chapters\n- Collect screenshots from the example setup', truncated: false },
      { heading: 'Log', text: '2026-10-08: outline written, examples collected\n2026-10-03: task opened', truncated: false },
    ],
    log: [
      { at: '2026-10-08 16:20', glyph: 'n', context: slug, text: 'Outline written, examples collected' },
      { at: '2026-10-03 11:05', glyph: 'n', context: slug, text: 'Task opened after the team call' },
    ],
  }
}

// the tokens of the week (usage.py view()): invented counts per day and source, today a little loud
function usageView(now) {
  const per = [[38, 9, 4], [52, 14, 0], [0, 0, 0], [61, 22, 6], [44, 11, 3], [57, 18, 5], [96, 31, 7]]
  const models = ['claude-opus-5-5', 'claude-sonnet-5-5', 'claude-haiku-5-5']
  const projects = ['demo-project', 'docs-site', 'example-tools']
  const total = { input: 0, output: 0, cache_read: 0, cache_write: 0 }
  const days = per.map(([session, subagent, worker], i) => {
    const day = isoIn(i - 6, now)
    const sources = Object.fromEntries([['session', session], ['subagent', subagent], ['worker', worker]].map(([s, k]) => {
      const counts = { input: k * 300, output: k * 1000, cache_read: k * 42000, cache_write: k * 2600 }
      for (const f of Object.keys(total)) total[f] += counts[f]
      return [s, counts]
    }))
    const output = (session + subagent + worker) * 1000
    const split = (names, key) => output ? names.map((n, j) => ({ [key]: n, output: Math.round(output * [0.6, 0.3, 0.1][j]) })) : []
    return { day, sources, output, models: split(models, 'model'), projects: split(projects, 'project') }
  })
  const sum = names => names.map((n, j) => ({ n, output: days.reduce((a, d) => a + (d.models[j]?.output ?? 0), 0) }))
  return { days, total, models: sum(models).map(x => ({ model: x.n, output: x.output })), projects: sum(projects).map(x => ({ project: x.n, output: x.output })),
    outliers: [{ source: 'subagent', today: 31000, usual: 14000, factor: 2.2 }] }
}

// the knowledge graph (graph.py view()): a small invented Bridge, its config entries, tasks and the files they name
const GRAPH_NODES = [
  ['bridge-config.yaml', 'core', 'core', 'Bridge configuration'],
  ['identity/personas/demo-user.yaml', 'identity', 'personas', 'Demo user'],
  ['identity/mandants/demo-team.yaml', 'identity', 'mandants', 'Demo team'],
  ['infra/remotes/homebox.yaml', 'infra', 'remotes', 'The always-on example machine'],
  ['infra/channels/mail.yaml', 'infra', 'channels', 'Mail drafts'],
  ['workflow/projects/demo-board.yaml', 'workflow', 'projects', 'Demo board'],
  ['workflow/contexts/demo.yaml', 'workflow', 'contexts', 'Demo project'],
  ['workflow/briefings/morning.yaml', 'workflow', 'briefings', 'Morning briefing'],
  ['workflow/workloads/mail-watcher.yaml', 'workflow', 'workloads', 'Mail watcher'],
  ['work/tasks/demo-task/STATUS.md', 'work', 'tasks', 'Onboarding guide for the demo project', 'doing'],
  ['work/tasks/docs-refresh/STATUS.md', 'work', 'tasks', 'Refresh the docs index', 'doing'],
  ['work/tasks/alpha-release/STATUS.md', 'work', 'tasks', 'Prepare the alpha release notes', 'doing'],
  ['docs/demo-guide.md', 'docs', 'docs', '', null, true],
]
const GRAPH_EDGES = [
  ['workflow/contexts/demo.yaml', 'workflow/projects/demo-board.yaml', 'project_ref', 'ref'],
  ['workflow/contexts/demo.yaml', 'identity/mandants/demo-team.yaml', 'mandant_ref', 'ref'],
  ['identity/mandants/demo-team.yaml', 'identity/personas/demo-user.yaml', 'persona_ref', 'ref'],
  ['workflow/briefings/morning.yaml', 'workflow/projects/demo-board.yaml', 'project_ref', 'ref'],
  ['workflow/workloads/mail-watcher.yaml', 'infra/remotes/homebox.yaml', 'remote_ref', 'ref'],
  ['workflow/workloads/mail-watcher.yaml', 'infra/channels/mail.yaml', 'channel_ref', 'ref'],
  ['work/tasks/demo-task/STATUS.md', 'workflow/contexts/demo.yaml', 'context_ref', 'ref'],
  ['work/tasks/demo-task/STATUS.md', 'docs/demo-guide.md', 'deliverable', 'path'],
  ['work/tasks/docs-refresh/STATUS.md', 'docs/demo-guide.md', 'deliverable', 'path'],
  ['work/tasks/alpha-release/STATUS.md', 'workflow/projects/demo-board.yaml', 'project_ref', 'ref'],
  ['bridge-config.yaml', 'workflow/briefings/morning.yaml', 'profile', 'path'],
]

function graphView() {
  const edges = GRAPH_EDGES.map(([s, t, key, kind]) => ({ s, t, key, kind }))
  const degree = id => edges.filter(e => e.s === id || e.t === id).length
  const nodes = GRAPH_NODES.map(([id, group, family, title, status = null, leaf = false]) => ({
    id, group, family, label: id.endsWith('/STATUS.md') ? id.split('/').at(-2) : id.split('/').at(-1).replace(/\.[a-z]+$/, ''),
    title, status, ...(leaf ? { leaf: true } : {}), degree: degree(id) }))
  return { nodes, edges }
}

function graphNode(id) {
  const g = graphView()
  const n = g.nodes.find(x => x.id === id)
  if (!n) return null
  const text = id.endsWith('.md') ? `# ${n.title || n.label}\n\nInvented example text: nothing here comes from a real Bridge.\n`
    : `# invented example entry\ntitle: ${n.title}\n${g.edges.filter(e => e.s === id).map(e => `${e.key}: ${e.t.split('/').at(-1).replace(/\.yaml$/, '')}`).join('\n')}\n`
  return { id, text, cut: false, out: g.edges.filter(e => e.s === id), in: g.edges.filter(e => e.t === id) }
}

// what the dashboard closed, dropped or hid (history.py state()), newest first, each with its undo
function historyItem(key, title, kind, did, ident) {
  return { key, title, kind, did, ident, undone_ms: null,
    undo: kind === 'task' ? { verb: 'task_reopen', args: { slug: ident } } : kind === 'inbox' ? { verb: 'inbox_reopen', args: { id: ident } }
      : { verb: 'unhide', args: { key } } }
}

function historyEntries(now) {
  const it = historyItem
  return [
    { id: 'h0a1b2c3d4e', at_ms: now - 40 * MIN, verb: 'done', backfilled: false,
      items: [it('inbox:20261009-0800-demo-renewal-9f8e', 'Renew the test certificate', 'inbox', 'done', '20261009-0800-demo-renewal-9f8e')] },
    { id: 'h1b2c3d4e5f', at_ms: now - 3 * 3600000, verb: 'hide', backfilled: false,
      items: [it('gh:example/repo#9', 'Waiting for the reply on the license question', 'other', `hidden until ${isoIn(3, now)}`, null)] },
    { id: 'h2c3d4e5f60', at_ms: now - DAY - 2 * 3600000, verb: 'task_close', backfilled: false,
      items: [it('task:old-fixtures', 'Clean up the old example fixtures', 'task', 'done', 'old-fixtures'),
        it('task:old-notes', 'Tidy the old setup notes', 'task', 'declined', 'old-notes')] },
  ]
}

// the other Bridges and A2A agents (agents.py state()): what their cards say and one conversation
function agentsState(now) {
  const card = (name, description, skills) => ({ name, description, version: '0.4.0', protocol: '0.3', binding: 'JSONRPC',
    provider: { name: 'Example Org' }, endpoint: 'https://example.org/a2a/', input: ['text'], output: ['text'], streaming: false, docs: null, skills })
  return {
    peers: [
      { id: 'team-bridge', reach: 'ok', last_error: null, summary: 'The Bridge of a teammate: board, docs and release questions',
        owner: 'teammate', network: 'tailnet', needs_token: true, usage: { allowed: ['ask', 'task'], human_gate: 'the owner confirms every task' },
        card: card('Team Bridge', 'Answers questions about the demo project and takes small tasks.', [
          { id: 'status', name: 'Project status', description: 'Says where the demo project stands: open items, the next release, who works on what.',
            tags: ['board'], examples: ['Where does the alpha release stand?'] },
          { id: 'docs', name: 'Docs lookup', description: 'Finds the page in the project docs that answers a question.', tags: ['docs'], examples: ['Where is the setup guide?'] }]),
        card_error: null, card_at_ms: now - 15 * MIN, last_ms: now - 2 * 3600000 },
      { id: 'docs-agent', reach: 'unknown', last_error: null, summary: 'An example agent for the public docs', owner: null, network: 'public',
        needs_token: false, usage: { allowed: ['ask'], human_gate: null }, card: null, card_error: null, card_at_ms: null, last_ms: null },
    ],
    convs: [
      { id: 'g0a1b2c3d4e', peer: 'team-bridge', started_ms: now - 2 * 3600000 - 5 * MIN, last_ms: now - 2 * 3600000, context_id: 'ctx-demo', running: false,
        turns: [{ q: 'Where does the alpha release stand?', mode: 'ask', a: 'Two of five items are open, the release notes and one test fix. The date holds.',
          state: 'completed', task_id: null, waiting: false, at_ms: now - 2 * 3600000 - 5 * MIN, answered_ms: now - 2 * 3600000, error: null }] },
    ],
  }
}

// the triage (triage.py state()): one line per task and inbox row of the demo, the last run 20 minutes ago
function triageState(now, running = null) {
  // effort is for the AI only: a row the person does carries none (triage.py)
  const x = (kind, title, gist, verdict, doer, effort, extra = {}) => ({ kind, title, gist, verdict, reason: null, doer, effort, why: null,
    verdict_from: 'haiku', model: 'haiku-5-5', level: effort === 'small' ? 1 : 2, jev: null, ...extra })
  const items = {
    'task:demo-task': x('task', 'Write the onboarding guide for the demo project', 'A setup guide for new team members', 'continue', 'either', 'medium'),
    'task:docs-refresh': x('task', 'Refresh the docs index', 'Rebuild the index after the folder change', 'continue', 'ai', 'small'),
    'task:alpha-release': x('task', 'Prepare the alpha release notes', 'Release notes from the merged changes', 'continue', 'you', null,
      { why: 'the wording for the announcement' }),
    'inbox:demo-inbox-4': x('inbox', 'Release checklist', 'A review asked on the checklist PR', 'unclear', 'you', null, { reason: 'no answer from the team yet' }),
    'inbox:20261009-0900-review-demo-a1b2': x('inbox', 'Review the demo report', 'The report waits for a read', 'close', 'you', null,
      { reason: 'the linked issue is closed' }),
  }
  return { running, error: null, items,
    last: { at: localIso(now - 20 * MIN), count: Object.keys(items).length, cost_ct: 0.42, cost_known: true, calls: 2, model: 'haiku-5-5', duration_sec: 18.5 } }
}

// a Jev order of a work page (jev.py rank()): the page's task and inbox rows, by an invented priority
function jevOrder(page, now) {
  const keys = []
  for (const sec of page.sections ?? []) for (const it of sec.items ?? []) {
    const key = it.inbox ? `inbox:${it.inbox}` : it.task ? `task:${it.task}` : null
    if (key && !keys.some(k => k.key === key)) keys.push({ key, title: it.title })
  }
  const items = keys.map((k, i) => {
    const u = Math.max(0.2, 0.9 - i * 0.2), im = i < 2 ? 0.8 : 0.4, ef = i % 2 ? 0.3 : 0.6, me = i === 0 ? 0.7 : 0.3
    const priority = Math.round((0.42 * u + 0.38 * im + 0.12 * (1 - ef)) * 1000) / 1000
    return { key: k.key, rank: i + 1, title: k.title, urgency: u, impact: im, effort: ef, only_me: me, first: i ? 0.1 : 0.6, priority, confidence: 0.8,
      quadrant: u >= 0.5 && im >= 0.5 ? 'now' : im >= 0.5 ? 'plan' : u >= 0.5 ? 'hand' : 'drop', who: me >= 0.5 ? 'me' : 'delegate' }
  })
  return { at_ms: now, day: isoIn(0, now), took_ms: 2400, calls: 1, sent: items.length, skipped: { private: 0, section: 0, triage: 0, over: 0 },
    first: items[0]?.key ?? null, items, usage: { input_tokens: 1840, output_tokens: 220 }, price: null }
}

/** A transport with the same interface as the real one, backed by the example state */
export function createMockTransport(opts = {}) {
  const now = () => Date.now()
  let state = buildState(now(), opts)
  let handlers = {}
  const mockMutes = [{ id: '20261008-0900-board-radar-0a1b', source: 'board-radar', scope: 'family', key_prefix: 'radar:stale:' }]   // invented, for the noise card
  let seq = state.model.seq
  const jev = createMockJev ? createMockJev() : null   // the Jev tab's mock: the server's once-per-day rule, invented tokens
  const history = opts.empty ? [] : historyEntries(now())
  const orders = {}                                       // the kept Jev order per work page, as jev.py keeps it
  const words = WORDS[opts.lang]
  const emit = (name, payload) => { if (handlers[name]) handlers[name](localize(payload, words)) }
  const note = (text, tone = 'info') => emit('note', { at: hhmm(now()), text, tone })
  const ok = data => ({ status: 200, ok: true, data: localize(data, words), error: null })
  const fail = (status, code, message, extra = {}) => ({ status, ok: false, data: { ok: false, ...extra, error: { code, message, field: null } }, error: { code, message, field: null } })

  // what a close, drop or hide leaves in the history drawer, in the shape history.py keeps
  const remember = (verb, keys) => {
    const rows = state.model.sections.flatMap(s => s.rows)
    const items = keys.map(key => {
      const r = rows.find(x => x.key === key)
      const kind = key.startsWith('task:') ? 'task' : r?.inbox_id ? 'inbox' : 'other'
      const ident = kind === 'task' ? key.slice(5) : kind === 'inbox' ? r.inbox_id : null
      return historyItem(key, r?.title ?? key, kind, verb === 'drop' ? 'dropped' : verb === 'hide' ? `hidden until ${isoIn(3, now())}` : 'done', ident)
    })
    history.unshift({ id: `h${Math.random().toString(16).slice(2, 12).padEnd(10, '0')}`, at_ms: now(), verb, items, backfilled: false })
  }
  const removeRows = keys => {
    for (const s of state.model.sections) {
      s.rows = s.rows.filter(r => !keys.includes(r.key))
      s.compact = s.compact.filter(k => !keys.includes(k))
      s.total = s.rows.length
    }
    state.model.approvable = state.model.approvable.filter(k => !keys.includes(k))
    state.model.task_rows = state.model.task_rows.filter(r => !keys.includes(r.key))
    state.model.review = { ...state.model.review, keys: state.model.review.keys.filter(k => !keys.includes(k)) }
    seq += 1
    state.model = { ...state.model, seq }
    setTimeout(() => emit('view', state.model), 300)
  }

  return {
    async get(path) {
      const [pathname, query = ''] = path.split('?')
      const url = { pathname, searchParams: new URLSearchParams(query) }
      if (url.pathname === '/api/bootstrap') {
        if (opts.auth === false) return fail(401, 'unauthorized', 'no cookie')
        return ok({ ok: true, csrf: 'mock', language: opts.lang || 'en', version: '0.1.0',
          config: { port: 8797, relay: true, tabs_seconds: 10, full_minutes: 10, voice: false, target: 'area', control: 'Control', profile: 'morning' } })
      }
      if (url.pathname === '/api/state') return ok(state)
      if (url.pathname === '/api/inbox') return ok(inboxDetail(url.searchParams.get('id'), state))
      if (url.pathname === '/api/task') return ok(taskDetail(url.searchParams.get('slug')))
      if (url.pathname === '/api/inbox/noise') {
        // invented sources and one invented rule, in the shape of `inbox.py stats --json` and `mute list --json`
        const src = (source, filed, dropped, reasons, muted = 0) => ({ source, filed, dropped, muted, done: filed - dropped - muted - 1, open: 1,
          share: Math.round(dropped / filed * 100) / 100, reasons })
        return ok({ ok: true, noise: { days: 30,
          sources: [src('homebox/health', 12, 5, { once: 3, family: 2 }, 2), src('board-radar', 8, 2, { duplicate: 2 }), src('mail-watcher', 20, 1, { unknown: 1 })],
          mutes: mockMutes } })
      }
      if (url.pathname === '/api/github') return ok(githubDetail(url.searchParams.get('ref')))
      if (url.pathname === '/api/relay') return ok(state.relay)
      if (url.pathname === '/api/workers') {
        // invented runs in the shape of `workload view --json`; nothing here is a real machine
        const run = (id, system, kind, state, when, marks, strip, findings = []) => ({ id, title: id.replace(/-/g, ' '), purpose: `Example run ${id}`,
          system, kind, sphere: system === 'mail' ? 'work' : 'private', host: 'homebox', runtime: 'launchd', owner: 'bridge', when,
          unit: `bridge.${id}`, log: `~/.bridge/workloads/${id}.out`, program: `scripts/${id}.sh`, program_where: 'repository', retired: false,
          state, severity: findings[0]?.severity ?? 'none', findings, continuous: kind === 'daemon',
          strip: strip.map((v, i) => ({ at: `2026-10-10T${String(6 + i).padStart(2, '0')}:00:00Z`, rc: v === 'failed' ? 1 : 0, verdict: v })),
          day: { marks: marks.map(p => ({ at_pct: p, label: `${Math.round(p * 0.24)}:00` })), trace_pct: marks.length ? marks[0] : null, trace_at: '', trace_label: 'last run', note: kind === 'daemon' ? 'runs all the time' : '' },
          week: [false, true, true, true, true, true, false], month_due: [], ran_days: ['2026-10-09', '2026-10-10'] })
        return ok({ ok: true, view: { schema: 1, host: 'homebox', generated_at: new Date(now() - 12 * MIN).toISOString(), zone: 'Europe/Berlin',
          stats: { in_service: 5, with_findings: 2, not_reported: 0, retired: 1 },
          systems: [{ id: 'mail', title: 'Mail', count: 2 }, { id: 'board', title: 'Board', count: 2 }],
          runs: [
            run('mail-watcher', 'mail', 'interval', 'in_sync', 'every 300 s', [], ['ok', 'ok', 'ok', 'ok', 'ok', 'ok']),
            run('mail-digest', 'mail', 'recurring', 'in_sync', 'daily 07:20', [30], ['ok', 'ok', 'skipped', 'ok']),
            run('board-pilot', 'board', 'daemon', 'absent', 'all the time', [], ['ok', 'failed', 'failed'],
              [{ state: 'absent', severity: 'high', detail: 'provisioned once, but nothing on the machine carries it any more', hint: 'provision it again, or retire the declaration' }]),
            run('board-report', 'board', 'recurring', 'drifted', 'Mon to Fri 08:00 and 17:00', [33, 71], ['ok', 'expired', 'ok'],
              [{ state: 'drifted', severity: 'medium', detail: 'the unit differs from its declaration', hint: 'provision it again' }]),
            run('backup-sync', '', 'recurring', 'intentionally_absent', 'daily 02:00', [8], []),
          ],
          elsewhere: { inventory_stale: [], intentionally_absent: ['backup-sync'], undeclared: { named: [], counted: 12 } } } })
      }
      if (url.pathname === '/api/tab/screen') {
        const tab = state.tabs.tabs.find(x => x.ref === url.searchParams.get('ref'))
        if (!tab) return fail(404, 'not_found', 'no such tab')
        const text = ['❯ ' + (tab.last || 'Go on with the task'), '', '⏺ Reading the task folder and the last log rows.',
          '  ⎿  Read work/tasks/demo-task/STATUS.md (48 lines)', '', '⏺ ' + (tab.state === 'needs-you' ? 'Allow edit of README.md?' : 'Working on the next step.'),
          '', '─'.repeat(40), '> '].join('\n')
        return ok({ ok: true, ref: tab.ref, name: tab.name, state: tab.state, workspace: tab.workspace, text, at_ms: now() })
      }
      if (url.pathname === '/api/history') return ok({ ok: true, entries: history })
      if (url.pathname === '/api/agents') return ok({ ok: true, ...state.agents })
      if (url.pathname === '/api/ticker') return ok({ ok: true, ticker: state.ticker })
      if (url.pathname === '/api/usage') return ok({ ok: true, usage: usageView(now()) })
      if (url.pathname === '/api/graph') return ok({ ok: true, ...graphView() })
      if (url.pathname === '/api/graph/node') {
        const found = graphNode(url.searchParams.get('id'))
        return found ? ok({ ok: true, ...found }) : fail(404, 'not_found', 'no such node')
      }
      if (url.pathname === '/api/page') {
        const page = state.model.pages.find(p => p.id === url.searchParams.get('page'))
        const section = page?.sections.find(s => s.id === url.searchParams.get('section'))
        if (!section) return fail(404, 'not_found', 'unknown page or section')
        const extra = [3, 4].map(i => ({ index: i, title: `example/repo#${20 + i} Follow up item ${i}`, detail: 'Backlog', when: 'Fri', tone: null,
          link: { kind: 'web', href: `https://example.org/repo/issues/${20 + i}` }, task: null, ask: true, mark: null, priority: null, state: null,
          lines: [], starting: false, tab: null }))
        return ok({ ok: true, items: [...section.items, ...extra], total: section.total })
      }
      return fail(404, 'not_found', 'unknown path')
    },
    async post(path, body) {
      await new Promise(r => setTimeout(r, 250))
      if (path === '/api/reload') {
        const loading = { pass: 'quick', fresh: !!body?.fresh, started_ms: now(), eta_ms: 3000, queued: 'full', last_error: null }
        state.loading = loading
        emit('loading', loading)
        setTimeout(() => {
          state.loading = { pass: null, fresh: false, started_ms: 0, eta_ms: 0, queued: null, last_error: null }
          seq += 1
          state.model = { ...state.model, seq, collected_at: hhmm(now()), collected_ms: now(), full_ms: now() }
          emit('loading', state.loading)
          emit('view', state.model)
        }, 3000)
        return { status: 202, ok: true, data: { ok: true, loading }, error: null }
      }
      if (path === '/api/ask' && body?.via === 'quick') {
        // a short session of its own: invented answer, invented cost, nothing is asked for real
        const model = body.model || 'haiku'
        const q = body?.kind === 'free' ? String(body.args?.text ?? '') : `Example question of kind ${body?.kind}`
        let conv = state.quick.convs.find(c => c.id === body.conv)
        if (!conv) {
          conv = { id: `q${Math.random().toString(16).slice(2, 12).padEnd(10, '0')}`, kind: body.kind, started_ms: now(), session: null, total_usd: 0, turns: [], running: false }
          state.quick = { ...state.quick, convs: [conv, ...state.quick.convs] }
        }
        conv.turns.push({ q, a: null, model_asked: model, model: null, cost_usd: null, at_ms: now(), error: null })
        conv.running = true
        emit('quick', JSON.parse(JSON.stringify(state.quick)))
        setTimeout(() => {
          const t = conv.turns[conv.turns.length - 1]
          t.a = 'Example answer from the mock. Seven of eleven steps are done; the next one is the yaml change in this repository.\nNothing was asked for real.'
          t.model = `${model}-5-5`
          t.cost_usd = { haiku: 0.0021, sonnet: 0.011, opus: 0.054 }[model] ?? 0.002
          conv.running = false
          emit('quick', JSON.parse(JSON.stringify(state.quick)))
        }, 2200)
        return { status: 202, ok: true, data: { ok: true, conv: conv.id }, error: null }
      }
      if (path === '/api/ask') {
        const id = `${new Date().toISOString().replace(/[-:]/g, '').slice(0, 15)}-${Math.random().toString(16).slice(2, 10)}`
        const preview = body?.kind === 'free' ? String(body.args?.text ?? '') : `Example prompt of kind ${body?.kind}`
        if (!state.relay.online) {
          const record = { id, kind: body?.kind, created_ms: now(), status: 'offline', preview: preview.slice(0, 200), answer: null, answered_ms: null }
          return fail(409, 'relay_offline', 'relay offline', { record, fallback: { available: true, tab: { ref: 'surface:3', name: 'Control', state: 'waiting' } } })
        }
        const record = { id, kind: body?.kind, created_ms: now(), status: 'queued', preview: preview.slice(0, 200), answer: null, answered_ms: null }
        setTimeout(() => emit('relay', { ...record, status: 'submitted' }), 900)
        setTimeout(() => emit('relay', { ...record, status: 'answered', answered_ms: now(),
          answer: 'Example answer from the mock: nothing was sent to a real session.\nThe real answer shows here as plain text.' }), 2600)
        return { status: 202, ok: true, data: { ok: true, record }, error: null }
      }
      if (path === '/api/route') {
        if (state.launch.router === 'off') return fail(409, 'launch_off', 'model choice or Auto is off')
        const keys = (body?.keys ?? []).slice(0, 20)
        return ok({ ok: true, routes: Object.fromEntries(keys.map(k => [k, mockRoute(k, state.launch)])) })
      }
      if (path === '/api/triage/run') {
        // a run of a few seconds, then the same lines with a new time; nothing is asked for real
        if (state.triage.running) return { status: 409, ok: false, data: { ok: false, triage: state.triage }, error: null }
        state.triage = { ...state.triage, running: { started_ms: now(), why: 'click' } }
        emit('triage', state.triage)
        setTimeout(() => { state.triage = opts.empty ? { ...state.triage, running: null } : triageState(now()); emit('triage', state.triage) }, 3000)
        return { status: 202, ok: true, data: { ok: true, triage: state.triage }, error: null }
      }
      if (path.startsWith('/api/jev/') && !jev) return fail(404, 'jev_off', 'Jev is off')
      if (path === '/api/jev/rank') {
        const page = state.model.pages.find(p => p.id === body?.page && p.jev)
        if (!page) return fail(404, 'not_found', 'no page with jev: under that id')
        const day = isoIn(0, now())
        if (body.force || (body.daily && orders[page.id]?.day !== day)) {
          await new Promise(res => setTimeout(res, 1200))
          orders[page.id] = jevOrder(page, now())
        }
        return ok({ ok: true, page: page.id, order: orders[page.id] ?? null, today: { day, ratings: 0, input_tokens: 0, output_tokens: 0, unknown: 0 } })
      }
      if (path === '/api/jev/run') {
        // the Jev tab: invented judgments from jev/logic.js, the real API is never asked
        const r = jev(state.model, { force: !!body?.force, cacheOnly: !!body?.cache_only })
        if (r.paid) await new Promise(res => setTimeout(res, 2400))
        return ok(r.result)
      }
      if (path === '/api/action') {
        const verb = body?.verb
        const args = body?.args ?? {}
        const keys = args.keys ?? (args.key ? [args.key] : [])
        const result = { ok: true, verb, note: `Mock: ${verb} ${keys.join(', ') || args.tab_ref || ''}`.trim(), steps: [], settled: [],
          reload: 'none', jump: null, relay: null, confirm: null }
        if (verb === 'approve_all' && !args.confirm) return ok({ ...result, note: '', confirm: { count: keys.length } })
        if (['drop', 'done', 'later', 'hide', 'task_close', 'settle'].includes(verb) || (verb === 'approve_all' && args.confirm)) {
          result.settled = keys
          remember(verb, keys)
          removeRows(keys)
        }
        if (['task_reopen', 'inbox_reopen', 'unhide'].includes(verb)) {
          // the undo of the history drawer: the newest item that hands out exactly this undo is taken back
          const hit = history.flatMap(e => e.items).find(it => !it.undone_ms && it.undo?.verb === verb
            && Object.entries(args).every(([k, v]) => k === 'as' || k === 'note' || it.undo.args[k] === v))
          if (hit) hit.undone_ms = now()
        }
        if (verb === 'drop' && (args.reason === 'family' || args.reason === 'source')) {
          result.muted = `20261010-1200-mock-${mockMutes.length}`
          mockMutes.push({ id: result.muted, source: 'homebox/health', scope: args.reason,
            ...(args.reason === 'source' ? { until: '2026-11-09' } : { key_prefix: 'health:crash:' }) })
        }
        if (verb === 'inbox_unmute') mockMutes.splice(0, mockMutes.length, ...mockMutes.filter(r => r.id !== args.id))
        if (verb === 'snapshot_list') result.note = 'Mock: 3 snapshots, latest 09:00'
        if (verb === 'row_action') result.note = `Mock: the step ${args.action} would start an agent tab on this row`
        if (verb === 'launch_settings' || verb === 'launch_settings_reset') {
          const next = verb === 'launch_settings' ? { ...state.launch.settings, ...(args.settings ?? {}) } : LAUNCH_CONFIG
          state.launch = launchState(next, !!createMockJev)
          result.note = verb === 'launch_settings' ? 'Mock: setting saved' : 'Mock: settings from the config again'
          setTimeout(() => emit('state', state), 80)
        }
        if (verb === 'ticker_settings' || verb === 'ticker_settings_reset') {
          const next = verb === 'ticker_settings' ? { ...state.ticker.settings, ...(args.settings ?? {}) } : TICKER_CONFIG
          state.ticker = tickerState(next, now())
          result.note = verb === 'ticker_settings' ? 'Mock: ticker setting saved' : 'Mock: ticker settings from the config again'
          setTimeout(() => emit('state', state), 80)
        }
        if (verb === 'ticker_refresh') {
          state.ticker = tickerNext(state.ticker, { refreshing: true })
          emit('ticker', state.ticker)      // the start goes out as an event, like the server's
          result.note = 'Mock: reading the feeds'
          setTimeout(() => { state.ticker = tickerNext(state.ticker, { refreshing: false, fetched_ms: now() }); emit('ticker', state.ticker) }, 1500)
        }
        if (verb === 'ticker_edit') {
          // invented picks and short titles after a moment; nothing is asked for real
          const started = now()
          state.ticker = tickerNext(state.ticker, { editor: { ...state.ticker.editor, running: { started_ms: started }, error: null } })
          emit('ticker', state.ticker)
          result.note = 'Mock: the editor is at work, nothing is asked for real'
          setTimeout(() => {
            const short = { r1: 'Agents that ask first make fewer mistakes', a1: 'Example model reads long texts twice as fast', t1: 'Test time cut in half' }
            const items = ['r1', 'a1', 't1'].map(id => state.ticker.items.find(x => x.id === id)).filter(Boolean).map(x => ({ ...x, short: short[x.id] }))
            state.ticker = tickerNext(state.ticker, { items, editor: { ...state.ticker.editor, running: null,
              last: { at_ms: now(), picked: items.length, of: 5, duration_ms: now() - started, cost_usd: 0.0018 } } })
            emit('ticker', state.ticker)
          }, 2500)
        }
        if (verb === 'ticker_profile') {
          const text = args.llm ? 'Example agents, small automation, test speed, long documents' : 'agents, automation, tests, documents'
          state.ticker = tickerNext(state.ticker, { profile: { ...state.ticker.profile, last: { text, llm: !!args.llm, at_ms: now(), from: 4, error: null, cost_usd: null } } })
          emit('ticker', state.ticker)
        }
        if (verb.startsWith('ticker_')) result.ticker = state.ticker
        if (verb === 'task_review') {
          // a check that runs for six seconds, then the same result again with a new time
          const publish = review => { seq += 1; state.model = { ...state.model, seq, review }; emit('view', state.model) }
          publish({ ...state.model.review, running: { started_ms: now(), count: keys.length, escalate: !!args.escalate } })
          setTimeout(() => publish({ ...state.model.review, running: null,
            last: { ...state.model.review.last, reviewed_at: new Date(now()).toISOString().slice(0, 19) } }), 6000)
        }
        setTimeout(() => note(result.note, 'ok'), 50)
        return ok(result)
      }
      return fail(404, 'not_found', 'unknown path')
    },
    events(h, onConn) {
      handlers = h
      setTimeout(() => {
        onConn('open')
        emit('hello', { version: '0.1.0', started_ms: state.server.started_ms, language: opts.lang || 'en' })
        emit('state', state)
      }, 30)
      return { close() { handlers = {} } }
    },
  }
}
