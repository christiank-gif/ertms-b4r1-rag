from __future__ import annotations

from dataclasses import asdict

from .compare import compare_with_workbook
from .engine import run
from .model import Scenario, BRAKE_POSITIONS
from .tables import M_NVEBCL
from .lambda_model import LambdaParameters
from .model import gradient_rows
from .vba import is_blank
from .workbook import load_workbook_scenario


# SECTION 13/13 — INTERFACE GRAPHIQUE (Tkinter) : un onglet par feuille d'entrée du
# classeur ERA v5.1 + onglet Résultats (points caractéristiques, graphique, export)
# + onglet « Comparaison VBA » (conformité cellule par cellule au classeur importé).
# Aucune clause SRS : présentation des entrées/sorties ; le calcul reste celui des
# sections 1-12 (bouton ▶ / F5).
# ==========================================================================
"""Interface graphique (Tkinter) : un onglet par feuille d'entrée du classeur
ERA v5.1 ('Train (main)', 'Track', 'National values', 'Fixed values', 'Brake
parameters (lambda)', 'Correction factors', 'Brake parameters (gamma)'), avec
les mêmes libellés et les mêmes règles d'activation que les handlers du
classeur, plus un onglet 'Results' (points caractéristiques, graphique,
export CSV/PNG). Scénarios sauvegardés en JSON ; import possible des entrées
d'un classeur .xlsm.

    python era_bct.py --gui
"""

def _scenario_diff(a, b, tol=1e-9):
    """Champs divergents entre deux scénarios (onglets du GUI vs classeur importé).

    Compare les scénarios *normalisés* (les contraintes des feuilles étant
    appliquées des deux côtés) ; tolérance numérique réglable.
    """
    import math
    out = []

    def diff(x, y, path):
        if isinstance(x, dict) and isinstance(y, dict):
            for k in sorted(set(x) | set(y), key=str):
                diff(x.get(k), y.get(k), f"{path}.{k}" if path else str(k))
            return
        if x == y:
            return
        if (isinstance(x, (int, float)) and not isinstance(x, bool)
                and isinstance(y, (int, float)) and not isinstance(y, bool)):
            if math.isclose(x, y, rel_tol=tol, abs_tol=tol):
                return
            out.append(f"{path} : onglets = {x:g} ≠ classeur = {y:g}")
        else:
            sx, sy = repr(x), repr(y)
            if len(sx) > 40:
                sx = sx[:37] + "..."
            if len(sy) > 40:
                sy = sy[:37] + "..."
            out.append(f"{path} : onglets = {sx} ≠ classeur = {sy}")

    diff(asdict(a), asdict(b), "")
    return out


try:                                   # tkinter absent → CLI inchangé, --gui l'explique
    import tkinter as tk
    from tkinter import filedialog, messagebox, ttk
    _TK_OK = True
except ImportError:
    _TK_OK = False

