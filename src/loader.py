"""Lecture du fichier de pauses.

Deux structures sont reconnues automatiquement :

1. « vocalcom » — rapport Vocalcom « Agents pause report » (créneaux de 30 min, un bloc par agent) :

       1055: NOM, Prénom                                   ← ligne agent (login : nom)
                 12:00 12:30 01:00 … 11:30 Total           ← en-tête des créneaux
       Pause     a.m.  00'00 00'00 … 00'00                 ← statut : 24 créneaux du matin
                 p.m.  00'00 02'37 … 00'00 0h02'37         ← 24 créneaux de l'après-midi + Total
       …
       Résumé  / Trait. total / Durée de travail / Durée de pause / Arrivée-Départ : 07h03-16h04

   Particularité du rapport (vérifiée par réconciliation avec les totaux) : le libellé « a.m. » occupe une
   colonne de plus que « p.m. » ; les valeurs d'une ligne commencent donc TOUJOURS une colonne après son
   libellé. Seule la ligne « p.m. » porte le total du statut (colonne qui suit les 24 créneaux).
   Contrôle : Σ des créneaux = « Durée de pause » du Résumé (page « Qualité des données »).

2. « tabulaire » — une ligne par pause (heure début / heure fin) ou par créneau (tranche + durée), avec
   détection automatique des colonnes (ou mapping manuel dans l'interface).

DONNÉE OBSERVÉE uniquement ici : aucune durée n'est inventée.
"""
from __future__ import annotations

import datetime as dt
import re
from io import BytesIO, StringIO

import numpy as np
import pandas as pd

from . import cleaner
from .config import SLOT_MIN
from .models import ParsedPauses
from .normalizer import (PAUSE_SYNONYMS, auto_map_columns, clean_text, norm_login, parse_date, parse_duration_s,
                         parse_slot_start, parse_time_min, strip_accents)
from .validation import (CAT_DATE_INV, CAT_DATE_MANQ, CAT_DOUBLON, CAT_ECART, CAT_HORAIRE, CAT_INCOHERENT,
                         CAT_VALEUR, IssueLog)

SRC = "Pauses"
AGENT_RE = re.compile(r"^\s*(\d+)\s*:\s*(.*\S)?\s*$")
AMPM_RE = re.compile(r"^([ap])\.?\s?m\.?$", re.I)
N_HALF = 24                                   # créneaux par ligne a.m. / p.m.
MONTHS = {"janvier": 1, "fevrier": 2, "mars": 3, "avril": 4, "mai": 5, "juin": 6, "juillet": 7, "aout": 8,
          "septembre": 9, "octobre": 10, "novembre": 11, "decembre": 12}

AGENT_COLS = ["date", "login", "nom_source", "arrivee_min", "depart_min", "pause_resume_s", "pause_slots_s",
              "trait_total_s", "travail_s", "ligne_source"]
SLOT_COLS = ["date", "login", "type_pause", "slot_start_min", "seconds"]
EVENT_COLS = ["event_id", "date", "login", "type_pause", "debut_min", "fin_min", "duree_s"]


# ───────────────────────── lecture brute ─────────────────────────
def read_grids(content: bytes, name: str = "") -> dict[str, pd.DataFrame]:
    """Octets Excel -> {feuille: grille brute (sans en-tête, cellules telles quelles)}.
    Le type réel est reconnu par la signature du fichier, pas par l'extension (un « .xls » peut être un .xlsx)."""
    head = content[:8]
    if head.startswith(b"PK"):
        engine = "openpyxl"
    elif head.startswith(b"\xd0\xcf\x11\xe0"):
        engine = "xlrd"
    else:
        return _read_text_like(content, name)
    try:
        grids = pd.read_excel(BytesIO(content), sheet_name=None, header=None, dtype=object, engine=engine)
    except ImportError as e:
        raise RuntimeError("Lecture impossible : module manquant (ajoutez « xlrd » pour les .xls, « openpyxl » pour "
                           f"les .xlsx dans requirements.txt). Détail : {e}") from e
    return {str(k): v for k, v in grids.items()}


