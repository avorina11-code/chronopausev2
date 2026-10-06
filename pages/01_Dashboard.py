"""Dashboard : KPI, distribution horaire, types de pause, simultanéité, aperçu des dépassements."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import streamlit as st

from src import calculations as calc
from src import ui
from src import visualizations as viz
from src.config import fmt_duration, fmt_int, fmt_ms, slot_label

ctx = ui.get_context("Dashboard", "📊", "Vue d'ensemble opérationnelle — tous les indicateurs suivent les filtres de la barre latérale")
v, k, rules = ctx.view, ctx.kpis, ctx.rules
st.caption("Statuts inclus : " + (", ".join(v.flt.types) if v.flt.types else "aucun") +
           f" · Règles appliquées à : {', '.join(rules.types_regles) or 'aucun statut'}")
ui.kpi_grid(k, rules)

if k["n_agents"] == 0 or v.slots.empty:
    st.warning("Aucune donnée pour les filtres sélectionnés.")
    st.stop()

bs = calc.by_slot(v)
st.plotly_chart(viz.fig_distribution(bs, "blocs_entames", "Distribution des pauses par créneau (pauses entamées)"), use_container_width=True)

a, b = st.columns(2)
bt = calc.by_type(v)
a.plotly_chart(viz.fig_by_type(bt, ctx.colors), use_container_width=True)
b.plotly_chart(viz.fig_simultaneity(ctx.sim, rules.simultaneite_max_pct), use_container_width=True)
if len(ctx.sim):
    base = {"presents": "agents connectés (Arrivée-Départ)", "fichier": "agents du fichier", "rh": "effectif RH"}[ctx.sim.attrs.get("base", "fichier")]
    b.caption(f"Effectif de référence : {base}. Barres grisées : créneaux sous l'effectif minimum ({rules.effectif_min_simult}), exclus du pic.")

st.markdown("#### Agents à surveiller")
ov = calc.overage_by_agent(v)
ov = ov[ov["Dépassement (min)"] > 0].head(10)
if ov.empty:
    st.success("Aucun dépassement sur la sélection avec les règles configurées.")
else:
    st.caption("Classement indicatif selon les règles configurées — ce n'est pas une sanction automatique.")
    ui.display_df(ov[["Agent", "Login", "Nb pauses", "Temps autorisé (min)", "Temps réel (min)", "Dépassement (min)", "Motifs"]])
    st.page_link("pages/04_Depassements.py", label="Voir l'analyse complète des dépassements", icon="⚠️")
