# Changelog

All notable user-visible changes are documented here. The project follows Semantic Versioning once the first public release is tagged.

## [Unreleased]

- Real Runs now fail closed before model use when the exact App Server workspace sandbox cannot be created; Codex execution explicitly disables network, extra writable roots, ambient user config, unrelated tools and plugins, uses an ephemeral thread, injects only the Factory MCP server, filters the shell environment, and classifies setup failures as environment errors.
- Agent Runs now use a shallow, standalone Git object database outside the writable workspace; known-correct objects, remotes, alternates, and `.git` markers are absent, while tracked and untracked changes are both scored.
- MCP Run/Case reads now use Agent-specific views that omit known-correct refs, patch digests, provenance, full gate evidence, and scores while preserving complete user-facing audit/export data.
- Release packaging now requires sanitized, commit-bound evidence from one real Codex code Run and one real Codex Issue-to-PR Run, including required simulator actions and proof that the temporary installation was fully removed.
- The repeatable clean-Windows installation lifecycle is implemented; hosted execution, single-host Windows 11 Docker Desktop acceptance, real Codex Docker evidence, and public release are still pending.
- Windows CI runs the complete non-Docker product check; isolated Linux CI runs both real Docker golden verticals with a fixed official-image digest.
- Tag releases repeat the Docker gates, attach a checksum plus a commit/protocol/Docker-bound manifest, require a fresh Windows installation job, and publish GitHub provenance.
- The single browser golden scenario now has blocking assertions and runs in CI with screenshots kept as workflow evidence.
- Installer and uninstaller now distinguish an installed plugin from an available marketplace entry, remove Codex 0.150 marketplace rows correctly, and carry custom port/data settings into service and Startup launches.

## [0.1.0] - 2026-08-28

### Added

- Blueprint, Case Factory, and Runs & Scores local product surfaces.
- Code and recorded Issue-to-PR verticals with a base Case and exactly two confirmed variants.
- Isolated Git and SQLite Run resets with objective positive/negative generation gates.
- Docker verifier boundary and a release-only real Docker integration gate.
- Codex plugin with one bounded Skill and six local simulator MCP tools.
- Agent timeout/crash, environment/reset error, validator error, and task result separation.
- RunCase Interchange Case and Score validation plus three-Case task-pack export.
- Windows build, start, stop, install, uninstall, and release packaging scripts.

### Security

- Loopback-only service, random local session token, HttpOnly Strict cookie, pre-storage redaction, immutable container references, and path-safe cleanup.
