"""Tests de la génération du SQL staging et du schema.yml."""

from __future__ import annotations

import copy
from typing import Any

import yaml

from src.model_generator import generate_schema_yml, generate_sql


def test_sql_contains_source_ref(mock_config: dict[str, Any]) -> None:
    assert "{{ source('raw', 'T_COMMANDE') }}" in generate_sql(mock_config)


def test_sql_contains_config_block(mock_config: dict[str, Any]) -> None:
    sql = generate_sql(mock_config)
    assert "{{" in sql
    assert "config(" in sql


def test_incremental_has_strategy(mock_config: dict[str, Any]) -> None:
    # mock_config détecte T_CMD_MAJ → matérialisation incrémentale.
    assert mock_config["model"]["materialized"] == "incremental"
    assert "incremental_strategy='merge'" in generate_sql(mock_config)


def test_incremental_has_delta_filter(mock_config: dict[str, Any]) -> None:
    sql = generate_sql(mock_config)
    assert "is_incremental()" in sql
    assert "where" in sql
    assert '"T_CMD_MAJ" >' in sql


def test_view_no_delta_filter(mock_config: dict[str, Any]) -> None:
    cfg = copy.deepcopy(mock_config)
    cfg["model"]["materialized"] = "view"
    assert "is_incremental()" not in generate_sql(cfg)


def test_excluded_column_absent(mock_config: dict[str, Any]) -> None:
    cfg = copy.deepcopy(mock_config)
    nom = next(c for c in cfg["columns"] if c["source"] == "T_CMD_NOM")
    nom["include"] = False
    sql = generate_sql(cfg)
    assert "as nom" not in sql


def test_keep_raw_adds_raw_column(mock_config: dict[str, Any]) -> None:
    cfg = copy.deepcopy(mock_config)
    nom = next(c for c in cfg["columns"] if c["source"] == "T_CMD_NOM")
    nom["keep_raw"] = True
    assert "raw_nom" in generate_sql(cfg)


def test_trim_lower_on_varchar(mock_config: dict[str, Any]) -> None:
    sql = generate_sql(mock_config)
    assert 'LOWER(TRIM("T_CMD_NOM"))' in sql


def test_no_trim_on_numeric(mock_config: dict[str, Any]) -> None:
    sql = generate_sql(mock_config)
    assert 'TRIM("T_CMD_MONTANT")' not in sql


def test_coalesce_applied(mock_config: dict[str, Any]) -> None:
    cfg = copy.deepcopy(mock_config)
    nom = next(c for c in cfg["columns"] if c["source"] == "T_CMD_NOM")
    nom["coalesce"] = "''"
    assert "COALESCE(" in generate_sql(cfg)


def test_schema_yaml_has_unique_test_on_pk(mock_config: dict[str, Any]) -> None:
    doc = yaml.safe_load(generate_schema_yml(mock_config))
    cols = doc["models"][0]["columns"]
    pk = next(c for c in cols if c["name"] == "id")
    assert "unique" in pk["tests"]


def test_schema_yaml_has_model_name(mock_config: dict[str, Any]) -> None:
    assert mock_config["model"]["name"] in generate_schema_yml(mock_config)


def test_ephemeral_no_unique_key(mock_config: dict[str, Any]) -> None:
    cfg = copy.deepcopy(mock_config)
    cfg["model"]["materialized"] = "ephemeral"
    assert "unique_key" not in generate_sql(cfg)


def test_purge_comment_when_enabled(mock_config: dict[str, Any]) -> None:
    cfg = copy.deepcopy(mock_config)
    cfg["purge"]["enabled"] = True
    assert "{# PURGE" in generate_sql(cfg)
