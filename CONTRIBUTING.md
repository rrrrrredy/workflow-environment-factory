# Contributing

Contributions are welcome when they preserve the product's evidence boundary: a task environment must be resettable, traceable to a confirmed source, objectively distinguish known wrong and correct states, and honest about what remains unobserved.

## Before opening a change

1. Read [architecture](docs/architecture.md), [security and local data](docs/security-and-data.md), and [known limitations](docs/known-limitations.md).
2. Search existing issues and keep one pull request focused on one user-visible problem.
3. Do not add production credentials, repository data, local paths, transcripts, tokens, or screenshots from real Runs.
4. Do not broaden the 0.1 Agent/platform scope without an accepted design issue.

## Development setup

```powershell
$env:WEF_NODE = 'C:\path\to\node-v22\node.exe'
$env:WEF_PYTHON = 'C:\path\to\python.exe'
.\scripts\Sync-Protocol.ps1 -ProtocolRoot C:\path\to\agent-run-protocol
.\scripts\Check.ps1 -InstallDependencies
```

Use the normal check for local development. The real Docker gate is a release/maintainer check and requires an explicitly reviewed immutable image digest:

```powershell
$env:WEF_DOCKER_GATE_IMAGE = 'python@sha256:<reviewed-real-digest>'
.\scripts\Check.ps1 -RequireDocker
```

## Change expectations

- Backend input models remain strict and reject unknown fields.
- New Case behavior needs negative, positive, and reset evidence in one of the two golden verticals.
- Agent crash, timeout, environment error, reset error, validator error, and task failure must not be collapsed.
- Any durable diagnostic content passes through redaction.
- Recursive or forceful cleanup resolves the exact target under a product-owned root first.
- UI changes need a strict production build and a real browser check at desktop and mobile widths.
- Protocol changes belong in the independent Agent Run Protocol repository first.
- The Codex MCP surface must not gain a score, validator, provenance, or hidden-solution mutation tool.

## Pull requests

Explain the user-visible problem, the evidence supporting the change, the exact verification performed, and any unproven boundary. Synthetic fixtures should say they are synthetic. A green build alone is not acceptance evidence.

By contributing, you agree that your contribution is licensed under Apache-2.0.
