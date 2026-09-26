# GraphQL Patterns for GitHub Projects V2

Fallback patterns when `gh project item-edit` is insufficient.

> **Every connection below is paginated for a reason.** `items` and `fields`
> are GraphQL connections: `first: N` returns N and says nothing about the
> rest. A board with 377 items answers `items(first: 100)` with 100 and no
> error, so a lookup that finds nothing has two indistinguishable meanings —
> "not on the board" and "past page one". Ask for `totalCount` alongside the
> nodes and loop on `pageInfo.hasNextPage` whenever the board can outgrow one
> page. GitHub caps `first` at **100**.

## Get Project ID

```bash
PROJECT_ID=$(gh api graphql -f query='
  query($org: String!, $num: Int!) {
    organization(login: $org) {
      projectV2(number: $num) { id }
    }
  }' -f org="$ORG" -F num=$NUM \
  --jq '.data.organization.projectV2.id')
```

## Get Field IDs + Option IDs

`first: 100` is the API maximum. Boards do exceed 30 fields, and a `first: 30`
query hides the rest without an error, so always check `totalCount`.

```bash
gh api graphql -f query='
  query($id: ID!) {
    node(id: $id) {
      ... on ProjectV2 {
        fields(first: 100) {
          totalCount
          nodes {
            ... on ProjectV2SingleSelectField {
              id name
              options { id name color description }
            }
            ... on ProjectV2Field {
              id name dataType
            }
            ... on ProjectV2IterationField {
              id name
            }
          }
        }
      }
    }
  }' -f id="$PROJECT_ID"
```

## Get Item ID by Issue URL

Do **not** stop at `items(first: 100)` — a board bigger than one page turns a
missing item into a false "not on the board". Page until `hasNextPage` is false:

```bash
find_item() {  # $1 = PROJECT_ID, $2 = ISSUE_URL
  local cursor=null item=""
  while :; do
    local page
    page=$(gh api graphql -f query='
      query($id: ID!, $after: String) {
        node(id: $id) {
          ... on ProjectV2 {
            items(first: 100, after: $after) {
              pageInfo { hasNextPage endCursor }
              nodes { id content { ... on Issue { url } } }
            }
          }
        }
      }' -f id="$1" -f after="$cursor")
    item=$(jq -r --arg u "$2" \
      '.data.node.items.nodes[] | select(.content.url == $u) | .id' <<<"$page")
    [ -n "$item" ] && { printf '%s\n' "$item"; return 0; }
    [ "$(jq -r '.data.node.items.pageInfo.hasNextPage' <<<"$page")" = "true" ] || return 1
    cursor=$(jq -r '.data.node.items.pageInfo.endCursor' <<<"$page")
  done
}
ITEM_ID=$(find_item "$PROJECT_ID" "$ISSUE_URL") || echo "issue is not on the board"
```

The cheaper route when you only have an issue and want to know *whether* it is
on a board — no paging at all, since the connection hangs off the issue:

```bash
gh api graphql -f query='
  query($owner:String!,$repo:String!,$num:Int!){
    repository(owner:$owner,name:$repo){ issue(number:$num){
      projectItems(first:10){ totalCount nodes { id project { number title } } } } }
  }' -f owner="$ORG" -f repo="$REPO" -F num=$N
```

## Update Single-Select Field

```bash
gh api graphql -f query='
  mutation($project: ID!, $item: ID!, $field: ID!, $value: String!) {
    updateProjectV2ItemFieldValue(input: {
      projectId: $project
      itemId: $item
      fieldId: $field
      value: {singleSelectOptionId: $value}
    }) {
      projectV2Item { id }
    }
  }' -f project="$PROJECT_ID" -f item="$ITEM_ID" \
     -f field="$FIELD_ID" -f value="$OPTION_ID"
```

> **Always `-f value=$OPTION_ID`, never `-F`.** Option IDs are frequently
> all-digits (e.g. `98236657`); `-F` coerces a digit-only value to Int and the
> mutation fails with `Variable $value of type String! was provided invalid
> value`. IDs containing letters happen to survive `-F` — don't rely on it.

## Update Text Field

```bash
gh api graphql -f query='
  mutation($project: ID!, $item: ID!, $field: ID!, $text: String!) {
    updateProjectV2ItemFieldValue(input: {
      projectId: $project
      itemId: $item
      fieldId: $field
      value: {text: $text}
    }) {
      projectV2Item { id }
    }
  }' -f project="$PROJECT_ID" -f item="$ITEM_ID" \
     -f field="$FIELD_ID" -f text="$VALUE"
```

## Update Number Field

```bash
gh api graphql -f query='
  mutation($project: ID!, $item: ID!, $field: ID!, $num: Float!) {
    updateProjectV2ItemFieldValue(input: {
      projectId: $project
      itemId: $item
      fieldId: $field
      value: {number: $num}
    }) {
      projectV2Item { id }
    }
  }' -f project="$PROJECT_ID" -f item="$ITEM_ID" \
     -f field="$FIELD_ID" -F num=$VALUE
```

## Update Date Field

```bash
gh api graphql -f query='
  mutation($project: ID!, $item: ID!, $field: ID!, $date: Date!) {
    updateProjectV2ItemFieldValue(input: {
      projectId: $project
      itemId: $item
      fieldId: $field
      value: {date: $date}
    }) {
      projectV2Item { id }
    }
  }' -f project="$PROJECT_ID" -f item="$ITEM_ID" \
     -f field="$FIELD_ID" -f date="2026-04-30"
```

## Board Query — All Items with Fields

Same paging rule as above: `totalCount` tells you whether one page was enough,
`pageInfo.endCursor` feeds `after:` for the next. An audit that skips this
reports on the first 100 items and calls it the board.

