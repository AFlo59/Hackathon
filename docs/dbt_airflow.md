# Orchestration dbt avec Airflow (Cosmos)

Ce document décrit comment dbt est orchestré dans Airflow via **Astronomer Cosmos** : le contrat du module `configs/`, les conventions d'écriture d'un DAG, et un tour guidé des DAGs d'exemple. Il s'articule avec les autres guides dbt :

- ce qui est exécuté (modèles, couches) est défini dans [`dbt_modeling.md`](dbt_modeling.md) ; la stratégie de tests dans [`dbt_tests.md`](dbt_tests.md) ;
- le workflow de dev, la CI GitLab et la promotion entre environnements Snowflake relèvent de [`dbt_workflow.md`](dbt_workflow.md). Ici, on traite uniquement la **mécanique d'orchestration**.

Emplacement : les DAGs vivent dans `dags/` au sein du projet dbt ; les exemples sont dans `dags/examples/`.

-----

## 1. Principe : Cosmos

Cosmos lit le projet dbt et **rend chaque modèle (et ses tests) comme une tâche Airflow**. On gagne l'observabilité native d'Airflow : retry par modèle, drill-down sur la tâche en échec, lineage, sans réécrire la logique dbt.

Deux points d'entrée pour le rendu :

- **`DbtDag`** — un DAG entièrement constitué de tâches dbt. Simple, mais on ne peut rien y ajouter d'autre.
- **`DbtTaskGroup`** — un *task group* dbt inséré dans un `DAG` Airflow normal, ce qui permet de mêler des tâches non-dbt (init, capteurs, notifications…).

> **Convention du projet** : on écrit un `DAG` qui enveloppe un `DbtTaskGroup` (voir §3). `DbtDag` reste une variante acceptable pour un DAG 100 % dbt sans étape annexe.

-----

## 2. Le module `configs/` (contrat)

La configuration est centralisée dans le package `configs/` du projet dbt et importée par chaque DAG. **On la considère comme une boîte noire stable** : ce guide documente ce que chaque module expose, pas son implémentation.

|Module           |Expose                                           |Rôle                                                                                    |
|-----------------|-------------------------------------------------|----------------------------------------------------------------------------------------|
|`airflow_config` |`AIRFLOW_CONFIG` (alias `AC`)                    |`AC.dag_prefix` (préfixe des `dag_id`), `AC.dag_config()` (les `default_args`)          |
|`config`         |`env_vars`, `dbt_profiles_dir`, `dbt_project_dir`|Chemins du projet dbt et variables d'environnement injectées                            |
|`hostname_config`|`dbt_target`                                     |Résout la **cible dbt** (`target` de `profiles.yml`) selon la machine et l'environnement|
|`git_info`       |`dag_tags`                                       |Tags appliqués au DAG, dérivés des infos Git                                            |

Point clé : `dbt_target` est résolu **selon la machine et l'environnement**. C'est ainsi que le même DAG cible automatiquement le bon `target` Snowflake selon le contexte d'exécution, sans cible codée en dur. La *politique* de promotion entre environnements, elle, relève de [`dbt_workflow.md`](dbt_workflow.md).

-----

## 3. Anatomie d'un DAG (template canonique)

```python
from datetime import datetime
from os import path

from airflow import DAG
from airflow.operators.empty import EmptyOperator
from cosmos import ProfileConfig, ProjectConfig, RenderConfig, DbtTaskGroup

# Config centralisée (cf. §2)
from {{ cookiecutter.project_source_directory }}.configs.airflow_config import AIRFLOW_CONFIG as AC
from {{ cookiecutter.project_source_directory }}.configs.git_info import dag_tags
from {{ cookiecutter.project_source_directory }}.configs.config import env_vars, dbt_profiles_dir, dbt_project_dir
from {{ cookiecutter.project_source_directory }}.configs.hostname_config import dbt_target

# Convention : le dag_id est dérivé du nom du fichier
dag_name = path.basename(__file__)[:-3]

profile_config = ProfileConfig(
    profiles_yml_filepath=f"{dbt_profiles_dir}/profiles.yml",
    profile_name="ceos",
    target_name=dbt_target,            # cible Snowflake résolue selon la machine et l'environnement
)

project_config = ProjectConfig(
    project_name="{{ cookiecutter.project_source_directory }}",
    dbt_project_path=dbt_project_dir,
    env_vars=env_vars,
    install_dbt_deps=True,             # dbt deps au parsing ET à l'exécution
)

with DAG(
    dag_id=f"{AC.dag_prefix}-{dag_name}",   # préfixe + nom de fichier
    start_date=datetime(2025, 4, 7),
    schedule=None,
    catchup=False,
    max_active_tasks=10,
    default_args=AC.dag_config(),
    tags=dag_tags,
    params={},
) as dag:

    init = EmptyOperator(task_id="init")

    run = DbtTaskGroup(
        group_id="model_decision_octroi",
        project_config=project_config,
        profile_config=profile_config,
        render_config=RenderConfig(
            select=["+tag:octroi"],                # le + embarque l'amont
            exclude=["fct_decision_octroi_incr"],
        ),
    )

    init >> run

    dag.validate()

if __name__ == "__main__":
    dag.test()
```

