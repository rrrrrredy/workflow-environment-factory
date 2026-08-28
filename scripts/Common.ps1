Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

$script:WefRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))

function Resolve-WefNode {
  $candidate = $null
  if (-not [string]::IsNullOrWhiteSpace($env:WEF_NODE)) {
    if (-not (Test-Path -LiteralPath $env:WEF_NODE -PathType Leaf)) {
      throw "WEF_NODE does not point to a Node executable: $env:WEF_NODE"
    }
    $candidate = [System.IO.Path]::GetFullPath($env:WEF_NODE)
  } else {
    $command = Get-Command node.exe -ErrorAction SilentlyContinue
    if ($null -eq $command) { $command = Get-Command node -ErrorAction SilentlyContinue }
    if ($null -eq $command) { throw "Node.js 22 is required. Install Node 22 or set WEF_NODE to node.exe." }
    $candidate = $command.Source
  }
  $version = (& $candidate -p "process.versions.node").Trim()
  if ($LASTEXITCODE -ne 0) { throw "Could not run Node at $candidate" }
  if ([int]($version.Split('.')[0]) -ne 22) {
    throw "Workflow Environment Factory requires Node 22.x; found $version at $candidate."
  }
  return $candidate
}

function Resolve-WefPython {
  $candidate = $null
  if (-not [string]::IsNullOrWhiteSpace($env:WEF_PYTHON)) {
    if (-not (Test-Path -LiteralPath $env:WEF_PYTHON -PathType Leaf)) {
      throw "WEF_PYTHON does not point to a Python executable: $env:WEF_PYTHON"
    }
    $candidate = [System.IO.Path]::GetFullPath($env:WEF_PYTHON)
  } else {
    $command = Get-Command python.exe -ErrorAction SilentlyContinue
    if ($null -eq $command) { $command = Get-Command python -ErrorAction SilentlyContinue }
    if ($null -eq $command) { throw "Python 3.11-3.13 is required. Install Python or set WEF_PYTHON." }
    $candidate = $command.Source
  }
  $version = (& $candidate -c "import sys; print('.'.join(map(str, sys.version_info[:3])))").Trim()
  if ($LASTEXITCODE -ne 0) { throw "Could not run Python at $candidate" }
  $parts = $version.Split('.')
  if ([int]$parts[0] -ne 3 -or [int]$parts[1] -lt 11 -or [int]$parts[1] -gt 13) {
    throw "Workflow Environment Factory requires Python 3.11-3.13; found $version at $candidate."
  }
  return $candidate
}

function Get-WefNpmCli([string]$NodePath) {
  $npmCli = Join-Path (Split-Path -Parent $NodePath) "node_modules\npm\bin\npm-cli.js"
  if (-not (Test-Path -LiteralPath $npmCli -PathType Leaf)) { throw "npm-cli.js was not found beside Node: $npmCli" }
  return $npmCli
}

function Invoke-WefNpm([string[]]$Arguments) {
  $node = Resolve-WefNode
  if (-not [string]::IsNullOrWhiteSpace($env:WEF_NODE)) {
    & $node (Get-WefNpmCli $node) @Arguments
  } else {
    $npm = Get-Command npm.cmd -ErrorAction SilentlyContinue
    if ($null -eq $npm) { $npm = Get-Command npm -ErrorAction Stop }
    & $npm.Source @Arguments
  }
  if ($LASTEXITCODE -ne 0) { throw "npm failed with exit code $LASTEXITCODE" }
}

function Test-WefMarketplacePresent([string]$Listing, [string]$Name) {
  $escaped = [regex]::Escape($Name)
  return (
    $Listing -match "(?im)^\s*$escaped(?:\s+|$)" -or
    $Listing -match "(?im)^\s*Marketplace\s+\W*$escaped\W*$"
  )
}

function Test-WefPluginInstalled([string]$Listing, [string]$Selector) {
  $escaped = [regex]::Escape($Selector)
  return $Listing -match "(?im)^\s*$escaped\s+installed(?:,|\s|$)"
}

function Get-WefVenvPython {
  $runningOnWindows = [System.Runtime.InteropServices.RuntimeInformation]::IsOSPlatform(
    [System.Runtime.InteropServices.OSPlatform]::Windows
  )
  if ($runningOnWindows) { return Join-Path $script:WefRoot ".venv\Scripts\python.exe" }
  return Join-Path $script:WefRoot ".venv/bin/python"
}

function Initialize-WefVenv {
  $venvPython = Get-WefVenvPython
  if (-not (Test-Path -LiteralPath $venvPython -PathType Leaf)) {
    $basePython = Resolve-WefPython
    & $basePython -m venv (Join-Path $script:WefRoot ".venv")
    if ($LASTEXITCODE -ne 0) { throw "Could not create the product virtual environment." }
  }
  return $venvPython
}

function Get-WefDataDir([string]$Requested = "") {
  if (-not [string]::IsNullOrWhiteSpace($Requested)) { return [System.IO.Path]::GetFullPath($Requested) }
  if (-not [string]::IsNullOrWhiteSpace($env:WEF_DATA_DIR)) { return [System.IO.Path]::GetFullPath($env:WEF_DATA_DIR) }
  if (-not [string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) {
    return [System.IO.Path]::GetFullPath((Join-Path $env:LOCALAPPDATA "WorkflowEnvironmentFactory"))
  }
  return [System.IO.Path]::GetFullPath((Join-Path ([Environment]::GetFolderPath("UserProfile")) ".workflow-environment-factory"))
}

function Get-WefProtocolDir {
  return Join-Path $script:WefRoot ".runtime-deps\runcase-interchange\0.1.0\schemas"
}

function Get-WefHealth([int]$Port) {
  try { return Invoke-RestMethod -Uri "http://127.0.0.1:$Port/health" -Method Get -TimeoutSec 2 } catch { return $null }
}

function Get-WefSessionUrl([string]$DataDir, [int]$Port) {
  $tokenPath = Join-Path $DataDir "session-token"
  if (-not (Test-Path -LiteralPath $tokenPath -PathType Leaf)) { return $null }
  $token = (Get-Content -LiteralPath $tokenPath -Raw).Trim()
  if ($token.Length -lt 32) { return $null }
  return "http://127.0.0.1:$Port/session/$token"
}
