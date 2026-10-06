"""Base RH et rapprochement avec les agents du fichier de pauses.

Règles de rapprochement :
 • La CLÉ est le login (comparaison insensible à la casse et aux zéros de tête).
 • Un login trouvé mais dont le nom diffère franchement du nom du rapport est signalé (alerte_nom).
 • Un agent non trouvé reçoit au mieux une SUGGESTION par nom (≥ 2 mots communs, nom entièrement contenu dans
   l'autre). Une suggestion n'est JAMAIS appliquée sans activation explicite dans la barre latérale.
"""
from __future__ import annotations

import pandas as pd

from . import cleaner
from .models import RHData
from .normalizer import (RH_SYNONYMS, auto_map_columns, clean_text, display_name, login_key, name_overlap, norm_login,
                         split_name)
from .validation import CAT_DOUBLON_RH, IssueLog

SRC = "RH"
RH_COLS = ["matricule", "login", "key", "nom_prenom", "nom", "prenom", "nom_affiche", "equipe", "superviseur",
           "ligne_source"]
MATCH_COLS = ["login", "nom_source", "nom_affiche", "nom", "prenom", "matricule", "equipe", "superviseur",
              "statut_rapprochement", "alerte_nom", "suggestion_matricule", "suggestion_nom_rh"]
ST_LOGIN, ST_SUGG, ST_NONE, ST_NO_RH = "Rapproché (login)", "Suggestion par nom", "Non rapproché", "Base RH non chargée"


# ───────────────────────── chargement ─────────────────────────
def _build(tbl: pd.DataFrame, mp: dict, sheet: str, header_row: int) -> RHData:
    issues = IssueLog(SRC)
    rows = []
    for rec in tbl.to_dict("records"):
        get = lambda f: rec.get(mp[f]) if f in mp else None  # noqa: E731
        login = norm_login(get("login"))
        matricule = norm_login(get("matricule"))
        full = clean_text(get("nom_prenom"))
        nom, prenom = clean_text(get("nom")), clean_text(get("prenom"))
        if nom or prenom:
            full = full or display_name(nom, prenom)
        else:
            nom, prenom = split_name(full)
        rows.append(dict(matricule=matricule, login=login, key=login_key(login) if login else "", nom_prenom=full,
                         nom=nom, prenom=prenom, nom_affiche=display_name(nom, prenom) or full,
                         equipe=clean_text(get("equipe")), superviseur=clean_text(get("superviseur")),
                         ligne_source=rec.get(cleaner.LINE_COL)))
    df = pd.DataFrame(rows, columns=RH_COLS)

    no_login = df[df["login"] == ""]
    for _, r in no_login.iterrows():
        issues.add("Info", "Login RH vide", f"Agent RH sans login : {r['matricule'] or '(sans matricule)'} — {r['nom_affiche']}.",
                   "Non rapprochable par login (une suggestion par nom reste possible)", ref=r["ligne_source"])
    with_login = df[df["login"] != ""]
    dup = with_login[with_login.duplicated("key", keep=False)]
    for k, g in dup.groupby("key"):
        issues.add("Avertissement", CAT_DOUBLON_RH, f"Login {g['login'].iloc[0]} présent {len(g)} fois dans la base RH "
                   f"(lignes {', '.join(map(str, g['ligne_source']))}).", "Première occurrence utilisée", login=g["login"].iloc[0])
    df = pd.concat([df[df["login"] == ""], with_login.drop_duplicates("key", keep="first")]).sort_values("ligne_source")
    mat = df[df["matricule"] != ""]
    for m, g in mat[mat.duplicated("matricule", keep=False)].groupby("matricule"):
        issues.add("Avertissement", CAT_DOUBLON_RH, f"Matricule {m} présent {len(g)} fois (lignes "
                   f"{', '.join(map(str, g['ligne_source']))}).", "Conservé tel quel")
    df = df.reset_index(drop=True)
    meta = dict(sheet=sheet, header_row=header_row, mapping=dict(mp), n_agents=len(df),
                n_sans_login=int((df["login"] == "").sum()), n_avec_login=int((df["login"] != "").sum()),
                champs_absents=[f for f in ("matricule", "equipe", "superviseur") if f not in mp])
    return RHData(df, issues.to_df(), meta)


