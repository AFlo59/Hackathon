"""Tests de la logique pure du connecteur (parsing DESC TABLE).

Les méthodes réseau ne sont pas testées ici (pas de connexion Snowflake) ;
on vérifie le parsing des lignes ``DESC TABLE`` qui alimente toute la chaîne.
"""

from __future__ import annotations

from src.snowflake_connector import SnowflakeConnector


def _row(name, type_, kind="COLUMN", null="Y", default=None, pk="N",
         uk="N", check=None, expr=None, comment=None):
    return (name, type_, kind, null, default, pk, uk, check, expr, comment)


def test_parse_desc_row_basic() -> None:
    parsed = SnowflakeConnector._parse_desc_row(
        _row("ID", "NUMBER(38,0)", null="N", pk="Y", comment="Clé")
    )
    assert parsed == {
        "name": "ID",
        "type": "NUMBER(38,0)",
        "nullable": False,
        "primary_key": True,
        "comment": "Clé",
    }


def test_parse_desc_row_nullable_no_comment() -> None:
    parsed = SnowflakeConnector._parse_desc_row(_row("NOM", "VARCHAR(50)"))
    assert parsed["nullable"] is True
    assert parsed["primary_key"] is False
    assert parsed["comment"] is None


def test_parse_desc_row_short_tuple() -> None:
    # Certaines variantes ne renvoient que name/type : pas d'IndexError.
    parsed = SnowflakeConnector._parse_desc_row(("X", "FLOAT"))
    assert parsed["name"] == "X"
    assert parsed["comment"] is None
