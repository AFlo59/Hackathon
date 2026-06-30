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

## À améliorer / corriger (à traiter ensuite)

- [ ] Éléments qui ne fonctionnent pas (à identifier ensemble).
- [ ] Améliorations UX ciblées.

> Cette section sera enrichie au fur et à mesure des corrections.
