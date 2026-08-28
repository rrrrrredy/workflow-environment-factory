from __future__ import annotations

import json
import os
from pathlib import Path

from synthetic_server import blueprint_payload, create_repository, make_correct
from workflow_environment_factory.config import Settings, ensure_factory_data_root
from workflow_environment_factory.engine import DockerEngine
from workflow_environment_factory.models import RecordingEvent
from workflow_environment_factory.services import Services


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    data_dir = Path(os.environ["WEF_DOCKER_GATE_DATA_DIR"]).resolve()
    image = os.environ["WEF_DOCKER_GATE_IMAGE"]
    settings = Settings(
        host="127.0.0.1",
        port=43121,
        data_dir=data_dir,
        database_path=data_dir / "factory.sqlite3",
        content_dir=data_dir / "content",
        worktrees_dir=data_dir / "worktrees",
        simulator_dir=data_dir / "simulators",
        token_path=data_dir / "session-token",
        protocol_schema_dir=root / ".runtime-deps" / "runcase-interchange" / "0.1.0" / "schemas",
        codex_executable="codex",
        docker_executable=os.getenv("DOCKER_EXECUTABLE", "docker"),
        web_root=root / "dist" / "web",
    )
    ensure_factory_data_root(settings.data_dir)
    for directory in (settings.content_dir, settings.worktrees_dir, settings.simulator_dir):
        directory.mkdir(parents=True, exist_ok=True)
    services = Services.build(settings, DockerEngine(settings.docker_executable))
    runs = []
    try:
        repository, base, solution = create_repository(data_dir)
        recording = services.recordings.start("Docker gate Issue-to-PR demonstration")
        for event_type, data in (
            ("issue_read", {"issue_key": "APP-alpha"}),
            ("repository_changed", {"path": "app.py"}),
            ("pr_created", {"branch": "fix/app-alpha", "target": "main", "linked_issue_key": "APP-alpha"}),
            ("issue_status_updated", {"issue_key": "APP-alpha", "status": "in_review"}),
        ):
            services.recordings.append(recording.recording_id, RecordingEvent(event_type=event_type, data=data))
        recording = services.recordings.complete(recording.recording_id, confirmed=True)

        code_blueprint = services.factory.create_blueprint(
            blueprint_payload(repository, base, solution, issue=False, container_image=image)
        )
        issue_blueprint = services.factory.create_blueprint(
            blueprint_payload(
                repository,
                base,
                solution,
                issue=True,
                demonstration_id=str(recording.recording_id),
                container_image=image,
            )
        )
        code_cases = services.factory.generate_cases(code_blueprint.blueprint_id)
        issue_cases = services.factory.generate_cases(issue_blueprint.blueprint_id)
        assert len(code_cases) == 3 and all(case.validation.objective_gate_passed for case in code_cases)
        assert len(issue_cases) == 3 and all(case.validation.objective_gate_passed for case in issue_cases)
        assert all(case.protocol_case["provenance"]["confirmed_by_user"] for case in code_cases + issue_cases)

        code_wrong = services.factory.prepare_run(code_cases[0].case_id)
        runs.append(code_wrong.run_id)
        assert services.scorer.score(code_wrong.run_id)["task_result"]["status"] == "fail"
        code_correct = services.factory.prepare_run(code_cases[1].case_id)
        runs.append(code_correct.run_id)
        make_correct(Path(code_correct.workspace_path))
        assert services.scorer.score(code_correct.run_id)["task_result"]["status"] == "pass"

        issue_wrong = services.factory.prepare_run(issue_cases[0].case_id)
        runs.append(issue_wrong.run_id)
        make_correct(Path(issue_wrong.workspace_path))
        assert services.scorer.score(issue_wrong.run_id)["task_result"]["status"] == "fail"
        issue_correct = services.factory.prepare_run(issue_cases[2].case_id)
        runs.append(issue_correct.run_id)
        make_correct(Path(issue_correct.workspace_path))
        assert issue_correct.simulator_database_path is not None
        database = Path(issue_correct.simulator_database_path)
        services.simulator.get_issue(database, "APP-gamma")
        services.simulator.create_pr(
            database,
            title="Docker gate gamma fix",
            branch="fix/app-gamma",
            target="main",
            linked_issue_key="APP-gamma",
        )
        services.simulator.update_issue_status(database, "APP-gamma", "in_review")
        assert services.scorer.score(issue_correct.run_id)["task_result"]["status"] == "pass"
        output = {
            "engine": services.engine.name,
            "image": image,
            "code_cases": len(code_cases),
            "issue_pr_cases": len(issue_cases),
            "code_wrong": "fail",
            "code_correct": "pass",
            "issue_wrong": "fail",
            "issue_correct": "pass",
            "reset_gates": "all_passed",
            "provenance": "all_confirmed",
        }
        print(json.dumps(output, indent=2))
    finally:
        for run_id in runs:
            services.factory.cleanup_run(run_id)
        services.close()


if __name__ == "__main__":
    main()
