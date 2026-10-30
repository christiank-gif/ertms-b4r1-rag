from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field, fields
from typing import Optional


# SECTION 2/13 — MODÈLE DE DONNÉES D'ENTRÉE (feuilles du classeur v5.1) — SUBSET-026 §3.13.2 (inputs for speed and distance monitoring).
# ==========================================================================

"""Input data model of the ERA Braking Curves Tool v5.1.

Every field maps to a cell, a named range or an ActiveX control of the
workbook; the mapping is given in the comments.  ``Scenario.normalise()``
applies the constraints that the worksheet event handlers enforce in Excel
(Sheet1, Sheet4, Sheet11 class modules).
"""

import copy
import json
from dataclasses import asdict, dataclass, field, fields
from typing import Optional

# Positions de frein admises — SUBSET-026 §3.13.2.2.4 (Brake Position: Passenger in P /
# Freight in P / Freight in G); pour γ, choix du jeu de modèles par §3.13.2.2.4.2.
BRAKE_POSITIONS = ("Passenger in P", "Freight in P", "Freight in G")


@dataclass
# Entrées train — SUBSET-026 §3.13.2.2 : T_traction_cut_off (§3.13.2.2.8,
# T_traction: §3.13.9.3.2.3), service_brake_interface (§3.13.2.2.7, rétroaction du
# frein de service: §3.13.6.3.2.5, Annexe A §A.3.10), traction_cut_off_interface
# (§3.13.2.2.8), special_brake_indep_adhesion (§3.13.2.2.6, frein indépendant de
# l'adhérence: §3.13.5.4), speed_inaccuracy / odomètre (V_ura et inexactitude de
# position: SUBSET-041; cf. §3.13.9.3.2.1 et §3.13.9.4.8.2), supervised_manoeuvre
# (β et L_trainover/under: §3.13.9.4.8.2), train_length / overall_length
# (§3.13.2.2.11; entrée de Kr_int: §3.13.2.3.7.12), rotating_mass_pct (§3.13.2.2.10,
# utilisé par la compensation masses tournantes §3.13.4.3), antenna_to_front
# (L_antenna-front: §3.13.9.4.8.2), A_est1 (§3.13.9.3.2.8).
class Train:                                   # sheet "Train (main)"
    train_type: str = "lambda"                 # option buttons Lambda / Gamma
    brake_position: str = "Freight in P"       # D23 (Passenger_P / Freight_P / Freight_G)
    T_traction_cut_off: float = 2.0            # D4
    service_brake_interface: bool = True       # Service_brake_interface_yes
    traction_cut_off_interface: bool = True    # Traction_cut_off_interface_yes
    special_brake_indep_adhesion: bool = False  # Add_brake_yes
    speed_inaccuracy: str = "subset041"        # Subset_sci / User_sci
    speed_inaccuracy_pct: Optional[float] = None  # D8
    odometer_abs: float = 0.0                  # D9
    odometer_rel_pct: float = 0.0              # D10
    supervised_manoeuvre: bool = False         # Supervised_manoeuvre_yes
    safe_consist_length: bool = True           # D25 ("Yes"/"No")
    engine_orientation_same: bool = True       # Engine_vs_train_orient_same
    consist_rear_min: float = 400.0            # D15
    consist_rear_nom: float = 400.0            # E15 (= D14)
    consist_rear_max: float = 400.0            # F15
    consist_front_min: float = 0.0             # D17
    consist_front_nom: float = 0.0             # E17 (= D16)
    consist_front_max: float = 0.0             # F17
    train_length: float = 200.0                # D18
    rotating_mass_pct: Optional[float] = 10.0  # D19 (None = unknown)
    antenna_to_front: float = 12.5             # D20
    engine_length: float = 25.0                # D21
    A_est1: float = 0.0                        # D22 (acceleration, m/s2)

    @property
    def max_overall_length(self) -> float:     # D24
        if self.train_type == "gamma":
            return 4095.0
        return 900.0 if self.brake_position == "Passenger in P" else 1500.0

    @property
    def overall_length(self) -> float:         # D26 =IF(D25="No",D18,F15+F17)
        if not self.safe_consist_length:
            return self.train_length
        return self.consist_rear_max + self.consist_front_max


