export type BlueprintKind = "code" | "issue_pr";
export type RunStatus =
  | "preparing"
  | "ready"
  | "running"
  | "validating"
  | "completed"
  | "agent_timeout"
  | "agent_crash"
  | "reset_error"
  | "environment_error";

export interface Meta {
  product: string;
  version: string;
  engine: string;
  docker_available: boolean | null;
  docker_details: string | null;
  protocol_schema_dir: string;
  data_dir: string;
  gate: string;
}

export interface RecordingEvent {
  event_type: "issue_read" | "repository_changed" | "pr_created" | "issue_status_updated";
  data: Record<string, unknown>;
  timestamp?: string;
}

export interface Recording {
  recording_id: string;
  name: string;
  status: "recording" | "completed";
  events: RecordingEvent[];
  confirmed: boolean;
  created_at: string;
  completed_at: string | null;
}

export interface BlueprintPayload {
  name: string;
  kind: BlueprintKind;
  repository_path: string;
  base_revision: string;
  solution_revision: string;
  title_template: string;
  goal_template: string;
  completion_summary: string;
  external_ref: string | null;
  variable: {
    name: string;
    original: string;
    variants: [string, string];
    paths: string[];
    confirmed_by_user: boolean;
    description: string;
  };
  container_image: string;
  verifier: { argv: string[]; timeout_ms: number };
  allowed_paths: string[];
  allowed_tools: string[];
  issue: null | {
    key: string;
    title: string;
    body: string;
    initial_status: string;
    target_status: string;
    pr_target: string;
  };
  demonstration_id: string | null;
  timeout_ms: number;
}

export interface Blueprint {
  blueprint_id: string;
  payload: BlueprintPayload;
  repository_root: string;
  base_commit: string;
  solution_commit: string;
  solution_patch_digest: string;
  created_at: string;
}

export interface CaseValidation {
  baseline_status: "pass" | "fail" | "error" | "timeout";
  solution_status: "pass" | "fail" | "error" | "timeout";
  baseline_exit_code: number | null;
  solution_exit_code: number | null;
  reset_verified: boolean;
  objective_gate_passed: boolean;
  details: string;
}

export interface ProtocolCase {
  schema_version: "workflow.case.v1";
  case_id: string;
  title: string;
  description: string;
  goal: { text: string; completion_summary: string; external_ref?: string };
  variables: Array<{ name: string; value: string; source: string; confirmed_by_user: boolean }>;
  environment: {
    kind: string;
    summary: string;
    build_ref: string;
    digest: string;
    repository?: { source_ref: string; base_revision: string };
  };
  allowed_tools: Array<{ name: string; interface: string; scopes: string[] }>;
  validators: Array<{
    validator_id: string;
    name: string;
    kind: string;
    required: boolean;
    objective: boolean;
    weight: number;
  }>;
  provenance: {
    kind: string;
    parent_case_id?: string;
    confirmed_by_user: boolean;
    source_refs: Array<{ kind: string; ref: string }>;
    transformation?: { recipe: string; parameters: Record<string, unknown>; patch_ref: string };
  };
  safety: {
    network: string;
    network_allowlist?: string[];
    writable_paths: string[];
    denied_paths: string[];
    timeout_ms: number;
  };
  created_at: string;
}

export interface CaseRecord {
  case_id: string;
  blueprint_id: string;
  variant_index: number;
  variable_value: string;
  protocol_case: ProtocolCase;
  validation: CaseValidation;
  created_at: string;
}

export interface RunRecord {
  run_id: string;
  case_id: string;
  status: RunStatus;
  workspace_path: string;
  simulator_database_path: string | null;
  agent_attempted: boolean;
  codex_events: Array<Record<string, unknown>>;
  error: string;
  started_at: string;
  completed_at: string | null;
}

export interface ValidationResult {
  validator_id: string;
  status: "pass" | "fail" | "error" | "skipped";
  objective: boolean;
  required: boolean;
  duration_ms: number;
  summary?: string;
}

export interface WorkflowScore {
  schema_version: "workflow.score.v1";
  score_id: string;
  run_id: string;
  case_id: string;
  created_at: string;
  execution: { status: string; started_at: string; ended_at: string; failure_stage?: string; details?: string };
  task_result: { status: "pass" | "partial" | "fail" | "not_scored"; score?: number; reason?: string };
  validations: ValidationResult[];
  resource_usage: { duration_ms: number; validation_ms?: number };
  nondeterminism: { sample_count: number; single_run_evidence: boolean; notes: string[] };
  summary: string;
}

export interface RunDetail {
  run: RunRecord;
  score: WorkflowScore | null;
}

export interface ProtocolDocumentRecord {
  document_id: string;
  schema_version: "agent.run.v1" | "workflow.case.v1" | "workflow.score.v1";
  external_id: string;
  digest: string;
  document: Record<string, unknown>;
  imported_at: string;
}
