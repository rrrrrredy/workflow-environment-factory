. (Join-Path $PSScriptRoot "Common.ps1")

$testRoot = Join-Path $script:WefRoot ".runtime-data\installation-safety-$([Guid]::NewGuid().ToString('N'))"
New-Item -ItemType Directory -Path $testRoot -Force | Out-Null
try {
  $owned = Join-Path $testRoot "owned"
  Initialize-WefDataRoot $owned
  if ((Assert-WefDataRoot $owned) -ne [System.IO.Path]::GetFullPath($owned)) {
    throw "Owned data root did not round-trip."
  }

  $existingEmpty = Join-Path $testRoot "existing-empty"
  New-Item -ItemType Directory -Path $existingEmpty | Out-Null
  $existingEmptyRejected = $false
  try { Initialize-WefDataRoot $existingEmpty } catch { $existingEmptyRejected = $true }
  if (-not $existingEmptyRejected -or @(Get-ChildItem -LiteralPath $existingEmpty -Force).Count -ne 0) {
    throw "An existing unmarked directory was not rejected and preserved."
  }

  $failedInstall = Join-Path $testRoot "failed-install"
  Initialize-WefDataRoot $failedInstall
  Remove-WefDataRootCreatedByFailedInstall $failedInstall
  if (Test-Path -LiteralPath $failedInstall) {
    throw "A data root created by a failed install was not removed."
  }

  $foreign = Join-Path $testRoot "foreign"
  New-Item -ItemType Directory -Path $foreign | Out-Null
  $sentinel = Join-Path $foreign "keep.txt"
  [System.IO.File]::WriteAllText($sentinel, "keep")
  $foreignRejected = $false
  try { Initialize-WefDataRoot $foreign } catch { $foreignRejected = $true }
  if (-not $foreignRejected -or -not (Test-Path -LiteralPath $sentinel -PathType Leaf)) {
    throw "A nonempty foreign directory was not rejected and preserved."
  }

  $wrong = Join-Path $testRoot "wrong-marker"
  New-Item -ItemType Directory -Path $wrong | Out-Null
  [System.IO.File]::WriteAllText(
    (Get-WefDataMarkerPath $wrong),
    '{"schema_version":"product.data-root.v1","product":"another-product"}'
  )
  $wrongRejected = $false
  try { Assert-WefDataRoot $wrong | Out-Null } catch { $wrongRejected = $true }
  if (-not $wrongRejected) { throw "A foreign product marker was accepted." }

  $unsafeRejected = $false
  try { Assert-WefSafeDataPath ([System.IO.Path]::GetPathRoot($testRoot)) | Out-Null } catch { $unsafeRejected = $true }
  if (-not $unsafeRejected) { throw "A drive root was accepted as product data." }

  $shell = New-Object -ComObject WScript.Shell
  $foreignShortcutPath = Join-Path $testRoot "foreign-shortcut.lnk"
  $foreignShortcut = $shell.CreateShortcut($foreignShortcutPath)
  $foreignShortcut.TargetPath = (Get-Command notepad.exe -ErrorAction Stop).Source
  $foreignShortcut.WorkingDirectory = $testRoot
  $foreignShortcut.Description = "Foreign installation-safety fixture"
  $foreignShortcut.Save()
  $foreignHash = (Get-FileHash -LiteralPath $foreignShortcutPath -Algorithm SHA256).Hash
  $foreignShortcutRejected = $false
  try { Assert-WefStartupShortcutAvailable $foreignShortcutPath } catch { $foreignShortcutRejected = $true }
  if (-not $foreignShortcutRejected -or (Remove-WefOwnedStartupShortcut $foreignShortcutPath)) {
    throw "A foreign same-name shortcut was accepted or removed."
  }
  if ((Get-FileHash -LiteralPath $foreignShortcutPath -Algorithm SHA256).Hash -ne $foreignHash) {
    throw "A foreign same-name shortcut was modified."
  }

  $ownedShortcutPath = Join-Path $testRoot "owned-shortcut.lnk"
  $powerShellCommand = Get-Command pwsh.exe -ErrorAction SilentlyContinue
  if ($null -eq $powerShellCommand) { $powerShellCommand = Get-Command powershell.exe -ErrorAction Stop }
  $ownedShortcut = $shell.CreateShortcut($ownedShortcutPath)
  $ownedShortcut.TargetPath = $powerShellCommand.Source
  $ownedShortcut.Arguments = "-NoProfile -File `"$(Join-Path $PSScriptRoot 'Start.ps1')`""
  $ownedShortcut.WorkingDirectory = $script:WefRoot
  $ownedShortcut.Description = Get-WefStartupShortcutDescription
  $ownedShortcut.Save()
  Assert-WefStartupShortcutAvailable $ownedShortcutPath
  if (-not (Remove-WefOwnedStartupShortcut $ownedShortcutPath) -or (Test-Path -LiteralPath $ownedShortcutPath)) {
    throw "An owned shortcut was not removed."
  }

  Write-Host "Installation data-root and shortcut ownership safety passed."
} finally {
  $resolvedTestRoot = (Resolve-Path -LiteralPath $testRoot).Path
  $expectedPrefix = Join-Path $script:WefRoot ".runtime-data\installation-safety-"
  if (-not $resolvedTestRoot.StartsWith($expectedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Unsafe installation-safety cleanup target: $resolvedTestRoot"
  }
  Remove-Item -LiteralPath $resolvedTestRoot -Recurse -Force
}
