# DBT Model Generator — CLAUDE.md

Contexte projet : application Streamlit qui génère des modèles staging DBT optimisés
(performance de requête prioritaire sur le stockage) pour Snowflake.

---

## Structure du projet

```
dbt-model-generator/
├── app.py                       # Streamlit — 4 pages (Connexion / Exploration / Config / Génération)
├── requirements.txt
└── src/
    ├── __init__.py
    ├── snowflake_connector.py   # Connexion Snowflake + introspection (DESC TABLE, SHOW …)
    ├── sources_generator.py     # DESC TABLE → sources.yml DBT
    ├── yaml_config.py           # Template YAML de config staging (grain, delta, normalisation…)
    ├── normalizer.py            # Pipeline de normalisation des noms de colonnes
    └── model_generator.py       # YAML config → SQL staging + schema.yml
```

---

## Lancer l'application

```bash
pip install -r requirements.txt --break-system-packages
streamlit run app.py
```

---

## Conventions de code

- Python 3.11+, annotations `from __future__ import annotations`
- Type hints sur toutes les fonctions publiques
- Docstrings en français (langue du projet)
- Pas de dépendances externes hors `requirements.txt`
- Snowflake : toujours utiliser la syntaxe `::TYPE` pour les casts (plus performante que `CAST()`)
- YAML : utiliser le `_NullDumper` personnalisé (`sort_keys=False`, `allow_unicode=True`)
- Streamlit : toute modification de state → `st.session_state`, jamais de variables globales

---

## TODO LIST

### 🔌 Connecteur Snowflake (`src/snowflake_connector.py`)

- [ ] **Gestion de la reconnexion automatique** — détecter une connexion expirée
      (token timeout Snowflake ~4h) et se reconnecter transparemment
- [ ] **Support Key-Pair authentication** — ajouter `private_key_path` + `private_key_passphrase`
      comme alternative au mot de passe
- [ ] **Support SSO / Okta** — paramètre `authenticator='externalbrowser'` ou
      `authenticator='https://myorg.okta.com'`
- [ ] **Cache des métadonnées** — mettre en cache `list_databases`, `list_schemas`, `list_tables`
      avec `@st.cache_data(ttl=300)` pour éviter les appels répétés
- [ ] **DESC TABLE pour les vues** — `DESC VIEW` quand l'objet est une vue
      (SHOW TABLES ne retourne pas `kind=VIEW` correctement dans tous les cas)
- [ ] **Gestion des erreurs réseau** — retry exponentiel (3 tentatives) sur
      `OperationalError` et `DatabaseError` temporaires
- [ ] **Multi-profil** — permettre de sauvegarder / charger plusieurs profils de connexion
      nommés dans `st.session_state` (ex : DEV / PREPROD / PROD)

---

### 📄 Génération YAML (`src/sources_generator.py` + `src/yaml_config.py`)

- [ ] **Multi-tables dans un seul sources.yml** — permettre de sélectionner N tables
      et les regrouper sous un même source DBT
