// SPDX-License-Identifier: MIT
// UI texts of the chat as cmux (rules/language-policy.md section 3): the `chatArea` part of both tables, side by
// side under identical keys. text.js takes them in as TABLES.en.chatArea and TABLES.de.chatArea, so a view reads
// them through T() as before. Keys and comments are English; only the values of `de` are German.

export const CHAT = {
  en: {
    personOff: 'Questions to the AI are not set up for you yet.',
    personNote: 'The AI sees only the files of your areas. It reads, it changes nothing.',
    personAsk: 'Ask', personNew: 'New chat', personBox: 'Your question', personWait: 'Reading your files',
    personFailed: 'That did not work. Please try again.', personLeft: n => `${n} questions left today`,
    personEmpty: 'Ask about your tasks and files.',
    label: 'What the chat shows', work: 'Work', a2a: n => `A2A (${n})`,
    agents: 'Agents (A2A)', running: 'An agent is answering', waiting: 'An answer waits for its owner',
  },
  de: {
    personOff: 'Fragen an die KI sind für dich noch nicht eingerichtet.',
    personNote: 'Die KI sieht nur die Akten deiner Bereiche. Sie liest nur und ändert nichts.',
    personAsk: 'Fragen', personNew: 'Neuer Chat', personBox: 'Deine Frage', personWait: 'Liest deine Akten',
    personFailed: 'Das hat nicht geklappt. Bitte versuch es noch einmal.', personLeft: n => `Heute noch ${n} Fragen`,
    personEmpty: 'Frag nach deinen Aufgaben und Akten.',
    label: 'Was der Chat zeigt', work: 'Arbeit', a2a: n => `A2A (${n})`,
    agents: 'Agenten (A2A)', running: 'Ein Agent antwortet gerade', waiting: 'Eine Antwort wartet auf die Freigabe',
  },
}
