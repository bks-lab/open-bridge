---
summary: "Mail drafts: footers in identity/mail-footers/ (who signs, styles, language variants), occasions in workflow/mail-profiles/ (footer, theme, greeting, snippets, attachments, client, who it applies to), recipients from mandants; skills/mail-draft builds a draft in Apple Mail, Outlook or an .eml and never sends. Selection order, footer styles, theme roles, preflight checks, clients and their limits."
type: guide
last_updated: 2026-10-24
related:
  - ../skills/mail-draft/SKILL.md
  - ../identity/mail-footers/_schema.yaml
  - ../identity/mail-footers/_template.yaml
  - ../workflow/mail-profiles/_schema.yaml
  - ../workflow/mail-profiles/_template.yaml
  - mandants.md
  - personas.md
  - ../DESIGN.md
---

# Mail drafts

A mail has two parts that change at different speeds. The message changes
every time. Everything around it (who signs, how the person is greeted, which
colours, what is attached, which client gets it) depends on the OCCASION and
the RECIPIENT, and repeats. The Bridge keeps that second part in files, so an
agent writes only the message, and the same request produces the same dress
every time.

Nothing here sends. `skills/mail-draft` creates a draft; the person presses Send.

## Three families, three questions

| File | Question | Typical count |
|---|---|---|
| `identity/mail-footers/<id>.yaml` | Who signs, and how is that shown? | one per way of signing: full, compact, per company |
| `workflow/mail-profiles/<id>.yaml` | What occasion is this? | one per occasion: everyday, application, status report, family |
| `identity/mandants/<id>.yaml` | Who receives it? | already there; three optional fields added |

All three are USER files. A footer or profile a whole team uses is `scope: org`
and ships through the org overlay; a member `extends` the shared footer with
their own name. CORE holds only `_schema.yaml` and `_template.yaml` for the two
new families, and the engine. A footer can never be `scope: core`: it holds a
name, a phone number and an address.

## Footers

```yaml
schema_version: 1
scope: user
id: contact
persona_ref: alex            # name, email, phone come from identity/personas/alex.yaml
style: card                  # card | compact | minimal | text
role: "Independent consultant"
org: "Example Studio"
website: "https://example.com"
wordmark: {top: "EX", bottom: "STUDIO"}
links:   [{badge: "in", label: "LinkedIn", url: "https://...", color: "#0A66C2"}]
cards:   [{kicker: "Portfolio", title: "Recent work", text: "...", url: "https://..."}]
cta:     {label: "Book a call", url: "https://..."}
notice:  {text: "Away until 14 August.", from: 2026-07-25, until: 2026-08-14}
tagline: {lead: "Currently:", name: "a tool", text: "...", url: "https://..."}
legal:   ["Example Studio · 1 Example Street · VAT XX000"]
variants:
  de: {role: "...", tagline: {...}}
```

| Block | What it is |
|---|---|
| `wordmark` | a two-line text logo. Text, never an image: Outlook blocks remote images and some clients show embedded ones as attachments |
| `links` | small coloured badges with a label. A hex colour only for someone else's brand; your own colours are theme roles (`primary`, `link`, ...) so they follow DESIGN.md |
| `cards` | tiles with a link; two share a row, `wide: true` takes one |
| `cta` | one button that also renders in desktop Outlook (VML) |
| `notice` | a dated line, left out outside its `from`/`until` window, so a stale "away until" never reaches anyone |
| `tagline` | one line under a rule |
| `legal` | small print, one line each |
| `visitor_params` | `{visitor_query}` in a URL becomes `?for=<first name>` so the page it opens can greet the reader; only a plain name ever goes in |

**Styles** render the same data at different weights: `card` everything,
`compact` two lines plus badges and legal (replies), `minimal` two lines
(lists), `text` the text rendering in the HTML part too.

**Inheritance**: `extends: <footer>` starts from another footer; fields here
win, lists replace. **Language**: `variants.<lang>` holds only what changes,
and is picked by the recipient's language.

## Profiles

```yaml
schema_version: 1
scope: user
id: application
extends: everyday
footer: contact
footer_style: card
masthead: true
eyebrow: "Application"
address_form: formal
subject: "Application: {subject}"
greeting: {formal: "Dear {name},", fallback: "Hello,"}
sign_off: {formal: "Kind regards,\n{sender_name}"}
snippets: {availability: "I am available from **1 November**."}
attachments: ["~/Documents/cv.pdf"]
require: {attachments: true}
applies_to: {types: [company]}
variants:
  de: {subject: "...", greeting: {...}, sign_off: {...}}
```

Placeholders in `subject`, `greeting`, `sign_off`, `preheader`:
`{first_name} {last_name} {name} {group} {sender_name} {sender_first_name} {subject} {date}`.
A greeting is not added when the body already opens with one of
`greeting_words` as a whole word; a sign-off is not added when one of the
body's last three lines starts like the profile's closing line or names the
sender. A body pulls a snippet in with `{{snippet:<name>}}`.

