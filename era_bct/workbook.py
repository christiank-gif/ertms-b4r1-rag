from __future__ import annotations

import os
import struct
import zipfile
from xml.etree import ElementTree as ET

from .model import (Scenario, Train, Track, NationalValues, FixedValues, LambdaBrake, GammaBrake)


# SECTION 10/13 — LECTURE DES ENTRÉES D'UN CLASSEUR .xlsm (cellules + contrôles ActiveX). Aucune clause SRS : entrée/sortie.
# ==========================================================================

"""Reads the inputs of an ERA Braking Curves Tool workbook (.xlsm) into a Scenario.

Cell values are taken from the cached results (``data_only``) and the states
of the ActiveX option buttons / check boxes / scroll bars are decoded from the
persisted MS-Forms binary streams (xl/activeX/*.bin).
"""

import os
import struct
import zipfile
from xml.etree import ElementTree as ET


_NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
       "r": "http://schemas.openxmlformats.org/officeDocument/2006/relationships"}
_RID = "{%s}id" % _NS["r"]

_MORPH_FIELDS = [(0, 4, "Various"), (1, 4, "BackColor"), (2, 4, "ForeColor"), (3, 4, "MaxLength"),
                 (4, 1, "BorderStyle"), (5, 1, "ScrollBars"), (6, 1, "DisplayStyle"), (7, 1, "MousePointer"),
                 (9, 2, "PasswordChar"), (10, 4, "ListWidth"), (11, 2, "BoundColumn"), (12, 2, "TextColumn"),
                 (13, 2, "ColumnCount"), (14, 2, "ListRows"), (15, 2, "cColumnInfo"), (16, 1, "MatchEntry"),
                 (17, 1, "ListStyle"), (18, 1, "ShowDropButtonWhen"), (20, 1, "DropButtonStyle"),
                 (21, 1, "MultiSelect"), (22, 4, "Value"), (23, 4, "Caption"), (24, 4, "PicturePosition"),
                 (25, 4, "BorderColor"), (26, 4, "SpecialEffect"), (27, 2, "MouseIcon"), (28, 2, "Picture"),
                 (29, 2, "Accelerator"), (32, 4, "GroupName")]
_SCROLL_FIELDS = [(0, 4, "ForeColor"), (1, 4, "BackColor"), (2, 4, "Various"), (4, 1, "MousePointer"),
                  (5, 4, "Min"), (6, 4, "Max"), (7, 4, "Position")]


def _morph(data: bytes) -> dict:
    o = 20
    m1, m2 = struct.unpack_from("<II", data, o)
    mask = m1 | (m2 << 32)
    o += 8
    start, vals = o, {}
    for bit, size, name in _MORPH_FIELDS:
        if mask >> bit & 1:
            while (o - start) % size:
                o += 1
            vals[name] = int.from_bytes(data[o:o + size], "little")
            o += size
    while (o - start) % 4:
        o += 1
    extra = o
    if mask >> 8 & 1:
        o += 8
    out = {}
    for name in ("Value", "Caption", "GroupName"):
        if name in vals:
            n, compressed = vals[name] & 0x7FFFFFFF, vals[name] >> 31
            out[name] = data[o:o + n].decode("latin-1" if compressed else "utf-16-le")
            o += n
            while (o - extra) % 4:
                o += 1
    return out


def _scroll(data: bytes) -> dict:
    o = 20
    mask, = struct.unpack_from("<I", data, o)
    o += 4
    start, vals = o, {}
    for bit, size, name in _SCROLL_FIELDS:
        if mask >> bit & 1:
            while (o - start) % size:
                o += 1
            vals[name] = struct.unpack_from({4: "<i", 1: "<b"}[size], data, o)[0]
            o += size
    return vals


