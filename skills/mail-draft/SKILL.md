---
name: mail-draft
description: >-
  Drafts outgoing email and never sends: Markdown to mail-safe HTML themed from
  DESIGN.md, footers from identity/mail-footers/, occasions from
  workflow/mail-profiles/, recipients from mandants, preflight checks; Apple
  Mail, Outlook or .eml. Trigger: "draft an email", "mail to", "email draft",
  "mail footer", "email signature", "mail profile".
metadata:
  scope: core
allowed-tools:
  - Bash(skills/mail-draft/mail-draft.sh:*)
  - Read
  - Write
---

# mail-draft

Builds a mail as a DRAFT in the person's mail client. The person reads it and
presses Send. There is no send command, not behind a flag, not in any client
module: a draft that is wrong costs a minute, a sent mail that is wrong cannot
be taken back. "Send X to Y" is a request for the finished draft.

Engine: `skills/mail-draft/mail-draft.sh` (Python, stdlib + PyYAML). Model and
every field: [`docs/mail-draft.md`](../../docs/mail-draft.md).

## What decides what

| Question | Answered by | Tier |
|---|---|---|
| Who signs, how to reach them | `identity/mail-footers/<id>.yaml` (borrows from a persona) | user / org |
| What occasion, which footer, greeting, attachments | `workflow/mail-profiles/<id>.yaml` | user / org |
| Who receives it, in which language, formal or not | `identity/mandants/<id>.yaml` (`mail_profile`, `defaults.language`, `defaults.address_form`) | user |
| Colours and type | `DESIGN.md` through the `design` theme | core / fork |
| Machine defaults (client, drafts folder) | `bridge-config.yaml` `mail:` | user |

CORE ships only the engine, the two `_schema.yaml` and the two `_template.yaml`.
Every real footer and profile is a USER file (or `org` when a team shares one
through an overlay), and the schema refuses `scope: core` for a footer.

## Decision tree

```
Request about mail
├── write / draft / "send" a mail ──────────► § Draft a mail
├── "how will X be addressed?" ─────────────► mail-draft.sh explain --to X
├── new footer / signature / profile ───────► § Set up
├── paste a signature into Outlook/Mail ────► mail-draft.sh signature <footer> --out <dir>
├── "is my mail setup ok?" ─────────────────► mail-draft.sh validate && mail-draft.sh list
└── "what can my mails look like?" ─────────► mail-draft.sh gallery --open
```

## Draft a mail

1. Resolve the recipient and occasion first: `mail-draft.sh explain --to <who>`.
   It prints the profile, footer, language, form of address and sender, each
   with the reason. If the profile names a `style_skill`, load that skill
   before writing the text.
2. Write the body as Markdown into a file (greeting and sign-off come from the
   profile; leave them out unless the text needs its own). Syntax: headings,
   lists, tables, `> [!NOTE]` alerts, `[[Button]](url)`, `[done]` badges,
   `{{snippet:<name>}}` from the profile.
3. Preview and show the person the text part in chat:
   `mail-draft.sh preview --to <who> --subject "<s>" --body-file <f> [--attach <file>]`
4. On their go: `mail-draft.sh compose ...` with the same arguments.
   Preflight errors stop it (missing attachment, leftover `{placeholder}`,
   required attachment absent). Warnings are printed for the person.
5. Report what the command printed: client, recipients, attachments, whether
   the Drafts folder counted it, and for Outlook that "From" must be switched
   by hand. Never claim a draft that was not verified.

Recipients: an address, `mandant:<id>`, `<mandant>/<person>`, a person id, or
a person's `nicknames` entry. A body may link `[text](site:home)` when the
profile or `mail.link_aliases` defines `site:home`.
Override anything per call: `--profile`, `--footer`/`--no-footer`,
`--footer-style`, `--theme`, `--lang`, `--informal`/`--formal`, `--client`.

## Set up

Read the matching `_template.yaml` and `_schema.yaml` first
([`rules/file-creation.md`](../../rules/file-creation.md)), then:

- a footer per way of signing: `identity/mail-footers/<id>.yaml`, `persona_ref`
  for name/email/phone, `style: card | compact | minimal | text`, `variants:`
  per language, `extends:` to build on a shared team footer
- a profile per occasion: `workflow/mail-profiles/<id>.yaml`, one `default: true`,
  `applies_to:` to be picked by mandant, mandant type or tag, `extends:` for
  variations, `variants:` for per-language wording
- on a mandant or person: `mail_profile: <id>` to pin an occasion
- finish with `mail-draft.sh validate` (CI runs it too), then
  `mail-draft.sh gallery --open` to see every profile side by side

## Gallery

`mail-draft.sh gallery [--out <dir>] [--body-file <f>] [--open]` renders one
sample mail per built-in theme and per profile, each with its footer, greeting
and theme, and writes a local overview page (light and dark) under
`<mail.drafts_dir>/gallery/`. It never touches a mail client. A profile that
cannot render is shown as a tile with the reason, not skipped.

## Clients

| client | draft | sender | notes |
|---|---|---|---|
| `apple-mail` | real draft, read back from Drafts (sender, attachments) | set from the footer, read back | default on macOS |
| `outlook` | open window; counted in Drafts where Outlook lets scripts see it | NOT settable, reported | no `--hide`; the new Outlook hides account folders from scripts, so its drafts read as unverified |
| `eml` | `.eml` with `X-Unsent: 1` | in the file | any OS; opens as a draft in Outlook and Thunderbird |
| `none` | only the bundle | n/a | for review or another tool |

Every run also writes a bundle (source, HTML, text, .eml, light/dark preview,
report) under `mail.drafts_dir`, by default `.bridge/mail-drafts/` (gitignored:
a draft holds addresses and private text).

## Never

- send, or add a code path that sends
- hand the body to osascript as an argument (it travels as a file); prefer
  `--body-file` over `--body` for anything longer than a line
- pick a colour in a footer or profile for your own brand (theme roles only)
- write a real footer or profile into CORE
