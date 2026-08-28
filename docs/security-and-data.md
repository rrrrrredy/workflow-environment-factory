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
| Git worktree | Fresh Agent task state | Product data directory | Removed on explicit Run cleanup |
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
- only the fresh worktree mounted at `/workspace`.

The mounted workspace is writable because objective tests often produce files. The host Docker daemon remains a privileged dependency; a malicious image or daemon compromise is outside this application's security boundary. Review image provenance and verifier commands.

## Codex boundary

Codex runs with `workspace-write` inside a fresh worktree and `--approve-for-me`. In 0.1 it uses the user's active Codex installation and configuration. The factory's Skill instructs Codex not to read the solution, validator implementation, other Runs, or product data, and the plugin exposes no score mutation tool. These instructions do not turn the host OS into a hard sandbox. Use a dedicated Windows user or VM for hostile repositories.

The product records visible Codex JSONL events. It does not claim to read hidden reasoning.

## File-system cleanup

- Worktrees must resolve under the configured worktree root before removal.
- Simulator snapshots must resolve under the configured simulator root; only the exact database, its SQLite sidecars, and an empty per-Run directory are removed.
- The uninstaller validates the full data path and refuses broad recursive targets.
- A score remains stored when a Run record is updated; updates use SQLite conflict-update semantics rather than delete-and-reinsert.

## Reporting a vulnerability

Do not open a public issue for a suspected secret exposure, sandbox escape, arbitrary file deletion, score mutation, or authentication bypass. Follow [SECURITY.md](../SECURITY.md).
