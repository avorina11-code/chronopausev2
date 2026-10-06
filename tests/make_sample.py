"""Génère un faux rapport Vocalcom (même structure que le vrai) + une base RH, pour les tests."""
from __future__ import annotations

import numpy as np
import pandas as pd

N = 28  # colonnes du rapport


def _mmss(s: float) -> str:
    return f"{int(s // 60):02d}'{int(s % 60):02d}"


def _hms(s: float) -> str:
    return f"{int(s // 3600)}h{int(s % 3600 // 60):02d}'{int(s % 60):02d}"


def vocalcom_grid(agents: list[dict]) -> pd.DataFrame:
    """agents : [{login, name, arr:(h,m), dep:(h,m), statuses:{label: {slot_start_min: seconds}} | [(label, {...}), …]}]"""
    rows: list[list] = []

    def blank():
        rows.append([np.nan] * N)

    def put(vals: dict):
        r = [np.nan] * N
        for c, v in vals.items():
            r[c] = v
        rows.append(r)

    put({1: "Agents pause report"})
    put({1: "Le 6/10/2026"})
    for _ in range(20):
        blank()
    for ag in agents:
        put({0: f"{ag['login']}: {ag['name']}"})
        blank()
        hdr = {3 + k: lab for k, lab in enumerate([f"{(h if h else 12):02d}:{m:02d}" for h in range(12) for m in (0, 30)])}
        hdr[27] = "Total"
        put(hdr)
        blank()
        total_all = 0.0
        for label, slots in (ag["statuses"] if isinstance(ag["statuses"], list) else list(ag["statuses"].items())):
            am = {k: slots.get(k * 30, 0.0) for k in range(24)}
            pm = {k: slots.get(720 + k * 30, 0.0) for k in range(24)}
            tot = sum(am.values()) + sum(pm.values())
            total_all += tot
            r = {0: label, 3: "a.m."}
            r.update({4 + k: _mmss(v) for k, v in am.items()})           # a.m. : valeurs décalées d'une colonne
            put(r)
            r = {2: "p.m."}
            r.update({3 + k: _mmss(v) for k, v in pm.items()})
            r[27] = _hms(tot)                                              # total sur la ligne p.m.
            put(r)
            blank()
        arr, dep = ag["arr"][0] * 3600 + ag["arr"][1] * 60, ag["dep"][0] * 3600 + ag["dep"][1] * 60
        work = max(0, (dep - arr) - total_all) if ag.get("work") is None else ag["work"]
        put({1: "Résumé"}); blank()
        put({1: f"Trait. total : {_hms(total_all + work)}"}); blank()
        put({1: f"Durée de travail : {_hms(work)}"}); blank()
        put({1: f"Durée de pause : {_hms(total_all)}"}); blank()
        put({1: f"Arrivée-Départ : {ag['arr'][0]:02d}h{ag['arr'][1]:02d}-{ag['dep'][0]:02d}h{ag['dep'][1]:02d}"}); blank()
        blank()
    put({1: "mardi 6 octobre 2026 11:05:27", 18: "Page 1"})
    return pd.DataFrame(rows, dtype=object)


def sample_agents() -> list[dict]:
    return [
        dict(login="1055", name="HERIMAMPIONONA, Rovaniaina Larissa", arr=(10, 18), dep=(19, 0), statuses=[
            ("Pause", {720 + 4 * 30: 157.0}),
            ("Individual Coaching", {600 + 60: 265.0, 690: 964.0}),
            ("Traitement BO", {600: 681.0, 630: 1800.0, 660: 1535.0, 690 + 0: 0.0, **{720 + k * 30: 1800.0 for k in range(5)}}),
        ]),
        dict(login="1098", name="RATOLOJANAHARY, Nina Marie", arr=(7, 18), dep=(16, 0), statuses=[
            ("Pause", {570: 940.0, 600: 331.0, 780: 314.0})]),
        dict(login="1140", name="ANDRIANAVALONA, Fenitra Malala", arr=(9, 23), dep=(20, 2), statuses=[
            ("Pause", {660: 3.0}),                       # deux lignes « Pause » pour le même agent
            ("Pause", {690: 52.0, 750: 261.0, 810: 120.0}),
            ("Sharing time", {690: 329.0, 720: 190.0}),
        ]),
        dict(login="1178", name="DILIMIZONY, Ravaka Lalaina Francia", arr=(6, 58), dep=(7, 33), statuses=[], work=2088),
        dict(login="1859", name="RAHAJARIVELO, Dimbiarijaona", arr=(8, 0), dep=(17, 0), statuses=[
            ("Pause", {600: 900.0, 780: 900.0})]),
    ]


def rh_grid() -> pd.DataFrame:
    rows = [["Matricule_RH", "Login_Vocalcom", "Nom_Prenom"],
            ["CN00001", 1055, "HERIMAMPIONONA Rovaniaina Larissa"],
            ["CN00002", "1098", "RATOLOJANAHARY Nina Marie"],
            ["CN00003", "1140", "ANDRIANAVALONA Fenitra Malala"],
            ["CN00004", "1999", "AUTRE Agent Absent"],
            ["CN01566", np.nan, "RAHAJARIVELO Dimbiarijaona Herizo"],
            ["CN01557", np.nan, "NOMENJANAHARY Solonjatovoheriniaina Mampifaly"]]
    return pd.DataFrame(rows, dtype=object)
