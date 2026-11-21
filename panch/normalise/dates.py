"""Dates on Indian invoices. Pure, no I/O.

Day first by default. `ambiguous=True` means another reading of the same
digits is a valid, different date: today that is only a numeric date with a
two-digit year where day and month could swap ("03/11/26"). A four-digit
dd-mm-yyyy date is treated as the known Indian format and not flagged, or
roughly 40% of clean invoices (day <= 12) would be held. TEAM DECISION:
confirm with PR 2 before changing this.
"""
from __future__ import annotations

import re
from datetime import date

from .numerals import nfc, to_ascii_digits

_EN_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}
# NATIVE-CHECK: Gregorian month names as written in Tamil and Hindi.
_TA_MONTHS = {
    "ஜனவரி": 1, "பிப்ரவரி": 2, "பெப்ரவரி": 2, "பிப்ரவரி": 2, "மார்ச்": 3, "மார்ச்சு": 3,
    "ஏப்ரல்": 4, "மே": 5, "ஜூன்": 6, "ஜுன்": 6, "ஜூலை": 7, "ஜுலை": 7,
    "ஆகஸ்ட்": 8, "ஆகஸ்டு": 8, "ஆகத்து": 8, "செப்டம்பர்": 9, "செப்டெம்பர்": 9,
    "அக்டோபர்": 10, "அக்டோபர": 10, "நவம்பர்": 11, "டிசம்பர்": 12,
}
_HI_MONTHS = {
    "जनवरी": 1, "फरवरी": 2, "फ़रवरी": 2, "मार्च": 3, "अप्रैल": 4, "अप्रेल": 4,
    "मई": 5, "जून": 6, "जुलाई": 7, "अगस्त": 8, "सितंबर": 9, "सितम्बर": 9,
    "अक्टूबर": 10, "अक्तूबर": 10, "नवंबर": 11, "नवम्बर": 11, "दिसंबर": 12, "दिसम्बर": 12,
}


def _mkey(word: str) -> str:
    return nfc(word).replace("़", "").strip(".,").lower()


MONTHS: dict[str, int] = {}
for _table in (_EN_MONTHS, _TA_MONTHS, _HI_MONTHS):
    for _k, _v in _table.items():
        MONTHS[_mkey(_k)] = _v

_ORDINAL = re.compile(r"(?<=\d)(st|nd|rd|th)\b", re.IGNORECASE)
_NUMERIC = re.compile(r"(\d{1,4})\s*([-/.])\s*(\d{1,2})\s*\2\s*(\d{1,4})")
_TOKENS = re.compile(r"[^\s,\-/.]+")


def _year(y: str) -> int | None:
    if len(y) == 4:
        return int(y)
    if len(y) == 2:
        yy = int(y)
        return 2000 + yy if yy < 70 else 1900 + yy
    return None


def _make(y: int, m: int, d: int) -> date | None:
    try:
        return date(y, m, d)
    except ValueError:
        return None


def parse_date(text: str | None) -> tuple[date | None, bool]:
    """Returns (date or None, ambiguous)."""
    if text is None or not str(text).strip():
        return None, False
    s = to_ascii_digits(nfc(str(text))).strip()
    s = _ORDINAL.sub("", s)

    m = _NUMERIC.fullmatch(s)
    if m:
        a, _sep, b, c = m.groups()
        if len(a) == 4:                              # yyyy-mm-dd
            return _make(int(a), int(b), int(c)), False
        if len(c) not in (2, 4):
            return None, False
        y = _year(c)
        d, mo = int(a), int(b)
        primary = _make(y, mo, d)
        if primary is None:
            return None, False
        swapped = _make(y, d, mo) if d != mo else None
        ambiguous = len(c) == 2 and swapped is not None
        return primary, ambiguous

    # textual month: "3 Nov 2026", "3rd November 2026", "Nov 3, 2026", "03-Nov-26"
    toks = _TOKENS.findall(s)
    month = None
    nums: list[str] = []
    for t in toks:
        k = _mkey(t)
        if k in MONTHS and month is None:
            month = MONTHS[k]
        elif t.isdigit():
            nums.append(t)
        else:
            return None, False
    if month is None or len(nums) != 2:
        return None, False
    day_s, year_s = nums
    if len(day_s) > 2 and len(year_s) <= 2:          # "2026 Nov 3"
        day_s, year_s = year_s, day_s
    if len(day_s) > 2 or len(year_s) not in (2, 4):
        return None, False
    return _make(_year(year_s), month, int(day_s)), False
