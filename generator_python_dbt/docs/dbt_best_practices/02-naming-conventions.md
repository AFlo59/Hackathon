# 02 — Conventions de nommage dbt

> Source : [dbt — How we structure / Staging](https://docs.getdbt.com/best-practices/how-we-structure/2-staging)

## Nom de fichier / de modèle

Patron : **`stg_[source]__[entity]s.sql`**

- **double underscore** entre système source et entité (séparation visuelle) ;
- entité au **pluriel** (`customers`, `payments`) ;
- inclure le **système source** pour la découvrabilité.

| ✅ Recommandé                     | ❌ À éviter            |
|----------------------------------|------------------------|
| `stg_stripe__payments.sql`       | `stg_payments.sql`     |
| `stg_jaffle_shop__customers.sql` | `stg_customers.sql`    |

> « the double underscore … helps visually distinguish the separate parts.
> Think of it like an oxford comma, the extra clarity is very much worth the
> extra punctuation. »

## Nommage des colonnes

- **snake_case** systématique, cohérent sur tout le projet.
- **Clés (IDs)** : renommer avec un suffixe descriptif.

```sql
id      as payment_id,
orderid as order_id,
```

Cela clarifie le rôle de chaque identifiant et facilite l'usage en aval.

## Impact sur le générateur

- `yaml_config.build_model_name()` produit `stg_<source>__<entity>`.
- `yaml_config.entity_name()` nettoie le nom de table (retrait des préfixes
  techniques `T_`, `TBL_`, `DIM_`…).
- `normalizer.normalize_name()` met tout en `snake_case` (gère camelCase,
  acronymes, accents, caractères spéciaux, préfixes/suffixes métier).

> ⚠️ Point d'amélioration identifié : la **pluralisation** de l'entité et le
> **renommage automatique des IDs** (`id` → `<entity>_id`) ne sont pas encore
> appliqués — à arbitrer (risqué en français).
