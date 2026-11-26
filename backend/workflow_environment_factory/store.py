from __future__ import annotations

import json
import sqlite3
import threading
from collections.abc import Iterable
from functools import wraps
from pathlib import Path
from typing import Any, TypeVar
from uuid import UUID

from pydantic import BaseModel

from .models import BlueprintRecord, CaseRecord, ProtocolDocumentRecord, RecordingRecord, RunRecord, RunStatus

ModelT = TypeVar("ModelT", bound=BaseModel)


def _serialized(method):
    @wraps(method)
    def wrapped(self, *args, **kwargs):
        with self._lock:
            return method(self, *args, **kwargs)

    return wrapped


class FactoryStore:
    def __init__(self, database_path: Path):
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.database_path = database_path
        self._lock = threading.RLock()
        self.connection = sqlite3.connect(database_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA busy_timeout=5000")
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    @_serialized
    def _migrate(self) -> None:
        self.connection.executescript(
            """
            CREATE TABLE IF NOT EXISTS blueprints (
                id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS cases (
                id TEXT PRIMARY KEY,
                blueprint_id TEXT NOT NULL REFERENCES blueprints(id) ON DELETE CASCADE,
                variant_index INTEGER NOT NULL,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL,
                UNIQUE(blueprint_id, variant_index)
            );
            CREATE TABLE IF NOT EXISTS runs (
                id TEXT PRIMARY KEY,
                case_id TEXT NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS scores (
                id TEXT PRIMARY KEY,
                run_id TEXT NOT NULL REFERENCES runs(id) ON DELETE CASCADE,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS score_heads (
                run_id TEXT PRIMARY KEY REFERENCES runs(id) ON DELETE CASCADE,
                score_id TEXT NOT NULL UNIQUE REFERENCES scores(id) ON DELETE RESTRICT
            );
            CREATE TABLE IF NOT EXISTS recordings (
                id TEXT PRIMARY KEY,
                payload_json TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS protocol_documents (
                id TEXT PRIMARY KEY,
                schema_version TEXT NOT NULL,
                external_id TEXT NOT NULL,
                digest TEXT NOT NULL UNIQUE,
                payload_json TEXT NOT NULL,
                imported_at TEXT NOT NULL
            );
            """
        )
        historical_runs = self.connection.execute("SELECT DISTINCT run_id FROM scores ORDER BY run_id").fetchall()
        for historical in historical_runs:
            score = self.connection.execute(
                "SELECT id FROM scores WHERE run_id = ? ORDER BY created_at ASC, id ASC LIMIT 1",
                (historical["run_id"],),
            ).fetchone()
            if score is not None:
                self.connection.execute(
                    "INSERT OR IGNORE INTO score_heads(run_id, score_id) VALUES (?, ?)",
                    (historical["run_id"], score["id"]),
                )
        self.connection.commit()

    @_serialized
    def close(self) -> None:
        self.connection.close()

    @staticmethod
    def _json(model: BaseModel | dict[str, Any]) -> str:
        if isinstance(model, BaseModel):
            return model.model_dump_json()
        return json.dumps(model, separators=(",", ":"), sort_keys=True)

    @staticmethod
    def _load(row: sqlite3.Row | None, model_type: type[ModelT]) -> ModelT | None:
        return None if row is None else model_type.model_validate_json(row["payload_json"])

    @_serialized
    def save_blueprint(self, record: BlueprintRecord) -> BlueprintRecord:
        self.connection.execute(
            "INSERT INTO blueprints(id, payload_json, created_at) VALUES (?, ?, ?)",
            (str(record.blueprint_id), self._json(record), record.created_at.isoformat()),
        )
        self.connection.commit()
        return record

    @_serialized
    def get_blueprint(self, blueprint_id: UUID | str) -> BlueprintRecord | None:
        row = self.connection.execute(
            "SELECT payload_json FROM blueprints WHERE id = ?", (str(blueprint_id),)
        ).fetchone()
        return self._load(row, BlueprintRecord)

    @_serialized
    def list_blueprints(self) -> list[BlueprintRecord]:
        rows = self.connection.execute("SELECT payload_json FROM blueprints ORDER BY created_at DESC").fetchall()
        return [BlueprintRecord.model_validate_json(row["payload_json"]) for row in rows]

    @_serialized
    def save_cases(self, cases: Iterable[CaseRecord]) -> list[CaseRecord]:
        values = list(cases)
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            if values:
                existing = self.list_cases(values[0].blueprint_id)
                if existing:
                    return existing
            for record in values:
                self.connection.execute(
                    "INSERT INTO cases(id, blueprint_id, variant_index, payload_json, created_at) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        str(record.case_id),
                        str(record.blueprint_id),
                        record.variant_index,
                        self._json(record),
                        record.created_at.isoformat(),
                    ),
                )
        return values

    @_serialized
    def get_case(self, case_id: UUID | str) -> CaseRecord | None:
        row = self.connection.execute("SELECT payload_json FROM cases WHERE id = ?", (str(case_id),)).fetchone()
        return self._load(row, CaseRecord)

    @_serialized
    def list_cases(self, blueprint_id: UUID | str | None = None) -> list[CaseRecord]:
        if blueprint_id is None:
            rows = self.connection.execute(
                "SELECT payload_json FROM cases ORDER BY created_at DESC, variant_index"
            ).fetchall()
        else:
            rows = self.connection.execute(
                "SELECT payload_json FROM cases WHERE blueprint_id = ? ORDER BY variant_index",
                (str(blueprint_id),),
            ).fetchall()
        return [CaseRecord.model_validate_json(row["payload_json"]) for row in rows]

    @_serialized
    def save_run(self, record: RunRecord) -> RunRecord:
        self.connection.execute(
            "INSERT INTO runs(id, case_id, payload_json, created_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "case_id = excluded.case_id, payload_json = excluded.payload_json, created_at = excluded.created_at",
            (str(record.run_id), str(record.case_id), self._json(record), record.started_at.isoformat()),
        )
        self.connection.commit()
        return record

    @_serialized
    def get_run(self, run_id: UUID | str) -> RunRecord | None:
        row = self.connection.execute("SELECT payload_json FROM runs WHERE id = ?", (str(run_id),)).fetchone()
        return self._load(row, RunRecord)

    @_serialized
    def list_runs(self) -> list[RunRecord]:
        rows = self.connection.execute("SELECT payload_json FROM runs ORDER BY created_at DESC").fetchall()
        return [RunRecord.model_validate_json(row["payload_json"]) for row in rows]

    @_serialized
    def save_score(self, score: dict[str, Any], run: RunRecord | None = None) -> dict[str, Any]:
        self.connection.execute("BEGIN IMMEDIATE")
        try:
            row = self.connection.execute(
                "SELECT scores.payload_json FROM score_heads "
                "JOIN scores ON scores.id = score_heads.score_id WHERE score_heads.run_id = ?",
                (score["run_id"],),
            ).fetchone()
            if row is not None:
                self.connection.commit()
                return json.loads(row["payload_json"])
            self.connection.execute(
                "INSERT INTO scores(id, run_id, payload_json, created_at) VALUES (?, ?, ?, ?)",
                (score["score_id"], score["run_id"], self._json(score), score["created_at"]),
            )
            self.connection.execute(
                "INSERT INTO score_heads(run_id, score_id) VALUES (?, ?)",
                (score["run_id"], score["score_id"]),
            )
            if run is not None:
                run.validation_previous_status = None
                self.connection.execute(
                    "UPDATE runs SET payload_json = ? WHERE id = ?", (self._json(run), str(run.run_id))
                )
            self.connection.commit()
            return score
        except Exception:
            self.connection.rollback()
            row = self.connection.execute(
                "SELECT scores.payload_json FROM score_heads "
                "JOIN scores ON scores.id = score_heads.score_id WHERE score_heads.run_id = ?",
                (score["run_id"],),
            ).fetchone()
            if row is not None:
                return json.loads(row["payload_json"])
            raise

    @_serialized
    def get_score_for_run(self, run_id: UUID | str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT scores.payload_json FROM score_heads "
            "JOIN scores ON scores.id = score_heads.score_id WHERE score_heads.run_id = ?",
            (str(run_id),),
        ).fetchone()
        return None if row is None else json.loads(row["payload_json"])

    @_serialized
    def save_recording(self, recording: RecordingRecord) -> RecordingRecord:
        self.connection.execute(
            "INSERT OR REPLACE INTO recordings(id, payload_json, created_at) VALUES (?, ?, ?)",
            (str(recording.recording_id), self._json(recording), recording.created_at.isoformat()),
        )
        self.connection.commit()
        return recording

    @_serialized
    def get_recording(self, recording_id: UUID | str) -> RecordingRecord | None:
        row = self.connection.execute(
            "SELECT payload_json FROM recordings WHERE id = ?", (str(recording_id),)
        ).fetchone()
        return self._load(row, RecordingRecord)

    @_serialized
    def list_recordings(self) -> list[RecordingRecord]:
        rows = self.connection.execute("SELECT payload_json FROM recordings ORDER BY created_at DESC").fetchall()
        return [RecordingRecord.model_validate_json(row["payload_json"]) for row in rows]

    @_serialized
    def save_protocol_document(self, record: ProtocolDocumentRecord) -> ProtocolDocumentRecord:
        existing = self.connection.execute(
            "SELECT payload_json FROM protocol_documents WHERE digest = ?", (record.digest,)
        ).fetchone()
        if existing is not None:
            return ProtocolDocumentRecord.model_validate_json(existing["payload_json"])
        self.connection.execute(
            "INSERT INTO protocol_documents(id, schema_version, external_id, digest, payload_json, imported_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                str(record.document_id),
                record.schema_version,
                record.external_id,
                record.digest,
                self._json(record),
                record.imported_at.isoformat(),
            ),
        )
        self.connection.commit()
        return record

    @_serialized
    def list_protocol_documents(self) -> list[ProtocolDocumentRecord]:
        rows = self.connection.execute(
            "SELECT payload_json FROM protocol_documents ORDER BY imported_at DESC"
        ).fetchall()
        return [ProtocolDocumentRecord.model_validate_json(row["payload_json"]) for row in rows]

    @_serialized
    def get_protocol_document(self, document_id: UUID | str) -> ProtocolDocumentRecord | None:
        row = self.connection.execute(
            "SELECT payload_json FROM protocol_documents WHERE id = ?", (str(document_id),)
        ).fetchone()
        return self._load(row, ProtocolDocumentRecord)

    @_serialized
    def claim_ready_run(self, run_id: UUID | str) -> RunRecord | None:
        row = self.connection.execute("SELECT payload_json FROM runs WHERE id = ?", (str(run_id),)).fetchone()
        if row is None:
            return None
        run = RunRecord.model_validate_json(row["payload_json"])
        if run.status != RunStatus.READY or run.workspace_cleaned:
            return None
        previous_payload = row["payload_json"]
        run.status = RunStatus.QUEUED
        with self.connection:
            cursor = self.connection.execute(
                "UPDATE runs SET payload_json = ? WHERE id = ? AND payload_json = ?",
                (self._json(run), str(run_id), previous_payload),
            )
        return run if cursor.rowcount == 1 else None

    @_serialized
    def claim_cleanup(self, run_id: UUID | str) -> RunRecord | None:
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            run = self.get_run(run_id)
            if run is None:
                return None
            if run.status in {RunStatus.PREPARING, RunStatus.QUEUED, RunStatus.RUNNING, RunStatus.VALIDATING}:
                raise ValueError("cannot clean an active Run")
            run.workspace_cleaned = True
            self.connection.execute("UPDATE runs SET payload_json = ? WHERE id = ?", (self._json(run), str(run_id)))
            return run

    @_serialized
    def claim_scoring(self, run_id: UUID | str) -> tuple[RunRecord | None, dict[str, Any] | None]:
        with self.connection:
            self.connection.execute("BEGIN IMMEDIATE")
            existing = self.get_score_for_run(run_id)
            if existing is not None:
                return None, existing
            run = self.get_run(run_id)
            if run is None:
                raise KeyError("run not found")
            if run.status == RunStatus.VALIDATING:
                return None, None
            if run.workspace_cleaned or run.status not in {
                RunStatus.COMPLETED,
                RunStatus.AGENT_CRASH,
                RunStatus.AGENT_TIMEOUT,
            }:
                raise ValueError(f"run cannot be scored from status {run.status}")
            claimed = run.model_copy(update={"status": RunStatus.VALIDATING, "validation_previous_status": run.status})
            self.connection.execute("UPDATE runs SET payload_json = ? WHERE id = ?", (self._json(claimed), str(run_id)))
            return run, None

    @_serialized
    def recover_interrupted_runs(self) -> list[RunRecord]:
        recovered: list[RunRecord] = []
        for run in self.list_runs():
            if run.status == RunStatus.VALIDATING and run.validation_previous_status:
                run.status = run.validation_previous_status
                run.validation_previous_status = None
                recovered.append(self.save_run(run))
            elif run.status.value in {"preparing", "queued", "running", "validating"}:
                run.status = RunStatus.ENVIRONMENT_ERROR
                run.error = "The factory restarted before this Run reached a terminal state."
                recovered.append(self.save_run(run))
        return recovered
