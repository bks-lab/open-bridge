---
summary: "Cloud costs per day for the cockpit's overview page: which accounts and contracts opt in (costs: block), what scripts/cloud-costs.py measures per provider, which login or permission each provider needs, how a missing login becomes a question with the command to run, how to declare the daily workload, and how the cockpit reads the file."
type: guide
last_updated: 2026-10-29
related:
  - cloud-accounts.md
  - bridge-cockpit.md
  - workloads.md
  - inbox.md
  - ../identity/accounts/_template.yaml
  - ../identity/contracts/_template.yaml
  - ../scripts/cloud-costs.py
  - ../skills/secrets/SKILL.md
---

# Cloud costs

`scripts/cloud-costs.py` asks the providers what each opted-in account cost per
day, adds the fixed contracts, converts everything to EUR and writes one stamped
JSON file. The cockpit's overview page shows it against a budget. Every number is
measured from the provider; nothing is read from a `status:` field, and a fixed
contract is labelled as such (`kind: fixed`), never passed off as usage.

    cloud-costs.py --host H --out FILE [--root R] [--days 35] [--today YYYY-MM-DD] [--inbox]

## Opting in

An account in `identity/accounts/<id>.yaml` opts in with a `costs:` block (the
commented block in `_template.yaml` lists every key). Only `status: active`
accounts are asked.

```yaml
costs:
  enabled: true
  provider: azure                       # optional, otherwise guessed like cloud-inventory
  group_by: service                     # azure: service | resource_group | tag:<name>
  budget_month: 50                      # optional, in `currency`
  currency: EUR                         # optional, the currency of budget_month (default EUR)
```

The budget is converted to EUR with the same rates as the amounts and keeps its
declared currency as `budget_currency`; without a rate it stays as declared and
says `budget_fx_missing: true`. A contract's budget is in `pricing.currency`
unless its `costs.currency` says otherwise.

A contract in `identity/contracts/<id>.yaml` opts in with `costs: {enabled: true}`.
Its monthly amount (`pricing.monthly_fee`, else `pricing.base_per_year / 12`,
gross before net) is spread evenly over the days (`monthly * 12 / 365` per day).
Use this for anything that bills a flat plan and has no daily cost API.

### One entry per project

An account that carries several projects (an OpenAI organization with one
project per customer, an Azure subscription with one resource group per
service) can answer as one entry per project instead of one for the account:

```yaml
costs:
  enabled: true
  key_ref: "keychain://openai-admin/me"
  split: project                        # one entry per project: <id>/<project id>
  parts: {proj_abc: "Customer A"}       # optional: a name when the key may not list projects
  budgets: {proj_abc: 30}               # optional: a budget per project, in `currency`
```

| Provider | `split:` | A part is |
|---|---|---|
| `openai` | `project` | a project, named from `/v1/organization/projects` with the same admin key; costs outside any project land in `<id>/none` |
| `azure` | `resource_group` or `tag:<name>` | a resource group or a tag value (`(none)` when untagged); the groups stay per service |
| `elastic` | `index_size` | a share of the bill by what each project stores in the cluster (below) |

One Elastic deployment often carries several projects (indices per tenant) on
one bill. `split: index_size` shares each day's amount out by today's index
sizes, read with a cluster key that may only see sizes (index privilege
`monitor`, no `read`):

```yaml
costs:
  split: index_size
  cluster_url: https://my-deployment.es.example.cloud.es.io
  size_key_ref: "azure-keyvault://<vault>/<secret>"
  shares:                              # first match wins; a leading .ds- is dropped
    - {match: "*customer-a*", part: "Customer A"}
    - {match: ".*", part: "Shared (system)"}
    - {match: "*", part: "Internal"}
```

An index that matches no rule lands in `other`. Today's sizes stand for every
day of the window, an approximation each entry names as `split_basis`
(`{by, bytes, share}`).

