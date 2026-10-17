#!/bin/bash
# Regression suite for workflow/workloads/_schema.yaml.
#
#   run.sh            the suite: every valid/ file must pass, every invalid/
#                     file must fail AND name the reason it was written for.
#   run.sh --mutate   the mutation battery: soften ONE rule in a scratch copy of
#                     the schema and prove that exactly ONE negative control
#                     goes hollow. A rule whose control stays red under its own
#                     softening was never being tested by that control.
#
# valid/   Real cases from a live inventory, plus generic coverage cases for
#            the branches the inventory happens not to use.
# invalid/ Negative controls; every one MUST fail, the reason is asserted
#            (a test that fails for the wrong reason proves nothing), and every
#            one MUST have a needle in the battery below (a control nobody
#            mutated is a control nobody proved).
#
# What round 4 changed about this: until then the controls covered only the
# FORBIDDING half of the kind rules. Eight requiring rules and four sub clauses
# of the allOf rule could be deleted outright without the green moving at all.
# The names promised one property and the bodies measured another. Each of
# those rules now has its own control and its own needle, and whatever is NOT
# fully covered is printed at the end of the run, so nobody reads the green as
# larger than it is.
#
# Round 5 added the CONTENTS. Until then the schema only guarded STRUCTURE:
# which keys exist, which trigger belongs to which kind, what shape a time
# takes. What stood INSIDE a field it never looked at. Four holes fell through
# there, and all four passed both gates: a plaintext address in the mandant
# field, a phone number in the person field, a secret in the clear in
# execution.env, and relative paths in command, interpreter and working_dir.
# The interpreter case is the most expensive one because it does not crash: a
# relative path is a different TCC client, so only the grant is missing, and
# the run looks like an empty inbox.
# Counter-check for each of the four: the control validates CLEAN against the
# schema as it stood before that round. None of the four is invented.
#
# Language: this suite is CORE, and so is the schema it guards. Until
# 2026-08-27 this header said the opposite, that the controls were user tier
# and could stay in another language. The scope router had said `user` for this
# whole directory, which was a defect rather than a decision: the CI job that
# runs this file promotes, so the suite had to travel with it or the upstream
# would call a file that never arrived. A fixture depicts a declaration, and
# the `scope:` inside one describes what it depicts, never where it lives.
#
# The field separator in both tables is "@@" and not "|": the patterns in the
# schema contain alternations, and a "|" in there would have cut the table in
# half without a sound.
#
# The working tree is never modified, not even by --mutate.
set -u
DIR="$(cd "$(dirname "$0")" && pwd)"
SCHEMA="$DIR/../_schema.yaml"

