import { useMemo, useState } from "react";
import { ArrowRight, Check, CircleDot, FolderGit2, GitBranch, LockKeyhole, Plus, Radio } from "lucide-react";

import { api } from "../api";
import type { Blueprint, BlueprintKind, BlueprintPayload, Recording, RecordingEvent } from "../types";
import { Button, Field, PageHeader, StatusTag, formatDate, shortId } from "../ui";

interface Props {
  blueprints: Blueprint[];
  recordings: Recording[];
  onChanged: () => Promise<void>;
  onContinue: () => void;
  onError: (message: string) => void;
}

interface Draft {
  name: string;
  kind: BlueprintKind;
  repositoryPath: string;
  baseRevision: string;
  solutionRevision: string;
  titleTemplate: string;
  goalTemplate: string;
  completionSummary: string;
  externalRef: string;
  variableName: string;
  original: string;
  variantOne: string;
  variantTwo: string;
  variablePaths: string;
  variableDescription: string;
  containerImage: string;
  verifierArgv: string;
  allowedPaths: string;
  timeoutMs: string;
  demonstrationId: string;
  issueKey: string;
  issueTitle: string;
  issueBody: string;
  initialStatus: string;
  targetStatus: string;
  prTarget: string;
}

const initialDraft: Draft = {
  name: "",
  kind: "code",
  repositoryPath: "",
  baseRevision: "HEAD~1",
  solutionRevision: "HEAD",
  titleTemplate: "Fix {value}",
  goalTemplate: "Complete the confirmed {value} task and pass the objective verifier.",
  completionSummary: "The objective verifier passes and changes stay inside the confirmed paths.",
  externalRef: "",
  variableName: "case_value",
  original: "",
  variantOne: "",
  variantTwo: "",
  variablePaths: "",
  variableDescription: "A user-confirmed value changed in both the baseline and correct repository states.",
  containerImage: "",
  verifierArgv: '["python", "verify.py"]',
  allowedPaths: "",
  timeoutMs: "900000",
  demonstrationId: "",
  issueKey: "APP-{value}",
  issueTitle: "Resolve {value}",
  issueBody: "Complete the confirmed {value} workflow.",
  initialStatus: "open",
  targetStatus: "in_review",
  prTarget: "main"
};

function splitValues(value: string): string[] {
  return value
    .split(/[\n,]/)
    .map((item) => item.trim())
    .filter(Boolean);
}

