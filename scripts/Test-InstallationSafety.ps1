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

  Write-Host "Installation data-root safety passed."
} finally {
  $resolvedTestRoot = (Resolve-Path -LiteralPath $testRoot).Path
  $expectedPrefix = Join-Path $script:WefRoot ".runtime-data\installation-safety-"
  if (-not $resolvedTestRoot.StartsWith($expectedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
    throw "Unsafe installation-safety cleanup target: $resolvedTestRoot"
  }
  Remove-Item -LiteralPath $resolvedTestRoot -Recurse -Force
}
