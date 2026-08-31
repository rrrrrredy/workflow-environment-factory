param(
  [ValidateRange(1024, 65535)][int]$Port = 43121,
  [string]$DataDir = ""
)

. (Join-Path $PSScriptRoot "Common.ps1")

$resolvedDataDir = Get-WefDataDir $DataDir
$pidPath = Join-Path $resolvedDataDir "service.pid"
if (-not (Test-Path -LiteralPath $pidPath -PathType Leaf)) {
  $health = Get-WefHealth $Port
  if ($null -ne $health -and $health.product -eq "workflow-environment-factory") {
    throw "The service is reachable but its PID file is missing. Refusing to guess which process to stop."
  }
  Write-Host "Workflow Environment Factory is not running."
  return
}

try { $serviceRecord = Get-Content -LiteralPath $pidPath -Raw | ConvertFrom-Json }
catch { throw "Invalid service ownership record: $pidPath" }
if (
  $serviceRecord.schema_version -ne "product.windows-service.v2" -or
  $serviceRecord.product -ne "workflow-environment-factory" -or
  [string]$serviceRecord.process_token -notmatch '^[a-f0-9]{64}$'
) {
  throw "Invalid service PID file: $pidPath"
}
$serviceProcessId = [int]$serviceRecord.pid
if ($serviceProcessId -le 0 -or [int]$serviceRecord.port -ne $Port) {
  throw "Service ownership record does not match the requested port: $pidPath"
}

$serviceProcessInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $serviceProcessId" -ErrorAction SilentlyContinue
if ($null -eq $serviceProcessInfo) {
  $health = Get-WefHealth $Port
  if ($null -ne $health) {
    throw "The recorded process is gone but port $Port is serving an application. Refusing to remove ownership evidence."
  }
  Remove-Item -LiteralPath $pidPath -Force
  Write-Host "Removed a stale PID file; the service was not running."
  return
}

$expectedPython = [System.IO.Path]::GetFullPath((Get-WefVenvPython))
$recordedPython = [System.IO.Path]::GetFullPath([string]$serviceRecord.server_path)
$actualExecutable = if ($null -eq $serviceProcessInfo.ExecutablePath) { "" } else {
  [System.IO.Path]::GetFullPath([string]$serviceProcessInfo.ExecutablePath)
}
$commandLine = [string]$serviceProcessInfo.CommandLine
if (
  -not $actualExecutable.Equals($expectedPython, [StringComparison]::OrdinalIgnoreCase) -or
  -not $recordedPython.Equals($expectedPython, [StringComparison]::OrdinalIgnoreCase) -or
  $commandLine.IndexOf("workflow_environment_factory.cli", [StringComparison]::OrdinalIgnoreCase) -lt 0
) {
  throw "PID $serviceProcessId does not belong to this Workflow Environment Factory checkout. Refusing to stop it."
}
$health = Get-WefHealth $Port
if (
  $null -eq $health -or
  $health.product -ne "workflow-environment-factory" -or
  [string]$health.instance_id -cne [string]$serviceRecord.process_token
) {
  throw "The service did not prove its per-process identity. Refusing to stop PID $serviceProcessId."
}

Stop-Process -Id $serviceProcessId
for ($attempt = 0; $attempt -lt 40; $attempt += 1) {
  Start-Sleep -Milliseconds 125
  if ($null -eq (Get-Process -Id $serviceProcessId -ErrorAction SilentlyContinue)) { break }
}
if ($null -ne (Get-Process -Id $serviceProcessId -ErrorAction SilentlyContinue)) {
  throw "Service process $serviceProcessId did not stop."
}
Remove-Item -LiteralPath $pidPath -Force
Write-Host "Workflow Environment Factory stopped. Blueprints, Cases, Runs, and Scores were preserved."
