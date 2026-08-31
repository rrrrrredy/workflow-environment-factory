from __future__ import annotations

import json
from pathlib import Path

import pytest
from conftest import RepositoryFixture, make_code_correct, mark_synthetic_agent_attempt
from workflow_environment_factory.engine import ProcessResult
from workflow_environment_factory.models import AttemptOrigin, BlueprintCreate, RunStatus


def code_blueprint(repository: RepositoryFixture) -> BlueprintCreate:
    return BlueprintCreate.model_validate(
        {
            "name": "Normalize a confirmed label",
            "kind": "code",
            "repository_path": str(repository.root),
            "base_revision": repository.base_commit,
            "solution_revision": repository.solution_commit,
            "title_template": "Normalize the {value} label",
            "goal_template": "Fix normalization for the confirmed {value} label and pass the objective verifier.",
            "completion_summary": "The verifier passes with changes limited to app.py.",
            "external_ref": "local-issue:normalize-{value}",
            "variable": {
                "name": "label",
                "original": "alpha",
                "variants": ["beta", "gamma"],
                "paths": ["app.py"],
                "confirmed_by_user": True,
                "description": "A confirmed fixture label transformed in both baseline and correct states.",
            },
            "container_image": f"python@sha256:{'1' * 64}",
            "verifier": {"argv": ["python", "verify.py"], "timeout_ms": 10_000},
            "allowed_paths": ["app.py"],
            "allowed_tools": ["shell", "file", "git"],
        }
    )