if _TK_OK:

    import os


    APP_TITLE = "ERA Braking Curves – Python v5.1"
    PAD = dict(padx=4, pady=2)


    # ======================================================================== helpers
    def parse(s: str, optional=False):
        s = (s or "").strip().replace(",", ".")
        if s == "":
            if optional:
                return None
            raise ValueError("valeur manquante")
        return float(s)


    def fmt(v) -> str:
        if v is None or v == "":
            return ""
        if isinstance(v, float) and v.is_integer():
            return str(int(v))
        return repr(v) if isinstance(v, float) else str(v)


    class ScrollFrame(ttk.Frame):
        """Vertically scrollable container (self.body receives the widgets)."""

        def __init__(self, parent):
            super().__init__(parent)
            canvas = tk.Canvas(self, highlightthickness=0)
            sb = ttk.Scrollbar(self, orient="vertical", command=canvas.yview)
            self.body = ttk.Frame(canvas)
            self.body.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
            canvas.create_window((0, 0), window=self.body, anchor="nw")
            canvas.configure(yscrollcommand=sb.set)
            canvas.pack(side="left", fill="both", expand=True)
            sb.pack(side="right", fill="y")

            def wheel(e):
                canvas.yview_scroll(int(-1 * (e.delta / 120)) if e.delta else (1 if e.num == 5 else -1), "units")
            canvas.bind_all("<MouseWheel>", wheel, add="+")
            canvas.bind_all("<Button-4>", wheel, add="+")
            canvas.bind_all("<Button-5>", wheel, add="+")


    class Field:
        """Labelled numeric entry: label | entry | unit | cell reference."""

        def __init__(self, parent, row, label, unit="", cell="", width=10, optional=False, col=0):
            self.label = ttk.Label(parent, text=label)
            self.label.grid(row=row, column=col, sticky="w", **PAD)
            self.var = tk.StringVar()
            self.entry = ttk.Entry(parent, textvariable=self.var, width=width, justify="right")
            self.entry.grid(row=row, column=col + 1, sticky="w", **PAD)
            if unit:
                ttk.Label(parent, text=unit).grid(row=row, column=col + 2, sticky="w")
            if cell:
                ttk.Label(parent, text=cell, foreground="#888").grid(row=row, column=col + 3, sticky="w", padx=6)
            self.name = label
            self.optional = optional

        def get(self):
            try:
                return parse(self.var.get(), self.optional)
            except ValueError as exc:
                raise ValueError(f"{self.name} : {exc}") from None

        def set(self, v):
            self.var.set(fmt(v))

        def enable(self, on: bool):
            self.entry.configure(state="normal" if on else "disabled")


    class Choice:
        """Group of radio buttons bound to one value."""

        def __init__(self, parent, row, label, options, cell="", col=0):
            ttk.Label(parent, text=label).grid(row=row, column=col, sticky="w", **PAD)
            fr = ttk.Frame(parent)
            fr.grid(row=row, column=col + 1, columnspan=2, sticky="w")
            self.var = tk.StringVar()
            self.buttons = {}
            for value, text in options:
                b = ttk.Radiobutton(fr, text=text, value=str(value), variable=self.var)
                b.pack(side="left", padx=3)
                self.buttons[str(value)] = b
            if cell:
                ttk.Label(parent, text=cell, foreground="#888").grid(row=row, column=col + 3, sticky="w", padx=6)

        def get(self):
            return self.var.get()

        def set(self, v):
            self.var.set(str(v))

        def enable(self, on: bool, only=None):
            for k, b in self.buttons.items():
                if only is None or k in only:
                    b.configure(state="normal" if on else "disabled")


    class YesNo(Choice):
        def __init__(self, parent, row, label, cell="", col=0, yes="Yes", no="No"):
            super().__init__(parent, row, label, [("1", yes), ("0", no)], cell, col)

        def get(self):
            return self.var.get() == "1"

        def set(self, v):
            self.var.set("1" if v else "0")


    class EntryTable(ttk.Frame):
        """Editable grid of numbers (fixed number of rows, or growable)."""

        def __init__(self, parent, headers, nrows, width=9, growable=False, max_rows=None, title=None):
            super().__init__(parent)
            self.headers, self.width, self.growable, self.max_rows = headers, width, growable, max_rows
            r0 = 0
            if title:
                ttk.Label(self, text=title, font=("TkDefaultFont", 9, "bold")).grid(row=0, column=0,
                                                                                      columnspan=len(headers) + 1,
                                                                                      sticky="w")
                r0 = 1
            for j, h in enumerate(headers):
                ttk.Label(self, text=h).grid(row=r0, column=j + 1, **PAD)
            self.r0 = r0 + 1
            self.rows: list[list[tk.StringVar]] = []
            self.widgets: list[list] = []
            for _ in range(nrows):
                self._add_row()
            if growable:
                bar = ttk.Frame(self)
                bar.grid(row=1000, column=0, columnspan=len(headers) + 1, sticky="w")
                ttk.Button(bar, text="+ ligne", command=self._add_row).pack(side="left", padx=2, pady=3)
                ttk.Button(bar, text="– ligne", command=self._del_row).pack(side="left", padx=2, pady=3)

        def _add_row(self):
            if self.max_rows and len(self.rows) >= self.max_rows:
                return
            i = len(self.rows)
            vars_, ws = [], []
            lab = ttk.Label(self, text=str(i + 1), foreground="#888")
            lab.grid(row=self.r0 + i, column=0, sticky="e")
            ws.append(lab)
            for j in range(len(self.headers)):
                v = tk.StringVar()
                e = ttk.Entry(self, textvariable=v, width=self.width, justify="right")
                e.grid(row=self.r0 + i, column=j + 1, padx=1, pady=1)
                vars_.append(v)
                ws.append(e)
            self.rows.append(vars_)
            self.widgets.append(ws)

        def _del_row(self):
            if self.rows:
                for w in self.widgets.pop():
                    w.destroy()
                self.rows.pop()

        def set(self, data):
            if self.growable:
                while len(self.rows) > len(data):
                    self._del_row()
                while len(self.rows) < len(data):
                    self._add_row()
            for vars_, vals in zip(self.rows, data):
                vals = vals if isinstance(vals, (list, tuple)) else [vals]
                for v, x in zip(vars_, vals):
                    v.set(fmt(x))

        def get(self, skip_empty=False):
            out = []
            for i, vars_ in enumerate(self.rows):
                txt = [v.get() for v in vars_]
                if skip_empty and all(t.strip() == "" for t in txt):
                    continue
                try:
                    out.append([parse(t) for t in txt])
                except ValueError:
                    raise ValueError(f"{self.headers} ligne {i + 1} : valeur numérique attendue") from None
            return out

        def enable(self, on: bool):
            for ws in self.widgets:
                for w in ws[1:]:
                    w.configure(state="normal" if on else "disabled")


    def section(parent, text, row, col=0, colspan=4):
        lf = ttk.LabelFrame(parent, text=text)
        lf.grid(row=row, column=col, columnspan=colspan, sticky="nwe", padx=6, pady=4)
        return lf


    # ========================================================================== app
    class App(tk.Tk):
        def __init__(self, scenario: Scenario | None = None, wb_path=None):
            super().__init__()
            self.title(APP_TITLE)
            self.geometry("1180x820")
            self.path = None
            self.wb_path = wb_path
            self.result = None
            self._building = True
            self._toolbar()
            self.nb = ttk.Notebook(self)
            self.nb.pack(fill="both", expand=True)
            self._tab_train()
            self._tab_track()
            self._tab_national()
            self._tab_fixed()
            self._tab_lambda()
            self._tab_correction()
            self._tab_gamma()
            self._tab_results()
            self._tab_compare()
            self.status = tk.StringVar(value="")
            ttk.Label(self, textvariable=self.status, anchor="w", relief="sunken").pack(fill="x", side="bottom")
            self.load(scenario or Scenario.default())
            self._building = False
            self.refresh()

        # -------------------------------------------------------------- toolbar
        def _toolbar(self):
            bar = ttk.Frame(self)
            bar.pack(fill="x")
            for text, cmd in (("Nouveau (valeurs v5.1)", self.cmd_new), ("Ouvrir JSON…", self.cmd_open),
                              ("Importer .xlsm…", self.cmd_import), ("Enregistrer JSON…", self.cmd_save)):
                ttk.Button(bar, text=text, command=cmd).pack(side="left", padx=3, pady=4)
            ttk.Button(bar, text="▶ Calculate the curves", command=self.cmd_calculate).pack(side="right", padx=6, pady=4)
            self.bind("<F5>", lambda e: self.cmd_calculate())

        def _watch(self, *widgets):
            for w in widgets:
                w.var.trace_add("write", lambda *a: self.refresh())

        # ------------------------------------------------------------ Train tab
        def _tab_train(self):
            sf = ScrollFrame(self.nb)
            self.nb.add(sf, text="Train (main)")
            f = sf.body
            g = section(f, "Train", 0)
            self.train_type = Choice(g, 0, "Train type", [("lambda", "Lambda train"), ("gamma", "Gamma train")])
            self.brake_position = Choice(g, 1, "Brake position", [(p, p) for p in BRAKE_POSITIONS], "D23")
            self.T_tco = Field(g, 2, "Traction model: T_traction_cut_off", "s", "D4")
            self.sb_int = YesNo(g, 3, "Service brake interface ?")
            self.tco_int = YesNo(g, 4, "Traction cut off interface ?")
            self.add_brake = YesNo(g, 5, "Special/additional brake independent from wheel/track adhesion?")
            g = section(f, "Odometry", 1)
            self.sci = Choice(g, 0, "Speed inaccuracy", [("subset041", "Subset-041"), ("user", "Fixed (Enter value)")])
            self.sci_pct = Field(g, 1, "Speed inaccuracy", "%", "D8", optional=True)
            self.odo = Choice(g, 2, "Odometer inaccuracy", [("fixed", "Abs. value + Rel. value"),
                                                            ("subset041", "Subset-041 (5 m + 5 %)")])
            self.odo_abs = Field(g, 3, "Odometer inaccuracy (abs.)", "m", "D9")
            self.odo_rel = Field(g, 4, "Odometer inaccuracy (rel.)", "%", "D10")
            g = section(f, "Train length and consist", 2)
            self.sm = YesNo(g, 0, "Supervised Manoeuvre ?")
            self.safe_len = YesNo(g, 1, "Safe consist length info available ?", "D25")
            self.orient = Choice(g, 2, "Engine orientation vs. train orientation",
                                 [("same", "Same"), ("opposite", "Opposite")])
            ttk.Label(g, text="Consist length in rear of the engine (inclusive) (m)").grid(row=3, column=0, sticky="w", **PAD)
            self.rear = EntryTable(g, ["min (m)", "nominal (m)", "max (m)"], 1)
            self.rear.grid(row=3, column=1, columnspan=2, sticky="w")
            ttk.Label(g, text="D15:F15", foreground="#888").grid(row=3, column=3, sticky="w", padx=6)
            ttk.Label(g, text="Consist length in front of the engine (m)").grid(row=4, column=0, sticky="w", **PAD)
            self.front = EntryTable(g, ["min (m)", "nominal (m)", "max (m)"], 1)
            self.front.grid(row=4, column=1, columnspan=2, sticky="w")
            ttk.Label(g, text="D17:F17", foreground="#888").grid(row=4, column=3, sticky="w", padx=6)
            self.train_length = Field(g, 5, "Train length", "m", "D18")
            self.rot = Choice(g, 6, "Nominal rotating mass", [("unknown", "Unknown"), ("value", "Fixed (Enter value)")])
            self.rot_pct = Field(g, 7, "Nominal rotating mass", "%", "D19", optional=True)
            self.antenna = Field(g, 8, "Distance antenna - engine front", "m", "D20")
            self.engine_len = Field(g, 9, "Engine length", "m", "D21")
            self.acc = Field(g, 10, "Acceleration", "m/s²", "D22")
            self.len_info = tk.StringVar()
            ttk.Label(g, textvariable=self.len_info, foreground="#06c").grid(row=11, column=0, columnspan=4, sticky="w", **PAD)
            self._watch(self.train_type, self.brake_position, self.sci, self.odo, self.sm, self.safe_len, self.rot)
            for t in (self.rear, self.front):
                for v in t.rows[0]:
                    v.trace_add("write", lambda *a: self.refresh())
            self.train_length.var.trace_add("write", lambda *a: self.refresh())

        # ------------------------------------------------------------ Track tab
        def _tab_track(self):
            sf = ScrollFrame(self.nb)
            self.nb.add(sf, text="Track")
            f = sf.body
            g = section(f, "Target", 0, colspan=2)
            self.target = Choice(g, 0, "Target type", [("LOA_MRSP", "LOA/MRSP"), ("EOA_SvL", "EOA/SvL")])
            self.V_target = Field(g, 1, "Target speed", "km/h", "B2")
            self.d_target = Field(g, 2, "Dist. origin/target", "m", "B3")
            self.V_init = Field(g, 3, "Initial speed", "km/h", "B4")
            self.d_svl = Field(g, 4, "Distance EOA/SvL", "m", "E1")
            self.rs_mode = Choice(g, 5, "Release speed", [("fixed", "Fixed"), ("onboard", "Calc on-board")])
            self.rs_value = Field(g, 6, "Release speed", "km/h", "E2")
            self.level = Choice(g, 7, "Level", [("1", "L1"), ("2", "L2")])
            g = section(f, "Track conditions", 1, colspan=2)
            self.inhib = YesNo(g, 0, "Brake inhibition area (gamma)")
            self.inhib_start = Field(g, 1, "Start of brake inhibition", "m", "B6")
            ttk.Label(g, text="End of brake inhibition : EBD foot").grid(row=2, column=0, sticky="w", **PAD)
            self.redadh = YesNo(g, 3, "Reduced adhesion area")
            self.redadh_start = Field(g, 4, "Start of reduced adhesion", "m", "B9")
            self.redadh_end = Field(g, 5, "End of reduced adhesion", "m", "B10")
            g = section(f, "Relocation balises (F2:G31, max 30)", 2, col=0, colspan=1)
            self.balises = EntryTable(g, ["Distance from origin (m)", "Location accuracy (m)"], 4, width=14,
                                      growable=True, max_rows=30)
            self.balises.pack(anchor="w")
            g = section(f, "Gradient profile (I3:J…)", 2, col=1, colspan=1)
            ttk.Label(g, text="Segments: start (m), end (m), gradient G (‰, + = uphill). "
                              "The last end is extended to the SvL / EBD foot if needed.",
                      wraplength=430, foreground="#555").pack(anchor="w")
            self.gradient = EntryTable(g, ["d start (m)", "d end (m)", "G (‰)"], 3, width=11, growable=True, max_rows=51)
            self.gradient.pack(anchor="w")
            self._watch(self.target, self.rs_mode, self.inhib, self.redadh)

        # ---------------------------------------------------------- National tab
        def _tab_national(self):
            f = ttk.Frame(self.nb)
            self.nb.add(f, text="National values")
            g = section(f, "National values", 0)
            self.q_sbtsm = YesNo(g, 0, "Permission to use service brake in target speed monitoring", "Q_NVSBTSMPERM")
            self.q_gui = YesNo(g, 1, "Permission to use the guidance curve", "Q_NVGUIPERM")
            self.q_inhsmic = YesNo(g, 2, "Permission to inhibit the compensation of the speed measurement inaccuracy",
                                   "Q_NVINHSMICPERM")
            self.a_red1 = Field(g, 3, "Maximum deceleration value under reduced adhesion conditions (1)", "m/s²",
                                "A_NVMAXREDADH1")
            self.a_red2 = Field(g, 4, "Maximum deceleration value under reduced adhesion conditions (2)", "m/s²",
                                "A_NVMAXREDADH2")
            self.a_red3 = Field(g, 5, "Maximum deceleration value under reduced adhesion conditions (3)", "m/s²",
                                "A_NVMAXREDADH3")
            self.m_avadh = Field(g, 6, "Weighting factor for available wheel/rail adhesion (gamma)", "", "M_NVAVADH")
            self.ebcl_info = tk.StringVar()
            ttk.Label(g, textvariable=self.ebcl_info, foreground="#06c").grid(row=7, column=0, columnspan=4, sticky="w", **PAD)
            ttk.Label(g, text="Kr_int, Kv_int, Kt_int, A_NVP12, A_NVP23: see tab 'Correction factors'.",
                      foreground="#555").grid(row=8, column=0, columnspan=4, sticky="w", **PAD)
            self._watch(self.q_sbtsm, self.q_inhsmic)

        # ------------------------------------------------------------- Fixed tab
        FIXED = [("dV_ebi_min", "km/h"), ("dV_ebi_max", "km/h"), ("V_ebi_min", "km/h"), ("V_ebi_max", "km/h"),
                 ("dV_sbi_min", "km/h"), ("dV_sbi_max", "km/h"), ("V_sbi_min", "km/h"), ("V_sbi_max", "km/h"),
                 ("dV_warning_min", "km/h"), ("dV_warning_max", "km/h"), ("V_warning_min", "km/h"),
                 ("V_warning_max", "km/h"), ("T_warning", "s"), ("T_driver", "s"), ("T_41", "s"),
                 ("M_rotating_max", "%"), ("M_rotating_min", "%"), ("g", "m/s²")]

        def _tab_fixed(self):
            f = ttk.Frame(self.nb)
            self.nb.add(f, text="Fixed values")
            g = section(f, "Fixed values (SUBSET-026 Appendix A.3.1)", 0)
            self.fixed = {}
            for i, (n, u) in enumerate(self.FIXED):
                self.fixed[n] = Field(g, i, n, u, f"C{i + 2}")

        # ------------------------------------------------------------ Lambda tab
        def _tab_lambda(self):
            sf = ScrollFrame(self.nb)
            self.nb.add(sf, text="Brake parameters (lambda)")
            self.tab_lambda = sf
            f = sf.body
            g = section(f, "Brake percentage and brake build-up times", 0)
            self.lam = Field(g, 0, "Brake percentage λ (30 – 250)", "%", "F3")
            self.cm = Choice(g, 1, "T_brake_service", [("cm", "Conversion Model"), ("user", "User's shorter value")])
            self.tbs_user = Field(g, 2, "T_brake_service (user's shorter value)", "s", "F14", optional=True)
            self.tbs_react_user = Field(g, 3, "T_brake_service_react (user's shorter value)", "s", "F17", optional=True)
            self.cm_max = Field(g, 4, "Conversion Model maximum speed", "km/h", "I27")
            self.lam_info = tk.Text(g, height=7, width=95, font=("TkFixedFont", 9), relief="flat", background="#f4f4f4")
            self.lam_info.grid(row=5, column=0, columnspan=4, sticky="w", **PAD)
            g = section(f, "Normal service brake deceleration (A_brake_normal_service)", 1)
            self.a_sb01 = Field(g, 0, "A_SB01", "m/s²", "U2")
            self.a_sb12 = Field(g, 1, "A_SB12", "m/s²", "U3")
            tf = ttk.Frame(g)
            tf.grid(row=2, column=0, columnspan=4, sticky="w")
            self.ns_P, self.ns_G = [], []
            for k in range(3):
                t = EntryTable(tf, ["V (km/h)", "AD (m/s²)"], 14, width=8,
                               title=f"A_brake_normal_service_{k} – P")
                t.grid(row=0, column=k, padx=6, sticky="n")
                self.ns_P.append(t)
                t = EntryTable(tf, ["V (km/h)", "AD (m/s²)"], 14, width=8,
                               title=f"A_brake_normal_service_{k} – Freight G")
                t.grid(row=1, column=k, padx=6, pady=6, sticky="n")
                self.ns_G.append(t)
            self._watch(self.cm)
            self.lam.var.trace_add("write", lambda *a: self.refresh())

        # ------------------------------------------------------- Correction tab
        def _tab_correction(self):
            sf = ScrollFrame(self.nb)
            self.nb.add(sf, text="Correction factors")
            self.tab_corr = sf
            f = sf.body
            g = section(f, "Integrated correction factors (lambda)", 0)
            tf = ttk.Frame(g)
            tf.grid(row=0, column=0, columnspan=4, sticky="w")
            self.kv_freight = EntryTable(tf, ["V (km/h)", "Kv_int"], 10, width=8, title="Kv_int – freight (A5:B14)")
            self.kv_freight.grid(row=0, column=0, padx=6, sticky="n")
            self.kv_pass = EntryTable(tf, ["V (km/h)", "Kv_int_x_a", "Kv_int_x_b"], 10, width=8,
                                      title="Kv_int – passenger (D5:E14 / E31:E40)")
            self.kv_pass.grid(row=0, column=1, padx=6, sticky="n")
            self.kr = EntryTable(tf, ["L (m)", "Kr_int"], 10, width=8, title="Kr_int(L) (A32:B41)")
            self.kr.grid(row=0, column=2, padx=6, sticky="n")
            self.a_p12 = Field(g, 1, "A_NVP12", "m/s²", "D44")
            self.a_p23 = Field(g, 2, "A_NVP23", "m/s²", "F44")
            self.kt = Field(g, 3, "Kt_int", "", "D47")
            g = section(f, "Gradient correction factors for normal service deceleration", 1)
            self.kn_plus = EntryTable(g, ["V (km/h)", "Kn+ (m/s²)"], 10, width=8, title="Positive gradients (A4:B13)")
            self.kn_plus.grid(row=0, column=0, padx=6, sticky="n")
            self.kn_minus = EntryTable(g, ["V (km/h)", "Kn- (m/s²)"], 10, width=8, title="Negative gradients (C4:D13)")
            self.kn_minus.grid(row=0, column=1, padx=6, sticky="n")

        # ------------------------------------------------------------- Gamma tab
        GTABLES = [("A_brake_emergency", "Emergency brake deceleration"), ("Kwet_rst", "Correction factor Kwet_rst(V)"),
                   ("A_brake_service", "Full service brake deceleration"),
                   ("A_brake_normal_service", "Normal service brake deceleration")]
        GTIMES = [("T_brake_emergency", "T_brake_emergency"), ("T_brake_service", "T_brake_service"),
                  ("T_brake_emergency_react", "T_brake_emergency_react"),
                  ("T_brake_service_react", "T_brake_service_react")]

        def _tab_gamma(self):
            sf = ScrollFrame(self.nb)
            self.nb.add(sf, text="Brake parameters (gamma)")
            self.tab_gamma = sf
            f = sf.body
            self.gt, self.gtimes = {}, {}
            for k, comb in enumerate(("comb1", "comb2")):
                title = "Combination n°1" if comb == "comb1" else \
                    "Combination n°2 (brake inhibition of special brake(s) area)"
                g = section(f, title, k)
                tf = ttk.Frame(g)
                tf.grid(row=0, column=0, columnspan=4, sticky="w")
                for j, (key, label) in enumerate(self.GTABLES):
                    t = EntryTable(tf, ["V (km/h)", "value"], 14, width=8, title=label)
                    t.grid(row=0, column=j, padx=5, sticky="n")
                    self.gt[(comb, key)] = t
                for j, (key, label) in enumerate(self.GTIMES):
                    self.gtimes[(comb, key)] = Field(g, 1 + j, label, "s")
            g = section(f, "Emergency Brake Confidence Level (EBCL) and Kdry_rst(V, EBCL)", 2)
            self.ebcl = Choice(g, 0, "EBCL", [(str(i), lab) for i, lab in
                                              enumerate(["0.5"] + [f"1-10E-{i}" for i in range(1, 10)])])
            ttk.Label(g, text="Kdry_rst for the 7 speed steps (V0…V6 of the emergency brake table) — sheet "
                              "'Correction factor Kdry_rst'", foreground="#555").grid(row=1, column=0, columnspan=4,
                                                                                      sticky="w", **PAD)
            tf = ttk.Frame(g)
            tf.grid(row=2, column=0, columnspan=4, sticky="w")
            hdr = [f"Kdry{j}" for j in range(7)]
            self.kdry1 = EntryTable(tf, hdr, 10, width=7, title="Combination n°1 (one row per EBCL 0…9)")
            self.kdry1.grid(row=0, column=0, padx=5, sticky="n")
            self.kdry2 = EntryTable(tf, hdr, 10, width=7, title="Combination n°2")
            self.kdry2.grid(row=0, column=1, padx=5, sticky="n")
            self._watch(self.ebcl)

        # ----------------------------------------------------------- Results tab
        def _tab_results(self):
            f = ttk.Frame(self.nb)
            self.nb.add(f, text="Results")
            self.tab_results = f
            left = ttk.Frame(f)
            left.pack(side="left", fill="y", padx=6, pady=6)
            ttk.Button(left, text="▶ Calculate the curves", command=self.cmd_calculate).pack(fill="x", pady=3)
            ttk.Button(left, text="Exporter les courbes (CSV)…", command=self.cmd_csv).pack(fill="x", pady=3)
            ttk.Button(left, text="Exporter le graphique…", command=self.cmd_png).pack(fill="x", pady=3)
            self.tree = ttk.Treeview(left, columns=("v",), height=10)
            self.tree.heading("#0", text="Characteristic points")
            self.tree.heading("v", text="Distance from target (m)")
            self.tree.column("#0", width=230)
            self.tree.column("v", width=160, anchor="e")
            self.tree.pack(fill="x", pady=6)
            ttk.Label(left, text="Courbes affichées").pack(anchor="w")
            self.show = {}
            for n in ("EBD", "SBD", "EBI", "SBI", "Warning", "Permitted", "Indication", "GUI", "Release speed"):
                v = tk.BooleanVar(value=True)
                ttk.Checkbutton(left, text=n, variable=v, command=self.draw).pack(anchor="w")
                self.show[n] = v
            ttk.Label(left, text="Messages").pack(anchor="w", pady=(8, 0))
            self.msg = tk.Text(left, width=48, height=12, wrap="word", font=("TkDefaultFont", 9))
            self.msg.pack(fill="both", expand=True)
            right = ttk.Frame(f)
            right.pack(side="left", fill="both", expand=True)
            self.canvas = None
            try:
                from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk
                from matplotlib.figure import Figure
                self.fig = Figure(figsize=(8, 6))
                self.ax = self.fig.add_subplot()
                self.canvas = FigureCanvasTkAgg(self.fig, master=right)
                NavigationToolbar2Tk(self.canvas, right)
                self.canvas.get_tk_widget().pack(fill="both", expand=True)
            except ImportError:
                ttk.Label(right, text="matplotlib non installé : graphique indisponible").pack()

        # ---------------------------------------------------- Comparaison tab
        # Comparaison avec les valeurs en cache du VBA (compare_with_workbook,
        # section 11). Le calcul de comparaison utilise toujours les entrées du
        # classeur (même jeu d'entrées que le VBA par construction) ; les
        # onglets ne servent qu'au contrôle de divergence demandé à l'utilisateur.
        def _tab_compare(self):
            f = ttk.Frame(self.nb)
            self.nb.add(f, text="Comparaison VBA")
            self.tab_compare = f
            top = ttk.Frame(f)
            top.pack(fill="x", padx=6, pady=4)
            ttk.Button(top, text="Comparer au classeur…", command=self.cmd_compare).pack(side="left", padx=3)
            ttk.Button(top, text="Choisir le classeur…", command=self.cmd_pick_workbook).pack(side="left", padx=3)
            ttk.Label(top, text="Tolérance").pack(side="left", padx=(14, 2))
            self.cmp_tol = tk.StringVar(value="1e-9")
            ttk.Entry(top, textvariable=self.cmp_tol, width=8).pack(side="left")
            self.auto_cmp = tk.BooleanVar(value=False)
            ttk.Checkbutton(top, text="Comparer automatiquement après chaque calcul",
                            variable=self.auto_cmp).pack(side="left", padx=14)
            self.cmp_wb_label = tk.StringVar(
                value=(f"Classeur de référence : {self.wb_path}" if self.wb_path else
                       "Classeur de référence : aucun — « Importer .xlsm… » ou « Choisir le classeur… » (les entrées du classeur sont copiées dans les onglets)"))
            ttk.Label(f, textvariable=self.cmp_wb_label, anchor="w", foreground="#555").pack(fill="x", padx=6)
            self.cmp_tree = ttk.Treeview(f, columns=("cells", "bad"), height=8)
            self.cmp_tree.heading("#0", text="Zone comparée (valeurs en cache du VBA)")
            self.cmp_tree.heading("cells", text="Cellules")
            self.cmp_tree.heading("bad", text="Écarts")
            self.cmp_tree.column("#0", width=340)
            self.cmp_tree.column("cells", width=110, anchor="e")
            self.cmp_tree.column("bad", width=110, anchor="e")
            self.cmp_tree.pack(fill="x", padx=6, pady=4)
            self.cmp_detail = tk.Text(f, wrap="word", font=("TkDefaultFont", 9))
            self.cmp_detail.pack(fill="both", expand=True, padx=6, pady=4)
            self.cmp_tree.tag_configure("ok", foreground="#070")
            self.cmp_tree.tag_configure("bad", foreground="#b00")

        def _import_workbook(self, p, jump=False):
            """Importe le classeur p : ses entrées sont copiées directement
            dans les onglets de l'interface (Train, Track, National, etc.)."""
            try:
                sc = load_workbook_scenario(p)
                self.load(sc)
            except ImportError:
                messagebox.showerror(APP_TITLE, "openpyxl est requis pour lire les classeurs .xlsm :\n\n"
                                              "pip install openpyxl")
                return False
            except Exception as exc:
                messagebox.showerror(APP_TITLE, f"Import du classeur impossible :\n{exc}")
                return False
            self.wb_path = p
            self.cmp_wb_label.set(f"Classeur de référence : {p}")
            if jump:
                self.nb.select(0)
            self.status.set(f"Entrées du classeur copiées dans les onglets : {os.path.basename(p)}")
            return True

        def cmd_pick_workbook(self):
            p = filedialog.askopenfilename(filetypes=[("Classeur ERA", "*.xlsm *.xlsx")])
            if p:
                self._import_workbook(p)

        def cmd_compare(self, auto=False):
            if not self.wb_path:
                self.cmd_pick_workbook()
            if not self.wb_path:
                return
            try:
                sc_wb = load_workbook_scenario(self.wb_path)
            except ImportError:
                messagebox.showerror(APP_TITLE, "openpyxl est requis pour lire les classeurs .xlsm :\n\n"
                                              "pip install openpyxl")
                return
            except Exception as exc:
                messagebox.showerror(APP_TITLE, f"Lecture du classeur impossible :\n{exc}")
                return
            try:
                tol = parse(self.cmp_tol.get() or "1e-9")
            except ValueError:
                messagebox.showerror(APP_TITLE, "Tolérance invalide (ex. 1e-9)")
                return
            # divergence onglets / classeur : confirmation avant de continuer
            try:
                sc_gui = self.collect()
                sc_gui.copy().normalise()
                sc_wb_n = sc_wb.copy()
                sc_wb_n.normalise()
                diffs = _scenario_diff(sc_gui, sc_wb_n)
            except Exception:
                diffs = []
            if diffs:
                msg = ("Les entrées des onglets divergent du classeur :\n\n"
                       + "\n".join(diffs[:15])
                       + (f"\n… ({len(diffs) - 15} autres)" if len(diffs) > 15 else "")
                       + "\n\nLa comparaison se fait toujours avec les entrées du classeur.\n"
                         "Si ces entrées ont changé, relancez la macro dans Excel "
                         "(Calculate the curves) puis enregistrez, sinon le cache VBA "
                         "du classeur est périmé.\n\nContinuer ?")
                if not messagebox.askyesno(APP_TITLE, msg):
                    return
            self.config(cursor="watch")
            self.status.set("Comparaison en cours…")
            self.update_idletasks()
            try:
                res_wb = run(sc_wb)
                if res_wb.aborted:
                    raise RuntimeError(res_wb.aborted)
                rep_cmp = compare_with_workbook(res_wb, self.wb_path, tol=tol)
            except Exception as exc:
                self.config(cursor="")
                messagebox.showerror(APP_TITLE, f"Comparaison impossible :\n{exc}\n\n"
                                              "Vérifiez que le classeur a bien été calculé par le VBA "
                                              "puis enregistré avec ces entrées.")
                self.status.set("Comparaison : erreur")
                return
            self.config(cursor="")
            self._show_compare(rep_cmp, res_wb)

        def _show_compare(self, rep_cmp, res_wb):
            t = self.cmp_tree
            t.delete(*t.get_children())
            self.cmp_detail.delete("1.0", "end")
            names = {"curves": "Feuille Curves (N2:AZ…)", "track": "Feuille Track (A36:F…)",
                     "deceleration": "Table de décélération", "pivots": "Pivots (feuille Calc)"}
            total, cells_total = 0, 0
            for k, v in rep_cmp.items():
                if "mismatches" not in v:
                    continue
                cells_total += v["cells"]
                total += v["mismatches"]
                iid = t.insert("", "end", text=names.get(k, k), values=(v["cells"], v["mismatches"]),
                               tags=("bad",) if v["mismatches"] else ("ok",))
                for (r, c, xv, pv) in v["examples"]:
                    t.insert(iid, "end", text=f"ligne {r}, colonne {c}", values=(xv, pv), tags=("bad",))
            d = self.cmp_detail
            d.insert("end", f"Classeur : {self.wb_path}\n")
            d.insert("end", f"Cellules comparées : {cells_total}    écarts : {total}\n\n")
            if cells_total == 0:
                d.insert("end", "Aucune valeur en cache dans le classeur.\n"
                                "Ouvrez-le dans Excel, lancez « Calculate the curves », enregistrez, "
                                "puis relancez la comparaison.\n\n")
            s = rep_cmp["summary"]
            labels = ("V_linespeed", "perturbation", "indication", "permitted", "warning",
                      "sbi", "ebi", "start_rsm", "release_speed")
            d.insert("end", "Points caractéristiques (ligne 38 du classeur) — Excel / Python :\n")
            for name, xe, pe in zip(labels, s["excel"], s["python"]):
                d.insert("end", f"  {name:13s}  {xe!r:24}  {pe!r}\n")
            if s["match"]:
                d.insert("end", "\nRésumé : CONFORME au VBA.\n")
            else:
                d.insert("end", "\nRésumé : écarts sur les points caractéristiques.\n")
            for w in res_wb.warnings:
                d.insert("end", f"  • {w}\n")
            if cells_total == 0:
                self.status.set("Comparaison : classeur sans valeurs en cache")
            elif total == 0 and s["match"]:
                self.status.set(f"Comparaison : conforme au VBA ({cells_total} cellules)")
            else:
                self.status.set(f"Comparaison : {total} écarts de cellules"
                                + ("" if s["match"] else " + écarts au résumé"))
            self.nb.select(self.tab_compare)

        # ====================================================== scenario <-> UI
        def load(self, sc: Scenario):
            self._building = True
            t, tr, nv, fv, lb, gb = sc.train, sc.track, sc.national, sc.fixed, sc.lambda_brake, sc.gamma_brake
            self.train_type.set(t.train_type)
            self.brake_position.set(t.brake_position)
            self.T_tco.set(t.T_traction_cut_off)
            self.sb_int.set(t.service_brake_interface)
            self.tco_int.set(t.traction_cut_off_interface)
            self.add_brake.set(t.special_brake_indep_adhesion)
            self.sci.set(t.speed_inaccuracy)
            self.sci_pct.set(t.speed_inaccuracy_pct)
            self.odo.set("subset041" if (t.odometer_abs, t.odometer_rel_pct) == (5, 5) else "fixed")
            self.odo_abs.set(t.odometer_abs)
            self.odo_rel.set(t.odometer_rel_pct)
            self.sm.set(t.supervised_manoeuvre)
            self.safe_len.set(t.safe_consist_length)
            self.orient.set("same" if t.engine_orientation_same else "opposite")
            self.rear.set([[t.consist_rear_min, t.consist_rear_nom, t.consist_rear_max]])
            self.front.set([[t.consist_front_min, t.consist_front_nom, t.consist_front_max]])
            self.train_length.set(t.train_length)
            self.rot.set("unknown" if t.rotating_mass_pct is None else "value")
            self.rot_pct.set(t.rotating_mass_pct)
            self.antenna.set(t.antenna_to_front)
            self.engine_len.set(t.engine_length)
            self.acc.set(t.A_est1)
            self.target.set(tr.target)
            self.V_target.set(tr.V_target)
            self.d_target.set(tr.d_target)
            self.V_init.set(tr.V_initial)
            self.d_svl.set(tr.d_svl)
            self.rs_mode.set(tr.release_speed)
            self.rs_value.set(tr.fixed_release_speed)
            self.level.set(tr.level)
            self.inhib.set(tr.brake_inhibition)
            self.inhib_start.set(tr.brake_inhib_start)
            self.redadh.set(tr.reduced_adhesion)
            self.redadh_start.set(tr.reduced_adh_start)
            self.redadh_end.set(tr.reduced_adh_end)
            self.balises.set(tr.balises)
            rows = tr.gradient
            self.gradient.set([[rows[i][0], rows[i + 1][0] if i + 1 < len(rows) else "", rows[i][1]]
                               for i in range(0, len(rows), 2)])
            self.q_sbtsm.set(nv.Q_NVSBTSMPERM)
            self.q_gui.set(nv.Q_NVGUIPERM)
            self.q_inhsmic.set(nv.Q_NVINHSMICPERM)
            self.a_red1.set(nv.A_NVMAXREDADH1)
            self.a_red2.set(nv.A_NVMAXREDADH2)
            self.a_red3.set(nv.A_NVMAXREDADH3)
            self.m_avadh.set(nv.M_NVAVADH)
            for n, fld in self.fixed.items():
                fld.set(getattr(fv, n))
            self.lam.set(lb.lambda_pct)
            self.cm.set("cm" if lb.conversion_model else "user")
            self.tbs_user.set(lb.T_brake_service_user)
            self.tbs_react_user.set(lb.T_brake_service_react_user)
            self.cm_max.set(lb.conversion_model_max_speed)
            self.a_sb01.set(lb.A_SB01)
            self.a_sb12.set(lb.A_SB12)
            for k in range(3):
                self.ns_P[k].set(lb.normal_service_P[k])
                self.ns_G[k].set(lb.normal_service_G[k])
            self.kv_freight.set(lb.kv_freight)
            self.kv_pass.set([[v, a, b] for v, a, b in zip(lb.kv_passenger_speeds, lb.kv_passenger_a, lb.kv_passenger_b)])
            self.kr.set(lb.kr)
            self.a_p12.set(lb.A_NVP12)
            self.a_p23.set(lb.A_NVP23)
            self.kt.set(lb.Kt_int)
            self.kn_plus.set(lb.kn_plus)
            self.kn_minus.set(lb.kn_minus)
            for comb in ("comb1", "comb2"):
                d = getattr(gb, comb)
                for key, _ in self.GTABLES:
                    self.gt[(comb, key)].set(d[key])
                for key, _ in self.GTIMES:
                    self.gtimes[(comb, key)].set(d[key])
            self.ebcl.set(gb.ebcl)
            self.kdry1.set([gb.kdry_by_ebcl.get(i, {}).get("comb1", [""] * 7) for i in range(10)])
            self.kdry2.set([gb.kdry_by_ebcl.get(i, {}).get("comb2", [""] * 7) for i in range(10)])
            self._building = False
            self.refresh()

        def collect(self) -> Scenario:
            sc = Scenario.default()
            t, tr, nv, fv, lb, gb = sc.train, sc.track, sc.national, sc.fixed, sc.lambda_brake, sc.gamma_brake
            t.train_type = self.train_type.get()
            t.brake_position = self.brake_position.get()
            t.T_traction_cut_off = self.T_tco.get()
            t.service_brake_interface = self.sb_int.get()
            t.traction_cut_off_interface = self.tco_int.get()
            t.special_brake_indep_adhesion = self.add_brake.get()
            t.speed_inaccuracy = self.sci.get()
            t.speed_inaccuracy_pct = self.sci_pct.get()
            if self.odo.get() == "subset041":
                t.odometer_abs, t.odometer_rel_pct = 5.0, 5.0
            else:
                t.odometer_abs, t.odometer_rel_pct = self.odo_abs.get(), self.odo_rel.get()
            t.supervised_manoeuvre = self.sm.get()
            t.safe_consist_length = self.safe_len.get()
            t.engine_orientation_same = self.orient.get() == "same"
            (t.consist_rear_min, t.consist_rear_nom, t.consist_rear_max), = self.rear.get()
            (t.consist_front_min, t.consist_front_nom, t.consist_front_max), = self.front.get()
            t.train_length = self.train_length.get()
            t.rotating_mass_pct = None if self.rot.get() == "unknown" else self.rot_pct.get()
            if self.rot.get() == "value" and t.rotating_mass_pct is None:
                raise ValueError("Nominal rotating mass : valeur manquante")
            t.antenna_to_front = self.antenna.get()
            t.engine_length = self.engine_len.get()
            t.A_est1 = self.acc.get()
            tr.target = self.target.get()
            tr.V_target = self.V_target.get()
            tr.d_target = self.d_target.get()
            tr.V_initial = self.V_init.get()
            tr.d_svl = self.d_svl.get()
            tr.release_speed = self.rs_mode.get()
            tr.fixed_release_speed = self.rs_value.get()
            tr.level = int(self.level.get())
            tr.brake_inhibition = self.inhib.get()
            tr.brake_inhib_start = self.inhib_start.get()
            tr.reduced_adhesion = self.redadh.get()
            tr.reduced_adh_start = self.redadh_start.get()
            tr.reduced_adh_end = self.redadh_end.get()
            tr.balises = sorted(self.balises.get(skip_empty=True))
            if not tr.balises:
                raise ValueError("Au moins une balise de relocalisation est nécessaire (balise 0 à l'origine)")
            segs = self.gradient.get(skip_empty=True)
            if not segs:
                tr.gradient = []
            else:
                for i in range(len(segs) - 1):
                    if segs[i][1] != segs[i + 1][0]:
                        raise ValueError(f"Gradient profile : la fin du segment {i + 1} ({fmt(segs[i][1])} m) doit être "
                                         f"le début du segment {i + 2} ({fmt(segs[i + 1][0])} m)")
                tr.gradient = gradient_rows([(s[0], s[2]) for s in segs], segs[-1][1])
            nv.Q_NVSBTSMPERM = self.q_sbtsm.get()
            nv.Q_NVGUIPERM = self.q_gui.get()
            nv.Q_NVINHSMICPERM = self.q_inhsmic.get()
            nv.A_NVMAXREDADH1, nv.A_NVMAXREDADH2, nv.A_NVMAXREDADH3 = self.a_red1.get(), self.a_red2.get(), self.a_red3.get()
            nv.M_NVAVADH = self.m_avadh.get()
            for n, fld in self.fixed.items():
                setattr(fv, n, fld.get())
            lb.lambda_pct = self.lam.get()
            lb.conversion_model = self.cm.get() == "cm"
            lb.T_brake_service_user = self.tbs_user.get()
            lb.T_brake_service_react_user = self.tbs_react_user.get()
            lb.conversion_model_max_speed = self.cm_max.get()
            lb.A_SB01, lb.A_SB12 = self.a_sb01.get(), self.a_sb12.get()
            lb.normal_service_P = [t_.get() for t_ in self.ns_P]
            lb.normal_service_G = [t_.get() for t_ in self.ns_G]
            lb.kv_freight = self.kv_freight.get()
            kvp = self.kv_pass.get()
            lb.kv_passenger_speeds = [r[0] for r in kvp]
            lb.kv_passenger_a = [r[1] for r in kvp]
            lb.kv_passenger_b = [r[2] for r in kvp]
            lb.kr = self.kr.get()
            lb.A_NVP12, lb.A_NVP23, lb.Kt_int = self.a_p12.get(), self.a_p23.get(), self.kt.get()
            lb.kn_plus, lb.kn_minus = self.kn_plus.get(), self.kn_minus.get()
            for comb in ("comb1", "comb2"):
                d = getattr(gb, comb)
                for key, _ in self.GTABLES:
                    d[key] = self.gt[(comb, key)].get()
                for key, _ in self.GTIMES:
                    d[key] = self.gtimes[(comb, key)].get()
            gb.ebcl = int(self.ebcl.get())
            k1, k2 = self.kdry1.get(), self.kdry2.get()
            gb.kdry_by_ebcl = {i: {"comb1": k1[i], "comb2": k2[i]} for i in range(10)}
            return sc

        # ============================================ enabling rules (event handlers)
        def refresh(self):
            if self._building or getattr(self, "_in_refresh", False):
                return
            self._in_refresh = True
            try:
                self._refresh()
            finally:
                self._in_refresh = False

        # Règles d'activation des champs = handlers d'événements des feuilles du
        # classeur v5.1 (Sheet1/Sheet4/Sheet11) ; contraintes d'entrées SUBSET-026 §3.13.2.
        def _refresh(self):
            gamma = self.train_type.get() == "gamma"
            pos = self.brake_position.get()
            sm = self.sm.get()
            eoa = self.target.get() == "EOA_SvL"
            # Train (main) — Sheet1 events
            self.add_brake.enable(pos == "Passenger in P")
            inhsmic = self.q_inhsmic.get()
            self.sci.enable(not inhsmic)
            self.sci_pct.enable(not inhsmic and self.sci.get() == "user")
            odo_fixed = self.odo.get() == "fixed"
            self.odo_abs.enable(odo_fixed)
            self.odo_rel.enable(odo_fixed)
            if not odo_fixed:
                self.odo_abs.set(5)
                self.odo_rel.set(5)
            if sm and not self.safe_len.get():
                self.safe_len.set(True)
            self.safe_len.enable(not sm)
            if not sm and self.orient.get() != "same":
                self.orient.set("same")
            self.orient.enable(sm)
            safe = self.safe_len.get()
            self.rear.enable(safe)
            self.front.enable(sm)
            self.train_length.enable(not safe)
            self.rot_pct.enable(self.rot.get() == "value")
            self.sb_int.enable(self.q_sbtsm.get())
            try:
                (rmin, rnom, rmax), = self.rear.get()
                (fmin, fnom, fmax), = self.front.get()
                L = (rmax + fmax) if safe else parse(self.train_length.var.get())
                Lmax = 4095 if gamma else (900 if pos == "Passenger in P" else 1500)
                txt = f"Overall train length (D26) = {fmt(L)} m   –   maximum (D24) = {Lmax} m"
                if L > Lmax:
                    txt += "   ⚠ TOO LONG OVERALL TRAIN LENGTH"
                if rmin > rnom or rmax < rnom or fmin > fnom or fmax < fnom:
                    txt += "   ⚠ INVALID MIN/MAX CONSIST LENGTH"
                self.len_info.set(txt)
            except ValueError:
                self.len_info.set("")
            # Track — Sheet4 events
            self.V_target.enable(not eoa)
            if eoa:
                self.V_target.set(0)
            self.d_svl.enable(eoa)
            self.rs_mode.enable(eoa)
            self.rs_value.enable(eoa and self.rs_mode.get() == "fixed")
            onboard = eoa and self.rs_mode.get() == "onboard"
            self.level.enable(onboard, only=["2"])
            self.level.enable(onboard and not sm, only=["1"])
            if onboard and sm and self.level.get() == "1":
                self.level.set(2)                             # CR1367
            self.inhib.enable(gamma)
            if not gamma and self.inhib.get():
                self.inhib.set(False)
            self.inhib_start.enable(gamma and self.inhib.get())
            self.redadh_start.enable(self.redadh.get())
            self.redadh_end.enable(self.redadh.get())
            # National values
            self.m_avadh.enable(gamma)
            try:
                self.ebcl_info.set(f"M_NVEBCL = {M_NVEBCL(int(self.ebcl.get())):.7g} %  (from the EBCL selected in "
                                   "'Brake parameters (gamma)')" if gamma else "M_NVEBCL : gamma trains only")
            except ValueError:
                pass
            # tabs shown according to the train type (Sheet1.lambda_Change)
            for tab in (self.tab_lambda, self.tab_corr):
                self.nb.tab(tab, state="hidden" if gamma else "normal")
            self.nb.tab(self.tab_gamma, state="normal" if gamma else "hidden")
            # Brake parameters (lambda) — ShorterValue
            user = self.cm.get() == "user"
            self.tbs_user.enable(user)
            self.tbs_react_user.enable(user)
            self.update_lambda_info()

        def update_lambda_info(self):
            self.lam_info.configure(state="normal")
            self.lam_info.delete("1.0", "end")
            try:
                sc = self.collect()
                lp = LambdaParameters(sc)
                L = sc.train.overall_length
                lines = [
                    f"λ (F3) = {fmt(lp.lambda1)} %   λ service (F4) = {fmt(lp.lambda2)} %   overall length = {fmt(L)} m",
                    f"V_lim EB (F5) = {lp.V_lim_eb:.3f} km/h   V_lim SB (F6) = {lp.V_lim_sb:.3f} km/h   kto (F7) = {lp.kto:g}",
                    f"T_brake_emergency cm0/cmt (F8/F9) = {lp.T_be_cm0:.3f} / {lp.T_be_cmt:.3f} s   → used (F12) = "
                    f"{lp.T_brake_emergency:.3f} s  × Kt_int",
                    f"T_brake_service cm0/cmt (F10/F11) = {lp.T_bs_cm0:.3f} / {lp.T_bs_cmt:.3f} s   → used (F13) = "
                    f"{fmt(lp.T_brake_service)} s",
                    f"T_brake_emergency_react (F15) = {lp.T_brake_emergency_react:g} s   "
                    f"T_brake_service_react (F16) = {fmt(lp.T_brake_service_react)} s",
                    f"A_brake_emergency max = {lp.A_ebmax:.4f} m/s²   Kv_int set = {lp.kv_set}   "
                    f"normal service table = A_brake_normal_service_{lp.normal_service_table_index}",
                ]
                self.lam_info.insert("1.0", "\n".join(lines))
            except Exception as exc:                          # incomplete entry while typing
                self.lam_info.insert("1.0", f"(computed values unavailable: {exc})")
            self.lam_info.configure(state="disabled")

        # ============================================================== commands
        def cmd_new(self):
            self.path = None
            self.load(Scenario.default())
            self.status.set("Valeurs enregistrées dans era_braking_curves_tool_v5.1.xlsm")

        def cmd_open(self):
            p = filedialog.askopenfilename(filetypes=[("Scénario JSON", "*.json")])
            if p:
                try:
                    self.load(Scenario.from_json(p))
                    self.path = p
                    self.status.set(f"Ouvert : {p}")
                except Exception as exc:
                    messagebox.showerror(APP_TITLE, f"Lecture impossible :\n{exc}")

        # Import des entrées d'un classeur ERA existant (.xlsm, section 10).
        def cmd_import(self):
            p = filedialog.askopenfilename(filetypes=[("Classeur ERA", "*.xlsm *.xlsx")])
            if p:
                self._import_workbook(p, jump=True)

        def cmd_save(self):
            try:
                sc = self.collect()
            except ValueError as exc:
                messagebox.showerror(APP_TITLE, str(exc))
                return
            p = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("Scénario JSON", "*.json")],
                                             initialfile=os.path.basename(self.path) if self.path else "scenario.json")
            if p:
                sc.to_json(p)
                self.path = p
                self.status.set(f"Enregistré : {p}")

        def cmd_calculate(self):
            try:
                sc = self.collect()
                sc.copy().normalise()
            except ValueError as exc:
                messagebox.showerror(APP_TITLE, str(exc))
                return
            self.config(cursor="watch")
            self.status.set("Calcul en cours…")
            self.update_idletasks()
            try:
                res = run(sc)
            except Exception as exc:
                self.config(cursor="")
                messagebox.showerror(APP_TITLE, f"Erreur d'exécution (le VBA aurait aussi échoué) :\n{exc}")
                self.status.set("Erreur")
                return
            self.config(cursor="")
            self.result = res
            self.show_result()
            self.nb.select(self.tab_results)
            if self.auto_cmp.get() and self.wb_path:
                self.cmd_compare(auto=True)

        def show_result(self):
            res = self.result
            self.tree.delete(*self.tree.get_children())
            s = res.summary or {}
            labels = [("V_linespeed", "Initial speed (km/h)"), ("perturbation", "Perturbation"),
                      ("indication", "Indication"), ("permitted", "Permitted"), ("warning", "Warning"),
                      ("sbi", "SBI"), ("ebi", "EBI"), ("start_rsm", "StartRSM"), ("release_speed", "Release speed (km/h)")]
            for k, lab in labels:
                v = s.get(k, "")
                self.tree.insert("", "end", text=lab, values=(f"{v:.2f}" if isinstance(v, float) else v,))
            self.msg.delete("1.0", "end")
            if res.aborted:
                self.msg.insert("end", f"⛔ {res.aborted}\n\n")
            for w in res.warnings:
                self.msg.insert("end", f"• {w}\n")
            if not res.aborted and not res.warnings:
                self.msg.insert("end", "Calculation completed")
            self.status.set("Calculation aborted" if res.aborted else "Calculation completed")
            self.draw()

        def draw(self):
            if self.canvas is None or self.result is None:
                return
            self.ax.clear()
            self.result.draw(self.ax, curves={n for n, v in self.show.items() if v.get()})
            self.fig.tight_layout()
            self.canvas.draw_idle()

        def cmd_csv(self):
            if not self.result:
                return
            p = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV", "*.csv")],
                                             initialfile="curves.csv")
            if p:
                self.result.to_csv(p)
                self.status.set(f"Courbes exportées : {p}")

        def cmd_png(self):
            if not self.result:
                return
            p = filedialog.asksaveasfilename(defaultextension=".png", filetypes=[("PNG", "*.png"), ("PDF", "*.pdf"),
                                                                                 ("SVG", "*.svg")],
                                             initialfile="curves.png")
            if p:
                self.fig.savefig(p, dpi=130)
                self.status.set(f"Graphique exporté : {p}")


    def gui_main(scenario=None, wb_path=None):
        App(scenario, wb_path).mainloop()



