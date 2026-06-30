# Tests dbt — taxonomie, socle par couche & conventions

Ce document décrit **quels** tests on écrit, **comment** on les nomme et les configure, et le **socle attendu par couche**. Il s'articule avec les deux autres guides dbt :

- la structure en couches référencée ici est définie dans [`dbt_modeling.md`](dbt_modeling.md) ;
- l'**exécution** des tests (quand ils tournent, ce qui bloque la CI GitLab, l'exécution de la freshness, l'ordre de build) est décrite dans [`dbt_workflow.md`](dbt_workflow.md).

Contexte technique du projet : dbt-core **1.10.8**, packages `dbt_utils` et `dbt_expectations` disponibles.

-----

## 1. Taxonomie des tests

dbt distingue deux familles, à ne pas confondre :

|Famille       |Ce qu'elle valide                                                                                     |Sur quoi                                               |
|--------------|------------------------------------------------------------------------------------------------------|-------------------------------------------------------|
|**Data tests**|Des assertions sur la donnée *réelle* produite par un modèle (unicité, non-nullité, plage de valeurs…)|Les lignes en base après `dbt run`                     |
|**Unit tests**|La *logique* de transformation (CASE, jointures, fenêtrage, calculs) sur des entrées contrôlées       |Des fixtures mockées, sans dépendre de la donnée réelle|

Au sein des **data tests**, quatre formes :

- **Génériques natifs** : `unique`, `not_null`, `accepted_values`, `relationships`. Déclarés dans le YAML.
- **Génériques de packages** : fournis par `dbt_utils` et `dbt_expectations` (voir §2). Déclarés dans le YAML.
- **Singuliers** : une requête SQL dans `tests/` qui retourne les lignes en échec. Pour une règle métier ponctuelle, non réutilisable.
- **Génériques custom** : un test réutilisable défini une fois (`{% test ... %}`) dans `tests/generic/`, puis appelé comme un test natif.

> Clé YAML : depuis dbt 1.8, la clé recommandée pour les data tests est **`data_tests:`** (l'ancienne `tests:` reste acceptée). On utilise `data_tests:` dans tout le projet.

-----

## 2. Packages standard

Deux packages constituent le standard du projet. Leur déclaration et l'épinglage des versions vivent dans `packages.yml` (cf doc d'installation), pas ici — ce guide ne porte que leur usage.

- **`dbt_utils`** — socle de fait. Tests les plus utilisés : `unique_combination_of_columns` (clés composites), `accepted_range`, `not_null_proportion`, `expression_is_true`, `relationships_where`, `equal_rowcount` / `fewer_rows_than`, `cardinality_equality`.
- **`dbt_expectations`** — contrôles plus riches, style Great Expectations. Réservé aux marts (voir §3) : `expect_column_values_to_be_between`, `expect_column_values_to_match_regex`, `expect_column_distinct_count_to_equal`, `expect_column_values_to_be_of_type`, `expect_table_row_count_to_be_between`.

Règle d'arbitrage : on privilégie le **natif**, puis `dbt_utils` quand le natif ne suffit pas, et on réserve `dbt_expectations` aux contrôles métier fins des marts. On ne multiplie pas les dépendances pour un test qu'un singulier ferait aussi bien.

-----

## 3. Socle par couche

Principe directeur : **tester le grain à chaque couche matérialisée**, être strict au plus près de la consommation (marts) et léger là où la donnée n'est pas exposée (intermediate). Pour chaque couche : ce qui est **exigé** (bloquant) et ce qui est **recommandé**.

### Sources

- **Exigé** : freshness (configurée dans `dbt_modeling.md`, exécutée via `dbt_workflow.md`).
- **Recommandé** : `unique` + `not_null` sur la clé primaire si la source en garantit une. Sinon, on reporte le contrôle de grain au staging — la donnée brute n'est pas toujours fiable.

### Staging

- **Exigé** : le **grain**. Clé primaire en `unique` + `not_null`, ou `dbt_utils.unique_combination_of_columns` pour une clé composite. C'est le test non négociable de la couche.
- **Recommandé** : `accepted_values` sur les énumérations à faible cardinalité, `not_null` sur les colonnes structurantes.
- On reste léger : le staging est en 1:1 avec la source, sans logique métier à éprouver.

### Intermediate

- **Exigé** : la **préservation du grain** aux points de risque. Après une jointure, vérifier qu'il n'y a pas eu d'explosion (unicité maintenue, ou `equal_rowcount` vs l'amont) ; après une déduplication, vérifier l'unicité.
- **Recommandé** : pour la logique dense (règles métier, calculs), privilégier les **unit tests** (§5) plutôt que de multiplier les data tests — ils valident la logique sans attendre que la donnée réelle déclenche le cas.

