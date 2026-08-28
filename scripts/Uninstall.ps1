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
  if (Test-Path -LiteralPath $shortcutPath -PathType Leaf) {
    Remove-Item -LiteralPath $shortcutPath -Force
    Write-Host "Removed current-user startup shortcut."
  }
}

$codexCommand = Get-Command codex.exe -ErrorAction SilentlyContinue
if ($null -eq $codexCommand) { $codexCommand = Get-Command codex -ErrorAction SilentlyContinue }
if ($null -ne $codexCommand) {
  $pluginOutput = (& $codexCommand.Source plugin list 2>&1 | Out-String)
  if ($pluginOutput.Contains($pluginSelector, [StringComparison]::OrdinalIgnoreCase)) {
    & $codexCommand.Source plugin remove $pluginSelector
    if ($LASTEXITCODE -ne 0) { throw "Codex could not remove $pluginSelector." }
  }
  $marketplaceOutput = (& $codexCommand.Source plugin marketplace list 2>&1 | Out-String)
  if ($marketplaceOutput -match '(?im)^Marketplace\s+\W*workflow-environment-factory\W*$') {
    & $codexCommand.Source plugin marketplace remove $marketplaceName
    if ($LASTEXITCODE -ne 0) { throw "Codex could not remove marketplace $marketplaceName." }
  }
} else {
  Write-Warning "Codex CLI was not found; plugin configuration could not be inspected."
}

if ($DeleteData -and (Test-Path -LiteralPath $resolvedDataDir -PathType Container)) {
  $dataFullPath = [System.IO.Path]::GetFullPath($resolvedDataDir).TrimEnd('\')
  $dataRoot = [System.IO.Path]::GetPathRoot($dataFullPath).TrimEnd('\')
  $profilePath = [System.IO.Path]::GetFullPath([Environment]::GetFolderPath("UserProfile")).TrimEnd('\')
  $localAppDataPath = if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { "" } else {
    [System.IO.Path]::GetFullPath($env:LOCALAPPDATA).TrimEnd('\')
  }
  if ($dataFullPath.Length -lt 12 -or $dataFullPath -eq $dataRoot -or $dataFullPath -eq $profilePath -or $dataFullPath -eq $localAppDataPath) {
    throw "Refusing to recursively delete an unsafe data path: $dataFullPath"
  }
  Remove-Item -LiteralPath $dataFullPath -Recurse -Force
  Write-Host "Deleted local Workflow Environment Factory data: $dataFullPath (not recoverable by this uninstaller)."
} else {
  Write-Host "Preserved local product data: $resolvedDataDir"
}

Write-Host "Workflow Environment Factory is uninstalled. The source checkout was not deleted."
