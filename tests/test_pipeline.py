"""Tests du pipeline sur un faux rapport Vocalcom : python tests/test_pipeline.py  (ou pytest)."""
import sys
from io import BytesIO
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import numpy as np
import pandas as pd

from make_sample import rh_grid, sample_agents, vocalcom_grid
from src import calculations as calc
from src import loader, rh_matching
from src.config import Rules, fmt_duration, fmt_ms, slot_label, tranche_label
from src.validation import merge_issues


def _xlsx(grid: pd.DataFrame) -> bytes:
    bio = BytesIO()
    grid.to_excel(bio, header=False, index=False, sheet_name="Feuil1")
    return bio.getvalue()


def load():
    grids = loader.read_grids(_xlsx(vocalcom_grid(sample_agents())), "rapport.xlsx")
    return grids, loader.parse_pause_file(grids, None)


def test_helpers():
    assert slot_label(0) == "00:00" and slot_label(1440) == "24:00" and slot_label(552.4) == "09:12"
    assert tranche_label(480) == "08:00 - 08:30" and tranche_label(1410) == "23:30 - 24:00"
    assert fmt_ms(157) == "02'37" and fmt_ms(5581) == "1h33'01"
    assert fmt_duration(6 * 3600 + 48 * 60) == "6 h 48 min" and fmt_duration(float("nan")) == "—"


def test_parse_vocalcom():
    grids, p = load()
    assert p.layout == "vocalcom"
    assert list(p.agents["login"]) == ["1055", "1098", "1140", "1178", "1859"]
    assert str(p.meta["dates"][0]) == "2026-10-06" and p.meta["generation"] == "06/10/2026 11:05:27"
    # réconciliation Σ créneaux = « Durée de pause » du Résumé, pour tous les agents
    assert ((p.agents["pause_resume_s"] - p.agents["pause_slots_s"]).abs() <= 1).all()
    assert not (p.issues["categorie"] == "Écart de contrôle").any(), p.issues
    a = p.agents.set_index("login")
    assert a.loc["1055", "arrivee_min"] == 10 * 60 + 18 and a.loc["1055", "depart_min"] == 19 * 60
    assert a.loc["1178", "pause_slots_s"] == 0
    s = p.slots
    # a.m. (décalé d'une colonne) : 11'21 à 10:00 ; p.m. : 5 créneaux pleins de 12:00 à 14:00
    bo = s[(s.login == "1055") & (s.type_pause == "Traitement BO")].set_index("slot_start_min")["seconds"]
    assert bo[600] == 681 and bo[630] == 1800 and bo[720] == 1800 and bo[840] == 1800
    # statut répété (deux lignes « Pause » pour 1140) : additionné
    assert s[(s.login == "1140") & (s.type_pause == "Pause") & (s.slot_start_min == 690)]["seconds"].iloc[0] == 52
    assert p.meta["lignes_rejetees"] == 0


def test_rh_matching():
    rh = rh_matching.load_rh({"Base_RH": rh_grid()})
    assert rh.df is not None and rh.meta["n_sans_login"] == 2
    _, p = load()
    m = rh_matching.match_agents(p.agents, rh).set_index("login")
    assert m.loc["1055", "statut_rapprochement"] == "Rapproché (login)" and m.loc["1055", "matricule"] == "CN00001"
    assert m.loc["1178", "statut_rapprochement"] == "Non rapproché"
    assert m.loc["1859", "statut_rapprochement"] == "Suggestion par nom" and m.loc["1859", "suggestion_matricule"] == "CN01566"
    assert m.loc["1859", "matricule"] == ""                                   # suggestion non appliquée par défaut
    m2 = rh_matching.match_agents(p.agents, rh, True).set_index("login")
    assert m2.loc["1859", "matricule"] == "CN01566"                            # appliquée sur demande seulement
    assert set(rh_matching.rh_not_in_pauses(rh, set(m.index))["matricule"]) == {"CN00004", "CN01557"} | {"CN01566"}
    nr = rh_matching.match_agents(p.agents, None)
    assert (nr["statut_rapprochement"] == "Base RH non chargée").all()
    assert len(merge_issues(p.issues, rh.issues)) > 0


