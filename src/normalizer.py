"""Normalisation : synonymes de colonnes + parseurs tolérants (login, date, heure, durée, créneau, noms).

Principe : un parseur renvoie NaN/None pour une cellule VIDE et lève ValueError pour une cellule
NON INTERPRÉTABLE — l'appelant consigne alors l'anomalie au lieu de supprimer la valeur en silence.
"""
from __future__ import annotations

import datetime as dt
import math
import re
import unicodedata
from difflib import SequenceMatcher

import numpy as np
import pandas as pd

# ───────────────────────── synonymes de colonnes ─────────────────────────
PAUSE_SYNONYMS = {
    "login": ["login", "login agent", "login vocalcom", "user", "username", "user name", "identifiant", "id agent",
              "id", "code agent", "agent id", "utilisateur", "matricule vocalcom"],
    "nom_source": ["agent", "nom", "nom agent", "nom prenom", "nom et prenom", "name", "collaborateur", "conseiller",
                   "nom de l agent", "agent name"],
    "date": ["date", "jour", "day", "date pause", "date de la pause"],
    "heure_debut": ["heure debut", "heure de debut", "debut", "debut pause", "start", "start time", "begin",
                    "heure debut pause", "h debut", "heure start"],
    "heure_fin": ["heure fin", "heure de fin", "fin", "fin pause", "end", "end time", "stop", "heure fin pause",
                  "h fin", "heure end"],
    "duree": ["duree", "duree pause", "duree de la pause", "duration", "temps", "temps de pause", "duree s",
              "duree min", "duree minutes"],
    "type_pause": ["type pause", "type de pause", "type", "pause", "statut", "status", "motif", "raison",
                   "code pause", "etat", "reason", "pause type"],
    "tranche": ["tranche", "tranche 30 min", "tranche horaire", "creneau", "creneau horaire", "slot", "plage",
                "plage horaire", "tranche de 30 min"],
}

RH_SYNONYMS = {
    "login": ["login", "login vocalcom", "login agent", "id vocalcom", "identifiant", "user", "username",
              "id agent", "login vocal"],
    "matricule": ["matricule", "matricule rh", "mat", "id rh", "employee id", "numero employe", "code employe",
                  "matricule employe"],
    "nom_prenom": ["nom prenom", "nom et prenom", "nom prenoms", "nom complet", "agent", "collaborateur",
                   "employe", "name", "full name", "nom  prenom"],
    "nom": ["nom", "last name", "lastname", "family name"],
    "prenom": ["prenom", "prenoms", "first name", "firstname"],
    "equipe": ["equipe", "team", "groupe", "service", "campagne", "projet", "plateau"],
    "superviseur": ["superviseur", "supervisor", "manager", "responsable", "chef d equipe", "team leader", "tl",
                    "n+1"],
}