def _read_text_like(content: bytes, name: str) -> dict[str, pd.DataFrame]:
    text = content.decode("utf-8", errors="replace")
    if "<table" in text.lower():
        try:
            tables = pd.read_html(StringIO(text), header=None)
        except Exception as e:  # noqa: BLE001
            raise RuntimeError(f"Fichier HTML déguisé en Excel illisible : {e}") from e
        return {f"Table{i + 1}": t.astype(object) for i, t in enumerate(tables)}
    try:
        df = pd.read_csv(StringIO(text), sep=None, engine="python", header=None, dtype=object)
    except Exception as e:  # noqa: BLE001
        raise RuntimeError(f"Format de fichier non reconnu ({name or 'sans nom'}) : {e}") from e
    return {"Feuille1": df}


# ───────────────────────── détection de structure ─────────────────────────
def _is_vocalcom(grid: pd.DataFrame) -> bool:
    if grid.empty:
        return False
    sub = grid.iloc[:, :6].map(clean_text)
    has_agent = sub.iloc[:, :2].apply(lambda c: c.str.match(AGENT_RE)).to_numpy().any()
    has_ampm = sub.apply(lambda c: c.str.match(AMPM_RE)).to_numpy().any()
    has_resume = sub.iloc[:, :3].apply(lambda c: c.map(lambda t: strip_accents(t).lower() == "resume")).to_numpy().any()
    return bool(has_agent and has_ampm and has_resume)


def inspect_pause_file(grids: dict[str, pd.DataFrame]) -> dict:
    """{'layout': 'vocalcom'|'tabulaire', 'sheet': feuille, 'header_row': index base 0}."""
    for name, g in grids.items():
        if _is_vocalcom(g):
            return {"layout": "vocalcom", "sheet": name, "header_row": 0}
    best = max(grids, key=lambda k: int(grids[k].map(lambda v: clean_text(v) != "").to_numpy().sum()))
    return {"layout": "tabulaire", "sheet": best, "header_row": cleaner.detect_header_row(grids[best])}


def parse_pause_file(grids: dict[str, pd.DataFrame], default_date: dt.date | None = None, sheet: str | None = None,
                     header_row: int | None = None, mapping: dict | None = None) -> ParsedPauses:
    info = inspect_pause_file(grids)
    if info["layout"] == "vocalcom":
        return _parse_vocalcom(grids, info["sheet"], default_date)
    sheet = sheet or info["sheet"]
    header_row = info["header_row"] if header_row is None else int(header_row)
    return _parse_tabular(grids, sheet, header_row, mapping, default_date)


# ───────────────────────── utilitaires ─────────────────────────
def _col_letter(i: int) -> str:
    s, i = "", i + 1
    while i:
        i, r = divmod(i - 1, 26)
        s = chr(65 + r) + s
    return s


def _find_report_date(grid: pd.DataFrame, issues: IssueLog):
    """Date du rapport : première cellule des 40 premières lignes contenant une date numérique (« Le 6/10/2026 »)."""
    for i in range(min(40, len(grid))):
        for v in grid.iloc[i].tolist():
            if isinstance(v, (dt.datetime, pd.Timestamp, dt.date)):
                return parse_date(v)
            t = clean_text(v)
            found = re.findall(r"\d{1,2}[/.-]\d{1,2}[/.-]\d{2,4}", t) if t else []
            if found:
                dates = []
                for f in found:
                    try:
                        dates.append(parse_date(f))
                    except ValueError:
                        issues.add("Erreur", CAT_DATE_INV, f"Date illisible dans l'en-tête du rapport : « {f} »",
                                   "Date ignorée", ref=i + 1)
                if len(set(dates)) > 1:
                    issues.add("Avertissement", CAT_INCOHERENT,
                               f"Le rapport semble couvrir plusieurs jours ({t}).",
                               "Première date retenue ; vérifier le fichier", ref=i + 1)
                if dates:
                    return dates[0]
    return None


