from __future__ import annotations

import hashlib
import json
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

from .content_store import ContentStore
from .engine import ExecutionEngine, ProcessResult
from .gitops import GitWorkspaceManager
from .models import (
    BlueprintCreate,
    BlueprintKind,
    BlueprintRecord,
    CaseRecord,
    CaseValidation,
    RunRecord,
    RunStatus,
)
from .protocol import ProtocolValidator
from .simulator import IssuePrSimulator
from .store import FactoryStore


def _timestamp() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _sha256_json(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return f"sha256:{hashlib.sha256(payload).hexdigest()}"


class CaseFactory:
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

    def create_blueprint(self, payload: BlueprintCreate) -> BlueprintRecord:
        if payload.kind == BlueprintKind.ISSUE_PR:
            recording = self.store.get_recording(payload.demonstration_id)  # type: ignore[arg-type]
            if recording is None or recording.status != "completed" or not recording.confirmed:
                raise ValueError("Issue-to-PR blueprint requires a completed, user-confirmed recording")
            event_types = {event.event_type for event in recording.events}
            required = {"issue_read", "repository_changed", "pr_created", "issue_status_updated"}
            if not required.issubset(event_types):
                raise ValueError(f"recording is missing required workflow evidence: {sorted(required - event_types)}")
        root, base, solution, patch_digest = self.git.inspect_repository(
            payload.repository_path,
            payload.base_revision,
            payload.solution_revision,
        )
        record = BlueprintRecord(
            payload=payload,
            repository_root=str(root),
            base_commit=base,
            solution_commit=solution,
            solution_patch_digest=patch_digest,
        )
        return self.store.save_blueprint(record)

    def generate_cases(self, blueprint_id: UUID | str) -> list[CaseRecord]:
        blueprint = self.store.get_blueprint(blueprint_id)
        if blueprint is None:
            raise KeyError("blueprint not found")
        existing = self.store.list_cases(blueprint.blueprint_id)
        if existing:
            return existing
        values = [blueprint.payload.variable.original, *blueprint.payload.variable.variants]
        case_ids = [uuid4(), uuid4(), uuid4()]
        cases: list[CaseRecord] = []
        for index, value in enumerate(values):
            protocol_case = self._protocol_case(blueprint, case_ids, index, value)
            self.protocol.validate(protocol_case)
            validation = self._validate_case(blueprint, case_ids[index], index, value)
            cases.append(
                CaseRecord(
                    case_id=case_ids[index],
                    blueprint_id=blueprint.blueprint_id,
                    variant_index=index,
                    variable_value=value,
                    protocol_case=protocol_case,
                    validation=validation,
                )
            )
        return self.store.save_cases(cases)

    def _protocol_case(
        self,
        blueprint: BlueprintRecord,
        case_ids: list[UUID],
        index: int,
        value: str,
    ) -> dict[str, Any]:
        payload = blueprint.payload
        repository_urn = f"urn:local-repository:{hashlib.sha256(blueprint.repository_root.encode('utf-8')).hexdigest()}"
        title = payload.title_template.replace("{value}", value)
        goal = payload.goal_template.replace("{value}", value)
        environment_basis = {
            "image": payload.container_image,
            "base": blueprint.base_commit,
            "solution_patch": blueprint.solution_patch_digest,
            "variable": payload.variable.name,
            "value": value,
            "kind": payload.kind.value,
        }
        allowed_tools = [
            {
                "name": tool,
                "interface": "mcp"
                if tool == "simulator-mcp"
                else tool
                if tool in {"shell", "file", "git", "browser"}
                else "other",
                "scopes": ["workspace"]
                if tool != "simulator-mcp"
                else ["issues:read", "issues:update", "pull_requests:create"],
            }
            for tool in payload.allowed_tools
        ]
        if payload.kind == BlueprintKind.ISSUE_PR and not any(
            tool["name"] == "simulator-mcp" for tool in allowed_tools
        ):
            allowed_tools.append(
                {
                    "name": "simulator-mcp",
                    "interface": "mcp",
                    "scopes": ["issues:read", "issues:update", "pull_requests:create"],
                }
            )
        validators = [
            {
                "validator_id": "code-verifier",
                "name": "Repository objective verifier",
                "kind": "test",
                "objective": True,
                "required": True,
                "weight": 0.8 if payload.kind == BlueprintKind.CODE else 0.5,
                "executor_ref": f"{self.engine.name}.command.v1",
                "assertion": {"argv": payload.verifier.argv, "exit_code": 0},
                "timeout_ms": payload.verifier.timeout_ms,
                "evidence_policy": "structured",
            },
            {
                "validator_id": "allowed-paths",
                "name": "Changed paths stay inside the confirmed scope",
                "kind": "git",
                "objective": True,
                "required": True,
                "weight": 0.2,
                "executor_ref": "git.changed-paths.v1",
                "assertion": {"allow": payload.allowed_paths},
                "timeout_ms": 5_000,
                "evidence_policy": "structured",
            },
        ]
        if payload.kind == BlueprintKind.ISSUE_PR:
            assert payload.issue is not None
            validators[0]["weight"] = 0.4
            validators[1]["weight"] = 0.2
            validators.append(
                {
                    "validator_id": "issue-pr-state",
                    "name": "Issue status and linked pull request state",
                    "kind": "database",
                    "objective": True,
                    "required": True,
                    "weight": 0.4,
                    "executor_ref": "wef.simulator.issue-pr-state.v1",
                    "assertion": {
                        "issue": payload.issue.key.replace("{value}", value),
                        "status": payload.issue.target_status,
                        "linked_pr": True,
                        "pr_target": payload.issue.pr_target,
                    },
                    "timeout_ms": 5_000,
                    "evidence_policy": "structured",
                }
            )
        captured_at = blueprint.created_at.isoformat().replace("+00:00", "Z")
        source_refs: list[dict[str, Any]] = [
            {"kind": "repository", "ref": repository_urn, "captured_at": captured_at},
            {"kind": "commit", "ref": blueprint.base_commit},
            {"kind": "commit", "ref": blueprint.solution_commit},
        ]
        if payload.external_ref:
            source_refs.append({"kind": "issue", "ref": payload.external_ref.replace("{value}", value)})
        provenance: dict[str, Any]
        if index == 0:
            if payload.kind == BlueprintKind.ISSUE_PR:
                source_refs.append({"kind": "demonstration", "ref": str(payload.demonstration_id)})
                provenance = {
                    "kind": "recorded_workflow",
                    "source_refs": source_refs,
                    "confirmed_by_user": True,
                    "notes": "The correct commit is validation evidence and is never mounted into Agent runs.",
                }
            else:
                provenance = {
                    "kind": "repository_commit",
                    "source_refs": source_refs,
                    "confirmed_by_user": True,
                    "notes": "The correct commit is validation evidence and is never mounted into Agent runs.",
                }
        else:
            transformation = {
                "recipe": "confirmed-text-substitution.v1",
                "parameters": {
                    "variable": payload.variable.name,
                    "from": payload.variable.original,
                    "to": value,
                    "paths": payload.variable.paths,
                },
                "patch_ref": self.content_store.put_json(
                    {"blueprint_id": str(blueprint.blueprint_id), "variant_index": index, "value": value}
                ),
                "notes": "The same confirmed substitution is applied independently to the baseline and correct states.",
            }
            provenance = {
                "kind": "derived_variant",
                "source_refs": [{"kind": "case", "ref": str(case_ids[0])}, *source_refs],
                "parent_case_id": str(case_ids[0]),
                "transformation": transformation,
                "confirmed_by_user": True,
            }
        document: dict[str, Any] = {
            "schema_version": "workflow.case.v1",
            "case_id": str(case_ids[index]),
            "title": title,
            "description": "A user-confirmed repository task generated and gated by Workflow Environment Factory.",
            "goal": {
                "text": goal,
                "completion_summary": payload.completion_summary.replace("{value}", value),
                **({"external_ref": payload.external_ref.replace("{value}", value)} if payload.external_ref else {}),
            },
            "variables": [
                {
                    "name": payload.variable.name,
                    "value": value,
                    "value_type": "string",
                    "source": f"confirmed paths: {', '.join(payload.variable.paths)}",
                    "confirmed_by_user": True,
                    "sensitive": False,
                    "description": payload.variable.description,
                }
            ],
            "environment": {
                "kind": "code" if payload.kind == BlueprintKind.CODE else "hybrid",
                "summary": f"Fresh Git worktree validated in container image {payload.container_image}"
                + (" with a fresh local Issue/PR SQLite snapshot" if payload.kind == BlueprintKind.ISSUE_PR else ""),
                "build_ref": f"container-image:{payload.container_image}",
                "digest": _sha256_json(environment_basis),
                "repository": {"source_ref": repository_urn, "base_revision": blueprint.base_commit},
                "initialize": [
                    {
                        "step_id": "create-worktree",
                        "kind": "snapshot",
                        "executor_ref": "git.worktree.add.v1",
                        "parameters": {"revision": blueprint.base_commit},
                        "timeout_ms": 120_000,
                    }
                ],
                "reset": [
                    {
                        "step_id": "fresh-worktree",
                        "kind": "snapshot",
                        "executor_ref": "git.worktree.add.v1",
                        "parameters": {"revision": blueprint.base_commit, "variant_index": index},
                        "timeout_ms": 120_000,
                    }
                ],
                "health_checks": [
                    {
                        "step_id": "container-engine-ready",
                        "kind": "container",
                        "executor_ref": f"{self.engine.name}.health.v1",
                        "parameters": {"image": payload.container_image},
                        "timeout_ms": 30_000,
                    }
                ],
                "state_refs": [blueprint.solution_patch_digest],
            },
            "allowed_tools": allowed_tools,
            "validators": validators,
            "provenance": provenance,
            "safety": {
                "network": "allowlist" if payload.kind == BlueprintKind.ISSUE_PR else "disabled",
                **({"network_allowlist": ["127.0.0.1:43121"]} if payload.kind == BlueprintKind.ISSUE_PR else {}),
                "writable_paths": payload.allowed_paths,
                "denied_paths": [".git/config", ".env", "simulator-data", "validators"],
                "secret_refs": [],
                "timeout_ms": payload.timeout_ms,
                "resource_limits": {"cpu_count": 2, "memory_mb": 3_072, "disk_mb": 6_144, "process_count": 128},
            },
            "created_at": captured_at,
            "labels": [
                payload.kind.value.replace("_", "-"),
                "generated",
                "base-case" if index == 0 else "derived-variant",
            ],
            "extensions": {
                "workflow_environment_factory": {
                    "blueprint_id": str(blueprint.blueprint_id),
                    "variant_index": index,
                    "engine_required": "docker",
                }
            },
        }
        if payload.kind == BlueprintKind.ISSUE_PR:
            document["environment"]["start_urls"] = ["http://127.0.0.1:43121/simulator"]
        return document

    def _validate_case(self, blueprint: BlueprintRecord, case_id: UUID, index: int, value: str) -> CaseValidation:
        repository = Path(blueprint.repository_root)
        payload = blueprint.payload
        baseline_path: Path | None = None
        reset_path: Path | None = None
        solution_path: Path | None = None
        baseline_result = ProcessResult("error", None, "", "not run", 0)
        solution_result = ProcessResult("error", None, "", "not run", 0)
        reset_verified = False
        issue_state_verified = blueprint.payload.kind != BlueprintKind.ISSUE_PR
        gate_error = ""
        cleanup_errors: list[str] = []
        try:
            baseline_path, _ = self.git.materialize(
                repository,
                blueprint.base_commit,
                case_id,
                f"case-{index}-baseline-a",
                payload.variable.original,
                value,
                payload.variable.paths,
            )
            first_digest = self._workspace_state_digest(baseline_path)
            self.git.remove(repository, baseline_path)
            baseline_path = None
            reset_path, _ = self.git.materialize(
                repository,
                blueprint.base_commit,
                case_id,
                f"case-{index}-baseline-b",
                payload.variable.original,
                value,
                payload.variable.paths,
            )
            second_digest = self._workspace_state_digest(reset_path)
            reset_verified = first_digest == second_digest
            baseline_result = self.engine.run(
                reset_path,
                payload.container_image,
                payload.verifier.argv,
                payload.verifier.timeout_ms,
            )
            self.git.remove(repository, reset_path)
            reset_path = None
            solution_path, _ = self.git.materialize(
                repository,
                blueprint.solution_commit,
                case_id,
                f"case-{index}-solution",
                payload.variable.original,
                value,
                payload.variable.paths,
            )
            solution_result = self.engine.run(
                solution_path,
                payload.container_image,
                payload.verifier.argv,
                payload.verifier.timeout_ms,
            )
            if payload.kind == BlueprintKind.ISSUE_PR:
                issue_state_verified = self._validate_issue_state_gate(blueprint, case_id, value)
        except Exception as error:  # Infrastructure errors are evidence gaps, never task failures.
            gate_error = f"case gate infrastructure error: {error}"
        finally:
            for path in (baseline_path, reset_path, solution_path):
                if path is not None:
                    try:
                        self.git.remove(repository, path)
                    except Exception as error:
                        cleanup_errors.append(str(error))
        if cleanup_errors:
            reset_verified = False
            gate_error = f"case gate cleanup error: {'; '.join(cleanup_errors)}"
        passed = (
            not gate_error
            and baseline_result.status == "fail"
            and solution_result.status == "pass"
            and reset_verified
            and issue_state_verified
        )
        success_details = "Baseline failed, correct state passed, and two fresh resets matched."
        if payload.kind == BlueprintKind.ISSUE_PR:
            success_details += " Fresh simulator baseline failed and the programmatic correct Issue/PR state passed."
        return CaseValidation(
            baseline_status=baseline_result.status,  # type: ignore[arg-type]
            solution_status=solution_result.status,  # type: ignore[arg-type]
            baseline_exit_code=baseline_result.exit_code,
            solution_exit_code=solution_result.exit_code,
            reset_verified=reset_verified,
            objective_gate_passed=passed,
            details=(
                success_details
                if passed
                else gate_error
                or (
                    "A valid Case requires baseline=fail, solution=pass, deterministic reset evidence, "
                    "and objective state checks."
                )
            ),
        )

    def _validate_issue_state_gate(self, blueprint: BlueprintRecord, case_id: UUID, value: str) -> bool:
        issue = blueprint.payload.issue
        if issue is None:
            raise ValueError("Issue-to-PR Case is missing its confirmed Issue template")
        simulator_root = (self.git.worktrees_root.parent / "simulators").resolve()
        gate_dir = (simulator_root / "case-gates" / str(case_id)).resolve()
        if simulator_root not in gate_dir.parents:
            raise ValueError("simulator gate directory escaped the product data root")
        gate_dir.mkdir(parents=True, exist_ok=False)
        baseline_database = gate_dir / "baseline.sqlite3"
        correct_database = gate_dir / "correct.sqlite3"
        issue_key = issue.key.replace("{value}", value)
        try:
            for database in (baseline_database, correct_database):
                self.simulator.initialize(
                    database,
                    key=issue_key,
                    title=issue.title.replace("{value}", value),
                    body=issue.body.replace("{value}", value),
                    status=issue.initial_status,
                    pr_target=issue.pr_target,
                )
            baseline_state = self.simulator.get_issue(baseline_database, issue_key, record=False)
            correct_initial_state = self.simulator.get_issue(correct_database, issue_key, record=False)
            reset_matches = baseline_state == correct_initial_state
            baseline = self.simulator.validate(
                baseline_database,
                issue_key=issue_key,
                target_status=issue.target_status,
                pr_target=issue.pr_target,
            )
            self.simulator.create_pr(
                correct_database,
                title=f"Validated fix for {issue_key}",
                branch=f"wef-gate/{case_id}",
                target=issue.pr_target,
                linked_issue_key=issue_key,
            )
            self.simulator.update_issue_status(correct_database, issue_key, issue.target_status)
            correct = self.simulator.validate(
                correct_database,
                issue_key=issue_key,
                target_status=issue.target_status,
                pr_target=issue.pr_target,
            )
            return reset_matches and not baseline.passed and correct.passed
        finally:
            cleanup_errors: list[str] = []
            for database in (baseline_database, correct_database):
                if database.exists():
                    try:
                        database.unlink()
                    except OSError as error:
                        cleanup_errors.append(str(error))
            try:
                gate_dir.rmdir()
            except OSError as error:
                cleanup_errors.append(str(error))
            if cleanup_errors:
                raise RuntimeError(f"simulator gate cleanup failed: {'; '.join(cleanup_errors)}")

    def _workspace_state_digest(self, workspace: Path) -> str:
        diff = self.git.run(workspace, ["diff", "--binary", "HEAD"])
        if diff.exit_code != 0:
            raise RuntimeError(f"could not fingerprint reset state: {diff.stderr.strip()}")
        untracked = self.git.run(workspace, ["ls-files", "--others", "--exclude-standard"])
        if untracked.exit_code != 0:
            raise RuntimeError(f"could not list reset state: {untracked.stderr.strip()}")
        hasher = hashlib.sha256()
        hasher.update(diff.stdout.encode("utf-8"))
        for relative in sorted(line for line in untracked.stdout.splitlines() if line):
            target = (workspace / relative).resolve()
            if workspace.resolve() not in target.parents or not target.is_file():
                raise ValueError("untracked reset artifact escaped the workspace")
            hasher.update(relative.encode("utf-8"))
            hasher.update(target.read_bytes())
        return f"sha256:{hasher.hexdigest()}"

    def prepare_run(self, case_id: UUID | str) -> RunRecord:
        case = self.store.get_case(case_id)
        if case is None:
            raise KeyError("case not found")
        if not case.validation.objective_gate_passed:
            raise ValueError("case did not pass the baseline/solution/reset gate")
        blueprint = self.store.get_blueprint(case.blueprint_id)
        if blueprint is None:
            raise KeyError("blueprint not found")
        run = RunRecord(case_id=case.case_id, status=RunStatus.PREPARING, workspace_path="")
        workspace: Path | None = None
        database_path: Path | None = None
        try:
            workspace, _ = self.git.materialize(
                Path(blueprint.repository_root),
                blueprint.base_commit,
                run.run_id,
                "agent-workspace",
                blueprint.payload.variable.original,
                case.variable_value,
                blueprint.payload.variable.paths,
            )
            run.workspace_path = str(workspace)
            if blueprint.payload.kind == BlueprintKind.ISSUE_PR:
                assert blueprint.payload.issue is not None
                database_path = self.git.worktrees_root.parent / "simulators" / str(run.run_id) / "simulator.sqlite3"
                issue = blueprint.payload.issue
                self.simulator.initialize(
                    database_path,
                    key=issue.key.replace("{value}", case.variable_value),
                    title=issue.title.replace("{value}", case.variable_value),
                    body=issue.body.replace("{value}", case.variable_value),
                    status=issue.initial_status,
                    pr_target=issue.pr_target,
                )
                run.simulator_database_path = str(database_path)
            run.status = RunStatus.READY
            return self.store.save_run(run)
        except Exception as error:
            cleanup_errors: list[str] = []
            if workspace is not None:
                try:
                    self.git.remove(Path(blueprint.repository_root), workspace)
                except Exception as cleanup_error:
                    cleanup_errors.append(str(cleanup_error))
            if database_path is not None:
                try:
                    self._remove_simulator_snapshot(database_path)
                except Exception as cleanup_error:
                    cleanup_errors.append(str(cleanup_error))
            run.status = RunStatus.RESET_ERROR
            run.error = str(error) + (f" Cleanup also failed: {'; '.join(cleanup_errors)}" if cleanup_errors else "")
            return self.store.save_run(run)

    def cleanup_run(self, run_id: UUID | str) -> None:
        run = self.store.get_run(run_id)
        if run is None:
            return
        case = self.store.get_case(run.case_id)
        blueprint = None if case is None else self.store.get_blueprint(case.blueprint_id)
        if blueprint is None:
            raise KeyError("run blueprint not found")
        cleanup_errors: list[str] = []
        if run.workspace_path:
            try:
                self.git.remove(Path(blueprint.repository_root), Path(run.workspace_path))
            except Exception as error:
                cleanup_errors.append(str(error))
        if run.simulator_database_path:
            try:
                self._remove_simulator_snapshot(Path(run.simulator_database_path))
            except Exception as error:
                cleanup_errors.append(str(error))
        if cleanup_errors:
            raise RuntimeError(f"Run cleanup failed: {'; '.join(cleanup_errors)}")

    def _remove_simulator_snapshot(self, database_path: Path) -> None:
        simulator_root = (self.git.worktrees_root.parent / "simulators").resolve()
        resolved = database_path.resolve()
        if simulator_root not in resolved.parents:
            raise ValueError("refusing to remove a simulator snapshot outside the product data directory")
        for target in (resolved, Path(f"{resolved}-wal"), Path(f"{resolved}-shm")):
            if target.exists():
                target.unlink()
        parent = resolved.parent
        if parent != simulator_root and simulator_root in parent.parents:
            with suppress(OSError):
                parent.rmdir()
