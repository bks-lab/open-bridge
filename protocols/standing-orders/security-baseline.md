---
name: security-baseline
scope: always
enforcement: advisory
applies_to: [builder, guard]
---
# Security Baseline

> **Template `applies_to`.** `builder` and `guard` below are placeholder
> sub-agent names — replace them with your own `.claude/agents/*.md`
> sub-agents. open-bridge itself ships only `archivist`, which this order
> does not target, so as shipped it applies to no dispatched sub-agent;
> adapt `applies_to` (or set it to `[]` for all) once you add your own.

## Rules

- NEVER commit secrets, tokens, API keys, or credentials to git
- NEVER write secrets to .env files — use secure vaults or environment variables
- NEVER use Google Fonts CDN — self-host or use system fonts (GDPR)
- Check for command injection, XSS, SQL injection in any code you write
- Validate at system boundaries (user input, external APIs) — trust internal code

## Dependencies

- Review new dependencies before adding them
- Prefer well-maintained packages with active communities
- Pin versions — don't use open ranges in production

## Violations

- Secrets in git history (even if later removed)
- .env files with real credentials committed
- External CDN fonts without self-hosting
