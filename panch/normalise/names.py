"""Vendor names: transliterate (never translate), strip honorifics and legal
suffixes, then a phonetic key. Pure, no I/O.

`vendor_key` is a SOFT key. It is meant to collapse spelling and script
variants ("Venkateshwara" / "Venkateswara" / Tamil script) and it will also
collapse some genuinely different vendors. Same key never means same vendor
on its own; PR 2 decides with hard keys (GSTIN, account + IFSC).
"""
from __future__ import annotations

import re

from .numerals import nfc, to_ascii_digits
from .translit import to_latin

HONORIFICS = {
    "m/s", "ms", "messrs", "mr", "mrs", "sri", "shri", "shree", "sree", "srii",
    "shrii", "sreee", "thiru", "tiru", "thirumathi", "smt", "the",
}
LEGAL_SUFFIXES = {
    "pvt", "private", "ltd", "limited", "llp", "inc", "opc", "co", "company",
    "traders", "trader", "and", "&",
}

_MS = re.compile(r"\bm\s*/\s*s\b\.?", re.IGNORECASE)
_PUNCT = re.compile(r"[^\w\s&]", re.UNICODE)


def vendor_translit(name: str | None) -> str:
    """Cleaned Latin form, for display and fuzzy matching (trigram, JW)."""
    if not name:
        return ""
    s = to_latin(to_ascii_digits(nfc(name)))
    s = _MS.sub(" ", s)
    s = s.replace("&", " & ")
    s = _PUNCT.sub(" ", s)
    toks = [t for t in s.split() if t not in HONORIFICS and t not in LEGAL_SUFFIXES]
    return " ".join(toks)


# Applied in order to each token. Collapses aspiration, voicing, retroflex /
# dental, w/v and doubled letters, so Tamil-script names (which do not mark
# voicing: முருகன் -> murukan) meet their English spellings (Murugan).
_PHONETIC_RULES: list[tuple[str, str]] = [
    ("ksh", "ks"), ("x", "ks"), ("q", "k"), ("ck", "k"),
    ("zh", "l"), ("sh", "s"), ("ch", "c"), ("ph", "f"), ("f", "p"),
    ("ng", "n"), ("ny", "n"),
    ("kh", "k"), ("gh", "g"), ("th", "t"), ("dh", "d"), ("bh", "b"), ("jh", "j"),
    ("g", "k"), ("d", "t"), ("b", "p"), ("w", "v"), ("z", "s"), ("c", "s"),
]
_VOWELS = set("aeiouy")


def _token_key(tok: str) -> str:
    if tok.isdigit():
        return tok
    if len(tok) > 4 and tok.endswith("s") and not tok.endswith("ss"):
        tok = tok[:-1]                       # plural: hardwares -> hardware
    for a, b in _PHONETIC_RULES:
        tok = tok.replace(a, b)
    if not tok:
        return ""
    head, rest = tok[0], tok[1:]
    rest = "".join(ch for ch in rest if ch not in _VOWELS and ch != "h")
    if head in _VOWELS:
        head = "a"                           # any leading vowel
    out = [head]
    for ch in rest:
        if ch != out[-1]:
            out.append(ch)                   # collapse doubles: tt -> t
    return "".join(out)


def vendor_key(name: str | None) -> str:
    """'M/s. Sri Murugan Hardwares Pvt Ltd' == 'Sri Murugan Hardware'.

    Tokens are keyed and then sorted, so word order does not matter.
    """
    cleaned = vendor_translit(name)
    keys = sorted(k for k in (_token_key(t) for t in cleaned.split()) if k)
    return " ".join(keys)