Les conventions à respecter, lisibles dans ce template :

- **`dag_id` dérivé du fichier** : `path.basename(__file__)[:-3]`, préfixé par `AC.dag_prefix`. On ne code jamais le `dag_id` en dur — renommer le fichier suffit.
- **Profil** : `profiles_yml_filepath` pointant vers le `profiles.yml` du projet, `target_name=dbt_target` (résolu selon la machine et l'environnement). Jamais de cible en dur.
- **Patron `DAG` + `DbtTaskGroup`** avec une tâche `init` (`EmptyOperator`), chaînés `init >> run`. Le point d'ancrage pour brancher d'éventuelles tâches annexes.
- **Deps** : `install_dbt_deps=True` dans `ProjectConfig` couvre `dbt deps` au parsing **et** à l'exécution (c'est aussi la valeur par défaut). On ne le déclare qu'à un seul endroit — pas dans `operator_args` ni `RenderConfig`. À noter : du fait du découpage par modèle, `dbt deps` s'exécute une fois par tâche.
- **Validation** : `dag.validate()` à la construction du DAG. Pour le **test local**, la voie documentée est le CLI du projet (voir ci-dessous).

> `ExecutionConfig` n'est pas passé ici : Cosmos exécute alors dbt en mode `LOCAL` (dans l'environnement Airflow). On ne l'ajoute que pour changer de mode (venv, conteneur…).

### Test local via le CLI

Le test local d'un DAG se fait via une commande CLI. Deux pièces :

Un `cli.py` à la racine du projet dbt, qui déclare une commande par DAG. La commande importe le DAG et appelle son `.test()` :

```python
import click

@click.group()
def cli():
    """
    AIRFLOW DAGS FOR LOCAL TESTS
    ****************************
    """

@cli.command("dbt_taskGroup_octroi")
def test_dbt_taskGroup_octroi():
    from {{ cookiecutter.project_source_directory }}.dags.dbt_taskGroup_octroi import dbt_taskGroup_octroi
    dbt_taskGroup_octroi.test(
        run_conf={
            # Paramètres du DAG pour surcharger les valeurs par défaut
        }
    )
```

Un lanceur `cli` à la racine du projet **global** (le dossier parent du projet dbt), qui appelle ce module :

```bash
./venv/bin/python -m {{ cookiecutter.project_source_directory }}.cli $@
```

Le test local s'exécute alors depuis la racine du projet global :

```bash
./cli dbt_taskGroup_octroi
```

Ajouter un DAG testable en local = déclarer une nouvelle commande dans `cli.py`.

-----

## 4. Sélection des modèles

Le projet dbt est monolithique ; chaque DAG cible un sous-ensemble via `select` / `exclude` dans `RenderConfig`, avec la syntaxe des **sélecteurs de graphe dbt** :

- `tag:octroi` — les modèles portant le tag `octroi` ;
- `+tag:octroi` — y compris leur **amont** (le `+` en préfixe) ; `tag:octroi+` pour l'aval ;
- `path:models/staging` — par chemin ;
- `exclude=["fct_decision_octroi_incr"]` — retire des modèles du périmètre.

Le découpage par **tag** est le mécanisme retenu pour partitionner le projet en DAGs par domaine.

`load_method` (dans `RenderConfig`) détermine comment Cosmos lit le projet :

