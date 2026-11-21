"""Invoice numbers. Pure, no I/O.

'INV-0042', 'inv 42' and '42' all normalise to '42'. The financial-year part
is kept, because vendors restart numbering every year: '42/2025-26' becomes
'42@fy2025-26' and is a different invoice from '42/2026-27'.
"""
from __future__ import annotations

import re

from .numerals import nfc, to_ascii_digits

# Generic prefixes carry no identity. Series letters ("A-42", "TN/42") do, so
# only these words are dropped.
GENERIC_PREFIXES = {"inv", "invoice", "bill", "no", "number", "num", "ref", "tax",
                    "ti", "gst", "sl", "sr", "serial", "cash", "credit"}

_FY = re.compile(r"(?<!\d)(?:fy\s*)?((?:20)?\d{2})\s*[-/]\s*((?:20)?\d{2})(?!\d)", re.IGNORECASE)
_RUNS = re.compile(r"[a-z]+|\d+")


def _fy(text: str):
    """Find a financial year like 2025-26, 25-26, 2025-2026 or FY25-26."""
    for start in range(len(text)):          # overlapping scan: "42/2025-26"
        m = _FY.match(text, start)
        if not m:
            continue
        a, b = m.group(1), m.group(2)
        ya = int(a) if len(a) == 4 else 2000 + int(a)
        yb = int(b) if len(b) == 4 else 2000 + int(b)
        if yb == ya + 1 and 2000 <= ya <= 2099:
            return f"{ya}-{str(yb)[2:]}", m.span()
    return None, None


def norm_invoice_number(text: str | None) -> str:
    """Canonical invoice number; '' when nothing is left."""
    if text is None:
        return ""
    s = to_ascii_digits(nfc(str(text))).lower().strip()
    fy, span = _fy(s)
    if span:
        s = s[: span[0]] + " " + s[span[1]:]
    runs = _RUNS.findall(s)
    # drop generic words only while they lead (INV-, Bill No.)
    while runs and runs[0] in GENERIC_PREFIXES:
        runs.pop(0)
    parts = [r.lstrip("0") or "0" if r.isdigit() else r for r in runs]
    core = "-".join(parts)
    if fy:
        return f"{core}@fy{fy}" if core else f"@fy{fy}"
    return core
