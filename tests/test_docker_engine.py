from __future__ import annotations

import pytest
from workflow_environment_factory.engine import (
    DockerEngine,
    LocalTestEngine,
    ProcessResult,
    _container_user_args,
)


def test_posix_container_uses_host_identity() -> None:
    assert _container_user_args("posix", 1001, 1002) == ["--user", "1001:1002"]


def test_windows_container_keeps_docker_desktop_identity() -> None:
    assert _container_user_args("nt", None, None) == []


def test_posix_container_rejects_missing_identity() -> None:
    with pytest.raises(RuntimeError, match="host uid and gid"):
        _container_user_args("posix", None, None)


def test_cached_image_skips_pull(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    calls: list[list[str]] = []

    def fake_run(self, workspace, image, argv, timeout_ms):
        del self, workspace, image, timeout_ms
        calls.append(argv)
        return ProcessResult("pass", 0, "cached", "", 4)

    monkeypatch.setattr(LocalTestEngine, "run", fake_run)
    image = "python@sha256:" + "a" * 64

    assert DockerEngine()._prepare_image(tmp_path, image) is None
    assert calls == [["docker", "image", "inspect", image]]


def test_missing_image_is_pulled_before_execution(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    calls: list[list[str]] = []

    def fake_run(self, workspace, image, argv, timeout_ms):
        del self, workspace, image, timeout_ms
        calls.append(argv)
        if argv[1:3] == ["image", "inspect"]:
            return ProcessResult("fail", 1, "", "No such image", 3)
        return ProcessResult("pass", 0, "pulled", "", 800)

    monkeypatch.setattr(LocalTestEngine, "run", fake_run)
    image = "python@sha256:" + "b" * 64

    assert DockerEngine()._prepare_image(tmp_path, image) is None
    assert calls == [
        ["docker", "image", "inspect", image],
        ["docker", "pull", image],
    ]


def test_image_pull_failure_is_an_environment_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    def fake_run(self, workspace, image, argv, timeout_ms):
        del self, workspace, image, timeout_ms
        if argv[1:3] == ["image", "inspect"]:
            return ProcessResult("fail", 1, "", "No such image", 3)
        return ProcessResult("timeout", None, "", "registry unavailable", 300_000)

    monkeypatch.setattr(LocalTestEngine, "run", fake_run)
    image = "python@sha256:" + "c" * 64

    result = DockerEngine()._prepare_image(tmp_path, image)

    assert result is not None
    assert result.status == "error"
    assert result.exit_code is None
    assert "preparation failed before verifier execution" in result.stderr
    assert "registry unavailable" in result.stderr
