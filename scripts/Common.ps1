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

function Get-WefMarketplaceRecord([string]$Listing, [string]$Name) {
  $escaped = [regex]::Escape($Name)
  foreach ($line in ($Listing -split "\r?\n")) {
    if ($line -match "^\s*$escaped\s+(.+?)\s*$") {
      return [pscustomobject]@{
        name = $Name
        root = [System.IO.Path]::GetFullPath($Matches[1].Trim()).TrimEnd('\')
      }
    }
  }
  return $null
}

function Get-WefPluginRecord([string]$Listing, [string]$Selector) {
  $escaped = [regex]::Escape($Selector)
  foreach ($line in ($Listing -split "\r?\n")) {
    if ($line -match "^\s*$escaped\s+installed(?:,\s*[a-z]+)*\s+(\S+)\s+(.+?)\s*$") {
      return [pscustomobject]@{
        selector = $Selector
        version = $Matches[1]
        path = [System.IO.Path]::GetFullPath($Matches[2].Trim()).TrimEnd('\')
      }
    }
  }
  return $null
}

function Test-WefMarketplacePresent([string]$Listing, [string]$Name) {
  return $null -ne (Get-WefMarketplaceRecord $Listing $Name)
}

function Test-WefPluginInstalled([string]$Listing, [string]$Selector) {
  return $null -ne (Get-WefPluginRecord $Listing $Selector)
}

function Test-WefSamePath([string]$Left, [string]$Right) {
  $leftPath = [System.IO.Path]::GetFullPath($Left).TrimEnd('\')
  $rightPath = [System.IO.Path]::GetFullPath($Right).TrimEnd('\')
  return $leftPath.Equals($rightPath, [StringComparison]::OrdinalIgnoreCase)
}

function Assert-WefCodexOwnership(
  $MarketplaceRecord,
  $PluginRecord,
  [string]$Source,
  [string]$PluginPath,
  [string]$Version
) {
  if ($null -ne $MarketplaceRecord -and -not (Test-WefSamePath $MarketplaceRecord.root $Source)) {
    throw "A foreign Codex marketplace already uses the name workflow-environment-factory at $($MarketplaceRecord.root). It was not changed."
  }
  if (
    $null -ne $PluginRecord -and
    (-not (Test-WefSamePath $PluginRecord.path $PluginPath) -or [string]$PluginRecord.version -cne $Version)
  ) {
    throw "A foreign or different-version Codex plugin already uses workflow-environment-factory. It was not changed."
  }
}

function Get-WefInstallationReceiptPath([string]$DataDir) {
  return Join-Path ([System.IO.Path]::GetFullPath($DataDir)) ".workflow-environment-factory-installation.json"
}

function Write-WefInstallationReceipt([string]$DataDir, [string]$Source, [string]$PluginPath, [string]$Version) {
  $receipt = [ordered]@{
    schema_version = "product.installation-ownership.v1"
    product = "workflow-environment-factory"
    marketplace_name = "workflow-environment-factory"
    marketplace_source = [System.IO.Path]::GetFullPath($Source).TrimEnd('\')
    plugin_selector = "workflow-environment-factory@workflow-environment-factory"
    plugin_path = [System.IO.Path]::GetFullPath($PluginPath).TrimEnd('\')
    plugin_version = $Version
    recorded_at = [DateTimeOffset]::UtcNow.ToString("o")
  } | ConvertTo-Json -Depth 4
  [System.IO.File]::WriteAllText(
    (Get-WefInstallationReceiptPath $DataDir),
    "$receipt`n",
    [Text.UTF8Encoding]::new($false)
  )
}

function Read-WefInstallationReceipt([string]$DataDir) {
  $path = Get-WefInstallationReceiptPath $DataDir
  if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return $null }
  try { $receipt = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json }
  catch { throw "Workflow Environment Factory installation receipt is invalid: $path" }
  if (
    $receipt.schema_version -ne "product.installation-ownership.v1" -or
    $receipt.product -ne "workflow-environment-factory"
  ) {
    throw "Workflow Environment Factory installation receipt names another product: $path"
  }
  return $receipt
}

function Get-WefStartupShortcutPath {
  $startupDirectory = [Environment]::GetFolderPath("Startup")
  if ([string]::IsNullOrWhiteSpace($startupDirectory)) {
    throw "Windows Startup directory could not be resolved."
  }
  return Join-Path $startupDirectory "Workflow Environment Factory.lnk"
}

function Get-WefStartupShortcutDescription {
  return "Workflow Environment Factory startup [owner:workflow-environment-factory]"
}

function Test-WefOwnedStartupShortcut([string]$ShortcutPath) {
  if (-not (Test-Path -LiteralPath $ShortcutPath -PathType Leaf)) { return $false }
  $shell = $null
  $shortcut = $null
  try {
    $shell = New-Object -ComObject WScript.Shell
    $shortcut = $shell.CreateShortcut($ShortcutPath)
    $expectedScript = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot "Start.ps1"))
    $expectedWorkingDirectory = [System.IO.Path]::GetFullPath($script:WefRoot).TrimEnd('\')
    $actualWorkingDirectory = [System.IO.Path]::GetFullPath([string]$shortcut.WorkingDirectory).TrimEnd('\')
    $targetName = [System.IO.Path]::GetFileName([string]$shortcut.TargetPath).ToLowerInvariant()
    $scriptArgument = '-File "' + $expectedScript + '"'
    return (
      ([string]$shortcut.Description -ceq (Get-WefStartupShortcutDescription)) -and
      ($targetName -in @("pwsh.exe", "powershell.exe")) -and
      ($actualWorkingDirectory -ceq $expectedWorkingDirectory) -and
      ([string]$shortcut.Arguments).IndexOf($scriptArgument, [StringComparison]::OrdinalIgnoreCase) -ge 0
    )
  } catch {
    return $false
  } finally {
    if ($null -ne $shortcut -and [Runtime.InteropServices.Marshal]::IsComObject($shortcut)) {
      [Runtime.InteropServices.Marshal]::FinalReleaseComObject($shortcut) | Out-Null
    }
    if ($null -ne $shell -and [Runtime.InteropServices.Marshal]::IsComObject($shell)) {
      [Runtime.InteropServices.Marshal]::FinalReleaseComObject($shell) | Out-Null
    }
  }
}

function Assert-WefStartupShortcutAvailable([string]$ShortcutPath) {
  if ((Test-Path -LiteralPath $ShortcutPath -PathType Leaf) -and -not (Test-WefOwnedStartupShortcut $ShortcutPath)) {
    throw "The Startup shortcut name is already used by another application. It was not overwritten: $ShortcutPath"
  }
}

function Remove-WefOwnedStartupShortcut([string]$ShortcutPath) {
  if (Test-WefOwnedStartupShortcut $ShortcutPath) {
    Remove-Item -LiteralPath $ShortcutPath -Force
    return $true
  }
  return $false
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

function Assert-WefSafeDataPath([string]$DataDir) {
  $directorySeparators = [char[]]@([System.IO.Path]::DirectorySeparatorChar, [System.IO.Path]::AltDirectorySeparatorChar)
  $pathComparison = if ($IsWindows) { [StringComparison]::OrdinalIgnoreCase } else { [StringComparison]::Ordinal }
  $separator = [string][System.IO.Path]::DirectorySeparatorChar
  $resolved = [System.IO.Path]::GetFullPath($DataDir).TrimEnd($directorySeparators)
  $root = [System.IO.Path]::GetPathRoot($resolved).TrimEnd($directorySeparators)
  $profile = [System.IO.Path]::GetFullPath([Environment]::GetFolderPath("UserProfile")).TrimEnd($directorySeparators)
  $localAppData = if ([string]::IsNullOrWhiteSpace($env:LOCALAPPDATA)) { "" } else {
    [System.IO.Path]::GetFullPath($env:LOCALAPPDATA).TrimEnd($directorySeparators)
  }
  $documentsFolder = [Environment]::GetFolderPath("MyDocuments")
  $documents = if ([string]::IsNullOrWhiteSpace($documentsFolder)) { "" } else {
    [System.IO.Path]::GetFullPath($documentsFolder).TrimEnd($directorySeparators)
  }
  if ($resolved.Length -lt 12 -or $resolved -eq $root -or $resolved -eq $profile -or $resolved -eq $localAppData -or $resolved -eq $documents) {
    throw "Refusing to use an unsafe Workflow Environment Factory data path: $resolved"
  }
  $checkout = [System.IO.Path]::GetFullPath($script:WefRoot).TrimEnd($directorySeparators)
  $dataInsideCheckout = $resolved.Equals($checkout, $pathComparison) -or
    $resolved.StartsWith(($checkout + $separator), $pathComparison)
  $checkoutInsideData = $checkout.StartsWith(($resolved + $separator), $pathComparison)
  if ($dataInsideCheckout -or $checkoutInsideData) {
    throw "Refusing a data path that overlaps the Workflow Environment Factory source checkout: $resolved"
  }
  return $resolved
}

function Get-WefDataMarkerPath([string]$DataDir) {
  return Join-Path ([System.IO.Path]::GetFullPath($DataDir)) ".workflow-environment-factory-data.json"
}

function Assert-WefDataRoot([string]$DataDir) {
  $resolved = Assert-WefSafeDataPath $DataDir
  $item = Get-Item -LiteralPath $resolved -Force -ErrorAction Stop
  if (-not $item.PSIsContainer -or ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
    throw "Workflow Environment Factory data root must be a real directory, not a file or reparse point: $resolved"
  }
  $markerPath = Get-WefDataMarkerPath $resolved
  if (-not (Test-Path -LiteralPath $markerPath -PathType Leaf)) {
    throw "Refusing to treat an unmarked directory as Workflow Environment Factory data: $resolved"
  }
  try { $marker = Get-Content -LiteralPath $markerPath -Raw | ConvertFrom-Json }
  catch { throw "Workflow Environment Factory data marker is invalid: $markerPath" }
  if ($marker.schema_version -ne "product.data-root.v1" -or $marker.product -ne "workflow-environment-factory") {
    throw "Workflow Environment Factory data marker names another product: $markerPath"
  }
  return $resolved
}

function Initialize-WefDataRoot([string]$DataDir) {
  $resolved = Assert-WefSafeDataPath $DataDir
  if (Test-Path -LiteralPath $resolved) {
    $item = Get-Item -LiteralPath $resolved -Force
    if (-not $item.PSIsContainer -or ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint)) {
      throw "Workflow Environment Factory data root must be a real directory, not a file or reparse point: $resolved"
    }
    $markerPath = Get-WefDataMarkerPath $resolved
    if (Test-Path -LiteralPath $markerPath -PathType Leaf) {
      Assert-WefDataRoot $resolved | Out-Null
      return
    }
    throw "DataDir already exists but has no Workflow Environment Factory marker: $resolved"
  } else {
    New-Item -ItemType Directory -Path $resolved | Out-Null
  }
  $marker = [ordered]@{
    schema_version = "product.data-root.v1"
    product = "workflow-environment-factory"
    created_at = [DateTimeOffset]::UtcNow.ToString("o")
  } | ConvertTo-Json -Depth 3
  [System.IO.File]::WriteAllText((Get-WefDataMarkerPath $resolved), "$marker`n", [Text.UTF8Encoding]::new($false))
  Assert-WefDataRoot $resolved | Out-Null
}

function Remove-WefDataRootCreatedByFailedInstall([string]$DataDir) {
  $resolved = Assert-WefDataRoot $DataDir
  Remove-Item -LiteralPath $resolved -Recurse -Force
}

function Get-WefProtocolDir {
  return Join-Path $script:WefRoot ".runtime-deps\runcase-interchange\0.1.2\schemas"
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
