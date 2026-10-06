"""PAUSE ANALYZER – page d'accueil : import des fichiers, détection de structure, résumé d'import.

Lancement :  streamlit run app.py
"""
import datetime as dt
import hashlib
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd
import streamlit as st

from src import cleaner, loader, rh_matching, ui
from src.normalizer import PAUSE_SYNONYMS, RH_SYNONYMS
from src.config import fmt_int

ui.page_setup("Accueil", "⏱️")
ui.header("Import des fichiers", "Les fichiers chargés restent des données brutes : tout le traitement se fait sur des copies en mémoire.")


@st.cache_data(show_spinner="Lecture du fichier Excel…")
def cached_grids(content: bytes, name: str):
    return loader.read_grids(content, name)


FIELD_LABELS = {"login": "Login *", "nom_source": "Nom de l'agent", "date": "Date", "heure_debut": "Heure début",
                "heure_fin": "Heure fin", "duree": "Durée", "type_pause": "Type de pause", "tranche": "Tranche (30 min)"}

c1, c2 = st.columns(2)
f_pause = c1.file_uploader("① Fichier des pauses (Excel)", type=["xls", "xlsx", "xlsm"],
                           help="Rapport Vocalcom « Agents pause report » ou tableau de pauses.")
f_rh = c2.file_uploader("② Base RH (Excel)", type=["xls", "xlsx", "xlsm"],
                        help="Doit contenir au minimum une colonne login ; nom, matricule, équipe, superviseur si disponibles.")

# ───────────────────────── fichier des pauses ─────────────────────────
if f_pause is not None:
    raw = f_pause.getvalue()
    try:
        grids = cached_grids(raw, f_pause.name)
    except Exception as e:  # noqa: BLE001
        st.error(f"Impossible de lire le fichier de pauses : {e}")
        st.stop()
    info = loader.inspect_pause_file(grids)
    sheet = hr = mapping = None
    if info["layout"] == "tabulaire":
        with st.expander("🔎 Détection des colonnes (modifiable)", expanded=True):
            sheet = st.selectbox("Feuille", list(grids), index=list(grids).index(info["sheet"]))
            if sheet != info["sheet"]:
                info["header_row"] = cleaner.detect_header_row(grids[sheet])
            hr = st.number_input("Ligne d'en-tête (1 = première ligne)", 1, 200, info["header_row"] + 1) - 1
            tbl = cleaner.table_from_grid(grids[sheet], hr)
            cols = [c for c in tbl.columns if c != "__ligne_excel"]
            from src.normalizer import auto_map_columns
            auto = auto_map_columns(cols, PAUSE_SYNONYMS)
            mapping, cc = {}, st.columns(4)
            for i, (fld, lab) in enumerate(FIELD_LABELS.items()):
                opts = ["(aucune)"] + cols
                sel = cc[i % 4].selectbox(lab, opts, index=opts.index(auto[fld]) if fld in auto else 0, key=f"map_{fld}_{sheet}_{hr}")
                if sel != "(aucune)":
                    mapping[fld] = sel
            st.dataframe(tbl.drop(columns="__ligne_excel").head(8), use_container_width=True)
        ok = "login" in mapping and (("heure_debut" in mapping and "heure_fin" in mapping) or ("tranche" in mapping and "duree" in mapping))
        if not ok:
            st.error("Mapping insuffisant : il faut **Login** + (**Heure début** et **Heure fin**) ou (**Tranche** et **Durée**).")
            st.stop()
    parsed = loader.parse_pause_file(grids, None, sheet, hr, mapping)
    if (parsed.issues["categorie"] == "Date manquante").any():
        d = st.date_input("📅 Aucune date trouvée dans le fichier : indiquez la date des pauses", value=dt.date.today())
        parsed = loader.parse_pause_file(grids, d, sheet, hr, mapping)
    sig = hashlib.md5(raw).hexdigest()
    if st.session_state.get("pause_sig") != sig:
        ui.reset_widget_state()
        st.session_state["pause_sig"] = sig
    st.session_state["parsed"] = parsed
    st.session_state["pause_name"] = f_pause.name

