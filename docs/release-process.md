# Release process

A source build is not a release. A `v*` tag produces a GitHub Release only after both golden verticals pass against real Docker.

## Fixed inputs

- Agent Run Protocol: tag `v0.1.0`.
- Codex CLI used by `doctor`: `0.150.0-alpha.8`.
- Docker gate image: `python:3.11.16-slim-bookworm@sha256:0bee7276f83efd4a1ee05bbbf4281d95ed28e079220a9457f25a93e3f1e3c31b`.

The image is the Docker Official Image manifest digest returned by Docker Hub for the named tag on 2026-08-28. The multi-platform manifest resolves to an architecture-specific image while preserving one reviewed reference.

## CI gates

1. Windows builds the React product, installs the locked Python environment, runs all local golden tests, and validates the plugin.
2. Ubuntu runs the same checks with Docker available.
3. The Docker gate creates a fresh synthetic repository and confirmed Issue-to-PR demonstration.
4. It generates one base Case plus two provenance-preserving variants for each vertical.
5. Wrong code fails and correct code passes.
6. Correct code without simulator state fails the Issue-to-PR Case; correct code plus linked PR and issue status passes.
7. Every prepared Run is cleaned up.

The release workflow repeats the Docker gate rather than trusting an earlier workflow, builds the Windows source archive with compiled web assets and pinned protocol schemas, emits a SHA-256 file, and attaches GitHub build provenance.

The release remains a technical preview until the separate fresh Windows installation, Codex execution, UI, uninstall, and no-residue acceptance is attached.
