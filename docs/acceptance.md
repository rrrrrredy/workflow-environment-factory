# Acceptance and evidence

Passing a build is not product acceptance. Version 0.2.1 separates deterministic Case evidence, hosted package lifecycle evidence, platform isolation evidence, and authenticated Agent evidence so one cannot substitute for another.

## Current status

| Gate | Status on 2026-08-31 | Evidence boundary |
|---|---|---|
| Strict frontend and backend checks | Passed | Production React build, Python static analysis, twenty focused tests, portable lifecycle tests, and plugin/MCP validation on the frozen candidate |
| Agent answer-isolation regression | Passed | Agent Run has no `.git`, remote, alternates, or known-correct object; MCP Agent view omits solution commit and patch digest; untracked paths are scored |
| Synthetic real-browser product flow | Passed | Local recording, three Case columns, inspector, three Runs, `not_scored` timeout boundary, mobile no-overflow, and zero console errors with generated data |
| Hosted Windows archive lifecycle | Passed | Install/repair failure rollback, loopback service, plugin/marketplace ownership, preservation, explicit deletion, and final absence; Docker is an explicitly recorded command stub |
| Hosted Linux archive lifecycle | Passed | Build, plugin/service restart and removal, final absence, and a reachable real Docker daemon |
| Hosted macOS archive lifecycle | Passed | Build, plugin/service restart and removal, final absence, and no-model read isolation; no Docker task gate or physical Mac |
| Real Docker code vertical | Passed on hosted Linux | Three Cases prove baseline fail, correct state pass, reset equality, wrong Run fail, and corrected Run pass against the immutable release image |
| Real Docker Issue-to-PR vertical | Passed on hosted Linux | Three Cases prove code and simulator negative/positive states, resets, provenance, and objective scoring against the immutable release image |
| Windows Codex read isolation | Known unsupported | Exact deny-read ACL setup or enforcement failure only; `agent_execution_supported=false` and `model_executed=false` |
| Hosted Linux Codex read isolation | Known unsupported | Exact `bwrap` network-namespace failure only; `agent_execution_supported=false` and `model_executed=false` |
| Hosted macOS Codex read isolation | Passed | No-model shell writes only in the Run workspace and cannot read the product database or known-correct source commit |
| Authenticated Codex code and Issue-to-PR Runs | Not run | Still required before a stable label; deterministic correct states are not credited to Codex |
| Ordinary user-owned clean machine and physical Mac | Not run | Hosted lifecycle jobs do not substitute for either environment |
| Independent adversarial and user-perspective review | Performed | Findings are tracked as release blockers or explicit preview limitations; the tag workflow must still pass after accepted fixes |

The repository remains a technical preview while the authenticated Agent and ordinary-machine gates are not run. A known-unsupported platform record never enables Agent execution.

## Regular local check

```powershell
$env:WEF_NODE = 'C:\path\to\node-v22\node.exe'
$env:WEF_PYTHON = 'C:\path\to\python.exe'
.\scripts\Check.ps1 -InstallDependencies
```

This checks the build and focused contracts without pretending to be a Docker acceptance run.

## Release-only real Docker gate

Choose a reviewed immutable image digest that contains Python and can execute the synthetic verifier, then run:

```powershell
$env:WEF_DOCKER_GATE_IMAGE = 'python@sha256:<reviewed-real-digest>'
.\scripts\Check.ps1 -RequireDocker
```

The gate creates temporary local data and executes both environment/verifier verticals through `DockerEngine`:

- code: 3/3 generated Cases pass baseline-fail, correct-pass, and reset equality; a wrong Run fails and a corrected Run passes;
- Issue-to-PR: 3/3 generated Cases pass code, simulator negative/positive, reset, and provenance gates; correct code without PR/status fails; correct code plus linked PR and target status passes.

The temporary path is resolved under the repository's ignored `.runtime-data\docker-gate-*` prefix before recursive cleanup.

This deterministic gate applies the known correct code and simulator state programmatically. It proves reset, discrimination, provenance, Docker containment, and scoring; it is not evidence that Codex completed either task.

## Release-only real Codex gate

On a clean Windows 11 checkout with authenticated Codex and Docker Desktop, set the reviewed image and run:

```powershell
$env:WEF_NODE = 'C:\path\to\node-v22\node.exe'
$env:WEF_PYTHON = 'C:\path\to\python.exe'
$env:WEF_DOCKER_GATE_IMAGE = 'python:3.11.16-slim-bookworm@sha256:0bee7276f83efd4a1ee05bbbf4281d95ed28e079220a9457f25a93e3f1e3c31b'
.\scripts\Prepare-ReleaseEvidence.ps1 -Version 0.2.1 -ProtocolRoot C:\path\to\runcase-interchange
```