def _find_generation(grid: pd.DataFrame) -> str | None:
    """« mardi 6 octobre 2026 11:05:27 » -> « 06/10/2026 11:05:27 » (pied de page du rapport)."""
    rows = list(range(min(40, len(grid)))) + list(range(max(0, len(grid) - 30), len(grid)))
    for i in rows:
        for v in grid.iloc[i].tolist()[:8]:
            t = strip_accents(clean_text(v)).lower()
            m = re.search(r"(\d{1,2})\s+([a-z]+)\s+(\d{4})\s+(\d{1,2}:\d{2}(?::\d{2})?)", t)
            if m and m[2] in MONTHS:
                return f"{int(m[1]):02d}/{MONTHS[m[2]]:02d}/{m[3]} {m[4]}"
    return None


# ───────────────────────── rapport Vocalcom ─────────────────────────
def _parse_vocalcom(grids: dict, sheet: str, default_date: dt.date | None) -> ParsedPauses:
    grid = grids[sheet]
    issues = IssueLog(SRC)
    rep_date = _find_report_date(grid, issues)
    if rep_date is None and default_date is not None:
        rep_date = default_date
        issues.add("Info", "Date saisie", "Aucune date dans le rapport : date indiquée par l'utilisateur.",
                   f"Date retenue : {default_date:%d/%m/%Y}")
    if rep_date is None:
        issues.add("Erreur", CAT_DATE_MANQ, "Aucune date trouvée dans l'en-tête du rapport.",
                   "Saisir la date dans l'interface")
        rep_date = dt.date.today()          # provisoire : l'interface redemande la date aussitôt
    generation = _find_generation(grid)

    rows = grid.to_numpy(dtype=object)
    n_rows, n_cols = rows.shape
    agents: list[dict] = []
    slots: list[dict] = []
    seen_logins: set[str] = set()
    stats = dict(blocks=0, bad_blocks=0)
    cur: dict | None = None
    pending: dict | None = None

    def cell(r: int, c: int):
        return rows[r, c] if 0 <= c < n_cols else None

    def close_pending():
        """Statut commencé (ligne a.m.) mais jamais terminé (pas de ligne p.m.)."""
        nonlocal pending
        if pending is not None and cur is not None:
            issues.add("Erreur", CAT_INCOHERENT, f"Statut « {pending['label']} » : ligne p.m. introuvable.",
                       "Matin conservé, après-midi ignoré", login=cur["login"], ref=pending["row"] + 1)
            stats["bad_blocks"] += 1
            _commit(pending, None)
        pending = None

    def read_half(r: int, marker_col: int, half_label: str) -> tuple[list, bool]:
        vals, ok = [], True
        for k in range(N_HALF):
            c = marker_col + 1 + k
            raw = cell(r, c)
            try:
                s = parse_duration_s(raw, numeric_unit="s")
                s = 0.0 if np.isnan(s) else float(s)
            except ValueError:
                issues.add("Erreur", CAT_VALEUR,
                           f"Cellule {_col_letter(c)}{r + 1} ({pending['label'] if pending else '?'}, {half_label}) : "
                           f"« {clean_text(raw)} » illisible.", "Cellule comptée pour 0 s", login=cur["login"] if cur else "",
                           ref=r + 1)
                s, ok = 0.0, False
            if s > SLOT_MIN * 60 + 1:
                issues.add("Avertissement", CAT_INCOHERENT,
                           f"Cellule {_col_letter(c)}{r + 1} : {s / 60:.1f} min dans un créneau de {SLOT_MIN} min.",
                           "Valeur conservée telle quelle", login=cur["login"] if cur else "", ref=r + 1)
            vals.append(s)
        return vals, ok

    def _commit(block: dict, pm: dict | None):
        """Enregistre les créneaux > 0 d'un statut et contrôle son total."""
        label = block["label"] or "(sans libellé)"
        if label in cur["labels"]:
            issues.add("Info", "Statut répété", f"Le statut « {label} » apparaît plusieurs fois pour cet agent.",
                       "Durées additionnées par créneau", login=cur["login"], ref=block["row"] + 1)
        cur["labels"].add(label)
        total = 0.0
        for half, vals, base in (("am", block["am"], 0), ("pm", pm["vals"] if pm else [0.0] * N_HALF, 720)):
            for k, s in enumerate(vals):
                if s > 0:
                    cur["slots"][(label, base + k * SLOT_MIN)] = cur["slots"].get((label, base + k * SLOT_MIN), 0.0) + s
                    total += s
        if pm is not None and pm["total"] is not None and abs(pm["total"] - total) > 1:
            issues.add("Avertissement", CAT_ECART,
                       f"Statut « {label} » : Σ créneaux = {total:.0f} s ≠ total du rapport = {pm['total']:.0f} s.",
                       "Créneaux conservés ; vérifier l'alignement des colonnes", login=cur["login"], ref=block["row"] + 1)

    def finish_agent():
        nonlocal cur, pending
        if cur is None:
            return
        close_pending()
        slot_total = float(sum(cur["slots"].values()))
        for (label, start), s in cur["slots"].items():
            slots.append(dict(date=rep_date, login=cur["login"], type_pause=label, slot_start_min=int(start), seconds=s))
        arr, dep = cur.get("arrivee"), cur.get("depart")
        if arr is not None and dep is not None and dep < arr:
            issues.add("Avertissement", CAT_HORAIRE, f"Départ ({dep:.0f} min) avant arrivée ({arr:.0f} min).",
                       "Départ ramené à minuit", login=cur["login"], ref=cur["row"] + 1)
            dep = 1440.0
        if cur.get("pause_resume") is None:
            issues.add("Avertissement", "Donnée manquante", "« Durée de pause » absente du Résumé.",
                       "Contrôle de réconciliation impossible pour cet agent", login=cur["login"], ref=cur["row"] + 1)
        elif abs(cur["pause_resume"] - slot_total) > 1:
            issues.add("Avertissement", CAT_ECART,
                       f"Σ créneaux = {slot_total:.0f} s ≠ « Durée de pause » du Résumé = {cur['pause_resume']:.0f} s.",
                       "Créneaux conservés ; vérifier l'agent", login=cur["login"], ref=cur["row"] + 1)
        if arr is not None and dep is not None:
            out = sum(1 for (_, st), s in cur["slots"].items() if s > 60 and (st + SLOT_MIN <= arr or st >= dep))
            if out:
                issues.add("Info", CAT_INCOHERENT, f"{out} créneau(x) de pause hors de la plage Arrivée-Départ.",
                           "Conservé tel quel", login=cur["login"], ref=cur["row"] + 1)
        agents.append(dict(date=rep_date, login=cur["login"], nom_source=cur["nom"] or cur["login"],
                           arrivee_min=arr if arr is not None else np.nan, depart_min=dep if dep is not None else np.nan,
                           pause_resume_s=cur["pause_resume"] if cur["pause_resume"] is not None else np.nan,
                           pause_slots_s=slot_total,
                           trait_total_s=cur["trait"] if cur["trait"] is not None else np.nan,
                           travail_s=cur["travail"] if cur["travail"] is not None else np.nan,
                           ligne_source=cur["row"] + 1))
        cur = None

    for r in range(n_rows):
        texts = [clean_text(rows[r, c]) for c in range(min(7, n_cols))]
        if not any(texts):
            continue
        marker = next((c for c, t in enumerate(texts[:6]) if AMPM_RE.match(t)), None)

        # 1) nouvelle ligne agent
        if marker is None:
            m = next((AGENT_RE.match(t) for t in texts[:2] if AGENT_RE.match(t)), None)
            if m:
                finish_agent()
                login = norm_login(m[1])
                name = re.sub(r"\s*,\s*", " ", (m[2] or "")).strip()
                if login in seen_logins:
                    issues.add("Avertissement", CAT_DOUBLON, f"Agent {login} présent plusieurs fois dans le rapport.",
                               "Bloc ignoré (première occurrence conservée)", login=login, ref=r + 1)
                    cur = None
                    continue
                seen_logins.add(login)
                cur = dict(login=login, nom=name, row=r, slots={}, labels=set(), pause_resume=None, trait=None,
                           travail=None, arrivee=None, depart=None)
                if not name:
                    issues.add("Info", "Donnée manquante", "Nom absent de la ligne agent.", "Login utilisé comme nom",
                               login=login, ref=r + 1)
                continue
        if cur is None:
            continue

        # 2) lignes de créneaux
        if marker is not None:
            kind = AMPM_RE.match(texts[marker])[1].lower()
            if kind == "a":
                close_pending()
                pending = dict(label=texts[0], row=r, am=None)
                stats["blocks"] += 1
                pending["am"], ok_am = read_half(r, marker, "a.m.")
                pending["ok"] = ok_am
            else:
                if pending is None:
                    issues.add("Avertissement", CAT_INCOHERENT, "Ligne p.m. sans ligne a.m. correspondante.",
                               "Ligne ignorée", login=cur["login"], ref=r + 1)
                    continue
                vals, ok_pm = read_half(r, marker, "p.m.")
                total = None
                raw_tot = cell(r, marker + 1 + N_HALF)
                if clean_text(raw_tot):
                    try:
                        total = parse_duration_s(raw_tot, numeric_unit="s")
                        total = None if np.isnan(total) else float(total)
                    except ValueError:
                        issues.add("Avertissement", CAT_VALEUR, f"Total du statut illisible : « {clean_text(raw_tot)} ».",
                                   "Contrôle du total impossible", login=cur["login"], ref=r + 1)
                if not (pending["ok"] and ok_pm):
                    stats["bad_blocks"] += 1
                _commit(pending, dict(vals=vals, total=total))
                pending = None
            continue

        # 3) lignes du Résumé
        for t in texts:
            low = strip_accents(t).lower()
            if (m := re.search(r"trait\.?\s*total\s*:\s*(.+)$", low)):
                cur["trait"] = _safe_dur(m[1], issues, cur, r)
            elif (m := re.search(r"duree de travail\s*:\s*(.+)$", low)):
                cur["travail"] = _safe_dur(m[1], issues, cur, r)
            elif (m := re.search(r"duree de pause\s*:\s*(.+)$", low)):
                cur["pause_resume"] = _safe_dur(m[1], issues, cur, r)
            elif (m := re.search(r"arrivee\s*-\s*depart\s*:\s*(.+)$", low)):
                mm = re.search(r"(\d{1,2})\s*h\s*(\d{2})\s*-\s*(\d{1,2})\s*h\s*(\d{2})", m[1])
                if mm:
                    cur["arrivee"] = int(mm[1]) * 60 + int(mm[2])
                    cur["depart"] = int(mm[3]) * 60 + int(mm[4])
                else:
                    issues.add("Avertissement", CAT_HORAIRE, f"Arrivée-Départ illisible : « {m[1]} ».",
                               "Plage de présence inconnue", login=cur["login"], ref=r + 1)
    finish_agent()

    agents_df = pd.DataFrame(agents, columns=AGENT_COLS)
    slots_df = pd.DataFrame(slots, columns=SLOT_COLS)
    if len(slots_df):
        slots_df["slot_start_min"] = slots_df["slot_start_min"].astype(int)
        slots_df["seconds"] = slots_df["seconds"].astype(float)
    non_empty = int(grid.map(lambda v: clean_text(v) != "").any(axis=1).sum())
    meta = dict(layout="vocalcom", layout_label="Rapport Vocalcom « Agents pause report » (créneaux de 30 min)",
                lignes_non_vides=non_empty, feuilles=list(grids), lignes_source=stats["blocks"],
                unite_lignes="blocs agent × statut", lignes_exploitables=stats["blocks"] - stats["bad_blocks"],
                lignes_rejetees=stats["bad_blocks"], dates=[rep_date], generation=generation)
    return ParsedPauses("vocalcom", agents_df, slots_df, pd.DataFrame(columns=EVENT_COLS), issues.to_df(), meta)


