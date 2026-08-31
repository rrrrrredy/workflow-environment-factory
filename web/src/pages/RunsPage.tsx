import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  Bot,
  CheckCircle2,
  Clock3,
  Code2,
  Download,
  FileJson2,
  Gauge,
  Play,
  RotateCcw,
  ShieldAlert,
  Sparkles,
  Trash2,
  Upload
} from "lucide-react";

import { api } from "../api";
import type { CaseRecord, ProtocolDocumentRecord, RunDetail, RunRecord } from "../types";
import { Button, EmptyState, PageHeader, StatusTag, formatDate, shortId } from "../ui";

interface Props {
  cases: CaseRecord[];
  runs: RunRecord[];
  onChanged: () => Promise<void>;
  onError: (message: string) => void;
}

const activeStatuses = new Set(["preparing", "running", "validating"]);

export function RunsPage({ cases, runs, onChanged, onError }: Props) {
  const runnableCases = useMemo(() => cases.filter((caseRecord) => caseRecord.validation.objective_gate_passed), [cases]);
  const [caseId, setCaseId] = useState(runnableCases[0]?.case_id ?? "");
  const [selectedRunId, setSelectedRunId] = useState(runs[0]?.run_id ?? "");
  const [detail, setDetail] = useState<RunDetail | null>(null);
  const [protocolDocuments, setProtocolDocuments] = useState<ProtocolDocumentRecord[]>([]);
  const [busy, setBusy] = useState("");

  useEffect(() => {
    if (!caseId && runnableCases[0]) setCaseId(runnableCases[0].case_id);
  }, [caseId, runnableCases]);

  useEffect(() => {
    if (!selectedRunId && runs[0]) setSelectedRunId(runs[0].run_id);
  }, [runs, selectedRunId]);

  const loadDetail = useCallback(
    async (runId: string, quiet = false) => {
      if (!runId) {
        setDetail(null);
        return null;
      }
      try {
        const next = await api.run(runId);
        setDetail(next);
        return next;
      } catch (reason) {
        if (!quiet) onError(reason instanceof Error ? reason.message : String(reason));
        return null;
      }
    },
    [onError]
  );

  useEffect(() => {
    void loadDetail(selectedRunId);
  }, [loadDetail, selectedRunId]);

  const loadProtocolDocuments = useCallback(async () => {
    try {
      setProtocolDocuments(await api.protocolImports());
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : String(reason));
    }
  }, [onError]);

  useEffect(() => {
    void loadProtocolDocuments();
  }, [loadProtocolDocuments]);

  useEffect(() => {
    if (!detail || !activeStatuses.has(detail.run.status)) return;
    const timer = window.setInterval(() => {
      void loadDetail(detail.run.run_id, true).then((next) => {
        if (next && !activeStatuses.has(next.run.status)) void onChanged();
      });
    }, 1500);
    return () => window.clearInterval(timer);
  }, [detail, loadDetail, onChanged]);

  const perform = async (name: string, operation: () => Promise<unknown>) => {
    setBusy(name);
    try {
      await operation();
      await onChanged();
      if (selectedRunId) await loadDetail(selectedRunId);
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy("");
    }
  };

  const prepare = async () => {
    if (!caseId) return;
    setBusy("prepare");
    try {
      const run = await api.prepareRun(caseId);
      setSelectedRunId(run.run_id);
      await onChanged();
      await loadDetail(run.run_id);
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy("");
    }
  };

  const execute = async () => {
    if (!detail) return;
    const runId = detail.run.run_id;
    setBusy("execute");
    try {
      await api.executeRun(runId);
      setDetail((current) =>
        current ? { ...current, run: { ...current.run, status: "running" }, score: null } : current
      );
      await onChanged();
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy("");
    }
  };

  const selectedCase = cases.find((caseRecord) => caseRecord.case_id === detail?.run.case_id) ?? null;
  const passCount = runs.filter((run) => run.status === "completed").length;
  const interruptedCount = runs.filter((run) => ["agent_timeout", "agent_crash", "environment_error", "reset_error"].includes(run.status)).length;

  const importProtocolFile = async (file: File) => {
    setBusy("import");
    try {
      const parsed: unknown = JSON.parse(await file.text());
      if (!parsed || typeof parsed !== "object") throw new Error("The selected file is not a JSON object.");
      const record = parsed as Record<string, unknown>;
      const documents = record.format === "wef.task-pack.v1" && Array.isArray(record.cases) ? record.cases : [record];
      for (const document of documents) {
        if (!document || typeof document !== "object" || Array.isArray(document)) {
          throw new Error("A task pack contains an invalid Case document.");
        }
        await api.importProtocol(document as Record<string, unknown>);
      }
      await loadProtocolDocuments();
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy("");
    }
  };

  const exportScore = async () => {
    if (!detail?.score) return;
    setBusy("export-score");
    try {
      const document = await api.exportScore(detail.run.run_id);
      const blob = new Blob([`${JSON.stringify(document, null, 2)}\n`], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = window.document.createElement("a");
      anchor.href = url;
      anchor.download = `workflow-score-${detail.run.run_id}.json`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setBusy("");
    }
  };

  return (
    <div className="page runs-page">
      <PageHeader
        eyebrow="03 / Run and score"
        title="Runs & Scores"
        description="Launch Codex in a fresh Case, follow the attempt, and separate task failure from Agent or environment failure."
      />

      <section className="run-launcher panel">
        <div>
          <span className="section-kicker">Fresh attempt</span>
          <h2>Choose a gated Case</h2>
          <p>Every click creates a new isolated Git snapshot and, for Issue → PR, a new simulator database.</p>
        </div>
        <select value={caseId} onChange={(event) => setCaseId(event.target.value)} aria-label="Case to prepare">
          {!runnableCases.length ? <option value="">Generate a gated Case first</option> : null}
          {runnableCases.map((caseRecord) => (
            <option key={caseRecord.case_id} value={caseRecord.case_id}>
              {caseRecord.protocol_case.title} · {caseRecord.variable_value}
            </option>
          ))}
        </select>
        <Button busy={busy === "prepare"} disabled={!caseId} onClick={() => void prepare()}>
          <RotateCcw size={16} /> Prepare fresh Run
        </Button>
      </section>

      <section className="run-metrics" aria-label="Run summary">
        <article>
          <Activity size={18} />
          <div>
            <span>Retained Runs</span>
            <strong>{runs.length}</strong>
          </div>
        </article>
        <article>
          <CheckCircle2 size={18} />
          <div>
            <span>Reached validation</span>
            <strong>{passCount}</strong>
          </div>
        </article>
        <article>
          <ShieldAlert size={18} />
          <div>
            <span>Interrupted, not task-failed</span>
            <strong>{interruptedCount}</strong>
          </div>
        </article>
        <article>
          <Gauge size={18} />
          <div>
            <span>Evidence policy</span>
            <strong>Single run</strong>
          </div>
        </article>
      </section>

      {!runs.length ? (
        <EmptyState title="No Run yet">
          Prepare a gated Case. The factory will keep Agent timeout, crash, reset failure, and task failure as different outcomes.
        </EmptyState>
      ) : (
        <div className="runs-workspace">
          <aside className="run-list panel">
            <div className="list-heading">
              <span>Recent Runs</span>
              <small>{runs.length} local</small>
            </div>
            {runs.map((run) => {
              const caseRecord = cases.find((candidate) => candidate.case_id === run.case_id);
              return (
                <button
                  className={run.run_id === selectedRunId ? "run-list-item selected" : "run-list-item"}
                  key={run.run_id}
                  type="button"
                  onClick={() => setSelectedRunId(run.run_id)}
                >
                  <div>
                    <strong>{caseRecord?.protocol_case.title ?? "Unknown Case"}</strong>
                    <span>{caseRecord?.variable_value ?? shortId(run.case_id)} · {formatDate(run.started_at)}</span>
                  </div>
                  <StatusTag status={run.status} />
                </button>
              );
            })}
          </aside>

          <section className="run-detail panel">
            {!detail ? (
              <div className="loading-inline">Loading Run evidence…</div>
            ) : (
              <>
                <header className="run-detail-header">
                  <div>
                    <span className="section-kicker">Run {shortId(detail.run.run_id)}</span>
                    <h2>{selectedCase?.protocol_case.title ?? "Codex attempt"}</h2>
                    <p>{selectedCase?.protocol_case.goal.text}</p>
                  </div>
                  <StatusTag status={detail.run.status} />
                </header>

                <div className="run-facts">
                  <div>
                    <span>Workspace</span>
                    <code title={detail.run.workspace_path}>{detail.run.workspace_path || "Not created"}</code>
                  </div>
                  <div>
                    <span>Started</span>
                    <strong>{formatDate(detail.run.started_at)}</strong>
                  </div>
                  <div>
                    <span>Finished</span>
                    <strong>{formatDate(detail.run.completed_at)}</strong>
                  </div>
                  <div>
                    <span>Captured events</span>
                    <strong>{detail.run.codex_events.length}</strong>
                  </div>
                </div>

                {detail.run.error ? (
                  <div className="run-error">
                    <ShieldAlert size={17} />
                    <div>
                      <strong>Execution did not complete normally</strong>
                      <span>{detail.run.error}</span>
                    </div>
                  </div>
                ) : null}

                <div className="run-actions">
                  {detail.run.status === "ready" ? (
                    <Button busy={busy === "execute"} onClick={() => void execute()}>
                      <Bot size={16} /> Execute with Codex
                    </Button>
                  ) : null}
                  {detail.run.status === "completed" && detail.run.agent_attempted && !detail.score ? (
                    <Button
                      tone="secondary"
                      busy={busy === "score"}
                      onClick={() =>
                        void perform("score", async () => {
                          await api.scoreRun(detail.run.run_id);
                        })
                      }
                    >
                      <Sparkles size={16} /> Validate completed attempt
                    </Button>
                  ) : null}
                  {!activeStatuses.has(detail.run.status) ? (
                    <Button
                      tone="quiet"
                      busy={busy === "cleanup"}
                      onClick={() =>
                        void perform("cleanup", async () => {
                          await api.cleanupRun(detail.run.run_id);
                        })
                      }
                    >
                      <Trash2 size={16} /> Remove Run workspace
                    </Button>
                  ) : null}
                </div>

                {detail.score ? (
                  <section className="score-card">
                    <div className="score-summary">
                      <div className={`score-orb ${detail.score.task_result.status}`}>
                        {detail.score.task_result.status === "not_scored"
                          ? "—"
                          : Math.round((detail.score.task_result.score ?? 0) * 100)}
                      </div>
                      <div>
                        <span className="section-kicker">Objective result</span>
                        <h3>{detail.score.task_result.status.replaceAll("_", " ")}</h3>
                        <p>{detail.score.task_result.reason}</p>
                      </div>
                      <div className="score-duration">
                        <Clock3 size={16} /> {(detail.score.resource_usage.duration_ms / 1000).toFixed(1)}s
                      </div>
                    </div>
                    <div className="validation-table">
                      {detail.score.validations.length ? (
                        detail.score.validations.map((validation) => (
                          <div key={validation.validator_id}>
                            <span>
                              <Code2 size={15} /> {validation.validator_id}
                            </span>
                            <span>{validation.summary}</span>
                            <StatusTag status={validation.status} />
                          </div>
                        ))
                      ) : (
                        <div className="not-scored-copy">
                          No validator ran. Agent interruption is retained as execution evidence, not converted into a task score.
                        </div>
                      )}
                    </div>
                    <p className="single-run-note">Single-run evidence: this result describes one attempt, not general Agent quality.</p>
                    <div className="score-export">
                      <Button tone="quiet" busy={busy === "export-score"} onClick={() => void exportScore()}>
                        <Download size={15} /> Export workflow.score.v1
                      </Button>
                    </div>
                  </section>
                ) : null}

                <section className="event-log">
                  <div className="list-heading">
                    <span>Codex event stream</span>
                    <small>Secrets redacted before storage</small>
                  </div>
                  {detail.run.codex_events.length ? (
                    detail.run.codex_events.slice(-30).map((event, index) => (
                      <div className="event-row" key={`${index}-${String(event.type ?? "event")}`}>
                        <span>{String(event.type ?? "event")}</span>
                        <code>{JSON.stringify(event)}</code>
                      </div>
                    ))
                  ) : (
                    <p className="muted-copy">No Codex event has been retained for this Run yet.</p>
                  )}
                </section>
              </>
            )}
          </section>
        </div>
      )}

      <section className="protocol-library panel">
        <div className="protocol-library-heading">
          <div>
            <span className="section-kicker">Open interchange</span>
            <h2>Protocol library</h2>
            <p>Validate and retain RunCase Interchange files. Imported documents remain evidence; they never become runnable local Cases automatically.</p>
          </div>
          <label className={busy === "import" ? "button secondary disabled" : "button secondary"}>
            <Upload size={16} /> {busy === "import" ? "Importing…" : "Import JSON"}
            <input
              type="file"
              accept="application/json,.json"
              disabled={busy === "import"}
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void importProtocolFile(file);
                event.target.value = "";
              }}
            />
          </label>
        </div>
        <div className="protocol-document-list">
          {protocolDocuments.map((document) => (
            <article key={document.document_id}>
              <FileJson2 size={18} />
              <div>
                <strong>{document.schema_version}</strong>
                <span>{shortId(document.external_id, 18)} · {formatDate(document.imported_at)}</span>
              </div>
              <code>{shortId(document.digest, 14)}</code>
            </article>
          ))}
          {!protocolDocuments.length ? (
            <p className="muted-copy">No imported document. You can import Runtime Evolution Workbench `agent.run.v1` files here.</p>
          ) : null}
        </div>
      </section>
    </div>
  );
}
