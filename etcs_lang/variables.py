"""ERTMS/ETCS variables per SUBSET-026-7 §7.5 (ERTMS/ETCS language).

Each variable is encoded as an unsigned big-endian integer of its specified
length. Engineering units are converted to/from the coded value with the
resolution/formula given in the specification (Q_SCALE dependent distances,
5 km/h speeds, 1 s / 10 ms timers, BCD identities...).
"""

import json
import os
import re

from .bitstream import BitWriter, BitReader

_DATA = os.path.join(os.path.dirname(__file__), "data", "spec_db.json")
with open(_DATA, encoding="utf-8") as _f:
    _SPEC = json.load(_f)

_SPEC_VARS = _SPEC["variables"]


def _bits(name, default):
    entry = _SPEC_VARS.get(name)
    if entry and entry.get("length_bits"):
        return entry["length_bits"]
    return default


class Variable:
    """A named fixed-length bit field with optional engineering-unit scaling."""

    def __init__(self, name, length_bits, scale=None, description=""):
        self.name = name
        self.length_bits = length_bits
        self.scale = scale  # callable(value_coded)->engineering or None
        self.description = description

    def check(self, value):
        if value < 0 or value >= (1 << self.length_bits):
            raise ValueError(
                f"{self.name}: value {value} out of range [0, {2**self.length_bits - 1}]"
            )
        return value

    def encode(self, writer: BitWriter, value: int) -> None:
        writer.write_uint(self.check(int(value)), self.length_bits)

    def decode(self, reader: BitReader):
        return reader.read_uint(self.length_bits)


# Q_SCALE resolution factors for distance variables (ch.7 §7.5.1.10):
# 0 -> 10 cm, 1 -> 1 m, 2 -> 10 m
Q_SCALE_RESOLUTION = {0: 0.10, 1: 1.0, 2: 10.0}


def q_scale_factor(q_scale: int) -> float:
    return Q_SCALE_RESOLUTION[q_scale]


# Composite variables (ch.7 §7.5): NID_LRBG = NID_C (10 bits) + NID_BG (14 bits),
# NID_ENGINE = NID_C (10 bits) + NID_ENGINE (14 bits).
COMPOSITE_LENGTHS = {
    "NID_LRBG": 24,   # NID_C(10) + NID_BG(14)
    "NID_PRVLRBG": 24,
    "NID_ENGINE": 24,  # NID_C(10) + NID_ENGINE(14)
}


def variable_length(name: str) -> int:
    if name in COMPOSITE_LENGTHS:
        return COMPOSITE_LENGTHS[name]
    return _bits(name, None)


def build_variable(name: str) -> Variable:
    length = variable_length(name)
    if length is None:
        raise KeyError(f"unknown variable {name}")
    return Variable(name, length, description=(SPEC_VAR_DESCRIPTIONS.get(name, "")))


# Human-readable descriptions extracted from SUBSET-026-7
SPEC_VAR_DESCRIPTIONS = {}
for _name, _entry in _SPEC_VARS.items():
    if _entry.get("resolution"):
        SPEC_VAR_DESCRIPTIONS[_name] = _entry["resolution"]


# Well-known coded variables with their bit lengths (ch.7 §7.5).
VARIABLES = {
    name: build_variable(name)
    for name in [
        "NID_PACKET", "Q_DIR", "L_PACKET", "NID_MESSAGE", "L_MESSAGE", "T_TRAIN",
        "M_ACK", "NID_LRBG", "NID_ENGINE", "Q_SCALE", "D_SR", "D_REF", "V_SM",
        "Q_UPDOWN", "M_VERSION", "Q_MEDIA", "N_PIG", "N_TOTAL", "M_DUP",
        "M_MCOUNT", "NID_C", "NID_BG", "Q_LINK", "NID_LOOP", "NID_RBC",
        "NID_RADIO", "Q_RBC", "Q_SLEEPSESSION", "M_MODE", "M_LEVEL", "NID_NTC",
        "V_TRAIN", "Q_DIRTRAIN", "Q_DIRLRBG", "Q_DLRBG", "D_LRBG", "L_DOUBTOVER",
        "L_DOUBTUNDER", "Q_INTEGRITY", "L_TRAININT", "NC_CDTRAIN", "NC_TRAIN",
        "L_TRAIN", "V_MAXTRAIN", "M_LOADINGGAUGE", "M_AXLELOADCAT", "M_AIRTIGHT",
        "N_AXLE", "N_ITER", "M_VOLTAGE", "NID_CTRACTION", "V_EMA", "T_EMA",
        "L_SECTION", "Q_SECTIONTIMER", "T_SECTIONTIMER", "D_SECTIONTIMERSTOPLOC",
        "L_ENDSECTION", "Q_ENDTIMER", "T_ENDTIMER", "D_ENDTIMERSTARTLOC",
        "Q_DANGERPOINT", "D_DP", "V_RELEASEDP", "Q_OVERLAP", "D_STARTOL",
        "T_OL", "D_OL", "V_RELEASEOL", "D_LOC", "T_CYCLOC", "D_CYCLOC", "M_LOC",
        "Q_LGTLOC", "Q_STATUSLRBG", "NID_OPERATIONAL", "NID_TSR", "X_TEXT",
        "V_STATIC", "V_NVSHUNT", "V_NVSTFF", "V_NVONSIGHT", "V_NVLIMSUPERV",
        "V_NVUNFIT", "V_NVREL", "D_NVROLL", "NID_VBCMK", "Q_NEWCOUNTRY",
        "NID_XUSER", "Q_ASPECT", "Q_TRACKINIT", "D_TRACKINIT", "G_TSR",
        "Q_GDIR", "NID_LX", "T_TRAIN", "M_POSITION", "V_MRSP",
    ]
    if variable_length(name) is not None
}

