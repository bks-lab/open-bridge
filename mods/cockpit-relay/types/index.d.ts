/** The relay's switch as the mod reads it from `cockpit:` */
export type RelaySettings = {
  /** cockpit.enabled is true */
  enabled: boolean
  /** cockpit.relay is not false: this session heartbeats and takes cockpit questions addressed to it */
  relay: boolean
  /** language of the mod's notes: cockpit.language, else language.conversation */
  language: 'de' | 'en'
}

/** The cockpit question this session submitted and has not seen answered yet */
export type RelayFlight = {
  /** Record id, YYYYMMDDTHHMMSS-<8 hex> */
  id: string
  /** When it was submitted (ms) */
  at: number
  /** The main turn that carries it, once turn.start named it */
  turnId: string | null
}

declare module 'claude-code' {
  interface PluginState {
    'cockpit-relay': {
      /** The relay settings; null outside a Bridge, in agent tabs, in a -p run or when the config is unreadable */
      settings: RelaySettings | null
      /** A main turn of this session runs (turn.start seen, its turn.complete not yet): the relay waits */
      busy: boolean
      /** The cockpit question in flight in this session, at most one */
      flight: RelayFlight | null
      /** Questions marked stuck while their known turn still ran: its turn.complete still writes the answer */
      late: { id: string; turnId: string }[]
      /** The session id this session heartbeats under; null while the relay is off */
      session: string | null
    }
  }
}
