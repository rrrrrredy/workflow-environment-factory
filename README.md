# Workflow Environment Factory

Workflow Environment Factory turns your own repository or Issue-to-PR process into a small, resettable Codex environment: one confirmed source Case, exactly two traceable variants, a fresh state for every attempt, and objective scoring after Codex finishes.

It is not a public benchmark, an environment-outsourcing service, or a dashboard for watching an Agent. The useful output is a task pack you can keep, rerun, inspect, and improve as your repository and workflow change.

> **Release status:** 0.1 technical preview for Windows 11 and Codex. The two product verticals, local UI, plugin, recovery boundaries, and synthetic browser flow are implemented. A real Docker gate and clean-Windows acceptance must still pass before this repository is labeled stable.

![Workflow Environment Factory Case matrix with fully synthetic data](docs/images/ui-desktop-case-factory-synthetic.png)

## What you get

The product has three surfaces:

- **Blueprint** connects a local Git repository or records a local Issue-to-PR demonstration, then confirms the variable, baseline, known-correct revision, immutable container, allowed paths, and completion standard.
- **Case Factory** creates a base Case and exactly two user-confirmed variants. A Case is runnable only when its baseline fails, correct state passes, and two fresh resets match. Issue-to-PR Cases also prove that the wrong simulator state fails and the programmatic correct state passes.
- **Runs & Scores** launches Codex in a new Git worktree and, when needed, a new local Issue/PR database. Task failure, Agent timeout, Agent crash, reset failure, and validator failure remain different outcomes.

Runs & Scores also contains a protocol library: it validates, redacts, and retains imported `agent.run.v1`, `workflow.case.v1`, and `workflow.score.v1` files without silently turning an external document into a runnable local Case.

The Codex plugin contributes one bounded Skill and six MCP tools for reading the active Case and operating the local Issue/PR simulator. It has no tool that changes a validator or score.

## The evidence boundary

A generated task is admitted only when all of these are true:

1. the confirmed baseline fails the objective verifier;
2. the known-correct revision passes it;
3. two independently created baseline states have the same fingerprint;
4. each variant has a named parent and a user-confirmed substitution recipe;
5. for Issue-to-PR, a fresh wrong database state fails and a fresh correct state passes.

This proves that the Case distinguishes the two known states. It does **not** prove that a model is generally good, that a generated variant is realistic in every way, or that one passing Run will pass again. Every Score is labeled single-run evidence.

The known-correct commit and validator implementation are never mounted into the Agent workspace. Screenshots are not accepted as the primary score for code or browser workflow state.

## Quick start

Requirements:

- Windows 11;
- Docker Desktop using Linux containers;
- Python 3.11, 3.12, or 3.13;
- Node.js 22.x;
- Git;
- Codex CLI/Desktop with `codex` on `PATH`;
- PowerShell 7 recommended.

Download the signed-checksum release archive, extract it, inspect the installer, then run:

```powershell
Set-Location workflow-environment-factory-0.1.0
.\scripts\Install.ps1 -Open
```

The installer creates a project-local Python virtual environment, installs the locked frontend and backend dependencies, runs focused checks, confirms Docker and Codex, registers this checkout as a Codex marketplace, installs the plugin, and starts a loopback-only service. Restart Codex after installation.

To run from source before a packaged protocol dependency exists:

```powershell
git clone https://github.com/rrrrrredy/workflow-environment-factory.git
Set-Location workflow-environment-factory
$env:WEF_NODE = 'C:\path\to\node-v22\node.exe'
$env:WEF_PYTHON = 'C:\path\to\python.exe'
.\scripts\Sync-Protocol.ps1 -ProtocolRoot C:\path\to\agent-run-protocol
.\scripts\Install.ps1 -Open
```

See [installation and removal](docs/installation.md) for every state change and the portable start path.

## Normal use

