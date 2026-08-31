param(
  [switch]$DeleteData,
  [ValidateRange(1024, 65535)][int]$Port = 43121,
  [string]$DataDir = ""
)

. (Join-Path $PSScriptRoot "Common.ps1")

$resolvedDataDir = Get-WefDataDir $DataDir
$pluginSelector = "workflow-environment-factory@workflow-environment-factory"
$marketplaceName = "workflow-environment-factory"
& (Join-Path $PSScriptRoot "Stop.ps1") -Port $Port -DataDir $resolvedDataDir

$startupDirectory = [Environment]::GetFolderPath("Startup")
if (-not [string]::IsNullOrWhiteSpace($startupDirectory)) {
  $shortcutPath = Join-Path $startupDirectory "Workflow Environment Factory.lnk"
  if (Remove-WefOwnedStartupShortcut $shortcutPath) {
    Write-Host "Removed current-user startup shortcut."
  } elseif (Test-Path -LiteralPath $shortcutPath -PathType Leaf) {
    Write-Warning "Preserved a same-name Startup shortcut because it is not owned by Workflow Environment Factory: $shortcutPath"
  }
}

$codexCommand = Get-Command codex.exe -ErrorAction SilentlyContinue
if ($null -eq $codexCommand) { $codexCommand = Get-Command codex -ErrorAction SilentlyContinue }
if ($null -ne $codexCommand) {
  $receipt = Read-WefInstallationReceipt $resolvedDataDir
  $pluginOutput = (& $codexCommand.Source plugin list 2>&1 | Out-String)
  $pluginRecord = Get-WefPluginRecord $pluginOutput $pluginSelector
  $marketplaceOutput = (& $codexCommand.Source plugin marketplace list 2>&1 | Out-String)
  $marketplaceRecord = Get-WefMarketplaceRecord $marketplaceOutput $marketplaceName
  if (($null -ne $pluginRecord -or $null -ne $marketplaceRecord) -and $null -eq $receipt) {
    throw "Codex registrations exist, but this data root has no ownership receipt. They were preserved."
  }
  if ($null -ne $receipt) {
    Assert-WefCodexOwnership $marketplaceRecord $pluginRecord ([string]$receipt.marketplace_source) ([string]$receipt.plugin_path) ([string]$receipt.plugin_version)
  }
  if ($null -ne $pluginRecord) {
    & $codexCommand.Source plugin remove $pluginSelector
    if ($LASTEXITCODE -ne 0) { throw "Codex could not remove $pluginSelector." }
  }
  if ($null -ne $marketplaceRecord) {
    & $codexCommand.Source plugin marketplace remove $marketplaceName
    if ($LASTEXITCODE -ne 0) { throw "Codex could not remove marketplace $marketplaceName." }
  }
} else {
  Write-Warning "Codex CLI was not found; plugin configuration could not be inspected."
}

if ($DeleteData -and (Test-Path -LiteralPath $resolvedDataDir -PathType Container)) {
  $dataFullPath = Assert-WefDataRoot $resolvedDataDir
  Remove-Item -LiteralPath $dataFullPath -Recurse -Force
  Write-Host "Deleted local Workflow Environment Factory data: $dataFullPath (not recoverable by this uninstaller)."
} else {
  Write-Host "Preserved local product data: $resolvedDataDir"
}

& (Join-Path $PSScriptRoot "Inspect-Installation.ps1") -RequireAbsent -RequireNoData:$DeleteData -Port $Port -DataDir $resolvedDataDir | Out-Null
Write-Host "Workflow Environment Factory is uninstalled. The source checkout was not deleted."