def test_calculations():
    rh = rh_matching.load_rh({"Base_RH": rh_grid()})
    _, p = load()
    match = rh_matching.match_agents(p.agents, rh)
    rules = Rules(("Pause",), 30.0, 8, 0.0, 15.0, "presents", "moyenne", 2, 0)
    ds = calc.build_dataset(p, match, rules, 6)
    v = calc.apply_filters(ds, calc.Filters())
    sim = calc.simultaneity(v, rules, 6)
    k = calc.compute_kpis(v, rules, sim)
    assert k["n_agents"] == 5 and k["total_s"] == p.slots["seconds"].sum()
    ag = ds.agents.set_index("login")
    # 1098 : Pause 940+331+314 = 1585 s ; limite 1800 s -> pas de dépassement ; 1859 : 1800 s -> pile à la limite
    assert ag.loc["1098", "pause_regle_s"] == 1585 and ag.loc["1098", "exces_cumule_s"] == 0
    # 1140 : 3 + 52+261+120 = 436 s -> pas de dépassement
    assert not ag.loc["1140", "en_depassement"]
    # durcir la règle : 20 min -> 1098 (26 min 25 s) dépasse de 385 s
    r2 = Rules(("Pause",), 20.0, 8, 0.0, 15.0, "presents", "moyenne", 2, 0)
    ds2 = calc.build_dataset(p, match, r2, 6)
    a2 = ds2.agents.set_index("login")
    assert a2.loc["1098", "exces_cumule_s"] == 1585 - 1200 and a2.loc["1098", "en_depassement"]
    v2 = calc.apply_filters(ds2, calc.Filters())
    assert v2.slots["exces_s"].sum() == a2["exces_cumule_s"].sum()
    for fn in (calc.by_type, calc.by_slot, calc.overage_by_agent, calc.overage_by_day, calc.overage_by_type, calc.overage_by_slot):
        assert isinstance(fn(v2), pd.DataFrame)
    assert len(calc.to_excel_bytes({"Pauses": ds2.blocs, "Agents": ds2.agents})) > 1000
    # filtre plage horaire et statut
    vf = calc.apply_filters(ds2, calc.Filters(plage=(600, 720), statut="En dépassement"))
    assert set(vf.agents["login"]) == {"1098", "1859"} and vf.slots["slot_start_min"].between(600, 690).all()
    assert a2.loc["1859", "exces_cumule_s"] == 600
    assert (sim["pct"].dropna() >= 0).all() and sim.attrs["base"] == "presents"


def test_tabular_events():
    rows = [["Login", "Agent", "Date", "Début pause", "Fin pause", "Type pause"],
            ["1055", "HERI Larissa", "06/10/2026", "09:12", "09:24", "Pause"],
            ["1055", "HERI Larissa", "06/10/2026", "09:45", "10:10", "Pause repas"],
            ["1055", "HERI Larissa", "06/10/2026", "09:12", "09:24", "Pause"],        # doublon
            ["1098", "RATO Nina", "06/10/2026", "11:30", "11:20", "Pause"],            # fin < début
            ["", "X", "06/10/2026", "08:00", "08:10", "Pause"],                        # login manquant
            ["1098", "RATO Nina", "", "08:00", "08:10", "Pause"]]                      # date manquante
    grids = {"S": pd.DataFrame(rows, dtype=object)}
    info = loader.inspect_pause_file(grids)
    assert info["layout"] == "tabulaire" and info["header_row"] == 0
    p = loader.parse_pause_file(grids, None, "S", 0, None)
    assert p.meta["lignes_exploitables"] == 2 and p.meta["lignes_rejetees"] == 4
    cats = set(p.issues["categorie"])
    assert {"Doublon", "Horaire invalide", "Date manquante", "Valeur invalide"} <= cats
    p2 = loader.parse_pause_file(grids, __import__("datetime").date(2026, 10, 6), "S", 0, None)
    assert p2.meta["lignes_exploitables"] == 3
    assert p.events["duree_s"].tolist() == [720, 1500]
    # 09:45 -> 10:10 : 15 min dans le créneau 09:30 et 10 min dans 10:00
    s = p.slots[p.slots.type_pause == "Pause repas"].sort_values("slot_start_min")
    assert s["slot_start_min"].tolist() == [570, 600] and s["seconds"].tolist() == [900, 600]
    match = rh_matching.match_agents(p.agents, None)
    ds = calc.build_dataset(p, match, Rules(("Pause",)), None)
    assert (ds.blocs["precision_horaire"] == "Exacte (début/fin du fichier)").all() and len(ds.blocs) == 2


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("OK ", name)
