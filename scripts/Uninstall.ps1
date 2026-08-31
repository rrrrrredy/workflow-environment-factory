param(
  [switch]$DeleteData,
  [ValidateRange(1024, 65535)][int]$Port = 43121,
  [string]$DataDir = ""
)

. (Join-Path $PSScriptRoot "Common.ps1")

$resolvedDataDir = Get-WefDataDir $DataDir
$pluginSelector = "workflow-environment-factory@workflow-environment-factory"
$marketplaceName = "workflow-environment-factory"
try { & (Join-Path $PSScriptRoot "Stop.ps1") -Port $Port -DataDir $resolvedDataDir } catch {
  Write-Warning "Service stop needs attention: $($_.Exception.Message)"
}

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
  $pluginOutput = (& $codexCommand.Source plugin list 2>&1 | Out-String)
  if (Test-WefPluginInstalled $pluginOutput $pluginSelector) {
    & $codexCommand.Source plugin remove $pluginSelector
    if ($LASTEXITCODE -ne 0) { throw "Codex could not remove $pluginSelector." }
  }
  $marketplaceOutput = (& $codexCommand.Source plugin marketplace list 2>&1 | Out-String)
  if (Test-WefMarketplacePresent $marketplaceOutput $marketplaceName) {
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
