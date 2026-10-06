"""Tableau détaillé : lignes normalisées, recherche, filtres complémentaires, export."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pandas as pd
import streamlit as st

from src import calculations as calc
from src import ui
from src.config import fmt_int
from src.rh_matching import rh_not_in_pauses
from src.validation import merge_issues

ctx = ui.get_context("Tableau détaillé", "📋", "Données normalisées — les filtres de la barre latérale s'appliquent")
v = ctx.view
q = st.text_input("🔎 Rechercher un agent (nom, login, matricule)", "")
stat = st.multiselect("Statut de la pause", ["Normale", "Dépassement", "Hors règle"], default=[])

def search(df: pd.DataFrame) -> pd.DataFrame:
    if q.strip():
        t = q.strip().lower()
        mask = (df["nom_affiche"].astype(str).str.lower().str.contains(t, regex=False) | df["login"].astype(str).str.contains(t, regex=False)
                | df["matricule"].astype(str).str.lower().str.contains(t, regex=False))
        df = df[mask]
    return df

b = search(v.blocs)
if stat:
    b = b[b["statut_pause"].isin(stat)]
s = search(v.slots)
a = search(v.agents)
cols_b = ["date", "login", "nom", "prenom", "matricule", "equipe", "superviseur", "type_pause", "heure_debut", "heure_fin",
          "duree_minutes", "tranche_30min", "nb_creneaux", "statut_pause", "depassement_minutes", "precision_horaire"]
out_b = b[[c for c in cols_b if c in b]].sort_values(["date", "login", "heure_debut"])
cols_s = ["date", "login", "nom_affiche", "type_pause", "tranche_30min", "heure", "minute", "seconds", "exces_s", "est_regle"]
out_s = s[cols_s].rename(columns={"seconds": "duree_observee_s", "exces_s": "depassement_cumule_s", "est_regle": "soumis_aux_regles"})
cols_a = ["date", "login", "nom_affiche", "matricule", "equipe", "superviseur", "statut_rapprochement", "arrivee_min", "depart_min",
          "pause_totale_s", "pause_regle_s", "nb_pauses_regle", "exces_cumule_s", "exces_bloc_s", "exces_nb", "en_depassement", "motifs"]
out_a = a[[c for c in cols_a if c in a]]

t1, t2, t3 = st.tabs([f"Pauses ({len(out_b)})", f"Créneaux observés ({len(out_s)})", f"Agents / jour ({len(out_a)})"])
with t1:
    st.caption("Heure début/fin = bornes des créneaux de 30 min (plage couvrante) pour un rapport par créneaux ; la durée est la somme des durées observées.")
    ui.display_df(out_b)
with t2:
    ui.display_df(out_s)
with t3:
    ui.display_df(out_a)

d1, d2 = st.columns(2)
d1.download_button("⬇ Pauses (CSV)", out_b.to_csv(index=False).encode("utf-8-sig"), "pauses_normalisees.csv", "text/csv")
d2.download_button("⬇ Toutes les données nettoyées (Excel)", calc.to_excel_bytes({"Pauses": out_b, "Creneaux": out_s, "Agents_jour": out_a}),
                   "donnees_nettoyees.xlsx", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
