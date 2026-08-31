# Release process

A source build is not a release. The 0.2.0 tag produces only a GitHub prerelease after deterministic Docker environment gates and extracted Windows/Linux/macOS archive lifecycles pass. Its attested manifests record that locally authenticated Codex, physical-Mac, macOS Docker Desktop, and single-host Windows 11 Docker Desktop gates were not run; those omissions block any stable label.

## Fixed inputs

- RunCase Interchange: commit `462fa2fa7cdaa8f58cd4c1dcc9cf778e1d2d0073` from tag `v0.1.2`, with per-schema SHA-256 verification.
- Node.js: 22.23.2 in CI and release jobs.
- Python: 3.13.13 for Windows product/archive jobs; 3.11.16 for Ubuntu build jobs and the Docker gate image.
- Codex CLI used by `doctor` and the read-isolation gates: `0.151.0`.
- Docker gate image: `python:3.11.16-slim-bookworm@sha256:0bee7276f83efd4a1ee05bbbf4281d95ed28e079220a9457f25a93e3f1e3c31b`.

The image is the Docker Official Image manifest digest returned by Docker Hub for the named tag on 2026-08-28. The multi-platform manifest resolves to an architecture-specific image while preserving one reviewed reference.

## CI gates

1. Windows builds the React product, installs exact Python version constraints, runs all local golden tests, validates the plugin, and uses a real no-model App Server shell to prove that the workspace is writable while the product database and source solution commit are unreadable. These constraints do not hash-lock wheel or sdist artifacts.
2. Windows also runs one asserted browser golden scenario covering recording, three Cases, task-pack export, timeout/not-scored separation, protocol import, and mobile overflow.
3. Ubuntu runs the same checks with Docker available; hosted Linux and Apple Silicon macOS repeat the same fail-closed read-isolation proof.
4. The Docker gate creates a fresh synthetic repository and confirmed Issue-to-PR demonstration; it is explicitly an environment/verifier gate, not an Agent execution claim.
5. It generates one base Case plus two provenance-preserving variants for each vertical.
6. Wrong code fails and correct code passes.
7. Correct code without simulator state fails the Issue-to-PR Case; correct code plus linked PR and issue status passes.
8. Every prepared Run is cleaned up.

## Optional authenticated product evidence

Hosted CI has no user's Codex authentication, so it cannot truthfully manufacture real Agent evidence. From a clean reviewed commit on Windows 11 with Docker Desktop and authenticated Codex, run:

```powershell
$env:WEF_DOCKER_GATE_IMAGE = 'python:3.11.16-slim-bookworm@sha256:0bee7276f83efd4a1ee05bbbf4281d95ed28e079220a9457f25a93e3f1e3c31b'
.\scripts\Prepare-ReleaseEvidence.ps1 -Version 0.2.0 -ProtocolRoot C:\path\to\runcase-interchange
```

The gate must run from a normal Windows session. Before either model call, it selects the same restricted permission profile used by the Run and proves three properties with an offline App Server command: the generated workspace is writable, the product SQLite database is unreadable, and `git show` cannot open the source repository's known-correct commit. A platform that cannot enforce restricted reads fails closed before the model starts. Each Codex Run ignores ambient user config and explicitly loads only the Factory MCP server with a token derived for that Run; that token cannot access Blueprints, product data, or another Run. The gate then produces one real code Score and one real Issue-to-PR Score, proves the required MCP actions, and removes its temporary product installation. The sanitized file includes no prompts, repository content, credential, or local path. Review it and commit only `release-evidence/workflow-product-gate-0.2.0.json`.

`Verify-ReleaseEvidence.ps1` requires the tested commit to be an ancestor of the reviewed code and permits only that evidence file to differ. The 0.2.0 technical preview packages without this proof and records `not_run` in the attested manifests. Authenticated evidence remains required before any stable release.

The release workflow repeats the Docker and browser gates rather than trusting an earlier workflow, builds Windows and portable archives with compiled web assets, pinned protocol schemas, and an embedded `release-source.json` for no-`.git` acceptance, emits SHA-256 files plus commit/protocol/Docker-bound technical-preview manifests, and attaches GitHub build provenance.

The reviewed repository must be made public before the release tag is pushed. GitHub does not issue build-provenance attestations for a private repository owned by an individual account. Make the repository public only after the final reviews pass, immediately enable secret scanning, push protection, Dependabot security updates, and strict `main` checks, and then push the tag. The release workflow fails before checkout when the repository is still private.

A separate hosted Windows job runs the real installer, loopback service, Codex plugin/marketplace registration, Startup removal, data preservation, reinstall, and explicit deletion. Because hosted Windows runners do not provide Docker Desktop, that job uses an explicitly recorded Docker command stub only to exercise the installer's prerequisite path. Extracted portable archive jobs run on Ubuntu with real Docker and on Apple Silicon macOS with the Docker check explicitly skipped. These records are complementary and do not establish physical-machine acceptance.

The workflow publishes a GitHub prerelease using the version-matched notes under `docs/releases/`. A missing notes file blocks publication; an automatically generated commit summary is not accepted as the product release page.

The release remains a technical preview because authenticated Codex execution and separate fresh Windows 11 installation with Docker Desktop Linux containers were not performed. CI evidence must not be promoted into either claim.
