# SPDX-License-Identifier: MIT
# Bridge — post-clone setup (Windows PowerShell)
#
# Ensures every supported AI agent can auto-discover the repo's skills by
# exposing the canonical top-level `skills\` folder at three discovery paths:
#   .claude\skills   (Claude Code)
#   .agents\skills   (Codex / Gemini CLI / Copilot CLI / Cursor)
#   .github\skills   (GitHub Copilot)
# All three ship as committed symlinks to `..\skills`; this script repairs any
# that a native-Windows-git checkout materialized as a plain file, then arms the
# git hooks so the deterministic pre-push leak guard is active.
#
# On Windows a real symlink needs Admin OR Developer Mode (Settings > Privacy &
# security > For developers). When that is unavailable, this script falls back
# per path to a directory junction, which needs no elevation and behaves the
# same for an agent's filesystem walk.
#
# macOS / Linux / WSL: use `bin/setup` instead.

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$absSource = (Resolve-Path "skills").Path

# Repairs one discovery path -> skills\ . Returns $true on success, $false on
# failure. Mirrors bash bin/setup's link_skills().
function Repair-SkillLink {
    param([string]$Target)          # e.g. .claude\skills

    $parent    = Split-Path -Parent $Target   # e.g. .claude
    $relSource = "..\skills"                   # relative target — mirrors the committed symlink

    # Already a working link?
    if (Test-Path $Target) {
        $item = Get-Item $Target -Force
        if ($item.LinkType -eq "SymbolicLink" -or $item.LinkType -eq "Junction") {
            Write-Host "OK   $Target is a working $($item.LinkType)"
            return $true
        }
        if ($item.PSIsContainer) {
            Write-Host "ERR  $Target exists as a real directory — manual review needed"
            Write-Host "     (expected: a link to skills\)"
            return $false
        }
        Write-Host "INFO Removing broken $Target (likely Windows-git symlink-as-textfile)"
        Remove-Item $Target -Force
    }

    # Ensure the parent dir (.claude / .agents / .github) exists
    New-Item -ItemType Directory -Path $parent -Force | Out-Null

    # Try a real symlink first (preserves git mode 120000 on commit)
    try {
        New-Item -ItemType SymbolicLink -Path $Target -Target $relSource -ErrorAction Stop | Out-Null
        Write-Host "OK   Created symlink $Target -> $relSource"
        return $true
    } catch {
        # Fall back to a directory junction — no elevation needed, no Developer Mode
        Write-Host "INFO Symlink for $Target failed (needs Admin or Developer Mode); trying junction..."
        try {
            New-Item -ItemType Junction -Path $Target -Target $absSource -ErrorAction Stop | Out-Null
            Write-Host "OK   Created junction $Target -> $absSource"
            return $true
        } catch {
            Write-Host "ERR  Could not create a symlink or junction for $Target"
            Write-Host "     Enable Developer Mode (Settings > Privacy & security > For developers)"
            Write-Host "     or run PowerShell as Administrator, then re-run this script."
            return $false
        }
    }
}

$ok     = $true
$linked = @()
foreach ($t in ".claude\skills", ".agents\skills", ".github\skills") {
    if (Repair-SkillLink $t) { $linked += $t } else { $ok = $false }
}

# Verify discovery through the primary (Claude Code) path
if (Test-Path ".claude\skills\bridge-onboard\SKILL.md") {
    Write-Host "OK   Skill discovery verified (.claude\skills\bridge-onboard\ resolves)"
} else {
    Write-Host "WARN Links created but skills not visible — check that skills\ exists at repo root"
    $ok = $false
}

# Arm the git hooks (rules/push-guard.md + the task-sync/logging backstop): route
# git hooks to the tracked dir. One setting wires BOTH scripts/hooks/pre-push (blocks
# publishing a user/* branch to a public upstream) AND scripts/hooks/pre-commit (the
# task-sync + continuous-logging reminder). Git for Windows runs these sh hooks via its
# bundled Git-Bash, so no chmod is needed. A hook that isn't on core.hooksPath is
# present but NOT wired.
# NOTE: do NOT `pre-commit install` — the pre-commit framework refuses when
# core.hooksPath is set; .pre-commit-config.yaml is for CI / manual runs only.
$hooksArmed = $false
if (Test-Path "scripts\hooks") {
    try {
        git config core.hooksPath scripts/hooks
        if ($LASTEXITCODE -eq 0) {
            $hooksArmed = $true
            Write-Host "OK   Git hooks armed (core.hooksPath -> scripts/hooks): pre-push guard + pre-commit task/log reminder"
        } else {
            throw "git config exited $LASTEXITCODE"
        }
    } catch {
        Write-Host "ERR  git config core.hooksPath failed — is git installed and is this a git repo?"
        $ok = $false
    }
} else {
    Write-Host "WARN scripts\hooks\ missing — git hooks NOT armed (pre-push leak guard inactive)"
    $ok = $false
}

# Honest, specific summary — never a blanket "OK" that could hide an unarmed guard.
Write-Host ""
if ($linked.Count -gt 0) {
    Write-Host "Linked to skills\ : $($linked -join ', ')"
}
if ($hooksArmed) {
    Write-Host "Pre-push leak guard: ARMED (core.hooksPath = scripts/hooks)"
} else {
    Write-Host "Pre-push leak guard: NOT ARMED — this clone could push a user/* branch to a public upstream unchecked."
}

if ($ok) {
    Write-Host "Setup complete."
    exit 0
} else {
    Write-Host "Setup finished WITH PROBLEMS — review the lines above before relying on this clone."
    exit 1
}
