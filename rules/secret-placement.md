---
scope: core
description: Secret-reference URI formats and the folder/group hierarchy secrets live in (1Password, KeePass, Key Vault, Keychain) — how identity/accounts/*.yaml resolve to real vault locations
---
# Secret Placement & Reference URIs

`identity/accounts/*.yaml` never hold raw secrets — only **reference URIs** that
point at where the credential actually lives. This rule fixes (a) the URI format
per backend and (b) the folder/group hierarchy, so a reference resolves
deterministically and a human finds the secret in the vault without guessing.

## Supported schemes & URI format

This table is the SOURCE. Four other places carry the same list in machine
form: the `secrets` skill, the overlay leak check, the workload engine and the
workload schema. `scripts/check-secret-grammar.py` fails CI when any of them
drifts from this table. Before that check existed they already had drifted:
three of the four disagreed with each other, and a fifth scheme sat in the
account template that no list defined at all.

| Backend | URI format | Resolves to |
|---|---|---|
| Azure Key Vault | `azure-keyvault://<vault>/<secret-name>` | secret in that vault |
| macOS Keychain | `keychain://<service>[/<account>]` | generic-password item |
| 1Password | `1password://<vault>/<item>/<field>` | one field of one item |
| 1Password, CLI spelling | `op://<vault>/<item>/<field>` | alias of the row above, accepted on input |
| KeePass (.kdbx) | `keepass://<db>/<group-path>/<entry>/<field>` | one field of one entry |
| HashiCorp Vault | `vault://<mount>/<path>/<field>` | one field of one KV secret |
| File | `file://<absolute-path>` | a file with mode 0600 inside a declared store |

- `<field>` defaults to `password` if omitted, and to `value` for `vault://`.
  The LAST segment is the field. Write `#field` at the end when an entry name
  would otherwise be read as one.
- `<db>` for KeePass is the logical database name (e.g. `personal`, `<org>`),
  never a filesystem path: where a database lives is a property of the machine,
  not of the reference. The `secrets` skill takes that mapping with
  `--db <name>=/path/to.kdbx`. An earlier version of this rule promised the key
  `secrets.keepass.<db>.path` in `bridge-config.yaml`; nothing ever read it, so
  the promise is withdrawn rather than left standing.
- `<group-path>` is slash-separated KeePass groups, e.g. `<org>/<customer>`.
- `file://` is the fallback for a machine with no keychain and no agent, a
  systemd service on a Linux box being the usual case. It is a locator like the
  others, and it is the only one a careless reader can follow to the value, so
  it belongs in a declared store and at mode 0600.

## Folder / group hierarchy (the placement convention)

Group secrets **by owner-org first, then by service/customer, then by role** —
the same axis the Bridge uses for scope. This keeps one customer's secrets in one
subtree and makes access-scoping and rotation reviewable.

```
<org>/<customer-or-service>/<role>
```

Examples (1Password vault `<ORG>` / KeePass group path):
```
<org>/<customer>/azure-sp-outbound   → 1password://<ORG>/<customer>-azure-sp-outbound/password
<org>/<customer>/storage-api         → keepass://<org>/<ORG>/<customer>/storage-api/password
<org>/_org/cloudflare-token          → 1password://<ORG>/cloudflare-token/credential
<org>/<service>/hf-token             → keepass://personal/<org>/<service>/hf-token/token
```

Rules:
- **One item = one credential.** Don't stuff multiple services in one item; the
  URI addresses a single field.
- **Org/customer isolation.** A customer's secrets live under `<org>/<customer>/…`
  only — never mixed into a shared/root group. This mirrors the data-isolation
  boundary (docs/multi-instance.md): a per-customer Bridge instance references only
  its own subtree.
- **Namespaced entry names.** Prefix the entry with the customer when the vault is
  flat (1Password vaults have no nested groups): `<customer>-azure-sp-outbound`,
  not `azure-sp`.
- **Reference must resolve.** The `<vault>/<group-path>/<entry>` in the URI must
  match the real location. If you move a secret, update the account file's URI.

## Retrieval

**Resolution goes through the `secrets` skill** (`skills/secrets/`), not through
a hand-written call per site. Before it existed, this rule named the backend
tools and every caller wrote its own invocation: one instance carried 72 inline
keychain reads, each of them its own small decision about quoting, emptiness and
what an error means.

```bash
skills/secrets/secrets.sh refs                        # every reference in the tree, and where it is written
skills/secrets/secrets.sh check --all                 # resolve each one and measure the value
skills/secrets/secrets.sh run --env TOKEN=<uri> -- cmd   # hand it to a child process, nothing else
```

No command prints a value. `check` reports length and the first eight hex
characters of the sha256, which is enough to tell two live tokens apart and to
compare one machine's copy with another's. `run` puts the value in the child's
environment, captures what the child writes, and replaces the value (and its
base64, hex, percent and JSON encodings) before that output reaches the caller.

Three distinctions the skill makes, because each one was once a silent failure:

- **An empty entry is a miss.** `security find-generic-password` exits 0 for an
  item holding zero bytes, so existence is not the measurement; length is.
- **"Not readable here" is not "missing".** An ssh session has no unlocked login
  keychain. The entry may be perfectly fine. Exit code 69 says so, and 3 means
  the entry really is gone.
- **A value never travels in argv.** Anything on a command line is visible in
  `ps` to every process of the same user. The tools take the value on stdin:
  `security -i` reads whole command lines there, and `keepassxc-cli` takes the
  master password the same way.

Storing a new secret (`store`), finding plaintext that should have been a
reference (`audit`), and the per-kind placement policy (`where`) ship in the
`secrets` skill ([`skills/secrets/SKILL.md`](../skills/secrets/SKILL.md)). The
convention below is what those verbs follow.

## What counts as a secret

Anything a secret scanner flags in a tracked file is a secret, whether or not it
works on its own. That includes the identifier half of a credential: an AWS
access key ID (`AKIA` or `ASIA` plus sixteen characters) cannot sign a request
alone, yet it names the account to attack and every scanner reports it. The
same goes for the other shapes in `skills/secrets/engine/patterns.py`, which
`secrets.sh audit` runs over the tree.

- Such a value goes only as a reference URI, in the place you were about to
  paste it: `access_key_ref: <reference URI>`, never `access_key_id: <value>`.
- "It is only the ID", "it is revoked" and "it is the documented example key"
  are not exemptions. A fixture that must carry one assembles it at run time or
  ends the line with `# pragma: allowlist secret`.
- Not a secret: a tenant, subscription or account number, an IBAN, a customer
  number. They locate or identify and unlock nothing, so the scanner does not
  flag them and they stay where they are used.
- A value that was committed is rotated. Deleting it from the tree does not
  un-leak a clone.

## Hard rules

- Raw secret values never appear in any repo file, commit, log, or artifact.
- A credential identifier the scanner flags (an access key ID, a token prefix) is a raw
  secret for this rule.
- The account YAML is `scope: user`/`org`; the shipped `.gitignore` ignores it by default, and
  a private origin re-allows it (`scripts/user-data.py arm`) and tracks it with the rest of
  your commits. Either way it holds **only** the URI, never the value, so a leak of the file
  leaks a pointer, not a credential.
- A staged credential in an account YAML (or any instance file) is refused at commit time
  regardless of scope: `scripts/hooks/pre-commit` runs `scripts/user-data.py scan-staged`
  against the index, so the backup a private instance now commits can never become the leak.
- Rotation updates the vault; the URI (and thus the account file) usually stays
  unchanged. If the entry is renamed/moved, update the URI in the same change.
