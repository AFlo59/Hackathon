# 04 — Matérialisation, sources & tests

> Source : [dbt — How we structure / Staging](https://docs.getdbt.com/best-practices/how-we-structure/2-staging)

## Matérialisation : `view` par défaut

```yaml
# dbt_project.yml
models:
  jaffle_shop:
    staging:
      +materialized: view
```

Pourquoi `view` pour le staging :

- « Any downstream model … will always get the freshest data possible » ;
- « It avoids wasting space in the warehouse on models that are not intended to
  be queried by data consumers ».

> ⚠️ Tension avec la spec projet : le `CLAUDE.md` racine demande un support
> **incrémental** (`incremental_strategy='merge'`, filtre delta). Compromis
> retenu : **défaut = `view`** (conforme dbt), incrémental disponible en option,
> avec auto-détection de la colonne de mise à jour (`delta.column`) pour basculer
> facilement.

## Sources & freshness

Le `sources.yml` déclare les tables brutes et leur fraîcheur :

```yaml
version: 2
sources:
  - name: raw
    database: MY_DB
    schema: RAW_SALES
    tables:
      - name: T_COMMANDE
        loaded_at_field: T_CMD_MAJ
        freshness:
          warn_after:  {count: 24, period: hour}
          error_after: {count: 48, period: hour}
```

## Tests recommandés

- **Clé primaire** : `unique` + `not_null`.
- **Colonnes non nullables** : `not_null`.
- Tests métier : `accepted_values`, `relationships` (FK), `dbt_expectations`.

## Impact sur le générateur

| Bonne pratique                  | Implémentation                                  |
|---------------------------------|-------------------------------------------------|
| `view` par défaut               | `build_staging_config(materialized="view")`     |
| Incrémental optionnel + delta   | `delta.column` auto-détecté, filtre `is_incremental()` |
| `unique`+`not_null` sur PK      | `sources_generator` & `model_generator` (schema.yml) |
| `not_null` sur non-nullable     | `sources_generator.build_sources()`             |
| Freshness auto                  | `detect_delta_column()` → `loaded_at_field`     |

> Points d'amélioration identifiés : tests `accepted_values` / `relationships`,
> détection des FK candidates (`*_ID`), inférence du domaine depuis le schéma.
