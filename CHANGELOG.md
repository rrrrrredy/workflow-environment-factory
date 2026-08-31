# Changelog

All notable user-visible changes are documented here. The project follows Semantic Versioning once the first public release is tagged.

## [Unreleased]

- A Score now requires retained evidence that the Codex process started, rejects a merely prepared workspace, and has one deterministic immutable head per Run even when an older database contains duplicate historical rows.
- Docker verification mounts the Agent workspace read-only; every verifier also receives before/after workspace fingerprints, and any mutation produces `validator_error` plus `not_scored` instead of a task result.
- The installer refuses a foreign same-name Startup shortcut; inspection reports the collision, and uninstall removes only a shortcut carrying this product's ownership marker.
- RunCase Interchange is pinned to v0.1.1 by exact commit and schema hashes, closing portable-path traversal; protocol-import errors now identify the schema before the detailed validation message.
- Release documentation now distinguishes exact Python version constraints from an artifact-hash lock, and the nested synthetic UI probe allows the documented slow-start window.
- Windows archive lifecycle CI now uses and records a narrow Docker command stub while the separate Ubuntu job retains the real Docker task gates; the evidence no longer implies same-host Docker Desktop acceptance.
- The 0.1.0 tag path now publishes only a Windows technical preview: its attested manifest records that authenticated Codex and single-host Docker Desktop gates were not run, while those gates remain required before any stable label; macOS is explicitly unsupported.
- Tag publishing now fails immediately while the repository is private, matching GitHub's provenance-attestation boundary for individual accounts and the documented public-before-tag release order.
- Immutable verifier-image inspection and pulling now happen before the task timer starts; acquisition failures are reported as environment errors instead of task failures or task timeouts.
- Clean-Windows installation acceptance now pins and restores the loopback host variable across nested install, repair, and uninstall checks.
- Linux Docker verifiers now run as the host uid/gid so validation cannot leave root-owned files that make resets or cleanup fail.
- Windows CI and release installation gates now use an exact Python build that is available on the Windows 2025 runner.
- The environment example now uses the public RunCase Interchange repository name instead of the retired protocol working name.
- GitHub tag releases now require curated, version-matched adoption notes and are labeled prereleases so the public release surface preserves the Windows/Docker/Codex evidence boundary.
- Installation is now transactional across the product-created data root, plugin, marketplace, Startup shortcut, service startup, and failed `-Repair`; the clean-Windows gate injects real port conflicts and requires restoration plus a machine-readable zero-residue audit.
- Every entry point now creates only a previously nonexistent data directory or reuses one with a valid product ownership marker; it rejects existing unmarked directories, wrong-product markers, reparse points, and protected roots.
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
