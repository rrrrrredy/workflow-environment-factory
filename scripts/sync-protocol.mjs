#!/usr/bin/env node

import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { randomUUID } from "node:crypto";

const repositoryRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const expected = new Map([
  ["agent.run.v1.schema.json", "91beb4fd801e86aca4cf934cd6772bc155decf127f0cbbfb1d92b288ac18545e"],
  ["workflow.case.v1.schema.json", "475ba693caba4dd50b86f53d4ca9c54b6176dc5955ea245a04d7bf42f28ed808"],
  ["workflow.score.v1.schema.json", "a8fb3c43870c4c0e8a8358208bdc5d28d8fab35ebf72400a3109625127da7a36"]
]);

const rootIndex = process.argv.indexOf("--protocol-root");
if (rootIndex < 0 || !process.argv[rootIndex + 1]) {
  throw new Error("Usage: node scripts/sync-protocol.mjs --protocol-root /path/to/runcase-interchange");
}
const source = resolve(process.argv[rootIndex + 1], "schemas");
const destination = resolve(repositoryRoot, ".runtime-deps", "runcase-interchange", "0.1.2", "schemas");
mkdirSync(destination, { recursive: true });

for (const [name, expectedDigest] of expected) {
  const sourcePath = resolve(source, name);
  if (!existsSync(sourcePath)) throw new Error(`Protocol schema missing: ${sourcePath}`);
  const canonical = readFileSync(sourcePath, "utf8").replace(/\r\n?/g, "\n");
  const digest = createHash("sha256").update(canonical, "utf8").digest("hex");
  if (digest !== expectedDigest) {
    throw new Error(`RunCase v0.1.2 schema ${name} digest mismatch. Expected ${expectedDigest}, got ${digest}.`);
  }
  const target = resolve(destination, name);
  const temporary = `${target}.tmp-${randomUUID()}`;
  try {
    writeFileSync(temporary, canonical, { encoding: "utf8", flag: "wx", mode: 0o600 });
    rmSync(target, { force: true });
    renameSync(temporary, target);
  } finally {
    rmSync(temporary, { force: true });
  }
}

process.stdout.write(`RunCase Interchange 0.1.2 schemas synced to ${destination}\n`);
