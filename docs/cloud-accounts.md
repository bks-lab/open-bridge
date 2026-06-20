---
summary: "Cloud-account inventory convention — read the inventory file before any cloud op"
type: guide
last_updated: 2026-06-19
related:
  - ../identity/accounts
---

# Cloud Accounts & Secrets

Cloud-provider accounts (and their secret stores) live as inventory files under
**`identity/accounts/<provider>-<tenant>.yaml`** — one file per account, the single
source of truth for tenant/account IDs, subscriptions, vault/keystore names,
resource-group maps, member rosters, and the bootstrap CLI sequence. Complex files
carry a companion **`<id>.README.md`** (decision matrix, setup recipes, rotation
how-to).

## Read the inventory first (vocabulary triggers)

Whenever a cloud operation is in play, read the matching inventory file *before*
running anything — never reconstruct IDs from memory.

| Context | Read first |
|---------|-----------|
| cloud CLI (`az`, `gcloud`, `aws`, `wrangler`, `gh api`, provider REST) | `identity/accounts/<provider>-<tenant>.yaml` (+ its README) |
| vault / keystore / secret / "rotate the key" | the account file's vault block + rotation README |
| tenant / subscription / project / resource-group op | the account file's ID + RG map |
| domain / DNS / registrar op | the registrar account file |

## Hard rules

- **Before ANY cloud op, read `identity/accounts/<provider>-<tenant>.yaml`** for
  the tenant/account ID, subscription/project, vault names, and bootstrap snippet.
  Never guess and never reconstruct from memory.
- **No raw secrets in YAML.** Reference only via URI —
  `azure-keyvault://…`, `keychain://…`, `1password://…`, or the equivalent for
  your store. Real values live in the vault/keystore.
- **Tenant/account switch is never a blocker.** Switching active
  subscription/project/tenant is a one-command operation; on an auth failure, try
  the documented switch first, then surface a concrete command to the user.
- **Tag on every new secret version.** When setting a new secret version, always
  pass the store's metadata (content-type, scope/created tags) — otherwise the
  metadata is lost. Keep the exact command in the account's rotation README.
- **Bootstrap from the file.** Each `<provider>-<tenant>.yaml` ships a ready-to-copy
  `bootstrap:` block — use it; don't reassemble the login/setup sequence by hand.

## Inventory

`ls identity/accounts/*.yaml` is the source of truth — one file per account.
Companion `<id>.README.md` files carry the decision matrix and setup/rotation
recipes for the more complex accounts. Schema and field conventions live in the
folder's `_template.yaml` and `_schema.yaml`.

On a **fresh clone** the folder holds only `_template.yaml` and `_schema.yaml` —
no account files yet. You add `<provider>-<tenant>.yaml` files as you onboard
accounts, so an empty `ls identity/accounts/*.yaml` result is expected, not a
broken setup.

> **Scope:** account files are tiered by ownership (who pays/owns), not by who
> logs in — org-owned/billed accounts are org scope (team-visible), purely
> personal accounts are user scope. Credentials for AD/IdP apps and any
> destructive or billing operation stay human-gated.
