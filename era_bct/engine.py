from __future__ import annotations

import csv
from dataclasses import dataclass, field

from .accel import AccelMixin
from .curves import calculate_curves
from .geometry import GeometryMixin
from .lambda_model import LambdaParameters
from .model import Scenario
from .tables import build_gamma_table, build_lambda_table, gamma_max_speed, M_NVEBCL, new_calc_sheet
from .track import build_track, AbortCalculation
from .vba import Grid


# SECTION 9/13 — ORCHESTRATION ('Calculate the curves') ET RÉSULTATS.
# ==========================================================================

"""Orchestration: equivalent of the 'Calculate the curves' buttons
(Sheet17 for lambda trains, Sheet16 for gamma trains)."""

import csv
from dataclasses import dataclass, field


# Curves sheet layout (row 1 headers of 'Curves Lambda train' / 'Curves Gamma train')
CURVE_COLUMNS = {
    14: "speed_kmh", 15: "A_safe", 16: "A_expected", 17: "A_normal_service", 18: "EBD", 19: "SBD",
    20: "EBI", 21: "SBI1", 22: "SBI2", 23: "SBI", 24: "Warning", 25: "Permitted", 26: "Indication",
    27: "EBI_release_speed", 28: "speed_EBI_rs", 29: "RS_position", 30: "release_speed", 31: "GUI_EOA",
    32: "GUI_SvL", 33: "speed_GUI_EOA", 34: "GUI_LOA_MRSP", 35: "speed_GUI_LOA", 36: "speed_SBD",
    37: "t_be_reduced", 38: "t_bs_reduced", 43: "A_EB", 44: "A_EB_after", 45: "A_SB", 46: "A_SB_after",
    47: "A_safemax", 48: "A_safemax_after", 49: "A_expectedmax", 50: "A_expectedmax_after",
    51: "iteration", 52: "GUI_foot_changed",
}


# Moteur de calcul: méthodes géométriques (V_ura, inexactitude de position),
# décélérations (A_safe/A_expected/A_normal_service) et grille CR1344
# (A_EB/A_SafeMax/A_SB/A_ExpectedMax) ; feuilles Track/Calc/Curves internes.
class Engine(GeometryMixin, AccelMixin):
    def __init__(self, sc: Scenario):
        self.sc = sc
        self.gamma = sc.train.train_type == "gamma"
        self.warnings: list[str] = []
        self.lp = None
        self.decel = None
        self.calc = new_calc_sheet(self.gamma)
        self.track = Grid("Track")
        self.curves = Grid("Curves Gamma train" if self.gamma else "Curves Lambda train")
        self.gradient_extended_to = None
        self.d_finish_extended = None
        self._index_d_init = 0

    def warn(self, msg: str):
        self.warnings.append(msg)


