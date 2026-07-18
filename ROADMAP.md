# Roadmap

**Honest status:** open-bridge is built and used by its author day-to-day — **N=1**.
This roadmap is a *direction*, not a set of dated promises. Priorities move with
what people actually need. **Every open item below links to its issue — react 👍
on the issues you want most**; that's the signal ordering gets decided by.
Discuss use-cases in [Discussions](https://github.com/bks-lab/open-bridge/discussions).

Nothing below is a commitment to a date, and "Later / exploring" means exactly that.

## Shipped

- **Persistent project memory** — context that survives across sessions, in plain
  markdown + YAML in git.
- **Cross-tool skill discovery** — the same `SKILL.md` skills are found by Claude
  Code, GitHub Copilot, Codex, Gemini and Cursor via standard discovery paths.
- **Structured work-system** — a generated board + an append-only work log, with
  a closed status model.
- **Guided onboarding** — a four-lane front door (see it run, describe your
  goal, go private first, or bind a workspace) that takes a fresh clone to a
  running instance; hardened first-run (push-guard, scope consent, goal
  clarity) ([#51](https://github.com/bks-lab/open-bridge/issues/51),
  [#46](https://github.com/bks-lab/open-bridge/issues/46)).
- **Organization overlays** — subscribe to an organization's config by git URL
  and provision it onto a vanilla open-bridge, no fork
  ([#48](https://github.com/bks-lab/open-bridge/issues/48), `docs/org-overlays.md`).
- **Meeting transcription** — a bring-your-own-worker contract for `/debrief`
  plus a full reference pipeline (whisper.cpp + pyannote speaker naming) as a
  CORE skill (`docs/transcription-worker.md`, `skills/meeting-transcription/`).
- **One-command health check** — `/bridge-status` reports whether an instance
  is wired up correctly: configs resolve, the board generates from the task
  dirs, and docs + links are healthy
  ([#44](https://github.com/bks-lab/open-bridge/issues/44)).
- **Mirror-aware install** — a clone commits to your own private repo, never a
  silent push upstream: the armed `pre-push` guard, the private-template setup,
  and the `git fetch upstream && git merge upstream/main` update path keep you
  current without a public fork
  ([#52](https://github.com/bks-lab/open-bridge/issues/52), `rules/push-guard.md`).
- **Representative agent (Bridge-Agent) runtime** — a persistent, addressable
  A2A endpoint that fronts a persona to the world and to peer bridges under
  human gates; generic runtime + template in `agents/`, guide in
  `docs/representative-agent.md`
  ([#49](https://github.com/bks-lab/open-bridge/issues/49),
  [#126](https://github.com/bks-lab/open-bridge/pull/126)).
- **MCP→A2A gateway** — a thin, stateless gateway (`agents/_gateway/`) that
  lets MCP-only frontends (Claude connectors, ChatGPT developer mode, Gemini)
  talk to a bridge's A2A agent; anonymous access is standard, a bearer token
  unlocks more
  ([#125](https://github.com/bks-lab/open-bridge/pull/125); further work
  tracked in [#124](https://github.com/bks-lab/open-bridge/issues/124)).

## Now — building

- **Data-model guardrails — which data lives where**
  ([#53](https://github.com/bks-lab/open-bridge/issues/53)) — make the
  CORE/org/user data boundaries explicit and enforceable, so instances stay
  clean by construction.

## Next

- **More worked examples**
  ([#45](https://github.com/bks-lab/open-bridge/issues/45)) — additional
  end-to-end example setups beyond `examples/agency`.

## Later — exploring

- **Deployment & structured-feedback story**
  ([#56](https://github.com/bks-lab/open-bridge/issues/56)) — a repeatable way
  to roll an instance out to someone else and learn from how it behaves.

## Ecosystem — companion projects

open-bridge is the substrate; these optional, independently usable projects sit
around it. Take only what you need.

- **Bridge Deck** — a pixel-art, real-time dashboard that renders a bridge's
  live state (services, crew, calendar, channels). Separate repo,
  **Apache-2.0**, read-only, config-driven.
  → [`bks-lab/bridge-deck`](https://github.com/bks-lab/bridge-deck)
- **Representative agent** — the CORE `agents/` runtime + template, plus the
  MCP→A2A gateway that fronts it to MCP-only clients; see *Shipped*.

> Honest note: these run today as a single-maintainer (N=1) setup. They're
> built for technical early adopters, not yet for critical infrastructure.

## How priorities are set

Today this is shaped by one maintainer's real use (N=1) plus community 👍 on
the linked issues and Discussions. Items move between sections as they're
picked up; the changelog is the [Releases
page](https://github.com/bks-lab/open-bridge/releases).
