from __future__ import annotations

import os
import subprocess
from pathlib import Path

import uvicorn
from workflow_environment_factory.app import create_app
from workflow_environment_factory.auth import load_or_create_token
from workflow_environment_factory.config import Settings, ensure_factory_data_root
from workflow_environment_factory.engine import LocalTestEngine
from workflow_environment_factory.models import AttemptOrigin, BlueprintCreate, RecordingEvent, RunStatus, utc_now
from workflow_environment_factory.services import Services


def run_git(repository: Path, *arguments: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        capture_output=True,
        text=True,
        check=True,
        shell=False,
    )
    return result.stdout.strip()


def create_repository(root: Path) -> tuple[Path, str, str]:
    repository = root / "synthetic-repository"
    repository.mkdir(parents=True)
    repository.joinpath("app.py").write_text(
        'LABEL = "alpha"\n\n\ndef normalize(value: str) -> str:\n    return value.strip()\n',
        encoding="utf-8",
    )
    repository.joinpath("verify.py").write_text(
        "import app\n"
        "expected = app.LABEL.lower()\n"
        "actual = app.normalize(f'  {app.LABEL.upper()}  ')\n"
        "raise SystemExit(0 if actual == expected else 1)\n",
        encoding="utf-8",
    )
    run_git(repository, "init", "-b", "main")
    run_git(repository, "add", "app.py", "verify.py")
    run_git(
        repository,
        "-c",
        "user.name=WEF Synthetic",
        "-c",
        "user.email=synthetic@example.invalid",
        "commit",
        "-m",
        "synthetic failing baseline",
    )
    base = run_git(repository, "rev-parse", "HEAD")
    repository.joinpath("app.py").write_text(
        'LABEL = "alpha"\n\n\ndef normalize(value: str) -> str:\n    return value.strip().lower()\n',
        encoding="utf-8",
    )
    run_git(repository, "add", "app.py")
    run_git(
        repository,
        "-c",
        "user.name=WEF Synthetic",
        "-c",
        "user.email=synthetic@example.invalid",
        "commit",
        "-m",
        "synthetic correct state",
    )
    return repository, base, run_git(repository, "rev-parse", "HEAD")


def blueprint_payload(
    repository: Path,
    base: str,
    solution: str,
    *,
    issue: bool,
    demonstration_id: str | None = None,
    container_image: str | None = None,
) -> BlueprintCreate:
    payload: dict[str, object] = {
        "name": "Synthetic Issue-to-PR workflow" if issue else "Synthetic label normalization",
        "kind": "issue_pr" if issue else "code",
        "repository_path": str(repository),
        "base_revision": base,
        "solution_revision": solution,
        "title_template": "Resolve APP-{value}" if issue else "Normalize the {value} label",
        "goal_template": (
            "Read APP-{value}, fix normalization, create a linked local PR, and move it to In Review."
            if issue
            else "Fix normalization for the confirmed {value} label and pass the objective verifier."
        ),
        "completion_summary": (
            "Code passes, a linked local PR targets main, and APP-{value} is In Review."
            if issue
            else "The verifier passes with changes limited to app.py."
        ),
        "external_ref": "simulator:issue:APP-{value}" if issue else "local-issue:normalize-{value}",
        "variable": {
            "name": "label",
            "original": "alpha",
            "variants": ["beta", "gamma"],
            "paths": ["app.py"],
            "confirmed_by_user": True,
            "description": "A fully synthetic confirmed label used only for the product preview.",
        },
        "container_image": container_image or f"python@sha256:{('2' if issue else '1') * 64}",
        "verifier": {"argv": ["python", "verify.py"], "timeout_ms": 10_000},
        "allowed_paths": ["app.py"],
        "allowed_tools": ["shell", "file", "git", "simulator-mcp"] if issue else ["shell", "file", "git"],
        "timeout_ms": 60_000,
    }
    if issue:
        payload["issue"] = {
            "key": "APP-{value}",
            "title": "Normalize the {value} label",
            "body": "The synthetic {value} fixture fails the objective verifier.",
            "initial_status": "open",
            "target_status": "in_review",
            "pr_target": "main",
        }
        payload["demonstration_id"] = demonstration_id
    return BlueprintCreate.model_validate(payload)


def mark_synthetic_attempt(services: Services, run, status: RunStatus = RunStatus.COMPLETED):
    run.agent_attempted = True
    run.attempt_origin = AttemptOrigin.SYNTHETIC_FIXTURE
    run.model_executed = False
    run.status = status
    run.codex_events.append(
        {
            "type": "gate.synthetic_attempt",
            "source": "fully-synthetic-ui-fixture",
            "model_executed": False,
        }
    )
    services.store.save_run(run)
    return run


