from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path
from uuid import UUID

from .models import BlueprintKind, RunStatus, utc_now
from .redaction import redact
from .store import FactoryStore


class CodexRunner:
    def __init__(self, store: FactoryStore, executable: str = "codex"):
        self.store = store
        self.executable = executable

    def execute(self, run_id: UUID | str) -> None:
        run = self.store.get_run(run_id)
        if run is None:
            raise KeyError("run not found")
        if run.status != RunStatus.READY:
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
        command = [
            self.executable,
            "exec",
            "--json",
            "--color",
            "never",
            "--sandbox",
            "workspace-write",
            "--approve-for-me",
            "-C",
            run.workspace_path,
            prompt,
        ]
        run.status = RunStatus.RUNNING
        self.store.save_run(run)
        started = time.monotonic()
        process: subprocess.Popen[str] | None = None
        try:
            process = subprocess.Popen(
                command,
                cwd=Path(run.workspace_path),
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                shell=False,
                creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0,
            )
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
            run.status = RunStatus.AGENT_CRASH
            run.error = str(error)
        finally:
            run.completed_at = utc_now()
            run.codex_events.append(
                {"type": "runner_duration", "duration_ms": int((time.monotonic() - started) * 1_000)}
            )
            self.store.save_run(run)
