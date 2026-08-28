# Changelog

All notable user-visible changes are documented here. The project follows Semantic Versioning once the first public release is tagged.

## [Unreleased]

- Clean-Windows acceptance, real Codex Docker evidence, and public release are still pending.
- Windows CI runs the complete non-Docker product check; isolated Linux CI runs both real Docker golden verticals with a fixed official-image digest.
- Tag releases repeat the Docker gates, attach a checksum, and publish GitHub provenance.

## [0.1.0] - 2026-08-28

### Added

- Blueprint, Case Factory, and Runs & Scores local product surfaces.
- Code and recorded Issue-to-PR verticals with a base Case and exactly two confirmed variants.
- Git worktree and SQLite snapshot resets with objective positive/negative generation gates.
- Docker verifier boundary and a release-only real Docker integration gate.
- Codex plugin with one bounded Skill and six local simulator MCP tools.
- Agent timeout/crash, environment/reset error, validator error, and task result separation.
- Agent Run Protocol Case and Score validation plus three-Case task-pack export.
- Windows build, start, stop, install, uninstall, and release packaging scripts.

### Security

- Loopback-only service, random local session token, HttpOnly Strict cookie, pre-storage redaction, immutable container references, and path-safe cleanup.
