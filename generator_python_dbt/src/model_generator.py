"""Génération du SQL staging + ``schema.yml`` à partir du config staging.

Consomme le document produit par :func:`src.yaml_config.build_staging_config`
(éventuellement édité par l'utilisateur) et produit :

* un fichier ``.sql`` DBT (CTE ``source`` → ``renamed`` → ``select``) optimisé
  pour Snowflake (casts ``::TYPE``, ``TRIM``/``LOWER`` sur chaînes, filtre delta
  incrémental) ;
* le ``schema.yml`` associé (tests sur la clé unique).
"""

from __future__ import annotations

import re
from typing import Any

from .normalizer import build_sql_expression
from .yaml_config import NO_UNIQUE_KEY, dump_yaml


def _format_unique_key(unique_key: Any) -> str:
    """Rend ``unique_key`` pour le bloc ``config`` Jinja."""
    if isinstance(unique_key, list):
        inner = ", ".join(f"'{k}'" for k in unique_key)
        return f"[{inner}]"
    return f"'{unique_key}'"


def _str_list(values: Any) -> str:
    """Rend une liste de chaînes pour un argument Jinja : ``['a', 'b']``."""
    return "[" + ", ".join(f"'{v}'" for v in values) + "]"


def _config_block(config: dict[str, Any]) -> str:
    """Construit le bloc ``{{ config(...) }}``."""
    model = config["model"]
    materialized = model["materialized"]
    unique_key = config.get("unique_key", NO_UNIQUE_KEY)

    lines = [f"    materialized='{materialized}'"]
    if materialized == "incremental":
        lines.append("    incremental_strategy='merge'")
        on_change = config.get("on_schema_change")
        if on_change:
            lines.append(f"    on_schema_change='{on_change}'")
    if materialized in ("incremental", "table") and unique_key != NO_UNIQUE_KEY:
        lines.append(f"    unique_key={_format_unique_key(unique_key)}")

    # Cluster keys — uniquement pour table / incremental (pas view ni ephemeral).
    cluster = config.get("cluster_by", {})
    if materialized in ("incremental", "table") and cluster.get("enabled") and cluster.get("columns"):
        lines.append(f"    cluster_by={_str_list(cluster['columns'])}")

    if model.get("tags"):
        lines.append(f"    tags={_str_list(model['tags'])}")
    if model.get("schema"):
        lines.append(f"    schema='{model['schema']}'")

    # Hooks
    hooks = config.get("hooks", {})
    if hooks.get("pre_hook"):
        lines.append(f"    pre_hook={_str_list(hooks['pre_hook'])}")
    if hooks.get("post_hook"):
        lines.append(f"    post_hook={_str_list(hooks['post_hook'])}")

    # Grants dbt natifs : {select: [ROLE_A, ROLE_B]}
    grants = config.get("grants", {})
    if grants:
        inner = ", ".join(f"'{priv}': {_str_list(roles)}" for priv, roles in grants.items())
        lines.append(f"    grants={{{inner}}}")

    # persist_docs : propagation des descriptions dans Snowflake
    persist = config.get("persist_docs", {})
    if persist.get("relation") or persist.get("columns"):
        lines.append(
            f"    persist_docs={{'relation': {bool(persist.get('relation'))}, "
            f"'columns': {bool(persist.get('columns'))}}}"
        )

    body = ",\n".join(lines)
    return "{{\n  config(\n" + body + "\n  )\n}}"


# Ordre des groupes de colonnes.
_GROUP_KEYS: tuple[str, ...] = ("ids", "strings", "numerics", "booleans", "dates", "timestamps")

