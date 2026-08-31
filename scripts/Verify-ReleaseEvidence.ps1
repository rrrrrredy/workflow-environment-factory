param(
  [string]$Version = "0.2.0"
)

. (Join-Path $PSScriptRoot "Common.ps1")

Push-Location $script:WefRoot
try {
  $relativeEvidence = "release-evidence/workflow-product-gate-$Version.json"
  $evidencePath = Join-Path $script:WefRoot $relativeEvidence
  if (-not (Test-Path -LiteralPath $evidencePath -PathType Leaf)) {
    throw "Release evidence is missing: $relativeEvidence"
  }
  $evidence = Get-Content -LiteralPath $evidencePath -Raw | ConvertFrom-Json
  if ($evidence.product -ne "workflow-environment-factory" -or $evidence.version -ne $Version) {
    throw "Release evidence names the wrong product or version."
  }
  if ($evidence.schema_version -ne "product.real-codex-gate.v1") {
    throw "Release evidence has an unsupported schema."
  }
  if ([string]$evidence.testedCommit -notmatch '^[0-9a-f]{40}$') {
    throw "Release evidence has an invalid testedCommit."
  }
  $expectedImage = "python:3.11.16-slim-bookworm@sha256:0bee7276f83efd4a1ee05bbbf4281d95ed28e079220a9457f25a93e3f1e3c31b"
  if ($evidence.dockerImage -ne $expectedImage) { throw "Release evidence used another Docker image." }
  if ([string]$evidence.codexVersion -notmatch '0\.150\.0-alpha\.8') {
    throw "Release evidence was not produced with supported Codex 0.150.0-alpha.8."
  }
  $required = @(
    ([int]$evidence.cases.codeGenerated -eq 3),
    ([int]$evidence.cases.issuePrGenerated -eq 3),
    [bool]$evidence.cases.allGenerationGatesPassed,
    ([int]$evidence.cases.taskPackCaseCount -eq 3),
    [bool]$evidence.isolation.noDotGitInAgentWorkspace,
    [bool]$evidence.isolation.noRemote,
    [bool]$evidence.isolation.noAlternateObjectStore,
    [bool]$evidence.isolation.knownCorrectObjectUnavailable,
    [bool]$evidence.isolation.agentViewOmittedFactoryEvidence,
    [bool]$evidence.realCodex.codeWorkspacePreflight,
    ($evidence.realCodex.codeTaskStatus -eq "pass"),
    ($evidence.realCodex.codeExecutionStatus -eq "completed"),
    ([int]$evidence.realCodex.codeEventCount -gt 0),
    [bool]$evidence.realCodex.issuePrWorkspacePreflight,
    ($evidence.realCodex.issuePrTaskStatus -eq "pass"),
    ($evidence.realCodex.issuePrExecutionStatus -eq "completed"),
    ([int]$evidence.realCodex.issuePrEventCount -gt 0),
    [bool]$evidence.realCodex.issueRead,
    [bool]$evidence.realCodex.pullRequestCreated,
    [bool]$evidence.realCodex.issueStatusUpdated,
    [bool]$evidence.realCodex.singleRunEvidence,
    [bool]$evidence.probeCleanup.workspacesAndGitStateRemoved,
    [bool]$evidence.dataPolicy.fullySynthetic,
    (-not [bool]$evidence.dataPolicy.containsPromptOrRepositoryContent),
    (-not [bool]$evidence.dataPolicy.containsCredentialOrLocalPath),
    [bool]$evidence.installationCleanup.serviceStopped,
    [bool]$evidence.installationCleanup.pluginRemoved,
    [bool]$evidence.installationCleanup.marketplaceRemoved,
    [bool]$evidence.installationCleanup.startupAbsent,
    [bool]$evidence.installationCleanup.disposableDataDeleted
  )
  if ($required -contains $false) { throw "Release evidence does not satisfy every real product-gate condition." }

  git cat-file -e "$($evidence.testedCommit)^{commit}"
  if ($LASTEXITCODE -ne 0) { throw "The tested commit is not present in this checkout." }
  git merge-base --is-ancestor $evidence.testedCommit HEAD
  if ($LASTEXITCODE -ne 0) { throw "The tested commit is not an ancestor of the release tag." }
  $changed = @(git diff --name-only "$($evidence.testedCommit)..HEAD" | Where-Object {
    -not [string]::IsNullOrWhiteSpace($_)
  })
  $unexpected = @($changed | Where-Object { $_ -ne $relativeEvidence })
  if ($changed.Count -ne 1 -or $unexpected.Count -gt 0) {
    throw "Only $relativeEvidence may change after the real product gate. Re-run the gate on the current code."
  }
  Write-Host "Real Codex release evidence verified for v$Version at tested commit $($evidence.testedCommit)."
} finally {
  Pop-Location
}
