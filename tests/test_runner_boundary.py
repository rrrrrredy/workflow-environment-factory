from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from uuid import uuid4

from workflow_environment_factory.app_server_preflight import CodexWorkspacePreflight
from workflow_environment_factory.gitops import GitWorkspaceManager
from workflow_environment_factory.runner import build_codex_command

_FAKE_APP_SERVER = r"""
import json
import pathlib
import sys

for line in sys.stdin:
    message = json.loads(line)
    if message.get("method") == "initialize":
        print(json.dumps({"id": message["id"], "result": {"serverInfo": {"name": "fake"}}}), flush=True)
    elif message.get("method") == "command/exec":
        if message["params"].get("permissionProfile") != "wef_run":
            raise SystemExit("missing restricted permission profile")
        command = message["params"]["command"]
        if "apply" in command:
            patch = pathlib.Path(command[-1])
            marker = next(
                line[6:]
                for line in patch.read_text(encoding="utf-8").splitlines()
                if line.startswith("+++ b/")
            )
            (pathlib.Path(message["params"]["cwd"]) / marker).write_text("write-ok\n", encoding="utf-8")
            exit_code = 0
        elif "hash-object" in command or any(item.startswith("--git-dir=") for item in command):
            exit_code = 1
        else:
            exit_code = 0
        print(json.dumps({"id": message["id"], "result": {"exitCode": exit_code}}), flush=True)
"""


def test_no_model_app_server_preflight_writes_and_removes_bounded_sentinel(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    git_dir = tmp_path / "git-state"
    git_dir.mkdir()
    database = tmp_path / "factory.sqlite3"
    database.write_text("synthetic known-answer canary", encoding="utf-8")
    source = tmp_path / "source"
    source.mkdir()
    (source / "answer.txt").write_text("known correct", encoding="utf-8")
    subprocess.run(["git", "init", "-b", "main", str(source)], check=True, capture_output=True, text=True)
    subprocess.run(["git", "-C", str(source), "add", "answer.txt"], check=True, capture_output=True, text=True)
    subprocess.run(
        [
            "git",
            "-C",
            str(source),
            "-c",
            "user.name=WEF Test",
            "-c",
            "user.email=wef@example.invalid",
            "commit",
            "-m",
            "known correct",
        ],
        check=True,
        capture_output=True,
        text=True,
    )
    solution = subprocess.run(
        ["git", "-C", str(source), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    mcp_script = tmp_path / "mcp-server.mjs"
    mcp_script.write_text("// reviewed synthetic MCP", encoding="utf-8")
    environment = dict(os.environ)
    environment.update({"GIT_DIR": str(git_dir), "GIT_WORK_TREE": str(workspace)})
    preflight = CodexWorkspacePreflight([sys.executable, "-u", "-c", _FAKE_APP_SERVER], timeout_seconds=5)
    preflight.check(
        workspace,
        environment,
        database_path=database,
        repository_root=source,
        solution_commit=solution,
        mcp_script=mcp_script,
    )
    assert list(workspace.glob(".workflow-environment-preflight-*")) == []


def test_codex_command_overrides_network_writable_roots_and_shell_environment(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    environment = GitWorkspaceManager.isolated_environment(workspace)
    environment["GITHUB_TOKEN"] = "synthetic-command-secret-12345678"
    mcp_script = tmp_path / "mcp-server.mjs"
    mcp_script.write_text("// synthetic", encoding="utf-8")
    command = build_codex_command(
        "codex",
        workspace,
        "Synthetic task",
        environment,
        mcp_script=mcp_script,
        agent_token="synthetic-run-scoped-token",
        run_id=uuid4(),
        port=43121,
    )
    rendered = "\n".join(command)
    assert "--ephemeral" in command
    assert "--ignore-user-config" in command
    assert "--skip-git-repo-check" in command
    assert "--strict-config" in command
    assert any(item.startswith('default_permissions="wef_run"') for item in command)
    assert any(item.startswith("permissions.wef_run.filesystem=") for item in command)
    assert "permissions.wef_run.network={enabled=false}" in command
    assert "--sandbox" not in command
    assert "--approve-for-me" not in command
    assert command[command.index("--ask-for-approval") + 1] == "never"
    assert 'shell_environment_policy.inherit="core"' in command
    assert "shell_environment_policy.ignore_default_excludes=false" in command
    assert "shell_environment_policy.experimental_use_profile=false" in command
    assert "GIT_DIR=" in rendered and "GIT_WORK_TREE=" in rendered
    assert 'web_search="disabled"' in command
    assert "mcp_servers.workflow-environment-factory.required=true" in command
    assert str(mcp_script.resolve()).replace("\\", "\\\\") in rendered
    assert "WEF_AGENT_TOKEN" in rendered and "WEF_RUN_ID" in rendered
    assert "WEF_DATA_DIR" not in rendered
    assert "synthetic-command-secret-12345678" not in rendered


def test_mcp_uses_only_run_scoped_credentials_and_enforces_active_run() -> None:
    script = Path("plugins/workflow-environment-factory/scripts/mcp-server.mjs").read_text(encoding="utf-8")
    assert "WEF_AGENT_TOKEN" in script
    assert "WEF_RUN_ID" in script
    assert "requireActiveRun(args)" in script
    assert "WEF_DATA_DIR" not in script
    assert "session-token" not in script
