from __future__ import annotations

import json
import sqlite3
from collections.abc import Iterable
from pathlib import Path
from typing import Any, TypeVar
from uuid import UUID

from pydantic import BaseModel

from .models import BlueprintRecord, CaseRecord, ProtocolDocumentRecord, RecordingRecord, RunRecord, RunStatus

ModelT = TypeVar("ModelT", bound=BaseModel)


class FactoryStore:
    def __init__(self, database_path: Path):
        database_path.parent.mkdir(parents=True, exist_ok=True)
        self.database_path = database_path
        self.connection = sqlite3.connect(database_path, check_same_thread=False)
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA journal_mode=WAL")
        self.connection.execute("PRAGMA foreign_keys=ON")
        self._migrate()

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
        historical_runs = self.connection.execute(
            "SELECT DISTINCT run_id FROM scores ORDER BY run_id"
        ).fetchall()
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

    def save_blueprint(self, record: BlueprintRecord) -> BlueprintRecord:
        self.connection.execute(
            "INSERT INTO blueprints(id, payload_json, created_at) VALUES (?, ?, ?)",
            (str(record.blueprint_id), self._json(record), record.created_at.isoformat()),
        )
        self.connection.commit()
        return record

    def get_blueprint(self, blueprint_id: UUID | str) -> BlueprintRecord | None:
        row = self.connection.execute(
            "SELECT payload_json FROM blueprints WHERE id = ?", (str(blueprint_id),)
        ).fetchone()
        return self._load(row, BlueprintRecord)

    def list_blueprints(self) -> list[BlueprintRecord]:
        rows = self.connection.execute("SELECT payload_json FROM blueprints ORDER BY created_at DESC").fetchall()
        return [BlueprintRecord.model_validate_json(row["payload_json"]) for row in rows]

    def save_cases(self, cases: Iterable[CaseRecord]) -> list[CaseRecord]:
        values = list(cases)
        with self.connection:
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

    def get_case(self, case_id: UUID | str) -> CaseRecord | None:
        row = self.connection.execute("SELECT payload_json FROM cases WHERE id = ?", (str(case_id),)).fetchone()
        return self._load(row, CaseRecord)

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

    def save_run(self, record: RunRecord) -> RunRecord:
        self.connection.execute(
            "INSERT INTO runs(id, case_id, payload_json, created_at) VALUES (?, ?, ?, ?) "
            "ON CONFLICT(id) DO UPDATE SET "
            "case_id = excluded.case_id, payload_json = excluded.payload_json, created_at = excluded.created_at",
            (str(record.run_id), str(record.case_id), self._json(record), record.started_at.isoformat()),
        )
        self.connection.commit()
        return record

    def get_run(self, run_id: UUID | str) -> RunRecord | None:
        row = self.connection.execute("SELECT payload_json FROM runs WHERE id = ?", (str(run_id),)).fetchone()
        return self._load(row, RunRecord)

    def list_runs(self) -> list[RunRecord]:
        rows = self.connection.execute("SELECT payload_json FROM runs ORDER BY created_at DESC").fetchall()
        return [RunRecord.model_validate_json(row["payload_json"]) for row in rows]

    def save_score(self, score: dict[str, Any]) -> dict[str, Any]:
        existing = self.get_score_for_run(score["run_id"])
        if existing is not None:
            return existing
        with self.connection:
            self.connection.execute(
                "INSERT INTO scores(id, run_id, payload_json, created_at) VALUES (?, ?, ?, ?)",
                (score["score_id"], score["run_id"], self._json(score), score["created_at"]),
            )
            self.connection.execute(
                "INSERT INTO score_heads(run_id, score_id) VALUES (?, ?)",
                (score["run_id"], score["score_id"]),
            )
        return score

    def get_score_for_run(self, run_id: UUID | str) -> dict[str, Any] | None:
        row = self.connection.execute(
            "SELECT scores.payload_json FROM score_heads "
            "JOIN scores ON scores.id = score_heads.score_id WHERE score_heads.run_id = ?",
            (str(run_id),),
        ).fetchone()
        return None if row is None else json.loads(row["payload_json"])

    def save_recording(self, recording: RecordingRecord) -> RecordingRecord:
        self.connection.execute(
            "INSERT OR REPLACE INTO recordings(id, payload_json, created_at) VALUES (?, ?, ?)",
            (str(recording.recording_id), self._json(recording), recording.created_at.isoformat()),
        )
        self.connection.commit()
        return recording

    def get_recording(self, recording_id: UUID | str) -> RecordingRecord | None:
        row = self.connection.execute(
            "SELECT payload_json FROM recordings WHERE id = ?", (str(recording_id),)
        ).fetchone()
        return self._load(row, RecordingRecord)

    def list_recordings(self) -> list[RecordingRecord]:
        rows = self.connection.execute("SELECT payload_json FROM recordings ORDER BY created_at DESC").fetchall()
        return [RecordingRecord.model_validate_json(row["payload_json"]) for row in rows]

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

    def list_protocol_documents(self) -> list[ProtocolDocumentRecord]:
        rows = self.connection.execute(
            "SELECT payload_json FROM protocol_documents ORDER BY imported_at DESC"
        ).fetchall()
        return [ProtocolDocumentRecord.model_validate_json(row["payload_json"]) for row in rows]

    def get_protocol_document(self, document_id: UUID | str) -> ProtocolDocumentRecord | None:
        row = self.connection.execute(
            "SELECT payload_json FROM protocol_documents WHERE id = ?", (str(document_id),)
        ).fetchone()
        return self._load(row, ProtocolDocumentRecord)

    def recover_interrupted_runs(self) -> list[RunRecord]:
        recovered: list[RunRecord] = []
        for run in self.list_runs():
            if run.status.value in {"preparing", "running", "validating"}:
                run.status = RunStatus.ENVIRONMENT_ERROR
                run.error = "The factory restarted before this Run reached a terminal state."
                recovered.append(self.save_run(run))
        return recovered
