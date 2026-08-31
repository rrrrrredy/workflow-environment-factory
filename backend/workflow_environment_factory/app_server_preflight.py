from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
import time
from collections import deque
from collections.abc import Mapping, Sequence
from contextlib import suppress
from pathlib import Path
from typing import Any, TextIO
from uuid import uuid4

from .codex_permissions import PROFILE_ID, permission_profile_cli_args

_READ_ISOLATION_PROBE = """
import os
import subprocess
import sys
from pathlib import Path

database, source, solution, sentinel = sys.argv[1:5]
Path(sentinel).write_text("write-ok", encoding="utf-8")
try:
    Path(database).read_bytes()
except OSError:
    pass
else:
    print("FORBIDDEN_DATABASE_READ_SUCCEEDED")
    raise SystemExit(73)

clean_environment = dict(os.environ)
clean_environment.pop("GIT_DIR", None)
clean_environment.pop("GIT_WORK_TREE", None)
version = subprocess.run(
    ["git", "--version"], capture_output=True, text=True, env=clean_environment, check=False
)
if version.returncode != 0:
    print("GIT_UNAVAILABLE")
    raise SystemExit(74)
probe = subprocess.run(
    ["git", "-C", source, "show", solution],
    capture_output=True,
    text=True,
    env=clean_environment,
    check=False,
)
if probe.returncode == 0:
    print("FORBIDDEN_SOLUTION_READ_SUCCEEDED")
    raise SystemExit(75)
Path(sentinel).write_text(
    "write-ok;database-read-blocked;solution-read-blocked", encoding="utf-8"
)
"""


class CodexPreflightError(RuntimeError):
    """The installed Codex could not establish the requested workspace sandbox."""


def _server_error_message(value: Any) -> str:
    if isinstance(value, dict) and isinstance(value.get("message"), str) and value["message"]:
        return value["message"]
    return "unknown server error"


