# render-greeting.ps1 — Bridge greeting engine for Windows / PowerShell.
#
# The Windows sibling of render-motd.sh. Same three-layer model:
#   1. Engine (this file)        — generic, no instance literals. CORE.
#   2. Instance config           — a hashtable $BridgeGreetingConfig with the
#                                  per-instance brand + data source. USER, local.
#   3. Branding (logo + colour)  — a fastfetch-format logo asset under
#                                  assets/logos/, reused across both renderers.
#
# A profile that dot-sources this engine and a config, then calls
# Show-BridgeGreeting, renders an instance dashboard. No config → it greets
# cleanly with just the header (empty data → those sections don't render).
#
# Data providers are pluggable via $cfg.Provider. 'azure-devops' is implemented
# (WIQL work items, pipelines, repo commits via the `az` CLI + REST). 'github'
# is a documented extension point — add a Get-GhSection dispatch alongside
# Get-AdoSection and the rest of the engine is provider-agnostic.

$script:E = [char]27   # ESC, for ANSI sequences

# Emit UTF-8 so block-glyph logos + emoji survive (the OEM codepage replaces
# them with '?' when stdout is a non-console stream, e.g. piped or over SSH).
try {
    [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)
    $OutputEncoding = [System.Text.UTF8Encoding]::new($false)
} catch {}

# ── Logo ──────────────────────────────────────────────────────────────────
# Reuse the fastfetch logo format (assets/logos/*.txt) so one brand asset feeds
# both the bash/fastfetch renderer and this one. The format uses:
#   $1 / $2          colour anchors (primary / secondary)
#   \u{XXXX}         unicode escape for box-drawing glyphs
#   ·  (U+00B7)      padding placeholder → rendered as a space
function ConvertFrom-FastfetchLogo {
    param(
        [string]$Path,
        [string]$Color1 = '39',   # 39 = terminal default foreground (monochrome)
        [string]$Color2 = '39'
    )
    if (-not (Test-Path $Path)) { return @() }
    $c1 = "$($script:E)[${Color1}m"
    $c2 = "$($script:E)[${Color2}m"
    $reset = "$($script:E)[0m"
    $lines = @()
    foreach ($raw in (Get-Content -LiteralPath $Path -Encoding UTF8)) {
        # decode \u{XXXX} → char
        $line = [regex]::Replace($raw, '\\u\{([0-9A-Fa-f]+)\}', {
            param($m) [char][int]("0x" + $m.Groups[1].Value)
        })
        $line = $line -replace '·', ' '
        $line = $line -replace '\$1', $c1
        $line = $line -replace '\$2', $c2
        $lines += "  $line$reset"
    }
    return $lines
}

# ── Generic helpers ─────────────────────────────────────────────────────────
function Get-Greeting {
    $h = (Get-Date).Hour
    if ($h -ge 5 -and $h -lt 12)  { return 'Good morning' }
    if ($h -ge 12 -and $h -lt 18) { return 'Good afternoon' }
    return 'Good evening'
}

function Write-Hr {
    param([int]$Width = 74, [string]$Color = '34', [char]$Glyph = [char]0x2501)  # ━
    Write-Host "  $($script:E)[${Color}m$([string]$Glyph * $Width)$($script:E)[0m"
}

function Format-Truncate {
    param([string]$Text, [int]$Max)
    if ($null -eq $Text) { return '' }
    if ($Text.Length -gt $Max) { return $Text.Substring(0, $Max - 3) + '...' }
    return $Text
}

# Work-item type/state → icon + colour. Standard Agile/ADO values; an instance
# may extend the state map via $cfg.StateColors without touching the engine.
$script:TypeIcon  = @{ 'Bug' = '🐛'; 'User Story' = '📖'; 'Task' = '✅'; 'Test Case' = '🧪' }
$script:TypeColor = @{ 'Bug' = '31'; 'User Story' = '32'; 'Task' = '36'; 'Test Case' = '35' }
$script:StateColor = @{
    'In Development'    = '93'
    'Ready for Testing' = '96'
    'In Testing'        = '93'
    'OnHold'            = '90'
    'Design'            = '95'
}

# ── Azure DevOps provider ────────────────────────────────────────────────────
function Get-AdoToken {
    param([string]$ResourceId)
    $t = az account get-access-token --resource $ResourceId --query accessToken -o tsv 2>$null
    if ([string]::IsNullOrWhiteSpace($t)) { return $null }
    return $t
}

