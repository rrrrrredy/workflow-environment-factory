from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


@dataclass(frozen=True)
class SimulatorValidation:
    status_matches: bool
    linked_pr_exists: bool
    pr_target_matches: bool
    details: dict[str, Any]

    @property
    def passed(self) -> bool:
        return self.status_matches and self.linked_pr_exists and self.pr_target_matches


class IssuePrSimulator:
    @staticmethod
    def initialize(database_path: Path, *, key: str, title: str, body: str, status: str, pr_target: str) -> None:
        database_path.parent.mkdir(parents=True, exist_ok=True)
        if database_path.exists():
            raise FileExistsError(f"simulator database already exists: {database_path}")
        connection = sqlite3.connect(database_path)
        try:
            connection.executescript(
                """
                CREATE TABLE issues (
                    issue_key TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    body TEXT NOT NULL,
                    status TEXT NOT NULL,
                    expected_pr_target TEXT NOT NULL
                );
                CREATE TABLE pull_requests (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL,
                    branch TEXT NOT NULL,
                    target TEXT NOT NULL,
                    linked_issue_key TEXT NOT NULL REFERENCES issues(issue_key),
                    created_at TEXT NOT NULL
                );
                CREATE TABLE events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                """
            )
            connection.execute(
                "INSERT INTO issues(issue_key, title, body, status, expected_pr_target) VALUES (?, ?, ?, ?, ?)",
                (key, title, body, status, pr_target),
            )
            connection.commit()
        finally:
            connection.close()

    @staticmethod
    def _connect(database_path: Path) -> sqlite3.Connection:
        connection = sqlite3.connect(database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        return connection

    def get_issue(self, database_path: Path, issue_key: str, *, record: bool = True) -> dict[str, Any]:
        connection = self._connect(database_path)
        try:
            row = connection.execute("SELECT * FROM issues WHERE issue_key = ?", (issue_key,)).fetchone()
            if row is None:
                raise KeyError(f"issue not found: {issue_key}")
            issue = dict(row)
            if record:
                self._event(connection, "issue_read", {"issue_key": issue_key})
                connection.commit()
            return issue
        finally:
            connection.close()

    def create_pr(
        self,
        database_path: Path,
        *,
        title: str,
        branch: str,
        target: str,
        linked_issue_key: str,
    ) -> dict[str, Any]:
        connection = self._connect(database_path)
        try:
            cursor = connection.execute(
                "INSERT INTO pull_requests(title, branch, target, linked_issue_key, created_at) VALUES (?, ?, ?, ?, ?)",
                (title, branch, target, linked_issue_key, _now()),
            )
            pr_id = cursor.lastrowid
            self._event(
                connection,
                "pr_created",
                {"pr_id": pr_id, "target": target, "branch": branch, "linked_issue_key": linked_issue_key},
            )
            connection.commit()
            row = connection.execute("SELECT * FROM pull_requests WHERE id = ?", (pr_id,)).fetchone()
            if row is None:
                raise RuntimeError("simulator pull request disappeared")
            return dict(row)
        finally:
            connection.close()

    def update_issue_status(self, database_path: Path, issue_key: str, status: str) -> dict[str, Any]:
        connection = self._connect(database_path)
        try:
            result = connection.execute("UPDATE issues SET status = ? WHERE issue_key = ?", (status, issue_key))
            if result.rowcount != 1:
                raise KeyError(f"issue not found: {issue_key}")
            self._event(connection, "issue_status_updated", {"issue_key": issue_key, "status": status})
            connection.commit()
            row = connection.execute("SELECT * FROM issues WHERE issue_key = ?", (issue_key,)).fetchone()
            if row is None:
                raise RuntimeError("simulator issue disappeared")
            return dict(row)
        finally:
            connection.close()

    def list_pull_requests(self, database_path: Path) -> list[dict[str, Any]]:
        connection = self._connect(database_path)
        try:
            return [dict(row) for row in connection.execute("SELECT * FROM pull_requests ORDER BY id").fetchall()]
        finally:
            connection.close()

    def events(self, database_path: Path) -> list[dict[str, Any]]:
        connection = self._connect(database_path)
        try:
            return [
                {**dict(row), "data": json.loads(row["data_json"])}
                for row in connection.execute("SELECT * FROM events ORDER BY id").fetchall()
            ]
        finally:
            connection.close()

    def validate(
        self,
        database_path: Path,
        *,
        issue_key: str,
        target_status: str,
        pr_target: str,
    ) -> SimulatorValidation:
        connection = self._connect(database_path)
        try:
            issue = connection.execute("SELECT * FROM issues WHERE issue_key = ?", (issue_key,)).fetchone()
            prs = connection.execute(
                "SELECT * FROM pull_requests WHERE linked_issue_key = ? ORDER BY id",
                (issue_key,),
            ).fetchall()
            status_matches = issue is not None and issue["status"] == target_status
            linked_pr_exists = len(prs) > 0
            pr_target_matches = any(row["target"] == pr_target for row in prs)
            return SimulatorValidation(
                status_matches=status_matches,
                linked_pr_exists=linked_pr_exists,
                pr_target_matches=pr_target_matches,
                details={
                    "issue_status": None if issue is None else issue["status"],
                    "expected_status": target_status,
                    "linked_pr_count": len(prs),
                    "pr_targets": [row["target"] for row in prs],
                    "expected_pr_target": pr_target,
                },
            )
        finally:
            connection.close()

    @staticmethod
    def _event(connection: sqlite3.Connection, event_type: str, data: dict[str, Any]) -> None:
        connection.execute(
            "INSERT INTO events(event_type, data_json, created_at) VALUES (?, ?, ?)",
            (event_type, json.dumps(data, sort_keys=True), _now()),
        )
