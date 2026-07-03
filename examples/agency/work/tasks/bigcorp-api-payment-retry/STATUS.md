---
slug: bigcorp-api-payment-retry
type: incident
status: doing
priority: P1
created: 2026-06-23
last_updated: 2026-06-24
headline: "Stripe webhook signatures failing in prod — secret rotated, deploy config not updated (P1)"
sync:
  github:
    repo: acme-dev/bigcorp-issues
    issues: [142]
    project: { org: acme-dev, number: 1 }
---

# BigCorp — payment webhook retries failing in prod

## Situation

Since ~07:14 UTC, Stripe payment webhooks fail signature verification, so orders never
move to "paid". Customers are charged but not fulfilled — a P1 incident.

## Status

Root cause found: the webhook signing secret was rotated on Stripe and the new value
isn't in the deployment config yet, so every signature check fails. Config, not code.

## Next Steps

- [ ] set the new STRIPE_WEBHOOK_SECRET in the deploy config + restart
- [ ] replay the stuck webhook events so the orders settle
- [ ] add a check that warns when the secret is within 7 days of its rotation
