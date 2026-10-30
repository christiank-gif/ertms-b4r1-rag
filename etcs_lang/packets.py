"""ERTMS/ETCS packets per SUBSET-026-7 §7.4 (track-to-train §7.4.2, train-to-track §7.4.3).

Packet layout (ch.7 §7.3.3):
- track-to-train: NID_PACKET(8), Q_DIR(2), L_PACKET(13), then information;
- train-to-track: NID_PACKET(8), L_PACKET(13), then information.
L_PACKET counts ALL bits of the packet including its header (§7.5.1.49).
Packet 255 (End of Information) is a single NID_PACKET = 255.
"""

import json
import os

from .bitstream import BitWriter, BitReader
from .variables import (
    VARIABLES, encode_distance, decode_distance, encode_speed, decode_speed,
    encode_timer, decode_timer, encode_bcd, decode_bcd,
)
from .versions import version_code

_DATA = os.path.join(os.path.dirname(__file__), "data", "packets_db.json")
with open(_DATA, encoding="utf-8") as _f:
    PACKET_DEFS = json.load(_f)


def packet_name(number, direction="track_to_train"):
    for key in (f"{number}#{direction}", str(number)):
        entry = PACKET_DEFS.get(key)
        if entry:
            return entry["name"]
    return f"Packet {number}"


class Packet:
    """A decoded packet: number, direction and ordered field values."""

    def __init__(self, number, direction, fields=None):
        self.number = number
        self.direction = direction
        self.fields = fields or {}

    @property
    def name(self):
        return packet_name(self.number, self.direction)

    def __repr__(self):
        return f"Packet {self.number} ({self.name}) {self.fields}"


class PacketWriter:
    """Builds one packet and patches L_PACKET (counts the whole packet in bits)."""

    def __init__(self, number, track_to_train=True, q_dir=0):
        self.w = BitWriter()
        self.packet_start = len(self.w)
        self.w.write_uint(number, 8)
        self.header_bits = 8
        if track_to_train:
            self.w.write_uint(q_dir, 2)
            self.header_bits = 10
        self.lp_pos = len(self.w)
        self.w.write_uint(0, 13)

    def raw(self, name, value):
        VARIABLES[name].encode(self.w, value)

    def uint(self, value, bits):
        self.w.write_uint(value, bits)

    def dist(self, name, meters, q_scale):
        return encode_distance(self.w, name, meters, q_scale)

    def speed(self, name, kmh):
        return encode_speed(self.w, name, kmh)

    def timer(self, name, seconds, resolution=1.0):
        return encode_timer(self.w, name, seconds, resolution)

    def bytes(self, data):
        self.w.write_bytes(data)

    def finish(self) -> bytes:
        while len(self.w) % 8:
            self.w.write_uint(0, 1)
        l_packet = len(self.w) - self.packet_start
        bits = self.w.to_bits()
        for i in range(13):
            bits[self.lp_pos + i] = (l_packet >> (12 - i)) & 1
        out = BitWriter()
        out.write_bits(bits)
        return out.to_bytes()


# ---- track-to-train packet builders (ch.7 §7.4.2) ------------------------------

def build_packet_0_vbcmk(nid_vbcmk: int, q_dir=0) -> bytes:
    """Packet 0 (track-to-train): Virtual Balise Cover marker.

    Per ch.8 §8.4.2.3 the packet 0 is appended directly to the balise header:
    NID_PACKET(8)=0 + NID_VBCMK(6), no Q_DIR/L_PACKET.
    """
    w = BitWriter()
    w.write_uint(0, 8)
    w.write_uint(nid_vbcmk, 6)
    return w.to_bits()  # 14 raw bits, to be embedded bit-exactly after the header


def build_packet_2_system_version_order(m_version, q_dir=0) -> bytes:
    """Packet 2: System Version order — NID_PACKET, Q_DIR, L_PACKET, M_VERSION(7)."""
    p = PacketWriter(2, track_to_train=True, q_dir=q_dir)
    p.raw("M_VERSION", version_code(m_version))
    return p.finish()