def make_correct(workspace: Path) -> None:
    target = workspace / "app.py"
    target.write_text(
        target.read_text(encoding="utf-8").replace("return value.strip()", "return value.strip().lower()"),
        encoding="utf-8",
    )


def seed(services: Services, data_dir: Path) -> None:
    repository, base, solution = create_repository(data_dir)
    recording = services.recordings.start("Synthetic confirmed Issue-to-PR demonstration")
    for event_type, data in (
        ("issue_read", {"issue_key": "APP-alpha"}),
        ("repository_changed", {"path": "app.py"}),
        ("pr_created", {"branch": "fix/app-alpha", "target": "main", "linked_issue_key": "APP-alpha"}),
        ("issue_status_updated", {"issue_key": "APP-alpha", "status": "in_review"}),
    ):
        services.recordings.append(recording.recording_id, RecordingEvent(event_type=event_type, data=data))
    recording = services.recordings.complete(recording.recording_id, confirmed=True)

    code_blueprint = services.factory.create_blueprint(blueprint_payload(repository, base, solution, issue=False))
    issue_blueprint = services.factory.create_blueprint(
        blueprint_payload(repository, base, solution, issue=True, demonstration_id=str(recording.recording_id))
    )
    code_cases = services.factory.generate_cases(code_blueprint.blueprint_id)
    issue_cases = services.factory.generate_cases(issue_blueprint.blueprint_id)

    failed = services.factory.prepare_run(code_cases[0].case_id)
    mark_synthetic_attempt(services, failed)
    services.scorer.score(failed.run_id, allow_synthetic_fixture=True)

    passing = services.factory.prepare_run(issue_cases[1].case_id)
    make_correct(Path(passing.workspace_path))
    assert passing.simulator_database_path is not None
    issue_key = "APP-beta"
    services.simulator.get_issue(Path(passing.simulator_database_path), issue_key)
    services.simulator.create_pr(
        Path(passing.simulator_database_path),
        title="Synthetic beta fix",
        branch="fix/app-beta",
        target="main",
        linked_issue_key=issue_key,
    )
    services.simulator.update_issue_status(Path(passing.simulator_database_path), issue_key, "in_review")
    mark_synthetic_attempt(services, passing)
    services.scorer.score(passing.run_id, allow_synthetic_fixture=True)

    interrupted = services.factory.prepare_run(code_cases[2].case_id)
    mark_synthetic_attempt(services, interrupted, RunStatus.AGENT_TIMEOUT)
    interrupted.error = "Synthetic Codex attempt reached its Case timeout."
    interrupted.completed_at = utc_now()
    services.store.save_run(interrupted)
    services.scorer.score(interrupted.run_id, allow_synthetic_fixture=True)

    for index, run in enumerate(services.store.list_runs(), start=1):
        run.workspace_path = f"C:\\demo\\workflow-environment-factory\\run-{index}"
        if run.simulator_database_path:
            run.simulator_database_path = f"C:\\demo\\workflow-environment-factory\\simulator-{index}.sqlite3"
        services.store.save_run(run)


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    data_dir = Path(os.environ["WEF_SYNTHETIC_DATA_DIR"]).resolve()
    port = int(os.getenv("WEF_SYNTHETIC_PORT", "43141"))
    settings = Settings(
        host="127.0.0.1",
        port=port,
        data_dir=data_dir,
        database_path=data_dir / "factory.sqlite3",
        content_dir=data_dir / "content",
        worktrees_dir=data_dir / "worktrees",
        simulator_dir=data_dir / "simulators",
        token_path=data_dir / "session-token",
        protocol_schema_dir=root / ".runtime-deps" / "runcase-interchange" / "0.1.2" / "schemas",
        codex_executable="codex",
        docker_executable="synthetic-no-docker",
        web_root=root / "dist" / "web",
    )
    ensure_factory_data_root(settings.data_dir)
    for directory in (settings.content_dir, settings.worktrees_dir, settings.simulator_dir):
        directory.mkdir(parents=True, exist_ok=True)
    services = Services.build(settings, LocalTestEngine())
    try:
        seed(services, data_dir)
        load_or_create_token(settings.token_path)
        uvicorn.run(create_app(services), host=settings.host, port=settings.port, access_log=False, log_level="warning")
    finally:
        services.close()


if __name__ == "__main__":
    main()
