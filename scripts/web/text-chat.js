// SPDX-License-Identifier: MIT
// UI texts of the chat as cmux (rules/language-policy.md section 3): the `chatArea` part of both tables, side by
// side under identical keys. text.js takes them in as TABLES.en.chatArea and TABLES.de.chatArea, so a view reads
// them through T() as before. Keys and comments are English; only the values of `de` are German.

export const CHAT = {
  en: {
    personOff: 'Questions to the AI are not set up for you yet.',
    label: 'What the chat shows', work: 'Work', a2a: n => `A2A (${n})`,
    agents: 'Agents (A2A)', running: 'An agent is answering', waiting: 'An answer waits for its owner',
  },
  de: {
    personOff: 'Fragen an die KI sind für dich noch nicht eingerichtet.',
    label: 'Was der Chat zeigt', work: 'Arbeit', a2a: n => `A2A (${n})`,
    agents: 'Agenten (A2A)', running: 'Ein Agent antwortet gerade', waiting: 'Eine Antwort wartet auf die Freigabe',
  },
}
