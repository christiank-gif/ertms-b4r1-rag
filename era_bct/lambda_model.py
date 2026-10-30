from __future__ import annotations

from .vba import Table


# SECTION 3/13 — MODÈLE DE FREIN λ (conversion model) — SUBSET-026 §3.13.3 + Annexe A §A.3.7-§A.3.9.
# ==========================================================================

"""Lambda train brake model: VBA Module2 + formulas of the sheets
'Brake parameters (lambda)' and 'Integrated correction factors'."""



# ----------------------------------------------------------------- Module2
# Vitesse limite du modèle de conversion UIC — SUBSET-026 §3.13.3.3.2 (calcul de la
# décélération de base) et Annexe A §A.3.7.
def V_lim(lam: float) -> float:
    return 16.85 * lam ** 0.428


_A = {1: (0.0663, 0.00472, 0.000061, -0.00000063),
      2: (0.13, 0.00514, -0.00000454, 0.000000273),
      3: (0.0479, 0.00581, -0.00000676, 0.0000000558),
      4: (0.048, 0.00552, -0.00000385, 0.00000003),
      5: (0.0559, 0.00506, 0.00000166, 0.00000000323)}


# A_basic(V), décélération de base du brake percentage conversion model —
# SUBSET-026 §3.13.3.3.2 (step function) + Annexe A §A.3.7.4-§A.3.7.6 (polynômes
# en λ par palier de vitesse).
def AD_UIC(lam: float, v: float) -> float:
    """UIC conversion model deceleration (m/s2)."""
    if v > 16.85 * lam ** 0.428:
        if v > 100:
            if v > 120:
                if v > 150:
                    n = 5 if v > 180 else 4
                else:
                    n = 3
            else:
                n = 2
        else:
            n = 1
        a0, a1, a2, a3 = _A[n]
        return a3 * lam ** 3 + a2 * lam ** 2 + a1 * lam + a0
    return 0.0075 * lam + 0.076


# Temps équivalent de montée du frein d'urgence (conversion model) — SUBSET-026
# §3.13.3.4.2 + Annexe A §A.3.8.1-§A.3.8.4 (formules en fonction de la longueur,
# par position de frein).
def t_bbu(L: float, brake_position: str) -> float:
    """Equivalent emergency brake build-up time (VBA function returns 0 when no branch applies)."""
    if brake_position == "Passenger in P":
        L = max(L, 400)
        return 2.3 + 0.17 * (L / 100) ** 2
    if brake_position == "Freight in P":
        L = max(L, 400)
        if L <= 900:
            return 2.3 + 0.17 * (L / 100) ** 2
        if L <= 1500:
            return -0.4 + 1.6 * L / 100 + 0.03 * (L / 100) ** 2
        return 0.0
    if brake_position == "Freight in G":
        if L <= 900:
            return 12 + 0.05 * (L / 100) ** 2
        if L <= 1500:
            return -0.4 + 1.6 * L / 100 + 0.03 * (L / 100) ** 2
    return 0.0


# Temps équivalent de montée du frein de service — SUBSET-026 §3.13.3.4.3 +
# Annexe A §A.3.9.1-§A.3.9.4.
def t_bbuSB(L: float, brake_position: str) -> float:
    """Equivalent service brake build-up time."""
    if brake_position == "Freight in P":
        if L <= 900:
            return 3 + 2.77 * L / 100
        if L <= 1500:
            return 10.5 + 0.32 * L / 100 + 0.18 * (L / 100) ** 2
        return 0.0
    if brake_position == "Freight in G":
        L = max(L, 400)
        if L <= 900:
            return 3 + 2.77 * L / 100
        if L <= 1500:
            return 10.5 + 0.32 * L / 100 + 0.18 * (L / 100) ** 2
        return 0.0
    if brake_position == "Passenger in P":
        return 3 + 1.5 * L / 100 + 0.1 * (L / 100) ** 2
    return 0.0


# Temps de réaction du frein d'urgence — Annexe A §A.3.8.6 (T_beu_react par
# position de frein).
def t_bbuEB_react(brake_position: str) -> float:
    return {"Passenger in P": 1.42, "Freight in P": 2.99, "Freight in G": 9.3}.get(brake_position, 0.0)


# Temps de réaction du frein de service — Annexe A §A.3.9.8.
def t_bbuSB_react(brake_position: str) -> float:
    return {"Passenger in P": 1.06, "Freight in P": 2.07, "Freight in G": 5.7}.get(brake_position, 0.0)


def _next_step(x):
    # =IF(I17<100,100,IF(I17<120,120,IF(I17<150,150,IF(I17<180,180,I17))))
    return 100 if x < 100 else 120 if x < 120 else 150 if x < 150 else 180 if x < 180 else x


# Construction en step function (paliers V, V+0,001) — SUBSET-026
# §3.13.2.2.3.1.1-§3.13.2.2.3.1.2.
def uic_table(lam: float, vmax: float):
    """Rows I16:J27 (or M16:N27) of 'Brake parameters (lambda)'."""
    i17 = V_lim(lam)
    i19 = _next_step(i17)
    i21 = _next_step(i19)
    i23 = _next_step(i21)
    i25 = _next_step(i23)
    j17, j19, j21, j23, j25, j27 = (AD_UIC(lam, v) for v in (i17, i19, i21, i23, i25, vmax))
    keys = [0, i17, i17 + 0.001, i19, i19 + 0.001, i21, i21 + 0.001, i23, i23 + 0.001, i25, i25 + 0.001, vmax]
    vals = [j17, j17, j19, j19, j21, j21, j23, j23, j25, j25, j27, j27]
    return list(zip(keys, vals))


