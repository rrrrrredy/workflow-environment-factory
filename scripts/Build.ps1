param(
  [switch]$InstallDependencies,
  [string]$ProtocolRoot = ""
)

. (Join-Path $PSScriptRoot "Common.ps1")

$node = Resolve-WefNode
$venvPython = Initialize-WefVenv
$schemaDirectory = Get-WefProtocolDir
if (-not (Test-Path -LiteralPath (Join-Path $schemaDirectory "workflow.case.v1.schema.json") -PathType Leaf)) {
  if ([string]::IsNullOrWhiteSpace($ProtocolRoot)) {
    throw "Protocol schemas are missing. Pass -ProtocolRoot to a checked-out agent-run-protocol release."
  }
  & (Join-Path $PSScriptRoot "Sync-Protocol.ps1") -ProtocolRoot $ProtocolRoot
}

if ($InstallDependencies -or -not (Test-Path -LiteralPath (Join-Path $script:WefRoot "node_modules") -PathType Container)) {
  Push-Location $script:WefRoot
  try {
    Invoke-WefNpm @("ci")
    $previousConstraint = [Environment]::GetEnvironmentVariable("PIP_CONSTRAINT", "Process")
    [Environment]::SetEnvironmentVariable("PIP_CONSTRAINT", (Join-Path $script:WefRoot "requirements.lock"), "Process")
    try {
      & $venvPython -m pip install --disable-pip-version-check --constraint requirements.lock --editable ".[dev]"
      if ($LASTEXITCODE -ne 0) { throw "Python dependency installation failed." }
    } finally {
      [Environment]::SetEnvironmentVariable("PIP_CONSTRAINT", $previousConstraint, "Process")
    }
  } finally {
    Pop-Location
  }
}

$typescript = Join-Path $script:WefRoot "node_modules\typescript\bin\tsc"
$vite = Join-Path $script:WefRoot "node_modules\vite\bin\vite.js"
foreach ($required in @($typescript, $vite)) {
  if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
    throw "Dependency missing: $required. Run scripts\Build.ps1 -InstallDependencies."
  }
}

Push-Location $script:WefRoot
try {
  & $node $typescript -p tsconfig.web.json --noEmit
  if ($LASTEXITCODE -ne 0) { throw "Web TypeScript check failed." }
  & $node $vite build
  if ($LASTEXITCODE -ne 0) { throw "Web production build failed." }
} finally {
  Pop-Location
}

Write-Host "Workflow Environment Factory build passed with Node $(& $node -p 'process.versions.node')."
