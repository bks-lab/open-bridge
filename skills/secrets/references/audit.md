# audit: plaintext that should have been a reference

The scan side. Read this when a report named something and the next step is not
obvious, before believing a clean run, when a pattern has to be added or
changed, or when a fixture has to look like a token and the scanner keeps
finding it.

The read side is [`resolve.md`](resolve.md), the write side is
[`store.md`](store.md). Those two are about references that exist. This one is
about the values that never became one.

Nothing here prints a value. The runs below are real, against a throwaway tree
and a throwaway keychain, and the tokens in them were generated for the run and
thrown away with it. Paths are written in a neutral shape, because a worked
example that carries somebody's home directory teaches the wrong habit twice.

## Where this started

Not with a theory about scanners. A maintainer copied an instance of this Bridge
onto a second machine and found small text files holding tokens and credentials
in working folders and temp directories, on both machines. They were not
committed, so no promote scan had ever looked at them, and they were not
referenced, so `refs` and `check` did not know they existed. They were there
because an agent handed a secret had nowhere declared to put it and chose for
itself.

Two verbs came out of that. `where` answers the question before the value is
written down, and `audit` finds what was written down before anybody asked. The
second one only pays for itself if it also scans OUTSIDE the repo, which is what
`--also` is for.

## One list instead of three

Before this slice the repo carried three sets of patterns for the same job, and
each knew something the others did not. Measured on 2026-09-20:

| Copy | Did not know |
|---|---|
| the table in `rules/promote-safety.md` | `AIza`, `github_pat_` |
| `RAW_SECRET_PATTERNS` in `scripts/overlay.py` | `AIza`, `github_pat_`, `Bearer ` |
| a third list in an instance-only rule | nothing the others knew, and it never reached CORE |

The instance one was the only list that knew about personal data, which is also
the reason it was never right to merge them blindly: an IBAN is not a
credential, and a promote scan is not where that question gets decided.

`engine/patterns.py` is now the source, and every entry declares which of the
other copies has to carry it.

### The list

| Pattern | Marker | Kind | Belongs in | Carried by |
|---|---|---|---|---|
| `private-key` | `BEGIN` | credential | service-runtime | overlay, promote |
| `ssh-public-with-key` | `ssh-rsa` | credential | personal-token | promote |
| `aws-access-key` | `AKIA` | credential | org-credential | overlay, promote |
| `aws-temp-key` | `ASIA` | credential | org-credential | overlay, promote |
| `github-token` | `ghp_` | credential | personal-token | overlay, promote |
| `github-fine-grained` | `github_pat_` | credential | personal-token | overlay, promote |
| `slack-token` | `xox` | credential | org-credential | overlay, promote |
| `openai-style-key` | `sk-` | credential | personal-token | overlay, promote |
| `google-api-key` | `AIza` | credential | org-credential | overlay, promote |
| `jwt` | `eyJ` | credential | service-runtime | overlay, promote |
| `azure-account-key` | `AccountKey=` | credential | org-credential | overlay, promote |
| `bearer-token` | `Bearer ` | credential | service-runtime | overlay, promote |
| `password-assignment` | `password` | credential | asks, see below | neither |
| `iban` | `IBAN` | pii | nothing, deliberately | neither |
| `german-tax-id` | `Steuer` | pii | nothing, deliberately | neither |

A public key is in the list on purpose, and not because it is secret. It is not.
It is there because it usually travels with the private one, and a tree that
carries the public half is worth a second look at the folder it sits in.

