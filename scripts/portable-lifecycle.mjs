#!/usr/bin/env node

import {
  closeSync,
  existsSync,
  lstatSync,
  mkdirSync,
  openSync,
  readFileSync,
  realpathSync,
  rmSync,
  writeFileSync
} from "node:fs";
import { homedir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawn, spawnSync } from "node:child_process";

const scriptPath = fileURLToPath(import.meta.url);
const repositoryRoot = resolve(dirname(scriptPath), "..");
const product = "workflow-environment-factory";
const displayName = "Workflow Environment Factory";
const markerName = ".workflow-environment-factory-data.json";
const serviceName = "portable-service.json";
const pluginSelector = "workflow-environment-factory@workflow-environment-factory";
const marketplaceName = "workflow-environment-factory";
const defaultPort = 43121;

function fail(message) {
  throw new Error(message);
}

function parseArguments(argv) {
  const command = argv[0];
  if (!command) fail("Expected install, start, stop, inspect, or uninstall.");
  const options = {
    command,
    dataDir: process.env.WEF_DATA_DIR || join(homedir(), ".workflow-environment-factory"),
    port: defaultPort,
    marketplaceSource: repositoryRoot,
    noStart: false,
    open: false,
    deleteData: false,
    requireAbsent: false,
    requireNoData: false,
    skipDependencies: false,
    skipDockerCheck: false
  };
  const booleanOptions = new Map([
    ["--no-start", "noStart"],
    ["--open", "open"],
    ["--delete-data", "deleteData"],
    ["--require-absent", "requireAbsent"],
    ["--require-no-data", "requireNoData"],
    ["--skip-dependencies", "skipDependencies"],
    ["--skip-docker-check", "skipDockerCheck"]
  ]);
  const valueOptions = new Map([
    ["--data-dir", "dataDir"],
    ["--port", "port"],
    ["--marketplace-source", "marketplaceSource"]
  ]);
  for (let index = 1; index < argv.length; index += 1) {
    const argument = argv[index];
    if (booleanOptions.has(argument)) {
      options[booleanOptions.get(argument)] = true;
      continue;
    }
    if (valueOptions.has(argument)) {
      index += 1;
      if (index >= argv.length) fail(`${argument} requires a value.`);
      options[valueOptions.get(argument)] = argv[index];
      continue;
    }
    fail(`Unknown option: ${argument}`);
  }
  options.port = Number.parseInt(String(options.port), 10);
  if (!Number.isInteger(options.port) || options.port < 1024 || options.port > 65535) {
    fail("--port must be an integer between 1024 and 65535.");
  }
  options.dataDir = resolve(String(options.dataDir));
  options.marketplaceSource = resolve(String(options.marketplaceSource));
  return options;
}

function requirePortablePlatform() {
  if (!new Set(["darwin", "linux"]).has(process.platform)) {
    fail("This entry point is for Linux and macOS. Use the PowerShell lifecycle on Windows.");
  }
}

function requireNode22() {
  if (Number.parseInt(process.versions.node.split(".")[0], 10) !== 22) {
    fail(`${displayName} requires Node.js 22.x; found ${process.versions.node}.`);
  }
}

function commandPath(name) {
  const result = spawnSync("sh", ["-c", `command -v ${name}`], { encoding: "utf8" });
  return result.status === 0 ? result.stdout.trim() : "";
}

function systemPython() {
  const candidates = process.env.WEF_PYTHON ? [process.env.WEF_PYTHON] : [commandPath("python3"), commandPath("python")];
  for (const candidate of candidates) {
    if (!candidate || !existsSync(candidate)) continue;
    const version = spawnSync(candidate, ["-c", "import sys; print('.'.join(map(str, sys.version_info[:3])))"], {
      encoding: "utf8"
    });
    if (version.status !== 0) continue;
    const parts = version.stdout.trim().split(".").map((part) => Number.parseInt(part, 10));
    if (parts[0] === 3 && parts[1] >= 11 && parts[1] <= 13) return candidate;
  }
  fail("Workflow Environment Factory requires Python 3.11, 3.12, or 3.13.");
}

function venvPython() {
  return resolve(repositoryRoot, ".venv", "bin", "python");
}

function protocolDirectory() {
  return resolve(repositoryRoot, ".runtime-deps", "runcase-interchange", "0.1.2", "schemas");
}

function assertPackagedRuntime() {
  if (!existsSync(resolve(repositoryRoot, "dist", "web", "index.html"))) {
    fail("Production UI is missing. Use a release archive or run npm ci && npm run build:web first.");
  }
  for (const schema of ["agent.run.v1.schema.json", "workflow.case.v1.schema.json", "workflow.score.v1.schema.json"]) {
    if (!existsSync(resolve(protocolDirectory(), schema))) {
      fail("RunCase Interchange v0.1.2 schemas are missing. Use a release archive or run the portable schema sync first.");
    }
  }
}

