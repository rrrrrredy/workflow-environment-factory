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

$rawProcessId = (Get-Content -LiteralPath $pidPath -Raw).Trim()
$serviceProcessId = 0
if (-not [int]::TryParse($rawProcessId, [ref]$serviceProcessId) -or $serviceProcessId -le 0) {
  throw "Invalid service PID file: $pidPath"
}

$serviceProcessInfo = Get-CimInstance Win32_Process -Filter "ProcessId = $serviceProcessId" -ErrorAction SilentlyContinue
if ($null -eq $serviceProcessInfo) {
  Remove-Item -LiteralPath $pidPath -Force
  Write-Host "Removed a stale PID file; the service was not running."
  return
}

$expectedPython = [System.IO.Path]::GetFullPath((Get-WefVenvPython))
$actualExecutable = if ($null -eq $serviceProcessInfo.ExecutablePath) { "" } else {
  [System.IO.Path]::GetFullPath([string]$serviceProcessInfo.ExecutablePath)
}
$commandLine = [string]$serviceProcessInfo.CommandLine
if (
  -not $actualExecutable.Equals($expectedPython, [StringComparison]::OrdinalIgnoreCase) -or
  $commandLine.IndexOf("workflow_environment_factory.cli", [StringComparison]::OrdinalIgnoreCase) -lt 0
) {
  throw "PID $serviceProcessId does not belong to this Workflow Environment Factory checkout. Refusing to stop it."
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