# Libellés de section par maillon dbt. Le staging suit le style guide dbt
# (ids/strings/numerics…) ; les autres maillons utilisent des libellés sémantiques.
_LAYER_LABELS: dict[str, dict[str, str]] = {
    "staging": {
        "ids": "-- ids", "strings": "-- strings", "numerics": "-- numerics",
        "booleans": "-- booleans", "dates": "-- dates", "timestamps": "-- timestamps",
        "raw": "-- raw (colonnes brutes conservées)", "audit": "-- audit",
    },
    "intermediate": {
        "ids": "-- [Clés de jointure]", "strings": "-- [Dimensions enrichies]",
        "numerics": "-- [Métriques pré-calculées]", "booleans": "-- [Flags / indicateurs métier]",
        "dates": "-- [Dates / périodes]", "timestamps": "-- [Timestamps]",
        "raw": "-- [Colonnes brutes (raw)]", "audit": "-- [Colonnes d'audit]",
    },
    "marts_fct": {
        "ids": "-- [Clés de dimension (FK)]", "strings": "-- [Dimensions]",
        "numerics": "-- [Métriques / faits]", "booleans": "-- [Flags]",
        "dates": "-- [Dates / périodes]", "timestamps": "-- [Timestamps]",
        "raw": "-- [Colonnes brutes (raw)]", "audit": "-- [Colonnes d'audit]",
    },
    "marts_dim": {
        "ids": "-- [Clé naturelle / surrogate]", "strings": "-- [Attributs descriptifs]",
        "numerics": "-- [Attributs numériques]", "booleans": "-- [Flags]",
        "dates": "-- [Dates de validité]", "timestamps": "-- [Timestamps]",
        "raw": "-- [Colonnes brutes (raw)]", "audit": "-- [Colonnes d'audit]",
    },
}

_LAYER_DESC: dict[str, str] = {
    "staging": "staging (brut nettoyé, 1 source = 1 modèle)",
    "intermediate": "intermediate (jointures, agrégations légères)",
    "marts_fct": "marts / fact (métriques, faits)",
    "marts_dim": "marts / dimension (attributs descriptifs)",
}


def _labels(config: dict[str, Any]) -> dict[str, str]:
    return _LAYER_LABELS.get(config["model"].get("layer", "staging"), _LAYER_LABELS["staging"])


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


def _audit_expressions() -> list[str]:
    """Colonnes d'audit dbt ajoutées en fin de modèle."""
    return [
        "current_timestamp() as _loaded_at",
        "'{{ invocation_id }}' as _dbt_invocation_id",
    ]


def _select_body(config: dict[str, Any], indent: str = "        ") -> str:
    """Construit le corps du SELECT, colonnes regroupées par type avec commentaires."""
    pk_targets = _pk_targets(config)
    labels = _labels(config)
    keep_all_raw = config.get("normalization", {}).get("keep_all_raw", False)
    grouped: dict[str, list[str]] = {key: [] for key in _GROUP_KEYS}
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
        if col.get("keep_raw") or keep_all_raw:
            raw_exprs.append(f'"{col["source"]}" as raw_{col["target"]}')

    # (is_expression, texte) — les commentaires ne portent pas de virgule.
    rows: list[tuple[bool, str]] = []
    for key in _GROUP_KEYS:
        if grouped[key]:
            rows.append((False, labels[key]))
            rows.extend((True, expr) for expr in grouped[key])
    if raw_exprs:
        rows.append((False, labels["raw"]))
        rows.extend((True, expr) for expr in raw_exprs)
    if config.get("audit", {}).get("enabled"):
        rows.append((False, labels["audit"]))
        rows.extend((True, expr) for expr in _audit_expressions())

    if not any(is_expr for is_expr, _ in rows):
        return f"{indent}*"

    last_expr = max(i for i, (is_expr, _) in enumerate(rows) if is_expr)
    lines = [
        f"{indent}{text}{',' if is_expr and i != last_expr else ''}"
        for i, (is_expr, text) in enumerate(rows)
    ]
    return "\n".join(lines)


def _render_value(value: Any) -> str:
    """Rend une valeur SQL : numérique brute, sinon chaîne échappée."""
    text = str(value)
    if re.fullmatch(r"-?\d+(\.\d+)?", text):
        return text
    return "'" + text.replace("'", "''") + "'"


