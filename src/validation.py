"""Journal d'anomalies. Règle du projet : rien n'est supprimé en silence — chaque ligne écartée,
corrigée ou signalée est consignée ici avec l'action entreprise."""
from __future__ import annotations

import pandas as pd

ISSUE_COLS = ["severite", "categorie", "login", "detail", "action", "ref", "source"]
SEVERITY_ORDER = {"Erreur": 0, "Avertissement": 1, "Info": 2}

# Catégories utilisées par la page « Qualité des données » (ne pas renommer à la légère)
CAT_DOUBLON = "Doublon"
CAT_HORAIRE = "Horaire invalide"
CAT_VALEUR = "Valeur invalide"
CAT_INCOHERENT = "Valeur incohérente"
CAT_DATE_MANQ = "Date manquante"
CAT_DATE_INV = "Date invalide"
CAT_ECART = "Écart de contrôle"
CAT_DOUBLON_RH = "Doublon RH"


def empty_issues() -> pd.DataFrame:
    return pd.DataFrame(columns=ISSUE_COLS)


class IssueLog:
    """Collecteur d'anomalies pour une source (« Pauses » ou « RH »)."""

    def __init__(self, source: str):
        self.source = source
        self.rows: list[dict] = []

    def add(self, severite: str, categorie: str, detail: str, action: str = "", login="", ref="") -> None:
        self.rows.append(dict(severite=severite, categorie=categorie, login=str(login or ""), detail=detail,
                              action=action, ref="" if ref is None else str(ref), source=self.source))

    def to_df(self) -> pd.DataFrame:
        if not self.rows:
            return empty_issues()
        return pd.DataFrame(self.rows, columns=ISSUE_COLS)

    def __len__(self) -> int:
        return len(self.rows)


def merge_issues(*frames) -> pd.DataFrame:
    """Concatène plusieurs journaux (None ignorés), triés par sévérité."""
    parts = [f for f in frames if f is not None and len(f)]
    if not parts:
        return empty_issues()
    out = pd.concat([f.reindex(columns=ISSUE_COLS) for f in parts], ignore_index=True)
    out["_o"] = out["severite"].map(SEVERITY_ORDER).fillna(9)
    return out.sort_values("_o", kind="stable").drop(columns="_o").reset_index(drop=True)
