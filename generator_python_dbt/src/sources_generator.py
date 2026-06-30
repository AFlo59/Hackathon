"""Génération d'un ``sources.yml`` DBT à partir des métadonnées (DESC TABLE).

Produit la structure ``version: 2 / sources / tables`` avec :

* tests ``unique`` + ``not_null`` sur les colonnes clé primaire ;
* test ``not_null`` sur les colonnes non nullables ;
* bloc ``freshness`` auto-détecté sur une colonne TIMESTAMP de mise à jour ;
* ``tags`` et ``meta`` au niveau source.
"""

from __future__ import annotations

from typing import Any

from .yaml_config import detect_delta_column, detect_pii, dump_yaml


def build_sources(
    *,
    source_name: str,
    database: str,
    schema: str,
    table: str,
    columns: list[dict[str, Any]],
    tags: list[str] | None = None,
    meta: dict[str, Any] | None = None,
    table_comment: str | None = None,
    freshness_warn_hours: int = 24,
    freshness_error_hours: int = 48,
) -> dict[str, Any]:
    """Construit le dict ``sources.yml`` pour une table.

    Args:
        source_name: nom logique du source DBT (ex : ``raw``).
        database / schema / table: localisation Snowflake.
        columns: liste de dicts ``{"name", "type", "nullable", "primary_key"}``.
        tags / meta: métadonnées au niveau source.
        freshness_warn_hours / freshness_error_hours: seuils de freshness.

    Returns:
        Le document ``sources.yml`` sous forme de ``dict``.
    """
    table_columns: list[dict[str, Any]] = []
    for col in columns:
        col_name = str(col["name"])
        tests: list[str] = []
        if col.get("primary_key"):
            tests = ["unique", "not_null"]
        elif col.get("nullable") is False:
            tests = ["not_null"]

        entry: dict[str, Any] = {"name": col_name}
        if col.get("comment"):
            entry["description"] = str(col["comment"])
        if tests:
            entry["tests"] = tests
        if detect_pii(col_name):
            entry["meta"] = {"pii": True}
        table_columns.append(entry)

    table_def: dict[str, Any] = {"name": table, "columns": table_columns}
    if table_comment:
        table_def["description"] = table_comment

    delta_col = detect_delta_column(columns)
    if delta_col:
        table_def["loaded_at_field"] = delta_col
        table_def["freshness"] = {
            "warn_after": {"count": freshness_warn_hours, "period": "hour"},
            "error_after": {"count": freshness_error_hours, "period": "hour"},
        }

    source_def: dict[str, Any] = {
        "name": source_name,
        "database": database,
        "schema": schema,
    }
    if tags:
        source_def["tags"] = tags
    if meta:
        source_def["meta"] = meta
    source_def["tables"] = [table_def]

    return {"version": 2, "sources": [source_def]}


def generate_sources_yml(**kwargs: Any) -> str:
    """Variante texte : retourne directement le YAML sérialisé."""
    return dump_yaml(build_sources(**kwargs))