# ───────────────────────── base RH ─────────────────────────
if f_rh is not None:
    try:
        rgrids = cached_grids(f_rh.getvalue(), f_rh.name)
    except Exception as e:  # noqa: BLE001
        st.error(f"Impossible de lire la base RH : {e}")
        st.stop()
    rh = rh_matching.load_rh(rgrids)
    if rh.df is None:
        with st.expander("🔎 Colonne login non détectée dans la base RH : sélection manuelle", expanded=True):
            sh = st.selectbox("Feuille RH", list(rgrids))
            hrr = st.number_input("Ligne d'en-tête RH", 1, 200, cleaner.detect_header_row(rgrids[sh], RH_SYNONYMS) + 1, key="rh_hr") - 1
            cols = [c for c in cleaner.table_from_grid(rgrids[sh], hrr).columns if c != "__ligne_excel"]
            mp, cc = {}, st.columns(3)
            for i, fld in enumerate(["login", "matricule", "nom_prenom", "equipe", "superviseur"]):
                sel = cc[i % 3].selectbox(fld, ["(aucune)"] + cols, key=f"rhmap_{fld}")
                if sel != "(aucune)":
                    mp[fld] = sel
            if "login" in mp:
                rh = rh_matching.load_rh(rgrids, sh, hrr, mp)
    st.session_state["rh"] = rh if rh.df is not None else None
    st.session_state["rh_name"] = f_rh.name
elif "rh" in st.session_state and f_rh is None and "rh_name" in st.session_state:
    del st.session_state["rh"], st.session_state["rh_name"]

# ───────────────────────── résumé d'import ─────────────────────────
if "parsed" not in st.session_state:
    st.info("Chargez le fichier de pauses pour démarrer. La base RH est optionnelle mais recommandée (noms lisibles, rapprochement des agents).")
    st.stop()

p, rh = st.session_state["parsed"], st.session_state.get("rh")
m = p.meta
match = rh_matching.match_agents(p.agents, rh)
issues = p.issues
n_check = int(issues["severite"].isin(["Erreur", "Avertissement"]).sum()) if len(issues) else 0
st.subheader("Résumé du fichier importé")
lines = [f"✅ **Fichier chargé** : {st.session_state.get('pause_name')} — {m['layout_label']}",
         f"✅ **{fmt_int(m['lignes_non_vides'])}** lignes non vides · feuille(s) : {', '.join(m['feuilles'])}",
         f"✅ **{fmt_int(m['lignes_source'])}** {m['unite_lignes']} lues"
         + (f" — **{fmt_int(m['lignes_exploitables'])}** exploitables"),
         f"✅ **{fmt_int(len(match))}** agents détectés (logins distincts)"]
if m.get("dates"):
    lines.append("📅 Date(s) du rapport : " + ", ".join(d.strftime("%d/%m/%Y") for d in m["dates"])
                 + (f" (généré le {m['generation']})" if m.get("generation") else ""))
if m["lignes_rejetees"]:
    lines.append(f"⚠️ **{fmt_int(m['lignes_rejetees'])}** lignes rejetées")
lines.append(f"⚠️ **{fmt_int(n_check)}** point(s) nécessitent une vérification" if n_check else "✅ Aucune anomalie bloquante détectée")
if rh is not None:
    n_ok = int((match["statut_rapprochement"] == "Rapproché (login)").sum())
    icon = "✅" if n_ok == len(match) else "⚠️"
    lines.append(f"{icon} **{n_ok / len(match) * 100:.0f} %** des agents rapprochés avec la base RH ({n_ok}/{len(match)}) — "
                 f"{st.session_state.get('rh_name')}")
else:
    lines.append("ℹ️ Base RH non chargée : les agents sont identifiés par leur login et le nom du rapport.")
st.markdown("\n\n".join(lines))

st.divider()
st.markdown("**Naviguer dans l'analyse**")
cols = st.columns(6)
for col, (page, label, icon) in zip(cols, [("pages/01_Dashboard.py", "Dashboard", "📊"), ("pages/02_Agent.py", "Agent", "🧑"),
                                           ("pages/03_Analyse_Globale.py", "Analyse globale", "🌐"),
                                           ("pages/04_Depassements.py", "Dépassements", "⚠️"),
                                           ("pages/05_Qualite_Donnees.py", "Qualité des données", "🧪"),
                                           ("pages/06_Tableau_Detaille.py", "Tableau détaillé", "📋")]):
    col.page_link(page, label=label, icon=icon)

with st.expander("Aperçu des données brutes (copie en lecture seule)"):
    if f_pause is None:
        st.caption("Rechargez le fichier pour l'aperçu.")
    else:
        sh = st.selectbox("Feuille", m["feuilles"], key="prev_sheet") if len(m["feuilles"]) > 1 else m["feuilles"][0]
        preview = cached_grids(f_pause.getvalue(), f_pause.name)[sh].dropna(how="all").dropna(how="all", axis=1).head(40)
        st.dataframe(preview.astype(str), use_container_width=True)