# Fetch all configured sections in parallel ThreadJobs; return a hashtable
# keyed by section index → result objects. Provider-specific.
function Get-AdoData {
    param([hashtable]$Cfg, [hashtable]$Hdr)
    $ado  = $Cfg.Ado
    $base = "https://dev.azure.com/$($ado.Org)/$($ado.Project)/_apis"
    $jobs = @{}

    for ($i = 0; $i -lt $Cfg.Sections.Count; $i++) {
        $sec = $Cfg.Sections[$i]
        switch ($sec.Kind) {
            'workitems' {
                $jobs[$i] = Start-ThreadJob -ArgumentList $Hdr, $base, $sec.Wiql {
                    param($h, $base, $wiql)
                    try {
                        $body = (@{ query = $wiql } | ConvertTo-Json)
                        $r = Invoke-RestMethod -Uri "$base/wit/wiql?`$top=15&api-version=7.1" -Headers $h -Method Post -Body $body -ErrorAction Stop
                        if ($r.workItems.Count -gt 0) {
                            $n   = [Math]::Min(14, $r.workItems.Count - 1)
                            $ids = ($r.workItems[0..$n] | ForEach-Object { $_.id }) -join ','
                            $f   = 'System.Id,System.Title,System.State,System.WorkItemType,System.AssignedTo'
                            $w   = Invoke-RestMethod -Uri "$base/wit/workitems?ids=$ids&fields=$f&api-version=7.1" -Headers $h -ErrorAction Stop
                            return $w.value
                        }
                    } catch {}
                    return @()
                }
            }
            'pipelines' {
                $top = if ($sec.Top) { $sec.Top } else { 5 }
                $jobs[$i] = Start-ThreadJob -ArgumentList $top {
                    param($top)
                    az pipelines runs list --top $top --query "[].{name:definition.name,result:result,state:state,branch:sourceBranch}" -o json 2>$null | ConvertFrom-Json
                }
            }
            'commits' {
                $branch = $sec.Branch; $top = if ($sec.Top) { $sec.Top } else { 5 }
                $jobs[$i] = Start-ThreadJob -ArgumentList $Hdr, $base, $ado.RepoId, $branch, $top {
                    param($h, $base, $repo, $branch, $top)
                    try {
                        $u = "$base/git/repositories/$repo/commits?searchCriteria.itemVersion.version=$branch&`$top=$top&api-version=7.0"
                        $r = Invoke-RestMethod -Uri $u -Headers $h -ErrorAction Stop
                        return $r.value
                    } catch {}
                    return @()
                }
            }
        }
    }

    $jobList = @($jobs.Values)
    if ($jobList.Count -gt 0) { $null = Wait-Job -Job $jobList -Timeout 20 }
    $data = @{}
    foreach ($k in $jobs.Keys) {
        $data["$k"] = @(Receive-Job -Job $jobs[$k] -ErrorAction SilentlyContinue)
    }
    if ($jobList.Count -gt 0) { Remove-Job -Job $jobList -Force -ErrorAction SilentlyContinue }
    return $data
}

# ── Section renderers ─────────────────────────────────────────────────────────
function Show-WorkItems {
    param($Items, [hashtable]$Sec, [hashtable]$StateColors)
    if (-not $Items -or @($Items).Count -eq 0) {
        $empty = if ($Sec.Empty) { $Sec.Empty } else { 'Nothing here.' }
        Write-Host "  $($script:E)[32m$empty$($script:E)[0m"
        return
    }
    foreach ($item in $Items) {
        $type  = $item.fields.'System.WorkItemType'
        $state = $item.fields.'System.State'
        $title = $item.fields.'System.Title'
        $icon  = if ($script:TypeIcon.ContainsKey($type))  { $script:TypeIcon[$type] }  else { '📌' }
        $tc    = if ($script:TypeColor.ContainsKey($type)) { $script:TypeColor[$type] } else { '37' }
        $sc    = if ($StateColors.ContainsKey($state)) { $StateColors[$state] } else { '37' }
        if ($Sec.ShowAssignee) {
            $a = $item.fields.'System.AssignedTo'
            if ($a -is [System.Management.Automation.PSCustomObject]) { $a = $a.displayName } else { $a = 'Unassigned' }
            $a = Format-Truncate $a 18
            $title = Format-Truncate $title 44
            Write-Host "  $icon $($script:E)[${tc}m#$($item.id)$($script:E)[0m $($script:E)[90m[$($script:E)[${sc}m$state$($script:E)[90m]$($script:E)[0m $($script:E)[90m($a)$($script:E)[0m $title"
        } else {
            $title = Format-Truncate $title 52
            Write-Host "  $icon $($script:E)[${tc}m#$($item.id)$($script:E)[0m $($script:E)[90m[$($script:E)[${sc}m$state$($script:E)[90m]$($script:E)[0m $title"
        }
    }
}

function Show-Pipelines {
    param($Pipes)
    if (-not $Pipes) { Write-Host "  $($script:E)[33m⚠  Pipelines not available$($script:E)[0m"; return }
    foreach ($run in $Pipes) {
        $icon = switch ($run.result) { 'succeeded' {'✅'} 'failed' {'❌'} 'canceled' {'⚫'} $null {'🔄'} default {'❓'} }
        $rc   = switch ($run.result) { 'succeeded' {'32'} 'failed' {'31'} 'canceled' {'90'} $null {'33'} default {'37'} }
        $name = Format-Truncate $run.name 40
        $branch = ($run.branch -replace 'refs/(heads|pull)/', '') -replace '/merge', ''
        $branch = Format-Truncate $branch 25
        Write-Host "  $icon $($script:E)[${rc}m$($name.PadRight(42))$($script:E)[0m $($script:E)[90m$branch$($script:E)[0m"
    }
}

