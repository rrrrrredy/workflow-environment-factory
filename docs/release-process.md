# Release process

A source build is not a release. A `v*` tag produces a GitHub Release only after both golden verticals pass against real Docker.

## Fixed inputs

- Agent Run Protocol: tag `v0.1.0`.
- Codex CLI used by `doctor`: `0.150.0-alpha.8`.
- Docker gate image: `python:3.11.16-slim-bookworm@sha256:0bee7276f83efd4a1ee05bbbf4281d95ed28e079220a9457f25a93e3f1e3c31b`.

The image is the Docker Official Image manifest digest returned by Docker Hub for the named tag on 2026-08-28. The multi-platform manifest resolves to an architecture-specific image while preserving one reviewed reference.

## CI gates

1. Windows builds the React product, installs the locked Python environment, runs all local golden tests, and validates the plugin.
2. Windows also runs one asserted browser golden scenario covering recording, three Cases, task-pack export, timeout/not-scored separation, protocol import, and mobile overflow.
3. Ubuntu runs the same checks with Docker available.
4. The Docker gate creates a fresh synthetic repository and confirmed Issue-to-PR demonstration.
5. It generates one base Case plus two provenance-preserving variants for each vertical.
6. Wrong code fails and correct code passes.
7. Correct code without simulator state fails the Issue-to-PR Case; correct code plus linked PR and issue status passes.
8. Every prepared Run is cleaned up.

The release workflow repeats the Docker and browser gates rather than trusting an earlier workflow, builds the Windows source archive with compiled web assets and pinned protocol schemas, emits a SHA-256 file plus a commit/protocol/Docker-bound release manifest, and attaches GitHub build provenance.

A separate fresh Windows job runs the real installer, loopback service, Codex plugin/marketplace registration, Startup removal, data preservation, reinstall, and explicit deletion. Its sanitized `factory-installation-evidence.json` is published with the archive. The Ubuntu Docker gate and this Windows lifecycle gate are complementary; neither is described as a single-host Windows 11 Docker Desktop acceptance.

The release remains a technical preview until the separate fresh Windows installation, Codex execution, UI, uninstall, and no-residue acceptance is attached.
