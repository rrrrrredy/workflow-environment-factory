param(
  [string]$Version = "0.1.0",
  [string]$OutputDirectory = "",
  [string]$ProtocolRoot = ""
)

. (Join-Path $PSScriptRoot "Common.ps1")

if (-not [string]::IsNullOrWhiteSpace($ProtocolRoot)) {
  & (Join-Path $PSScriptRoot "Sync-Protocol.ps1") -ProtocolRoot $ProtocolRoot
}
& (Join-Path $PSScriptRoot "Verify-ReleaseEvidence.ps1") -Version $Version
if ($LASTEXITCODE -ne 0) { throw "Authenticated real Codex release evidence is invalid." }
& (Join-Path $PSScriptRoot "Check.ps1") -InstallDependencies -RequireDocker -ProtocolRoot $ProtocolRoot
if ($LASTEXITCODE -ne 0) { throw "Release checks failed." }

Push-Location $script:WefRoot
try {
  $status = (git status --porcelain=v1 | Out-String).Trim()
  if ($LASTEXITCODE -ne 0) { throw "The checkout is not a Git repository." }
  if ($status.Length -gt 0) { throw "Release packaging requires a clean Git checkout so the archive matches the reviewed commit." }

  $package = Get-Content -LiteralPath (Join-Path $script:WefRoot "package.json") -Raw | ConvertFrom-Json
  $manifest = Get-Content -LiteralPath (Join-Path $script:WefRoot "plugins\workflow-environment-factory\.codex-plugin\plugin.json") -Raw | ConvertFrom-Json
  if ($package.version -ne $Version -or $manifest.version -ne $Version) {
    throw "Requested version $Version must match package.json and plugin.json."
  }
  $commit = (git rev-parse HEAD | Out-String).Trim()
  if ($LASTEXITCODE -ne 0 -or $commit -notmatch '^[0-9a-f]{40}$') { throw "Could not resolve release commit." }

  $schemaDirectory = Get-WefProtocolDir
  $productEvidencePath = Join-Path $script:WefRoot "release-evidence\workflow-product-gate-$Version.json"
  foreach ($schema in @("agent.run.v1.schema.json", "workflow.case.v1.schema.json", "workflow.score.v1.schema.json")) {
    if (-not (Test-Path -LiteralPath (Join-Path $schemaDirectory $schema) -PathType Leaf)) {
      throw "Release dependency is missing: $schema"
    }
  }

  $outputRoot = if ([string]::IsNullOrWhiteSpace($OutputDirectory)) {
    Join-Path $script:WefRoot "artifacts"
  } else { [System.IO.Path]::GetFullPath($OutputDirectory) }
  New-Item -ItemType Directory -Path $outputRoot -Force | Out-Null
  $archivePath = Join-Path $outputRoot "workflow-environment-factory-$Version-windows-x64.zip"
  $checksumPath = "$archivePath.sha256"
  $manifestPath = Join-Path $outputRoot "workflow-environment-factory-$Version.release.json"
  foreach ($existing in @($archivePath, $checksumPath, $manifestPath)) {
    if (Test-Path -LiteralPath $existing -PathType Leaf) { Remove-Item -LiteralPath $existing -Force }
  }

  $temporaryRoot = Join-Path ([System.IO.Path]::GetTempPath()) "wef-package-$([Guid]::NewGuid().ToString('N'))"
  New-Item -ItemType Directory -Path $temporaryRoot | Out-Null
  try {
    $folderName = "workflow-environment-factory-$Version"
    $sourceArchive = Join-Path $temporaryRoot "source.zip"
    $expanded = Join-Path $temporaryRoot "expanded"
    git archive --format=zip --prefix="$folderName/" --output=$sourceArchive HEAD
    if ($LASTEXITCODE -ne 0) { throw "git archive failed." }
    Expand-Archive -LiteralPath $sourceArchive -DestinationPath $expanded
    $stageRoot = Join-Path $expanded $folderName
    $releaseSource = [ordered]@{
      schema_version = "product.release-source.v1"
      product = "workflow-environment-factory"
      version = $Version
      commit = $commit
    } | ConvertTo-Json -Depth 3
    [System.IO.File]::WriteAllText((Join-Path $stageRoot "release-source.json"), "$releaseSource`n", [Text.UTF8Encoding]::new($false))

    Copy-Item -LiteralPath (Join-Path $script:WefRoot "dist\web") -Destination (Join-Path $stageRoot "dist\web") -Recurse -Force
    $stagedSchemaDirectory = Join-Path $stageRoot ".runtime-deps\runcase-interchange\0.1.0\schemas"
    New-Item -ItemType Directory -Path $stagedSchemaDirectory -Force | Out-Null
    foreach ($schema in @("agent.run.v1.schema.json", "workflow.case.v1.schema.json", "workflow.score.v1.schema.json")) {
      Copy-Item -LiteralPath (Join-Path $schemaDirectory $schema) -Destination (Join-Path $stagedSchemaDirectory $schema) -Force
    }
    $schemaHashes = [ordered]@{}
    foreach ($schema in @("agent.run.v1.schema.json", "workflow.case.v1.schema.json", "workflow.score.v1.schema.json")) {
      $schemaHashes[$schema] = (Get-FileHash -LiteralPath (Join-Path $schemaDirectory $schema) -Algorithm SHA256).Hash.ToLowerInvariant()
    }
    $dependencyManifest = [ordered]@{
      name = "runcase-interchange"
      version = "0.1.0"
      source = "https://github.com/rrrrrredy/runcase-interchange"
      release = "https://github.com/rrrrrredy/runcase-interchange/releases/tag/v0.1.0"
      files = $schemaHashes
    } | ConvertTo-Json -Depth 4
    [System.IO.File]::WriteAllText((Join-Path $stageRoot ".runtime-deps\runcase-interchange\dependency.json"), "$dependencyManifest`n")

    $tar = Get-Command tar.exe -ErrorAction SilentlyContinue
    if ($null -eq $tar) { $tar = Get-Command tar -ErrorAction Stop }
    & $tar.Source -a -c -f $archivePath -C $expanded $folderName
    if ($LASTEXITCODE -ne 0) { throw "Release archive creation failed." }
    $listing = (& $tar.Source -tf $archivePath | Out-String)
    foreach ($required in @(
      "$folderName/.agents/plugins/marketplace.json",
      "$folderName/release-source.json",
      "$folderName/release-evidence/workflow-product-gate-$Version.json",
      "$folderName/scripts/Acceptance-InstallUninstall.ps1",
      "$folderName/plugins/workflow-environment-factory/.codex-plugin/plugin.json",
      "$folderName/dist/web/index.html",
      "$folderName/.runtime-deps/runcase-interchange/0.1.0/schemas/workflow.case.v1.schema.json"
    )) {
      if (-not $listing.Contains($required, [StringComparison]::Ordinal)) {
        throw "Release archive is missing required file: $required"
      }
    }
  } finally {
    if (Test-Path -LiteralPath $temporaryRoot -PathType Container) {
      $resolvedTemporary = (Resolve-Path -LiteralPath $temporaryRoot).Path
      $expectedPrefix = Join-Path ([System.IO.Path]::GetTempPath()) "wef-package-"
      if (-not $resolvedTemporary.StartsWith($expectedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Unsafe package cleanup target: $resolvedTemporary"
      }
      Remove-Item -LiteralPath $resolvedTemporary -Recurse -Force
    }
  }

  $checksum = (Get-FileHash -LiteralPath $archivePath -Algorithm SHA256).Hash.ToLowerInvariant()
  $productEvidenceHash = (Get-FileHash -LiteralPath $productEvidencePath -Algorithm SHA256).Hash.ToLowerInvariant()
  [System.IO.File]::WriteAllText($checksumPath, "$checksum  workflow-environment-factory-$Version-windows-x64.zip`n")
  $protocolHashes = [ordered]@{}
  foreach ($schema in @("agent.run.v1.schema.json", "workflow.case.v1.schema.json", "workflow.score.v1.schema.json")) {
    $protocolHashes[$schema] = (Get-FileHash -LiteralPath (Join-Path $schemaDirectory $schema) -Algorithm SHA256).Hash.ToLowerInvariant()
  }
  $releaseManifest = [ordered]@{
    schema_version = "workflow-environment-factory.release.v1"
    version = $Version
    commit = $commit
    protocol_dependency = [ordered]@{
      name = "runcase-interchange"
      version = "0.1.0"
      schema_sha256 = $protocolHashes
    }
    docker_gate_image = [string]$env:WEF_DOCKER_GATE_IMAGE
    real_codex_evidence = [ordered]@{
      file = "release-evidence/workflow-product-gate-$Version.json"
      sha256 = $productEvidenceHash
    }
    archive = [ordered]@{
      file = [System.IO.Path]::GetFileName($archivePath)
      sha256 = $checksum
      bytes = (Get-Item -LiteralPath $archivePath).Length
    }
    created_at = [DateTime]::UtcNow.ToString("o")
  } | ConvertTo-Json -Depth 7
  [System.IO.File]::WriteAllText($manifestPath, "$releaseManifest`n", [Text.UTF8Encoding]::new($false))
  Write-Host "Release archive: $archivePath"
  Write-Host "SHA-256: $checksum"
} finally {
  Pop-Location
}
