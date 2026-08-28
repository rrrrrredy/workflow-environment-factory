param(
  [switch]$EnableStartup,
  [switch]$NoStart,
  [switch]$Open,
  [switch]$Repair,
  [string]$ProtocolRoot = "",
  [string]$MarketplaceSource = ""
)

. (Join-Path $PSScriptRoot "Common.ps1")

if ($env:OS -ne "Windows_NT") { throw "The 0.1 installer supports Windows 11 only." }
Resolve-WefNode | Out-Null
Resolve-WefPython | Out-Null
$codexCommand = Get-Command codex.exe -ErrorAction SilentlyContinue
if ($null -eq $codexCommand) { $codexCommand = Get-Command codex -ErrorAction SilentlyContinue }
if ($null -eq $codexCommand) { throw "Codex CLI is required and was not found on PATH." }

Write-Host "Checking the local runtime, protocol schemas, plugin, and focused product contracts..."
& (Join-Path $PSScriptRoot "Check.ps1") -InstallDependencies -ProtocolRoot $ProtocolRoot
if ($LASTEXITCODE -ne 0) { throw "Release checks failed; nothing was installed." }
$venvPython = Get-WefVenvPython
$previousProtocol = [Environment]::GetEnvironmentVariable("WEF_PROTOCOL_SCHEMA_DIR", "Process")
[Environment]::SetEnvironmentVariable("WEF_PROTOCOL_SCHEMA_DIR", (Get-WefProtocolDir), "Process")
try {
  & $venvPython -m workflow_environment_factory.cli doctor
  if ($LASTEXITCODE -ne 0) { throw "Docker/Codex prerequisites are not ready; nothing was installed." }
} finally {
  [Environment]::SetEnvironmentVariable("WEF_PROTOCOL_SCHEMA_DIR", $previousProtocol, "Process")
}

$source = if ([string]::IsNullOrWhiteSpace($MarketplaceSource)) { $script:WefRoot } else { $MarketplaceSource }
$marketplaceName = "workflow-environment-factory"
$pluginSelector = "workflow-environment-factory@workflow-environment-factory"
$marketplaceOutput = (& $codexCommand.Source plugin marketplace list 2>&1 | Out-String)
$marketplacePresent = $marketplaceOutput -match '(?im)^Marketplace\s+\W*workflow-environment-factory\W*$'
$pluginOutput = (& $codexCommand.Source plugin list 2>&1 | Out-String)
$pluginPresent = $pluginOutput.Contains($pluginSelector, [StringComparison]::OrdinalIgnoreCase)

if ($Repair -and $pluginPresent) {
  & $codexCommand.Source plugin remove $pluginSelector
  if ($LASTEXITCODE -ne 0) { throw "Could not remove the existing plugin during repair." }
  $pluginPresent = $false
}
if ($Repair -and $marketplacePresent) {
  & $codexCommand.Source plugin marketplace remove $marketplaceName
  if ($LASTEXITCODE -ne 0) { throw "Could not remove the existing marketplace during repair." }
  $marketplacePresent = $false
}
if (-not $marketplacePresent) {
  & $codexCommand.Source plugin marketplace add $source
  if ($LASTEXITCODE -ne 0) { throw "Could not add the Workflow Environment Factory marketplace." }
}
if (-not $pluginPresent) {
  try {
    & $codexCommand.Source plugin add $pluginSelector
    if ($LASTEXITCODE -ne 0) { throw "Codex plugin installation failed." }
  } catch {
    if (-not $marketplacePresent) { & $codexCommand.Source plugin marketplace remove $marketplaceName 2>$null | Out-Null }
    throw
  }
}

if ($EnableStartup) {
  $startupDirectory = [Environment]::GetFolderPath("Startup")
  if ([string]::IsNullOrWhiteSpace($startupDirectory)) { throw "Windows Startup directory could not be resolved." }
  $shortcutPath = Join-Path $startupDirectory "Workflow Environment Factory.lnk"
  $powerShellCommand = Get-Command pwsh.exe -ErrorAction SilentlyContinue
  if ($null -eq $powerShellCommand) { $powerShellCommand = Get-Command powershell.exe -ErrorAction Stop }
  $shell = New-Object -ComObject WScript.Shell
  $shortcut = $shell.CreateShortcut($shortcutPath)
  $shortcut.TargetPath = $powerShellCommand.Source
  $shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $PSScriptRoot 'Start.ps1')`""
  $shortcut.WorkingDirectory = $script:WefRoot
  $shortcut.WindowStyle = 7
  $shortcut.Description = "Start Workflow Environment Factory locally at sign-in"
  $shortcut.Save()
  Write-Host "Enabled current-user startup: $shortcutPath"
}

if (-not $NoStart) { & (Join-Path $PSScriptRoot "Start.ps1") -Open:$Open }
Write-Host "Workflow Environment Factory is installed. Restart Codex to load its simulator MCP tools and Skill."
Write-Host "Uninstall with .\scripts\Uninstall.ps1; product data is preserved unless -DeleteData is explicitly supplied."
