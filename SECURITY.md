# Security policy

## Supported versions

| Version | Security fixes |
|---|---|
| 0.1.x preview | Yes |
| Unreleased source snapshots | Best effort |

## Report privately

Do not open a public issue for suspected authentication bypass, token or secret exposure, arbitrary file access/deletion, Docker escape, unsafe worktree cleanup, protocol validation bypass, hidden-solution disclosure, or score mutation.

Use GitHub's private vulnerability reporting at:

`https://github.com/rrrrrredy/workflow-environment-factory/security/advisories/new`

Include the affected version/commit, Windows and Docker versions, reproduction steps using non-sensitive data, impact, and any proposed mitigation. Do not include real secrets or private repository contents.

The maintainer will acknowledge a complete report as soon as practical, reproduce it privately, coordinate a fix and disclosure window, and credit the reporter when requested and appropriate.

## Security boundary

The preview is a single-user local application. Loopback authentication, redaction, Docker limits, and path validation reduce risk but do not make hostile repositories, images, Codex configuration, or the host Docker daemon trusted. Read [security and local data](docs/security-and-data.md) before deployment.