Each entry carries `parent` (the account id) and `part`, and is named
`<display_name>: <part name>`. Parts that `parts:` gives the same name are one
entry, `parts:` then listing them and the id ending in the name's slug: two
resource groups of one service (pre and prod) read as one project. A budget
in `budgets:` is keyed by part or by that name; the account's own
`budget_month` applies only while it is not split. A failure stays one entry
for the whole account.

## What each provider needs

Logins come first: Azure, AWS and Google are read through their own CLIs on the
machine that runs the collector, with the login those CLIs already hold. No
service principals, no keys for them. OpenAI, Anthropic and Elastic Cloud have no CLI
login, so they need an admin key, stored once with the secrets skill and named by
reference.

| Provider | How it is read | What it needs |
|---|---|---|
| `azure` | `az rest` against the Cost Management query API, daily `ActualCost` per service, resource group or tag, every declared subscription summed | `az login` on that machine, and the **Cost Management Reader** role on each subscription |
| `aws` | `aws ce get-cost-and-usage`, daily `UnblendedCost` per service and record type: usage per service in the groups, credits and refunds apart (see below) | a login for the aws CLI (`aws login`, optionally `--profile`) with **ce:GetCostAndUsage**. Each request costs about 0.01 USD, so once a day is the rhythm |
| `gcp` | `bq query` over the Cloud Billing export, cost plus credits per day and service | a **Cloud Billing export to BigQuery** (`costs.bigquery_table`), `gcloud auth login --update-adc`, read access to that dataset |
| `openai` | `GET /v1/organization/costs`, daily per line item | an **admin key** (`sk-admin-...`) from platform.openai.com > Settings > Organization > Admin keys, as `costs.key_ref` |
| `anthropic` | `GET /v1/organizations/cost_report`, daily per description (amounts come in cents and are converted) | an **Admin API key** (`sk-ant-admin...`) from console.anthropic.com > Settings > Admin keys, as `costs.key_ref` |
| `twilio` | `twilio api:core:usage:records:daily:list`: the day is `totalprice`, the groups the deepest priced usage categories (so `calls` and `calls-inbound` are not counted twice), the unexplained rest `other` | a login for the twilio CLI (`twilio login`, optionally `costs.profile`). It pages through every category of every day, so a run takes a minute or two |
| `elastic` | Elastic Cloud `GET /api/v2/billing/organizations/<org>/charts?bucketing_strategy=daily`, one group per deployment, amounts in ECU read as USD | an **Elastic Cloud API key** (cloud.elastic.co > Organization > API keys, a role that may read billing; not a cluster key) as `costs.key_ref`; `costs.organization_id` optional, otherwise the key's first organization |
| `cloudflare` | no daily cost API | declare the plan as a contract with `costs.enabled`; the account entry says so instead of staying silent |

The key is read through the secrets skill, so `key_ref` may point into any
declared store (`keychain://`, `1password://`, `azure-keyvault://`, ...). Storing
a key, the value never in a command line or the conversation:

    bash <bridge>/skills/secrets/secrets.sh store keychain://openai-admin/me --root <bridge> --from prompt

The collector writes this line with its own Bridge root as an absolute path, so
it works from any directory and over ssh. When a key is already stored but wrong
(a project key instead of an admin key, or one the provider refused) it adds
`--replace`. A store this machine cannot read at all (no keychain on Linux, a
keychain over ssh) is an `access` failure, not a login.

## When a login is missing

Every failure is classified on its account entry:

- `error_kind: "auth"`: not logged in, an expired token, a missing or refused
  key. The entry carries `login: {argv, hint}`: the command to run (`az login
  --tenant <id>`, `aws login --profile <p>`, `gcloud auth login --update-adc`, or
  the `secrets.sh store` line above) and one sentence what to do. An account may
  set its own command as `costs.login: [argv...]`.
- `error_kind: "access"`: logged in, a permission missing; the error names it.
- `error_kind: "error"`: anything else.

The cockpit turns `login.argv` into what you run: on the same machine as it is,
for a file read over ssh as `ssh -t <host> '<command>'` (`az login` then gets
`--use-device-code`). With `--inbox` the collector also files one inbox item per
account that needs a person (key `cloud-costs-login-<id>`, gate `only-you`) and
closes it after the next run that reads the account again.