def build_packet_2_onboard_versions(versions) -> bytes:
    """Packet 2 (train-to-track): Onboard supported system versions — M_VERSION, N_ITER, M_VERSION(k)."""
    p = PacketWriter(2, track_to_train=False)
    p.raw("M_VERSION", version_code(versions[0]))
    p.raw("N_ITER", len(versions) - 1)
    for v in versions[1:]:
        p.raw("M_VERSION", version_code(v))
    return p.finish()


def build_packet_3_national_values(q_scale, d_validnv_m, nid_c, values: dict) -> bytes:
    """Packet 3: National Values (mandatory head fields, ch.7 §7.4.2.2)."""
    p = PacketWriter(3, track_to_train=True)
    p.raw("Q_SCALE", q_scale)
    p.dist("D_VALIDNV", d_validnv_m, q_scale)
    p.raw("NID_C", nid_c)
    extra = values.get("nid_c_list", [])
    p.raw("N_ITER", len(extra))
    for c in extra:
        p.raw("NID_C", c)
    p.speed("V_NVSHUNT", values.get("v_nvshunt", 0))
    p.speed("V_NVSTFF", values.get("v_nvstff", 0))
    p.speed("V_NVONSIGHT", values.get("v_nvonsight", 0))
    p.speed("V_NVLIMSUPERV", values.get("v_nvlimsuperv", 0))
    p.speed("V_NVUNFIT", values.get("v_nvunfit", 0))
    p.speed("V_NVREL", values.get("v_nvrel", 0))
    return p.finish()


def build_packet_15_l2_ma(q_scale, v_ema_kmh, t_ema_s, l_endsection_m,
                          sections_m=None, q_endtimer=0, t_endtimer_s=0.0,
                          d_endtimerstartloc_m=0.0, q_dangerpoint=0, d_dp_m=0.0,
                          v_releasedp_kmh=0.0, q_overlap=0, d_startol_m=0.0,
                          t_ol_s=0.0, d_ol_m=0.0, v_releaseol_kmh=0.0, q_dir=0) -> bytes:
    """Packet 15: Level 2 Movement Authority (ch.7 §7.4.2.4)."""
    sections_m = sections_m or []
    p = PacketWriter(15, track_to_train=True, q_dir=q_dir)
    p.raw("Q_SCALE", q_scale)
    p.speed("V_EMA", v_ema_kmh)
    p.timer("T_EMA", t_ema_s)
    sections = sections_m if sections_m else [l_endsection_m]
    p.raw("N_ITER", len(sections) - 1)
    for s in sections:
        p.dist("L_SECTION", s, q_scale)
        p.raw("Q_SECTIONTIMER", 0)
        p.timer("T_SECTIONTIMER", 0)
        p.dist("D_SECTIONTIMERSTOPLOC", 0.0, q_scale)
    p.dist("L_ENDSECTION", l_endsection_m, q_scale)
    p.raw("Q_SECTIONTIMER", 0)
    p.timer("T_SECTIONTIMER", 0)
    p.dist("D_SECTIONTIMERSTOPLOC", 0.0, q_scale)
    p.raw("Q_ENDTIMER", q_endtimer)
    if q_endtimer:
        p.timer("T_ENDTIMER", t_endtimer_s)
        p.dist("D_ENDTIMERSTARTLOC", d_endtimerstartloc_m, q_scale)
    p.raw("Q_DANGERPOINT", q_dangerpoint)
    if q_dangerpoint:
        p.dist("D_DP", d_dp_m, q_scale)
        p.speed("V_RELEASEDP", v_releasedp_kmh)
    p.raw("Q_OVERLAP", q_overlap)
    if q_overlap:
        p.dist("D_STARTOL", d_startol_m, q_scale)
        p.timer("T_OL", t_ol_s)
        p.dist("D_OL", d_ol_m, q_scale)
        p.speed("V_RELEASEOL", v_releaseol_kmh)
    return p.finish()


def build_packet_21_gradient(q_scale, d_trackinit_m, gradients, q_trackinit=1, q_dir=0) -> bytes:
    """Packet 21: Gradient Profile — N_ITER, then G_GRADIENT(k)(8, signed), D_GRADIENT(k)."""
    p = PacketWriter(21, track_to_train=True, q_dir=q_dir)
    p.raw("Q_SCALE", q_scale)
    p.raw("Q_TRACKINIT", q_trackinit)
    if q_trackinit:
        p.dist("D_TRACKINIT", d_trackinit_m, q_scale)
    p.raw("N_ITER", len(gradients))
    for g, d in gradients:
        p.uint(g & 0xFF, 8)
        p.dist("D_GRADIENT", d, q_scale)
    return p.finish()