# Common aliases / additions not covered by the automatic extraction
_EXTRA_LENGTHS = {
    "NID_C": 10, "NID_BG": 14, "NID_RBC": 14, "NID_LOOP": 14, "NID_RIU": 14,
    "NID_RADIO": 64, "NID_NTC": 8, "NID_VBCMK": 6, "NID_XUSER": 9,
    "NID_LX": 8, "NID_CTRACTION": 10, "D_LRBG": 15, "D_VALIDNV": 15,
    "G_GRADIENT": 8, "D_GRADIENT": 15, "L_STATIC": 15, "D_STATIC": 15,
    "D_LRT": 15, "Q_DIR_TSR": 2, "M_LEVELTR": 3, "Q_TRACKINIT": 1,
    "D_TRACKINIT": 15, "Q_FRONT": 1, "M_ERROR": 8, "V_MAXTRAIN": 7,
    "M_LOADINGGAUGE": 8, "M_AXLELOADCAT": 7, "M_AIRTIGHT": 2, "N_AXLE": 10,
    "L_TSR": 15, "D_TSR": 15, "NID_TSR": 8, "Q_NEWCOUNTRY": 1, "Q_RBC": 1,
    "Q_SLEEPSESSION": 1, "Q_DIRLRBG": 2, "Q_DLRBG": 2, "L_DOUBTOVER": 15,
    "L_DOUBTUNDER": 15, "Q_INTEGRITY": 2, "L_TRAININT": 15, "Q_DIRTRAIN": 2,
    "NC_CDTRAIN": 4, "NC_TRAIN": 15, "M_VOLTAGE": 4,
}
for _n, _l in _EXTRA_LENGTHS.items():
    if _n not in VARIABLES:
        VARIABLES[_n] = Variable(_n, _l)


def encode_variable(writer: BitWriter, name: str, value: int) -> None:
    VARIABLES[name].encode(writer, value)


def decode_variable(reader: BitReader, name: str) -> int:
    return VARIABLES[name].decode(reader)


# ---- engineering-unit helpers -------------------------------------------------

def encode_distance(writer: BitWriter, name: str, meters: float, q_scale: int) -> int:
    """Encode a distance variable (15/16 bits) scaled by Q_SCALE (ch.7 §7.5.1.10)."""
    resolution = q_scale_factor(q_scale)
    coded = round(meters / resolution)
    var = VARIABLES[name]
    var.encode(writer, coded)
    return coded


def decode_distance(reader: BitReader, name: str, q_scale: int) -> float:
    coded = VARIABLES[name].decode(reader)
    return coded * q_scale_factor(q_scale)


def encode_speed(writer: BitWriter, name: str, kmh: float) -> int:
    """Encode a speed variable with 5 km/h resolution (e.g. V_EMA, V_TRAIN)."""
    coded = round(kmh / 5.0)
    var = VARIABLES[name]
    var.encode(writer, coded)
    return coded


def decode_speed(reader: BitReader, name: str) -> float:
    return VARIABLES[name].decode(reader) * 5.0


def encode_timer(writer: BitWriter, name: str, seconds: float, resolution: float = 1.0) -> int:
    coded = round(seconds / resolution)
    var = VARIABLES[name]
    var.encode(writer, coded)
    return coded


def decode_timer(reader: BitReader, name: str, resolution: float = 1.0) -> float:
    return VARIABLES[name].decode(reader) * resolution


def encode_bcd(writer: BitWriter, name: str, digits: str, length_bits: int) -> None:
    """Binary Coded Decimal, e.g. NID_OPERATIONAL (32 bits, up to 8 digits)."""
    value = 0
    n_digits = length_bits // 4
    padded = digits.ljust(n_digits, "F")[:n_digits]
    for ch in padded:
        value = (value << 4) | int(ch, 16)
    writer.write_uint(value, length_bits)


def decode_bcd(reader: BitReader, length_bits: int) -> str:
    value = reader.read_uint(length_bits)
    n_digits = length_bits // 4
    s = ""
    for i in range(n_digits):
        nibble = (value >> (4 * (n_digits - 1 - i))) & 0xF
        s += format(nibble, "X")
    return s


def encode_text(writer: BitWriter, text: str, max_chars: int) -> int:
    """X_TEXT string: ISO 8859-1 characters, 8 bits each (ch.7 §7.5.1.174)."""
    data = text.encode("iso-8859-1")[:max_chars]
    for byte in data:
        writer.write_uint(byte, 8)
    return len(data)


def decode_text(reader: BitReader, n_chars: int) -> str:
    raw = bytes(reader.read_uint(8) for _ in range(n_chars))
    return raw.decode("iso-8859-1")