### Marts

Couche la plus stricte : c'est le point de consommation PowerBI, donc la porte de qualité.

- **Exigé** : grain (`unique` + `not_null` sur la clé du mart) ; `not_null` sur les clés et les mesures critiques ; `relationships` des clés étrangères des faits vers leurs dimensions.
- **Recommandé** : tests métier — plages de valeurs (`accepted_range` / `expect_column_values_to_be_between`), règles de cohérence (`expression_is_true` ou singuliers), contrôles `dbt_expectations`.

### Récapitulatif

|Couche      |Grain                       |not_null clés/critiques|relationships    |Tests métier riches|
|------------|:--------------------------:|:---------------------:|:---------------:|:-----------------:|
|Sources     |recommandé                  |—                      |—                |—                  |
|Staging     |**exigé**                   |recommandé             |—                |—                  |
|Intermediate|**exigé** (points de risque)|—                      |—                |via unit tests     |
|Marts       |**exigé**                   |**exigé**              |**exigé** (faits)|recommandé         |

-----

## 4. Sévérité & seuils

Trois leviers, configurables par test (dans le YAML) ou globalement (`dbt_project.yml`) :

- **`severity`** : `error` (défaut, bloque) ou `warn` (signale sans bloquer).
- **`error_if` / `warn_if`** : seuils sur le nombre de lignes en échec, ex. `warn_if: '>0'` et `error_if: '>100'`. Utile pour tolérer un bruit connu.
- **`store_failures: true`** : matérialise les lignes en échec dans un schéma dédié, pour investigation.

Lignes directrices :

- `error` par défaut — un test qui ne bloque jamais ne sert à rien.
- `warn` pour un test bruité, ou nouvellement introduit le temps de fiabiliser la donnée.
- `store_failures` sur les tests métier complexes des marts, où comprendre *quelles* lignes échouent fait gagner du temps.

```yaml
data_tests:
  - dbt_utils.accepted_range:
      min_value: 0
      config:
        severity: warn
        warn_if: '>0'
        error_if: '>50'
        store_failures: true
```

Ce qui bloque effectivement la CI relève de [`dbt_workflow.md`](dbt_workflow.md).

-----

## 5. Unit tests

Supportés en dbt 1.10. Ils valident la **logique** d'un modèle sur des entrées mockées : on fournit des lignes d'entrée (`given`) et la sortie attendue (`expect`), indépendamment de la donnée réelle.

Quand les utiliser : sur les modèles à **logique dense** — règles métier en intermediate, calculs et agrégations en marts. **Pas** sur le staging (passe-plat sans logique à éprouver).

Déclaration au niveau racine du YAML du modèle concerné (`unit_tests:`, frère de `models:`) :

```yaml
unit_tests:
  - name: test_montant_ttc_applique_la_tva
    model: fct_factures
    given:
      - input: ref('int_factures_consolidees')
        rows:
          - { facture_id: 1, montant_ht: 100.0, taux_tva: 0.20 }
    expect:
      rows:
        - { facture_id: 1, montant_ttc: 120.0 }
```

Les unit tests s'exécutent avec `dbt test` ; leur ciblage en CI est traité dans [`dbt_workflow.md`](dbt_workflow.md).

-----

## 6. Nommage & emplacement

- **Data tests (génériques)** : déclarés dans le **YAML du modèle** (un YAML par modèle, cf `dbt_modeling.md`). Au niveau colonne pour un test mono-colonne, au niveau modèle pour les tests multi-colonnes (`unique_combination_of_columns`, etc.).
- **Tests singuliers** : fichiers SQL dans `tests/`, nommés `assert_<règle>.sql` — ex. `assert_montant_ttc_positif.sql`.
- **Tests génériques custom** : un fichier par test dans `tests/generic/`, `<nom_du_test>.sql` contenant `{% test <nom>(model, column_name) %}`.
- **Unit tests** : dans le YAML du modèle, sous `unit_tests:`.

Cohérence avec la convention de langue (cf `dbt_modeling.md`) : les **noms de tests et de macros** sont du code → anglais ; ils peuvent référencer des **colonnes** en français.

-----

## Renvois

- Exécution des tests et de la freshness, ce qui bloque la CI GitLab, ordre de build, promotion → [`dbt_workflow.md`](dbt_workflow.md)
- Couches, structure des dossiers, conventions de nommage des modèles → [`dbt_modeling.md`](dbt_modeling.md)