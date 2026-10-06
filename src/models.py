"""Structures de données échangées entre le chargement, le rapprochement RH et les calculs."""
from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


@dataclass
class ParsedPauses:
    """Résultat de la lecture du fichier de pauses (données OBSERVÉES uniquement).

    layout  : « vocalcom » (rapport par créneaux de 30 min) ou « tabulaire » (une ligne = une pause / un créneau)
    agents  : une ligne par (date, login) — nom_source, arrivee_min, depart_min, pause_resume_s, pause_slots_s…
    slots   : une ligne par (date, login, type_pause, slot_start_min) — seconds observées (+ event_id si exact)
    events  : pauses à horaires exacts (fichiers tabulaires début/fin) — vide pour Vocalcom
    issues  : journal des anomalies (voir validation.ISSUE_COLS)
    meta    : statistiques de lecture (lignes, feuilles, dates…)
    """
    layout: str
    agents: pd.DataFrame
    slots: pd.DataFrame
    events: pd.DataFrame
    issues: pd.DataFrame
    meta: dict = field(default_factory=dict)


@dataclass
class RHData:
    """Base RH normalisée. df = None si aucune colonne login n'a pu être détectée."""
    df: pd.DataFrame | None
    issues: pd.DataFrame
    meta: dict = field(default_factory=dict)
