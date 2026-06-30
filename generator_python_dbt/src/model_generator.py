"""Génération du SQL staging + ``schema.yml`` à partir du config staging.

Consomme le document produit par :func:`src.yaml_config.build_staging_config`
(éventuellement édité par l'utilisateur) et produit :

* un fichier ``.sql`` DBT (CTE ``source`` → ``renamed`` → ``select``) optimisé
  pour Snowflake (casts ``::TYPE``, ``TRIM``/``LOWER`` sur chaînes, filtre delta
  incrémental) ;
* le ``schema.yml`` associé (tests sur la clé unique).
"""

from __future__ import annotations

from typing import Any

from .normalizer import build_sql_expression
from .yaml_config import NO_UNIQUE_KEY, dump_yaml


def _format_unique_key(unique_key: Any) -> str:
    """Rend ``unique_key`` pour le bloc ``config`` Jinja."""
    if isinstance(unique_key, list):
        inner = ", ".join(f"'{k}'" for k in unique_key)
        return f"[{inner}]"
    return f"'{unique_key}'"


def _config_block(config: dict[str, Any]) -> str:
    """Construit le bloc ``{{ config(...) }}``."""
    model = config["model"]
    materialized = model["materialized"]
    unique_key = config.get("unique_key", NO_UNIQUE_KEY)

    lines = [f"    materialized='{materialized}'"]
    if materialized == "incremental":
        lines.append("    incremental_strategy='merge'")
    if materialized in ("incremental", "table") and unique_key != NO_UNIQUE_KEY:
        lines.append(f"    unique_key={_format_unique_key(unique_key)}")
    if model.get("tags"):
        tags = ", ".join(f"'{t}'" for t in model["tags"])
        lines.append(f"    tags=[{tags}]")
    if model.get("schema"):
        lines.append(f"    schema='{model['schema']}'")

    body = ",\n".join(lines)
    return "{{\n  config(\n" + body + "\n  )\n}}"


# Ordre et libellés des groupes de colonnes (cf. style guide dbt).
_GROUP_ORDER: tuple[tuple[str, str], ...] = (
    ("ids", "-- ids"),
    ("strings", "-- strings"),
    ("numerics", "-- numerics"),
    ("booleans", "-- booleans"),
    ("dates", "-- dates"),
    ("timestamps", "-- timestamps"),
)


def _column_group(target: str, cast: str, pk_targets: set[str]) -> str:
    """Classe une colonne dans un groupe dbt selon son rôle / son type."""
    cast = cast.upper()
    if target in pk_targets or target == "id" or target.endswith("_id"):
        return "ids"
    if cast.startswith("BOOL"):
        return "booleans"
    if cast.startswith("TIMESTAMP"):
        return "timestamps"
    if cast.startswith("DATE"):
        return "dates"
    if cast.startswith(("BIGINT", "INT", "FLOAT", "DOUBLE", "REAL", "NUMBER", "DEC", "NUM", "SMALLINT", "TINYINT")):
        return "numerics"
    return "strings"


def _pk_targets(config: dict[str, Any]) -> set[str]:
    """Cibles correspondant à la clé unique (pour le regroupement / les tests)."""
    unique_key = config.get("unique_key", NO_UNIQUE_KEY)
    if isinstance(unique_key, list):
        return set(unique_key)
    if unique_key != NO_UNIQUE_KEY:
        return {unique_key}
    return set()