1. Prepare one local repository with a failing baseline commit and a descendant known-correct commit.
2. Pull an image and use its immutable `repository@sha256:…` digest in the Blueprint.
3. For a code task, confirm the value and paths that can become two variants. For Issue-to-PR, first complete the four-step local demonstration recorder.
4. Create the Blueprint, then generate Cases. Do not run any Case whose evidence gate is blocked.
5. Inspect provenance, writable paths, validators, and what Codex cannot see. Export the three-Case task pack if you want a portable record.
6. Prepare a Run. This always creates a new worktree and, for Issue-to-PR, a new SQLite snapshot.
7. Execute with Codex. The plugin exposes only the active local simulator operations.
8. Read the objective Score. Treat a timeout or crash as an execution failure with `not_scored`, not as a failed task.
9. Remove the Run workspace when finished. The retained Case, Run metadata, and Score stay local.

![Workflow Environment Factory separating Agent timeout from task failure](docs/images/ui-desktop-runs-synthetic.png)

## Privacy and security

- The service only accepts `127.0.0.1` and refuses another bind address.
- A random local token protects every API route; the browser receives an HttpOnly, SameSite=Strict cookie.
- Structured Codex events are redacted before storage. Secret-like fields, bearer tokens, API keys, GitHub tokens, private keys, and oversized content are handled explicitly.
- Docker verifiers run with network disabled, CPU/memory/process limits, a read-only container filesystem, and only the fresh workspace mounted.
- The Issue/PR simulator is local SQLite. It never calls GitHub, Linear, or a production account.
- Repository paths and diagnostic content stay on the machine. Protocol exports are explicit user actions.
- The solution revision is used to prove the Case during generation, but it is not mounted into Agent Runs.

Read [security and local data](docs/security-and-data.md) before using the preview on a sensitive repository.

## Uninstall

```powershell
.\scripts\Uninstall.ps1
```

This stops the service and removes the Codex plugin, marketplace entry, and optional startup shortcut. It preserves product data by default. Permanent data removal is a separate explicit action:

```powershell
.\scripts\Uninstall.ps1 -DeleteData
```

The uninstaller resolves and validates the exact data path before recursive deletion. It refuses drive roots, the user profile, and broad application-data roots. It never deletes the source checkout.

## Architecture

- Python 3.11-3.13, FastAPI, Pydantic, SQLite, Git worktrees, and a bounded Docker executor;
- React/Vite local workbench served by the Python service;
- independent Codex plugin with raw-stdio MCP and one Skill;
- local GitHub/Linear-style Issue/PR simulator with database/API validation;
- Agent Run Protocol JSON Schemas as the only cross-product dependency.

Workflow Environment Factory does not share a service, database, queue, UI, executor, or product code with Runtime Evolution Workbench. See [architecture](docs/architecture.md).

## Deliberate non-goals for 0.1

No arbitrary production SaaS cloning, production accounts or data, cloud concurrency, reinforcement learning, model training, multi-Agent orchestration, environment marketplace, screenshot-similarity scoring, unreviewed LLM-generated tasks, or support for Agents other than Codex.

## Development and release gates

```powershell
$env:WEF_NODE = 'C:\path\to\node-v22\node.exe'
$env:WEF_PYTHON = 'C:\path\to\python.exe'
.\scripts\Check.ps1 -InstallDependencies
```

The regular check performs a strict React production build, locked Python dependency check, static analysis, the two focused golden scenarios, and plugin/MCP validation. Formal release packaging additionally requires an immutable Docker image in `WEF_DOCKER_GATE_IMAGE` and runs both verticals through the real Docker executor.

Current evidence and remaining gates are listed in [acceptance](docs/acceptance.md). Contributions are welcome under [CONTRIBUTING.md](CONTRIBUTING.md); security reports follow [SECURITY.md](SECURITY.md).

## License

Apache-2.0. The permissive license includes an explicit patent grant and permits individual, internal, and commercial use subject to its terms.
