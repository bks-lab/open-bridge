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
    'Result: the vendor takes the current format, nothing to change': 'Ergebnis: Der Anbieter nimmt das jetzige Format, nichts zu ändern',
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
    '2 for you today, coming up: Review the demo report': '2 für dich heute, demnächst: Den Demo-Bericht prüfen',
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
    'Check the release notes': 'Die Release Notes prüfen', 'Summarise the meeting notes': 'Die Besprechungsnotizen zusammenfassen',
    'Find the action items': 'Die offenen Punkte finden', 'Releases and checks': 'Releases und Prüfungen',
    'A second workspace with the same title': 'Ein zweiter Workspace mit demselben Titel',
    // chat and relay
    'My briefing state from the dashboard (09:10): 2 for you today, coming up: Review the demo report':
      'Mein Briefing-Stand aus dem Dashboard (09:10): 2 für dich heute, demnächst: Den Demo-Bericht prüfen',
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
    // the decision guide: invented readings of the waiting tabs
    'Release notes for the alpha release': 'Release Notes für das Alpha-Release', 'Alpha release notes': 'Alpha-Release-Notizen',
    'Prepare the alpha release notes from the merged pull requests': 'Bereite die Alpha-Release-Notes aus den gemergten Pull Requests vor',
    'Sources for the team page of the demo project': 'Quellen für die Teamseite des Demo-Projekts',
    'Find three good sources for the team page and summarise them': 'Finde drei gute Quellen für die Teamseite und fass sie zusammen',
    'Changelog for the coming release': 'Changelog für das kommende Release', 'Changelog entry': 'Changelog-Eintrag',
    'Write the changelog entry for the release': 'Schreib den Changelog-Eintrag für das Release',
    'Now write them into RELEASE_NOTES.md.': 'Schreib sie jetzt in RELEASE_NOTES.md.',
    'Check which of them are recent enough.': 'Prüf, welche davon aktuell genug sind.',
    'I found three sources, all from this year.\n\nShould I summarise them in **team.md**?': 'Ich habe drei Quellen gefunden, alle von diesem Jahr.\n\nSoll ich sie in **team.md** zusammenfassen?',
    'Changelog entry written for the release.': 'Changelog-Eintrag für das Release geschrieben.',
    'The release notes edit is ready; it waits for your permission to write RELEASE_NOTES.md.':
      'Die Änderung der Release Notes steht; sie wartet auf deine Erlaubnis, RELEASE_NOTES.md zu schreiben.',
    'Permission to edit one file.': 'Die Erlaubnis, eine Datei zu ändern.',
    'a single file, easy to review': 'eine einzige Datei, leicht zu prüfen', 'let it plan once more': 'noch einmal planen lassen',
    'Three sources found and read; nothing is written to team.md yet.': 'Drei Quellen gefunden und gelesen; in team.md steht noch nichts.',
    'Whether to summarise the sources in team.md.': 'Ob es die Quellen in team.md zusammenfassen soll.',
    'Summarise': 'Zusammenfassen', 'Yes, summarise them in team.md.': 'Ja, fass sie in team.md zusammen.', 'the sources are read': 'die Quellen sind gelesen',
    'List them first': 'Erst auflisten', 'List the three sources with one line each first.': 'Liste zuerst die drei Quellen mit je einer Zeile auf.',
    'check before writing': 'vor dem Schreiben prüfen',
    'Summarise and push': 'Zusammenfassen und pushen', 'Summarise them in team.md, commit and push.': 'Fass sie in team.md zusammen, committe und pushe.',
    'saves a round trip': 'spart eine Runde',
    'The changelog entry is written; the release itself has not started.': 'Der Changelog-Eintrag ist geschrieben; das Release selbst hat nicht begonnen.',
    'What comes after the changelog.': 'Was nach dem Changelog kommt.',
    'Show the entry': 'Eintrag zeigen', 'Show me the changelog entry.': 'Zeig mir den Changelog-Eintrag.', 'read it before it ships': 'vor dem Ausliefern lesen',
    'Tag the release': 'Release taggen', 'Tag the release and push the tag.': 'Tagge das Release und pushe den Tag.', 'the entry is done': 'der Eintrag ist fertig',
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
    'Mock: Haiku reads the session, nothing is asked for real': 'Demo: Haiku liest die Sitzung, nichts wird wirklich gefragt',
    'Mock: ticker settings from the config again': 'Demo: Band wieder nach Config',
    'Mock: reading the feeds': 'Demo: Feeds werden gelesen',
    'Mock: the editor is at work, nothing is asked for real': 'Demo: die Redaktion arbeitet, nichts wird wirklich gefragt',
    // chats handed on, one per status (handedConvs)
    'Tidy the demo board labels': 'Die Labels auf dem Demo-Board aufräumen',
    'Add a changelog entry for the demo release': 'Einen Changelog-Eintrag für die Demo-Version anlegen',
    'Rename the old demo branch': 'Den alten Demo-Branch umbenennen',
    'Update the example fixtures': 'Die Beispiel-Fixtures aktualisieren',
    'Fix the broken link check': 'Den kaputten Linkcheck reparieren',
    'Move the notes into the docs folder': 'Die Notizen in den Doku-Ordner verschieben',
    'Set up the demo test run': 'Den Demo-Testlauf einrichten',
    'Write the release summary': 'Die Zusammenfassung zur Version schreiben',
    'Plan the next demo sprint': 'Den nächsten Demo-Sprint planen',
    'Check the open demo reviews': 'Die offenen Demo-Reviews prüfen',
    'Sort the demo inbox': 'Den Demo-Posteingang sortieren',
    'Example answer from the mock: the steps are clear, an agent can take it from here.': 'Beispielantwort aus der Demo: die Schritte sind klar, ein Agent kann übernehmen.',
    // the briefs of the cards (views/card.js): goal, story parts, criteria, proposals
    'A new team member sets up the demo project in under an hour': 'Ein neues Teammitglied richtet das Demo-Projekt in unter einer Stunde ein',
    'a new team member': 'neues Teammitglied', 'a written guide for the demo setup': 'eine schriftliche Anleitung für das Demo-Setup',
    'I am ready to work on the first day': 'ich am ersten Tag loslegen kann',
    'Every setup step is written down with its command': 'Jeder Einrichtungsschritt steht mit seinem Befehl da',
    'Two colleagues followed the guide without asking': 'Zwei Kollegen sind der Anleitung ohne Rückfrage gefolgt',
    'The guide is linked from the README': 'Die Anleitung ist im README verlinkt',
    'Readers find every docs page from one index': 'Lesende finden jede Doku-Seite über einen Index',
    'Every page of the docs folder is listed once': 'Jede Seite des Doku-Ordners steht genau einmal da',
    'No link of the index is broken': 'Kein Link des Index ist kaputt',
    'Readers find every page from one index, grouped by topic': 'Lesende finden jede Seite über einen Index, nach Thema gruppiert',
    'a reader of the docs': 'Leser der Doku', 'one index of every page': 'einen Index aller Seiten', 'I never search the folder': 'ich nie den Ordner durchsuchen muss',
    'The index groups the pages by topic': 'Der Index gruppiert die Seiten nach Thema',
    'The alpha release notes name every change since the last tag': 'Die Notizen zur Alpha nennen jede Änderung seit dem letzten Tag',
    'Each change links its pull request': 'Jede Änderung verlinkt ihren Pull Request',
    'The notes are reviewed before the tag is pushed': 'Die Notizen sind geprüft, bevor der Tag gepusht wird',
    'The report of the demo check is ready to read.': 'Der Bericht der Demo-Prüfung liegt zum Lesen bereit.',
    'The work is done and written down in STATUS.md': 'Die Arbeit ist erledigt und in STATUS.md festgehalten',
    'Someone else checked the result': 'Jemand anderes hat das Ergebnis geprüft',
    'First step': 'Erster Schritt',
    // Work through: the themes, the titles and the reasons of the suggestions
    'Release work': 'Release-Arbeit',
    'Docs and guides': 'Doku und Anleitungen',
    'Board hygiene': 'Board-Pflege',
    'Release notes from the merged changes': 'Release Notes aus den gemergten Änderungen',
    'Board: Add a config switch for the report': 'Board: Einen Config-Schalter für den Bericht einbauen',
    'Only you can say if the switch is wanted': 'Nur du kannst sagen, ob der Schalter gewollt ist',
    'the linked issue is closed': 'das verknüpfte Issue ist geschlossen',
    'Polish the wording of the release checklist': 'Den Wortlaut der Release-Checkliste glätten',
    'The wording waits for the release date': 'Der Wortlaut wartet auf das Release-Datum',
    'The fixtures are gone from the repository': 'Die Fixtures sind aus dem Repository verschwunden',
    'Accounts for two new members are ready': 'Zugänge für zwei neue Mitglieder sind bereit',
    'The board was tidied last week': 'Das Board wurde letzte Woche aufgeräumt',
    // Work through, round 3: the activity of the demo task, its summary, the mail note of an instruction
    'Started: find three good sources for the team page': 'Gestartet: drei gute Quellen für die Teamseite finden',
    'Outline agreed with the team, screenshots come next': 'Gliederung mit dem Team abgestimmt, als Nächstes die Screenshots',
    'Outline written, examples collected': 'Gliederung geschrieben, Beispiele gesammelt',
    'example/repo#15 Add a config switch for the report': 'example/repo#15 Einen Config-Schalter für den Bericht einbauen',
    'example/repo#18 Docs: setup guide outline': 'example/repo#18 Doku: Gliederung der Einrichtungsanleitung',
    'Finished: three sources found, the result note is filed': 'Fertig: drei Quellen gefunden, die Ergebnisnotiz ist abgelegt',
    'The new config key needs a line in the setup guide': 'Der neue Config-Schlüssel braucht eine Zeile in der Einrichtungsanleitung',
    'Started: update the setup docs': 'Gestartet: die Einrichtungs-Doku nachziehen',
    'Docs and guides': 'Doku und Anleitungen',
    'Since last week the outline was agreed with the team and the first two chapters stand as a draft. An agent found three sources, and the screenshots come next.':
      'Seit letzter Woche ist die Gliederung mit dem Team abgestimmt, und die ersten zwei Kapitel stehen als Entwurf. Ein Agent hat drei Quellen gefunden, als Nächstes kommen die Screenshots.',
    'A file of the demo, invented: nothing here is real.': 'Eine Datei der Demo, erfunden: nichts hier ist echt.',
    'No verb in the sentence: done, later, drop, a mail or a reply.': 'Kein Verb im Satz: erledigt, später, weg, eine Mail oder eine Antwort.',
    'Write a mail draft with the mail-draft skill, a draft only, never send it': 'Schreibe einen Mail-Entwurf mit dem Skill mail-draft, nur als Entwurf, niemals senden',
    'No verb in this part:': 'Kein Verb in diesem Teil:', 'Started from the cockpit': 'Aus dem Cockpit gestartet',
    // Work through, round 3 after review: the notes the demo gives its verbs, the briefs and steps of its tasks
    'Mock: the note is kept': 'Demo: Notiz gespeichert', 'Mock: decided': 'Demo: entschieden', 'Mock: put off': 'Demo: verschoben',
    'Mock: shelved': 'Demo: zurückgestellt', 'Mock: an agent starts on it': 'Demo: ein Agent fängt damit an', 'Mock: back in the list': 'Demo: wieder in der Liste',
    'Onboard the new team members': 'Die neuen Teammitglieder einarbeiten',
    'Issue example-org/demo-project#12 links the finished guide': 'Issue example-org/demo-project#12 verlinkt die fertige Anleitung',
    ' links the finished guide': ' verlinkt die fertige Anleitung',
    'The open points of the review (§3) are answered': 'Die offenen Punkte des Reviews (§3) sind beantwortet',
    'The open points of the review (': 'Die offenen Punkte des Reviews (', ') are answered': ') sind beantwortet',
    'Done, with its result written down in STATUS.md': 'Erledigt, mit dem Ergebnis in STATUS.md festgehalten',
    'Outline the chapters': 'Die Kapitel gliedern', 'Collect examples from the setup': 'Beispiele aus der Einrichtung sammeln',
    'Write the first two chapters': 'Die ersten zwei Kapitel schreiben', 'Take the screenshots': 'Die Screenshots machen',
    'Let a new colleague try the guide': 'Eine neue Kollegin die Anleitung ausprobieren lassen',
    'List the merged changes since the last tag': 'Die gemergten Änderungen seit dem letzten Tag auflisten',
    'Link each change to its pull request': 'Jede Änderung mit ihrem Pull Request verlinken',
    'Answer the open points of the review': 'Die offenen Punkte des Reviews beantworten', 'Push the tag': 'Den Tag pushen',
    'List every page of the docs folder': 'Jede Seite des Doku-Ordners auflisten', 'Group the pages by topic': 'Die Seiten nach Thema gruppieren',
    'Check every link of the index': 'Jeden Link des Index prüfen',
    'Read what is still open': 'Lesen, was noch offen ist', 'Do the work': 'Die Arbeit erledigen', 'Write the result into STATUS.md': 'Das Ergebnis in STATUS.md schreiben',
    'Outline the guide in chapters, screenshots come next.': 'Die Anleitung in Kapitel gliedern, als Nächstes die Screenshots.',
    // Work through, round 4: what runs, what is not now, two tasks to merge, a question due later
    'Reword the release checklist': 'Die Release-Checkliste umformulieren',
    'Rebuild the search index of the docs site': 'Den Suchindex der Doku-Seite neu bauen',
    'Restart the three test tunnels on Sunday evening': 'Am Sonntagabend die drei Testtunnel neu starten',
    'Check the quote for the new laptops': 'Das Angebot für die neuen Laptops prüfen',
    'Idea: badges for the docs pages': 'Idee: Abzeichen für die Doku-Seiten',
    'Idea: a workshop on the release process': 'Idee: ein Workshop zum Release-Ablauf',
    'Review the pull request for the export fix': 'Den Pull Request für die Export-Korrektur prüfen',
    'Document the new config switch': 'Den neuen Config-Schalter dokumentieren',
    'Order new business cards': 'Neue Visitenkarten bestellen',
    'Send the weekly digest': 'Den Wochenüberblick verschicken',
    'Audit the licenses of the example dependencies': 'Die Lizenzen der Beispiel-Abhängigkeiten prüfen',
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
    status: null, next: null,
    // round 4: when a task last moved (STATUS.md last_updated), the day an item put off comes back
    updated: null, until: null,
    // round 6: the GitHub list the row also stands in (collector.py on_board)
    on_board: null,
    ...over,
  }
}

const A = (id, primary = false, dim = false) => ({ id, primary, dim })

/** Where a row comes from, in the shape the server sends (lib/bridge_cockpit/origin.py classify_row) */
const O = (category, detail = null, raw = null, extra = {}) => ({ category, word_key: null, detail, raw, ref: null, via_cockpit: false, ...extra })

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

// the decision guide (guide.py): a dialog read with its numbered options, a question read with three steps;
// the changelog tab is not read yet, so it shows the button
let guideRev = 0
const GUIDE_READS = {
  'surface:7': { state: 'needs-you', about: 'Release notes for the alpha release',
    topic: { title: 'Alpha release notes', first: 'Prepare the alpha release notes from the merged pull requests', task: 'alpha-release',
      task_title: 'Prepare the alpha release notes', project: 'demo' },
    read: { first: 'Prepare the alpha release notes from the merged pull requests', prev: null, user: 'Now write them into RELEASE_NOTES.md.',
      said: 'Edit file RELEASE_NOTES.md\nDo you want to make this edit?', source: 'screen' }, where: 'The release notes edit is ready; it waits for your permission to write RELEASE_NOTES.md.',
    waits_for: 'Permission to edit one file.', pick: 0, options: [
      { label: 'Yes', send: null, n: 1, why: 'a single file, easy to review', risky: false },
      { label: 'No, and tell Claude what to do differently', send: null, n: 3, why: 'let it plan once more', risky: false }] },
  'surface:12': { state: 'waiting', about: 'Sources for the team page of the demo project',
    topic: { title: null, first: 'Find three good sources for the team page and summarise them', task: 'demo-task',
      task_title: 'Write the onboarding guide for the demo project', project: 'demo' },
    read: { first: 'Find three good sources for the team page and summarise them', prev: null, user: 'Check which of them are recent enough.',
      said: 'I found three sources, all from this year.\n\nShould I summarise them in **team.md**?', source: 'transcript' }, where: 'Three sources found and read; nothing is written to team.md yet.',
    waits_for: 'Whether to summarise the sources in team.md.', pick: 0, options: [
      { label: 'Summarise', send: 'Yes, summarise them in team.md.', n: null, why: 'the sources are read', risky: false },
      { label: 'List them first', send: 'List the three sources with one line each first.', n: null, why: 'check before writing', risky: false },
      { label: 'Summarise and push', send: 'Summarise them in team.md, commit and push.', n: null, why: 'saves a round trip', risky: true }] },
  'surface:13': { state: 'waiting', about: 'Changelog for the coming release',
    topic: { title: 'Changelog entry', first: 'Write the changelog entry for the release', task: null, task_title: null, project: 'demo' },
    read: { first: 'Write the changelog entry for the release', prev: null, user: 'Write the changelog entry for the release',
      said: 'Changelog entry written for the release.', source: 'transcript' }, where: 'The changelog entry is written; the release itself has not started.',
    waits_for: 'What comes after the changelog.', pick: 0, options: [
      { label: 'Show the entry', send: 'Show me the changelog entry.', n: null, why: 'read it before it ships', risky: false },
      { label: 'Tag the release', send: 'Tag the release and push the tag.', n: null, why: 'the entry is done', risky: true }] },
}

/** A reading of a mock tab as the server keeps it: keyed by the question the tab asks */
function guideEntry(ref, tab, now) {
  const read = GUIDE_READS[ref]
  return { ref, key: tab?.ask?.hash ?? `${read.state}:${tab?.since_ms ?? 0}`, auto: true, running: false, started_ms: now - 2 * MIN,
    at_ms: now - 2 * MIN, error: null, cost_usd: 0.0021, source: 'transcript', ...read }
}

