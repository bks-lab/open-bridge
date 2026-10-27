// SPDX-License-Identifier: MIT
// UI texts of the Work through page (rules/language-policy.md section 3): the `flow` part of both tables, side by
// side under identical keys. text.js takes them in as TABLES.en.flow and TABLES.de.flow, so a view reads them
// through T(). Keys and comments are English; only the values of `de` are German. Mouse first: no text names a key.

export const FLOW = {
  en: {
    title: 'Work through',
    progress: (n, m) => `${n} in progress · ${m} open`,
    side: {
      label: 'Group by', themes: 'Themes', areas: 'Areas', allThemes: 'All themes', allAreas: 'All areas', noTheme: 'No theme yet',
      noArea: 'No area', you: n => `${n} need you`, open: n => `${n} open`, asks: 'Something here needs you',
      regroup: 'Order themes again', regrouping: 'Ordering the themes', ordering: 'Haiku gives the new points a theme',
      budget: 'No runs left today: what has no theme yet waits under No theme yet', failed: 'The themes could not be ordered',
      pick: 'Theme or area', move: 'Move to theme', moveLabel: 'Theme of this point', newTheme: 'New theme', newName: 'Name of the new theme',
      rename: 'Rename the theme', renameLabel: 'New name', save: 'Save', cancel: 'Cancel',
    },
    show: { label: 'Show', focus: 'Focus', list: 'List' },
    tabs: { label: 'Open points', count: n => (n === 1 ? '1 point' : `${n} points`) },
    doing: {
      who: 'Who works on it',
      tab: (name, word, ago) => `Agent tab ${name}: ${word}${ago ? `, for ${ago}` : ''}`,
      start: (word, ago) => `Started from the cockpit ${ago} ago, ${word}`,
      session: (name, ago) => `Your session in the tab ${name}${ago ? `, for ${ago}` : ''}`,
      none: d => (d == null ? 'No tab open.' : d === 0 ? 'No tab open, last moved today.' : d === 1 ? 'No tab open, last moved yesterday.' : `No tab open, last moved ${d} days ago.`),
      stage: { started: 'starting', working: 'at work', waiting: 'waiting', 'needs-you': 'asks you', idle: 'quiet' },
      goOn: 'Let AI go on with it',
    },
    walk2: { label: 'Walk through the points', prev: 'Previous point', next: 'Next point', last: 'That was the last point here.',
      nextSide: name => `Next: ${name}`, toSide: 'Go there' },
    details: {
      label: 'Details', hint: 'A click pulls a block in.', loading: 'Reading the task',
      blocks: { goal: 'Goal and story', criteria: 'Acceptance criteria', steps: 'Steps', source: 'Source', notes: 'Notes and log',
        result: 'Result', screen: 'Screen of the tab', related: 'Related' },
      none: { goal: 'No goal written yet.', criteria: 'No criteria written yet.', steps: 'No steps in the file.', source: 'No source named.',
        notes: 'No notes and no log lines yet.', result: 'Nothing came back yet.', screen: 'No tab, so no screen.', related: 'Nothing related.' },
      open: 'Open the link', view: 'View the whole screen', done: 'done', todo: 'open',
    },
    list: {
      label: 'The points of this group', pickAll: 'All', pick: title => `Pick ${title}`, take: 'Take the suggestions',
      picked: n => (n === 1 ? '1 picked' : `${n} picked`), confirm: 'Confirm', cancel: 'Cancel', undo: 'Undo the batch',
      ran: n => (n === 1 ? '1 point decided in one batch' : `${n} points decided in one batch`),
      honest: 'Only suggestions: nothing runs without a click.', none: 'No suggestion',
      from: { triage: day => `from the triage of ${day}`, themes: 'from Haiku now' },
      verb: { done: 'Done', drop: 'Drop', later: 'Later', do: 'Let AI do it', you: 'Needs you' },
      laterUntil: day => `Later until ${day}`, age: d => (d === 0 ? 'today' : `${d} d`),
      cols: { kind: 'Kind', stage: 'Stage', area: 'Area', age: 'Age', suggestion: 'Suggestion' },
      empty: 'Nothing open here.', drop: 'Drop all because', later: 'Later until',
    },
    batch: {
      summary: plan => {
        const p = { counts: {}, reasons: [], days: [], skipped: [], ...(plan && typeof plan === 'object' ? plan : {}) }
        const day = d => { const [, m, x] = String(d).split('-'); return `${['Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'][Number(m) - 1] ?? m} ${Number(x)}` }
        const parts = [p.counts.done ? `${p.counts.done} done` : null,
          p.counts.drop ? `${p.counts.drop} drop${p.reasons.length === 1 ? `: ${p.reasons[0]}` : ''}` : null,
          p.counts.later ? `${p.counts.later} later until ${p.days.map(day).join(', ')}` : null,
          p.counts.do ? `${p.counts.do} to an agent` : null].filter(Boolean)
        const out = p.skipped.length ? `${p.skipped.length} stay out` : null
        return [parts.join(', ') || 'Nothing to do', out].filter(Boolean).join('; ')
      },
    },
    open: n => (n === 1 ? '1 open' : `${n} open`),
    decided: n => `${n} decided here`,
    chipsLabel: 'Show one kind only',
    chips: { all: 'All', you: 'Asks you', running: 'Running', tasks: 'Tasks', reports: 'Reports' },
    lane: {
      label: 'Running', show: 'Show its screen', hide: 'Fold its screen', noScreen: 'Nothing on its screen yet.',
      stage: { started: 'starting', working: 'at work' }, session: 'your session', since: m => `for ${m} min`,
    },
    kind: { back: 'Back from a tab', asks: 'A tab asks', result: 'Finished', idle: 'Quiet', lost: 'Tab gone', question: 'A question for you', doing: 'In progress', task: 'In review', reports: 'Reports' },
    back: name => `Back from the tab ${name}`, backAsk: 'How did it go?', backGone: 'The item of this tab is settled already.',
    started: ago => `started ${ago} ago`, lostSub: 'No tab and no answer since the start.', since: ago => `for ${ago}`,
    idleSub: 'The tab went quiet, no question read on its screen.', result: 'Result', criteria: 'Criteria to check yourself',
    improve: { button: 'Improve', toTab: 'What is still to do, to the tab', anew: 'What is still to do, as a new start', send: 'Send to the tab', restart: 'Start again' },
    forTask: title => `Task: ${title}`,
    verbs: { do: 'Let AI do it', advise: 'Advise', done: 'Done', later: 'Later until', drop: 'Drop because', restart: 'Start again' },
    approve: 'Give your yes', doneClose: 'Done and close the tab', runsOn: 'Runs on', notYet: 'Not yet', toTab: 'To tab', view: 'View',
    start: {
      label: 'What the agent should do', button: 'Start', empty: 'Write what the agent should do first.',
      note: title => `${title}. At the end, write a note "Result: ..." on the item.`,
      manual: 'No terminal driver: start it by hand with these commands.', copy: 'Copy the commands',
      busy: n => (n === 1 ? '1 is running already. Start anyway?' : `${n} are running already. Start anyway?`), anyway: 'Start anyway',
    },
    later: { label: 'Until when', tomorrow: 'Tomorrow', monday: 'Monday', week: 'Next week', date: 'Date', go: 'Put off' },
    drop: {
      label: 'Why it goes', other: 'Another reason', send: 'Drop',
      reason: { resolves_itself: 'Resolves itself', not_needed: 'No longer needed', someone_else: 'Someone else does it', not_worth_it: 'Too big for what it brings' },
    },
    advice: {
      title: 'Advice', running: 'Asking for advice', failed: 'No answer came back.', start: 'Start from it', close: 'Close',
      note: 'Read only: nothing changes until you pick a verb.',
    },
    reports: n => (n === 1 ? '1 report' : `${n} reports`), seen: 'Seen', allSeen: 'All seen',
    walk: { label: 'Walk through the cards', done: 'That was the last card.' },
    left: {
      button: n => `Left out (${n})`, title: 'Left out of the queue',
      reason: { later: 'Put off', waiting: 'Waits on someone else', resting: 'Resting or blocked', stream: 'Streams, they come through their inbox items', idea: 'Ideas and backlog, they wait on the calm card' },
      until: day => `until ${day}`,
    },
    rest: { title: 'All decided.', sub: 'Nothing open waits in the queue.', suggest: 'To start with', none: 'No idea or backlog task to suggest.' },
    noDriver: 'No terminal driver here: agents are not started from this page, so what runs and the agent tabs do not show.',
  },
  de: {
    title: 'Abarbeiten',
    progress: (n, m) => `${n} in Arbeit · ${m} offen`,
    side: {
      label: 'Gruppieren nach', themes: 'Themen', areas: 'Bereiche', allThemes: 'Alle Themen', allAreas: 'Alle Bereiche', noTheme: 'Noch ohne Thema',
      noArea: 'Ohne Bereich', you: n => `${n} brauchen dich`, open: n => `${n} offen`, asks: 'Hier braucht dich etwas',
      regroup: 'Themen neu ordnen', regrouping: 'Themen werden geordnet', ordering: 'Haiku gibt den neuen Punkten ein Thema',
      budget: 'Für heute keine Läufe mehr: was noch kein Thema hat, wartet unter Noch ohne Thema', failed: 'Die Themen ließen sich nicht ordnen',
      pick: 'Thema oder Bereich', move: 'In Thema legen', moveLabel: 'Thema dieses Punkts', newTheme: 'Neues Thema', newName: 'Name des neuen Themas',
      rename: 'Thema umbenennen', renameLabel: 'Neuer Name', save: 'Speichern', cancel: 'Abbrechen',
    },
    show: { label: 'Ansicht', focus: 'Fokus', list: 'Liste' },
    tabs: { label: 'Offene Punkte', count: n => (n === 1 ? '1 Punkt' : `${n} Punkte`) },
    doing: {
      who: 'Wer daran arbeitet',
      tab: (name, word, ago) => `Agent-Tab ${name}: ${word}${ago ? `, seit ${ago}` : ''}`,
      start: (word, ago) => `Vor ${ago} aus dem Cockpit gestartet, ${word}`,
      session: (name, ago) => `Deine Sitzung im Tab ${name}${ago ? `, seit ${ago}` : ''}`,
      none: d => (d == null ? 'Kein Tab offen.' : d === 0 ? 'Kein Tab offen, zuletzt heute bewegt.' : d === 1 ? 'Kein Tab offen, zuletzt gestern bewegt.' : `Kein Tab offen, zuletzt bewegt vor ${d} Tagen.`),
      stage: { started: 'startet', working: 'arbeitet', waiting: 'wartet', 'needs-you': 'fragt dich', idle: 'still' },
      goOn: 'Bridge macht weiter',
    },
    walk2: { label: 'Durch die Punkte gehen', prev: 'Vorheriger Punkt', next: 'Nächster Punkt', last: 'Das war der letzte Punkt hier.',
      nextSide: name => `Weiter mit: ${name}`, toSide: 'Dorthin' },
    details: {
      label: 'Details', hint: 'Ein Klick holt einen Baustein dazu.', loading: 'Aufgabe wird gelesen',
      blocks: { goal: 'Ziel und Story', criteria: 'Akzeptanzkriterien', steps: 'Schritte', source: 'Quelle', notes: 'Notizen und Log',
        result: 'Ergebnis', screen: 'Bildschirm des Tabs', related: 'Verwandtes' },
      none: { goal: 'Noch kein Ziel geschrieben.', criteria: 'Noch keine Kriterien geschrieben.', steps: 'Keine Schritte in der Akte.', source: 'Keine Quelle genannt.',
        notes: 'Noch keine Notizen und keine Logzeilen.', result: 'Noch nichts zurückgekommen.', screen: 'Kein Tab, also kein Bildschirm.', related: 'Nichts Verwandtes.' },
      open: 'Link öffnen', view: 'Ganzen Bildschirm ansehen', done: 'erledigt', todo: 'offen',
    },
    list: {
      label: 'Die Punkte dieser Gruppe', pickAll: 'Alle', pick: title => `${title} auswählen`, take: 'Vorschläge übernehmen',
      picked: n => `${n} ausgewählt`, confirm: 'Bestätigen', cancel: 'Abbrechen', undo: 'Stapel rückgängig',
      ran: n => (n === 1 ? '1 Punkt in einem Stapel entschieden' : `${n} Punkte in einem Stapel entschieden`),
      honest: 'Nur Vorschläge: ohne Klick läuft nichts.', none: 'Kein Vorschlag',
      from: { triage: day => `aus der Sortierung vom ${day}`, themes: 'von Haiku jetzt' },
      verb: { done: 'Erledigt', drop: 'Weg', later: 'Später', do: 'Bridge macht', you: 'Fragt dich' },
      laterUntil: day => `Später bis ${day}`, age: d => (d === 0 ? 'heute' : `${d} T`),
      cols: { kind: 'Art', stage: 'Stand', area: 'Bereich', age: 'Alter', suggestion: 'Vorschlag' },
      empty: 'Hier ist nichts offen.', drop: 'Alle weg, weil', later: 'Später bis',
    },
    batch: {
      summary: plan => {
        const p = { counts: {}, reasons: [], days: [], skipped: [], ...(plan && typeof plan === 'object' ? plan : {}) }
        const day = d => { const [, m, x] = String(d).split('-'); return `${Number(x)}.${Number(m)}.` }
        const parts = [p.counts.done ? `${p.counts.done} erledigt` : null,
          p.counts.drop ? `${p.counts.drop} weg${p.reasons.length === 1 ? `: ${p.reasons[0]}` : ''}` : null,
          p.counts.later ? `${p.counts.later} später bis ${p.days.map(day).join(', ')}` : null,
          p.counts.do ? `${p.counts.do} an einen Agenten` : null].filter(Boolean)
        const out = p.skipped.length ? `${p.skipped.length} bleiben draußen` : null
        return [parts.join(', ') || 'Nichts zu tun', out].filter(Boolean).join('; ')
      },
    },
    open: n => `${n} offen`,
    decided: n => `${n} hier entschieden`,
    chipsLabel: 'Nur eine Art zeigen',
    chips: { all: 'Alle', you: 'Fragt dich', running: 'Läuft', tasks: 'Aufgaben', reports: 'Meldungen' },
    lane: {
      label: 'Läuft', show: 'Bildschirm zeigen', hide: 'Bildschirm einklappen', noScreen: 'Noch nichts auf dem Bildschirm.',
      stage: { started: 'startet', working: 'arbeitet' }, session: 'deine Sitzung', since: m => `seit ${m} Min`,
    },
    kind: { back: 'Zurück aus einem Tab', asks: 'Tab fragt', result: 'Fertig', idle: 'Still', lost: 'Tab verschwunden', question: 'Frage an dich', doing: 'In Arbeit', task: 'In Prüfung', reports: 'Meldungen' },
    back: name => `Zurück aus dem Tab ${name}`, backAsk: 'Wie ging es aus?', backGone: 'Der Eintrag dieses Tabs ist schon erledigt.',
    started: ago => `gestartet vor ${ago}`, lostSub: 'Seit dem Start kein Tab und keine Antwort.', since: ago => `seit ${ago}`,
    idleSub: 'Der Tab ist still, auf seinem Bildschirm keine Frage erkannt.', result: 'Ergebnis', criteria: 'Kriterien zum Selbstprüfen',
    improve: { button: 'Nachbessern', toTab: 'Was noch fehlt, an den Tab', anew: 'Was noch fehlt, als neuer Start', send: 'An den Tab senden', restart: 'Neu starten' },
    forTask: title => `Aufgabe: ${title}`,
    verbs: { do: 'Bridge macht', advise: 'Beraten', done: 'Erledigt', later: 'Später bis', drop: 'Weg, weil', restart: 'Neu starten' },
    approve: 'Ja geben', doneClose: 'Erledigt und Tab schließen', runsOn: 'Läuft weiter', notYet: 'Noch nicht', toTab: 'Zum Tab', view: 'Ansehen',
    start: {
      label: 'Was der Agent tun soll', button: 'Starten', empty: 'Erst schreiben, was der Agent tun soll.',
      note: title => `${title}. Schreib zum Schluss eine Notiz "Ergebnis: ..." an den Eintrag.`,
      manual: 'Kein Terminal-Treiber: von Hand mit diesen Befehlen starten.', copy: 'Befehle kopieren',
      busy: n => (n === 1 ? '1 läuft schon. Trotzdem starten?' : `${n} laufen schon. Trotzdem starten?`), anyway: 'Trotzdem starten',
    },
    later: { label: 'Bis wann', tomorrow: 'Morgen', monday: 'Montag', week: 'Nächste Woche', date: 'Datum', go: 'Verschieben' },
    drop: {
      label: 'Warum es weg kann', other: 'Anderer Grund', send: 'Weg damit',
      reason: { resolves_itself: 'Erledigt sich von selbst', not_needed: 'Nicht mehr nötig', someone_else: 'Macht jemand anders', not_worth_it: 'Zu groß für den Nutzen' },
    },
    advice: {
      title: 'Rat', running: 'Rat wird geholt', failed: 'Keine Antwort gekommen.', start: 'Daraus starten', close: 'Schließen',
      note: 'Nur lesend: nichts ändert sich, bis du ein Verb wählst.',
    },
    reports: n => (n === 1 ? '1 Meldung' : `${n} Meldungen`), seen: 'Gesehen', allSeen: 'Alle gesehen',
    walk: { label: 'Durch die Karten gehen', done: 'Das war die letzte Karte.' },
    left: {
      button: n => `Ausgelassen (${n})`, title: 'Nicht im Band',
      reason: { later: 'Verschoben', waiting: 'Wartet auf jemand anderen', resting: 'Ruht oder blockiert', stream: 'Streams, sie kommen über ihre Posteingangseinträge', idea: 'Ideen und Backlog, sie warten auf der Ruhekarte' },
      until: day => `bis ${day}`,
    },
    rest: { title: 'Alles entschieden.', sub: 'Im Band wartet nichts Offenes.', suggest: 'Zum Starten', none: 'Keine Idee und keine Backlog-Aufgabe zum Vorschlagen.' },
    noDriver: 'Hier gibt es keinen Terminal-Treiber: Agenten starten nicht von dieser Seite, Laufendes und Agenten-Tabs fehlen deshalb.',
  },
}