# Décode l'état des contrôles ActiveX (boutons d'option, cases à cocher) persisté
# dans les flux binaires MS-Forms du .xlsm.
def read_controls(path) -> dict:
    """Returns {sheet name: {control name: state dict}}."""
    out: dict = {}
    with zipfile.ZipFile(path) as z:
        def xml(p):
            return ET.fromstring(z.read(p))
        wb = xml("xl/workbook.xml")
        wbrels = {r.get("Id"): r.get("Target") for r in xml("xl/_rels/workbook.xml.rels")}
        for s in wb.find("m:sheets", _NS):
            tgt = "xl/" + wbrels[s.get(_RID)]
            relp = f"{os.path.dirname(tgt)}/_rels/{os.path.basename(tgt)}.rels"
            if relp not in z.namelist():
                continue
            rels = {r.get("Id"): r.get("Target") for r in xml(relp)}
            sheet = {}
            for c in xml(tgt).findall(".//m:control", _NS):
                name = c.get("name")
                if name in sheet:
                    continue
                x = os.path.normpath(os.path.join(os.path.dirname(tgt), rels[c.get(_RID)])).replace("\\", "/")
                relx = f"{os.path.dirname(x)}/_rels/{os.path.basename(x)}.rels"
                b = os.path.normpath(os.path.join(os.path.dirname(x), xml(relx)[0].get("Target"))).replace("\\", "/")
                data = z.read(b)
                clsid = data[:16].hex()
                if clsid.startswith("e081d1df"):
                    sheet[name] = _scroll(data)
                elif clsid.startswith(("501dd28b", "601dd28b")):
                    sheet[name] = _morph(data)
            out[s.get("name")] = sheet
    return out


def _on(ctrls, sheet, name) -> bool:
    return ctrls.get(sheet, {}).get(name, {}).get("Value") in ("1", "True", "-1")


def _rows(ws, kcol, vcol, r1, r2):
    return [[ws[f"{kcol}{r}"].value, ws[f"{vcol}{r}"].value] for r in range(r1, r2 + 1)]


