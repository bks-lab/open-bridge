# GraphQL Patterns for GitHub Projects V2

Fallback patterns when `gh project item-edit` is insufficient.

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

```bash
gh api graphql -f query='
  query($id: ID!) {
    node(id: $id) {
      ... on ProjectV2 {
        fields(first: 30) {
          nodes {
            ... on ProjectV2SingleSelectField {
              id name
              options { id name }
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

```bash
ITEM_ID=$(gh api graphql -f query='
  query($id: ID!) {
    node(id: $id) {
      ... on ProjectV2 {
        items(first: 100) {
          nodes {
            id
            content { ... on Issue { number url } }
          }
        }
      }
    }
  }' -f id="$PROJECT_ID" \
  --jq ".data.node.items.nodes[] | select(.content.url == \"$ISSUE_URL\") | .id")
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

```bash
gh api graphql -f query='
  query($org: String!, $num: Int!) {
    organization(login: $org) {
      projectV2(number: $num) {
        title
        items(first: 100) {
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
                number title state url
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

## Delete Draft Item

```bash
gh project item-delete $NUM --owner $ORG --id $DRAFT_ITEM_ID
```

Only works for drafts (items without a backing issue). Real issues
cannot be deleted from the board — use Status: Declined instead.
