from workflow_environment_factory.cli import codex_version_supported


def test_codex_version_requires_restricted_read_capability_release() -> None:
    assert codex_version_supported("codex-cli 0.151.0")
    assert codex_version_supported("codex-cli 1.0.0")
    assert not codex_version_supported("codex-cli 0.150.0-alpha.8")
    assert not codex_version_supported("unexpected output")
