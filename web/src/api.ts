import type {
  Blueprint,
  BlueprintPayload,
  CaseRecord,
  Meta,
  ProtocolDocumentRecord,
  Recording,
  RecordingEvent,
  RunDetail,
  RunRecord,
  WorkflowScore
} from "./types";

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number
  ) {
    super(message);
  }
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(path, {
    ...init,
    credentials: "same-origin",
    headers: {
      "content-type": "application/json",
      ...(init?.headers ?? {})
    }
  });
  const text = await response.text();
  let body: unknown = {};
  if (text) {
    try {
      body = JSON.parse(text);
    } catch {
      body = { detail: text };
    }
  }
  if (!response.ok) {
    const detail = body && typeof body === "object" && "detail" in body ? String(body.detail) : `HTTP ${response.status}`;
    throw new ApiError(response.status === 401 ? "Local session expired. Restart the workbench to open a fresh session." : detail, response.status);
  }
  return body as T;
}

export const api = {
  meta: () => request<Meta>("/api/meta"),
  recordings: async () => (await request<{ recordings: Recording[] }>("/api/recordings")).recordings,
  startRecording: (name: string) =>
    request<Recording>("/api/recordings", { method: "POST", body: JSON.stringify({ name }) }),
  appendRecording: (recordingId: string, event: RecordingEvent) =>
    request<Recording>(`/api/recordings/${encodeURIComponent(recordingId)}/events`, {
      method: "POST",
      body: JSON.stringify(event)
    }),
  completeRecording: (recordingId: string, confirmed: boolean) =>
    request<Recording>(`/api/recordings/${encodeURIComponent(recordingId)}/complete`, {
      method: "POST",
      body: JSON.stringify({ confirmed })
    }),
  blueprints: async () => (await request<{ blueprints: Blueprint[] }>("/api/blueprints")).blueprints,
  createBlueprint: (payload: BlueprintPayload) =>
    request<Blueprint>("/api/blueprints", { method: "POST", body: JSON.stringify(payload) }),
  cases: async (blueprintId?: string) =>
    (
      await request<{ cases: CaseRecord[] }>(
        blueprintId ? `/api/cases?blueprint_id=${encodeURIComponent(blueprintId)}` : "/api/cases"
      )
    ).cases,
  generateCases: (blueprintId: string) =>
    request<{ cases: CaseRecord[]; all_gates_passed: boolean }>(
      `/api/blueprints/${encodeURIComponent(blueprintId)}/generate`,
      { method: "POST" }
    ),
  exportTaskPack: (blueprintId: string) =>
    request<Record<string, unknown>>(`/api/blueprints/${encodeURIComponent(blueprintId)}/export`),
  exportCase: (caseId: string) => request<Record<string, unknown>>(`/api/cases/${encodeURIComponent(caseId)}/export`),
  runs: async () => (await request<{ runs: RunRecord[] }>("/api/runs")).runs,
  run: (runId: string) => request<RunDetail>(`/api/runs/${encodeURIComponent(runId)}`),
  prepareRun: (caseId: string) =>
    request<RunRecord>(`/api/cases/${encodeURIComponent(caseId)}/runs`, { method: "POST" }),
  executeRun: (runId: string) =>
    request<{ accepted: boolean; run_id: string }>(`/api/runs/${encodeURIComponent(runId)}/execute`, {
      method: "POST"
    }),
  scoreRun: (runId: string) =>
    request<WorkflowScore>(`/api/runs/${encodeURIComponent(runId)}/score`, { method: "POST" }),
  exportScore: (runId: string) => request<Record<string, unknown>>(`/api/runs/${encodeURIComponent(runId)}/score/export`),
  protocolImports: async () =>
    (await request<{ documents: ProtocolDocumentRecord[] }>("/api/protocol/imports")).documents,
  importProtocol: (document: Record<string, unknown>) =>
    request<ProtocolDocumentRecord>("/api/protocol/imports", {
      method: "POST",
      body: JSON.stringify({ document })
    }),
  cleanupRun: (runId: string) =>
    request<{ cleaned: boolean; run_id: string }>(`/api/runs/${encodeURIComponent(runId)}/cleanup`, {
      method: "POST"
    })
};
