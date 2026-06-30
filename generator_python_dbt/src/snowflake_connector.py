"""Connexion Snowflake + introspection des métadonnées.

Encapsule l'ouverture de connexion et les requêtes ``SHOW`` / ``DESC TABLE``
utilisées pour découvrir databases, schémas, tables et colonnes.

Robustesse (cf. CLAUDE_1.md) :

* **retry exponentiel** (3 tentatives, 1s/2s/4s) sur erreurs réseau temporaires ;
* **reconnexion automatique** si la connexion est fermée / le token expiré (~4h) ;
* **authentification** par mot de passe, **Key-Pair** ou **SSO/Okta** ;
* ``DESC TABLE`` avec repli ``DESC VIEW`` pour les vues.

L'import de ``snowflake.connector`` est différé : le module reste importable
(et testable) sans le driver installé.
"""

from __future__ import annotations

import time
from typing import Any

#: Nombre de tentatives et délais (secondes) du retry exponentiel.
_MAX_RETRIES = 3
_BASE_DELAY = 1.0


def _import_driver() -> Any:
    try:
        import snowflake.connector as sf  # type: ignore
    except ImportError as exc:  # pragma: no cover - dépend de l'environnement
        raise RuntimeError(
            "Le paquet 'snowflake-connector-python' est requis pour se connecter. "
            "Installez-le via : pip install snowflake-connector-python"
        ) from exc
    return sf