function installPythonRuntime(options) {
  const environmentPath = resolve(repositoryRoot, ".venv");
  const python = venvPython();
  if (options.skipDependencies) {
    if (!existsSync(python)) fail("Portable Python environment is missing; remove --skip-dependencies.");
    return python;
  }
  if (!existsSync(python)) {
    if (existsSync(environmentPath)) {
      fail(`The existing .venv is not a compatible Linux/macOS environment: ${environmentPath}`);
    }
    run(systemPython(), ["-m", "venv", environmentPath]);
  }
  run(python, [
    "-m",
    "pip",
    "install",
    "--disable-pip-version-check",
    "--constraint",
    resolve(repositoryRoot, "requirements.lock"),
    "--editable",
    repositoryRoot
  ]);
  return python;
}

function dockerDaemonAvailable() {
  const docker = commandPath("docker");
  if (!docker) return false;
  const probe = spawnSync(docker, ["info", "--format", "{{json .ServerVersion}}"], { encoding: "utf8" });
  return probe.status === 0;
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: options.cwd ?? repositoryRoot,
    env: options.env ?? process.env,
    encoding: "utf8",
    stdio: options.capture ? "pipe" : "inherit"
  });
  if (result.error) throw result.error;
  if (result.status !== 0) {
    const detail = options.capture ? `\n${result.stdout ?? ""}${result.stderr ?? ""}`.trimEnd() : "";
    fail(`${basename(command)} ${args.join(" ")} exited with ${result.status}.${detail}`);
  }
  return options.capture ? `${result.stdout ?? ""}${result.stderr ?? ""}` : "";
}

function assertSafeDataPath(requested) {
  const dataDir = resolve(requested);
  const home = resolve(homedir());
  if (dataDir === "/" || dataDir === home || dataDir.length < 8) {
    fail(`Refusing to use an unsafe ${displayName} data path: ${dataDir}`);
  }
  return dataDir;
}

function markerPath(dataDir) {
  return join(dataDir, markerName);
}

function assertDataRoot(requested) {
  const dataDir = assertSafeDataPath(requested);
  if (!existsSync(dataDir)) fail(`${displayName} data directory does not exist: ${dataDir}`);
  const root = lstatSync(dataDir);
  if (!root.isDirectory() || root.isSymbolicLink()) fail(`${displayName} data root must be a real directory: ${dataDir}`);
  const ownedMarker = markerPath(dataDir);
  if (!existsSync(ownedMarker) || lstatSync(ownedMarker).isSymbolicLink()) {
    fail(`Refusing to use an unmarked ${displayName} data directory: ${dataDir}`);
  }
  let marker;
  try {
    marker = JSON.parse(readFileSync(ownedMarker, "utf8"));
  } catch {
    fail(`${displayName} data marker is invalid: ${ownedMarker}`);
  }
  if (marker?.schema_version !== "product.data-root.v1" || marker?.product !== product) {
    fail(`${displayName} data marker names another product: ${ownedMarker}`);
  }
  return dataDir;
}

function initializeDataRoot(requested) {
  const dataDir = assertSafeDataPath(requested);
  let created = false;
  if (existsSync(dataDir)) {
    assertDataRoot(dataDir);
    return { dataDir, created };
  }
  mkdirSync(dataDir, { recursive: true, mode: 0o700 });
  created = true;
  writeFileSync(
    markerPath(dataDir),
    `${JSON.stringify({ schema_version: "product.data-root.v1", product, created_at: new Date().toISOString() }, null, 2)}\n`,
    { encoding: "utf8", flag: "wx", mode: 0o600 }
  );
  assertDataRoot(dataDir);
  return { dataDir, created };
}

function removeOwnedDataRoot(requested) {
  const dataDir = assertDataRoot(requested);
  rmSync(dataDir, { recursive: true, force: false });
}

function servicePath(dataDir) {
  return join(dataDir, serviceName);
}

function readService(dataDir) {
  const path = servicePath(dataDir);
  if (!existsSync(path)) return null;
  if (lstatSync(path).isSymbolicLink()) fail(`Portable service record cannot be a symbolic link: ${path}`);
  let record;
  try {
    record = JSON.parse(readFileSync(path, "utf8"));
  } catch {
    fail(`Portable service record is invalid: ${path}`);
  }
  if (
    record?.schema_version !== "product.portable-service.v1" ||
    record?.product !== product ||
    resolve(record?.repository_root ?? "") !== repositoryRoot ||
    resolve(record?.server_path ?? "") !== venvPython() ||
    record?.command_marker !== "workflow_environment_factory.cli" ||
    !Number.isInteger(record?.pid) ||
    record.pid < 1
  ) {
    fail(`Portable service record is not owned by this checkout: ${path}`);
  }
  return record;
}

