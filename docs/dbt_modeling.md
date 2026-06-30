# Modélisation dbt — couches & conventions de nommage

Ce document décrit l'architecture en couches du projet dbt et les conventions de nommage associées. Il constitue le socle des deux autres guides dbt :

- la stratégie de tests par couche est détaillée dans [`dbt_tests.md`](dbt_tests.md) ;
- l'orchestration (ordre de build, exécution de la freshness, CI GitLab, promotion) est détaillée dans [`dbt_workflow.md`](dbt_workflow.md).

On ne documente **pas** les modèles individuels ici : leur description vit dans les `description:` des YAML et remonte dans `dbt docs`. Ce guide porte les **principes**, pas l'inventaire.

-----

## 1. Vue d'ensemble des couches

Le projet suit les trois couches techniques recommandées par dbt Labs. La donnée est raffinée de gauche à droite, sans saut de couche :

```
sources (raw)  ──►  staging  ──►  intermediate  ──►  marts
                    stg_         int_              fct_/dim_
```

|Couche      |Rôle                                                        |Matérialisation (Snowflake)       |Exposé en aval|
|------------|------------------------------------------------------------|----------------------------------|--------------|
|Staging     |Nettoyage 1:1 de la source (renommage, recast, cosmétique)  |`ephemeral` (ou `view` si debug)  |Non           |
|Intermediate|Briques de logique métier intermédiaires (jointures, étapes)|`ephemeral` (ou `view` si debug)  |Non           |
|Marts       |Objets métier finaux consommés par PowerBI / le SI          |`table` (ou `incremental` si gros)|Oui           |

**Règle de dépendance :** un modèle ne référence que la couche immédiatement en amont ou la même couche. Staging lit les sources, intermediate lit staging, marts lit intermediate (ou staging si trivial). Pas de marts qui lit directement une source.

-----

## 2. Sources

Les sources sont un concept *first-class* de dbt (nœud de lineage à part entière, fonction `{{ source() }}`, contrôle de fraîcheur), **mais ce n'est pas une couche ni un dossier**. Leur déclaration est colocalisée dans `staging`, dans un sous-dossier par système source, aux côtés des modèles `stg_` qui s'appuient dessus.

- **Un fichier de déclaration par système source**, groupé : `_<source>__sources.yml`. Toutes les tables d'un même système y sont déclarées (elles partagent `database` / `schema` et les défauts de freshness).
- **Toutes les colonnes sont déclarées et documentées au niveau source.** Les descriptions sont moissonnées depuis les commentaires de colonnes Snowflake (via `dbt-codegen` `generate_source` avec `include_descriptions=true`). Le YAML de source est donc la **source de vérité documentaire** du projet.
- L'accès se fait **toujours** via `{{ source('<source>', '<table>') }}`, jamais en référence en dur à une table du warehouse.

**Propagation en aval.** Plutôt que de re-saisir les descriptions, on les **hérite** depuis l'amont via `dbt-codegen` `generate_model_yaml` avec **`upstream_descriptions=true`** (défaut `False`, donc à passer explicitement — sinon aucune description n'est remontée). L'héritage est soumis à trois conditions, sinon rien ne remonte pour la colonne concernée :

