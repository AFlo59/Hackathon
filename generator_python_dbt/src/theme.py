"""Thème visuel Sofinco pour l'application Streamlit.

Dérivé du *Design System Sofinco v2.1*
(``docs/colors_enterprise/design_sofinco.html``).

Règles de marque :

* Police **Open Sans** exclusivement.
* Couleur principale (teal) ``#009597`` pour accents, titres, actions.
* Corps de texte en marine ``#071621`` (jamais ``#000000``).
* Accents sémantiques à rôle unique (succès, info, attention, alerte).
* Couleurs interdites : ``#000000``, ``#FF0000``, ``#0000FF``.
"""

from __future__ import annotations

# --------------------------------------------------------------------------- #
# Tokens couleur — cœur de marque
# --------------------------------------------------------------------------- #
PRINCIPALE = "#009597"        # accents dominants, KPI, titres
ARDOISE = "#666E8A"           # texte secondaire, légendes
MARINE = "#071621"            # corps de texte par défaut
SARCELLE_FONCE = "#006466"    # tags UPPERCASE, labels

# Neutres
BLANC = "#FFFFFF"
BLANC_CASSE = "#F7F8FA"
BLANC_CASSE_2 = "#F5F5F5"
GRIS_CLAIR = "#E8E8E8"
GRIS_NEUTRE = "#C0C4CC"

# Accents sémantiques — un rôle unique chacun
VERT = "#2D8E57"              # succès, validé
BLEU = "#3A7CC3"             # information, technique
VIOLET = "#7030A0"           # stratégique, transverse
ORANGE = "#E07A2F"           # attention, vigilance
CORAIL = "#F47682"           # alerte forte, bloqueur
JAUNE = "#FFC000"            # mise en avant ponctuelle

# Fonds pastels (conteneurs neutres, jamais sémantiques)
PASTEL_SARCELLE = "#EBF7F7"
PASTEL_ORANGE = "#FDE8D0"
PASTEL_ROSE = "#F6E7E6"
PASTEL_VERT = "#E5F2D0"

# Police de marque
POLICE = "'Open Sans', sans-serif"


def inject_theme() -> None:
    """Injecte la police Open Sans et les surcharges CSS Sofinco.

    À appeler une fois, juste après ``st.set_page_config``.
    """
    import streamlit as st

    css = f"""
    <style>
    @import url('https://fonts.googleapis.com/css2?family=Open+Sans:ital,wght@0,400;0,600;0,700;0,800&display=swap');

    html, body, [class*="css"], .stMarkdown, .stApp {{
        font-family: {POLICE};
        color: {MARINE};
    }}

    /* Titres en teal de marque */
    h1, h2, h3 {{ color: {PRINCIPALE}; font-weight: 700; }}

    /* Boutons primaires */
    .stButton > button, .stDownloadButton > button, .stFormSubmitButton > button {{
        background: {PRINCIPALE};
        color: {BLANC};
        border: none;
        border-radius: 6px;
        font-weight: 600;
        transition: background 0.2s ease;
    }}
    .stButton > button:hover, .stDownloadButton > button:hover,
    .stFormSubmitButton > button:hover {{
        background: {SARCELLE_FONCE};
        color: {BLANC};
    }}

    /* Onglets actifs */
    .stTabs [aria-selected="true"] {{ color: {PRINCIPALE} !important; }}

    /* Barre latérale */
    section[data-testid="stSidebar"] {{ background: {BLANC_CASSE}; }}

    /* Liens */
    a {{ color: {PRINCIPALE}; }}
    a:hover {{ color: {SARCELLE_FONCE}; }}
    </style>
    """
    st.markdown(css, unsafe_allow_html=True)


def pii_badge() -> str:
    """Petit badge HTML « PII » (fond orange pastel) pour l'UI."""
    return (
        f"<span style='background:{PASTEL_ORANGE};color:{ORANGE};"
        "font-size:0.7rem;font-weight:700;padding:2px 8px;border-radius:3px;"
        "text-transform:uppercase;letter-spacing:0.5px;'>⚠️ PII</span>"
    )