def test_code_factory_generates_only_gated_cases_and_scores_objectively(services, repository_fixture) -> None:
    blueprint = services.factory.create_blueprint(code_blueprint(repository_fixture))
    cases = services.factory.generate_cases(blueprint.blueprint_id)

    assert len(cases) == 3
    assert [case.variable_value for case in cases] == ["alpha", "beta", "gamma"]
    assert all(case.validation.objective_gate_passed for case in cases)
    assert all(case.validation.baseline_status == "fail" for case in cases)
    assert all(case.validation.solution_status == "pass" for case in cases)
    assert all(case.validation.reset_verified for case in cases)
    assert cases[0].protocol_case["provenance"]["kind"] == "repository_commit"
    assert all(case.protocol_case["provenance"]["parent_case_id"] == str(cases[0].case_id) for case in cases[1:])

    first_reset = services.factory.prepare_run(cases[1].case_id)
    second_reset = services.factory.prepare_run(cases[1].case_id)
    assert first_reset.workspace_path != second_reset.workspace_path
    assert Path(first_reset.workspace_path, "app.py").read_text(encoding="utf-8") == Path(
        second_reset.workspace_path, "app.py"
    ).read_text(encoding="utf-8")
    services.factory.cleanup_run(first_reset.run_id)
    services.factory.cleanup_run(second_reset.run_id)

    failed_run = services.factory.prepare_run(cases[0].case_id)
    mark_synthetic_agent_attempt(services, failed_run)
    with pytest.raises(ValueError, match="synthetic fixture"):
        services.scorer.score(failed_run.run_id)
    failed_score = services.scorer.score(failed_run.run_id, allow_synthetic_fixture=True)
    assert failed_score["task_result"]["status"] == "fail"
    assert failed_score["extensions"]["workflow_environment_factory"] == {
        "engine": "local-test-only",
        "attempt_origin": "synthetic_fixture",
        "model_executed": False,
        "verifier_output_ref": failed_score["extensions"]["workflow_environment_factory"]["verifier_output_ref"],
    }
    assert "no model was executed" in failed_score["nondeterminism"]["notes"][0]
    services.factory.cleanup_run(failed_run.run_id)

    passing_run = services.factory.prepare_run(cases[2].case_id)
    passing_workspace = Path(passing_run.workspace_path)
    assert not (passing_workspace / ".git").exists()
    git_dir = services.git.isolated_git_dir(passing_workspace)
    assert git_dir.is_dir()
    assert services.git.run_isolated(passing_workspace, ["remote"]).stdout.strip() == ""
    assert not (git_dir / "objects" / "info" / "alternates").exists()
    solution_probe = services.git.run_isolated(
        passing_workspace, ["cat-file", "-e", f"{repository_fixture.solution_commit}^{{commit}}"]
    )
    assert solution_probe.exit_code != 0
    unexpected = passing_workspace / "outside-allowed-path.txt"
    unexpected.write_text("must be scored", encoding="utf-8")
    assert services.git.changed_paths(passing_workspace, "HEAD") == ["outside-allowed-path.txt"]
    unexpected.unlink()
    make_code_correct(passing_workspace)
    mark_synthetic_agent_attempt(services, passing_run)
    passing_score = services.scorer.score(passing_run.run_id, allow_synthetic_fixture=True)
    assert passing_score["task_result"] == {
        "status": "pass",
        "score": 1.0,
        "reason": "All required objective validators passed.",
    }
    assert passing_score["nondeterminism"]["single_run_evidence"] is True
    services.protocol.validate(passing_score)
    services.factory.cleanup_run(passing_run.run_id)

    crashed_run = services.factory.prepare_run(cases[0].case_id)
    crashed_run.status = RunStatus.AGENT_CRASH
    crashed_run.agent_attempted = True
    crashed_run.attempt_origin = AttemptOrigin.SYNTHETIC_FIXTURE
    crashed_run.model_executed = False
    crashed_run.error = "Codex exited before validation with " + "Bear" + "er synthetic-secret-12345678"
    services.store.save_run(crashed_run)
    crashed_score = services.scorer.score(crashed_run.run_id, allow_synthetic_fixture=True)
    assert crashed_score["execution"]["status"] == "agent_crash"
    assert crashed_score["task_result"]["status"] == "not_scored"
    assert crashed_score["validations"] == []
    assert "synthetic-secret-12345678" not in crashed_score["execution"]["details"]
    assert services.store.get_run(crashed_run.run_id).status == RunStatus.AGENT_CRASH
    services.protocol.validate(crashed_score)
    services.store.save_run(services.store.get_run(crashed_run.run_id))
    assert services.store.get_score_for_run(crashed_run.run_id)["score_id"] == crashed_score["score_id"]
    services.factory.cleanup_run(crashed_run.run_id)

    unstarted_run = services.factory.prepare_run(cases[0].case_id)
    try:
        services.scorer.score(unstarted_run.run_id)
        raise AssertionError("READY state was incorrectly accepted as a Codex score")
    except ValueError as error:
        assert "cannot be scored" in str(error)
    services.factory.cleanup_run(unstarted_run.run_id)

    class MutatingVerifier:
        name = "mutating-test-verifier"

        def run(self, workspace: Path, image: str, argv: list[str], timeout_ms: int) -> ProcessResult:
            del image, argv, timeout_ms
            (workspace / "verifier-created.txt").write_text("unexpected", encoding="utf-8")
            return ProcessResult("pass", 0, "", "", 1)

    mutated_run = services.factory.prepare_run(cases[0].case_id)
    mark_synthetic_agent_attempt(services, mutated_run)
    original_engine = services.scorer.engine
    services.scorer.engine = MutatingVerifier()
    try:
        mutated_score = services.scorer.score(mutated_run.run_id, allow_synthetic_fixture=True)
    finally:
        services.scorer.engine = original_engine
    assert mutated_score["execution"]["status"] == "validator_error"
    assert mutated_score["task_result"]["status"] == "not_scored"
    integrity = next(
        row for row in mutated_score["validations"] if row["validator_id"] == "verifier-workspace-integrity"
    )
    assert integrity["status"] == "error"
    assert services.scorer.score(mutated_run.run_id)["score_id"] == mutated_score["score_id"]
    services.factory.cleanup_run(mutated_run.run_id)


def test_codex_preflight_failure_is_environment_error_without_model_score(services, repository_fixture) -> None:
    class FailingPreflight:
        def check(self, workspace: Path, environment: dict[str, str]) -> None:
            del workspace, environment
            raise RuntimeError("windows sandbox failed Bear" + "er synthetic-preflight-secret-12345678")

    blueprint = services.factory.create_blueprint(code_blueprint(repository_fixture))
    case = services.factory.generate_cases(blueprint.blueprint_id)[0]
    run = services.factory.prepare_run(case.case_id)
    services.runner.preflight = FailingPreflight()
    services.runner.execute(run.run_id)
    retained = services.store.get_run(run.run_id)
    assert retained is not None
    assert retained.status == RunStatus.ENVIRONMENT_ERROR
    assert retained.completed_at is not None
    assert any(event.get("type") == "environment_preflight_failed" for event in retained.codex_events)
    assert "synthetic-preflight-secret-12345678" not in json.dumps(retained.model_dump(mode="json"))
    assert services.store.get_score_for_run(run.run_id) is None
    services.factory.cleanup_run(run.run_id)
