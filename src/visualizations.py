"""Graphiques Plotly. Chaque fonction renvoie une Figure (jamais d'exception sur données vides)."""
from __future__ import annotations

import datetime as dt

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go

from .config import SLOT_MIN, SLOT_SEC, fmt_ms, slot_label

PALETTE = px.colors.qualitative.Safe + px.colors.qualitative.Set2
RED, GREY = "#D1344B", "#8A94A6"
BASE_DAY = dt.datetime(2000, 1, 1)
LAYOUT = dict(template="plotly_white", margin=dict(l=10, r=10, t=40, b=10), font=dict(size=13),
              legend=dict(orientation="h", y=-0.2))


def type_colors(types) -> dict:
    return {t: PALETTE[i % len(PALETTE)] for i, t in enumerate(sorted(types))}


def _empty(msg="Aucune donnée pour les filtres sélectionnés", h=300) -> go.Figure:
    f = go.Figure()
    f.add_annotation(text=msg, showarrow=False, font=dict(size=15, color=GREY))
    f.update_layout(**LAYOUT, height=h, xaxis_visible=False, yaxis_visible=False)
    return f


def fig_distribution(bs: pd.DataFrame, metric: str = "blocs_entames", title: str = "") -> go.Figure:
    if bs.empty:
        return _empty()
    labels = {"blocs_entames": "Pauses (blocs) entamées", "minutes": "Minutes de pause observées",
              "agents": "Agents distincts en pause"}
    f = px.bar(bs, x=bs["slot_start_min"].map(slot_label), y=metric, labels={"x": "Créneau (début)", metric: labels[metric]},
               title=title or labels[metric])
    f.update_traces(marker_color="#1F6FEB", hovertemplate="%{x}<br>%{y:.0f}<extra></extra>")
    f.update_layout(**LAYOUT, height=340, xaxis_title="Créneau de 30 min (heure de début)", yaxis_title=labels[metric])
    f.update_layout(clickmode="event+select")
    return f


def fig_by_type(tbl: pd.DataFrame, colors: dict) -> go.Figure:
    if tbl.empty:
        return _empty()
    f = go.Figure()
    f.add_bar(y=tbl["Type de pause"], x=tbl["Durée totale (min)"] / 60, orientation="h",
              marker_color=[colors.get(t, GREY) for t in tbl["Type de pause"]],
              customdata=tbl[["Nb pauses (blocs)", "Agents"]],
              hovertemplate="%{y}<br>%{x:.1f} h<br>%{customdata[0]} pauses · %{customdata[1]} agents<extra></extra>")
    f.update_layout(**LAYOUT, height=max(260, 46 * len(tbl) + 90), title="Durée totale par type (heures)",
                    yaxis=dict(autorange="reversed"), xaxis_title="Heures", showlegend=False)
    return f


def fig_type_hourly(slots: pd.DataFrame, colors: dict) -> go.Figure:
    if slots.empty:
        return _empty()
    g = slots.groupby(["heure", "type_pause"])["seconds"].sum().div(60).reset_index()
    f = px.bar(g, x="heure", y="seconds", color="type_pause", color_discrete_map=colors,
               labels={"heure": "Heure", "seconds": "Minutes", "type_pause": "Type"}, title="Répartition horaire par type (minutes)")
    f.update_layout(**LAYOUT, height=340, xaxis=dict(dtick=1))
    return f


def fig_heatmap(slots: pd.DataFrame, metric: str = "agents") -> go.Figure:
    if slots.empty:
        return _empty()
    if metric == "agents":
        g = slots.groupby(["type_pause", "slot_start_min"])["login"].nunique()
        lab = "Agents distincts"
    elif metric == "equiv":
        g = slots.groupby(["type_pause", "slot_start_min"])["seconds"].sum() / SLOT_SEC
        lab = "Agents simultanés (moyenne)"
    else:
        g = slots.groupby(["type_pause", "slot_start_min"])["seconds"].sum() / 60
        lab = "Minutes"
    pv = g.unstack(fill_value=0)
    full = range(int(pv.columns.min()), int(pv.columns.max()) + SLOT_MIN, SLOT_MIN)
    pv = pv.reindex(columns=full, fill_value=0)
    f = go.Figure(go.Heatmap(z=pv.values, x=[slot_label(c) for c in pv.columns], y=pv.index.tolist(),
                             colorscale="YlOrRd", colorbar_title=lab,
                             hovertemplate="%{y}<br>%{x}<br>" + lab + " : %{z:.1f}<extra></extra>"))
    f.update_layout(**LAYOUT, height=max(280, 44 * len(pv) + 120), title=f"Heatmap — {lab}",
                    xaxis_title="Créneau (heure de début)", yaxis=dict(autorange="reversed"))
    return f


def fig_simultaneity(sim: pd.DataFrame, limit_pct: float) -> go.Figure:
    if sim.empty:
        return _empty()
    f = go.Figure()
    for d, g in sim.groupby("date"):
        col = [RED if x else ("#1F6FEB" if r else "#C5CCD8") for x, r in zip(g["depasse"], g["retenu"])]
        f.add_bar(x=g["slot_start_min"].map(slot_label), y=g["pct"], name=str(d), marker_color=col,
                  customdata=g[["equiv_agents", "agents_distincts", "effectif"]],
                  hovertemplate="%{x}<br>%{y:.1f} %<br>≈ %{customdata[0]:.1f} agents simultanés"
                                "<br>%{customdata[1]} agents distincts · effectif %{customdata[2]:.0f}<extra></extra>")
    if limit_pct > 0:
        f.add_hline(y=limit_pct, line_dash="dash", line_color=RED, annotation_text=f"Limite {limit_pct:g} %")
    f.update_layout(**LAYOUT, height=340, title="Simultanéité (% de l'effectif de référence)", yaxis_title="%",
                    xaxis_title="Créneau (heure de début)", barmode="group", showlegend=sim["date"].nunique() > 1)
    return f


