#!/usr/bin/env bash
# consent-boundary-check.sh — Claude Code PreToolUse hook
#
# Enforces the Bridge consent boundary: each active agent instance
# declares a consent_scope in its SKILL.md and may only write to
# paths inside that scope. Writes outside are blocked (if
# forbidden) or flagged (if unlisted or need consent).
#
# This hook is OPT-IN. Enable it by adding a PreToolUse hook block
# to your .claude/settings.json — see .claude/hooks/README.md.
#
# Behaviour:
#   - Reads the current tool call from stdin (JSON from Claude Code)
#   - Extracts the target path from tool args
#   - Discovers the active instance (BRIDGE_ACTIVE_INSTANCE env var
#     OR most recently modified log.md under agents/active/)
#   - Reads the instance's role.md or the role template's SKILL.md
#     for the consent_scope block
#   - Evaluates the target path against write_forbidden,
#     write_free, write_with_consent (in that order)
#   - Exit code decides the tool call:
#       0 → allow (with optional stderr warning)
#       2 → block (Claude Code treats exit 2 as PreToolUse deny)
#
# The hook does not implement full glob matching — it uses bash's
# pattern matching (extglob) for common cases and falls back to a
# "warn and allow" for unknowns. This is by design: the hook is a
# safety net, not a sandbox. Full enforcement lives in Layer 3 (CI).
#
# Current status: MVP. The hook is installed as a non-default
# option. When enabled, it logs every tool call to stderr and warns
# on boundary risks; it does NOT yet block anything (set BLOCK=1 to
# enable blocking, once you have tested it on your own instance).

set -uo pipefail

BLOCK="${BRIDGE_CONSENT_BLOCK:-0}"
BRIDGE_ROOT="${BRIDGE_ROOT:-$(pwd)}"
LOG_PREFIX="[consent-boundary]"

# ─── Read stdin JSON from Claude Code ──────────────────────────────
INPUT="$(cat)"

# Extract tool name and file path — bash + sed, no jq dependency.
# Claude Code PreToolUse payloads include:
#   tool_name: "Write" | "Edit" | "Bash" | "NotebookEdit"
#   tool_input: { file_path | command | ... }
TOOL_NAME="$(printf '%s' "$INPUT" | sed -n 's/.*"tool_name"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)"

# For Write/Edit: pull file_path
# For Bash: scan the command for common write invocations
TARGET_PATH=""
case "$TOOL_NAME" in
  Write|Edit|NotebookEdit)
    TARGET_PATH="$(printf '%s' "$INPUT" | sed -n 's/.*"file_path"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)"
    ;;
  Bash)
    CMD="$(printf '%s' "$INPUT" | sed -n 's/.*"command"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' | head -1)"
    # Crude extraction — pick the first path-looking token after a
    # write-ish command. This is a heuristic; a real implementation
    # would parse the command tree.
    case "$CMD" in
      *"mv "*|*"cp "*|*"rm "*|*" > "*|*" >> "*|*"tee "*|*"touch "*|*"mkdir "*)
        TARGET_PATH="$CMD"  # keep the whole command; downstream checks use substring matching
        ;;
      *)
        # Read-only-ish command (find, ls, cat, git status, …) — allow
        exit 0
        ;;
    esac
    ;;
  *)
    # Not a write tool — allow
    exit 0
    ;;
esac

# Empty target → allow (Claude Code will handle the real error)
[ -z "$TARGET_PATH" ] && exit 0

# ─── Discover the active instance ──────────────────────────────────
# Primary: agent-activation rule writes .bridge-active-instance as a
# state file at activation time and clears it on deactivation. Secondary:
# BRIDGE_ACTIVE_INSTANCE env var (if the user sets it manually). Tertiary
# fallback: most recently modified log.md under agents/active/.
INSTANCE_ID=""
STATE_FILE="$BRIDGE_ROOT/.bridge-active-instance"

