"""Pipeline de normalisation des noms de colonnes.

Transforme un nom de colonne source (souvent en `CamelCase`, `SCREAMING_CASE`,
préfixé/suffixé ou accentué) en un identifiant `snake_case` propre, puis construit
l'expression SQL Snowflake optimisée associée.

L'ordre des étapes est important :

1. retrait du préfixe / suffixe métier (ex : ``T_CMD_``, ``_STG``) ;
2. découpe ``snake_case`` (réalisée AVANT le retrait d'accents pour que les
   caractères accentués ne créent pas de fausses frontières de mots) ;
3. suppression des accents (NFKD → ASCII) ;
4. remplacement des caractères spéciaux par ``_`` ;
5. passage en minuscules et nettoyage des underscores.
"""

from __future__ import annotations

import re
import unicodedata

# Frontière « fin d'acronyme / mot capitalisé » : ``HTTPSRequest`` → ``HTTPS_Request``.
_CAMEL_ACRONYM = re.compile(r"(.)([A-Z][a-z]+)")
# Frontière « minuscule/chiffre → majuscule » : ``customerID`` → ``customer_ID``.
_CAMEL_BOUNDARY = re.compile(r"([a-z0-9])([A-Z])")
# Tout ce qui n'est pas alphanumérique ASCII devient un underscore.
_NON_ALNUM = re.compile(r"[^a-zA-Z0-9]+")
# Underscores multiples à réduire.
_MULTI_UNDERSCORE = re.compile(r"_+")

# Types Snowflake considérés comme « chaîne » (déclenchent TRIM + casse).
_STRING_TYPES = ("VARCHAR", "CHAR", "TEXT", "STRING", "NVARCHAR", "NCHAR")


def is_string_type(cast: str) -> bool:
    """Indique si un type/cast Snowflake correspond à une chaîne de caractères."""
    return cast.upper().startswith(_STRING_TYPES)


def _to_snake(name: str) -> str:
    """Insère des underscores aux frontières de casse (sur ASCII uniquement)."""
    name = _CAMEL_ACRONYM.sub(r"\1_\2", name)
    name = _CAMEL_BOUNDARY.sub(r"\1_\2", name)
    return name


def _strip_accents(text: str) -> str:
    """Supprime les diacritiques : ``Prénom`` → ``Prenom``."""
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_name(
    name: str,
    *,
    prefix: str | None = None,
    suffix: str | None = None,
) -> str:
    """Normalise un nom de colonne en ``snake_case`` ASCII minuscule.

    Args:
        name: nom source brut.
        prefix: préfixe métier à retirer s'il est présent (ex : ``T_CMD_``).
        suffix: suffixe métier à retirer s'il est présent (ex : ``_STG``).

    Returns:
        L'identifiant normalisé. La fonction est idempotente.
    """
    result = name.strip()

    if prefix and result.upper().startswith(prefix.upper()):
        result = result[len(prefix):]
    if suffix and result.upper().endswith(suffix.upper()):
        result = result[: len(result) - len(suffix)]

    result = _to_snake(result)
    result = _strip_accents(result)
    result = _NON_ALNUM.sub("_", result)
    result = _MULTI_UNDERSCORE.sub("_", result)
    result = result.strip("_").lower()
    return result


def build_sql_expression(
    source_name: str,
    cast_type: str,
    *,
    coalesce: str | None = None,
    string_case: str = "lower",
    trim: bool = True,
) -> str:
    """Construit l'expression SQL Snowflake optimisée d'une colonne.

    Conventions de performance (cf. CLAUDE.md) :

    * cast via la syntaxe ``::TYPE`` (plus performante que ``CAST()``) ;
    * ``TRIM`` + normalisation de casse uniquement sur les chaînes ;
    * ``COALESCE`` appliqué avant le cast quand une valeur par défaut est fournie.

    Args:
        source_name: nom de colonne source (sera entre guillemets doubles).
        cast_type: type cible Snowflake (ex : ``VARCHAR``, ``BIGINT``, ``FLOAT``).
        coalesce: valeur de repli littérale (ex : ``"''"`` ou ``"0"``) ; ``None`` désactive.
        string_case: ``"lower"``, ``"upper"`` ou ``"none"`` (ignoré hors chaîne).
        trim: applique ``TRIM`` sur les chaînes (ignoré hors chaîne).

    Returns:
        L'expression SQL sans alias ``AS``.
    """
    is_string = is_string_type(cast_type)
    expr = f'"{source_name}"'

    if is_string and trim:
        expr = f"TRIM({expr})"
    if is_string and string_case == "lower":
        expr = f"LOWER({expr})"
    elif is_string and string_case == "upper":
        expr = f"UPPER({expr})"

    if coalesce is not None:
        expr = f"COALESCE({expr}, {coalesce})"

    return f"{expr}::{cast_type}"
