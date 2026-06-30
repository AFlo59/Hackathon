"""DBT Model Generator — application Streamlit.

Quatre pages :

1. **Connexion**   — paramètres Snowflake et ouverture de connexion (mise en cache).
2. **Exploration** — navigation databases / schémas / tables et choix d'une table.
3. **Config**      — édition de la config staging (éditeur colonne-par-colonne + YAML).
4. **Génération**  — SQL staging, schema.yml, sources.yml + export ZIP / copie.

Conventions :

* Toute mutation d'état passe par ``st.session_state`` (jamais de variable globale).
* **Aucun appel Snowflake dans le corps d'une page** : ils passent tous par les
  fonctions ``_cached_*`` (``@st.cache_data``) ou ``_get_connector``
  (``@st.cache_resource``), pour éviter de rejouer le réseau à chaque rerun.
"""

from __future__ import annotations

import datetime as dt
import io
import json
import zipfile
from typing import Any

import pandas as pd
import streamlit as st

from src import theme
from src.model_generator import generate_model
from src.snowflake_connector import SnowflakeConnector
from src.sources_generator import generate_sources_yml
from src.yaml_config import (
    LAYERS,
    build_model_name,
    build_staging_config,
    dump_yaml,
    layer_folder,
    load_yaml,
)

st.set_page_config(page_title="DBT Model Generator", page_icon="🧱", layout="wide")
theme.inject_theme()

# --------------------------------------------------------------------------- #
# État de session
# --------------------------------------------------------------------------- #
_DEFAULTS: dict[str, Any] = {
    "connected": False,
    "account": "",          # clé de cache des appels Snowflake
    "columns": None,        # métadonnées de la table sélectionnée
    "selection": {},        # database / schema / table choisis
    "config": None,         # dict de config staging
    "config_yaml": "",      # version texte éditée du config
    "history": [],          # modèles générés pendant la session
}
for _key, _val in _DEFAULTS.items():
    st.session_state.setdefault(_key, _val)


# --------------------------------------------------------------------------- #
# Couche d'accès Snowflake — mise en cache (perf)
# --------------------------------------------------------------------------- #
@st.cache_resource(show_spinner="Connexion à Snowflake…")
def _get_connector(
    account: str,
    user: str,
    password: str,
    role: str,
    warehouse: str,
    database: str,
    authenticator: str = "",
    private_key_path: str = "",
    private_key_passphrase: str = "",
) -> SnowflakeConnector:
    """Ouvre (et met en cache) la connexion. Objet non sérialisable → cache_resource."""
    connector = SnowflakeConnector(
        account=account,
        user=user,
        password=password or None,
        role=role or None,
        warehouse=warehouse or None,
        database=database or None,
        authenticator=authenticator or None,
        private_key_path=private_key_path or None,
        private_key_passphrase=private_key_passphrase or None,
    )
    connector.connect()
    return connector


# `_connector` (underscore) n'est pas hashé ; `account` sert de clé de cache.
@st.cache_data(ttl=300, show_spinner=False)
def _cached_databases(_connector: SnowflakeConnector, account: str) -> list[str]:
    return _connector.list_databases()


@st.cache_data(ttl=300, show_spinner=False)
def _cached_schemas(_connector: SnowflakeConnector, account: str, database: str) -> list[str]:
    return _connector.list_schemas(database)


@st.cache_data(ttl=300, show_spinner=False)
def _cached_tables(
    _connector: SnowflakeConnector, account: str, database: str, schema: str
) -> list[str]:
    return _connector.list_tables(database, schema)


@st.cache_data(ttl=300, show_spinner=False)
def _cached_columns(
    _connector: SnowflakeConnector, account: str, database: str, schema: str, table: str
) -> list[dict[str, Any]]:
    return _connector.describe_table(database, schema, table)


@st.cache_data(ttl=300, show_spinner=False)
def _cached_distinct(
    _connector: SnowflakeConnector, account: str, database: str, schema: str,
    table: str, column: str,
) -> list[Any] | None:
    return _connector.get_distinct_values(database, schema, table, column)


@st.cache_data(ttl=300, show_spinner=False)
def _cached_table_comment(
    _connector: SnowflakeConnector, account: str, database: str, schema: str, table: str
) -> str | None:
    try:
        return _connector.get_table_comment(database, schema, table)
    except Exception:  # noqa: BLE001 - le commentaire est optionnel
        return None


