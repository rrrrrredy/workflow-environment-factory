param(
  [switch]$Foreground,
  [switch]$Open,
  [ValidateRange(1024, 65535)][int]$Port = 43121,
  [string]$DataDir = ""
)

. (Join-Path $PSScriptRoot "Common.ps1")

$python = Get-WefVenvPython
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
  throw "The product virtual environment is missing. Run scripts\Install.ps1 or scripts\Build.ps1 -InstallDependencies."
}
$webIndex = Join-Path $script:WefRoot "dist\web\index.html"
if (-not (Test-Path -LiteralPath $webIndex -PathType Leaf)) { throw "The production UI is missing. Run scripts\Build.ps1 first." }
$protocolDirectory = Get-WefProtocolDir
if (-not (Test-Path -LiteralPath (Join-Path $protocolDirectory "workflow.case.v1.schema.json") -PathType Leaf)) {
  throw "RunCase Interchange schemas are missing. Run scripts\Sync-Protocol.ps1 first."
}

$resolvedDataDir = Get-WefDataDir $DataDir
$pidPath = Join-Path $resolvedDataDir "service.pid"
$existingHealth = Get-WefHealth $Port
if ($null -ne $existingHealth) {
  if ($existingHealth.product -ne "workflow-environment-factory") { throw "Port $Port is already serving another application." }
  if (-not (Test-Path -LiteralPath $resolvedDataDir -PathType Container)) {
    throw "A Factory service is reachable, but this data directory does not exist. Refusing to adopt it."
  }
  Assert-WefDataRoot $resolvedDataDir | Out-Null
  if (-not (Test-Path -LiteralPath $pidPath -PathType Leaf)) {
    throw "A Factory service is reachable, but this data directory has no service ownership record. Refusing to adopt it."
  }
  try { $serviceRecord = Get-Content -LiteralPath $pidPath -Raw | ConvertFrom-Json }
  catch { throw "Invalid service ownership record: $pidPath" }
  $expectedRepository = [System.IO.Path]::GetFullPath($script:WefRoot)
  $expectedPython = [System.IO.Path]::GetFullPath((Get-WefVenvPython))
  if (
    $serviceRecord.schema_version -ne "product.windows-service.v2" -or
    $serviceRecord.product -ne "workflow-environment-factory" -or
    [int]$serviceRecord.port -ne $Port -or
    -not ([System.IO.Path]::GetFullPath([string]$serviceRecord.repository_root)).Equals($expectedRepository, [StringComparison]::OrdinalIgnoreCase) -or
    -not ([System.IO.Path]::GetFullPath([string]$serviceRecord.server_path)).Equals($expectedPython, [StringComparison]::OrdinalIgnoreCase) -or
    [string]$serviceRecord.process_token -notmatch '^[a-f0-9]{64}$' -or
    [string]$existingHealth.instance_id -cne [string]$serviceRecord.process_token
  ) {
    throw "The reachable Factory service did not prove ownership by this checkout and data directory. Refusing to adopt it."
  }
  $existingUrl = Get-WefSessionUrl $resolvedDataDir $Port
  Write-Host "Workflow Environment Factory is already running."
  if ($null -ne $existingUrl) {
    Write-Host $existingUrl
    if ($Open) { Start-Process $existingUrl }
  }
  return
}

Initialize-WefDataRoot $resolvedDataDir
$logsDir = Join-Path $resolvedDataDir "logs"
New-Item -ItemType Directory -Path $logsDir -Force | Out-Null
$stdoutPath = Join-Path $logsDir "service.stdout.log"
$stderrPath = Join-Path $logsDir "service.stderr.log"
$processToken = "$([Guid]::NewGuid().ToString('N'))$([Guid]::NewGuid().ToString('N'))"

$environmentNames = @("WEF_DATA_DIR", "WEF_PORT", "WEF_HOST", "WEF_PROTOCOL_SCHEMA_DIR", "WEF_PROCESS_TOKEN", "PYTHONUNBUFFERED")
$previousEnvironment = @{}
foreach ($name in $environmentNames) { $previousEnvironment[$name] = [Environment]::GetEnvironmentVariable($name, "Process") }
[Environment]::SetEnvironmentVariable("WEF_DATA_DIR", $resolvedDataDir, "Process")
[Environment]::SetEnvironmentVariable("WEF_PORT", [string]$Port, "Process")
[Environment]::SetEnvironmentVariable("WEF_HOST", "127.0.0.1", "Process")
[Environment]::SetEnvironmentVariable("WEF_PROTOCOL_SCHEMA_DIR", $protocolDirectory, "Process")
[Environment]::SetEnvironmentVariable("WEF_PROCESS_TOKEN", $processToken, "Process")
[Environment]::SetEnvironmentVariable("PYTHONUNBUFFERED", "1", "Process")

try {
  if ($Foreground) {
    Push-Location $script:WefRoot
    try { & $python -m workflow_environment_factory.cli serve } finally { Pop-Location }
    return
  }
  $serviceProcess = Start-Process `
    -FilePath $python `
    -ArgumentList @("-m", "workflow_environment_factory.cli", "serve") `
    -WorkingDirectory $script:WefRoot `
    -WindowStyle Hidden `
    -PassThru `
    -RedirectStandardOutput $stdoutPath `
    -RedirectStandardError $stderrPath
  $serviceRecord = [ordered]@{
    schema_version = "product.windows-service.v2"
    product = "workflow-environment-factory"
    pid = $serviceProcess.Id
    port = $Port
    repository_root = $script:WefRoot
    server_path = [System.IO.Path]::GetFullPath($python)
    command_marker = "workflow_environment_factory.cli"
    process_token = $processToken
    started_at = [DateTimeOffset]::UtcNow.ToString("o")
  } | ConvertTo-Json -Depth 4
  [System.IO.File]::WriteAllText($pidPath, "$serviceRecord`n", [Text.UTF8Encoding]::new($false))
} finally {
  foreach ($name in $environmentNames) {
    [Environment]::SetEnvironmentVariable($name, $previousEnvironment[$name], "Process")
  }
}

$ready = $false
for ($attempt = 0; $attempt -lt 80; $attempt += 1) {
  Start-Sleep -Milliseconds 250
  if ($serviceProcess.HasExited) { break }
  $health = Get-WefHealth $Port
  if (
    $null -ne $health -and
    $health.product -eq "workflow-environment-factory" -and
    [string]$health.instance_id -ceq $processToken
  ) {
    $ready = $true
    break
  }
}

if (-not $ready) {
  if (-not $serviceProcess.HasExited) { Stop-Process -Id $serviceProcess.Id -Force }
  if (Test-Path -LiteralPath $pidPath -PathType Leaf) { Remove-Item -LiteralPath $pidPath -Force }
  $errorTail = if (Test-Path -LiteralPath $stderrPath -PathType Leaf) {
    (Get-Content -LiteralPath $stderrPath -Tail 30) -join "`n"
  } else { "No service error log was created." }
  throw "Workflow Environment Factory did not become healthy on port $Port.`n$errorTail"
}

$sessionUrl = Get-WefSessionUrl $resolvedDataDir $Port
Write-Host "Workflow Environment Factory is running as process $($serviceProcess.Id)."
Write-Host "Data: $resolvedDataDir"
if ($null -ne $sessionUrl) {
  Write-Host $sessionUrl
  if ($Open) { Start-Process $sessionUrl }
} else {
  Write-Warning "The service is healthy, but its local session URL is not available yet."
}