# Évaluation des formules des feuilles 'Brake parameters (lambda)' et
# 'Integrated correction factors' — SUBSET-026 §3.13.3 (conversion models),
# §3.13.6.2.2.3 (T_be/T_be_react), §3.13.6.3.2.4 (T_bs/T_bs_react).
class LambdaParameters:
    """Evaluates the sheet formulas for a given scenario."""

    def __init__(self, sc):
        t, lb, tr = sc.train, sc.lambda_brake, sc.track
        pos = t.brake_position
        L = t.overall_length
        self.lambda1 = lb.lambda_pct                                   # F3
        self.lambda2 = 135 if self.lambda1 > 135 else self.lambda1     # F4
        self.V_lim_eb = V_lim(self.lambda1)                            # F5
        self.V_lim_sb = V_lim(self.lambda2)                            # F6
        # Facteur kto — Annexe A §A.3.8.5 / §A.3.9.5 : 1,2 en position P, 1,16 en
        # position G.
        kto = 1.2 if pos in ("Freight in P", "Passenger in P") else 1.16  # F7
        self.kto = kto
        self.T_be_cm0 = t_bbu(L, pos)                                  # F8
        self.T_be_cmt = kto * t_bbu(L, pos)                            # F9
        self.T_bs_cm0 = t_bbuSB(L, pos)                                # F10
        self.T_bs_cmt = kto * t_bbuSB(L, pos)                          # F11
        # T_be (§3.13.6.2.2.3): sans cible de vitesse → t_bbuEB brut; sinon
        # kto × t_bbuEB (Annexe A §A.3.8.5). NOTE outil v5.1: T_be utilisé pour l'EBI est
        # ensuite multiplié par Kt_int (F12 × D47) — cf. calculate_curves; à confirmer par
        # --compare sur le classeur réel.
        self.T_brake_emergency = self.T_be_cm0 if tr.V_target == 0 else self.T_be_cmt      # F12
        self.D13 = 1 if lb.conversion_model else 0
        cm_bs = self.T_bs_cm0 if tr.V_target == 0 else self.T_bs_cmt
        self.T_brake_service = cm_bs if self.D13 == 1 else lb.T_brake_service_user          # F13
        self.T_brake_service_user = lb.T_brake_service_user                                  # F14
        self.T_brake_emergency_react = t_bbuEB_react(pos)                                    # F15
        self.T_brake_service_react = (t_bbuSB_react(pos) if self.D13 == 1
                                      else lb.T_brake_service_react_user)                    # F16
        self.T_brake_service_react_user = lb.T_brake_service_react_user                      # F17
        vmax = lb.conversion_model_max_speed
        self.max_speed = vmax                                                                # I27
        self.eb_rows = uic_table(self.lambda1, vmax)                                         # I16:J27
        self.sb_rows = uic_table(self.lambda2, vmax)                                         # M16:N27
        self.A_brake_emergency = Table(self.eb_rows)
        self.A_brake_service = Table(self.sb_rows)
        n16 = self.sb_rows[0][1]
        tables = lb.normal_service_G if pos == "Freight in G" else lb.normal_service_P
        # Sélection du jeu A_brake_normal_service par les pivots A_SB01/A_SB12 — SUBSET-026
        # §3.13.2.2.3.1.10-§3.13.2.2.3.1.11.
        idx = 0 if n16 <= lb.A_SB01 else (1 if n16 <= lb.A_SB12 else 2)
        self.normal_service_table_index = idx
        self.ns_rows = [[0, tables[idx][0][1]]] + [list(r) for r in tables[idx][1:]]          # Q14:R27
        self.A_brake_normal_service = Table(self.ns_rows)
        # Integrated correction factors
        # A_ebmax = MAX de la table A_brake_emergency — SUBSET-026 §3.13.6.2.1.8.2.
        self.A_ebmax = max(v for _, v in self.eb_rows)                 # MAX(J16:J27)
        sp = lb.kv_passenger_speeds
        # Kv_int voyageurs: interpolation linéaire entre les subsets a et b quand
        # A_NVP12 < A_ebmax < A_NVP23 — SUBSET-026 §3.13.2.3.7.11.4-§3.13.2.3.7.11.6.
        if lb.A_NVP12 < self.A_ebmax < lb.A_NVP23:                     # E18:E27
            f = (self.A_ebmax - lb.A_NVP12) / (lb.A_NVP23 - lb.A_NVP12)
            kv_mid = [a + f * (b - a) for a, b in zip(lb.kv_passenger_a, lb.kv_passenger_b)]
        else:
            kv_mid = [""] * len(sp)
        self.kv_passenger_mid = kv_mid
        # Choix du jeu Kv_int: fret (§3.13.2.3.7.10) ou voyageurs (subsets a/b selon
        # A_ebmax vs A_NVP12/A_NVP23 — §3.13.2.3.7.11.5-§3.13.2.3.7.11.6).
        if pos in ("Freight in P", "Freight in G"):
            rows, self.kv_set = lb.kv_freight, "freight"
        elif self.A_ebmax <= lb.A_NVP12:
            rows, self.kv_set = list(zip(sp, lb.kv_passenger_a)), "passenger_a"
        elif self.A_ebmax >= lb.A_NVP23:
            rows, self.kv_set = list(zip(sp, lb.kv_passenger_b)), "passenger_b"
        else:
            rows, self.kv_set = list(zip(sp, kv_mid)), "passenger_interpolated"
        self.Kv_int = Table(rows)
        self.Kr_int = Table(lb.kr)
        self.Kt_int = lb.Kt_int
        self.Kn_plus = Table(lb.kn_plus)
        self.Kn_minus = Table(lb.kn_minus)

    def summary(self) -> dict:
        return {k: v for k, v in vars(self).items() if isinstance(v, (int, float, str))}


# ==========================================================================
