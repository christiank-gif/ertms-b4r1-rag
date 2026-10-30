from __future__ import annotations

from collections import deque

from .geometry import ceiling_speed_margin
from .vba import Grid, VBAError, clng, num, roundup, vlookup


# SECTION 7/13 — FEUILLE 'TRACK' (profil de gradient, compensation, zones) — SUBSET-026 §3.13.4, §3.13.5.
# ==========================================================================

"""Port of ``button_track_Click`` (Sheet4, 'Track'): gradient profile, train-length
compensation, reduced adhesion and brake-inhibition areas, distance pivots."""

from collections import deque


COMB2 = "Comb. n°2"


class AbortCalculation(Exception):
    """The macro stopped with a 'Calculation aborted' message box."""


# Feuille 'Track' : profil de gradient (§3.13.4.1, §3.13.2.3.3), zones sans
# contribution des freins spéciaux (§3.13.5.1-§3.13.5.2 → comb. n°2), zones
# d'adhérence réduite (§3.13.5.3-§3.13.5.5: A_MAXREDADH étendue de la longueur
# du train, §3.13.6.2.1.6), compensation longueur/masses tournantes (§3.13.4.2,
# §3.13.4.3), pivots de distance pour le balayage A.3.12.
def build_track(ctx) -> Grid:
    sc = ctx.sc
    tr, t, fv, nv = sc.track, sc.train, sc.fixed, sc.national
    g = Grid("Track")
    ctx.track = g
    L = clng(t.overall_length)                                   # D26 (Long)
    gamma = t.train_type == "gamma"
    d_target = tr.d_target
    V_target = tr.V_target
    d_finish = tr.d_target + tr.d_svl
    # balises F2:G31
    for i, (d, acc) in enumerate(tr.balises):
        g[2 + i, 6] = d
        g[2 + i, 7] = acc
    # gradient profile I3:Jn (input rows are copied: the macro edits the I column)
    rows = [list(r) for r in tr.gradient]
    for i, (d, gr) in enumerate(rows):
        g[3 + i, 9] = d
        g[3 + i, 10] = gr
    p = 3
    if g[p, 10] in (None, ""):
        ctx.warn("No gradient value entered, 0 gradient profile assumed up to EBD foot")
        g[p + 1, 9] = d_finish
        g[p, 10] = 0
        g[p + 1, 10] = 0
        last_step = p + 1
    else:
        while g[p, 10] not in (None, ""):
            if g[p + 2, 10] in (None, "") and g[p + 1, 9] not in (None, ""):
                if g[p + 1, 9] < d_finish:
                    if tr.target != "LOA_MRSP":
                        ctx.warn("SvL beyond end of entered gradient profile: profile extended "
                                 "with the last gradient value entered")
                    g[p + 1, 9] = d_finish
                    ctx.gradient_extended_to = d_finish
                else:
                    d_finish = g[p + 1, 9]
            p += 2
        last_step = p - 1

    def profile():
        n = last_step - 3 + 1
        keys = [g[3 + i, 9] for i in range(n)]
        keys = [None if k in (None, "") else float(k) for k in keys]
        vals = [g[3 + i, 10] for i in range(n)]
        return keys, vals

    # Brake inhibition interval (gamma)
    if gamma and tr.brake_inhibition and tr.brake_inhib_start <= d_finish:
        for r in range(clng(tr.brake_inhib_start + 36), clng(d_finish + 36) + 1):
            g[r, 6] = COMB2
    # Reduced adhesion
    # A_MAXREDADH applicable — SUBSET-026 §3.13.5.3-§3.13.5.5 ; sélection de
    # A_NVMAXREDADH1/2/3 selon les freins spéciaux indépendants de l'adhérence et la
    # position de frein (§3.13.2.3.7.5, §3.13.5.4).
    if tr.reduced_adhesion:
        if t.brake_position == "Passenger in P":
            a_max = nv.A_NVMAXREDADH1 if t.special_brake_indep_adhesion else nv.A_NVMAXREDADH2
        else:
            a_max = nv.A_NVMAXREDADH3
        for a in range(clng(tr.reduced_adh_start) + 36, clng(tr.reduced_adh_end) + L + 36 + 1):
            g[a, 5] = a_max

    keys, vals = profile()
    g[36, 1] = 0
    last_u = int(d_finish + 36)
    for u in range(37, last_u + 1):
        if g[u - 1, 1] < d_finish:
            g[u, 1] = g[u - 1, 1] + 1
    for u in range(36, last_u + 1):
        g[u, 2] = vlookup(keys, vals, g[u, 1])
    _compensate(ctx, g, 36, last_u, L)

    # LOA/MRSP: EBD foot must lie within the gradient profile
    d_finish_ext = d_finish
    if tr.target == "LOA_MRSP":
        extended = False
        V_ebd = V_target + ceiling_speed_margin(V_target, fv.V_ebi_min, fv.V_ebi_max, fv.dV_ebi_min, fv.dV_ebi_max)
        V_temp, d_temp = V_ebd, d_target
        while not (V_temp <= V_target):
            A_safe = ctx.A_safe(V_temp, d_finish if extended else d_temp)
            if A_safe <= 0:
                raise AbortCalculation("Calculation aborted, A_safe null or negative")
            d_temp = d_temp + ((V_temp / 3.6) ** 2 - ((V_temp - 0.1) / 3.6) ** 2) / (2 * A_safe)
            if d_temp > d_finish and not extended:
                ctx.warn("LOA/MRSP target: EBD foot beyond end of entered gradient profile; "
                         "profile extended with the last gradient value entered")
                extended = True
            V_temp = V_temp - 0.1
        if extended:
            d_finish_ext = roundup(d_temp, 0)
            g[last_step, 9] = d_finish_ext
            ctx.gradient_extended_to = d_finish_ext
        keys, vals = profile()
        last_ext = int(d_finish_ext + 36)
        u0 = clng(d_finish + 37)
        for u in range(u0, last_ext + 1):
            if g[u - 1, 1] < d_finish_ext:
                g[u, 1] = g[u - 1, 1] + 1
        for u in range(u0, last_ext + 1):
            g[u, 2] = vlookup(keys, vals, g[u, 1])
        _compensate(ctx, g, u0, last_ext, L)
        if gamma and tr.brake_inhibition and tr.brake_inhib_start <= d_finish:
            for r in range(u0, last_ext + 1):
                g[r, 6] = COMB2

    # distance pivot values
    calc = ctx.calc
    lam = t.train_type == "lambda"
    last_ext = int(d_finish_ext + 36)
    if lam:
        calc.clear(2, 2, 44, 2)
        calc.clear(2, 5, 44, 5)
        s = 0
        for ligne in range(37, last_ext + 1):
            if g[ligne - 1, 4] != g[ligne, 4] or g[ligne - 1, 5] != g[ligne, 5]:
                calc[s + 2, 2] = g[ligne, 1]
                s += 1
        s = 0
        for ligne in range(37, int(d_target + 36) + 1):
            if g[ligne - 1, 4] != g[ligne, 4]:
                calc[s + 2, 5] = g[ligne, 1]
                s += 1
    else:
        calc.clear(2, 3, 44, 3)
        calc.clear(2, 7, 44, 7)
        s = 0
        for ligne in range(37, last_ext + 1):
            if (g[ligne - 1, 4] != g[ligne, 4] or g[ligne - 1, 5] != g[ligne, 5]
                    or g[ligne - 1, 6] != g[ligne, 6]):
                calc[s + 2, 3] = g[ligne, 1]
                s += 1
        s = 0
        for ligne in range(37, int(d_target + 36) + 1):
            if g[ligne - 1, 4] != g[ligne, 4] or g[ligne - 1, 6] != g[ligne, 6]:
                calc[s + 2, 7] = g[ligne, 1]
                s += 1
    # clear everything beyond the (extended) end of the profile
    g.clear(last_ext + 1, 1, 10 ** 7, 6)
    ctx.d_finish_extended = d_finish_ext
    return g


