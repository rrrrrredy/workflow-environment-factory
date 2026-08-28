from __future__ import annotations

from pathlib import Path

from conftest import RepositoryFixture, make_code_correct
from workflow_environment_factory.models import BlueprintCreate, RecordingEvent


def issue_blueprint(repository: RepositoryFixture, demonstration_id) -> BlueprintCreate:
    return BlueprintCreate.model_validate(
        {
            "name": "Recorded Issue-to-PR normalization flow",
            "kind": "issue_pr",
            "repository_path": str(repository.root),
            "base_revision": repository.base_commit,
            "solution_revision": repository.solution_commit,
            "title_template": "Resolve APP-{value}",
            "goal_template": (
                "Read APP-{value}, fix normalization, create a linked pull request, and move it to In Review."
            ),
            "completion_summary": "Code passes, a linked PR targets main, and APP-{value} is In Review.",
            "external_ref": "simulator:issue:APP-{value}",
            "variable": {
                "name": "label",
                "original": "alpha",
                "variants": ["beta", "gamma"],
                "paths": ["app.py"],
                "confirmed_by_user": True,
            },
            "container_image": f"python@sha256:{'2' * 64}",
            "verifier": {"argv": ["python", "verify.py"], "timeout_ms": 10_000},
            "allowed_paths": ["app.py"],
            "allowed_tools": ["shell", "file", "git", "simulator-mcp"],
            "issue": {
                "key": "APP-{value}",
                "title": "Normalize the {value} label",
                "body": "The {value} normalization fixture fails the objective verifier.",
                "initial_status": "open",
                "target_status": "in_review",
                "pr_target": "main",
            },
            "demonstration_id": str(demonstration_id),
        }
    )


def test_recorded_issue_pr_case_requires_code_and_database_state(services, repository_fixture) -> None:
    recording = services.recordings.start("Synthetic Issue-to-PR demonstration")
    for event_type, data in (
        ("issue_read", {"issue_key": "APP-alpha"}),
        ("repository_changed", {"path": "app.py"}),
        ("pr_created", {"branch": "fix/app-alpha", "target": "main", "linked_issue_key": "APP-alpha"}),
        ("issue_status_updated", {"issue_key": "APP-alpha", "status": "in_review"}),
    ):
        services.recordings.append(recording.recording_id, RecordingEvent(event_type=event_type, data=data))
    recording = services.recordings.complete(recording.recording_id, confirmed=True)
    extraction = services.recordings.extract(recording.recording_id)
    assert extraction["candidate_variables"]["target_status"] == "in_review"
    assert extraction["candidate_variables"]["pr_target"] == "main"

    blueprint = services.factory.create_blueprint(issue_blueprint(repository_fixture, recording.recording_id))
    cases = services.factory.generate_cases(blueprint.blueprint_id)
    assert len(cases) == 3
    assert all(case.validation.objective_gate_passed for case in cases)
    assert all("programmatic correct Issue/PR state passed" in case.validation.details for case in cases)
    assert cases[0].protocol_case["provenance"]["kind"] == "recorded_workflow"
    assert len(cases[0].protocol_case["validators"]) == 3

    wrong_run = services.factory.prepare_run(cases[0].case_id)
    make_code_correct(Path(wrong_run.workspace_path))
    wrong_score = services.scorer.score(wrong_run.run_id)
    assert wrong_score["task_result"]["status"] == "fail"
    issue_validation = next(row for row in wrong_score["validations"] if row["validator_id"] == "issue-pr-state")
    assert issue_validation["status"] == "fail"
    wrong_database = Path(wrong_run.simulator_database_path)
    services.factory.cleanup_run(wrong_run.run_id)
    assert not wrong_database.exists()

    correct_run = services.factory.prepare_run(cases[1].case_id)
    assert correct_run.simulator_database_path != wrong_run.simulator_database_path
    make_code_correct(Path(correct_run.workspace_path))
    database = Path(correct_run.simulator_database_path)
    issue_key = "APP-beta"
    assert services.simulator.get_issue(database, issue_key)["status"] == "open"
    services.simulator.create_pr(
        database,
        title="Normalize beta",
        branch="fix/app-beta",
        target="main",
        linked_issue_key=issue_key,
    )
    services.simulator.update_issue_status(database, issue_key, "in_review")
    correct_score = services.scorer.score(correct_run.run_id)
    assert correct_score["task_result"]["status"] == "pass"
    assert (
        next(row for row in correct_score["validations"] if row["validator_id"] == "issue-pr-state")["status"] == "pass"
    )
    services.protocol.validate(correct_score)
    correct_database = Path(correct_run.simulator_database_path)
    services.factory.cleanup_run(correct_run.run_id)
    assert not correct_database.exists()
