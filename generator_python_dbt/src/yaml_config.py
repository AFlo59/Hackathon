"""Template YAML de config staging + helpers de sérialisation.

Le « config staging » est le document pivot de l'application : produit à partir
des métadonnées de table, édité par l'utilisateur (YAML brut ou ``st.data_editor``),
puis consommé par :mod:`src.model_generator` pour produire le SQL et le ``schema.yml``.

Format du document :

.. code-block:: yaml

    source:
      name: raw
      table: T_COMMANDE
    model:
      name: stg_commande
      materialized: incremental   # view | table | incremental | ephemeral
      schema: staging
      tags: [staging]
      meta: {owner: data-team}
    unique_key: id                 # str | list[str] | "TODO_SET_UNIQUE_KEY"
    delta:
      enabled: true
      column: UPDATED_AT
    purge:
      enabled: false
    normalization:
      prefix: "T_CMD_"
      suffix: ""
    columns:
      - source: T_CMD_NOM
        target: nom
        cast: VARCHAR
        include: true
        keep_raw: false
        string_case: lower         # lower | upper | none
        trim: true
        coalesce: null             # littéral SQL ou null
        is_string: true
"""

from __future__ import annotations

import re
from typing import Any

import yaml

from .normalizer import is_string_type, normalize_name

#: Sentinelle utilisée quand aucune clé unique n'a pu être déduite.
NO_UNIQUE_KEY = "TODO_SET_UNIQUE_KEY"

# Noms de colonnes (normalisés) évoquant une date de mise à jour → delta / freshness.
_DELTA_HINTS = ("updated_at", "update_date", "modified_at", "maj", "date_maj", "last_update")

_NUMBER_RE = re.compile(r"NUMBER\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)", re.IGNORECASE)


# --------------------------------------------------------------------------- #
# Sérialisation YAML
# --------------------------------------------------------------------------- #
class _NullDumper(yaml.Dumper):
    """Dumper YAML : ``None`` → champ vide, ordre des clés préservé."""


def _represent_none(dumper: yaml.Dumper, _: Any) -> yaml.Node:
    return dumper.represent_scalar("tag:yaml.org,2002:null", "")


_NullDumper.add_representer(type(None), _represent_none)


def dump_yaml(data: Any) -> str:
    """Sérialise ``data`` en YAML (``sort_keys=False``, ``allow_unicode=True``)."""
    return yaml.dump(
        data,
        Dumper=_NullDumper,
        sort_keys=False,
        allow_unicode=True,
        default_flow_style=False,
    )


def load_yaml(text: str) -> Any:
    """Désérialise un document YAML de config."""
    return yaml.safe_load(text)


# --------------------------------------------------------------------------- #
# Inférence de types
# --------------------------------------------------------------------------- #
def infer_cast(snowflake_type: str) -> str:
    """Déduit le type cible (``::TYPE``) optimisé depuis un type Snowflake brut.

    * ``NUMBER(38,0)``  → ``BIGINT``   (échelle nulle → entier)
    * ``NUMBER(18,4)``  → ``FLOAT``    (échelle non nulle → flottant)
    * ``VARCHAR(256)``  → ``VARCHAR``
    * ``TIMESTAMP_NTZ`` → ``TIMESTAMP_NTZ`` (inchangé)
    """
    raw = snowflake_type.strip().upper()

    match = _NUMBER_RE.match(raw)
    if match:
        scale = int(match.group(2))
        return "BIGINT" if scale == 0 else "FLOAT"

    if raw.startswith("NUMBER") or raw.startswith("DECIMAL") or raw.startswith("NUMERIC"):
        # NUMBER sans précision explicite : entier par défaut.
        return "BIGINT"
    if raw.startswith(("VARCHAR", "CHAR", "TEXT", "STRING", "NVARCHAR", "NCHAR")):
        return "VARCHAR"
    if raw.startswith("TIMESTAMP"):
        return raw  # conserve la variante NTZ / LTZ / TZ
    if raw.startswith(("FLOAT", "DOUBLE", "REAL")):
        return "FLOAT"
    if raw.startswith("INT") or raw in ("BIGINT", "SMALLINT", "TINYINT", "BYTEINT"):
        return "BIGINT"
    if raw.startswith("BOOL"):
        return "BOOLEAN"
    if raw.startswith("DATE"):
        return "DATE"
    return raw


def _default_coalesce(cast: str) -> str | None:
    """Valeur de repli par défaut désactivée : l'utilisateur l'active explicitement."""
    return None


# Préfixes de nom de table fréquents (Oracle/SQL Server style) à retirer pour
# obtenir un nom d'entité propre : ``T_COMMANDE`` → ``commande``.
_TABLE_PREFIXES = ("t_", "tbl_", "dim_", "fact_", "fct_", "stg_", "ref_")


