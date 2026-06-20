---
name: code-standards
scope: always
enforcement: advisory
applies_to: [analyst, builder]
---
# Code Standards

## Rules

- Read the target repo's CLAUDE.md before making changes
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

- Modifying files in a repo without reading its CLAUDE.md first
- Bundling unrelated changes in a single commit
- Adding unrequested features, refactors, or improvements