- [ ] **Détection automatique des relations** — détecter les colonnes FK candidates
      (colonnes `_ID` qui matchent des PKs d'autres tables) et les noter dans la description
- [ ] **Import d'un sources.yml existant** — parser un sources.yml fourni pour ne pas
      écraser les descriptions/tests déjà écrits manuellement (merge intelligent)
- [ ] **Tests avancés DBT** — générer des tests `accepted_values`, `relationships`,
      `dbt_expectations.expect_column_values_to_not_be_null` à partir des métadonnées
- [ ] **Inférence du domaine** — déduire automatiquement `meta.domain` depuis le nom du schéma
      (ex : `RAW_SALES` → `sales`, `FINANCE_DW` → `finance`)
- [ ] **Validation du YAML édité** — vérifier que le YAML de config staging respecte
      le schéma attendu (jsonschema ou Pydantic) avant de lancer la génération
- [ ] **Pydantic model pour la config staging** — remplacer les `dict[str, Any]` par des
      dataclasses/Pydantic pour la validation et l'autocomplétion

---

### 🧪 Tests (`tests/`)

> Aucun fichier de test n'existe encore. Créer le dossier `tests/` avec pytest.

- [ ] **Créer `tests/test_normalizer.py`**
  - `test_snake_case_camel` — `CustomerID` → `customer_id`
  - `test_snake_case_acronym` — `MyHTTPSRequest` → `my_https_request`
  - `test_strip_prefix` — `T_CMD_NOM` avec prefix `T_CMD_` → `nom`
  - `test_strip_suffix` — `NOM_STG` avec suffix `_STG` → `nom`
  - `test_remove_accents` — `PrénomÀ` → `prenoma`
  - `test_remove_special_chars` — `col-name!2` → `col_name_2`
  - `test_combined_pipeline` — `T_CLI_Prénom-Client` → `prenom_client`
  - `test_build_sql_expression_string` — TRIM + LOWER + COALESCE + ::VARCHAR
  - `test_build_sql_expression_numeric` — pas de TRIM, COALESCE + ::FLOAT
  - `test_idempotence` — normaliser deux fois doit donner le même résultat

- [ ] **Créer `tests/test_sources_generator.py`**
  - `test_basic_structure` — version 2, sources[], tables[]
  - `test_pk_gets_unique_test` — colonne PK → tests: [unique, not_null]
  - `test_not_null_column_gets_not_null_test` — nullable=False → not_null
  - `test_freshness_auto_detect_updated_at` — colonne `updated_at` TIMESTAMP → freshness
  - `test_freshness_auto_detect_maj` — colonne `T_CMD_MAJ` TIMESTAMP → freshness
  - `test_no_freshness_when_no_timestamp` — table sans colonne TIMESTAMP → pas de freshness
  - `test_tags_and_meta_included`
  - `test_yaml_is_valid` — le YAML généré est parseable par `yaml.safe_load`

- [ ] **Créer `tests/test_yaml_config.py`**
  - `test_delta_auto_detect_updated_at`
  - `test_delta_auto_detect_maj`
  - `test_no_delta_when_no_timestamp`
  - `test_pk_set_as_unique_key`
  - `test_composite_pk` — 2 colonnes PK → unique_key est une liste
  - `test_no_pk` — pas de PK → unique_key = "TODO_SET_UNIQUE_KEY"
  - `test_cast_inference_number_0` — `NUMBER(38,0)` → `BIGINT`
  - `test_cast_inference_number_float` — `NUMBER(18,4)` → `FLOAT`
  - `test_cast_inference_varchar` — `VARCHAR(256)` → `VARCHAR`
  - `test_cast_inference_timestamp` — `TIMESTAMP_NTZ` → `TIMESTAMP_NTZ`
  - `test_roundtrip_yaml` — générer → sérialiser → désérialiser → identique

- [ ] **Créer `tests/test_model_generator.py`**
  - `test_sql_contains_source_ref` — `{{ source('raw', 'TABLE') }}` présent
  - `test_sql_contains_config_block` — `{{ config(...) }}` présent
  - `test_incremental_has_strategy` — mat=incremental → `incremental_strategy='merge'`
  - `test_incremental_has_delta_filter` — delta.enabled → `where ts > ...`
  - `test_view_no_delta_filter` — mat=view → pas de `is_incremental()`
  - `test_excluded_column_absent` — include=False → absent du SQL
  - `test_keep_raw_adds_raw_column` — keep_raw=True → `raw_xxx` présent
  - `test_trim_lower_on_varchar` — type VARCHAR → LOWER(TRIM(...))
  - `test_no_trim_on_numeric` — type FLOAT → pas de TRIM
  - `test_coalesce_applied` — coalesce non null → COALESCE(...)
  - `test_schema_yaml_has_unique_test_on_pk`
  - `test_schema_yaml_has_model_name`
  - `test_ephemeral_no_unique_key` — mat=ephemeral → pas de unique_key dans config
  - `test_purge_comment_when_enabled` — purge.enabled=True → commentaire {# PURGE #}

- [ ] **Créer `tests/conftest.py`** — fixtures partagées (`mock_columns`, `mock_config`)
- [ ] **CI GitHub Actions** — `.github/workflows/test.yml` avec `pytest` + `ruff` sur PR

---

### 🖥️ Application Streamlit (`app.py`)

- [ ] **Page Connexion — persistance chiffrée** — proposer de sauvegarder les credentials
      dans `~/.dbt_generator/credentials.enc` (chiffré avec `cryptography.fernet`)
- [ ] **Page Exploration — aperçu des données** — bouton "Voir 10 lignes" qui exécute
      `SELECT * FROM table LIMIT 10` et affiche un `st.dataframe`
- [ ] **Page Exploration — stats de colonnes** — `COUNT(DISTINCT col)`, `COUNT(NULL)`,
      `MIN/MAX` sur les colonnes numériques via une requête APPROX_COUNT_DISTINCT
- [ ] **Page Config — éditeur colonne par colonne** — remplacer l'éditeur YAML brut par
      `st.data_editor` sur un DataFrame des colonnes (include, target_name, cast, coalesce,
      keep_raw, string_case) + synchronisation vers le YAML
- [ ] **Page Config — détection des colonnes PII** — signaler les colonnes dont le nom
      contient `email`, `phone`, `nom`, `prenom`, `siret`, `iban` avec un badge ⚠️
- [ ] **Page Génération — diff avant/après normalisation** — afficher côte à côte les
      colonnes source et cible dans un tableau coloré (vert = normalisé, gris = inchangé)
- [ ] **Page Génération — copie clipboard** — bouton "📋 Copier le SQL" via
      `st.components.v1.html` + JavaScript `navigator.clipboard.writeText`
- [ ] **Page Génération — export ZIP** — télécharger `.sql` + `schema.yml` +
      `sources.yml` en un seul fichier ZIP
- [ ] **Mode sombre / thème** — ajouter `.streamlit/config.toml` avec le thème aux
      couleurs DBT (orange primaire `#FF694B`)
- [ ] **Sidebar — historique des modèles générés** — conserver dans `st.session_state`
      la liste des modèles générés pendant la session avec lien de re-téléchargement

---

## Priorités suggérées

1. Tests unitaires (normalizer + model_generator) — fondation qualité
2. Éditeur colonne-par-colonne (`st.data_editor`) — meilleure UX
3. Cache Snowflake (`@st.cache_data`) — performance
4. Export ZIP — praticité quotidienne
5. Reconnexion automatique — robustesse

---

## Commandes utiles

```bash
# Tests
pytest tests/ -v

# Lint
ruff check src/ app.py

# Lancer l'app
streamlit run app.py

# Vérifier la syntaxe de tous les .py
python -m py_compile src/*.py app.py
```