### Which profile a draft gets

First match wins:

1. `--profile <id>`
2. the recipient person's `mail_profile`
3. the recipient mandant's `mail_profile`
4. a profile whose `applies_to` names the mandant, then its type, then a tag
5. `bridge-config.yaml` `mail.default_profile`, then the profile with `default: true`
6. a built-in neutral profile

With several recipients the first one decides. `mail-draft.sh explain --to <who>`
prints the decision and the reason for each part of it.

Language: `--lang`, then the person's `defaults.language`, then the mandant's
`language`, then the profile's `language`, then `mail.language`. Form of
address: `--formal`/`--informal`, then the person's `defaults.address_form`,
then the mandant's `address_form`, then the profile's.

Two profiles whose `applies_to` claim the same mandant, type or tag are
reported by `validate`: only the first by name would ever be picked.

### Section headings and short links

`heading_styles` dresses a `##` heading by its words, so a status mail does not
need alert syntax for its two recurring sections:

```yaml
heading_styles:
  callout: [Summary, Overview]     # accent fill, like a `>` quote
  warning: [Blocked, Critical]     # warning edge, like `> [!WARNING]`
```

`link_aliases` lets a body write `[our site](site:home)`:

```yaml
link_aliases:
  "site:home": "https://example.com/"
  "site:contact": "https://example.com/contact"
```

Both merge over the same keys in `bridge-config.yaml` `mail:`, the profile
winning per key. A target shaped like an alias that no map defines stops the
draft, and an alias may only point at an http(s), mailto or tel URL.

`heading_styles: false` in a profile switches the dressed headings off for that
occasion, including the words in `mail.heading_styles`; an empty map cannot,
because it merges over them. A profile that `extends` it may switch them back
on with its own map. The `plain` theme never dresses a heading in the first
place, so a plain profile needs no `false`.

## Mandants

Optional fields, all read-only for this skill (`groups` below):

```yaml
mail_profile: family              # on the mandant: everyone here gets this occasion
language: de                      # on the mandant: the group's default language
address_form: informal            # on the mandant: the group's default form of address
persons:
  - id: sam
    nicknames: [sammy]            # `--to sammy` works too; an id always wins
    mail_profile: everyday        # on one person: wins over the mandant
    defaults:
      language: de                # picks footer and profile variants
      address_form: informal      # picks the informal greeting and visitor parameter
groups:
  leads: [sam]                    # `--to mandant:family#leads` reaches only these ids
```

A group is a named list of person ids on the mandant, not a tag on each person.
The list says in one place who a group mail reaches, which is what a sender
checks before writing to it, and a member that is no person of the mandant is
an error in `validate` and at draft time. Tags spread over persons would fail
quietly: a misspelt tag just leaves someone out. `mandant:<id>` without a group
still reaches everyone with an email.

## Theme

`design` reads `DESIGN.md`'s frontmatter and maps tokens to roles. Each role
takes the first candidate token that exists AND is readable (4.5:1 on the
card); a link colour that is too light for 15px text is skipped for the next
candidate, and when no candidate is readable the first one is darkened until
it is, and `mail-draft.sh explain` says so. Dark mode uses `colorsDark` (or `dark-*`
tokens), never an inversion. No webfont is ever loaded.

| Role | Candidates |
|---|---|
| `link` | link, accent, secondary, info |
| `text` / `text_muted` | on-surface / on-surface-muted |
| `bg` / `card_bg` / `muted_bg` | surface / surface-raised / surface-muted |
| `primary`, `success`, `info`, `warning`, `danger` | same names |

`tokens:` in a profile (or `mail.tokens`) pins a role: `{link: secondary}`.
`minimal` and `plain` ignore DESIGN.md: they are for recipients for whom a
designed mail would be wrong, not lesser versions of it.

## Preflight

Errors stop the draft (`--force` overrides): an attachment that does not
exist, a required attachment missing, attachments over 25 MB, a `{placeholder}`
left in the text, an unknown snippet, an empty subject, a `file://` link, CSS
variables copied from a browser.

Warnings are printed for the person: an attachment promised in the text
(`attachment_words`) but none attached, link text naming one host while the
link goes to another, tracking parameters, remote images, a footer notice out
of its window, a missing language variant, Outlook's sender, the profile's
`style_skill`.

## Clients

| `client` | Result | Sender | Limits |
|---|---|---|---|
| `apple-mail` | a real draft, read back from Drafts: sender and attachments as saved | set from the footer's `sender`/`email`, read back | needs a Mail account with that address; gets the HTML without dark-mode rules (below) |
| `outlook` | an open compose window; counted in Drafts where scripts can see the folder | Outlook's default account | no `--hide` (without a window Outlook stores nothing); the new Outlook shows scripts only its local folders, not the account's Drafts, so the draft is reported as an open, unverified window; the sender cannot be set by script |
| `eml` | a `.eml` with `X-Unsent: 1` | in the file | Outlook and Thunderbird open it as a draft; Apple Mail opens it read-only |
| `none` | only the bundle | | for review or another tool |

