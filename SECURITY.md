# Security Policy

`open-bridge` orchestrates AI agents and handles configuration files plus
**references** to secret stores (KeyVault, 1Password, Keychain URIs — never the
secrets themselves). A flaw in how those references are parsed, in agent-dispatch
logic, or in a shipped skill or script can have real consequences. We take such
reports seriously and appreciate the time it takes to file a good one.

---

## Reporting a Vulnerability

**Please do not open a public GitHub issue for security bugs.** A public report
gives an exposure window before a fix exists.

Instead, email **info@bks-lab.com** with `SECURITY` in the subject line. Include
as much of the following as you can:

- **Affected component** — the file, skill (`skills/<name>/`), script
  (`scripts/`), protocol, or agent-dispatch path involved.
- **Reproduction** — minimal steps, config, or input that triggers the issue.
  A redacted `bridge-config.yaml` (secrets removed) helps.
- **Impact** — what an attacker can read, write, exfiltrate, or execute, and
  under what preconditions.
- **Version** — the commit SHA or release you tested against.

If you have a suggested fix, include it — but a clear report alone is plenty.

---

## Scope

**In scope** — the Bridge's own code and logic:

- Skills, scripts, and protocols shipped in this repository.
- Agent-dispatch logic — how agents are spawned, scoped, and coordinated.
- Config handling — parsing of `bridge-config.yaml`, cluster-wrapper YAML, and
  the resolution of secret-store **references** (KeyVault / 1Password / Keychain
  URIs).
- Template, schema, and validation logic that other instances depend on.

**Out of scope:**

- **A user's own private `user/` branch content** — personal configs, notes, and
  instance-specific data live outside this repository's responsibility.
- **Third-party agent runtimes** — Claude Code, Gemini CLI, and other host
  harnesses. Report those to their respective vendors.
- **Secrets the user committed themselves.** open-bridge stores references, not
  values; a raw credential placed in a tracked file by the operator is an
  operational mistake, not a vulnerability in this project. (We still recommend
  rotating it immediately.)

If you are unsure whether something is in scope, report it and let us decide.

---

## Response Expectations

`open-bridge` is a community open-source project maintained on a best-effort
basis. We want to set honest expectations:

- We aim to **acknowledge** a report within a few business days.
- There is **no SLA** and **no guaranteed fix timeline**.
- There is **no bug bounty** — we cannot offer payment for reports.

We will keep you informed as we triage and, where appropriate, credit you in the
fix (only with your consent).

---

## Coordinated Disclosure

We ask that you give us a reasonable window to investigate and ship a fix before
disclosing the issue publicly. We will work with you on timing and will not take
action against anyone who reports in good faith, acts within this scope, and
avoids privacy violations or service disruption while testing.

---

## Supported Versions

Only the latest release and the current `main` tip receive security fixes. Older
commits and forks are not maintained — update to the current `main` before
reporting, and confirm the issue still reproduces there.

---

Last updated: 2026-06-21.
