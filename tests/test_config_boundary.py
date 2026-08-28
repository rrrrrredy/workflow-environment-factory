from __future__ import annotations

import json
from pathlib import Path

import pytest
from workflow_environment_factory.config import DATA_MARKER_NAME, Settings, ensure_factory_data_root


def test_settings_creates_and_reuses_product_owned_data_root(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "owned"
    monkeypatch.setenv("WEF_DATA_DIR", str(data_dir))
    settings = Settings.load(Path(__file__).resolve().parents[1])

    assert settings.data_dir == data_dir.absolute()
    marker = json.loads((data_dir / DATA_MARKER_NAME).read_text(encoding="utf-8"))
    assert marker["product"] == "workflow-environment-factory"
    ensure_factory_data_root(data_dir)


def test_doctor_settings_are_side_effect_free(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "doctor-does-not-create"
    monkeypatch.setenv("WEF_DATA_DIR", str(data_dir))

    settings = Settings.load(Path(__file__).resolve().parents[1], initialize=False)

    assert settings.data_dir == data_dir.absolute()
    assert not data_dir.exists()


def test_existing_unmarked_data_roots_are_rejected_without_touching_content(tmp_path: Path) -> None:
    existing_empty = tmp_path / "existing-empty"
    existing_empty.mkdir()
    with pytest.raises(ValueError, match="ownership marker"):
        ensure_factory_data_root(existing_empty)
    assert list(existing_empty.iterdir()) == []

    foreign = tmp_path / "foreign"
    foreign.mkdir()
    sentinel = foreign / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")

    with pytest.raises(ValueError, match="ownership marker"):
        ensure_factory_data_root(foreign)

    assert sentinel.read_text(encoding="utf-8") == "keep"
