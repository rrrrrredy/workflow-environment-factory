from __future__ import annotations

import fnmatch
import hashlib
import json
import threading
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from uuid import UUID, uuid4

from .content_store import ContentStore
from .engine import ExecutionEngine, ProcessResult
from .gitops import GitWorkspaceManager
from .models import AttemptOrigin, BlueprintKind, RunStatus
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
        self._score_locks_guard = threading.Lock()
        self._score_locks: dict[str, threading.Lock] = {}

    def score(self, run_id: UUID | str, *, allow_synthetic_fixture: bool = False) -> dict[str, Any]:
        key = str(run_id)
        with self._score_locks_guard:
            run_lock = self._score_locks.setdefault(key, threading.Lock())
        with run_lock:
            return self._score_locked(run_id, allow_synthetic_fixture=allow_synthetic_fixture)

    def _score_locked(self, run_id: UUID | str, *, allow_synthetic_fixture: bool) -> dict[str, Any]:
        existing = self.store.get_score_for_run(run_id)
        if existing is not None:
            return existing
        run = self.store.get_run(run_id)
        if run is None:
            raise KeyError("run not found")
        if run.status not in {RunStatus.COMPLETED, RunStatus.AGENT_CRASH, RunStatus.AGENT_TIMEOUT}:
            raise ValueError(f"run cannot be scored from status {run.status}")
        if not run.agent_attempted:
            raise ValueError("run has no retained evidence that the Codex runner started an attempt")
        if run.attempt_origin == AttemptOrigin.SYNTHETIC_FIXTURE and not allow_synthetic_fixture:
            raise ValueError("synthetic fixture Runs cannot be scored through the production scoring path")
        if run.attempt_origin not in {AttemptOrigin.CODEX_PROCESS, AttemptOrigin.SYNTHETIC_FIXTURE}:
            raise ValueError("run attempt origin is missing or ambiguous")
        attempt_note = (
            "Synthetic fixture evidence only; no model was executed."
            if run.attempt_origin == AttemptOrigin.SYNTHETIC_FIXTURE
            else "This record represents one Codex process attempt; model execution was not independently inferred."
        )
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
                    "notes": [f"{attempt_note} No task score was inferred from the interrupted run."],
                },
                "summary": "Agent execution ended before validation; the task was not scored.",
                "extensions": {
                    "workflow_environment_factory": {
                        "engine": self.engine.name,
                        "attempt_origin": run.attempt_origin.value,
                        "model_executed": run.model_executed,
                    }
                },
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

        pre_verifier_state: dict[str, str] | None = None
        try:
            pre_verifier_state = self._workspace_state(workspace)
        except Exception as error:
            execution_status = "validator_error"
            failure_stage = "validating"
            validation_rows.append(
                {
                    "validator_id": "verifier-workspace-integrity",
                    "status": "error",
                    "objective": False,
                    "required": True,
                    "duration_ms": 0,
                    "summary": str(redact(str(error))),
                    "evidence": [
                        {
                            "kind": "text",
                            "summary": "Pre-verifier workspace snapshot failed.",
                            "redacted": True,
                        }
                    ],
                }
            )

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

        if pre_verifier_state is not None:
            try:
                post_verifier_state = self._workspace_state(workspace)
                integrity_passed = post_verifier_state == pre_verifier_state
                if not integrity_passed:
                    execution_status = "validator_error"
                    failure_stage = "validating"
                validation_rows.append(
                    {
                        "validator_id": "verifier-workspace-integrity",
                        "status": "pass" if integrity_passed else "error",
                        "objective": False,
                        "required": True,
                        "duration_ms": 0,
                        "summary": "The verifier left the Agent workspace unchanged."
                        if integrity_passed
                        else "The verifier changed the Agent workspace; the task result is not scored.",
                        "evidence": [
                            {
                                "kind": "structured",
                                "summary": "Workspace state before and after verifier execution",
                                "data": {
                                    "before_paths": sorted(pre_verifier_state),
                                    "after_paths": sorted(post_verifier_state),
                                    "state_equal": integrity_passed,
                                },
                            }
                        ],
                    }
                )
                changed_paths = sorted(post_verifier_state)
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
                                "summary": f"{len(changed_paths)} changed path(s) after verifier execution",
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
                        "validator_id": "verifier-workspace-integrity",
                        "status": "error",
                        "objective": False,
                        "required": True,
                        "duration_ms": 0,
                        "summary": str(redact(str(error))),
                        "evidence": [
                            {
                                "kind": "text",
                                "summary": "Post-verifier workspace snapshot failed.",
                                "redacted": True,
                            }
                        ],
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
                "notes": [f"{attempt_note} This score covers one freshly reset Case."],
            },
            "summary": "Task passed every required objective validator."
            if task_result["status"] == "pass"
            else "Task did not pass every required objective validator.",
            "extensions": {
                "workflow_environment_factory": {
                    "engine": self.engine.name,
                    "attempt_origin": run.attempt_origin.value,
                    "model_executed": run.model_executed,
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

    def _workspace_state(self, workspace: Path) -> dict[str, str]:
        root = workspace.resolve()
        state: dict[str, str] = {}
        for relative in self.git.changed_paths(root, "HEAD"):
            normalized = relative.replace("\\", "/")
            path = PurePosixPath(normalized)
            if path.is_absolute() or ".." in path.parts or normalized in {"", "."}:
                raise RuntimeError(f"Git reported an unsafe changed path: {relative}")
            candidate = root.joinpath(*path.parts)
            if candidate.is_symlink():
                state[normalized] = f"symlink:{candidate.readlink()}"
            elif not candidate.exists():
                state[normalized] = "deleted"
            elif candidate.is_file():
                digest = hashlib.sha256()
                with candidate.open("rb") as handle:
                    for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                        digest.update(chunk)
                state[normalized] = f"sha256:{digest.hexdigest()}"
            else:
                state[normalized] = "non-file"
        return state

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
