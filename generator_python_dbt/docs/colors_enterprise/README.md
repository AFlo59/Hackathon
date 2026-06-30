# Thème couleurs — Design System Sofinco v2.1

Référence visuelle complète : [`design_sofinco.html`](design_sofinco.html).
Implémentation : [`src/theme.py`](../../src/theme.py) + [`.streamlit/config.toml`](../../.streamlit/config.toml).

## Cœur de marque (rôles exclusifs)

| Token            | Hex        | Rôle                                    |
|------------------|------------|-----------------------------------------|
| Principale       | `#009597`  | Accents dominants, KPI, titres, actions |
| Ardoise          | `#666E8A`  | Texte secondaire, légendes              |
| Marine           | `#071621`  | Corps de texte par défaut               |
| Sarcelle foncé   | `#006466`  | Tags UPPERCASE, labels (ponctuel)       |

## Accents sémantiques (un rôle unique chacun)

| Token   | Hex       | Rôle                          |
|---------|-----------|-------------------------------|
| Vert    | `#2D8E57` | Positif, validé, succès       |
| Bleu    | `#3A7CC3` | Information, technique         |
| Violet  | `#7030A0` | Stratégique, transverse       |
| Orange  | `#E07A2F` | Attention, vigilance (PII ⚠️) |
| Corail  | `#F47682` | Alerte forte, bloqueur        |
| Jaune   | `#FFC000` | Mise en avant « à retenir »   |

## Mapping Streamlit (`.streamlit/config.toml`)

| Paramètre Streamlit        | Token Sofinco        | Hex       |
|----------------------------|----------------------|-----------|
| `primaryColor`             | Principale           | `#009597` |
| `backgroundColor`          | Blanc                | `#FFFFFF` |
| `secondaryBackgroundColor` | Blanc cassé          | `#F7F8FA` |
| `textColor`                | Marine               | `#071621` |
| `font`                     | Open Sans (sans serif) | —       |

`src/theme.inject_theme()` complète ce thème natif : import de la police
**Open Sans**, titres en teal, boutons primaires teal → sarcelle foncé au survol,
onglets actifs en teal.

## Règles à respecter

- **Police** : Open Sans exclusivement.
- **Jamais** : `#000000` (→ `#071621`), `#FF0000` (→ corail), `#0000FF` (→ bleu).
- Les fonds pastels sont des **conteneurs neutres**, jamais porteurs de sens.
- Un accent sémantique = un seul rôle (ne pas réutiliser l'orange pour autre
  chose que l'attention/PII, etc.).
