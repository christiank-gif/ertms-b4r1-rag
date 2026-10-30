"""System version handling per SUBSET-026 chapter 6 (Management of older System Versions).

M_VERSION is a 7-bit variable (SUBSET-026-7 §7.5.1.79): the three MSBs carry the
incompatible version number X, the four LSBs the compatible number Y.

Legally operated trackside versions (ch.6 §6.4.1): X in {1, 2, 3}; within X=1,
Y in {0,1}; within X=2, Y in {0,1,2,3}; within X=3, Y = 0.
On-board highest supported versions (ch.6 §6.4.2): 2.1, 2.2 or 3.0.
"""

from enum import Enum


class SystemVersion(Enum):
    V1_0 = (1, 0)
    V1_1 = (1, 1)
    V2_0 = (2, 0)
    V2_1 = (2, 1)
    V2_2 = (2, 2)
    V2_3 = (2, 3)
    V3_0 = (3, 0)

    def __init__(self, x, y):
        self.x = x
        self.y = y

    @property
    def code(self) -> int:
        """7-bit M_VERSION encoding: 3 MSB = X, 4 LSB = Y."""
        return (self.x << 4) | self.y

    def __str__(self):
        return f"{self.x}.{self.y}"


VERSION_CODES = {v.code: v for v in SystemVersion}

# ch.6 §6.4.1: envelope of legally operated trackside system versions
TRACKSIDE_LEGAL = {SystemVersion.V1_0, SystemVersion.V1_1,
                   SystemVersion.V2_0, SystemVersion.V2_1, SystemVersion.V2_2,
                   SystemVersion.V2_3, SystemVersion.V3_0}

# ch.6 §6.4.2: allowed highest supported on-board versions
ONBOARD_HIGHEST_ALLOWED = {SystemVersion.V2_1, SystemVersion.V2_2, SystemVersion.V3_0}


def version_code(version) -> int:
    """Return the 7-bit M_VERSION code for a SystemVersion or an 'X.Y' string."""
    if isinstance(version, SystemVersion):
        return version.code
    v = parse_version(version)
    return v.code


def parse_version(version) -> SystemVersion:
    """Parse 'X.Y' (str or tuple) into a SystemVersion; raise on unknown values."""
    if isinstance(version, SystemVersion):
        return version
    if isinstance(version, tuple):
        x, y = version
    else:
        parts = str(version).split(".")
        x, y = int(parts[0]), int(parts[1])
    for v in SystemVersion:
        if v.x == x and v.y == y:
            return v
    raise ValueError(f"unknown ETCS system version {x}.{y}")


def decode_version_code(code: int) -> SystemVersion:
    """Decode a 7-bit M_VERSION value (ch.7 §7.5.1.79)."""
    if code in VERSION_CODES:
        return VERSION_CODES[code]
    x, y = code >> 4, code & 0x0F
    raise ValueError(f"M_VERSION code {code:07b} (X={x}, Y={y}) is not a valid version")


def is_legal_trackside(version) -> bool:
    return parse_version(version) in TRACKSIDE_LEGAL


def is_valid_onboard_highest(version) -> bool:
    return parse_version(version) in ONBOARD_HIGHEST_ALLOWED


def supported_envelope(highest) -> list:
    """All versions from 1.0 up to the on-board highest supported one (ch.6 §6.4.2.2)."""
    highest = parse_version(highest)
    ordered = sorted(SystemVersion, key=lambda v: (v.x, v.y))
    start = ordered.index(SystemVersion.V1_0)
    end = ordered.index(highest)
    return ordered[start : end + 1]
