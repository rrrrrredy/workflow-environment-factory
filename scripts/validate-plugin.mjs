import { existsSync, readFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const pluginRoot = join(root, "plugins", "workflow-environment-factory");
const marketplacePath = join(root, ".agents", "plugins", "marketplace.json");
const manifestPath = join(pluginRoot, ".codex-plugin", "plugin.json");
const requiredFiles = [
  marketplacePath,
  manifestPath,
  join(pluginRoot, ".mcp.json"),
  join(pluginRoot, "scripts", "mcp-server.mjs"),
  join(pluginRoot, "skills", "factory-case", "SKILL.md")
];

for (const path of requiredFiles) {
  if (!existsSync(path)) throw new Error(`Required plugin file is missing: ${path}`);
}

const manifest = JSON.parse(readFileSync(manifestPath, "utf8"));
if (manifest.name !== "workflow-environment-factory" || manifest.version !== "0.2.1") {
  throw new Error("Plugin name/version does not match the release contract.");
}
if (manifest.mcpServers !== "./.mcp.json" || manifest.skills !== "./skills/") {
  throw new Error("Plugin capability paths are invalid.");
}

const marketplace = JSON.parse(readFileSync(marketplacePath, "utf8"));
if (marketplace.name !== "workflow-environment-factory") throw new Error("Marketplace name is invalid.");
const entry = marketplace.plugins?.find((candidate) => candidate.name === manifest.name);
if (!entry || entry.source?.source !== "local" || entry.source?.path !== "./plugins/workflow-environment-factory") {
  throw new Error("Marketplace plugin source is invalid.");
}

process.stdout.write("Plugin structure and marketplace metadata passed.\n");