The script refuses a dirty checkout or an existing product installation. It temporarily installs the real plugin and validates the user-facing distribution path, starts the loopback service with disposable data, then runs authenticated Codex with ambient user config disabled and only the product's MCP server explicitly registered. Codex completes one code Case and one Issue-to-PR Case; Docker-backed scoring proves the outcomes, the known-correct object remains absent, required MCP simulator actions are present, and both Runs are cleaned. The gate then uninstalls and proves that plugin, marketplace, service, Startup entry, and data are absent. It writes only a sanitized, commit-bound JSON evidence file; prompts, repository contents, credentials, and local paths are excluded.

Run this gate from an ordinary Windows Terminal or PowerShell session. Each real Run first performs a no-model App Server workspace preflight under the same offline writable-root boundary; a failure stops before model use and makes the release gate inconclusive. Never rerun it with unrestricted Codex execution merely to obtain a green artifact.

The evidence is single-run proof for two golden tasks, not a model-quality benchmark. Review and commit only `release-evidence/workflow-product-gate-0.2.1.json`, then run `scripts\Verify-ReleaseEvidence.ps1` before tagging.

## Synthetic browser probe

The checked-in probe uses only generated repository content, generated commits, a local test engine, and a local SQLite simulator. It never uses a real user path, prompt, token, repository, or account in screenshots.

Expected assertions:

```json
{
  "recordedOptionPresent": true,
  "caseColumns": 3,
  "inspectorVisible": true,
  "runCount": 3,
  "notScoredBoundaryVisible": true,
  "noHorizontalOverflow": true,
  "browserErrors": []
}
```

## Necessary fault cases

- Service restart while a Run is preparing, running, or validating becomes `environment_error`.
- Agent timeout and crash produce `not_scored`, with no objective validator inferred.
- Docker timeout removes the named container.
- Failed reset records `reset_error` and attempts exact isolated workspace/Git-state and simulator cleanup.
- Verifier infrastructure error is not converted into a failed task.
- Updating a Run after scoring does not delete its Score.
- Secret-like runner and verifier output is redacted before durable storage.
- Simulator cleanup removes the exact database and sidecars only.
- A missing PID file never causes the stop script to guess a process.

## Clean-Windows release checklist

1. Start from a Windows 11 user with no prior product marketplace, plugin, data directory, service, or startup shortcut.
2. Verify the release archive SHA-256 and extract it.
3. Install with Docker, Python, Node, Git, and Codex already present.
4. Restart Codex and confirm the product Skill and six MCP tools appear.
5. Complete one real code Blueprint with a base Case and two valid variants.
6. Complete one local Issue-to-PR recording, Blueprint, base Case, and two valid variants.
7. Execute Codex on one wrong and one correct path for each vertical and inspect objective Scores.
   Confirm the Agent-safe MCP response omits the known-correct commit and patch digest, and `git cat-file` cannot read the known-correct object from the Run.
8. Stop and restart the service; verify retained documents and interrupted-Run recovery.
9. Export and validate a Case, Score, and task pack with RunCase Interchange tooling.
10. Uninstall without deleting data; confirm plugin, marketplace, service, and startup state are gone.
11. Optionally reinstall and prove preserved data reopens.
12. Uninstall with a dedicated disposable data directory and `-DeleteData`; verify only that exact directory is removed.
13. Occupy the configured port before a first install and a later `-Repair`; verify the first leaves no new product state and the second restores the prior plugin, marketplace, Startup shortcut, and data.
14. Require the machine-readable installation-state audit to pass after normal removal and again with no data after explicit deletion.

Store command output, protocol files, screenshots containing synthetic or deliberately non-sensitive data, and the clean-environment description with the release evidence. Do not replace these steps with a build badge.

The repeatable clean-user installation portion is encoded in `scripts\Acceptance-InstallUninstall.ps1`. Its Windows evidence and the Ubuntu real-Docker golden evidence are complementary. A final release still requires the checklist above on Windows 11 with Docker Desktop Linux containers; combining two CI machines must not be described as that single-host acceptance.

`scripts/Acceptance-Portable.sh` adds hosted Ubuntu and macOS plugin/service lifecycle evidence. Ubuntu requires its real Docker daemon; macOS intentionally records only build, plugin, loopback service, restart, uninstall, and absence because GitHub-hosted macOS has no Docker Desktop task gate. Neither hosted result is presented as a physical-machine or authenticated model run.
