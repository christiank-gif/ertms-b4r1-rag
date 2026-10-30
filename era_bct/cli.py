from __future__ import annotations

import argparse
import json
import sys

from .compare import compare_with_workbook
from .engine import run
from .model import Scenario
from .workbook import load_workbook_scenario
from .gui import gui_main


# SECTION 12/13 — INTERFACE EN LIGNE DE COMMANDE.
# ==========================================================================

"""Command line:  python era_bct.py INPUT [--csv F] [--plot F] [--json F] [--compare]

INPUT is a scenario .json or an ERA Braking Curves Tool workbook (.xlsm), whose
inputs (cells and ActiveX controls) are read.  --compare checks the Python
results against the values cached in the workbook by the VBA macro.
"""
import argparse
import json
import sys



def main(argv=None):
    ap = argparse.ArgumentParser(prog="era_bct", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("input", nargs="?", help="scenario .json or ERA workbook .xlsm (no file/options: opens the graphical interface)")
    ap.add_argument("--gui", action="store_true", help="open the graphical interface (default when no file and no option is given)")
    ap.add_argument("--csv", help="write the curve table (Curves sheet columns N:AZ)")
    ap.add_argument("--plot", help="write a speed/distance plot (png, svg, pdf)")
    ap.add_argument("--json", help="write the scenario read from the input as json")
    ap.add_argument("--compare", action="store_true", help="compare with the results cached in the .xlsm")
    ap.add_argument("--tol", type=float, default=1e-9)
    a = ap.parse_args(argv)
    # Sans fichier ni option : l'outil s'utilise par son interface graphique.
    # Dans le GUI, les entrées se saisissent dans les onglets ou se lisent
    # depuis un classeur ERA (« Importer .xlsm… ») ou un scénario JSON.
    gui_mode = a.gui or (a.input is None and not (a.csv or a.plot or a.json or a.compare))
    if gui_mode:
        sc, wb_path = None, None
        if a.input:
            if a.input.lower().endswith(".json"):
                sc = Scenario.from_json(a.input)
            elif a.input.lower().endswith((".xlsm", ".xlsx")):
                sc = load_workbook_scenario(a.input)
                wb_path = a.input
        gui_main(sc, wb_path)
        return 0
    if a.input is None:
        sc = Scenario.default()
    elif a.input.lower().endswith((".xlsm", ".xlsx")):
        sc = load_workbook_scenario(a.input)
    else:
        sc = Scenario.from_json(a.input)
    if a.json:
        sc.to_json(a.json)
    res = run(sc)
    for w in res.warnings:
        print("warning:", w)
    if res.aborted:
        print("ABORTED:", res.aborted)
    print(json.dumps(res.summary, indent=1))
    if a.csv:
        res.to_csv(a.csv)
    if a.plot:
        res.plot(a.plot)
    if a.compare:
        rep = compare_with_workbook(res, a.input, tol=a.tol)
        ok = all(v.get("mismatches", 0) == 0 for v in rep.values() if "mismatches" in v) and rep["summary"]["match"]
        for k, v in rep.items():
            if "mismatches" in v:
                print(f"{k:13s} {v['cells']:7d} cells  {v['mismatches']:5d} mismatches")
                for ex in v["examples"][:5]:
                    print("      row %d col %d  excel=%r python=%r" % ex)
        print("summary match:", rep["summary"]["match"])
        return 0 if ok else 1
    return 0 if not res.aborted else 2





# ==========================================================================