- **Codegen ≥ 0.13.0** : la lecture des descriptions depuis les **sources** n'a été ajoutée qu'en 0.13.0 (`#154`). Les versions antérieures (jusqu'à 0.12.1 incluse) ne lisent que les *modèles* amont — or le parent du staging est une source, donc rien ne remonte.
- **Noms de colonnes identiques** : la macro mappe par nom (insensible à la casse), pas par lignée. Une colonne **renommée** au staging (recast, conventions `est_`/`date_`/`_le`) perd le lien — sa description doit être posée localement.
- **Modèle déjà construit** : codegen introspecte la relation (`ref()` + `get_columns_in_relation`), donc `dbt run -s <modèle>` avant de générer le YAML.

Conséquence : l'héritage couvre les colonnes **passées telles quelles** ; les colonnes **renommées ou dérivées** sont documentées à la main (re-moisson, saisie, ou doc block si récurrentes — voir §6).

### Freshness

La **configuration** de fraîcheur vit ici (dans le YAML de source) :

```yaml
sources:
  - name: <source>
    database: RAW
    schema: <source>
    loaded_at_field: _etl_loaded_at
    freshness:
      warn_after:  { count: 12, period: hour }
      error_after: { count: 24, period: hour }
    tables:
      - name: <table>
```

L'**exécution** (`dbt source freshness`) et son placement dans la CI sont décrits dans [`dbt_workflow.md`](dbt_workflow.md).

-----

## 3. Staging

Première et seule couche en relation directe avec une source. Elle prépare la donnée brute sans rien décider sur le plan métier.

**Autorisé :** renommage de colonnes, cast de types, normalisation cosmétique (casse, trim), calculs triviaux ligne à ligne.
**Interdit :** jointures, agrégations, déduplication métier, logique applicative. Tout cela relève de l'intermediate.

- Matérialisation : `ephemeral` (toujours frais, coût de stockage nul).
- Un modèle de staging = une table source (relation 1:1).
- Organisation : un sous-dossier par système source.

```
models/staging/<source>/
  _<source>__sources.yml          # déclaration des sources (groupée par système)
  stg_<source>__<entity>.sql
  stg_<source>__<entity>.yml       # un YAML par modèle (voir §6)
```

-----

## 4. Intermediate

Couche de logique métier intermédiaire. Elle existe pour **décomposer** une transformation complexe en étapes lisibles et réutilisables, pas pour être consommée telle quelle.

- Jointures, agrégations, pivots, déduplication, application des règles métier.
- Matérialisation : `ephemeral` par défaut (inlinée en CTE, garde le warehouse propre) ; passer en `view` ponctuellement pour débugger.
- Organisation par concept métier, pas par source.
- Nommage : `int_<entité>_<verbe_au_participe>` (underscores simples, conforme à dbt Labs) — le verbe décrit l'action effectuée.

```
models/intermediate/<domaine>/
  int_orders_joined_to_payments.sql
  int_orders_joined_to_payments.yml
```

-----

## 5. Marts

Couche finale, exposée au SI et à PowerBI. Un mart représente un **objet métier** (entité ou processus), pensé pour la consommation analytique, pas pour refléter la structure source.

- Matérialisation : `table` par défaut ; `incremental` (stratégie `merge`, clé d'unicité, éventuellement `cluster_by`) pour les grosses tables de faits.
- Organisation par domaine métier : un sous-dossier par domaine (`finance`, `marketing`…).
- Nommage : `fct_<processus>` pour les faits, `dim_<entité>` pour les dimensions (convention Kimball).

```
models/marts/<domaine>/
  fct_orders.sql
  fct_orders.yml
  dim_customers.sql
  dim_customers.yml
```

-----

## 6. Conventions de nommage

### Fichiers de modèles

- **Le nom du fichier `.sql` est le nom du modèle.** Unique sur tout le projet.
- Le **double underscore** (`__`) est réservé au **staging**, pour séparer deux espaces de noms orthogonaux : `stg_<source>__<entity>`. L'intermediate n'a pas cette dualité et utilise des underscores simples : `int_<entité>_<verbe>`.
- **Un fichier YAML par modèle** (modèles uniquement — voir ci-dessous).

### Un YAML par modèle (convention assumée)

On s'écarte ici du défaut dbt Labs (un `_<source>__models.yml` regroupant plusieurs modèles) : **chaque modèle a son propre fichier de propriétés**, nommé comme le modèle et **sans underscore de tête**, pour qu'il soit adjacent à son `.sql`.

```
stg_billing__invoices.sql
stg_billing__invoices.yml   ◄── propriétés du seul modèle stg_billing__invoices
```

Justification : nos tables ont énormément de colonnes ; un fichier par modèle reste lisible, produit des diffs chirurgicaux en MR (quasi zéro conflit de merge), et colle au fonctionnement de `dbt-codegen` qui génère le YAML modèle par modèle. Coût technique nul : dbt agrège tous les `.yml`, le découpage lui est indifférent.

> ⚠️ Cette règle ne s'applique **qu'aux modèles**. Les **sources** restent groupées par système dans un `_<source>__sources.yml` (voir §2).

### Colonnes

**Langue : français.** Les noms de colonnes suivent la langue des sources (français) : on évite un renommage massif au staging et on garde la cohérence avec les descriptions moissonnées et le vocabulaire des consommateurs PowerBI.

> Distinction structurante : seules les **données** (noms de colonnes) sont en français. Le **code et la structure** restent en anglais — préfixes de couche (`stg_`/`int_`/`fct_`/`dim_`), noms de CTE, macros, variables, arborescence des dossiers. La langue des colonnes est **unique sur tout le projet** ; les descriptions sont en français.

Conventions :

- `snake_case` partout.
- Clés : `<entité>_id` (clés de substitution générées via `dbt_utils.generate_surrogate_key`).
- Booléens : préfixe `est_` (`est_actif`, `est_solde`). Pour une possession/occurrence où `a_` se lit mal, reformuler en état ou utiliser le préfixe neutre `flag_`.
- Dates pures : préfixe `date_` (`date_creation`, `date_facture`) — idiomatique.
- Horodatages (UTC) : suffixe `_le` sur le participe (`cree_le`, `modifie_le`, `annule_le`). L'asymétrie préfixe (dates) / suffixe (horodatages) est assumée : elle privilégie une lecture française naturelle.
- Ordre des colonnes conseillé : identifiants → attributs/dimensions → mesures → colonnes techniques/audit.

### Doc blocks (colonnes dérivées récurrentes)

Les colonnes issues des sources sont déjà documentées par moisson (§2) et héritées en aval — pas besoin de doc blocks pour elles. Les doc blocks servent aux colonnes **dérivées** créées en intermediate/marts et réutilisées dans plusieurs modèles (ex. un indicateur calculé, une clé de substitution standardisée), pour éviter de re-saisir la même description :

```
models/_project__docs.md
```

```markdown
{% docs montant_ttc %}
Montant toutes taxes comprises, calculé comme montant HT × (1 + taux de TVA applicable).
{% enddocs %}
```

```yaml
# dans n'importe quel <model>.yml exposant cette colonne dérivée
columns:
  - name: montant_ttc
    description: '{{ doc("montant_ttc") }}'
```

-----

## 7. Arborescence cible

```
models/
├── staging/
│   ├── billing/
│   │   ├── _billing__sources.yml
│   │   ├── stg_billing__invoices.sql
│   │   ├── stg_billing__invoices.yml
│   │   ├── stg_billing__customers.sql
│   │   └── stg_billing__customers.yml
│   └── crm/
│       ├── _crm__sources.yml
│       ├── stg_crm__contacts.sql
│       └── stg_crm__contacts.yml
├── intermediate/
│   └── orders/
│       ├── int_orders_joined_to_payments.sql
│       └── int_orders_joined_to_payments.yml
└── marts/
    └── finance/
        ├── fct_orders.sql
        ├── fct_orders.yml
        ├── dim_customers.sql
        └── dim_customers.yml
```

-----

## Renvois

- Tests par couche, sévérité, tests custom, data vs unit tests → [`dbt_tests.md`](dbt_tests.md)
- Ordre de build, exécution de la freshness, CI GitLab, promotion → [`dbt_workflow.md`](dbt_workflow.md)