def _load_private_key(path: str, passphrase: str | None) -> bytes:
    """Charge une clé privée PEM et la sérialise en DER PKCS8 (Key-Pair auth)."""
    from cryptography.hazmat.primitives import serialization  # import différé

    with open(path, "rb") as handle:
        private_key = serialization.load_pem_private_key(
            handle.read(),
            password=passphrase.encode() if passphrase else None,
        )
    return private_key.private_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


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
        authenticator: str | None = None,
        private_key_path: str | None = None,
        private_key_passphrase: str | None = None,
    ) -> None:
        """Initialise le connecteur.

        Args:
            account / user: identifiants de compte.
            password: mot de passe (auth standard).
            authenticator: ``'externalbrowser'`` (SSO) ou URL Okta
                (ex : ``'https://myorg.okta.com'``).
            private_key_path / private_key_passphrase: authentification Key-Pair.
        """
        self.params: dict[str, Any] = {
            "account": account,
            "user": user,
            "password": password,
            "warehouse": warehouse,
            "database": database,
            "schema": schema,
            "role": role,
            "authenticator": authenticator,
        }
        self.private_key_path = private_key_path
        self.private_key_passphrase = private_key_passphrase
        self._conn: Any | None = None

    # ------------------------------------------------------------------ #
    # Cycle de vie
    # ------------------------------------------------------------------ #
    def connect(self) -> None:
        """Ouvre la connexion si nécessaire (idempotent tant qu'elle est valide)."""
        if self._conn is not None and not self._is_closed():
            return
        sf = _import_driver()
        clean = {k: v for k, v in self.params.items() if v is not None}
        if self.private_key_path:
            clean.pop("password", None)
            clean["private_key"] = _load_private_key(
                self.private_key_path, self.private_key_passphrase
            )
        self._conn = sf.connect(**clean)

    def _is_closed(self) -> bool:
        """Indique si la connexion sous-jacente est fermée (token expiré, etc.)."""
        conn = self._conn
        if conn is None:
            return True
        is_closed = getattr(conn, "is_closed", None)
        try:
            return bool(is_closed()) if callable(is_closed) else False
        except Exception:  # noqa: BLE001 - défensif
            return True

    def close(self) -> None:
        """Ferme la connexion si elle est ouverte."""
        if self._conn is not None:
            try:
                self._conn.close()
            finally:
                self._conn = None

    def __enter__(self) -> SnowflakeConnector:
        self.connect()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    # Exécution avec retry + reconnexion
    # ------------------------------------------------------------------ #
    def _fetchall(self, query: str) -> list[tuple[Any, ...]]:
        """Exécute une requête avec retry exponentiel et reconnexion auto."""
        sf = _import_driver()
        transient = (sf.errors.OperationalError, sf.errors.DatabaseError)

        delay = _BASE_DELAY
        last_exc: Exception | None = None
        for attempt in range(_MAX_RETRIES):
            try:
                if self._conn is None or self._is_closed():
                    self._conn = None
                    self.connect()
                cur = self._conn.cursor()
                try:
                    cur.execute(query)
                    return cur.fetchall()
                finally:
                    cur.close()
            except transient as exc:  # erreur temporaire → on retente
                last_exc = exc
                self._conn = None  # force une reconnexion propre
                if attempt < _MAX_RETRIES - 1:
                    time.sleep(delay)
                    delay *= 2
        assert last_exc is not None
        raise last_exc

    # ------------------------------------------------------------------ #
    # Introspection
    # ------------------------------------------------------------------ #
    def list_databases(self) -> list[str]:
        """Liste les databases accessibles."""
        return [str(r[1]) for r in self._fetchall("SHOW DATABASES")]

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
        """Introspecte les colonnes via ``DESC TABLE`` (repli ``DESC VIEW``).

        ``SHOW TABLES`` ne distingue pas toujours correctement les vues : on
        tente ``DESC TABLE`` puis, en cas d'échec, ``DESC VIEW``.

        Returns:
            Liste de dicts ``{"name", "type", "nullable", "primary_key", "comment"}``.
        """
        fqn = f'"{database}"."{schema}"."{table}"'
        try:
            rows = self._fetchall(f"DESC TABLE {fqn}")
        except Exception:  # noqa: BLE001 - l'objet est probablement une vue
            rows = self._fetchall(f"DESC VIEW {fqn}")
        return [self._parse_desc_row(r) for r in rows]

    @staticmethod
    def _parse_desc_row(row: tuple[Any, ...]) -> dict[str, Any]:
        """Convertit une ligne ``DESC TABLE`` en métadonnée de colonne.

        Colonnes Snowflake : name, type, kind, null?, default, primary key,
        unique key, check, expression, comment.
        """
        def cell(idx: int) -> Any:
            return row[idx] if len(row) > idx else None

        nullable = str(cell(3)).upper() == "Y" if cell(3) is not None else True
        primary_key = str(cell(5)).upper() == "Y" if cell(5) is not None else False
        comment = cell(9)
        return {
            "name": str(row[0]),
            "type": str(row[1]),
            "nullable": nullable,
            "primary_key": primary_key,
            "comment": str(comment) if comment else None,
        }

    def preview(
        self, database: str, schema: str, table: str, limit: int = 10
    ) -> list[tuple[Any, ...]]:
        """Retourne un aperçu de ``limit`` lignes de la table."""
        fqn = f'"{database}"."{schema}"."{table}"'
        return self._fetchall(f"SELECT * FROM {fqn} LIMIT {int(limit)}")

    def get_table_comment(self, database: str, schema: str, table: str) -> str | None:
        """Récupère le commentaire de table via ``INFORMATION_SCHEMA.TABLES``."""
        rows = self._fetchall(
            f'SELECT COMMENT FROM "{database}".INFORMATION_SCHEMA.TABLES '
            f"WHERE TABLE_SCHEMA = '{schema}' AND TABLE_NAME = '{table}'"
        )
        if rows and rows[0][0]:
            return str(rows[0][0])
        return None

    def get_distinct_values(
        self, database: str, schema: str, table: str, column: str, limit: int = 36
    ) -> list[Any] | None:
        """Valeurs distinctes d'une colonne, ou ``None`` si > ``limit - 1``.

        Utilisé par les filtres WHERE de la page Config : si ≤ 35 valeurs, on
        propose un multiselect ; au-delà, un champ d'expression libre.
        """
        fqn = f'"{database}"."{schema}"."{table}"'
        rows = self._fetchall(
            f'SELECT DISTINCT "{column}" FROM {fqn} LIMIT {int(limit)}'
        )
        if len(rows) >= limit:
            return None
        return [r[0] for r in rows]
