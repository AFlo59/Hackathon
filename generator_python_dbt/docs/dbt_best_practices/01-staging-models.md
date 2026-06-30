# 01 — Modèles staging dbt

> Source : [dbt — How we structure / Staging](https://docs.getdbt.com/best-practices/how-we-structure/2-staging)

## Rôle du staging

Le staging est **l'unité atomique** d'un projet dbt : la première couche de
transformation, point d'entrée de chaque table source.

> « Staging models should have a 1-to-1 relationship to our source tables. »

Pour **chaque table source**, on crée **un seul** modèle staging qui la référence
via la macro `source()`.

## Transformations AUTORISÉES

| Transformation        | Exemple                                                |
|-----------------------|--------------------------------------------------------|
| **Renommage**         | aligner les noms source sur les standards du projet    |
| **Cast de type**      | `created::timestamp_ltz` (sur Snowflake : `::TYPE`)    |
| **Calculs simples**   | conversion d'unité : `amount / 100.0 as amount`        |
| **Catégorisation**    | `case when ... then ... end` (buckets, booléens)       |

```sql
-- catégorisation
case
    when payment_method in ('stripe', 'paypal', 'credit_card') then 'credit'
    else 'cash'
end as payment_type
```

## Transformations INTERDITES

- **Jointures** — « joins are almost always a bad idea here — they create
  immediate duplicated computation and confusing relationships ». Le but est de
  nettoyer **un concept source à la fois**.
- **Agrégations** — « if we start changing the grain of our tables by grouping in
  this layer, we'll lose access to source data ». On ne change pas le grain.

> Exception : les `base_` models pour des jointures techniques nécessaires
> (tables de suppression, union de sources symétriques) — voir fichier 03.

## Impact sur le générateur

`model_generator.py` produit **uniquement** : renommage + cast `::TYPE` +
`TRIM`/`LOWER`/`COALESCE` (nettoyage), et **jamais** de jointure ni d'agrégation.
Le grain de la table source est préservé.
