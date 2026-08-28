param(
  [string]$Version = "0.1.0",
  [string]$EvidenceDirectory = "",
  [ValidateRange(1024, 65535)][int]$Port = 43131,
  [string]$ProtocolRoot = ""
)

. (Join-Path $PSScriptRoot "Common.ps1")
$evidencePath = $null

if ($env:OS -ne "Windows_NT") { throw "The authenticated real Codex gate requires Windows 11." }
if ([string]::IsNullOrWhiteSpace($env:WEF_DOCKER_GATE_IMAGE)) {
  throw "WEF_DOCKER_GATE_IMAGE must name the reviewed immutable release image."
}

Push-Location $script:WefRoot
try {
  $status = (git status --porcelain=v1 | Out-String).Trim()
  if ($LASTEXITCODE -ne 0) { throw "The checkout is not a Git repository." }
  if ($status.Length -gt 0) { throw "Commit or remove every change before running the real release gate." }
  $package = Get-Content -LiteralPath (Join-Path $script:WefRoot "package.json") -Raw | ConvertFrom-Json
  if ($package.version -ne $Version) { throw "Requested version $Version does not match package.json." }

  $node = Resolve-WefNode
  $python = Resolve-WefPython
  $nodeDirectory = Split-Path -Parent $node
  $codexCommand = Get-Command codex.exe -ErrorAction SilentlyContinue
  if ($null -eq $codexCommand) { $codexCommand = Get-Command codex -ErrorAction SilentlyContinue }
  if ($null -eq $codexCommand) { throw "Codex CLI is required for the authenticated product gate." }
  $codexVersion = (& $codexCommand.Source --version 2>&1 | Out-String).Trim()
  if ($codexVersion -notmatch '0\.150\.0-alpha\.8') {
    throw "The release gate requires Codex 0.150.0-alpha.8; found $codexVersion."
  }

  if ($null -ne (Get-WefHealth $Port)) { throw "Port $Port is already serving a local application." }
  $pluginSelector = "workflow-environment-factory@workflow-environment-factory"
  $marketplaceName = "workflow-environment-factory"
  $initialPlugins = (& $codexCommand.Source plugin list 2>&1 | Out-String)
  $initialMarketplaces = (& $codexCommand.Source plugin marketplace list 2>&1 | Out-String)
  if (Test-WefPluginInstalled $initialPlugins $pluginSelector) {
    throw "Refusing to run: Workflow Environment Factory is already installed in the active Codex home."
  }
  if (Test-WefMarketplacePresent $initialMarketplaces $marketplaceName) {
    throw "Refusing to run: the Workflow Environment Factory marketplace already exists in the active Codex home."
  }
  $startupDirectory = [Environment]::GetFolderPath("Startup")
  $shortcutPath = if ([string]::IsNullOrWhiteSpace($startupDirectory)) {
    $null
  } else {
    Join-Path $startupDirectory "Workflow Environment Factory.lnk"
  }
  if ($null -ne $shortcutPath -and (Test-Path -LiteralPath $shortcutPath -PathType Leaf)) {
    throw "Refusing to run: a Workflow Environment Factory Startup shortcut already exists."
  }

  & (Join-Path $PSScriptRoot "Check.ps1") -InstallDependencies -RequireDocker -ProtocolRoot $ProtocolRoot
  if ($LASTEXITCODE -ne 0) { throw "Release checks or deterministic Docker environment gates failed." }

  $outputRoot = if ([string]::IsNullOrWhiteSpace($EvidenceDirectory)) {
    Join-Path $script:WefRoot "release-evidence"
  } else {
    [System.IO.Path]::GetFullPath($EvidenceDirectory)
  }
  New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
  $evidencePath = Join-Path $outputRoot "workflow-product-gate-$Version.json"
  if (Test-Path -LiteralPath $evidencePath -PathType Leaf) { Remove-Item -LiteralPath $evidencePath -Force }

  $gateData = Join-Path ([System.IO.Path]::GetTempPath()) "wef-real-codex-gate-$([Guid]::NewGuid().ToString('N'))"
  New-Item -ItemType Directory -Path $gateData | Out-Null
  $previousPath = $env:PATH
  $environmentNames = @("WEF_REAL_GATE_DATA_DIR", "WEF_REAL_GATE_OUTPUT", "WEF_REAL_GATE_PORT")
  $previousEnvironment = @{}
  foreach ($name in $environmentNames) {
    $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process")
  }
  $cleanupRequired = $false
  try {
    $env:PATH = "$nodeDirectory$([System.IO.Path]::PathSeparator)$previousPath"
    $cleanupRequired = $true
    & (Join-Path $PSScriptRoot "Install.ps1") -NoStart -Port $Port -DataDir $gateData -ProtocolRoot $ProtocolRoot
    & (Join-Path $PSScriptRoot "Start.ps1") -Port $Port -DataDir $gateData
    [Environment]::SetEnvironmentVariable("WEF_REAL_GATE_DATA_DIR", $gateData, "Process")
    [Environment]::SetEnvironmentVariable("WEF_REAL_GATE_OUTPUT", $evidencePath, "Process")
    [Environment]::SetEnvironmentVariable("WEF_REAL_GATE_PORT", [string]$Port, "Process")
    $venvPython = Get-WefVenvPython
    & $venvPython (Join-Path $script:WefRoot "spikes\real_codex_gate.py")
    if ($LASTEXITCODE -ne 0) { throw "Real Codex code and Issue-to-PR product gates failed." }
  } finally {
    try {
      if ($cleanupRequired) {
        & (Join-Path $PSScriptRoot "Uninstall.ps1") -DeleteData -Port $Port -DataDir $gateData
      }
    } finally {
      $env:PATH = $previousPath
      foreach ($name in $environmentNames) {
        [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], "Process")
      }
    }
  }

  if ($null -ne (Get-WefHealth $Port)) { throw "The real gate left the product service running." }
  if (Test-WefPluginInstalled (& $codexCommand.Source plugin list 2>&1 | Out-String) $pluginSelector) {
    throw "The real gate left the Codex plugin installed."
  }
  if (Test-WefMarketplacePresent (& $codexCommand.Source plugin marketplace list 2>&1 | Out-String) $marketplaceName) {
    throw "The real gate left the Codex marketplace registered."
  }
  if ($null -ne $shortcutPath -and (Test-Path -LiteralPath $shortcutPath -PathType Leaf)) {
    throw "The real gate left a Startup shortcut."
  }
  if (Test-Path -LiteralPath $gateData) { throw "The real gate left its disposable product data directory." }

  $evidence = Get-Content -LiteralPath $evidencePath -Raw | ConvertFrom-Json
  $head = (git rev-parse HEAD | Out-String).Trim()
  if ($evidence.testedCommit -ne $head) { throw "Product-gate evidence does not match the current commit." }
  $evidence | Add-Member -NotePropertyName installationCleanup -NotePropertyValue ([ordered]@{
    serviceStopped = $true
    pluginRemoved = $true
    marketplaceRemoved = $true
    startupAbsent = $true
    disposableDataDeleted = $true
  }) -Force
  $json = $evidence | ConvertTo-Json -Depth 12
  [System.IO.File]::WriteAllText($evidencePath, "$json`n", [Text.UTF8Encoding]::new($false))
  Write-Host "Real Codex product-gate evidence: $evidencePath"
  Write-Host "Tested commit: $head"
  Write-Host "The temporary plugin, marketplace, service, and product data were removed."
  Write-Host "Review and commit only this evidence file before tagging v$Version."
} catch {
  if ($null -ne $evidencePath -and (Test-Path -LiteralPath $evidencePath -PathType Leaf)) {
    Remove-Item -LiteralPath $evidencePath -Force
  }
  throw
} finally {
  Pop-Location
}
