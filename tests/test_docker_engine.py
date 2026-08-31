from __future__ import annotations

import pytest
from workflow_environment_factory.engine import _container_user_args


def test_posix_container_uses_host_identity() -> None:
    assert _container_user_args("posix", 1001, 1002) == ["--user", "1001:1002"]


def test_windows_container_keeps_docker_desktop_identity() -> None:
    assert _container_user_args("nt", None, None) == []


def test_posix_container_rejects_missing_identity() -> None:
    with pytest.raises(RuntimeError, match="host uid and gid"):
        _container_user_args("posix", None, None)