@dataclass
class Result:
    scenario: Scenario
    engine: Engine
    summary: dict
    warnings: list = field(default_factory=list)
    aborted: str | None = None

    # --------------------------------------------------------------- access
    def column(self, name: str):
        col = {v: k for k, v in CURVE_COLUMNS.items()}[name]
        return self.engine.curves.cols.get(col, {})

    def curve(self, name: str, x_speed: str = "speed_kmh"):
        """Returns [(distance_from_target_m, speed_kmh)] for a supervision curve."""
        sp = self.column(x_speed)
        out = []
        for r, d in sorted(self.column(name).items()):
            if is_blank(d) or isinstance(d, bool):
                continue
            v = sp.get(r)
            if v is None:
                continue
            out.append((float(d), float(v)))
        return out

    def rows(self):
        cols = sorted(CURVE_COLUMNS)
        rows_idx = sorted({r for c in cols for r in self.engine.curves.cols.get(c, {})})
        header = [CURVE_COLUMNS[c] for c in cols]
        data = []
        for r in rows_idx:
            data.append([self.engine.curves[r, c] for c in cols])
        return header, data

    def to_csv(self, path):
        header, data = self.rows()
        with open(path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["row"] + header)
            rows_idx = sorted({r for c in CURVE_COLUMNS for r in self.engine.curves.cols.get(c, {})})
            for r, d in zip(rows_idx, data):
                w.writerow([r] + ["" if v is None else v for v in d])

    def to_dataframe(self):
        import pandas as pd
        header, data = self.rows()
        return pd.DataFrame(data, columns=header)

    def draw(self, ax, curves=None):
        """Draws the supervision limits on a matplotlib Axes (distance from the origin, as in the Excel charts)."""
        sc = self.scenario
        names = ["EBD", "EBI", "SBI", "Warning", "Permitted", "Indication"]
        if sc.track.target == "EOA_SvL":
            names.insert(1, "SBD")
        if curves is not None:
            names = [n for n in names if n in curves]
        for n in names:
            pts = self.curve(n)
            if pts:
                ax.plot([sc.track.d_target - d for d, _ in pts], [v for _, v in pts], label=n, lw=1.2)
        gui = self.curve("GUI_LOA_MRSP", "speed_GUI_LOA") if sc.track.target == "LOA_MRSP" else \
            self.curve("GUI_EOA", "speed_GUI_EOA")
        if gui and sc.national.Q_NVGUIPERM and (curves is None or "GUI" in curves):
            ax.plot([sc.track.d_target - d for d, _ in gui], [v for _, v in gui], "--", label="GUI", lw=1)
        if sc.track.target == "EOA_SvL" and (curves is None or "Release speed" in curves):
            rs = self.curve("RS_position", "release_speed")
            if rs and any(v for _, v in rs):
                ax.plot([sc.track.d_target - d for d, _ in rs], [v for _, v in rs], ":",
                        label="Release speed", lw=1)
        ax.axvline(sc.track.d_target, color="k", lw=0.8)
        ax.set_xlabel("Distance from origin (m)")
        ax.set_ylabel("Speed (km/h)")
        ax.set_title(f"ERA braking curves – {sc.train.train_type} train, "
                     f"{sc.track.target.replace('_', '/')} target at {sc.track.d_target:g} m")
        ax.grid(alpha=0.3)
        ax.legend(fontsize=8)

    def plot(self, path=None, show=False):
        """Speed/distance plot saved to ``path`` (png, svg, pdf) and/or shown."""
        if show:
            import matplotlib.pyplot as plt
            fig, ax = plt.subplots(figsize=(11, 6))
        else:
            from matplotlib.figure import Figure
            fig = Figure(figsize=(11, 6))
            ax = fig.add_subplot()
        self.draw(ax)
        fig.tight_layout()
        if path:
            fig.savefig(path, dpi=130)
        if show:
            plt.show()
        return fig


# Exécution complète : tables de décélération (§3.13.2.2.3.1), feuille Track
# (§3.13.4-§3.13.5), courbes et limites de supervision (§3.13.8-§3.13.9).
# Vitesse initiale bornée par la vitesse max du train (§3.13.2.2.13) ou la vitesse
# max du conversion model (§3.13.3.3.1).
def run(sc: Scenario, *, normalise: bool = True, raise_on_abort: bool = False) -> Result:
    """Runs the full calculation (track values, deceleration tables, curves)."""
    sc = sc.copy()
    notes = sc.normalise() if normalise else []
    e = Engine(sc)
    e.warnings.extend(notes)
    summary: dict = {}
    aborted = None
    try:
        # NB: the VBA refreshes the Track sheet *before* the deceleration sheet, so the
        # LOA/MRSP gradient-extension check reads the deceleration values left by the
        # previous run.  Here the tables are built first (same values when the inputs
        # did not change between two runs).
        if e.gamma:
            e.decel = build_gamma_table(sc, e.calc)
            e.M_NVEBCL = M_NVEBCL(sc.gamma_brake.ebcl)
            vmax = gamma_max_speed(sc.gamma_brake)
            clip_msg = "Intial speed clipped to maximum train speed"
        else:
            e.lp = LambdaParameters(sc)
            e.decel = build_lambda_table(e.lp, sc, e.calc)
            vmax = e.lp.max_speed
            clip_msg = "Initial speed clipped to Conversion Model max speed (200 km/h)"
        build_track(e)
        v0 = sc.track.V_initial
        if v0 > vmax:
            e.warn(clip_msg)
            v0 = vmax
        summary = calculate_curves(e, e.gamma, v0)
    except AbortCalculation as exc:
        aborted = str(exc)
        if raise_on_abort:
            raise
    return Result(scenario=sc, engine=e, summary=summary, warnings=e.warnings, aborted=aborted)


# ==========================================================================
