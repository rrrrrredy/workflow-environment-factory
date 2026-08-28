from __future__ import annotations

import json
import os
import platform
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from synthetic_server import blueprint_payload, create_repository
from workflow_environment_factory.gitops import GitWorkspaceManager


def _json_request(
    base_url: str,
    token: str,
    method: str,
    path: str,
    payload: dict[str, Any] | None = None,
    *,
    timeout: int = 600,
) -> Any:
    data = None if payload is None else json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=data,
        method=method,
        headers={"authorization": f"Bearer {token}", "content-type": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        body = error.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"product API {method} {path} failed with {error.code}: {body}") from error
    return json.loads(body) if body else {}


def _wait_for_score(base_url: str, token: str, run_id: str, timeout_seconds: int = 300) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last_status = "unknown"
    while time.monotonic() < deadline:
        snapshot = _json_request(base_url, token, "GET", f"/api/runs/{run_id}", timeout=30)
        last_status = snapshot["run"]["status"]
        if snapshot.get("score") is not None:
            return snapshot
        if last_status in {"agent_timeout", "agent_crash", "reset_error", "environment_error"}:
            raise RuntimeError(f"real Codex Run ended without a Score: {last_status}")
        time.sleep(0.5)
    raise TimeoutError(f"real Codex Run did not produce a Score within {timeout_seconds}s; last={last_status}")


def _command_text(command: list[str], cwd: Path) -> str:
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, check=False, shell=False)
    if result.returncode != 0:
        raise RuntimeError(f"command failed: {' '.join(command)}")
    return (result.stdout or result.stderr).strip()