@dataclass
# Entrées trackside — SUBSET-026 §3.13.2.3 : cible EOA/SvL ou LOA/MRSP (§3.13.8.1.1,
# §3.13.8.2), V_target/d_target (§3.13.8.1.1), d_svl (EBD jusqu'à la SvL: §3.13.8.3.2),
# release_speed fixe/embarquée (§3.13.9.4.3-§3.13.9.4.8), balises de relocalisation
# (Q_locacc: §3.13.9.4.8.2), gradient (§3.13.2.3.3, profil: §3.13.4.1),
# brake_inhibition (§3.13.5.1-§3.13.5.2: locations sans contribution des freins
# spéciaux), reduced_adhesion (§3.13.2.3.5, zones: §3.13.5.3-§3.13.5.5).
class Track:                                   # sheet "Track"
    target: str = "LOA_MRSP"                   # option buttons LoA_MRSP / EoA_SvL
    V_target: float = 40.0                     # B2 (forced to 0 for EOA/SvL)
    d_target: float = 6000.0                   # B3 distance origin -> target
    V_initial: float = 160.0                   # B4
    d_svl: float = 0.0                         # E1 distance EOA -> SvL
    release_speed: str = "fixed"               # Release_speed_fixed / Release_speed_OB
    fixed_release_speed: float = 0.0           # E2
    level: int = 2                             # Level1 / Level2
    # F2:G31 relocation balises: [distance from origin, location accuracy]
    balises: list = field(default_factory=lambda: [[0, 0], [2000, 0], [3000, 0], [4000, 0]])
    # I3:Jn gradient profile, as the sheet rows (d, G permil); see gradient_rows()
    gradient: list = field(default_factory=lambda: [[0, 0], [2000, 0], [2000, -5], [4000, -5],
                                                    [4000, 10], [6055, 10]])
    brake_inhibition: bool = False             # check box Brake_inhibition (gamma only)
    brake_inhib_start: float = 2000.0          # B6
    reduced_adhesion: bool = False             # check box Reduced_adhesion
    reduced_adh_start: float = 4500.0          # B9
    reduced_adh_end: float = 6500.0            # B10


@dataclass
# National Values — SUBSET-026 §3.13.2.3.7 : Q_NVSBTSMPERM / Q_NVGUIPERM /
# Q_NVINHSMICPERM (§3.13.2.3.7.1-§3.13.2.3.7.4), A_NVMAXREDADH1-3
# (§3.13.2.3.7.5, sélection selon §3.13.5.3-§3.13.5.4), M_NVAVADH (§3.13.2.3.7.6,
# utilisée dans A_brake_safe: §3.13.2.3.7.7 / §3.13.6.2.1.4).
class NationalValues:                          # sheet "National values"
    Q_NVSBTSMPERM: bool = True
    Q_NVGUIPERM: bool = True
    Q_NVINHSMICPERM: bool = False
    A_NVMAXREDADH1: float = 0.2                # B4
    A_NVMAXREDADH2: float = 0.2                # B5
    A_NVMAXREDADH3: float = 0.2                # B6
    M_NVAVADH: float = 0.0                     # B7


@dataclass
# Fixed values — SUBSET-026 Annexe A §A.3.1 (List of Fixed Value Data) :
# dV_ebi/dV_sbi/dV_warning et leurs plages V (§3.13.9.2.3-§3.13.9.2.6), T_warning
# (§3.13.9.3.4.2), T_driver (§3.13.9.3.5.2), T_41 (SUBSET-041 §5.2.1.13, utilisé en
# §3.13.9.4.8.2), M_rotating_max/min (§3.13.4.3.2), g.
class FixedValues:                             # sheet "Fixed values" C2:C19
    dV_ebi_min: float = 7.5
    dV_ebi_max: float = 15.0
    V_ebi_min: float = 110.0
    V_ebi_max: float = 210.0
    dV_sbi_min: float = 5.5
    dV_sbi_max: float = 10.0
    V_sbi_min: float = 110.0
    V_sbi_max: float = 210.0
    dV_warning_min: float = 4.0
    dV_warning_max: float = 5.0
    V_warning_min: float = 110.0
    V_warning_max: float = 140.0
    T_warning: float = 2.0
    T_driver: float = 4.0
    T_41: float = 1.0
    M_rotating_max: float = 15.0
    M_rotating_min: float = 2.0
    g: float = 9.81


