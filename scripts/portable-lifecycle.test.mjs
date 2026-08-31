import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, readFileSync, rmSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import {
  assertDataRoot,
  assertSafeDataPath,
  commandOwnsServer,
  initializeDataRoot,
  marketplaceListingContains,
  parseArguments,
  pluginListingContains,
  removeOwnedDataRoot
} from "./portable-lifecycle.mjs";

test("portable arguments and unsafe roots fail closed", () => {
  const parsed = parseArguments(["install", "--port", "43121", "--skip-docker-check"]);
  assert.equal(parsed.port, 43121);
  assert.equal(parsed.skipDockerCheck, true);
  assert.throws(() => parseArguments(["start", "--port", "80"]), /between 1024 and 65535/);
  assert.throws(() => assertSafeDataPath("/"), /unsafe/);
});

test("Codex aligned plugin and marketplace tables are parsed exactly", () => {
  assert.equal(
    pluginListingContains(
      "workflow-environment-factory@workflow-environment-factory    installed, enabled  0.1.0  /tmp/plugin",
      "workflow-environment-factory@workflow-environment-factory"
    ),
    true
  );
  assert.equal(
    marketplaceListingContains("MARKETPLACE ROOT\nworkflow-environment-factory  /tmp/source", "workflow-environment-factory"),
    true
  );
});

test("portable ownership accepts the macOS-resolved Python executable only with the module marker", () => {
  const linkedPython = "/tmp/factory/.venv/bin/python";
  const realPython = "/Library/Frameworks/Python.framework/Versions/3.13/bin/python3.13";
  const marker = "workflow_environment_factory.cli";
  assert.equal(commandOwnsServer(`${realPython} -m ${marker} serve`, linkedPython, realPython, marker), true);
  assert.equal(commandOwnsServer(`${realPython} -m another.module serve`, linkedPython, realPython, marker), false);
  assert.equal(commandOwnsServer(`/tmp/foreign/python -m ${marker} serve`, linkedPython, realPython, marker), false);
});

test("portable data deletion requires the exact Factory marker", () => {
  const root = mkdtempSync(join(tmpdir(), "wef-portable-"));
  try {
    const owned = join(root, "owned-data");
    const initialized = initializeDataRoot(owned);
    assert.equal(initialized.created, true);
    assert.equal(
      JSON.parse(readFileSync(join(owned, ".workflow-environment-factory-data.json"), "utf8")).product,
      "workflow-environment-factory"
    );
    assert.equal(assertDataRoot(owned), owned);

    const foreign = join(root, "foreign-data");
    mkdirSync(foreign);
    writeFileSync(join(foreign, "keep.txt"), "keep", "utf8");
    assert.throws(() => removeOwnedDataRoot(foreign), /unmarked/);
    assert.equal(readFileSync(join(foreign, "keep.txt"), "utf8"), "keep");

    if (process.platform !== "win32") {
      const link = join(root, "linked-data");
      symlinkSync(owned, link, "dir");
      assert.throws(() => assertDataRoot(link), /real directory/);
    }
    removeOwnedDataRoot(owned);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});
