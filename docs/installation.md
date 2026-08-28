# Installation and removal

## Supported preview environment

- Windows 11 x64
- Docker Desktop using Linux containers
- Python 3.11-3.13
- Node.js 22.x
- Git
- Codex CLI/Desktop with `codex` on `PATH`
- PowerShell 7 recommended

The installer is a readable PowerShell script. It does not require administrator privileges.

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

Use `-EnableStartup` only when you want the current-user service to start at sign-in. Use `-NoStart` to prepare dependencies and the plugin without starting the service.

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
.\scripts\Sync-Protocol.ps1 -ProtocolRoot D:\code\agent-run-protocol
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

## Environment variables

| Variable | Purpose |
|---|---|
| `WEF_NODE` | Exact Node 22 executable |
| `WEF_PYTHON` | Exact Python 3.11-3.13 executable |
| `WEF_DATA_DIR` | Override the local product data directory |
| `WEF_PORT` | Override the backend port; default `43121` |
| `WEF_PROTOCOL_SCHEMA_DIR` | Override the Agent Run Protocol schema directory |
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

The script refuses to recursively delete a drive root, user profile, `%LOCALAPPDATA%`, or a suspiciously short path. This deletion is not recoverable by the product.

## Offline behavior

After dependencies and the Codex plugin are installed, the product UI, database, simulator, task-pack export, and Docker verifier can operate without cloud sync. Codex itself may still require network access according to the user's Codex setup. The Docker executor always gives the verifier container `--network none`.
