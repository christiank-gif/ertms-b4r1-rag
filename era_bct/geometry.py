from __future__ import annotations

from .vba import Ref, is_blank, num, wmax, wmin


# SECTION 5/13 — GÉOMÉTRIE (V_ura, marges de plafond, inexactitude de position) — SUBSET-026 §3.13.9.2, §3.13.9.4.8.2.
# ==========================================================================

"""Port of VBA Module1: speed/position inaccuracies, ceiling speed margins,
shifting of the start of the P curve, trip location related to the EOA."""



# V_ura (speed under reading amount) selon les performances SUBSET-041 —
# utilisée pour V_delta0 au sens du SUBSET-026 §3.13.9.3.2.1 (compensation
# d'inexactitude de vitesse, inhibable par Q_NVINHSMICPERM).
def S41_speed_inacc(speed: float) -> float:
    """Speed measurement inaccuracy of SUBSET-041 (km/h)."""
    if speed <= 30:
        return 2.0
    if speed >= 500:
        return 12.0
    return 2 + (10 * (speed - 30)) / 470


# Marge de plafond: dV = min(dV_min + C·(V−V_min), dV_max) avec
# C = (dV_max−dV_min)/(V_max−V_min) — SUBSET-026 §3.13.9.2.3 (dV_ebi),
# §3.13.9.2.5 (dV_sbi), §3.13.9.2.6 (dV_warning) ; pour une LOA: §3.13.9.2.7.
def ceiling_speed_margin(ceiling_speed, V_min, V_max, dV_min, dV_max) -> float:
    if ceiling_speed > V_min:
        C = (dV_max - dV_min) / (V_max - V_min)
        return min(dV_min + C * (ceiling_speed - V_min), dV_max)
    return dV_min


class GeometryMixin:
    """Methods that need the 'Train (main)' and 'Track' data (self.sc, self.track)."""

    # Position de l'antenne et sur/sous-longueurs de consist (L_trainover/
    # L_trainunder) — SUBSET-026 §3.13.9.4.8.2 (β: manœuvre supervisée).
    def _antenna_and_lengths(self, distance, coeffSM):
        t, d_target = self.sc.train, self.sc.track.d_target
        if t.engine_orientation_same:
            antenna = d_target - distance - coeffSM * t.consist_front_nom - t.antenna_to_front
            over = t.consist_front_nom - t.consist_front_min
            under = t.consist_front_max - t.consist_front_nom
        else:
            antenna = d_target - distance - coeffSM * t.consist_rear_nom + t.antenna_to_front
            over = t.consist_rear_nom - t.consist_rear_min
            under = t.consist_rear_max - t.consist_rear_nom
        return antenna, over, under

    # Dernière balise de relocalisation en amont et sa précision de localisation
    # (Q_locacc-refBG) — SUBSET-026 §3.13.9.4.8.2, §3.13.9.4.9.1.
    def _balise(self, antenna_position):
        b = self.track.vlookup(antenna_position, 6, 2, 31, 1)
        acc = self.track.vlookup(antenna_position, 6, 2, 31, 2)
        return num(b), num(acc)

    # Intervalle de confiance de position: Q_locacc + erreur odomètre absolue +
    # erreur relative depuis la balise + sous-longueur de consist — cf. §3.13.1.4
    # (distances depuis la localisation de référence) et §3.13.9.4.9.1.
    def Position_inacc(self, distance, coeffSM) -> float:
        t = self.sc.train
        antenna, _, under = self._antenna_and_lengths(distance, coeffSM)
        balise, locacc = self._balise(antenna)
        return t.odometer_abs + locacc + ((antenna - balise) * t.odometer_rel_pct / 100) + coeffSM * under

    # d_tripEOA = d_EOA + α·L_antenna-front + max{ 2·Q_locacc + 10 m + 10%·d_EOA +
    # β·(L_over+L_under) ; 2 × intervalle de confiance de position } — SUBSET-026
    # §3.13.9.4.8.2 (α = coefflevel: niveau 1).
    def d_tripEOA(self, distance, coefflevel, coeffSM) -> float:
        t = self.sc.train
        antenna, over, under = self._antenna_and_lengths(distance, coeffSM)
        balise, locacc = self._balise(antenna)
        return coefflevel * t.antenna_to_front + max(
            2 * locacc + 10 + 0.1 * (self.sc.track.d_target - balise) + coeffSM * (over + under),
            2 * self.Position_inacc(distance, coeffSM))

    # Outil: l'antenne doit rester en aval de l'origine (sinon calcul abandonné).
    def Downstream_antenna_position_vs_origin(self, distance, coeffSM) -> bool:
        antenna, _, _ = self._antenna_and_lengths(distance, coeffSM)
        return antenna >= 0

    # Outil: décalage du pied de la courbe P pour compenser l'inexactitude de position
    # lors de la supervision depuis l'origine — cf. §3.13.1.4 ; la SBI2/W suivent le
    # même décalage (min borné par l'écart EBI-SBI, cf. §3.13.9.3.3.2).
    def Shifted_startcurve(self, SBI1, SBI2, GUI1, GUI2, Vest, startcurve) -> float:
        """Arguments are cell values; GUI1 may be a Ref (cell) or a literal 0."""
        t, tr = self.sc.train, self.sc.track
        coeffSM = 1 if t.supervised_manoeuvre else 0
        if t.engine_orientation_same:
            d_iter = tr.d_target - coeffSM * t.consist_front_nom - t.antenna_to_front - 1
        else:
            d_iter = tr.d_target - coeffSM * t.consist_rear_nom + t.antenna_to_front - 1
        start = num(startcurve)
        shifted = start
        T_driver = self.sc.fixed.T_driver
        sbi1, sbi2, gui2 = num(SBI1), num(SBI2), num(GUI2)
        while not (shifted >= d_iter):
            s = self.Position_inacc(d_iter, coeffSM)
            if tr.target == "EOA_SvL":
                if self.sc.national.Q_NVGUIPERM:
                    a = wmax(sbi2 + s + Vest * T_driver * 1000 / 3600, gui2 + s)
                    b = wmax(sbi1 + Vest * T_driver * 1000 / 3600, GUI1)
                    shift = wmin(s, a - b) if a > b else 0.0
                else:
                    shift = wmin(s, sbi2 + s - sbi1) if sbi2 + s > sbi1 else 0.0
            else:
                shift = s
            shifted = start + shift
            d_iter = d_iter - 1
        return shifted


__all__ = ["S41_speed_inacc", "ceiling_speed_margin", "GeometryMixin", "Ref"]


# ==========================================================================