function Show-Commits {
    param($Commits)
    if (-not $Commits) { Write-Host "  $($script:E)[33m⚠  Commits not available$($script:E)[0m"; return }
    foreach ($c in $Commits) {
        $sha    = $c.commitId.Substring(0, 7)
        $msg    = Format-Truncate ($c.comment.Split("`n")[0]) 54
        $author = Format-Truncate $c.author.name 22
        Write-Host "  $($script:E)[33m$sha$($script:E)[0m $($script:E)[90m$($author.PadRight(24))$($script:E)[0m $msg"
    }
}

# ── Orchestrator ──────────────────────────────────────────────────────────────
function Show-BridgeGreeting {
    param([hashtable]$Config)

    if (-not $Config) { Write-Host "  $(Get-Greeting)."; return }
    $cfg = $Config
    $E = $script:E

    # auto-cd if configured (kept here so the profile shim stays one line)
    if ($cfg.WorkDir -and (Test-Path $cfg.WorkDir)) { Set-Location $cfg.WorkDir }

    Write-Host ''
    # Logo — branding belongs to the instance (logo asset + colour from config).
    $c1 = if ($cfg.Color1) { $cfg.Color1 } elseif ($cfg.Color) { $cfg.Color } else { '39' }
    $c2 = if ($cfg.Color2) { $cfg.Color2 } else { $c1 }
    if ($cfg.Logo -and (Test-Path $cfg.Logo)) {
        foreach ($l in (ConvertFrom-FastfetchLogo -Path $cfg.Logo -Color1 $c1 -Color2 $c2)) { Write-Host $l }
        Write-Host ''
    } elseif ($cfg.LogoLines) {
        foreach ($l in $cfg.LogoLines) { Write-Host "  $E[${c1}m$l$E[0m" }
        Write-Host ''
    }

    $label = if ($cfg.Label) { $cfg.Label } else { 'Bridge' }
    $dt = Get-Date -Format 'dddd, dd. MMMM yyyy  HH:mm'
    Write-Host "  $E[1;${c1}m $(Get-Greeting), $label$E[0m  $E[90m●  $dt$E[0m"
    Write-Hr -Color $c1
    Write-Host ''

    if (-not $cfg.Sections -or $cfg.Sections.Count -eq 0) { return }

    # ── Cache (default 1h) ──
    $cacheFile = if ($cfg.CacheFile) { $cfg.CacheFile } else { "$env:TEMP\bridge-greeting-cache.json" }
    $ttl       = if ($cfg.CacheTtlSeconds) { $cfg.CacheTtlSeconds } else { 3600 }
    $ageS = if (Test-Path $cacheFile) { ((Get-Date) - (Get-Item $cacheFile).LastWriteTime).TotalSeconds } else { [double]::MaxValue }

    if ($ageS -lt $ttl) {
        Write-Host "  $E[90m⚡ Data from cache (loaded $([int]($ageS/60)) min ago)$E[0m"; Write-Host ''
        $data = Get-Content $cacheFile -Raw | ConvertFrom-Json
    } else {
        $data = $null
        if ($cfg.Provider -eq 'azure-devops') {
            $token = Get-AdoToken -ResourceId $cfg.Ado.ResourceId
            if (-not $token) {
                Write-Host "  $E[33m⚠  Not authenticated — run 'az login'$E[0m"; Write-Host ''; return
            }
            $hdr = @{ Authorization = "Bearer $token"; 'Content-Type' = 'application/json' }
            $data = Get-AdoData -Cfg $cfg -Hdr $hdr
        } else {
            Write-Host "  $E[33m⚠  Unknown provider '$($cfg.Provider)'$E[0m"; Write-Host ''; return
        }
        $data | ConvertTo-Json -Depth 12 | Set-Content $cacheFile -Encoding UTF8
    }

    $stateColors = $script:StateColor.Clone()
    if ($cfg.StateColors) { foreach ($k in $cfg.StateColors.Keys) { $stateColors[$k] = $cfg.StateColors[$k] } }

    # ── Render sections in declared order ──
    for ($i = 0; $i -lt $cfg.Sections.Count; $i++) {
        $sec = $cfg.Sections[$i]
        # cache is JSON → keys are strings; fresh fetch → keys are strings too
        $items = $data."$i"
        Write-Host "  $E[1;33m$($sec.Title)$E[0m"
        Write-Host "  $E[90m$([string]([char]0x2500) * 74)$E[0m"   # ─
        switch ($sec.Kind) {
            'workitems' { Show-WorkItems -Items $items -Sec $sec -StateColors $stateColors }
            'pipelines' { Show-Pipelines -Pipes $items }
            'commits'   { Show-Commits -Commits $items }
        }
        Write-Host ''
    }

    Write-Hr -Color $c1
    Write-Host "  $E[90m📁 $(Get-Location)  ●  PowerShell $($PSVersionTable.PSVersion)$E[0m"
    Write-Hr -Color $c1
    Write-Host ''
}
