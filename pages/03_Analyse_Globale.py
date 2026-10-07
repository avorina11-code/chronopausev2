"""Analyse globale : distribution horaire, types de pause, heatmap, simultanéité."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import streamlit as st

from src import calculations as calc
from src import ui
from src import visualizations as viz
from src.config import fmt_duration, fmt_int, fmt_ms, slot_label

ctx = ui.get_context("Analyse globale", "🌐", "Comportement collectif : quand, quoi, combien en même temps")
v, rules, k = ctx.view, ctx.rules, ctx.kpis
if v.slots.empty:
    st.warning("Aucune donnée pour les filtres sélectionnés.")
    st.stop()

t1, t2, t3, t4 = st.tabs(["Distribution horaire", "Types de pause", "Heatmap", "Simultanéité"])

with t1:
    metric = st.radio("Mesure", ["blocs_entames", "minutes", "agents"], horizontal=True,
                      format_func={"blocs_entames": "Pauses entamées", "minutes": "Minutes de pause", "agents": "Agents distincts"}.get)
    bs = calc.by_slot(v)
    ui.slot_detail(v, viz.fig_distribution(bs, metric), key="glob_dist")
    if len(bs):
        top = bs.sort_values(metric, ascending=False).iloc[0]
        st.info(f"Créneau le plus chargé : **{top['tranche']}** ({top[metric]:.0f}).")
    st.caption("« Pauses entamées » = blocs dont le 1er créneau observé est celui-ci (bornes de créneaux, pas d'heure exacte).")

with t2:
    bt = calc.by_type(v)
    a, b = st.columns([3, 2])
    a.plotly_chart(viz.fig_by_type(bt, ctx.colors), use_container_width=True)
    b.dataframe(bt, hide_index=True, use_container_width=True)
    st.plotly_chart(viz.fig_type_hourly(v.slots, ctx.colors), use_container_width=True)

with t3:
    hm = st.radio("Valeur", ["agents", "equiv", "minutes"], horizontal=True,
                  format_func={"agents": "Agents distincts", "equiv": "Agents simultanés (moyenne)", "minutes": "Minutes"}.get)
    st.plotly_chart(viz.fig_heatmap(v.slots, hm), use_container_width=True)

with t4:
    sim = ctx.sim
    c = st.columns(4)
    ui.metric(c[0], "Pic de simultanéité", f"{k['peak_pct']:.1f} %" if k["peak_pct"] == k["peak_pct"] else "—")
    ui.metric(c[1], "Heure du pic", k["peak_hour"])
    ui.metric(c[2], "Agents concernés (≈)", f"{k['peak_agents']:.1f}" if k["peak_agents"] == k["peak_agents"] else "—")
    ui.metric(c[3], "Créneaux > limite", fmt_int(k["n_periodes_dep"]) if rules.simultaneite_max_pct > 0 else "limite désactivée")
    st.plotly_chart(viz.fig_simultaneity(sim, rules.simultaneite_max_pct), use_container_width=True)
    if len(sim):
        base = sim.attrs.get("base", "fichier")
        st.caption(f"Base : {ui.BASE_LABELS[base]} · Mesure : {ui.MESURE_LABELS[rules.mesure_simultaneite]}. "
                   "Effectif = agents connectés dont [arrivée, départ] recoupe le créneau (donnée du Résumé).")
        t = sim.copy()
        t["Alerte"] = t["depasse"].map({True: "⚠ > limite", False: ""})
        t.loc[~t["retenu"], "Alerte"] = "effectif trop faible"
        t = t[["date", "tranche", "agents_distincts", "equiv_agents", "effectif", "pct", "Alerte"]]
        t.columns = ["Date", "Tranche", "Agents distincts", "Équivalent simultané", "Effectif réf.", "% simultanéité", "Alerte"]
        st.dataframe(t, hide_index=True, use_container_width=True,
                     column_config={"Équivalent simultané": st.column_config.NumberColumn(format="%.1f"),
                                    "% simultanéité": st.column_config.NumberColumn(format="%.1f %%")})