function processAlive(pid) {
  try {
    process.kill(pid, 0);
    return true;
  } catch (error) {
    return error?.code === "EPERM";
  }
}

function processCommand(pid) {
  const result = spawnSync("ps", ["-p", String(pid), "-o", "command="], { encoding: "utf8" });
  return result.status === 0 ? result.stdout.trim() : "";
}

function assertOwnedProcess(record) {
  const command = processCommand(record.pid);
  const server = resolve(record.server_path);
  const realServer = realpathSync(server);
  if (!commandOwnsServer(command, server, realServer, record.command_marker)) {
    fail(`Refusing to signal PID ${record.pid}; its command does not match the owned Factory server.`);
  }
}

function commandOwnsServer(command, server, realServer, commandMarker) {
  return Boolean(
    command &&
    (command.includes(server) || command.includes(realServer)) &&
    command.includes(`-m ${commandMarker}`)
  );
}

async function health(port) {
  try {
    const response = await fetch(`http://127.0.0.1:${port}/health`, { signal: AbortSignal.timeout(2_000) });
    return response.ok ? await response.json() : null;
  } catch {
    return null;
  }
}

function sessionUrl(dataDir, port) {
  const tokenPath = join(dataDir, "session-token");
  if (!existsSync(tokenPath)) return null;
  const token = readFileSync(tokenPath, "utf8").trim();
  return token.length >= 32 ? `http://127.0.0.1:${port}/session/${token}` : null;
}

async function waitFor(predicate, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  while (Date.now() < deadline) {
    if (await predicate()) return true;
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 250));
  }
  return false;
}

function openUrl(url) {
  const opener = process.platform === "darwin" ? "open" : "xdg-open";
  const child = spawn(opener, [url], { detached: true, stdio: "ignore" });
  child.unref();
}

async function startService(options) {
  requireNode22();
  assertPackagedRuntime();
  const server = venvPython();
  if (!existsSync(server)) fail("Portable Python environment is missing. Run Install.sh first.");
  const { dataDir } = initializeDataRoot(options.dataDir);
  const currentHealth = await health(options.port);
  if (currentHealth) {
    if (currentHealth.product !== product) fail(`Port ${options.port} is already serving another application.`);
    const url = sessionUrl(dataDir, options.port);
    process.stdout.write(`${displayName} is already running.\n${url ?? ""}\n`);
    if (options.open && url) openUrl(url);
    return false;
  }
  const existingRecord = readService(dataDir);
  if (existingRecord && processAlive(existingRecord.pid)) {
    assertOwnedProcess(existingRecord);
    fail(`Owned process ${existingRecord.pid} is running but did not answer its recorded health endpoint.`);
  }
  if (existingRecord) rmSync(servicePath(dataDir));
  const logsDir = join(dataDir, "logs");
  mkdirSync(logsDir, { recursive: true, mode: 0o700 });
  const stdoutFd = openSync(join(logsDir, "service.stdout.log"), "a", 0o600);
  const stderrPath = join(logsDir, "service.stderr.log");
  const stderrFd = openSync(stderrPath, "a", 0o600);
  const child = spawn(server, ["-m", "workflow_environment_factory.cli", "serve"], {
    cwd: repositoryRoot,
    detached: true,
    env: {
      ...process.env,
      WEF_DATA_DIR: dataDir,
      WEF_PORT: String(options.port),
      WEF_HOST: "127.0.0.1",
      WEF_PROTOCOL_SCHEMA_DIR: protocolDirectory(),
      PYTHONUNBUFFERED: "1"
    },
    stdio: ["ignore", stdoutFd, stderrFd]
  });
  closeSync(stdoutFd);
  closeSync(stderrFd);
  child.unref();
  const record = {
    schema_version: "product.portable-service.v1",
    product,
    pid: child.pid,
    port: options.port,
    repository_root: repositoryRoot,
    server_path: server,
    command_marker: "workflow_environment_factory.cli",
    started_at: new Date().toISOString()
  };
  writeFileSync(servicePath(dataDir), `${JSON.stringify(record, null, 2)}\n`, { encoding: "utf8", flag: "wx", mode: 0o600 });
  const ready = await waitFor(async () => (await health(options.port))?.product === product, 20_000);
  if (!ready) {
    if (processAlive(child.pid)) process.kill(child.pid, "SIGTERM");
    rmSync(servicePath(dataDir), { force: true });
    const tail = existsSync(stderrPath) ? readFileSync(stderrPath, "utf8").split(/\r?\n/).slice(-30).join("\n") : "";
    fail(`${displayName} did not become healthy on port ${options.port}.\n${tail}`);
  }
  const url = sessionUrl(dataDir, options.port);
  process.stdout.write(`${displayName} is running as process ${child.pid}.\nData: ${dataDir}\n${url ?? ""}\n`);
  if (options.open && url) openUrl(url);
  return true;
}

