param(
  [ValidateRange(1024, 65535)][int]$Port = 53121,
  [string]$ProtocolRoot = "",
  [string]$EvidencePath = ""
)

. (Join-Path $PSScriptRoot "Common.ps1")

if ($env:OS -ne "Windows_NT") { throw "Installation acceptance requires a fresh Windows environment." }

function Assert-Acceptance([bool]$Condition, [string]$Message) {
  if (-not $Condition) { throw "INSTALLATION ACCEPTANCE FAILED: $Message" }
}

function Invoke-CodexText([string[]]$Arguments) {
  $command = Get-Command codex.exe -ErrorAction SilentlyContinue
  if ($null -eq $command) { $command = Get-Command codex -ErrorAction Stop }
  $text = (& $command.Source @Arguments 2>&1 | Out-String)
  if ($LASTEXITCODE -ne 0) { throw "codex $($Arguments -join ' ') failed:`n$text" }
  return $text
}

function Remove-TestRoot([string]$Path, [string]$AllowedParent) {
  if (-not (Test-Path -LiteralPath $Path -PathType Container)) { return }
  $resolved = (Resolve-Path -LiteralPath $Path).Path.TrimEnd('\')
  $parent = [System.IO.Path]::GetFullPath($AllowedParent).TrimEnd('\') + '\'
  if (-not $resolved.StartsWith($parent, [StringComparison]::OrdinalIgnoreCase) -or
      -not ([System.IO.Path]::GetFileName($resolved)).StartsWith("wef-install-acceptance-", [StringComparison]::OrdinalIgnoreCase)) {
    throw "Refusing to remove an unsafe acceptance directory: $resolved"
  }
  Remove-Item -LiteralPath $resolved -Recurse -Force
}

$tempParent = if ([string]::IsNullOrWhiteSpace($env:RUNNER_TEMP)) {
  [System.IO.Path]::GetTempPath()
} else {
  [System.IO.Path]::GetFullPath($env:RUNNER_TEMP)
}
$acceptanceRoot = Join-Path $tempParent "wef-install-acceptance-$([Guid]::NewGuid().ToString('N'))"
$acceptanceCodexHome = Join-Path $acceptanceRoot "codex-home"
$acceptanceData = Join-Path $acceptanceRoot "product-data"
$selector = "workflow-environment-factory@workflow-environment-factory"
$marketplace = "workflow-environment-factory"
$startupDirectory = [Environment]::GetFolderPath("Startup")
$shortcutPath = Join-Path $startupDirectory "Workflow Environment Factory.lnk"
$environmentNames = @("CODEX_HOME", "WEF_DATA_DIR", "WEF_PORT")
$previousEnvironment = @{}
foreach ($name in $environmentNames) {
  $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}
$installationAttempted = $false
$startedAt = [DateTimeOffset]::UtcNow

try {
  Assert-Acceptance (-not (Test-Path -LiteralPath $shortcutPath)) "the fresh user already has the product Startup shortcut"
  New-Item -ItemType Directory -Path $acceptanceCodexHome -Force | Out-Null
  [Environment]::SetEnvironmentVariable("CODEX_HOME", $acceptanceCodexHome, "Process")
  [Environment]::SetEnvironmentVariable("WEF_DATA_DIR", $acceptanceData, "Process")
  [Environment]::SetEnvironmentVariable("WEF_PORT", [string]$Port, "Process")

  $initialPlugins = Invoke-CodexText @("plugin", "list")
  $initialMarketplaces = Invoke-CodexText @("plugin", "marketplace", "list")
  Assert-Acceptance (-not (Test-WefPluginInstalled $initialPlugins $selector)) "isolated Codex home is not plugin-clean"
  Assert-Acceptance (-not (Test-WefMarketplacePresent $initialMarketplaces $marketplace)) "isolated Codex home is not marketplace-clean"

  $installationAttempted = $true
  & (Join-Path $PSScriptRoot "Install.ps1") -EnableStartup -Port $Port -DataDir $acceptanceData -ProtocolRoot $ProtocolRoot
  Assert-Acceptance (Test-Path -LiteralPath $shortcutPath -PathType Leaf) "installer did not create the requested Startup shortcut"
  $health = Get-WefHealth $Port
  Assert-Acceptance ($null -ne $health -and $health.product -eq "workflow-environment-factory") "installed service is not healthy"
  $listeners = @(Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction Stop)
  Assert-Acceptance ($listeners.Count -gt 0) "service has no listening socket"
  Assert-Acceptance (@($listeners | Where-Object { $_.LocalAddress -notin @("127.0.0.1", "::1") }).Count -eq 0) "service is listening beyond loopback"
  Assert-Acceptance (Test-WefPluginInstalled (Invoke-CodexText @("plugin", "list")) $selector) "plugin was not installed"
  Assert-Acceptance (Test-WefMarketplacePresent (Invoke-CodexText @("plugin", "marketplace", "list")) $marketplace) "marketplace was not registered"
  $sentinel = Join-Path $acceptanceData "preserve-me.txt"
  [System.IO.File]::WriteAllText($sentinel, "installation acceptance sentinel`n")

  & (Join-Path $PSScriptRoot "Uninstall.ps1") -Port $Port -DataDir $acceptanceData
  Assert-Acceptance ($null -eq (Get-WefHealth $Port)) "service remained reachable after uninstall"
  Assert-Acceptance (Test-Path -LiteralPath $sentinel -PathType Leaf) "default uninstall did not preserve product data"
  Assert-Acceptance (-not (Test-Path -LiteralPath $shortcutPath)) "Startup shortcut remained after uninstall"
  Assert-Acceptance (-not (Test-WefPluginInstalled (Invoke-CodexText @("plugin", "list")) $selector)) "plugin remained installed after uninstall"
  Assert-Acceptance (-not (Test-WefMarketplacePresent (Invoke-CodexText @("plugin", "marketplace", "list")) $marketplace)) "marketplace remained after uninstall"

  & (Join-Path $PSScriptRoot "Install.ps1") -NoStart -Port $Port -DataDir $acceptanceData -ProtocolRoot $ProtocolRoot
  Assert-Acceptance (Test-Path -LiteralPath $sentinel -PathType Leaf) "reinstall did not preserve existing data"
  & (Join-Path $PSScriptRoot "Uninstall.ps1") -DeleteData -Port $Port -DataDir $acceptanceData
  Assert-Acceptance (-not (Test-Path -LiteralPath $acceptanceData)) "explicit data deletion left the acceptance data directory behind"
  Assert-Acceptance (-not (Test-Path -LiteralPath $shortcutPath)) "final uninstall left a Startup shortcut"
  Assert-Acceptance (-not (Test-WefPluginInstalled (Invoke-CodexText @("plugin", "list")) $selector)) "final uninstall left the plugin installed"
  Assert-Acceptance (-not (Test-WefMarketplacePresent (Invoke-CodexText @("plugin", "marketplace", "list")) $marketplace)) "final uninstall left the marketplace registered"

  $dockerVersion = (& docker version --format '{{.Server.Version}}|{{.Server.Os}}|{{.Server.Arch}}' 2>&1 | Out-String).Trim()
  if ($LASTEXITCODE -ne 0) { throw "Docker became unavailable after installation acceptance: $dockerVersion" }
  $worktreeDirty = -not [string]::IsNullOrWhiteSpace((& git -C $script:WefRoot status --porcelain | Out-String).Trim())
  $evidence = [ordered]@{
    schema_version = "product.installation-acceptance.v1"
    product = "workflow-environment-factory"
    product_version = (Get-Content -LiteralPath (Join-Path $script:WefRoot "pyproject.toml") -Raw | Select-String -Pattern '(?m)^version\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
    tested_commit = (& git -C $script:WefRoot rev-parse HEAD).Trim()
    worktree_dirty = $worktreeDirty
    started_at = $startedAt.ToString("o")
    completed_at = [DateTimeOffset]::UtcNow.ToString("o")
    os = (Get-CimInstance Win32_OperatingSystem).Caption
    os_version = [Environment]::OSVersion.VersionString
    node_version = (& (Resolve-WefNode) -p "process.versions.node").Trim()
    python_version = (& (Resolve-WefPython) -c "import platform; print(platform.python_version())").Trim()
    codex_version = (Invoke-CodexText @("--version")).Trim()
    docker_server = $dockerVersion
    checks = [ordered]@{
      clean_isolated_codex_home = $true
      docker_doctor_passed = $true
      service_started = $true
      loopback_only = $true
      plugin_installed = $true
      marketplace_registered = $true
      startup_created_and_removed = $true
      default_uninstall_preserved_data = $true
      reinstall_preserved_data = $true
      explicit_delete_removed_data = $true
      final_plugin_absent = $true
      final_marketplace_absent = $true
      final_service_absent = $true
    }
    evidence_boundary = "This proves the Windows installation lifecycle and a responding Docker server. Linux-container task execution is proven separately by the Docker golden gate."
  }
  $json = $evidence | ConvertTo-Json -Depth 6
  if (-not [string]::IsNullOrWhiteSpace($EvidencePath)) {
    $fullEvidencePath = [System.IO.Path]::GetFullPath($EvidencePath)
    $evidenceDirectory = Split-Path -Parent $fullEvidencePath
    New-Item -ItemType Directory -Path $evidenceDirectory -Force | Out-Null
    [System.IO.File]::WriteAllText($fullEvidencePath, "$json`n")
    Write-Host "Installation evidence: $fullEvidencePath"
  }
  Write-Output $json
} finally {
  try {
    if ($installationAttempted) {
      & (Join-Path $PSScriptRoot "Uninstall.ps1") -DeleteData -Port $Port -DataDir $acceptanceData 2>$null | Out-Null
    }
  } catch {
    Write-Warning "Fallback uninstall needs attention: $($_.Exception.Message)"
  }
  foreach ($name in $environmentNames) {
    [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], "Process")
  }
  Remove-TestRoot $acceptanceRoot $tempParent
}
