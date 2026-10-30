"""ERA Braking Curves simulation tool v5.1 — réécriture Python autonome.

Port fidèle de l'outil Excel/VBA ERA Braking Curves Tool v5.1, conforme au
référentiel SUBSET-026 v4.0.0 (SRS, chapitre 3.13 + Annexe A) et SUBSET-041.
Chaque formule porte en commentaire la (les) clause(s) SRS implémentée(s).

Utilisation :
    python -m era_bct                 # interface graphique (Tkinter)
    python -m era_bct scenario.json   # CLI : points caractéristiques
    python -m era_bct classeur.xlsm --compare --tol 1e-9
"""

from .vba import (
    VBAError, Ref, EMPTY, EMPTY_STR, is_blank, num, gt, clng, vint, vround,
    roundup, vpow, wmax, wmin, match_index, vlookup, Table, Grid,
)
from .model import (
    BRAKE_POSITIONS, Train, Track, NationalValues, FixedValues,
    LambdaBrake, GammaBrake, Scenario, gradient_rows,
)
from .lambda_model import V_lim, AD_UIC, t_bbu, t_bbuSB, t_bbuEB_react, t_bbuSB_react, uic_table, LambdaParameters
from .tables import RowTable, new_calc_sheet, build_lambda_table, build_gamma_table, kdry_rows, M_NVEBCL, gamma_max_speed, column_values
from .geometry import S41_speed_inacc, ceiling_speed_margin, GeometryMixin
from .accel import AccelMixin
from .track import AbortCalculation, build_track, COMB2
from .curves import calculate_curves
from .engine import Engine, Result, run, CURVE_COLUMNS
from .workbook import read_controls, load_workbook_scenario
from .compare import compare_with_workbook
from .cli import main

__all__ = [
    "VBAError", "Ref", "EMPTY", "EMPTY_STR", "is_blank", "num", "gt", "clng", "vint", "vround",
    "roundup", "vpow", "wmax", "wmin", "match_index", "vlookup", "Table", "Grid",
    "BRAKE_POSITIONS", "Train", "Track", "NationalValues", "FixedValues",
    "LambdaBrake", "GammaBrake", "Scenario", "gradient_rows",
    "V_lim", "AD_UIC", "t_bbu", "t_bbuSB", "t_bbuEB_react", "t_bbuSB_react", "uic_table", "LambdaParameters",
    "RowTable", "new_calc_sheet", "build_lambda_table", "build_gamma_table", "kdry_rows", "M_NVEBCL",
    "gamma_max_speed", "column_values",
    "S41_speed_inacc", "ceiling_speed_margin", "GeometryMixin",
    "AccelMixin", "AbortCalculation", "build_track", "COMB2",
    "calculate_curves", "Engine", "Result", "run", "CURVE_COLUMNS",
    "read_controls", "load_workbook_scenario", "compare_with_workbook", "main",
]
