import { useEffect, useMemo, useState } from "react";
import {
  ArrowRight,
  Check,
  Download,
  Eye,
  FileCode2,
  GitCompareArrows,
  Lock,
  Play,
  RefreshCw,
  Shield,
  Sparkles
} from "lucide-react";

import { api } from "../api";
import type { Blueprint, CaseRecord } from "../types";
import { Button, EmptyState, PageHeader, StatusTag, shortId } from "../ui";

interface Props {
  blueprints: Blueprint[];
  cases: CaseRecord[];
  onChanged: () => Promise<void>;
  onContinue: () => void;
  onError: (message: string) => void;
}

function gateRows(caseRecord: CaseRecord) {
  return [
    {
      name: "Baseline fails",
      detail: `Verifier ${caseRecord.validation.baseline_status}`,
      passed: caseRecord.validation.baseline_status === "fail",
      expected: "EXPECTED FAIL"
    },
    {
      name: "Correct state passes",
      detail: `Verifier ${caseRecord.validation.solution_status}`,
      passed: caseRecord.validation.solution_status === "pass",
      expected: "PASS"
    },
    {
      name: "Reset A = Reset B",
      detail: "Fresh repository states match",
      passed: caseRecord.validation.reset_verified,
      expected: "EQUAL"
    },
    {
      name: "Objective state gate",
      detail: caseRecord.protocol_case.validators.map((validator) => validator.name).join(" · "),
      passed: caseRecord.validation.objective_gate_passed,
      expected: "PASS"
    }
  ];
}

