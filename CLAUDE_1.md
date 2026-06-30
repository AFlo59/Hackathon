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
    ├── snowflake_connector.py   # Connexion Snowflake + introspection (DESC TABLE, SHOW…)
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
- Performance Streamlit : tout appel Snowflake doit passer par `@st.cache_data` ou
  `@st.cache_resource` — aucun appel réseau dans le corps principal d'une page

---

## TODO LIST

### ⚡ Performance & navigation (`app.py`)

> Problème : l'app est lente à la navigation et à l'actualisation.
> Cause principale : les appels Snowflake sont rejoués à chaque rerun Streamlit.

- [ ] **Cache des listes Snowflake** — décorer `list_databases`, `list_schemas`, `list_tables`
      avec `@st.cache_data(ttl=300, show_spinner=False)` dans `snowflake_connector.py`.
      La connexion elle-même doit être dans `@st.cache_resource` (objet non sérialisable)
- [ ] **Éviter les reruns en cascade** — remplacer les `st.selectbox` qui déclenchent
      un rerun complet par un formulaire `st.form` sur la page Exploration
      (un seul rerun au submit, pas un par selectbox)
- [ ] **Lazy loading des colonnes** — ne charger `desc_table` qu'au clic du bouton
      "Inspecter", jamais automatiquement au changement de sélection
- [ ] **Fragment Streamlit** — utiliser `@st.experimental_fragment` (Streamlit ≥ 1.33)
      sur les sections indépendantes (ex : aperçu YAML, tableau de colonnes) pour
      éviter de redessiner toute la page à chaque interaction
- [ ] **Spinner localisé** — chaque appel réseau doit avoir son propre `st.spinner`
      ciblé, pas un spinner global qui bloque toute l'UI
- [ ] **Pagination du tableau de colonnes** — au-delà de 50 colonnes, paginer avec
      `st.dataframe` + paramètre `height` fixe plutôt que de tout afficher d'un coup

---

### 🔌 Connecteur Snowflake (`src/snowflake_connector.py`)

- [ ] **Reconnexion automatique** — détecter une connexion expirée (token ~4h) et
      se reconnecter transparemment sans recharger la page
- [ ] **Support Key-Pair authentication** — paramètres `private_key_path` +
      `private_key_passphrase` comme alternative au mot de passe
- [ ] **Support SSO / Okta** — `authenticator='externalbrowser'` ou URL Okta
- [ ] **Gestion des erreurs réseau** — retry exponentiel (3 tentatives, délai 1s/2s/4s)
      sur `OperationalError` et `DatabaseError` temporaires
- [ ] **Multi-profil** — sauvegarder / charger plusieurs profils nommés
      (DEV / PREPROD / PROD) dans `st.session_state`
- [ ] **DESC TABLE vs DESC VIEW** — utiliser `DESC VIEW` quand l'objet est une vue
      (`SHOW TABLES` ne remonte pas correctement `kind=VIEW` dans tous les comptes)
- [ ] **Récupération des commentaires de colonnes** — s'assurer que la colonne `COMMENT`
      (index 9 du résultat DESC TABLE) est bien extraite et propagée jusqu'à l'UI et au
      YAML généré. Certaines versions du connecteur retournent `None` même si le commentaire
      existe — ajouter un fallback via `INFORMATION_SCHEMA.COLUMNS.COMMENT`

---

### ⚙️ Page Config — Paramétrages manquants (`app.py` + `src/yaml_config.py` + `src/model_generator.py`)

#### Cluster Keys

- [ ] **Ajout d'un CLUSTER BY dans la config staging** — ajouter le champ suivant dans
      le YAML de config et dans le bloc `{{ config(...) }}` généré :
      ```yaml
      cluster_by:
        enabled: true
        columns: [date_commande, statut]   # une ou plusieurs colonnes
      ```
      Générer dans le SQL :
      ```sql
      {{ config(
          materialized='table',
          cluster_by=['date_commande', 'statut']
      ) }}
      ```
      Valable pour `table` et `incremental` uniquement (pas `view` ni `ephemeral`).
      Afficher dans l'UI un `st.multiselect` sur les colonnes incluses dans le modèle.

#### Filtre WHERE par colonne (clause de filtrage)

> Règle : si le nombre de valeurs distinctes d'une colonne ≤ 35, proposer un
> multiselect des valeurs. Si > 35, proposer un champ texte libre pour saisir
> les valeurs à inclure/exclure.

