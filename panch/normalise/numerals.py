"""Digit and script helpers. Pure, no I/O."""
from __future__ import annotations

import unicodedata

# Traditional Tamil number signs (ten, hundred, thousand). These are not
# positional digits; "௲௰" style values are flagged, never parsed silently.
TRADITIONAL_TAMIL_NUMERALS = {"௰": 10, "௱": 100, "௲": 1000}

TAMIL_RANGE = (0x0B80, 0x0BFF)
DEVANAGARI_RANGE = (0x0900, 0x097F)


def nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


def to_ascii_digits(text: str) -> str:
    """Map every Unicode decimal digit (Tamil, Devanagari, Latin, ...) to ASCII.

    Only characters of category Nd are converted, so traditional Tamil
    numerals (category No) are left untouched for the caller to flag.
    """
    out = []
    for ch in text:
        if "0" <= ch <= "9":
            out.append(ch)
            continue
        if unicodedata.category(ch) == "Nd":
            out.append(str(unicodedata.decimal(ch)))
        else:
            out.append(ch)
    return "".join(out)


def has_traditional_tamil_numerals(text: str | None) -> bool:
    return bool(text) and any(ch in TRADITIONAL_TAMIL_NUMERALS for ch in text)


def _in(ch: str, rng: tuple[int, int]) -> bool:
    return rng[0] <= ord(ch) <= rng[1]


def dominant_script(text: str | None) -> str | None:
    """'ta', 'hi' or 'en' by letter count; None if there are no letters."""
    if not text:
        return None
    ta = hi = lat = 0
    for ch in text:
        if _in(ch, TAMIL_RANGE):
            ta += 1
        elif _in(ch, DEVANAGARI_RANGE):
            hi += 1
        elif ch.isascii() and ch.isalpha():
            lat += 1
    best = max(ta, hi, lat)
    if best == 0:
        return None
    if best == ta:
        return "ta"
    if best == hi:
        return "hi"
    return "en"


def canon_id(text: str | None) -> str | None:
    """GSTIN / IFSC canonical form: native digits to ASCII, whitespace removed.

    Nothing else changes (no case folding, no character fixes): a malformed
    value must stay malformed so the format checks can see it.
    """
    if text is None:
        return None
    s = "".join(to_ascii_digits(nfc(text)).split())
    return s or None


def canon_account(text: str | None) -> str | None:
    """Account number: ASCII digits with spaces and hyphens removed.

    If anything other than digits, spaces or hyphens is present, the value is
    returned with only digit conversion and whitespace removal, so a check can
    flag it instead of this function quietly repairing it.
    """
    if text is None:
        return None
    s = "".join(to_ascii_digits(nfc(text)).split())
    if not s:
        return None
    stripped = s.replace("-", "")
    return stripped if stripped.isdigit() else s


def canon_phone(text: str | None) -> str | None:
    if text is None:
        return None
    s = to_ascii_digits(nfc(text)).strip()
    return s or None
