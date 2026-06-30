"""DBT Model Generator — application Streamlit.

Quatre pages :

1. **Connexion**   — paramètres Snowflake et ouverture de connexion.
2. **Exploration** — navigation databases / schémas / tables et choix d'une table.
3. **Config**      — édition de la config staging (éditeur colonne-par-colonne + YAML).
4. **Génération**  — SQL staging, schema.yml, sources.yml + export ZIP / copie.

Toute mutation d'état passe par ``st.session_state`` (jamais de variable globale).
"""

from __future__ import annotations

import io
import json
import zipfile
from typing import Any

import pandas as pd
import streamlit as st

from src.model_generator import generate_model
from src.snowflake_connector import SnowflakeConnector
from src.sources_generator import generate_sources_yml
from src.yaml_config import build_staging_config, dump_yaml, load_yaml

st.set_page_config(page_title="DBT Model Generator", page_icon="🧱", layout="wide")

# --------------------------------------------------------------------------- #
# État de session
# --------------------------------------------------------------------------- #
_DEFAULTS: dict[str, Any] = {
    "connector": None,
    "connected": False,
    "columns": None,        # métadonnées de la table sélectionnée
    "selection": {},        # database / schema / table choisis
    "config": None,         # dict de config staging
    "config_yaml": "",      # version texte éditée du config
}
for _key, _val in _DEFAULTS.items():
    st.session_state.setdefault(_key, _val)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _columns_to_df(columns: list[dict[str, Any]]) -> pd.DataFrame:
    return pd.DataFrame(columns)


def _config_columns_df(config: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(config["columns"])


def _df_to_config_columns(df: pd.DataFrame) -> list[dict[str, Any]]:
    return df.to_dict(orient="records")


def _build_zip(model_name: str, sql: str, schema_yml: str, sources_yml: str) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"models/staging/{model_name}.sql", sql)
        zf.writestr("models/staging/schema.yml", schema_yml)
        zf.writestr("models/staging/sources.yml", sources_yml)
    return buffer.getvalue()


def _copy_button(label: str, text: str, key: str) -> None:
    """Bouton de copie clipboard via composant HTML + JavaScript."""
    payload = json.dumps(text)
    html = f"""
        <button id="{key}" style="padding:6px 12px;border-radius:6px;border:1px solid #FF694B;
            background:#FF694B;color:white;cursor:pointer;font-size:0.9rem;">{label}</button>
        <script>
            const btn = document.getElementById("{key}");
            btn.addEventListener("click", () => {{
                navigator.clipboard.writeText({payload});
                btn.innerText = "✅ Copié";
                setTimeout(() => btn.innerText = "{label}", 1500);
            }});
        </script>
    """
    st.components.v1.html(html, height=44)


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #
def page_connexion() -> None:
    st.header("🔌 Connexion Snowflake")
    with st.form("connexion"):
        c1, c2 = st.columns(2)
        account = c1.text_input("Account", placeholder="xy12345.eu-west-1")
        user = c2.text_input("User")
        password = c1.text_input("Password", type="password")
        role = c2.text_input("Role", placeholder="(optionnel)")
        warehouse = c1.text_input("Warehouse", placeholder="(optionnel)")
        database = c2.text_input("Database par défaut", placeholder="(optionnel)")
        submitted = st.form_submit_button("Se connecter")

    if submitted:
        try:
            connector = SnowflakeConnector(
                account=account,
                user=user,
                password=password or None,
                role=role or None,
                warehouse=warehouse or None,
                database=database or None,
            )
            connector.connect()
            st.session_state.connector = connector
            st.session_state.connected = True
            st.success("Connexion établie ✅")
        except Exception as exc:  # noqa: BLE001 - on affiche l'erreur à l'utilisateur
            st.session_state.connected = False
            st.error(f"Échec de connexion : {exc}")


def page_exploration() -> None:
    st.header("🗂️ Exploration")
    if not st.session_state.connected:
        st.warning("Connectez-vous d'abord (page Connexion).")
        return

    connector: SnowflakeConnector = st.session_state.connector
    try:
        databases = connector.list_databases()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Impossible de lister les databases : {exc}")
        return

    c1, c2, c3 = st.columns(3)
    database = c1.selectbox("Database", databases)
    schemas = connector.list_schemas(database) if database else []
    schema = c2.selectbox("Schéma", schemas)
    tables = connector.list_tables(database, schema) if schema else []
    table = c3.selectbox("Table", tables)

    if table and st.button("Introspecter la table"):
        columns = connector.describe_table(database, schema, table)
        st.session_state.columns = columns
        st.session_state.selection = {
            "database": database,
            "schema": schema,
            "table": table,
        }
        st.session_state.config = None  # force la reconstruction
        st.success(f"{len(columns)} colonnes introspectées.")

    if st.session_state.columns and st.session_state.selection.get("table") == table:
        st.subheader("Colonnes")
        st.dataframe(_columns_to_df(st.session_state.columns), use_container_width=True)