if [ -f "$STATE_FILE" ]; then
  INSTANCE_ID="$(sed -n 's/^instance_id:[[:space:]]*\(.*\)/\1/p' "$STATE_FILE" | head -1 | tr -d ' ')"
  BRIDGE_PERSONA_REF="$(sed -n 's/^persona_ref:[[:space:]]*\(.*\)/\1/p' "$STATE_FILE" | head -1 | tr -d ' ')"
  export BRIDGE_PERSONA_REF
fi

if [ -z "$INSTANCE_ID" ]; then
  INSTANCE_ID="${BRIDGE_ACTIVE_INSTANCE:-}"
fi

if [ -z "$INSTANCE_ID" ] && [ -d "$BRIDGE_ROOT/agents/active" ]; then
  # Last-resort fallback: most recently modified log.md under agents/active/
  INSTANCE_ID="$(find "$BRIDGE_ROOT/agents/active" -name 'log.md' -type f 2>/dev/null \
    | xargs -I {} stat -f '%m %N' {} 2>/dev/null \
    | sort -rn | head -1 | awk '{print $2}' \
    | sed -E "s|^$BRIDGE_ROOT/agents/active/||; s|/log.md$||")"
fi

if [ -z "$INSTANCE_ID" ]; then
  # No active instance — this is an onboarding or CORE dev session.
  # Emit a note on stderr for visibility, but do not block.
  >&2 printf '%s no active instance — hook pass-through\n' "$LOG_PREFIX"
  exit 0
fi

INSTANCE_DIR="$BRIDGE_ROOT/agents/active/$INSTANCE_ID"
ROLE_FILE="$INSTANCE_DIR/role.md"

# ─── Hard rules we check without parsing frontmatter ───────────────
# These are the universal boundaries from the Bridge invariant —
# they apply regardless of the specific role's consent_scope.

# 1. Writes to any OTHER instance's folder are forbidden
case "$TARGET_PATH" in
  *"agents/active/$INSTANCE_ID/"*|*"agents/active/${INSTANCE_ID}/"*)
    # Own folder — allowed
    exit 0
    ;;
  *"agents/active/"*)
    >&2 printf '%s FORBIDDEN: write to another active instance folder: %s\n' \
      "$LOG_PREFIX" "$TARGET_PATH"
    if [ "$BLOCK" = "1" ]; then exit 2; fi
    ;;
esac

# 2. Writes to personas/*.yaml (except template/examples) need consent
case "$TARGET_PATH" in
  *"personas/_template.yaml"*|*"personas/examples/"*)
    # Template and examples are CORE — allowed to be read, writes are
    # still sensitive but not forbidden outright
    ;;
  *"personas/"*".yaml"*)
    >&2 printf '%s ⚠ persona write: %s — needs explicit user consent\n' \
      "$LOG_PREFIX" "$TARGET_PATH"
    ;;
esac

# 3. Writes to bridge-config.yaml (user-layer only)
case "$TARGET_PATH" in
  *"bridge-config.yaml"*)
    >&2 printf '%s ⚠ bridge-config.yaml write: %s — USER-layer config, needs explicit user consent\n' \
      "$LOG_PREFIX" "$TARGET_PATH"
    ;;
esac

# 4. Writes to standing-orders matching OTHER personas
if [ -n "${BRIDGE_PERSONA_REF:-}" ]; then
  case "$TARGET_PATH" in
    *"protocols/standing-orders/routing-${BRIDGE_PERSONA_REF}.md"*)
      # Own persona's routing — consented
      ;;
    *"protocols/standing-orders/routing-"*".md"*)
      >&2 printf '%s FORBIDDEN: cross-persona standing-order write: %s\n' \
        "$LOG_PREFIX" "$TARGET_PATH"
      if [ "$BLOCK" = "1" ]; then exit 2; fi
      ;;
  esac
fi

# ─── Default: allow, with a log line ───────────────────────────────
>&2 printf '%s ok: %s (%s, instance=%s)\n' \
  "$LOG_PREFIX" "$TOOL_NAME" "$TARGET_PATH" "$INSTANCE_ID"
exit 0