def build_packet_27_issp(q_scale, d_trackinit_m, profiles, q_trackinit=1, q_dir=0) -> bytes:
    """Packet 27: International Static Speed Profile — N_ITER, V_STATIC(k), D_STATIC(k), L_STATIC(k)."""
    p = PacketWriter(27, track_to_train=True, q_dir=q_dir)
    p.raw("Q_SCALE", q_scale)
    p.raw("Q_TRACKINIT", q_trackinit)
    if q_trackinit:
        p.dist("D_TRACKINIT", d_trackinit_m, q_scale)
    p.raw("N_ITER", len(profiles))
    for v, l, d in profiles:
        p.speed("V_STATIC", v)
        p.dist("D_STATIC", d, q_scale)
        p.dist("L_STATIC", l, q_scale)
    return p.finish()


def build_packet_41_level_transition(q_scale, m_leveltr, nid_c, nid_rbc, d_lrt_m, q_dir=0) -> bytes:
    """Packet 41: Level Transition Order (subset of fields, ch.7 §7.4.2.x)."""
    p = PacketWriter(41, track_to_train=True, q_dir=q_dir)
    p.raw("Q_SCALE", q_scale)
    p.raw("M_LEVELTR", m_leveltr)
    p.raw("NID_C", nid_c)
    p.raw("NID_RBC", nid_rbc)
    p.dist("D_LRT", d_lrt_m, q_scale)
    return p.finish()


def build_packet_42_session_mgmt(q_rbc, nid_c, nid_rbc, nid_radio, q_sleepsession=0, q_dir=0) -> bytes:
    """Packet 42: Session Management for RBC interfaced to GSM-R (ch.7 §7.4.2.11)."""
    p = PacketWriter(42, track_to_train=True, q_dir=q_dir)
    p.raw("Q_RBC", q_rbc)
    p.raw("NID_C", nid_c)
    p.raw("NID_RBC", nid_rbc)
    p.uint(int(nid_radio), 64)
    p.raw("Q_SLEEPSESSION", q_sleepsession)
    return p.finish()


def build_packet_44_external_data(nid_xuser, payload: bytes, nid_ntc=0, q_dir=0) -> bytes:
    """Packet 44 (track-to-train): Data used by applications outside ERTMS/ETCS."""
    p = PacketWriter(44, track_to_train=True, q_dir=q_dir)
    p.raw("NID_XUSER", nid_xuser)
    p.raw("NID_NTC", nid_ntc)
    p.bytes(payload)
    return p.finish()


def build_packet_65_tsr(q_scale, nid_tsr, d_tsr_m, l_tsr_m, q_front, v_tsr_kmh, q_dir_tsr=0, q_dir=0) -> bytes:
    """Packet 65: Temporary Speed Restriction (ch.7 §7.4.2.x)."""
    p = PacketWriter(65, track_to_train=True, q_dir=q_dir)
    p.raw("Q_SCALE", q_scale)
    p.raw("NID_TSR", nid_tsr)
    p.raw("Q_DIR_TSR", q_dir_tsr)
    p.dist("D_TSR", d_tsr_m, q_scale)
    p.dist("L_TSR", l_tsr_m, q_scale)
    p.raw("Q_FRONT", q_front)
    p.speed("V_TSR", v_tsr_kmh)
    return p.finish()


def build_packet_136_infill_location(q_newcountry, nid_c, nid_bg, q_dir=0) -> bytes:
    """Packet 136: Infill location reference (ch.7 §7.4.2.x)."""
    p = PacketWriter(136, track_to_train=True, q_dir=q_dir)
    p.raw("Q_NEWCOUNTRY", q_newcountry)
    p.raw("NID_C", nid_c)
    p.raw("NID_BG", nid_bg)
    return p.finish()


def build_packet_255() -> bytes:
    """Packet 255: End of Information — NID_PACKET = 255 only."""
    w = BitWriter()
    w.write_uint(255, 8)
    return w.to_bytes()