def _select_body(config: dict[str, Any], indent: str = "        ") -> str:
    """Construit le corps du SELECT, colonnes regroupées par type avec commentaires."""
    pk_targets = _pk_targets(config)
    grouped: dict[str, list[str]] = {key: [] for key, _ in _GROUP_ORDER}
    raw_exprs: list[str] = []

    for col in config["columns"]:
        if not col.get("include", True):
            continue
        expr = build_sql_expression(
            col["source"],
            col["cast"],
            coalesce=col.get("coalesce"),
            string_case=col.get("string_case", "lower"),
            trim=col.get("trim", True),
        )
        group = _column_group(col["target"], col["cast"], pk_targets)
        grouped[group].append(f"{expr} as {col['target']}")
        if col.get("keep_raw"):
            raw_exprs.append(f'"{col["source"]}" as raw_{col["target"]}')

    # (is_expression, texte) — les commentaires ne portent pas de virgule.
    rows: list[tuple[bool, str]] = []
    for key, label in _GROUP_ORDER:
        if grouped[key]:
            rows.append((False, label))
            rows.extend((True, expr) for expr in grouped[key])
    if raw_exprs:
        rows.append((False, "-- raw (colonnes brutes conservées)"))
        rows.extend((True, expr) for expr in raw_exprs)

    if not any(is_expr for is_expr, _ in rows):
        return f"{indent}*"

    last_expr = max(i for i, (is_expr, _) in enumerate(rows) if is_expr)
    lines = [
        f"{indent}{text}{',' if is_expr and i != last_expr else ''}"
        for i, (is_expr, text) in enumerate(rows)
    ]
    return "\n".join(lines)


def generate_sql(config: dict[str, Any]) -> str:
    """Génère le SQL DBT du modèle staging."""
    source = config["source"]
    model = config["model"]
    materialized = model["materialized"]
    delta = config.get("delta", {})

    parts: list[str] = []

    if config.get("purge", {}).get("enabled"):
        parts.append(
            "{# PURGE: ce modèle contient des colonnes potentiellement sensibles, "
            "vérifier la politique de rétention avant exécution. #}"
        )

    parts.append(_config_block(config))

    source_ref = f"{{{{ source('{source['name']}', '{source['table']}') }}}}"

    select_body = _select_body(config)

    where_clause = ""
    if materialized == "incremental" and delta.get("enabled") and delta.get("column"):
        delta_col = delta["column"]
        # Colonne cible normalisée correspondante (pour le max côté destination).
        target = next(
            (c["target"] for c in config["columns"] if c["source"] == delta_col),
            delta_col,
        )
        where_clause = (
            "\n    {% if is_incremental() %}\n"
            f'    where "{delta_col}" > (select max({target}) from {{{{ this }}}})\n'
            "    {% endif %}"
        )

    cte = (
        "with source as (\n"
        f"    select * from {source_ref}\n"
        "),\n\n"
        "renamed as (\n"
        "    select\n"
        f"{select_body}\n"
        "    from source"
        f"{where_clause}\n"
        ")\n\n"
        "select * from renamed"
    )

    parts.append(cte)
    return "\n\n".join(parts) + "\n"


def generate_schema_yml(config: dict[str, Any]) -> str:
    """Génère le ``schema.yml`` (documentation + tests) du modèle."""
    model = config["model"]
    unique_key = config.get("unique_key", NO_UNIQUE_KEY)

    if isinstance(unique_key, list):
        pk_targets = set(unique_key)
    elif unique_key != NO_UNIQUE_KEY:
        pk_targets = {unique_key}
    else:
        pk_targets = set()

    columns_doc: list[dict[str, Any]] = []
    for col in config["columns"]:
        if not col.get("include", True):
            continue
        entry: dict[str, Any] = {"name": col["target"]}
        if col["target"] in pk_targets:
            # Clé unique simple → unique + not_null ; clé composite → not_null par colonne.
            entry["tests"] = ["unique", "not_null"] if not isinstance(unique_key, list) else ["not_null"]
        columns_doc.append(entry)

    doc: dict[str, Any] = {
        "version": 2,
        "models": [
            {
                "name": model["name"],
                "description": f"Modèle staging généré depuis {config['source']['table']}.",
                "columns": columns_doc,
            }
        ],
    }
    return dump_yaml(doc)


def generate_model(config: dict[str, Any]) -> dict[str, str]:
    """Génère l'ensemble des artefacts du modèle.

    Returns:
        ``{"model_name", "sql", "schema_yml"}``.
    """
    return {
        "model_name": config["model"]["name"],
        "sql": generate_sql(config),
        "schema_yml": generate_schema_yml(config),
    }
