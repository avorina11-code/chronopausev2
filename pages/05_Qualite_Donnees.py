"""Qualité des données : les données utilisées sont-elles fiables ? (non filtrée : porte sur tout le fichier)"""
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

ctx = ui.get_context("Qualité des données", "🧪", "Contrôle du nettoyage et du rapprochement — porte sur l'intégralité des fichiers (filtres ignorés)")
p, rh, match = ctx.parsed, ctx.rh, ctx.match
m = p.meta
issues = merge_issues(p.issues, rh.issues if rh is not None else None)
cnt = lambda *cats: int(issues["categorie"].isin(cats).sum()) if len(issues) else 0  # noqa: E731

st.markdown("#### Lecture du fichier de pauses")
c = st.columns(4)
ui.metric(c[0], "Lignes source", fmt_int(m["lignes_source"]), help=m["unite_lignes"])
ui.metric(c[1], "Lignes exploitables", fmt_int(m["lignes_exploitables"]),
          delta=f"{m['lignes_exploitables'] / m['lignes_source'] * 100:.1f} %" if m["lignes_source"] else None, delta_color="off")
ui.metric(c[2], "Lignes rejetées", fmt_int(m["lignes_rejetees"]))
ui.metric(c[3], "Agents détectés", fmt_int(len(match)))
c = st.columns(4)
ui.metric(c[0], "Doublons", fmt_int(cnt("Doublon")))
ui.metric(c[1], "Horaires / valeurs invalides", fmt_int(cnt("Horaire invalide", "Valeur invalide", "Valeur incohérente")))
ui.metric(c[2], "Dates manquantes / invalides", fmt_int(cnt("Date manquante", "Date invalide")))
ui.metric(c[3], "Écarts de contrôle", fmt_int(cnt("Écart de contrôle")), help="Somme des créneaux ≠ totaux du rapport.")

if p.layout == "vocalcom" and p.agents["pause_resume_s"].notna().any():
    a = p.agents.dropna(subset=["pause_resume_s"])
    ok = int(((a["pause_resume_s"] - a["pause_slots_s"]).abs() <= 1).sum())
    (st.success if ok == len(a) else st.error)(
        f"Contrôle de réconciliation : la somme des créneaux lus égale la « Durée de pause » du Résumé pour {ok} agent(s) sur {len(a)}"
        + (" — l'alignement des colonnes est validé." if ok == len(a) else " — vérifier les agents en écart."))
    bm = ctx.ds.blocs
    st.caption(f"Pauses < 60 s (micro-pauses) : {int((bm['duree_s'] < 60).sum())} bloc(s) sur {len(bm)} — comptés tels quels "
               "(modifiable via « Ignorer dans le décompte les pauses < N secondes »).")

st.markdown("#### Rapprochement avec la base RH")
if rh is None:
    st.info("Aucune base RH chargée.")
else:
    n = len(match)
    ok = int((match["statut_rapprochement"] == "Rapproché (login)").sum())
    sug = int((match["statut_rapprochement"] == "Suggestion par nom").sum())
    non = int((match["statut_rapprochement"] == "Non rapproché").sum())
    c = st.columns(4)
    ui.metric(c[0], "Logins trouvés dans la RH", f"{ok / n * 100:.0f} %", delta=f"{ok} / {n}", delta_color="off")
    ui.metric(c[1], "Logins inconnus", f"{(n - ok) / n * 100:.0f} %", delta=f"{n - ok} agent(s)", delta_color="off")
    ui.metric(c[2], "Suggestions par nom", fmt_int(sug), help="Agent RH sans login dont le nom est compatible : à confirmer.")
    ui.metric(c[3], "Logins RH vides / doublons", f"{rh.meta.get('n_sans_login', 0)} / {cnt('Doublon RH')}")
    bad = match[match["statut_rapprochement"] != "Rapproché (login)"][["login", "nom_source", "statut_rapprochement", "suggestion_matricule", "suggestion_nom_rh"]]
    if len(bad):
        st.markdown("**Agents du fichier de pauses non rapprochés par login**")
        bad.columns = ["Login", "Nom (rapport)", "Statut", "Matricule suggéré", "Nom RH suggéré"]
        ui.display_df(bad)
    alert = match[match["alerte_nom"] != ""][["login", "alerte_nom"]]
    if len(alert):
        st.markdown("**Login trouvé mais nom différent** (vérifier qu'il s'agit de la même personne)")
        alert.columns = ["Login", "Constat"]
        ui.display_df(alert)
    absent = rh_not_in_pauses(rh, set(match["login"]))
    with st.expander(f"Agents de la base RH absents du fichier de pauses ({len(absent)}) — information"):
        absent.columns = ["Matricule", "Login", "Nom"]
        ui.display_df(absent)

st.markdown("#### Journal des anomalies")
st.caption("Rien n'est supprimé en silence : chaque ligne écartée, corrigée ou signalée figure ici avec l'action entreprise.")
if issues.empty:
    st.success("Aucune anomalie détectée.")
else:
    f1, f2, f3 = st.columns(3)
    sev = f1.multiselect("Sévérité", ["Erreur", "Avertissement", "Info"], default=["Erreur", "Avertissement"])
    cat = f2.multiselect("Catégorie", sorted(issues["categorie"].unique()))
    src = f3.multiselect("Source", sorted(issues["source"].unique()))
    sel = issues[issues["severite"].isin(sev)]
    sel = sel[sel["categorie"].isin(cat)] if cat else sel
    sel = sel[sel["source"].isin(src)] if src else sel
    summ = issues.groupby(["severite", "categorie"]).size().reset_index(name="Nombre")
    a, b = st.columns([1, 2])
    a.dataframe(summ, hide_index=True, use_container_width=True)
    b.dataframe(sel.rename(columns={"severite": "Sévérité", "categorie": "Catégorie", "login": "Login", "detail": "Détail",
                                    "action": "Action", "ref": "Ligne source", "source": "Source"}),
                hide_index=True, use_container_width=True, height=330)
    st.download_button("⬇ Journal des anomalies (CSV)", issues.to_csv(index=False).encode("utf-8-sig"), "anomalies.csv", "text/csv")

with st.expander("Donnée observée vs donnée calculée"):
    st.markdown("""
| Indicateur | Nature | Règle |
|---|---|---|
| Durée par créneau de 30 min | **Observée** | Lue telle quelle dans le rapport (mm'ss) |
| Arrivée / Départ, Durée de pause (Résumé) | **Observée** | Lus dans le rapport ; servent aux contrôles et à l'effectif |
| Bloc de pause (début, fin) | **Calculée** | Créneaux consécutifs d'un même statut ; début/fin = bornes de créneaux, **pas** des heures exactes |
| Durée d'un bloc | **Calculée (exacte)** | Somme des durées observées |
| Dépassement | **Calculé** | Selon les règles saisies dans la barre latérale |
| Simultanéité | **Calculée** | Σ secondes ÷ 1800 ÷ effectif de référence |
| Nom / matricule | **RH** | Par login uniquement ; suggestions par nom jamais appliquées sans votre accord |
""")