def _event_types(snapshot: dict[str, Any]) -> list[str]:
    return sorted(
        {
            str(event.get("type", "unknown"))
            for event in snapshot["run"].get("codex_events", [])
            if isinstance(event, dict)
        }
    )


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    data_dir = Path(os.environ["WEF_REAL_GATE_DATA_DIR"]).resolve()
    output_path = Path(os.environ["WEF_REAL_GATE_OUTPUT"]).resolve()
    image = os.environ["WEF_DOCKER_GATE_IMAGE"]
    port = int(os.getenv("WEF_REAL_GATE_PORT", "43131"))
    base_url = f"http://127.0.0.1:{port}"
    token = (data_dir / "session-token").read_text(encoding="utf-8").strip()
    prepared: list[tuple[str, Path, Path]] = []
    cleanup_verified = False

    repository, base_commit, solution_commit = create_repository(data_dir)
    recording = _json_request(
        base_url,
        token,
        "POST",
        "/api/recordings",
        {"name": "Real Codex Issue-to-PR release gate"},
    )
    for event_type, event_data in (
        ("issue_read", {"issue_key": "APP-alpha"}),
        ("repository_changed", {"path": "app.py"}),
        ("pr_created", {"branch": "fix/app-alpha", "target": "main", "linked_issue_key": "APP-alpha"}),
        ("issue_status_updated", {"issue_key": "APP-alpha", "status": "in_review"}),
    ):
        _json_request(
            base_url,
            token,
            "POST",
            f"/api/recordings/{recording['recording_id']}/events",
            {"event_type": event_type, "data": event_data},
        )
    _json_request(
        base_url,
        token,
        "POST",
        f"/api/recordings/{recording['recording_id']}/complete",
        {"confirmed": True},
    )

    code_payload = blueprint_payload(repository, base_commit, solution_commit, issue=False, container_image=image)
    issue_payload = blueprint_payload(
        repository,
        base_commit,
        solution_commit,
        issue=True,
        demonstration_id=recording["recording_id"],
        container_image=image,
    )
    code_payload.timeout_ms = 180_000
    issue_payload.timeout_ms = 240_000
    code_blueprint = _json_request(
        base_url, token, "POST", "/api/blueprints", code_payload.model_dump(mode="json")
    )
    issue_blueprint = _json_request(
        base_url, token, "POST", "/api/blueprints", issue_payload.model_dump(mode="json")
    )
    code_generation = _json_request(
        base_url, token, "POST", f"/api/blueprints/{code_blueprint['blueprint_id']}/generate"
    )
    issue_generation = _json_request(
        base_url, token, "POST", f"/api/blueprints/{issue_blueprint['blueprint_id']}/generate"
    )
    code_cases = code_generation["cases"]
    issue_cases = issue_generation["cases"]
    if len(code_cases) != 3 or not code_generation["all_gates_passed"]:
        raise RuntimeError("real Codex gate code Cases did not pass generation")
    if len(issue_cases) != 3 or not issue_generation["all_gates_passed"]:
        raise RuntimeError("real Codex gate Issue-to-PR Cases did not pass generation")

    safe_case = _json_request(base_url, token, "GET", f"/api/agent/cases/{code_cases[1]['case_id']}")
    safe_case_json = json.dumps(safe_case, sort_keys=True)
    safe_view_omits_factory_evidence = (
        solution_commit not in safe_case_json
        and code_blueprint["solution_patch_digest"] not in safe_case_json
        and "provenance" not in safe_case
    )

    code_run = _json_request(base_url, token, "POST", f"/api/cases/{code_cases[1]['case_id']}/runs")
    code_workspace = Path(code_run["workspace_path"])
    code_git_dir = GitWorkspaceManager.isolated_git_dir(code_workspace)
    prepared.append((code_run["run_id"], code_workspace, code_git_dir))
    no_dot_git = not (code_workspace / ".git").exists()
    no_remote = GitWorkspaceManager.run_isolated(code_workspace, ["remote"]).stdout.strip() == ""
    no_alternates = not (code_git_dir / "objects" / "info" / "alternates").exists()
    solution_unavailable = (
        GitWorkspaceManager.run_isolated(
            code_workspace, ["cat-file", "-e", f"{solution_commit}^{{commit}}"]
        ).exit_code
        != 0
    )
    _json_request(base_url, token, "POST", f"/api/runs/{code_run['run_id']}/execute")
    code_snapshot = _wait_for_score(base_url, token, code_run["run_id"])
    if code_snapshot["score"]["task_result"]["status"] != "pass":
        raise RuntimeError("real Codex code Run did not pass objective scoring")

    issue_run = _json_request(base_url, token, "POST", f"/api/cases/{issue_cases[2]['case_id']}/runs")
    issue_workspace = Path(issue_run["workspace_path"])
    issue_git_dir = GitWorkspaceManager.isolated_git_dir(issue_workspace)
    prepared.append((issue_run["run_id"], issue_workspace, issue_git_dir))
    _json_request(base_url, token, "POST", f"/api/runs/{issue_run['run_id']}/execute")
    issue_snapshot = _wait_for_score(base_url, token, issue_run["run_id"], timeout_seconds=360)
    if issue_snapshot["score"]["task_result"]["status"] != "pass":
        raise RuntimeError("real Codex Issue-to-PR Run did not pass objective scoring")
    simulator_events = _json_request(
        base_url, token, "GET", f"/api/simulator/runs/{issue_run['run_id']}/events"
    )["events"]
    simulator_event_types = {event["event_type"] for event in simulator_events}
    required_actions = {"issue_read", "pr_created", "issue_status_updated"}
    if not required_actions.issubset(simulator_event_types):
        raise RuntimeError("real Codex Issue-to-PR Run did not perform every required MCP simulator action")

    task_pack = _json_request(
        base_url, token, "GET", f"/api/blueprints/{issue_blueprint['blueprint_id']}/export"
    )
    issue_score = _json_request(base_url, token, "GET", f"/api/runs/{issue_run['run_id']}/score/export")
    code_score = _json_request(base_url, token, "GET", f"/api/runs/{code_run['run_id']}/score/export")

    for run_id, _, _ in prepared:
        _json_request(base_url, token, "POST", f"/api/runs/{run_id}/cleanup")
    cleanup_verified = all(not workspace.exists() and not git_dir.exists() for _, workspace, git_dir in prepared)
    if not cleanup_verified:
        raise RuntimeError("real Codex gate left a Run workspace or isolated Git directory")

    tested_commit = _command_text(["git", "rev-parse", "HEAD"], root)
    if len(tested_commit) != 40:
        raise RuntimeError("real Codex gate must run from a committed checkout")
    codex_version = _command_text([os.getenv("CODEX_EXECUTABLE", "codex"), "--version"], root)
    evidence = {
        "schema_version": "product.real-codex-gate.v1",
        "product": "workflow-environment-factory",
        "version": "0.1.0",
        "testedCommit": tested_commit,
        "platform": {"system": platform.system(), "release": platform.release(), "python": platform.python_version()},
        "codexVersion": codex_version,
        "dockerImage": image,
        "cases": {
            "codeGenerated": len(code_cases),
            "issuePrGenerated": len(issue_cases),
            "allGenerationGatesPassed": True,
            "taskPackCaseCount": len(task_pack["cases"]),
        },
        "isolation": {
            "noDotGitInAgentWorkspace": no_dot_git,
            "noRemote": no_remote,
            "noAlternateObjectStore": no_alternates,
            "knownCorrectObjectUnavailable": solution_unavailable,
            "agentViewOmittedFactoryEvidence": safe_view_omits_factory_evidence,
        },
        "realCodex": {
            "codeTaskStatus": code_score["task_result"]["status"],
            "codeExecutionStatus": code_score["execution"]["status"],
            "codeEventCount": len(code_snapshot["run"]["codex_events"]),
            "codeEventTypes": _event_types(code_snapshot),
            "issuePrTaskStatus": issue_score["task_result"]["status"],
            "issuePrExecutionStatus": issue_score["execution"]["status"],
            "issuePrEventCount": len(issue_snapshot["run"]["codex_events"]),
            "issuePrEventTypes": _event_types(issue_snapshot),
            "issueRead": "issue_read" in simulator_event_types,
            "pullRequestCreated": "pr_created" in simulator_event_types,
            "issueStatusUpdated": "issue_status_updated" in simulator_event_types,
            "singleRunEvidence": True,
        },
        "protocol": {
            "case": issue_cases[0]["protocol_case"]["schema_version"],
            "score": issue_score["schema_version"],
        },
        "probeCleanup": {"runCount": len(prepared), "workspacesAndGitStateRemoved": cleanup_verified},
        "dataPolicy": {
            "fullySynthetic": True,
            "containsPromptOrRepositoryContent": False,
            "containsCredentialOrLocalPath": False,
        },
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(evidence, indent=2))


if __name__ == "__main__":
    main()
