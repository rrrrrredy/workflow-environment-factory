from __future__ import annotations

import fnmatch
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from .content_store import ContentStore
from .engine import ExecutionEngine, ProcessResult
from .gitops import GitWorkspaceManager
from .models import BlueprintKind, RunStatus
from .protocol import ProtocolValidator
from .redaction import redact
from .simulator import IssuePrSimulator
from .store import FactoryStore


def _timestamp(value: datetime | None = None) -> str:
    return (value or datetime.now(UTC)).isoformat().replace("+00:00", "Z")


def _path_allowed(path: str, patterns: list[str]) -> bool:
    normalized = path.replace("\\", "/")
    for pattern in patterns:
        candidate = pattern.replace("\\", "/").rstrip("/")
        if normalized == candidate or normalized.startswith(f"{candidate}/") or fnmatch.fnmatch(normalized, candidate):
            return True
    return False


class ScoreService:
    def __init__(
        self,
        *,
        store: FactoryStore,
        content_store: ContentStore,
        protocol: ProtocolValidator,
        git: GitWorkspaceManager,
        engine: ExecutionEngine,
        simulator: IssuePrSimulator | None = None,
    ):
        self.store = store
        self.content_store = content_store
        self.protocol = protocol
        self.git = git
        self.engine = engine
        self.simulator = simulator or IssuePrSimulator()

    def score(self, run_id: UUID | str) -> dict[str, Any]:
        run = self.store.get_run(run_id)
        if run is None:
            raise KeyError("run not found")
        if run.status not in {RunStatus.READY, RunStatus.COMPLETED, RunStatus.AGENT_CRASH, RunStatus.AGENT_TIMEOUT}:
            raise ValueError(f"run cannot be scored from status {run.status}")
        case = self.store.get_case(run.case_id)
        if case is None:
            raise KeyError("case not found")
        blueprint = self.store.get_blueprint(case.blueprint_id)
        if blueprint is None:
            raise KeyError("blueprint not found")
        if run.status in {RunStatus.AGENT_CRASH, RunStatus.AGENT_TIMEOUT}:
            completed = run.completed_at or datetime.now(UTC)
            score: dict[str, Any] = {
                "schema_version": "workflow.score.v1",
                "score_id": str(uuid4()),
                "run_id": str(run.run_id),
                "case_id": str(case.case_id),
                "configuration_snapshot_id": self._configuration_snapshot_id(
                    str(blueprint.blueprint_id), str(case.case_id)
                ),
                "protocol_versions": {
                    "run": "agent.run.v1",
                    "case": "workflow.case.v1",
                    "score": "workflow.score.v1",
                },
                "created_at": _timestamp(completed),
                "execution": {
                    "status": run.status.value,
                    "started_at": _timestamp(run.started_at),
                    "ended_at": _timestamp(completed),
                    "failure_stage": "running",
                    "details": str(redact(run.error or "Agent execution did not complete.")),
                },
                "task_result": {
                    "status": "not_scored",
                    "reason": "Agent execution did not complete, so objective validators were not run.",
                },
                "validations": [],
                "trace_findings": [],
                "resource_usage": {
                    "duration_ms": max(0, int((completed - run.started_at).total_seconds() * 1_000)),
                    "validation_ms": 0,
                },
                "nondeterminism": {
                    "sample_count": 1,
                    "single_run_evidence": True,
                    "notes": ["This record represents one interrupted Codex attempt; no task score was inferred."],
                },
                "summary": "Agent execution ended before validation; the task was not scored.",
                "extensions": {"workflow_environment_factory": {"engine": self.engine.name}},
            }
            self.protocol.validate(score)
            run.completed_at = completed
            self.store.save_run(run)
            return self.store.save_score(score)
        started = datetime.now(UTC)
        run.status = RunStatus.VALIDATING
        self.store.save_run(run)
        workspace = Path(run.workspace_path)
        validation_rows: list[dict[str, Any]] = []
        execution_status = "completed"
        failure_stage: str | None = None

        verifier = self.engine.run(
            workspace,
            blueprint.payload.container_image,
            blueprint.payload.verifier.argv,
            blueprint.payload.verifier.timeout_ms,
        )
        if verifier.status in {"error", "timeout"}:
            execution_status = "validator_error"
            failure_stage = "validating"
        validation_rows.append(self._command_validation(verifier))

        try:
            changed_paths = self.git.changed_paths(workspace, blueprint.base_commit)
            paths_pass = bool(changed_paths) and all(
                _path_allowed(path, blueprint.payload.allowed_paths) for path in changed_paths
            )
            validation_rows.append(
                {
                    "validator_id": "allowed-paths",
                    "status": "pass" if paths_pass else "fail",
                    "objective": True,
                    "required": True,
                    "duration_ms": 0,
                    "summary": "All changed paths are in the confirmed scope."
                    if paths_pass
                    else "No change or at least one changed path is outside the confirmed scope.",
                    "evidence": [
                        {
                            "kind": "structured",
                            "summary": f"{len(changed_paths)} changed path(s)",
                            "data": {"changed_paths": changed_paths, "allowed": blueprint.payload.allowed_paths},
                        }
                    ],
                }
            )
        except Exception as error:
            execution_status = "validator_error"
            failure_stage = "validating"
            validation_rows.append(
                {
                    "validator_id": "allowed-paths",
                    "status": "error",
                    "objective": True,
                    "required": True,
                    "duration_ms": 0,
                    "summary": str(redact(str(error))),
                    "evidence": [{"kind": "text", "summary": "Git changed-path validation failed.", "redacted": True}],
                }
            )

        if blueprint.payload.kind == BlueprintKind.ISSUE_PR:
            assert blueprint.payload.issue is not None
            if run.simulator_database_path is None:
                execution_status = "validator_error"
                failure_stage = "validating"
                state_status = "error"
                state_details: dict[str, Any] = {"error": "simulator database is missing"}
            else:
                issue = blueprint.payload.issue
                state = self.simulator.validate(
                    Path(run.simulator_database_path),
                    issue_key=issue.key.replace("{value}", case.variable_value),
                    target_status=issue.target_status,
                    pr_target=issue.pr_target,
                )
                state_status = "pass" if state.passed else "fail"
                state_details = state.details
            validation_rows.append(
                {
                    "validator_id": "issue-pr-state",
                    "status": state_status,
                    "objective": True,
                    "required": True,
                    "duration_ms": 0,
                    "summary": "Simulator database reached the required Issue-to-PR state."
                    if state_status == "pass"
                    else "Simulator database does not satisfy the required Issue-to-PR state.",
                    "evidence": [
                        {
                            "kind": "structured",
                            "summary": "Issue and pull request database assertions",
                            "data": state_details,
                        }
                    ],
                }
            )

        completed = datetime.now(UTC)
        if execution_status == "completed":
            required_passed = all(row["status"] == "pass" for row in validation_rows if row["required"])
            task_status = "pass" if required_passed else "fail"
            task_score = self._weighted_score(case.protocol_case, validation_rows)
            task_result: dict[str, Any] = {
                "status": task_status,
                "score": task_score,
                "reason": "All required objective validators passed."
                if required_passed
                else "At least one required validator failed.",
            }
        else:
            task_result = {"status": "not_scored", "reason": "Validation infrastructure did not complete."}

        score: dict[str, Any] = {
            "schema_version": "workflow.score.v1",
            "score_id": str(uuid4()),
            "run_id": str(run.run_id),
            "case_id": str(case.case_id),
            "configuration_snapshot_id": self._configuration_snapshot_id(
                str(blueprint.blueprint_id), str(case.case_id)
            ),
            "protocol_versions": {"run": "agent.run.v1", "case": "workflow.case.v1", "score": "workflow.score.v1"},
            "created_at": _timestamp(completed),
            "execution": {
                "status": execution_status,
                "started_at": _timestamp(run.started_at),
                "ended_at": _timestamp(completed),
                **({"failure_stage": failure_stage} if failure_stage else {}),
            },
            "task_result": task_result,
            "validations": validation_rows,
            "trace_findings": [],
            "resource_usage": {
                "duration_ms": max(0, int((completed - run.started_at).total_seconds() * 1_000)),
                "validation_ms": max(0, int((completed - started).total_seconds() * 1_000)),
            },
            "nondeterminism": {
                "sample_count": 1,
                "single_run_evidence": True,
                "notes": ["This score represents one Codex attempt on one freshly reset Case."],
            },
            "summary": "Task passed every required objective validator."
            if task_result["status"] == "pass"
            else "Task did not pass every required objective validator.",
            "extensions": {
                "workflow_environment_factory": {
                    "engine": self.engine.name,
                    "verifier_output_ref": self.content_store.put_json(
                        redact({"stdout": verifier.stdout, "stderr": verifier.stderr, "exit_code": verifier.exit_code})
                    ),
                }
            },
        }
        self.protocol.validate(score)
        run.status = RunStatus.COMPLETED if execution_status == "completed" else RunStatus.ENVIRONMENT_ERROR
        run.completed_at = completed
        self.store.save_run(run)
        return self.store.save_score(score)

    @staticmethod
    def _command_validation(result: ProcessResult) -> dict[str, Any]:
        status = "pass" if result.status == "pass" else "fail" if result.status == "fail" else "error"
        return {
            "validator_id": "code-verifier",
            "status": status,
            "objective": True,
            "required": True,
            "duration_ms": result.duration_ms,
            "summary": f"Objective verifier {result.status}"
            + ("." if result.exit_code is None else f" with exit code {result.exit_code}."),
            "evidence": [
                {
                    "kind": "structured",
                    "summary": "Verifier process result",
                    "data": {"status": result.status, "exit_code": result.exit_code},
                }
            ],
        }

    @staticmethod
    def _weighted_score(protocol_case: dict[str, Any], results: list[dict[str, Any]]) -> float:
        weights = {validator["validator_id"]: validator["weight"] for validator in protocol_case["validators"]}
        earned = sum(weights.get(row["validator_id"], 0) for row in results if row["status"] == "pass")
        total = sum(weights.values()) or 1
        return round(min(1.0, earned / total), 4)

    def _configuration_snapshot_id(self, blueprint_id: str, case_id: str) -> str:
        payload = json.dumps(
            {"blueprint": blueprint_id, "case": case_id, "engine": self.engine.name},
            sort_keys=True,
        ).encode("utf-8")
        return f"cfg:{hashlib.sha256(payload).hexdigest()}"
