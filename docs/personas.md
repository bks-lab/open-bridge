# Personas — Self-Identity Definitions

A persona represents an **identity the user holds**. It answers the
question *"which hat am I wearing right now?"* — freelancer, company
director, private citizen, client's project owner, etc.

Personas carry tax data, legal entity information, destination paths
for document filing, and signatures for outgoing correspondence. They
are read by skills and sub-agents (especially the `archivist`) to
route work to the correct legal context.

## Quick start

1. Check the examples: `docs/examples/personas/freelancer-example.yaml`
   and `docs/examples/personas/company-example.yaml`
2. Copy `identity/personas/_template.yaml` to `identity/personas/<your-id>.yaml` on
   your `user/*` branch (never commit personas to `main`)
3. Fill in your tax number, address, destinations, signature
4. Reference the persona from a routing context:
   ```yaml
   # workflow/contexts/<domain>.yaml — routing-rules SoT for a domain
   persona_ref: <your-id>
   # routing rules below reference destinations[<key>] from the persona
   ```

Your persona is now active whenever that context is loaded by a skill
(e.g. `doc-system` reading `workflow/contexts/doc-system.yaml`).

## Personas vs mandants — the core distinction

The Bridge has two similar-looking concepts. Keep them apart:

| | Persona | Mandant |
|---|---|---|
| **File location** | `identity/personas/<id>.yaml` | `identity/mandants/<id>.yaml` |
| **Represents** | An identity **the user holds** | A recipient **group the user addresses** |
| **`role:` field** | `self` (always) | not set / context-dependent |
| **Used by** | `document-intake`, invoice generation, signature blocks | `workflow/calendars/entries.yaml`, bridge-deck messaging tabs |
| **Answers** | "Under which legal entity do I file this?" | "To whom do I send this message?" |
| **Example** | "Me as freelancer" / "Me as UG CEO" | "My team at work" / "My family" |
| **bridge-deck** | Not rendered (role:self excluded) | Rendered as addressbook cards |
| **Tax data** | Yes (tax ID, VAT ID, advisor) | No |
| **Destinations** | Yes (filing paths) | No |

Short form: **personas are who I AM**, **mandants are who I SEND TO**.

A single real-world person can appear in both. For example, if you
have a company "Example UG" with you as CEO, you might have:

- `identity/personas/example-ug.yaml` → type:company, role:self, tax data
- `identity/mandants/<client>.yaml` → type:company, role:recipient, channels

The same physical email address can appear in both files — they
answer different questions.

## Types

| Type | Icon | Use case |
|------|------|----------|
| `individual` | 👤 | Natural person identity (freelancer, private citizen, sole proprietor) |
| `company` | 🏢 | Legal entity the user represents (Ltd., LLC, Inc., GmbH, UG, SA, …) |

## Schema

See `identity/personas/_template.yaml` for the full annotated schema. Key fields:

```yaml
schema_version: 1
id: <slug>                    # unique, matches filename without .yaml
type: individual | company
role: self                    # required, always "self"
display_name: "..."

persons:                      # one or more people representing this persona
  - id: primary
    display_name: "..."
    channels: { email: "...", phone: "..." }
    address: { street: "...", zip: "...", city: "...", country: "..." }

tax:                          # consumed by document-intake
  tax_id: "..."
  tax_office: "..."
  vat_id: "..."               # optional
  tax_advisor: { name: "...", location: "...", billing_agent: "..." }
  vehicle: { plate: "...", classification: "..." }   # optional

destinations:                 # keys referenced by name from routing rules
  <key>: "${onedrive_root}/..."   # in workflow/contexts/<id>.yaml

signature: |
  Multi-line signature block
  for outgoing correspondence

notes: |
  Free-text description
```

## How personas integrate with other Bridge concepts

### With contexts

A `workflow/contexts/<name>.yaml` can declare a persona it operates as:

```yaml
identity:
  name: my-workspace
persona_ref: example-freelancer
# ... rest of context ...
```

Skills and sub-agents that run in this context read `persona_ref` to
resolve tax data and destination paths. If no `persona_ref` is set,
anything that requires a persona raises a clear error with a link to
this documentation.

### With standing orders

A routing standing order can be scoped to a specific persona:

```markdown
---
name: routing-example-freelancer
scope: per-context
persona_ref: example-freelancer
enforcement: blocking
applies_to: [archivist]
---
# Document Routing — Example Freelancer
...
```

When the `archivist` runs, it loads routing rules matching the
active context's `persona_ref`. This prevents freelancer rules from
leaking into company filings (or vice-versa).

### With the archivist sub-agent

The `archivist` (`.claude/agents/archivist.md`) reads the active
persona via context chain:

1. Active context (from `bridge-config.yaml` or command argument)
2. Context declares `persona_ref`
3. Persona provides `tax` data + `destinations` map
4. Standing orders `routing-<persona-id>.md` provide classification rules
5. Documents are classified, named, and moved according to the matrix

### With the invoice-generation skill (future)

Personas carry `signature` and `tax` data used when composing outgoing
invoices. The invoice-generation skill (not yet built) will read
`identity/personas/<id>.yaml` to fill header + footer + VAT fields.

## Multiple personas for one user

Most users need between 1 and 4 personas. Create separate files when:

- You file taxes as multiple legal entities (freelancer + company)
- You have distinct signature lines per hat
- Documents must route to different folder hierarchies
- Your tax advisor treats you as multiple Mandanten

One persona is enough when:

- You are a sole proprietor with one tax context
- All documents land in the same folder structure
- You use a single signature for all correspondence

## Layer and Git discipline

Personas are **USER layer**. They contain personal data (tax IDs,
real addresses, signature blocks) and must never land on the CORE
(`main`) branch. The cherry-pick promote rules in
[`rules/operations.md`](../rules/operations.md) already block
`identity/personas/*` (except `identity/personas/_template.yaml` and
`docs/examples/personas/**` which are CORE).

| Path | Layer | Who commits |
|------|-------|-------------|
| `identity/personas/_template.yaml` | CORE | Bridge maintainers |
| `docs/examples/personas/**` | CORE | Bridge maintainers |
| `identity/personas/<real-id>.yaml` | USER | End user on `user/*` branch |

## Related docs

- [`mandants.md`](mandants.md) — Recipient groups for outgoing messages
- [`../rules/operations.md`](../rules/operations.md) — Path allowlist / blocklist for CORE/USER cherry-pick
- [`../rules/promote-safety.md`](../rules/promote-safety.md) — Content scan for promotes