def entity_name(table: str, *, prefix: str = "", suffix: str = "") -> str:
    """Déduit le nom d'entité dbt depuis un nom de table.

    Retire le préfixe/suffixe métier puis un préfixe technique courant
    (``T_``, ``TBL_``, ``DIM_``…) afin de produire un nom idiomatique.
    """
    name = normalize_name(table, prefix=prefix, suffix=suffix)
    for tech in _TABLE_PREFIXES:
        if name.startswith(tech):
            name = name[len(tech):]
            break
    return name or normalize_name(table)


def build_model_name(source_name: str, table: str, *, prefix: str = "", suffix: str = "") -> str:
    """Construit le nom de modèle staging idiomatique ``stg_<source>__<entity>``.

    Cf. style guide dbt : le double underscore sépare système source et entité.
    """
    return f"stg_{normalize_name(source_name)}__{entity_name(table, prefix=prefix, suffix=suffix)}"


# --------------------------------------------------------------------------- #
# Détection delta / clé unique
# --------------------------------------------------------------------------- #
def detect_delta_column(columns: list[dict[str, Any]]) -> str | None:
    """Repère une colonne TIMESTAMP de mise à jour pour le filtrage incrémental.

    Args:
        columns: liste de dicts ``{"name", "type", ...}``.

    Returns:
        Le nom source de la colonne candidate, ou ``None``.
    """
    for col in columns:
        if not str(col.get("type", "")).upper().startswith("TIMESTAMP"):
            continue
        normalized = normalize_name(str(col["name"]))
        if any(hint in normalized for hint in _DELTA_HINTS):
            return str(col["name"])
    return None


def detect_unique_key(
    columns: list[dict[str, Any]],
    *,
    prefix: str = "",
    suffix: str = "",
) -> str | list[str]:
    """Construit ``unique_key`` à partir des colonnes marquées clé primaire.

    Les noms sont normalisés avec ``prefix``/``suffix`` pour rester alignés sur
    les noms cibles des colonnes du modèle.
    """
    pks = [
        normalize_name(str(c["name"]), prefix=prefix, suffix=suffix)
        for c in columns
        if c.get("primary_key")
    ]
    if not pks:
        return NO_UNIQUE_KEY
    if len(pks) == 1:
        return pks[0]
    return pks


# --------------------------------------------------------------------------- #
# Construction de la config staging
# --------------------------------------------------------------------------- #
def build_staging_config(
    *,
    source_name: str,
    table: str,
    columns: list[dict[str, Any]],
    prefix: str = "",
    suffix: str = "",
    model_name: str | None = None,
    materialized: str = "view",
    schema: str = "staging",
    tags: list[str] | None = None,
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Génère le document de config staging à partir des métadonnées de table.

    Args:
        source_name: nom du source DBT (ex : ``raw``).
        table: nom de la table source.
        columns: liste de dicts ``{"name", "type", "nullable", "primary_key"}``.
        prefix / suffix: éléments à retirer lors de la normalisation des noms.
        model_name: nom du modèle ; déduit en ``stg_<source>__<entity>`` si absent.
        materialized: ``view`` (défaut, recommandation dbt pour le staging) /
            ``table`` / ``incremental`` / ``ephemeral``.
        schema: schéma cible du modèle.
        tags / meta: métadonnées DBT.

    Returns:
        Le document de config sous forme de ``dict``.

    Note:
        Le style guide dbt recommande de matérialiser les modèles staging en
        ``view`` (fraîcheur garantie, pas d'espace gaspillé). Une colonne de
        mise à jour est tout de même auto-détectée (``delta.column``) pour
        permettre de basculer aisément en ``incremental``.
    """
    delta_col = detect_delta_column(columns)
    unique_key = detect_unique_key(columns, prefix=prefix, suffix=suffix)

    config_columns: list[dict[str, Any]] = []
    for col in columns:
        cast = infer_cast(str(col["type"]))
        config_columns.append(
            {
                "source": str(col["name"]),
                "target": normalize_name(str(col["name"]), prefix=prefix, suffix=suffix),
                "cast": cast,
                "include": True,
                "keep_raw": False,
                "string_case": "lower" if is_string_type(cast) else "none",
                "trim": is_string_type(cast),
                "coalesce": _default_coalesce(cast),
                "is_string": is_string_type(cast),
            }
        )

    return {
        "source": {"name": source_name, "table": table},
        "model": {
            "name": model_name or build_model_name(
                source_name, table, prefix=prefix, suffix=suffix
            ),
            "materialized": materialized,
            "schema": schema,
            "tags": tags or ["staging"],
            "meta": meta or {},
        },
        "unique_key": unique_key,
        "delta": {"enabled": bool(delta_col), "column": delta_col},
        "purge": {"enabled": False},
        "normalization": {"prefix": prefix, "suffix": suffix},
        "columns": config_columns,
    }
