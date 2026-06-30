# Contrat et clé primaire des marts

Règle de gouvernance applicable à **tout mart** (objet matérialisé exposé aux consommateurs). Elle garantit la stabilité du schéma et l'intégrité de l'identifiant.

---

## 1. La règle

Tout mart doit respecter les trois obligations suivantes :

1. **Contrat activé** : `config.contract.enforced: true`.
2. **Clé primaire déclarée** via une `constraint` de type `primary_key` (au niveau colonne pour une PK simple, au niveau modèle pour une PK composite).
3. **Tests d'intégrité sur la clé primaire** : `not_null` et unicité (`unique` pour une PK simple, `dbt_utils.unique_combination_of_columns` pour une PK composite).

Ces trois obligations sont **contrôlées en CI** (voir §5).

---

## 2. Répartition des rôles — qui garantit quoi

Point essentiel pour ne pas se fier au mauvais mécanisme : les trois obligations ne protègent pas la même chose.

| Mécanisme | Garantit | Ne garantit pas |
|---|---|---|
| `contract.enforced: true` | Le **schéma** : présence des colonnes déclarées et conformité de leurs types au build (le run échoue si l'objet produit ne correspond pas). | L'intégrité des **données**. |
| `constraint primary_key` | Une **métadonnée déclarative** (la PK figure dans le DDL, lisible par les outils). | L'unicité à l'écriture : sur Snowflake, `primary_key` et `unique` sont **informatifs, non enforced**. Seul `not_null` est réellement enforced par Snowflake. |
| `data_tests` (`not_null`, unicité) | L'**intégrité réelle des données** : c'est la seule vérification effective de l'unicité et de la non-nullité de la PK. | — |

> À retenir : la contrainte `primary_key` ne suffit **pas** à garantir l'unicité sur Snowflake. Ce sont les `data_tests` qui l'assurent — d'où leur caractère obligatoire en complément de la contrainte.

> Avec `contract.enforced: true`, dbt impose de renseigner le `data_type` de chaque colonne déclarée, et fait échouer le build si les colonnes ou les types produits divergent de la déclaration.

---

## 3. PK simple (mono-colonne)

Tout se déclare **au niveau de la colonne** : la contrainte et les deux tests.

```yaml
models:
  - name: fct_decision_octroi
    description: "{{ doc('fct_decision_octroi__description') }}"
    config:
      contract:
        enforced: true
    columns:
      - name: iddos
        data_type: character varying(32)
        description: "{{ doc('octroi__iddos') }}"
        constraints:
          - type: primary_key
        data_tests:
          - not_null
          - unique
        meta:
          data_type: ident_doss
```

---

## 4. PK composite (multi-colonnes)

La déclaration **se scinde** : la contrainte et le test d'unicité passent au niveau **modèle**, le `not_null` reste **par colonne**.

```yaml
models:
  - name: fct_exposition_garantie
    description: "{{ doc('fct_exposition_garantie__description') }}"
    config:
      contract:
        enforced: true
    constraints:
      - type: primary_key
        columns:
          - iddos
          - idgar
    data_tests:
      - dbt_utils.unique_combination_of_columns:
          combination_of_columns:
            - iddos
            - idgar
    columns:
      - name: iddos
        data_type: character varying(32)
        description: "{{ doc('octroi__iddos') }}"
        data_tests:
          - not_null
        meta:
          data_type: ident_doss
      - name: idgar
        data_type: character varying(32)
        description: "{{ doc('garantie__idgar') }}"
        data_tests:
          - not_null
```

Deux différences structurantes avec la PK simple :

- la **contrainte `primary_key`** se déclare au niveau modèle (`models[].constraints`), avec la liste **ordonnée** des colonnes ;
- l'**unicité** se vérifie sur la **combinaison** des colonnes via `dbt_utils.unique_combination_of_columns`, jamais par un `unique` sur chaque colonne prise isolément ;
- le **`not_null`** reste un test par colonne (chaque composante de la PK doit être non nulle).

> **Piège fréquent** : transcrire mécaniquement les tests `unique` + `not_null` d'une PK simple vers une composite produit un `unique` par colonne. C'est **sémantiquement faux** — une colonne de la PK n'a pas à être unique individuellement — et cela laisse passer des doublons de combinaison. Utiliser impérativement le test sur la combinaison.

> **Dépendance** : `dbt_utils.unique_combination_of_columns` requiert le package `dbt_utils` dans `packages.yml`.

---

## 5. Contrôle CI

La CI vérifie, pour **chaque mart**, que :

- `config.contract.enforced` vaut `true` ;
- une contrainte `primary_key` est déclarée (au niveau colonne ou modèle) ;
- la PK porte les tests d'intégrité attendus : `not_null` sur chaque colonne de la PK, et l'unicité (`unique` en mono-colonne, `dbt_utils.unique_combination_of_columns` en composite).

Un mart ne respectant pas ces obligations fait **échouer la pipeline**. La règle est donc bloquante au merge, pas seulement documentaire.

---

## 6. Erreurs fréquentes

| Symptôme | Cause probable |
|---|---|
| Build qui échoue sur un mart avec contrat | Une colonne déclarée sans `data_type`, ou un écart entre colonnes/types déclarés et produits. |
| Doublons non détectés sur une PK composite | Test `unique` posé par colonne au lieu de `dbt_utils.unique_combination_of_columns` sur la combinaison. |
| CI en échec « PK manquante » | Contrainte `primary_key` absente, ou déclarée au niveau colonne alors que la PK est composite (doit être au niveau modèle). |
| `dbt_utils` introuvable | Package non déclaré dans `packages.yml` ou `dbt deps` non exécuté. |