```bash
gh api graphql -f query='
  query($org: String!, $num: Int!, $after: String) {
    organization(login: $org) {
      projectV2(number: $num) {
        title
        items(first: 100, after: $after) {
          totalCount
          pageInfo { hasNextPage endCursor }
          nodes {
            id
            fieldValues(first: 20) {
              nodes {
                ... on ProjectV2ItemFieldSingleSelectValue {
                  name
                  field { ... on ProjectV2SingleSelectField { name } }
                }
                ... on ProjectV2ItemFieldTextValue {
                  text
                  field { ... on ProjectV2Field { name } }
                }
                ... on ProjectV2ItemFieldNumberValue {
                  number
                  field { ... on ProjectV2Field { name } }
                }
              }
            }
            content {
              ... on Issue {
                number title state stateReason url
                repository { name }
                assignees(first: 5) { nodes { login } }
                updatedAt
              }
            }
          }
        }
      }
    }
  }' -f org="$ORG" -F num=$NUM
```

## Field Schema Operations

Changing the board's own shape. No `gh project` subcommand covers this — GraphQL
only. Gate every one of these on an explicit human yes (see SKILL.md § Field
Schema Operations) and update `workflow/projects/{slug}.yaml` in the same change.

### Create a field

`dataType` is one of `TEXT`, `NUMBER`, `DATE`, `SINGLE_SELECT`, `ITERATION`.
Options are required for `SINGLE_SELECT`; `color` and `description` are
non-null in the input, so pass `GRAY` and `""` when you have nothing better.
Colors: `GRAY` `BLUE` `GREEN` `YELLOW` `ORANGE` `RED` `PINK` `PURPLE`.

```bash
gh api graphql -f query='
  mutation($project: ID!) {
    createProjectV2Field(input: {
      projectId: $project
      dataType: SINGLE_SELECT
      name: "Area"
      singleSelectOptions: [
        {name: "Platform", color: BLUE,  description: ""}
        {name: "Security", color: RED,   description: ""}
      ]
    }) {
      projectV2Field { ... on ProjectV2SingleSelectField { id name options { id name } } }
    }
  }' -f project="$PROJECT_ID"
```

### Rename single-select options without losing item values

**`singleSelectOptions` overwrites the whole list.** With an `id` → renamed in
place, item values follow. Without an `id` → created. Left out → **deleted**,
and every item holding it loses its value. So: read the live options, map them,
send all of them back. The list order is the board's column order.

```bash
# 1. read live options (never work from a snapshot in a config file)
gh api graphql -f query='
  query($id: ID!) { node(id: $id) { ... on ProjectV2SingleSelectField {
    id name options { id name color description } } } }' -f id="$FIELD_ID"

# 2. send the FULL list back, existing ids kept, new options without an id
gh api graphql -f query='
  mutation($field: ID!) {
    updateProjectV2Field(input: {
      fieldId: $field
      singleSelectOptions: [
        {id: "042f14fe", name: "🔴 Critical", color: GRAY, description: ""}
        {id: "2a84265d", name: "🟠 High",     color: GRAY, description: ""}
        {                name: "⚪ Backlog",  color: GRAY, description: ""}
      ]
    }) {
      projectV2Field { ... on ProjectV2SingleSelectField { options { id name } } }
    }
  }' -f field="$FIELD_ID"
```

Emoji in option names: build the mutation from the **live JSON** of the source
board rather than typing the names. Several of these glyphs carry a variation
selector (`🛠️` is `U+1F6E0 U+FE0F`, `🏗` is bare `U+1F3D7`) and a hand-typed
name that differs by one invisible codepoint creates a second, near-identical
option instead of renaming the first.

**Verification is on the items, not the field.** The mutation response confirms
the rename by definition. Re-read the items and compare the value distribution
against what you recorded before the change.

### Delete a field

Destructive and not undoable — the column and all its values go. Human gate.

```bash
gh api graphql -f query='
  mutation($field: ID!) {
    deleteProjectV2Field(input: {fieldId: $field}) {
      projectV2Field { ... on ProjectV2Field { id name } }
    }
  }' -f field="$FIELD_ID"
```

### What survives a rename

Item values, saved views and the board's built-in workflows all reference the
option **ID**, so an ID-preserving rename leaves them intact. What does *not*
follow: prose elsewhere that spells the old option name — task files, wiki
pages, tracker snapshots under `work/trackers/`. Grep for the old strings after
renaming, or they quietly become lies.

## Change Issue Close-Reason (no reopen)

To re-classify an **already-closed** issue's reason (e.g. `completed` →
`not_planned` during a declined-audit) without a noisy reopen/close cycle —
`closeIssue` is idempotent on a closed issue and just updates `stateReason`:

```bash
ISSUE_NODE_ID=$(gh api graphql -f query='
  query($owner:String!,$repo:String!,$num:Int!){
    repository(owner:$owner,name:$repo){ issue(number:$num){ id } }
  }' -f owner="$ORG" -f repo="$REPO" -F num=$N \
  --jq '.data.repository.issue.id')

gh api graphql -f query='
  mutation($id: ID!) {
    closeIssue(input: {issueId: $id, stateReason: NOT_PLANNED}) {
      issue { number state stateReason }
    }
  }' -F id="$ISSUE_NODE_ID"
```

`stateReason` accepts `NOT_PLANNED`, `COMPLETED`, `DUPLICATE`. For an OPEN
issue prefer `gh issue close --reason "not planned"`.

## Delete Draft Item

```bash
gh project item-delete $NUM --owner $ORG --id $DRAFT_ITEM_ID
```

Only works for drafts (items without a backing issue). Real issues
cannot be deleted from the board — use Status: Declined instead.
