---
name: New Sub-Agent
about: Share a themed sub-agent for the crew
title: "[sub-agent] "
labels: sub-agent
---

**Sub-agent name**
The slug for `.claude/agents/<name>.md` (lowercase, hyphenated).

**Purpose**
What does this sub-agent do? When should the crew dispatch it (the kind of heavy, parallel, or isolated work it offloads from the main context)?

**Agent frontmatter**
Paste the YAML frontmatter from `.claude/agents/<name>.md`:

```yaml
---
name: <name>
description: <one-line trigger description — when to dispatch this agent>
tools: <comma-separated tool list, or omit to inherit all>
model: <inherit | sonnet | opus | haiku>
---
```

(No `role:` field, no `presets/` directory — sub-agents are flat files under `.claude/agents/`.)

**Agent body / voice**
Paste the markdown body below the frontmatter — the system prompt, posture, and any theme-specific voice.

**Structured output**
How does the agent return its result? Sub-agents should hand back a concise structured summary (findings, file paths, decisions) — not raw log dumps or full file contents — so the main context stays clean. Describe the shape it returns.

**Themed set?**
A themed set is several flat `.claude/agents/*.md` files. If this is part of a set, list the other agent names and how they fit together.