def _ns_table(z, ab):
    return [[v, a] for v, a in zip(z, ab)]


_Z0 = [0, 40, 40.001, 160, 160.001, 160, 160.001, 160, 160.001, 160, 160.001, 180, 180.001, 200]
_AB0 = [0.4, 0.4, 0.3, 0.3, 0.3, 0.3, 0.35, 0.35, 0.35, 0.35, 0.35, 0.35, 0.35, 0.35]
_Z1 = [0, 60, 60.001, 160, 160.001, 160, 160.001, 160, 160.001, 160, 160.001, 160, 160.001, 200]
_AB1 = [1, 1, 0.6, 0.6, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]
_Z2 = [0, 80, 80.001, 160, 160.001, 160, 160.001, 160, 160.001, 160, 160.001, 160, 160.001, 200]
_AB2 = [0.5, 0.5, 0.3, 0.3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]
_AL0 = [0, 50, 50.001, 160, 160.001, 180, 180.001, 180, 180.001, 180, 180.001, 180, 180.001, 200]
_AN0 = [1, 1, 0.7, 0.7, 0.2, 0.2, 1, 1, 0.5, 0.5, 1, 1, 1, 1]
_AL1 = [0, 70, 70.001, 160, 160.001, 160, 160.001, 160, 160.001, 160, 160.001, 160, 160.001, 200]
_AN1 = [1, 1, 0.5, 0.5, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]
_AL2 = [0, 80, 80.001, 90, 90.001, 120, 120.001, 160, 160.001, 160, 160.001, 160, 160.001, 200]
_AN2 = [0.5, 0.5, 0.3, 0.3, 1, 1, 1, 1, 1, 1, 1, 1, 1, 1]

_KV_SPEEDS = [0, 25, 25.001, 30, 30.001, 100, 100.001, 160, 160.001, 200]


@dataclass
# Paramètres du freinage en λ — SUBSET-026 §3.13.3.3.1 (entrées du brake percentage
# conversion model: λ, vitesse max du modèle), §3.13.2.2.3.1.10-§3.13.2.2.3.1.11
# (3 jeux A_brake_normal_service sélectionnés par les pivots A_SB01/A_SB12),
# §3.13.2.3.7.11 (Kv_int voyageurs: subsets a/b, pivots A_NVP12/A_NVP23),
# §3.13.2.3.7.12 (Kr_int), §3.13.2.2.9.2 (Kn+/Kn-: correction gradient sur le
# service normal), §3.13.3.3.3 (Kt_int en sortie du conversion model).
class LambdaBrake:                              # sheets "Brake parameters (lambda)",
    lambda_pct: float = 90.0                    # "Integrated correction factors" ...
    conversion_model: bool = True               # Conversionmodel / ShorterValue (D13)
    T_brake_service_user: Optional[float] = None        # F14
    T_brake_service_react_user: Optional[float] = None  # F17
    conversion_model_max_speed: float = 200.0   # I27 / M27
    A_SB01: float = 1.2                         # U2
    A_SB12: float = 1.3                         # U3
    # rows 2..15 of Z/AB (P) and AL/AN (G) for A_brake_normal_service_0/1/2
    normal_service_P: list = field(default_factory=lambda: [_ns_table(_Z0, _AB0), _ns_table(_Z1, _AB1),
                                                            _ns_table(_Z2, _AB2)])
    normal_service_G: list = field(default_factory=lambda: [_ns_table(_AL0, _AN0), _ns_table(_AL1, _AN1),
                                                            _ns_table(_AL2, _AN2)])
    kv_freight: list = field(default_factory=lambda: [[0, .7], [200, .7], [200.001, .7], [200, .7],
                                                      [200.001, .7], [200, .7], [200.001, .7], [200, .7],
                                                      [200.001, .7], [200, .7]])            # A5:B14
    kv_passenger_speeds: list = field(default_factory=lambda: list(_KV_SPEEDS))           # D5:D14
    kv_passenger_a: list = field(default_factory=lambda: [.7, .7, .9, .9, .7, .7, .7, .7, .7, .7])  # E5:E14
    kv_passenger_b: list = field(default_factory=lambda: [.7] * 10)                        # E31:E40
    kr: list = field(default_factory=lambda: [[0, .9], [150, .9], [150.001, .9], [300, .9], [300.001, .9],
                                              [600, .9], [600.001, .9], [600, .9], [600.001, .9],
                                              [900, .9]])                                  # A32:B41
    A_NVP12: float = 1.0                        # D44
    A_NVP23: float = 1.2                        # F44
    Kt_int: float = 1.1                         # D47
    # "Gradient correction factors" A4:B13 (Kn+) and C4:D13 (Kn-)
    kn_plus: list = field(default_factory=lambda: [[0, 0], [25, 0], [25.001, 0], [55, 0], [55.001, 0],
                                                   [100, 0], [100.001, 0], [115, 0], [115.001, 0], [200, 0]])
    kn_minus: list = field(default_factory=lambda: [[0, 0], [25, 0], [25.001, 0], [55, 0], [55.001, 0],
                                                    [100, 0], [100.001, 0], [115, 0], [115.001, 0], [200, 0]])


