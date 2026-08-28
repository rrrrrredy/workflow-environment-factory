# Release process

A source build is not a release. A `v*` tag produces a GitHub Release only after deterministic Docker environment gates, locally authenticated real Codex gates, and clean archive installation gates all pass.

## Fixed inputs

- RunCase Interchange: tag `v0.1.0`.
- Node.js: 22.23.2 in CI and release jobs.
- Python: 3.11.16 in CI, release jobs, and the Docker gate image.
- Codex CLI used by `doctor`: `0.150.0-alpha.8`.
- Docker gate image: `python:3.11.16-slim-bookworm@sha256:0bee7276f83efd4a1ee05bbbf4281d95ed28e079220a9457f25a93e3f1e3c31b`.

The image is the Docker Official Image manifest digest returned by Docker Hub for the named tag on 2026-08-28. The multi-platform manifest resolves to an architecture-specific image while preserving one reviewed reference.

## CI gates

1. Windows builds the React product, installs the locked Python environment, runs all local golden tests, and validates the plugin.
2. Windows also runs one asserted browser golden scenario covering recording, three Cases, task-pack export, timeout/not-scored separation, protocol import, and mobile overflow.
3. Ubuntu runs the same checks with Docker available.
4. The Docker gate creates a fresh synthetic repository and confirmed Issue-to-PR demonstration; it is explicitly an environment/verifier gate, not an Agent execution claim.
5. It generates one base Case plus two provenance-preserving variants for each vertical.
6. Wrong code fails and correct code passes.
7. Correct code without simulator state fails the Issue-to-PR Case; correct code plus linked PR and issue status passes.
8. Every prepared Run is cleaned up.

## Authenticated product evidence

Hosted CI has no user's Codex authentication, so it cannot truthfully manufacture real Agent evidence. From a clean reviewed commit on Windows 11 with Docker Desktop and authenticated Codex, run:

```powershell
$env:WEF_DOCKER_GATE_IMAGE = 'python:3.11.16-slim-bookworm@sha256:0bee7276f83efd4a1ee05bbbf4281d95ed28e079220a9457f25a93e3f1e3c31b'
.\scripts\Prepare-ReleaseEvidence.ps1 -Version 0.1.0 -ProtocolRoot C:\path\to\runcase-interchange
```

The gate must run from a normal Windows session. Before either model call, it proves that the exact Run directory can sustain an offline App Server `workspaceWrite` sandbox; failure is infrastructure-inconclusive and cannot be bypassed with unrestricted execution. Each Codex Run ignores ambient user config and explicitly loads only the Factory MCP server. The gate then produces one real code Score and one real Issue-to-PR Score, proves the required MCP actions, verifies the Agent cannot read the known-correct object or factory-only evidence, and removes its temporary product installation. The sanitized file includes no prompts, repository content, credential, or local path. Review it and commit only `release-evidence/workflow-product-gate-0.1.0.json`.

`Verify-ReleaseEvidence.ps1` requires the tested commit to be an ancestor of the release tag and permits only that evidence file to differ. `Package-Release.ps1` refuses to package without this proof, embeds it in the archive, records its SHA-256 in the release manifest, and publishes it as a separately attested asset.

The release workflow verifies the committed real Codex evidence, repeats the Docker and browser gates rather than trusting an earlier workflow, builds the Windows source archive with compiled web assets, pinned protocol schemas, and an embedded `release-source.json` for no-`.git` acceptance, emits a SHA-256 file plus a commit/protocol/Docker/evidence-bound release manifest, and attaches GitHub build provenance.

A separate fresh Windows job runs the real installer, loopback service, Codex plugin/marketplace registration, Startup removal, data preservation, reinstall, and explicit deletion. Its sanitized `factory-installation-evidence.json` is published with the archive. The Ubuntu Docker gate and this Windows lifecycle gate are complementary; neither is described as a single-host Windows 11 Docker Desktop acceptance.

The workflow publishes a GitHub prerelease using the version-matched notes under `docs/releases/`. A missing notes file blocks publication; an automatically generated commit summary is not accepted as the product release page.

The release remains a technical preview until the separate fresh Windows 11 installation with Docker Desktop Linux containers, Codex execution, UI, uninstall, and no-residue acceptance is attached.
