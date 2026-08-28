from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


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
    def load(cls, repository_root: Path | None = None) -> Settings:
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
        data_dir = Path(os.getenv("WEF_DATA_DIR", str(default_data))).expanduser().resolve()
        default_protocol = data_dir / "dependencies" / "agent-run-protocol" / "0.1.0" / "schemas"
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
        for directory in (
            settings.data_dir,
            settings.content_dir,
            settings.worktrees_dir,
            settings.simulator_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)
        return settings
