from __future__ import annotations

from .geometry import S41_speed_inacc, ceiling_speed_margin
from .vba import Ref, gt, is_blank, num, vint, vround, vlookup, wmax, wmin, vpow


# SECTION 8/13 — COURBES EBD/SBD/GUI ET LIMITES EBI/SBI/W/P/I, RELEASE SPEED — SUBSET-026 §3.13.8, §3.13.9.
# ==========================================================================

"""Port of VBA Module4 ``calculate_curves`` (sheets 'Curves Lambda train' /
'Curves Gamma train').  The worksheet columns are kept as storage so that the
algorithm (and its quirks) can be compared line by line with the VBA.
"""


# worksheet columns
N, O, P, Q, R, S, T, U, V, W, X, Y, Z = range(14, 27)
AA, AB, AC, AD, AE, AF, AG, AH, AI, AJ, AK, AL = range(27, 39)
AO, AP, AQ, AR, AS, AT, AU, AV, AW, AX, AY, AZ = range(41, 53)


def _abort(msg="Calculation aborted, insufficient distance origin-target"):
    raise AbortCalculation(msg)


# Courbes et limites de supervision — SUBSET-026 §3.13.8 (EBD: §3.13.8.3, SBD:
# §3.13.8.4, GUI: §3.13.8.5) et §3.13.9 (plafonds: §3.13.9.2, EBI: §3.13.9.3.2,
# SBI: §3.13.9.3.3, W: §3.13.9.3.4, P: §3.13.9.3.5, I: §3.13.9.3.6, release
# speed: §3.13.9.4). Distances comptées depuis l'origine (§3.13.1.4) ; cible
# unique EOA/SvL ou LOA/MRSP (§3.13.8.2). Stockage fidèle aux colonnes du
# classeur pour permettre --compare.
def calculate_curves(e, gamma: bool, initial_speed: float):  # noqa: C901  (faithful port)
    sc = e.sc
    tm, tr, nv, fv = sc.train, sc.track, sc.national, sc.fixed
    C = e.curves
    EOA = tr.target == "EOA_SvL"
    LOA = not EOA
    GUI = nv.Q_NVGUIPERM
    INHSMIC_no = not nv.Q_NVINHSMICPERM
    SBTSM = nv.Q_NVSBTSMPERM
    SBint = tm.service_brake_interface
    user_sci = tm.speed_inaccuracy == "user"
    D8 = num(tm.speed_inaccuracy_pct)
    D20 = tm.antenna_to_front

    # module-level / un-initialised VBA variables keep their value between iterations
    st = dict(t_be_enough_step_dist=0.0, t_bs_enough_step_dist=0.0, shift_SBI_W=0.0, q=0,
              coefflevel=0, V_release=0.0, release_speed_found=False, GUI_foot_changed=False,
              gc2=False, gc2_after=False, perturbation=0.0, startrsm=0.0)

    V_linespeed = initial_speed
    V_target = tr.V_target
    d_target = tr.d_target
    d_finish = tr.d_target + tr.d_svl

    csm = ceiling_speed_margin
    # Marges de plafond à la cible et à la vitesse ligne — SUBSET-026 §3.13.9.2.3
    # (dV_ebi), §3.13.9.2.5 (dV_sbi), §3.13.9.2.6 (dV_warning) ; LOA: §3.13.9.2.7.
    dV_ebi_target = csm(V_target, fv.V_ebi_min, fv.V_ebi_max, fv.dV_ebi_min, fv.dV_ebi_max)
    dV_sbi_target = csm(V_target, fv.V_sbi_min, fv.V_sbi_max, fv.dV_sbi_min, fv.dV_sbi_max)
    dV_warning_target = csm(V_target, fv.V_warning_min, fv.V_warning_max, fv.dV_warning_min, fv.dV_warning_max)
    dV_ebi_ls = csm(V_linespeed, fv.V_ebi_min, fv.V_ebi_max, fv.dV_ebi_min, fv.dV_ebi_max)
    dV_sbi_ls = csm(V_linespeed, fv.V_sbi_min, fv.V_sbi_max, fv.dV_sbi_min, fv.dV_sbi_max)
    dV_warning_ls = csm(V_linespeed, fv.V_warning_min, fv.V_warning_max, fv.dV_warning_min, fv.dV_warning_max)

    A_est1 = tm.A_est1
    if gamma:
        V_delta12_max = 3.6 * A_est1 * max(sc.gamma_brake.comb2["T_brake_emergency"],
                                           sc.gamma_brake.comb1["T_brake_emergency"])
    else:
        V_delta12_max = 3.6 * A_est1 * e.lp.T_brake_emergency * e.lp.Kt_int
    if user_sci:
        # Outil: borne supérieure de la table EBD = (V_linespeed + dV_ebi) majoré de
        # V_ura (§3.13.9.3.2.1 / SUBSET-041) ou du pourcentage utilisateur, + V_delta12_max
        # (surestime la vitesse atteinte en fin de montée EB: cf. §A.3.12).
        EBD_upper_speed = (V_linespeed + dV_ebi_ls) * (1 + D8 / 100) + V_delta12_max
    else:
        # Outil: borne supérieure de la table EBD = (V_linespeed + dV_ebi) majoré de
        # V_ura (§3.13.9.3.2.1 / SUBSET-041) ou du pourcentage utilisateur, + V_delta12_max
        # (surestime la vitesse atteinte en fin de montée EB: cf. §A.3.12).
        EBD_upper_speed = V_linespeed + dV_ebi_ls + S41_speed_inacc(V_linespeed + dV_ebi_ls) + V_delta12_max

    C[2, N] = 0
    for qq in range(3, vint(EBD_upper_speed * 10) + 2 + 1):
        C[qq, N] = vround(C[qq - 1, N] + 0.1, 1)

    if LOA:
        # LOA/MRSP: l'EBD part de V_target + dV_ebi (plafond EBI à la cible —
        # §3.13.9.2.7) ; EOA/SvL: pieds EBD/SBD à la SvL (§3.13.8.3.2), d_finish =
        # d_target + d_svl ; A_safe/A_expected > 0 (§3.13.6.2.1.1).
        V_ebd = V_target + dV_ebi_target
        C[vint(V_ebd * 10) + 2, R] = 0
        A_Safe = e.A_safe(V_ebd, d_target)
        if A_Safe <= 0:
            _abort("Calculation aborted, A_safe null or negative")
        C[vint(V_ebd * 10) + 2, O] = A_Safe
    else:
        C[2, R] = -tr.d_svl
        C[2, S] = 0
        C[2, AE] = 0
        C[2, AF] = -tr.d_svl
        V_ebd = 0.0
        A_Safe = e.A_safe(0, d_finish)
        A_Expected = e.A_expected(0, d_target)
        if A_Safe <= 0:
            _abort("Calculation aborted, A_safe null or negative")
        C[2, O] = A_Safe
        if A_Expected <= 0:
            _abort("Calculation aborted, A_expected null or negative")
        C[2, P] = A_Expected
        if tr.release_speed == "onboard":
            st["V_release"] = 0.0
            st["release_speed_found"] = False
            st["coefflevel"] = 1 if tr.level == 1 else 0
    coefflevel = st["coefflevel"]
    coeffSM = 1 if tm.supervised_manoeuvre else 0

    T_traction_cut_off = tm.T_traction_cut_off
    T_warning, T_driver, T_41 = fv.T_warning, fv.T_driver, fv.T_41

    # ------------------------------------------------------------------ EBD
    # EBD: intégration de (V/3,6)² / (2·A_safe) par pas de 0,1 km/h, A_safe réévaluée
    # à chaque pas — SUBSET-026 §3.13.8.3.1-§3.13.8.3.3.
    p = vint(V_ebd * 10) + 3 if LOA else 3
    while not is_blank(C[p, N]):
        C[p, R] = C.n(p - 1, R) + ((C.n(p, N) / 3.6) ** 2 - (C.n(p - 1, N) / 3.6) ** 2) / (2 * A_Safe)
        if C.n(p, R) < d_target:
            A_Safe = e.A_safe(C[p, N], d_target - C.n(p, R))
            if A_Safe <= 0:
                _abort("Calculation aborted, A_safe null or negative")
            C[p, O] = A_Safe
            p += 1
        else:
            _abort()
    # EBD sous la cible jusqu'à V_target (MRSP/LOA: le pied de l'EBD est à la cible,
    # §3.13.8.3.1).
    if LOA:      # EBD beyond the target
        p = vint(V_ebd * 10) + 1
        A_Safe = e.A_safe(V_ebd, d_target)
        while p != vint(V_target * 10) + 1:
            C[p, R] = C.n(p + 1, R) + ((C.n(p, N) / 3.6) ** 2 - (C.n(p + 1, N) / 3.6) ** 2) / (2 * A_Safe)
            A_Safe = e.A_safe(C[p, N], d_target - C.n(p, R))
            if A_Safe <= 0:
                _abort("Calculation aborted, A_safe null or negative")
            C[p, O] = A_Safe
            p -= 1

    # ------------------------------------------------------------------ SBD
    if EOA:
        p = 3
        # SBD (cible EOA) — SUBSET-026 §3.13.8.4.1 : intégration avec A_expected
        # (§3.13.6.3.1.3) jusqu'à l'EOA.
        C[2, AJ] = 0
        while not is_blank(C[p, N]):
            C[p, AJ] = C[p, N]
            C[p, S] = C.n(p - 1, S) + ((C.n(p, N) / 3.6) ** 2 - (C.n(p - 1, N) / 3.6) ** 2) / (2 * A_Expected)
            if C.n(p, S) < d_target:
                A_Expected = e.A_expected(C[p, N], d_target - C.n(p, S))
                if A_Expected <= 0:
                    _abort("Calculation aborted, A_expected null or negative")
                C[p, P] = A_Expected
                p += 1
            else:
                _abort()

    # ------------------------------------------------------- GUI for EOA/SvL
    if GUI and EOA:
        # GUI pour EOA/SvL — SUBSET-026 §3.13.8.5.1-§3.13.8.5.2 (si Q_NVGUIPERM):
        # courbes de guidage calculées avec A_normal_service (§3.13.6.4.3) depuis l'EOA
        # et depuis la SvL (frein de service normal appliqué en amont du point d'arrêt).
        C[2, AG] = 0
        p = 3
        A_ns = e.A_normal_service(0, d_target)
        while not is_blank(C[p, N]):
            C[p, AG] = C[p, N]
            C[p, AE] = C.n(p - 1, AE) + ((C.n(p, N) / 3.6) ** 2 - (C.n(p - 1, N) / 3.6) ** 2) / (2 * A_ns)
            if C.n(p, AE) < d_target:
                A_ns = e.A_normal_service(C[p, N], d_target - C.n(p, AE))
                if A_ns <= 0:
                    _abort("Calculation aborted, A_normal_service null or negative")
                p += 1
            else:
                _abort()
        p = 3
        A_ns = e.A_normal_service(0, d_finish)
        while not is_blank(C[p, N]):
            C[p, AF] = C.n(p - 1, AF) + ((C.n(p, N) / 3.6) ** 2 - (C.n(p - 1, N) / 3.6) ** 2) / (2 * A_ns)
            if C.n(p, AF) < d_target:
                A_ns = e.A_normal_service(C[p, N], d_target - C.n(p, AF))
                if A_ns <= 0:
                    _abort("Calculation aborted, A_normal_service null or negative")
                p += 1
            else:
                _abort()

    gb = sc.gamma_brake
    inhib_start = tr.brake_inhib_start
    if gamma:
        st["gc2"] = False
        st["gc2_after"] = False
        if GUI and LOA:
            st["GUI_foot_changed"] = False

    # brake parameters that do not depend on the speed step (lambda)
    if not gamma:
        lp = e.lp
        lam_t_be = lp.T_brake_emergency * lp.Kt_int
        lam_t_be_react = lp.T_brake_emergency_react * lp.Kt_int
        if sc.lambda_brake.conversion_model:
            lam_t_bs, lam_t_bs_react = lp.T_brake_service, lp.T_brake_service_react
        else:
            lam_t_bs, lam_t_bs_react = num(lp.T_brake_service_user), num(lp.T_brake_service_react_user)

    Train_position = 0.0
    V_delta0 = 0.0
    shift_EBI_SBI2 = shift_EBI_SBI2_I = shift_P = shift_I = 0.0
    q = 0
    perturbation = 0.0
    T_traction_nr = T_berem_nr = T_traction_max = T_traction_min = 0.0
    t_bs1_nr = t_bs2_nr = 0.0
    V_bec_A = 0.0

    # ======================================== EBI, SBI, W, P, I supervision limits
    p_first = vint((V_linespeed + dV_ebi_ls) * 10) + 2
    for p in range(p_first, vint(V_target * 10) + 2 - 1, -1):
        V_est = C.n(p, N)
        if V_est >= V_linespeed:
            if tm.supervised_manoeuvre:
                if tm.engine_orientation_same:
                    Train_position = d_target - D20 - tm.consist_front_nom
                else:
                    Train_position = d_target + D20 - tm.consist_rear_nom
            else:
                Train_position = d_target - D20

        if gamma:
            if tr.brake_inhibition and (d_target - Train_position + e.Position_inacc(Train_position, coeffSM)
                                        >= inhib_start):
                st["gc2"] = True
                cb = gb.comb2
            else:
                st["gc2"] = False
                cb = gb.comb1
            t_be, t_bs = cb["T_brake_emergency"], cb["T_brake_service"]
            t_be_react, t_bs_react = cb["T_brake_emergency_react"], cb["T_brake_service_react"]
        else:
            t_be, t_be_react, t_bs, t_bs_react = lam_t_be, lam_t_be_react, lam_t_bs, lam_t_bs_react

        t_2be = 2 * t_be - t_be_react
        t_2bs = 2 * t_bs - t_bs_react
        if SBTSM and SBint:
            t_bs1_nr = t_bs2_nr = t_bs
        else:
            t_bs1_nr = t_bs2_nr = 0.0

        if V_est <= V_linespeed + dV_ebi_ls:
            if tm.traction_cut_off_interface:
            # T_traction (sans rétroaction du frein de service) — SUBSET-026 §3.13.9.3.2.3 :
            # T_traction_cut_off − (T_warning + T_bs2) si interface de coupure de traction,
            # sinon T_traction_cut_off (note §3.13.9.3.2.4) ; T_berem = max(T_be_reduced −
            # T_traction, 0) — §3.13.9.3.2.6.
                T_traction_nr = max(T_traction_cut_off - (T_warning + t_bs2_nr), 0)
                if SBTSM and SBint:
                # T_traction_max / T_traction_min avec rétroaction du frein de service (T_bs1/
                # T_bs2 non verrouillés) — SUBSET-026 §3.13.9.3.2.3, Annexe A §A.3.10.4.
                    T_traction_max = max(T_traction_cut_off - (T_warning + t_bs_react), 0)
                    T_traction_min = max(T_traction_cut_off - (T_warning + t_bs), 0)
                else:
                    T_traction_max = T_traction_min = T_traction_nr
            else:
                T_traction_nr = T_traction_max = T_traction_min = T_traction_cut_off
            T_berem_nr = max(t_be - T_traction_nr, 0)

            if INHSMIC_no:
                V_delta0 = V_est * D8 / 100 if user_sci else S41_speed_inacc(V_est)
            else:
                V_delta0 = 0.0
            # A_est2 = min(A_est1, 0,4) — SUBSET-026 §3.13.9.3.2.9 (accélération estimée
            # pendant T_berem).
            A_est2 = min(A_est1, 0.4)

            A_EB = A_SafeMax = A_SB = A_ExpectedMax = fv.g
            A_EB_after = A_SafeMax_after = A_SB_after = A_ExpectedMax_after = 0.0
            converg_index = 0
            # Convergence itérative: A_EB/A_SB/A_SafeMax/A_ExpectedMax dépendent de
            # Train_position (le pied des courbes P/I décalées) — valeurs définies par
            # l'Annexe A §A.3.12.2.2-§A.3.12.2.5.
            while not ((A_EB_after == A_EB and A_SB_after == A_SB and A_SafeMax == A_SafeMax_after
                        and A_ExpectedMax == A_ExpectedMax_after) or converg_index == 5):
                V_delta1 = A_est1 * T_traction_nr * 3.6
                V_delta2 = A_est2 * T_berem_nr * 3.6
                # V_bec pour le calcul de A_EB/A_safe_max — cf. §3.13.9.3.2.10 et Annexe A
                # §A.3.12.2.2-§A.3.12.2.3 (sans T_driver: cas 'no reaction' pour l'évaluation
                # des décélérations min/max).
                V_bec_A = max(V_est + V_delta0 + V_delta1, V_target) + V_delta2
                A_EB = e.A_EB_grid(V_bec_A, d_target - Train_position)
                A_SafeMax = e.A_SafeMax_grid(V_bec_A, d_target - Train_position)
                A_SB = e.A_SB_grid(V_est, d_target - Train_position)
                A_ExpectedMax = e.A_ExpectedMax_grid(V_est, d_target - Train_position)

                # V_t1be: vitesse estimée à la fin du temps de réaction EB — Annexe A §A.3.12.3.1
                # (exceptions EOA/MRSP-LOA: §A.3.12.3.2-§A.3.12.3.5) ; V_t2be: vitesse en fin de
                # rampe — §A.3.12.4.1-§A.3.12.4.3.
                V_t1be = V_est + V_delta0
                if T_traction_max < t_be_react:
                    V_t1be = V_t1be + A_est1 * T_traction_max * 3.6 + A_est2 * (t_be_react - T_traction_max) * 3.6
                else:
                    V_t1be = V_t1be + A_est1 * t_be_react * 3.6
                V_t2be = max(0, V_est + V_delta0 + A_est1 * T_traction_max * 3.6
                             + A_est2 * (t_2be - T_traction_max) * 3.6 - A_EB * (t_2be - t_be_react) * 3.6 / 2)

                # T_be_reduced — SUBSET-026 §3.13.6.2.2.4 + Annexe A §A.3.12 : t_2be =
                # 2·T_be − T_be_react (§A.3.12.2.1), t_2be_enough (§A.3.12.5.1), D_t2be_enough
                # (§A.3.12.6.1), équivalence en distance t_be_enough_step_dist (§A.3.12.7,
                # formules §A.3.12.9.13 si A_est1=0 / §A.3.12.9.14-§A.3.12.9.15 si A_est1>0),
                # t_be_reduced = max(T_be_react, min(t_be_enough_step, T_be)) (§A.3.12.8.1-
                # §A.3.12.8.2) ; cas standstill/cible atteinte: §A.3.12.3.2, §A.3.12.3.4,
                # §A.3.12.4.2-§A.3.12.4.3 ; exception T_traction ≥ T_be: §A.3.12.1.5.
                if T_traction_min >= t_be:
                    t_be_reduced = t_be
                elif EOA and V_t1be == 0:
                    t_be_reduced = t_be_react
                elif LOA and V_t1be <= V_target:
                    t_be_reduced = t_be_react
                elif EOA and V_t2be > 0:
                    t_be_reduced = t_be
                elif LOA and V_t2be >= V_target:
                    t_be_reduced = t_be
                else:
                    dV_eb_t = max(0, V_est + V_delta0 - V_target)
                    t_be_incr = t_2be - t_be_react
                    t_2be_enough = (t_be_react + ((A_est2 / A_EB) * t_be_incr)
                                    + vpow(((A_est2 / A_EB) * t_be_incr) ** 2 + (2 * t_be_incr / A_EB)
                                           * ((dV_eb_t / 3.6) + (A_est1 - A_est2) * T_traction_max
                                              + A_est2 * t_be_react), 0.5))
                    D_t2be_enough = ((((A_est2 - A_est1) * (T_traction_max ** 2) / 2)
                                      + A_EB * (t_be_react ** 3) / (6 * t_be_incr))
                                     + ((V_est + V_delta0) / 3.6 + (A_est1 - A_est2) * T_traction_max
                                        - A_EB * (t_be_react ** 2) / (2 * t_be_incr)) * t_2be_enough
                                     + (A_est2 + A_EB * t_be_react / t_be_incr) * ((t_2be_enough ** 2) / 2)
                                     + (-A_EB / t_be_incr) * (t_2be_enough ** 3) / 6)
                    if A_est1 == 0:
                        st["t_be_enough_step_dist"] = ((D_t2be_enough + ((V_target / 3.6) ** 2) / (2 * A_SafeMax))
                                                       / ((V_est + V_delta0) / 3.6)
                                                       - ((V_est + V_delta0) / 3.6) / (2 * A_SafeMax))
                    elif A_est1 > 0:
                        t_be_x = ((V_est + V_delta0) / 3.6 + (A_est1 - A_est2) * T_traction_min) / (-A_est2)
                        t_be_y = vpow((A_SafeMax / (A_SafeMax + A_est2))
                                      * ((t_be_x ** 2) + ((A_est1 - A_est2) * (T_traction_min ** 2)
                                                          + (2 * D_t2be_enough)) / A_est2)
                                      + ((V_target / 3.6) ** 2) / (A_est2 * (A_SafeMax + A_est2)), 0.5)
                        st["t_be_enough_step_dist"] = t_be_x + t_be_y
                    t_be_enough_step = (t_be_react + t_2be_enough) / 2
                    t_be_enough_step = max(t_be_enough_step, st["t_be_enough_step_dist"])
                    t_be_reduced = max(t_be_react, min(t_be_enough_step, t_be))

                # T_bs_reduced (frein de service) — SUBSET-026 §3.13.6.3.2.5 + Annexe A
                # §A.3.12.5.2 (t_2bs_enough), §A.3.12.6.1 (D_t2bs_enough), §A.3.12.8
                # (t_bs_reduced) ; V_t2bs: §A.3.12.4.4-§A.3.12.4.6.
                V_t1bs = V_est
                V_t2bs = max(0, V_est - A_SB * (t_2bs - t_bs_react) * 3.6 / 2)
                if EOA and V_t1bs == 0:
                    t_bs_reduced = t_bs_react
                elif LOA and V_t1bs <= V_target:
                    t_bs_reduced = t_bs_react
                elif EOA and V_t2bs > 0:
                    t_bs_reduced = t_bs
                elif LOA and V_t2bs >= V_target:
                    t_bs_reduced = t_bs
                else:
                    dV_sb_t = max(0, V_est - V_target)
                    t_bs_incr = t_2bs - t_bs_react
                    t_2bs_enough = t_bs_react + vpow((2 * t_bs_incr / A_SB) * dV_sb_t / 3.6, 0.5)
                    D_t2bs_enough = (V_est / 3.6) * t_2bs_enough + (-A_SB / (6 * t_bs_incr)) * ((t_2bs_enough - t_bs_react) ** 3)
                    if V_est > 0:
                        st["t_bs_enough_step_dist"] = ((D_t2bs_enough + ((V_target / 3.6) ** 2) / (2 * A_ExpectedMax))
                                                       / (V_est / 3.6) - (V_est / 3.6) / (2 * A_ExpectedMax))
                    elif V_est == 0:
                        st["t_bs_enough_step_dist"] = t_bs_react
                    t_bs_enough_step = (t_bs_react + t_2bs_enough) / 2
                    t_bs_enough_step = max(t_bs_enough_step, st["t_bs_enough_step_dist"])
                    t_bs_reduced = max(t_bs_react, min(t_bs_enough_step, t_bs))

                if SBTSM and SBint:
                # T_bs1 / T_bs2 — SUBSET-026 §3.13.9.3.3.3-§3.13.9.3.3.6 : T_bs_reduced si la
                # commande et la rétroaction du frein de service sont disponibles, sinon 0 ;
                # Annexe A §A.3.10.4 (verrouillage T_bs1/T_bs2 non modélisé au-delà).
                    t_bs1 = t_bs2 = t_bs_reduced
                else:
                    t_bs1 = t_bs2 = 0.0
                if tm.traction_cut_off_interface:
                # T_traction final — SUBSET-026 §3.13.9.3.2.3.
                    T_traction = max(T_traction_cut_off - (T_warning + t_bs2), 0)
                else:
                    T_traction = T_traction_cut_off
                T_berem_min = max(t_be_react - T_traction_max, 0)
                T_berem = max(t_be_reduced - T_traction, 0)

                V_delta1 = A_est1 * T_traction * 3.6
                V_delta2 = A_est2 * T_berem * 3.6
                # V_bec / D_bec — SUBSET-026 §3.13.9.3.2.10 :
                #   V_bec = max(V_est + V_delta0 + V_delta1, V_target) + V_delta2   (note §3.13.9.3.2.11)
                #   D_bec = distance parcourue pendant T_traction + T_berem.
                V_bec = max(V_est + V_delta0 + V_delta1, V_target) + V_delta2
                D_bec = ((max(V_est + V_delta0 + V_delta1 * 0.5, V_target) * T_traction / 3600) * 1000
                         + ((max(V_est + V_delta0 + V_delta1, V_target) + 0.5 * V_delta2) * T_berem / 3600) * 1000)
                # d_EBI(V_est) = d_EBD(V_bec) − D_bec — SUBSET-026 §3.13.9.3.2.12 (localisation
                # de la limite EBI à partir de la courbe EBD).
                ebd = C.vlookup(V_bec, N, 2, 10000, 5)
                if not is_blank(ebd):
                    C[p, T] = num(ebd) + D_bec
                    C[p, AK] = t_be_reduced
                    C[p, AL] = t_bs_reduced
                    if C.n(p, T) >= d_target:
                        _abort()
                else:
                    _abort("Calculation aborted, EBD point not found")

                # EBI précalculé pour la release speed embarquée — SUBSET-026 §3.13.9.4.8.1-
                # §3.13.9.4.8.2 : d_EBD(V_est + V_ura) + (V/3,6)·( T_traction_cut_off +
                # max(T_be − T_traction_cut_off, 0) + α·T_41 ) — traction cut-off considérée non
                # implémentée, T_be non réduit ; α = 1 en niveau 1 (T_41: SUBSET-041 §5.2.1.13).
                # EBI used to determine the release speed calculated on-board
                if EOA and tr.release_speed == "onboard":
                    if INHSMIC_no:
                        if user_sci:
                            V_delta0rsob = max(V_est * D8 / 100, S41_speed_inacc(V_est))
                        else:
                            V_delta0rsob = S41_speed_inacc(V_est)
                    else:
                        V_delta0rsob = 0.0
                    ebd = C.vlookup(V_est + V_delta0rsob, N, 2, 10000, 5)
                    if not is_blank(ebd):
                        C[p, AA] = num(ebd) + ((V_est + V_delta0rsob) / 3.6) * (
                            T_traction_cut_off + max(t_be - T_traction_cut_off, 0) + coefflevel * T_41)
                    else:
                        _abort("Calculation aborted, EBD point not found")

                # SBI2 (cible basée EBD: LOA/MRSP) — SUBSET-026 §3.13.9.3.3.2 :
                # d_SBI2 = d_EBI + V_est×T_bs2 (vitesse supposée constante pendant T_bs2).
                # SBI2
                if V_est <= V_linespeed + dV_sbi_ls:
                    C[p, V] = C.n(p, T) + V_est * 1000 / 3600 * t_bs2
                    if C.n(p, V) >= d_target:
                        _abort()
                else:
                    C[p, V] = ""

                # SBI1 (EOA, depuis la courbe SBD: §3.13.9.3.3.1) et SBI = max(SBI1, SBI2)
                # (§3.13.9.3.1.2-§3.13.9.3.1.3).
                if EOA:      # SBI1 and resulting SBI
                    if V_est <= V_linespeed + dV_sbi_ls:
                        C[p, U] = C.n(p, S) + V_est * 1000 / 3600 * t_bs1
                        if C.n(p, U) >= d_target:
                            _abort()
                    else:
                        C[p, U] = ""
                    if not is_blank(C[p, U]) and not is_blank(C[p, V]):
                        C[p, W] = wmax(Ref(C[p, U]), Ref(C[p, V]))
                else:
                    C[p, W] = C[p, V]

                # GUI pour cible LOA/MRSP — SUBSET-026 §3.13.8.5.1 : pied du GUI calculé depuis
                # l'EBD à V_target (+V_ura) avec T_traction_max/T_berem_min (frein d'urgence sans
                # traction), puis V_target×(T_driver + T_bs_gui) — cf. §3.13.9.3.5.4 ; remontée
                # avec A_normal_service jusqu'à V_est.
                # GUI curve for LOA/MRSP target (its foot depends on T_be, T_bs2)
                if GUI and LOA:
                    V_delta0 = S41_speed_inacc(V_target) if INHSMIC_no else 0.0   # (VBA re-uses V_delta0)
                    t_bs_gui = t_bs_react if (SBTSM and SBint) else t_bs2
                    V_bec = V_target + V_delta0
                    D_bec = V_bec * (T_traction_max + T_berem_min) * 1000 / 3600
                # d_EBI(V_est) = d_EBD(V_bec) − D_bec — SUBSET-026 §3.13.9.3.2.12 (localisation
                # de la limite EBI à partir de la courbe EBD).
                    ebd = C.vlookup(V_bec, N, 2, 10000, 5)
                    if not is_blank(ebd):
                        GUI_foot = max(num(ebd) + D_bec + (V_target * (T_driver + t_bs_gui) * 1000 / 3600), 0)
                    else:
                        _abort("Calculation aborted, EBD point not found")
                    if p == p_first:
                        A_ns = e.A_normal_service(V_target, d_target - GUI_foot)
                        v = vint(V_target * 10) + 3
                        C[v - 1, AI] = C[v - 1, N]
                        C[v - 1, AH] = GUI_foot
                        C[v - 1, Q] = A_ns
                        while not (v > p):
                            C[v, AI] = C[v, N]
                            C[v, AH] = C.n(v - 1, AH) + ((C.n(v, N) / 3.6) ** 2 - (C.n(v - 1, N) / 3.6) ** 2) / (2 * A_ns)
                            if C.n(v, AH) < d_target:
                                A_ns = e.A_normal_service(C[v, N], d_target - C.n(v, AH))
                                if A_ns < 0:
                                    _abort("Calculation aborted, A_normal_service negative")
                                C[v, Q] = A_ns
                                v += 1
                            else:
                                _abort()
                    elif st["GUI_foot_changed"]:
                        v = vint(V_target * 10) + 3
                        C[v - 1, AI] = C[v - 1, N]
                        C[v - 1, AH] = GUI_foot
                        A_ns = e.A_normal_service(V_target, d_target - GUI_foot)
                        while not (C.n(v, N) > V_est):
                            C[v, AI] = C[v, N]
                            C[v, AH] = C.n(v - 1, AH) + ((C.n(v, N) / 3.6) ** 2 - (C.n(v - 1, N) / 3.6) ** 2) / (2 * A_ns)
                            if C.n(v, AH) < d_target:
                                A_ns = e.A_normal_service(C[v, N], d_target - C.n(v, AH))
                                if A_ns < 0:
                                    _abort("Calculation aborted, A_normal_service negative")
                                C[v, Q] = A_ns
                                v += 1
                            else:
                                _abort()

                # Warning, Permitted and Indication
            # T_indication = max(0,8 × T_bs_reduced, 5) + T_driver — SUBSET-026
            # §3.13.9.3.6.3-§3.13.9.3.6.4 (T_indication réduit si rétroaction du frein de
            # service disponible ; T_driver: §A.3.1).
                T_indication = max(0.8 * t_bs_reduced, 5) + T_driver
                if V_est <= V_linespeed + dV_warning_ls:
                # Warning — SUBSET-026 §3.13.9.3.4.1 : d_W = d_SBI + V_est×T_warning
                # (T_warning: §A.3.1).
                    C[p, X] = C.n(p, W) + V_est * 1000 / 3600 * T_warning
                    if C.n(p, X) >= d_target:
                        _abort()
                else:
                    C[p, X] = ""

                if V_est <= V_linespeed:
                    # Permitted — SUBSET-026 §3.13.9.3.5 : avec GUI, d_P = max des max(SBI1+tdv, GUI_
                    # EOA) et max(SBI2+tdv, GUI_SvL) (§3.13.9.3.5.4) ; sans GUI, d_P = d_SBI +
                    # tdv (§3.13.9.3.5.5) ; tdv = V_est×T_driver (T_driver: §A.3.1, §3.13.9.3.5.2).
                    tdv = V_est * 1000 / 3600 * T_driver
                    if GUI:
                        if EOA:
                            C[p, Y] = wmax(wmax(C.n(p, U) + tdv, Ref(C[p, AE])), wmax(C.n(p, V) + tdv, Ref(C[p, AF])))
                        else:
                            C[p, Y] = wmax(C.n(p, V) + tdv, Ref(C[p, AH]))
                    else:
                        C[p, Y] = C.n(p, W) + tdv
                    C[p, Y] = wmax(Ref(C[p, Y]), 0)
                    if C.n(p, Y) >= d_target:
                        _abort()
                    # anticipation of the shifted P curve: virtual train front position
                    if V_est == V_linespeed:
                        if GUI:
                            if EOA:
                                Train_position = e.Shifted_startcurve(C[p, U], C[p, V], Ref(C[p, AE]), C[p, AF], V_est, C[p, Y])
                            else:
                                Train_position = e.Shifted_startcurve(0, C[p, V], 0, C[p, AH], V_est, C[p, Y])
                        else:
                            if EOA:
                                Train_position = e.Shifted_startcurve(C[p, U], C[p, V], 0, 0, V_est, C[p, Y])
                            else:
                                Train_position = e.Shifted_startcurve(0, C[p, V], 0, 0, V_est, C[p, Y])
                        if not e.Downstream_antenna_position_vs_origin(Train_position, coeffSM):
                            _abort()
                    else:
                        shift_EBI_SBI2 = e.Position_inacc(Train_position, coeffSM)
                        if C.n(p, V) + shift_EBI_SBI2 > C.n(p, U):
                            st["shift_SBI_W"] = wmin(shift_EBI_SBI2, C.n(p, V) + shift_EBI_SBI2 - C.n(p, U))
                        if EOA:
                            if GUI:
                                nd = C.n(p, N) * T_driver * 1000 / 3600
                                a = wmax(C.n(p, V) + shift_EBI_SBI2 + nd, C.n(p, AF) + shift_EBI_SBI2)
                                b = wmax(C.n(p, U) + nd, Ref(C[p, AE]))
                                shift_P = wmin(shift_EBI_SBI2, a - b) if a > b else 0.0
                            else:
                                shift_P = st["shift_SBI_W"] if C.n(p, V) + shift_EBI_SBI2 > C.n(p, U) else 0.0
                        else:
                            shift_P = shift_EBI_SBI2
                        Train_position = C.n(p, Y) + shift_P
                        if not e.Downstream_antenna_position_vs_origin(Train_position, coeffSM):
                            _abort()

                    if gamma:
                        if tr.brake_inhibition and (d_target - Train_position + e.Position_inacc(Train_position, coeffSM)
                                                    >= inhib_start):
                            st["gc2_after"] = True
                        else:
                            st["gc2_after"] = False
                        if GUI and LOA and tr.brake_inhibition:
                            if st["gc2_after"] != st["gc2"]:
                                c1, c2 = gb.comb1, gb.comb2
                                if (c2["T_brake_emergency_react"] != c1["T_brake_emergency_react"]
                                        or c2["T_brake_service_react"] != c1["T_brake_service_react"]
                                        or c2["T_brake_service"] != c1["T_brake_service"]):
                                    st["GUI_foot_changed"] = True
                            else:
                                st["GUI_foot_changed"] = False

                    A_EB_after = e.A_EB_grid(V_bec_A, d_target - Train_position)
                    A_SafeMax_after = e.A_SafeMax_grid(V_bec_A, d_target - Train_position)
                    A_SB_after = e.A_SB_grid(V_est, d_target - Train_position)
                    A_ExpectedMax_after = e.A_ExpectedMax_grid(V_est, d_target - Train_position)
                    converg_index += 1
                    C[p, AQ], C[p, AR], C[p, AS], C[p, AT] = A_EB, A_EB_after, A_SB, A_SB_after
                    C[p, AU], C[p, AV], C[p, AW], C[p, AX] = A_SafeMax, A_SafeMax_after, A_ExpectedMax, A_ExpectedMax_after
                    C[p, AY] = converg_index
                    if gamma and GUI and LOA and tr.brake_inhibition:
                        C[p, AZ] = st["GUI_foot_changed"]

                    # Indication — SUBSET-026 §3.13.9.3.6.1 : d_I = d_P + V_est×T_indication.
                    C[p, Z] = C.n(p, Y) + V_est * 1000 / 3600 * T_indication
                    if C.n(p, Z) >= d_target:
                        _abort()

                    # Outil: localisation de la perturbation = pied des courbes décalées à
                    # V_linespeed (EBI/SBI/P recalculés avec T_bs1_nr/T_bs2_nr = 0 : §3.13.9.3.3.3 ;
                    # cf. §3.13.9.3.5.9 pour la localisation de référence de la cible).
                    # perturbation location
                    if V_est == V_linespeed:
                        q = p
                        V_delta0 = S41_speed_inacc(V_est) if INHSMIC_no else 0.0
                        V_delta1 = V_delta2 = 0.0
                # V_bec / D_bec — SUBSET-026 §3.13.9.3.2.10 :
                #   V_bec = max(V_est + V_delta0 + V_delta1, V_target) + V_delta2   (note §3.13.9.3.2.11)
                #   D_bec = distance parcourue pendant T_traction + T_berem.
                        V_bec = max(V_est + V_delta0 + V_delta1, V_target) + V_delta2
                        D_bec = ((max(V_est + V_delta0 + V_delta1 * 0.5, V_target) * T_traction_nr / 3600) * 1000
                                 + ((max(V_est + V_delta0 + V_delta1, V_target) + 0.5 * V_delta2) * T_berem_nr / 3600) * 1000)
                # d_EBI(V_est) = d_EBD(V_bec) − D_bec — SUBSET-026 §3.13.9.3.2.12 (localisation
                # de la limite EBI à partir de la courbe EBD).
                        ebd = C.vlookup(V_bec, N, 2, 10000, 5)
                        if not is_blank(ebd):
                            EBI_pert = num(ebd) + D_bec
                        else:
                            _abort("Calculation aborted, EBD point not found")
                        SBI2_pert = EBI_pert + V_est * 1000 / 3600 * t_bs2_nr
                        SBI1_pert = C.n(q, S) + V_est * 1000 / 3600 * t_bs1_nr
                        vd = V_est * T_driver * 1000 / 3600
                        if GUI:
                            if EOA:
                                P_pert = wmax(wmax(SBI1_pert + vd, Ref(C[q, AE])), wmax(SBI2_pert + vd, Ref(C[q, AF])))
                            else:
                                P_pert = wmax(SBI2_pert + vd, Ref(C[q, AH]))
                        else:
                            P_pert = wmax(SBI2_pert, SBI1_pert) + vd
                        T_indication = max(0.8 * C.n(q, AL), 5) + T_driver
                        perturbation = P_pert + (V_est * 1000 / 3600 * T_indication)
                        if perturbation > d_target:
                            _abort()
                else:   # V_est > V_linespeed: one evaluation with the antenna at the origin
                    C[p, Y] = ""
                    C[p, Z] = ""
                    C[p, AQ], C[p, AS], C[p, AU], C[p, AW] = A_EB, A_SB, A_SafeMax, A_ExpectedMax
                    break
        else:
            C[p, T] = ""

    if q == 0:
        raise AbortCalculation("Initial speed is not a multiple of 0.1 km/h: no perturbation point "
                               "(VBA run-time error on Cells(0, ...))")

    # Outil: décalage des courbes pour l'inexactitude de position (supervision depuis
    # l'origine) — cf. Position_inacc (§3.13.1.4) ; W suit min(shift, écart SBI2-SBI1)
    # de sorte que le Warning ne dépasse pas l'EBI (cf. §3.13.9.3.4.1).
    # =========== shift the curves for position inaccuracy (virtual run from the origin)
    if GUI:
        if EOA:
            args = (C[q, U], C[q, V], Ref(C[q, AE]), C[q, AF])
        else:
            args = (0, C[q, V], 0, C[q, AH])
    else:
        args = (C[q, U], C[q, V], 0, 0) if EOA else (0, C[q, V], 0, 0)
    perturbation = e.Shifted_startcurve(*args, V_linespeed, perturbation)
    startind = e.Shifted_startcurve(*args, V_linespeed, C[q, Z])
    startbtg = e.Shifted_startcurve(*args, V_linespeed, C[q, Y])

    shift_P = startbtg - C.n(q, Y)
    shift_I = startind - C.n(q, Z)
    if not e.Downstream_antenna_position_vs_origin(startbtg, coeffSM):
        _abort()
    shift_EBI_SBI2 = e.Position_inacc(startbtg, coeffSM)
    if not e.Downstream_antenna_position_vs_origin(startind, coeffSM):
        _abort()
    shift_EBI_SBI2_I = e.Position_inacc(startind, coeffSM)
    st["shift_SBI_W"] = wmin(shift_EBI_SBI2, C.n(q, V) + shift_EBI_SBI2 - C.n(q, U))

    V_release = st["V_release"]
    startrsm = 0.0
    if not (perturbation < d_target and startind < d_target):
        _abort()

    p = vint((V_linespeed + dV_ebi_ls) * 10) + 2
    while p != vint(V_target * 10) + 1:
        if p > q:
            if not is_blank(C[p, T]):
                C[p, T] = C.n(p, T) + shift_EBI_SBI2
            if GUI:
                if EOA:
                    C[p, AF] = C.n(p, AF) + shift_EBI_SBI2
                else:
                    C[p, AH] = C.n(p, AH) + shift_EBI_SBI2
            if not is_blank(C[p, V]):
                C[p, V] = C.n(p, V) + shift_EBI_SBI2
                if gt(C[p, V], C[p, U]):
                    if not is_blank(C[p, W]):
                        C[p, W] = C[p, V]
                    if not is_blank(C[p, X]):
                        C[p, X] = C.n(p, X) + st["shift_SBI_W"]
        else:
            if p < q:
                if not e.Downstream_antenna_position_vs_origin(C.n(p + 1, Y), coeffSM):
                    _abort()
                shift_EBI_SBI2 = e.Position_inacc(C.n(p + 1, Y), coeffSM)
                if not e.Downstream_antenna_position_vs_origin(C.n(p + 1, Z), coeffSM):
                    _abort()
                shift_EBI_SBI2_I = e.Position_inacc(C.n(p + 1, Z), coeffSM)
            C[p, T] = C.n(p, T) + shift_EBI_SBI2
            C[p, V] = C.n(p, V) + shift_EBI_SBI2
            if gt(C[p, V], C[p, U]):
                C[p, W] = C[p, V]
                st["shift_SBI_W"] = wmin(shift_EBI_SBI2, C.n(p, V) - C.n(p, U))
                C[p, X] = C.n(p, X) + st["shift_SBI_W"]
            if EOA:
                if GUI:
                    C[p, AF] = C.n(p, AF) + shift_EBI_SBI2
                    nd = C.n(p, N) * T_driver * 1000 / 3600
                    a = wmax(C.n(p, V) + nd, Ref(C[p, AF]))
                    b = wmax(C.n(p, U) + nd, Ref(C[p, AE]))
                    if a > b:
                        shift_P = wmin(shift_EBI_SBI2, a - b)
                        shift_I = wmin(shift_EBI_SBI2_I, a - b)
                    else:
                        shift_P = shift_I = 0.0
                else:
                    if gt(C[p, V], C[p, U]):
                        shift_P = st["shift_SBI_W"]
                        shift_I = wmin(shift_EBI_SBI2_I, C.n(p, V) - C.n(p, U))
                    else:
                        shift_P = shift_I = 0.0
            else:
                if GUI:
                    C[p, AH] = C.n(p, AH) + shift_EBI_SBI2
                shift_P = shift_EBI_SBI2
                shift_I = shift_EBI_SBI2_I
            C[p, Y] = C.n(p, Y) + shift_P
            C[p, Z] = C.n(p, Z) + shift_I
            # compensate the graphical horizontal distortion when relocation takes place
            if C[p + 1, Y] is not None and gt(C[p, Y], C[p + 1, Y]):
                for col in (T, V, W, X, Y, Z, AF, AH):
                    C[p + 1, col] = C[p, col]
        p -= 1

    # Limites de plafond: lignes pseudo-horizontales à (V_linespeed + dV_ebi/sbi/
    # warning) et V_linespeed jusqu'à l'origine — SUBSET-026 §3.13.9.2.1-§3.13.9.2.2.
    # clipping to the ceiling speed values (pseudo horizontal line until origin)
    C[vint((V_linespeed + dV_ebi_ls) * 10) + 2, T] = d_target
    C[vint((V_linespeed + dV_sbi_ls) * 10) + 2, W] = d_target
    C[vint((V_linespeed + dV_warning_ls) * 10) + 2, X] = d_target
    C[vint(V_linespeed * 10) + 2, Y] = d_target

    # release speed and start of release speed monitoring
    if EOA:
        # Release speed fixe (trackside) — SUBSET-026 §3.13.9.4.4-§3.13.9.4.5 ; début de
        # la surveillance (startrsm) = SBI à V_release (§3.13.9.4.6).
        if tr.release_speed == "fixed":
            V_release = min(tr.fixed_release_speed, tr.V_initial)
            if V_release != 0:
                startrsm = num(C.vlookup(V_release, N, 2, 5000, 10))
                C[2, AC] = startind
                C[2, AD] = V_release
                C[3, AC] = -(coefflevel * D20 + e.Position_inacc(0, coeffSM))
                C[3, AD] = V_release
        else:
            w = 2
            # Release speed calculée embarquée — SUBSET-026 §3.13.9.4.8-§3.13.9.4.8.2 :
            # recherche itérative (implémentation libre: §3.13.9.4.8.2.2) de V_release
            # satisfaisant |V_release − (V_EBD(d_tripEOA+α·D41+D_bec) − V_ura)| ≤ 1 km/h et
            # d_tripEOA + α·D41 + D_bec ≤ d_EBD(V_target) ; startrsm = SBI le plus restrictif
            # cf. §3.13.9.4.6 ; MRSP dans l'area: §3.13.9.4.9.
            while not is_blank(C[w, AA]):
                C[w, AB] = C[w, N]
                w += 1
            Train_position = startind
            if not e.Downstream_antenna_position_vs_origin(Train_position, coeffSM):
                _abort()
            w = 2
            found = st["release_speed_found"]
            while not (Train_position <= -(coefflevel * D20 + e.Position_inacc(Train_position, coeffSM) + 0.1)):
                dtrip = e.d_tripEOA(Train_position, coefflevel, coeffSM)
                if dtrip < abs(C.n(2, AA)):
                    C[w, AP] = min(V_linespeed, num(C.vlookup(-dtrip, AA, 2, 5000, 2)))
                    if not found:
                        if Train_position >= 0:
                            if num(C.vlookup(Train_position, W, 2, 5000, 6)) <= C.n(w, AP):
                                found = True
                                V_release = C.n(w, AP)
                                sbi_at = num(C.vlookup(V_release, N, 2, 5000, 10))
                                startrsm = Train_position if Train_position < sbi_at - 5 else sbi_at
                        else:
                            found = True
                            V_release = 0.0
                else:
                    C[w, AP] = 0
                C[w, AO] = Train_position
                Train_position = Train_position - 1 if Train_position > 10 else Train_position - 0.1
                w += 1
            for pp in range(2, w):
                C[pp, AC] = C[w + 1 - pp, AO]
                C[pp, AD] = C[w + 1 - pp, AP]
                C[w + 1 - pp, AO] = None
                C[w + 1 - pp, AP] = None

    # Au-delà de startrsm, l'EBI relatif à l'EBD est remplacé par une limite verticale
    # à V_release ; W/P/I clippés à la verticale — SUBSET-026 §3.13.9.4.6 (start
    # location of the release speed monitoring).
    if EOA and V_release != 0:
        def first_not_below(col):
            pp = 2
            while not (C.n(pp, N) >= num(C.vlookup(C[pp, col], AC, 2, 10000, 2))):
                C[pp, col] = None
                pp += 1
            return pp
        first_not_below(W)
        first_not_below(X)
        first_not_below(Y)
        pp = 2      # vertical part of the I curve
        while not (C.n(pp, N) >= num(C.vlookup(C[pp, Z], AC, 2, 10000, 2))):
            C[pp, Z] = startrsm
            pp += 1
        top_ebi = vint((V_linespeed + dV_ebi_ls) * 10) + 2
        pp = 2
        while not (C.n(pp, T) >= startrsm or pp == top_ebi):
            C[pp, T] = None
            pp += 1
        ww = pp      # vertical part of the EBI curve
        if C.n(pp, N) >= V_release:
            while ww != vint(V_release * 10) + 1:
                C[ww, T] = startrsm
                ww -= 1
        else:
            while ww != 2:
                C[ww, T] = startrsm
                ww -= 1
        top_sbi = vint((V_linespeed + dV_sbi_ls) * 10) + 2
        for col in (U, V):
            pp = 2
            while not (C.n(pp, col) >= startrsm or pp == top_sbi + 1):
                if pp == top_sbi:
                    C[pp, col] = startrsm
                else:
                    C[pp, col] = None
                pp += 1

    # Clip des limites au voisinage de la cible LOA/MRSP — SUBSET-026 §3.13.9.2.7 :
    # mêmes formules que les plafonds en substituant V_MRSP par V_target(LOA).
    if LOA:    # clipping in the vicinity of the LOA/MRSP target
        base = vint(V_target * 10) + 2
        for col, dv in ((T, dV_ebi_target), (X, dV_warning_target)):
            pp = base
            while pp != vint((V_target + dv) * 10) + 2:
                C[pp, col] = None
                pp += 1
            C[pp, col] = C[base, R]
        pp = base
        while pp != vint((V_target + dV_sbi_target) * 10) + 2:
            C[pp, V] = None
            C[pp, W] = None
            pp += 1
        C[pp, V] = C[base, R]
        C[pp, W] = C[base, R]
        C[base, Z] = C[base, Y]
        C[base, Y] = C[base, R]

    # Récapitulatif aux points caractéristiques (V_linespeed) et release speed —
    # colonnes EBI/SBI/W du classeur (recherche par VLookup).
    summary = {
        "V_linespeed": V_linespeed,
        "perturbation": perturbation,
        "indication": startind,
        "permitted": startbtg,
        "warning": C.vlookup(V_linespeed, N, 2, 10000, 11),
        "sbi": C.vlookup(V_linespeed, N, 2, 10000, 10),
        "ebi": C.vlookup(V_linespeed, N, 2, 10000, 7),
        "start_rsm": (startrsm if V_release != 0 else "N/A") if EOA else "N/A",
        "release_speed": V_release if EOA else "N/A",
    }
    return summary


# ==========================================================================
