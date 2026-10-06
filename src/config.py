"""Constantes, règles paramétrables et helpers de formatage."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

SLOT_MIN = 30                      # durée d'un créneau (minutes)
SLOT_SEC = SLOT_MIN * 60           # durée d'un créneau (secondes)
N_SLOTS = 24 * 60 // SLOT_MIN      # créneaux par jour (48)


@dataclass(frozen=True)
class Rules:
    """Règles saisies par l'utilisateur (jamais « officielles »). 0 = règle désactivée.
    L'ordre des champs est celui utilisé par ui.get_context()."""
    types_regles: tuple = ()
    duree_max_cumulee_min: float = 30.0
    nb_max_pauses: int = 8
    duree_max_par_pause_min: float = 0.0
    simultaneite_max_pct: float = 15.0
    base_simultaneite: str = "presents"      # presents | fichier | rh
    mesure_simultaneite: str = "moyenne"     # moyenne | distincts
    effectif_min_simult: int = 5
    bloc_min_s: int = 0                      # blocs plus courts = « micro-pauses » (ignorées du décompte)


def _bad(x) -> bool:
    return x is None or (isinstance(x, (float, np.floating)) and np.isnan(x))


def slot_label(minutes) -> str:
    """Minutes depuis minuit -> « HH:MM » (1440 -> « 24:00 »)."""
    if _bad(minutes):
        return ""
    h, m = divmod(int(round(float(minutes))), 60)
    return f"{h:02d}:{m:02d}"


def tranche_label(minutes) -> str:
    """Début de créneau (minutes) -> « 08:00 - 08:30 »."""
    if _bad(minutes):
        return ""
    return f"{slot_label(minutes)} - {slot_label(float(minutes) + SLOT_MIN)}"


def fmt_int(n) -> str:
    """Entier avec séparateur de milliers (« 1 284 »)."""
    if _bad(n):
        return "—"
    return f"{int(round(float(n))):,}".replace(",", " ")


def fmt_duration(seconds) -> str:
    """Secondes -> « 6 h 48 min » ou « 28 min 15 s »."""
    if _bad(seconds):
        return "—"
    s = int(round(float(seconds)))
    sign = "-" if s < 0 else ""
    h, rem = divmod(abs(s), 3600)
    m, sec = divmod(rem, 60)
    if h:
        return f"{sign}{h} h {m:02d} min"
    if m or sec:
        return f"{sign}{m} min {sec:02d} s" if sec else f"{sign}{m} min"
    return "0 min"


def fmt_ms(seconds) -> str:
    """Secondes -> « 02'37 » (format du rapport Vocalcom) ou « 1h33'01 » au-delà d'une heure."""
    if _bad(seconds):
        return "—"
    s = int(round(float(seconds)))
    h, rem = divmod(abs(s), 3600)
    m, sec = divmod(rem, 60)
    return f"{h}h{m:02d}'{sec:02d}" if h else f"{m:02d}'{sec:02d}"
