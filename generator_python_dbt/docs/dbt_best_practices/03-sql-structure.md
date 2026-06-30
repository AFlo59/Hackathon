# 03 — Structure SQL (CTE) & organisation des colonnes

> Source : [dbt — How we structure / Staging](https://docs.getdbt.com/best-practices/how-we-structure/2-staging)

## Structure CTE standard

Tout modèle staging suit le même patron :

1. **CTE `source`** — récupère le brut via `source()` ;
2. **CTE `renamed`** — applique toutes les transformations ;
3. **`select * from renamed`** — sélection finale.

```sql
-- stg_stripe__payments.sql
with source as (
    select * from {{ source('stripe', 'payment') }}
),

renamed as (
    select
        -- ids
        id      as payment_id,
        orderid as order_id,
        -- strings
        paymentmethod as payment_method,
        -- numerics
        amount        as amount_cents,
        amount / 100.0 as amount,
        -- booleans
        case when status = 'successful' then true else false end as is_completed_payment,
        -- dates
        date_trunc('day', created) as created_date,
        -- timestamps
        created::timestamp_ltz as created_at
    from source
)

select * from renamed
```

## Organisation des colonnes par type

Grouper les colonnes par **section commentée**, dans cet ordre :

```
-- ids
-- strings
-- numerics
-- booleans
-- dates
-- timestamps
```

## Base models (exception aux jointures)

Pour une jointure technique nécessaire, créer un `base_` model dans un
sous-dossier, puis joindre dans le staging :

```sql
-- base_jaffle_shop__customers.sql
with source as (
    select * from {{ source('jaffle_shop', 'customers') }}
),
customers as (
    select id as customer_id, first_name, last_name from source
)
select * from customers
```

## Impact sur le générateur

`model_generator._select_body()` :

- émet exactement la structure `source → renamed → select * from renamed` ;
- regroupe les colonnes par type avec les commentaires `-- ids`, `-- strings`,
  `-- numerics`, `-- booleans`, `-- dates`, `-- timestamps` ;
- gère la virgule de fin automatiquement (pas de virgule sur la dernière
  expression ni sur les lignes de commentaire).