export function BlueprintPage({ blueprints, recordings, onChanged, onContinue, onError }: Props) {
  const [draft, setDraft] = useState<Draft>(initialDraft);
  const [creating, setCreating] = useState(false);
  const [recorderBusy, setRecorderBusy] = useState(false);
  const [activeRecordingId, setActiveRecordingId] = useState("");
  const [recordingStep, setRecordingStep] = useState(0);
  const [demo, setDemo] = useState({
    name: "Issue-to-PR demonstration",
    issueKey: "APP-alpha",
    path: "app.py",
    branch: "fix/app-alpha",
    target: "main",
    status: "in_review"
  });
  const confirmedRecordings = useMemo(
    () => recordings.filter((recording) => recording.status === "completed" && recording.confirmed),
    [recordings]
  );

  const update = <Key extends keyof Draft>(key: Key, value: Draft[Key]) => {
    setDraft((current) => ({ ...current, [key]: value }));
  };

  const createBlueprint = async () => {
    setCreating(true);
    try {
      const parsedArgv: unknown = JSON.parse(draft.verifierArgv);
      if (!Array.isArray(parsedArgv) || parsedArgv.some((item) => typeof item !== "string")) {
        throw new Error("Verifier argv must be a JSON array of strings.");
      }
      const variablePaths = splitValues(draft.variablePaths);
      const allowedPaths = splitValues(draft.allowedPaths);
      const isIssue = draft.kind === "issue_pr";
      const payload: BlueprintPayload = {
        name: draft.name,
        kind: draft.kind,
        repository_path: draft.repositoryPath,
        base_revision: draft.baseRevision,
        solution_revision: draft.solutionRevision,
        title_template: draft.titleTemplate,
        goal_template: draft.goalTemplate,
        completion_summary: draft.completionSummary,
        external_ref: draft.externalRef || null,
        variable: {
          name: draft.variableName,
          original: draft.original,
          variants: [draft.variantOne, draft.variantTwo],
          paths: variablePaths,
          confirmed_by_user: true,
          description: draft.variableDescription
        },
        container_image: draft.containerImage,
        verifier: { argv: parsedArgv, timeout_ms: 120_000 },
        allowed_paths: allowedPaths,
        allowed_tools: isIssue ? ["shell", "file", "git", "simulator-mcp"] : ["shell", "file", "git"],
        issue: isIssue
          ? {
              key: draft.issueKey,
              title: draft.issueTitle,
              body: draft.issueBody,
              initial_status: draft.initialStatus,
              target_status: draft.targetStatus,
              pr_target: draft.prTarget
            }
          : null,
        demonstration_id: isIssue ? draft.demonstrationId || null : null,
        timeout_ms: Number(draft.timeoutMs)
      };
      await api.createBlueprint(payload);
      await onChanged();
      setDraft(initialDraft);
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setCreating(false);
    }
  };

  const startRecording = async () => {
    setRecorderBusy(true);
    try {
      const recording = await api.startRecording(demo.name);
      setActiveRecordingId(recording.recording_id);
      setRecordingStep(0);
      await onChanged();
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setRecorderBusy(false);
    }
  };

  const recordNextStep = async () => {
    if (!activeRecordingId) return;
    const events: RecordingEvent[] = [
      { event_type: "issue_read", data: { issue_key: demo.issueKey } },
      { event_type: "repository_changed", data: { path: demo.path } },
      {
        event_type: "pr_created",
        data: { branch: demo.branch, target: demo.target, linked_issue_key: demo.issueKey }
      },
      { event_type: "issue_status_updated", data: { issue_key: demo.issueKey, status: demo.status } }
    ];
    const event = events[recordingStep];
    if (!event) return;
    setRecorderBusy(true);
    try {
      await api.appendRecording(activeRecordingId, event);
      const nextStep = recordingStep + 1;
      setRecordingStep(nextStep);
      await onChanged();
      if (nextStep === events.length) {
        const completed = await api.completeRecording(activeRecordingId, true);
        update("demonstrationId", completed.recording_id);
        setActiveRecordingId("");
        setRecordingStep(0);
        await onChanged();
      }
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setRecorderBusy(false);
    }
  };

  const stepLabels = ["Read the Issue", "Record repository change", "Create local PR", "Move Issue status"];

  return (
    <div className="page">
      <PageHeader
        eyebrow="01 / Define"
        title="Blueprint"
        description="Confirm the source, variable, reset boundary, and completion standard before any Case is generated."
        actions={
          blueprints.length ? (
            <Button tone="secondary" onClick={onContinue}>
              Open Case Factory <ArrowRight size={16} />
            </Button>
          ) : null
        }
      />

      <section className="principle-strip">
        <div>
          <FolderGit2 size={18} />
          <span>
            <strong>Baseline</strong> must fail
          </span>
        </div>
        <div>
          <Check size={18} />
          <span>
            <strong>Correct state</strong> must pass
          </span>
        </div>
        <div>
          <Radio size={18} />
          <span>
            <strong>Two resets</strong> must match
          </span>
        </div>
        <div>
          <LockKeyhole size={18} />
          <span>
            Solution and validators stay hidden from Codex
          </span>
        </div>
      </section>

      <div className="blueprint-layout">
        <section className="panel form-panel">
          <div className="section-heading">
            <div>
              <span className="section-kicker">New blueprint</span>
              <h2>Describe one real task family</h2>
            </div>
            <div className="segmented" aria-label="Blueprint kind">
              <button
                className={draft.kind === "code" ? "selected" : ""}
                type="button"
                onClick={() => update("kind", "code")}
              >
                Code
              </button>
              <button
                className={draft.kind === "issue_pr" ? "selected" : ""}
                type="button"
                onClick={() => update("kind", "issue_pr")}
              >
                Issue → PR
              </button>
            </div>
          </div>

          <div className="form-grid">
            <Field label="Blueprint name" wide>
              <input value={draft.name} onChange={(event) => update("name", event.target.value)} placeholder="Label normalization workflow" />
            </Field>
            <Field label="Repository path" hint="Local Git repository; never uploaded." wide>
              <input
                value={draft.repositoryPath}
                onChange={(event) => update("repositoryPath", event.target.value)}
                placeholder="D:\\Code\\label-normalizer"
              />
            </Field>
            <Field label="Baseline revision">
              <input value={draft.baseRevision} onChange={(event) => update("baseRevision", event.target.value)} />
            </Field>
            <Field label="Correct revision">
              <input value={draft.solutionRevision} onChange={(event) => update("solutionRevision", event.target.value)} />
            </Field>
            <Field label="Task title template">
              <input value={draft.titleTemplate} onChange={(event) => update("titleTemplate", event.target.value)} />
            </Field>
            <Field label="External task reference">
              <input
                value={draft.externalRef}
                onChange={(event) => update("externalRef", event.target.value)}
                placeholder="local-issue:{value}"
              />
            </Field>
            <Field label="Goal template" wide>
              <textarea value={draft.goalTemplate} onChange={(event) => update("goalTemplate", event.target.value)} rows={3} />
            </Field>
            <Field label="Completion summary" wide>
              <textarea
                value={draft.completionSummary}
                onChange={(event) => update("completionSummary", event.target.value)}
                rows={2}
              />
            </Field>
          </div>

          <div className="subsection-title">
            <CircleDot size={16} /> Confirmed variable and variants
          </div>
          <div className="form-grid four">
            <Field label="Variable name">
              <input value={draft.variableName} onChange={(event) => update("variableName", event.target.value)} />
            </Field>
            <Field label="Original value">
              <input value={draft.original} onChange={(event) => update("original", event.target.value)} placeholder="alpha" />
            </Field>
            <Field label="Variant 01">
              <input value={draft.variantOne} onChange={(event) => update("variantOne", event.target.value)} placeholder="beta" />
            </Field>
            <Field label="Variant 02">
              <input value={draft.variantTwo} onChange={(event) => update("variantTwo", event.target.value)} placeholder="gamma" />
            </Field>
            <Field label="Substitution paths" hint="Comma or newline separated." wide>
              <input value={draft.variablePaths} onChange={(event) => update("variablePaths", event.target.value)} placeholder="app.py" />
            </Field>
            <Field label="Why this variable is valid" wide>
              <input
                value={draft.variableDescription}
                onChange={(event) => update("variableDescription", event.target.value)}
              />
            </Field>
          </div>

          <div className="subsection-title">
            <GitBranch size={16} /> Environment and objective verifier
          </div>
          <div className="form-grid">
            <Field label="Immutable container image" hint="Image must include an exact sha256 digest." wide>
              <input
                value={draft.containerImage}
                onChange={(event) => update("containerImage", event.target.value)}
                placeholder="python:3.12-slim@sha256:…"
              />
            </Field>
            <Field label="Verifier argv" hint="JSON array; no shell expansion." wide>
              <input value={draft.verifierArgv} onChange={(event) => update("verifierArgv", event.target.value)} />
            </Field>
            <Field label="Writable paths" hint="Comma or newline separated.">
              <input value={draft.allowedPaths} onChange={(event) => update("allowedPaths", event.target.value)} placeholder="app.py" />
            </Field>
            <Field label="Agent timeout (ms)">
              <input inputMode="numeric" value={draft.timeoutMs} onChange={(event) => update("timeoutMs", event.target.value)} />
            </Field>
          </div>

          {draft.kind === "issue_pr" ? (
            <div className="issue-fields">
              <div className="subsection-title">Issue simulator contract</div>
              <div className="form-grid">
                <Field label="Confirmed demonstration" wide>
                  <select value={draft.demonstrationId} onChange={(event) => update("demonstrationId", event.target.value)}>
                    <option value="">Select a completed recording</option>
                    {confirmedRecordings.map((recording) => (
                      <option key={recording.recording_id} value={recording.recording_id}>
                        {recording.name} · {recording.events.length} events
                      </option>
                    ))}
                  </select>
                </Field>
                <Field label="Issue key template">
                  <input value={draft.issueKey} onChange={(event) => update("issueKey", event.target.value)} />
                </Field>
                <Field label="Issue title template">
                  <input value={draft.issueTitle} onChange={(event) => update("issueTitle", event.target.value)} />
                </Field>
                <Field label="Issue body" wide>
                  <textarea value={draft.issueBody} onChange={(event) => update("issueBody", event.target.value)} rows={2} />
                </Field>
                <Field label="Initial status">
                  <input value={draft.initialStatus} onChange={(event) => update("initialStatus", event.target.value)} />
                </Field>
                <Field label="Required status">
                  <input value={draft.targetStatus} onChange={(event) => update("targetStatus", event.target.value)} />
                </Field>
                <Field label="PR target">
                  <input value={draft.prTarget} onChange={(event) => update("prTarget", event.target.value)} />
                </Field>
              </div>
            </div>
          ) : null}

          <div className="form-actions">
            <span>Creation stores the blueprint only. Case generation runs the technical gate separately.</span>
            <Button busy={creating} onClick={() => void createBlueprint()}>
              <Plus size={16} /> Create blueprint
            </Button>
          </div>
        </section>

        <aside className="right-stack">
          {draft.kind === "issue_pr" ? (
            <section className="panel recorder-card">
              <div className="section-heading compact">
                <div>
                  <span className="section-kicker">Local recorder</span>
                  <h2>Capture one Issue → PR demonstration</h2>
                </div>
                <Radio size={18} />
              </div>
              {!activeRecordingId ? (
                <div className="recorder-form">
                  {Object.entries(demo).map(([key, value]) => (
                    <Field key={key} label={key.replace(/([A-Z])/g, " $1")}>
                      <input
                        value={value}
                        onChange={(event) => setDemo((current) => ({ ...current, [key]: event.target.value }))}
                      />
                    </Field>
                  ))}
                  <Button tone="secondary" busy={recorderBusy} onClick={() => void startRecording()}>
                    Start local recording
                  </Button>
                </div>
              ) : (
                <div className="recording-live">
                  <div className="recording-pulse">
                    <span /> Recording locally
                  </div>
                  <ol>
                    {stepLabels.map((label, index) => (
                      <li className={index < recordingStep ? "done" : index === recordingStep ? "current" : ""} key={label}>
                        {index < recordingStep ? <Check size={14} /> : <span>{index + 1}</span>}
                        {label}
                      </li>
                    ))}
                  </ol>
                  <Button busy={recorderBusy} onClick={() => void recordNextStep()}>
                    Record “{stepLabels[recordingStep]}”
                  </Button>
                  <p>The fourth action completes and confirms the recording. No production account is used.</p>
                </div>
              )}
            </section>
          ) : null}

          <section className="panel existing-card">
            <div className="section-heading compact">
              <div>
                <span className="section-kicker">Saved locally</span>
                <h2>{blueprints.length} blueprint{blueprints.length === 1 ? "" : "s"}</h2>
              </div>
            </div>
            <div className="blueprint-list">
              {blueprints.slice(0, 6).map((blueprint) => (
                <article key={blueprint.blueprint_id}>
                  <div>
                    <h3>{blueprint.payload.name}</h3>
                    <p>{blueprint.payload.kind === "code" ? "Code task" : "Issue → PR"} · {formatDate(blueprint.created_at)}</p>
                  </div>
                  <StatusTag status="confirmed" />
                  <dl>
                    <div>
                      <dt>Base</dt>
                      <dd>{shortId(blueprint.base_commit)}</dd>
                    </div>
                    <div>
                      <dt>Correct</dt>
                      <dd>{shortId(blueprint.solution_commit)}</dd>
                    </div>
                  </dl>
                </article>
              ))}
              {!blueprints.length ? <p className="muted-copy">No blueprint yet. Define the first real task family on the left.</p> : null}
            </div>
          </section>
        </aside>
      </div>
    </div>
  );
}
