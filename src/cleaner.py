"""Nettoyage des grilles Excel brutes (jamais de modification de l'original : on travaille sur des copies)."""
from __future__ import annotations

import pandas as pd

from .normalizer import PAUSE_SYNONYMS, clean_text, norm_text

LINE_COL = "__ligne_excel"


def detect_header_row(grid: pd.DataFrame, synonyms: dict | None = None, scan: int = 60) -> int:
    """Index (base 0) de la ligne d'en-tête : celle qui contient le plus de libellés connus.
    À défaut, première ligne comptant au moins 2 cellules texte."""
    syn = synonyms or PAUSE_SYNONYMS
    known = {norm_text(s) for lst in syn.values() for s in lst}
    best, best_score = None, 0
    for i in range(min(scan, len(grid))):
        row = [norm_text(v) for v in grid.iloc[i].tolist()]
        score = sum(1 for c in row if c and c in known)
        if score > best_score:
            best, best_score = i, score
    if best is not None:
        return int(best)
    for i in range(min(scan, len(grid))):
        if sum(1 for v in grid.iloc[i].tolist() if clean_text(v)) >= 2:
            return int(i)
    return 0


def table_from_grid(grid: pd.DataFrame, header_row: int) -> pd.DataFrame:
    """Grille brute -> tableau : noms de colonnes pris sur `header_row`, lignes entièrement vides retirées,
    colonne `__ligne_excel` = numéro de ligne dans le fichier source (base 1)."""
    header_row = int(max(0, min(header_row, max(len(grid) - 1, 0))))
    raw = grid.iloc[header_row].tolist() if len(grid) else []
    names, seen = [], {}
    for i, v in enumerate(raw):
        n = clean_text(v) or f"colonne_{i + 1}"
        if n in seen:
            seen[n] += 1
            n = f"{n} ({seen[n]})"
        else:
            seen[n] = 1
        names.append(n)
    body = grid.iloc[header_row + 1:].copy()
    body.columns = names
    body[LINE_COL] = body.index + 1
    mask = body.drop(columns=LINE_COL).map(lambda v: clean_text(v) != "").any(axis=1) if len(body) else pd.Series(dtype=bool)
    body = body[mask].dropna(axis=1, how="all") if len(body) else body
    if LINE_COL not in body.columns:
        body[LINE_COL] = []
    return body.reset_index(drop=True)
