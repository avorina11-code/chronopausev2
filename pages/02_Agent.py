"""Vue individuelle : timeline chronologique d'un agent sur une journée."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import streamlit as st

from src import calculations as calc
from src import ui
from src import visualizations as viz
from src.config import fmt_duration, fmt_int, fmt_ms, slot_label

ctx = ui.get_context("Agent", "🧑", "Timeline chronologique de la journée d'un agent")
v, rules = ctx.view, ctx.rules
ag = v.agents
if ag.empty:
    st.warning("Aucun agent pour les filtres sélectionnés.")
    st.stop()

labels = ag.drop_duplicates("login").set_index("login")["agent_label"].sort_values()
c1, c2 = st.columns([3, 1])
login = c1.selectbox("Agent", labels.index.tolist(), format_func=lambda l: labels[l], key="agent_pick")
days = sorted(ag.loc[ag["login"] == login, "date"].unique())
day = c2.selectbox("Date", days, format_func=lambda d: d.strftime("%d/%m/%Y"), key="agent_day")

row = ag[(ag["login"] == login) & (ag["date"] == day)].iloc[0]
s = ctx.ds.slots[(ctx.ds.slots["login"] == login) & (ctx.ds.slots["date"] == day)]
b = ctx.ds.blocs[(ctx.ds.blocs["login"] == login) & (ctx.ds.blocs["date"] == day)]
if v.flt.types:
    s, b = s[s["type_pause"].isin(v.flt.types)], b[b["type_pause"].isin(v.flt.types)]

with st.container(border=True):
    h1, h2, h3, h4 = st.columns(4)
    h1.markdown(f"**{row['nom_affiche']}**")
    h2.markdown(f"Login : `{login}`")
    h3.markdown(f"Équipe : {row.get('equipe') or '—'} · Superviseur : {row.get('superviseur') or '—'}")
    h4.markdown(f"Matricule : {row.get('matricule') or '—'} · RH : {row.get('statut_rapprochement')}")
    if row.get("alerte_nom"):
        st.warning(row["alerte_nom"])

nb = int((~b["micro"]).sum())
m = st.columns(5)
ui.metric(m[0], "Pauses (blocs)", fmt_int(nb), help="Blocs de créneaux consécutifs : minimum du nombre de pauses réelles.")
ui.metric(m[1], "Temps total (statuts affichés)", fmt_duration(s["seconds"].sum()))
ui.metric(m[2], "Temps soumis aux règles", fmt_duration(row["pause_regle_s"]),
          delta=f"autorisé : {rules.duree_max_cumulee_min:g} min" if rules.duree_max_cumulee_min > 0 else None, delta_color="off")
ui.metric(m[3], "Dépassement", fmt_duration(row["exces_cumule_s"]))
ui.metric(m[4], "Statut", "⚠ Dépassement" if row["en_depassement"] else "Normal", help=row["motifs"] or "Aucune règle dépassée")

arr = row.get("arrivee_min")
dep = row.get("depart_min")
st.plotly_chart(viz.fig_timeline(s, b, ctx.colors, arr, dep, f"{row['nom_affiche']} — {day.strftime('%d/%m/%Y')}"), use_container_width=True)
if ctx.parsed.layout == "vocalcom":
    st.caption("ℹ️ Le rapport ne fournit que la durée passée dans chaque créneau de 30 min : l'**opacité** d'une case = part du créneau "
               "passée dans ce statut ; l'heure exacte de début/fin n'est pas connue. Le texte au centre indique la durée observée du bloc. "
               "Rouge = dépassement de la règle configurée.")
st.plotly_chart(viz.fig_cumulative(s, rules.duree_max_cumulee_min), use_container_width=True)

st.markdown("#### Blocs de pause")
if b.empty:
    st.info("Aucune pause observée.")
else:
    t = b.sort_values("debut_min")[["type_pause", "heure_debut", "heure_fin", "nb_creneaux", "duree_s", "statut_pause",
                                    "depassement_minutes", "precision_horaire"]].copy()
    t["duree_s"] = t["duree_s"].map(fmt_ms)
    t.columns = ["Type", "Début (≥)", "Fin (≤)", "Créneaux", "Durée observée", "Statut", "Dépassement (min)", "Précision horaire"]
    ui.display_df(t)
