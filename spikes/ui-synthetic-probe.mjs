import { spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, readFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { createRequire } from "node:module";
import { fileURLToPath } from "node:url";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const scratchRoot = process.env.WEF_PROBE_TMP_ROOT ?? tmpdir();
mkdirSync(scratchRoot, { recursive: true });
const scratchDir = mkdtempSync(join(scratchRoot, "wef-synthetic-ui-"));
const dataDir = join(scratchDir, "data");
const outputDir = resolve(process.env.WEF_UI_OUTPUT_DIR ?? join(root, "docs", "images"));
const port = Number.parseInt(process.env.WEF_SYNTHETIC_PORT ?? "43141", 10);
const python = process.env.WEF_PYTHON ?? "python";
const require = createRequire(import.meta.url);
const playwrightModule = process.env.WEF_PLAYWRIGHT_MODULE ?? "playwright";
const { chromium } = require(playwrightModule);
const browserChannel = process.env.WEF_BROWSER_CHANNEL;
mkdirSync(outputDir, { recursive: true });

const server = spawn(python, [join(root, "spikes", "synthetic_server.py")], {
  cwd: root,
  env: { ...process.env, WEF_SYNTHETIC_DATA_DIR: dataDir, WEF_SYNTHETIC_PORT: String(port) },
  windowsHide: true,
  stdio: ["ignore", "pipe", "pipe"]
});
let serverStdout = "";
let serverStderr = "";
server.stdout.on("data", (chunk) => { serverStdout += chunk.toString(); });
server.stderr.on("data", (chunk) => { serverStderr += chunk.toString(); });

async function waitForHealth() {
  for (let attempt = 0; attempt < 240; attempt += 1) {
    if (server.exitCode !== null) {
      throw new Error(
        `Synthetic service exited before health (code ${server.exitCode}). stderr: ${serverStderr} stdout: ${serverStdout}`
      );
    }
    try {
      const response = await fetch(`http://127.0.0.1:${port}/health`);
      const body = await response.json();
      if (response.ok && body.product === "workflow-environment-factory") return;
    } catch {
      // Bounded loop against a synthetic loopback service only.
    }
    await new Promise((resolvePromise) => setTimeout(resolvePromise, 200));
  }
  throw new Error("Synthetic UI service did not become healthy.");
}

let browser;
try {
  await waitForHealth();
  const token = readFileSync(join(dataDir, "session-token"), "utf8").trim();
  browser = await chromium.launch({ headless: true, ...(browserChannel ? { channel: browserChannel } : {}) });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 } });
  const browserErrors = [];
  page.on("console", (message) => { if (message.type() === "error") browserErrors.push(message.text()); });
  page.on("pageerror", (error) => browserErrors.push(error.message));

  await page.goto(`http://127.0.0.1:${port}/session/${token}`, { waitUntil: "networkidle" });
  await page.getByRole("heading", { name: "Blueprint", exact: true }).waitFor();
  await page.locator(".segmented").getByRole("button", { name: "Issue → PR" }).click();
  await page.getByRole("button", { name: "Start local recording" }).click();
  for (let step = 0; step < 4; step += 1) {
    await page.getByRole("button", { name: /^Record “/ }).click();
  }
  const recordedOptionPresent = (await page.getByRole("option", { name: /Issue-to-PR demonstration/ }).count()) > 0;

  await page.locator(".nav-item").getByText("Case Factory").click();
  await page.getByRole("heading", { name: "Case Factory", exact: true }).waitFor();
  const caseColumns = await page.locator(".case-column").count();
  await page.getByRole("button", { name: /VARIANT 02/ }).click();
  const inspectorVisible = await page.locator(".case-inspector").isVisible();
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Export task pack" }).click();
  const taskPackDownload = await downloadPromise;
  const taskPackPath = await taskPackDownload.path();
  const taskPack = JSON.parse(readFileSync(taskPackPath, "utf8"));
  const taskPackCaseCount = taskPack.format === "wef.task-pack.v1" ? taskPack.cases.length : 0;
  await page.screenshot({ path: join(outputDir, "ui-desktop-case-factory-synthetic.png"), fullPage: true });

  await page.locator(".nav-item").getByText("Runs & Scores").click();
  await page.getByRole("heading", { name: "Runs & Scores", exact: true }).waitFor();
  await page.locator(".run-list-item").first().waitFor();
  const interruptedRun = page.locator(".run-list-item").filter({ hasText: "agent timeout" });
  await interruptedRun.click();
  await page.locator(".run-detail .status-tag").filter({ hasText: "agent timeout" }).waitFor();
  await page.locator(".score-card").waitFor();
  const runCount = await page.locator(".run-list-item").count();
  const notScoredBoundaryVisible = await page.getByText(/No validator ran/).isVisible();
  await page.locator('.protocol-library input[type="file"]').setInputFiles(
    join(root, "tests", "fixtures", "agent.run.synthetic.json")
  );
  await page.locator(".protocol-document-list article").waitFor();
  const protocolImportCount = await page.locator(".protocol-document-list article").count();
  await page.screenshot({ path: join(outputDir, "ui-desktop-runs-synthetic.png"), fullPage: true });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload({ waitUntil: "networkidle" });
  await page.getByRole("heading", { name: "Runs & Scores", exact: true }).waitFor();
  await page.screenshot({ path: join(outputDir, "ui-mobile-runs-synthetic.png"), fullPage: true });
  const overflow = await page.evaluate(() => ({
    viewport: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth
  }));

  const result = {
    data: "fully synthetic",
    recordedOptionPresent,
    caseColumns,
    inspectorVisible,
    taskPackCaseCount,
    runCount,
    notScoredBoundaryVisible,
    protocolImportCount,
    noHorizontalOverflow: overflow.scrollWidth <= overflow.viewport,
    browserErrors,
    outputs: [
      join(outputDir, "ui-desktop-case-factory-synthetic.png"),
      join(outputDir, "ui-desktop-runs-synthetic.png"),
      join(outputDir, "ui-mobile-runs-synthetic.png")
    ]
  };
  process.stdout.write(`${JSON.stringify(result, null, 2)}\n`);
  if (
    !result.recordedOptionPresent
    || result.caseColumns !== 3
    || !result.inspectorVisible
    || result.taskPackCaseCount !== 3
    || result.runCount !== 3
    || !result.notScoredBoundaryVisible
    || result.protocolImportCount !== 1
    || !result.noHorizontalOverflow
    || result.browserErrors.length > 0
  ) {
    throw new Error("Synthetic Workflow Factory UI acceptance failed");
  }
} finally {
  if (browser) await browser.close();
  if (server.exitCode === null) {
    const serverClosed = new Promise((resolvePromise) => server.once("close", resolvePromise));
    server.kill();
    await serverClosed;
  }
  rmSync(scratchDir, { recursive: true, force: true });
}