def _current_connector() -> SnowflakeConnector | None:
    """Récupère la connexion mise en cache à partir des identifiants de session."""
    creds = st.session_state.get("_creds")
    if not creds:
        return None
    return _get_connector(**creds)


# --------------------------------------------------------------------------- #
# Helpers UI
# --------------------------------------------------------------------------- #
def _config_columns_df(config: dict[str, Any]) -> pd.DataFrame:
    return pd.DataFrame(config["columns"])


def _df_to_config_columns(df: pd.DataFrame) -> list[dict[str, Any]]:
    return df.to_dict(orient="records")


def _build_zip(
    *,
    source_name: str,
    model_name: str,
    layer: str,
    sql: str,
    schema_yml: str,
    sources_yml: str,
    config_yaml: str,
) -> bytes:
    """Construit un ZIP respectant l'arborescence dbt réelle (dossier par maillon)."""
    buffer = io.BytesIO()
    folder = layer_folder(layer)
    # Le staging range par source ; les autres maillons à plat dans leur dossier.
    base = f"{folder}/{source_name}" if layer == "staging" else folder
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr(f"{base}/{model_name}.sql", sql)
        zf.writestr(f"{base}/{model_name}_schema.yml", schema_yml)
        zf.writestr(f"sources/sources_{source_name}.yml", sources_yml)
        zf.writestr("staging_config.yml", config_yaml)
    return buffer.getvalue()


def _copy_button(label: str, text: str, key: str) -> None:
    """Bouton copie clipboard robuste : API moderne + fallback ``execCommand``.

    Le fallback ``textarea`` + ``execCommand('copy')`` assure la compatibilité
    hors HTTPS (``navigator.clipboard`` n'est dispo qu'en contexte sécurisé).
    """
    payload = json.dumps(text)
    html = f"""
        <textarea id="src_{key}" style="position:absolute;left:-9999px;">{text}</textarea>
        <button id="{key}" style="padding:6px 14px;border-radius:6px;border:1px solid {theme.PRINCIPALE};
            background:{theme.PRINCIPALE};color:white;cursor:pointer;font-size:0.9rem;font-weight:600;">{label}</button>
        <script>
            const btn = document.getElementById("{key}");
            btn.addEventListener("click", () => {{
                const txt = {payload};
                const done = () => {{ btn.innerText = "✅ Copié"; setTimeout(() => btn.innerText = "{label}", 1500); }};
                if (navigator.clipboard && window.isSecureContext) {{
                    navigator.clipboard.writeText(txt).then(done);
                }} else {{
                    const ta = document.getElementById("src_{key}");
                    ta.select(); document.execCommand("copy"); done();
                }}
            }});
        </script>
    """
    st.components.v1.html(html, height=46)


# --------------------------------------------------------------------------- #
# Pages
# --------------------------------------------------------------------------- #
#: Libellés des méthodes d'authentification.
_AUTH_METHODS = ["Mot de passe", "Key-Pair", "SSO (navigateur)", "Okta"]


