"""Fixtures partagées pour la suite de tests."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Rend le paquet `src` importable quand pytest est lancé depuis n'importe où.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.yaml_config import build_staging_config  # noqa: E402


@pytest.fixture
def mock_columns() -> list[dict[str, object]]:
    """Métadonnées de colonnes représentatives d'une table de commandes."""
    return [
        {"name": "T_CMD_ID", "type": "NUMBER(38,0)", "nullable": False, "primary_key": True},
        {"name": "T_CMD_NOM", "type": "VARCHAR(256)", "nullable": True, "primary_key": False},
        {"name": "T_CMD_MONTANT", "type": "NUMBER(18,4)", "nullable": True, "primary_key": False},
        {"name": "T_CMD_MAJ", "type": "TIMESTAMP_NTZ", "nullable": True, "primary_key": False},
    ]


@pytest.fixture
def mock_config(mock_columns: list[dict[str, object]]) -> dict[str, object]:
    """Config staging construite à partir de ``mock_columns`` (préfixe ``T_CMD_``)."""
    return build_staging_config(
        source_name="raw",
        table="T_COMMANDE",
        columns=mock_columns,
        prefix="T_CMD_",
        materialized="incremental",
    )
