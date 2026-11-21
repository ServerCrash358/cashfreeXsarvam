"""Spoken numbers in English, Hindi/Hinglish and Tamil -> digit strings. Pure.
Word lists need native-speaker review (UNVERIFIED against real Saaras transcripts)."""
from __future__ import annotations

import re

from panch.normalise import to_ascii_digits
from panch.normalise.legacy import _MULT, _word_value, words_to_amount  # token parser that accepts mixed digits ("twenty 2 thousand")

DIGIT_WORDS = {
    # English
    "zero": 0, "oh": 0, "o": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7,
    "eight": 8, "nine": 9,
    # Hindi (Devanagari) and Hinglish
    "शून्य": 0, "एक": 1, "दो": 2, "तीन": 3, "चार": 4, "पाँच": 5, "पांच": 5, "छह": 6, "छः": 6, "सात": 7, "आठ": 8,
    "नौ": 9, "shunya": 0, "ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "paanch": 5, "panch": 5,
    "chhe": 6, "che": 6, "saat": 7, "aath": 8, "nau": 9,
    # Tamil and romanised Tamil
    "பூஜ்ஜியம்": 0, "சைபர்": 0, "ஒன்று": 1, "ஒண்ணு": 1, "இரண்டு": 2, "ரெண்டு": 2, "மூன்று": 3, "மூணு": 3,
    "நான்கு": 4, "நாலு": 4, "ஐந்து": 5, "அஞ்சு": 5, "ஆறு": 6, "ஏழு": 7, "எட்டு": 8, "ஒன்பது": 9,
    "onnu": 1, "rendu": 2, "moonu": 3, "naalu": 4, "anju": 5, "aaru": 6, "ezhu": 7, "ettu": 8, "ombodhu": 9,
    "ombadhu": 9,
    # more spellings (PR 4): Tamil script and romanised variants, Hinglish
    "இரெண்டு": 2, "ஒன்னு": 1, "ஒம்போது": 9, "பூஜ்யம்": 0,
    "ondru": 1, "onru": 1, "irandu": 2, "moondru": 3, "naangu": 4, "nalu": 4, "aindhu": 5, "ainthu": 5,
    "yezhu": 7, "onbadhu": 9, "onpathu": 9, "ombothu": 9, "poojyam": 0,
    "shoonya": 0, "chheh": 6, "paach": 5,
}
REPEAT = {"double": 2, "triple": 3, "डबल": 2, "ट्रिपल": 3, "டபுள்": 2}
_TOKEN = re.compile(r"[\wऀ-ॿ஀-௿]+")


def _tokens(text: str) -> list[str]:
    s = to_ascii_digits(text or "").lower().replace("।", " ").replace("॥", " ")  # Hindi danda
    s = re.sub(r"(?<=\d),(?=\d)", "", s)          # 22,000 -> 22000
    return _TOKEN.findall(s)


def spoken_to_digits(text: str) -> str:
    """Replace spoken single digits with numerals and join runs: 'code four seven two' -> 'code 472'."""
    out: list[str] = []
    run = ""
    repeat = 1
    for tok in _tokens(text):
        if tok in REPEAT:
            repeat = REPEAT[tok]
            continue
        if tok in DIGIT_WORDS or (tok.isdigit() and len(tok) == 1):
            d = str(DIGIT_WORDS.get(tok, tok))
            run += d * repeat
            repeat = 1
            continue
        if run:
            out.append(run)
            run = ""
        out.append(tok)
        repeat = 1
    if run:
        out.append(run)
    return " ".join(out)


def extract_digits(transcript: str, lang: str = "en") -> str:
    """All spoken digits in order, e.g. for the call-back's last four."""
    return "".join(re.findall(r"\d", spoken_to_digits(transcript)))


def numbers_from_speech(text: str) -> list[str]:
    """Digit strings for every number phrase: runs of digits and word amounts ('baais hazaar')."""
    found: list[str] = []
    group: list[str] = []

    def flush():
        if not group:
            return
        if any(t in _MULT for t in group):
            w = words_to_amount(" ".join(group))
            if w is not None:
                found.append(str(int(w)))
        else:
            for t in group:
                v = DIGIT_WORDS.get(t)
                found.append(t if t.isdigit() else (str(v) if v is not None else str(_word_value(t))))
        group.clear()

    for tok in spoken_to_digits(text).split():
        if tok.isdigit() or tok in _MULT or _word_value(tok) is not None:
            group.append(tok)
        else:
            flush()
    flush()
    return found
