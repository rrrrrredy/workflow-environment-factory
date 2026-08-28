from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest
from workflow_environment_factory.config import Settings
from workflow_environment_factory.engine import LocalTestEngine
from workflow_environment_factory.services import Services


@dataclass(frozen=True)
class RepositoryFixture:
    root: Path
    base_commit: str
    solution_commit: str


def run_git(repository: Path, *arguments: str) -> str:
    completed = subprocess.run(
        ["git", "-C", str(repository), *arguments],
        capture_output=True,
        text=True,
        check=True,
        shell=False,
    )
    return completed.stdout.strip()


@pytest.fixture
def repository_fixture(tmp_path: Path) -> RepositoryFixture:
    repository = tmp_path / "repository"
    repository.mkdir()
    (repository / "app.py").write_text(
        'LABEL = "alpha"\n\n\ndef normalize(value: str) -> str:\n    return value.strip()\n',
        encoding="utf-8",
    )
    (repository / "verify.py").write_text(
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
        "user.name=WEF Test",
        "-c",
        "user.email=wef@example.invalid",
        "commit",
        "-m",
        "base failing state",
    )
    base = run_git(repository, "rev-parse", "HEAD")
    (repository / "app.py").write_text(
        'LABEL = "alpha"\n\n\ndef normalize(value: str) -> str:\n    return value.strip().lower()\n',
        encoding="utf-8",
    )
    run_git(repository, "add", "app.py")
    run_git(
        repository,
        "-c",
        "user.name=WEF Test",
        "-c",
        "user.email=wef@example.invalid",
        "commit",
        "-m",
        "correct state",
    )
    solution = run_git(repository, "rev-parse", "HEAD")
    return RepositoryFixture(repository, base, solution)


@pytest.fixture
def services(tmp_path: Path) -> Services:
    repository_root = Path(__file__).resolve().parents[1]
    data_dir = tmp_path / "factory-data"
    settings = Settings(
        host="127.0.0.1",
        port=43121,
        data_dir=data_dir,
        database_path=data_dir / "factory.sqlite3",
        content_dir=data_dir / "content",
        worktrees_dir=data_dir / "worktrees",
        simulator_dir=data_dir / "simulators",
        token_path=data_dir / "session-token",
        protocol_schema_dir=repository_root / ".runtime-deps" / "runcase-interchange" / "0.1.0" / "schemas",
        codex_executable="codex",
        docker_executable="missing-docker-for-tests",
        web_root=tmp_path / "missing-web",
    )
    for directory in (data_dir, settings.content_dir, settings.worktrees_dir, settings.simulator_dir):
        directory.mkdir(parents=True, exist_ok=True)
    instance = Services.build(settings, LocalTestEngine())
    try:
        yield instance
    finally:
        instance.close()


def make_code_correct(workspace: Path) -> None:
    target = workspace / "app.py"
    source = target.read_text(encoding="utf-8")
    assert "return value.strip()" in source
    target.write_text(source.replace("return value.strip()", "return value.strip().lower()"), encoding="utf-8")