def load_rh(grids: dict, sheet: str | None = None, header_row: int | None = None, mapping: dict | None = None) -> RHData:
    """Charge la base RH. Sans paramètres : détection automatique (1re feuille contenant une colonne login).
    Avec `mapping` {champ: colonne} : mapping manuel. df = None si aucun login n'est détectable."""
    if sheet is not None and mapping:
        hr = cleaner.detect_header_row(grids[sheet], RH_SYNONYMS) if header_row is None else int(header_row)
        tbl = cleaner.table_from_grid(grids[sheet], hr)
        mp = {k: v for k, v in mapping.items() if v in tbl.columns}
        return _build(tbl, mp, sheet, hr) if "login" in mp else RHData(None, IssueLog(SRC).to_df(), {"n_sans_login": 0})
    best = None
    for name, g in grids.items():
        hr = cleaner.detect_header_row(g, RH_SYNONYMS)
        tbl = cleaner.table_from_grid(g, hr)
        mp = auto_map_columns([c for c in tbl.columns if c != cleaner.LINE_COL], RH_SYNONYMS)
        if "login" in mp and (best is None or len(tbl) > len(best[0])):
            best = (tbl, mp, name, hr)
    if best is None:
        return RHData(None, IssueLog(SRC).to_df(), {"n_sans_login": 0})
    return _build(*best)


# ───────────────────────── rapprochement ─────────────────────────
def _identity(rh_row) -> dict:
    return dict(nom_affiche=rh_row["nom_affiche"], nom=rh_row["nom"], prenom=rh_row["prenom"],
                matricule=rh_row["matricule"], equipe=rh_row["equipe"], superviseur=rh_row["superviseur"])


def match_agents(agents: pd.DataFrame, rh: RHData | None, use_suggestions: bool = False) -> pd.DataFrame:
    """Une ligne par login du fichier de pauses (voir MATCH_COLS)."""
    base = agents.drop_duplicates("login")[["login", "nom_source"]].reset_index(drop=True)
    base["nom_source"] = base["nom_source"].fillna("").astype(str)
    out = []
    has_rh = rh is not None and rh.df is not None
    by_key = {r["key"]: r for _, r in rh.df[rh.df["login"] != ""].iterrows()} if has_rh else {}
    pause_keys = {login_key(l) for l in base["login"]}

    # suggestions : agents non trouvés × agents RH sans login (ou dont le login est absent du fichier de pauses)
    sugg: dict[str, pd.Series] = {}
    if has_rh:
        pool = rh.df[(rh.df["login"] == "") | (~rh.df["key"].isin(pause_keys))]
        pairs = []
        for _, a in base[~base["login"].map(login_key).isin(set(by_key))].iterrows():
            for pi, r in pool.iterrows():
                hits, small = name_overlap(a["nom_source"], r["nom_affiche"])
                if hits >= 2 and hits == small:
                    pairs.append((hits * 10 - abs(len(a["nom_source"].split()) - len(r["nom_affiche"].split())), a["login"], pi))
        used_rh = set()
        for _, login, pi in sorted(pairs, key=lambda t: -t[0]):
            if login not in sugg and pi not in used_rh:
                sugg[login] = pool.loc[pi]
                used_rh.add(pi)

    for _, a in base.iterrows():
        login, src = a["login"], a["nom_source"]
        n0, p0 = split_name(src)
        row = dict(login=login, nom_source=src, nom_affiche=src, nom=n0, prenom=p0, matricule="", equipe="",
                   superviseur="", statut_rapprochement=ST_NO_RH, alerte_nom="", suggestion_matricule="",
                   suggestion_nom_rh="")
        if has_rh:
            hit = by_key.get(login_key(login))
            if hit is not None:
                row.update(_identity(hit), statut_rapprochement=ST_LOGIN)
                hits, _ = name_overlap(src, hit["nom_affiche"])
                if src and hit["nom_affiche"] and hits < 1:
                    row["alerte_nom"] = f"Nom du rapport « {src} » ≠ nom RH « {hit['nom_affiche']} » pour le login {login}."
            else:
                row["statut_rapprochement"] = ST_NONE
                s = sugg.get(login)
                if s is not None:
                    row["suggestion_matricule"] = s["matricule"]
                    row["suggestion_nom_rh"] = s["nom_affiche"] + (f" (login RH : {s['login']})" if s["login"] else "")
                    row["statut_rapprochement"] = ST_SUGG
                    if use_suggestions:
                        row.update(_identity(s))
        row["nom_affiche"] = row["nom_affiche"] or src
        out.append(row)
    return pd.DataFrame(out, columns=MATCH_COLS)


def rh_not_in_pauses(rh: RHData, logins: set) -> pd.DataFrame:
    """Agents de la base RH dont le login n'apparaît pas dans le fichier de pauses (information)."""
    cols = ["matricule", "login", "nom_affiche"]
    if rh is None or rh.df is None:
        return pd.DataFrame(columns=cols)
    keys = {login_key(l) for l in logins}
    d = rh.df[~rh.df["key"].isin(keys) | (rh.df["login"] == "")]
    return d[cols].reset_index(drop=True)
