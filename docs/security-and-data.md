# Security and local data

Workflow Environment Factory handles repository code, local paths, Agent events, and workflow demonstrations. The 0.1 preview assumes a single trusted Windows user and trusted repositories. It does not provide a multi-user security boundary.

## Data inventory

| Data | Why it exists | Default location | Export |
|---|---|---|---|
| Blueprint | Confirmed repository revisions, variable, paths, environment, and completion standard | Local SQLite | Product JSON in a task pack |
| Case | Protocol document, provenance, reset and positive/negative gate evidence | Local SQLite | `workflow.case.v1` or three-Case task pack |
| Run | Workspace reference, Codex events, status, and visible error | Local SQLite | Local UI; external `agent.run.v1` files can be retained separately in the protocol library |
| Score | Objective validations, execution status, time, and single-run caveat | Local SQLite | `workflow.score.v1` through the UI or local API |
| Verifier output | Redacted stdout, stderr, and exit code | SHA-256 local content store | By content reference when explicitly requested |
| Demonstration | Four structured local simulator actions and explicit confirmation | Local SQLite | Included by reference in Case provenance |
| Isolated Git snapshot | Fresh Agent files plus a separate shallow baseline object database | Product data directory | Both removed on explicit Run cleanup |
| Simulator database | Fresh Issue/PR state for one Run | Product data directory | Removed on explicit Run cleanup |

No cloud database, analytics SDK, telemetry endpoint, or team service is included.

## Local HTTP boundary

- `Settings.load` rejects any host except `127.0.0.1`.
- Every `/api/` route requires a random token using constant-time comparison.
- The startup URL exchanges that token for an HttpOnly, SameSite=Strict cookie and redirects to `/`.
- Access logging is disabled so the session URL is not written to the service access log.
- Treat the token as a local secret. Anyone who can read the product data directory as the same OS user can act as that user in the local product.

## Redaction

Codex events, runner errors, verifier output, and background failures are redacted before durable storage. Current rules cover:

- field names matching authorization, cookie, password, secret, token, API key, and private key;
- bearer tokens;
- OpenAI-style API keys;
- GitHub tokens;
- PEM private keys;
- oversized strings, which are truncated with an explicit marker.

Redaction is a defense in depth measure, not a guarantee that arbitrary secrets embedded in source code or novel formats will be recognized. Exclude sensitive repositories and paths that should never be processed.

## Docker verifier boundary

The verifier uses an immutable `image@sha256` reference and starts Docker with:

- `--network none`;
- `--cpus 2`;
- `--memory 3g`;
- `--pids-limit 128`;
- a read-only container filesystem;
- a `noexec,nosuid` temporary filesystem;
- only the fresh Agent working directory mounted at `/workspace`; its external Git object database is not mounted.

The mounted workspace is writable because objective tests often produce files. The host Docker daemon remains a privileged dependency; a malicious image or daemon compromise is outside this application's security boundary. Review image provenance and verifier commands.

## Codex boundary

Before Codex receives the prompt, a short-lived App Server process runs a no-model write/read/delete preflight with network disabled and the exact fresh Run directory as its only writable root. A failed preflight becomes `environment_error`; the product does not fall back to `danger-full-access` or `externalSandbox`.

Codex then runs with `workspace-write`, `--approve-for-me`, an ephemeral thread, explicit network denial, and no extra writable root. It ignores ambient user config and disables unrelated plugins, Hooks, apps, Web search, memories, computer use, image generation, and multi-Agent tools; the Factory MCP script is registered explicitly for that Run. Repository AGENTS rules remain visible. The working directory contains no `.git` marker, remote, alternate object store, or known-correct descendant object. A separate shallow Git directory contains the baseline. Model-generated commands inherit only Codex's core environment plus explicit isolated Git variables, with default secret-name filtering enabled and profile-based reintroduction disabled. Agent-specific MCP routes omit the solution commit, patch digest, provenance, full gate evidence, and score; user-facing workbench/export routes retain them.

Repository files present at the baseline, including ordinary tests or verifier scripts, remain visible. This product does not claim hidden-test security. In 0.1 Codex also uses the user's active installation and configuration. The Skill and API minimization reduce accidental leakage, but they do not turn the same OS user into a hard security boundary. Use a dedicated Windows user or VM for hostile repositories.

The product records visible Codex JSONL events. It does not claim to read hidden reasoning.

## File-system cleanup

- Internal gate worktrees and isolated Run workspace/Git-state directories must resolve under the configured product root before removal.
- Simulator snapshots must resolve under the configured simulator root; only the exact database, its SQLite sidecars, and an empty per-Run directory are removed.
- The uninstaller validates the full data path and refuses broad recursive targets.
- A score remains stored when a Run record is updated; updates use SQLite conflict-update semantics rather than delete-and-reinsert.

## Reporting a vulnerability

Do not open a public issue for a suspected secret exposure, sandbox escape, arbitrary file deletion, score mutation, or authentication bypass. Follow [SECURITY.md](../SECURITY.md).