/** The guide block of the state: on, reading by itself, the first two waiting tabs read */
function guideState(tabs, now, extra = {}) {
  const byRef = Object.fromEntries(tabs.map(t => [t.ref, t]))
  const entries = Object.fromEntries(['surface:7', 'surface:12'].filter(r => byRef[r]).map(r => [r, guideEntry(r, byRef[r], now)]))
  return { enabled: true, auto: true, per_hour: 30, available: true, overridden: [], rev: ++guideRev, entries, ...extra }
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

// tabs whose state the terminal reads off the title glyph (cmux without a hook): a name of their own would hide
// whether they wait, so the page offers no rename for the agent among them (logic.js canRename)
const GLYPH_TABS = new Set(['surface:9', 'surface:11'])
// what the terminal driver serves (workplace.py caps): everything, renaming workspaces included
const DRIVER_CAPS = ['tabs', 'sessions', 'open', 'launch', 'send', 'rename', 'control', 'focus', 'key', 'screen', 'close',
  'workspaces', 'rename_workspace', 'move_tab', 'set_color', 'set_description']
// the portable workspace colours (workplace.py COLORS): a workspace reports its hex and the name of it
const PALETTE = { Red: '#C0392B', Crimson: '#922B21', Orange: '#A04000', Amber: '#7D6608', Olive: '#4A5C18', Green: '#196F3D',
  Teal: '#006B6B', Aqua: '#0E6B8C', Blue: '#1565C0', Navy: '#1A5276', Indigo: '#283593', Purple: '#6A1B9A', Magenta: '#AD1457',
  Rose: '#880E4F', Brown: '#7B3F00', Charcoal: '#3E4B5E' }
const paletteName = hex => Object.keys(PALETTE).find(k => PALETTE[k] === String(hex ?? '').toUpperCase()) ?? null
// what "Organize with AI" proposes in the demo: one item of every kind, invented, nothing asked for real
function organizeProposal(now) {
  return { id: `o${String(now % 1e10).padStart(10, '0').replace(/[^0-9]/g, '0').slice(0, 10)}`, at_ms: now, scope: 4, items: [
    { id: 'ws_title:workspace:5', kind: 'ws_title', ref: 'workspace:5', from: 'Demo', to: 'Side project', why: 'Two workspaces share the title Demo', cap: 'rename_workspace' },
    { id: 'ws_color:workspace:4', kind: 'ws_color', ref: 'workspace:4', from: null, to: 'Teal', why: 'One colour for the writing', cap: 'set_color' },
    { id: 'ws_description:workspace:4', kind: 'ws_description', ref: 'workspace:4', from: null, to: 'Docs and link checks', why: 'Says what happens here', cap: 'set_description' },
    { id: 'tab_title:surface:11', kind: 'tab_title', ref: 'surface:11', from: 'zsh', to: 'Docs shell', why: 'A shell name says nothing', cap: 'rename' },
    { id: 'tab_move:surface:9', kind: 'tab_move', ref: 'surface:9', from: 'workspace:3', to: 'workspace:4', why: 'Notes belong with the docs', cap: 'move_tab' },
  ] }
}

// the briefs of the demo (card_fields.py shape) and how describe sees them: who wrote them, outdated or not, a proposal
const MOCK_BRIEFS = {
  'task:demo-task': { brief: { goal: 'A new team member sets up the demo project in under an hour',
    story: { as: 'a new team member', want: 'a written guide for the demo setup', so_that: 'I am ready to work on the first day' },
    acceptance: ['Every setup step is written down with its command', 'Two colleagues followed the guide without asking',
      'Issue example-org/demo-project#12 links the finished guide'], by: 'claude-haiku-5-5', at: '2026-10-08', edited: false },
  written: 'ai', stale: false, progress: { done: 2, total: 5 },
  // the parts card.py sends where a criterion names a reference (brief_refs.py): here an issue, as a link
  refs: { goal: null, story: null, acceptance: [null, null, [{ text: 'Issue ' },
    { text: 'example-org/demo-project#12', ref: { kind: 'web', href: 'https://example.org/demo-project/issues/12' } },
    { text: ' links the finished guide' }]] } },
  'task:docs-refresh': { brief: { goal: 'Readers find every docs page from one index',
    acceptance: ['Every page of the docs folder is listed once', 'No link of the index is broken'], by: 'claude-haiku-5-5', at: '2026-10-02', edited: true },
  written: 'human', stale: false, progress: { done: 1, total: 3 },
  proposal: { id: 'd0a1b2c3d4e', by: 'claude-haiku-5-5', brief: { goal: 'Readers find every page from one index, grouped by topic',
    story: { as: 'a reader of the docs', want: 'one index of every page', so_that: 'I never search the folder' },
    acceptance: ['Every page of the docs folder is listed once', 'No link of the index is broken', 'The index groups the pages by topic'] } } },
  'task:alpha-release': { brief: { goal: 'The alpha release notes name every change since the last tag',
    acceptance: ['Each change links its pull request', 'The open points of the review (§3) are answered'], by: 'claude-haiku-5-5', at: '2026-09-28', edited: false },
  written: 'ai', stale: true, progress: { done: 3, total: 4 },
  // a reference nobody can reach from the card: which review? The card says so, and the brief is tried once more
  refs: { goal: null, story: null, acceptance: [null, [{ text: 'The open points of the review (' }, { text: '§3', unresolved: true },
    { text: ') are answered' }]] }, extraGaps: ['unresolved_ref'] },
  'task:old-cleanup': { next: 'First step', progress: { done: 0, total: 2 } },
  'inbox:20261009-0940-filed-board-c2d3': { gaps: ['no_goal', 'task_closed', 'no_content'], closedTask: 'release-notes-2026-09' },
  'inbox:20261009-0900-review-demo-a1b2': { summary: 'The report of the demo check is ready to read.' },
}

const GATE_OWNER = { 'only-you': 'me', 'your-yes': 'bridge_then_me', free: 'bridge' }
// what a person sees an inbox row as (lib/inbox_verbs.py ART_OF_KIND); an unknown kind is an ask
const ART_OF_KIND = { decision: 'ask', question: 'ask', draft: 'ask', finding: 'report', result: 'report', idea: 'idea' }

/** A row's card and describe view, in the shape card.py and describe.py send them: invented from the row and its brief */
function mockCard(r, m = {}, now = Date.now()) {
  m = m ?? {}
  const inbox = !!r.inbox_id
  const task = !!r.task && !inbox
  const kind = inbox ? 'inbox' : task ? (r.work_kind === 'stream' || r.stream ? 'stream' : 'task') : 'info'
  const b = m.brief ?? null
  const what = m.next ?? r.next?.what ?? null
  const next = task ? (what ? { what, who: r.next?.from === 'status' || m.next ? 'me' : null, due: null, from: r.next?.from ?? 'status', since: r.next?.since ?? null } : null)
    : inbox ? { what: r.inbox_kind === 'decision' ? 'decide' : r.gate === 'your-yes' ? 'give your yes' : r.inbox_kind === 'result' ? 'check the result' : 'read',
      who: r.gate === 'free' ? 'bridge' : 'me', due: r.due ?? null, from: 'item', since: null } : null
  const gaps = m.gaps ?? (task ? [!b?.goal && 'no_goal', !next && 'no_next', m.next === 'First step' && 'placeholder_next',
    ...(m.extraGaps ?? [])].filter(Boolean)
    : inbox ? ['no_goal'] : [])
  const closed = m.closedTask ?? null
  const links = task ? [{ kind: 'task', key: r.task, label: r.title, closed: false }]
    : inbox ? [{ kind: 'inbox', key: r.inbox_id, label: r.title }, ...(r.task || closed ? [{ kind: 'task', key: closed ?? r.task, label: closed ?? r.task, closed: !!closed }] : [])]
      : r.link?.kind === 'web' ? [{ kind: 'web', href: r.link.href, label: r.ref ?? r.title }] : []
  const card = {
    kind, subkind: inbox ? r.inbox_kind ?? null : kind === 'info' && r.ref ? 'tracker' : null, title: r.title,
    summary: m.summary ?? null, goal: b?.goal ?? null, story: b?.story ?? null, acceptance: b?.acceptance ?? null,
    brief_refs: m.refs ?? null, next,
    state: { word: inbox ? r.inbox_state ?? 'open' : task ? r.status ?? 'doing' : r.status ?? null, blocked_by: null, since: null },
    owner: inbox ? GATE_OWNER[r.gate] ?? null : null, priority: r.priority ?? null, due: r.due ?? null, area: r.area ?? null,
    updated: null, source: r.origin ?? null, links, progress: m.progress ?? null,
    written: b ? (m.written === 'human' ? 'human' : 'ai') : m.summary ? 'item' : 'title', gaps,
  }
  const describe = b || m.proposal ? { written: m.written ?? null, stale: !!m.stale, stale_why: m.stale ? 'basis' : null,
    running: false, last_error: null, warnings: (m.extraGaps ?? []).includes('unresolved_ref') ? ['Unresolved reference: §3'] : [],
    model_mismatch: false, proposal: m.proposal ? { ...m.proposal, at_ms: now - 40 * MIN } : null, by: b?.by ?? null, at: b?.at ?? null } : null
  return { card, describe }
}

/** What the demo's describe writes for a row without a brief: invented, in the shape the model answers with */
function mockBrief(r) {
  return { goal: 'Done, with its result written down in STATUS.md', acceptance: r.stream ? [] : ['The work is done and written down in STATUS.md', 'Someone else checked the result'],
    by: 'claude-haiku-5-5', edited: false }
}

/** The open rows as the server counts them (collector.py counts.flow_open): the keys of the sections, of the hidden rows
 *  not settled here, of every file, of every open task a page names (task_rows, closable or a stream) and of every item
 *  put off past the window (deferred), each once. Its own loop, so the page's universe (flow.js) is checked against it */
function openCount(sections, hidden, files, taskRows = [], deferred = []) {
  const keys = new Set()
  for (const sec of sections) for (const r of sec.rows) keys.add(r.key)
  for (const r of hidden) if (r.settled_as == null) keys.add(r.key)
  for (const f of files ?? []) keys.add(`task:${f.slug}`)
  for (const r of taskRows) if (r.closable || r.stream) keys.add(r.key)
  for (const r of deferred) keys.add(r.key)
  return keys.size
}

export function buildState(now = Date.now(), opts = {}) {
  const empty = !!opts.empty
  const rows = {
    review: row({
      key: 'inbox:20261009-0900-review-demo-a1b2', bucket: 'do', section: 'now', title: 'Review the demo report',
      origin: O('skill', 'briefing/morning', 'briefing/morning'), work_kind: 'task', inbox_kind: 'decision',
      why: ['due tomorrow', 'only you'], sources: ['inbox'], inbox_id: '20261009-0900-review-demo-a1b2', gate: 'only-you',
      task: 'demo-task', urgency: 'today', area: 'Demo', area_names: ['Demo'], task_type: 'feature', due: isoIn(1, now),
      inbox_state: 'open', inbox_key: 'demo-review', mark: { label: 'Demo', color: 'blue' }, is_new: true,
      actions: [A('done', true), A('advise')], selectable: true,
    }),
    release: row({
      key: 'task:alpha-release', bucket: 'do', section: 'now', title: 'Prepare the alpha release notes',
      origin: O('bridge', null, 'Ad-hoc 2026-10-02'), work_kind: 'task',
      why: ['tab asks for permission'], sources: ['tasks'], task: 'alpha-release', priority: 'P0', urgency: 'now', status: 'doing',
      area: 'Ops', area_names: ['Ops'], task_type: 'ops', mark: { label: 'Ops', color: 'red' },
      tab: { ref: 'surface:7', state: 'needs-you', live: true, waiting: true },
      actions: [A('to_tab', true)], team: { team_id: 'build', started: 1, next_role: { id: 'review', name: 'Review' }, ready: false, waiting_for: 'Implement' },
    }),
    labels: row({
      key: 'inbox:20261009-0910-tidy-labels-c3d4', bucket: 'delegate', section: 'give', title: 'Tidy the issue labels on the demo board',
      origin: O('bot', 'issue-radar', 'homebox/issue-radar', { ref: 'example/repo#3' }), inbox_kind: 'finding',
      why: ['needs your yes'], sources: ['inbox'], inbox_id: '20261009-0910-tidy-labels-c3d4', gate: 'your-yes', has_action: true,
      priority: 'P2', area: 'Demo', area_names: ['Demo'], inbox_state: 'open', inbox_key: 'tidy-labels',
      actions: [A('do', true), A('advise')], selectable: true,
    }),
    docs: row({
      key: 'inbox:20261009-0915-update-docs-e5f6', bucket: 'delegate', section: 'give', title: 'Update the setup docs after the config change',
      origin: O('session', 'claude', 'claude'), inbox_kind: 'decision',
      why: ['needs your yes', `due ${isoIn(-3, now).slice(8)}.${isoIn(-3, now).slice(5, 7)}`, 'changed since 08:40'], due: isoIn(-3, now),
      sources: ['inbox'], inbox_id: '20261009-0915-update-docs-e5f6', gate: 'your-yes',
      has_action: true, area: 'Docs', area_names: ['Docs'], inbox_state: 'open', inbox_key: 'update-docs',
      mark: { label: 'Docs', color: 'green' }, is_changed: true, actions: [A('do', true), A('advise')], selectable: true,
    }),
    sweep: row({
      key: 'inbox:20261009-0920-sweep-logs-0a0b', bucket: 'plan', section: 'give', title: 'Sweep old log files in the scratch folder',
      origin: O('bot', 'nightly-sweep', 'homebox/nightly-sweep'), inbox_kind: 'result',
      why: ['may run alone'], sources: ['inbox'], inbox_id: '20261009-0920-sweep-logs-0a0b', gate: 'free', has_action: true,
      area: 'Ops', area_names: ['Ops'], inbox_state: 'approved', inbox_key: 'sweep-logs',
      actions: [A('approved', false, true)],
    }),
    demo: row({
      key: 'task:demo-task', bucket: 'tasks', section: 'work', title: 'Write the onboarding guide for the demo project',
      origin: O('bridge', null, 'Ad-hoc 2026-10-01'), work_kind: 'task',
      why: ['1 in the inbox'], sources: ['tasks'], task: 'demo-task', priority: 'P1', area: 'Demo', area_names: ['Demo'], status: 'doing',
      next: { what: 'Review the demo report', from: 'inbox', since: isoIn(-2, now), key: 'inbox:20261009-0900-review-demo-a1b2' },
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
      origin: O('skill', 'debrief', 'debrief 2026-09-02 weekly'), work_kind: 'task',
      sources: ['tasks'], task: 'quiet-docs', priority: 'P3', area: 'Docs', area_names: ['Docs'], closable: true,
      actions: [A('do', true), A('advise')],
      review: { verdict: 'stale', reason: 'No log row, commit or note for 34 days and nothing blocks it.', confidence: 'high',
        model: 'claude-haiku-5-5', kept: false, resolved: false, changed: false, days_since_activity: 34, cached: true,
        chips: [{ kind: 'steps', count: 4 }], closed_refs: [], title: 'Tidy the old setup notes', status: 'doing', priority: 'P3' },
    }),
    waits: row({
      key: 'task:vendor-reply', bucket: 'tasks', section: 'work', title: 'Settle the invoice format with the vendor',
      origin: O('bridge', null, null), work_kind: 'task',
      sources: ['tasks'], task: 'vendor-reply', priority: 'P2', area: 'Demo', area_names: ['Demo'], closable: true,
      actions: [A('do', true), A('advise')],
      review: { verdict: 'waiting', reason: 'The vendor has not answered the question from 02.10 yet (example/repo#9 open).',
        confidence: 'low', model: 'claude-sonnet-5-5', kept: false, resolved: false, changed: false, days_since_activity: 8, cached: false,
        chips: [{ kind: 'ref', ref: 'example/repo#9', state: 'open' }, { kind: 'blocked' }], closed_refs: [],
        title: 'Settle the invoice format with the vendor', status: 'doing', priority: 'P2' },
    }),
    flaky: row({
      key: 'ref:example/repo#12', bucket: 'plan', section: 'track', title: 'Fix the flaky test in example/repo#12',
      origin: O('github', 'example/repo', null, { ref: 'example/repo#12' }), work_kind: null,
      why: ['assigned to you', 'quiet for 3 days'], sources: ['github'], ref: 'example/repo#12', priority: 'P2',
      url: 'https://example.org/repo/issues/12', link: { kind: 'web', href: 'https://example.org/repo/issues/12' },
      mark: { label: 'Demo', color: 'blue' }, actions: [A('ask')], on_board: { page: 'trackers', section: 'mine' },
    }),
    index: row({
      key: 'task:docs-refresh', bucket: 'tasks', section: 'work', title: 'Refresh the docs index', sources: ['tasks'],
      origin: O('work', 'team-onboarding', 'inbox 20261001-0900-index-b2c3 (2026-10-01, team-onboarding): Refresh the docs index', { word_key: 'stream' }), work_kind: 'task',
      task: 'docs-refresh', priority: 'P2', area: 'Docs', area_names: ['Docs'], task_type: 'docs', status: 'doing',
      next: { what: 'Check the links of the new index page', from: 'status', since: isoIn(-3, now), key: null },
      tab: { ref: 'surface:8', state: 'working', live: true, waiting: false }, actions: [A('to_tab', true)],
    }),
    // a task in progress that no tab drives: Work through says when it last moved and offers to go on with it
    polish: row({
      key: 'task:release-polish', bucket: 'tasks', section: 'work', title: 'Polish the wording of the release checklist', sources: ['tasks'],
      origin: O('bridge', null, 'Ad-hoc 2026-10-03'), work_kind: 'task', task: 'release-polish', priority: 'P2', area: 'Ops', area_names: ['Ops'],
      status: 'doing', updated: isoIn(-4, now), actions: [A('do', true), A('advise')], selectable: true, closable: true,
    }),
    cleanup: row({
      key: 'task:old-cleanup', bucket: 'tasks', section: 'work', title: 'Clean up the old example fixtures', sources: ['tasks'],
      origin: O('session', 'codex', 'inbox 20260930-1000-fixtures-d4e5 (2026-09-30, codex): Clean up the old example fixtures'), work_kind: 'task',
      task: 'old-cleanup', priority: 'P3', area: 'Ops', area_names: ['Ops'], status: 'review', actions: [A('do', true), A('advise')], selectable: true,
    }),
    vendor: row({
      key: 'inbox:20261008-1400-vendor-reply-9f9f', bucket: 'waiting', section: 'later', title: 'Waiting for the reply on the license question',
      origin: O('person', 'alex', 'alex'), inbox_kind: 'question',
      why: ['asked 2 days ago'], sources: ['inbox'], inbox_id: '20261008-1400-vendor-reply-9f9f', gate: 'only-you', area: 'Demo',
      area_names: ['Demo'], inbox_state: 'open', inbox_key: 'license-reply', actions: [A('follow_up')],
    }),
    idea: row({
      key: 'task:report-dark-mode', bucket: 'resting', section: 'later', title: 'Idea: dark mode for the weekly report',
      origin: O('other', 'team-notes', 'team-notes'), work_kind: 'task',
      why: ['quiet for 12 days'], sources: ['tasks'], task: 'report-dark-mode', priority: 'P3', area: 'Docs', area_names: ['Docs'],
      actions: [A('do', true), A('advise')], selectable: true,
    }),
    // a stream, a report about it from its own tab, a GitLab issue, a row the cockpit filed from a board row
    onboarding: row({
      key: 'task:team-onboarding', bucket: 'tasks', section: 'work', title: 'Onboard the new team members', sources: ['tasks'],
      task: 'team-onboarding', priority: 'P2', area: 'Demo', area_names: ['Demo'], status: 'doing', stream: true, work_kind: 'stream',
      origin: O('bridge', null, 'Ad-hoc 2026-09-15'), actions: [A('do', true), A('advise')], selectable: true,
    }),
    onboardingNote: row({
      key: 'inbox:20261009-0930-onboarding-note-b1c2', bucket: 'plan', section: 'later', title: 'Accounts for two new members are ready',
      sources: ['inbox'], inbox_id: '20261009-0930-onboarding-note-b1c2', gate: 'free', task: 'team-onboarding', area: 'Demo',
      area_names: ['Demo'], inbox_state: 'open', inbox_key: 'tab-team-onboarding-accounts', work_kind: 'stream', inbox_kind: 'result',
      origin: O('session', 'team-onboarding', 'tab:team-onboarding'), actions: [A('done', true)],
    }),
    gitlab: row({
      key: 'item:grp/app#3', bucket: 'plan', section: 'track', title: 'Update the deploy notes', sources: ['gitlab'], ref: 'grp/app#3',
      url: 'https://example.org/grp/app/-/issues/3', link: { kind: 'web', href: 'https://example.org/grp/app/-/issues/3' },
      origin: O('tracker', 'grp/app', null, { word_key: 'GitLab', ref: 'grp/app#3' }), actions: [A('ask')],
    }),
    // Work through, round 4: two tasks on the same thing to merge, a task a live tab works on (recognised from its
    // session), a question due on Sunday evening (Not now, Later, until two days before), an item put off with its day,
    // an idea in the inbox, a pull request in Now (a point), an issue and a pull request watched
    reword: row({
      key: 'task:release-wording', bucket: 'tasks', section: 'work', title: 'Reword the release checklist', sources: ['tasks'],
      origin: O('bridge', null, 'Ad-hoc 2026-10-05'), work_kind: 'task', task: 'release-wording', priority: 'P2', area: 'Ops', area_names: ['Ops'],
      status: 'review', updated: isoIn(-2, now), actions: [A('do', true), A('advise')], selectable: true, closable: true,
    }),
    search: row({
      key: 'task:search-index', bucket: 'tasks', section: 'work', title: 'Rebuild the search index of the docs site', sources: ['tasks'],
      origin: O('bridge', null, 'Ad-hoc 2026-10-06'), work_kind: 'task', task: 'search-index', priority: 'P2', area: 'Docs', area_names: ['Docs'],
      status: 'doing', updated: isoIn(0, now), actions: [A('do', true), A('advise')], selectable: true, closable: true,
    }),
    tunnels: row({
      key: 'inbox:20261009-1010-restart-tunnels-7c1d', bucket: 'plan', section: 'give', title: 'Restart the three test tunnels on Sunday evening',
      origin: O('person', 'sam', 'sam'), inbox_kind: 'question', why: ['due on Sunday'], sources: ['inbox'], inbox_id: '20261009-1010-restart-tunnels-7c1d',
      gate: 'only-you', area: 'Ops', area_names: ['Ops'], urgency: 'later', due: `${isoIn(5, now)}T19:00`, inbox_state: 'open', inbox_key: 'restart-tunnels',
      actions: [A('done', true), A('advise')], selectable: true,
    }),
    deferred: row({
      key: 'inbox:20261008-1600-quote-check-3e4f', bucket: 'plan', section: 'later', title: 'Check the quote for the new laptops',
      origin: O('person', 'kim', 'kim'), inbox_kind: 'decision', sources: ['inbox'], inbox_id: '20261008-1600-quote-check-3e4f', gate: 'only-you',
      area: 'Ops', area_names: ['Ops'], inbox_state: 'deferred', until: isoIn(3, now), inbox_key: 'quote-check', actions: [A('done', true)],
    }),
    badges: row({
      key: 'inbox:20261009-0950-idea-badges-5a6b', bucket: 'plan', section: 'later', title: 'Idea: badges for the docs pages',
      origin: O('person', 'lee', 'lee'), inbox_kind: 'idea', sources: ['inbox'], inbox_id: '20261009-0950-idea-badges-5a6b', gate: 'free',
      area: 'Docs', area_names: ['Docs'], inbox_state: 'open', inbox_key: 'idea-badges', actions: [A('done', true)],
    }),
    exportPr: row({
      key: 'ref:example/tools#21', bucket: 'do', section: 'now', title: 'Review the pull request for the export fix', sources: ['github'],
      origin: O('github', 'example/tools', null, { ref: 'example/tools#21' }), ref: 'example/tools#21', urgency: 'today', priority: 'P1',
      url: 'https://example.org/tools/pull/21', link: { kind: 'web', href: 'https://example.org/tools/pull/21' }, actions: [A('ask')],
    }),
    checklistPr: row({
      key: 'ref:example/tools#4', bucket: 'plan', section: 'track', title: 'Release checklist', sources: ['github'],
      origin: O('github', 'example/tools', null, { ref: 'example/tools#4' }), ref: 'example/tools#4',
      url: 'https://example.org/tools/pull/4', link: { kind: 'web', href: 'https://example.org/tools/pull/4' }, actions: [A('ask')],
      on_board: { page: 'trackers', section: 'mine' },
    }),
    switchDocs: row({
      key: 'ref:example/repo#18', bucket: 'plan', section: 'track', title: 'Document the new config switch', sources: ['github'],
      origin: O('github', 'example/repo', null, { ref: 'example/repo#18' }), ref: 'example/repo#18',
      url: 'https://example.org/repo/issues/18', link: { kind: 'web', href: 'https://example.org/repo/issues/18' }, actions: [A('ask')],
    }),
    filed: row({
      key: 'inbox:20261009-0940-filed-board-c2d3', bucket: 'plan', section: 'later', title: 'Board: Add a config switch for the report',
      sources: ['inbox'], inbox_id: '20261009-0940-filed-board-c2d3', gate: 'free', inbox_state: 'open', inbox_kind: 'decision',
      inbox_key: 'briefing:morning:mine:example/repo#15',
      origin: O('github', 'example/repo', 'bridge-cockpit', { ref: 'example/repo#15', via_cockpit: true }), actions: [A('done', true)],
    }),
  }
  const sec = (id, list, compact) => ({ id, total: list.length, rows: list, compact: compact.map(r => r.key) })
  const sections = empty ? [sec('now', [], []), sec('give', [], []), sec('work', [], []), sec('track', [], []), sec('later', [], [])] : [
    sec('now', [rows.review, rows.release, rows.exportPr], [rows.review, rows.release]),
    sec('give', [rows.labels, rows.docs, rows.sweep, rows.tunnels], [rows.labels, rows.docs, rows.sweep]),
    sec('work', [rows.demo, rows.index, rows.polish, rows.cleanup, rows.onboarding, rows.reword, rows.search], [rows.demo, rows.index]),
    sec('track', [rows.flaky, rows.gitlab, rows.checklistPr, rows.switchDocs], []),
    sec('later', [rows.vendor, rows.idea, rows.onboardingNote, rows.filed, rows.deferred, rows.badges], []),
  ]
  const numbers = {}
  let n = 0
  for (const s of sections) for (const r of s.rows) { n += 1; r.number = n; numbers[r.key] = n }
  // every row carries its card (card.py) and, where describe has something to say, its describe view (describe.py
  // state_for): one brief written by AI, one a person edited with a proposal waiting, one outdated, one with gaps
  for (const r of Object.values(rows)) Object.assign(r, mockCard(r, MOCK_BRIEFS[r.key], now))
  for (const r of Object.values(rows)) r.art = r.inbox_id ? ART_OF_KIND[r.inbox_kind] ?? 'ask' : null
  // what waits for you, as the server counts it (collector.py): the rows of Now that ask
  const forYou = sections[0].rows.filter(r => !r.inbox_id || r.art === 'ask').length
  // the open rows Work through places once each (collector.py counts.flow_open), counted here by their keys
  const hidden = empty ? [] : [row({
    key: 'title:Renew the test certificate', bucket: 'plan', section: 'later', title: 'Renew the test certificate', sources: ['calendar'],
    origin: O('calendar', 'Calendar'), work_kind: null,
    hidden_until: isoIn(5, now), actions: [A('ask')],
  }),
  // a task put off until a day (its file is deferred), and a row settled here: not open any more, so Work through neither
  // shows nor counts it
  row({
    key: 'task:license-audit', bucket: 'tasks', section: 'work', title: 'Audit the licenses of the example dependencies', sources: ['tasks'],
    origin: O('bridge', null, null), work_kind: 'task', task: 'license-audit', status: 'doing', priority: 'P2', area: 'Ops', area_names: ['Ops'],
    hidden_until: isoIn(12, now), updated: isoIn(-6, now), actions: [A('do', true)],
  }),
  row({
    key: 'title:Order new business cards', bucket: 'plan', section: 'later', title: 'Order new business cards', sources: ['calendar'],
    origin: O('calendar', 'Calendar'), work_kind: null, hidden_until: null, settled_as: 'done', actions: [A('ask')],
  })]
  for (const r of hidden) Object.assign(r, mockCard(r, null, now))
  // an idea put off for months on the idea shelf of the work page: past the briefing's window, so no section holds it;
  // Work through carries it (collector.deferred_rows) under Ideas with the day it comes back
  const deferred = empty ? [] : [row({
    key: 'inbox:20260915-1000-idea-workshop-7a8b', bucket: 'plan', section: 'later', title: 'Idea: a workshop on the release process',
    origin: O('person', 'lee', 'lee'), inbox_kind: 'idea', sources: ['inbox'], inbox_id: '20260915-1000-idea-workshop-7a8b', gate: 'free',
    area: 'Ops', area_names: ['Ops'], inbox_state: 'deferred', until: isoIn(90, now), inbox_key: 'idea-workshop', actions: [A('done', true)],
  })]
  for (const r of deferred) Object.assign(r, mockCard(r, null, now), { art: 'idea' })
  // the tasks a page names that no section carries (collector task_rows): open, so Work through holds them too
  const taskRows = empty ? [] : [rows.quiet, rows.waits]

  // every task and stream as a file (collector.files_of, cockpit.files_scope all): the ones a row stands for with
  // that row's bucket, a deferred one, and the backlog the queue never shows; only the keys the page reads
  const fileOfRow = (r, extra = {}) => ({ slug: r.task, kind: r.stream || r.work_kind === 'stream' ? 'stream' : 'task',
    status: r.status ?? 'doing', area_names: r.area_names ?? [], priority: r.priority ?? null, title: r.title,
    updated: isoIn(-3, now), blocked_by: null, bucket: r.bucket ?? null, deferred: false, deferred_until: null, ...extra })
  const backlog = (slug, title, area, priority, days) => ({ slug, kind: 'task', status: 'backlog', area_names: [area],
    priority, title, updated: isoIn(-days, now), blocked_by: null, bucket: null, deferred: false, deferred_until: null })
  const files = empty ? [] : [
    fileOfRow(rows.release, { updated: isoIn(0, now) }), fileOfRow(rows.demo, { updated: isoIn(-1, now) }),
    fileOfRow(rows.quiet, { updated: isoIn(-34, now) }), fileOfRow(rows.waits, { bucket: 'waiting', updated: isoIn(-8, now) }),
    fileOfRow(rows.index), fileOfRow(rows.cleanup, { updated: isoIn(-5, now) }), fileOfRow(rows.onboarding, { updated: isoIn(-2, now) }),
    fileOfRow(rows.idea, { blocked_by: 'a decision on the report layout', updated: isoIn(-12, now) }),
    fileOfRow({ task: 'license-audit', title: 'Audit the licenses of the example dependencies', area: 'Ops', area_names: ['Ops'], priority: 'P2',
      bucket: 'tasks' }, { deferred: true, deferred_until: isoIn(12, now), updated: isoIn(-6, now) }),
    backlog('docs-search', 'Add a search to the docs site', 'Docs', 'P2', 9),
    backlog('metrics-export', 'Export the weekly metrics as CSV', 'Ops', 'P3', 21),
    backlog('customer-faq', 'Collect the questions of the first customers into an FAQ', 'Demo', 'P1', 4),
    backlog('mobile-layout', 'Check the report on a phone', 'Docs', 'P3', 40),
    // round 4: the two tasks to merge, the task a live tab works on, and a stream only the files list
    fileOfRow(rows.polish, { updated: isoIn(-4, now) }), fileOfRow(rows.reword, { updated: isoIn(-2, now) }), fileOfRow(rows.search, { updated: isoIn(0, now) }),
    { slug: 'weekly-digest', kind: 'stream', status: 'doing', area_names: ['Ops'], priority: 'P3', title: 'Send the weekly digest', updated: isoIn(-7, now),
      blocked_by: null, bucket: null, deferred: false, deferred_until: null },
  ]

  const item = (index, over) => ({
    index, title: '', detail: '', when: '', tone: null, link: null, task: null, ask: false, mark: null,
    priority: null, state: null, lines: [], meter: null, starting: false, tab: null, origin: null, work_kind: null, about_kind: null, ...over,
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
      id: 'usage', title: 'Usage', badge: { kind: 'none' }, overview: true,
      // the live cards placed by the profile (`cards:`): costs right after the quota, tokens and noise at the end
      cards: [{ id: 'costs', after: 'quota' }, { id: 'usage', after: null }, { id: 'noise', after: null }], sections: [
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

  // the work page (group work, the By source view of the work tab) with jev:, so Jev orders its rows once a day: the
  // order Prio of Work through reads (round 4). Only with ?work_page=1: a work page also moves the day onto the start
  // page and adds By source and By Jev to the work tab, which the demo otherwise shows without
  if (!empty && opts.workPage === true) {
    const inboxItem = (r, i) => item(i, { title: r.title, detail: r.area ?? '', inbox: r.inbox_id, priority: r.priority, ask: true })
    const taskItem = (r, i) => item(i, { title: r.title, detail: r.area ?? '', task: r.task, priority: r.priority, state: r.status })
    pages.push({ id: 'work', title: 'Work', group: 'work', badge: { kind: 'none' }, jev: { skip_sections: [], private: [] }, sections: [
      { id: 'inbox', kind: 'inbox', title: 'Inbox', status: 'ok', reason: '', alarm: false, empty: 'nothing', count: 4, total: 4, weight: 4, bad: 0,
        as_of: hhmm(now - 2 * MIN), more: 0, items: [rows.review, rows.labels, rows.docs, rows.tunnels].map(inboxItem) },
      { id: 'ideas', kind: 'inbox', title: 'Ideas', status: 'ok', reason: '', alarm: false, empty: 'nothing', count: 2, total: 2, weight: 0, bad: 0,
        as_of: null, more: 0, items: [rows.badges, ...deferred].map(inboxItem) },
      { id: 'tasks', kind: 'tasks', title: 'Tasks', status: 'ok', reason: '', alarm: false, empty: 'nothing', count: 4, total: 4, weight: 4, bad: 0,
        as_of: null, more: 0, items: [rows.polish, rows.cleanup, rows.reword, rows.quiet].map(taskItem) },
    ] })
  }

  // where each page item comes from and what it is, as the collector adds them (collector.page_origin)
  const SECTION_ORIGIN = { command: sec => O('bot', sec.title), tracker: (sec, it) => O('github', it.gh?.repo ?? null),
    tasks: () => O('bridge'), calendar: sec => O('calendar', sec.title) }
  for (const pg of pages) {
    for (const sec of pg.sections) {
      for (const it of sec.items) {
        if (!it.origin && SECTION_ORIGIN[sec.kind]) it.origin = SECTION_ORIGIN[sec.kind](sec, it)
        if (it.work_kind == null && (it.task || it.gh?.task)) it.work_kind = it.gh?.stream ? 'stream' : 'task'
        if (it.about_kind == null && it.gh?.task) it.about_kind = it.gh.stream ? 'stream' : 'task'
      }
    }
  }

  // what the waiting tabs ask, as the tab poll reads it off their screens (asks.py): a dialog with three
  // options, a yes or no question, a summary with a draft typed in the tab; every other tab asks nothing.
  // Only tabs the poll reads carry one: needs-you, and waiting ones that are not filed (model.is_waiting),
  // so the filed report-draft has none
  const asks = {
    'surface:7': { text: 'Edit file RELEASE_NOTES.md\nDo you want to make this edit?', hash: '7a1f0c3e9b2d4a68', yes_no: true, draft: false,
      options: [{ n: 1, label: 'Yes' }, { n: 2, label: 'Yes, allow all edits during this session' }, { n: 3, label: 'No, and tell Claude what to do differently' }] },
    'surface:12': { text: 'I found three sources.\nShould I summarise them in team.md?', hash: 'c4e8b1d27f3a9056', yes_no: true, draft: false, options: [] },
    'surface:13': { text: 'Changelog entry written for the release.', hash: '5d0b7e2a8c1f4936', yes_no: false, draft: true, options: [] },
  }
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
    { ref: 'surface:13', ws_ref: 'workspace:2', name: 'changelog', workspace: 'Ops', state: 'waiting',
      last: 'Changelog entry written for the release.', slug: null, item: null, team: null, role: null, live: true, waiting: true,
      is_control: false, filed_by: null, since_ms: now - 8 * MIN, long: null },
    { ref: 'surface:8', ws_ref: 'workspace:4', name: 'docs-refresh', workspace: 'Docs', state: 'working', last: 'Running the link check (12 of 40 pages)',
      slug: 'docs-refresh', item: null, team: null, role: null, live: true, waiting: false, is_control: false, filed_by: null,
      since_ms: now - 26 * MIN, long: null },
    { ref: 'surface:9', ws_ref: 'workspace:3', name: 'notes', workspace: 'Demo', state: 'working', last: 'Reading the meeting notes',
      slug: null, item: null, team: null, role: null, live: true, waiting: false, is_control: false, filed_by: null, since_ms: now - 6 * MIN, long: null },
    { ref: 'surface:11', ws_ref: 'workspace:4', name: 'zsh', workspace: 'Docs', state: 'shell', last: '', slug: null, item: null,
      team: null, role: null, live: false, waiting: false, is_control: false, filed_by: null, since_ms: now - 140 * MIN, long: null },
    // round 4: a tab typed into by hand whose session works on a task: the cockpit recognises it (sessions.py, task_how seen)
    { ref: 'surface:14', ws_ref: 'workspace:4', name: 'docs search', workspace: 'Docs', state: 'working', last: 'Rebuilding the index (310 of 512 pages)',
      slug: null, item: null, team: null, role: null, live: true, waiting: false, is_control: false, filed_by: null, since_ms: now - 22 * MIN, long: null },
  ].map(t => ({ ...t, ask: asks[t.ref] ?? null, state_source: GLYPH_TABS.has(t.ref) ? 'glyph' : 'hook' }))

  // the return channel (returns.py build): a start at work, one whose tab asks, one that left its answer, one lost;
  // the Work through page draws the first in its lane and the others as cards. Inbox items without a task, but the
  // one that asks, so the files of the tasks keep the results the files suite counts
  const start = (r, mode, mins, stage, extra = {}) => ({ key: r.key, item: r.inbox_id ?? r.task, title: r.title, mode, at_ms: now - mins * MIN,
    stage, in_briefing: true, tab: null, result: null, ...extra })
  const tabRef = ref => { const t = tabs.find(x => x.ref === ref); return t ? { ref, state: t.state, since_ms: t.since_ms, last: t.last } : null }
  const returns = empty ? [] : [
    start(rows.docs, 'go', 6, 'working', { tab: tabRef('surface:9') }),
    start(rows.release, 'go', 40, 'asks', { tab: tabRef('surface:7') }),
    start(rows.labels, 'go', 80, 'result', { tab: tabRef('surface:10'),
      result: { kind: 'filed', text: 'Draft written to the inbox as a result. Anything else?', key: rows.labels.key, at_ms: null } }),
    start(rows.filed, 'go', 130, 'lost'),
    // a start whose tab went still without a question (idle: its agent ended, the shell is left), and one whose
    // task got its result line ("Result: ...", a note on the task since the start)
    { key: 'task:quiet-docs', item: 'quiet-docs', title: 'Tidy the old setup notes', mode: 'go', at_ms: now - 150 * MIN,
      stage: 'idle', in_briefing: true, result: null, tab: tabRef('surface:11') },
    { key: 'task:vendor-reply', item: 'vendor-reply', title: 'Settle the invoice format with the vendor', mode: 'go', at_ms: now - 90 * MIN,
      stage: 'result', in_briefing: true, tab: null,
      result: { kind: 'note', text: 'Result: the vendor takes the current format, nothing to change', key: null, at_ms: null } },
  ]

  const relayOnline = !opts.offline
  return localize({
    ok: true,
    server: { version: '0.1.0', started_ms: now - 50 * MIN },
    model: {
      seq: 3, stale: false, profile: 'morning', title: 'Morning',
      collected_at: hhmm(now - 2 * MIN), collected_ms: now - 2 * MIN, full_ms: now - 2 * MIN, is_full: true,
      headline: empty ? 'Nothing waits for you' : '2 for you today, coming up: Review the demo report',
      since: empty ? null : 'since 08:40: 1 new', skipped: [],
      agenda: empty ? [] : [{ when: hhmm(now + 70 * MIN), title: 'Team call' }, { when: hhmm(now + 250 * MIN), title: 'Review of the demo project' }],
      status: [{ title: 'Systems', count: empty ? 0 : 1, probe: true, state: 'ok' }, { title: 'Inbox', count: empty ? 0 : 6, probe: false, state: 'ok' }],
      extras: { clear: ['Services: all running'], hygiene: empty ? [] : ['2 tasks without a log row for 7 days'], workplace: empty ? null : 'Tabs: 3 suggested' },
      counts: { waiting_tabs: empty ? 0 : 2, long_tabs: empty ? 0 : 1, working_tabs: empty ? 0 : 2, now: forYou, give: sections[1].total, work: sections[2].total, track: sections[3].total, later: sections[4].total, hidden: hidden.length,
        flow_open: openCount(sections, hidden, files, taskRows, deferred) },
      sections, numbers, hidden, deferred,
      approvable: empty ? [] : [rows.labels.key, rows.docs.key],
      task_rows: taskRows,
      // the tasks closed this week (daybook.week_done): a closed task and an ended stream
      week: empty ? { count: 0, since: null, items: [] } : { count: 2, since: isoIn(-4, now), items: [
        { slug: 'release-checklist', title: 'Write the release checklist', closed: isoIn(-1, now), work_kind: 'done_task' },
        { slug: 'pilot-customer', title: 'Pilot with the first customer', closed: isoIn(-2, now), work_kind: 'done_stream' }] },
      review: empty ? { running: null, error: null, last: null, keys: [] } : {
        running: null, error: null, keys: [rows.demo.key, rows.quiet.key, rows.waits.key],
        last: { reviewed_at: new Date(now - 20 * MIN).toISOString().slice(0, 19), reviewed: 3, to_close: 1, cost_ct: 2.22,
          cost_known: true, models: ['haiku-5-5', 'sonnet-5-5'], duration_sec: 24.5, escalate_ct: 2.1, mismatch: false,
          tiers: [{ model: 'haiku-5-5', answered: 2, cost_ct: 0.12 }, { model: 'sonnet-5-5', answered: 1, cost_ct: 2.1 }], cached: 0 },
      },
      pages,
      alarms: empty ? [] : [{ page_id: 'systems', page_title: 'Systems', section_title: 'Checks', count: 1 }],
      files,
      teams: [
        { id: 'build', label: 'Build', for_types: ['feature'], roles: [{ id: 'implement', name: 'Implement', mode: 'go' }, { id: 'review', name: 'Review', mode: 'report' }] },
        { id: 'research', label: 'Research', for_types: ['research'], roles: [{ id: 'evidence', name: 'Evidence', mode: 'report' }, { id: 'counter', name: 'Counter', mode: 'report' }, { id: 'summary', name: 'Summary', mode: 'report' }] },
      ],
      // what the server sends: the asks of Now, the same number as counts.now
      briefing_badge: forYou,
      returns,
    },
    // the terminal's workspace list (the chat as cmux); two workspaces share a title and are told apart by ref
    tabs: { at_ms: now - 8000, error: null, control: { name: 'Control', ref: 'surface:3' }, tabs, workspaces: empty ? [] : [
      { ref: 'workspace:1', title: 'Control', pinned: true, cwd: '/demo/bridge' },
      { ref: 'workspace:2', title: 'Ops', cwd: '/demo/bridge', description: 'Releases and checks' },
      { ref: 'workspace:3', title: 'Demo', cwd: '/demo/bridge' },
      { ref: 'workspace:4', title: 'Docs', cwd: '/demo/bridge' },
      { ref: 'workspace:5', title: 'Demo', cwd: '/demo/other-repo', description: 'A second workspace with the same title' }]
      .map(w => ({ ...w, color: w.color ?? null, color_name: paletteName(w.color) })) },
    driver: { caps: DRIVER_CAPS },
    quick: { available: true, default: 'haiku', models: ['haiku', 'sonnet', 'opus'], keep_hours: 24, convs: empty ? [] : [aboutConv(now), ...handedConvs(now)] },
    jev: createMockJev ? { enabled: true, ready: true, reason: null } : { enabled: false, ready: false, reason: 'off' },
    agents: empty ? { peers: [], convs: [] } : agentsState(now),
    triage: empty ? { running: null, error: null, last: null, items: {} } : triageState(now),
    launch: launchState(LAUNCH_CONFIG, !!createMockJev),
    ticker: tickerState(TICKER_CONFIG, now),
    guide: guideState(tabs, now),
    // the first-run tour: ended in the demo unless ?tour=1 asks for a first visit
    tour: { enabled: true, done: opts.tour ? null : { how: 'finished', v: 1, at: isoIn(-3, now) } },
    // the work tab as the config sets it (cockpit.work_view, cockpit.focus_to_files): ?work=files and ?focus_to_files=1
    // and which tasks are files (cockpit.files_scope): the queue alone as the default config, ?files_scope=all for every one
    work: { view: ['due', 'source', 'jev', 'files', 'flow'].includes(opts.work) ? opts.work : 'due', focus_to_files: opts.focusToFiles === true,
      files_scope: opts.filesScope === 'all' ? 'all' : 'active',
      // the Work through page (cockpit.flow): on in the demo, ?flow=0 shows the cockpit without it
      // the views the work tab offers (cockpit.work_views): all of them, ?views=files,flow narrows
      views: Array.isArray(opts.views) && opts.views.length ? opts.views : ['due', 'source', 'jev', 'files', 'flow'],
      // the files tab's question to its records (cockpit.files_search): on in the demo, the Health area kept private
      files_search: { enabled: true, block: ['Health'], left: 20 },
      flow: { enabled: opts.flow !== false, drop_reasons: ['resolves_itself', 'not_needed', 'someone_else', 'not_worth_it'], return_after_s: 20,
        // round 4: a point comes up two days before its due; a session's task is recognised from what it did
        ahead_days: 2, infer_sessions: true,
        themes: { enabled: opts.flow !== false, max_themes: 8, budget_per_day: 6, model: null },
        // round 3: the summary of a point's Activity, the instruction line, a document attached (all off by default)
        summary: { enabled: opts.flow !== false, budget_per_day: 10, model: null },
        instruct: { enabled: opts.flow !== false, budget_per_day: 30, model: null },
        attach: { enabled: opts.flow !== false, max_mb: 10 } } },
    // what the day's budgets of Work through still hold (server.py state_payload flow_ai)
    flow_ai: { summary_left: 10, instruct_left: 30, instruct_running: false },
    // the themes of Work through (themes.py state), invented: three themes across the areas, a point moved by hand
    themes: empty || opts.flow === false ? { enabled: false } : themesState(now),
    loading: { pass: null, fresh: false, started_ms: 0, eta_ms: 0, queued: null, last_error: null },
    notes: [
      { at: hhmm(now - 9 * MIN), at_ms: now - 9 * MIN, text: 'Yes given, runs on the next pass: Sweep old log files', tone: 'ok' },
    ],
    relay: {
      enabled: true, online: relayOnline, reason: relayOnline ? null : 'no_heartbeat',
      session: relayOnline ? { id_short: 'a1b2c3d4', surface_ok: true, busy: false, at_ms: now - 2000 } : null,
      records: empty ? [] : [
        { id: '20261009T071000-1a2b3c4d', kind: 'overview', created_ms: now - 30 * MIN, status: 'answered',
          preview: 'My briefing state from the dashboard (09:10): 2 for you today, coming up: Review the demo report',
          answer: '1. Review the demo report first, it is due tomorrow and only you can do it.\n2. Give your yes to the two label and docs items, they run alone.\n3. The flaky test can wait until after the team call.',
          answered_ms: now - 29 * MIN },
        ...handedRecords(now),
      ],
    },
    cmux: { ok: true, error: null },
    sessions: { at_ms: now - 8000, sessions: empty ? [] : [
      { id: '7a16c7b2', pid: 101, name: 'demo-bridge-fc', project: 'demo-bridge', cwd: '/demo/bridge', here: true, status: 'busy',
        since_ms: now - 4 * MIN, started_ms: now - 95 * MIN, kind: 'interactive', version: '2.1.0', remote: true,
        tab: { ref: 'surface:3', ws_ref: 'workspace:1', name: 'Control', workspace: 'Control', state: 'working', is_control: true },
        agents: { running_count: 2, done_recent: 3, running: [
          { id: 'a1efe80', type: 'code-reviewer', description: 'Review the dashboard change', since_ms: now - 2 * MIN, background: true },
          { id: 'b77c012', type: 'Explore', description: 'Find where sessions are stored', since_ms: now - 40000, background: false }] },
        workflows: [{ name: 'demo-build', status: 'running', agents: 4, since_ms: now - 12 * MIN },
          { name: 'demo-nightly', status: 'paused', agents: 2, since_ms: now - 50 * MIN }] },
      { id: 'd8db96ad', pid: 102, name: 'demo-bridge-4b', project: 'demo-bridge', cwd: '/demo/bridge', here: true, status: 'idle',
        since_ms: now - 31 * MIN, started_ms: now - 5 * 60 * MIN, kind: 'interactive', version: '2.1.0', remote: false,
        tab: { ref: 'surface:7', ws_ref: 'workspace:2', name: 'alpha-release', workspace: 'Ops', state: 'needs-you', is_control: false },
        agents: { running_count: 0, done_recent: 0, running: [] }, workflows: [] },
      // a second session on the same tab (a resumed one): the tab counts both
      { id: '5e0b3d91', pid: 104, name: 'demo-bridge-7c', project: 'demo-bridge', cwd: '/demo/bridge', here: true, status: 'busy',
        since_ms: now - 2 * MIN, started_ms: now - 15 * MIN, kind: 'interactive', version: '2.1.0', remote: false,
        tab: { ref: 'surface:7', ws_ref: 'workspace:2', name: 'alpha-release', workspace: 'Ops', state: 'needs-you', is_control: false },
        agents: { running_count: 1, done_recent: 0, running: [
          { id: 'd51e2b0', type: 'Explore', description: 'Check the release notes', since_ms: now - 50000, background: false }] },
        workflows: [] },
      { id: '9f2c6a17', pid: 105, name: 'demo-bridge-notes', project: 'demo-bridge', cwd: '/demo/bridge', here: true, status: 'busy',
        since_ms: now - 6 * MIN, started_ms: now - 30 * MIN, kind: 'interactive', version: '2.1.0', remote: false,
        tab: { ref: 'surface:9', ws_ref: 'workspace:3', name: 'notes', workspace: 'Demo', state: 'working', is_control: false },
        agents: { running_count: 2, done_recent: 1, running: [
          { id: 'e8a4c11', type: 'general-purpose', description: 'Summarise the meeting notes', since_ms: now - 3 * MIN, background: true },
          { id: 'f19b7d3', type: 'Explore', description: 'Find the action items', since_ms: now - 70000, background: false }] },
        workflows: [{ name: 'demo-check', status: 'running', agents: null, since_ms: now - 5 * MIN }] },
      // round 4: the task a session works on, by its own task tab (waiting at its prompt) or recognised from what it did
      { id: '2f7a0c55', sid: '2f7a0c55-0000-4000-8000-000000000003', pid: 106, name: 'demo-bridge-research', project: 'demo-bridge', cwd: '/demo/bridge',
        here: true, status: 'idle', since_ms: now - 11 * MIN, started_ms: now - 40 * MIN, kind: 'interactive', version: '2.1.0', remote: false,
        tab: { ref: 'surface:12', ws_ref: 'workspace:3', name: 'demo-task research', workspace: 'Demo', state: 'waiting', is_control: false },
        task: 'demo-task', task_how: 'tab', task_since_ms: now - 40 * MIN, agents: { running_count: 0, done_recent: 2, running: [] }, workflows: [] },
      { id: '6b1d9e20', sid: '6b1d9e20-0000-4000-8000-000000000004', pid: 107, name: 'demo-bridge-search', project: 'demo-bridge', cwd: '/demo/bridge',
        here: true, status: 'busy', since_ms: now - MIN, started_ms: now - 35 * MIN, kind: 'interactive', version: '2.1.0', remote: false,
        tab: { ref: 'surface:14', ws_ref: 'workspace:4', name: 'docs search', workspace: 'Docs', state: 'working', is_control: false },
        task: 'search-index', task_how: 'seen', task_since_ms: now - 18 * MIN, agents: { running_count: 0, done_recent: 0, running: [] }, workflows: [] },
      { id: '3c9a1e44', pid: 103, name: 'other-repo-2a', project: 'other-repo', cwd: '/demo/other-repo', here: false, status: 'busy',
        since_ms: now - 9 * MIN, started_ms: now - 20 * MIN, kind: 'interactive', version: '2.1.0', remote: false,
        tab: null, agents: { running_count: 1, done_recent: 0, running: [
          { id: 'c03f9aa', type: 'general-purpose', description: 'Run the migration tests', since_ms: now - 6 * MIN, background: true }] },
        workflows: [] },
    ],
    // the workflow runs the server bound to an open task (sessions.py run_task): one whose result waits, one checked
    runs: empty ? [] : [
      { id: 'wf_3fa1c2d4-a01', task: 'alpha-release', name: 'release-check', status: 'completed', seen: false, agents: 5,
        since_ms: now - 50 * MIN, ended_ms: now - 35 * MIN, at_ms: now - 35 * MIN, sid: '7a16c7b2-0000-4000-8000-000000000001',
        how: ['named'], summary: 'Check the release candidate against the checklist',
        answer: 'Two items open: the changelog misses the fix for the export, and the upgrade note names the old flag.' },
      { id: 'wf_9b0e7f12-c33', task: 'docs-refresh', name: 'docs-outline', status: 'completed', seen: true, agents: 3,
        since_ms: now - 26 * 60 * MIN, ended_ms: now - 25 * 60 * MIN, at_ms: now - 25 * 60 * MIN,
        sid: 'd8db96ad-0000-4000-8000-000000000002', how: ['session'], summary: 'Outline the new getting-started page', answer: null },
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
      task: r?.task ?? null, due: r?.due ?? null, key: r?.inbox_key ?? 'example', from: r?.origin?.raw ?? 'demo-check', created: '2026-10-09T09:00:00',
      action_display: hasAction ? 'python3 scripts/example-tool.py --apply demo' : null, has_closes_when: hasAction,
    },
    events: [
      { verb: 'add', by: r?.origin?.raw ?? 'demo-check', at: '2026-10-09T09:00:00' },
      { verb: 'note', by: 'web', at: '2026-10-09T09:05:00', note: 'looked at it, fine' },
    ],
    // who filed it, as the server names it (details.py inbox_detail, origin.py)
    origin: r?.origin ?? O('other', 'demo-check', 'demo-check'),
    // its card and describe view (card.py, describe.py), as its row carries them
    card: r?.card ?? null, describe: r?.describe ?? null,
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

// a closed task the search finds in work/done/ (the queue never holds one): invented, like everything here
const DONE_FILE = { slug: 'release-notes-2026-09', title: 'Release notes for September', month: '2026-09',
  lines: ['Release notes for September went out on the 30th.', 'The vendor export timed out twice, fixed with a retry.'] }

// the records of the files tab's start (/api/records, work_find.py records): every task and stream of the demo, the
// closed one above and a closed one in an area the demo's block list keeps private (cockpit.files_search.block)
function mockRecords(state) {
  const out = new Map()
  const put = (slug, kind, title, status, area, updated, priority = null) => {
    if (slug && !out.has(slug)) {
      out.set(slug, { slug, kind, path: `work/${kind === 'stream' ? 'streams' : 'tasks'}/${slug}`, title, status, priority, area, updated,
        work_kind: kind })
    }
  }
  for (const f of state?.model?.files ?? []) put(f.slug, f.kind, f.title, f.status, f.area_names?.[0] ?? null, f.updated, f.priority)
  for (const r of (state?.model?.sections ?? []).flatMap(x => x.rows ?? []).filter(x => x.task && !x.inbox_id)) {
    put(r.task, r.stream || r.work_kind === 'stream' ? 'stream' : 'task', r.title, r.status ?? 'doing', r.area ?? null, null, r.priority ?? null)
  }
  const done = (slug, title, area, month, day) => ({ slug, kind: 'done', path: `work/done/${month}/${slug}`, title, status: 'done',
    priority: null, area, updated: `${month}-${day}`, work_kind: 'done_task' })
  const records = [...out.values(), done(DONE_FILE.slug, DONE_FILE.title, 'Docs', DONE_FILE.month, '30'),
    done('health-check-booking', 'Book the yearly check-up', 'Health', '2026-09', '12')]
  records.sort((a, b) => String(b.updated ?? '').localeCompare(String(a.updated ?? '')))
  return { ok: true, total: records.length, truncated: false, records }
}

// the search (work-find.py through /api/find): every word in the slug, title or a line of an invented file, the
// files whose slug or title holds every word first, then the rest; the same shape the server answers with
function findFiles(q, state) {
  const words = [...new Set(String(q ?? '').toLowerCase().split(/\s+/).filter(Boolean))].slice(0, 8)
  const rows = (state?.model?.sections ?? []).flatMap(x => x.rows ?? []).filter(r => r.task && !r.inbox_id)
  const seen = new Set()
  const files = rows.filter(r => !seen.has(r.task) && seen.add(r.task)).map(r => ({ slug: r.task, kind: r.stream ? 'stream' : 'task', title: r.title,
    path: `work/${r.stream ? 'streams' : 'tasks'}/${r.task}`, lines: [`headline: ${r.title}`, ...(r.next?.what ? [`next: ${r.next.what}`] : [])] }))
  files.push({ ...DONE_FILE, kind: 'done', path: `work/done/${DONE_FILE.month}/${DONE_FILE.slug}` })
  const groups = []
  for (const f of files) {
    const name = `${f.slug} ${f.title}`.toLowerCase()
    const hits = f.lines.map((text, i) => ({ path: `${f.path}/STATUS.md`, line: i + 2, text }))
      .filter(h => words.some(w => h.text.toLowerCase().includes(w)))
    const all = `${name} ${hits.map(h => h.text).join(' ')}`.toLowerCase()
    if (!words.length || !words.every(w => all.includes(w))) continue
    groups.push({ slug: f.slug, kind: f.kind, work_kind: f.kind === 'done' ? 'done_task' : f.kind, path: f.path, title: f.title, rank: words.every(w => name.includes(w)) ? 0 : 1,
      count: hits.length, hits })
  }
  groups.sort((a, b) => a.rank - b.rank || (a.kind === 'done') - (b.kind === 'done') || b.count - a.count)
  return { ok: true, query: String(q ?? '').trim(), words, engine: 'python', total: groups.length, truncated: false, groups }
}

// the checklist of each demo task (its Steps), and the paths its STATUS.md names; any other task a short one of its own
const DEMO_STEPS = {
  'demo-task': [[true, 'Outline the chapters'], [true, 'Collect examples from the setup'], [false, 'Write the first two chapters'],
    [false, 'Take the screenshots'], [false, 'Let a new colleague try the guide']],
  'alpha-release': [[true, 'List the merged changes since the last tag'], [true, 'Link each change to its pull request'],
    [true, 'Answer the open points of the review'], [false, 'Push the tag']],
  'docs-refresh': [[true, 'List every page of the docs folder'], [false, 'Group the pages by topic'], [false, 'Check every link of the index']],
}
const DEMO_STEPS_ANY = [[true, 'Read what is still open'], [false, 'Do the work'], [false, 'Write the result into STATUS.md']]
const DEMO_RELATED = { 'demo-task': ['docs/demo-guide.md', 'work/tasks/docs-refresh/STATUS.md'],
  'alpha-release': ['CHANGELOG.md', 'work/tasks/release-polish/STATUS.md'], 'docs-refresh': ['docs/index.md'] }

/** A task's file as details.py task_detail sends it; `words` the demo's own language, for the lines composed here */
function taskDetail(slug, state, words = null) {
  // the front of the task the row stands for (review C12): a P0 row opens as that P0, not as one fixed page
  const rows = [...(state?.model?.sections ?? []).flatMap(s => s.rows ?? []),
    ...(state?.model?.pages ?? []).flatMap(p => (p.sections ?? []).flatMap(s => s.items ?? []))]
  // the task's own row, not an inbox item that names the task
  const listed = (state?.model?.files ?? []).find(f => f.slug === slug)
  const row = rows.find(r => r?.task === slug && !r.inbox_id && !r.inbox) ?? rows.find(r => r?.task === slug)
    ?? (listed ? { title: listed.title, priority: listed.priority, state: listed.status, stream: listed.kind === 'stream' } : {})
  const done = slug === DONE_FILE.slug
  // what the server sends (details.py task_detail): the four kinds by the folder, the origin as origin.py names it,
  // and the open inbox items that name the task, each with who filed it
  const workKind = done ? 'done_task' : row.work_kind ?? (row.stream ? 'stream' : 'task')
  const folder = done ? `work/done/${DONE_FILE.month}` : workKind === 'stream' ? 'work/streams' : 'work/tasks'
  const raw = row.origin?.raw ?? 'team call on 2026-09-30'
  const inbox = (state?.model?.sections ?? []).flatMap(x => x.rows ?? []).filter(r => r.inbox_id && r.task === slug)
    .map(r => ({ id: r.inbox_id, summary: r.title, state: r.inbox_state ?? 'open', urgency: r.urgency ?? null, gate: r.gate ?? null,
      from: r.origin?.raw ?? null, kind: r.inbox_kind ?? null, origin: r.origin ?? null }))
  return {
    ok: true, slug, kind: done ? 'done' : workKind === 'stream' ? 'stream' : 'task', work_kind: workKind,
    origin: row.origin ?? O('other', raw, raw), inbox, path: `${folder}/${slug}/STATUS.md`,
    front: { type: row.task_type ?? 'feature', status: done ? 'done' : row.state ?? 'doing', priority: row.priority ?? 'P1', created: '2026-10-01',
      last_updated: '2026-10-08', headline: done ? DONE_FILE.title : row.title ?? 'Onboarding guide for the demo project', origin: raw,
      blocked_by: null },
    sections: [
      { heading: 'Goal', text: 'A new team member sets up the demo project in under an hour, with every step written down.', truncated: false },
      { heading: 'Next', text: '- Draft the first two chapters\n- Collect screenshots from the example setup', truncated: false },
      { heading: 'Log', text: '2026-10-08: outline written, examples collected\n2026-10-03: task opened', truncated: false },
      // the checklist the Steps tab of Work through reads
      { heading: 'Steps', text: (DEMO_STEPS[slug] ?? DEMO_STEPS_ANY).map(([done, step]) => `- [${done ? 'x' : ' '}] ${localize(step, words)}`).join('\n'), truncated: false },
    ],
    // the paths STATUS.md names under related (details.py)
    related: DEMO_RELATED[slug] ?? [],
    log: [
      { at: '2026-10-08 16:20', glyph: 'n', context: slug, text: 'Outline written, examples collected' },
      { at: '2026-10-03 11:05', glyph: 'n', context: slug, text: 'Task opened after the team call' },
    ],
    // the files of its folder besides STATUS.md (details.py folder_files)
    files: MOCK_FILES.map(f => ({ path: f.path, size: f.text.length })),
    // its card (card.py: the H1 as title, as the row says it) and describe view (describe.py)
    card: row.card ?? null, describe: row.describe ?? null,
  }
}

// the files of a task folder, read in place in the files view (/api/task?file=)
const MOCK_FILES = [
  { path: 'notes.md', text: '# Notes\n\nThe outline is agreed. **Open:** who reviews the second chapter.\n\n- Draft chapter one\n- Collect screenshots' },
  { path: 'research/options.yaml', text: 'options:\n  - name: one page\n    effort: small\n  - name: a guide in chapters\n    effort: medium\n' },
]

function taskFile(slug, file) {
  const f = MOCK_FILES.find(x => x.path === file)
  return f ? { ok: true, slug, file, text: f.text, cut: false } : null
}

// the tokens of 7, 30 or 90 days (usage.py view(days=n)): invented counts per day and source, today a little loud;
// two Bridges on this machine and one on another, and a third machine that does not answer
function usageView(now, n = 7) {
  const week = [[38, 9, 4], [52, 14, 0], [0, 0, 0], [61, 22, 6], [44, 11, 3], [57, 18, 5], [96, 31, 7]]
  const per = Array.from({ length: n }, (_, i) => {
    const [a, b, c] = week[(i + 7 - (n % 7)) % 7]
    const f = i === n - 1 ? 1 : 0.7 + 0.3 * Math.abs(Math.sin(i * 1.7))
    return [Math.round(a * f), Math.round(b * f), Math.round(c * f)]
  })
  const models = ['claude-opus-5-5', 'claude-sonnet-5-5', 'claude-haiku-5-5']
  const projects = ['demo-project', 'docs-site', 'example-tools', 'example-api']   // four: the chart shows its rest
  const bridges = [['demo-bridge', 'my-laptop', 0.6], ['team-bridge', 'my-server', 0.3], [null, 'my-laptop', 0.1]]
  const total = { input: 0, output: 0, cache_read: 0, cache_write: 0 }
  const days = per.map(([session, subagent, worker], i) => {
    const day = isoIn(i - n + 1, now)
    const sources = Object.fromEntries([['session', session], ['subagent', subagent], ['worker', worker]].map(([s, k]) => {
      const counts = { input: k * 300, output: k * 1000, cache_read: k * 42000, cache_write: k * 2600 }
      for (const f of Object.keys(total)) total[f] += counts[f]
      return [s, counts]
    }))
    const output = (session + subagent + worker) * 1000
    const shares = { 3: [0.6, 0.3, 0.1], 4: [0.5, 0.25, 0.15, 0.1] }
    const split = (names, key) => output ? names.map((x, j) => ({ [key]: x, output: Math.round(output * shares[names.length][j]) })) : []
    return { day, sources, output, models: split(models, 'model'), projects: split(projects, 'project'),
      bridges: output ? bridges.map(([bridge, host, f]) => ({ bridge, host, output: Math.round(output * f) })) : [] }
  })
  const sum = names => names.map((x, j) => ({ x, output: days.reduce((a, d) => a + (d.models[j]?.output ?? 0), 0) }))
  const all = days.reduce((a, d) => a + d.output, 0)
  return { range: n, at: new Date(now - 4 * MIN).toISOString(), host: 'my-laptop',
    days, total, models: sum(models).map(m => ({ model: m.x, output: m.output })),
    projects: sum(projects).map(x => ({ project: x.x, output: days.reduce((a, d) => a + (d.projects[projects.indexOf(x.x)]?.output ?? 0), 0) })),
    outliers: [{ source: 'subagent', today: 31000, usual: 14000, factor: 2.2 }],
    bridges: bridges.map(([bridge, host, f], j) => ({ bridge, host, output: Math.round(all * f), all: Math.round(all * f * 48),
      models: models.slice(0, 3 - j).map((m, k) => ({ model: m, output: Math.round(all * f * [0.6, 0.3, 0.1][k]) })),
      days: days.map(d => Math.round(d.output * f)) })),
    hosts: [{ host: 'my-laptop', ok: true, error: null, at: new Date(now - 4 * MIN).toISOString(), local: true },
      { host: 'my-server', ok: true, error: null, at: new Date(now - 9 * MIN).toISOString(), local: false },
      { host: 'my-workstation', ok: false, error: 'ssh: connect timed out', at: null, local: false }] }
}

// the cloud costs (bridge-resources.py costs -> costs-view.json): invented accounts, 35 days up to today; one over
// its forecast, one that needs a key, one fixed contract. Nothing here is a real tenant or account
function costsView(now) {
  const N = 35
  const today = isoIn(0, now)
  const day = i => isoIn(i - N + 1, now)
  const month = today.slice(0, 7)
  const left = (() => { const d = new Date(now); return new Date(d.getFullYear(), d.getMonth() + 1, 0).getDate() - d.getDate() })()
  const r2 = x => Math.round(x * 100) / 100
  const usage = (id, name, provider, base, groups, budget) => {
    const days = Array.from({ length: N }, (_, i) => {
      const weekend = [0, 6].includes(new Date(`${day(i)}T12:00:00`).getDay())
      const amount = r2(base * (weekend ? 0.6 : 1) * (0.8 + 0.4 * Math.abs(Math.sin(i * 1.3))))
      return { day: day(i), amount, provisional: i >= N - 2,
        groups: Object.fromEntries(groups.map(([g, f]) => [g, r2(amount * f)])) }
    })
    const mtd = r2(days.filter(d => d.day.startsWith(month)).reduce((a, d) => a + d.amount, 0))
    const settled = days.filter(d => !d.provisional).slice(-7)
    const mean = settled.reduce((a, d) => a + d.amount, 0) / settled.length
    return { id, display_name: name, provider, kind: 'usage', ok: true, error: null, currency: 'EUR',
      original_currency: provider === 'azure' ? 'EUR' : 'USD', group_by: 'service', budget_month: budget, days,
      month_to_date: mtd, forecast_month: r2(mtd + mean * left), last_complete_day: day(N - 3) }
  }
  const fixed = 12
  const contract = { id: 'hosting-example', display_name: 'Example web hosting', provider: 'contract', kind: 'fixed', ok: true, error: null,
    currency: 'EUR', original_currency: 'EUR', group_by: null, budget_month: null,
    days: Array.from({ length: N }, (_, i) => ({ day: day(i), amount: r2(fixed * 12 / 365), provisional: false, groups: { 'Web hosting': r2(fixed * 12 / 365) } })),
    month_to_date: r2(fixed * 12 / 365 * Number(today.slice(8, 10))), forecast_month: fixed, last_complete_day: today }
  return { schema: 1, kind: 'cloud-costs', host: 'my-server', at: new Date(now - 3 * 3600000).toISOString(), currency: 'EUR', days: N, today,
    fx: { date: isoIn(-1, now), source: 'ecb', rates: { USD: 1.08 } },
    source: 'ssh:my-server:~/.bridge/resources/costs.json', read_at: new Date(now - 2 * MIN).toISOString(), stale: false,
    accounts: [
      usage('azure-example', 'Example Azure', 'azure', 1.2, [['Functions', 0.55], ['Storage', 0.3], ['Key Vault', 0.15]], 50),
      usage('anthropic-example', 'Example Anthropic', 'anthropic', 2.6, [['Claude API, input', 0.4], ['Claude API, output', 0.6]], 60),
      usage('aws-example', 'Example AWS', 'aws', 0.35, [['Amazon S3', 0.7], ['AWS Lambda', 0.3]], null),
      { id: 'openai-example', display_name: 'Example OpenAI', provider: 'openai', kind: 'usage', ok: false, error_kind: 'auth',
        error: 'no admin key in the keychain', currency: 'EUR', days: [], month_to_date: null, forecast_month: null, budget_month: 20,
        login: { argv: ['bash', '/srv/bridge/skills/secrets/secrets.sh', 'store', 'keychain://openai-admin/example', '--root', '/srv/bridge', '--from', 'prompt'],
          hint: 'Create an admin key at platform.openai.com > Settings > Organization > Admin keys, then store it with this command.' },
        login_command: "ssh -t my-server 'bash /srv/bridge/skills/secrets/secrets.sh store keychain://openai-admin/example --root /srv/bridge --from prompt'" },
      contract,
    ] }
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
/** Chats handed on, one per status the chat's status line shows (logic.js handoffStatus): a tab start with each
 *  launch outcome, and the control session waiting, arrived and offline (their relay records below) */
export const HANDED_EXAMPLES = [
  ['Tidy the demo board labels', { to: 'tab', status: 'starting' }],
  ['Add a changelog entry for the demo release', { to: 'tab', status: 'started' }],
  ['Rename the old demo branch', { to: 'tab', status: 'running' }],
  ['Update the example fixtures', { to: 'tab', status: 'busy' }],
  ['Fix the broken link check', { to: 'tab', status: 'failed' }],
  ['Move the notes into the docs folder', { to: 'tab', status: 'partly' }],
  ['Set up the demo test run', { to: 'tab', status: 'manual' }],
  ['Write the release summary', { to: 'tab', status: 'nothing' }],
  ['Plan the next demo sprint', { to: 'control', status: 'queued', relay_id: '20261009T113000-0a0b0c01' }],
  ['Check the open demo reviews', { to: 'control', status: 'queued', relay_id: '20261009T113100-0a0b0c02' }],
  ['Sort the demo inbox', { to: 'control', status: 'offline', relay_id: '20261009T113200-0a0b0c03' }],
]

export function handedConvs(now) {
  return HANDED_EXAMPLES.map(([q, handed], i) => {
    const at = now - (60 - i * 4) * MIN
    const inbox = handed.to === 'tab' && handed.status !== 'starting' ? `20261009-11${String(i).padStart(2, '0')}-demo-chat-a1b${i}` : null
    return { id: `qd${String(i + 1).padStart(9, '0')}`, kind: 'free', started_ms: at, session: null, total_usd: 0.002, running: false,
      last_ms: at + MIN, turns: [{ q, a: 'Example answer from the mock: the steps are clear, an agent can take it from here.', model_asked: 'haiku',
        model: 'haiku-5-5', cost_usd: 0.002, at_ms: at, error: null }],
      // a chat handed to a tab is about the item it became: it leaves with that item (quick.py sweep_settled)
      about: inbox ? { kind: 'handoff', inbox } : null,
      handed: { at_ms: at + MIN, ...handed, ...(inbox ? { inbox_id: inbox } : {}) } }
  })
}

/** A chat asked on a briefing row: it carries the row and its inbox item, and leaves once that item is closed */
function aboutConv(now) {
  const at = now - 18 * MIN
  return { id: 'qa000000001', kind: 'row', started_ms: at, session: null, total_usd: 0.001, running: false, last_ms: at + MIN,
    about: { kind: 'row', key: 'inbox:20261009-0910-tidy-labels-c3d4', inbox: '20261009-0910-tidy-labels-c3d4' },
    turns: [{ q: 'What is behind: Tidy the issue labels on the demo board', a: 'Twelve labels overlap; the item asks to merge them into five.',
      model_asked: 'haiku', model: 'haiku-5-5', cost_usd: 0.001, at_ms: at, error: null }] }
}

/** The relay records of the chats handed to the control session: still queued, arrived, and offline */
function handedRecords(now) {
  return [['20261009T113000-0a0b0c01', 'queued'], ['20261009T113100-0a0b0c02', 'submitted'], ['20261009T113200-0a0b0c03', 'offline']]
    .map(([id, status], i) => ({ id, kind: 'free', created_ms: now - (24 - i * 4) * MIN, status, preview: 'From a quick question in the dashboard',
      answer: null, answered_ms: null }))
}

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
        needs_token: false, usage: { allowed: ['ask'], human_gate: null }, card: null, card_url: 'https://example.org/docs/.well-known/agent-card.json', card_error: null, card_at_ms: null, last_ms: null },
      // a peer in a tailnet this machine is not in: its name does not resolve, and the last message did not go out
      { id: 'partner-bridge', reach: 'failed', summary: 'The Bridge of a partner team, reached through their tailnet', owner: 'partner',
        network: 'tailnet', needs_token: true, usage: { allowed: ['ask'], human_gate: 'the owner confirms every answer' },
        card: null, card_url: 'https://example.org/partner/.well-known/agent-card.json',
        card_error: 'unreachable: [Errno 8] nodename nor servname provided, or not known', card_at_ms: now - 4 * MIN,
        last_error: 'peer refused the call (403): token missing, wrong, or bound to another identity', last_ms: now - 30 * MIN },
      // a peer from cockpit.a2a_sources: a skill's script reaches it through a broker and keeps the credentials
      { id: 'relay-bridge', reach: 'ok', last_error: null, summary: 'A colleague\'s Bridge, reached through a broker', owner: 'colleague',
        network: null, needs_token: true, via: 'broker', usage: { allowed: [], human_gate: null },
        card: card('Relay Bridge', 'Answers team and IT questions after its owner releases each answer.', [
          { id: 'ask', name: 'Questions', description: 'Team and IT questions, answered after release.', tags: ['peer'], examples: [] }]),
        card_url: null, card_error: null, card_at_ms: now - 3 * MIN, last_ms: null },
    ],
    keep_hours: 24,
    convs: [
      // three days untouched: past keep_hours, so the page lists it no more (the server archives it on its next look)
      { id: 'g0f0e0d0c0b', peer: 'team-bridge', started_ms: now - 72 * 3600000, last_ms: now - 72 * 3600000, context_id: null, running: false,
        turns: [{ q: 'Is the old demo branch still needed?', mode: 'ask', a: 'No, it was merged and can go.', state: 'completed', task_id: null,
          waiting: false, at_ms: now - 72 * 3600000, answered_ms: now - 72 * 3600000, error: null }] },
      { id: 'g0a1b2c3d4e', peer: 'team-bridge', started_ms: now - 2 * 3600000 - 5 * MIN, last_ms: now - 2 * 3600000, context_id: 'ctx-demo', running: false,
        turns: [{ q: 'Where does the alpha release stand?', mode: 'ask', a: 'Two of five items are open, the release notes and one test fix. The date holds.',
          state: 'completed', task_id: null, waiting: false, at_ms: now - 2 * 3600000 - 5 * MIN, answered_ms: now - 2 * 3600000, error: null }] },
    ],
  }
}

// the triage (triage.py state()): one line per task and inbox row of the demo, the last run 20 minutes ago
/** The themes of Work through as themes.py states them: invented names across the areas, the theme of each point (one
 *  a person moved), a suggestion with why for the points the triage says nothing about */
export const MOCK_THEMES = [{ id: 't1a2b3c', name: 'Release work', by: 'ai' }, { id: 't4d5e6f', name: 'Docs and guides', by: 'ai' },
  { id: 't7a8b9c', name: 'Board hygiene', by: 'person' }]
function themesState(now) {
  const [release, docs, board] = MOCK_THEMES.map(t => t.id)
  return { enabled: true, max_themes: 8, themes: MOCK_THEMES.map(t => ({ ...t })), budget_left: 5, running: false, last_error: null,
    at_ms: now - 6 * MIN, by_person: ['inbox:20261009-0910-tidy-labels-c3d4'],
    assign: { 'task:alpha-release': release, 'task:release-polish': release, 'task:old-cleanup': release,
      'inbox:20261009-0900-review-demo-a1b2': docs, 'task:demo-task': docs, 'task:docs-refresh': docs, 'inbox:20261009-0915-update-docs-e5f6': docs,
      'inbox:20261009-0910-tidy-labels-c3d4': board, 'inbox:20261009-0940-filed-board-c2d3': board },
    suggest: {
      'task:release-polish': { verb: 'later', reason: 'The wording waits for the release date', until: isoIn(4, now), drop: null, at_ms: now - 6 * MIN },
      'task:old-cleanup': { verb: 'done', reason: 'The fixtures are gone from the repository', until: null, drop: null, at_ms: now - 6 * MIN },
      'inbox:20261009-0910-tidy-labels-c3d4': { verb: 'drop', reason: 'The board was tidied last week', until: null, drop: 'not_needed', at_ms: now - 6 * MIN },
      'inbox:20261009-0940-filed-board-c2d3': { verb: 'you', reason: 'Only you can say if the switch is wanted', until: null, drop: null, at_ms: now - 6 * MIN },
    } }
}

function triageState(now, running = null) {
  // effort is for the AI only: a row the person does carries none (triage.py). next_rank is Jev's fresh rank of
  // the row (the order of the Work through page's tasks), rank_at when it was given
  const x = (kind, title, gist, verdict, doer, effort, extra = {}) => ({ kind, title, gist, verdict, reason: null, doer, effort, why: null,
    verdict_from: 'haiku', model: 'haiku-5-5', level: effort === 'small' ? 1 : 2, jev: null, next_rank: null, rank_at: null, ...extra })
  const items = {
    'task:demo-task': x('task', 'Write the onboarding guide for the demo project', 'A setup guide for new team members', 'continue', 'either', 'medium',
      { topic: 'docs' }),
    'task:docs-refresh': x('task', 'Refresh the docs index', 'Rebuild the index after the folder change', 'continue', 'ai', 'small',
      { topic: 'docs', next_rank: 1, rank_at: now - 3 * 3600000 }),
    'inbox:20261009-0915-update-docs-e5f6': x('inbox', 'Update the setup docs after the config change', 'Update the setup docs after the config change',
      'keep', 'ai', 'small', { topic: 'docs' }),
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
  // urgency and importance in a cycle of four, so the first four rows stand in the four squares (now, plan, hand, drop)
  const items = keys.map((k, i) => {
    const u = [0.9, 0.3, 0.8, 0.2][i % 4], im = [0.8, 0.9, 0.3, 0.2][i % 4], ef = i % 2 ? 0.3 : 0.6, me = i === 0 ? 0.7 : 0.3
    const priority = Math.round((0.42 * u + 0.38 * im + 0.12 * (1 - ef)) * 1000) / 1000
    return { key: k.key, rank: i + 1, title: k.title, urgency: u, impact: im, effort: ef, only_me: me, first: i ? 0.1 : 0.6, priority, confidence: 0.8,
      quadrant: u >= 0.5 && im >= 0.5 ? 'now' : im >= 0.5 ? 'plan' : u >= 0.5 ? 'hand' : 'drop', who: me >= 0.5 ? 'me' : 'delegate' }
  })
  return { at_ms: now, day: isoIn(0, now), took_ms: 2400, calls: 1, sent: items.length, skipped: { private: 0, section: 0, triage: 0, over: 0 },
    first: items[0]?.key ?? null, items, usage: { input_tokens: 1840, output_tokens: 220 }, price: null }
}

// ---------------------------------------------------------------- Work through, round 3: the Activity of a point

/** A row of the feed as activity.py sends it */
const feedRow = (ms, over) => ({ id: '', at: localIso(ms), at_ms: ms, kind: 'note', filters: ['notes'], text: '', change: null, undone_ms: null,
  by: null, links: [], doc: null, agent: null, ...over })

/** The invented rows of a point, newest first: every kind and filter on the demo task (an inbox item that names it
 *  reads it too), a short feed for the item about the setup docs, the creation alone for any other row */
function feedRows(row, now) {
  const ago = (min, over) => feedRow(now - min * MIN, over)
  const day = (days, over) => ({ ...feedRow(dayAt(-days, 12), over), at: isoIn(-days, now) })
  const doc = (path, state, extra = {}) => ({ path, state, changes: 1, attached: false, bytes: 4120, ...extra })
  if (row.task === 'demo-task') {
    return [
      ago(120, { id: 'theme:1', kind: 'theme', filters: ['state'], change: { field: 'theme', old: null, new: 'Docs and guides' }, by: { kind: 'themes', name: null } }),
      ago(160, { id: 'doc:1', kind: 'doc', filters: ['docs'], text: 'guide-draft.md', by: { kind: 'agent', name: 'demo-task research' },
        doc: doc('deliverables/guide-draft.md', 'new'), links: [{ kind: 'doc', slug: 'demo-task', path: 'deliverables/guide-draft.md' }] }),
      ago(240, { id: 'agent:1', kind: 'agent', filters: ['agents', 'state'], text: 'Started: find three good sources for the team page',
        change: { field: 'driver', old: null, new: 'demo-task research' }, by: { kind: 'suggestion', name: null },
        agent: { mode: 'go', stage: 'working', result: null }, links: [{ kind: 'tab', ref: 'surface:12' }] }),
      ago(19 * 60, { id: 'decision:1', kind: 'decision', filters: ['state'], change: { field: 'decision', old: null, new: 'later', until: isoIn(0, now) },
        undone_ms: now - 18 * 60 * MIN, by: { kind: 'batch', name: null } }),
      ago(21 * 60, { id: 'code:1', kind: 'code', filters: ['code'], text: 'example/repo#15 Add a config switch for the report', by: { kind: 'bridge', name: null },
        links: [{ kind: 'web', href: 'https://example.org/repo/issues/15' }] }),
      ago(25 * 60, { id: 'note:1', kind: 'note', filters: ['notes'], text: 'Outline agreed with the team, screenshots come next' }),
      ago(44 * 60, { id: 'doc:2', kind: 'doc', filters: ['docs'], by: { kind: 'git', name: null },
        doc: doc('deliverables/outline.md', 'changed', { changes: 3, bytes: 2310 }), links: [{ kind: 'doc', slug: 'demo-task', path: 'deliverables/outline.md' }] }),
      day(2, { id: 'log:1', kind: 'log', filters: ['notes'], text: 'Outline written, examples collected', by: { kind: 'bridge', name: null } }),
      ago(3 * 1440 + 60, { id: 'code:2', kind: 'code', filters: ['code'], text: 'example/repo#18 Docs: setup guide outline', by: { kind: 'git', name: null },
        links: [{ kind: 'web', href: 'https://example.org/repo/pull/18' }] }),
      ago(3 * 1440 + 120, { id: 'session:1', kind: 'session', filters: ['agents', 'state'], text: 'demo-task review',
        change: { field: 'driver', old: null, new: 'demo-task review' }, by: { kind: 'you', name: null } }),
      ago(4 * 1440, { id: 'agent:2', kind: 'agent', filters: ['agents', 'state'], text: 'Finished: three sources found, the result note is filed',
        by: { kind: 'agent', name: 'demo-task research' }, agent: { mode: 'go', stage: 'result', result: 'Three sources found' } }),
      ago(5 * 1440, { id: 'doc:3', kind: 'doc', filters: ['docs'], by: { kind: 'you', name: null },
        doc: doc('deliverables/screenshots.pdf', 'new', { attached: true, bytes: 48213 }), links: [{ kind: 'doc', slug: 'demo-task', path: 'deliverables/screenshots.pdf' }] }),
      ago(6 * 1440, { id: 'status:1', kind: 'status', filters: ['state'], change: { field: 'status', old: 'backlog', new: 'doing' }, by: { kind: 'git', name: null } }),
      day(7, { id: 'created:1', kind: 'created', filters: ['state'], change: { field: 'status', old: null, new: 'backlog' },
        by: { kind: 'you', name: null } }),
    ]
  }
  if (row.inbox_id === '20261009-0915-update-docs-e5f6') {
    return [
      ago(35, { id: 'agent:1', kind: 'agent', filters: ['agents', 'state'], text: 'Started: update the setup docs', change: { field: 'driver', old: null, new: null },
        by: { kind: 'you', name: null }, agent: { mode: 'go', stage: 'working', result: null } }),
      ago(26 * 60, { id: 'note:1', kind: 'note', filters: ['notes'], text: 'The new config key needs a line in the setup guide' }),
      day(3, { id: 'created:1', kind: 'created', filters: ['state'], change: { field: 'status', old: null, new: 'open' } }),
    ]
  }
  return [day(5, { id: 'created:1', kind: 'created', filters: ['state'], change: { field: 'status', old: null, new: row.status ?? 'open' } })]
}

/** The counts of a feed's filters, a row in all and in each of its own (activity.py counts) */
function feedCounts(rows) {
  const counts = { all: rows.length, notes: 0, docs: 0, state: 0, agents: 0, code: 0 }
  for (const r of rows) for (const f of r.filters) counts[f] += 1
  return counts
}

// the notes the demo gives the verbs Work through sends, in words both languages carry (WORDS); any other verb names itself
const MOCK_NOTES = { note: 'Mock: the note is kept', settle: 'Mock: decided', later: 'Mock: put off', shelve: 'Mock: shelved',
  do_it: 'Mock: an agent starts on it', task_reopen: 'Mock: back in the list', inbox_reopen: 'Mock: back in the list' }

// the sentence a mail of an instruction becomes: a start that drafts only (text.py instruct.mail_note)
const MAIL_NOTE = 'Write a mail draft with the mail-draft skill, a draft only, never send it'

/** A transport with the same interface as the real one, backed by the example state */
export function createMockTransport(opts = {}) {
  // opts.latency scales every pause the demo makes to look like a server (1 by default, 0 in the tests)
  const lag = Number.isFinite(opts.latency) ? opts.latency : 1
  const wait = (fn, ms) => setTimeout(fn, ms * lag)
  const now = () => Date.now()
  let state = buildState(now(), opts)
  let handlers = {}
  const mockMutes = [{ id: '20261008-0900-board-radar-0a1b', source: 'board-radar', scope: 'family', key_prefix: 'radar:stale:' }]   // invented, for the noise card
  let seq = state.model.seq
  let mockOrganize = null   // the demo's current organize proposal
  const jev = createMockJev ? createMockJev() : null   // the Jev tab's mock: the server's once-per-day rule, invented tokens
  const history = opts.empty ? [] : historyEntries(now())
  const orders = {}                                       // the kept Jev order per work page, as jev.py keeps it
  const added = {}                                        // Work through: notes and documents added per row key, newest first
  const summaries = {}                                    // the summary kept per key with the ids of the rows it read
  const blobs = new Map()                                 // the documents of the demo as Blob addresses, one per path
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
  const gone = new Map()                                   // the rows a decision took out, by key, for its undo
  const removeRows = (keys, verb) => {
    for (const sec of state.model.sections) {
      sec.rows.forEach((r, at) => { if (keys.includes(r.key)) gone.set(r.key, { section: sec.id, at, row: r, compact: sec.compact.includes(r.key),
        approvable: state.model.approvable.includes(r.key), task: state.model.task_rows.find(x => x.key === r.key) ?? null }) })
    }
    // a file put off stays a file, deferred; one closed or dropped leaves the list
    if (state.model.files) {
      const put = ['later', 'hide'].includes(verb)
      state.model.files = state.model.files.flatMap(f => (!keys.includes(`task:${f.slug}`) ? [f]
        : put ? [{ ...f, deferred: true, deferred_until: isoIn(3, now()) }] : []))
    }
    for (const s of state.model.sections) {
      s.rows = s.rows.filter(r => !keys.includes(r.key))
      s.compact = s.compact.filter(k => !keys.includes(k))
      s.total = s.rows.length
    }
    state.model.approvable = state.model.approvable.filter(k => !keys.includes(k))
    state.model.task_rows = state.model.task_rows.filter(r => !keys.includes(r.key))
    // an item put off past the window (model.deferred) leaves its list the same way
    for (const [at, r] of (state.model.deferred ?? []).entries()) {
      if (keys.includes(r.key)) gone.set(r.key, { section: 'deferred', at, row: r, compact: false, approvable: false, task: null })
    }
    if (state.model.deferred) state.model.deferred = state.model.deferred.filter(r => !keys.includes(r.key))
    state.model.review = { ...state.model.review, keys: state.model.review.keys.filter(k => !keys.includes(k)) }
    seq += 1
    state.model = { ...state.model, seq }
    wait(() => emit('view', state.model), 300)
  }

  // an undo: the row a decision took out comes back to its section, at its place, the page hears the new view
  const restoreRow = key => {
    const was = gone.get(key)
    if (!was) return
    gone.delete(key)
    if (was.section === 'deferred') {
      if (!(state.model.deferred ?? []).some(r => r.key === key)) state.model.deferred = [...(state.model.deferred ?? []), was.row]
      seq += 1
      state.model = { ...state.model, seq }
      wait(() => emit('view', state.model), 120)
      return
    }
    const sec = state.model.sections.find(x => x.id === was.section)
    if (!sec || sec.rows.some(r => r.key === key)) return
    sec.rows.splice(Math.min(was.at, sec.rows.length), 0, was.row)
    if (was.compact) sec.compact.push(key)
    sec.total = sec.rows.length
    if (was.approvable) state.model.approvable.push(key)
    if (was.task) state.model.task_rows.push(was.task)
    if (state.model.files && key.startsWith('task:')) state.model.files = state.model.files.map(f => (`task:${f.slug}` === key ? { ...f, deferred: false, deferred_until: null } : f))
    seq += 1
    state.model = { ...state.model, seq }
    wait(() => emit('view', state.model), 120)
  }

  // Work through, round 4 (actions_work.py flow_merge, task_unmerge; actions_chats.py session_unlink, session_link; the
  // verbs Back on of Not now sends): what each does to the demo's state, the answer as the server words it
  const merged = new Map()     // the files a merge took out, by slug, for its undo
  const refused = {}           // session_refused: sid -> {slug: at_ms}
  const publish = () => { seq += 1; state.model = { ...state.model, seq }; wait(() => emit('view', state.model), 120) }
  const fileByKey = key => (state.model.files ?? []).find(f => `task:${f.slug}` === key) ?? null
  const openTask = key => {
    const r = rowOf(key)
    if (r) return r
    const f = fileByKey(key)
    return f ? { key, task: f.slug, title: f.title, status: f.status, stream: f.kind === 'stream', work_kind: f.kind, inbox_id: null } : null
  }
  const decision = (key, change) => {
    added[key] = [feedRow(now(), { id: `decision:m${Object.values(added).flat().length + 1}`, kind: 'decision', filters: ['state'], change,
      by: { kind: 'you', name: null } }), ...(added[key] ?? [])]
  }
  const round4 = (verb, args, result) => {
    if (verb === 'flow_merge') {
      const off = flowOff()
      if (off) return off
      const keys = Array.isArray(args.keys) ? args.keys : []
      const bad = field => ({ ...fail(400, 'invalid_argument', `bad ${field}`), error: { code: 'invalid_argument', message: `bad ${field}`, field } })
      if (!keys.length || keys.length > 9 || keys.includes(args.keep) || new Set(keys).size !== keys.length) return bad('keys')
      for (const k of [args.keep, ...keys]) {
        const r = openTask(k)
        if (!r) return fail(409, 'stale_row', 'no such row')
        if (!String(k).startsWith('task:') || r.inbox_id || r.stream || r.work_kind === 'stream' || r.status === 'done') return fail(409, 'merge_not_task', 'only open tasks merge')
      }
      const keep = openTask(args.keep)
      const slugs = keys.map(k => k.slice(5))
      const items = []
      for (const k of keys) {
        const r = openTask(k)
        const slug = k.slice(5)
        const file = fileByKey(k)
        if (file) merged.set(slug, file)
        items.push({ key: k, title: r.title, kind: 'task', did: 'merged', ident: slug, into: keep.task, work_kind: 'task', undone_ms: null,
          undo: { verb: 'task_unmerge', args: { keep: keep.task, slug, as: r.status ?? 'doing' } } },
        { key: args.keep, title: keep.title, kind: 'task', did: 'merged_in', ident: keep.task, from: slug, undo: null, undone_ms: null })
        decision(k, { field: 'decision', old: null, new: 'merged', into: keep.task })
        decision(args.keep, { field: 'decision', old: null, new: 'merged_in', from: slug })
      }
      history.unshift({ id: `h${Math.random().toString(16).slice(2, 12).padEnd(10, '0')}`, at_ms: now(), verb: 'flow_merge', items, backfilled: false })
      removeRows(keys, 'merge')
      const names = keys.map(k => openTask(k)?.title ?? merged.get(k.slice(5))?.title ?? k).join(', ')
      return ok({ ...result, note: `${items.filter(x => x.did === 'merged').map(x => x.title).join(', ') || names} merged into ${keep.title}`, settled: keys,
        merge: { keep: keep.task, merged: slugs, failed: [] }, undo: items.filter(x => x.undo).map(x => ({ title: x.title, kind: 'task', undo: x.undo })) })
    }
    if (verb === 'task_unmerge') {
      const all = history.flatMap(e => e.items)
      const hit = all.find(it => !it.undone_ms && it.undo?.verb === 'task_unmerge' && it.undo.args.keep === args.keep && it.undo.args.slug === args.slug)
      if (!hit) return fail(409, 'not_applicable', 'no such merge to take back')
      hit.undone_ms = now()
      const into = all.find(it => !it.undone_ms && it.did === 'merged_in' && it.ident === args.keep && it.from === args.slug)
      if (into) into.undone_ms = now()
      const file = merged.get(args.slug)
      if (file && state.model.files && !fileByKey(`task:${args.slug}`)) state.model.files = [...state.model.files, file]
      merged.delete(args.slug)
      restoreRow(`task:${args.slug}`)
      publish()
      return ok({ ...result, note: `Merge of ${hit.title} taken back`, unmerge: { keep: args.keep, slug: args.slug } })
    }
    if (verb === 'session_unlink' || verb === 'session_link') {
      const list = state.sessions?.sessions ?? []
      const x = list.find(v => v.sid === args.session)
      if (!x) return fail(409, 'stale_row', 'no such session')
      if (verb === 'session_link') {
        if (refused[x.sid]) delete refused[x.sid][args.slug]
        Object.assign(x, { task: args.slug, task_how: 'hand', task_since_ms: now() })
      } else {
        if (!x.task) return fail(409, 'stale_row', 'the session has no task')
        refused[x.sid] = { ...(refused[x.sid] ?? {}), [x.task]: now() }
        result.session = { sid: x.sid, refused: x.task }
        result.note = x.task_how === 'seen' ? `The session no longer counts as work on ${x.task}` : `Mock: session_unlink ${x.task}`
        Object.assign(x, { task: null, task_how: null, task_since_ms: null })
      }
      state.sessions = { ...state.sessions, sessions: [...list] }
      wait(() => emit('sessions', state.sessions), 60)
      return null
    }
    if (verb === 'unhide') {
      const at = (state.model.hidden ?? []).findIndex(r => r.key === args.key)
      if (at < 0) return null
      const [r] = state.model.hidden.splice(at, 1)
      const sec = state.model.sections.find(x => x.id === (r.section ?? 'later')) ?? state.model.sections.at(-1)
      sec.rows = [...sec.rows, { ...r, hidden_until: null }]
      sec.total = sec.rows.length
      publish()
      return null
    }
    if (verb === 'inbox_reopen') {
      const r = rowOf(`inbox:${args.id}`)
      if (r?.inbox_state === 'deferred') { Object.assign(r, { inbox_state: 'open', until: null }); publish() }
      return null
    }
    if (verb === 'task_running' || verb === 'task_keep') {
      const keys = verb === 'task_running' ? [`task:${args.slug}`] : args.keys ?? []
      for (const k of keys) {
        const r = rowOf(k)
        if (!r) continue
        if (verb === 'task_running') Object.assign(r, { blocked_by: null, bucket: r.bucket === 'waiting' ? 'tasks' : r.bucket })
        else if (['resting', 'drop'].includes(r.bucket)) r.bucket = 'tasks'
      }
      publish()
      return null
    }
    return null
  }

  // Work through, round 3: the row of a key, the feed of a point (an inbox item that names a task reads the task's), the
  // refusals of flow_off and of a key no longer in the list
  const flowOff = () => (state.work?.flow?.enabled ? null : fail(409, 'flow_off', 'Work through is off'))
  const rowOf = key => state.model.sections.flatMap(x => x.rows).find(r => r.key === key) ?? null
  // the starts of the return channel on a row, as activity.py lists them, where the invented feed has none of its own
  const startRows = row => (state.model.returns ?? []).filter(r => r.key === row.key).map((r, k) => {
    const tab = state.tabs.tabs.find(t => t.ref === r.tab?.ref) ?? null
    return feedRow(r.at_ms ?? now(), { id: `agent:r${k + 1}`, kind: 'agent', filters: ['agents', 'state'], text: 'Started from the cockpit',
      change: { field: 'driver', old: null, new: tab?.name ?? null }, by: { kind: 'you', name: null },
      agent: { mode: r.mode ?? 'go', stage: r.stage ?? 'started', result: r.result?.text ?? null }, links: tab ? [{ kind: 'tab', ref: tab.ref }] : [] })
  })
  const feedOf = row => {
    const own = row.task ? `task:${row.task}` : row.key
    const base = feedRows(row, now())
    const rows = [...(added[row.key] ?? []), ...(own !== row.key ? added[own] ?? [] : []), ...base,
      ...(base.some(r => r.kind === 'agent') ? [] : startRows(row))]
      .sort((a, b) => (b.at_ms ?? 0) - (a.at_ms ?? 0))
    const hash = rows.map(r => r.id).join(',')
    const kept = summaries[row.key] ?? null
    const fl = state.work.flow
    return { ok: true, key: row.key, at_ms: now(), rows, more: false, counts: feedCounts(rows),
      facts: { created: rows.at(-1)?.at.slice(0, 10) ?? null, moved: rows[0]?.at ?? null,
        jev: row.task === 'demo-task' ? { quadrant: 'plan', rank: 2, urgency: 0.67, impact: 1.0, effort: 0.33, only_me: 0.8, at_ms: now() - 60 * MIN } : null },
      summary: kept ? { ...kept.summary, stale: kept.hash !== hash } : null,
      can: { note: true, attach: !!fl.attach?.enabled && !!row.task, summary: !!fl.summary?.enabled && rows.length > 0 }, hash }
  }
  // a document attached (activity.py attach): the name made safe and flat, the size and the data checked, a name taken
  // gets -2 up to -99; the row comes into the feed at once
  const attach = args => {
    const off = flowOff()
    if (off) return off
    if (!state.work.flow.attach?.enabled) return fail(409, 'attach_off', 'attaching is off')
    const row = rowOf(args.key)
    if (!row) return fail(409, 'stale_row', 'no such row')
    if (!row.task) return fail(409, 'attach_no_task', 'no open task on this row')
    const data = String(args.data ?? '')
    const bad = field => ({ ...fail(400, 'invalid_argument', `bad ${field}`), error: { code: 'invalid_argument', message: `bad ${field}`, field } })
    if (!data || data.length % 4 || !/^[A-Za-z0-9+/]+={0,2}$/.test(data)) return bad('data')
    const bytes = (data.length / 4) * 3 - (data.endsWith('==') ? 2 : data.endsWith('=') ? 1 : 0)
    if (bytes > state.work.flow.attach.max_mb * 1048576) return fail(413, 'attach_too_big', 'too big')
    // as activity.py safe_name: Python's \w is every letter and digit of any script, so \p{L} and \p{N} here; control
    // and format characters out; runs of blanks, then of underscores, as one
    let name = String(args.name ?? '').split(/[\\/]/).pop().normalize('NFC').replace(/[\p{Cc}\p{Cf}\p{Cs}\p{Co}\p{Cn}]/gu, '')
      .replace(/[^\p{L}\p{N}_ .()+,=@-]/gu, '_').replace(/ {2,}/g, ' ').replace(/_{2,}/g, '_').replace(/^[. _-]+/, '').replace(/[. ]+$/, '')
    if (name.length > 120) { const dot = name.lastIndexOf('.'); const ext = dot > 0 && name.length - dot <= 16 ? name.slice(dot) : ''; name = name.slice(0, 120 - ext.length) + ext }
    if (!name) return bad('name')
    const slug = row.task
    const own = `task:${slug}`
    const taken = new Set([...(added[own] ?? []), ...feedRows({ task: slug, key: own }, now())].filter(r => r.doc).map(r => r.doc.path.toLowerCase()))
    const dot = name.lastIndexOf('.')
    const [stem, ext] = dot > 0 ? [name.slice(0, dot), name.slice(dot)] : [name, '']
    let pick = name
    for (let n = 2; taken.has(`deliverables/${pick}`.toLowerCase()); n += 1) {
      if (n > 99) return fail(409, 'attach_exists', 'that name is taken')
      pick = `${stem}-${n}${ext}`
    }
    const path = `deliverables/${pick}`
    const r = feedRow(now(), { id: `doc:a${Object.values(added).flat().length + 1}`, kind: 'doc', filters: ['docs'], by: { kind: 'you', name: null },
      doc: { path, state: 'new', changes: 1, attached: true, bytes }, links: [{ kind: 'doc', slug, path }] })
    added[own] = [r, ...(added[own] ?? [])]
    // the page says the attachment itself (app.js flowAttach): no note of the demo's beside it
    return ok({ ok: true, verb: 'flow_attach', note: '', steps: [], settled: [], reload: 'none', attach: { path, name: pick, bytes, row: r } })
  }
  // a sentence of the instruction line as a plan (instruct.py), by a fixed word match, part by part (the parts between
  // commas): done, later, drop, a mail or a question to someone (always a start that drafts only), a start, a reply
  // (only with the point open and its tab at its prompt; after "reply:" the rest of the sentence is its words). A part
  // with none of them stays unclear, as the model says what it could not plan; nothing runs
  const instruct = args => {
    const rows = (args.keys ?? []).map(rowOf).filter(Boolean)
    if (!rows.length) return fail(409, 'stale_row', 'no such row')
    const text = String(args.text ?? '').trim()
    const steps = []
    const unclear = []
    const step = (op, rs, extra = {}) => steps.push({ n: steps.length + 1, op, keys: rs.map(r => r.key), titles: rs.map(r => r.title), skipped: [], ...extra })
    const monday = (() => { const d = new Date(now()); d.setDate(d.getDate() + (((8 - d.getDay()) % 7) || 7)); return isoIn(Math.round((d.getTime() - now()) / DAY), now()) })()
    // typed words go only to a tab that waits at its prompt (instruct.py takes_words); one that asks a choice is answered
    // on the card (asks), one at work takes nothing (not_offered)
    const reply = said => {
      const tab = args.point ? state.tabs.tabs.find(t => t.slug === rows[0].task && t.state !== 'shell') : null
      if (tab?.state === 'waiting' && !tab.is_control) step('reply', rows.slice(0, 1), { tab_ref: tab.ref, text: said })
      else step('reply', [], { tab_ref: null, text: said, skipped: rows.map(r => ({ key: r.key, title: r.title,
        why: !tab ? 'no_tab' : tab.state === 'needs-you' ? 'asks' : 'not_offered' })) })
    }
    const told = /(?:^|[\s,;])(?:reply|answer|antworte|antwort)\s*:\s*(.*)$/iu.exec(text)
    const head = told ? text.slice(0, told.index) : text
    for (const part of head.split(/[,;]/).map(x => x.trim().replace(/^(?:and|und|then|dann)\s+/iu, '')).filter(Boolean)) {
      const low = ` ${part.toLowerCase().replace(/[^\p{L}\p{N}]+/gu, ' ')} `
      const has = (...w) => w.some(x => low.includes(` ${x} `))
      const before = steps.length
      if (has('done', 'erledigt', 'fertig')) step('done', rows)
      if (has('later', 'später', 'monday', 'montag')) step('later', rows, { until: monday })
      if (has('drop', 'weg', 'not needed', 'nicht mehr nötig')) step('drop', rows, { reason: 'not_needed' })
      if (has('mail', 'e mail', 'email', 'ask', 'frag', 'frage')) step('do', rows, { mail: true, note: `${localize(MAIL_NOTE, words)}: ${part}` })
      else if (has('let ai', 'bridge macht', 'agent')) step('do', rows, { note: part })
      if (has('reply', 'antwort', 'antworte', 'go on', 'weiter')) reply(part)
      if (steps.length === before) unclear.push(part)
    }
    if (told) reply(told[1].trim() || text)
    return { id: `p${Math.random().toString(16).slice(2, 12).padEnd(10, '0')}`, text, point: !!args.point, n: rows.length, steps,
      unclear: !steps.length ? 'No verb in the sentence: done, later, drop, a mail or a reply.' : unclear.length ? `${localize('No verb in this part:', words)} ${unclear.join('; ')}` : null,
      model: 'haiku', at_ms: now() }
  }

  return {
    // the address of a file the page links: a document of a task opens as a Blob of invented text, the rest as it is
    href(p) {
      if (!String(p).startsWith('/api/flow/doc?') || typeof Blob !== 'function' || typeof URL?.createObjectURL !== 'function') return p
      if (!blobs.has(p)) {
        const file = new URLSearchParams(p.split('?')[1]).get('path') ?? ''
        const text = `${file}\n\n${localize('A file of the demo, invented: nothing here is real.', words)}\n`
        blobs.set(p, URL.createObjectURL(new Blob([text], { type: 'text/plain;charset=utf-8' })))
      }
      return blobs.get(p)
    },
    async get(path) {
      const [pathname, query = ''] = path.split('?')
      const url = { pathname, searchParams: new URLSearchParams(query) }
      if (url.pathname === '/api/bootstrap') {
        if (opts.auth === false) return fail(401, 'unauthorized', 'no cookie')
        // the check of the cockpit: block finds nothing in the invented config (config_warnings, #402)
        return ok({ ok: true, csrf: 'mock', language: opts.lang || 'en', version: '0.1.0', config_warnings: [],
          config: { port: 8797, relay: true, tabs_seconds: 10, full_minutes: 10, voice: false, target: 'area', control: 'Control', profile: 'morning' } })
      }
      if (url.pathname === '/api/state') return ok(state)
      if (url.pathname === '/api/inbox') return ok(inboxDetail(url.searchParams.get('id'), state))
      if (url.pathname === '/api/task' && url.searchParams.get('file')) {
        const found = taskFile(url.searchParams.get('slug'), url.searchParams.get('file'))
        return found ? ok(found) : fail(404, 'not_found', 'no such file')
      }
      if (url.pathname === '/api/task') return ok(taskDetail(url.searchParams.get('slug'), state, words))
      if (url.pathname === '/api/flow/activity') {
        const off = flowOff()
        if (off) return off
        const row = rowOf(url.searchParams.get('key'))
        if (!row) return fail(409, 'stale_row', 'no such row')
        const { hash, ...feed } = feedOf(row)
        return ok(feed)
      }
      if (url.pathname === '/api/records') return ok(mockRecords(state))
      if (url.pathname === '/api/find') {
        const q = String(url.searchParams.get('q') ?? '')
        if (q.trim().length < 2 || q.length > 200) return fail(400, 'invalid_argument', 'the query must be 2 to 200 characters')
        return ok(findFiles(q, state))
      }
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
        // like the server: a hash of the text, and unchanged without the text when the page names it (since)
        let h = 0x811c9dc5
        for (const ch of text) h = Math.imul(h ^ ch.codePointAt(0), 16777619) >>> 0
        const hash = h.toString(16).padStart(8, '0')
        const head = { ok: true, ref: tab.ref, name: tab.name, state: tab.state, workspace: tab.workspace, hash, at_ms: now() }
        return ok(url.searchParams.get('since') === hash ? { ...head, unchanged: true } : { ...head, text })
      }
      if (url.pathname === '/api/history') return ok({ ok: true, entries: history })
      if (url.pathname === '/api/agents') return ok({ ok: true, ...state.agents })
      if (url.pathname === '/api/ticker') return ok({ ok: true, ticker: state.ticker })
      if (url.pathname === '/api/usage') {
        const n = Number(url.searchParams.get('days'))
        return ok({ ok: true, usage: usageView(now(), [7, 30, 90].includes(n) ? n : 7) })
      }
      if (url.pathname === '/api/costs') return ok({ ok: true, view: costsView(now()) })
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
      await new Promise(r => wait(r, 250))
      if (path === '/api/flow/attach') return attach(body ?? {})
      // the demo has no server poll to slow down: a page reporting its visibility is simply acknowledged
      if (path === '/api/presence') return { status: 200, ok: true, data: { ok: true }, error: null }
      // nor an audit log: a page view is simply acknowledged
      if (path === '/api/seen') return { status: 200, ok: true, data: { ok: true }, error: null }
      if (path === '/api/reload') {
        const loading = { pass: 'quick', fresh: !!body?.fresh, started_ms: now(), eta_ms: 3000, queued: 'full', last_error: null }
        state.loading = loading
        emit('loading', loading)
        wait(() => {
          state.loading = { pass: null, fresh: false, started_ms: 0, eta_ms: 0, queued: null, last_error: null }
          seq += 1
          state.model = { ...state.model, seq, collected_at: hhmm(now()), collected_ms: now(), full_ms: now() }
          emit('loading', state.loading)
          emit('view', state.model)
        }, 3000)
        return { status: 202, ok: true, data: { ok: true, loading }, error: null }
      }
      if (path === '/api/ask' && body?.via === 'quick') {
        // a free question may bring what the page shows (actions.py ask `context`): refused when too long, never cut
        const context = body?.args?.context
        if (context != null && (body.kind !== 'free' || typeof context !== 'string' || context.length > 6000)) return fail(400, 'invalid_argument', 'bad context')
        // a short session of its own: invented answer, invented cost, nothing is asked for real
        const model = body.model || 'haiku'
        const q = body?.kind === 'free' ? String(body.args?.text ?? '') : `Example question of kind ${body?.kind}`
        let conv = state.quick.convs.find(c => c.id === body.conv)
        if (!conv) {
          conv = { id: `q${Math.random().toString(16).slice(2, 12).padEnd(10, '0')}`, kind: body.kind, started_ms: now(), session: null, total_usd: 0, turns: [], running: false,
            ...(body.place ? { place: body.place } : {}) }
          // a new conversation of the core takes the place of the last
          state.quick = { ...state.quick, convs: [conv, ...state.quick.convs.filter(c => !body.place || c.place !== body.place || c.running)] }
        }
        conv.turns.push({ q, a: null, model_asked: model, model: null, cost_usd: null, at_ms: now(), error: null })
        conv.running = true
        emit('quick', JSON.parse(JSON.stringify(state.quick)))
        wait(() => {
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
        wait(() => emit('relay', { ...record, status: 'submitted' }), 900)
        wait(() => emit('relay', { ...record, status: 'answered', answered_ms: now(),
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
        wait(() => { state.triage = opts.empty ? { ...state.triage, running: null } : triageState(now()); emit('triage', state.triage) }, 3000)
        return { status: 202, ok: true, data: { ok: true, triage: state.triage }, error: null }
      }
      if (path.startsWith('/api/jev/') && !jev) return fail(404, 'jev_off', 'Jev is off')
      if (path === '/api/jev/rank') {
        const page = state.model.pages.find(p => p.id === body?.page && p.jev)
        if (!page) return fail(404, 'not_found', 'no page with jev: under that id')
        const day = isoIn(0, now())
        if (body.force || (body.daily && orders[page.id]?.day !== day)) {
          await new Promise(res => wait(res, 1200))
          orders[page.id] = jevOrder(page, now())
        }
        return ok({ ok: true, page: page.id, order: orders[page.id] ?? null, today: { day, ratings: 0, input_tokens: 0, output_tokens: 0, unknown: 0 } })
      }
      if (path === '/api/jev/run') {
        // the Jev tab: invented judgments from jev/logic.js, the real API is never asked
        const r = jev(state.model, { force: !!body?.force, cacheOnly: !!body?.cache_only })
        if (r.paid) await new Promise(res => wait(res, 2400))
        return ok(r.result)
      }
      if (path === '/api/action') {
        const verb = body?.verb
        const args = body?.args ?? {}
        const keys = args.keys ?? (args.key ? [args.key] : [])
        const result = { ok: true, verb, note: MOCK_NOTES[verb] ?? `Mock: ${verb} ${keys.join(', ') || args.tab_ref || ''}`.trim(), steps: [], settled: [],
          reload: 'none', jump: null, relay: null, confirm: null }
        if (verb === 'approve_all' && !args.confirm) return ok({ ...result, note: '', confirm: { count: keys.length } })
        // the files tab's question to its records: the demo names the first record it was sent
        if (verb === 'files_ask') {
          const fs = state.work.files_search
          if (!fs?.enabled) return fail(409, 'files_ask_off', 'asking the records is off')
          const recs = mockRecords(state).records.filter(r => (args.paths ?? []).includes(r.path))
          if (!recs.length) return fail(409, 'files_ask_held', 'no record left to send')
          if (!fs.left) return fail(429, 'files_ask_budget', 'no questions left today')
          await new Promise(r => wait(r, 800))
          state.work = { ...state.work, files_search: { ...fs, left: fs.left - 1 } }
          return ok({ ...result, note: '', ask: { answer: `Start with ${recs[0].title}: it changed last and names the next step.`,
            files: [{ n: 1, why: 'it changed last', slug: recs[0].slug, path: recs[0].path, title: recs[0].title }], sent: recs.length,
            held: { n: 0, words: [] }, model: 'haiku', left: fs.left - 1, at_ms: now() } })
        }
        // Work through, round 3: an attachment, the summary of a point's Activity, the plan of an instruction
        if (['flow_attach', 'flow_activity_summary', 'flow_instruct'].includes(verb)) {
          const off = flowOff()
          if (off) return off
          if (verb === 'flow_attach') return attach(args)
          const ai = state.flow_ai
          if (verb === 'flow_activity_summary') {
            if (!state.work.flow.summary?.enabled) return fail(409, 'summary_off', 'the summary is off')
            const row = rowOf(args.key)
            if (!row) return fail(409, 'stale_row', 'no such row')
            const { hash, rows } = feedOf(row)
            if (!rows.length) return fail(409, 'summary_empty', 'nothing to summarise')
            const kept = summaries[row.key]
            if (kept && kept.hash === hash) return ok({ ...result, note: '', summary: { ...kept.summary, stale: false, cached: true }, flow_ai: ai })
            if (!ai.summary_left) return fail(429, 'summary_budget', 'no summaries left today')
            await new Promise(r => wait(r, 900))
            const summary = { text: 'Since last week the outline was agreed with the team and the first two chapters stand as a draft. An agent found three sources, and the screenshots come next.',
              since: isoIn(-7, now()), at_ms: now(), model: 'haiku' }
            summaries[row.key] = { hash, summary }
            state.flow_ai = { ...ai, summary_left: ai.summary_left - 1 }
            return ok({ ...result, note: '', summary: { ...summary, stale: false, cached: false }, flow_ai: state.flow_ai })
          }
          if (!state.work.flow.instruct?.enabled) return fail(409, 'instruct_off', 'the instruction line is off')
          if (!ai.instruct_left) return fail(429, 'instruct_budget', 'no instructions left today')
          const plan = instruct(args)
          if (plan.ok === false || plan.error) return plan
          await new Promise(r => wait(r, 700))
          state.flow_ai = { ...ai, instruct_left: ai.instruct_left - 1 }
          return ok({ ...result, note: '', plan, flow_ai: state.flow_ai })
        }
        // Work through, round 4: a merge of open tasks and its undo, Not now's Back on, a session's task taken back
        const r4 = round4(verb, args, result)
        if (r4) return r4
        // a note on a row: it comes into the row's Activity at once (task.py note, an inbox note event)
        if (verb === 'note' && args.key && String(args.text ?? '').trim()) {
          added[args.key] = [feedRow(now(), { id: `note:a${Object.values(added).flat().length + 1}`, kind: 'note', filters: ['notes'],
            text: String(args.text).trim(), by: { kind: 'you', name: null } }), ...(added[args.key] ?? [])]
        }
        // an answer to a tab: refused like the server when the question it names is no longer on screen
        // (the third option of the dialog stands for that here) or a draft is typed in the tab
        if (['tab_send', 'tab_option', 'tab_yes', 'tab_no', 'tab_go_on'].includes(verb)) {
          const tab = state.tabs.tabs.find(t => t.ref === args.tab_ref)
          if (!tab || (args.seen && args.seen !== tab.ask?.hash) || (verb === 'tab_option' && args.n === 3)) {
            return fail(409, 'tab_moved', 'The tab moved on before the answer, nothing was sent.')
          }
          if ((verb === 'tab_send' || verb === 'tab_go_on') && tab.ask?.draft) {
            return fail(409, 'tab_draft', 'Something is typed in that tab, nothing was sent.')
          }
          // a dialog takes its options, never typed words (actions.py v_tab_send)
          if (verb === 'tab_send' && tab.state === 'needs-you' && (args.seen || args.expect || args.name)) {
            return fail(409, 'not_applicable', 'A dialog takes its options, not text.')
          }
          const said = verb === 'tab_option' ? tab.ask?.options.find(o => o.n === args.n)?.label : verb === 'tab_send' ? args.text : verb
          result.note = `Mock: ${tab.name}: ${said}`
        }
        // a start from the chat answers with its inbox item and the launch outcome (actions.py v_chat_tab)
        if (verb === 'chat_tab') {
          result.inbox_id = `20261009-1200-demo-chat-${Math.random().toString(16).slice(2, 6).padEnd(4, '0')}`
          result.launch = 'started'
        }
        // a chat handed on carries how it went (quick.py handed); a second click while one starts is refused
        if (verb === 'quick_handoff') {
          const conv = state.quick.convs.find(x => x.id === args.conv)
          if (!conv) return fail(409, 'stale_row', 'the conversation is gone')
          if (conv.handed?.status === 'starting') return fail(409, 'handoff_running', 'This chat is being handed on right now.')
          if (args.to === 'control') {
            const record = { id: `${new Date(now()).toISOString().replace(/[-:]/g, '').slice(0, 15)}-${Math.random().toString(16).slice(2, 10).padEnd(8, '0')}`,
              kind: 'free', created_ms: now(), status: state.relay.online ? 'queued' : 'offline', preview: 'From a quick question in the dashboard', answer: null, answered_ms: null }
            state.relay = { ...state.relay, records: [...state.relay.records, record] }
            result.relay = record
            conv.handed = { to: 'control', at_ms: now(), status: record.status, relay_id: record.id }
          } else {
            conv.handed = { to: 'tab', at_ms: now(), status: 'started', inbox_id: `20261009-1200-demo-chat-${Math.random().toString(16).slice(2, 6).padEnd(4, '0')}` }
          }
          result.handed = { ...conv.handed }
          emit('quick', JSON.parse(JSON.stringify(state.quick)))
        }
        // a name of its own for a tab or a workspace, refused like the server (actions.py v_tab_rename)
        if (verb === 'tab_rename' || verb === 'workspace_rename') {
          const title = String(args.title ?? '').trim()
          const all = state.tabs.tabs
          if (verb === 'tab_rename') {
            const tab = all.find(t => t.ref === args.tab_ref)
            if (!tab) return fail(409, 'stale_tab', 'This tab is gone or changed meanwhile.')
            if (tab.is_control) return fail(409, 'control_tab', 'The control session keeps its name.')
            if (tab.slug || tab.item || tab.team) return fail(409, 'task_tab_name', 'This tab\'s name comes from its task and stays.')
            if (tab.state_source === 'glyph' && tab.state !== 'shell') return fail(409, 'rename_loses_state', 'Renaming this tab would hide whether it waits.')
            if (all.some(t => t.ref !== tab.ref && t.name.toLowerCase() === title.toLowerCase())) return fail(409, 'name_in_use', 'That name is already in use.')
            state.tabs = { ...state.tabs, tabs: all.map(t => t.ref === tab.ref ? { ...t, name: title } : t) }
          } else {
            const spaces = state.tabs.workspaces ?? []
            const ws = spaces.find(w => w.ref === args.ws_ref)
            if (!ws) return fail(409, 'stale_workspace', 'This workspace is gone or changed meanwhile.')
            if (ws.title === state.tabs.control?.name) return fail(409, 'control_tab', 'The control session keeps its name.')
            if (spaces.some(w => w.ref !== ws.ref && w.title.toLowerCase() === title.toLowerCase())) return fail(409, 'name_in_use', 'That name is already in use.')
            state.tabs = { ...state.tabs, workspaces: spaces.map(w => w.ref === ws.ref ? { ...w, title } : w),
              tabs: all.map(t => t.ws_ref === ws.ref ? { ...t, workspace: title } : t) }
          }
          emit('tabs', state.tabs)
          result.note = `Mock: now named ${title}`
        }
        // organize with AI: an invented proposal; apply changes the mock state as the terminal would
        if (verb === 'organize_propose') {
          mockOrganize = organizeProposal(now())
          result.proposal = mockOrganize
          result.note = ''
        }
        if (verb === 'organize_apply') {
          if (!mockOrganize || mockOrganize.id !== args.proposal) return fail(409, 'stale_proposal', 'This proposal is no longer current. Ask for a new one.')
          const picked = mockOrganize.items.filter(i => (args.items ?? []).includes(i.id))
          let spaces = state.tabs.workspaces ?? []
          let all = state.tabs.tabs
          for (const it of picked) {
            if (it.kind === 'ws_title') {
              spaces = spaces.map(w => w.ref === it.ref ? { ...w, title: it.to } : w)
              all = all.map(t => t.ws_ref === it.ref ? { ...t, workspace: it.to } : t)
            }
            if (it.kind === 'ws_color') spaces = spaces.map(w => w.ref === it.ref ? { ...w, color: it.to ? PALETTE[it.to] : null, color_name: it.to } : w)
            if (it.kind === 'ws_description') spaces = spaces.map(w => w.ref === it.ref ? { ...w, description: it.to } : w)
            if (it.kind === 'tab_title') all = all.map(t => t.ref === it.ref ? { ...t, name: it.to } : t)
            if (it.kind === 'tab_move') {
              const dest = spaces.find(w => w.ref === it.to)
              all = all.map(t => t.ref === it.ref ? { ...t, ws_ref: it.to, workspace: dest?.title ?? t.workspace } : t)
            }
          }
          state.tabs = { ...state.tabs, workspaces: spaces, tabs: all }
          emit('tabs', state.tabs)
          Object.assign(result, { applied: picked.map(i => i.id), skipped: [], failed: [] })
          result.note = `Mock: ${picked.length} applied`
        }
        if (['drop', 'done', 'later', 'hide', 'task_close', 'settle', 'shelve'].includes(verb) || (verb === 'approve_all' && args.confirm)) {
          result.settled = keys
          remember(verb, keys)
          removeRows(keys, verb)
        }
        if (verb.startsWith('flow_theme')) {
          // the themes of Work through (themes.py): a run gives each new point the theme of its area's nearest
          // invented theme, a move or a new theme by hand wins, a name by hand stays
          const th = { ...state.themes, themes: state.themes.themes.map(t => ({ ...t })), assign: { ...state.themes.assign } }
          const byArea = { Ops: MOCK_THEMES[0].id, Docs: MOCK_THEMES[1].id, Demo: MOCK_THEMES[1].id }
          const rows = state.model.sections.flatMap(x => x.rows)
          if (verb === 'flow_themes_run') {
            if (!th.budget_left) return fail(429, 'themes_budget', 'no runs left today')
            for (const k of args.keys ?? []) {
              if (args.mode === 'regroup' && th.by_person.includes(k)) continue
              if (args.mode === 'assign' && th.assign[k]) continue
              const r = rows.find(x => x.key === k)
              th.assign[k] = byArea[r?.area] ?? MOCK_THEMES[2].id
            }
            th.budget_left -= 1
            th.at_ms = now()
            // the page's own run stays quiet, the click says what it did
            result.note = args.mode === 'regroup' ? `Mock: themes ordered: ${(args.keys ?? []).length} points` : ''
          } else if (verb === 'flow_theme_move') {
            result.note = ''
            th.assign[args.key] = args.theme
            th.by_person = [...new Set([...th.by_person, args.key])]
          } else if (verb === 'flow_theme_new') {
            const id = `t${Math.random().toString(16).slice(2, 8).padEnd(6, '0')}`
            th.themes.push({ id, name: args.name, by: 'person' })
            th.assign[args.key] = id
            th.by_person = [...new Set([...th.by_person, args.key])]
          } else if (verb === 'flow_theme_rename') {
            th.themes = th.themes.map(t => (t.id === args.theme ? { ...t, name: args.name, by: 'person' } : t))
          }
          state.themes = th
          result.themes = th
          emit('themes', th)
        }
        if (verb === 'do_it' && args.note) {
          // a start with a sentence (the Work through page): it runs in the return channel at once, as the server records it
          const rows = state.model.sections.flatMap(x => x.rows)
          const started = keys.map(k => rows.find(r => r.key === k)).filter(Boolean)
            .map(r => ({ key: r.key, item: r.inbox_id ?? r.task, title: r.title, mode: 'go', at_ms: now(), stage: 'started', in_briefing: true, tab: null, result: null }))
          seq += 1
          state.model = { ...state.model, seq, returns: [...started, ...(state.model.returns ?? []).filter(x => !keys.includes(x.key))] }
          wait(() => emit('view', state.model), 200)
        }
        // what a decision on rows can be taken back by, one undo per row as the server's history hands them out
        if (['settle', 'later', 'shelve'].includes(verb)) {
          result.undo = keys.map(k => (k.startsWith('task:') ? { title: k, kind: 'task', undo: { verb: 'task_reopen', args: { slug: k.slice(5) } } }
            : { title: k, kind: 'inbox', undo: { verb: 'inbox_reopen', args: { id: k.slice(6) } } }))
        }
        if (['task_reopen', 'inbox_reopen', 'unhide'].includes(verb)) {
          // the undo of the history drawer: the newest item that hands out exactly this undo is taken back
          const hit = history.flatMap(e => e.items).find(it => !it.undone_ms && it.undo?.verb === verb
            && Object.entries(args).every(([k, v]) => k === 'as' || k === 'note' || it.undo.args[k] === v))
          if (hit) hit.undone_ms = now()
          // and the row the decision took out of the list is back where it stood
          restoreRow(verb === 'task_reopen' ? `task:${args.slug}` : verb === 'inbox_reopen' ? `inbox:${args.id}` : args.key)
        }
        if (verb === 'drop' && (args.reason === 'family' || args.reason === 'source')) {
          result.muted = `20261010-1200-mock-${mockMutes.length}`
          mockMutes.push({ id: result.muted, source: 'homebox/health', scope: args.reason,
            ...(args.reason === 'source' ? { until: '2026-11-09' } : { key_prefix: 'health:crash:' }) })
        }
        if (verb === 'describe_run' || verb === 'describe_apply' || verb === 'describe_discard') {
          // describe (describe.py): an invented brief after a pause like the model's, a proposal once a person
          // edited it, a proposal taken over or dropped; the row's card and view change, the page hears both
          const rows = [...state.model.sections.flatMap(x => x.rows), ...(state.model.task_rows ?? [])].filter(r => r.key === args.key)
          if (!rows.length) return fail(409, 'stale_row', 'the row is no longer there')
          const r = rows[0]
          const view = r.describe ?? { written: null, stale: false, running: false, last_error: null, warnings: [], model_mismatch: false, proposal: null, by: null, at: null }
          const prop = view.proposal
          if (verb !== 'describe_run' && (!prop || prop.id !== args.proposal)) return fail(409, 'stale_proposal', 'This proposal is no longer current.', { describe: view })
          const day = isoIn(0, now())
          const setBrief = (brief, written) => {
            const card = { ...r.card, goal: brief.goal ?? null, story: brief.story ?? null, acceptance: brief.acceptance ?? null,
              brief_refs: null, written, gaps: (r.card?.gaps ?? []).filter(g => g !== 'no_goal' && g !== 'unresolved_ref') }
            return { card, describe: { ...view, written, stale: false, stale_why: null, warnings: [], proposal: null,
              by: brief.by ?? 'claude-haiku-5-5', at: day } }
          }
          let next
          if (verb === 'describe_run') {
            await new Promise(res => wait(res, 1500))
            const brief = mockBrief(r)
            next = view.written === 'human'
              ? { describe: { ...view, proposal: { id: `d${String(now()).slice(-10)}`, by: brief.by, at_ms: now(), brief } } }
              : setBrief(brief, 'ai')
            result.outcome = view.written === 'human' ? 'proposal' : 'written'
            // a brief prepared ahead (the Work through page) stays quiet, as actions_work.py describe_run keeps it
            result.note = args.ahead ? '' : view.written === 'human' ? 'Mock: a proposal waits beside your text' : `Mock: described ${r.title}`
          } else if (verb === 'describe_apply') {
            next = setBrief({ ...prop.brief, ...(args.brief ?? {}), by: prop.by }, 'human')
            result.note = `Mock: applied for ${r.title}`
          } else {
            next = { describe: { ...view, proposal: null } }
            result.note = 'Mock: proposal discarded'
          }
          for (const x of rows) Object.assign(x, next)
          result.describe = rows[0].describe
          seq += 1
          state.model = { ...state.model, seq }
          wait(() => { emit('describe', { key: args.key, ...rows[0].describe }); emit('view', state.model) }, 60)
        }
        if (verb === 'run_seen') {
          // a workflow run's result checked: it no longer waits in its task's file (the server's sessions event)
          state.sessions = { ...state.sessions, runs: (state.sessions?.runs ?? []).map(r => (r.id === args.id ? { ...r, seen: true } : r)) }
          result.note = 'Mock: result checked'
          wait(() => emit('sessions', state.sessions), 80)
        }
        if (verb === 'inbox_unmute') mockMutes.splice(0, mockMutes.length, ...mockMutes.filter(r => r.id !== args.id))
        if (verb === 'snapshot_list') result.note = 'Mock: 3 snapshots, latest 09:00'
        if (verb === 'row_action') result.note = `Mock: the step ${args.action} would start an agent tab on this row`
        if (verb === 'launch_settings' || verb === 'launch_settings_reset') {
          const next = verb === 'launch_settings' ? { ...state.launch.settings, ...(args.settings ?? {}) } : LAUNCH_CONFIG
          state.launch = launchState(next, !!createMockJev)
          result.note = verb === 'launch_settings' ? 'Mock: setting saved' : 'Mock: settings from the config again'
          wait(() => emit('state', state), 80)
        }
        if (verb === 'ticker_settings' || verb === 'ticker_settings_reset') {
          const next = verb === 'ticker_settings' ? { ...state.ticker.settings, ...(args.settings ?? {}) } : TICKER_CONFIG
          state.ticker = tickerState(next, now())
          result.note = verb === 'ticker_settings' ? 'Mock: ticker setting saved' : 'Mock: ticker settings from the config again'
          wait(() => emit('state', state), 80)
        }
        if (verb === 'github_board' || verb === 'github_board_default') {
          // the switch and the default for new boards: kept on the boards of every section, nothing asked for real
          for (const sec of state.model.pages.flatMap(p => p.sections ?? [])) {
            sec.boards = sec.boards?.map(b => verb === 'github_board_default' ? { ...b, default: args.mode === 'profile' ? null : args.mode }
              : b.slug === args.slug ? { ...b, mode: args.mode } : b)
          }
          result.note = verb === 'github_board' ? `Mock: ${args.slug}: ${args.mode}` : `Mock: new boards: ${args.mode}`
          wait(() => emit('state', state), 80)
        }
        if (verb === 'ticker_refresh') {
          state.ticker = tickerNext(state.ticker, { refreshing: true })
          emit('ticker', state.ticker)      // the start goes out as an event, like the server's
          result.note = 'Mock: reading the feeds'
          wait(() => { state.ticker = tickerNext(state.ticker, { refreshing: false, fetched_ms: now() }); emit('ticker', state.ticker) }, 1500)
        }
        if (verb === 'ticker_edit') {
          // invented picks and short titles after a moment; nothing is asked for real
          const started = now()
          state.ticker = tickerNext(state.ticker, { editor: { ...state.ticker.editor, running: { started_ms: started }, error: null } })
          emit('ticker', state.ticker)
          result.note = 'Mock: the editor is at work, nothing is asked for real'
          wait(() => {
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
        if (verb === 'guide_read') {
          // an invented reading after a moment; nothing is asked for real
          const ref = args.tab_ref
          const tab = state.tabs.tabs.find(x => x.ref === ref)
          if (GUIDE_READS[ref]) {
            const started = now()
            state.guide = { ...state.guide, rev: ++guideRev, entries: { ...state.guide.entries,
              [ref]: { ...guideEntry(ref, tab, started), running: true, started_ms: started, at_ms: null, options: [], where: '' } } }
            emit('guide', state.guide)
            result.note = 'Mock: Haiku reads the session, nothing is asked for real'
            wait(() => {
              state.guide = { ...state.guide, rev: ++guideRev, entries: { ...state.guide.entries, [ref]: { ...guideEntry(ref, tab, now()), at_ms: now() } } }
              emit('guide', state.guide)
            }, 1800)
          }
        }
        if (verb === 'guide_settings' || verb === 'guide_settings_reset') {
          const patch = verb === 'guide_settings' ? Object.fromEntries(['enabled', 'auto'].filter(k => typeof args[k] === 'boolean').map(k => [k, args[k]])) : {}
          const settings = verb === 'guide_settings' ? { enabled: state.guide.enabled, auto: state.guide.auto, ...patch } : { enabled: true, auto: true }
          state.guide = guideState(state.tabs.tabs, now(), { ...settings, overridden: Object.keys(settings).filter(k => settings[k] !== true),
            entries: settings.enabled ? state.guide.entries : {} })
          result.note = verb === 'guide_settings' ? 'Mock: setting saved' : 'Mock: settings from the config again'
        }
        if (verb.startsWith('guide_')) result.guide = state.guide
        if (verb === 'tour_done' || verb === 'tour_reset') {
          state.tour = { ...state.tour, done: verb === 'tour_done' ? { how: args.how, v: args.v, at: isoIn(0, now()) } : null }
          result.tour = state.tour
          emit('tour', state.tour)
        }
        if (verb === 'task_review') {
          // a check that runs for six seconds, then the same result again with a new time
          const publish = review => { seq += 1; state.model = { ...state.model, seq, review }; emit('view', state.model) }
          publish({ ...state.model.review, running: { started_ms: now(), count: keys.length, escalate: !!args.escalate } })
          wait(() => publish({ ...state.model.review, running: null,
            last: { ...state.model.review.last, reviewed_at: new Date(now()).toISOString().slice(0, 19) } }), 6000)
        }
        wait(() => note(result.note, 'ok'), 50)
        return ok(result)
      }
      return fail(404, 'not_found', 'unknown path')
    },
    events(h, onConn) {
      handlers = h
      wait(() => {
        onConn('open')
        emit('hello', { version: '0.1.0', started_ms: state.server.started_ms, language: opts.lang || 'en' })
        emit('state', state)
      }, 30)
      return { close() { handlers = {} } }
    },
  }
}
