# Acknowledgments

open-bridge stands on a large body of public work. Many of its ideas —
agent-orchestration patterns, the propose-then-confirm posture, the
identity/voice split, config-as-data conventions — were shaped by blog
posts, papers, talks, and open-source projects encountered over time.
It is not possible to name every source, and the absence of a name here
is not a judgment of its worth.

Some inspirations are specific enough to name:

- **The `SOUL.md` convention** for agent voice/identity files — pioneered
  by **Peter Steinberger** (creator of OpenClaw), standardized by
  **SoulSpec** ([soulspec.org](https://soulspec.org/)), and since adopted
  across the agent ecosystem. **Nous Research's Hermes agent** — which uses
  a `SOUL.md` and a self-improving "curator" loop — directly informed
  open-bridge's `bridge-curator` and its learning-autonomy model (which
  inverts Hermes' auto-apply posture into a propose-then-confirm gate).
- **Anthropic's Claude Code** and the broader agent-tooling patterns it
  popularized — including the **Agent Skills / `SKILL.md`** format
  ([agentskills.io](https://agentskills.io/)) that open-bridge's skills build on.
- **The `AGENTS.md` convention** ([agents.md](https://agents.md/)) for
  agent-readable project instructions.
- **Google Labs' `DESIGN.md`** format for token-level design manifests.
- **Tiago Forte's PARA method** (Projects · Areas · Resources · Archives) —
  the default organization scheme behind the document-routing system.

This list is non-exhaustive, and **inspiration is not endorsement**: none
of the projects named above are affiliated with, sponsor, or endorse
open-bridge.

Where third-party code or text was incorporated directly, it is
attributed at the point of use and its license is retained in that file's
header. This document covers ideas and influence — which
carry no such obligation — so that gratitude can be expressed freely
without implying a legal or contractual relationship with any named work.
