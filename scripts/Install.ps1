param(
  [switch]$EnableStartup,
  [switch]$NoStart,
  [switch]$Open,
  [switch]$Repair,
  [ValidateRange(1024, 65535)][int]$Port = 43121,
  [string]$DataDir = "",
  [string]$ProtocolRoot = "",
  [string]$MarketplaceSource = ""
)

. (Join-Path $PSScriptRoot "Common.ps1")

if ($env:OS -ne "Windows_NT") { throw "The 0.1 installer supports Windows 11 only." }
Resolve-WefNode | Out-Null
Resolve-WefPython | Out-Null
$resolvedDataDir = Get-WefDataDir $DataDir
$codexCommand = Get-Command codex.exe -ErrorAction SilentlyContinue
if ($null -eq $codexCommand) { $codexCommand = Get-Command codex -ErrorAction SilentlyContinue }
if ($null -eq $codexCommand) { throw "Codex CLI is required and was not found on PATH." }

Write-Host "Checking the local runtime, protocol schemas, plugin, and focused product contracts..."
& (Join-Path $PSScriptRoot "Check.ps1") -InstallDependencies -ProtocolRoot $ProtocolRoot
if ($LASTEXITCODE -ne 0) { throw "Release checks failed; nothing was installed." }
$venvPython = Get-WefVenvPython
$previousProtocol = [Environment]::GetEnvironmentVariable("WEF_PROTOCOL_SCHEMA_DIR", "Process")
$previousDataDir = [Environment]::GetEnvironmentVariable("WEF_DATA_DIR", "Process")
$previousPort = [Environment]::GetEnvironmentVariable("WEF_PORT", "Process")
[Environment]::SetEnvironmentVariable("WEF_PROTOCOL_SCHEMA_DIR", (Get-WefProtocolDir), "Process")
[Environment]::SetEnvironmentVariable("WEF_DATA_DIR", $resolvedDataDir, "Process")
[Environment]::SetEnvironmentVariable("WEF_PORT", [string]$Port, "Process")
try {
  & $venvPython -m workflow_environment_factory.cli doctor
  if ($LASTEXITCODE -ne 0) { throw "Docker/Codex prerequisites are not ready; nothing was installed." }
} finally {
  [Environment]::SetEnvironmentVariable("WEF_PROTOCOL_SCHEMA_DIR", $previousProtocol, "Process")
  [Environment]::SetEnvironmentVariable("WEF_DATA_DIR", $previousDataDir, "Process")
  [Environment]::SetEnvironmentVariable("WEF_PORT", $previousPort, "Process")
}
$sourceCandidate = if ([string]::IsNullOrWhiteSpace($MarketplaceSource)) { $script:WefRoot } else { $MarketplaceSource }
$source = [System.IO.Path]::GetFullPath($sourceCandidate).TrimEnd('\')
$marketplaceName = "workflow-environment-factory"
$pluginSelector = "workflow-environment-factory@workflow-environment-factory"
$expectedPluginPath = [System.IO.Path]::GetFullPath(
  (Join-Path $source "plugins\workflow-environment-factory")
).TrimEnd('\')
$pluginManifest = Get-Content -LiteralPath (Join-Path $expectedPluginPath ".codex-plugin\plugin.json") -Raw |
  ConvertFrom-Json
$expectedPluginVersion = [string]$pluginManifest.version
$marketplaceAdded = $false
$pluginAdded = $false
$shortcutCreated = $false
$shortcutWasPresent = $false
$shortcutBackupPath = $null
$serviceWasRunning = $false
$shortcutPath = $null
$marketplaceRemovedForRepair = $false
$pluginRemovedForRepair = $false
$dataRootExisted = Test-Path -LiteralPath $resolvedDataDir
$dataRootCreated = $false

if ($EnableStartup) {
  $shortcutPath = Get-WefStartupShortcutPath
  $shortcutWasPresent = Test-Path -LiteralPath $shortcutPath -PathType Leaf
  Assert-WefStartupShortcutAvailable $shortcutPath
}

try {
  Initialize-WefDataRoot $resolvedDataDir
  $dataRootCreated = -not $dataRootExisted
  $existingHealth = Get-WefHealth $Port
  $serviceWasRunning = $null -ne $existingHealth -and $existingHealth.product -eq "workflow-environment-factory"
  $marketplaceOutput = (& $codexCommand.Source plugin marketplace list 2>&1 | Out-String)
  $marketplaceRecord = Get-WefMarketplaceRecord $marketplaceOutput $marketplaceName
  $pluginOutput = (& $codexCommand.Source plugin list 2>&1 | Out-String)
  $pluginRecord = Get-WefPluginRecord $pluginOutput $pluginSelector
  Assert-WefCodexOwnership $marketplaceRecord $pluginRecord $source $expectedPluginPath $expectedPluginVersion
  $marketplacePresent = $null -ne $marketplaceRecord
  $pluginPresent = $null -ne $pluginRecord

  if ($Repair -and $pluginPresent) {
    & $codexCommand.Source plugin remove $pluginSelector
    if ($LASTEXITCODE -ne 0) { throw "Could not remove the existing plugin during repair." }
    $pluginRemovedForRepair = $true
    $pluginPresent = $false
  }
  if ($Repair -and $marketplacePresent) {
    & $codexCommand.Source plugin marketplace remove $marketplaceName
    if ($LASTEXITCODE -ne 0) { throw "Could not remove the existing marketplace during repair." }
    $marketplaceRemovedForRepair = $true
    $marketplacePresent = $false
  }
  if (-not $marketplacePresent) {
    & $codexCommand.Source plugin marketplace add $source
    if ($LASTEXITCODE -ne 0) { throw "Could not add the Workflow Environment Factory marketplace." }
    $marketplaceAdded = $true
  }
  if (-not $pluginPresent) {
    & $codexCommand.Source plugin add $pluginSelector
    if ($LASTEXITCODE -ne 0) { throw "Codex plugin installation failed." }
    $pluginAdded = $true
  }
  $retainedMarketplace = Get-WefMarketplaceRecord (
    (& $codexCommand.Source plugin marketplace list 2>&1 | Out-String)
  ) $marketplaceName
  $retainedPlugin = Get-WefPluginRecord (
    (& $codexCommand.Source plugin list 2>&1 | Out-String)
  ) $pluginSelector
  Assert-WefCodexOwnership $retainedMarketplace $retainedPlugin $source $expectedPluginPath $expectedPluginVersion
  if ($null -eq $retainedMarketplace -or $null -eq $retainedPlugin) {
    throw "Codex did not retain the exact Workflow Environment Factory marketplace and plugin registration."
  }

  if ($EnableStartup) {
    $shortcutCreated = -not $shortcutWasPresent
    if ($shortcutWasPresent) {
      $shortcutBackupPath = Join-Path ([System.IO.Path]::GetTempPath()) "wef-startup-$([Guid]::NewGuid().ToString('N')).lnk"
      Copy-Item -LiteralPath $shortcutPath -Destination $shortcutBackupPath
    }
    $powerShellCommand = Get-Command pwsh.exe -ErrorAction SilentlyContinue
    if ($null -eq $powerShellCommand) { $powerShellCommand = Get-Command powershell.exe -ErrorAction Stop }
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($shortcutPath)
    $shortcut.TargetPath = $powerShellCommand.Source
    $shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $PSScriptRoot 'Start.ps1')`" -Port $Port -DataDir `"$resolvedDataDir`""
    $shortcut.WorkingDirectory = $script:WefRoot
    $shortcut.WindowStyle = 7
    $shortcut.Description = Get-WefStartupShortcutDescription
    $shortcut.Save()
    Write-Host "Enabled current-user startup: $shortcutPath"
  }

  if (-not $NoStart) { & (Join-Path $PSScriptRoot "Start.ps1") -Open:$Open -Port $Port -DataDir $resolvedDataDir }
  Write-WefInstallationReceipt $resolvedDataDir $source $expectedPluginPath $expectedPluginVersion
  Write-Host "Workflow Environment Factory is installed. Restart Codex to load its simulator MCP tools and Skill."
  Write-Host "Uninstall with .\scripts\Uninstall.ps1; product data is preserved unless -DeleteData is explicitly supplied."
} catch {
  $installationError = $_
  $rollbackErrors = [System.Collections.Generic.List[string]]::new()
  if (-not $serviceWasRunning) {
    $healthAfterFailure = Get-WefHealth $Port
    if ($null -ne $healthAfterFailure -and $healthAfterFailure.product -eq "workflow-environment-factory") {
      try { & (Join-Path $PSScriptRoot "Stop.ps1") -Port $Port -DataDir $resolvedDataDir | Out-Null }
      catch { $rollbackErrors.Add("service: $($_.Exception.Message)") }
    }
  }
  if ($null -ne $shortcutPath) {
    try {
      if ($shortcutWasPresent -and $null -ne $shortcutBackupPath -and (Test-Path -LiteralPath $shortcutBackupPath -PathType Leaf)) {
        Copy-Item -LiteralPath $shortcutBackupPath -Destination $shortcutPath -Force
      } elseif ($shortcutCreated -and (Test-Path -LiteralPath $shortcutPath -PathType Leaf)) {
        Remove-Item -LiteralPath $shortcutPath -Force
      }
    } catch { $rollbackErrors.Add("Startup shortcut: $($_.Exception.Message)") }
  }
  if ($pluginAdded) {
    try {
      & $codexCommand.Source plugin remove $pluginSelector 2>$null | Out-Null
      if ($LASTEXITCODE -ne 0) { throw "Codex plugin removal exited with $LASTEXITCODE." }
    } catch { $rollbackErrors.Add("plugin: $($_.Exception.Message)") }
  }
  if ($marketplaceAdded) {
    try {
      & $codexCommand.Source plugin marketplace remove $marketplaceName 2>$null | Out-Null
      if ($LASTEXITCODE -ne 0) { throw "Codex marketplace removal exited with $LASTEXITCODE." }
    } catch { $rollbackErrors.Add("marketplace: $($_.Exception.Message)") }
  }
  if ($marketplaceRemovedForRepair) {
    try {
      & $codexCommand.Source plugin marketplace add $source 2>$null | Out-Null
      if ($LASTEXITCODE -ne 0) { throw "Codex marketplace restoration exited with $LASTEXITCODE." }
    } catch { $rollbackErrors.Add("restore marketplace: $($_.Exception.Message)") }
  }
  if ($pluginRemovedForRepair) {
    try {
      & $codexCommand.Source plugin add $pluginSelector 2>$null | Out-Null
      if ($LASTEXITCODE -ne 0) { throw "Codex plugin restoration exited with $LASTEXITCODE." }
    } catch { $rollbackErrors.Add("restore plugin: $($_.Exception.Message)") }
  }
  if ($dataRootCreated -and (Test-Path -LiteralPath $resolvedDataDir -PathType Container)) {
    try { Remove-WefDataRootCreatedByFailedInstall $resolvedDataDir }
    catch { $rollbackErrors.Add("data root: $($_.Exception.Message)") }
  }
  if ($rollbackErrors.Count -gt 0) {
    throw "Installation failed: $($installationError.Exception.Message) Rollback was incomplete: $($rollbackErrors -join '; ')"
  }
  throw $installationError
} finally {
  if ($null -ne $shortcutBackupPath -and (Test-Path -LiteralPath $shortcutBackupPath -PathType Leaf)) {
    Remove-Item -LiteralPath $shortcutBackupPath -Force -ErrorAction SilentlyContinue
  }
}