def page_connexion() -> None:
    st.header("🔌 Connexion Snowflake")

    # --- Multi-profil (DEV / PREPROD / PROD) — en mémoire de session ---
    profiles: dict[str, dict[str, str]] = st.session_state.setdefault("profiles", {})
    if profiles:
        p1, p2, p3 = st.columns([3, 1, 1])
        chosen = p1.selectbox("Profil enregistré", ["—", *profiles])
        if chosen != "—" and p2.button("Charger"):
            st.session_state["_form_creds"] = profiles[chosen]
            st.rerun()
        if chosen != "—" and p3.button("Supprimer"):
            profiles.pop(chosen, None)
            st.rerun()

    defaults = st.session_state.get("_form_creds", {})
    auth_default = defaults.get("_auth", "Mot de passe")
    auth = st.selectbox(
        "Méthode d'authentification", _AUTH_METHODS,
        index=_AUTH_METHODS.index(auth_default) if auth_default in _AUTH_METHODS else 0,
    )

    with st.form("connexion"):
        c1, c2 = st.columns(2)
        account = c1.text_input(
            "Account", value=defaults.get("account", ""),
            placeholder="orgname-account_name",
            help="Format organisation-compte avec un TIRET : `UPUDFIG-OY62352` "
                 "(pas de point). Ou format legacy `locator.region.cloud`.",
        )
        user = c2.text_input("User", value=defaults.get("user", ""))

        password = private_key_path = private_key_passphrase = ""
        authenticator = ""
        if auth == "Mot de passe":
            password = c1.text_input("Password", type="password",
                                     value=defaults.get("password", ""))
        elif auth == "Key-Pair":
            private_key_path = c1.text_input(
                "Chemin de la clé privée (.p8)", value=defaults.get("private_key_path", "")
            )
            private_key_passphrase = c2.text_input(
                "Passphrase de la clé", type="password",
                value=defaults.get("private_key_passphrase", ""),
            )
        elif auth == "SSO (navigateur)":
            authenticator = "externalbrowser"
            c1.caption("Une fenêtre de navigateur s'ouvrira pour l'authentification.")
        else:  # Okta
            authenticator = c1.text_input(
                "URL Okta", value=defaults.get("authenticator", "https://"),
            )

        role = c1.text_input("Role", value=defaults.get("role", ""), placeholder="(optionnel)")
        warehouse = c2.text_input("Warehouse", value=defaults.get("warehouse", ""),
                                  placeholder="(optionnel)")
        database = c1.text_input("Database par défaut", value=defaults.get("database", ""),
                                 placeholder="(optionnel)")
        profile_name = c2.text_input("Nom du profil à sauvegarder", placeholder="ex : PROD")
        submitted = st.form_submit_button("Se connecter")

    if submitted:
        creds = {
            "account": account.strip(),
            "user": user,
            "password": password,
            "role": role,
            "warehouse": warehouse,
            "database": database,
            "authenticator": authenticator,
            "private_key_path": private_key_path,
            "private_key_passphrase": private_key_passphrase,
        }
        try:
            _get_connector(**creds)  # ouvre + met en cache (cache_resource)
            st.session_state["_creds"] = creds
            st.session_state["_form_creds"] = {**creds, "_auth": auth}
            st.session_state.account = creds["account"]
            st.session_state.connected = True
            if profile_name:
                # Profil complet (secrets inclus) — uniquement en mémoire de session.
                profiles[profile_name] = {**creds, "_auth": auth}
                st.toast(f"Profil « {profile_name} » enregistré")
            st.success("Connexion établie ✅")
        except Exception as exc:  # noqa: BLE001 - on affiche l'erreur à l'utilisateur
            st.session_state.connected = False
            msg = str(exc)
            if "404" in msg or "Not Found" in msg:
                msg += (
                    "\n\n💡 Vérifiez l'**identifiant de compte** : utilisez le format "
                    "`orgname-account_name` avec un **tiret** (ex : `UPUDFIG-OY62352`), "
                    "pas un point."
                )
            st.error(f"Échec de connexion : {msg}")


