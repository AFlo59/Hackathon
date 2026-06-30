# Documentation Streamlit — DBT Model Generator

Documentation de l'interface (`app.py`). Volontairement simple pour l'instant.

## Lancer

```bash
streamlit run app.py
```

## Les 4 pages

| Page              | Rôle                                                              |
|-------------------|------------------------------------------------------------------|
| 🔌 **Connexion**   | Saisie des paramètres Snowflake et ouverture de connexion.       |
| 🗂️ **Exploration** | Navigation database → schéma → table, puis introspection.        |
| ⚙️ **Config**      | Édition de la config staging (éditeur colonne-par-colonne + YAML).|
| 🚀 **Génération**  | `model.sql` / `schema.yml` / `sources.yml` + copie + export ZIP. |

## État de session (`st.session_state`)

Toute mutation d'état passe par `st.session_state` (jamais de variable globale).

| Clé             | Contenu                                              |
|-----------------|------------------------------------------------------|
| `connector`     | instance `SnowflakeConnector`                        |
| `connected`     | booléen de statut de connexion                       |
| `columns`       | métadonnées de la table introspectée                 |
| `selection`     | `{database, schema, table}` sélectionnés             |
| `config`        | dict de config staging                               |
| `config_yaml`   | version texte (YAML) synchronisée                    |

## Flux de données

```
Connexion ──► Exploration ──► Config ──► Génération
 connector     columns +       config      sql / schema.yml /
               selection                   sources.yml (+ ZIP)
```

## Performance (lot 1 — fait)

- **Cache** : `_get_connector` (`@st.cache_resource`) pour la connexion ;
  `_cached_databases/schemas/tables/columns` (`@st.cache_data(ttl=300)`) pour
  l'introspection. Aucun appel réseau dans le corps d'une page.
- **Clé de cache** : `account` (le connecteur, non sérialisable, est passé en
  `_connector` donc non hashé).
- **Cascade** : les `selectbox` restent réactifs (nécessaire pour la cascade
  database→schéma→table) mais les listes sont en cache → reruns sans réseau.
  C'est le vrai correctif de lenteur (un `st.form` casserait la cascade).
- **Lazy loading** : colonnes introspectées seulement au clic « Introspecter ».
- **Spinners localisés** + pagination du tableau de colonnes (> 50 → hauteur fixe).

## UX (lot 1 — fait)

- **Copier/coller** corrigé : `navigator.clipboard` + fallback `textarea` /
  `execCommand` (compatibilité hors HTTPS).
- **Export ZIP structuré** (arborescence dbt) : `models/staging/<source>/<model>.sql`,
  `<model>_schema.yml`, `sources/sources_<source>.yml`, `staging_config.yml`.
- **Historique de session** dans la sidebar (re-téléchargement du ZIP).
- **Import YAML** : upload d'un `staging_config.yml` → rechargé dans l'éditeur.

## À traiter ensuite

- [ ] Persistance chiffrée des credentials (`cryptography.fernet`).
- [ ] Détection PII (badge ⚠️) dans l'éditeur de colonnes.
