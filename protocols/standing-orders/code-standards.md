---
name: code-standards
scope: always
enforcement: advisory
applies_to: [analyst, builder]
load: on-trigger
triggers: ["write code", "implement", "refactor", "code review", "dispatch a build sub-agent"]
summary: "Code quality expectations applied to dispatched build sub-agents."
---
# Code Standards

> **Template `applies_to`.** `analyst` and `builder` below are placeholder
> sub-agent names — replace them with your own `.claude/agents/*.md`
> sub-agents. open-bridge itself ships only `archivist`, which this order
> does not target, so as shipped it applies to no dispatched sub-agent;
> adapt `applies_to` (or set it to `[]` for all) once you add your own.

## Rules

- Read the target repo's AGENTS.md or CLAUDE.md before making changes
- Follow existing patterns in the codebase — don't introduce new conventions
- Don't add features, refactor code, or make improvements beyond what was asked
- Don't add error handling for scenarios that can't happen
- Don't create abstractions for one-time operations
- Prefer editing existing files over creating new ones

## Testing

- Run existing tests before committing changes
- If the repo has a test suite, verify your changes don't break it
- For new functionality: write tests if the repo has a testing convention

## Commits

- Concise commit messages focused on "why" not "what"
- Don't bundle unrelated changes in one commit

## Violations

- Modifying files in a repo without reading its AGENTS.md or CLAUDE.md first
- Bundling unrelated changes in a single commit
- Adding unrequested features, refactors, or improvements
