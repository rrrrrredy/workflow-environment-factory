from __future__ import annotations

import os
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol
from uuid import uuid4


@dataclass(frozen=True)
class ProcessResult:
    status: str
    exit_code: int | None
    stdout: str
    stderr: str
    duration_ms: int


class ExecutionEngine(Protocol):
    name: str

    def run(self, workspace: Path, image: str, argv: list[str], timeout_ms: int) -> ProcessResult: ...


def _bounded(value: str, limit: int = 1_000_000) -> str:
    return value if len(value) <= limit else value[-limit:]


def _container_user_args(platform_name: str, uid: int | None, gid: int | None) -> list[str]:
    if platform_name != "posix":
        return []
    if uid is None or gid is None:
        raise RuntimeError("POSIX Docker execution requires the host uid and gid")
    return ["--user", f"{uid}:{gid}"]


class LocalTestEngine:
    """A deterministic test double. Production paths must use DockerEngine."""

    name = "local-test-only"

    def run(self, workspace: Path, image: str, argv: list[str], timeout_ms: int) -> ProcessResult:
        del image
        started = time.monotonic()
        try:
            completed = subprocess.run(
                argv,
                cwd=workspace,
                capture_output=True,
                text=True,
                timeout=timeout_ms / 1_000,
                shell=False,
                check=False,
            )
            return ProcessResult(
                status="pass" if completed.returncode == 0 else "fail",
                exit_code=completed.returncode,
                stdout=_bounded(completed.stdout),
                stderr=_bounded(completed.stderr),
                duration_ms=int((time.monotonic() - started) * 1_000),
            )
        except subprocess.TimeoutExpired as error:
            return ProcessResult(
                status="timeout",
                exit_code=None,
                stdout=_bounded(error.stdout or ""),
                stderr=_bounded(error.stderr or ""),
                duration_ms=int((time.monotonic() - started) * 1_000),
            )
        except OSError as error:
            return ProcessResult(
                status="error",
                exit_code=None,
                stdout="",
                stderr=str(error),
                duration_ms=int((time.monotonic() - started) * 1_000),
            )


class DockerEngine:
    name = "docker"
    image_inspect_timeout_ms = 10_000
    image_pull_timeout_ms = 300_000

    def __init__(self, executable: str = "docker"):
        self.executable = executable

    def availability(self) -> ProcessResult:
        return LocalTestEngine().run(
            Path.cwd(), "", [self.executable, "version", "--format", "{{.Server.Version}}"], 10_000
        )

    def _prepare_image(self, workspace: Path, image: str) -> ProcessResult | None:
        runner = LocalTestEngine()
        inspection = runner.run(
            workspace,
            "",
            [self.executable, "image", "inspect", image],
            self.image_inspect_timeout_ms,
        )
        if inspection.status == "pass":
            return None
        if inspection.status in {"error", "timeout"}:
            return ProcessResult(
                status="error",
                exit_code=inspection.exit_code,
                stdout=inspection.stdout,
                stderr=_bounded(
                    "container image inspection failed before verifier execution: "
                    f"{inspection.stderr or inspection.stdout or inspection.status}"
                ),
                duration_ms=inspection.duration_ms,
            )

        pull = runner.run(
            workspace,
            "",
            [self.executable, "pull", image],
            self.image_pull_timeout_ms,
        )
        if pull.status == "pass":
            return None
        return ProcessResult(
            status="error",
            exit_code=pull.exit_code,
            stdout=pull.stdout,
            stderr=_bounded(
                "container image preparation failed before verifier execution: "
                f"{pull.stderr or pull.stdout or pull.status}"
            ),
            duration_ms=pull.duration_ms,
        )

    def run(self, workspace: Path, image: str, argv: list[str], timeout_ms: int) -> ProcessResult:
        workspace = workspace.resolve()
        if not workspace.is_dir():
            raise ValueError(f"workspace does not exist: {workspace}")
        preparation = self._prepare_image(workspace, image)
        if preparation is not None:
            return preparation
        container_name = f"wef-{uuid4().hex[:20]}"
        uid = os.getuid() if hasattr(os, "getuid") else None
        gid = os.getgid() if hasattr(os, "getgid") else None
        command = [
            self.executable,
            "run",
            "--rm",
            "--name",
            container_name,
            "--network",
            "none",
            "--cpus",
            "2",
            "--memory",
            "3g",
            "--pids-limit",
            "128",
            "--read-only",
            *_container_user_args(os.name, uid, gid),
            "--tmpfs",
            "/tmp:rw,noexec,nosuid,size=256m",
            "--mount",
            f"type=bind,source={workspace},target=/workspace",
            "--workdir",
            "/workspace",
            image,
            *argv,
        ]
        started = time.monotonic()
        try:
            process = subprocess.Popen(
                command,
                cwd=workspace,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=False,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
            try:
                stdout, stderr = process.communicate(timeout=timeout_ms / 1_000)
            except subprocess.TimeoutExpired:
                process.kill()
                stdout, stderr = process.communicate()
                subprocess.run(
                    [self.executable, "rm", "-f", container_name],
                    capture_output=True,
                    text=True,
                    timeout=30,
                    shell=False,
                    check=False,
                )
                return ProcessResult(
                    status="timeout",
                    exit_code=None,
                    stdout=_bounded(stdout),
                    stderr=_bounded(stderr),
                    duration_ms=int((time.monotonic() - started) * 1_000),
                )
            return ProcessResult(
                status="pass" if process.returncode == 0 else "fail",
                exit_code=process.returncode,
                stdout=_bounded(stdout),
                stderr=_bounded(stderr),
                duration_ms=int((time.monotonic() - started) * 1_000),
            )
        except OSError as error:
            return ProcessResult(
                status="error",
                exit_code=None,
                stdout="",
                stderr=str(error),
                duration_ms=int((time.monotonic() - started) * 1_000),
            )