def fig_bar(df: pd.DataFrame, x: str, y: str, title: str, horizontal: bool = False, color: str = "#D1344B") -> go.Figure:
    if df.empty or df[y].fillna(0).sum() == 0:
        return _empty("Aucun dépassement sur la sélection", 260)
    f = px.bar(df, x=y if horizontal else x, y=x if horizontal else y, orientation="h" if horizontal else "v", title=title)
    f.update_traces(marker_color=color)
    f.update_layout(**LAYOUT, height=max(300, 28 * len(df) + 100) if horizontal else 320,
                    yaxis=dict(autorange="reversed") if horizontal else {})
    return f


def _t(minute: float) -> dt.datetime:
    return BASE_DAY + dt.timedelta(minutes=float(minute))


def fig_timeline(slots: pd.DataFrame, blocs: pd.DataFrame, colors: dict, arrivee=None, depart=None,
                 title: str = "") -> go.Figure:
    """Une ligne par type. Chaque créneau de 30 min = une case : l'OPACITÉ reflète la part du créneau
    réellement passée dans ce statut (durée observée / 30'). Rouge = dépassement. La position exacte
    dans le créneau est inconnue : on n'invente donc pas d'heure de début/fin précise."""
    if slots.empty:
        return _empty("Aucune pause observée pour cet agent / ce jour", 220)
    types = sorted(slots["type_pause"].unique(), key=lambda t: slots.loc[slots["type_pause"] == t, "slot_start_min"].min())
    f = go.Figure()
    for t in types:
        d = slots[slots["type_pause"] == t].sort_values("slot_start_min")
        occ = (d["seconds"] / SLOT_SEC).clip(0, 1)
        f.add_bar(orientation="h", y=[t] * len(d), x=[SLOT_MIN * 60000] * len(d), base=[_t(m) for m in d["slot_start_min"]],
                  marker=dict(color=[RED if e > 0 else colors.get(t, GREY) for e in d["exces_s"]],
                              opacity=(0.25 + 0.75 * occ).tolist(), line=dict(width=1, color="white")),
                  name=t, showlegend=False,
                  customdata=list(zip(d["tranche_30min"], d["seconds"].map(fmt_ms), d["exces_s"].map(lambda e: fmt_ms(e) if e > 0 else "—"))),
                  hovertemplate="<b>" + t + "</b><br>Créneau %{customdata[0]}<br>Durée observée : %{customdata[1]}"
                                "<br>Dépassement : %{customdata[2]}<extra></extra>")
    if len(blocs):
        bb = blocs.copy()
        f.add_trace(go.Scatter(x=[_t((a + b) / 2) for a, b in zip(bb["debut_min"], bb["fin_min"])], y=bb["type_pause"],
                               mode="text", showlegend=False, hoverinfo="skip",
                               text=[("⚠ " if s == "Dépassement" else "") + fmt_ms(d) for s, d in zip(bb["statut_pause"], bb["duree_s"])],
                               textfont=dict(size=12, color="#1B2430")))
    lo = min([slots["slot_start_min"].min()] + ([arrivee] if arrivee is not None and pd.notna(arrivee) else []))
    hi = max([slots["slot_start_min"].max() + SLOT_MIN] + ([depart] if depart is not None and pd.notna(depart) else []))
    lo, hi = int(lo // 60 * 60), int(-(-hi // 60) * 60)
    if arrivee is not None and depart is not None and pd.notna(arrivee) and pd.notna(depart):
        f.add_shape(type="rect", xref="x", yref="paper", x0=_t(arrivee), x1=_t(depart), y0=0, y1=1,
                    fillcolor=GREY, opacity=0.10, line_width=0, layer="below")
        f.add_annotation(x=_t(arrivee), y=1.02, yref="paper", text=f"Connecté {slot_label(arrivee)} → {slot_label(depart)}",
                         showarrow=False, xanchor="left", font=dict(size=11, color=GREY))
    f.update_layout(**LAYOUT, height=130 + 70 * len(types), title=title, barmode="overlay", showlegend=False,
                    xaxis=dict(type="date", range=[_t(lo), _t(hi)], tickformat="%H:%M", dtick=3600000, gridcolor="#E6EAF0"),
                    yaxis=dict(autorange="reversed", title=""))
    return f


def fig_cumulative(slots: pd.DataFrame, allowed_min: float) -> go.Figure:
    r = slots[slots["est_regle"]].sort_values("slot_start_min")
    if r.empty:
        return _empty("Aucun statut soumis aux règles pour cet agent", 220)
    g = r.groupby("slot_start_min")["seconds"].sum().cumsum() / 60
    x = [_t(m + SLOT_MIN) for m in g.index]
    f = go.Figure(go.Scatter(x=x, y=g.values, mode="lines+markers", line=dict(shape="hv", color="#1F6FEB"),
                             hovertemplate="%{x|%H:%M}<br>Cumul : %{y:.1f} min<extra></extra>", name="Cumul"))
    if allowed_min and allowed_min > 0:
        f.add_hline(y=allowed_min, line_dash="dash", line_color=RED, annotation_text=f"Autorisé {allowed_min:g} min")
    f.update_layout(**LAYOUT, height=260, title="Cumul des pauses soumises aux règles (fin de créneau)",
                    xaxis=dict(tickformat="%H:%M"), yaxis_title="Minutes", showlegend=False)
    return f