def page_exploration() -> None:
    st.header("🗂️ Exploration")
    if not st.session_state.connected:
        st.warning("Connectez-vous d'abord (page Connexion).")
        return

    connector = _current_connector()
    account = st.session_state.account
    try:
        databases = _cached_databases(connector, account)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Impossible de lister les databases : {exc}")
        return

    # Sélecteurs en cascade : les listes sont mises en cache (ttl 300s),
    # donc les reruns ne rejouent pas le réseau.
    c1, c2, c3 = st.columns(3)
    database = c1.selectbox("Database", databases)
    schemas = _cached_schemas(connector, account, database) if database else []
    schema = c2.selectbox("Schéma", schemas)
    tables = _cached_tables(connector, account, database, schema) if schema else []
    table = c3.selectbox("Table", tables)

    # Lazy loading : l'introspection des colonnes ne se fait qu'au clic.
    if table and st.button("🔍 Introspecter la table"):
        with st.spinner(f"Introspection de {table}…"):
            columns = _cached_columns(connector, account, database, schema, table)
        st.session_state.columns = columns
        st.session_state.selection = {"database": database, "schema": schema, "table": table}
        st.session_state.config = None  # force la reconstruction
        st.success(f"{len(columns)} colonnes introspectées.")

    if st.session_state.columns and st.session_state.selection.get("table") == table:
        st.subheader("Colonnes")
        df = pd.DataFrame(st.session_state.columns)
        # Pagination simple : hauteur fixe au-delà de 50 colonnes.
        if len(df) > 50:
            st.dataframe(df, use_container_width=True, height=600)
        else:
            st.dataframe(df, use_container_width=True)


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
    m1, m2, m3 = st.columns(3)

    # Maillon dbt — change le préfixe/dossier et régénère le nom du modèle.
    _LAYER_KEYS = list(LAYERS)
    prev_layer = config["model"].get("layer", "staging")
    layer = m1.selectbox(
        "Maillon dbt", _LAYER_KEYS, index=_LAYER_KEYS.index(prev_layer),
        format_func=lambda k: {"staging": "staging", "intermediate": "intermediate",
                               "marts_fct": "marts / fact", "marts_dim": "marts / dim"}[k],
    )
    config["model"]["layer"] = layer
    if layer != prev_layer:  # régénère le nom au changement de maillon
        config["model"]["name"] = build_model_name(
            source_name, sel["table"], prefix=prefix, suffix=suffix, layer=layer
        )

    config["model"]["name"] = m2.text_input("Nom du modèle", value=config["model"]["name"])
    _MATS = ["view", "table", "incremental", "ephemeral"]
    config["model"]["materialized"] = m3.selectbox(
        "Matérialisation", _MATS, index=_MATS.index(config["model"]["materialized"])
    )

    # Alerte PII : colonnes dont le nom évoque une donnée personnelle.
    pii_cols = [c["target"] for c in config["columns"] if c.get("pii")]
    if pii_cols:
        st.warning(
            "⚠️ Colonnes potentiellement **PII** (donnée personnelle) : "
            + ", ".join(f"`{c}`" for c in pii_cols)
            + " — taguées `meta.pii: true` dans le schema.yml."
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
            "comment": st.column_config.TextColumn("Description (Snowflake)"),
            "pii": st.column_config.CheckboxColumn("PII ⚠️", disabled=True),
        },
        key="columns_editor",
    )
    config["columns"] = _df_to_config_columns(edited)

    included_targets = [c["target"] for c in config["columns"] if c.get("include", True)]
    included_sources = [c["source"] for c in config["columns"] if c.get("include", True)]

    # --- Optimisation Snowflake & options dbt ---
    with st.expander("⚡ Optimisation & options dbt"):
        mat = config["model"]["materialized"]
        cb = config.setdefault("cluster_by", {"enabled": False, "columns": []})
        if mat in ("table", "incremental"):
            cb["enabled"] = st.checkbox("Activer le CLUSTER BY", value=cb.get("enabled", False))
            cb["columns"] = (
                st.multiselect("Colonnes de clustering", included_targets,
                               default=[c for c in cb.get("columns", []) if c in included_targets])
                if cb["enabled"] else []
            )
        else:
            st.caption("CLUSTER BY disponible uniquement pour `table` / `incremental`.")
            cb["enabled"] = False

        config.setdefault("audit", {"enabled": False})["enabled"] = st.checkbox(
            "Colonnes d'audit (`_loaded_at`, `_dbt_invocation_id`)",
            value=config["audit"].get("enabled", False),
        )
        config["normalization"]["keep_all_raw"] = st.checkbox(
            "Conserver toutes les colonnes brutes (`raw_*`)",
            value=config["normalization"].get("keep_all_raw", False),
        )

        pd_on = st.checkbox(
            "persist_docs (propager descriptions dans Snowflake)",
            value=config.get("persist_docs", {}).get("relation", False),
        )
        config["persist_docs"] = {"relation": pd_on, "columns": pd_on}

        grants_txt = st.text_input(
            "Grants SELECT (rôles séparés par des virgules)",
            value=", ".join(config.get("grants", {}).get("select", [])),
        )
        roles = [r.strip() for r in grants_txt.split(",") if r.strip()]
        config["grants"] = {"select": roles} if roles else {}

    # --- Filtres WHERE par colonne ---
    with st.expander("🔎 Filtres WHERE"):
        wc = config.setdefault("where_clause", {"mode": "and", "filters": []})
        wc["mode"] = st.radio("Combinaison des filtres", ["and", "or"], horizontal=True,
                              index=0 if wc.get("mode", "and") == "and" else 1)
        chosen = st.multiselect("Colonnes à filtrer", included_sources)
        connector = _current_connector()
        filters: list[dict[str, Any]] = []
        for src in chosen:
            st.markdown(f"**{src}**")
            op = st.selectbox("Opérateur", ["in", "not_in", "between", "custom"], key=f"op_{src}")
            flt: dict[str, Any] = {"column": src, "operator": op}
            if op in ("in", "not_in"):
                distinct = None
                if connector is not None and sel.get("database"):
                    distinct = _cached_distinct(connector, st.session_state.account,
                                                sel["database"], sel["schema"], sel["table"], src)
                if distinct is not None:
                    flt["values"] = st.multiselect("Valeurs", distinct, key=f"val_{src}")
                else:
                    st.caption("> 35 valeurs distinctes (ou hors connexion) : saisie libre.")
                    raw = st.text_input("Valeurs (séparées par des virgules)", key=f"val_{src}")
                    flt["values"] = [v.strip() for v in raw.split(",") if v.strip()]
            elif op == "between":
                b1, b2 = st.columns(2)
                flt["values"] = [b1.text_input("Min", key=f"min_{src}"),
                                 b2.text_input("Max", key=f"max_{src}")]
            else:  # custom
                flt["custom_expr"] = st.text_input("Expression SQL libre", key=f"expr_{src}",
                                                   placeholder=f"{src} > 0")
            filters.append(flt)
        wc["filters"] = filters

    st.session_state.config_yaml = dump_yaml(config)

    # Synchronisation bidirectionnelle : import d'un YAML de config.
    with st.expander("YAML de config (voir / importer)"):
        st.code(st.session_state.config_yaml, language="yaml")
        uploaded = st.file_uploader("Importer un staging_config.yml", type=["yml", "yaml"])
        if uploaded is not None and st.button("Appliquer le YAML importé"):
            try:
                st.session_state.config = load_yaml(uploaded.getvalue().decode("utf-8"))
                st.session_state.config_yaml = dump_yaml(st.session_state.config)
                st.success("Config importée ✅ — réaffichage…")
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(f"YAML invalide : {exc}")


