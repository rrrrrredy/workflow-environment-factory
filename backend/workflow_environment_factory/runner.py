from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from typing import Protocol
from uuid import UUID

from .app_server_preflight import CodexWorkspacePreflight
from .auth import derive_agent_token, load_or_create_token
from .codex_permissions import permission_profile_cli_args
from .gitops import GitWorkspaceManager
from .models import AttemptOrigin, BlueprintKind, RunStatus, utc_now
from .redaction import redact
from .store import FactoryStore


class WorkspacePreflight(Protocol):
    def check(
        self,
        workspace: Path,
        environment: dict[str, str],
        *,
        database_path: Path,
        repository_root: Path,
        solution_commit: str,
        mcp_script: Path,
    ) -> None: ...


_MANAGED_GIT_ENVIRONMENT = (
    "GIT_DIR",
    "GIT_WORK_TREE",
    "GIT_CONFIG_NOSYSTEM",
    "GIT_CONFIG_GLOBAL",
    "GIT_ATTR_NOSYSTEM",
    "GIT_TERMINAL_PROMPT",
    "GIT_OPTIONAL_LOCKS",
)


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def build_codex_command(
    executable: str,
    workspace: Path,
    prompt: str,
    environment: dict[str, str],
    *,
    mcp_script: Path,
    agent_token: str,
    run_id: UUID | str,
    port: int,
) -> list[str]:
    git_environment = ",".join(
        f"{name}={_toml_string(environment[name])}" for name in _MANAGED_GIT_ENVIRONMENT
    )
    node_executable = environment.get("WEF_NODE", "node")
    git_dir = Path(environment["GIT_DIR"])
    return [
        executable,
        "exec",
        "--json",
        "--color",
        "never",
        "--strict-config",
        "--ephemeral",
        "--ignore-user-config",
        "--skip-git-repo-check",
        "--disable",
        "apps",
        "--disable",
        "browser_use",
        "--disable",
        "computer_use",
        "--disable",
        "goals",
        "--disable",
        "hooks",
        "--disable",
        "image_generation",
        "--disable",
        "memories",
        "--disable",
        "multi_agent",
        "--disable",
        "multi_agent_v2",
        "--disable",
        "plugins",
        "--disable",
        "tool_suggest",
        "-c",
        'web_search="disabled"',
        *permission_profile_cli_args(git_dir=git_dir, mcp_script=mcp_script),
        "-c",
        'shell_environment_policy.inherit="core"',
        "-c",
        "shell_environment_policy.ignore_default_excludes=false",
        "-c",
        "shell_environment_policy.experimental_use_profile=false",
        "-c",
        f"shell_environment_policy.set={{{git_environment}}}",
        "-c",
        f"mcp_servers.workflow-environment-factory.command={_toml_string(node_executable)}",
        "-c",
        f"mcp_servers.workflow-environment-factory.args=[{_toml_string(str(mcp_script.resolve()))}]",
        "-c",
        (
            "mcp_servers.workflow-environment-factory.env="
            f"{{WEF_AGENT_TOKEN={_toml_string(agent_token)},"
            f"WEF_RUN_ID={_toml_string(str(UUID(str(run_id))))},WEF_PORT={_toml_string(str(port))}}}"
        ),
        "-c",
        "mcp_servers.workflow-environment-factory.required=true",
        "--ask-for-approval",
        "never",
        "--thread-source",
        "workflow-environment-factory",
        "-C",
        str(workspace.resolve()),
        prompt,
    ]


def _is_infrastructure_failure(stdout: str, stderr: str) -> bool:
    combined = f"{stdout}\n{stderr}".lower()
    markers = (
        "windows sandbox",
        "apply deny-read acls",
        "failed to create unified exec process",
        "not logged in",
        "authentication failed",
        "unauthorized",
        "rate limit",
        "model is not available",
        "failed to connect",
        "connection error",
    )
    return any(marker in combined for marker in markers)


