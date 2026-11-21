"""Pure parsing of spoken transcripts: digits, small counts, amounts, yes/no.

Used by the bundle approval (H) and the vendor call-back (E2). No I/O.

Word lists for Tamil and Hindi are best-effort and need a native-speaker
review (UNVERIFIED against real Saaras output). Saaras `codemix` may return
Latin-script Hindi/Tamil, so romanised forms are included too.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Optional

# --- numerals -------------------------------------------------------------

_SCRIPT_DIGITS = {}
for _i in range(10):
    _SCRIPT_DIGITS[chr(0x0BE6 + _i)] = str(_i)  # Tamil ௦-௯
    _SCRIPT_DIGITS[chr(0x0966 + _i)] = str(_i)  # Devanagari ०-९
_DIGIT_TABLE = str.maketrans(_SCRIPT_DIGITS)


def ascii_digits(text: str) -> str:
    """Tamil and Devanagari digits to ASCII. Other characters unchanged."""
    return text.translate(_DIGIT_TABLE)


# Single digits, all languages merged (a transcript is often code-mixed).
_DIGIT_WORDS: dict[str, int] = {}


def _add(value: int, *words: str) -> None:
    for w in words:
        _DIGIT_WORDS[w] = value


# English
_add(0, "zero", "oh", "o")
_add(1, "one")
_add(2, "two", "to", "too")
_add(3, "three")
_add(4, "four", "for")
_add(5, "five")
_add(6, "six")
_add(7, "seven")
_add(8, "eight")
_add(9, "nine")
# Hindi (Devanagari and romanised)
_add(0, "शून्य", "जीरो", "ज़ीरो", "shunya", "shoonya")
_add(1, "एक", "ek")
_add(2, "दो", "do")
_add(3, "तीन", "teen", "tin")
_add(4, "चार", "char", "chaar")
_add(5, "पांच", "पाँच", "paanch", "panch", "paach")
_add(6, "छह", "छः", "छे", "chhe", "che", "chheh", "chah")
_add(7, "सात", "saat", "sat")
_add(8, "आठ", "aath", "ath")
_add(9, "नौ", "nau")  # "no" is deliberately NOT a digit (it is a refusal)
# Tamil (script and romanised); native-check
_add(0, "பூஜ்ஜியம்", "பூஜ்யம்", "சைபர்", "poojyam", "saibar")
_add(1, "ஒன்று", "ஒண்ணு", "ஒன்னு", "onnu", "ondru", "onru")
_add(2, "இரண்டு", "ரெண்டு", "இரெண்டு", "rendu", "irandu")
_add(3, "மூன்று", "மூணு", "moonu", "moondru", "munu")
_add(4, "நான்கு", "நாலு", "naalu", "naangu", "nangu", "nalu")
_add(5, "ஐந்து", "அஞ்சு", "anju", "aindhu", "ainthu")
_add(6, "ஆறு", "aaru", "aru")
_add(7, "ஏழு", "ezhu", "elu", "yezhu")
_add(8, "எட்டு", "ettu")
_add(9, "ஒன்பது", "ஒம்போது", "onbadhu", "ombodhu", "ombothu", "onpathu")

# "to", "too", "for", "o", "oh" are common English function words. Only treat
# them as digits when they sit inside a run of other digits (see _digit_value).
_WEAK_DIGIT_WORDS = {"to", "too", "for", "o", "oh", "do", "sat", "tin", "ath", "aru", "elu", "che"}

# Small counts beyond 9 ("das bill").
_COUNT_WORDS: dict[str, int] = {
    "ten": 10, "das": 10, "दस": 10, "பத்து": 10, "pathu": 10,
    "eleven": 11, "gyarah": 11, "ग्यारह": 11,
    "twelve": 12, "barah": 12, "बारह": 12,
}

_MULTIPLIERS: dict[str, int] = {
    "hundred": 100, "sau": 100, "सौ": 100, "நூறு": 100, "nooru": 100,
    "thousand": 1000, "hazaar": 1000, "hazar": 1000, "hajar": 1000, "हज़ार": 1000,
    "हजार": 1000, "ஆயிரம்": 1000, "aayiram": 1000, "ayiram": 1000,
    "lakh": 100000, "lac": 100000, "laakh": 100000, "लाख": 100000, "லட்சம்": 100000,
    "latcham": 100000,
    "crore": 10000000, "करोड़": 10000000, "करोड": 10000000, "கோடி": 10000000,
}

YES_WORDS = {
    "yes", "yeah", "yep", "ok", "okay", "approve", "approved", "confirm",
    "haan", "han", "haa", "haanji", "hanji", "ji", "theek", "thik",
    "हाँ", "हां", "हा", "जी", "ठीक",
    "aam", "aama", "aamaa", "sari", "seri", "sariya",
    "ஆம்", "ஆமா", "ஆமாம்", "சரி",
}
NO_WORDS = {
    "no", "nope", "not", "cancel", "stop", "reject", "wait",
    "nahi", "nahin", "nai", "mat", "ruko", "mana",
    "नहीं", "नही", "मत", "रुको", "ना",
    "illa", "illai", "venda", "vendaam", "vendam", "kudathu",
    "இல்லை", "இல்ல", "வேண்டாம்", "வேணாம்", "கூடாது",
}
BILL_WORDS = {"bill", "bills", "invoice", "invoices", "बिल", "பில்", "பில்கள்", "payment", "payments"}

# Separators: whitespace and punctuation, but never Indic combining marks
# (Python's \w excludes vowel signs, so we cannot split on \W).
_SPLIT = re.compile(r"[\s,.;:!?\-–—_/|()\[\]{}\"'“”‘’।॥…]+")
_INDIAN_GROUPED = re.compile(r"(?<=\d),(?=\d)")


@dataclass(frozen=True)
class Token:
    raw: str
    digit: Optional[int] = None      # single spoken digit
    number: Optional[int] = None     # a written number ("22000", "472")
    count: Optional[int] = None      # small count word ("das")
    multiplier: Optional[int] = None


def tokenize(transcript: str) -> list[Token]:
    text = ascii_digits(transcript or "").lower()
    text = _INDIAN_GROUPED.sub("", text)          # "1,25,000" -> "125000"
    text = re.sub(r"(?<=\d)\s*-\s*(?=\d)", " ", text)  # "4-7-2" -> "4 7 2"
    text = re.sub(r"(?<=\d)(?=[^\d\s.,])", " ", text)  # "22000rs" -> "22000 rs"
    text = re.sub(r"(?<=[^\d\s])(?=\d)", " ", text)
    out: list[Token] = []
    for raw in _SPLIT.split(text):
        if not raw:
            continue
        if raw.isdigit():
            out.append(Token(raw, digit=int(raw) if len(raw) == 1 else None, number=int(raw)))
        elif raw in _DIGIT_WORDS:
            out.append(Token(raw, digit=_DIGIT_WORDS[raw]))
        elif raw in _COUNT_WORDS:
            out.append(Token(raw, count=_COUNT_WORDS[raw]))
        elif raw in _MULTIPLIERS:
            out.append(Token(raw, multiplier=_MULTIPLIERS[raw]))
        else:
            out.append(Token(raw))
    return _drop_weak_digits(out)


def _drop_weak_digits(tokens: list[Token]) -> list[Token]:
    """'to'/'for'/'do' count as digits only next to another digit token."""
    result = list(tokens)
    for i, t in enumerate(tokens):
        if t.digit is None or t.raw not in _WEAK_DIGIT_WORDS:
            continue
        prev_d = i > 0 and tokens[i - 1].digit is not None and tokens[i - 1].raw not in _WEAK_DIGIT_WORDS
        next_d = i + 1 < len(tokens) and tokens[i + 1].digit is not None and tokens[i + 1].raw not in _WEAK_DIGIT_WORDS
        next_bill = i + 1 < len(tokens) and tokens[i + 1].raw in BILL_WORDS
        if not (prev_d or next_d or next_bill):
            result[i] = Token(t.raw)
    return result


def extract_digits(transcript: str, lang: str = "en") -> str:
    """All spoken or written digits in order, as one string.

    "four seven two nine" -> "4729"; "नाम 4729" -> "4729"; "சரி நாலு ஏழு" -> "47".
    Multi-digit written numbers contribute all their digits. `lang` is accepted
    for the shared interface; the word list is merged across languages because
    real speech is code-mixed.
    """
    parts: list[str] = []
    for t in tokenize(transcript):
        if t.digit is not None:
            parts.append(str(t.digit))
        elif t.number is not None:
            parts.append(t.raw)  # keep leading zeros: code "025", last four "0471"
    return "".join(parts)


def digit_runs(tokens: list[Token]) -> list[tuple[int, int, str]]:
    """Runs of consecutive single-digit tokens: (start, end_exclusive, digits)."""
    runs, i = [], 0
    while i < len(tokens):
        if tokens[i].digit is not None and (tokens[i].number is None or len(tokens[i].raw) == 1):
            j = i
            while j < len(tokens) and tokens[j].digit is not None and (tokens[j].number is None or len(tokens[j].raw) == 1):
                j += 1
            runs.append((i, j, "".join(str(tokens[k].digit) for k in range(i, j))))
            i = j
        else:
            i += 1
    return runs


def amounts_in(tokens: list[Token], skip: set[int] = frozenset()) -> list[Decimal]:
    """Candidate rupee amounts: written numbers, optionally with a multiplier word.

    "22000" -> 22000; "22 hazaar" -> 22000; "1.25 lakh" is handled by the
    normaliser (PR 1) via `words_amount` in the approval module.
    """
    found: list[Decimal] = []
    for i, t in enumerate(tokens):
        if i in skip:
            continue
        base = t.number if t.number is not None else t.digit
        if base is None:
            continue
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if nxt is not None and nxt.multiplier:
            found.append(Decimal(base) * nxt.multiplier)
        elif t.number is not None and t.number >= 10:
            found.append(Decimal(t.number))
    return found


def small_numbers(tokens: list[Token], skip: set[int] = frozenset()) -> list[int]:
    """Counts like "do bill" / "2 bills" / "das": numbers 1-99 outside `skip`."""
    out = []
    for i, t in enumerate(tokens):
        if i in skip:
            continue
        nxt = tokens[i + 1] if i + 1 < len(tokens) else None
        if nxt is not None and nxt.multiplier:
            continue  # "22 hazaar" is an amount, not a count
        if t.count is not None:
            out.append(t.count)
        elif t.digit is not None:
            out.append(t.digit)
        elif t.number is not None and 0 < t.number < 100:
            out.append(t.number)
    return out


def consent(tokens: list[Token]) -> str:
    """'yes', 'no', 'ambiguous' (both heard) or 'none'."""
    words = {t.raw for t in tokens}
    yes, no = bool(words & YES_WORDS), bool(words & NO_WORDS)
    if yes and no:
        return "ambiguous"
    if yes:
        return "yes"
    if no:
        return "no"
    return "none"


def to_decimal(value) -> Decimal:
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as e:  # pragma: no cover - guard
        raise ValueError(f"not an amount: {value!r}") from e