An access key ID is in the list on purpose too: the ID half of a key pair is a
credential for this skill, even though it cannot sign a request alone
([`rules/secret-placement.md` § What counts as a secret](../../../rules/secret-placement.md#what-counts-as-a-secret)).

The two marked "neither" in the last column are the ones that belong to this
skill alone. The overlay scan runs over CODE and deliberately does not run the
key-and-value heuristic there, where it is wrong more often than right; and
personal data is reported where it lies rather than gated on a promote.

### Shape is not evidence

`password-assignment` is the only pattern whose match is not evidence by itself,
and it is also the one that catches what no vendor prefix does: the line a person
wrote by hand. `token = request.headers["authorization"]` and `token = "<a real
value>"` are the same shape. Measured over this repo, the shape alone produced
106 findings and 5 of them were real.

So that entry carries a second question, `confirm`, which looks at the VALUE:
shorter than twelve characters, or carrying a bracket, a dollar, a brace or a
space, or reading as a dotted path, or containing one of the stand-in words
(`example`, `redacted`, `changeme`, `dummy`, `fixture`, `your-`), and the match
is dropped. What survives mixes at least two character classes and looks
opaque. A scanner whose report has to be skimmed is a scanner whose real hit
gets skimmed too, which is the failure this guards against.

### A finding is a location, never a value

`excerpt()` caps what a report may quote at eight characters plus an ellipsis.
That is enough to find the hit in the file and not enough to use.

The rule has a scar behind it: a verify pass in this repo once decoded a base64
credential into the transcript while checking whether the credential was really
there, which materialised the secret in the log that existed to protect it. The
same reasoning runs through the whole skill, and it applies hardest here, because
an audit report is the one output people paste into a ticket.

## The three copies, and what holds them together

The copies are deliberate, not duplication nobody cleaned up:

| Copy | Why it cannot just call the skill |
|---|---|
| `skills/secrets/engine/patterns.py` | the source. The skill imports nothing outside its own directory, because the directory has to keep working when it is copied out alone |
| `scripts/overlay.py` (`RAW_SECRET_PATTERNS`) | refuses to write a raw secret into a file an overlay consumer receives, inside a script that runs without the skill |
| `rules/promote-safety.md` | prose with a table, read by whoever, or whatever, reviews a promote. Its reader is sometimes a person |

`scripts/check-secret-patterns.py` holds the three to one list. It compares by
MARKER, never by regular expression: two scanners may spell the same shape
differently and both be right, and what matters is that neither is blind to a
shape the other knows. A pattern's `aliases` cover the spellings that count as
the same thing, because `gh[pousr]_` in a regex IS `ghp_` plus its siblings, and
a comparison that demanded the literal would report a gap where there is none.

### What the check prints

```
$ python3 scripts/check-secret-patterns.py
source   15  BEGIN ssh-rsa AKIA ASIA ghp_ github_pat_ xox sk- AIza eyJ AccountKey= Bearer  password IBAN Steuer
overlay  11  BEGIN AKIA ASIA ghp_ github_pat_ xox sk- AIza eyJ AccountKey= Bearer
promote  12  BEGIN ssh-rsa AKIA ASIA ghp_ github_pat_ xox sk- AIza eyJ AccountKey= Bearer

every copy carries the patterns skills/secrets/engine/patterns.py declares for it
$ echo $?
0
```

What it compares is the TABLE in the promote rule. That rule carries the list a
second time, as the `$UNIVERSAL` alternation in the pre-commit recipe further
down, which is the form somebody actually runs, and measured on 2026-09-20 the
recipe knew five shapes fewer than the table above it: `ssh-rsa`,
`github_pat_`, `AIza`, `eyJ` and `Bearer `. A promote scanned with the
documented one-liner therefore walks past a fine-grained GitHub token, a Google
API key and a pasted JWT while the table in the same file says all three are
never CORE appropriate. That gap is held open by a red case named after it in
`scripts/tests/test_secret_patterns.py` rather than quietly patched, because the
recipe is what a reader copies.

A gap is reported with the pattern's own note, so the message says what walks
past rather than only that a string is absent:

```
scripts/overlay.py: does not know google-api-key ('AIza'). known to the instance
rule and to neither of the two CORE scans
```

### The mutation pass

`--mutate` softens one literal in one copy at a time and demands that the check
goes red for it:

```
$ python3 scripts/check-secret-patterns.py --mutate
red   the overlay scan loses the Google key
red   the overlay scan loses the fine-grained GitHub token
red   the promote table loses the AWS key

3 needles, 3 bit
```

This exists because the extractor is the fragile part, not the comparison. The
first version of `overlay_block()` matched non-greedily to the first `]`, which
stops inside `[A-Z ]*PRIVATE KEY`: it reported one pattern where there are
eight, and the check was green where it should have been loud. A comparison over
an empty block is green for the same reason a correct one is, and the mutation
pass is what tells those apart. Each needle is written to the file and the
original is written back in a `finally`, so a crash mid-run does not leave a
softened scanner behind.

## The pragma, for a fixture that has to look like a token

A line that declares itself is skipped:

```
# pragma: allowlist secret
```

Spelled exactly the way `detect-secrets` spells it, so one convention covers
both tools rather than each tool having its own comment.

The contract is the whole value of it: a synthetic fixture carries the pragma, a
real credential never does. That makes the exceptions countable. `grep -c
'allowlist secret'` over a tree answers "how many lines claim to be fixtures",
and a number that grows without a reason is itself a finding.

Two rules of use:

- **It silences the LINE, not the file.** There is no file-level or
  directory-level form on purpose. A blanket exemption is indistinguishable from
  nobody having looked.
- **Prefer not needing it.** In this skill's own suite every token-shaped string
  is built at runtime from a prefix (`synthetic_token` in `tests/conftest.py`),
  so the literal worth copying does not exist in the first place. The pragma is
  for what is left over, such as a class name that happens to be a long run of
  mixed case and digits.

There is an irony to live with here: this suite is about a scanner, so it is
full of strings that look like secrets, and the scanner runs over the repo
including those files. In prose the cheaper way out is usually to stay under the
pattern's own threshold. `ghp_` followed by a placeholder in angle brackets is
not a match, and an IBAN written as two groups instead of five is not one
either, which is why the examples in this file are shaped the way they are.

## `--also`: the places that are not in any repo

Inside `--root` the scan reads the TRACKED set of the git tree, because that is
what ships and because the walk otherwise drowns in build output. That is also
exactly why it is not enough: the loose token files that started this were never
tracked, and several were not even inside a repo.

```
$ secrets audit --also ~/.config --also /tmp/handover
```

Three things to know about an extra root:

- It is WALKED, not asked of git. Everything readable under it is read, minus
  the directories nobody wants scanned (`.git`, `node_modules`, `__pycache__`,
  virtualenvs, build output).
- Its findings are reported with an ABSOLUTE path, while findings inside the
  tree stay relative to it. That asymmetry is deliberate: a path outside the
  repo is only useful if it is complete.
- The scan is read-only. `audit` never moves, rewrites or deletes anything, and
  there is no `--fix`. What to do with a found value is a decision with a
  rotation attached, and `store` is the verb that makes it.

A symlink is skipped rather than followed, so pointing `--also` at a folder full
of links into the repo does not produce the same file twice under two names.

**Name a DIRECTORY, not a file.** A single file is accepted on the command line
and then read by nobody: the extra root is walked, and a walk over a file yields
nothing, so the scan reports one clean root that it never opened. That is the
worst shape a scanner can fail in, silently and green, and it is held open by
two red cases (`tests/test_audit.py` and `tests/test_audit_cli.py`, both named
after it) until `engine/audit.py` treats a file as its own one-entry listing.

## From a finding to a store

The report is not a list of suspicious strings. Each pattern declares the KIND
of secret it usually is, that kind goes through the same placement policy `where`
reads, and the answer comes back as a store and a naming shape:

```
  infra/channels/outbound.yaml:4  github-token  [ghp_ahov…]
      belongs in login-keychain: keychain://<provider>-<tenant>-<role>/<account>
```

Read that as one sentence: this is a GitHub token, personal tokens are declared
to live in the login keychain, and the entry is named by provider, tenant and
role. The next step is filling in the angle brackets, not inventing a name.

Three outcomes other than a store name:

| What the row says | What it means |
|---|---|
| `declare a store that holds <kind>` | the kind is real and nothing in `infra/secret-stores/` claims it. The fix is a declaration, not a folder somebody picks |
| no suggestion at all, under the personal-data heading | a PII pattern. It is reported where it lies and it is not moved. `secrets where iban` refuses with the same sentence and exit `5` |
| nothing, because the hit is not shown | the file sits inside a directory a `file` store declares. That is the store working, and `-v` shows the count |

That last one is the difference between this and a plain grep. A scanner that
reports its own store trains its reader to ignore it, and the report after that
is worth nothing at all.

## What a clean scan does not prove

Every report ends with the same line, and it is not modesty:

```
A clean scan is not a proof: this reads the files it can, with the patterns it has.
```

The honest limits, each of them a way a real value stays invisible:

| Limit | What slips through |
|---|---|
| the tracked set inside `--root` | the untracked scratch file next to the repo, until `--also` names its directory |
| the working tree, not the history | a value deleted this morning is still in the git log, and still valid until it is rotated |
| the patterns it has | a provider whose token shape nobody added, an internally minted credential, a passphrase that looks like a sentence |
| one line at a time | a value split across two lines, or wrapped in base64 inside a blob, or assembled at runtime from pieces |
| text it can decode | binaries, files over 2 MB, anything that is not UTF-8. They are passed over, and the report counts only what it read |
| a shape, not a meaning | a revoked token still reads as a token, and a live one that looks like a placeholder does not |

`--with-gitleaks` buys a second opinion when the binary is installed: several
hundred more shapes, from a project that does nothing else. It is deliberately
not a dependency and deliberately not a replacement, and when it is absent the
report says so in one line rather than failing:

```
gitleaks is not installed here
```

Neither tool turns a quiet scan into an absence. What an audit can do is make
the positives cheap enough that somebody actually runs it.

**Exit codes.** `0` when no credential is loose, `3` when at least one is.
Personal data does not change the code, because a tree holding an invoice with
an IBAN in it is not broken. That is what makes `audit` usable in a hook: the
code answers "is there a credential lying around", and nothing else.

## Worked example: a run

A throwaway tree with two stores declared, a channel file that still carries the
token somebody pasted while wiring it up, a workload file with an AWS key id, a
persona file with an IBAN in it, and a runtime token sitting inside the directory
that `runtime-drop` declares as a `file` store.

```
$ secrets audit
credentials in plain text:
  infra/channels/outbound.yaml:4  github-token  [ghp_ahov…]
      belongs in login-keychain: keychain://<provider>-<tenant>-<role>/<account>
  workflow/workloads/report.yaml:2  aws-access-key  [AKIAAHOV…]
      belongs in login-keychain: keychain://<org>-<system>/<account>

personal data, which is not a secret and is not moved:
  identity/personas/example.yaml:2  iban  [DE02 120…]

6 file(s) read, 2 credential(s) to deal with, 1 personal-data hit(s)
A clean scan is not a proof: this reads the files it can, with the patterns it has.
$ echo $?
3
```

The token in the declared store is not in that report. With `-v` it is counted,
and with `--also` the folder outside the repo comes along:

```
$ secrets audit --also /home/opuser/scratch -v
credentials in plain text:
  infra/channels/outbound.yaml:4  github-token  [ghp_ahov…]
      belongs in login-keychain: keychain://<provider>-<tenant>-<role>/<account>
  workflow/workloads/report.yaml:2  aws-access-key  [AKIAAHOV…]
      belongs in login-keychain: keychain://<org>-<system>/<account>
  /home/opuser/scratch/notes.txt:2  slack-token  [xoxb-aho…]
      belongs in login-keychain: keychain://<org>-<system>/<account>

personal data, which is not a secret and is not moved:
  identity/personas/example.yaml:2  iban  [DE02 120…]

1 hit(s) inside declared file stores, which is what a store is for

7 file(s) read, 3 credential(s) to deal with, 1 personal-data hit(s)
A clean scan is not a proof: this reads the files it can, with the patterns it has.
```

`--json` prints the same findings with one object per hit, carrying `expected`
and `note` as well, for a report that gets filed rather than read.

## Worked example: a finding, fixed

The first row of that report, dealt with. Four steps, and the order matters:
the value goes into the store BEFORE the file stops carrying it, so nothing is
lost between the two.

**1. Ask where it belongs.** The report already said, and `where` prints the
whole line including the note the declaration carries:

```
$ secrets where personal-token
personal-token: created under one person's identity; the provider's audit log shows that person

login-keychain  (keychain)
    The login keychain of this laptop
    reference   keychain://<provider>-<tenant>-<role>/<account>
    naming      <provider>-<tenant>-<role>
    note        Personal tokens stay personal.
    declared in infra/secret-stores/login-keychain.yaml
```

**2. Put the value in.** Out of the file and into the store, on stdin, never in
argv. The write is followed by a read of the same reference, and the bytes and
the fingerprint are what proves it landed:

```
$ printf %s "$VALUE" | secrets store keychain://github-example-ci/outbound \
    --kind personal-token --keychain /home/opuser/demo.keychain-db
keychain://github-example-ci/outbound
  stored in   /home/opuser/demo.keychain-db: service github-example-ci, account outbound
  read back   40 bytes, sha256 dababdcb
  store       login-keychain (infra/secret-stores/login-keychain.yaml)
```

**3. Replace the value in the file with the reference.** The line keeps saying
which secret it needs and stops carrying it:

```yaml
name: outbound
env:
  GITHUB_TOKEN_REF: keychain://github-example-ci/outbound
  MAIL_REF: keychain://mail-relay/outbound
```

The program resolves it in its own process at run time, with `secrets run --env
GITHUB_TOKEN=keychain://github-example-ci/outbound -- ...` or by resolving it
itself. What must not happen is resolving it here and writing the result into a
unit file, which is the one place it may not be.

**4. Prove both directions.** The audit no longer knows about it, and `check`
now does:

```
$ secrets audit --no-pii
credentials in plain text:
  workflow/workloads/report.yaml:2  aws-access-key  [AKIAAHOV…]
      belongs in login-keychain: keychain://<org>-<system>/<account>

6 file(s) read, 1 credential(s) to deal with, 0 personal-data hit(s)
A clean scan is not a proof: this reads the files it can, with the patterns it has.

$ secrets check keychain://github-example-ci/outbound --keychain /home/opuser/demo.keychain-db
reference                              status  bytes  sha256    where
-------------------------------------  ------  -----  --------  --------------------------------------------------------------------------
keychain://github-example-ci/outbound  ok      40     dababdcb  /home/opuser/demo.keychain-db: service github-example-ci, account outbound

1 references, 1 resolved, 0 to look at
```

**And then rotate it.** The value stood in a tracked file, so it has to be
treated as disclosed: anybody who cloned the repo, and every backup of it, has a
copy. Moving it into a store fixes the next leak, not this one. `rotate` is the
verb that would do the whole sequence in one go, and it is the next slice; until
then it is a new token at the provider, `store --replace`, and the old one
revoked.
