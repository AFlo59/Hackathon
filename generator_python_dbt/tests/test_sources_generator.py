"""Tests de la génération du sources.yml."""

from __future__ import annotations

from typing import Any

import yaml

from src.sources_generator import build_sources, generate_sources_yml


def _build(columns: list[dict[str, Any]], **kwargs: Any) -> dict[str, Any]:
    base = dict(
        source_name="raw",
        database="MY_DB",
        schema="RAW_SALES",
        table="T_COMMANDE",
        columns=columns,
    )
    base.update(kwargs)
    return build_sources(**base)


def test_basic_structure(mock_columns: list[dict[str, Any]]) -> None:
    doc = _build(mock_columns)
    assert doc["version"] == 2
    assert isinstance(doc["sources"], list)
    assert isinstance(doc["sources"][0]["tables"], list)


def test_pk_gets_unique_test(mock_columns: list[dict[str, Any]]) -> None:
    doc = _build(mock_columns)
    cols = doc["sources"][0]["tables"][0]["columns"]
    pk = next(c for c in cols if c["name"] == "T_CMD_ID")
    assert pk["tests"] == ["unique", "not_null"]


def test_not_null_column_gets_not_null_test() -> None:
    columns = [
        {"name": "CODE", "type": "VARCHAR(10)", "nullable": False, "primary_key": False},
    ]
    doc = _build(columns)
    code = doc["sources"][0]["tables"][0]["columns"][0]
    assert code["tests"] == ["not_null"]


def test_freshness_auto_detect_updated_at() -> None:
    columns = [
        {"name": "ID", "type": "NUMBER(38,0)", "nullable": False, "primary_key": True},
        {"name": "UPDATED_AT", "type": "TIMESTAMP_NTZ", "nullable": True, "primary_key": False},
    ]
    table = _build(columns)["sources"][0]["tables"][0]
    assert "freshness" in table
    assert table["loaded_at_field"] == "UPDATED_AT"


def test_freshness_auto_detect_maj(mock_columns: list[dict[str, Any]]) -> None:
    table = _build(mock_columns)["sources"][0]["tables"][0]
    assert "freshness" in table
    assert table["loaded_at_field"] == "T_CMD_MAJ"


def test_no_freshness_when_no_timestamp() -> None:
    columns = [
        {"name": "ID", "type": "NUMBER(38,0)", "nullable": False, "primary_key": True},
        {"name": "NOM", "type": "VARCHAR(50)", "nullable": True, "primary_key": False},
    ]
    table = _build(columns)["sources"][0]["tables"][0]
    assert "freshness" not in table


def test_tags_and_meta_included(mock_columns: list[dict[str, Any]]) -> None:
    doc = _build(mock_columns, tags=["sales"], meta={"owner": "data-team"})
    source = doc["sources"][0]
    assert source["tags"] == ["sales"]
    assert source["meta"] == {"owner": "data-team"}


def test_comments_propagated_to_description() -> None:
    columns = [
        {"name": "ID", "type": "NUMBER(38,0)", "nullable": False,
         "primary_key": True, "comment": "Clé primaire"},
    ]
    col = _build(columns)["sources"][0]["tables"][0]["columns"][0]
    assert col["description"] == "Clé primaire"


def test_pii_column_gets_meta() -> None:
    columns = [
        {"name": "EMAIL", "type": "VARCHAR(256)", "nullable": True, "primary_key": False},
    ]
    col = _build(columns)["sources"][0]["tables"][0]["columns"][0]
    assert col["meta"] == {"pii": True}


def test_table_comment_as_description(mock_columns: list[dict[str, Any]]) -> None:
    table = _build(mock_columns, table_comment="Table des commandes")["sources"][0]["tables"][0]
    assert table["description"] == "Table des commandes"


def test_yaml_is_valid(mock_columns: list[dict[str, Any]]) -> None:
    text = generate_sources_yml(
        source_name="raw",
        database="MY_DB",
        schema="RAW_SALES",
        table="T_COMMANDE",
        columns=mock_columns,
    )
    parsed = yaml.safe_load(text)
    assert parsed["version"] == 2