class CodexRunner:
    def __init__(
        self,
        store: FactoryStore,
        executable: str = "codex",
        preflight: WorkspacePreflight | None = None,
        port: int = 43121,
        mcp_script: Path | None = None,
        token_path: Path | None = None,
    ):
        self.store = store
        self.executable = executable
        self.preflight = preflight or CodexWorkspacePreflight(executable)
        self.port = port
        self.mcp_script = mcp_script or (
            Path(__file__).resolve().parents[2]
            / "plugins"
            / "workflow-environment-factory"
            / "scripts"
            / "mcp-server.mjs"
        )
        self.token_path = token_path or (self.store.database_path.parent / "session-token")

    def execute(self, run_id: UUID | str) -> None:
        run = self.store.get_run(run_id)
        if run is None:
            raise KeyError("run not found")
        if run.status == RunStatus.READY:
            run = self.store.claim_ready_run(run_id)
            if run is None:
                raise ValueError("run was already claimed by another executor")
        if run.status != RunStatus.QUEUED:
            raise ValueError(f"run cannot start from status {run.status}")
        case = self.store.get_case(run.case_id)
        if case is None:
            raise KeyError("case not found")
        blueprint = self.store.get_blueprint(case.blueprint_id)
        if blueprint is None:
            raise KeyError("blueprint not found")
        prompt = case.protocol_case["goal"]["text"]
        if blueprint.payload.kind == BlueprintKind.ISSUE_PR:
            assert blueprint.payload.issue is not None
            issue_key = blueprint.payload.issue.key.replace("{value}", case.variable_value)
            prompt += (
                f"\n\nUse the Workflow Environment Factory simulator tools for Run {run.run_id}. "
                f"Read Issue {issue_key}, create a linked pull request targeting {blueprint.payload.issue.pr_target}, "
                f"and move the Issue to {blueprint.payload.issue.target_status}."
            )
        started = time.monotonic()
        workspace = Path(run.workspace_path).resolve()
        environment = GitWorkspaceManager.isolated_environment(workspace)
        try:
            self.preflight.check(
                workspace,
                environment,
                database_path=self.store.database_path,
                repository_root=Path(blueprint.repository_root),
                solution_commit=blueprint.solution_commit,
                mcp_script=self.mcp_script,
            )
        except Exception as error:
            run.status = RunStatus.ENVIRONMENT_ERROR
            run.error = str(redact(f"Codex workspace preflight failed before model execution: {error}"))
            run.completed_at = utc_now()
            run.codex_events.append(redact({"type": "environment_preflight_failed", "error": str(error)}))
            run.codex_events.append(
                {"type": "runner_duration", "duration_ms": int((time.monotonic() - started) * 1_000)}
            )
            self.store.save_run(run)
            return
        run.codex_events.append(
            {"type": "environment_preflight_passed", "network_access": False, "writable_root_count": 1}
        )
        command = build_codex_command(
            self.executable,
            workspace,
            prompt,
            environment,
            mcp_script=self.mcp_script,
            agent_token=derive_agent_token(load_or_create_token(self.token_path), run.run_id),
            run_id=run.run_id,
            port=self.port,
        )
        run.status = RunStatus.RUNNING
        self.store.save_run(run)
        process: subprocess.Popen[str] | None = None
        try:
            process = subprocess.Popen(
                command,
                cwd=workspace,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=False,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
            run.agent_attempted = True
            run.attempt_origin = AttemptOrigin.CODEX_PROCESS
            run.model_executed = None
            self.store.save_run(run)
            stdout, stderr = process.communicate(timeout=blueprint.payload.timeout_ms / 1_000)
            for line in stdout.splitlines():
                if not line.strip():
                    continue
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    event = {"type": "unparsed_output", "text": line}
                run.codex_events.append(redact(event))
            if stderr.strip():
                run.codex_events.append(redact({"type": "stderr", "text": stderr}))
            if process.returncode == 0:
                run.status = RunStatus.COMPLETED
            elif _is_infrastructure_failure(stdout, stderr):
                run.status = RunStatus.ENVIRONMENT_ERROR
                run.error = f"Codex infrastructure failed with exit code {process.returncode}."
            else:
                run.status = RunStatus.AGENT_CRASH
                run.error = f"Codex exited with code {process.returncode}."
        except subprocess.TimeoutExpired:
            assert process is not None
            process.kill()
            stdout, stderr = process.communicate()
            run.codex_events.append(redact({"type": "timeout_output", "stdout": stdout, "stderr": stderr}))
            run.status = RunStatus.AGENT_TIMEOUT
            run.error = f"Codex exceeded the {blueprint.payload.timeout_ms} ms Case timeout."
        except OSError as error:
            run.status = RunStatus.ENVIRONMENT_ERROR
            run.error = str(redact(f"Codex process could not start: {error}"))
        finally:
            run.completed_at = utc_now()
            run.codex_events.append(
                {"type": "runner_duration", "duration_ms": int((time.monotonic() - started) * 1_000)}
            )
            self.store.save_run(run)