- [ ] **Fonction `get_distinct_values(conn, db, schema, table, column, limit=36)`** dans
      `snowflake_connector.py` — exécute `SELECT DISTINCT col FROM table LIMIT 36`.
      Retourne la liste si ≤ 35 valeurs, sinon retourne `None` (trop de valeurs)
- [ ] **Champ `filters` dans la config YAML** par colonne :
      ```yaml
      columns:
        - source_name: STATUT
          filters:
            operator: in             # in | not_in | between | custom
            values: [ACTIF, VALIDE]  # liste si ≤ 35 valeurs distinctes
            custom_expr:             # expression SQL libre si > 35 valeurs
                                     # ex : "STATUT NOT IN ('ANNULE','TEST')"
      ```
- [ ] **Clause WHERE globale composée** dans la config staging :
      ```yaml
      staging:
        where_clause:
          mode: and      # and | or
          filters:       # liste ordonnée des filtres de colonnes actifs
            - column: STATUT
              operator: in
              values: [ACTIF, VALIDE]
            - column: PAYS
              operator: not_in
              values: [TEST]
            - column: MONTANT
              operator: custom
              custom_expr: "MONTANT > 0"
      ```
      La WHERE est injectée dans le CTE `source` du SQL généré (après le filtre delta
      le cas échéant), en respectant l'ordre et l'opérateur `AND`/`OR`
- [ ] **UI dans la page Config** — pour chaque colonne incluse, un expander
      "Ajouter un filtre" qui :
      1. Charge les valeurs distinctes au clic (pas au chargement de la page)
      2. Si ≤ 35 valeurs : `st.multiselect` avec les valeurs disponibles
      3. Si > 35 valeurs : avertissement + champ texte pour expression SQL libre
      4. Opérateur : `IN` / `NOT IN` / `BETWEEN` / `Expression libre`
      5. Prévisualisation de la clause WHERE résultante en temps réel

#### Versionnage brut / normalisé

- [ ] **Champ `keep_raw` déjà présent mais incomplet** — actuellement `keep_raw=True`
      ajoute `raw_<nom>` sans commentaire ni test. Améliorer :
      - Ajouter `raw_<nom>` avec `description: "Valeur brute non normalisée de <source_name>"`
      - Ajouter dans le schema.yml le tag `raw: true` dans meta
      - Dans le SQL, grouper les colonnes brutes en section `-- Colonnes brutes (raw)`
      distincte, après les colonnes normalisées
- [ ] **Option globale `keep_all_raw`** dans la config :
      ```yaml
      normalization:
        keep_all_raw: false   # si true, ajoute raw_xxx pour TOUTES les colonnes
      ```
- [ ] **Colonne `_dbt_source_raw`** optionnelle — ajoute un `SELECT *` caché dans une
      colonne VARIANT (Snowflake) pour traçabilité complète de la ligne source :
      ```yaml
      staging:
        add_source_snapshot: false   # ajoute OBJECT_CONSTRUCT(*) as _source_raw
      ```

#### Descriptions depuis les commentaires Snowflake

- [ ] **Propagation automatique des commentaires** — lors de `desc_table`, le champ
      `comment` de chaque colonne doit remplir automatiquement :
      - `columns[].comment` dans la config staging
      - `columns[].description` dans le `sources.yml`
      - `columns[].description` dans le `schema.yml` du modèle
      Ne jamais écraser un commentaire existant si l'utilisateur l'a modifié manuellement
- [ ] **Affichage dans l'éditeur de colonnes** — montrer la colonne "Description (Snowflake)"
      dans le tableau de prévisualisation de la page Config avec possibilité d'édition inline
- [ ] **Commentaire de table** — récupérer le commentaire de la table via
      `INFORMATION_SCHEMA.TABLES.COMMENT` et le placer dans `table.description`
      du `sources.yml`

#### Autres customisations manquantes

- [ ] **`post_hook` et `pre_hook`** dans la config :
      ```yaml
      staging:
        pre_hook: []
        post_hook:
          - "GRANT SELECT ON {{ this }} TO ROLE REPORTER"
      ```
- [ ] **`grants`** DBT natif (≥ 1.2) :
      ```yaml
      staging:
        grants:
          select: [ROLE_REPORTER, ROLE_ANALYST]
      ```
- [ ] **`persist_docs`** — propager les descriptions dans les métadonnées Snowflake :
      ```yaml
      staging:
        persist_docs:
          relation: true
          columns: true
      ```
- [ ] **`full_refresh` protégé** — option `on_schema_change` configurable :
      `fail` | `ignore` | `append_new_columns` | `sync_all_columns`