def _safe_dur(txt: str, issues: IssueLog, cur: dict, r: int):
    try:
        v = parse_duration_s(txt.strip())
        return None if np.isnan(v) else float(v)
    except ValueError:
        issues.add("Avertissement", CAT_VALEUR, f"Durée du Résumé illisible : « {txt.strip()} ».",
                   "Valeur ignorée", login=cur["login"], ref=r + 1)
        return None


# ───────────────────────── fichier tabulaire ─────────────────────────
def _parse_tabular(grids: dict, sheet: str, header_row: int, mapping: dict | None,
                   default_date: dt.date | None) -> ParsedPauses:
    issues = IssueLog(SRC)
    grid = grids[sheet]
    tbl = cleaner.table_from_grid(grid, header_row)
    cols = [c for c in tbl.columns if c != cleaner.LINE_COL]
    mp = {k: v for k, v in (mapping or auto_map_columns(cols, PAUSE_SYNONYMS)).items() if v in tbl.columns}

    events_mode = "heure_debut" in mp and "heure_fin" in mp
    slots_mode = not events_mode and "tranche" in mp and "duree" in mp
    layout_label = ("Tableau de pauses — horaires début / fin exacts" if events_mode
                    else "Tableau de pauses — créneaux de 30 min + durée")
    for fld, lab in (("date", "Date"), ("type_pause", "Type de pause"), ("nom_source", "Nom de l'agent")):
        if fld not in mp:
            fallback = {"date": "date saisie dans l'interface" if default_date else "lignes sans date rejetées",
                        "type_pause": "type « Pause » par défaut", "nom_source": "login utilisé comme nom"}[fld]
            issues.add("Info", "Colonne manquante", f"Colonne « {lab} » non trouvée.", f"Repli : {fallback}")
    unknown = [c for c in cols if c not in mp.values()]
    if unknown:
        issues.add("Info", "Colonne inconnue", "Colonnes non utilisées : " + ", ".join(unknown[:12]) +
                   ("…" if len(unknown) > 12 else ""), "Ignorées")
    last = max((i for i in range(len(grid)) if any(clean_text(v) for v in grid.iloc[i].tolist())), default=header_row)
    n_empty = max(0, last - header_row - len(tbl))
    if n_empty:
        issues.add("Info", "Ligne vide", f"{n_empty} ligne(s) vide(s) au milieu du tableau.", "Ignorées")
    if slots_mode:
        issues.add("Info", "Hypothèse", "Durées sans unité lues comme minutes ; « mm:ss » comme minutes:secondes.",
                   "Modifiable dans normalizer.parse_duration_s")

    events, slot_rows, seen = [], [], set()
    n_ok = 0
    for rec in tbl.to_dict("records"):
        ref = rec.get(cleaner.LINE_COL)
        login = norm_login(rec.get(mp.get("login")))
        if not login:
            issues.add("Erreur", CAT_VALEUR, "Login manquant.", "Ligne rejetée", ref=ref)
            continue
        raw_d = rec.get(mp["date"]) if "date" in mp else None
        try:
            date = parse_date(raw_d, default_date)
        except ValueError as e:
            issues.add("Erreur", CAT_DATE_INV, str(e), "Ligne rejetée", login=login, ref=ref)
            continue
        if date is None:
            issues.add("Erreur", CAT_DATE_MANQ, "Date manquante.", "Ligne rejetée (saisir une date dans l'interface)",
                       login=login, ref=ref)
            continue
        typ = clean_text(rec.get(mp.get("type_pause"))) or "Pause"
        name = clean_text(rec.get(mp.get("nom_source"))) if "nom_source" in mp else ""
        try:
            if events_mode:
                a, b = parse_time_min(rec.get(mp["heure_debut"])), parse_time_min(rec.get(mp["heure_fin"]))
                if np.isnan(a) or np.isnan(b):
                    issues.add("Erreur", CAT_HORAIRE, "Heure de début ou de fin manquante.", "Ligne rejetée",
                               login=login, ref=ref)
                    continue
                if b <= a:
                    issues.add("Erreur", CAT_HORAIRE, f"Fin ({b:.0f} min) non postérieure au début ({a:.0f} min).",
                               "Ligne rejetée", login=login, ref=ref)
                    continue
                dur = (b - a) * 60
                if "duree" in mp:
                    given = parse_duration_s(rec.get(mp["duree"]))
                    if not np.isnan(given) and abs(given - dur) > 60:
                        issues.add("Avertissement", CAT_INCOHERENT,
                                   f"Durée du fichier ({given / 60:.1f} min) ≠ fin − début ({dur / 60:.1f} min).",
                                   "Durée recalculée à partir des horaires", login=login, ref=ref)
                key = (login, date, typ, round(a, 2), round(b, 2))
            elif slots_mode:
                st = parse_slot_start(rec.get(mp["tranche"]))
                dur = parse_duration_s(rec.get(mp["duree"]))
                if np.isnan(st) or np.isnan(dur):
                    issues.add("Erreur", CAT_VALEUR, "Tranche ou durée manquante.", "Ligne rejetée", login=login, ref=ref)
                    continue
                if dur > SLOT_MIN * 60 + 1:
                    issues.add("Avertissement", CAT_INCOHERENT, f"{dur / 60:.1f} min dans un créneau de {SLOT_MIN} min.",
                               "Valeur conservée", login=login, ref=ref)
                key = (login, date, typ, st, round(dur, 1))
            else:
                issues.add("Erreur", CAT_VALEUR, "Mapping insuffisant (ni début/fin, ni tranche + durée).",
                           "Ligne rejetée", login=login, ref=ref)
                continue
        except ValueError as e:
            cat = CAT_HORAIRE if events_mode and "heure" in str(e) else CAT_VALEUR
            issues.add("Erreur", cat, str(e), "Ligne rejetée", login=login, ref=ref)
            continue
        if key in seen:
            issues.add("Avertissement", CAT_DOUBLON, "Ligne identique déjà lue.", "Ligne ignorée", login=login, ref=ref)
            continue
        seen.add(key)
        n_ok += 1
        if events_mode:
            eid = len(events) + 1
            events.append(dict(event_id=eid, date=date, login=login, type_pause=typ, debut_min=a, fin_min=b, duree_s=dur,
                               nom_source=name))
            k = int(a // SLOT_MIN) * SLOT_MIN
            while k < b:
                ov = min(b, k + SLOT_MIN) - max(a, k)
                if ov > 0:
                    slot_rows.append(dict(date=date, login=login, type_pause=typ, slot_start_min=k, seconds=ov * 60,
                                          event_id=eid, nom_source=name))
                k += SLOT_MIN
        else:
            slot_rows.append(dict(date=date, login=login, type_pause=typ, slot_start_min=int(st), seconds=float(dur),
                                  nom_source=name))

    slots_df = pd.DataFrame(slot_rows)
    if slots_df.empty:
        slots_df = pd.DataFrame(columns=SLOT_COLS + ["event_id"])
    ev_df = pd.DataFrame(events) if events else pd.DataFrame(columns=EVENT_COLS + ["nom_source"])
    if len(slots_df):
        slots_df = slots_df.groupby(["date", "login", "type_pause", "slot_start_min"] + (["event_id"] if events_mode else []),
                                    as_index=False).agg(seconds=("seconds", "sum"), nom_source=("nom_source", "first"))
    names = (slots_df.groupby(["date", "login"])["nom_source"].first().reset_index()
             if len(slots_df) else pd.DataFrame(columns=["date", "login", "nom_source"]))
    tot = (slots_df.groupby(["date", "login"])["seconds"].sum().rename("pause_slots_s").reset_index()
           if len(slots_df) else pd.DataFrame(columns=["date", "login", "pause_slots_s"]))
    agents_df = names.merge(tot, on=["date", "login"], how="outer")
    agents_df["nom_source"] = agents_df["nom_source"].fillna("").replace("", np.nan).fillna(agents_df["login"])
    for c in ("arrivee_min", "depart_min", "pause_resume_s", "trait_total_s", "travail_s"):
        agents_df[c] = np.nan
    agents_df["ligne_source"] = np.nan
    agents_df = agents_df[AGENT_COLS]
    slots_df = slots_df.drop(columns=[c for c in ("nom_source",) if c in slots_df])
    ev_df = ev_df.drop(columns=[c for c in ("nom_source",) if c in ev_df])
    if not events_mode:
        slots_df = slots_df.drop(columns=[c for c in ("event_id",) if c in slots_df])
    dates = sorted({d for d in agents_df["date"].dropna()}) if len(agents_df) else []
    meta = dict(layout="tabulaire", layout_label=layout_label,
                lignes_non_vides=int(grid.map(lambda v: clean_text(v) != "").any(axis=1).sum()), feuilles=list(grids),
                lignes_source=len(tbl), unite_lignes="lignes", lignes_exploitables=n_ok,
                lignes_rejetees=len(tbl) - n_ok, dates=dates, generation=None)
    return ParsedPauses("tabulaire", agents_df, slots_df, ev_df, issues.to_df(), meta)
