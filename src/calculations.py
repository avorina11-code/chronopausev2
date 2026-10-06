"""Calculs analytiques.

DONNÉE OBSERVÉE  : seconds par (agent, statut, créneau 30 min) ; arrivée/départ du Résumé.
DONNÉE CALCULÉE  : tout le reste, selon les définitions ci-dessous.

 • Bloc de pause (« pause » reconstruite) = créneaux CONSÉCUTIFS du même statut pour un agent.
   Durée = somme des secondes observées (exacte). Début/fin = bornes des créneaux (plage couvrante,
   la position exacte dans le créneau est inconnue). Un bloc peut regrouper plusieurs pauses
   contiguës : « nombre de pauses » est donc un minimum.
 • Dépassement cumulé : on parcourt les créneaux dans l'ordre ; les secondes au-delà de la durée
   maximale cumulée (types soumis aux règles) sont du dépassement, attribué au créneau où il survient.
 • Simultanéité d'un créneau = Σ secondes en pause / 1800 (nombre MOYEN d'agents simultanément en
   pause) ou nombre d'agents distincts ayant ≥ 1 s ; rapporté à l'effectif de référence choisi.
 • Les règles sont évaluées sur la journée complète de l'agent, puis restituées selon les filtres.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from .config import N_SLOTS, SLOT_MIN, SLOT_SEC, Rules, slot_label, tranche_label
from .models import ParsedPauses

INFO_COLS = ["login", "nom_affiche", "nom", "prenom", "matricule", "equipe", "superviseur", "statut_rapprochement", "alerte_nom"]


@dataclass
class Dataset:
    slots: pd.DataFrame
    blocs: pd.DataFrame
    agents: pd.DataFrame           # une ligne par (date, login)
    rules: Rules
    types: list
    rh_headcount: int | None = None
    has_team: bool = False
    has_sup: bool = False


def default_rule_types(types) -> tuple:
    """Par défaut : statuts dont le libellé contient « pause ». C'est une SUGGESTION, modifiable."""
    return tuple(t for t in types if "pause" in str(t).lower())


def agent_directory(parsed: ParsedPauses, match: pd.DataFrame) -> pd.DataFrame:
    a = parsed.agents.merge(match[[c for c in INFO_COLS if c in match]], on="login", how="left")
    a["nom_affiche"] = a["nom_affiche"].fillna(a["nom_source"])
    a["agent_label"] = a["nom_affiche"].astype(str) + " — " + a["login"].astype(str)
    return a


def _excess(slots: pd.DataFrame, allowed_s: float) -> pd.Series:
    """Secondes de dépassement cumulé par ligne (ordre chronologique par agent et par jour)."""
    cum_after = slots.groupby(["date", "login"])["sec_regle"].cumsum()
    cum_before = cum_after - slots["sec_regle"]
    return np.maximum(0, cum_after - np.maximum(allowed_s, cum_before))


