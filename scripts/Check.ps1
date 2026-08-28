param(
  [switch]$InstallDependencies,
  [switch]$RequireDocker,
  [string]$ProtocolRoot = ""
)

. (Join-Path $PSScriptRoot "Common.ps1")

& (Join-Path $PSScriptRoot "Build.ps1") -InstallDependencies:$InstallDependencies -ProtocolRoot $ProtocolRoot
if ($LASTEXITCODE -ne 0) { throw "Build failed." }

$node = Resolve-WefNode
$venvPython = Get-WefVenvPython
Push-Location $script:WefRoot
try {
  & $venvPython -m pip check
  if ($LASTEXITCODE -ne 0) { throw "Python dependency check failed." }
  & $venvPython -m ruff check backend tests spikes/synthetic_server.py spikes/docker_gate.py spikes/real_codex_gate.py
  if ($LASTEXITCODE -ne 0) { throw "Python static checks failed." }
  New-Item -ItemType Directory -Path (Join-Path $script:WefRoot ".runtime-data") -Force | Out-Null
  & $venvPython -m pytest --basetemp (Join-Path $script:WefRoot ".runtime-data\pytest") -q
  if ($LASTEXITCODE -ne 0) { throw "Golden scenario tests failed." }
  & $node (Join-Path $PSScriptRoot "validate-plugin.mjs")
  if ($LASTEXITCODE -ne 0) { throw "Plugin validation failed." }
  & $node --check (Join-Path $script:WefRoot "plugins/workflow-environment-factory/scripts/mcp-server.mjs")
  if ($LASTEXITCODE -ne 0) { throw "MCP server syntax check failed." }
  if ($RequireDocker) {
    $previousProtocol = [Environment]::GetEnvironmentVariable("WEF_PROTOCOL_SCHEMA_DIR", "Process")
    [Environment]::SetEnvironmentVariable("WEF_PROTOCOL_SCHEMA_DIR", (Get-WefProtocolDir), "Process")
    try {
      & $venvPython -m workflow_environment_factory.cli doctor
      if ($LASTEXITCODE -ne 0) { throw "Docker/Codex product prerequisites failed." }
      if ([string]::IsNullOrWhiteSpace($env:WEF_DOCKER_GATE_IMAGE)) {
        throw "WEF_DOCKER_GATE_IMAGE must name an immutable image@sha256 digest for the release gate."
      }
      $gateData = Join-Path $script:WefRoot ".runtime-data\docker-gate-$([Guid]::NewGuid().ToString('N'))"
      New-Item -ItemType Directory -Path $gateData -Force | Out-Null
      $previousGateData = [Environment]::GetEnvironmentVariable("WEF_DOCKER_GATE_DATA_DIR", "Process")
      [Environment]::SetEnvironmentVariable("WEF_DOCKER_GATE_DATA_DIR", $gateData, "Process")
      try {
        & $venvPython (Join-Path $script:WefRoot "spikes\docker_gate.py")
        if ($LASTEXITCODE -ne 0) { throw "Real Docker code and Issue-to-PR gates failed." }
      } finally {
        [Environment]::SetEnvironmentVariable("WEF_DOCKER_GATE_DATA_DIR", $previousGateData, "Process")
        if (Test-Path -LiteralPath $gateData -PathType Container) {
          $resolvedGateData = (Resolve-Path -LiteralPath $gateData).Path
          $expectedPrefix = Join-Path $script:WefRoot ".runtime-data\docker-gate-"
          if (-not $resolvedGateData.StartsWith($expectedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
            throw "Unsafe Docker gate cleanup target: $resolvedGateData"
          }
          Remove-Item -LiteralPath $resolvedGateData -Recurse -Force
        }
      }
    } finally {
      [Environment]::SetEnvironmentVariable("WEF_PROTOCOL_SCHEMA_DIR", $previousProtocol, "Process")
    }
  }
} finally {
  Pop-Location
}

Write-Host "Workflow Environment Factory release checks passed."
