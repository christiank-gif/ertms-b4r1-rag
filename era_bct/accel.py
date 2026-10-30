from __future__ import annotations

from .vba import clng, gt, is_blank, num


# SECTION 6/13 — DÉCÉLÉRATIONS A_safe/A_expected/A_normal_service + GRILLE CR1344 — SUBSET-026 §3.13.6 + Annexe A §A.3.12.
# ==========================================================================

"""Port of VBA Module3: A_safe, A_expected, A_normal_service and the CR1344
"grid" functions A_EB, A_SafeMax, A_SB, A_ExpectedMax.

In all functions d is counted from the origin (not from the target), as in the VBA.
"""



def _ge(a, b) -> bool:
    """VBA Variant ``a >= b`` (a text cell is greater than any number)."""
    return not gt(b, a)


class AccelMixin:
    # ---------------------------------------------------------------- basics
    # Lecture de la feuille Track (ligne CLng(d)+36): col.4 = A_gradient compensée,
    # col.5 = A_MAXREDADH (réduite), col.6 = comb. n°2 (freins spéciaux inhibés).
    def _trk(self, d, col):
        return self.track[clng(d + 36), col]

    # A_gradient(d) — SUBSET-026 §3.13.4 : accélération due au gradient, compensée sur
    # la longueur du train (§3.13.4.2) et pour les masses tournantes (§3.13.4.3).
    def A_gradientComp(self, d) -> float:
        return num(self._trk(d, 4))

    def _dec(self, v, col):
        return self.decel[clng(v * 10 + 2), col]

    def _inhib(self, d) -> bool:
        tr = self.sc.track
        return tr.brake_inhibition and d >= tr.brake_inhib_start

    # A_safe(V,d) — SUBSET-026 §3.13.6.2.1.3 :
    #   normal: A_brake_safe(V,d) + A_gradient(d) ;
    #   adhérence réduite limitante: min(A_brake_safe, A_MAXREDADH) + A_gradient.
    # A_brake_safe (§3.13.6.2.1.4) :
    #   γ (Train Data): Kdry_rst(V,EBCL) × (Kwet_rst(V) + M_NVAVADH×(1−Kwet_rst(V)))
    #               × A_brake_emergency(V,d)   (M_NVAVADH: §3.13.2.3.7.7)
    #   λ (conversion model): Kv_int(V) × Kr_int(L_TRAIN) × A_brake_emergency(V)
    # A_MAXREDADH: §3.13.6.2.1.6 (zone étendue de la longueur du train: §3.13.5.5).
    # Colonnes 6-8 = zone sans freins spéciaux (comb. n°2, §3.13.5.2).
    def A_safe(self, v, d, gamma=None) -> float:
        gamma = self.gamma if gamma is None else gamma
        v, d = num(v), num(d)
        if gamma:
            M = self.sc.national.M_NVAVADH
            if self._inhib(d):
                kdry, kwet, aeb = self._dec(v, 7), self._dec(v, 8), self._dec(v, 6)
            else:
                kdry, kwet, aeb = self._dec(v, 3), self._dec(v, 4), self._dec(v, 2)
            kdry, kwet, aeb = num(kdry), num(kwet), num(aeb)
            a_brake_safe = kdry * (kwet + M * (1 - kwet)) * aeb
        else:
            L = clng(self.sc.train.overall_length)          # Train_length As Integer
            kv, aeb = num(self._dec(v, 3)), num(self._dec(v, 2))
            a_brake_safe = kv * num(self.lp.Kr_int(L)) * aeb
        red = self._trk(d, 5)
        if is_blank(red):
            return a_brake_safe + self.A_gradientComp(d)
        return min(a_brake_safe, num(red)) + self.A_gradientComp(d)

    # A_expected(V,d) = A_brake_service(V,d) + A_gradient(d) — SUBSET-026
    # §3.13.6.3.1.3-§3.13.6.3.1.4 (pas de correction voie: §3.13.6.3.1.1).
    def A_expected(self, v, d, gamma=None) -> float:
        gamma = self.gamma if gamma is None else gamma
        v, d = num(v), num(d)
        if gamma:
            col = 12 if self._inhib(d) else 10
        else:
            col = 5
        return num(self._dec(v, col)) + self.A_gradientComp(d)

    # A_normal_service(V,d) = A_brake_normal_service(V,d) + A_gradient(d)
    #   − Kn+(V)·G/1000 si G>0 / − Kn−(V)·G/1000 si G<0 — SUBSET-026 §3.13.6.4.3-
    # §3.13.6.4.4 (Kn±: §3.13.2.2.9.2 ; λ_rot: §3.13.4.3.2).
    def A_normal_service(self, v, d, gamma=None) -> float:
        gamma = self.gamma if gamma is None else gamma
        v, d = num(v), num(d)
        if gamma:
            a = num(self._dec(v, 16 if self._inhib(d) else 14))
            kp, km = 18, 19
        else:
            a = num(self._dec(v, 7))
            kp, km = 9, 10
        grad = num(self._trk(d, 3))
        if grad > 0:
            return a + self.A_gradientComp(d) - num(self._dec(v, kp)) * grad / 1000
        if grad < 0:
            return a + self.A_gradientComp(d) - num(self._dec(v, km)) * grad / 1000
        return a + self.A_gradientComp(d)

    # ------------------------------------------------------------ CR1344 grid
    # Outil: premier pivot de vitesse ≥ x (balayage des régions de l'Annexe A
    # §A.3.12.2.2-§A.3.12.2.5 ; pivots: §3.13.8.1.3).
    def _first_index(self, col, x) -> int:
        """'find the first pivot value higher or equal than x'; returns the row before it (0 = none)."""
        calc = self.calc
        if is_blank(calc[2, col]):
            return 0
        m = 2
        while not _ge(calc[m, col], x):
            m += 1
            if is_blank(calc[m, col]):
                m = 1
                break
        return m - 1

    # Balayage des régions de vitesse, de celle de V_target (exclue) à celle de v —
    # Annexe A §A.3.12.2.2-§A.3.12.2.5.
    def _scan_speed(self, acc, vcol, v, d, fn, combine, subtract_grad):
        """Scans the speed regions from the one of V_target (exclusive) to the one of v (inclusive)."""
        calc = self.calc
        V_target = self.sc.track.V_target
        idx = self._first_index(vcol, V_target)
        if idx != 0:
            n = idx + 1
            while not _ge(calc[n, vcol], v):
                val = fn(num(calc[n, vcol]) + 1, d)
                if subtract_grad:
                    val -= self.A_gradientComp(d)
                acc = combine(acc, val)
                n += 1
                if is_blank(calc[n, vcol]):
                    break
        return acc

    # Corps générique de A_EB / A_safe_max / A_SB / A_expected_max: min ou max de
    # A_brake sur les régions vitesse × distance parcourues — SUBSET-026 Annexe A
    # §A.3.12.2.2 (A_EB = min), §A.3.12.2.3 (A_safe_max = max), §A.3.12.2.4 (A_SB =
    # min), §A.3.12.2.5 (A_expected_max = max).
    def _grid(self, v, d, fn, combine, subtract_grad, dcol, dcol_loop, vcol1, vcol2):
        """Generic body of A_EB_*, A_SafeMax_*, A_SB_*, A_ExpectedMax_* (Module3).

        dcol: distance pivot column searched for Index_d; dcol_loop: column tested in the
        Do Until condition of the distance loop (differs from dcol in A_ExpectedMax_lambda);
        vcol1/vcol2: speed pivot columns without/with brake inhibition (vcol2 None for lambda).
        """
        tr = self.sc.track
        V_target, d_target = tr.V_target, tr.d_target
        calc = self.calc
        acc = fn(V_target, d)
        if subtract_grad:
            acc -= self.A_gradientComp(d)
        index_d = self._index_d_init
        if not is_blank(calc[2, dcol]):
            m = 2
            while not _ge(calc[m, dcol], d):
                m += 1
                if is_blank(calc[m, dcol]):
                    m = 1
                    break
            index_d = m - 1
        dcol_loop = dcol if dcol_loop is None else dcol_loop
        if index_d == 0:
            return self._scan_speed(acc, vcol1, v, d, fn, combine, subtract_grad)
        d_temp = d
        p = index_d
        while not (d_temp > d_target or is_blank(calc[p, dcol_loop])):
            val = fn(V_target, d_temp)
            if subtract_grad:
                val -= self.A_gradientComp(d_temp)
            acc = combine(acc, val)
            vcol = vcol2 if (vcol2 is not None and self._inhib(d_temp)) else vcol1
            acc = self._scan_speed(acc, vcol, v, d_temp, fn, combine, subtract_grad)
            p += 1
            d_temp = num(calc[p, dcol]) + 1
        return acc

    # A_EB — SUBSET-026 Annexe A §A.3.12.2.2.
    def A_EB_grid(self, v, d):
        v, d = num(v), num(d)
        self._index_d_init = 0
        if self.gamma:
            return self._grid(v, d, self.A_safe, min, True, 3, None, 1, 2)
        return self._grid(v, d, self.A_safe, min, True, 2, None, 1, None)

    # A_safe_max — SUBSET-026 Annexe A §A.3.12.2.3.
    def A_SafeMax_grid(self, v, d):
        v, d = num(v), num(d)
        self._index_d_init = 0
        if self.gamma:
            return self._grid(v, d, self.A_safe, max, False, 3, None, 1, 2)
        return self._grid(v, d, self.A_safe, max, False, 2, None, 1, None)

    # A_SB — SUBSET-026 Annexe A §A.3.12.2.4.
    def A_SB_grid(self, v, d):
        v, d = num(v), num(d)
        self._index_d_init = 0
        if self.gamma:
            return self._grid(v, d, self.A_expected, min, True, 7, None, 5, 6)
        return self._grid(v, d, self.A_expected, min, True, 5, None, 4, None)

    # A_expected_max — SUBSET-026 Annexe A §A.3.12.2.5.
    def A_ExpectedMax_grid(self, v, d):
        v, d = num(v), num(d)
        if self.gamma:
            # VBA: Index_d is initialised to 1 (not 0) in A_ExpectedMax_gamma
            self._index_d_init = 1
            return self._grid(v, d, self.A_expected, max, False, 7, None, 5, 6)
        # VBA: A_ExpectedMax_lambda tests the EBD distance pivots (column 2) in the
        # Do Until condition while d_temp follows the SBD distance pivots (column 5)
        self._index_d_init = 0
        return self._grid(v, d, self.A_expected, max, False, 5, 2, 4, None)


# ==========================================================================