def build_dataset(parsed: ParsedPauses, match: pd.DataFrame, rules: Rules,
                  rh_headcount: int | None = None) -> Dataset:
    agents = agent_directory(parsed, match)
    info = agents.drop_duplicates("login")[["login", "nom_affiche", "nom", "prenom", "matricule", "equipe",
                                            "superviseur", "statut_rapprochement"]]
    s = parsed.slots.copy()
    s["type_pause"] = s["type_pause"].astype(str)
    s = s.merge(info, on="login", how="left")
    s["nom_affiche"] = s["nom_affiche"].fillna(s["login"])
    s["est_regle"] = s["type_pause"].isin(rules.types_regles)
    s["sec_regle"] = np.where(s["est_regle"], s["seconds"], 0.0)
    s = s.sort_values(["date", "login", "slot_start_min", "type_pause"]).reset_index(drop=True)
    allowed = rules.duree_max_cumulee_min * 60 if rules.duree_max_cumulee_min > 0 else np.inf
    s["exces_s"] = _excess(s, allowed) if len(s) else 0.0
    s["heure"] = (s["slot_start_min"] // 60).astype(int)
    s["minute"] = (s["slot_start_min"] % 60).astype(int)
    s["tranche_30min"] = s["slot_start_min"].map(tranche_label)

    # ── blocs
    if len(s):
        if parsed.layout == "tabulaire" and "event_id" in s and s["event_id"].notna().any():
            blocs = _blocs_from_events(s, parsed.events)
        else:
            idx = (s["slot_start_min"] // SLOT_MIN)
            key = ["date", "login", "type_pause"]
            s["_o"] = s.sort_values(key + ["slot_start_min"]).groupby(key).cumcount()
            ss = s.sort_values(key + ["slot_start_min"])
            ss["_grp"] = (ss.groupby(key)["slot_start_min"].diff().fillna(0) != SLOT_MIN).astype(int)
            ss["_grp"] = ss["_grp"].where(ss.groupby(key).cumcount() > 0, 1)
            ss["bloc_id"] = ss["_grp"].cumsum()
            s["bloc_id"] = ss["bloc_id"].reindex(s.index)
            blocs = (ss.groupby("bloc_id").agg(
                date=("date", "first"), login=("login", "first"), type_pause=("type_pause", "first"),
                debut_min=("slot_start_min", "min"), fin_min=("slot_start_min", lambda x: x.max() + SLOT_MIN),
                duree_s=("seconds", "sum"), nb_creneaux=("slot_start_min", "count"),
                exces_cumule_s=("exces_s", "sum"), est_regle=("est_regle", "first")).reset_index())
            blocs["precision_horaire"] = "Créneaux (plage couvrante)"
        s = s.drop(columns=[c for c in ("_o",) if c in s])
    else:
        blocs = pd.DataFrame(columns=["bloc_id", "date", "login", "type_pause", "debut_min", "fin_min", "duree_s",
                                      "nb_creneaux", "exces_cumule_s", "est_regle", "precision_horaire"])
    blocs = blocs.merge(info, on="login", how="left")
    blocs["nom_affiche"] = blocs["nom_affiche"].fillna(blocs["login"])
    blocs["micro"] = blocs["duree_s"] < rules.bloc_min_s
    lim = rules.duree_max_par_pause_min * 60
    blocs["exces_bloc_s"] = np.where(blocs["est_regle"] & (lim > 0), np.maximum(0, blocs["duree_s"] - lim), 0.0)
    blocs["depassement_s"] = np.maximum(blocs["exces_cumule_s"].where(blocs["est_regle"], 0), blocs["exces_bloc_s"])
    blocs["statut_pause"] = np.select([~blocs["est_regle"], blocs["depassement_s"] > 0],
                                      ["Hors règle", "Dépassement"], "Normale")
    blocs["heure_debut"] = blocs["debut_min"].map(lambda m: slot_label(m) if pd.notna(m) else "")
    blocs["heure_fin"] = blocs["fin_min"].map(lambda m: slot_label(m) if pd.notna(m) else "")
    blocs["duree_minutes"] = (blocs["duree_s"] / 60).round(2)
    blocs["depassement_minutes"] = (blocs["depassement_s"] / 60).round(2)
    blocs["tranche_30min"] = blocs["debut_min"].map(lambda m: tranche_label(m // SLOT_MIN * SLOT_MIN) if pd.notna(m) else "")

    # ── agents / jour
    reg = s[s["est_regle"]]
    g_reg = reg.groupby(["date", "login"]).agg(pause_regle_s=("seconds", "sum"), exces_cumule_s=("exces_s", "sum"))
    br = blocs[blocs["est_regle"] & ~blocs["micro"]].groupby(["date", "login"]).agg(
        nb_pauses_regle=("bloc_id", "count"), exces_bloc_s=("exces_bloc_s", "sum"))
    g_all = s.groupby(["date", "login"]).agg(pause_totale_s=("seconds", "sum"), nb_creneaux=("seconds", "count"))
    ad = (agents.merge(g_all, on=["date", "login"], how="left").merge(g_reg, on=["date", "login"], how="left")
          .merge(br, on=["date", "login"], how="left"))
    for c in ("pause_totale_s", "nb_creneaux", "pause_regle_s", "exces_cumule_s", "nb_pauses_regle", "exces_bloc_s"):
        ad[c] = ad[c].fillna(0)
    ad["temps_autorise_s"] = rules.duree_max_cumulee_min * 60 if rules.duree_max_cumulee_min > 0 else np.nan
    ad["exces_nb"] = np.maximum(0, ad["nb_pauses_regle"] - rules.nb_max_pauses) if rules.nb_max_pauses > 0 else 0
    motifs = pd.DataFrame({
        "Durée cumulée": ad["exces_cumule_s"] > 0,
        "Durée d'une pause": ad["exces_bloc_s"] > 0,
        "Nombre de pauses": ad["exces_nb"] > 0})
    ad["en_depassement"] = motifs.any(axis=1)
    ad["motifs"] = motifs.apply(lambda r: ", ".join(k for k, v in r.items() if v), axis=1)
    types = sorted(parsed.slots["type_pause"].astype(str).unique())
    return Dataset(s, blocs, ad, rules, types, rh_headcount,
                   has_team=bool(agents["equipe"].fillna("").astype(str).str.len().gt(0).any()),
                   has_sup=bool(agents["superviseur"].fillna("").astype(str).str.len().gt(0).any()))


def _blocs_from_events(s: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    """Fichiers tabulaires : un bloc = une pause du fichier, avec ses horaires EXACTS."""
    e = events.rename(columns={"event_id": "bloc_id"}).copy()
    ex = s.groupby("event_id").agg(exces_cumule_s=("exces_s", "sum"), est_regle=("est_regle", "first"),
                                   nb_creneaux=("slot_start_min", "count"))
    s["bloc_id"] = s["event_id"]
    e = e.merge(ex, left_on="bloc_id", right_index=True, how="left")
    e["precision_horaire"] = "Exacte (début/fin du fichier)"
    return e[["bloc_id", "date", "login", "type_pause", "debut_min", "fin_min", "duree_s", "nb_creneaux",
              "exces_cumule_s", "est_regle", "precision_horaire"]]


# ───────────────────────── filtres ─────────────────────────
@dataclass
class Filters:
    dates: tuple = ()
    equipes: tuple = ()
    superviseurs: tuple = ()
    logins: tuple = ()
    types: tuple = ()
    plage: tuple = (0, 1440)
    statut: str = "Tous"           # Tous | En dépassement | Normal


@dataclass
class View:
    slots: pd.DataFrame
    blocs: pd.DataFrame
    agents: pd.DataFrame
    flt: Filters


def apply_filters(ds: Dataset, f: Filters) -> View:
    a = ds.agents
    if f.dates:
        a = a[a["date"].isin(f.dates)]
    if f.equipes:
        a = a[a["equipe"].isin(f.equipes)]
    if f.superviseurs:
        a = a[a["superviseur"].isin(f.superviseurs)]
    if f.logins:
        a = a[a["login"].isin(f.logins)]
    if f.statut == "En dépassement":
        a = a[a["en_depassement"]]
    elif f.statut == "Normal":
        a = a[~a["en_depassement"]]
    keys = a[["date", "login"]].drop_duplicates()
    s = ds.slots.merge(keys, on=["date", "login"], how="inner")
    b = ds.blocs.merge(keys, on=["date", "login"], how="inner")
    if f.types:
        s, b = s[s["type_pause"].isin(f.types)], b[b["type_pause"].isin(f.types)]
    lo, hi = f.plage
    s = s[(s["slot_start_min"] >= lo) & (s["slot_start_min"] + SLOT_MIN <= hi)]
    b = b[(b["debut_min"] >= lo) & (b["debut_min"] < hi)]
    return View(s.reset_index(drop=True), b.reset_index(drop=True), a.reset_index(drop=True), f)


# ───────────────────────── simultanéité ─────────────────────────
def simultaneity(view: View, rules: Rules, rh_headcount: int | None = None) -> pd.DataFrame:
    """Une ligne par (date, créneau). Colonnes : equiv_agents, agents_distincts, effectif, pct, depasse."""
    s, a = view.slots, view.agents
    if s.empty:
        return pd.DataFrame(columns=["date", "slot_start_min", "tranche", "agents_distincts", "equiv_agents",
                                     "effectif", "pct", "depasse", "retenu"])
    g = s.groupby(["date", "slot_start_min"]).agg(sec=("seconds", "sum"), agents_distincts=("login", "nunique")).reset_index()
    g["equiv_agents"] = g["sec"] / SLOT_SEC
    base = rules.base_simultaneite
    if base == "presents" and a[["arrivee_min", "depart_min"]].notna().all(axis=1).sum() == 0:
        base = "fichier"
    eff = []
    for d, grp in g.groupby("date"):
        if base == "presents":
            ar = a[(a["date"] == d)].dropna(subset=["arrivee_min", "depart_min"])
            st = grp["slot_start_min"].to_numpy()
            n = ((ar["arrivee_min"].to_numpy(float)[:, None] < st[None, :] + SLOT_MIN)
                 & (ar["depart_min"].to_numpy(float)[:, None] > st[None, :])).sum(axis=0)
            eff.append(pd.Series(n, index=grp.index))
        elif base == "rh" and rh_headcount:
            eff.append(pd.Series(rh_headcount, index=grp.index))
        else:
            eff.append(pd.Series((a["date"] == d).sum(), index=grp.index))
    g["effectif"] = pd.concat(eff).reindex(g.index).astype(float)
    num = g["equiv_agents"] if rules.mesure_simultaneite == "moyenne" else g["agents_distincts"]
    g["pct"] = np.where(g["effectif"] > 0, num / g["effectif"].where(g["effectif"] > 0) * 100, np.nan)
    g["retenu"] = g["effectif"] >= (rules.effectif_min_simult if base == "presents" else 1)
    g["depasse"] = g["retenu"] & (rules.simultaneite_max_pct > 0) & (g["pct"] > rules.simultaneite_max_pct)
    g["tranche"] = g["slot_start_min"].map(tranche_label)
    g.attrs["base"] = base
    return g.drop(columns="sec").sort_values(["date", "slot_start_min"]).reset_index(drop=True)


# ───────────────────────── KPI ─────────────────────────
def compute_kpis(view: View, rules: Rules, sim: pd.DataFrame) -> dict:
    n_ag = view.agents["login"].nunique()
    total = view.slots["seconds"].sum()
    blocs = view.blocs[~view.blocs["micro"]]
    dep_agents = view.agents.loc[view.agents["en_depassement"], "login"].nunique()
    peak = sim[sim["retenu"]].sort_values("pct", ascending=False).head(1) if len(sim) else sim
    return dict(
        n_agents=n_ag, total_s=total, avg_s=total / n_ag if n_ag else np.nan,
        exces_s=view.slots["exces_s"].sum(), n_dep=dep_agents,
        pct_dep=dep_agents / n_ag * 100 if n_ag else np.nan, n_pauses=len(blocs),
        peak_pct=float(peak["pct"].iloc[0]) if len(peak) else np.nan,
        peak_hour=peak["tranche"].iloc[0].split(" - ")[0] if len(peak) else "—",
        peak_agents=float(peak["equiv_agents"].iloc[0]) if len(peak) else np.nan,
        n_periodes_dep=int(sim["depasse"].sum()) if len(sim) else 0)


# ───────────────────────── tableaux d'analyse ─────────────────────────
def by_type(view: View) -> pd.DataFrame:
    s, b = view.slots, view.blocs[~view.blocs["micro"]]
    if s.empty:
        return pd.DataFrame(columns=["Type de pause", "Nb pauses (blocs)", "Agents", "Durée totale (min)",
                                     "Durée moyenne / bloc (min)", "% du temps", "Dépassement (min)"])
    g = s.groupby("type_pause").agg(sec=("seconds", "sum"), agents=("login", "nunique"), exc=("exces_s", "sum"))
    g["n"] = b.groupby("type_pause").size()
    g["n"] = g["n"].fillna(0).astype(int)
    out = pd.DataFrame({"Type de pause": g.index, "Nb pauses (blocs)": g["n"].values, "Agents": g["agents"].values,
                        "Durée totale (min)": (g["sec"] / 60).round(1).values,
                        "Durée moyenne / bloc (min)": np.where(g["n"] > 0, g["sec"] / 60 / g["n"].where(g["n"] > 0), np.nan).round(1),
                        "% du temps": (g["sec"] / g["sec"].sum() * 100).round(1).values,
                        "Dépassement (min)": (g["exc"] / 60).round(1).values})
    return out.sort_values("Durée totale (min)", ascending=False).reset_index(drop=True)


def by_slot(view: View) -> pd.DataFrame:
    s, b = view.slots, view.blocs[~view.blocs["micro"]]
    if s.empty:
        return pd.DataFrame(columns=["slot_start_min", "tranche", "minutes", "agents", "blocs_entames", "exces_min"])
    g = s.groupby("slot_start_min").agg(minutes=("seconds", lambda x: x.sum() / 60), agents=("login", "nunique"),
                                         exces_min=("exces_s", lambda x: x.sum() / 60))
    g["blocs_entames"] = b.groupby("debut_min").size().reindex(g.index).fillna(0).astype(int)
    g = g.reindex(range(int(g.index.min()), int(g.index.max()) + SLOT_MIN, SLOT_MIN)).fillna(0).reset_index()
    g = g.rename(columns={"index": "slot_start_min"})
    g["tranche"] = g["slot_start_min"].map(tranche_label)
    return g


def overage_by_agent(view: View) -> pd.DataFrame:
    a = view.agents
    cols = ["Agent", "Login", "Jours analysés", "Jours en dépassement", "Nb pauses", "Temps autorisé (min)",
            "Temps réel (min)", "Dépassement (min)", "Motifs"]
    if a.empty:
        return pd.DataFrame(columns=cols)
    ex = view.slots.groupby("login")["exces_s"].sum()
    g = a.groupby("login").agg(Agent=("nom_affiche", "first"), j=("date", "nunique"), jd=("en_depassement", "sum"),
                               n=("nb_pauses_regle", "sum"), aut=("temps_autorise_s", "sum"),
                               reel=("pause_regle_s", "sum"), motifs=("motifs", lambda x: ", ".join(sorted({m for v in x for m in v.split(", ") if m}))))
    out = pd.DataFrame({"Agent": g["Agent"], "Login": g.index, "Jours analysés": g["j"], "Jours en dépassement": g["jd"].astype(int),
                        "Nb pauses": g["n"].astype(int), "Temps autorisé (min)": (g["aut"] / 60).round(1),
                        "Temps réel (min)": (g["reel"] / 60).round(1),
                        "Dépassement (min)": (ex.reindex(g.index).fillna(0) / 60).round(1), "Motifs": g["motifs"]})
    return out.sort_values(["Dépassement (min)", "Temps réel (min)"], ascending=False).reset_index(drop=True)


def overage_by_day(view: View) -> pd.DataFrame:
    a = view.agents
    if a.empty:
        return pd.DataFrame(columns=["Date", "Agents", "Agents en dépassement", "% agents", "Dépassement (min)"])
    ex = view.slots.groupby("date")["exces_s"].sum()
    g = a.groupby("date").agg(n=("login", "nunique"), d=("en_depassement", "sum"))
    return pd.DataFrame({"Date": g.index, "Agents": g["n"].values, "Agents en dépassement": g["d"].astype(int).values,
                         "% agents": (g["d"] / g["n"] * 100).round(1).values,
                         "Dépassement (min)": (ex.reindex(g.index).fillna(0) / 60).round(1).values})


def overage_by_type(view: View) -> pd.DataFrame:
    s = view.slots
    g = s[s["est_regle"]].groupby("type_pause")["exces_s"].sum() / 60 if len(s) else pd.Series(dtype=float)
    return g.round(1).rename("Dépassement (min)").reset_index().rename(columns={"type_pause": "Type de pause"})


def overage_by_slot(view: View) -> pd.DataFrame:
    bs = by_slot(view)
    return bs[["tranche", "exces_min"]].rename(columns={"tranche": "Tranche", "exces_min": "Dépassement (min)"}) if len(bs) else bs


def to_excel_bytes(sheets: dict[str, pd.DataFrame]) -> bytes:
    from io import BytesIO
    bio = BytesIO()
    with pd.ExcelWriter(bio, engine="openpyxl") as w:
        for name, df in sheets.items():
            d = df.copy()
            for c in d.columns:
                if d[c].map(lambda v: hasattr(v, "year") and not hasattr(v, "hour")).any():
                    d[c] = d[c].astype(str)
            d.to_excel(w, sheet_name=name[:31], index=False)
    return bio.getvalue()
