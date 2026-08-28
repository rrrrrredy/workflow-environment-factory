from __future__ import annotations

import os
import sys
from pathlib import Path

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
        sentinel = pathlib.Path(message["params"]["command"][-1])
        sentinel.write_text("ok", encoding="utf-8")
        print(json.dumps({"id": message["id"], "result": {"exitCode": 0}}), flush=True)
"""


def test_no_model_app_server_preflight_writes_and_removes_bounded_sentinel(tmp_path: Path) -> None:
    preflight = CodexWorkspacePreflight([sys.executable, "-u", "-c", _FAKE_APP_SERVER], timeout_seconds=5)
    preflight.check(tmp_path, os.environ)
    assert list(tmp_path.glob(".workflow-environment-preflight-*")) == []


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
        data_dir=tmp_path / "data",
        port=43121,
    )
    rendered = "\n".join(command)
    assert "--ephemeral" in command
    assert "--ignore-user-config" in command
    assert "--skip-git-repo-check" in command
    assert "--strict-config" in command
    assert "sandbox_workspace_write.network_access=false" in command
    assert "sandbox_workspace_write.writable_roots=[]" in command
    assert 'shell_environment_policy.inherit="core"' in command
    assert "shell_environment_policy.ignore_default_excludes=false" in command
    assert "shell_environment_policy.experimental_use_profile=false" in command
    assert "GIT_DIR=" in rendered and "GIT_WORK_TREE=" in rendered
    assert 'web_search="disabled"' in command
    assert "mcp_servers.workflow-environment-factory.required=true" in command
    assert str(mcp_script.resolve()).replace("\\", "\\\\") in rendered
    assert "synthetic-command-secret-12345678" not in rendered