class CodexWorkspacePreflight:
    """Run a bounded App Server command before any model-backed Codex execution."""

    def __init__(self, command_prefix: str | Sequence[str], timeout_seconds: float = 30.0):
        self.command_prefix = [command_prefix] if isinstance(command_prefix, str) else list(command_prefix)
        if not self.command_prefix:
            raise ValueError("Codex App Server command prefix cannot be empty")
        self.timeout_seconds = timeout_seconds

    def check(
        self,
        workspace: Path,
        environment: Mapping[str, str],
        *,
        database_path: Path,
        repository_root: Path,
        solution_commit: str,
        mcp_script: Path,
    ) -> None:
        root = workspace.resolve(strict=True)
        if not root.is_dir():
            raise CodexPreflightError("Managed workspace preflight requires a directory")
        database = database_path.resolve(strict=True)
        if not database.is_file():
            raise CodexPreflightError("Managed workspace preflight requires an existing product database")
        source = repository_root.resolve(strict=True)
        if not source.is_dir():
            raise CodexPreflightError("Managed workspace preflight requires an existing source repository")
        mcp = mcp_script.resolve(strict=True)
        if not mcp.is_file():
            raise CodexPreflightError("Managed workspace preflight requires the reviewed MCP server")
        git_environment = dict(os.environ)
        git_environment.pop("GIT_DIR", None)
        git_environment.pop("GIT_WORK_TREE", None)
        solution_probe = subprocess.run(
            ["git", "-C", str(source), "cat-file", "-e", f"{solution_commit}^{{commit}}"],
            capture_output=True,
            text=True,
            timeout=15,
            env=git_environment,
            shell=False,
            check=False,
        )
        if solution_probe.returncode != 0:
            raise CodexPreflightError("The known-correct commit is no longer available in the source repository")
        sentinel = root / f".workflow-environment-preflight-{uuid4().hex}"
        git_dir = Path(environment["GIT_DIR"]).resolve(strict=True)
        process = subprocess.Popen(
            [
                *self.command_prefix,
                *permission_profile_cli_args(git_dir=git_dir, mcp_script=mcp),
                "app-server",
                "--strict-config",
                "--listen",
                "stdio://",
            ],
            cwd=root,
            env=dict(environment),
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            shell=False,
            creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
        )
        assert process.stdin is not None
        assert process.stdout is not None
        assert process.stderr is not None
        lines: queue.Queue[str | None] = queue.Queue()
        stderr_chunks: deque[str] = deque(maxlen=32)
        threading.Thread(target=self._read_stdout, args=(process.stdout, lines), daemon=True).start()
        threading.Thread(target=self._read_stderr, args=(process.stderr, stderr_chunks), daemon=True).start()
        primary_error: BaseException | None = None
        try:
            self._request(
                process,
                lines,
                stderr_chunks,
                1,
                "initialize",
                {
                    "clientInfo": {
                        "name": "workflow_environment_factory",
                        "title": "Workflow Environment Factory",
                        "version": "0.2.0",
                    },
                    "capabilities": {
                        "experimentalApi": True,
                        "requestAttestation": False,
                        "optOutNotificationMethods": [],
                        "extensions": {},
                    },
                },
            )
            self._write(process, {"method": "initialized"})
            result = self._request(
                process,
                lines,
                stderr_chunks,
                2,
                "command/exec",
                {
                    "command": [
                        sys.executable,
                        "-c",
                        _READ_ISOLATION_PROBE,
                        str(database),
                        str(source),
                        solution_commit,
                        str(sentinel),
                    ],
                    "cwd": str(root),
                    "permissionProfile": PROFILE_ID,
                    "timeoutMs": 15_000,
                },
            )
            if not isinstance(result, dict) or result.get("exitCode") != 0:
                exit_code = result.get("exitCode") if isinstance(result, dict) else None
                raise CodexPreflightError(f"Managed workspace preflight exited with {exit_code!r}")
            expected = "write-ok;database-read-blocked;solution-read-blocked"
            if not sentinel.is_file() or sentinel.read_text(encoding="utf-8") != expected:
                raise CodexPreflightError(
                    "Managed workspace preflight did not prove workspace write plus blocked database and solution reads"
                )
        except BaseException as error:
            primary_error = error
            raise
        finally:
            cleanup_error: OSError | None = None
            if sentinel.exists():
                try:
                    sentinel.unlink()
                except OSError as error:
                    cleanup_error = error
            self._stop(process)
            if cleanup_error is not None and primary_error is None:
                raise CodexPreflightError(f"Managed workspace preflight could not remove its sentinel: {cleanup_error}")

    def _request(
        self,
        process: subprocess.Popen[str],
        lines: queue.Queue[str | None],
        stderr_chunks: deque[str],
        request_id: int,
        method: str,
        params: dict[str, Any],
    ) -> Any:
        self._write(process, {"id": request_id, "method": method, "params": params})
        deadline = time.monotonic() + self.timeout_seconds
        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise CodexPreflightError(f"Codex App Server preflight timed out during {method}")
            try:
                line = lines.get(timeout=remaining)
            except queue.Empty as error:
                raise CodexPreflightError(f"Codex App Server preflight timed out during {method}") from error
            if line is None:
                stderr = "".join(stderr_chunks)[-4_000:].strip()
                detail = f": {stderr}" if stderr else ""
                raise CodexPreflightError(f"Codex App Server exited during {method}{detail}")
            try:
                message = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(message, dict):
                continue
            if "method" in message and "id" in message:
                self._write(
                    process,
                    {
                        "id": message["id"],
                        "error": {
                            "code": -32001,
                            "message": "Workflow Environment Factory never auto-approves App Server requests",
                        },
                    },
                )
                continue
            if message.get("id") != request_id:
                continue
            if "error" in message:
                raise CodexPreflightError(
                    f"Codex App Server preflight request failed: {_server_error_message(message['error'])}"
                )
            return message.get("result")

    @staticmethod
    def _write(process: subprocess.Popen[str], message: dict[str, Any]) -> None:
        if process.stdin is None:
            raise CodexPreflightError("Codex App Server stdin is unavailable")
        try:
            process.stdin.write(json.dumps(message, separators=(",", ":")) + "\n")
            process.stdin.flush()
        except (BrokenPipeError, OSError) as error:
            raise CodexPreflightError(f"Codex App Server connection failed: {error}") from error

    @staticmethod
    def _read_stdout(stream: TextIO, lines: queue.Queue[str | None]) -> None:
        try:
            for line in stream:
                lines.put(line)
        finally:
            lines.put(None)

    @staticmethod
    def _read_stderr(stream: TextIO, chunks: deque[str]) -> None:
        while True:
            chunk = stream.read(1_024)
            if not chunk:
                return
            chunks.append(chunk)

    @staticmethod
    def _stop(process: subprocess.Popen[str]) -> None:
        if process.stdin is not None:
            with suppress(OSError):
                process.stdin.close()
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=2)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=2)