def _step_table(speeds, values):
    """Builds rows V0, V1, V1+.001, ... as laid out in 'Brake parameters (gamma)'."""
    return [[v, a] for v, a in zip(speeds, values)]


_GV = [0, 40, 40.001, 80, 80.001, 100, 100.001, 155, 155.001, 180, 180.001, 250, 250.001, 300]
_GNSV = [0, 150, 150.001, 280, 280.001, 280, 280.001, 280, 280.001, 280, 280.001, 280, 280.001, 300]


def _gamma_comb(eb_values, kwet=0.95):
    return {
        "A_brake_emergency": _step_table(_GV, eb_values),
        "Kwet_rst": _step_table(_GV, [kwet] * 14),
        "T_brake_emergency": 2.5,
        "A_brake_service": _step_table(_GV, [.81, .81, .72, .72, .66, .66, .65, .65, .45, .45, .49, .49, .41, .41]),
        "T_brake_service": 4.8,
        "A_brake_normal_service": _step_table(_GNSV, [.3, .3, .35, .35, .4, .4, .4, .4, .4, .4, .4, .4, .4, .4]),
        "T_brake_emergency_react": 1.0,
        "T_brake_service_react": 1.2,
    }


@dataclass
# Paramètres du freinage en γ (modèles saisis en Train Data) — SUBSET-026
# §3.13.2.2.3.1 (step functions, jusqu'à 2 jeux de modèles: comb. n°1/comb. n°2,
# cf. §3.13.5.2 pour les locations sans freins spéciaux), §3.13.2.2.3.2 (temps de
# réaction et de montée), §3.13.2.2.9.1.5 (Kdry_rst(V, M_NVEBCL) et Kwet_rst(V)),
# ebcl ↔ M_NVEBCL: §3.13.2.3.7.8 (niveau de confiance sur la décélération EB).
class GammaBrake:                               # sheets "Brake parameters (gamma)",
    comb1: dict = field(default_factory=lambda: _gamma_comb(        # "Correction factor Kdry_rst"
        [.81, .81, .72, .72, .66, .66, .64, .64, .44, .44, .48, .48, .4, .4]))
    comb2: dict = field(default_factory=lambda: _gamma_comb(
        [.72, .72, .72, .72, .66, .66, .64, .64, .44, .44, .48, .48, .4, .4]))
    ebcl: int = 4                               # EBCL0..EBCL9 option buttons
    # Kdry_rst(V, EBCL): {ebcl: {"comb1": [7 values], "comb2": [7 values]}}
    kdry_by_ebcl: dict = field(default_factory=dict)

    @property
    def max_speed(self) -> float:               # H20
        return float(self.comb1["A_brake_emergency"][-1][0])