def strip_accents(s: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", s) if not unicodedata.combining(c))


def clean_text(v) -> str:
    """Cellule -> texte propre (NaN -> '', espaces insécables et multiples réduits)."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return ""
    try:
        if pd.isna(v):
            return ""
    except (TypeError, ValueError):
        pass
    return re.sub(r"\s+", " ", str(v).replace("\xa0", " ")).strip()


def norm_text(v) -> str:
    """Minuscules, sans accents ni ponctuation : « Heure début » -> « heure debut »."""
    s = strip_accents(clean_text(v)).lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9+]+", " ", s)).strip()


def auto_map_columns(columns, synonyms: dict) -> dict:
    """Associe chaque champ standard à une colonne du fichier. Retourne {champ: nom_colonne}.
    Passe 1 : égalité exacte (après normalisation). Passe 2 : tous les mots du synonyme présents dans la colonne.
    Une colonne n'est affectée qu'à un seul champ."""
    cols = [(c, norm_text(c)) for c in columns if clean_text(c)]
    out, used = {}, set()
    for fld, syns in synonyms.items():
        ns = {norm_text(s) for s in syns}
        for c, n in cols:
            if c not in used and n in ns:
                out[fld] = c
                used.add(c)
                break
    for fld, syns in synonyms.items():
        if fld in out:
            continue
        for syn in sorted({norm_text(s) for s in syns}, key=len, reverse=True):
            words = set(syn.split())
            hit = next((c for c, n in cols if c not in used and words and words <= set(n.split())), None)
            if hit is not None:
                out[fld] = hit
                used.add(hit)
                break
    return out


# ───────────────────────── login ─────────────────────────
def norm_login(v) -> str:
    """Login en texte : 1055, 1055.0 et ' 1055 ' donnent « 1055 »."""
    if v is None:
        return ""
    if isinstance(v, (int, np.integer)):
        return str(int(v))
    if isinstance(v, (float, np.floating)):
        if math.isnan(v):
            return ""
        return str(int(v)) if float(v).is_integer() else str(v)
    s = clean_text(v)
    if re.fullmatch(r"\d+\.0+", s):
        s = s.split(".")[0]
    return s


def login_key(v) -> str:
    """Clé de rapprochement : minuscules, sans zéros de tête pour les logins numériques."""
    s = norm_login(v).lower()
    return (s.lstrip("0") or "0") if s.isdigit() else s


# ───────────────────────── dates ─────────────────────────
def parse_date(v, default: dt.date | None = None):
    """Cellule -> datetime.date. Vide -> default (ou None). Illisible -> ValueError."""
    if v is None or (isinstance(v, float) and math.isnan(v)) or clean_text(v) == "":
        return default
    if isinstance(v, pd.Timestamp):
        return v.date()
    if isinstance(v, dt.datetime):
        return v.date()
    if isinstance(v, dt.date):
        return v
    if isinstance(v, (int, float, np.integer, np.floating)):
        if 20000 < float(v) < 80000:                       # numéro de série Excel
            return (dt.datetime(1899, 12, 30) + dt.timedelta(days=float(v))).date()
        raise ValueError(f"date illisible : {v!r}")
    s = clean_text(v)
    m = re.search(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})", s)
    if m:
        return _mk_date(int(m[1]), int(m[2]), int(m[3]), s)
    m = re.search(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})", s)
    if m:
        y = int(m[3])
        y += 2000 if y < 100 else 0
        return _mk_date(y, int(m[2]), int(m[1]), s)           # jour d'abord (format français)
    raise ValueError(f"date illisible : {s!r}")


def _mk_date(y: int, mo: int, d: int, raw: str) -> dt.date:
    try:
        return dt.date(y, mo, d)
    except ValueError as e:
        raise ValueError(f"date invalide : {raw!r}") from e


# ───────────────────────── heures ─────────────────────────
def parse_time_min(v) -> float:
    """Cellule -> minutes depuis minuit (float). Vide -> NaN. Illisible -> ValueError.
    Accepte time/datetime, fraction de jour Excel, « 08:15 », « 08:15:30 », « 8h15 », « 08:15 PM »."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return float("nan")
    if isinstance(v, (dt.datetime, pd.Timestamp)):
        return v.hour * 60 + v.minute + v.second / 60
    if isinstance(v, dt.time):
        return v.hour * 60 + v.minute + v.second / 60
    if isinstance(v, (int, float, np.integer, np.floating)):
        f = float(v)
        if 0 <= f < 1:
            return f * 1440
        raise ValueError(f"heure illisible : {v!r}")
    s = clean_text(v).lower()
    if not s:
        return float("nan")
    m = re.fullmatch(r"(\d{1,2})\s*(?:[:h])\s*(\d{1,2})(?:\s*[:m']\s*(\d{1,2}))?\s*(am|pm|a\.m\.|p\.m\.)?", s)
    if not m:
        raise ValueError(f"heure illisible : {s!r}")
    h, mi, sec = int(m[1]), int(m[2]), int(m[3] or 0)
    if m[4]:
        pm = m[4].startswith("p")
        h = (h % 12) + (12 if pm else 0)
    if h > 24 or mi > 59 or sec > 59 or (h == 24 and (mi or sec)):
        raise ValueError(f"heure hors limites : {s!r}")
    return h * 60 + mi + sec / 60


def parse_slot_start(v) -> float:
    """Tranche (« 08:00 - 08:30 », « 08:00 », time…) -> début de créneau en minutes (multiple de 30)."""
    if v is None or (isinstance(v, float) and math.isnan(v)) or clean_text(v) == "":
        return float("nan")
    if isinstance(v, (dt.time, dt.datetime, pd.Timestamp, float, int, np.floating, np.integer)):
        t = parse_time_min(v)
    else:
        s = clean_text(v)
        first = re.split(r"\s*(?:-|–|—|à|a|au)\s*(?=\d)", s, maxsplit=1)[0]
        t = parse_time_min(first)
    return float(int(t // 30) * 30)


# ───────────────────────── durées ─────────────────────────
def parse_duration_s(v, numeric_unit: str = "min") -> float:
    """Cellule -> secondes (float). Vide -> NaN. Illisible -> ValueError.

    Formats : « 02'37 » (mm'ss), « 0h02'37 » (h m' s), « 1:02:37 » (h:m:s), « 12:30 » (m:s — hypothèse),
    « 1h30 », « 45 s », « 12 min », time/timedelta Excel, fraction de jour (0<x<1).
    Un nombre brut est interprété en `numeric_unit` (« min » par défaut, ou « s »)."""
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return float("nan")
    if isinstance(v, pd.Timedelta):
        return v.total_seconds()
    if isinstance(v, dt.timedelta):
        return v.total_seconds()
    if isinstance(v, (dt.datetime, pd.Timestamp)):
        return v.hour * 3600 + v.minute * 60 + v.second
    if isinstance(v, dt.time):
        return v.hour * 3600 + v.minute * 60 + v.second
    if isinstance(v, (int, float, np.integer, np.floating)):
        f = float(v)
        if f == 0:
            return 0.0
        if 0 < f < 1:
            return f * 86400
        return f * (60 if numeric_unit == "min" else 1)
    s = clean_text(v).lower().replace("’", "'").replace("´", "'")
    if not s:
        return float("nan")
    if (m := re.fullmatch(r"(\d+)\s*h\s*(\d{1,2})\s*'\s*(\d{1,2})\s*(?:\"|'')?", s)):
        return int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3])
    if (m := re.fullmatch(r"(\d+)\s*'\s*(\d{1,2})\s*(?:\"|'')?", s)):
        return int(m[1]) * 60 + int(m[2])
    if (m := re.fullmatch(r"(\d+):(\d{2}):(\d{2})", s)):
        return int(m[1]) * 3600 + int(m[2]) * 60 + int(m[3])
    if (m := re.fullmatch(r"(\d+):(\d{2})", s)):
        return int(m[1]) * 60 + int(m[2])
    if (m := re.fullmatch(r"(\d+)\s*h\s*(\d{1,2})?\s*(?:min|m)?", s)):
        return int(m[1]) * 3600 + int(m[2] or 0) * 60
    if (m := re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*(?:s|sec|secondes?)", s)):
        return float(m[1].replace(",", "."))
    if (m := re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*(?:min|mn|m|minutes?)", s)):
        return float(m[1].replace(",", ".")) * 60
    if re.fullmatch(r"\d+(?:[.,]\d+)?", s):
        return float(s.replace(",", ".")) * (60 if numeric_unit == "min" else 1)
    raise ValueError(f"durée illisible : {s!r}")


# ───────────────────────── noms ─────────────────────────
def split_name(full: str) -> tuple[str, str]:
    """« HERIMAMPIONONA, Rovaniaina Larissa » ou « HERIMAMPIONONA Rovaniaina Larissa » -> (NOM, Prénom)."""
    s = clean_text(full)
    if not s:
        return "", ""
    if "," in s:
        a, b = s.split(",", 1)
        return clean_text(a), clean_text(b)
    toks = s.split(" ")
    nom = []
    for t in toks:
        letters = re.sub(r"[^A-Za-zÀ-ÿ]", "", t)
        if letters and letters == letters.upper():
            nom.append(t)
        else:
            break
    if not nom:                       # aucun mot en majuscules : 1er mot = nom
        nom = toks[:1]
    elif len(nom) == len(toks) and len(toks) > 1:   # tout en majuscules : ambigu -> 1er mot = nom
        nom = toks[:1]
    return " ".join(nom), " ".join(toks[len(nom):])


def display_name(nom: str, prenom: str) -> str:
    return clean_text(f"{nom} {prenom}")


def name_tokens(s: str) -> list[str]:
    return [t for t in norm_text(s).split() if len(t) >= 2]


def _tok_eq(a: str, b: str) -> bool:
    return a == b or (min(len(a), len(b)) >= 5 and SequenceMatcher(None, a, b).ratio() >= 0.88)


def name_overlap(a: str, b: str) -> tuple[int, int]:
    """(nombre de mots communs, taille du plus petit nom) — tolère de petites fautes de frappe."""
    ta, tb = name_tokens(a), name_tokens(b)
    if not ta or not tb:
        return 0, 0
    pool, hits = list(tb), 0
    for t in ta:
        k = next((i for i, u in enumerate(pool) if _tok_eq(t, u)), None)
        if k is not None:
            hits += 1
            pool.pop(k)
    return hits, min(len(ta), len(tb))


def names_compatible(a: str, b: str, strict: bool = False) -> bool:
    """strict (suggestions) : ≥ 2 mots communs et le plus court nom entièrement contenu dans l'autre.
    souple (contrôle d'un rapprochement par login) : au moins un mot de ≥ 3 lettres en commun."""
    hits, small = name_overlap(a, b)
    if strict:
        return hits >= 2 and hits == small
    return hits >= 1
