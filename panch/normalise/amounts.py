"""Amounts in figures to Decimal. Pure, no I/O, never float."""
from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation

from .numerals import has_traditional_tamil_numerals, nfc, to_ascii_digits

NUKTA = "़"

# Scale words allowed after a figure ("1.25 lakh"). Hindi keys have the nukta
# stripped because the input is stripped the same way.
SCALE_WORDS: dict[str, int] = {
    "thousand": 1_000,
    "lakh": 100_000, "lakhs": 100_000, "lac": 100_000, "lacs": 100_000,
    "crore": 10_000_000, "crores": 10_000_000, "cr": 10_000_000,
    "हजार": 1_000, "लाख": 100_000, "करोड": 10_000_000,
    "ஆயிரம்": 1_000, "லட்சம்": 100_000, "இலட்சம்": 100_000, "லட்ச": 100_000,
    "கோடி": 10_000_000,
}

_CURRENCY = re.compile(
    r"(₹|௹|\binr\b|\brs\b\.?|\brupees?\b|ரூபாய்|ரூ\.?|रुपये|रुपए|रुपया|रु\.?|रू\.?)",
    re.IGNORECASE,
)
_TRAILERS = re.compile(r"(/-|/=|\bonly\b|मात्र|केवल|மட்டும்)", re.IGNORECASE)
_NUMBER = re.compile(r"([-+]?)\s*(\d[\d,]*(?:\.\d*)?|\.\d+)\s*(.*)", re.DOTALL)


def _clean(text: str) -> str:
    s = to_ascii_digits(nfc(text)).replace(NUKTA, "")
    s = _CURRENCY.sub(" ", s)
    s = _TRAILERS.sub(" ", s)
    return " ".join(s.split()).strip(" :")


def _valid_grouping(int_part: str) -> bool:
    if "," not in int_part:
        return int_part.isdigit()
    groups = int_part.split(",")
    if not all(g.isdigit() for g in groups):
        return False
    if not 1 <= len(groups[0]) <= 3 or len(groups[-1]) != 3:
        return False
    return all(len(g) in (2, 3) for g in groups[1:-1])


def _to_decimal(sign: str, num: str, max_decimals: int | None) -> Decimal | None:
    num = num.rstrip(".")
    int_part, _, frac = num.partition(".")
    if int_part and not _valid_grouping(int_part):
        return None
    if max_decimals is not None and len(frac) > max_decimals:
        return None
    try:
        value = Decimal((int_part.replace(",", "") or "0") + ("." + frac if frac else ""))
    except InvalidOperation:
        return None
    return -value if sign == "-" else value


def parse_amount(text: str | None) -> Decimal | None:
    """'₹ 1,25,000.00/-' -> Decimal('125000.00'); '1.25 lakh' -> Decimal('125000').

    Returns None for anything it cannot read with certainty: words, traditional
    Tamil numerals, bad digit grouping ('12,40'), more than two decimals, or an
    unknown word after the figure. None is the signal to ASK; never a guess.
    """
    if text is None or not str(text).strip():
        return None
    text = str(text)
    if has_traditional_tamil_numerals(text):
        return None
    s = _clean(text)
    m = _NUMBER.fullmatch(s)
    if not m:
        return None
    sign, num, tail = m.groups()
    tail = tail.strip().lower()
    scale = 1
    if tail:
        if tail not in SCALE_WORDS:
            return None
        scale = SCALE_WORDS[tail]
    value = _to_decimal(sign, num, max_decimals=2 if scale == 1 else None)
    if value is None:
        return None
    if scale != 1:
        value = value * scale
        if value != value.to_integral_value():
            return None  # "1.234567 lakh" does not land on whole paise
        value = value.quantize(Decimal(1))
    return value


_QTY_TAIL = re.compile(r"[^\d]*")


def parse_quantity(text: str | None) -> Decimal | None:
    """'10 Nos' -> 10, '2.5 kg' -> 2.5. Unit words are dropped, nothing else."""
    if text is None or not str(text).strip():
        return None
    text = str(text)
    if has_traditional_tamil_numerals(text):
        return None
    s = " ".join(to_ascii_digits(nfc(text)).split())
    m = _NUMBER.fullmatch(s)
    if not m:
        return None
    sign, num, tail = m.groups()
    if tail and (any(ch.isdigit() for ch in tail) or not _QTY_TAIL.fullmatch(tail)):
        return None
    return _to_decimal(sign, num, max_decimals=None)