@dataclass
class Scenario:
    train: Train = field(default_factory=Train)
    track: Track = field(default_factory=Track)
    national: NationalValues = field(default_factory=NationalValues)
    fixed: FixedValues = field(default_factory=FixedValues)
    lambda_brake: LambdaBrake = field(default_factory=LambdaBrake)
    gamma_brake: GammaBrake = field(default_factory=GammaBrake)

    # ------------------------------------------------------------------ io
    def to_dict(self) -> dict:
        d = asdict(self)
        d["gamma_brake"]["kdry_by_ebcl"] = {str(k): v for k, v in self.gamma_brake.kdry_by_ebcl.items()}
        return d

    def to_json(self, path) -> None:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, indent=1)

    @classmethod
    def from_dict(cls, d: dict) -> "Scenario":
        def build(dc, data):
            names = {f.name for f in fields(dc)}
            unknown = set(data) - names
            if unknown:
                raise ValueError(f"Unknown {dc.__name__} field(s): {sorted(unknown)}")
            return dc(**data)
        gb = dict(d.get("gamma_brake", {}))
        if "kdry_by_ebcl" in gb:
            gb["kdry_by_ebcl"] = {int(k): v for k, v in gb["kdry_by_ebcl"].items()}
        return cls(train=build(Train, d.get("train", {})),
                   track=build(Track, d.get("track", {})),
                   national=build(NationalValues, d.get("national", {})),
                   fixed=build(FixedValues, d.get("fixed", {})),
                   lambda_brake=build(LambdaBrake, d.get("lambda_brake", {})),
                   gamma_brake=build(GammaBrake, gb))

    @classmethod
    def from_json(cls, path) -> "Scenario":
        with open(path, encoding="utf-8") as f:
            return cls.from_dict(json.load(f))

    @classmethod
    def default(cls) -> "Scenario":
        """Inputs saved in era_braking_curves_tool_v5.1.xlsm (incl. the Kdry_rst(V, EBCL) tables)."""
        return cls.from_dict(json.loads(_DEFAULT_SCENARIO_JSON))

    def copy(self) -> "Scenario":
        return copy.deepcopy(self)

    # ------------------------------------------------------- UI constraints
    def normalise(self) -> list[str]:
        """Applies the constraints enforced by the worksheet event handlers.

        Returns the list of adjustments made (empty when nothing changed).
        """
        notes = []
        t, tr, nv = self.train, self.track, self.national
        if t.train_type not in ("lambda", "gamma"):
            raise ValueError("train_type must be 'lambda' or 'gamma'")
        if t.brake_position not in BRAKE_POSITIONS:
            raise ValueError(f"brake_position must be one of {BRAKE_POSITIONS}")
        if tr.target not in ("LOA_MRSP", "EOA_SvL"):
            raise ValueError("target must be 'LOA_MRSP' or 'EOA_SvL'")
        if tr.target == "EOA_SvL" and tr.V_target != 0:
            tr.V_target = 0.0
            notes.append("EOA/SvL target: target speed set to 0 (LoA_MRSP_Change)")
        if tr.target == "LOA_MRSP" and tr.d_svl != 0:
            tr.d_svl = 0.0
            notes.append("LOA/MRSP target: SvL distance set to 0 (LoA_MRSP_Change)")
        if t.supervised_manoeuvre:
            if not t.safe_consist_length:
                t.safe_consist_length = True
                notes.append("Supervised manoeuvre: safe consist length forced to 'Yes'")
            if tr.target == "EOA_SvL" and tr.release_speed == "onboard" and tr.level != 2:
                tr.level = 2
                notes.append("Supervised manoeuvre: level 2 forced (CR1367)")
        else:
            if not t.engine_orientation_same:
                t.engine_orientation_same = True
                notes.append("No supervised manoeuvre: engine orientation forced to 'same'")
            if t.consist_front_min or t.consist_front_nom or t.consist_front_max:
                t.consist_front_min = t.consist_front_nom = t.consist_front_max = 0.0
                notes.append("No supervised manoeuvre: consist length in front of the engine set to 0")
        if t.train_type == "lambda":
            if tr.brake_inhibition:
                tr.brake_inhibition = False
                notes.append("Lambda train: brake inhibition area disabled")
        if t.speed_inaccuracy not in ("subset041", "user"):
            raise ValueError("speed_inaccuracy must be 'subset041' or 'user'")
        if t.speed_inaccuracy == "user" and not nv.Q_NVINHSMICPERM and t.speed_inaccuracy_pct is None:
            raise ValueError("speed_inaccuracy='user' requires speed_inaccuracy_pct")
        if t.overall_length > t.max_overall_length:
            raise ValueError(f"TOO LONG OVERALL TRAIN LENGTH ({t.overall_length} > {t.max_overall_length})")
        if (t.consist_rear_min > t.consist_rear_nom or t.consist_rear_max < t.consist_rear_nom
                or t.consist_front_min > t.consist_front_nom or t.consist_front_max < t.consist_front_nom):
            raise ValueError("INVALID MIN/MAX CONSIST LENGTH")
        if len(tr.balises) > 30:
            raise ValueError("At most 30 relocation balises (Track!F2:G31)")
        lb = self.lambda_brake
        if t.train_type == "lambda" and not lb.conversion_model and lb.T_brake_service_user is None:
            raise ValueError("User's shorter value selected: T_brake_service_user (F14) required")
        if t.train_type == "gamma" and self.gamma_brake.ebcl not in self.gamma_brake.kdry_by_ebcl:
            raise ValueError(f"No Kdry_rst table for EBCL index {self.gamma_brake.ebcl}")
        return notes