export function CaseFactoryPage({ blueprints, cases, onChanged, onContinue, onError }: Props) {
  const [blueprintId, setBlueprintId] = useState(blueprints[0]?.blueprint_id ?? "");
  const [selectedCaseId, setSelectedCaseId] = useState("");
  const [generating, setGenerating] = useState(false);
  const [exporting, setExporting] = useState(false);

  useEffect(() => {
    if (!blueprintId && blueprints[0]) setBlueprintId(blueprints[0].blueprint_id);
  }, [blueprintId, blueprints]);

  const blueprint = blueprints.find((item) => item.blueprint_id === blueprintId) ?? null;
  const visibleCases = useMemo(
    () => cases.filter((caseRecord) => caseRecord.blueprint_id === blueprintId).sort((a, b) => a.variant_index - b.variant_index),
    [blueprintId, cases]
  );

  useEffect(() => {
    if (!visibleCases.some((caseRecord) => caseRecord.case_id === selectedCaseId)) {
      setSelectedCaseId(visibleCases[0]?.case_id ?? "");
    }
  }, [selectedCaseId, visibleCases]);

  const selectedCase = visibleCases.find((caseRecord) => caseRecord.case_id === selectedCaseId) ?? null;

  const generate = async () => {
    if (!blueprintId) return;
    setGenerating(true);
    try {
      const result = await api.generateCases(blueprintId);
      if (!result.all_gates_passed) {
        onError("At least one Case failed its objective generation gate. Inspect the evidence before running Codex.");
      }
      await onChanged();
      setSelectedCaseId(result.cases[0]?.case_id ?? "");
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setGenerating(false);
    }
  };

  const exportSelected = async () => {
    if (!blueprint || visibleCases.length !== 3) return;
    setExporting(true);
    try {
      const document = await api.exportTaskPack(blueprint.blueprint_id);
      const blob = new Blob([`${JSON.stringify(document, null, 2)}\n`], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const anchor = window.document.createElement("a");
      anchor.href = url;
      anchor.download = `workflow-task-pack-${blueprint.blueprint_id}.json`;
      anchor.click();
      URL.revokeObjectURL(url);
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : String(reason));
    } finally {
      setExporting(false);
    }
  };

  return (
    <div className="page case-page">
      <PageHeader
        eyebrow="02 / Generate and gate"
        title="Case Factory"
        description="One source task becomes a base Case and exactly two traceable variants. Every Case must pass the gate before it can run."
        actions={
          <>
            <Button
              tone="secondary"
              busy={exporting}
              disabled={!blueprint || visibleCases.length !== 3}
              onClick={() => void exportSelected()}
            >
              <Download size={16} /> Export task pack
            </Button>
            <Button busy={generating} disabled={!blueprint || visibleCases.length > 0} onClick={() => void generate()}>
              <Sparkles size={16} /> {visibleCases.length ? "Cases generated" : "Generate cases"}
            </Button>
          </>
        }
      />

      <section className="selector-bar">
        <label>
          <span>Blueprint</span>
          <select value={blueprintId} onChange={(event) => setBlueprintId(event.target.value)}>
            {!blueprints.length ? <option value="">Create a blueprint first</option> : null}
            {blueprints.map((item) => (
              <option key={item.blueprint_id} value={item.blueprint_id}>
                {item.payload.name}
              </option>
            ))}
          </select>
        </label>
        {blueprint ? (
          <div className="source-facts">
            <div>
              <span>Source</span>
              <strong>{blueprint.payload.name}</strong>
            </div>
            <div>
              <span>Baseline</span>
              <strong>{shortId(blueprint.base_commit)}</strong>
            </div>
            <div>
              <span>Correct state</span>
              <strong>{shortId(blueprint.solution_commit)}</strong>
            </div>
            <div>
              <span>Container</span>
              <strong>{shortId(blueprint.payload.container_image, 18)}</strong>
            </div>
          </div>
        ) : null}
      </section>

      {!blueprint ? (
        <EmptyState title="No blueprint selected">Create a blueprint that names a real baseline and a known-correct revision.</EmptyState>
      ) : null}

      {blueprint && !visibleCases.length ? (
        <EmptyState title="Ready to generate three Cases">
          The factory will materialize each state twice, run the baseline and correct verifier, and retain failure evidence instead of accepting an unproven variant.
        </EmptyState>
      ) : null}

      {visibleCases.length ? (
        <div className="case-workspace">
          <section className="case-matrix" aria-label="Generated Case gate matrix">
            {visibleCases.map((caseRecord) => {
              const selected = caseRecord.case_id === selectedCaseId;
              return (
                <button
                  className={selected ? "case-column selected" : "case-column"}
                  key={caseRecord.case_id}
                  type="button"
                  onClick={() => setSelectedCaseId(caseRecord.case_id)}
                >
                  <header>
                    <span>{caseRecord.variant_index === 0 ? "BASE" : `VARIANT 0${caseRecord.variant_index}`}</span>
                    <StatusTag status={caseRecord.validation.objective_gate_passed} label="Gated" />
                  </header>
                  <div className="case-identity">
                    <div>
                      <span>Variable</span>
                      <strong>{caseRecord.variable_value}</strong>
                    </div>
                    <div>
                      <span>Provenance</span>
                      <strong>{caseRecord.protocol_case.provenance.kind.replaceAll("_", " ")}</strong>
                    </div>
                    <div>
                      <span>Case ID</span>
                      <strong>{shortId(caseRecord.case_id)}</strong>
                    </div>
                  </div>
                  <div className="gate-stack">
                    {gateRows(caseRecord).map((gate) => (
                      <div className={gate.passed ? "gate-row pass" : "gate-row fail"} key={gate.name}>
                        <span className="gate-icon">{gate.passed ? <Check size={14} /> : "!"}</span>
                        <span className="gate-copy">
                          <strong>{gate.name}</strong>
                          <small>{gate.detail}</small>
                        </span>
                        <span className="gate-result">{gate.passed ? gate.expected : "BLOCKED"}</span>
                      </div>
                    ))}
                  </div>
                </button>
              );
            })}
          </section>

          {selectedCase ? (
            <aside className="case-inspector">
              <div className="inspector-heading">
                <div>
                  <span>Selected Case</span>
                  <h2>{selectedCase.protocol_case.title}</h2>
                </div>
                <StatusTag status={selectedCase.validation.objective_gate_passed} label="Runnable" />
              </div>
              <section>
                <h3>
                  <Sparkles size={16} /> Why this Case exists
                </h3>
                <p>{selectedCase.protocol_case.goal.text}</p>
                <p className="inspector-note">{selectedCase.validation.details}</p>
              </section>
              <section>
                <h3>
                  <GitCompareArrows size={16} /> Provenance
                </h3>
                <dl className="inspector-list">
                  <div>
                    <dt>Kind</dt>
                    <dd>{selectedCase.protocol_case.provenance.kind.replaceAll("_", " ")}</dd>
                  </div>
                  <div>
                    <dt>Parent</dt>
                    <dd>{selectedCase.protocol_case.provenance.parent_case_id ? shortId(selectedCase.protocol_case.provenance.parent_case_id) : "Original source"}</dd>
                  </div>
                  <div>
                    <dt>Recipe</dt>
                    <dd>{selectedCase.protocol_case.provenance.transformation?.recipe ?? "None"}</dd>
                  </div>
                  <div>
                    <dt>Confirmed</dt>
                    <dd>{selectedCase.protocol_case.provenance.confirmed_by_user ? "Yes" : "No"}</dd>
                  </div>
                </dl>
              </section>
              <section>
                <h3>
                  <Shield size={16} /> Objective validators
                </h3>
                <div className="validator-list">
                  {selectedCase.protocol_case.validators.map((validator) => (
                    <div key={validator.validator_id}>
                      <span>{validator.name}</span>
                      <strong>{Math.round(validator.weight * 100)}%</strong>
                    </div>
                  ))}
                </div>
              </section>
              <section>
                <h3>
                  <FileCode2 size={16} /> Allowed paths
                </h3>
                <div className="path-chips">
                  {selectedCase.protocol_case.safety.writable_paths.map((path) => (
                    <code key={path}>{path}</code>
                  ))}
                </div>
                <p className="inspector-note">
                  Network: {selectedCase.protocol_case.safety.network}. Denied: {selectedCase.protocol_case.safety.denied_paths.join(", ")}.
                </p>
              </section>
            </aside>
          ) : null}
        </div>
      ) : null}

      {selectedCase ? (
        <section className="codex-visibility panel">
          <div className="visibility-title">
            <Eye size={19} />
            <div>
              <h2>What Codex sees</h2>
              <p>The task boundary is useful because the answer key stays outside it.</p>
            </div>
          </div>
          <div className="visibility-grid">
            <article className="allowed">
              <Check size={17} />
              <h3>Allowed task context</h3>
              <p>Fresh baseline workspace, task goal, confirmed writable paths, and local simulator tools.</p>
            </article>
            <article className="hidden">
              <Lock size={17} />
              <h3>Hidden solution</h3>
              <p>Correct commit, solution patch, repository history beyond the Case, and other Runs.</p>
            </article>
            <article className="hidden">
              <Shield size={17} />
              <h3>Hidden validators</h3>
              <p>Verifier implementation, expected artifacts, weights, and reference outputs.</p>
            </article>
            <article className="score">
              <RefreshCw size={17} />
              <h3>Independent scoring</h3>
              <p>Code, changed paths, and simulator state are checked only after the Agent attempt.</p>
            </article>
          </div>
          <div className="visibility-action">
            <Button onClick={onContinue}>
              <Play size={16} /> Run selected Case <ArrowRight size={15} />
            </Button>
          </div>
        </section>
      ) : null}
    </div>
  );
}