One failing account never stops the others.

## Credits

A provider that pays for usage with credits (AWS promotional credits) would
show a month at zero while the service runs. The amount stays what is paid, and
the usage behind it is kept: a day with credits carries `credits` (negative)
and `used` (before the credits), the account `credits_month` and `used_month`,
and its groups are usage per service before the credits. The cockpit says
"used X, credits Y" on such an account, so the usage is visible before the
credits run out.

## Currency

Everything is reported in EUR, converted with the ECB's daily reference rates
(fetched once per run, recorded as `fx: {date, source, rates}`). Without them an
account keeps its own currency and says `fx_missing: true`.

## The file

Written atomically. Per account: one entry per day of the window, oldest first,
zero-filled, at most eight groups per day (the rest as `other`); today and
yesterday are `provisional` on usage accounts because providers settle late;
`month_to_date`, and `forecast_month` (month so far plus the mean of the last
seven settled days for each remaining day; for a contract its monthly amount).

```json
{"schema": 1, "kind": "cloud-costs", "host": "my-server", "at": "2026-10-19T06:15:02+02:00",
 "currency": "EUR", "days": 35, "today": "2026-10-19",
 "fx": {"date": "2026-10-17", "source": "ecb", "rates": {"USD": 1.08}},
 "accounts": [{"id": "azure-example", "provider": "azure", "kind": "usage", "ok": true,
               "days": [{"day": "2026-10-17", "amount": 1.23, "provisional": true, "groups": {"Functions": 0.8}}],
               "month_to_date": 12.3, "forecast_month": 38.1, "budget_month": 50.0}]}
```

## Declaring the run

Once a day on the always-on machine, as a workload
(`workflow/workloads/cloud-costs.yaml`, see [workloads.md](workloads.md)):

```yaml
schema_version: 1
scope: user
id: cloud-costs
title: Cloud costs
purpose: "What the cloud accounts and contracts cost per day, for the cockpit's overview page."
system: _standalone
reports_to: inbox
placement:
  host: my-server
  kind: recurring
  runtime: launchd
  owner: bridge
schedule:
  rrule: "FREQ=DAILY"
  delivery_at: "06:30"
  duration_estimate_min: 5
  timezone: Europe/Berlin
execution:
  command: ["/usr/bin/python3", "/path/to/bridge/scripts/cloud-costs.py",
            "--host", "my-server", "--out", "~/.bridge/resources/costs.json", "--inbox"]
  working_dir: /path/to/bridge
  timeout_sec: 600
  single_flight: true
  on_timeout: report
response:
  evidence: log-trace
  notify_on: [failure, timeout]
reconcile:
  probe: "test -s ~/.bridge/resources/costs.json"
  expect: "exit 0"
```

The script expands the `~` in `--out` itself, so the command needs no shell.

### One collector per machine

A collector uses the logins of the machine it runs on. When those live on
different machines (one CLI is signed in on the always-on machine, another only
on a laptop, or a key store must not be copied), run one collector on each and
give every account `costs.host: <infra/remotes name>`: a collector started with
`--host <name>` asks only the accounts and contracts whose `costs.host` is that
name or unset. Declare one workload per machine, each writing its own file. A
laptop's run is a calendar job that catches up when the machine wakes.

## How the cockpit reads it

`scripts/bridge-resources.py costs --source <file | ssh:<host>:<path>>` reads the
file (over ssh for another machine, like `workers` and `cloud`). Repeat
`--source` once per collector: the reports merge by account, a good answer wins
over a failed one and then the newer report, and an account that needs a login
offers the command for the machine that measures it. The result is kept in
`.bridge/resources/costs-view.json` with where and when it was read and whether
it is stale (older than 36 hours), and makes one row per account. The server
answers `GET /api/costs` from that file, and the overview page shows the cost
card: a bar per day, each account against its budget, and an account that needs
a login with the command to copy. Which host and file: the instance's briefing
profile, see [bridge-cockpit.md](bridge-cockpit.md).