# Compensation sur la longueur du train: gradient fictif = minimum du profil sous
# le train — SUBSET-026 §3.13.4.2.1 ; masses tournantes: A_gradient =
# G·g/(1000 + 10·λ_rot) — §3.13.4.3.2 (λ_rot nominale §3.13.2.2.10, sinon
# M_rotating_max si G>0 / M_rotating_min si G<0).
def _compensate(ctx, g: Grid, r_from: int, r_to: int, L: int):
    """Train length compensation (sliding minimum over L+1 rows) and A_gradient."""
    fv, t = ctx.sc.fixed, ctx.sc.train
    lo = max(36, r_from - L)
    dq: deque = deque()
    for i in range(lo, r_to + 1):
        v = g[i, 2]
        if v is None:
            raise VBAError("Track: missing raw gradient value at row %d" % i)
        while dq and g[dq[-1], 2] >= v:
            dq.pop()
        dq.append(i)
        while dq[0] < max(36, i - L):
            dq.popleft()
        if i < r_from:
            continue
        gr = g[dq[0], 2]
        g[i, 3] = gr
        if t.rotating_mass_pct is not None:
            g[i, 4] = gr * fv.g / (1000 + 10 * t.rotating_mass_pct)
        elif gr > 0:
            g[i, 4] = gr * fv.g / (1000 + 10 * fv.M_rotating_max)
        else:
            g[i, 4] = gr * fv.g / (1000 + 10 * fv.M_rotating_min)


# ==========================================================================
