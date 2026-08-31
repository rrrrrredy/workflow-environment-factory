# Installation and removal

## Supported preview environment

- Windows 11 x64, Linux x64, or macOS
- Docker Desktop using Linux containers on Windows/macOS, or Docker Engine on Linux
- Python 3.11-3.13
- Node.js 22.x
- Git
- Codex CLI/Desktop with `codex` on `PATH`
- PowerShell 7 recommended

Windows uses the readable PowerShell lifecycle. Linux and macOS use the readable shell/Node lifecycle. Neither path requires administrator privileges.

GitHub-hosted Ubuntu proves the full portable plugin/service lifecycle with a real Docker daemon, while the existing Docker golden job proves both task verticals. GitHub-hosted macOS proves build, local service, plugin registration, restart, uninstall, and final absence while explicitly skipping the unavailable hosted Docker daemon. This is not physical-Mac, Docker Desktop, or authenticated-Codex task evidence.

## Install from a release archive

1. Download `workflow-environment-factory-0.1.0-windows-x64.zip` and its `.sha256` file from the same GitHub Release.
2. Verify the archive before extracting it:

   ```powershell
   Get-FileHash .\workflow-environment-factory-0.1.0-windows-x64.zip -Algorithm SHA256
   ```

3. Extract the archive, inspect `scripts\Install.ps1`, then run:

   ```powershell
   Set-Location .\workflow-environment-factory-0.1.0
   .\scripts\Install.ps1 -Open
   ```

4. Restart Codex so the new Skill and MCP server are discovered.

On Linux or macOS, download the matching portable archive, verify its SHA-256, extract it, then run:

```bash
chmod +x scripts/*.sh
./scripts/Install.sh --open
```

The portable installer creates `.venv`, installs the constrained production Python dependencies, checks Codex, requires a reachable Docker daemon, registers the same Codex marketplace/plugin, and starts the loopback service. It does not create a systemd unit or macOS LaunchAgent; run `Start.sh` after signing in.

Use `-EnableStartup` only when you want the current-user service to start at sign-in. Use `-NoStart` to prepare dependencies and the plugin without starting the service.

`-Port` and `-DataDir` are forwarded to the first service start and the optional Startup shortcut. A custom data path must either not exist yet or already carry this product's ownership marker; existing unmarked directories are rejected even when empty. `-Repair` restores the previous plugin, marketplace, Startup shortcut, and data if a later installation step fails. When either value is customized, launch Codex with matching `WEF_PORT` and `WEF_DATA_DIR` values so the simulator MCP tools use the same local instance.

## Exact state changes

| State | Installer action | Removal |
|---|---|---|
| `.venv` | Creates a project-local Python environment and installs constrained dependencies | Delete the extracted source folder after uninstalling |
| `node_modules` | Runs `npm ci` from the committed lockfile | Delete the extracted source folder after uninstalling |
| `dist/web` | Builds the local React UI | Delete the extracted source folder after uninstalling |
| Codex marketplace | Registers this extracted checkout | `Uninstall.ps1` removes it |
| Codex plugin | Adds `workflow-environment-factory@workflow-environment-factory` | `Uninstall.ps1` removes it |
| Local product data | Defaults to `%LOCALAPPDATA%\WorkflowEnvironmentFactory` | Preserved by default; `-DeleteData` removes only the validated exact path |
| Startup shortcut | Added only with `-EnableStartup` | `Uninstall.ps1` removes it |

The installer does not install Docker, Python, Node, Git, or Codex. It stops before changing Codex plugin state when a prerequisite check fails.

## Portable development path

Point to exact runtimes when multiple versions are installed:

```powershell
$env:WEF_NODE = 'D:\tools\node-v22\node.exe'
$env:WEF_PYTHON = 'D:\tools\Python311\python.exe'
.\scripts\Sync-Protocol.ps1 -ProtocolRoot D:\code\runcase-interchange
.\scripts\Check.ps1 -InstallDependencies
.\scripts\Start.ps1 -Open
```

