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

#### Cluster Keys (multi-colonnes)

- [ ] **CLUSTER BY multi-colonnes dans la config staging** — le clustering doit supporter
      une ou plusieurs colonnes, ordonnées par priorité de filtrage (la plus sélective en premier).
      Structure YAML :
      ```yaml
      cluster_by:
        enabled: true
        columns:                 # liste ordonnée — ordre = priorité Snowflake
          - date_commande        # colonne de partition principale (date, période)
          - statut               # colonne de filtrage secondaire
          - pays                 # troisième niveau si nécessaire (max 4 recommandé)
      ```
      Générer dans le SQL :
      ```sql
      {{ config(
          materialized='table',
          cluster_by=['date_commande', 'statut', 'pays']
      ) }}
      ```
      Règles de génération :
      - Valable uniquement pour `table` et `incremental` (griser l'option si `view` ou `ephemeral`)
      - Maximum 4 colonnes (limite de performance Snowflake au-delà)
      - Avertissement si une colonne de type `VARCHAR(>256)` ou `VARIANT` est sélectionnée
        (mauvais candidat au clustering)
      - Avertissement si aucune colonne de type `DATE`/`TIMESTAMP` n'est en première position
        (anti-pattern fréquent)

      UI dans la page Config — section "Optimisation Snowflake" :
      - `st.multiselect("Colonnes de clustering (ordre = priorité)", options=colonnes_incluses,
        max_selections=4)` avec réordonnancement possible via drag-and-drop (streamlit-sortables)
        ou numérotation manuelle
      - Indicateur visuel du type de chaque colonne candidate (🗓️ date, 🔤 texte, 🔢 numérique)
      - Prévisualisation live du `cluster_by=[...]` généré sous le multiselect

#### Filtre WHERE — Critères composés avec AND / OR

> Principe : la clause WHERE est une liste de **groupes de critères**.
> Au sein d'un groupe, les critères sont combinés par `AND` ou `OR`.
> Les groupes eux-mêmes sont combinés par `AND` entre eux (comme en SQL standard).
> Cela permet d'exprimer : `(A AND B) AND (C OR D)`.

- [ ] **Fonction `get_distinct_values(conn, db, schema, table, column, limit=36)`** dans
      `snowflake_connector.py` — exécute `SELECT DISTINCT "{col}" FROM "{db}"."{sch}"."{tbl}"
      ORDER BY 1 LIMIT 36`. Retourne la liste triée si ≤ 35 valeurs, sinon `None`.
      Mettre en cache avec `@st.cache_data(ttl=120)`.

- [ ] **Structure YAML de la clause WHERE composée** :
      ```yaml
      staging:
        where_clause:
          groups:                          # liste de groupes — combinés par AND entre eux
            - label: "Statuts valides"     # libellé libre pour lisibilité
              connector: and               # opérateur ENTRE les critères de CE groupe
              filters:
                - column: STATUT
                  operator: in             # in | not_in | between | gte | lte | eq | neq | custom
                  values: [ACTIF, VALIDE]  # liste (≤ 35 valeurs) ou null si custom
                  custom_expr:             # expression SQL brute si operator=custom ou >35 valeurs

                - column: DATE_COMMANDE
                  operator: gte
                  values: ["2024-01-01"]

            - label: "Exclusions pays"
              connector: or                # OR entre les critères de CE groupe
              filters:
                - column: PAYS
                  operator: not_in
                  values: [TEST, SANDBOX]

                - column: MONTANT
                  operator: custom
                  custom_expr: "MONTANT > 0"
      ```
      SQL généré (dans le CTE `source`, après le filtre delta) :
      ```sql
      where (
          -- Statuts valides
          STATUT IN ('ACTIF', 'VALIDE')
          AND DATE_COMMANDE >= '2024-01-01'
      )
      and (
          -- Exclusions pays
          PAYS NOT IN ('TEST', 'SANDBOX')
          OR MONTANT > 0
      )
      ```

- [ ] **Opérateurs supportés** et leur rendu SQL :

      | Opérateur    | Condition          | SQL généré                          |
      |--------------|--------------------|-------------------------------------|
      | `in`         | ≤ 35 valeurs       | `COL IN ('A', 'B')`                 |
      | `not_in`     | ≤ 35 valeurs       | `COL NOT IN ('A', 'B')`             |
      | `between`    | exactement 2 val.  | `COL BETWEEN 'A' AND 'B'`           |
      | `eq`         | 1 valeur           | `COL = 'A'`                         |
      | `neq`        | 1 valeur           | `COL != 'A'`                        |
      | `gte`        | 1 valeur           | `COL >= 'A'`                        |
      | `lte`        | 1 valeur           | `COL <= 'A'`                        |
      | `is_null`    | aucune valeur      | `COL IS NULL`                       |
      | `is_not_null`| aucune valeur      | `COL IS NOT NULL`                   |
      | `custom`     | expression libre   | expression SQL brute telle quelle   |

- [ ] **UI dans la page Config — constructeur de WHERE visuel** :
      - Section "Filtres WHERE" avec bouton "+ Ajouter un groupe"
      - Chaque groupe affiche :
        - Libellé éditable (`st.text_input`)
        - Sélecteur `AND` / `OR` pour le connecteur intra-groupe (`st.radio`)
        - Liste de critères avec bouton "+ Ajouter un critère"
        - Pour chaque critère :
          1. `st.selectbox` colonne (parmi les colonnes incluses)
          2. `st.selectbox` opérateur (liste ci-dessus, filtrée selon le type Snowflake)
          3. Selon opérateur + nombre de valeurs distinctes :
             - ≤ 35 valeurs distinctes → `st.multiselect` des valeurs (chargé au clic)
             - > 35 valeurs ou `custom` → `st.text_input` expression SQL libre
          4. Bouton 🗑️ pour supprimer le critère
        - Bouton 🗑️ pour supprimer le groupe entier
      - **Prévisualisation live** de la clause WHERE complète dans un `st.code` mis à jour
        à chaque modification, sans rerun de toute la page (utiliser `st.session_state`)
      - Validation : erreur si un `between` n'a pas exactement 2 valeurs,
        si un `eq` a plusieurs valeurs, etc.

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

#### Datatypes Snowflake — propagation complète dans les YAML générés

> Le type Snowflake natif (colonne `type` de DESC TABLE, ex : `NUMBER(38,0)`,
> `VARCHAR(256)`, `TIMESTAMP_NTZ(9)`) doit être présent dans tous les fichiers
> générés, en plus du cast DBT simplifié. Les deux notions sont distinctes :
> - `data_type` = type Snowflake brut tel que retourné par DESC TABLE → va dans `sources.yml`
> - `cast` = type simplifié pour le `::CAST` dans le SQL → va dans la config staging
> - `data_type` dans le `schema.yml` = type normalisé DBT (optionnel mais recommandé)

- [ ] **`data_type` dans `sources.yml`** — chaque colonne doit inclure le type Snowflake
      brut extrait de DESC TABLE :
      ```yaml
      sources:
        - name: raw
          tables:
            - name: COMMANDES
              columns:
                - name: CMD_ID
                  data_type: NUMBER(38,0)      # ← type Snowflake brut
                  description: "Identifiant commande"
                  tests: [unique, not_null]

                - name: CMD_CLIENT
                  data_type: VARCHAR(256)       # ← type Snowflake brut
                  description: "Nom du client"

                - name: CMD_MAJ
                  data_type: TIMESTAMP_NTZ(9)   # ← type Snowflake brut
                  description: "Dernière mise à jour"
      ```
      Le champ `data_type` est écrit tel quel depuis `col["type"]` de `desc_table()`,
      sans transformation — c'est la source de vérité.

- [ ] **`data_type` dans `schema.yml` du modèle** — après normalisation du nom,
      le type est converti en type DBT standardisé (compatible cross-adapter) :
      ```yaml
      models:
        - name: stg_commandes
          columns:
            - name: cmd_id
              data_type: bigint           # ← type DBT normalisé (issu de infer_cast())
              description: "Identifiant commande"
              tests: [unique, not_null]

            - name: cmd_client
              data_type: varchar          # ← type DBT normalisé
              description: "Nom du client"

            - name: raw_cmd_client        # colonne brute keep_raw=True
              data_type: varchar
              description: "Valeur brute non normalisée de CMD_CLIENT"
      ```
      Table de mapping `snowflake_type → dbt_type` (dans `normalizer.py`) :

      | Type Snowflake (regex)       | Type DBT      |
      |------------------------------|---------------|
      | `NUMBER(*,0)`, `INT*`        | `bigint`      |
      | `NUMBER(*,>0)`, `FLOAT*`     | `float`       |
      | `VARCHAR*`, `TEXT`, `STRING` | `varchar`     |
      | `BOOLEAN`                    | `boolean`     |
      | `DATE`                       | `date`        |
      | `TIMESTAMP_NTZ*`             | `timestamp`   |
      | `TIMESTAMP_TZ*`              | `timestamptz` |
      | `VARIANT`, `OBJECT`, `ARRAY` | `variant`     |

- [ ] **Affichage dans l'UI** — dans la page Config, le tableau de colonnes doit montrer
      deux colonnes côte à côte :
      - `Type source (Snowflake)` — non éditable, valeur brute de DESC TABLE
      - `Cast DBT (cible)` — éditable, valeur déduite mais overridable par l'utilisateur

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
  - `test_cluster_by_single_column`
  - `test_cluster_by_multi_columns_ordered` — ordre préservé dans le YAML
  - `test_cluster_by_ignored_for_view` — pas de cluster_by si mat=view
  - `test_cluster_by_ignored_for_ephemeral`
  - `test_where_single_group_and` — un groupe, connecteur AND
  - `test_where_single_group_or` — un groupe, connecteur OR
  - `test_where_multi_group` — deux groupes combinés par AND implicite
  - `test_where_operator_in`, `test_where_operator_not_in`
  - `test_where_operator_between` — exactement 2 valeurs
  - `test_where_operator_gte`, `test_where_operator_lte`
  - `test_where_operator_is_null`, `test_where_operator_is_not_null`
  - `test_where_operator_custom` — expression SQL libre
  - `test_datatype_preserved_in_config` — `col["type"]` non modifié
  - `test_roundtrip_yaml`

- [ ] **`tests/test_sources_generator.py`** (ajouts)
  - `test_data_type_snowflake_raw_in_sources_yml` — `NUMBER(38,0)` → `data_type: NUMBER(38,0)`
  - `test_data_type_varchar_in_sources_yml`
  - `test_data_type_timestamp_in_sources_yml`
  - `test_comments_propagated_to_description`

- [ ] **`tests/test_model_generator.py`**
  - `test_sql_contains_source_ref`, `test_incremental_has_strategy`
  - `test_cluster_by_single_col_in_config_block`
  - `test_cluster_by_multi_cols_in_config_block` — `cluster_by=['a', 'b', 'c']`
  - `test_cluster_by_absent_for_view`
  - `test_where_single_group_and_injected`
  - `test_where_multi_group_injected` — deux groupes dans le SQL
  - `test_where_after_delta_filter` — WHERE après le filtre `is_incremental()`
  - `test_where_in_operator_sql_render`
  - `test_where_between_operator_sql_render`
  - `test_where_custom_expr_passthrough`
  - `test_excluded_column_absent`, `test_keep_raw_adds_raw_column`
  - `test_raw_columns_in_dedicated_section`
  - `test_data_type_dbt_in_schema_yml` — `NUMBER(38,0)` → `data_type: bigint`
  - `test_data_type_raw_col_inherits_source_type`
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
3. **Datatypes** — `data_type` Snowflake → `sources.yml` + `schema.yml` (correctif de fond)
4. **Descriptions depuis commentaires** — propagation `COMMENT` Snowflake → YAML
5. **Cluster keys multi-colonnes** — optimisation Snowflake + UI multiselect ordonnée
6. **Filtres WHERE composés** — constructeur visuel AND/OR par groupes
7. **Organisation par maillon** — structuration de la sortie DBT
8. **keep_raw amélioré** — sections dédiées dans le SQL
9. **Tests unitaires** — fondation qualité
10. **Export ZIP structuré** — praticité quotidienne

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