def _render_filter(flt: dict[str, Any]) -> str:
    """Rend un filtre de colonne en condition SQL."""
    col = flt.get("column", "")
    operator = flt.get("operator", "in")
    if operator == "custom":
        return str(flt.get("custom_expr", "")).strip()
    if operator in ("in", "not_in"):
        values = ", ".join(_render_value(v) for v in flt.get("values", []))
        keyword = "in" if operator == "in" else "not in"
        return f'"{col}" {keyword} ({values})'
    if operator == "between":
        vals = flt.get("values", [])
        if len(vals) >= 2:
            return f'"{col}" between {_render_value(vals[0])} and {_render_value(vals[1])}'
    return ""


def _where_block(config: dict[str, Any], indent: str = "    ") -> str:
    """Construit le bloc WHERE : filtres métier (AND/OR) + filtre delta incrémental.

    Le filtre delta est encadré par ``{% if is_incremental() %}`` ; on s'appuie
    sur ``where 1=1`` pour composer trivialement filtres métier et delta.
    """
    materialized = config["model"]["materialized"]
    delta = config.get("delta", {})
    wc = config.get("where_clause", {})
    mode = "or" if str(wc.get("mode", "and")).lower() == "or" else "and"

    rendered = [r for f in wc.get("filters", []) if f and (r := _render_filter(f))]
    delta_active = (
        materialized == "incremental" and delta.get("enabled") and delta.get("column")
    )
    if not rendered and not delta_active:
        return ""

    lines = [f"{indent}where 1=1"]
    if rendered:
        joiner = f"\n{indent}  {mode} "
        joined = joiner.join(rendered)
        if mode == "or" and len(rendered) > 1:
            joined = f"({joined})"
        lines.append(f"{indent}  and {joined}")
    if delta_active:
        delta_col = delta["column"]
        target = next(
            (c["target"] for c in config["columns"] if c["source"] == delta_col),
            delta_col,
        )
        lines.append(f"{indent}{{% if is_incremental() %}}")
        lines.append(f'{indent}  and "{delta_col}" > (select max({target}) from {{{{ this }}}})')
        lines.append(f"{indent}{{% endif %}}")
    return "\n" + "\n".join(lines)


def _banner(config: dict[str, Any]) -> str:
    """Bannière d'en-tête décrivant le modèle et son maillon."""
    model = config["model"]
    layer = model.get("layer", "staging")
    source = config["source"]
    line = "-- " + "=" * 61
    return "\n".join([
        line,
        f"-- {layer.upper()} : {model['name']}",
        f"-- Source  : {source['name']}.{source['table']}",
        f"-- Maillon : {_LAYER_DESC.get(layer, layer)}",
        line,
    ])


def generate_sql(config: dict[str, Any]) -> str:
    """Génère le SQL DBT du modèle staging."""
    source = config["source"]

    parts: list[str] = [_banner(config)]

    if config.get("purge", {}).get("enabled"):
        parts.append(
            "{# PURGE: ce modèle contient des colonnes potentiellement sensibles, "
            "vérifier la politique de rétention avant exécution. #}"
        )

    parts.append(_config_block(config))

    source_ref = f"{{{{ source('{source['name']}', '{source['table']}') }}}}"

    select_body = _select_body(config)
    where_clause = _where_block(config)

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
        if col.get("comment"):
            entry["description"] = col["comment"]
        if col["target"] in pk_targets:
            # Clé unique simple → unique + not_null ; clé composite → not_null par colonne.
            entry["tests"] = ["unique", "not_null"] if not isinstance(unique_key, list) else ["not_null"]
        if col.get("pii"):
            entry["meta"] = {"pii": True}
        columns_doc.append(entry)

        # Colonne brute conservée → documentée avec meta.raw.
        if col.get("keep_raw") or config.get("normalization", {}).get("keep_all_raw"):
            columns_doc.append(
                {
                    "name": f"raw_{col['target']}",
                    "description": f"Valeur brute non normalisée de {col['source']}.",
                    "meta": {"raw": True},
                }
            )

    if config.get("audit", {}).get("enabled"):
        columns_doc.append(
            {"name": "_loaded_at", "description": "Horodatage de chargement dbt."}
        )
        columns_doc.append(
            {"name": "_dbt_invocation_id", "description": "Identifiant d'exécution dbt."}
        )

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
