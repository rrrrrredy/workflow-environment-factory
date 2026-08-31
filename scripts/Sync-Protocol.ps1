param(
  [string]$ProtocolRoot = "",
  [string]$ReleaseUrl = "https://github.com/rrrrrredy/runcase-interchange/releases/download/v0.1.1/runcase-interchange-schemas-0.1.1.zip",
  [string]$ExpectedSha256 = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"
$repositoryRoot = [System.IO.Path]::GetFullPath((Join-Path $PSScriptRoot ".."))
$destination = Join-Path $repositoryRoot ".runtime-deps\runcase-interchange\0.1.1\schemas"
New-Item -ItemType Directory -Path $destination -Force | Out-Null
$schemaNames = @(
  "agent.run.v1.schema.json",
  "workflow.case.v1.schema.json",
  "workflow.score.v1.schema.json"
)
$protocolCommit = "f4949e9e65cb7948a03e1d8bfe19dc915db31fd2"
$expectedSchemaSha256 = @{
  "agent.run.v1.schema.json" = "4ece323040ae5b1caa8f15ef833ad21430e27f03f111c0ed3aea8cb820777df4"
  "workflow.case.v1.schema.json" = "c99988eefd2654016c8f5b4783e98cd043cb1aff27dc564ebd97ca5bd03197ce"
  "workflow.score.v1.schema.json" = "a8fb3c43870c4c0e8a8358208bdc5d28d8fab35ebf72400a3109625127da7a36"
}

function Copy-Schemas([string]$SourceDirectory) {
  $resolvedSource = [System.IO.Path]::GetFullPath($SourceDirectory)
  foreach ($name in $schemaNames) {
    $sourcePath = Join-Path $resolvedSource $name
    if (-not (Test-Path -LiteralPath $sourcePath -PathType Leaf)) { throw "Protocol schema missing: $sourcePath" }
    $actualHash = (Get-FileHash -LiteralPath $sourcePath -Algorithm SHA256).Hash.ToLowerInvariant()
    if ($actualHash -cne $expectedSchemaSha256[$name]) {
      throw "Protocol schema $name does not match RunCase Interchange v0.1.1 commit $protocolCommit. Expected $($expectedSchemaSha256[$name]), got $actualHash."
    }
    Copy-Item -LiteralPath $sourcePath -Destination (Join-Path $destination $name) -Force
  }
}

if (-not [string]::IsNullOrWhiteSpace($ProtocolRoot)) {
  $schemaSource = Join-Path ([System.IO.Path]::GetFullPath($ProtocolRoot)) "schemas"
  Copy-Schemas $schemaSource
} else {
  if ([string]::IsNullOrWhiteSpace($ExpectedSha256)) {
    throw "ExpectedSha256 is required for a remote protocol release. Use -ProtocolRoot for a local development checkout."
  }
  $temporaryRoot = Join-Path ([System.IO.Path]::GetTempPath()) "wef-rci-sync-$([Guid]::NewGuid().ToString('N'))"
  New-Item -ItemType Directory -Path $temporaryRoot | Out-Null
  try {
    $archive = Join-Path $temporaryRoot "protocol.zip"
    Invoke-WebRequest -UseBasicParsing -Uri $ReleaseUrl -OutFile $archive
    $actual = (Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash
    if (-not $actual.Equals($ExpectedSha256, [StringComparison]::OrdinalIgnoreCase)) {
      throw "Protocol release checksum mismatch. Expected $ExpectedSha256, got $actual."
    }
    $expanded = Join-Path $temporaryRoot "expanded"
    Expand-Archive -LiteralPath $archive -DestinationPath $expanded
    $schemaDirectory = Get-ChildItem -LiteralPath $expanded -Directory -Recurse | Where-Object { $_.Name -eq "schemas" } | Select-Object -First 1
    if ($null -eq $schemaDirectory) { throw "Protocol release does not contain a schemas directory." }
    Copy-Schemas $schemaDirectory.FullName
  } finally {
    if (Test-Path -LiteralPath $temporaryRoot -PathType Container) {
      $resolvedTemporary = (Resolve-Path -LiteralPath $temporaryRoot).Path
      $expectedPrefix = Join-Path ([System.IO.Path]::GetTempPath()) "wef-rci-sync-"
      if (-not $resolvedTemporary.StartsWith($expectedPrefix, [StringComparison]::OrdinalIgnoreCase)) {
        throw "Unsafe protocol sync cleanup target: $resolvedTemporary"
      }
      Remove-Item -LiteralPath $resolvedTemporary -Recurse -Force
    }
  }
}

Write-Host "RunCase Interchange 0.1.1 schemas from commit $protocolCommit synced to $destination"
