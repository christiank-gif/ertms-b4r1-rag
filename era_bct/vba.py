from __future__ import annotations

import math


# SECTION 1/13 — SÉMANTIQUE EXCEL/VBA (helpers : Cell/VLookup/Max/Min, CLng, Round). Aucune clause SRS : reproduce le comportement du VBA.
# ==========================================================================

"""Excel / VBA semantics needed for a faithful port of the ERA Braking Curves Tool.

The VBA code stores intermediate results in worksheet cells and reads them back
with ``Cells(r, c)``, ``WorksheetFunction.VLookup`` (approximate match),
``WorksheetFunction.Max/Min``.  The helpers below reproduce the behaviours that
influence the numerical results:

* empty cells read as ``Empty`` (0 in arithmetic, equal to "" in comparisons);
* the string "" written by the VBA (``Cells(p, 20) = ""``) is *not* empty:
  arithmetic on it is a type mismatch, ``IsEmpty`` is False, and a number
  compared with it is always smaller (VBA Variant comparison rule);
* ``VLookup(..., True)`` is a binary search (lower-midpoint bisection) over the
  *whole* range, blank cells being resolved to the nearest non-blank cell above
  them.  The lower-midpoint variant was validated against the 2 491 cached
  values of the normal-service deceleration table of the v5.1 workbook, which
  is built from an unsorted lookup range;
* ``Cells(x, c)`` with a non-integer row rounds half-to-even (CLng);
* ``WorksheetFunction.Max/Min`` ignore empty and text cells when they are given
  as cell references.
"""

import math

EMPTY = None          # an empty cell (VBA Empty)
EMPTY_STR = ""        # the empty string written into a cell by the VBA code


class VBAError(RuntimeError):
    """A run-time error the VBA macro itself would have raised."""


def is_blank(x) -> bool:
    """``Cells(..) = ""`` test (True for Empty and for the empty string)."""
    return x is None or x == ""


def num(x) -> float:
    """Value of a cell used in arithmetic (Empty -> 0, text -> type mismatch)."""
    if x is None:
        return 0.0
    if isinstance(x, bool):
        return -1.0 if x else 0.0
    if isinstance(x, str):
        if x == "":
            raise VBAError("Type mismatch: arithmetic on an empty-string cell")
        try:
            return float(x)
        except ValueError as exc:
            raise VBAError(f"Type mismatch on text cell {x!r}") from exc
    return float(x)


def gt(a, b) -> bool:
    """VBA Variant ``a > b`` for cell values (numbers are less than strings)."""
    a_s, b_s = isinstance(a, str), isinstance(b, str)
    if a_s and b_s:
        return a > b
    if a_s:
        return True
    if b_s:
        return False
    return num(a) > num(b)


def clng(x: float) -> int:
    """VBA CLng / implicit Double->Long conversion (round half to even)."""
    return int(round(x))


def vint(x: float) -> int:
    """VBA ``Int`` (floor)."""
    return math.floor(x)


def vround(x: float, digits: int = 0) -> float:
    """VBA ``Round`` (banker's rounding)."""
    return round(x, digits)


def roundup(x: float, digits: int = 0) -> float:
    """Excel ``ROUNDUP`` (away from zero)."""
    f = 10 ** digits
    return math.copysign(math.ceil(abs(x) * f - 1e-12) / f, x)


def vpow(base: float, exp: float) -> float:
    """VBA ``^`` (negative base with fractional exponent is run-time error 5)."""
    if base < 0 and exp != int(exp):
        raise VBAError("Invalid procedure call: negative number raised to a fractional power")
    return base ** exp


class Ref:
    """A cell passed by reference to WorksheetFunction.Max/Min."""
    __slots__ = ("v",)

    def __init__(self, v):
        self.v = v


def _collect(args):
    out = []
    for a in args:
        if isinstance(a, Ref):
            if a.v is None or isinstance(a.v, str) or isinstance(a.v, bool):
                continue
            out.append(float(a.v))
        else:
            out.append(num(a))
    return out


