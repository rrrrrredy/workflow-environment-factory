from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from pathlib import PurePosixPath
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def utc_now() -> datetime:
    return datetime.now(UTC)


class BlueprintKind(StrEnum):
    CODE = "code"
    ISSUE_PR = "issue_pr"


class CommandSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    argv: list[str] = Field(min_length=1, max_length=100)
    timeout_ms: int = Field(default=120_000, ge=1_000, le=900_000)

    @field_validator("argv")
    @classmethod
    def command_values_are_bounded(cls, value: list[str]) -> list[str]:
        if any(not item or len(item) > 10_000 for item in value):
            raise ValueError("verifier argv values must be non-empty and at most 10,000 characters")
        return value


class VariableSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(pattern=r"^[A-Za-z][A-Za-z0-9_.-]*$")
    original: str = Field(min_length=1, max_length=500)
    variants: list[str] = Field(min_length=2, max_length=2)
    paths: list[str] = Field(min_length=1, max_length=100)
    confirmed_by_user: bool
    description: str = Field(default="", max_length=2_000)

    @field_validator("variants")
    @classmethod
    def variants_are_distinct(cls, value: list[str]) -> list[str]:
        if len(set(value)) != 2:
            raise ValueError("exactly two distinct variant values are required")
        return value

    @field_validator("paths")
    @classmethod
    def paths_are_portable(cls, value: list[str]) -> list[str]:
        for item in value:
            normalized = item.replace("\\", "/")
            path = PurePosixPath(normalized)
            if path.is_absolute() or ".." in path.parts or normalized in {"", "."}:
                raise ValueError(f"variable path must be a safe repository-relative file: {item}")
        return value

    @model_validator(mode="after")
    def confirmation_and_values(self) -> VariableSpec:
        if not self.confirmed_by_user:
            raise ValueError("variables must be explicitly confirmed by the user")
        if self.original in self.variants:
            raise ValueError("variant values must differ from the original")
        return self


class IssueTemplate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=500)
    body: str = Field(min_length=1, max_length=10_000)
    initial_status: str = Field(default="open", min_length=1, max_length=100)
    target_status: str = Field(default="in_review", min_length=1, max_length=100)
    pr_target: str = Field(default="main", min_length=1, max_length=200)


class BlueprintCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)
    kind: BlueprintKind
    repository_path: str = Field(min_length=1)
    base_revision: str = Field(min_length=1, max_length=200)
    solution_revision: str = Field(min_length=1, max_length=200)
    title_template: str = Field(min_length=1, max_length=500)
    goal_template: str = Field(min_length=1, max_length=10_000)
    completion_summary: str = Field(min_length=1, max_length=5_000)
    external_ref: str | None = Field(default=None, max_length=500)
    variable: VariableSpec
    container_image: str = Field(pattern=r"^[^\s@]+@sha256:[0-9a-f]{64}$", max_length=500)
    verifier: CommandSpec
    allowed_paths: list[str] = Field(min_length=1, max_length=100)
    allowed_tools: list[str] = Field(default_factory=lambda: ["shell", "file", "git"], min_length=1, max_length=20)
    issue: IssueTemplate | None = None
    demonstration_id: UUID | None = None
    timeout_ms: int = Field(default=900_000, ge=10_000, le=3_600_000)

    @field_validator("allowed_paths")
    @classmethod
    def allowed_paths_are_portable(cls, value: list[str]) -> list[str]:
        for item in value:
            normalized = item.replace("\\", "/")
            path = PurePosixPath(normalized)
            if path.is_absolute() or ".." in path.parts or normalized in {"", "."}:
                raise ValueError(f"allowed path must be repository-relative: {item}")
        return value

    @model_validator(mode="after")
    def issue_fields_match_kind(self) -> BlueprintCreate:
        if self.kind == BlueprintKind.ISSUE_PR and (self.issue is None or self.demonstration_id is None):
            raise ValueError("Issue-to-PR blueprints require an issue template and confirmed demonstration")
        if self.kind == BlueprintKind.CODE and (self.issue is not None or self.demonstration_id is not None):
            raise ValueError("code blueprints cannot carry Issue-to-PR recording fields")
        return self


class BlueprintRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    blueprint_id: UUID = Field(default_factory=uuid4)
    payload: BlueprintCreate
    repository_root: str
    base_commit: str
    solution_commit: str
    solution_patch_digest: str
    created_at: datetime = Field(default_factory=utc_now)


class CaseValidation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    baseline_status: Literal["pass", "fail", "error", "timeout"]
    solution_status: Literal["pass", "fail", "error", "timeout"]
    baseline_exit_code: int | None
    solution_exit_code: int | None
    reset_verified: bool
    objective_gate_passed: bool
    details: str


class CaseRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    case_id: UUID
    blueprint_id: UUID
    variant_index: int = Field(ge=0, le=2)
    variable_value: str
    protocol_case: dict[str, Any]
    validation: CaseValidation
    created_at: datetime = Field(default_factory=utc_now)


class RunStatus(StrEnum):
    PREPARING = "preparing"
    READY = "ready"
    RUNNING = "running"
    VALIDATING = "validating"
    COMPLETED = "completed"
    AGENT_TIMEOUT = "agent_timeout"
    AGENT_CRASH = "agent_crash"
    RESET_ERROR = "reset_error"
    ENVIRONMENT_ERROR = "environment_error"


class RunRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: UUID = Field(default_factory=uuid4)
    case_id: UUID
    status: RunStatus
    workspace_path: str
    simulator_database_path: str | None = None
    codex_events: list[dict[str, Any]] = Field(default_factory=list)
    error: str = ""
    started_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None


class RecordingEvent(BaseModel):
    model_config = ConfigDict(extra="forbid")
    event_type: Literal["issue_read", "repository_changed", "pr_created", "issue_status_updated"]
    data: dict[str, Any]
    timestamp: datetime = Field(default_factory=utc_now)


class RecordingRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    recording_id: UUID = Field(default_factory=uuid4)
    name: str = Field(min_length=1, max_length=200)
    status: Literal["recording", "completed"] = "recording"
    events: list[RecordingEvent] = Field(default_factory=list)
    confirmed: bool = False
    created_at: datetime = Field(default_factory=utc_now)
    completed_at: datetime | None = None


class ProtocolDocumentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document_id: UUID = Field(default_factory=uuid4)
    schema_version: Literal["agent.run.v1", "workflow.case.v1", "workflow.score.v1"]
    external_id: str = Field(min_length=1, max_length=500)
    digest: str = Field(pattern=r"^sha256:[0-9a-f]{64}$")
    document: dict[str, Any]
    imported_at: datetime = Field(default_factory=utc_now)