# ---- train-to-track packet builders (ch.7 §7.4.3) -------------------------------

def build_packet_0_position_report(q_scale, nid_c, nid_bg, d_lrbg_m, q_dirlrbg,
                                   q_dlrbg, l_doubtover_m, l_doubtunder_m,
                                   q_integrity, v_train_kmh, q_dirtrain,
                                   m_mode, m_level, l_trainint_m=0.0, nid_ntc=0) -> bytes:
    """Packet 0 (train-to-track): Position Report (ch.7 §7.4.3.1)."""
    p = PacketWriter(0, track_to_train=False)
    p.raw("Q_SCALE", q_scale)
    p.raw("NID_C", nid_c)
    p.raw("NID_BG", nid_bg)
    p.dist("D_LRBG", d_lrbg_m, q_scale)
    p.raw("Q_DIRLRBG", q_dirlrbg)
    p.raw("Q_DLRBG", q_dlrbg)
    p.dist("L_DOUBTOVER", l_doubtover_m, q_scale)
    p.dist("L_DOUBTUNDER", l_doubtunder_m, q_scale)
    p.raw("Q_INTEGRITY", q_integrity)
    if q_integrity in (1, 2):
        p.dist("L_TRAININT", l_trainint_m, q_scale)
    p.speed("V_TRAIN", v_train_kmh)
    p.raw("Q_DIRTRAIN", q_dirtrain)
    p.raw("M_MODE", m_mode)
    p.raw("M_LEVEL", m_level)
    if m_level == 4:  # NTC
        p.raw("NID_NTC", nid_ntc)
    return p.finish()


def build_packet_4_error_reporting(error_code: int) -> bytes:
    """Packet 4 (train-to-track): Error Reporting — NID_PACKET, L_PACKET, M_ERROR(8)."""
    p = PacketWriter(4, track_to_train=False)
    p.raw("M_ERROR", error_code)
    return p.finish()


def build_packet_5_train_running_number(nid_operational: str) -> bytes:
    """Packet 5 (train-to-track): Train running number — NID_OPERATIONAL, BCD 32 bits."""
    p = PacketWriter(5, track_to_train=False)
    encode_bcd(p.w, "NID_OPERATIONAL", nid_operational, 32)
    return p.finish()


def build_packet_11_train_data(nc_cdtrain, nc_train, l_train_m, v_maxtrain_kmh,
                               m_loadinggauge, m_axleloadcat, m_airtight,
                               n_axle, voltages=None) -> bytes:
    """Packet 11 (train-to-track): Validated train data (ch.7 §7.4.3.6)."""
    voltages = voltages or []
    p = PacketWriter(11, track_to_train=False)
    p.raw("NC_CDTRAIN", nc_cdtrain)
    p.raw("NC_TRAIN", nc_train)
    p.raw("L_TRAIN", int(l_train_m))
    p.speed("V_MAXTRAIN", v_maxtrain_kmh)
    p.raw("M_LOADINGGAUGE", m_loadinggauge)
    p.raw("M_AXLELOADCAT", m_axleloadcat)
    p.raw("M_AIRTIGHT", m_airtight)
    p.raw("N_AXLE", n_axle)
    p.raw("N_ITER", len(voltages))
    for v, c in voltages:
        p.raw("M_VOLTAGE", v)
        p.raw("NID_CTRACTION", c)
    return p.finish()


def packet_fields(number, direction="track_to_train"):
    """Field definitions of a packet from the SUBSET-026-7 extraction."""
    for key in (f"{number}#{direction}", str(number)):
        entry = PACKET_DEFS.get(key)
        if entry:
            return entry["fields"]
    return []


