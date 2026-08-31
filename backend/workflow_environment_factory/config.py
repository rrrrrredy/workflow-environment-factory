from __future__ import annotations

import json
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

DATA_MARKER_NAME = ".workflow-environment-factory-data.json"


def ensure_factory_data_root(data_dir: Path) -> None:
    if data_dir.exists():
        if not data_dir.is_dir() or data_dir.is_symlink():
            raise ValueError(f"Workflow Environment Factory data root must be a real directory: {data_dir}")
        marker_path = data_dir / DATA_MARKER_NAME
        if marker_path.exists():
            if not marker_path.is_file() or marker_path.is_symlink():
                raise ValueError(f"Data-root marker must be a real file: {marker_path}")
            try:
                marker = json.loads(marker_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as error:
                raise ValueError(f"Workflow Environment Factory data marker is invalid: {marker_path}") from error
            if (
                not isinstance(marker, dict)
                or marker.get("schema_version") != "product.data-root.v1"
                or marker.get("product") != "workflow-environment-factory"
            ):
                raise ValueError(f"Workflow Environment Factory data marker names another product: {marker_path}")
            return
        raise ValueError(
            f"Data directory already exists but has no Workflow Environment Factory ownership marker: {data_dir}"
        )
    else:
        data_dir.mkdir(parents=True)
    marker = {
        "schema_version": "product.data-root.v1",
        "product": "workflow-environment-factory",
        "created_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
    }
    with (data_dir / DATA_MARKER_NAME).open("x", encoding="utf-8", newline="\n") as output:
        json.dump(marker, output, indent=2)
        output.write("\n")


@dataclass(frozen=True)
class Settings:
    host: str
    port: int
    data_dir: Path
    database_path: Path
    content_dir: Path
    worktrees_dir: Path
    simulator_dir: Path
    token_path: Path
    protocol_schema_dir: Path
    codex_executable: str
    docker_executable: str
    web_root: Path

    @classmethod
    def load(cls, repository_root: Path | None = None, *, initialize: bool = True) -> Settings:
        host = os.getenv("WEF_HOST", "127.0.0.1")
        if host != "127.0.0.1":
            raise ValueError("Workflow Environment Factory only binds to 127.0.0.1")
        port = int(os.getenv("WEF_PORT", "43121"))
        if port < 1024 or port > 65535:
            raise ValueError("WEF_PORT must be between 1024 and 65535")
        local_app_data = os.getenv("LOCALAPPDATA")
        default_data = (
            Path(local_app_data) / "WorkflowEnvironmentFactory"
            if local_app_data
            else Path.home() / ".workflow-environment-factory"
        )
        requested_data = Path(os.getenv("WEF_DATA_DIR", str(default_data))).expanduser()
        data_dir = Path(os.path.abspath(requested_data))
        default_protocol = data_dir / "dependencies" / "runcase-interchange" / "0.1.1" / "schemas"
        protocol_schema_dir = Path(os.getenv("WEF_PROTOCOL_SCHEMA_DIR", str(default_protocol))).expanduser().resolve()
        root = (repository_root or Path.cwd()).resolve()
        settings = cls(
            host=host,
            port=port,
            data_dir=data_dir,
            database_path=data_dir / "factory.sqlite3",
            content_dir=data_dir / "content",
            worktrees_dir=data_dir / "worktrees",
            simulator_dir=data_dir / "simulators",
            token_path=data_dir / "session-token",
            protocol_schema_dir=protocol_schema_dir,
            codex_executable=os.getenv("CODEX_EXECUTABLE", "codex"),
            docker_executable=os.getenv("DOCKER_EXECUTABLE", "docker"),
            web_root=root / "dist" / "web",
        )
        if initialize:
            ensure_factory_data_root(settings.data_dir)
            for directory in (settings.content_dir, settings.worktrees_dir, settings.simulator_dir):
                directory.mkdir(parents=True, exist_ok=True)
        return settings
