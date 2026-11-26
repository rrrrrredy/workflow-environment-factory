from __future__ import annotations

import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest
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


def test_cleanup_revokes_ready_run_and_preserves_neighbor(services, repository_fixture):
    case = _case(services, repository_fixture)
    first = services.factory.prepare_run(case.case_id)
    second = services.factory.prepare_run(case.case_id)
    workspace = Path(first.workspace_path)
    (workspace / ".gitignore").write_text("generated/\n")
    (workspace / "generated").mkdir()
    (workspace / "generated" / "output").touch()
    (workspace / "temporary").touch()
    (services.git.isolated_git_dir(workspace) / "index.lock").touch()
    services.factory.cleanup_run(first.run_id)
    services.factory.cleanup_run(first.run_id)
    assert not workspace.parent.exists()
    assert Path(second.workspace_path).exists()
    neighbor = Path(second.workspace_path).parent / "other-data"
    neighbor.touch()
    third = services.factory.prepare_run(case.case_id)
    keeper = Path(third.workspace_path).parent / "other-data"
    keeper.touch()
    services.factory.cleanup_run(third.run_id)
    assert keeper.exists() and neighbor.exists()
    assert services.store.claim_ready_run(first.run_id) is None
    assert services.store.claim_ready_run(second.run_id) is not None
    with pytest.raises(ValueError, match="active"):
        services.factory.cleanup_run(second.run_id)


def test_trusted_verifier_and_declared_assets_bind_each_variant(services, repository_fixture):
    bp = _blueprint(repository_fixture)
    bp.allowed_paths = ["*"]
    bp.verifier.asset_paths = ["verify.py"]
    blueprint = services.factory.create_blueprint(bp)
    cases = services.factory.generate_cases(blueprint.blueprint_id)
    for index, case in enumerate(cases[:2]):
        run = services.factory.prepare_run(case.case_id)
        workspace = Path(run.workspace_path)
        make_code_correct(workspace)
        if not index:
            run.baseline_manifest_ref = None  # Also score a stored Run created before manifests.
            assert services.git.run_isolated(workspace, ["add", "app.py"]).exit_code == 0
            assert services.git.run_isolated(workspace, ["commit", "-m", "legitimate fix"]).exit_code == 0
        if index:
            (workspace / "verify.py").write_text("# different test revision\n", encoding="utf-8")
        mark_synthetic_agent_attempt(services, run)
        score = services.scorer.score(run.run_id, allow_synthetic_fixture=True)
        assert score["task_result"]["status"] == ("not_scored" if index else "pass")
        if index:
            assert any(
                row["validator_id"] == "verifier-assets" and row["status"] == "error" for row in score["validations"]
            )


def test_independent_stores_score_once_and_retry_failed_commit(services, repository_fixture):
    from workflow_environment_factory.services import Services

    case = _case(services, repository_fixture)
    run = services.factory.prepare_run(case.case_id)
    make_code_correct(Path(run.workspace_path))
    mark_synthetic_agent_attempt(services, run)
    second = Services.build(services.settings, services.scorer.engine)
    calls = []
    original = services.scorer.engine.run
    entered = threading.Event()
    release = threading.Event()

    def counted(*args):
        calls.append(1)
        entered.set()
        assert release.wait(10)
        return original(*args)

    try:
        from unittest.mock import patch

        with patch.object(services.scorer.engine, "run", counted), ThreadPoolExecutor(max_workers=2) as pool:
            first = pool.submit(services.scorer.score, run.run_id, allow_synthetic_fixture=True)
            assert entered.wait(10)
            other = pool.submit(second.scorer.score, run.run_id, allow_synthetic_fixture=True)
            with pytest.raises(ValueError, match="active"):
                second.factory.cleanup_run(run.run_id)
            release.set()
            assert first.result()["score_id"] == other.result()["score_id"]
        assert len(calls) == 1
        retry = services.factory.prepare_run(case.case_id)
        mark_synthetic_agent_attempt(services, retry)
        services.store.connection.execute(
            "CREATE TRIGGER refuse BEFORE INSERT ON scores BEGIN SELECT RAISE(ABORT,'busy fixture'); END"
        )
        with pytest.raises(sqlite3.IntegrityError):
            services.scorer.score(retry.run_id, allow_synthetic_fixture=True)
        assert services.store.get_run(retry.run_id).status == RunStatus.COMPLETED
        assert services.store.get_score_for_run(retry.run_id) is None
        services.store.connection.execute("DROP TRIGGER refuse")
        assert services.scorer.score(retry.run_id, allow_synthetic_fixture=True)["run_id"] == str(retry.run_id)
    finally:
        release.set()
        second.close()


def test_git_reports_original_unicode_paths_and_both_rename_endpoints(services, repository_fixture):
    case = _case(services, repository_fixture)
    run = services.factory.prepare_run(case.case_id)
    workspace = Path(run.workspace_path)
    old = workspace / "app.py"
    new = workspace / "\u4e2d\u6587 renamed.py"
    old.rename(new)
    assert services.git.run_isolated(workspace, ["add", "-A"]).exit_code == 0
    assert set(services.git.changed_paths(workspace, "HEAD")) == {"app.py", new.name}


def test_prepare_matches_the_case_gate_before_releasing_workspace(services, repository_fixture, monkeypatch):
    case = _case(services, repository_fixture)
    baseline = case.validation.baseline_manifest_ref
    assert baseline
    run = services.factory.prepare_run(case.case_id)
    assert run.status == RunStatus.READY and run.baseline_manifest_ref == baseline
    materialize = services.git.materialize_isolated

    def inconsistent_checkout(*args):
        workspace, count = materialize(*args)
        (workspace / "verify.py").write_text("# alternate checkout\n", encoding="utf-8")
        return workspace, count

    monkeypatch.setattr(services.git, "materialize_isolated", inconsistent_checkout)
    rejected = services.factory.prepare_run(case.case_id)
    assert rejected.status == RunStatus.RESET_ERROR
    assert not Path(rejected.workspace_path).exists()
    assert services.store.claim_ready_run(rejected.run_id) is None
