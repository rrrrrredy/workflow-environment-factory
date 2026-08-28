import { readFileSync } from "node:fs";
import { homedir } from "node:os";
import { join } from "node:path";

const tools = [
  {
    name: "wef_get_run",
    description: "Read one factory Run and the bounded Agent-safe Case context needed to complete it.",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      required: ["run_id"],
      properties: { run_id: { type: "string", format: "uuid" } }
    }
  },
  {
    name: "wef_get_case",
    description: "Read the bounded Agent-safe view of one validated Case. Known-correct refs and factory-only evidence are omitted.",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      required: ["case_id"],
      properties: { case_id: { type: "string", format: "uuid" } }
    }
  },
  {
    name: "wef_get_issue",
    description: "Read the single local simulator Issue for an Issue-to-PR Run and record the read action. This never contacts a production service.",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      required: ["run_id", "issue_key"],
      properties: {
        run_id: { type: "string", format: "uuid" },
        issue_key: { type: "string", minLength: 1, maxLength: 100 }
      }
    }
  },
  {
    name: "wef_list_pull_requests",
    description: "List pull requests created inside one Run's local simulator.",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      required: ["run_id"],
      properties: { run_id: { type: "string", format: "uuid" } }
    }
  },
  {
    name: "wef_create_pr",
    description: "Create a pull request only in one Run's local simulator. This cannot change a score or contact GitHub.",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      required: ["run_id", "title", "branch", "target", "linked_issue_key"],
      properties: {
        run_id: { type: "string", format: "uuid" },
        title: { type: "string", minLength: 1, maxLength: 500 },
        branch: { type: "string", minLength: 1, maxLength: 200 },
        target: { type: "string", minLength: 1, maxLength: 200 },
        linked_issue_key: { type: "string", minLength: 1, maxLength: 100 }
      }
    }
  },
  {
    name: "wef_update_issue_status",
    description: "Update one local simulator Issue status for a Run. The objective validator separately checks the required final status.",
    inputSchema: {
      type: "object",
      additionalProperties: false,
      required: ["run_id", "issue_key", "status"],
      properties: {
        run_id: { type: "string", format: "uuid" },
        issue_key: { type: "string", minLength: 1, maxLength: 100 },
        status: { type: "string", minLength: 1, maxLength: 100 }
      }
    }
  }
];

function dataRoot() {
  if (process.env.WEF_DATA_DIR) return process.env.WEF_DATA_DIR;
  if (process.env.LOCALAPPDATA) return join(process.env.LOCALAPPDATA, "WorkflowEnvironmentFactory");
  return join(homedir(), ".workflow-environment-factory");
}

function token() {
  return readFileSync(join(dataRoot(), "session-token"), "utf8").trim();
}

async function api(path, options = {}) {
  const port = process.env.WEF_PORT ?? "43121";
  const response = await fetch(`http://127.0.0.1:${port}${path}`, {
    ...options,
    headers: {
      authorization: `Bearer ${token()}`,
      "content-type": "application/json",
      ...(options.headers ?? {})
    },
    signal: AbortSignal.timeout(120_000)
  });
  const text = await response.text();
  let body;
  try {
    body = text ? JSON.parse(text) : {};
  } catch {
    body = { error: "invalid_local_service_response" };
  }
  if (!response.ok) throw new Error(`${response.status}: ${JSON.stringify(body)}`);
  return body;
}

async function callTool(name, args) {
  const runId = args.run_id ? encodeURIComponent(args.run_id) : "";
  if (name === "wef_get_run") return api(`/api/agent/runs/${runId}`);
  if (name === "wef_get_case") return api(`/api/agent/cases/${encodeURIComponent(args.case_id)}`);
  if (name === "wef_get_issue") {
    return api(`/api/simulator/runs/${runId}/issues/${encodeURIComponent(args.issue_key)}`);
  }
  if (name === "wef_list_pull_requests") return api(`/api/simulator/runs/${runId}/pull-requests`);
  if (name === "wef_create_pr") {
    return api(`/api/simulator/runs/${runId}/pull-requests`, {
      method: "POST",
      body: JSON.stringify({
        title: args.title,
        branch: args.branch,
        target: args.target,
        linked_issue_key: args.linked_issue_key
      })
    });
  }
  if (name === "wef_update_issue_status") {
    return api(`/api/simulator/runs/${runId}/issues/${encodeURIComponent(args.issue_key)}/status`, {
      method: "POST",
      body: JSON.stringify({ status: args.status })
    });
  }
  throw new Error(`Unknown tool: ${name}`);
}

function send(message) {
  process.stdout.write(`${JSON.stringify(message)}\n`);
}

async function handle(message) {
  if (!message || typeof message !== "object" || typeof message.method !== "string" || !("id" in message)) return;
  try {
    if (message.method === "initialize") {
      const requested = message.params?.protocolVersion;
      const supported = ["2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05", "2024-10-07"];
      send({
        jsonrpc: "2.0",
        id: message.id,
        result: {
          protocolVersion: supported.includes(requested) ? requested : "2025-11-25",
          capabilities: { tools: { listChanged: false } },
          serverInfo: { name: "workflow-environment-factory", version: "0.1.0" }
        }
      });
      return;
    }
    if (message.method === "ping") {
      send({ jsonrpc: "2.0", id: message.id, result: {} });
      return;
    }
    if (message.method === "tools/list") {
      send({ jsonrpc: "2.0", id: message.id, result: { tools } });
      return;
    }
    if (message.method === "tools/call") {
      const result = await callTool(message.params?.name, message.params?.arguments ?? {});
      send({
        jsonrpc: "2.0",
        id: message.id,
        result: {
          content: [{ type: "text", text: JSON.stringify(result, null, 2) }],
          structuredContent: result,
          isError: false
        }
      });
      return;
    }
    send({ jsonrpc: "2.0", id: message.id, error: { code: -32601, message: `Method not found: ${message.method}` } });
  } catch (error) {
    send({
      jsonrpc: "2.0",
      id: message.id,
      result: {
        content: [
          {
            type: "text",
            text: `Workflow Environment Factory unavailable: ${error instanceof Error ? error.message : String(error)}`
          }
        ],
        isError: true
      }
    });
  }
}

let buffer = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (chunk) => {
  buffer += chunk;
  let index;
  while ((index = buffer.indexOf("\n")) >= 0) {
    const line = buffer.slice(0, index).replace(/\r$/, "");
    buffer = buffer.slice(index + 1);
    if (line.trim().length === 0) continue;
    try {
      void handle(JSON.parse(line));
    } catch {
      // Invalid transport lines are ignored; stdout remains protocol-only.
    }
  }
});