async function stopService(options) {
  if (!existsSync(options.dataDir)) return false;
  const dataDir = assertDataRoot(options.dataDir);
  const record = readService(dataDir);
  const currentHealth = await health(options.port);
  if (!record) {
    if (currentHealth?.product === product) {
      fail(`A ${displayName} service is reachable, but this data directory has no owned portable service record.`);
    }
    return false;
  }
  if (record.port !== options.port) fail(`Portable service record uses port ${record.port}; pass --port ${record.port}.`);
  if (processAlive(record.pid)) {
    assertOwnedProcess(record);
    process.kill(record.pid, "SIGTERM");
    const stopped = await waitFor(() => !processAlive(record.pid), 5_000);
    if (!stopped) {
      assertOwnedProcess(record);
      process.kill(record.pid, "SIGKILL");
      if (!(await waitFor(() => !processAlive(record.pid), 2_000))) fail(`Owned process ${record.pid} did not stop.`);
    }
  }
  rmSync(servicePath(dataDir), { force: true });
  process.stdout.write(`Stopped ${displayName}.\n`);
  return true;
}

function codexState(required = true) {
  const codex = commandPath("codex");
  if (!codex) {
    if (required) fail("Codex CLI is required and was not found on PATH.");
    return { codex: "", pluginInstalled: null, marketplaceRegistered: null, errors: ["Codex CLI was not found."] };
  }
  const errors = [];
  let pluginInstalled = null;
  let marketplaceRegistered = null;
  try {
    const listing = run(codex, ["plugin", "list"], { capture: true });
    pluginInstalled = pluginListingContains(listing, pluginSelector);
  } catch (error) {
    errors.push(`plugin state: ${error.message}`);
  }
  try {
    const listing = run(codex, ["plugin", "marketplace", "list"], { capture: true });
    marketplaceRegistered = marketplaceListingContains(listing, marketplaceName);
  } catch (error) {
    errors.push(`marketplace state: ${error.message}`);
  }
  return { codex, pluginInstalled, marketplaceRegistered, errors };
}

function escapeRegex(value) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
}

function pluginListingContains(listing, selector) {
  return new RegExp(`^\\s*${escapeRegex(selector)}\\s+installed(?:,|\\s|$)`, "m").test(listing);
}

function marketplaceListingContains(listing, name) {
  return new RegExp(`^\\s*${escapeRegex(name)}(?:\\s+|$)`, "m").test(listing);
}

async function install(options) {
  requirePortablePlatform();
  requireNode22();
  const codex = codexState(true);
  assertPackagedRuntime();
  const python = installPythonRuntime(options);
  run(codex.codex, ["--version"]);
  if (options.skipDockerCheck) {
    if (process.env.WEF_PORTABLE_HOSTED_CI !== "1") {
      fail("--skip-docker-check is reserved for the disclosed GitHub-hosted macOS lifecycle gate.");
    }
    process.stderr.write("Docker daemon check skipped for hosted macOS lifecycle evidence; task execution is not claimed.\n");
  } else if (!dockerDaemonAvailable()) {
    fail("Docker with a reachable Linux-container daemon is required before Factory installation.");
  } else {
    run(
      python,
      ["-m", "workflow_environment_factory.cli", "doctor"],
      {
        env: {
          ...process.env,
          WEF_DATA_DIR: options.dataDir,
          WEF_PORT: String(options.port),
          WEF_HOST: "127.0.0.1",
          WEF_PROTOCOL_SCHEMA_DIR: protocolDirectory(),
          CODEX_EXECUTABLE: codex.codex,
          DOCKER_EXECUTABLE: commandPath("docker")
        }
      }
    );
  }
  const data = initializeDataRoot(options.dataDir);
  let marketplaceAdded = false;
  let pluginAdded = false;
  let serviceStarted = false;
  try {
    if (!codex.marketplaceRegistered) {
      run(codex.codex, ["plugin", "marketplace", "add", options.marketplaceSource]);
      marketplaceAdded = true;
    }
    if (!codex.pluginInstalled) {
      run(codex.codex, ["plugin", "add", pluginSelector]);
      pluginAdded = true;
    }
    const installed = codexState(true);
    if (!installed.marketplaceRegistered || !installed.pluginInstalled) fail("Codex did not retain the marketplace and plugin registration.");
    if (!options.noStart) serviceStarted = await startService(options);
    process.stdout.write(`${displayName} is installed. Restart Codex to load its simulator MCP tools and Skill.\n`);
  } catch (error) {
    if (serviceStarted) await stopService(options).catch(() => {});
    if (pluginAdded) spawnSync(codex.codex, ["plugin", "remove", pluginSelector], { stdio: "ignore" });
    if (marketplaceAdded) spawnSync(codex.codex, ["plugin", "marketplace", "remove", marketplaceName], { stdio: "ignore" });
    if (data.created && existsSync(data.dataDir)) removeOwnedDataRoot(data.dataDir);
    throw error;
  }
}

