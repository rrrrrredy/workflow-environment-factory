from __future__ import annotations

from pathlib import Path

from conftest import RepositoryFixture, make_code_correct
from workflow_environment_factory.models import BlueprintCreate, RunStatus


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
    failed_score = services.scorer.score(failed_run.run_id)
    assert failed_score["task_result"]["status"] == "fail"
    services.factory.cleanup_run(failed_run.run_id)

    passing_run = services.factory.prepare_run(cases[2].case_id)
    make_code_correct(Path(passing_run.workspace_path))
    passing_score = services.scorer.score(passing_run.run_id)
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
    crashed_run.error = "Codex exited before validation with " + "Bear" + "er synthetic-secret-12345678"
    services.store.save_run(crashed_run)
    crashed_score = services.scorer.score(crashed_run.run_id)
    assert crashed_score["execution"]["status"] == "agent_crash"
    assert crashed_score["task_result"]["status"] == "not_scored"
    assert crashed_score["validations"] == []
    assert "synthetic-secret-12345678" not in crashed_score["execution"]["details"]
    assert services.store.get_run(crashed_run.run_id).status == RunStatus.AGENT_CRASH
    services.protocol.validate(crashed_score)
    services.store.save_run(services.store.get_run(crashed_run.run_id))
    assert services.store.get_score_for_run(crashed_run.run_id)["score_id"] == crashed_score["score_id"]
    services.factory.cleanup_run(crashed_run.run_id)
