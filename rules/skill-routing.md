---
scope: core
description: Mandatory skill routing — when specific skills MUST be loaded before working
---
# Skill Routing Rules

## Purpose

Some skills are coordinators that enforce structured workflows, governance
rules, and learning loops. Bypassing them leads to ad-hoc work that
misses billing fields, skips preview gates, violates hard rules, and
loses institutional knowledge. These rules ensure the right skill is
loaded before work begins.

> **Worked example:** this rule ships as a template for mandatory-routing
> rules. CustomerA and `customer-a-coordinator` are placeholders — replace
> them with your own coordinator skills (org overlay); open-bridge itself
> ships no coordinator skill.

## CustomerA → customer-a-coordinator

**When:** The user's message contains ANY of these signals:
- Stakeholder names: <your customer contacts>
- Systems: <your integration systems>, Inbound Operator, Outbound Operator
- Artifacts: invoice number, correlation ID, document GUID
- Projects: <your project board>, extra-effort tracking, billing
- Infrastructure: fn-customer-a-ess-*, kv-customer-a-ess-*
- Topics: e-invoicing, UBL, weekly report, go-live

**Action:** Load `customer-a-coordinator` skill BEFORE doing any analysis,
creating issues, sending emails, or writing log entries.

**Why:** The coordinator enforces:
1. **Hard Rule #4** — issues via `github-projects-manager`, never raw `gh issue create`
2. **English-only fields** on the project board (German variants exist but are unused)
3. **Preview-before-execute** for all stakeholder-facing actions
4. **Immediate logging** with correct context tags (`customer-a/inbound`, `customer-a/outbound`)
5. **Learning loop** — new failure patterns are proposed to `knowledge.md`
6. **Billing classification** — every support action gets Billing Scope + Root Cause + Approval

**Anti-pattern:** "It's just a quick analysis" or "Let me just check the logs" —
these are exactly the cases where the coordinator adds the most value, because
quick analyses are the ones most likely to skip documentation and billing.

## Future routing rules

Add new entries here when a coordinator skill is created for another
customer or domain. Pattern: keyword triggers → mandatory skill → rationale.