# ── Each negative control names the substring its error MUST contain. ─────────
# One entry per enforced rule. `invalid/` is checked against this list below:
# a control nobody asserts is a file that proves nothing.
declare -a CASES=(
  # ── kind daemon / agent: no schedule block, no appointment, no cadence. ───
  "negative-daemon-with-schedule.yaml@@should not be valid under {'required': ['schedule']}"
  "negative-agent-with-interval.yaml@@should not be valid under {'required': ['schedule']}"
  # ── kind recurring: rrule, and no second trigger. ─────────────────────────
  "negative-recurring-without-schedule.yaml@@$: 'schedule' is a required property"
  "negative-recurring-without-rrule.yaml@@$.schedule: 'rrule' is a required property"
  "negative-recurring-with-every-sec.yaml@@should not be valid under {'required': ['every_sec']}"
  "negative-recurring-with-watch-paths.yaml@@should not be valid under {'required': ['watch_paths']}"
  "negative-recurring-with-oneshot-at.yaml@@should not be valid under {'required': ['at']}"
  # ── kind interval: every_sec, kein Termin, kein zweiter Ausloeser. ────────
  "negative-interval-without-schedule.yaml@@$: 'schedule' is a required property"
  "negative-interval-without-every-sec.yaml@@$.schedule: 'every_sec' is a required property"
  "negative-interval-with-clock-time.yaml@@should not be valid under {'required': ['delivery_at']}"
  "negative-interval-with-rrule.yaml@@should not be valid under {'required': ['rrule']}"
  "negative-interval-with-watch-paths.yaml@@should not be valid under {'required': ['watch_paths']}"
  "negative-interval-with-oneshot-at.yaml@@should not be valid under {'required': ['at']}"
  # ── kind watch: watch_paths; every_sec stays allowed as the fallback. ─────
  "negative-watch-without-schedule.yaml@@$: 'schedule' is a required property"
  "negative-watch-without-watch-paths.yaml@@$.schedule: 'watch_paths' is a required property"
  "negative-watch-with-rrule.yaml@@should not be valid under {'required': ['rrule']}"
  "negative-watch-with-oneshot-at.yaml@@should not be valid under {'required': ['at']}"
  # ── kind oneshot: at, and no second trigger. ──────────────────────────────
  "negative-oneshot-without-schedule.yaml@@$: 'schedule' is a required property"
  "negative-oneshot-without-at.yaml@@$.schedule: 'at' is a required property"
  "negative-oneshot-with-rrule.yaml@@should not be valid under {'required': ['rrule']}"
  "negative-oneshot-with-every-sec.yaml@@should not be valid under {'required': ['every_sec']}"
  "negative-oneshot-with-watch-paths.yaml@@should not be valid under {'required': ['watch_paths']}"
  # ── What the Bridge runs itself: command, deadline, evidence, response. ───
  "negative-bridge-owned-without-execution.yaml@@$: 'execution' is a required property"
  "negative-bridge-owned-without-response.yaml@@$: 'response' is a required property"
  "negative-bridge-owned-without-command.yaml@@$.execution: 'command' is a required property"
  "negative-without-deadline.yaml@@$.execution: 'timeout_sec' is a required property"
  "negative-bridge-owned-without-evidence.yaml@@$.response: 'evidence' is a required property"
  # ── A foreign runtime means a foreign owner. ──────────────────────────────
  "negative-foreign-runtime-with-bridge-owner.yaml@@$.placement.owner: 'foreign' was expected"
  # ── Times: the zone as Region/Place, instants as ISO 8601. ────────────────
  "negative-fixed-utc-offset.yaml@@$.schedule.timezone: '+02:00' does not match"
  "negative-offset-as-timezone-name.yaml@@$.schedule.timezone: 'Etc/GMT+2' should not be valid under {'pattern': '^Etc/GMT[+-]?[0-9]'}"
  "negative-oneshot-at-as-prose.yaml@@$.schedule.at: 'sometime next week' does not match"
  "negative-provisioned-at-as-prose.yaml@@$.placement.provisioned_at: 'yesterday evening' does not match"
  "negative-retired-as-prose.yaml@@$.retired.at: 'last year' does not match"
  # ── Repraesentanten je Regelklasse, siehe Abdeckungsnotiz unten. ──────────
  "negative-without-placement.yaml@@$: 'placement' is a required property"
  "negative-placement-without-owner.yaml@@$.placement: 'owner' is a required property"
  "negative-status-field.yaml@@$: Additional properties are not allowed ('status' was unexpected)"
  "negative-plaintext-address.yaml@@$.response.recipients[0]: Additional properties are not allowed ('address' was unexpected)"
  "negative-recipient-without-mandant.yaml@@$.response.recipients[0]: 'mandant' is a required property"
  "negative-unknown-owner.yaml@@$.placement.owner: 'devops' is not one of ['bridge', 'human', 'foreign']"
  "negative-rrule-without-freq.yaml@@$.schedule.rrule: 'every monday' does not match '^FREQ="
  "negative-deadline-zero.yaml@@$.execution.timeout_sec: 0 is less than the minimum of 1"
  "negative-empty-command.yaml@@$.execution.command: [] should be non-empty"
  "negative-purpose-too-short.yaml@@$.purpose: 'tiny' is too short"
  "negative-retired-without-reason.yaml@@$.retired: 'reason' is a required property"
  # ── Content: recipients are references, in the VALUE and not just the key. ─
  "negative-mandant-as-plaintext-address.yaml@@$.response.recipients[0].mandant: 'a.person@example.com' does not match"
  "negative-person-as-phone-number.yaml@@$.response.recipients[0].person: '+1 555 0123456' does not match"
  "negative-persona-as-plaintext-name.yaml@@$.persona_ref: 'Jane Doe' does not match"
  # ── Content: the environment carries references, never values, no spaces. ──
  "negative-secret-in-environment.yaml@@$.execution.env.SERVICE_API_KEY: 'sk-live-example-value-not-a-real-key' does not match"
  "negative-env-key-with-space.yaml@@$.execution.env: 'API KEY' does not match '^[A-Za-z_][A-Za-z0-9_]*$'"
  # ── Paths absolute: PATH and TCC here are not the login shell's. ──────────
  "negative-relative-interpreter.yaml@@$.placement.interpreter: 'python3' does not match '^/'"
  "negative-relative-working-dir.yaml@@$.execution.working_dir: '~/projects/example' does not match '^/'"
  # ── The program keeps its name, and does not lend it to the whole machine. ─
  "negative-version-in-interpreter-path.yaml@@$.placement.interpreter: '/opt/example/Cellar/sometool/1.73.5/bin/sometool' should not be valid under {'pattern'"
  "negative-shared-interpreter-with-grant.yaml@@$.placement.interpreter: '/usr/bin/python3' should not be valid under {'enum'"
  "negative-grant-without-interpreter.yaml@@$.placement: 'interpreter' is a required property"
  "negative-unknown-grant.yaml@@$.placement.privacy_grants[0]: 'full-disk' is not one of ["
  "negative-relative-command.yaml@@$.execution.command[0]: 'assistant' does not match '^/'"
  # ── A label prefix is a dotted name and nothing else. ─────────────────────
  "negative-label-prefix-malformed.yaml@@$.placement.label_prefix: '.leading.dot' does not match"
  # ── rights: what a run may do. ────────────────────────────────────────────
  "negative-rights-generic-shell.yaml@@$.rights.standing.tools: 'Bash,Read,Glob,Grep' should not be valid"
  "negative-rights-inline-handle.yaml@@$.rights.escalation.recipients[0].mandant_ref: 'person@example.com' does not match"
  "negative-rights-escalation-without-condition.yaml@@$.rights.escalation: 'unlocked_by' is a required property"
  "negative-rights-outward-without-caps.yaml@@$.rights.escalation: 'caps' is a required property"
  "negative-rights-outward-without-stop.yaml@@$.rights: 'stop' is a required property"
  "negative-rights-scope-tilde.yaml@@$.rights.standing.read_scope: '~/notes' does not match"
  "negative-rights-scope-escape.yaml@@$.rights.standing.read_scope: 'example/notes/../../../' does not match"
  "negative-rights-tool-without-scope.yaml@@$.rights.standing: 'read_scope' is a required property"
  "negative-rights-relative-stop-flag.yaml@@$.rights.stop.flag: '.stop' does not match"
  "negative-rights-fetch-without-hosts.yaml@@$.rights.standing: 'fetch_scope' is a required property"
  "negative-rights-hold-without-reply.yaml@@$.rights: 'reply' is a required property"
  "negative-rights-fetch-star-beside-hosts.yaml@@$.rights.standing.fetch_scope: ['example.com', '*'] is too long"
  "negative-rights-outward-without-consent.yaml@@$.rights: 'consent' is a required property"
)
# ── The mutation battery. ─────────────────────────────────────────────────────
# name @@ literal in _schema.yaml @@ softened literal @@ the ONE control that
# must go hollow. Every needle disables exactly one enforced rule; the run
# asserts that its control validates afterwards, that no OTHER control does, and
# that valid/ stays green (every needle is a pure loosening, so a valid file that
# breaks means the needle softened something else than it claims).
declare -a NEEDLES=(
  "daemon-may-carry-an-appointment@@{enum: [daemon, agent]}@@{enum: [agent]}@@negative-daemon-with-schedule.yaml"
  "agent-may-carry-a-cadence@@{enum: [daemon, agent]}@@{enum: [daemon]}@@negative-agent-with-interval.yaml"
  "recurring-may-carry-every_sec@@- not: {required: [every_sec]}         # recurring has appointments, not a cadence@@- not: {required: [never-present]}     # recurring has appointments, not a cadence@@negative-recurring-with-every-sec.yaml"
  "recurring-may-carry-watch_paths@@- not: {required: [watch_paths]}       # recurring is not a path watcher@@- not: {required: [never-present]}     # recurring is not a path watcher@@negative-recurring-with-watch-paths.yaml"
  "recurring-may-carry-at@@- not: {required: [at]}                # recurring is not a one-shot@@- not: {required: [never-present]}     # recurring is not a one-shot@@negative-recurring-with-oneshot-at.yaml"
  "interval-may-carry-rrule@@- not: {required: [rrule]}             # interval is not a recurrence@@- not: {required: [never-present]}     # interval is not a recurrence@@negative-interval-with-rrule.yaml"
  "interval-may-carry-watch_paths@@- not: {required: [watch_paths]}       # interval is not a path watcher@@- not: {required: [never-present]}     # interval is not a path watcher@@negative-interval-with-watch-paths.yaml"
  "interval-may-carry-at@@- not: {required: [at]}                # interval is not a one-shot@@- not: {required: [never-present]}     # interval is not a one-shot@@negative-interval-with-oneshot-at.yaml"
  "watch-may-carry-rrule@@- not: {required: [rrule]}             # watch is not a recurrence@@- not: {required: [never-present]}     # watch is not a recurrence@@negative-watch-with-rrule.yaml"
  "watch-may-carry-at@@- not: {required: [at]}                # watch is not a one-shot@@- not: {required: [never-present]}     # watch is not a one-shot@@negative-watch-with-oneshot-at.yaml"
  "oneshot-may-carry-rrule@@- not: {required: [rrule]}             # oneshot is not a recurrence@@- not: {required: [never-present]}     # oneshot is not a recurrence@@negative-oneshot-with-rrule.yaml"
  "oneshot-may-carry-every_sec@@- not: {required: [every_sec]}         # oneshot has no cadence@@- not: {required: [never-present]}     # oneshot has no cadence@@negative-oneshot-with-every-sec.yaml"
  "oneshot-may-carry-watch_paths@@- not: {required: [watch_paths]}       # oneshot is not a path watcher@@- not: {required: [never-present]}     # oneshot is not a path watcher@@negative-oneshot-with-watch-paths.yaml"
  "interval-may-carry-an-appointment@@not: {required: [delivery_at]}   # an interval job has no appointment@@not: {required: [never-present]} # an interval job has no appointment@@negative-interval-with-clock-time.yaml"
  "foreign-runtime-may-belong-to-the-bridge@@properties: {placement: {properties: {owner: {const: foreign}}}}@@properties: {placement: {properties: {owner: {enum: [foreign, bridge, human]}}}}@@negative-foreign-runtime-with-bridge-owner.yaml"
  "timezone-may-take-any-shape@@pattern: \"^[A-Za-z][A-Za-z0-9_+-]*/[A-Za-z0-9_+-]+(/[A-Za-z0-9_+-]+)?$\"@@pattern: \"^.*$\"@@negative-fixed-utc-offset.yaml"
  "offset-may-pass-as-a-zone-name@@not: {pattern: \"^Etc/GMT[+-]?[0-9]\"}   # the same fixed offset, spelled as an IANA name@@not: {pattern: \"^never-present\"}       # the same fixed offset, spelled as an IANA name@@negative-offset-as-timezone-name.yaml"
  "oneshot-instant-may-be-prose@@pattern: \"^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T([01][0-9]|2[0-3]):[0-5][0-9](:[0-5][0-9])?(Z|[+-]([01][0-9]|2[0-3]):[0-5][0-9])?$\"   # date AND time; at is the only thing that fires a oneshot@@pattern: \"^.*$\"   # date AND time; at is the only thing that fires a oneshot@@negative-oneshot-at-as-prose.yaml"
  "provisioned-at-may-be-prose@@pattern: \"^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])T([01][0-9]|2[0-3]):[0-5][0-9](:[0-5][0-9])?(Z|[+-]([01][0-9]|2[0-3]):[0-5][0-9])?$\"   # same shape as schedule.at; null passes a pattern untouched@@pattern: \"^.*$\"   # same shape as schedule.at; null passes a pattern untouched@@negative-provisioned-at-as-prose.yaml"
  "retirement-date-may-be-prose@@pattern: \"^[0-9]{4}-(0[1-9]|1[0-2])-(0[1-9]|[12][0-9]|3[01])(T([01][0-9]|2[0-3]):[0-5][0-9](:[0-5][0-9])?(Z|[+-]([01][0-9]|2[0-3]):[0-5][0-9])?)?$\"@@pattern: \"^.*$\"@@negative-retired-as-prose.yaml"
  "recurring-may-drop-its-schedule@@required: [schedule]                     # an appointment needs a schedule block@@required: []                             # an appointment needs a schedule block@@negative-recurring-without-schedule.yaml"
  "interval-may-drop-its-schedule@@required: [schedule]                     # a cadence needs a schedule block@@required: []                             # a cadence needs a schedule block@@negative-interval-without-schedule.yaml"
  "watch-may-drop-its-schedule@@required: [schedule]                     # a watcher needs a schedule block@@required: []                             # a watcher needs a schedule block@@negative-watch-without-schedule.yaml"
  "oneshot-may-drop-its-schedule@@required: [schedule]                     # a one-shot needs a schedule block@@required: []                             # a one-shot needs a schedule block@@negative-oneshot-without-schedule.yaml"
  "trigger-rrule-may-be-missing@@                    - required: [rrule]@@                    - required: []@@negative-recurring-without-rrule.yaml"
  # CAUGHT UP 2026-08-25: the rule was rebuilt into a oneOf (the shorthand
  # rrule OR a list of appointments), and the old needle looked for the
  # resolved required line and matched ZERO times. A needle that matches
  # nothing softens nothing, and the run still reported green for all the
  # others. The failure had been sitting in the tree since at least the
  # previous commit.
  "trigger-every_sec-may-be-missing@@required: [every_sec]                # interval without a cadence has no WHEN@@required: []                         # interval without a cadence has no WHEN@@negative-interval-without-every-sec.yaml"
  "trigger-watch_paths-may-be-missing@@required: [watch_paths]              # watch without paths listens to nothing@@required: []                         # watch without paths listens to nothing@@negative-watch-without-watch-paths.yaml"
  "trigger-at-may-be-missing@@required: [at]                       # oneshot without an instant never fires@@required: []                         # oneshot without an instant never fires@@negative-oneshot-without-at.yaml"
  "bridge-run-may-drop-its-execution@@required: [execution, response]@@required: [response]@@negative-bridge-owned-without-execution.yaml"
  "bridge-run-may-drop-its-response@@required: [execution, response]@@required: [execution]@@negative-bridge-owned-without-response.yaml"
  "bridge-run-may-drop-its-command@@execution: {required: [command, timeout_sec]}@@execution: {required: [timeout_sec]}@@negative-bridge-owned-without-command.yaml"
  "bridge-run-may-drop-its-deadline@@execution: {required: [command, timeout_sec]}@@execution: {required: [command]}@@negative-without-deadline.yaml"
  "bridge-run-may-drop-its-evidence@@response: {required: [evidence]}@@response: {required: []}@@negative-bridge-owned-without-evidence.yaml"
  "declaration-may-drop-its-placement@@required: [schema_version, scope, id, purpose, placement]@@required: [schema_version, scope, id, purpose]@@negative-without-placement.yaml"
  "placement-may-drop-its-owner@@required: [host, kind, runtime, owner]@@required: [host, kind, runtime]@@negative-placement-without-owner.yaml"
  "top-level-may-take-foreign-fields@@additionalProperties: false   # no status:, which is the whole reason this file exists@@additionalProperties: true    # no status:, which is the whole reason this file exists@@negative-status-field.yaml"
  "recipient-may-take-foreign-fields@@additionalProperties: false   # never a plaintext address, only a slug@@additionalProperties: true    # never a plaintext address, only a slug@@negative-plaintext-address.yaml"
  "owner-may-be-invented@@enum: [bridge, human, foreign]@@enum: [bridge, human, foreign, devops]@@negative-unknown-owner.yaml"
  "rrule-may-be-prose@@pattern: \"^FREQ=(SECONDLY|MINUTELY|HOURLY|DAILY|WEEKLY|MONTHLY|YEARLY)\"   # shorthand: one appointment@@pattern: \"^.*$\"   # shorthand: one appointment@@negative-rrule-without-freq.yaml"
  # CAUGHT UP 2026-08-25: since the appointment list arrived, the same
  # pattern stands TWICE in the schema (schedule.rrule and
  # appointments[].rrule). The needle matched both and was therefore
  # refused. It is made unique through the indentation: eight spaces is the
  # shorthand, fourteen is the list. What is checked here is the shorthand,
  # because the control uses it. The indentation ALONE was not enough: the
  # fourteen spaces of the list form contain the eight of the shorthand as a
  # substring, so a counter over substrings finds both. Both places have
  # carried a comment of their own since, exactly as the head of the allOf
  # block demands for itself: one uniquely addressable line per rule.
  "deadline-may-be-zero@@minimum: 1   # a deadline of zero is not a deadline@@minimum: 0   # a deadline of zero is not a deadline@@negative-deadline-zero.yaml"
  "command-may-be-empty@@minItems: 1   # an empty argv is not a command@@minItems: 0   # an empty argv is not a command@@negative-empty-command.yaml"
  "purpose-may-be-too-short@@minLength: 8   # four characters would be the shape without the content@@minLength: 1   # four characters would be the shape without the content@@negative-purpose-too-short.yaml"
  "retirement-may-drop-its-reason@@required: [at, reason]@@required: [at]@@negative-retired-without-reason.yaml"
  "recipient-may-drop-its-mandant@@required: [mandant]@@required: []@@negative-recipient-without-mandant.yaml"
  "mandant-may-be-an-address@@pattern: \"^[a-z0-9][a-z0-9-]*$\"   # slug shape; an address, a number or a written-out name cannot have it@@pattern: \"^.*$\"   # slug shape; an address, a number or a written-out name cannot have it@@negative-mandant-as-plaintext-address.yaml"
  "persona-may-be-a-written-out-name@@pattern: \"^(_shared|_infrastructure|[a-z][a-z0-9-]*)$\"@@pattern: \"^.*$\"@@negative-persona-as-plaintext-name.yaml"
  "person-may-be-a-phone-number@@pattern: \"^[a-z0-9][a-z0-9_-]*$\"   # the same shape, plus the underscore person keys use@@pattern: \"^.*$\"   # the same shape, plus the underscore person keys use@@negative-person-as-phone-number.yaml"
  "environment-may-carry-a-value@@pattern: '^(azure-keyvault|keychain|1password|keepass|op|vault|file)://\\S+$'   # a locator, never a value@@pattern: '^.*$'   # a locator, never a value@@negative-secret-in-environment.yaml"
  "environment-name-may-carry-a-space@@pattern: \"^[A-Za-z_][A-Za-z0-9_]*$\"   # the hand-written gate's ENV_NAME_PATTERN, character for character@@pattern: \"^.*$\"   # the hand-written gate's ENV_NAME_PATTERN, character for character@@negative-env-key-with-space.yaml"
  "interpreter-may-be-relative@@pattern: \"^/\"   # absolute, because a relative interpreter is a different TCC client@@pattern: \"^\"   # absolute, because a relative interpreter is a different TCC client@@negative-relative-interpreter.yaml"
  "working-dir-may-be-relative@@pattern: \"^/\"   # absolute; there is no login shell here to expand a ~ or a relative path@@pattern: \"^\"   # absolute; there is no login shell here to expand a ~ or a relative path@@negative-relative-working-dir.yaml"
  "interpreter-may-carry-a-version@@(?:^|/)(v?\\d+(?:\\.\\d+)+(?:[._-][A-Za-z0-9]+)?)(?:/|$)@@ZZZ-NO-MATCH-ZZZ@@negative-version-in-interpreter-path.yaml"
  "shared-interpreter-may-hold-a-grant@@/usr/bin/env, /usr/bin/python3, /usr/bin/perl@@/usr/bin/env, /usr/bin/perl@@negative-shared-interpreter-with-grant.yaml"
  "grant-may-drop-its-client-path@@required: [interpreter]              # a grant with no client path is issued to nothing@@required: []                         # a grant with no client path is issued to nothing@@negative-grant-without-interpreter.yaml"
  "grant-name-may-be-invented@@enum: [full-disk-access, calendar, contacts, reminders, photos,@@enum: [full-disk, full-disk-access, calendar, contacts, reminders, photos,@@negative-unknown-grant.yaml"
  "command-may-be-relative@@pattern: \"^/\"   # argv[0] absolute; PATH under a service manager is not a login PATH@@pattern: \"^\"   # argv[0] absolute; PATH under a service manager is not a login PATH@@negative-relative-command.yaml"
  "label-prefix-may-be-anything@@pattern: \"^[A-Za-z0-9][A-Za-z0-9_-]*(\\\\.[A-Za-z0-9][A-Za-z0-9_-]*)*$\"@@pattern: \"^.*$\"@@negative-label-prefix-malformed.yaml"
  # ── rights: what a run may do. One needle per rule, and each rule
  #    carries its reason on its own line so exactly one control goes
  #    hollow when it is softened. ───────────────────────────────────
  'rights-tools-may-be-generic-shell@@      pattern: "(^|[,\\s])Bash(\\(\\*\\))?\\s*([,\\s]|$)"       # generic shell is never declarable@@      pattern: "(^|,)\\s*never-present-tool\\s*(,|$)"       # generic shell is never declarable@@negative-rights-generic-shell.yaml'
  'rights-recipient-may-be-a-handle@@    pattern: "^[a-z0-9][a-z0-9-]*$"          # a reference, never a handle@@    pattern: "^.*$"          # a reference, never a handle@@negative-rights-inline-handle.yaml'
  'rights-escalation-may-lack-a-condition@@          - required: [unlocked_by]          # a level with no condition is the normal state under another name@@          - not: {required: [never-present]}          # a level with no condition is the normal state under another name@@negative-rights-escalation-without-condition.yaml'
  'rights-outward-may-lack-caps@@          required: [recipients, caps]       # reaching people without a list and a cap is a hole, not a right@@          not: {required: [never-present]}       # reaching people without a list and a cap is a hole, not a right@@negative-rights-outward-without-caps.yaml'
  # CAUGHT UP 2026-09-11: `consent` joined the rule on 2026-09-10, so the
  # line became `required: [stop, consent]` and this needle, still looking
  # for the old `required: [stop]`, matched ZERO times. Its sibling
  # `rights-outward-may-lack-a-consent` softens the same line the other
  # way: that one drops consent and keeps stop, this one drops stop and
  # keeps consent, so each still empties exactly one control.
  'rights-outward-may-lack-a-way-out@@          required: [stop, consent]          # a way out and a way in are both part of the permission@@          required: [consent]          # a way out and a way in are both part of the permission@@negative-rights-outward-without-stop.yaml'
  'rights-scope-may-climb-out@@    pattern: "^(?!/)(?!~)(?!.*\\.\\.).+$"           # no absolute path, no climbing out@@    pattern: "^(?!/)(?!~).+$"           # no absolute path, no climbing out@@negative-rights-scope-escape.yaml'
  'rights-scope-may-be-home-relative@@    pattern: "^(?!/)(?!~)(?!.*\\.\\.).+$"           # no absolute path, no climbing out@@    pattern: "^(?!/)(?!.*\\.\\.).+$"           # no absolute path, no climbing out@@negative-rights-scope-tilde.yaml'
  'rights-read-tool-may-lack-a-scope@@          required: [read_scope]             # a read tool with no scope is refused on every call@@          not: {required: [never-present]}             # a read tool with no scope is refused on every call@@negative-rights-tool-without-scope.yaml'
  'rights-stop-flag-may-be-relative@@            pattern: "^(~|/)"                # absolute or ~, never relative@@            pattern: "^.*$"                # absolute or ~, never relative@@negative-rights-relative-stop-flag.yaml'
  'rights-fetch-may-reach-any-host@@          required: [fetch_scope]            # a fetching tool with no host list reaches every host@@          not: {required: [never-present]}            # a fetching tool with no host list reaches every host@@negative-rights-fetch-without-hosts.yaml'
  'rights-hold-may-lack-a-release@@          required: [reply]                  # a hold with no release is a stop wearing a friendlier word@@          not: {required: [never-present]}                  # a hold with no release is a stop wearing a friendlier word@@negative-rights-hold-without-reply.yaml'
  'rights-star-may-stand-beside-hosts@@              maxItems: 1                    # a list that names hosts beside `*` reads bounded and is not@@              maxItems: 99                    # a list that names hosts beside `*` reads bounded and is not@@negative-rights-fetch-star-beside-hosts.yaml'
  'rights-outward-may-lack-a-consent@@          required: [stop, consent]          # a way out and a way in are both part of the permission@@          required: [stop]          # a way out and a way in are both part of the permission@@negative-rights-outward-without-consent.yaml'
)
# ── What is NOT fully covered. Printed at the end of every run. ───────────────
# Without this list the green above reads as completeness, and that is exactly
# the finding that led to round 4.
print_coverage_note() {
  cat <<'NOTE'

Coverage, named honestly:

  Its own control AND its own needle, per rule:
    kind rules, the forbidding and the requiring half
    allOf for bridge owned runs, all four sub clauses plus the deadline
    runtime external means owner foreign
    instant patterns at, provisioned_at, retired.at
    timezone: the Region/Place form, and the offset in IANA spelling
    retired.required, recipients[].required
    content: mandant and person as slugs, env value as a reference, env name
    paths: interpreter, working_dir, command[0]
    the program keeps its name: no version in the interpreter path, and a
      declared privacy grant needs a client path of its own
    rights, all twelve rules: generic shell, handle instead of reference,
      escalation without a condition, outward without caps, outward without a
      way out, scope climbing out, read tool without a scope, relative stop
      flag, fetch tool without a host list, hold without a release, `*`
      standing beside named hosts, and reaching a person with no way for a
      human to say yes

  Checked REPRESENTATIVELY only. One control stands for a whole class; remove
  another instance of the same class from the schema and you will NOT notice
  it HERE:
    required lists ........ all 5 lists have a control, but only one key per
                            list: placement (1 of 5 at the top), owner (1 of 4),
                            reason (1 of 2), mandant (1 of 1), interpreter
                            (1 of 1, the conditional list under allOf)
    additionalProperties .. 2 of 8 places: the top level and recipients[].
                            placement, schedule, execution, response, reconcile
                            and retired are unguarded
    enum .................. 3 of 10 fields: owner, privacy_grants and the deny
                            list of shared interpreters. scope, kind, runtime,
                            evidence, isolation, on_timeout and notify_on are
                            not
    pattern ............... 14 of 16 places. Exactly two stay unguarded:
                            id and delivery_at
    minimum ............... 1 of 4: timeout_sec. port, every_sec and
                            duration_estimate_min are not
    minItems .............. 1 of 2: command, not watch_paths
    minLength ............. 1 of 2: purpose, not retired.reason
    type and const ........ not at all, schema_version: const 1 included

  Content safety, and where it ends. The four content rules check FORM and not
  meaning, and none of them guesses what a secret is:
    env ................... a value is refused BECAUSE it is a value, not
                            because it looks like a key. A secret typed as a
                            LOCATOR (keychain:// followed by the key itself) is
                            well formed and passes. The form cannot see that.
    free text ............. command arguments, reconcile.probe, purpose,
                            learned_from and title stay unguarded. A secret in
                            argv lands in the unit file just as one in env does.
    command ............... only argv[0] is forced to be absolute. What follows
                            are flags and values, and a rule about those would
                            be a guess.
    existence ............. no pattern checks WHETHER the mandant, the person,
                            the entry in the store or the path exists. Only a
                            read of the respective source can do that, and the
                            declaration gate is there for it, not this file.
    the second gate ....... caught up (integration pass, round 4). The hand
                            written gate in engine/model.py now carries all four
                            rules itself, character for character with the
                            schema and without reading it; the class
                            TheHandWrittenGateHoldsWhatTheSchemaHolds measures
                            them together with their counter controls, and
                            test_the_two_gates_hold_the_same_rules_word_for_word
                            compares the six shared patterns directly against
                            this file. That is the point of the duplication: the
                            gate that answers the acting layer (provision.plan
                            calls model.validate, never the schema) holds the
                            same rule on a machine without check-jsonschema too.

  Why not all of them: a second control of the same keyword class proves the
  same behaviour on a different field and costs one uniquely addressable line in
  the schema per rule. The representatives are chosen rather than left over:
  what is checked is the instance whose silent failure would be the most
  expensive. The heaviest single case therefore stands above and not down here,
  namely additionalProperties at the top level, which keeps `status:` out.
NOTE
}

# Replace SEARCH once in SCHEMA_IN, write SCHEMA_OUT. Refuses on 0 or >1 hits:
# a needle that matches nothing softens nothing and would report a green that
# was never earned.
soften() {
  SCHEMA_IN="$1" SCHEMA_OUT="$2" SEARCH="$3" REPLACE="$4" python3 - <<'PY'
import os, sys, pathlib
src = pathlib.Path(os.environ["SCHEMA_IN"]).read_text(encoding="utf-8")
needle, repl = os.environ["SEARCH"], os.environ["REPLACE"]
hits = src.count(needle)
if hits != 1:
    sys.stderr.write(f"needle matched {hits} times, must match exactly 1\n")
    sys.exit(2)
pathlib.Path(os.environ["SCHEMA_OUT"]).write_text(src.replace(needle, repl), encoding="utf-8")
PY
}

# Which of the given files does SCHEMA still REJECT, and which went hollow?
# One check-jsonschema call names every instance it rejects, prefixed
# "  <path>::". A file it does not name is only a CANDIDATE for hollow, and each
# candidate is then asked again on its own, because the exit code is what
# decides hollowness, never parsed text. If that parsing ever stops matching,
# every file becomes a candidate and the sweep degrades into the per-file loop
# it replaces: slower, same verdict. That is the only direction it can fail in.
hollow_among() {
  local soft="$1"; shift
  local out f cand=() hollow=()
  out=$(check-jsonschema --schemafile "$soft" "$@" 2>&1)
  for f in "$@"; do
    printf '%s\n' "$out" | grep -qF "$(basename "$f")::" || cand+=("$f")
  done
  for f in "${cand[@]+"${cand[@]}"}"; do
    if check-jsonschema --schemafile "$soft" "$f" >/dev/null 2>&1; then
      hollow+=("$(basename "$f")")
    fi
  done
  printf '%s\n' "${hollow[@]+"${hollow[@]}"}"
}

run_suite() {
  local fail=0 n=0 f out rc file want case needle
  for f in "$DIR"/valid/*.yaml; do
    n=$((n+1))
    if check-jsonschema --schemafile "$SCHEMA" "$f" >/dev/null 2>&1; then
      echo "  ok    valid/$(basename "$f")"
    else
      echo "  FAIL  valid/$(basename "$f"): should validate but does not"; fail=$((fail+1))
    fi
  done

  for case in "${CASES[@]}"; do
    case "$case" in "#"*) continue ;; esac
    n=$((n+1))
    file="${case%%@@*}"; want="${case#*@@}"
    if [ ! -f "$DIR/invalid/$file" ]; then
      echo "  FAIL  invalid/$file: asserted but missing"; fail=$((fail+1)); continue
    fi
    out=$(check-jsonschema --schemafile "$SCHEMA" "$DIR/invalid/$file" 2>&1); rc=$?
    if [ $rc -eq 0 ]; then
      echo "  FAIL  invalid/$file: validated, but must not"; fail=$((fail+1))
    elif ! printf '%s' "$out" | grep -qF "$want"; then
      echo "  FAIL  invalid/$file: rejected for the WRONG reason"
      echo "        wanted: $want"; fail=$((fail+1))
    else
      echo "  ok    invalid/$file: rejected, and for the stated reason"
    fi
  done

  # A negative control nobody asserts proves nothing, so catch the unlisted file.
  # And a control with no needle is a control that was never held against its
  # own rule: exactly the gap that round 4 grew out of.
  for f in "$DIR"/invalid/*.yaml; do
    file="$(basename "$f")"
    if ! printf '%s\n' "${CASES[@]}" | grep -q "^$file@@"; then
      echo "  FAIL  invalid/$file: present but asserted by no case"; fail=$((fail+1)); n=$((n+1))
    fi
    if ! printf '%s\n' "${NEEDLES[@]}" | grep -q "@@$file\$"; then
      echo "  FAIL  invalid/$file: asserted, but no needle proves it"; fail=$((fail+1)); n=$((n+1))
    fi
  done

  echo
  if [ "$fail" -eq 0 ]; then echo "$n/$n green"; else echo "$fail of $n FAILED"; fi
  return $fail
}

run_mutations() {
  local fail=0 n=0 tmp soft name search replace target rc bystander vfail
  tmp="$(mktemp -d)"; trap 'rm -rf "$tmp"' RETURN
  soft="$tmp/_schema.yaml"

  for needle in "${NEEDLES[@]}"; do
    n=$((n+1))
    name="${needle%%@@*}";              needle="${needle#*@@}"
    search="${needle%%@@*}";            needle="${needle#*@@}"
    replace="${needle%%@@*}"
    target="${needle#*@@}"

    if ! soften "$SCHEMA" "$soft" "$search" "$replace" 2>"$tmp/err"; then
      echo "  FAIL  $name: $(cat "$tmp/err")"; fail=$((fail+1)); continue
    fi

    # Every needle is a pure loosening, so valid/ must stay green. This also
    # catches a softened schema that no longer parses, which would otherwise
    # fail every file and read as "the control stays red": a true sentence
    # about the wrong problem.
    if ! check-jsonschema --schemafile "$soft" "$DIR"/valid/*.yaml >"$tmp/vout" 2>&1; then
      echo "  FAIL  $name: valid/ breaks under this softening, so the needle"
      echo "        does not soften what it claims:"
      sed -n '2,4p' "$tmp/vout" | sed 's/^/        /'; fail=$((fail+1)); continue
    fi

    check-jsonschema --schemafile "$soft" "$DIR/invalid/$target" >/dev/null 2>&1; rc=$?
    if [ $rc -ne 0 ]; then
      echo "  FAIL  $name: invalid/$target stays red under its own softening,"
      echo "        so that control is not what proves this rule"; fail=$((fail+1)); continue
    fi

    bystander=$(hollow_among "$soft" $(ls "$DIR"/invalid/*.yaml | grep -v "/$target\$") | tr '\n' ' ')
    bystander="$(printf '%s' "$bystander" | sed 's/ *$//')"
    if [ -n "$bystander" ]; then
      echo "  FAIL  $name: softened one rule, but these also went hollow: $bystander"
      fail=$((fail+1)); continue
    fi

    echo "  ok    $name: only invalid/$target goes hollow"
  done

  echo
  if [ "$fail" -eq 0 ]; then echo "$n/$n needles bite"; else echo "$fail of $n needles FAILED"; fi
  return $fail
}

case "${1-}" in
  --mutate)
    echo "suite (baseline; a mutation result on a red baseline means nothing):"
    run_suite || exit $?
    echo
    echo "mutations:"
    run_mutations; rc=$?
    print_coverage_note
    exit $rc
    ;;
  "")
    run_suite; rc=$?
    print_coverage_note
    exit $rc
    ;;
  *)
    echo "usage: run.sh [--mutate]" >&2; exit 2
    ;;
esac