Apple Mail converts the HTML into its own format when the draft is created,
rendering it once under the Mac's CURRENT appearance and keeping the computed
colours. With dark-mode rules in the HTML, a Mac in dark mode froze pale text
into the draft, which a recipient reading in light mode would see as grey on
white. So Apple Mail gets the same mail without dark-mode rules (the recipient's
client still applies its own dark handling); `outlook`, `eml` and the preview
keep them. Mail also accepts any sender without an error and keeps its default
account when none has that address, so the sender, like the attachments, is
read back from the saved draft, and the report says what is really in it. On an
Exchange account Mail sometimes keeps both its own autosave of the new window
and the explicit save; when one run adds more than one draft with its subject,
the older copies created during that run are removed, never an older draft.

Footer values are not trusted at compose time either: a link that is not
http(s), mailto or tel becomes `#` and stops the draft, a badge colour that is
not a hex code or a token falls back to `primary`, and the footer and profile in
use are schema-checked on every draft, not only by `validate`.

The body travels to the mail client as a file, never as an osascript argument: a
long body in argv once made a client create nothing while the script reported
success. A draft counts only when the Drafts folder counts it from a fresh
process, because a message that is only an open window disappears with the
next restart.

## Replies

`compose --reply-to <ref>` answers an existing message in Apple Mail. `<ref>` is
a Message-ID (`<id@host>` or `id@host`, searched in the inbox, then in every
mailbox) or words of a subject (the newest inbox match; the run names it and
how many matched). Without `--to` and `--subject` the reply goes to the
original's sender with `Re: <subject>`; the profile's `subject` template is not
applied and there is no masthead, so the thread stays intact. `--reply-all`
answers every recipient. Nothing is ever sent.

A reply cannot be built the way a new draft is, measured on real replies:
setting the reply's content replaces the quote, and `make new attachment ... at
after the last paragraph of content` deleted the inserted text together with the
quote. So the HTML body with its footer is put on the clipboard and pasted
above the quote, then each file is pasted the same way (`set the clipboard to
(POSIX file ...)`). A paste lands wherever the focus is, so before every paste
the run checks that Mail is the frontmost app and the reply is its front
window; if not, it closes the reply without saving and reports that nothing was
saved, rather than leaving half a reply. The person's clipboard is restored
afterwards when it held text.

Afterwards the saved draft is read from Drafts and must contain the text, the
footer (its name), the quote of the original and every attachment; anything
missing is reported by name and the run fails. Plain new drafts are not
affected by any of this.

`outlook`, `eml` and `none` refuse a reply by name, before anything is created:
Outlook for Mac offers scripts no reliable way to answer with the quote and
attachments intact, and an .eml cannot carry a quote that lives in the mail
client.

## Machine defaults

```yaml
# bridge-config.yaml
mail:
  client: apple-mail           # apple-mail | outlook | eml | none
  default_profile: everyday
  language: en                 # language of footers and profiles without a suffix
  drafts_dir: .bridge/mail-drafts
  labels: {done: "DONE"}       # badge and alert labels in your language
  attachment_words: ["attached", "enclosed"]
```

## Commands

```
mail-draft.sh compose   --to <who> --subject <s> --body-file <f> [--attach f] [--profile p] [--client c]
mail-draft.sh compose   --reply-to <message-id|subject> --body-file <f> [--attach f] [--reply-all]
mail-draft.sh preview   ...same...   [--open]       light/dark page + text part, no client
mail-draft.sh check     ...same...                  preflight only
mail-draft.sh explain   --to <who> [--profile p]    which profile/footer/language, and why
mail-draft.sh signature <footer> [--lang] [--style] [--out dir]
mail-draft.sh list                                  footers, profiles, mandant mappings
mail-draft.sh validate                              schemas and every reference between files
mail-draft.sh verify    --client c --subject s      count drafts in the Drafts folder
mail-draft.sh gallery   [--out dir] [--body-file f] [--open]   every theme and profile on one page
```

## Gallery

`gallery` answers "what can my mails look like?". It renders the same sample
text once per built-in theme (`design`, `minimal`, `plain`) and once per
profile, as a draft for a placeholder reader would be built (footer, greeting,
sign-off, theme, masthead), and writes `index.html` with one tile per result:
name, purpose, theme, footer, client, sender, and the mail in light and dark.
The files land in `<mail.drafts_dir>/gallery/` unless `--out` says otherwise;
the drafts directory is gitignored because a rendered footer carries contact
data. No mail client is involved and nothing is sent. `--body-file` swaps the
sample for your own text, for example one in your language.
