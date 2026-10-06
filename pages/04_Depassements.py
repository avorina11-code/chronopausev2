"""Dépassements : par agent, par jour, par type, par tranche horaire."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import streamlit as st

from src import calculations as calc
from src import ui
from src import visualizations as viz
from src.config import fmt_duration, fmt_int, fmt_ms, slot_label

ctx = ui.get_context("Dépassements", "⚠️", "Écarts par rapport aux règles configurées (indicatif — pas une sanction automatique)")
v, rules, k = ctx.view, ctx.rules, ctx.kpis
if not rules.types_regles:
    st.warning("Aucun statut n'est soumis aux règles : sélectionnez-en dans « ⚙️ Règles de pause » (barre latérale).")
active = [lab for lab, on in [(f"durée cumulée > {rules.duree_max_cumulee_min:g} min", rules.duree_max_cumulee_min > 0),
                              (f"> {rules.nb_max_pauses} pauses", rules.nb_max_pauses > 0),
                              (f"pause > {rules.duree_max_par_pause_min:g} min", rules.duree_max_par_pause_min > 0)] if on]
st.caption("Règles actives : " + (" · ".join(active) or "aucune") + " — évaluées sur la journée complète de chaque agent.")

c = st.columns(4)
ui.metric(c[0], "% d'agents en dépassement", f"{k['pct_dep']:.0f} %" if k["n_agents"] else "—", delta=f"{k['n_dep']} / {k['n_agents']} agents", delta_color="off")
ui.metric(c[1], "Dépassement total", fmt_duration(k["exces_s"]))
tot_pause = v.agents["pause_regle_s"].sum()
ui.metric(c[2], "Temps soumis aux règles", fmt_duration(tot_pause))
ui.metric(c[3], "Pauses en dépassement", fmt_int((v.blocs["statut_pause"] == "Dépassement").sum()))

t1, t2, t3, t4 = st.tabs(["Par agent", "Par jour", "Par type de pause", "Par tranche horaire"])
with t1:
    ov = calc.overage_by_agent(v)
    only = st.checkbox("Uniquement les agents en dépassement", value=True)
    show = ov[ov["Dépassement (min)"] > 0] if only else ov
    ui.display_df(show)
    st.plotly_chart(viz.fig_bar(show.head(25), "Agent", "Dépassement (min)", "Dépassement par agent (min)", horizontal=True), use_container_width=True)
    st.download_button("⬇ Exporter (CSV)", show.to_csv(index=False).encode("utf-8-sig"), "depassements_par_agent.csv", "text/csv")
with t2:
    od = calc.overage_by_day(v)
    ui.display_df(od)
    st.plotly_chart(viz.fig_bar(od.assign(Date=od["Date"].astype(str)), "Date", "Dépassement (min)", "Dépassement par jour (min)"), use_container_width=True)
with t3:
    ot = calc.overage_by_type(v)
    ui.display_df(ot)
    st.plotly_chart(viz.fig_bar(ot, "Type de pause", "Dépassement (min)", "Dépassement par type (min)"), use_container_width=True)
with t4:
    os_ = calc.overage_by_slot(v)
    st.plotly_chart(viz.fig_bar(os_, "Tranche", "Dépassement (min)", "Dépassement par tranche horaire (min)"), use_container_width=True)
    st.caption("Le dépassement cumulé est attribué au créneau où l'agent franchit puis poursuit au-delà de la limite.")
