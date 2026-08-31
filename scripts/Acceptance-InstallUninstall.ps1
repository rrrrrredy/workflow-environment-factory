param(
  [ValidateRange(1024, 65535)][int]$Port = 53121,
  [string]$ProtocolRoot = "",
  [string]$EvidencePath = "",
  [switch]$UseDockerStub
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

function Get-AcceptanceCodexVersion {
  $output = Invoke-CodexText @("--version")
  $lines = @(($output -split "\r?\n") | Where-Object { $_.Trim() -match '^codex-cli\s+\S+$' })
  if ($lines.Count -ne 1) { throw "Could not isolate one Codex CLI version line from command output." }
  return $lines[0].Trim()
}

function Start-AcceptancePortBlocker([string]$Node, [string]$ScriptPath, [int]$ListenPort) {
  $quotedScriptPath = '"' + $ScriptPath.Replace('"', '\"') + '"'
  $process = Start-Process -FilePath $Node -ArgumentList @($quotedScriptPath, [string]$ListenPort) -WindowStyle Hidden -PassThru
  for ($attempt = 0; $attempt -lt 40; $attempt += 1) {
    Start-Sleep -Milliseconds 125
    if ($process.HasExited) { break }
    if (@(Get-NetTCPConnection -LocalPort $ListenPort -State Listen -ErrorAction SilentlyContinue).Count -gt 0) { break }
  }
  Assert-Acceptance (-not $process.HasExited) "port blocker failed to start"
  Assert-Acceptance (@(Get-NetTCPConnection -LocalPort $ListenPort -State Listen -ErrorAction SilentlyContinue).Count -gt 0) "port blocker did not listen"
  return $process
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

function Get-AcceptanceSourceEvidence {
  $releaseSourcePath = Join-Path $script:WefRoot "release-source.json"
  if (Test-Path -LiteralPath $releaseSourcePath -PathType Leaf) {
    $releaseSource = Get-Content -LiteralPath $releaseSourcePath -Raw | ConvertFrom-Json
    $expectedVersion = (Get-Content -LiteralPath (Join-Path $script:WefRoot "plugins\workflow-environment-factory\.codex-plugin\plugin.json") -Raw | ConvertFrom-Json).version
    Assert-Acceptance ($releaseSource.schema_version -eq "product.release-source.v1") "release-source.json has an unsupported schema"
    Assert-Acceptance ($releaseSource.product -eq "workflow-environment-factory") "release-source.json names another product"
    Assert-Acceptance ($releaseSource.version -eq $expectedVersion) "release-source.json version does not match plugin.json"
    Assert-Acceptance ([string]$releaseSource.commit -match '^[0-9a-f]{40}$') "release-source.json has an invalid commit"
    return [pscustomobject]@{
      kind = "release_archive"
      commit = [string]$releaseSource.commit
      dirty = $null
    }
  }

  $git = Get-Command git -ErrorAction Stop
  $commit = (& $git.Source -C $script:WefRoot rev-parse HEAD | Out-String).Trim()
  Assert-Acceptance ($LASTEXITCODE -eq 0 -and $commit -match '^[0-9a-f]{40}$') "source checkout commit cannot be resolved"
  $dirty = -not [string]::IsNullOrWhiteSpace((& $git.Source -C $script:WefRoot status --porcelain | Out-String).Trim())
  Assert-Acceptance ($LASTEXITCODE -eq 0) "source checkout status cannot be resolved"
  return [pscustomobject]@{
    kind = "git_checkout"
    commit = $commit
    dirty = $dirty
  }
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
$environmentNames = @("CODEX_HOME", "WEF_DATA_DIR", "WEF_PORT", "WEF_HOST", "DOCKER_EXECUTABLE")
$previousEnvironment = @{}
foreach ($name in $environmentNames) {
  $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
}
$installationAttempted = $false
$blockerProcess = $null
$startedAt = [DateTimeOffset]::UtcNow

try {
  Assert-Acceptance (-not (Test-Path -LiteralPath $shortcutPath)) "the fresh user already has the product Startup shortcut"
  New-Item -ItemType Directory -Path $acceptanceCodexHome -Force | Out-Null
  [Environment]::SetEnvironmentVariable("CODEX_HOME", $acceptanceCodexHome, "Process")
  [Environment]::SetEnvironmentVariable("WEF_DATA_DIR", $acceptanceData, "Process")
  [Environment]::SetEnvironmentVariable("WEF_PORT", [string]$Port, "Process")
  [Environment]::SetEnvironmentVariable("WEF_HOST", "127.0.0.1", "Process")
  $dockerMode = "real_server"
  if ($UseDockerStub) {
    $dockerMode = "command_stub"
    $dockerCommandPath = Join-Path $acceptanceRoot "docker.cmd"
    $dockerStub = @'
@echo off
if /I "%~1"=="version" (
  echo 0.0.0-acceptance-stub
  exit /b 0
)
echo unsupported Docker acceptance command 1>&2
exit /b 2
'@
    [System.IO.File]::WriteAllText($dockerCommandPath, $dockerStub, [Text.ASCIIEncoding]::new())
  } else {
    $dockerCommand = Get-Command docker.exe -ErrorAction SilentlyContinue
    if ($null -eq $dockerCommand) { $dockerCommand = Get-Command docker -ErrorAction Stop }
    $dockerCommandPath = $dockerCommand.Source
  }
  [Environment]::SetEnvironmentVariable("DOCKER_EXECUTABLE", $dockerCommandPath, "Process")

  $initialPlugins = Invoke-CodexText @("plugin", "list")
  $initialMarketplaces = Invoke-CodexText @("plugin", "marketplace", "list")
  Assert-Acceptance (-not (Test-WefPluginInstalled $initialPlugins $selector)) "isolated Codex home is not plugin-clean"
  Assert-Acceptance (-not (Test-WefMarketplacePresent $initialMarketplaces $marketplace)) "isolated Codex home is not marketplace-clean"

  $blockerPath = Join-Path $acceptanceRoot "port-blocker.mjs"
  $blockerSource = @'
import { createServer } from "node:http";
const port = Number.parseInt(process.argv[2], 10);
createServer((_request, response) => {
  response.statusCode = 503;
  response.end("occupied");
}).listen(port, "127.0.0.1");
'@
  [System.IO.File]::WriteAllText($blockerPath, $blockerSource, [Text.UTF8Encoding]::new($false))
  $blockerProcess = Start-AcceptancePortBlocker (Resolve-WefNode) $blockerPath $Port
  $rollbackFailure = $null
  try {
    & (Join-Path $PSScriptRoot "Install.ps1") -EnableStartup -Port $Port -DataDir $acceptanceData -ProtocolRoot $ProtocolRoot
  } catch {
    $rollbackFailure = $_
  }
  Assert-Acceptance ($null -ne $rollbackFailure) "installer unexpectedly succeeded with its service port occupied"
  Assert-Acceptance ($rollbackFailure.Exception.Message -match "did not become healthy|already serving another application") "failure injection did not reach service startup"
  Assert-Acceptance (-not (Test-WefPluginInstalled (Invoke-CodexText @("plugin", "list")) $selector)) "failed install left the plugin installed"
  Assert-Acceptance (-not (Test-WefMarketplacePresent (Invoke-CodexText @("plugin", "marketplace", "list")) $marketplace)) "failed install left the marketplace registered"
  Assert-Acceptance (-not (Test-Path -LiteralPath $shortcutPath)) "failed install left a Startup shortcut"
  Assert-Acceptance (-not (Test-Path -LiteralPath $acceptanceData)) "failed install left its newly created data root"
  Stop-Process -Id $blockerProcess.Id
  $blockerProcess.WaitForExit()
  $blockerProcess = $null
  & (Join-Path $PSScriptRoot "Uninstall.ps1") -DeleteData -Port $Port -DataDir $acceptanceData
  Assert-Acceptance (-not (Test-Path -LiteralPath $acceptanceData)) "failed-install cleanup left product data"

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

  $shortcutHash = (Get-FileHash -LiteralPath $shortcutPath -Algorithm SHA256).Hash
  & (Join-Path $PSScriptRoot "Stop.ps1") -Port $Port -DataDir $acceptanceData | Out-Null
  $blockerProcess = Start-AcceptancePortBlocker (Resolve-WefNode) $blockerPath $Port
  $repairFailure = $null
  try {
    & (Join-Path $PSScriptRoot "Install.ps1") -Repair -EnableStartup -Port $Port -DataDir $acceptanceData -ProtocolRoot $ProtocolRoot
  } catch {
    $repairFailure = $_
  }
  Assert-Acceptance ($null -ne $repairFailure) "repair unexpectedly succeeded with its service port occupied"
  Assert-Acceptance ($repairFailure.Exception.Message -match "did not become healthy|already serving another application") "repair failure injection did not reach service startup"
  Assert-Acceptance (Test-WefPluginInstalled (Invoke-CodexText @("plugin", "list")) $selector) "failed repair did not restore the plugin"
  Assert-Acceptance (Test-WefMarketplacePresent (Invoke-CodexText @("plugin", "marketplace", "list")) $marketplace) "failed repair did not restore the marketplace"
  Assert-Acceptance ((Get-FileHash -LiteralPath $shortcutPath -Algorithm SHA256).Hash -eq $shortcutHash) "failed repair did not restore the previous Startup shortcut"
  Assert-Acceptance (Test-Path -LiteralPath $sentinel -PathType Leaf) "failed repair damaged existing product data"
  Stop-Process -Id $blockerProcess.Id
  $blockerProcess.WaitForExit()
  $blockerProcess = $null
  & (Join-Path $PSScriptRoot "Start.ps1") -Port $Port -DataDir $acceptanceData
  $restartedHealth = Get-WefHealth $Port
  Assert-Acceptance ($null -ne $restartedHealth -and $restartedHealth.product -eq "workflow-environment-factory") "service did not restart after failed repair"

  & (Join-Path $PSScriptRoot "Uninstall.ps1") -Port $Port -DataDir $acceptanceData
  Assert-Acceptance ($null -eq (Get-WefHealth $Port)) "service remained reachable after uninstall"
  Assert-Acceptance (Test-Path -LiteralPath $sentinel -PathType Leaf) "default uninstall did not preserve product data"
  Assert-Acceptance (-not (Test-Path -LiteralPath $shortcutPath)) "Startup shortcut remained after uninstall"
  Assert-Acceptance (-not (Test-WefPluginInstalled (Invoke-CodexText @("plugin", "list")) $selector)) "plugin remained installed after uninstall"
  Assert-Acceptance (-not (Test-WefMarketplacePresent (Invoke-CodexText @("plugin", "marketplace", "list")) $marketplace)) "marketplace remained after uninstall"
  & (Join-Path $PSScriptRoot "Inspect-Installation.ps1") -RequireAbsent -Port $Port -DataDir $acceptanceData | Out-Null

  & (Join-Path $PSScriptRoot "Install.ps1") -NoStart -Port $Port -DataDir $acceptanceData -ProtocolRoot $ProtocolRoot
  Assert-Acceptance (Test-Path -LiteralPath $sentinel -PathType Leaf) "reinstall did not preserve existing data"
  & (Join-Path $PSScriptRoot "Uninstall.ps1") -DeleteData -Port $Port -DataDir $acceptanceData
  Assert-Acceptance (-not (Test-Path -LiteralPath $acceptanceData)) "explicit data deletion left the acceptance data directory behind"
  Assert-Acceptance (-not (Test-Path -LiteralPath $shortcutPath)) "final uninstall left a Startup shortcut"
  Assert-Acceptance (-not (Test-WefPluginInstalled (Invoke-CodexText @("plugin", "list")) $selector)) "final uninstall left the plugin installed"
  Assert-Acceptance (-not (Test-WefMarketplacePresent (Invoke-CodexText @("plugin", "marketplace", "list")) $marketplace)) "final uninstall left the marketplace registered"
  & (Join-Path $PSScriptRoot "Inspect-Installation.ps1") -RequireAbsent -RequireNoData -Port $Port -DataDir $acceptanceData | Out-Null

  $dockerFormat = if ($UseDockerStub) { '{{.Server.Version}}' } else { '{{.Server.Version}}|{{.Server.Os}}|{{.Server.Arch}}' }
  $dockerVersion = (& $dockerCommandPath version --format $dockerFormat 2>&1 | Out-String).Trim()
  if ($LASTEXITCODE -ne 0) { throw "Docker became unavailable after installation acceptance: $dockerVersion" }
  $sourceEvidence = Get-AcceptanceSourceEvidence
  $evidence = [ordered]@{
    schema_version = "product.installation-acceptance.v3"
    product = "workflow-environment-factory"
    product_version = (Get-Content -LiteralPath (Join-Path $script:WefRoot "pyproject.toml") -Raw | Select-String -Pattern '(?m)^version\s*=\s*"([^"]+)"').Matches[0].Groups[1].Value
    tested_commit = $sourceEvidence.commit
    source_kind = $sourceEvidence.kind
    worktree_dirty = $sourceEvidence.dirty
    started_at = $startedAt.ToString("o")
    completed_at = [DateTimeOffset]::UtcNow.ToString("o")
    os = (Get-CimInstance Win32_OperatingSystem).Caption
    os_version = [Environment]::OSVersion.VersionString
    node_version = (& (Resolve-WefNode) -p "process.versions.node").Trim()
    python_version = (& (Resolve-WefPython) -c "import platform; print(platform.python_version())").Trim()
    codex_version = Get-AcceptanceCodexVersion
    docker_check = [ordered]@{
      mode = $dockerMode
      output = $dockerVersion
      same_host_server_proven = -not $UseDockerStub
    }
    checks = [ordered]@{
      clean_isolated_codex_home = $true
      failed_install_rolled_back = $true
      failed_repair_restored_existing_install = $true
      docker_prerequisite_path_passed = $true
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
      installation_state_audit_passed = $true
    }
    evidence_boundary = if ($UseDockerStub) {
      "This proves the Windows archive installation lifecycle with a Docker command stub. It does not prove Docker Desktop on the same Windows host. Real Linux-container task execution is proven separately by the Ubuntu Docker golden gate."
    } else {
      "This proves the Windows archive installation lifecycle and a responding Docker server on the same host. Linux-container task execution is proven separately by the Docker golden gate."
    }
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
  if ($null -ne $blockerProcess -and -not $blockerProcess.HasExited) {
    Stop-Process -Id $blockerProcess.Id -Force -ErrorAction SilentlyContinue
  }
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
