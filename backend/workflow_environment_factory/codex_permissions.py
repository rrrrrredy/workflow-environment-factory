from __future__ import annotations

import json
from pathlib import Path

PROFILE_ID = "wef_run"


def _toml_string(value: str) -> str:
    return json.dumps(value, ensure_ascii=False)


def permission_profile_overrides(*, git_dir: Path, mcp_script: Path) -> list[str]:
    """Build one fail-closed profile shared by preflight and model execution."""
    filesystem = {
        ":minimal": "read",
        ":workspace_roots": "write",
        str(git_dir.resolve()): "write",
        str(mcp_script.resolve()): "read",
    }
    entries = ",".join(f"{_toml_string(path)}={_toml_string(access)}" for path, access in filesystem.items())
    return [
        f"default_permissions={_toml_string(PROFILE_ID)}",
        f"permissions.{PROFILE_ID}.filesystem={{{entries}}}",
        f"permissions.{PROFILE_ID}.network={{enabled=false}}",
    ]


def permission_profile_cli_args(*, git_dir: Path, mcp_script: Path) -> list[str]:
    arguments: list[str] = []
    for override in permission_profile_overrides(git_dir=git_dir, mcp_script=mcp_script):
        arguments.extend(("-c", override))
    return arguments