def wmax(*args) -> float:
    vals = _collect(args)
    return max(vals) if vals else 0.0


def wmin(*args) -> float:
    vals = _collect(args)
    return min(vals) if vals else 0.0


def _prev_index(keys):
    """prev[i] = index of the nearest non-blank key at or above i (-1 if none)."""
    prev, last = [], -1
    for i, k in enumerate(keys):
        if k is not None:
            last = i
        prev.append(last)
    return prev


def match_index(keys, x, prev=None) -> int:
    """Excel approximate-match binary search.  Returns an index or raises #N/A.

    ``keys`` is the full lookup column (None for blank cells); a blank cell met by
    the bisection is resolved to the nearest non-blank cell above it.
    """
    if x is None or isinstance(x, str):
        raise VBAError("Unable to get the VLookup property (blank/text lookup value)")
    if prev is None:
        prev = _prev_index(keys)
    x = float(x)
    lo, hi = 0, len(keys) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        j = prev[mid]
        if j >= 0 and keys[j] <= x:
            lo = mid + 1
        else:
            hi = mid - 1
    j = prev[hi] if hi >= 0 else -1
    if j < 0:
        raise VBAError("Unable to get the VLookup property (#N/A)")
    return j


def vlookup(keys, values, x):
    """``WorksheetFunction.VLookup(x, range, col)`` with approximate match."""
    return values[match_index(keys, x)]


class Table:
    """A static two-column lookup range (keys, values)."""

    def __init__(self, rows):
        self.keys = [None if (k is None or k == "") else float(k) for k, _ in rows]
        self.vals = [v for _, v in rows]

    def __call__(self, x):
        return vlookup(self.keys, self.vals, x)


class Grid:
    """A worksheet modelled as a sparse row/column store with 1-based indices."""

    def __init__(self, name: str):
        self.name = name
        self.cols: dict[int, dict[int, object]] = {}
        self._ver: dict[int, int] = {}
        self._cache: dict = {}

    def __getitem__(self, rc):
        r, c = rc
        if r < 1 or c < 1:
            raise VBAError(f"{self.name}: invalid cell reference ({r}, {c})")
        return self.cols.get(c, {}).get(r)

    def __setitem__(self, rc, v):
        r, c = rc
        if r < 1 or c < 1:
            raise VBAError(f"{self.name}: invalid cell reference ({r}, {c})")
        col = self.cols.setdefault(c, {})
        if v is None:
            col.pop(r, None)
        else:
            col[r] = v
        self._ver[c] = self._ver.get(c, 0) + 1

    def n(self, r, c) -> float:
        return num(self[r, c])

    def clear(self, r1, c1, r2, c2):
        for c in range(c1, c2 + 1):
            col = self.cols.get(c)
            if not col:
                continue
            for r in [r for r in col if r1 <= r <= r2]:
                del col[r]
            self._ver[c] = self._ver.get(c, 0) + 1

    def column(self, c, r1, r2):
        col = self.cols.get(c, {})
        return [col.get(r) for r in range(r1, r2 + 1)]

    def _keys(self, c, r1, r2):
        key = (c, r1, r2)
        ver = self._ver.get(c, 0)
        hit = self._cache.get(key)
        if hit and hit[0] == ver:
            return hit[1]
        raw = self.column(c, r1, r2)
        keys = [None if (v is None or isinstance(v, (str, bool))) else float(v) for v in raw]
        entry = (keys, _prev_index(keys))
        self._cache[key] = (ver, entry)
        return entry

    def vlookup(self, x, keycol, r1, r2, offset):
        """``VLookup(x, Range(keycol r1 : keycol+offset-1 r2), offset)``."""
        keys, prev = self._keys(keycol, r1, r2)
        i = match_index(keys, x, prev)
        return self[r1 + i, keycol + offset - 1]


# ==========================================================================
