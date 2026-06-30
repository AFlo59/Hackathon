"""Tests du pipeline de normalisation des noms et des expressions SQL."""

from __future__ import annotations

from src.normalizer import build_sql_expression, normalize_name


def test_snake_case_camel() -> None:
    assert normalize_name("CustomerID") == "customer_id"


def test_snake_case_acronym() -> None:
    assert normalize_name("MyHTTPSRequest") == "my_https_request"


def test_strip_prefix() -> None:
    assert normalize_name("T_CMD_NOM", prefix="T_CMD_") == "nom"


def test_strip_suffix() -> None:
    assert normalize_name("NOM_STG", suffix="_STG") == "nom"


def test_remove_accents() -> None:
    assert normalize_name("PrénomÀ") == "prenoma"


def test_remove_special_chars() -> None:
    assert normalize_name("col-name!2") == "col_name_2"


def test_combined_pipeline() -> None:
    assert normalize_name("T_CLI_Prénom-Client", prefix="T_CLI_") == "prenom_client"


def test_build_sql_expression_string() -> None:
    expr = build_sql_expression("NAME", "VARCHAR", coalesce="''", string_case="lower")
    assert "TRIM(" in expr
    assert "LOWER(" in expr
    assert "COALESCE(" in expr
    assert expr.endswith("::VARCHAR")


def test_build_sql_expression_numeric() -> None:
    expr = build_sql_expression("AMOUNT", "FLOAT", coalesce="0")
    assert "TRIM(" not in expr
    assert "COALESCE(" in expr
    assert expr.endswith("::FLOAT")


def test_idempotence() -> None:
    once = normalize_name("CustomerID")
    assert normalize_name(once) == once
