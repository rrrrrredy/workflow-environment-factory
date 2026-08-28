# Acceptance and evidence

Passing a build is not product acceptance. The 0.1 release requires two real golden workflows plus the minimum failure and recovery evidence needed to trust their result.

## Current status

| Gate | Status on 2026-08-28 | Evidence boundary |
|---|---|---|
| Strict frontend production build | Passed | TypeScript strict check and Vite production bundle |
| Focused backend golden scenarios | Passed | Three tests cover API auth, code vertical, and recorded Issue-to-PR vertical using the explicit local test engine |
| Plugin and MCP structure | Passed | Official plugin validator, Skill validator, local structure validator, Node syntax, and MCP initialize/tools handshake |
| Synthetic real-browser product flow | Passed | Local recording, three Case columns, inspector, three Runs, `not_scored` timeout boundary, mobile no-overflow, and zero console errors in Edge/Playwright |
| Service lifecycle | Passed | Background start, authenticated health, verified-PID stop, and exact temporary-data cleanup |
| Real Docker code vertical | **Pending** | Docker is not installed on the current development host; local tests do not satisfy this gate |
| Real Docker Issue-to-PR vertical | **Pending** | Same blocker; must run the release-only Docker gate with an immutable real image |
| Real Codex controlled Run with plugin | **Pending** | Must be performed in a clean acceptance environment, not by installing the preview into the developer's active Codex |
| Fresh Windows 11 install/uninstall | **Pending** | Requires a separate clean environment and proof that no plugin/service/startup state remains after uninstall |
| Two independent pre-release reviews | **Pending** | One adversarial reviewer and one user-perspective reviewer run only after release candidates are complete |

The repository must remain a technical preview while any bold pending gate remains.

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

The gate creates temporary local data and executes both product verticals through `DockerEngine`:

- code: 3/3 generated Cases pass baseline-fail, correct-pass, and reset equality; a wrong Run fails and a corrected Run passes;
- Issue-to-PR: 3/3 generated Cases pass code, simulator negative/positive, reset, and provenance gates; correct code without PR/status fails; correct code plus linked PR and target status passes.

The temporary path is resolved under the repository's ignored `.runtime-data\docker-gate-*` prefix before recursive cleanup.

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
- Failed reset records `reset_error` and attempts exact worktree/simulator cleanup.
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
8. Stop and restart the service; verify retained documents and interrupted-Run recovery.
9. Export and validate a Case, Score, and task pack with Agent Run Protocol tooling.
10. Uninstall without deleting data; confirm plugin, marketplace, service, and startup state are gone.
11. Optionally reinstall and prove preserved data reopens.
12. Uninstall with a dedicated disposable data directory and `-DeleteData`; verify only that exact directory is removed.

Store command output, protocol files, screenshots containing synthetic or deliberately non-sensitive data, and the clean-environment description with the release evidence. Do not replace these steps with a build badge.
