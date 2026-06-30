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


def test_banner_present(mock_config: dict[str, Any]) -> None:
    sql = generate_sql(mock_config)
    assert "-- ====" in sql
    assert "-- STAGING :" in sql
    assert "-- Maillon :" in sql


def test_layer_labels_intermediate(mock_config: dict[str, Any]) -> None:
    cfg = copy.deepcopy(mock_config)
    cfg["model"]["layer"] = "intermediate"
    sql = generate_sql(cfg)
    assert "[Clés de jointure]" in sql
    assert "-- ids" not in sql  # libellés sémantiques, pas dbt-staging


def test_cluster_by_in_config_block(mock_config: dict[str, Any]) -> None:
    cfg = copy.deepcopy(mock_config)
    cfg["model"]["materialized"] = "table"
    cfg["cluster_by"] = {"enabled": True, "columns": ["maj", "id"]}
    assert "cluster_by=['maj', 'id']" in generate_sql(cfg)


def test_cluster_by_ignored_for_view(mock_config: dict[str, Any]) -> None:
    cfg = copy.deepcopy(mock_config)
    cfg["model"]["materialized"] = "view"
    cfg["cluster_by"] = {"enabled": True, "columns": ["maj"]}
    assert "cluster_by" not in generate_sql(cfg)


def test_where_clause_single_column(mock_config: dict[str, Any]) -> None:
    cfg = copy.deepcopy(mock_config)
    cfg["model"]["materialized"] = "view"
    cfg["where_clause"] = {
        "mode": "and",
        "filters": [{"column": "STATUT", "operator": "in", "values": ["ACTIF", "VALIDE"]}],
    }
    sql = generate_sql(cfg)
    assert '"STATUT" in (' in sql
    assert "'ACTIF'" in sql


def test_where_clause_composite_or(mock_config: dict[str, Any]) -> None:
    cfg = copy.deepcopy(mock_config)
    cfg["model"]["materialized"] = "view"
    cfg["where_clause"] = {
        "mode": "or",
        "filters": [
            {"column": "PAYS", "operator": "in", "values": ["FR"]},
            {"column": "MONTANT", "operator": "custom", "custom_expr": "MONTANT > 0"},
        ],
    }
    sql = generate_sql(cfg)
    assert " or " in sql


def test_where_after_delta_filter(mock_config: dict[str, Any]) -> None:
    # mock_config est incrémental avec delta sur T_CMD_MAJ.
    cfg = copy.deepcopy(mock_config)
    cfg["where_clause"] = {
        "mode": "and",
        "filters": [{"column": "STATUT", "operator": "in", "values": ["ACTIF"]}],
    }
    sql = generate_sql(cfg)
    assert '"STATUT" in (' in sql
    assert "is_incremental()" in sql


def test_audit_columns_when_enabled(mock_config: dict[str, Any]) -> None:
    cfg = copy.deepcopy(mock_config)
    cfg["audit"] = {"enabled": True}
    sql = generate_sql(cfg)
    assert "current_timestamp() as _loaded_at" in sql
    assert "_dbt_invocation_id" in sql


def test_raw_columns_in_dedicated_section(mock_config: dict[str, Any]) -> None:
    cfg = copy.deepcopy(mock_config)
    next(c for c in cfg["columns"] if c["source"] == "T_CMD_NOM")["keep_raw"] = True
    sql = generate_sql(cfg)
    assert "-- raw (colonnes brutes conservées)" in sql
    assert "raw_nom" in sql


def test_keep_all_raw(mock_config: dict[str, Any]) -> None:
    cfg = copy.deepcopy(mock_config)
    cfg["normalization"]["keep_all_raw"] = True
    sql = generate_sql(cfg)
    assert "raw_id" in sql and "raw_nom" in sql


def test_persist_docs_and_grants(mock_config: dict[str, Any]) -> None:
    cfg = copy.deepcopy(mock_config)
    cfg["grants"] = {"select": ["ROLE_REPORTER"]}
    cfg["persist_docs"] = {"relation": True, "columns": True}
    sql = generate_sql(cfg)
    assert "grants={'select': ['ROLE_REPORTER']}" in sql
    assert "persist_docs=" in sql


def test_raw_column_documented_in_schema(mock_config: dict[str, Any]) -> None:
    cfg = copy.deepcopy(mock_config)
    next(c for c in cfg["columns"] if c["source"] == "T_CMD_NOM")["keep_raw"] = True
    doc = yaml.safe_load(generate_schema_yml(cfg))
    raw = next(c for c in doc["models"][0]["columns"] if c["name"] == "raw_nom")
    assert raw["meta"] == {"raw": True}


def test_comment_in_schema_yaml(mock_config: dict[str, Any]) -> None:
    cfg = copy.deepcopy(mock_config)
    cfg["columns"][0]["comment"] = "Identifiant commande"
    doc = yaml.safe_load(generate_schema_yml(cfg))
    descriptions = [c.get("description") for c in doc["models"][0]["columns"]]
    assert "Identifiant commande" in descriptions


def test_pii_meta_in_schema_yaml(mock_config: dict[str, Any]) -> None:
    # T_CMD_NOM → "nom" est marqué PII par build_staging_config.
    doc = yaml.safe_load(generate_schema_yml(mock_config))
    nom = next(c for c in doc["models"][0]["columns"] if c["name"] == "nom")
    assert nom.get("meta") == {"pii": True}