# Lit les entrées du classeur ERA Braking Curves Tool v5.1 (.xlsm): valeurs de
# cellules en cache (data_only) + états des contrôles ActiveX.
def load_workbook_scenario(path) -> Scenario:
    import openpyxl
    wb = openpyxl.load_workbook(path, data_only=True)
    ctrls = read_controls(path)
    tm, trs, nvs = wb["Train (main)"], wb["Track"], wb["National values"]
    fvs, bl, bg = wb["Fixed values"], wb["Brake parameters (lambda)"], wb["Brake parameters (gamma)"]
    ic, gc, kd = wb["Integrated correction factors"], wb["Gradient correction factors"], wb["Correction factor Kdry_rst"]

    def tv(cell, default=None):
        v = tm[cell].value
        return default if v is None or v == "" else v

    train = Train(
        train_type="gamma" if _on(ctrls, "Train (main)", "Gamma") else "lambda",
        brake_position=tm["D23"].value,
        T_traction_cut_off=tv("D4", 0.0),
        service_brake_interface=_on(ctrls, "Train (main)", "Service_brake_interface_yes"),
        traction_cut_off_interface=_on(ctrls, "Train (main)", "Traction_cut_off_interface_yes"),
        special_brake_indep_adhesion=_on(ctrls, "Train (main)", "Add_brake_yes"),
        speed_inaccuracy="user" if _on(ctrls, "Train (main)", "User_sci") else "subset041",
        speed_inaccuracy_pct=tv("D8"),
        odometer_abs=tv("D9", 0.0), odometer_rel_pct=tv("D10", 0.0),
        supervised_manoeuvre=_on(ctrls, "Train (main)", "Supervised_manoeuvre_yes"),
        safe_consist_length=(tm["D25"].value != "No"),
        engine_orientation_same=_on(ctrls, "Train (main)", "Engine_vs_train_orient_same"),
        consist_rear_min=tv("D15", 0.0), consist_rear_nom=tv("E15", 0.0), consist_rear_max=tv("F15", 0.0),
        consist_front_min=tv("D17", 0.0), consist_front_nom=tv("E17", 0.0), consist_front_max=tv("F17", 0.0),
        train_length=tv("D18", 0.0), rotating_mass_pct=tv("D19"),
        antenna_to_front=tv("D20", 0.0), engine_length=tv("D21", 0.0), A_est1=tv("D22", 0.0),
    )

    grad = []
    r = 3
    while r <= 104 and trs[f"J{r}"].value not in (None, ""):
        grad.append([trs[f"I{r}"].value, trs[f"J{r}"].value])
        if trs[f"I{r + 1}"].value in (None, ""):
            break
        grad.append([trs[f"I{r + 1}"].value, trs[f"J{r + 1}"].value])
        r += 2
    balises = [[trs[f"F{r}"].value, trs[f"G{r}"].value or 0] for r in range(2, 32)
               if trs[f"F{r}"].value not in (None, "")]
    track = Track(
        target="LOA_MRSP" if _on(ctrls, "Track", "LoA_MRSP") else "EOA_SvL",
        V_target=trs["B2"].value or 0, d_target=trs["B3"].value, V_initial=trs["B4"].value,
        d_svl=trs["E1"].value or 0, release_speed="fixed" if _on(ctrls, "Track", "Release_speed_fixed") else "onboard",
        fixed_release_speed=trs["E2"].value or 0, level=1 if _on(ctrls, "Track", "Level1") else 2,
        balises=balises, gradient=grad,
        brake_inhibition=_on(ctrls, "Track", "Brake_inhibition"),
        brake_inhib_start=trs["B6"].value if trs["B6"].value not in (None, "") else 0,
        reduced_adhesion=_on(ctrls, "Track", "Reduced_adhesion"),
        reduced_adh_start=trs["B9"].value or 0, reduced_adh_end=trs["B10"].value or 0,
    )
    national = NationalValues(
        Q_NVSBTSMPERM=_on(ctrls, "National values", "Q_NVSBTSMPERM_yes"),
        Q_NVGUIPERM=_on(ctrls, "National values", "Q_NVGUIPERM_yes"),
        Q_NVINHSMICPERM=_on(ctrls, "National values", "Q_NVINHSMICPERM_yes"),
        A_NVMAXREDADH1=nvs["B4"].value, A_NVMAXREDADH2=nvs["B5"].value, A_NVMAXREDADH3=nvs["B6"].value,
        M_NVAVADH=nvs["B7"].value,
    )
    fixed = FixedValues(*[fvs[f"C{r}"].value for r in range(2, 20)])

    lam = LambdaBrake(
        lambda_pct=bl["F3"].value,
        conversion_model=not _on(ctrls, "Brake parameters (lambda)", "ShorterValue"),
        T_brake_service_user=bl["F14"].value, T_brake_service_react_user=bl["F17"].value,
        conversion_model_max_speed=bl["I27"].value, A_SB01=bl["U2"].value, A_SB12=bl["U3"].value,
        normal_service_P=[_rows(bl, "Z", "AB", r, r + 13) for r in (2, 17, 32)],
        normal_service_G=[_rows(bl, "AL", "AN", r, r + 13) for r in (2, 17, 32)],
        kv_freight=_rows(ic, "A", "B", 5, 14),
        kv_passenger_speeds=[ic[f"D{r}"].value for r in range(5, 15)],
        kv_passenger_a=[ic[f"E{r}"].value for r in range(5, 15)],
        kv_passenger_b=[ic[f"E{r}"].value for r in range(31, 41)],
        kr=_rows(ic, "A", "B", 32, 41), A_NVP12=ic["D44"].value, A_NVP23=ic["F44"].value, Kt_int=ic["D47"].value,
        kn_plus=_rows(gc, "A", "B", 4, 13), kn_minus=_rows(gc, "C", "D", 4, 13),
    )
    # the first row of each normal-service table is (Q14=0, R14=AD0)
    lam.normal_service_P = [[[0, t[0][1]]] + t[1:] for t in lam.normal_service_P]
    lam.normal_service_G = [[[0, t[0][1]]] + t[1:] for t in lam.normal_service_G]

    def comb(kc, vc, tc):
        return {"A_brake_emergency": _rows(bg, kc, vc, 7, 20), "Kwet_rst": _rows(bg, kc, vc, 38, 51),
                "T_brake_emergency": bg[f"{tc}52"].value, "A_brake_service": _rows(bg, kc, vc, 54, 67),
                "T_brake_service": bg[f"{tc}68"].value, "A_brake_normal_service": _rows(bg, kc, vc, 70, 83),
                "T_brake_emergency_react": bg[f"{tc}85"].value, "T_brake_service_react": bg[f"{tc}86"].value}
    ebcl = next((i for i in range(10) if _on(ctrls, "Brake parameters (gamma)", f"EBCL{i}")), 4)
    kdry = {i: {"comb1": [kd[f"E{4 + 15 * i + 2 * j}"].value for j in range(7)],
                "comb2": [kd[f"Q{4 + 15 * i + 2 * j}"].value for j in range(7)]} for i in range(10)}
    gam = GammaBrake(comb1=comb("H", "J", "K"), comb2=comb("T", "V", "W"), ebcl=ebcl, kdry_by_ebcl=kdry)
    return Scenario(train=train, track=track, national=national, fixed=fixed, lambda_brake=lam, gamma_brake=gam)


# ==========================================================================
