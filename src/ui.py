"""Composants Streamlit communs : mise en page, sidebar (filtres + règles), contexte de page, KPI."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd
import streamlit as st

from . import calculations as calc
from .config import Rules, fmt_duration, fmt_int, slot_label
from .models import ParsedPauses, RHData
from .rh_matching import match_agents
from .visualizations import type_colors

CSS = """
<style>
.block-container {padding-top: 1.4rem; padding-bottom: 2rem;}
.pa-title {font-size: 1.55rem; font-weight: 700; letter-spacing: .04em; color:#1B2430; margin:0}
.pa-sub {color:#6B778C; margin: 0 0 .8rem 0; font-size:.95rem}
.pa-badge {display:inline-block; padding:2px 10px; border-radius:12px; font-size:.78rem; font-weight:600;
           background:#EAF1FE; color:#1F6FEB; margin-right:6px}
.pa-badge.warn {background:#FFF4E0; color:#B25E00}
.pa-badge.err  {background:#FDE8EC; color:#D1344B}
.pa-note {color:#6B778C; font-size:.82rem}
div[data-testid="stMetricValue"] {font-size: 1.7rem;}
</style>
"""

FILTER_PREFIX, RULE_PREFIX = "f_", "r_"
BASE_LABELS = {"presents": "Agents connectés sur le créneau (Arrivée-Départ)", "fichier": "Agents du fichier",
               "rh": "Effectif de la base RH"}
MESURE_LABELS = {"moyenne": "Nombre moyen simultané (durée ÷ 30 min)", "distincts": "Agents distincts (≥ 1 s)"}


@dataclass
class Ctx:
    parsed: ParsedPauses
    rh: RHData | None
    match: pd.DataFrame
    ds: calc.Dataset
    view: calc.View
    rules: Rules
    sim: pd.DataFrame
    kpis: dict
    colors: dict


def page_setup(title: str, icon: str = "⏱️") -> None:
    st.set_page_config(page_title=f"Pause Analyzer – {title}", page_icon=icon, layout="wide")
    st.markdown(CSS, unsafe_allow_html=True)


def header(title: str, subtitle: str = "") -> None:
    st.markdown(f"<p class='pa-title'>PAUSE ANALYZER · {title}</p><p class='pa-sub'>{subtitle}</p>", unsafe_allow_html=True)


def reset_widget_state() -> None:
    for k in list(st.session_state.keys()):
        if k.startswith((FILTER_PREFIX, RULE_PREFIX)):
            del st.session_state[k]


def _persist(keys) -> None:
    """Contournement officiel : conserve l'état des widgets quand on change de page."""
    for k in keys:
        if k in st.session_state:
            st.session_state[k] = st.session_state[k]


def metric(col, label, value, help=None, delta=None, delta_color="off") -> None:
    try:
        col.metric(label, value, delta=delta, delta_color=delta_color, help=help, border=True)
    except TypeError:                                   # anciennes versions de Streamlit
        col.metric(label, value, delta=delta, help=help)


def require_data() -> None:
    if "parsed" not in st.session_state:
        st.info("Aucun fichier chargé. Commencez par l'accueil pour importer le fichier de pauses (et la base RH).")
        st.page_link("app.py", label="➜ Aller à l'import des fichiers", icon="📥")
        st.stop()


def get_context(title: str, icon: str = "⏱️", subtitle: str = "") -> Ctx:
    page_setup(title, icon)
    require_data()
    parsed: ParsedPauses = st.session_state["parsed"]
    rh: RHData | None = st.session_state.get("rh")
    sb = st.sidebar
    _persist([k for k in st.session_state if k.startswith((FILTER_PREFIX, RULE_PREFIX))])

    # ── rapprochement RH (option : suggestions par nom)
    use_sugg = False
    if rh is not None and rh.df is not None:
        use_sugg = sb.toggle("Utiliser les suggestions de rapprochement par nom", key=FILTER_PREFIX + "sugg", value=False,
                             help="Désactivé par défaut : une suggestion par nom n'est qu'une hypothèse à confirmer.")
    match = match_agents(parsed.agents, rh, use_sugg)
    directory = calc.agent_directory(parsed, match)

    # ── filtres
    sb.markdown("### Filtres")
    dates = sorted(directory["date"].dropna().unique())
    types = sorted(parsed.slots["type_pause"].astype(str).unique())
    st.session_state.setdefault(FILTER_PREFIX + "dates", dates)
    st.session_state.setdefault(FILTER_PREFIX + "types", types)
    f_dates = sb.multiselect("Date", dates, key=FILTER_PREFIX + "dates", format_func=lambda d: d.strftime("%d/%m/%Y"))
    has_team = directory["equipe"].fillna("").astype(str).str.len().gt(0).any()
    has_sup = directory["superviseur"].fillna("").astype(str).str.len().gt(0).any()
    f_eq = sb.multiselect("Équipe", sorted(directory["equipe"].replace("", np.nan).dropna().unique()),
                          key=FILTER_PREFIX + "eq", placeholder="Toutes") if has_team else []
    f_sup = sb.multiselect("Superviseur", sorted(directory["superviseur"].replace("", np.nan).dropna().unique()),
                           key=FILTER_PREFIX + "sup", placeholder="Tous") if has_sup else []
    if not (has_team or has_sup):
        sb.caption("Équipe / Superviseur : indisponibles (absents de la base RH fournie).")
    labels = dict(zip(directory["login"], directory["agent_label"]))
    f_ag = sb.multiselect("Agent", sorted(labels, key=lambda l: labels[l]), key=FILTER_PREFIX + "ag",
                          format_func=lambda l: labels[l], placeholder="Tous")
    f_types = sb.multiselect("Type de pause", types, key=FILTER_PREFIX + "types")
    opts = [slot_label(m) for m in range(0, 1441, 30)]
    st.session_state.setdefault(FILTER_PREFIX + "plage", ("00:00", "24:00"))
    plage = sb.select_slider("Plage horaire", options=opts, key=FILTER_PREFIX + "plage")
    f_stat = sb.radio("Statut agent", ["Tous", "En dépassement", "Normal"], key=FILTER_PREFIX + "stat", horizontal=True)

    # ── règles (paramètres utilisateur, jamais « officiels »)
    with sb.expander("⚙️ Règles de pause (paramétrables)", expanded=False):
        st.caption("Valeurs par défaut = **exemples** de votre cahier des charges, à valider. 0 = règle désactivée.")
        default_types = list(calc.default_rule_types(types))
        st.session_state.setdefault(RULE_PREFIX + "types", default_types)
        r_types = st.multiselect("Statuts soumis aux règles", types, key=RULE_PREFIX + "types",
                                 help="Les autres statuts (Formation, Coaching, Brief…) restent affichés « Hors règle ».")
        r_cum = st.number_input("Durée max cumulée / agent / jour (min)", 0.0, 1440.0, 30.0, 1.0, key=RULE_PREFIX + "cum")
        r_nb = st.number_input("Nombre max de pauses / agent / jour", 0, 200, 8, 1, key=RULE_PREFIX + "nb")
        r_one = st.number_input("Durée max d'une pause (min)", 0.0, 1440.0, 0.0, 1.0, key=RULE_PREFIX + "one")
        r_sim = st.number_input("Simultanéité max (%)", 0.0, 100.0, 15.0, 1.0, key=RULE_PREFIX + "sim")
        r_base = st.selectbox("Effectif de référence (simultanéité)", list(BASE_LABELS), format_func=BASE_LABELS.get,
                              key=RULE_PREFIX + "base")
        r_mes = st.selectbox("Mesure de simultanéité", list(MESURE_LABELS), format_func=MESURE_LABELS.get,
                             key=RULE_PREFIX + "mes")
        r_eff = st.number_input("Effectif min. pour retenir un créneau", 1, 500, 5, 1, key=RULE_PREFIX + "eff",
                                help="Évite un « pic » artificiel quand très peu d'agents sont connectés.")
        r_micro = st.number_input("Ignorer dans le décompte les pauses < N secondes", 0, 3600, 0, 5, key=RULE_PREFIX + "micro")
    rules = Rules(tuple(r_types), r_cum, int(r_nb), r_one, r_sim, r_base, r_mes, int(r_eff), int(r_micro))

    rh_count = int((rh.df["login"] != "").sum()) if rh is not None and rh.df is not None else None
    ds = calc.build_dataset(parsed, match, rules, rh_count)
    def parse_time_to_minutes(p):
    if not p or not isinstance(p, str):
        return 0
    parts = p.strip().split(":")
    if len(parts) == 2 and parts[0].isdigit() and parts[1].isdigit():
        return int(parts[0]) * 60 + int(parts[1])
    return 0

if isinstance(plage, (list, tuple)) and len(plage) == 2:
    lo, hi = parse_time_to_minutes(plage[0]), parse_time_to_minutes(plage[1])
else:
    lo, hi = 0, 1439  # Valeur par défaut (00:00 à 23:59) si la plage est invalide
    view = calc.apply_filters(ds, calc.Filters(tuple(f_dates), tuple(f_eq), tuple(f_sup), tuple(f_ag),
                                               tuple(f_types), (lo, hi), f_stat))
    sim = calc.simultaneity(view, rules, rh_count)
    kp = calc.compute_kpis(view, rules, sim)

    header(title, subtitle)
    _banners(parsed, match, rh)
    return Ctx(parsed, rh, match, ds, view, rules, sim, kp, type_colors(types))


def _banners(parsed: ParsedPauses, match: pd.DataFrame, rh: RHData | None) -> None:
    chips = []
    if rh is None or rh.df is None:
        chips.append("<span class='pa-badge warn'>Base RH non chargée : noms/équipes indisponibles</span>")
    else:
        n_un = int((~match["statut_rapprochement"].isin(["Rapproché (login)"])).sum())
        if n_un:
            chips.append(f"<span class='pa-badge warn'>⚠ {n_un} agent(s) non rapproché(s) de la RH "
                         f"({n_un / len(match) * 100:.0f} %)</span>")
        else:
            chips.append("<span class='pa-badge'>✓ 100 % des agents rapprochés avec la RH</span>")
    n_err = int((parsed.issues["severite"] == "Erreur").sum()) if len(parsed.issues) else 0
    if n_err:
        chips.append(f"<span class='pa-badge err'>{n_err} erreur(s) de données — voir « Qualité des données »</span>")
    st.markdown(" ".join(chips), unsafe_allow_html=True)


def kpi_grid(k: dict, rules: Rules) -> None:
    c = st.columns(4)
    metric(c[0], "Agents analysés", fmt_int(k["n_agents"]))
    metric(c[1], "Temps de pause total", fmt_duration(k["total_s"]), help="Somme des durées observées sur les statuts et créneaux filtrés.")
    metric(c[2], "Temps moyen de pause", f"{fmt_duration(k['avg_s'])} / agent" if k["n_agents"] else "—")
    metric(c[3], "Dépassement total", fmt_duration(k["exces_s"]),
           help="Durée cumulée au-delà de la limite configurée, sur les statuts soumis aux règles.")
    c = st.columns(4)
    metric(c[0], "Agents en dépassement", f"{fmt_int(k['n_dep'])} agents",
           delta=f"{k['pct_dep']:.0f} % des agents" if k["n_agents"] else None, delta_color="off",
           help="Au moins une règle activée dépassée (durée cumulée, durée d'une pause, nombre de pauses).")
    metric(c[1], "Nombre de pauses", fmt_int(k["n_pauses"]),
           help="Blocs de créneaux consécutifs d'un même statut : minimum du nombre réel de pauses.")
    metric(c[2], "Pic de simultanéité", f"{k['peak_pct']:.0f} %" if k["peak_pct"] == k["peak_pct"] else "—",
           delta=f"≈ {k['peak_agents']:.1f} agents" if k["peak_agents"] == k["peak_agents"] else None, delta_color="off")
    metric(c[3], "Heure du pic", k["peak_hour"],
           delta=f"{k['n_periodes_dep']} créneau(x) > limite" if rules.simultaneite_max_pct > 0 else None, delta_color="off")


def display_df(df: pd.DataFrame, **kw) -> None:
    st.dataframe(df, use_container_width=True, hide_index=True, **kw)
