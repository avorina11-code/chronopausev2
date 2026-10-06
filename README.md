# ⏱️ Pause Analyzer

Outil d'analyse opérationnelle des pauses des agents (supervision / WFM) : on charge un rapport Excel brut,
l'application le nettoie, le croise avec la base RH et produit un dashboard interactif.

```
Excel brut → détection de structure → nettoyage → normalisation → croisement RH → calculs/contrôles → dashboard
```

## Lancer

```bash
pip install -r requirements.txt
streamlit run app.py
```

Déploiement : [Streamlit Community Cloud](https://share.streamlit.io) → dépôt GitHub → fichier principal `app.py`.
`requirements.txt` doit être à la racine (il contient `xlrd`, indispensable pour lire les `.xls` Vocalcom).

## Fichiers attendus

1. **Fichier de pauses** (Excel) — deux structures reconnues automatiquement :
   - **Rapport Vocalcom « Agents pause report »** : un bloc par agent (`1055: NOM, Prénom`), un statut par couple de
     lignes `a.m.` / `p.m.`, 24 créneaux de 30 min par ligne, puis un **Résumé** (Trait. total, Durée de travail,
     Durée de pause, Arrivée-Départ). Le libellé `a.m.` occupe une colonne de plus que `p.m.` : le lecteur en tient compte
     et vérifie que Σ créneaux = « Durée de pause » du Résumé.
   - **Tableau** : une ligne par pause (`Login`, `Date`, `Heure début`, `Heure fin`, `Type`) ou par créneau (`Tranche` + `Durée`).
     Les colonnes sont détectées par synonymes ; sinon mapping manuel dans l'interface.
2. **Base RH** (Excel, optionnelle mais recommandée) : au minimum une colonne login ; matricule, nom, équipe, superviseur si disponibles.

## Rapprochement RH

- Clé = **login** (insensible à la casse et aux zéros de tête).
- Login trouvé mais nom très différent → alerte « à vérifier ».
- Login inconnu → éventuelle **suggestion par nom** (≥ 2 mots communs). Jamais appliquée sans activation explicite dans la barre latérale.

## Règles de calcul (donnée observée vs calculée)

| Indicateur | Nature | Définition |
|---|---|---|
| Durée par créneau | observée | lue telle quelle dans le rapport |
| Bloc de pause | calculée | créneaux consécutifs d'un même statut ; début/fin = bornes de créneaux (pas une heure exacte). Un bloc peut regrouper plusieurs pauses : le nombre de pauses est un minimum |
| Durée d'un bloc | calculée (exacte) | somme des durées observées |
| Dépassement | calculé | secondes au-delà des règles saisies dans la barre latérale (jamais « officielles ») |
| Simultanéité | calculée | Σ secondes ÷ 1800 ÷ effectif de référence (présents / fichier / RH) |

Rien n'est supprimé en silence : toute ligne écartée, corrigée ou signalée figure dans la page **Qualité des données**.

## Structure

```
app.py                  import des fichiers + résumé
pages/                  01 Dashboard · 02 Agent · 03 Analyse globale · 04 Dépassements · 05 Qualité · 06 Tableau
src/config.py           constantes, règles (Rules), formatage
src/models.py           ParsedPauses, RHData
src/normalizer.py       synonymes de colonnes, parseurs (login, date, heure, durée, noms)
src/cleaner.py          détection d'en-tête, grille → tableau
src/loader.py           lecture Vocalcom / tableaux
src/rh_matching.py      base RH et rapprochement
src/validation.py       journal d'anomalies
src/calculations.py     blocs, dépassements, simultanéité, KPI
src/visualizations.py   graphiques Plotly
src/ui.py               sidebar (filtres, règles), contexte de page
tests/                  jeu de données synthétique + tests (python tests/test_pipeline.py)
```

⚠️ Ne publiez jamais de vrais fichiers de pauses / RH sur GitHub (le `.gitignore` les exclut).