def page_config() -> None:
    st.header("⚙️ Configuration du modèle staging")
    if not st.session_state.columns:
        st.warning("Sélectionnez et introspectez une table (page Exploration).")
        return

    sel = st.session_state.selection
    c1, c2, c3 = st.columns(3)
    source_name = c1.text_input("Nom du source DBT", value="raw")
    prefix = c2.text_input("Préfixe à retirer", value="")
    suffix = c3.text_input("Suffixe à retirer", value="")

    if st.button("Générer / réinitialiser la config") or st.session_state.config is None:
        st.session_state.config = build_staging_config(
            source_name=source_name,
            table=sel["table"],
            columns=st.session_state.columns,
            prefix=prefix,
            suffix=suffix,
        )
        st.session_state.config_yaml = dump_yaml(st.session_state.config)

    config = st.session_state.config

    st.subheader("Modèle")
    m1, m2 = st.columns(2)
    config["model"]["name"] = m1.text_input("Nom du modèle", value=config["model"]["name"])
    config["model"]["materialized"] = m2.selectbox(
        "Matérialisation",
        ["view", "table", "incremental", "ephemeral"],
        index=["view", "table", "incremental", "ephemeral"].index(
            config["model"]["materialized"]
        ),
    )

    st.subheader("Colonnes (édition colonne-par-colonne)")
    edited = st.data_editor(
        _config_columns_df(config),
        use_container_width=True,
        num_rows="fixed",
        column_config={
            "include": st.column_config.CheckboxColumn("Inclure"),
            "keep_raw": st.column_config.CheckboxColumn("Garder raw"),
            "trim": st.column_config.CheckboxColumn("TRIM"),
            "string_case": st.column_config.SelectboxColumn(
                "Casse", options=["lower", "upper", "none"]
            ),
        },
        key="columns_editor",
    )
    config["columns"] = _df_to_config_columns(edited)
    st.session_state.config_yaml = dump_yaml(config)

    with st.expander("YAML brut (synchronisé)"):
        st.code(st.session_state.config_yaml, language="yaml")


def page_generation() -> None:
    st.header("🚀 Génération")
    if not st.session_state.config:
        st.warning("Configurez le modèle d'abord (page Config).")
        return

    config = st.session_state.config
    sel = st.session_state.selection
    artefacts = generate_model(config)
    sources_yml = generate_sources_yml(
        source_name=config["source"]["name"],
        database=sel.get("database", ""),
        schema=sel.get("schema", ""),
        table=config["source"]["table"],
        columns=st.session_state.columns,
    )

    tab_sql, tab_schema, tab_sources = st.tabs(["model.sql", "schema.yml", "sources.yml"])
    with tab_sql:
        st.code(artefacts["sql"], language="sql")
        _copy_button("📋 Copier le SQL", artefacts["sql"], key="copy_sql")
    with tab_schema:
        st.code(artefacts["schema_yml"], language="yaml")
    with tab_sources:
        st.code(sources_yml, language="yaml")

    st.download_button(
        "📦 Télécharger le ZIP",
        data=_build_zip(
            artefacts["model_name"],
            artefacts["sql"],
            artefacts["schema_yml"],
            sources_yml,
        ),
        file_name=f"{artefacts['model_name']}.zip",
        mime="application/zip",
    )


# --------------------------------------------------------------------------- #
# Navigation
# --------------------------------------------------------------------------- #
PAGES = {
    "🔌 Connexion": page_connexion,
    "🗂️ Exploration": page_exploration,
    "⚙️ Config": page_config,
    "🚀 Génération": page_generation,
}

st.sidebar.title("🧱 DBT Model Generator")
status = "🟢 Connecté" if st.session_state.connected else "🔴 Déconnecté"
st.sidebar.caption(status)
choice = st.sidebar.radio("Navigation", list(PAGES.keys()))
PAGES[choice]()
