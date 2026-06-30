"""Tests de l'inférence de config staging et de la sérialisation YAML."""

from __future__ import annotations

from typing import Any

from src.yaml_config import (
    NO_UNIQUE_KEY,
    build_staging_config,
    detect_delta_column,
    detect_unique_key,
    dump_yaml,
    infer_cast,
    load_yaml,
)


def test_delta_auto_detect_updated_at() -> None:
    columns = [{"name": "UPDATED_AT", "type": "TIMESTAMP_NTZ"}]
    assert detect_delta_column(columns) == "UPDATED_AT"


def test_delta_auto_detect_maj() -> None:
    columns = [{"name": "T_CMD_MAJ", "type": "TIMESTAMP_NTZ"}]
    assert detect_delta_column(columns) == "T_CMD_MAJ"


def test_no_delta_when_no_timestamp() -> None:
    columns = [{"name": "NOM", "type": "VARCHAR(50)"}]
    assert detect_delta_column(columns) is None


def test_pk_set_as_unique_key() -> None:
    columns = [{"name": "ID", "type": "NUMBER(38,0)", "primary_key": True}]
    assert detect_unique_key(columns) == "id"


def test_composite_pk() -> None:
    columns = [
        {"name": "ORDER_ID", "type": "NUMBER(38,0)", "primary_key": True},
        {"name": "LINE_ID", "type": "NUMBER(38,0)", "primary_key": True},
    ]
    assert detect_unique_key(columns) == ["order_id", "line_id"]


def test_no_pk() -> None:
    columns = [{"name": "NOM", "type": "VARCHAR(50)", "primary_key": False}]
    assert detect_unique_key(columns) == NO_UNIQUE_KEY


def test_cast_inference_number_0() -> None:
    assert infer_cast("NUMBER(38,0)") == "BIGINT"


def test_cast_inference_number_float() -> None:
    assert infer_cast("NUMBER(18,4)") == "FLOAT"


def test_cast_inference_varchar() -> None:
    assert infer_cast("VARCHAR(256)") == "VARCHAR"


def test_cast_inference_timestamp() -> None:
    assert infer_cast("TIMESTAMP_NTZ") == "TIMESTAMP_NTZ"


def test_roundtrip_yaml(mock_config: dict[str, Any]) -> None:
    assert load_yaml(dump_yaml(mock_config)) == mock_config