def page_generation() -> None:
    st.header("🚀 Génération")
    if not st.session_state.config:
        st.warning("Configurez le modèle d'abord (page Config).")
        return

    config = st.session_state.config
    sel = st.session_state.selection
    artefacts = generate_model(config)

    table_comment = None
    connector = _current_connector()
    if connector is not None and sel.get("database"):
        table_comment = _cached_table_comment(
            connector, st.session_state.account,
            sel["database"], sel["schema"], sel["table"],
        )

    sources_yml = generate_sources_yml(
        source_name=config["source"]["name"],
        database=sel.get("database", ""),
        schema=sel.get("schema", ""),
        table=config["source"]["table"],
        columns=st.session_state.columns,
        table_comment=table_comment,
    )

    tab_sql, tab_schema, tab_sources = st.tabs(["model.sql", "schema.yml", "sources.yml"])
    with tab_sql:
        st.code(artefacts["sql"], language="sql")
        _copy_button("📋 Copier le SQL", artefacts["sql"], key="copy_sql")
    with tab_schema:
        st.code(artefacts["schema_yml"], language="yaml")
    with tab_sources:
        st.code(sources_yml, language="yaml")

    zip_bytes = _build_zip(
        source_name=config["source"]["name"],
        model_name=artefacts["model_name"],
        layer=config["model"].get("layer", "staging"),
        sql=artefacts["sql"],
        schema_yml=artefacts["schema_yml"],
        sources_yml=sources_yml,
        config_yaml=st.session_state.config_yaml or dump_yaml(config),
    )

    a1, a2 = st.columns(2)
    a1.download_button(
        "⬇️ Tout télécharger (.zip)",
        data=zip_bytes,
        file_name=f"{artefacts['model_name']}.zip",
        mime="application/zip",
    )
    if a2.button("➕ Ajouter à l'historique"):
        st.session_state.history.insert(
            0,
            {
                "name": artefacts["model_name"],
                "time": dt.datetime.now().strftime("%H:%M:%S"),
                "zip": zip_bytes,
            },
        )
        st.toast(f"« {artefacts['model_name']} » ajouté à l'historique")


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
st.sidebar.caption("🟢 Connecté" if st.session_state.connected else "🔴 Déconnecté")
choice = st.sidebar.radio("Navigation", list(PAGES.keys()))

# Historique de session (re-téléchargement)
if st.session_state.history:
    st.sidebar.divider()
    st.sidebar.subheader("🕘 Historique")
    for i, item in enumerate(st.session_state.history):
        st.sidebar.download_button(
            f"⬇️ {item['name']} · {item['time']}",
            data=item["zip"],
            file_name=f"{item['name']}.zip",
            mime="application/zip",
            key=f"hist_{i}",
        )

PAGES[choice]()
