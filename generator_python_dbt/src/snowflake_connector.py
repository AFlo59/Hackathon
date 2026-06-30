"""Connexion Snowflake + introspection des métadonnées.

Encapsule l'ouverture de connexion et les requêtes ``SHOW`` / ``DESC TABLE``
utilisées pour découvrir databases, schémas, tables et colonnes.

L'import de ``snowflake.connector`` est différé : le module reste importable
(et testable) sans le driver installé.
"""

from __future__ import annotations

from typing import Any


def _import_driver() -> Any:
    try:
        import snowflake.connector as sf  # type: ignore
    except ImportError as exc:  # pragma: no cover - dépend de l'environnement
        raise RuntimeError(
            "Le paquet 'snowflake-connector-python' est requis pour se connecter. "
            "Installez-le via : pip install snowflake-connector-python"
        ) from exc
    return sf


class SnowflakeConnector:
    """Gère la connexion et l'introspection d'un compte Snowflake."""

    def __init__(
        self,
        *,
        account: str,
        user: str,
        password: str | None = None,
        warehouse: str | None = None,
        database: str | None = None,
        schema: str | None = None,
        role: str | None = None,
    ) -> None:
        self.params: dict[str, Any] = {
            "account": account,
            "user": user,
            "password": password,
            "warehouse": warehouse,
            "database": database,
            "schema": schema,
            "role": role,
        }
        self._conn: Any | None = None

    # ------------------------------------------------------------------ #
    # Cycle de vie
    # ------------------------------------------------------------------ #
    def connect(self) -> None:
        """Ouvre la connexion (idempotent tant qu'elle reste valide)."""
        if self._conn is not None:
            return
        sf = _import_driver()
        clean = {k: v for k, v in self.params.items() if v is not None}
        self._conn = sf.connect(**clean)

    def close(self) -> None:
        """Ferme la connexion si elle est ouverte."""
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def __enter__(self) -> SnowflakeConnector:
        self.connect()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    # Requêtes
    # ------------------------------------------------------------------ #
    def _fetchall(self, query: str) -> list[tuple[Any, ...]]:
        self.connect()
        assert self._conn is not None
        cur = self._conn.cursor()
        try:
            cur.execute(query)
            return cur.fetchall()
        finally:
            cur.close()

    def list_databases(self) -> list[str]:
        """Liste les databases accessibles."""
        rows = self._fetchall("SHOW DATABASES")
        return [str(r[1]) for r in rows]

    def list_schemas(self, database: str) -> list[str]:
        """Liste les schémas d'une database."""
        rows = self._fetchall(f'SHOW SCHEMAS IN DATABASE "{database}"')
        return [str(r[1]) for r in rows]

    def list_tables(self, database: str, schema: str) -> list[str]:
        """Liste les tables et vues d'un schéma."""
        rows = self._fetchall(f'SHOW TABLES IN SCHEMA "{database}"."{schema}"')
        tables = [str(r[1]) for r in rows]
        view_rows = self._fetchall(f'SHOW VIEWS IN SCHEMA "{database}"."{schema}"')
        tables.extend(str(r[1]) for r in view_rows)
        return tables

    def describe_table(
        self, database: str, schema: str, table: str
    ) -> list[dict[str, Any]]:
        """Introspecte les colonnes via ``DESC TABLE``.

        Returns:
            Liste de dicts ``{"name", "type", "nullable", "primary_key"}``.
        """
        fqn = f'"{database}"."{schema}"."{table}"'
        rows = self._fetchall(f"DESC TABLE {fqn}")
        return [self._parse_desc_row(r) for r in rows]

    @staticmethod
    def _parse_desc_row(row: tuple[Any, ...]) -> dict[str, Any]:
        """Convertit une ligne ``DESC TABLE`` en métadonnée de colonne.

        Colonnes Snowflake : name, type, kind, null?, default, primary key, ...
        """
        name = str(row[0])
        col_type = str(row[1])
        nullable = str(row[3]).upper() == "Y" if len(row) > 3 else True
        primary_key = str(row[5]).upper() == "Y" if len(row) > 5 else False
        return {
            "name": name,
            "type": col_type,
            "nullable": nullable,
            "primary_key": primary_key,
        }

    def preview(
        self, database: str, schema: str, table: str, limit: int = 10
    ) -> list[tuple[Any, ...]]:
        """Retourne un aperçu de ``limit`` lignes de la table."""
        fqn = f'"{database}"."{schema}"."{table}"'
        return self._fetchall(f"SELECT * FROM {fqn} LIMIT {int(limit)}")
