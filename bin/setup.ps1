# SPDX-License-Identifier: MIT
# Bridge — post-clone setup (Windows PowerShell)
#
# Ensures Claude Code can auto-discover the repo's skills by exposing
# `skills\` at `.claude\skills\`. On Windows this requires either:
#   - Admin PowerShell, OR
#   - Developer Mode enabled (Settings > Privacy & security > For developers)
#
# If symlinks are not permitted, this script falls back to a directory
# junction (mklink /J), which works without elevation and behaves the
# same way for Claude Code's filesystem walks.
#
# macOS / Linux / WSL: use `bin/setup` instead.

$ErrorActionPreference = "Stop"
$repo = Split-Path -Parent $PSScriptRoot
Set-Location $repo

$target = ".claude\skills"
$source = "..\skills"
$absSource = (Resolve-Path "skills").Path

# Already correct?
if (Test-Path $target) {
    $item = Get-Item $target -Force
    if ($item.LinkType -eq "SymbolicLink" -or $item.LinkType -eq "Junction") {
        Write-Host "OK  $target is a working $($item.LinkType)"
        exit 0
    }
    if ($item.PSIsContainer) {
        Write-Host "ERR $target exists as a real directory — manual review needed"
        exit 1
    }
    Write-Host "INFO Removing broken $target"
    Remove-Item $target -Force
}

# Ensure parent exists
New-Item -ItemType Directory -Path ".claude" -Force | Out-Null

# Try symlink first (preserves git mode 120000)
try {
    New-Item -ItemType SymbolicLink -Path $target -Target $source -ErrorAction Stop | Out-Null
    Write-Host "OK  Created symlink $target -> $source"
} catch {
    # Fall back to junction (no admin needed, works for directories)
    Write-Host "INFO Symlink creation failed (needs Admin or Developer Mode)."
    Write-Host "     Falling back to directory junction..."
    cmd /c mklink /J "$target" "$absSource" | Out-Null
    if (Test-Path $target) {
        Write-Host "OK  Created junction $target -> $absSource"
    } else {
        Write-Host "ERR Could not create symlink or junction."
        Write-Host "    Enable Developer Mode (Settings > Privacy & security > For developers)"
        Write-Host "    or run PowerShell as Administrator and re-run this script."
        exit 1
    }
}

# Verify discovery
if (Test-Path "$target\bridge-onboard\SKILL.md") {
    Write-Host "OK  Skill discovery verified ($target\bridge-onboard\ resolves)"
} else {
    Write-Host "WARN Link created but skills not visible — check that skills\ exists at repo root"
    exit 1
}