- [ ] **Colonnes d'audit automatiques** — option pour ajouter en fin de modèle :
      ```sql
      CURRENT_TIMESTAMP()    as _loaded_at,
      '{{ invocation_id }}' as _dbt_invocation_id
      ```
- [ ] **Détection des colonnes PII** — signaler les colonnes dont le nom contient
      `email`, `phone`, `nom`, `prenom`, `siret`, `iban`, `carte`, `mdp`, `password`
      avec un badge ⚠️ dans l'UI et un tag `pii: true` dans le schema.yml

---

### 🚀 Page Génération — Organisation par maillon DBT

> Actuellement le SQL est généré en un seul fichier plat.
> Il faut organiser la sortie par **maillon de la chaîne DBT** :
> `sources → staging → intermediate → marts`

- [ ] **Sélecteur de maillon cible** dans la config :
      ```yaml
      staging:
        dbt_layer: staging   # staging | intermediate | marts
      ```
      Le maillon détermine le préfixe du modèle (`stg_`, `int_`, `fct_`, `dim_`) et
      le dossier cible recommandé

- [ ] **Préfixes par maillon** :

      | Maillon       | Préfixe     | Dossier DBT              |
      |---------------|-------------|--------------------------|
      | staging       | `stg_`      | `models/staging/<source>/` |
      | intermediate  | `int_`      | `models/intermediate/`   |
      | marts / fact  | `fct_`      | `models/marts/`          |
      | marts / dim   | `dim_`      | `models/marts/`          |

- [ ] **Regroupement sémantique des colonnes dans le SQL généré** — le SQL doit être
      découpé en sections clairement étiquetées selon la convention du maillon :

      Pour **staging** :
      ```sql
      -- =============================================================
      -- STAGING : stg_commandes
      -- Source  : ANALYTICS.RAW.COMMANDES
      -- Maillon : staging (brut nettoyé, 1 source = 1 modèle)
      -- =============================================================
      renamed as (
          select
              -- [PK / Grain]
              ...
              -- [Dimensions]
              ...
              -- [Mesures]
              ...
              -- [Timestamps]
              ...
              -- [Colonnes brutes (raw)]
              ...
              -- [Colonnes d'audit]
              ...
          from source
      )
      ```

      Pour **intermediate** (jointures, agrégations légères) :
      ```sql
      -- [Clés de jointure]
      -- [Dimensions enrichies]
      -- [Métriques pré-calculées]
      -- [Flags / indicateurs métier]
      ```

      Pour **marts / fct** :
      ```sql
      -- [Clés de dimension (FK)]
      -- [Dates / périodes]
      -- [Métriques / faits]
      -- [Colonnes d'audit]
      ```

      Pour **marts / dim** :
      ```sql
      -- [Clé naturelle]
      -- [Clé surrogate (dbt_utils.generate_surrogate_key)]
      -- [Attributs descriptifs]
      -- [Dates de validité (SCD2 éventuel)]
      -- [Colonnes d'audit]
      ```

- [ ] **Export structuré par maillon** — le ZIP de téléchargement doit respecter
      l'arborescence DBT réelle :
      ```
      models/
        staging/
          raw/
            stg_commandes.sql
            stg_commandes_schema.yml
      sources/
        sources_raw.yml
      ```

---

### 🖥️ Application Streamlit — Correctifs UX (`app.py`)

- [ ] **Copier/coller — correctif** — remplacer le bouton download par un composant JS
      fonctionnel. Méthode recommandée :
      ```python
      st.components.v1.html(
          f"""<button onclick="navigator.clipboard.writeText(`{sql_escaped}`)">
               📋 Copier
          </button>""",
          height=40,
      )
      ```
      Attention : échapper les backticks et guillemets dans le SQL avant injection.
      Alternative plus robuste : stocker le SQL dans un `<textarea hidden id="sql">`
      et copier via `document.getElementById('sql').select(); document.execCommand('copy')`
      pour compatibilité navigateurs sans HTTPS
- [ ] **Export ZIP unique** — bouton "⬇️ Tout télécharger (.zip)" qui produit
      `.sql` + `schema.yml` + `sources.yml` + `staging_config.yml` dans l'arborescence
      DBT (voir section Génération ci-dessus)
- [ ] **Éditeur colonne-par-colonne** — remplacer l'éditeur YAML brut par
      `st.data_editor` sur un DataFrame des colonnes avec colonnes éditables :
      `include`, `target_name`, `cast`, `coalesce`, `keep_raw`, `string_case`, `comment`
      Synchronisation bidirectionnelle : data_editor → YAML et upload YAML → data_editor