else:
    def gui_main(scenario=None, wb_path=None):
        raise SystemExit("tkinter non disponible sur ce système : interface graphique impossible ; "
                         "utiliser la ligne de commande (cf. docstring d'en-tête).")

# ---------------------------------------------------------------------------
# Scénario par défaut: entrées enregistrées de era_braking_curves_tool_v5.1.xlsm
# (inclus les tables Kdry_rst(V, EBCL) des 10 niveaux de confiance §3.13.2.3.7.8)
# ------------------------------------------------------------------------------
_DEFAULT_SCENARIO_JSON = """{"train":{"train_type":"lambda","brake_position":"Freight in P","T_traction_cut_off":2,"service_brake_interface":true,"traction_cut_off_interface":true,"special_brake_indep_adhesion":false,"speed_inaccuracy":"subset041","speed_inaccuracy_pct":null,"odometer_abs":0,"odometer_rel_pct":0,"supervised_manoeuvre":true,"safe_consist_length":true,"engine_orientation_same":false,"consist_rear_min":400,"consist_rear_nom":400,"consist_rear_max":400,"consist_front_min":0,"consist_front_nom":0,"consist_front_max":0,"train_length":200,"rotating_mass_pct":10,"antenna_to_front":12.5,"engine_length":25,"A_est1":0},"track":{"target":"LOA_MRSP","V_target":40,"d_target":6000,"V_initial":160,"d_svl":0,"release_speed":"fixed","fixed_release_speed":0,"level":2,"balises":[[0,0],[2000,0],[3000,0],[4000,0]],"gradient":[[0,0],[2000,0],[2000,-5],[4000,-5],[4000,10],[6055,10]],"brake_inhibition":false,"brake_inhib_start":2000,"reduced_adhesion":false,"reduced_adh_start":4500,"reduced_adh_end":6500},"national":{"Q_NVSBTSMPERM":true,"Q_NVGUIPERM":true,"Q_NVINHSMICPERM":false,"A_NVMAXREDADH1":0.2,"A_NVMAXREDADH2":0.2,"A_NVMAXREDADH3":0.2,"M_NVAVADH":0},"fixed":{"dV_ebi_min":7.5,"dV_ebi_max":15,"V_ebi_min":110,"V_ebi_max":210,"dV_sbi_min":5.5,"dV_sbi_max":10,"V_sbi_min":110,"V_sbi_max":210,"dV_warning_min":4,"dV_warning_max":5,"V_warning_min":110,"V_warning_max":140,"T_warning":2,"T_driver":4,"T_41":1,"M_rotating_max":15,"M_rotating_min":2,"g":9.81},"lambda_brake":{"lambda_pct":90,"conversion_model":true,"T_brake_service_user":null,"T_brake_service_react_user":null,"conversion_model_max_speed":200,"A_SB01":1.2,"A_SB12":1.3,"normal_service_P":[[[0,0.4],[40,0.4],[40.001,0.3],[160,0.3],[160.001,0.3],[160,0.3],[160.001,0.35],[160,0.35],[160.001,0.35],[160,0.35],[160.001,0.35],[180,0.35],[180.001,0.35],[200,0.35]],[[0,1],[60,1],[60.001,0.6],[160,0.6],[160.001,1],[160,1],[160.001,1],[160,1],[160.001,1],[160,1],[160.001,1],[160,1],[160.001,1],[200,1]],[[0,0.5],[80,0.5],[80.001,0.3],[160,0.3],[160.001,1],[160,1],[160.001,1],[160,1],[160.001,1],[160,1],[160.001,1],[160,1],[160.001,1],[200,1]]],"normal_service_G":[[[0,1],[50,1],[50.001,0.7],[160,0.7],[160.001,0.2],[180,0.2],[180.001,1],[180,1],[180.001,0.5],[180,0.5],[180.001,1],[180,1],[180.001,1],[200,1]],[[0,1],[70,1],[70.001,0.5],[160,0.5],[160.001,1],[160,1],[160.001,1],[160,1],[160.001,1],[160,1],[160.001,1],[160,1],[160.001,1],[200,1]],[[0,0.5],[80,0.5],[80.001,0.3],[90,0.3],[90.001,1],[120,1],[120.001,1],[160,1],[160.001,1],[160,1],[160.001,1],[160,1],[160.001,1],[200,1]]],"kv_freight":[[0,0.7],[200,0.7],[200.001,0.7],[200,0.7],[200.001,0.7],[200,0.7],[200.001,0.7],[200,0.7],[200.001,0.7],[200,0.7]],"kv_passenger_speeds":[0,25,25.001,30,30.001,100,100.001,160,160.001,200],"kv_passenger_a":[0.7,0.7,0.9,0.9,0.7,0.7,0.7,0.7,0.7,0.7],"kv_passenger_b":[0.7,0.7,0.7,0.7,0.7,0.7,0.7,0.7,0.7,0.7],"kr":[[0,0.9],[150,0.9],[150.001,0.9],[300,0.9],[300.001,0.9],[600,0.9],[600.001,0.9],[600,0.9],[600.001,0.9],[900,0.9]],"A_NVP12":1,"A_NVP23":1.2,"Kt_int":1.1,"kn_plus":[[0,0],[25,0],[25.001,0],[55,0],[55.001,0],[100,0],[100.001,0],[115,0],[115.001,0],[200,0]],"kn_minus":[[0,0],[25,0],[25.001,0],[55,0],[55.001,0],[100,0],[100.001,0],[115,0],[115.001,0],[200,0]]},"gamma_brake":{"comb1":{"A_brake_emergency":[[0,0.81],[40,0.81],[40.001,0.72],[80,0.72],[80.001,0.66],[100,0.66],[100.001,0.64],[155,0.64],[155.001,0.44],[180,0.44],[180.001,0.48],[250,0.48],[250.001,0.4],[300,0.4]],"Kwet_rst":[[0,0.95],[40,0.95],[40.001,0.95],[80,0.95],[80.001,0.95],[100,0.95],[100.001,0.95],[155,0.95],[155.001,0.95],[180,0.95],[180.001,0.95],[250,0.95],[250.001,0.95],[300,0.95]],"T_brake_emergency":2.5,"A_brake_service":[[0,0.81],[40,0.81],[40.001,0.72],[80,0.72],[80.001,0.66],[100,0.66],[100.001,0.65],[155,0.65],[155.001,0.45],[180,0.45],[180.001,0.49],[250,0.49],[250.001,0.41],[300,0.41]],"T_brake_service":4.8,"A_brake_normal_service":[[0,0.3],[150,0.3],[150.001,0.35],[280,0.35],[280.001,0.4],[280,0.4],[280.001,0.4],[280,0.4],[280.001,0.4],[280,0.4],[280.001,0.4],[280,0.4],[280.001,0.4],[300,0.4]],"T_brake_emergency_react":1,"T_brake_service_react":1.2},"comb2":{"A_brake_emergency":[[0,0.72],[40,0.72],[40.001,0.72],[80,0.72],[80.001,0.66],[100,0.66],[100.001,0.64],[155,0.64],[155.001,0.44],[180,0.44],[180.001,0.48],[250,0.48],[250.001,0.4],[300,0.4]],"Kwet_rst":[[0,0.95],[40,0.95],[40.001,0.95],[80,0.95],[80.001,0.95],[100,0.95],[100.001,0.95],[155,0.95],[155.001,0.95],[180,0.95],[180.001,0.95],[250,0.95],[250.001,0.95],[300,0.95]],"T_brake_emergency":2.5,"A_brake_service":[[0,0.81],[40,0.81],[40.001,0.72],[80,0.72],[80.001,0.66],[100,0.66],[100.001,0.65],[155,0.65],[155.001,0.45],[180,0.45],[180.001,0.49],[250,0.49],[250.001,0.41],[300,0.41]],"T_brake_service":4.8,"A_brake_normal_service":[[0,0.3],[150,0.3],[150.001,0.35],[280,0.35],[280.001,0.4],[280,0.4],[280.001,0.4],[280,0.4],[280.001,0.4],[280,0.4],[280.001,0.4],[280,0.4],[280.001,0.4],[300,0.4]],"T_brake_emergency_react":1,"T_brake_service_react":1.2},"ebcl":4,"kdry_by_ebcl":{"0":{"comb1":[1,1,1,1,1,1,1],"comb2":[1,1,1,1,1,1,1]},"1":{"comb1":[0.9,0.9,0.9,0.9,0.9,0.9,0.9],"comb2":[0.9,0.9,0.9,0.9,0.9,0.9,0.9]},"2":{"comb1":[0.85,0.85,0.85,0.85,0.85,0.85,0.85],"comb2":[0.85,0.85,0.85,0.85,0.85,0.85,0.85]},"3":{"comb1":[0.8,0.8,0.8,0.8,0.8,0.8,0.8],"comb2":[0.8,0.8,0.8,0.8,0.8,0.8,0.8]},"4":{"comb1":[0.75,0.75,0.75,0.75,0.75,0.75,0.75],"comb2":[0.75,0.75,0.75,0.75,0.75,0.75,0.75]},"5":{"comb1":[0.7,0.7,0.7,0.7,0.7,0.7,0.7],"comb2":[0.7,0.7,0.7,0.7,0.7,0.7,0.7]},"6":{"comb1":[0.6,0.6,0.6,0.6,0.6,0.6,0.6],"comb2":[0.6,0.6,0.6,0.6,0.6,0.6,0.6]},"7":{"comb1":[0.45,0.45,0.45,0.45,0.45,0.45,0.45],"comb2":[0.45,0.45,0.45,0.45,0.45,0.45,0.45]},"8":{"comb1":[0.4,0.4,0.4,0.4,0.4,0.4,0.4],"comb2":[0.4,0.4,0.4,0.4,0.4,0.4,0.4]},"9":{"comb1":[0.4,0.4,0.4,0.4,0.4,0.4,0.4],"comb2":[0.4,0.4,0.4,0.4,0.4,0.4,0.4]}}}}"""