- `LoadMode.DBT_LS` — exécute `dbt ls` pour parser (filtrage par tag rapide ; nécessite dbt et le parsing) ;
- `LoadMode.DBT_MANIFEST` — réutilise un `manifest.json` déjà produit (plus rapide, pas d'invocation dbt) ;
- `LoadMode.AUTOMATIC` — choisit selon ce qui est disponible.

-----

## 5. Modes d'exécution d'un modèle : Cosmos vs BashOperator

- **Opérateurs Cosmos** (via `DbtTaskGroup` / `DbtDag`) : chaque modèle devient une tâche Airflow native → granularité, retry par modèle, lineage. **C'est le mode par défaut**, à privilégier.
- **`BashOperator`** : un `dbt run` brut dans une seule tâche. Échappatoire pour un cas que Cosmos ne rend pas proprement, ou un one-shot. On y perd la granularité par modèle.

Les exemples illustrent les deux approches en version générique et en version concrète sur un modèle réel (`stg_so_preconf_mdroc__dmde_octroi`).

-----

## 6. Paramètres de comportement

- **`test_behavior`** (`TestBehavior`, dans `RenderConfig`) : pilote *quand* les tests s'exécutent.
  - `AFTER_EACH` (défaut) — chaque modèle est suivi de ses tests.
  - `AFTER_ALL` — tous les modèles d'abord, puis tous les tests ; ils ne tournent que si tous les modèles ont réussi.
  - autres : `NONE`, `BUILD`.
- **`full_refresh`** (`operator_args={"full_refresh": ...}`) : pour les modèles incrémentaux.
  - `False` — les nouvelles données sont ajoutées sans suppression (comportement incrémental).
  - `True` — la table est écrasée et reconstruite.

-----

## 7. Dépendances inter-DAG

- **`TriggerDagRunOperator`** (exemple `dbt_trigger`) — un DAG en **déclenche** un autre (push). **Approche privilégiée** dans le projet.
- **Sensor** (exemple `dbt_sensor`) — un DAG **attend** la fin d'un autre (pull). Fonctionne, mais occupe un slot d'exécution pendant l'attente ; à réserver aux cas où le trigger ne suffit pas.

-----

## 8. Utilitaires

- **`dbt_debug`** — vérifie la connexion dbt (`dbt debug`).
- **`dbt_seed`** — charge des fichiers seeds en tables sur Snowflake (`dbt seed`). **Interdit pour un usage industriel en production** : en production, les données sont déposées dans Snowflake par un outil *File Transfer*, puis intégrées en tant que **source**. En développement, l'usage de seeds est **toléré** pour accélérer l'implémentation, mais doit être **régularisé au moment de la mise en production**.

-----

## 9. Index de référence des DAGs d'exemple

`dags/examples/` :

|Fichier                               |DAG                                |Thème       |Description                                                 |
|--------------------------------------|-----------------------------------|------------|------------------------------------------------------------|
|`dbt_dag.py`                          |`dbt_dag`                          |Rendu       |Construction d'un `DbtDag`                                  |
|`dbt_taskGroup.py`                    |`dbt_taskGroup`                    |Rendu       |`DbtTaskGroup` d'exécution générique                        |
|`dbt_taskGroup_dmde_octroi.py`        |`dbt_taskGroup_dmde_octroi`        |Rendu       |`DbtTaskGroup` sur `stg_so_preconf_mdroc__dmde_octroi`      |
|`dbt_stagings.py`                     |`dbt_stagings`                     |Sélection   |Exécute les modèles de staging                              |
|`dbt_loadMethod.py`                   |`dbt_loadMethod`                   |Sélection   |`load_method=LoadMode.DBT_LS` : filtrage rapide par tag     |
|`dbt_taskGroup_exclude_dmde_octroi.py`|`dbt_taskGroup_exclude_dmde_octroi`|Sélection   |Exclusion de modèles du périmètre                           |
|`dbt_runOperator.py`                  |`dbt_runOperator`                  |Exécution   |`dbt run` générique (opérateur Cosmos)                      |
|`dbt_runOperator_dmde_octroi.py`      |`dbt_runOperator_dmde_octroi`      |Exécution   |Idem sur `stg_so_preconf_mdroc__dmde_octroi`                |
|`dbt_run_bashOperator.py`             |`dbt_run_bashOperator`             |Exécution   |`BashOperator` dbt générique                                |
|`dbt_run_bashOperator_dmde_octroi.py` |`dbt_run_bashOperator_dmde_octroi` |Exécution   |`BashOperator` sur `stg_so_preconf_mdroc__dmde_octroi`      |
|`dbt_testBehavior.py`                 |`dbt_testBehavior`                 |Comportement|Démonstration de `test_behavior` (ex. `AFTER_ALL`)          |
|`dbt_fullRefresh.py`                  |`dbt_fullRefresh`                  |Comportement|`full_refresh` False (incrément) vs True (reconstruction)   |
|`dbt_trigger.py`                      |`dbt_trigger`                      |Inter-DAG   |Déclenche un autre DAG (ici `dbt_stagings`)                 |
|`dbt_sensor.py`                       |`dbt_sensor`                       |Inter-DAG   |Attend l'exécution d'un autre DAG (privilégier les triggers)|
|`dbt_seed.py`                         |`dbt_seed`                         |Utilitaire  |`dbt seed` — toléré en dev, interdit en prod (cf. §8)       |
|`dbt_debug.py`                        |`dbt_debug`                        |Utilitaire  |`dbt debug` — vérifie la connexion                          |

-----

## Renvois

- Workflow de dev, CI GitLab, promotion entre environnements Snowflake → [`dbt_workflow.md`](dbt_workflow.md)
- Couches et modèles exécutés → [`dbt_modeling.md`](dbt_modeling.md)
- Stratégie de tests → [`dbt_tests.md`](dbt_tests.md)