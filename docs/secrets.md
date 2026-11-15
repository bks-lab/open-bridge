---
summary: "Secrets in a Bridge: files carry reference URIs, never values; the secrets skill resolves a reference for the program that needs it, says where a new secret belongs, and finds plaintext that should have been a reference."
type: guide
last_updated: 2026-11-15
related:
  - ../rules/secret-placement.md
  - ../skills/secrets/SKILL.md
  - ../infra/secret-stores/_template.yaml
  - cloud-accounts.md
---

# Secrets

A Bridge is a git repo your agent reads, so the rule is simple: **no secret value
ever sits in a tracked file.** Files carry a *reference*, a URI that says where
the value lives. The value stays in your vault or keychain, and a leak of the
file leaks a pointer, not a credential.

Three pieces make that hold:

| Piece | Owns |
|---|---|
| [`rules/secret-placement.md`](../rules/secret-placement.md) | the reference grammar (which URI schemes exist) and the naming hierarchy inside a vault. It is the source of truth |
| [`infra/secret-stores/`](../infra/secret-stores/_template.yaml) | one declaration per store: where it is, who can read it from where, and which kinds of secret belong in it |
| [`skills/secrets/`](../skills/secrets/SKILL.md) | the tool that resolves, stores, places and audits, without ever printing a value |

## Reference URIs

A reference is a locator. Parsing it is safe, printing it is safe, committing it
is the point.

| Backend | URI format |
|---|---|
| Azure Key Vault | `azure-keyvault://<vault>/<secret-name>` |
| macOS Keychain | `keychain://<service>[/<account>]` |
| 1Password | `1password://<vault>/<item>/<field>` (the CLI spelling `op://` is accepted on input) |
| KeePass | `keepass://<db>/<group-path>/<entry>/<field>` |
| HashiCorp Vault | `vault://<mount>/<path>/<field>` |
| File | `file://<absolute-path>`, mode 0600, inside a declared store |

The rule file has the details (default fields, the logical KeePass database
name, when `file://` is the right fallback). `scripts/check-secret-grammar.py`
fails CI when any machine-readable copy of this list drifts from the rule.

Inside a vault, secrets are grouped owner org first, then customer or service,
then role: `<org>/<customer-or-service>/<role>`. One item holds one credential,
and a customer's secrets never share a group with another's.

## Where a new secret goes

An agent handed a new token used to decide for itself where to keep it. The
answer is now declared once, in `infra/secret-stores/*.yaml`: each store lists
the **kinds** it holds. The kinds are a closed list: `personal-token`,
`org-credential`, `customer-credential`, `service-runtime`, `ci-secret`,
`household-shared`, `break-glass`.

Store declarations are machine and tenant inventory, so they are `scope: user`
(or private) and never promoted. CORE ships only the template and the schema.

Personal data is deliberately not a kind. An IBAN or a tax id identifies a
person rather than authenticating one, so it belongs where it is used, not in a
vault.

Identifiers count as secrets too, when a scanner flags them. An AWS access key
ID is the ID half of a key pair: it goes into a file as a reference, never as a
field value. See
[`rules/secret-placement.md` § What counts as a secret](../rules/secret-placement.md#what-counts-as-a-secret).

## What the secrets skill does

In Claude Code, `/secrets`; the engine is `skills/secrets/secrets.sh`. No
command prints a value. What it reports about a secret is its reference, its
length in bytes, and the first eight hex characters of its sha256: enough to
tell two tokens apart and to see that a rotation landed, not enough to use one.

| Verb | Does |
|---|---|
| `refs` | every reference in the tree, with file and line |
| `check` | resolves each reference and reports status, bytes and fingerprint |
| `run --env NAME=REF -- cmd` | hands the value to a child process, and scrubs it from what comes back |
| `where [kind]` | which declared store a new secret of that kind belongs in |
| `store REF` | writes a value into that store (from stdin, clipboard or a prompt, never argv), then reads it back to prove it |
| `stores` | lists the declared stores and what is wrong with them |
| `audit` | finds plaintext that should have been a reference, and personal data lying in the tree |

Two distinctions the skill makes because each one once failed silently:

- **An empty entry is a miss.** Some backends exit 0 for an entry holding zero
  bytes, so the measurement is length, not existence.
- **"Not readable here" is not "missing".** A login keychain answers in a
  desktop session and refuses over ssh. The skill reports that as a session
  problem (exit 69), not as a lost secret (exit 3).

The full contract, including every exit code: [`skills/secrets/SKILL.md`](../skills/secrets/SKILL.md).

## Related

- Cloud account inventory, which holds references to its credentials:
  [cloud-accounts.md](cloud-accounts.md).
- Workload declarations carry references too; the program resolves them at run
  time, and a resolved value is never written into a unit file:
  [workloads.md](workloads.md).
