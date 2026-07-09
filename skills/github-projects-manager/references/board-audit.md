# Board Hygiene — Coverage & Reconciliation

Creating an issue is not "done" until it is **connected to the board and
consistent with it**. This reference covers the two drift classes a cleanup
looks for, plus the write primitives that repair them.

Two orthogonal axes:

| Axis | Question | Failure it catches |
|------|----------|--------------------|
| **Coverage** | Is every relevant open issue *on* the board? | Orphan issues that live in a tracked repo but were never added to the project |
| **Reconcile** | Does the board Status agree with the issue's real state? | "Declined" on the board but the issue is still OPEN; board "Done" but issue OPEN; issue CLOSED but board still "In progress" |

## The checker script

`scripts/board-audit.sh` runs both axes read-only and prints a report.
**Config-first**: read `workflow/projects/{slug}.yaml` and pass the board's
terminal Status strings + tracked repos — never let the heuristics stand in
for the config when it exists.

```bash
scripts/board-audit.sh \
  --owner "$ORG" --project "$NUM" \
  --declined "$(yq '.status_mapping.declined' workflow/projects/$SLUG.yaml)" \
  --done     "$(yq '.status_mapping.done'     workflow/projects/$SLUG.yaml)" \
  --repos    owner/repo1,owner/repo2
```

- `--declined` / `--done` come from the config's `status_mapping` (the same
  block the write-direction uses). Omit them and the script classifies Status
  options by keyword (`declin|cancel|reject|abgelehnt|storniert` vs
  `done|complete|erledigt|fertig|live|shipped`) — a fallback, not a substitute.
- `--repos` is the coverage set — the repos whose open issues should all live on
  this board. Read them from the project config's `audit.coverage_repos` (fall
  back to `project.issue_repo` when that key is absent). Omit to skip the
  coverage pass. Repo-level coverage only fits boards backed by dedicated repos;
  for a board that shares a repo with others (label/prefix-scoped), leave
  `audit.coverage_repos` unset — a repo diff would false-positive.
- Runs under **bash** (shebang), so loops split correctly. Do not port to zsh
  without `${=var}`.

## Reconciliation rules (generic, config-driven)

Classify each board Status into `declined | done | active` (via
`status_mapping`), then for every item backed by a real Issue:

| Board class | Expected issue | Mismatch → action |
|-------------|----------------|-------------------|
| **declined** | `CLOSED` + `NOT_PLANNED` | OPEN → close as not_planned · CLOSED/COMPLETED → **contradiction, human decides** |
| **done** | `CLOSED` (COMPLETED ok) | OPEN → finish+close, or move board off done |
| **active** (backlog/doing/review) | `OPEN` | CLOSED → stale board, move to done/declined per how it was closed |

**Contradictions never auto-resolve.** "Declined on board but closed as
completed" and "closed but board still active" are ambiguous — the board might
be wrong OR the issue might be. Surface them; let the human pick the direction.
This is the same posture as governance `done_only_by_user`.

## Coverage — find orphans (two ways)

**Per-issue (robust, no diffing):** an open issue on no ProjectV2 board has
`projectItems.totalCount == 0`.

```bash
gh api graphql -f query='{repository(owner:"'$ORG'",name:"'$REPO'"){
  issues(first:100,states:OPEN){nodes{number projectItems(first:1){totalCount}}}}}' \
  --jq '.data.repository.issues.nodes[] | select(.projectItems.totalCount==0) | .number'
```

**Repo-vs-board diff:** compare open issue numbers against the board's items
for that repo. If you use `comm`, **both lists MUST be `LC_ALL=C sort`
(lexical), never `sort -n`** — mixed 2-/3-digit numbers mis-diff under numeric
sort and silently invent/miss orphans.

## Repair primitives

### Add an existing issue to the board
```bash
gh project item-add "$NUM" --owner "$ORG" --url "$ISSUE_URL"
```
Then classify (Status + required fields) — an item with no Status is itself a
hygiene defect (`no-status items` in the audit summary).

### Close an OPEN declined issue as not planned
```bash
gh issue close "$N" --repo "$ORG/$REPO" --reason "not planned" --comment "…"
```

### Change the close-reason of an ALREADY-CLOSED issue (no reopen)
When an issue was closed as `completed` but should be `not_planned` (or vice
versa), use the `closeIssue` mutation — idempotent on a closed issue, updates
only `stateReason`, no noisy reopen event:
```bash
id=$(gh api graphql -f query='{repository(owner:"'$ORG'",name:"'$REPO'"){issue(number:'$N'){id}}}' \
     --jq '.data.repository.issue.id')
gh api graphql -f query='mutation($id:ID!){closeIssue(input:{issueId:$id,stateReason:NOT_PLANNED}){issue{state stateReason}}}' -F id="$id"
```

### Set the board Status (single-select)
See `graphql-patterns.md` → *Update Single-Select Field*. **Gotcha:** the
`singleSelectOptionId` is often all digits (e.g. `98236657`); pass it with
`-f` (string), never `-F` — `-F` coerces a digit-only value to Int and the
mutation fails with `Variable $o of type String! was provided invalid value`.

## Archived-repo issue hygiene (adjacent)

Archived repos are **read-only** — you cannot close/comment/edit issues while
archived. To clear open issues out of an archived repo:
```bash
gh api -X PATCH repos/$ORG/$REPO -f archived=false        # unarchive (API works — no web UI needed)
gh issue close "$N" --repo "$ORG/$REPO" --reason "not planned" --comment "…"
gh api -X PATCH repos/$ORG/$REPO -f archived=true          # re-archive immediately
```
Find them fleet-wide with the search qualifier (no repo-by-repo loop):
```bash
gh search issues --owner "$ORG" --state open --archived --include-prs=false --json repository,number,title
```

## Reconciliation query (paginated, with stateReason)

```bash
gh api graphql --paginate -f query='
  query($owner:String!,$num:Int!,$endCursor:String){
    organization(login:$owner){ projectV2(number:$num){
      items(first:100, after:$endCursor){
        pageInfo{ hasNextPage endCursor }
        nodes{
          fieldValueByName(name:"Status"){ ... on ProjectV2ItemFieldSingleSelectValue{ name } }
          content{ __typename
            ... on Issue{ number url state stateReason repository{ nameWithOwner } } }
        }
      }
    }}
  }' -f owner="$ORG" -F num="$NUM"
```
`--paginate` follows `pageInfo.endCursor` automatically (the query must declare
`$endCursor:String` and select `pageInfo{ hasNextPage endCursor }`). Slurp the
pages with `jq -s '[.[].data.organization.projectV2.items.nodes[]]'`.