def build_packet_from_fields(number, direction, values) -> bytes:
    """Build a packet generically from its SUBSET-026-7 field table.

    values: dict name -> int. A field flagged 'repeat' starts a repetition
    group whose size is given by the last N_ITER seen (N_ITER+1 entries);
    repeated entries are read from values as 'NAME_0', 'NAME_1', ...
    (falling back to the plain 'NAME'). M_VERSION accepts 'X.Y' strings.
    """
    t2t = direction == "track_to_train"
    p = PacketWriter(number, track_to_train=t2t, q_dir=int(values.get("Q_DIR", 0)) if t2t else 0)
    n_iter = 0
    i = 0
    fields = packet_fields(number, direction)
    while i < len(fields):
        f = fields[i]
        name = f["name"]
        if name in ("NID_PACKET", "L_PACKET"):
            i += 1
            continue
        if name == "Q_DIR" and t2t:
            i += 1
            continue  # written by PacketWriter
        if name == "N_ITER":
            n_iter = int(values.get("N_ITER", 0))
            p.uint(n_iter, f["length_bits"])
            i += 1
            continue
        if f["repeat"]:
            # collect the whole consecutive group of repeated fields
            group = []
            while i < len(fields) and fields[i]["repeat"]:
                group.append(fields[i])
                i += 1
            for k in range(n_iter + 1):
                for gf in group:
                    v = values.get(f"{gf['name']}_{k}", values.get(gf["name"], 0))
                    p.uint(int(v), gf["length_bits"])
            continue
        # conditional fields of packet 15: present only when the Q_ flag = 1
        if number == 15:
            cond = {"T_ENDTIMER": "Q_ENDTIMER", "D_ENDTIMERSTARTLOC": "Q_ENDTIMER",
                    "D_DP": "Q_DANGERPOINT", "V_RELEASEDP": "Q_DANGERPOINT",
                    "D_STARTOL": "Q_OVERLAP", "T_OL": "Q_OVERLAP",
                    "D_OL": "Q_OVERLAP", "V_RELEASEOL": "Q_OVERLAP"}
            if name in cond and int(values.get(cond[name], 0)) == 0:
                i += 1
                continue
        v = values.get(name, 0)
        if name == "M_VERSION" and isinstance(v, str) and "." in v:
            v = version_code(v)
        p.uint(int(v), f["length_bits"])
        i += 1
    return p.finish()


BUILDERS = {
    (0, "track_to_train"): build_packet_0_vbcmk,
    (2, "track_to_train"): build_packet_2_system_version_order,
    (2, "train_to_track"): build_packet_2_onboard_versions,
    (3, "track_to_train"): build_packet_3_national_values,
    (15, "track_to_train"): build_packet_15_l2_ma,
    (21, "track_to_train"): build_packet_21_gradient,
    (27, "track_to_train"): build_packet_27_issp,
    (41, "track_to_train"): build_packet_41_level_transition,
    (42, "track_to_train"): build_packet_42_session_mgmt,
    (44, "track_to_train"): build_packet_44_external_data,
    (65, "track_to_train"): build_packet_65_tsr,
    (136, "track_to_train"): build_packet_136_infill_location,
    (255, "track_to_train"): lambda: build_packet_255(),
    (0, "train_to_track"): build_packet_0_position_report,
    (4, "train_to_track"): build_packet_4_error_reporting,
    (5, "train_to_track"): build_packet_5_train_running_number,
    (11, "train_to_track"): build_packet_11_train_data,
}


def build_packet(number, direction, **kwargs) -> bytes:
    key = (number, direction)
    if key not in BUILDERS:
        raise KeyError(f"no builder for packet {number} ({direction})")
    return BUILDERS[key](**kwargs)


# ---- packet decoding -----------------------------------------------------------

