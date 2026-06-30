# DBT Model Generator

Application **Streamlit** qui génère des **modèles staging DBT optimisés**
(performance de requête prioritaire sur le stockage) pour **Snowflake**, à partir
de l'introspection des tables (`DESC TABLE`).

## Quoi ? Pourquoi ? Comment ?

- **Quoi** : générer du SQL DBT staging + `schema.yml` + `sources.yml` prêts à l'emploi.
- **Pourquoi** : éviter l'écriture manuelle, répétitive et source d'erreurs des modèles
  staging (normalisation des noms, casts, tests, freshness, incrémental).
- **Comment** : introspection Snowflake → config staging éditable → génération.

## Structure

```
generator_python_dbt/
├── app.py                       # Streamlit — 4 pages (Connexion / Exploration / Config / Génération)
├── requirements.txt
├── .streamlit/config.toml       # Thème Sofinco
├── src/
│   ├── __init__.py
│   ├── snowflake_connector.py   # Connexion + introspection + retry/reconnexion/Key-Pair/SSO
│   ├── sources_generator.py     # DESC TABLE → sources.yml DBT
│   ├── yaml_config.py           # Config staging (cast, delta, maillon, PII…) + dump YAML
│   ├── normalizer.py            # Normalisation des noms + expressions SQL
│   ├── model_generator.py       # Config → SQL staging + schema.yml
│   └── theme.py                 # Thème visuel Sofinco
├── tests/                       # Suite pytest (70 tests)
└── docs/                        # dbt_best_practices / streamlit / colors_enterprise / config_reference
```

## Lancer l'application

```bash
pip install -r requirements.txt
streamlit run app.py
```

## Flux d'utilisation

1. **Connexion** — saisir les paramètres Snowflake.
2. **Exploration** — naviguer database → schéma → table, puis *Introspecter*.
3. **Config** — préfixe/suffixe à retirer, édition colonne-par-colonne (`st.data_editor`),
   matérialisation ; YAML synchronisé en lecture.
4. **Génération** — onglets `model.sql` / `schema.yml` / `sources.yml`, **copie** du SQL
   et **export ZIP** de l'arborescence `models/staging/`.

## Fonctionnalités

- **Connecteur robuste** : retry exponentiel, reconnexion auto, auth mot de passe /
  Key-Pair / SSO / Okta, `DESC TABLE`→`DESC VIEW`, multi-profil.
- **Perf Streamlit** : cache `@st.cache_resource`/`@st.cache_data`, lazy loading,
  spinners localisés.
- **Génération dbt** : structure CTE `source → renamed → select`, casts `::TYPE`,
  colonnes groupées par type, filtre delta incrémental, `cluster_by`, colonnes
  d'audit, filtres `WHERE` composés, `keep_raw`, hooks/grants/persist_docs.
- **Médaillon** : `staging` / `intermediate` / `marts` (préfixe, dossier, libellés).
- **Métadonnées** : commentaires Snowflake → descriptions, détection **PII**.
- **Thème Sofinco** (voir [docs/colors_enterprise/](docs/colors_enterprise/README.md)).

Schéma complet de la config : [docs/config_reference.md](docs/config_reference.md).

## Conventions

- Python 3.11+, `from __future__ import annotations`, type hints, docstrings FR.
- Snowflake : casts via `::TYPE` (plus performant que `CAST()`).
- YAML : `_NullDumper` (`sort_keys=False`, `allow_unicode=True`).
- Streamlit : tout l'état via `st.session_state`, aucun appel réseau hors cache.

## Commandes utiles

```bash
pytest tests/ -v                 # tests
ruff check src/ app.py           # lint
streamlit run app.py             # app
python -m py_compile src/*.py app.py
```
