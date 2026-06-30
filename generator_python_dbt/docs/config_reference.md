# Référence — `staging_config.yml`

Document pivot produit par `yaml_config.build_staging_config()`, éditable dans la
page Config (éditeur + import YAML), consommé par `model_generator`.

```yaml
source:
  name: raw                       # nom du source dbt
  table: T_COMMANDE               # table source

model:
  name: stg_raw__commande         # stg_<source>__<entity> (auto selon maillon)
  materialized: incremental       # view | table | incremental | ephemeral
  layer: staging                  # staging | intermediate | marts_fct | marts_dim
  schema: staging
  tags: [staging]
  meta: {}

unique_key: id                    # str | list[str] | "TODO_SET_UNIQUE_KEY"

delta:                            # filtre incrémental (is_incremental)
  enabled: true
  column: T_CMD_MAJ               # colonne TIMESTAMP de mise à jour (auto-détectée)

purge:
  enabled: false                  # ajoute un commentaire {# PURGE #}

cluster_by:                       # table / incremental uniquement
  enabled: false
  columns: []

audit:
  enabled: false                  # _loaded_at + _dbt_invocation_id

where_clause:
  mode: and                       # and | or
  filters:
    - {column: STATUT, operator: in,      values: [ACTIF, VALIDE]}
    - {column: PAYS,   operator: not_in,  values: [TEST]}
    - {column: MONTANT, operator: between, values: [0, 1000]}
    - {column: X,      operator: custom,  custom_expr: "X > 0"}

hooks:
  pre_hook: []
  post_hook: ["GRANT SELECT ON {{ this }} TO ROLE REPORTER"]

grants: {select: [ROLE_REPORTER]} # grants dbt natifs (≥ 1.2)
persist_docs: {relation: false, columns: false}
on_schema_change: null            # fail | ignore | append_new_columns | sync_all_columns

normalization:
  prefix: "T_CMD_"
  suffix: ""
  keep_all_raw: false             # raw_* pour TOUTES les colonnes

columns:
  - source: T_CMD_NOM             # nom source
    target: nom                   # nom normalisé (snake_case)
    cast: VARCHAR                 # type cible (::TYPE)
    include: true                 # inclure dans le SELECT
    keep_raw: false               # ajoute raw_<target>
    string_case: lower            # lower | upper | none
    trim: true                    # TRIM (chaînes)
    coalesce: null                # littéral SQL ou null
    is_string: true
    comment: null                 # description (commentaire Snowflake)
    pii: false                    # donnée personnelle détectée → meta.pii
```

## Opérateurs de filtre WHERE

| `operator` | Rendu SQL                              |
|------------|----------------------------------------|
| `in`       | `"COL" in ('a', 'b')`                  |
| `not_in`   | `"COL" not in ('a', 'b')`             |
| `between`  | `"COL" between v0 and v1`              |
| `custom`   | expression libre (`custom_expr`)       |

Les valeurs numériques ne sont pas mises entre quotes ; les chaînes sont
échappées. Les filtres sont combinés par `mode` (`and`/`or`), puis le filtre
delta est ajouté sous `{% if is_incremental() %}`.

## Maillons (médaillon)

| `layer`        | Préfixe | Dossier ZIP            | Libellés de section          |
|----------------|---------|------------------------|------------------------------|
| `staging`      | `stg_`  | `models/staging/<src>/`| `-- ids/strings/numerics…`   |
| `intermediate` | `int_`  | `models/intermediate/` | `[Clés de jointure]…`        |
| `marts_fct`    | `fct_`  | `models/marts/`        | `[Clés de dimension (FK)]…`  |
| `marts_dim`    | `dim_`  | `models/marts/`        | `[Clé naturelle / surrogate]…`|
