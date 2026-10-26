// SPDX-License-Identifier: MIT
// UI texts of the Work through page (rules/language-policy.md section 3): the `flow` part of both tables, side by
// side under identical keys. text.js takes them in as TABLES.en.flow and TABLES.de.flow, so a view reads them
// through T(). Keys and comments are English; only the values of `de` are German. Mouse first: no text names a key.

export const FLOW = {
  en: {
    title: 'Work through',
    open: n => (n === 1 ? '1 open' : `${n} open`),
    decided: n => `${n} decided here`,
    chipsLabel: 'Show one kind only',
    chips: { all: 'All', you: 'Asks you', running: 'Running', tasks: 'Tasks', reports: 'Reports' },
    lane: {
      label: 'Running', show: 'Show its screen', hide: 'Fold its screen', noScreen: 'Nothing on its screen yet.',
      stage: { started: 'starting', working: 'at work' }, since: m => `for ${m} min`,
    },
    kind: { back: 'Back from a tab', asks: 'A tab asks', result: 'Finished', idle: 'Quiet', lost: 'Tab gone', question: 'A question for you', task: 'Task', reports: 'Reports' },
    back: name => `Back from the tab ${name}`, backAsk: 'How did it go?', backGone: 'The item of this tab is settled already.',
    started: ago => `started ${ago} ago`, lostSub: 'No tab and no answer since the start.', since: ago => `for ${ago}`,
    forTask: title => `Task: ${title}`,
    verbs: { do: 'Let AI do it', advise: 'Advise', done: 'Done', later: 'Later until', drop: 'Drop because', restart: 'Start again' },
    approve: 'Give your yes', doneClose: 'Done and close the tab', runsOn: 'Runs on', notYet: 'Not yet', toTab: 'To tab', view: 'View',
    start: {
      label: 'What the agent should do', button: 'Start', empty: 'Write what the agent should do first.',
      note: title => `${title}. At the end, write a note "Result: ..." on the item.`,
      manual: 'No terminal driver: start it by hand with these commands.', copy: 'Copy the commands',
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
    open: n => `${n} offen`,
    decided: n => `${n} hier entschieden`,
    chipsLabel: 'Nur eine Art zeigen',
    chips: { all: 'Alle', you: 'Fragt dich', running: 'Läuft', tasks: 'Aufgaben', reports: 'Meldungen' },
    lane: {
      label: 'Läuft', show: 'Bildschirm zeigen', hide: 'Bildschirm einklappen', noScreen: 'Noch nichts auf dem Bildschirm.',
      stage: { started: 'startet', working: 'arbeitet' }, since: m => `seit ${m} Min`,
    },
    kind: { back: 'Zurück aus einem Tab', asks: 'Tab fragt', result: 'Fertig', idle: 'Still', lost: 'Tab verschwunden', question: 'Frage an dich', task: 'Aufgabe', reports: 'Meldungen' },
    back: name => `Zurück aus dem Tab ${name}`, backAsk: 'Wie ging es aus?', backGone: 'Der Eintrag dieses Tabs ist schon erledigt.',
    started: ago => `gestartet vor ${ago}`, lostSub: 'Seit dem Start kein Tab und keine Antwort.', since: ago => `seit ${ago}`,
    forTask: title => `Aufgabe: ${title}`,
    verbs: { do: 'Bridge macht', advise: 'Beraten', done: 'Erledigt', later: 'Später bis', drop: 'Weg, weil', restart: 'Neu starten' },
    approve: 'Ja geben', doneClose: 'Erledigt und Tab schließen', runsOn: 'Läuft weiter', notYet: 'Noch nicht', toTab: 'Zum Tab', view: 'Ansehen',
    start: {
      label: 'Was der Agent tun soll', button: 'Starten', empty: 'Erst schreiben, was der Agent tun soll.',
      note: title => `${title}. Schreib zum Schluss eine Notiz "Ergebnis: ..." an den Eintrag.`,
      manual: 'Kein Terminal-Treiber: von Hand mit diesen Befehlen starten.', copy: 'Befehle kopieren',
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