async function inspect(options) {
  requirePortablePlatform();
  const errors = [];
  const dataPresent = existsSync(options.dataDir);
  let dataOwned = false;
  let serviceRecordPresent = false;
  let serviceProcessOwned = false;
  if (dataPresent) {
    try {
      assertDataRoot(options.dataDir);
      dataOwned = true;
      const record = readService(options.dataDir);
      serviceRecordPresent = record !== null;
      if (record && processAlive(record.pid)) {
        assertOwnedProcess(record);
        serviceProcessOwned = true;
      }
    } catch (error) {
      errors.push(`data/service state: ${error.message}`);
    }
  }
  const currentHealth = await health(options.port);
  const serviceReachable = currentHealth?.product === product;
  const codex = codexState(false);
  errors.push(...codex.errors);
  const dockerAvailable = dockerDaemonAvailable();
  const installedStatePresent = serviceReachable || serviceRecordPresent || serviceProcessOwned || codex.pluginInstalled === true || codex.marketplaceRegistered === true;
  const state = {
    schema_version: "product.installation-state.v1",
    product,
    platform: process.platform,
    inspected_at: new Date().toISOString(),
    inspection_complete: errors.length === 0,
    installed_state_present: installedStatePresent,
    data_directory_present: dataPresent,
    data_directory_owned: dataOwned,
    checks: {
      service_reachable: serviceReachable,
      portable_service_record_present: serviceRecordPresent,
      portable_service_process_owned: serviceProcessOwned,
      plugin_installed: codex.pluginInstalled,
      marketplace_registered: codex.marketplaceRegistered,
      docker_daemon_reachable: dockerAvailable
    },
    errors
  };
  process.stdout.write(`${JSON.stringify(state, null, 2)}\n`);
  if (options.requireAbsent && (errors.length > 0 || installedStatePresent)) fail(`${displayName} installation absence could not be proved.`);
  if (options.requireNoData && dataPresent) fail(`${displayName} data is still present.`);
  return state;
}

async function uninstall(options) {
  requirePortablePlatform();
  await stopService(options).catch((error) => process.stderr.write(`Service stop needs attention: ${error.message}\n`));
  const codex = codexState(false);
  if (codex.codex) {
    if (codex.pluginInstalled) run(codex.codex, ["plugin", "remove", pluginSelector]);
    if (codex.marketplaceRegistered) run(codex.codex, ["plugin", "marketplace", "remove", marketplaceName]);
  }
  if (options.deleteData && existsSync(options.dataDir)) {
    removeOwnedDataRoot(options.dataDir);
    process.stdout.write(`Deleted local ${displayName} data: ${options.dataDir}\n`);
  } else {
    process.stdout.write(`Preserved local product data: ${options.dataDir}\n`);
  }
  await inspect({ ...options, requireAbsent: true, requireNoData: options.deleteData });
}

async function main() {
  const options = parseArguments(process.argv.slice(2));
  switch (options.command) {
    case "install":
      await install(options);
      break;
    case "start":
      requirePortablePlatform();
      await startService(options);
      break;
    case "stop":
      requirePortablePlatform();
      await stopService(options);
      break;
    case "inspect":
      await inspect(options);
      break;
    case "uninstall":
      await uninstall(options);
      break;
    default:
      fail(`Unknown command: ${options.command}`);
  }
}

export {
  assertDataRoot,
  assertSafeDataPath,
  commandOwnsServer,
  initializeDataRoot,
  marketplaceListingContains,
  parseArguments,
  pluginListingContains,
  removeOwnedDataRoot
};

if (resolve(process.argv[1] ?? "") === scriptPath) {
  main().catch((error) => {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 1;
  });
}
