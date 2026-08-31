from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path
from typing import Any
from uuid import UUID

from fastapi import BackgroundTasks, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field

from .auth import load_or_create_token, token_matches
from .engine import DockerEngine
from .models import BlueprintCreate, ProtocolDocumentRecord, RecordingEvent, RunStatus
from .redaction import redact
from .services import Services


class RecordingStart(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=200)


class RecordingComplete(BaseModel):
    model_config = ConfigDict(extra="forbid")
    confirmed: bool


class PullRequestCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    title: str = Field(min_length=1, max_length=500)
    branch: str = Field(min_length=1, max_length=200)
    target: str = Field(min_length=1, max_length=200)
    linked_issue_key: str = Field(min_length=1, max_length=100)


class StatusUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    status: str = Field(min_length=1, max_length=100)


class ProtocolImport(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document: dict[str, Any]


def _bearer(value: str | None) -> str | None:
    if value is None or not value.lower().startswith("bearer "):
        return None
    return value[7:].strip()


def _agent_case_view(case: Any) -> dict[str, Any]:
    document = case.protocol_case
    environment = document["environment"]
    return {
        "case_id": str(case.case_id),
        "title": document["title"],
        "goal": document["goal"],
        "variables": document["variables"],
        "environment": {
            "kind": environment["kind"],
            "summary": environment["summary"],
            **({"start_urls": environment["start_urls"]} if "start_urls" in environment else {}),
        },
        "allowed_tools": document["allowed_tools"],
        "validators": [
            {
                "validator_id": validator["validator_id"],
                "kind": validator["kind"],
                "objective": validator["objective"],
                "required": validator["required"],
            }
            for validator in document["validators"]
        ],
        "safety": document["safety"],
        "single_run_evidence": True,
    }


def create_app(services: Services) -> FastAPI:
    app = FastAPI(title="Workflow Environment Factory", version="0.2.0", docs_url=None, redoc_url=None)
    session_token = load_or_create_token(services.settings.token_path)

    @app.middleware("http")
    async def local_auth(request: Request, call_next: Any) -> Response:
        content_length = request.headers.get("content-length")
        if content_length and content_length.isdigit() and int(content_length) > 5 * 1024 * 1024:
            return Response(content='{"error":"request_too_large"}', status_code=413, media_type="application/json")
        if request.url.path.startswith("/api/"):
            authorization = request.headers.get("authorization")
            cookie = request.cookies.get("wef_session")
            if not token_matches(session_token, _bearer(authorization) or cookie):
                return Response(
                    content='{"error":"authentication_required"}', status_code=401, media_type="application/json"
                )
        return await call_next(request)

    @app.get("/health")
    async def health() -> dict[str, Any]:
        return {"ok": True, "product": "workflow-environment-factory", "version": "0.2.0"}

    @app.get("/session/{token}")
    async def establish_session(token: str) -> RedirectResponse:
        if not token_matches(session_token, token):
            raise HTTPException(status_code=404, detail="not found")
        response = RedirectResponse("/", status_code=302)
        response.set_cookie(
            "wef_session",
            session_token,
            httponly=True,
            samesite="strict",
            secure=False,
            max_age=12 * 60 * 60,
        )
        return response

    @app.get("/api/meta")
    async def meta() -> dict[str, Any]:
        docker = services.engine.availability() if isinstance(services.engine, DockerEngine) else None
        return {
            "product": "Workflow Environment Factory",
            "version": "0.2.0",
            "engine": services.engine.name,
            "docker_available": None if docker is None else docker.status == "pass",
            "docker_details": None if docker is None else docker.stderr or docker.stdout,
            "protocol_schema_dir": str(services.settings.protocol_schema_dir),
            "data_dir": str(services.settings.data_dir),
            "gate": "A Case is runnable only when baseline fails, the correct state passes, and two resets match.",
        }

    @app.get("/api/recordings")
    async def recordings() -> dict[str, Any]:
        return {"recordings": services.store.list_recordings()}

    @app.post("/api/recordings", status_code=201)
    async def start_recording(body: RecordingStart) -> Any:
        return services.recordings.start(body.name)

    @app.get("/api/recordings/{recording_id}")
    async def get_recording(recording_id: UUID) -> Any:
        recording = services.store.get_recording(recording_id)
        if recording is None:
            raise HTTPException(404, "recording not found")
        return recording

    @app.post("/api/recordings/{recording_id}/events")
    async def append_recording(recording_id: UUID, event: RecordingEvent) -> Any:
        try:
            return services.recordings.append(recording_id, event)
        except (KeyError, ValueError) as error:
            raise HTTPException(409, str(error)) from error

    @app.post("/api/recordings/{recording_id}/complete")
    async def complete_recording(recording_id: UUID, body: RecordingComplete) -> Any:
        try:
            return services.recordings.complete(recording_id, confirmed=body.confirmed)
        except (KeyError, ValueError) as error:
            raise HTTPException(409, str(error)) from error

    @app.get("/api/recordings/{recording_id}/extraction")
    async def extract_recording(recording_id: UUID) -> Any:
        try:
            return services.recordings.extract(recording_id)
        except KeyError as error:
            raise HTTPException(404, str(error)) from error

    @app.get("/api/blueprints")
    async def blueprints() -> dict[str, Any]:
        return {"blueprints": services.store.list_blueprints()}

    @app.post("/api/blueprints", status_code=201)
    async def create_blueprint(body: BlueprintCreate) -> Any:
        try:
            return services.factory.create_blueprint(body)
        except (KeyError, ValueError) as error:
            raise HTTPException(409, str(error)) from error

    @app.post("/api/blueprints/{blueprint_id}/generate", status_code=201)
    async def generate_cases(blueprint_id: UUID) -> Any:
        try:
            cases = services.factory.generate_cases(blueprint_id)
            return {"cases": cases, "all_gates_passed": all(case.validation.objective_gate_passed for case in cases)}
        except (KeyError, ValueError, RuntimeError) as error:
            raise HTTPException(409, str(error)) from error

    @app.get("/api/blueprints/{blueprint_id}/export")
    async def export_task_pack(blueprint_id: UUID) -> Any:
        blueprint = services.store.get_blueprint(blueprint_id)
        if blueprint is None:
            raise HTTPException(404, "blueprint not found")
        cases = services.store.list_cases(blueprint_id)
        if len(cases) != 3 or not all(case.validation.objective_gate_passed for case in cases):
            raise HTTPException(409, "task pack requires exactly three Cases that passed every generation gate")
        for case in cases:
            services.protocol.validate(case.protocol_case)
        return {
            "format": "wef.task-pack.v1",
            "blueprint_id": str(blueprint.blueprint_id),
            "name": blueprint.payload.name,
            "created_at": blueprint.created_at.isoformat().replace("+00:00", "Z"),
            "case_count": len(cases),
            "cases": [case.protocol_case for case in cases],
            "evidence_boundary": (
                "Each Case passed baseline=fail, correct=pass, and deterministic reset checks. "
                "These are generation gates, not evidence of general Agent quality."
            ),
        }

    @app.get("/api/cases")
    async def cases(blueprint_id: UUID | None = None) -> dict[str, Any]:
        return {"cases": services.store.list_cases(blueprint_id)}

    @app.get("/api/cases/{case_id}")
    async def get_case(case_id: UUID) -> Any:
        case = services.store.get_case(case_id)
        if case is None:
            raise HTTPException(404, "case not found")
        return case

    @app.get("/api/agent/cases/{case_id}")
    async def get_agent_case(case_id: UUID) -> Any:
        case = services.store.get_case(case_id)
        if case is None:
            raise HTTPException(404, "case not found")
        return _agent_case_view(case)

    @app.get("/api/cases/{case_id}/export")
    async def export_case(case_id: UUID) -> Any:
        case = services.store.get_case(case_id)
        if case is None:
            raise HTTPException(404, "case not found")
        services.protocol.validate(case.protocol_case)
        return case.protocol_case

    @app.get("/api/runs/{run_id}/score/export")
    async def export_score(run_id: UUID) -> Any:
        score = services.store.get_score_for_run(run_id)
        if score is None:
            raise HTTPException(404, "score not found")
        services.protocol.validate(score)
        return score

    @app.get("/api/protocol/imports")
    async def protocol_imports() -> dict[str, Any]:
        return {"documents": services.store.list_protocol_documents()}

    @app.get("/api/protocol/imports/{document_id}")
    async def get_protocol_import(document_id: UUID) -> Any:
        record = services.store.get_protocol_document(document_id)
        if record is None:
            raise HTTPException(404, "imported protocol document not found")
        return record

    @app.post("/api/protocol/imports", status_code=201)
    async def import_protocol(body: ProtocolImport) -> Any:
        try:
            services.protocol.validate(body.document)
            sanitized = redact(body.document)
            services.protocol.validate(sanitized)
        except (ValueError, TypeError) as error:
            schema_version = body.document.get("schema_version")
            label = schema_version if isinstance(schema_version, str) else "a RunCase Interchange schema"
            raise HTTPException(422, f"The file does not conform to {label}.\n{error}") from error
        schema_version = sanitized["schema_version"]
        id_fields = {
            "agent.run.v1": "run_id",
            "workflow.case.v1": "case_id",
            "workflow.score.v1": "score_id",
        }
        external_id = sanitized.get(id_fields[schema_version])
        if not isinstance(external_id, str) or not external_id:
            raise HTTPException(422, "protocol document is missing its external identifier")
        canonical = json.dumps(sanitized, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
        record = ProtocolDocumentRecord(
            schema_version=schema_version,
            external_id=external_id,
            digest=f"sha256:{hashlib.sha256(canonical).hexdigest()}",
            document=sanitized,
        )
        return services.store.save_protocol_document(record)

    @app.get("/api/runs")
    async def runs() -> dict[str, Any]:
        return {"runs": services.store.list_runs()}

    @app.post("/api/cases/{case_id}/runs", status_code=201)
    async def prepare_run(case_id: UUID) -> Any:
        try:
            run = services.factory.prepare_run(case_id)
        except (KeyError, ValueError, RuntimeError) as error:
            raise HTTPException(409, str(error)) from error
        if run.status == RunStatus.RESET_ERROR:
            raise HTTPException(503, run.error)
        return run

    @app.get("/api/runs/{run_id}")
    async def get_run(run_id: UUID) -> Any:
        run = services.store.get_run(run_id)
        if run is None:
            raise HTTPException(404, "run not found")
        return {"run": run, "score": services.store.get_score_for_run(run_id)}

    @app.get("/api/agent/runs/{run_id}")
    async def get_agent_run(run_id: UUID) -> Any:
        run = services.store.get_run(run_id)
        if run is None:
            raise HTTPException(404, "run not found")
        case = services.store.get_case(run.case_id)
        if case is None:
            raise HTTPException(404, "run case not found")
        return {
            "run": {
                "run_id": str(run.run_id),
                "case_id": str(run.case_id),
                "status": run.status,
                "workspace_path": run.workspace_path,
                "started_at": run.started_at,
                "completed_at": run.completed_at,
            },
            "case": _agent_case_view(case),
        }

    def execute_and_score(run_id: UUID) -> None:
        try:
            services.runner.execute(run_id)
        except Exception as error:
            run = services.store.get_run(run_id)
            if run is not None:
                run.status = RunStatus.ENVIRONMENT_ERROR
                run.error = str(redact(f"Agent runner failed: {error}"))
                services.store.save_run(run)
            return
        completed_run = services.store.get_run(run_id)
        if completed_run is None or completed_run.status == RunStatus.ENVIRONMENT_ERROR:
            return
        try:
            services.scorer.score(run_id)
        except Exception as error:
            run = services.store.get_run(run_id)
            if run is not None:
                run.status = RunStatus.ENVIRONMENT_ERROR
                run.error = str(redact(f"Scoring failed: {error}"))
                services.store.save_run(run)

    @app.post("/api/runs/{run_id}/execute", status_code=status.HTTP_202_ACCEPTED)
    async def execute_run(run_id: UUID, background_tasks: BackgroundTasks) -> dict[str, Any]:
        run = services.store.claim_ready_run(run_id)
        if run is None:
            current = services.store.get_run(run_id)
            if current is None:
                raise HTTPException(404, "run not found")
            raise HTTPException(409, f"run cannot start from status {current.status}")
        background_tasks.add_task(execute_and_score, run_id)
        return {"accepted": True, "run_id": str(run_id)}

    @app.post("/api/runs/{run_id}/score")
    async def score_run(run_id: UUID) -> Any:
        try:
            return services.scorer.score(run_id)
        except (KeyError, ValueError, RuntimeError) as error:
            raise HTTPException(409, str(error)) from error

    @app.post("/api/runs/{run_id}/cleanup")
    async def cleanup_run(run_id: UUID) -> dict[str, Any]:
        try:
            services.factory.cleanup_run(run_id)
            return {"cleaned": True, "run_id": str(run_id)}
        except (KeyError, ValueError, RuntimeError) as error:
            raise HTTPException(409, str(error)) from error

    def simulator_database(run_id: UUID) -> tuple[Path, Any]:
        run = services.store.get_run(run_id)
        if run is None or run.simulator_database_path is None:
            raise HTTPException(404, "Issue-to-PR simulator Run not found")
        database = Path(run.simulator_database_path)
        if not database.is_file():
            raise HTTPException(404, "Issue-to-PR simulator snapshot is no longer available")
        return database, run

    @app.get("/api/simulator/runs/{run_id}/issues/{issue_key}")
    async def simulator_issue(run_id: UUID, issue_key: str) -> Any:
        database, _ = simulator_database(run_id)
        try:
            return services.simulator.get_issue(database, issue_key)
        except KeyError as error:
            raise HTTPException(404, str(error)) from error

    @app.get("/api/simulator/runs/{run_id}/pull-requests")
    async def simulator_prs(run_id: UUID) -> Any:
        database, _ = simulator_database(run_id)
        return {"pull_requests": services.simulator.list_pull_requests(database)}

    @app.post("/api/simulator/runs/{run_id}/pull-requests", status_code=201)
    async def simulator_create_pr(run_id: UUID, body: PullRequestCreate) -> Any:
        database, _ = simulator_database(run_id)
        try:
            return services.simulator.create_pr(database, **body.model_dump())
        except (KeyError, ValueError, RuntimeError, sqlite3.IntegrityError) as error:
            raise HTTPException(409, str(error)) from error

    @app.post("/api/simulator/runs/{run_id}/issues/{issue_key}/status")
    async def simulator_status(run_id: UUID, issue_key: str, body: StatusUpdate) -> Any:
        database, _ = simulator_database(run_id)
        try:
            return services.simulator.update_issue_status(database, issue_key, body.status)
        except KeyError as error:
            raise HTTPException(404, str(error)) from error

    @app.get("/api/simulator/runs/{run_id}/events")
    async def simulator_events(run_id: UUID) -> Any:
        database, _ = simulator_database(run_id)
        return {"events": services.simulator.events(database)}

    if services.settings.web_root.is_dir():
        assets = services.settings.web_root / "assets"
        if assets.is_dir():
            app.mount("/assets", StaticFiles(directory=assets), name="assets")

        @app.get("/{path:path}")
        async def spa(path: str) -> FileResponse:
            del path
            return FileResponse(services.settings.web_root / "index.html")
    else:

        @app.get("/")
        async def missing_ui() -> Response:
            return Response("Workflow Environment Factory UI has not been built.\n", media_type="text/plain")

    return app