def decode_packet(reader: BitReader, direction="track_to_train", in_telegram=False) -> Packet:
    nid_packet = reader.read_uint(8)
    if nid_packet == 255:
        return Packet(255, direction, {})
    if direction == "track_to_train" and nid_packet == 0 and in_telegram:
        # ch.8 §8.4.2.3: packet 0 appended to header = NID_PACKET + NID_VBCMK only
        return Packet(0, direction, {"NID_VBCMK": reader.read_uint(6)})
    if direction == "track_to_train":
        reader.read_uint(2)  # Q_DIR
    header_bits = 23 if direction == "track_to_train" else 21
    l_packet = reader.read_uint(13)
    packet_end = reader.pos - header_bits + l_packet
    fields = {}
    if direction == "track_to_train":
        if nid_packet == 0:
            fields["NID_VBCMK"] = reader.read_uint(6)
        elif nid_packet == 2:
            fields["M_VERSION"] = reader.read_uint(7)
        elif nid_packet == 42:
            fields["Q_RBC"] = reader.read_uint(1)
            fields["NID_C"] = reader.read_uint(10)
            fields["NID_RBC"] = reader.read_uint(14)
            fields["NID_RADIO"] = reader.read_uint(64)
            fields["Q_SLEEPSESSION"] = reader.read_uint(1)
        elif nid_packet == 136:
            fields["Q_NEWCOUNTRY"] = reader.read_uint(1)
            fields["NID_C"] = reader.read_uint(10)
            fields["NID_BG"] = reader.read_uint(14)
        elif nid_packet == 15:
            fields["Q_SCALE"] = reader.read_uint(2)
            fields["V_EMA"] = reader.read_uint(7)
            fields["T_EMA"] = reader.read_uint(10)
            n_iter = reader.read_uint(5)
            fields["N_ITER"] = n_iter
            sections = []
            for _ in range(n_iter + 1):
                sec = {"L_SECTION": reader.read_uint(15),
                       "Q_SECTIONTIMER": reader.read_uint(1),
                       "T_SECTIONTIMER": reader.read_uint(10),
                       "D_SECTIONTIMERSTOPLOC": reader.read_uint(15)}
                sections.append(sec)
            fields["sections"] = sections
            fields["L_ENDSECTION"] = reader.read_uint(15)
            fields["Q_SECTIONTIMER"] = reader.read_uint(1)
            fields["T_SECTIONTIMER"] = reader.read_uint(10)
            fields["D_SECTIONTIMERSTOPLOC"] = reader.read_uint(15)
            fields["Q_ENDTIMER"] = reader.read_uint(1)
            if fields["Q_ENDTIMER"]:
                fields["T_ENDTIMER"] = reader.read_uint(10)
                fields["D_ENDTIMERSTARTLOC"] = reader.read_uint(15)
            fields["Q_DANGERPOINT"] = reader.read_uint(1)
            if fields["Q_DANGERPOINT"]:
                fields["D_DP"] = reader.read_uint(15)
                fields["V_RELEASEDP"] = reader.read_uint(7)
            fields["Q_OVERLAP"] = reader.read_uint(1)
            if fields["Q_OVERLAP"]:
                fields["D_STARTOL"] = reader.read_uint(15)
                fields["T_OL"] = reader.read_uint(10)
                fields["D_OL"] = reader.read_uint(15)
                fields["V_RELEASEOL"] = reader.read_uint(7)
            reader._pos = packet_end
        else:
            pass
    else:
        if nid_packet == 0:
            fields["Q_SCALE"] = reader.read_uint(2)
            fields["NID_C"] = reader.read_uint(10)
            fields["NID_BG"] = reader.read_uint(14)
            fields["D_LRBG"] = reader.read_uint(15)
            fields["Q_DIRLRBG"] = reader.read_uint(2)
            fields["Q_DLRBG"] = reader.read_uint(2)
            fields["L_DOUBTOVER"] = reader.read_uint(15)
            fields["L_DOUBTUNDER"] = reader.read_uint(15)
            fields["Q_INTEGRITY"] = reader.read_uint(2)
            if fields["Q_INTEGRITY"] in (1, 2):
                fields["L_TRAININT"] = reader.read_uint(15)
            fields["V_TRAIN"] = reader.read_uint(7)
            fields["Q_DIRTRAIN"] = reader.read_uint(2)
            fields["M_MODE"] = reader.read_uint(5)
            fields["M_LEVEL"] = reader.read_uint(3)
            if fields["M_LEVEL"] == 4:
                fields["NID_NTC"] = reader.read_uint(8)
        elif nid_packet == 4:
            fields["M_ERROR"] = reader.read_uint(8)
        elif nid_packet == 5:
            fields["NID_OPERATIONAL"] = decode_bcd(reader, 32)
        elif nid_packet == 11:
            fields["NC_CDTRAIN"] = reader.read_uint(4)
            fields["NC_TRAIN"] = reader.read_uint(15)
            fields["L_TRAIN"] = reader.read_uint(12)
            fields["V_MAXTRAIN"] = reader.read_uint(7)
        else:
            pass
    reader._pos = packet_end
    return Packet(nid_packet, direction, fields)
