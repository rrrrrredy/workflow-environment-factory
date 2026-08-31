from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import tempfile
from pathlib import Path

from workflow_environment_factory.app_server_preflight import CodexWorkspacePreflight
from workflow_environment_factory.gitops import GitWorkspaceManager

WINDOWS_DENY_READ_ACL_ERROR = "windows sandbox: helper_unknown_error: apply deny-read ACLs"


def run(*argv: str, cwd: Path | None = None) -> str:
    completed = subprocess.run(
        list(argv),
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
        shell=False,
        check=True,
    )
    return completed.stdout.strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Prove that the Codex Agent shell cannot read factory answers")
    parser.add_argument("--codex", default="codex")
    parser.add_argument("--evidence", required=True)
    parser.add_argument(
        "--allow-known-windows-unsupported",
        action="store_true",
        help="Record the exact native-Windows deny-read ACL limitation without treating Agent execution as supported",
    )
    arguments = parser.parse_args()
    repository_root = Path(__file__).resolve().parents[1]
    mcp_script = repository_root / "plugins" / "workflow-environment-factory" / "scripts" / "mcp-server.mjs"
    codex = shutil.which(arguments.codex) or arguments.codex
    command_prefix = [codex]
    if os.name == "nt" and Path(codex).suffix.lower() in {".cmd", ".bat"}:
        command_prefix = [os.environ.get("COMSPEC", "cmd.exe"), "/d", "/c", codex]
    evidence_path = Path(arguments.evidence).resolve()
    evidence_path.parent.mkdir(parents=True, exist_ok=True)
    codex_version = run(*command_prefix, "--version")

    try:
        with tempfile.TemporaryDirectory(prefix="wef-read-isolation-") as temporary:
            root = Path(temporary).resolve()
            data_dir = root / "factory-data"
            data_dir.mkdir()
            database = data_dir / "factory.sqlite3"
            database.write_text("FORBIDDEN_DATABASE_CANARY", encoding="utf-8")

            source = root / "source-repository"
            source.mkdir()
            (source / "known-correct.txt").write_text("FORBIDDEN_SOLUTION_CANARY", encoding="utf-8")
            run("git", "init", "-b", "main", str(source))
            run("git", "-C", str(source), "add", "known-correct.txt")
            run(
                "git",
                "-C",
                str(source),
                "-c",
                "user.name=WEF Read Isolation Gate",
                "-c",
                "user.email=wef-read-isolation@example.invalid",
                "commit",
                "-m",
                "known correct state",
            )
            solution_commit = run("git", "-C", str(source), "rev-parse", "HEAD")

            workspace_parent = data_dir / "worktrees" / "gate-run"
            workspace = workspace_parent / "workspace"
            workspace.mkdir(parents=True)
            (workspace_parent / "git-state").mkdir()
            environment = GitWorkspaceManager.isolated_environment(workspace)
            environment["PATH"] = os.environ["PATH"]

            CodexWorkspacePreflight(command_prefix, timeout_seconds=45).check(
                workspace,
                environment,
                database_path=database,
                repository_root=source,
                solution_commit=solution_commit,
                mcp_script=mcp_script,
            )
    except BaseException as error:
        error_text = f"{type(error).__name__}: {error}"
        known_windows_unsupported = (
            arguments.allow_known_windows_unsupported
            and os.name == "nt"
            and WINDOWS_DENY_READ_ACL_ERROR in str(error)
        )
        evidence_path.write_text(
            json.dumps(
                {
                    "schema": "wef.codex-read-isolation.v1",
                    "platform": platform.system().lower(),
                    "machine": platform.machine().lower(),
                    "codex_version": codex_version,
                    "status": "known_unsupported" if known_windows_unsupported else "failed",
                    "agent_execution_supported": False,
                    "limitation": "native_windows_deny_read_acl_unavailable" if known_windows_unsupported else None,
                    "error": error_text,
                    "model_executed": False,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )
        if known_windows_unsupported:
            print(f"Known unsupported native-Windows read isolation recorded: {evidence_path}")
            return 0
        raise

    evidence_path.write_text(
        json.dumps(
            {
                "schema": "wef.codex-read-isolation.v1",
                "platform": platform.system().lower(),
                "machine": platform.machine().lower(),
                "codex_version": codex_version,
                "status": "passed",
                "agent_execution_supported": True,
                "workspace_write": "pass",
                "product_database_read": "blocked",
                "source_solution_commit_read": "blocked",
                "model_executed": False,
            },
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"Codex read-isolation gate passed: {evidence_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