- [ ] **Persistance chiffrée des credentials** — sauvegarder dans
      `~/.dbt_generator/credentials.enc` avec `cryptography.fernet`
- [ ] **Sidebar — historique de session** — liste des modèles générés pendant la
      session avec horodatage et lien de re-téléchargement
- [ ] **Thème DBT** — ajouter `.streamlit/config.toml` :
      ```toml
      [theme]
      primaryColor = "#FF694B"
      backgroundColor = "#FFFFFF"
      secondaryBackgroundColor = "#F5F5F5"
      textColor = "#1A1A1A"
      ```

---

### 📄 Génération YAML (`src/sources_generator.py` + `src/yaml_config.py`)

- [ ] **Multi-tables dans un seul sources.yml** — sélectionner N tables et les
      regrouper sous un même source DBT
- [ ] **Import d'un sources.yml existant** — merge intelligent pour ne pas écraser
      les descriptions/tests déjà écrits manuellement
- [ ] **Tests avancés DBT** — générer `accepted_values` (si ≤ 35 valeurs distinctes),
      `relationships`, `not_null_where`
- [ ] **Validation Pydantic** — remplacer les `dict[str, Any]` par des modèles Pydantic
      pour validation au parsing du YAML et autocomplétion

---

### 🧪 Tests (`tests/`)

> Créer le dossier `tests/` avec pytest + fixtures partagées dans `conftest.py`.

- [ ] **`tests/test_normalizer.py`**
  - `test_snake_case_camel`, `test_snake_case_acronym`
  - `test_strip_prefix`, `test_strip_suffix`
  - `test_remove_accents`, `test_remove_special_chars`
  - `test_combined_pipeline`
  - `test_build_sql_expression_string` — TRIM + LOWER + COALESCE + ::VARCHAR
  - `test_build_sql_expression_numeric` — pas de TRIM, COALESCE + ::FLOAT
  - `test_idempotence`

- [ ] **`tests/test_sources_generator.py`**
  - `test_basic_structure`, `test_pk_gets_unique_test`
  - `test_freshness_auto_detect_updated_at`, `test_freshness_auto_detect_maj`
  - `test_comments_propagated_to_description`
  - `test_yaml_is_valid`

- [ ] **`tests/test_yaml_config.py`**
  - `test_delta_auto_detect`, `test_composite_pk`, `test_cast_inference_*`
  - `test_cluster_by_in_config`
  - `test_where_clause_single_column`
  - `test_where_clause_composite_and`
  - `test_where_clause_composite_or`
  - `test_roundtrip_yaml`

- [ ] **`tests/test_model_generator.py`**
  - `test_sql_contains_source_ref`, `test_incremental_has_strategy`
  - `test_cluster_by_in_config_block`
  - `test_where_clause_injected_in_source_cte`
  - `test_where_after_delta_filter`
  - `test_excluded_column_absent`, `test_keep_raw_adds_raw_column`
  - `test_raw_columns_in_dedicated_section`
  - `test_comments_in_schema_yaml`
  - `test_layer_prefix_staging`, `test_layer_prefix_intermediate`
  - `test_layer_prefix_fct`, `test_layer_prefix_dim`
  - `test_audit_columns_when_enabled`
  - `test_purge_comment_when_enabled`

- [ ] **CI GitHub Actions** — `.github/workflows/test.yml` avec `pytest` + `ruff` sur PR

---

## Priorités suggérées

1. **Performance** — cache `@st.cache_data` + `st.form` sur la page Exploration
2. **Copier/coller** — correctif JS immédiat (bloquant pour les utilisateurs)
3. **Descriptions depuis commentaires** — propagation `COMMENT` Snowflake → YAML
4. **Filtres WHERE par colonne** — fonctionnalité métier clé
5. **Cluster keys** — optimisation Snowflake manquante
6. **Organisation par maillon** — structuration de la sortie DBT
7. **keep_raw amélioré** — sections dédiées dans le SQL
8. **Tests unitaires** — fondation qualité
9. **Export ZIP structuré** — praticité quotidienne

---

## Commandes utiles

```bash
# Installer les dépendances
pip install -r requirements.txt --break-system-packages

# Lancer l'app
streamlit run app.py

# Tests
pytest tests/ -v

# Lint
ruff check src/ app.py

# Vérifier la syntaxe
python -m py_compile src/*.py app.py
```
