from __future__ import annotations

from .vba import Grid, Table, is_blank
from .model import Scenario


# SECTION 4/13 — TABLES DE DÉCÉLÉRATION AU PAS DE 0,1 km/h + PIVOTS — SUBSET-026 §3.13.2.2.3.1.
# ==========================================================================

"""Deceleration tables at 0.1 km/h resolution and speed "pivot" values.

Ports of ``button_lambda_Click`` (Sheet12, 'Lambda train deceleration'),
``button_gamma_Click`` (Sheet13, 'Gamma train deceleration') and
``Kdry_rst_Click`` (Sheet3, copy of Kdry_rst(V, EBCL) into the gamma sheet).
"""



class RowTable:
    """Column-oriented copy of a deceleration sheet: cells[col][row]."""

    def __init__(self, name, ncols):
        self.name = name
        self.cols = {c: {} for c in range(1, ncols + 1)}

    def __getitem__(self, rc):
        r, c = rc
        return self.cols[c].get(r)

    def __setitem__(self, rc, v):
        r, c = rc
        self.cols[c][r] = v


CALC_LAMBDA_HEADERS = {1: 'EBD Speed "pivot" values', 2: 'EBD Distance"pivot" values (from origin)',
                       4: 'SBD Speed "pivot" values', 5: 'SBD Distance"pivot" values (from origin)',
                       7: 'GUI Speed "pivot" values '}
CALC_GAMMA_HEADERS = {1: 'EBD1 Speed "pivot" values', 2: 'EBD2 Speed "pivot" values',
                      3: 'EBD Distance "pivot" values (from origin)', 5: 'SBD1 Speed "pivot" values',
                      6: 'SBD2 Speed "pivot" values', 7: 'SBD Distance "pivot" values (from origin)',
                      9: 'GUI1 Speed "pivot" values', 10: 'GUI2 Speed "pivot" values'}


def new_calc_sheet(gamma: bool) -> Grid:
    g = Grid("Calc Gamma" if gamma else "Calc Lambda")
    for c, h in (CALC_GAMMA_HEADERS if gamma else CALC_LAMBDA_HEADERS).items():
        g[1, c] = h
    return g


# Outil: compilation des pivots de vitesse aux changements de modèle — nécessaire
# au balayage des régions de l'Annexe A §A.3.12.2 (cf. §3.13.8.1.3: décélérations
# dépendant de la vitesse et de la distance).
def _pivots(t: RowTable, calc: Grid, total, groups):
    """'Compilation of the speed "pivot" values' loops (shared by both sheets)."""
    counters = [0] * len(groups)
    for ligne in range(0, total + 1):
        for k, (cmp_cols, mark_col, calc_col) in enumerate(groups):
            if any(t[ligne + 3, c] != t[ligne + 2, c] for c in cmp_cols):
                nxt = t[ligne + 3, 1]
                if (nxt or 0) != 0:          # 'do not take the first speed entrance (=0 km/h)'
                    t[ligne + 2, mark_col] = t[ligne + 2, 1]
                    calc[counters[k] + 2, calc_col] = t[ligne + 2, mark_col]
                    counters[k] += 1


# Tables de décélération au pas de 0,1 km/h — SUBSET-026 §3.13.2.2.3.1 (step
# functions A_brake_emergency/service/normal_service pour le conversion model).
def build_lambda_table(lp, sc, calc: Grid) -> RowTable:
    t = RowTable("Lambda train deceleration", 10)
    total = int(round(lp.max_speed * 12 + 90))      # Total_ligne (Integer)
    freight = sc.train.brake_position in ("Freight in P", "Freight in G")
    for ligne in range(0, total + 1):
        r = ligne + 2
        v = ligne / 10
        t[r, 1] = v
        t[r, 2] = lp.A_brake_emergency(v)
        t[r, 5] = lp.A_brake_service(v)
        t[r, 7] = lp.A_brake_normal_service(v)
        t[r, 3] = lp.Kv_int(v)
        t[r, 9] = lp.Kn_plus(v)
        t[r, 10] = lp.Kn_minus(v)
    _ = freight  # the Kv_int set is selected in LambdaParameters (same tests as the VBA)
    calc.clear(2, 1, 36, 1)
    calc.clear(2, 4, 36, 4)
    calc.clear(2, 7, 36, 7)
    _pivots(t, calc, total, [((2, 3), 4, 1), ((5,), 6, 4), ((7,), 8, 7)])
    return t


# Kdry_rst(V, M_NVEBCL) pour l'EBCL sélectionné, au format de la feuille
# 'Correction factor Kdry_rst' — SUBSET-026 §3.13.2.2.9.1.5.
def kdry_rows(gb, comb: str):
    """J23:J36 (comb1) / V23:V36 (comb2) after Kdry_rst_Click for the selected EBCL."""
    k = gb.kdry_by_ebcl[gb.ebcl][comb]
    keys = [r[0] for r in gb.comb1["A_brake_emergency"]] if comb == "comb1" else \
        [r[0] for r in gb.comb2["A_brake_emergency"]]
    vals = []
    for j in range(7):
        vals += [k[j], k[j]]
    return list(zip(keys, vals))


# M_NVEBCL à partir de l'EBCL sélectionné — SUBSET-026 §3.13.2.3.7.8 (niveau de
# confiance sur la décélération de frein d'urgence).
def M_NVEBCL(ebcl: int) -> float:
    return 100 - 100 * 5 * 10 ** -1 if ebcl == 0 else 100 - 100 * 10 ** (-ebcl)


def gamma_max_speed(gb) -> float:
    return float(gb.comb1["A_brake_emergency"][-1][0])          # H20


# Tables γ (comb. n°1 avec freins spéciaux / comb. n°2 sans — §3.13.5.2) au pas de
# 0,1 km/h — SUBSET-026 §3.13.2.2.3.1 (Kdry_rst, Kwet_rst, A_brake_*).
def build_gamma_table(sc, calc: Grid) -> RowTable:
    gb = sc.gamma_brake
    lb = sc.lambda_brake
    t = RowTable("Gamma train deceleration", 19)
    total = int(round(gamma_max_speed(gb) * 12 + 90))
    c1, c2 = gb.comb1, gb.comb2
    T = {2: Table(c1["A_brake_emergency"]), 3: Table(kdry_rows(gb, "comb1")), 4: Table(c1["Kwet_rst"]),
         6: Table(c2["A_brake_emergency"]), 7: Table(kdry_rows(gb, "comb2")), 8: Table(c2["Kwet_rst"]),
         10: Table(c1["A_brake_service"]), 12: Table(c2["A_brake_service"]),
         14: Table(c1["A_brake_normal_service"]), 16: Table(c2["A_brake_normal_service"]),
         18: Table(lb.kn_plus), 19: Table(lb.kn_minus)}
    for ligne in range(0, total + 1):
        r = ligne + 2
        v = ligne / 10
        t[r, 1] = v
        for c, tab in T.items():
            t[r, c] = tab(v)
    for c in (1, 2, 5, 6, 9, 10):
        calc.clear(2, c, 36, c)
    _pivots(t, calc, total, [((2, 3, 4), 5, 1), ((6, 7, 8), 9, 2), ((10,), 11, 5),
                             ((12,), 13, 6), ((14,), 15, 9), ((16,), 17, 10)])
    return t


def column_values(calc: Grid, col: int):
    out, r = [], 2
    while not is_blank(calc[r, col]):
        out.append(calc[r, col])
        r += 1
    return out


# ==========================================================================