`Start.ps1` does not install the plugin. Code-only Cases can be inspected without it, but Issue-to-PR Codex Runs need the plugin's local simulator tools.

## Start and stop

```powershell
.\scripts\Start.ps1 -Open
.\scripts\Stop.ps1
```

The service is hidden in background mode and writes its PID plus logs under the product data directory. `Stop.ps1` resolves the PID, verifies that its executable is this checkout's virtual-environment Python, and verifies the expected module name before stopping it. It refuses to guess when the PID file is missing.

For troubleshooting, use foreground mode:

```powershell
.\scripts\Start.ps1 -Foreground
```

Linux/macOS use:

```bash
./scripts/Start.sh --open
./scripts/Stop.sh
```

The portable service record binds the PID to this checkout's virtual-environment Python and module command. Stop refuses to signal a process when either does not match.

## Environment variables

| Variable | Purpose |
|---|---|
| `WEF_NODE` | Exact Node 22 executable |
| `WEF_PYTHON` | Exact Python 3.11-3.13 executable |
| `WEF_DATA_DIR` | Override the local product data directory |
| `WEF_PORT` | Override the backend port; default `43121` |
| `WEF_PROTOCOL_SCHEMA_DIR` | Override the RunCase Interchange schema directory |
| `CODEX_EXECUTABLE` | Override the Codex command used for Runs |
| `DOCKER_EXECUTABLE` | Override the Docker command |

The host is deliberately not configurable beyond `127.0.0.1`.

## Uninstall

```powershell
.\scripts\Uninstall.ps1
```

This removes the plugin, marketplace, optional startup shortcut, and running service. It preserves the local data directory and source checkout.

To delete local product data permanently:

```powershell
.\scripts\Uninstall.ps1 -DeleteData
```

Verify the final machine state without changing it:

```powershell
.\scripts\Inspect-Installation.ps1 -RequireAbsent
.\scripts\Inspect-Installation.ps1 -RequireAbsent -RequireNoData
```

The first command permits the data preserved by the default uninstall. The second is the strict zero-data check after an explicit `-DeleteData` uninstall. Both fail when Codex plugin/marketplace state cannot be inspected instead of claiming success from missing evidence.

The script deletes only a real directory carrying a valid Workflow Environment Factory ownership marker. It also rejects files, reparse points, a drive root, user profile, Documents, `%LOCALAPPDATA%`, or another suspiciously broad path. This deletion is not recoverable by the product.

Linux/macOS equivalents use long options:

```bash
./scripts/Uninstall.sh
./scripts/Uninstall.sh --delete-data
./scripts/Inspect-Installation.sh --require-absent --require-no-data
```

The portable uninstaller preserves product data by default and deletes only an exact real directory carrying the Factory marker. It never removes the source or extracted release directory.

Release CI executes `scripts\Acceptance-InstallUninstall.ps1` in an isolated Codex home. It occupies the service port to prove a failed first install removes every newly created product state, then repeats the fault during `-Repair` and requires the prior plugin, marketplace, Startup shortcut, and data to survive byte-for-byte where applicable. It then records real registration, loopback service, preservation, reinstall, ownership-marked deletion, and machine-audited final-removal evidence. Hosted Windows CI records an explicit Docker command stub only for the prerequisite path; real Linux-container execution of both product verticals is a separate Ubuntu Docker golden gate, and neither result proves same-host Windows 11 Docker Desktop acceptance.

`scripts/Acceptance-Portable.sh` records the equivalent plugin/service/restart/removal lifecycle on hosted Ubuntu and macOS. Linux additionally requires the real hosted Docker daemon. macOS records the Docker omission and makes no Case-execution claim.

## Offline behavior

After dependencies and the Codex plugin are installed, the product UI, database, simulator, task-pack export, and Docker verifier can operate without cloud sync. Codex itself may still require network access according to the user's Codex setup. The Docker executor always gives the verifier container `--network none`.
