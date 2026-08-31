#!/usr/bin/env node

import { createHash } from "node:crypto";
import {
  cpSync,
  existsSync,
  mkdirSync,
  mkdtempSync,
  readFileSync,
  rmSync,
  writeFileSync
} from "node:fs";
import { tmpdir } from "node:os";
import { basename, dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { spawnSync } from "node:child_process";

const scriptPath = fileURLToPath(import.meta.url);
const repositoryRoot = resolve(dirname(scriptPath), "..");
const protocolVersion = "0.1.2";
const protocolCommit = "462fa2fa7cdaa8f58cd4c1dcc9cf778e1d2d0073";
const schemaNames = [
  "agent.run.v1.schema.json",
  "workflow.case.v1.schema.json",
  "workflow.score.v1.schema.json"
];

function fail(message) {
  throw new Error(message);
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    cwd: options.cwd ?? repositoryRoot,
    encoding: "utf8",
    maxBuffer: 16 * 1024 * 1024
  });
  if (result.status !== 0) {
    fail(`${command} ${args.join(" ")} failed.\n${result.stderr || result.stdout}`.trim());
  }
  return result.stdout.trim();
}

function parseArguments(argv) {
  const values = new Map();
  for (let index = 0; index < argv.length; index += 2) {
    const key = argv[index];
    const value = argv[index + 1];
    if (!key?.startsWith("--") || value === undefined) fail("Use --version <version> --output <directory>.");
    values.set(key, value);
  }
  const version = values.get("--version");
  const output = values.get("--output");
  if (!version || !/^\d+\.\d+\.\d+$/.test(version) || !output || values.size !== 2) {
    fail("Use --version <version> --output <directory>.");
  }
  return { version, output: resolve(output) };
}

function sha256(path) {
  return createHash("sha256").update(readFileSync(path)).digest("hex");
}

function main() {
  const { version, output } = parseArguments(process.argv.slice(2));
  const packageJson = JSON.parse(readFileSync(join(repositoryRoot, "package.json"), "utf8"));
  const pluginJson = JSON.parse(
    readFileSync(join(repositoryRoot, "plugins/workflow-environment-factory/.codex-plugin/plugin.json"), "utf8")
  );
  if (packageJson.version !== version || pluginJson.version !== version) {
    fail(`Requested version ${version} must match package.json and plugin.json.`);
  }
  if (run("git", ["status", "--porcelain=v1"])) fail("Portable packaging requires a clean Git checkout.");
  const commit = run("git", ["rev-parse", "HEAD"]);
  if (!/^[0-9a-f]{40}$/.test(commit)) fail("Could not resolve the release commit.");

  const webIndex = join(repositoryRoot, "dist/web/index.html");
  if (!existsSync(webIndex)) fail("Missing production web build. Run npm run build:web first.");
  const protocolDirectory = join(repositoryRoot, ".runtime-deps", "runcase-interchange", protocolVersion, "schemas");
  const schemaHashes = {};
  for (const name of schemaNames) {
    const path = join(protocolDirectory, name);
    if (!existsSync(path)) fail(`Missing pinned RunCase schema: ${name}`);
    schemaHashes[name] = sha256(path);
  }

  mkdirSync(output, { recursive: true });
  const product = "workflow-environment-factory";
  const folderName = `${product}-${version}`;
  const archiveName = `${folderName}-portable.tar.gz`;
  const archivePath = join(output, archiveName);
  const checksumPath = `${archivePath}.sha256`;
  const manifestPath = join(output, `${folderName}-portable.release.json`);
  for (const path of [archivePath, checksumPath, manifestPath]) rmSync(path, { force: true });

  const temporaryRoot = mkdtempSync(join(tmpdir(), "wef-portable-package-"));
  try {
    const sourceArchive = join(temporaryRoot, "source.tar");
    const expanded = join(temporaryRoot, "expanded");
    mkdirSync(expanded);
    run("git", ["archive", "--format=tar", `--prefix=${folderName}/`, `--output=${sourceArchive}`, "HEAD"]);
    run("tar", ["-xf", sourceArchive, "-C", expanded]);
    const stageRoot = join(expanded, folderName);
    cpSync(join(repositoryRoot, "dist/web"), join(stageRoot, "dist/web"), { recursive: true, force: true });
    const stagedProtocol = join(stageRoot, ".runtime-deps", "runcase-interchange", protocolVersion);
    mkdirSync(join(stagedProtocol, "schemas"), { recursive: true });
    for (const name of schemaNames) {
      cpSync(join(protocolDirectory, name), join(stagedProtocol, "schemas", name));
    }
    writeFileSync(
      join(stagedProtocol, "dependency.json"),
      `${JSON.stringify({
        name: "runcase-interchange",
        version: protocolVersion,
        commit: protocolCommit,
        source: "https://github.com/rrrrrredy/runcase-interchange",
        release: `https://github.com/rrrrrredy/runcase-interchange/releases/tag/v${protocolVersion}`,
        files: schemaHashes
      }, null, 2)}\n`,
      "utf8"
    );
    writeFileSync(
      join(stageRoot, "release-source.json"),
      `${JSON.stringify({
        schema_version: "product.release-source.v1",
        product,
        version,
        commit
      }, null, 2)}\n`,
      "utf8"
    );

    const required = [
      "LICENSE",
      "NOTICE",
      "release-source.json",
      "scripts/Install.sh",
      "scripts/Acceptance-Portable.sh",
      "plugins/workflow-environment-factory/.codex-plugin/plugin.json",
      "dist/web/index.html",
      `.runtime-deps/runcase-interchange/${protocolVersion}/schemas/workflow.case.v1.schema.json`
    ];
    for (const file of required) {
      if (!existsSync(join(stageRoot, file))) fail(`Portable archive is missing required file: ${file}`);
    }
    run("tar", ["-czf", archivePath, "-C", expanded, folderName]);
  } finally {
    rmSync(temporaryRoot, { recursive: true, force: true });
  }

  const digest = sha256(archivePath);
  writeFileSync(checksumPath, `${digest}  ${basename(archivePath)}\n`, "utf8");
  writeFileSync(
    manifestPath,
    `${JSON.stringify({
      schema_version: "workflow-environment-factory.portable-release.v1",
      version,
      commit,
      release_tier: "technical_preview",
      target_platforms: ["linux-x64", "macos-arm64"],
      evidence_scope: {
        linux: "The tag workflow must run the extracted archive lifecycle with a reachable Linux-container Docker daemon.",
        macos: "The tag workflow must run the extracted archive lifecycle on hosted Apple Silicon macOS; Docker task execution is not claimed.",
        physical_device: "not_run",
        authenticated_codex_run: "not_run"
      },
      protocol_dependency: { version: protocolVersion, commit: protocolCommit, schema_sha256: schemaHashes },
      archive: { file: basename(archivePath), sha256: digest },
      created_at: new Date().toISOString()
    }, null, 2)}\n`,
    "utf8"
  );
  process.stdout.write(`Portable release archive: ${archivePath}\nSHA-256: ${digest}\n`);
}

try {
  main();
} catch (error) {
  process.stderr.write(`${error.message}\n`);
  process.exitCode = 1;
}