# Profil de gradient au format feuille 'Track' (I3:Jn) — SUBSET-026 §3.13.2.3.3,
# profil par éléments: §3.13.4.1.
def gradient_rows(breakpoints, end):
    """Builds the Track!I3:J.. layout from [(start_distance, gradient_permil), ...].

    Rows alternate (start, G) and (end, G); the end of one segment is the start
    of the next one, exactly as the sheet formulas I5 '=IF(J5="","",I4)' do.
    """
    rows = []
    for i, (start, g) in enumerate(breakpoints):
        seg_end = breakpoints[i + 1][0] if i + 1 < len(breakpoints) else end
        rows.append([start, g])
        rows.append([seg_end, g])
    return rows


# ==========================================================================


# ------------------------------------------------------------------------------
_DEFAULT_SCENARIO_JSON = """{"train":{"train_type":"lambda","brake_position":"Freight in P","T_traction_cut_off":2,"service_brake_interface":true,"traction_cut_off_interface":true,"special_brake_indep_adhesion":false,"speed_inaccuracy":"subset041","speed_inaccuracy_pct":null,"odometer_abs":0,"odometer_rel_pct":0,"supervised_manoeuvre":true,"safe_consist_length":true,"engine_orientation_same":false,"consist_rear_min":400,"consist_rear_nom":400,"consist_rear_max":400,"consist_front_min":0,"consist_front_nom":0,"consist_front_max":0,"train_length":200,"rotating_mass_pct":10,"antenna_to_front":12.5,"engine_length":25,"A_est1":0},"track":{"target":"LOA_MRSP","V_target":40,"d_target":6000,"V_initial":160,"d_svl":0,"release_speed":"fixed","fixed_release_speed":0,"level":2,"balises":[[0,0],[2000,0],[3000,0],[4000,0]],"gradient":[[0,0],[2000,0],[2000,-5],[4000,-5],[4000,10],[6055,10]],"brake_inhibition":false,"brake_inhib_start":2000,"reduced_adhesion":false,"reduced_adh_start":4500,"reduced_adh_end":6500},"national":{"Q_NVSBTSMPERM":true,"Q_NVGUIPERM":true,"Q_NVINHSMICPERM":false,"A_NVMAXREDADH1":0.2,"A_NVMAXREDADH2":0.2,"A_NVMAXREDADH3":0.2,"M_NVAVADH":0},"fixed":{"dV_ebi_min":7.5,"dV_ebi_max":15,"V_ebi_min":110,"V_ebi_max":210,"dV_sbi_min":5.5,"dV_sbi_max":10,"V_sbi_min":110,"V_sbi_max":210,"dV_warning_min":4,"dV_warning_max":5,"V_warning_min":110,"V_warning_max":140,"T_warning":2,"T_driver":4,"T_41":1,"M_rotating_max":15,"M_rotating_min":2,"g":9.81},"lambda_brake":{"lambda_pct":90,"conversion_model":true,"T_brake_service_user":null,"T_brake_service_react_user":null,"conversion_model_max_speed":200,"A_SB01":1.2,"A_SB12":1.3,"normal_service_P":[[[0,0.4],[40,0.4],[40.001,0.3],[160,0.3],[160.001,0.3],[160,0.3],[160.001,0.35],[160,0.35],[160.001,0.35],[160,0.35],[160.001,0.35],[180,0.35],[180.001,0.35],[200,0.35]],[[0,1],[60,1],[60.001,0.6],[160,0.6],[160.001,1],[160,1],[160.001,1],[160,1],[160.001,1],[160,1],[160.001,1],[160,1],[160.001,1],[200,1]],[[0,0.5],[80,0.5],[80.001,0.3],[160,0.3],[160.001,1],[160,1],[160.001,1],[160,1],[160.001,1],[160,1],[160.001,1],[160,1],[160.001,1],[200,1]]],"normal_service_G":[[[0,1],[50,1],[50.001,0.7],[160,0.7],[160.001,0.2],[180,0.2],[180.001,1],[180,1],[180.001,0.5],[180,0.5],[180.001,1],[180,1],[180.001,1],[200,1]],[[0,1],[70,1],[70.001,0.5],[160,0.5],[160.001,1],[160,1],[160.001,1],[160,1],[160.001,1],[160,1],[160.001,1],[160,1],[160.001,1],[200,1]],[[0,0.5],[80,0.5],[80.001,0.3],[90,0.3],[90.001,1],[120,1],[120.001,1],[160,1],[160.001,1],[160,1],[160.001,1],[160,1],[160.001,1],[200,1]]],"kv_freight":[[0,0.7],[200,0.7],[200.001,0.7],[200,0.7],[200.001,0.7],[200,0.7],[200.001,0.7],[200,0.7],[200.001,0.7],[200,0.7]],"kv_passenger_speeds":[0,25,25.001,30,30.001,100,100.001,160,160.001,200],"kv_passenger_a":[0.7,0.7,0.9,0.9,0.7,0.7,0.7,0.7,0.7,0.7],"kv_passenger_b":[0.7,0.7,0.7,0.7,0.7,0.7,0.7,0.7,0.7,0.7],"kr":[[0,0.9],[150,0.9],[150.001,0.9],[300,0.9],[300.001,0.9],[600,0.9],[600.001,0.9],[600,0.9],[600.001,0.9],[900,0.9]],"A_NVP12":1,"A_NVP23":1.2,"Kt_int":1.1,"kn_plus":[[0,0],[25,0],[25.001,0],[55,0],[55.001,0],[100,0],[100.001,0],[115,0],[115.001,0],[200,0]],"kn_minus":[[0,0],[25,0],[25.001,0],[55,0],[55.001,0],[100,0],[100.001,0],[115,0],[115.001,0],[200,0]]},"gamma_brake":{"comb1":{"A_brake_emergency":[[0,0.81],[40,0.81],[40.001,0.72],[80,0.72],[80.001,0.66],[100,0.66],[100.001,0.64],[155,0.64],[155.001,0.44],[180,0.44],[180.001,0.48],[250,0.48],[250.001,0.4],[300,0.4]],"Kwet_rst":[[0,0.95],[40,0.95],[40.001,0.95],[80,0.95],[80.001,0.95],[100,0.95],[100.001,0.95],[155,0.95],[155.001,0.95],[180,0.95],[180.001,0.95],[250,0.95],[250.001,0.95],[300,0.95]],"T_brake_emergency":2.5,"A_brake_service":[[0,0.81],[40,0.81],[40.001,0.72],[80,0.72],[80.001,0.66],[100,0.66],[100.001,0.65],[155,0.65],[155.001,0.45],[180,0.45],[180.001,0.49],[250,0.49],[250.001,0.41],[300,0.41]],"T_brake_service":4.8,"A_brake_normal_service":[[0,0.3],[150,0.3],[150.001,0.35],[280,0.35],[280.001,0.4],[280,0.4],[280.001,0.4],[280,0.4],[280.001,0.4],[280,0.4],[280.001,0.4],[280,0.4],[280.001,0.4],[300,0.4]],"T_brake_emergency_react":1,"T_brake_service_react":1.2},"comb2":{"A_brake_emergency":[[0,0.72],[40,0.72],[40.001,0.72],[80,0.72],[80.001,0.66],[100,0.66],[100.001,0.64],[155,0.64],[155.001,0.44],[180,0.44],[180.001,0.48],[250,0.48],[250.001,0.4],[300,0.4]],"Kwet_rst":[[0,0.95],[40,0.95],[40.001,0.95],[80,0.95],[80.001,0.95],[100,0.95],[100.001,0.95],[155,0.95],[155.001,0.95],[180,0.95],[180.001,0.95],[250,0.95],[250.001,0.95],[300,0.95]],"T_brake_emergency":2.5,"A_brake_service":[[0,0.81],[40,0.81],[40.001,0.72],[80,0.72],[80.001,0.66],[100,0.66],[100.001,0.65],[155,0.65],[155.001,0.45],[180,0.45],[180.001,0.49],[250,0.49],[250.001,0.41],[300,0.41]],"T_brake_service":4.8,"A_brake_normal_service":[[0,0.3],[150,0.3],[150.001,0.35],[280,0.35],[280.001,0.4],[280,0.4],[280.001,0.4],[280,0.4],[280.001,0.4],[280,0.4],[280.001,0.4],[280,0.4],[280.001,0.4],[300,0.4]],"T_brake_emergency_react":1,"T_brake_service_react":1.2},"ebcl":4,"kdry_by_ebcl":{"0":{"comb1":[1,1,1,1,1,1,1],"comb2":[1,1,1,1,1,1,1]},"1":{"comb1":[0.9,0.9,0.9,0.9,0.9,0.9,0.9],"comb2":[0.9,0.9,0.9,0.9,0.9,0.9,0.9]},"2":{"comb1":[0.85,0.85,0.85,0.85,0.85,0.85,0.85],"comb2":[0.85,0.85,0.85,0.85,0.85,0.85,0.85]},"3":{"comb1":[0.8,0.8,0.8,0.8,0.8,0.8,0.8],"comb2":[0.8,0.8,0.8,0.8,0.8,0.8,0.8]},"4":{"comb1":[0.75,0.75,0.75,0.75,0.75,0.75,0.75],"comb2":[0.75,0.75,0.75,0.75,0.75,0.75,0.75]},"5":{"comb1":[0.7,0.7,0.7,0.7,0.7,0.7,0.7],"comb2":[0.7,0.7,0.7,0.7,0.7,0.7,0.7]},"6":{"comb1":[0.6,0.6,0.6,0.6,0.6,0.6,0.6],"comb2":[0.6,0.6,0.6,0.6,0.6,0.6,0.6]},"7":{"comb1":[0.45,0.45,0.45,0.45,0.45,0.45,0.45],"comb2":[0.45,0.45,0.45,0.45,0.45,0.45,0.45]},"8":{"comb1":[0.4,0.4,0.4,0.4,0.4,0.4,0.4],"comb2":[0.4,0.4,0.4,0.4,0.4,0.4,0.4]},"9":{"comb1":[0.4,0.4,0.4,0.4,0.4,0.4,0.4],"comb2":[0.4,0.4,0.4,0.4,0.4,0.4,0.4]}}}}"""



if __name__ == "__main__":
    import sys
    sys.exit(main())