from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from conftest import RepositoryFixture, make_code_correct, mark_synthetic_agent_attempt
from workflow_environment_factory.models import BlueprintCreate, RunStatus


def _blueprint(repository: RepositoryFixture) -> BlueprintCreate:
    return BlueprintCreate.model_validate(
        {
            "name": "Concurrency boundary fixture",
            "kind": "code",
            "repository_path": str(repository.root),
            "base_revision": repository.base_commit,
            "solution_revision": repository.solution_commit,
            "title_template": "Normalize {value}",
            "goal_template": "Normalize the confirmed {value} label.",
            "completion_summary": "The objective verifier passes.",
            "variable": {
                "name": "label",
                "original": "alpha",
                "variants": ["beta", "gamma"],
                "paths": ["app.py", "verify.py"],
                "confirmed_by_user": True,
            },
            "container_image": f"python@sha256:{'1' * 64}",
            "verifier": {"argv": ["python", "verify.py"], "timeout_ms": 10_000},
            "allowed_paths": ["app.py"],
            "allowed_tools": ["shell", "file", "git"],
            "timeout_ms": 60_000,
        }
    )


def _case(services, repository: RepositoryFixture):
    blueprint = services.factory.create_blueprint(_blueprint(repository))
    return services.factory.generate_cases(blueprint.blueprint_id)[0]


def test_ready_run_can_be_claimed_by_only_one_executor(services, repository_fixture) -> None:
    run = services.factory.prepare_run(_case(services, repository_fixture).case_id)

    with ThreadPoolExecutor(max_workers=8) as pool:
        claimed = list(pool.map(lambda _: services.store.claim_ready_run(run.run_id), range(8)))

    winners = [candidate for candidate in claimed if candidate is not None]
    assert len(winners) == 1
    assert winners[0].status == RunStatus.QUEUED
    assert services.store.get_run(run.run_id).status == RunStatus.QUEUED


def test_concurrent_scoring_runs_one_validator_and_returns_one_score(services, repository_fixture) -> None:
    run = services.factory.prepare_run(_case(services, repository_fixture).case_id)
    make_code_correct(Path(run.workspace_path))
    mark_synthetic_agent_attempt(services, run)
    original_engine = services.scorer.engine
    counter_lock = threading.Lock()
    calls = 0

    class CountingEngine:
        name = "counting-test-engine"

        def run(self, *args, **kwargs):
            nonlocal calls
            with counter_lock:
                calls += 1
            return original_engine.run(*args, **kwargs)

    services.scorer.engine = CountingEngine()
    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            scores = list(
                pool.map(
                    lambda _: services.scorer.score(run.run_id, allow_synthetic_fixture=True),
                    range(2),
                )
            )
    finally:
        services.scorer.engine = original_engine

    assert calls == 1
    assert scores[0]["score_id"] == scores[1]["score_id"]
    assert services.store.get_score_for_run(run.run_id)["score_id"] == scores[0]["score_id"]
