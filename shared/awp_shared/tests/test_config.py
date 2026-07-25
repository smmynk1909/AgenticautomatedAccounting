import json
from pathlib import Path

import pytest
import yaml

from awp_shared.config import ConfigError, load_config, validate_all


def test_real_config_directory_passes_boot_validation() -> None:
    """Regression guard: catches drift between config/*.yaml and config/schema/*.json."""
    load_config.cache_clear()
    validate_all()


def test_load_config_rejects_schema_violation(tmp_path: Path) -> None:
    load_config.cache_clear()
    (tmp_path / "schema").mkdir()
    (tmp_path / "widgets.yaml").write_text(yaml.dump({"not_a_number": "oops"}), encoding="utf-8")
    schema = {
        "type": "object",
        "required": ["count"],
        "properties": {"count": {"type": "integer"}},
    }
    (tmp_path / "schema" / "widgets.schema.json").write_text(json.dumps(schema), encoding="utf-8")

    with pytest.raises(ConfigError, match="failed schema validation"):
        load_config("widgets", config_dir=tmp_path)


def test_load_config_missing_file_raises(tmp_path: Path) -> None:
    load_config.cache_clear()
    with pytest.raises(ConfigError, match="missing config file"):
        load_config("does_not_exist", config_dir=tmp_path)


def test_env_var_interpolation(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    load_config.cache_clear()
    monkeypatch.setenv("WIDGET_URL", "http://example.invalid")
    (tmp_path / "schema").mkdir()
    (tmp_path / "widgets.yaml").write_text(yaml.dump({"url": "${WIDGET_URL}"}), encoding="utf-8")

    data = load_config("widgets", config_dir=tmp_path)
    assert data["url"] == "http://example.invalid"
