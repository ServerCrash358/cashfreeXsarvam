"""Local, deterministic Tamil / Devanagari to Latin transliteration.

Used for the vendor key and for parsing Tamil number words. It is a lookup
table, not a model, so the same input always gives the same output and no
network call is needed. Case is significant in `tamil_phonemic` (T, N, R, L
mark the retroflex/alveolar letters); `to_latin` lowercases for names.
"""
from __future__ import annotations

from .numerals import nfc

# ---------------------------------------------------------------- Tamil
TA_VOWELS = {
    "அ": "a", "ஆ": "aa", "இ": "i", "ஈ": "ii", "உ": "u", "ஊ": "uu",
    "எ": "e", "ஏ": "ee", "ஐ": "ai", "ஒ": "o", "ஓ": "oo", "ஔ": "au",
}
TA_CONS = {
    "க": "k", "ங": "ng", "ச": "c", "ஞ": "ny", "ட": "T", "ண": "N",
    "த": "t", "ந": "n", "ப": "p", "ம": "m", "ய": "y", "ர": "r",
    "ல": "l", "வ": "v", "ழ": "zh", "ள": "L", "ற": "R", "ன": "n",
    "ஜ": "j", "ஷ": "sh", "ஸ": "s", "ஹ": "h", "ஶ": "sh",
}
TA_SIGNS = {
    "ா": "aa", "ி": "i", "ீ": "ii", "ு": "u", "ூ": "uu",
    "ெ": "e", "ே": "ee", "ை": "ai", "ொ": "o", "ோ": "oo",
    "ௌ": "au",
}
TA_VIRAMA = "்"
TA_AYTHAM = "ஃ"


def tamil_phonemic(text: str) -> str:
    """Tamil script to a case-sensitive phonemic Latin string.

    'பன்னிரண்டாயிரத்து' -> 'panniraNTaayirattu'. Non-Tamil characters pass
    through unchanged.
    """
    s = nfc(text)
    out: list[str] = []
    i = 0
    while i < len(s):
        ch = s[i]
        if ch in TA_CONS:
            nxt = s[i + 1] if i + 1 < len(s) else ""
            if nxt == TA_VIRAMA:
                out.append(TA_CONS[ch]); i += 2; continue
            if nxt in TA_SIGNS:
                out.append(TA_CONS[ch] + TA_SIGNS[nxt]); i += 2; continue
            if nxt == "ௗ":  # au length mark
                out.append(TA_CONS[ch] + "au"); i += 2; continue
            out.append(TA_CONS[ch] + "a"); i += 1; continue
        if ch in TA_VOWELS:
            out.append(TA_VOWELS[ch]); i += 1; continue
        if ch == TA_AYTHAM:
            out.append("h"); i += 1; continue
        if ch in TA_SIGNS or ch == TA_VIRAMA:
            i += 1; continue  # stray sign: drop
        out.append(ch); i += 1
    return "".join(out)


# ------------------------------------------------------------ Devanagari
HI_VOWELS = {
    "अ": "a", "आ": "aa", "इ": "i", "ई": "ii", "उ": "u", "ऊ": "uu", "ऋ": "ri",
    "ए": "e", "ऐ": "ai", "ओ": "o", "औ": "au", "ऑ": "o", "ऍ": "e",
}
HI_CONS = {
    "क": "k", "ख": "kh", "ग": "g", "घ": "gh", "ङ": "n",
    "च": "ch", "छ": "chh", "ज": "j", "झ": "jh", "ञ": "n",
    "ट": "t", "ठ": "th", "ड": "d", "ढ": "dh", "ण": "n",
    "त": "t", "थ": "th", "द": "d", "ध": "dh", "न": "n",
    "प": "p", "फ": "ph", "ब": "b", "भ": "bh", "म": "m",
    "य": "y", "र": "r", "ल": "l", "व": "v", "ळ": "l",
    "श": "sh", "ष": "sh", "स": "s", "ह": "h",
}
HI_NUKTA_CONS = {"ज": "z", "फ": "f", "ड": "r", "ढ": "rh", "क": "q", "ख": "kh", "ग": "g"}
HI_SIGNS = {
    "ा": "aa", "ि": "i", "ी": "ii", "ु": "u", "ू": "uu",
    "ृ": "ri", "े": "e", "ै": "ai", "ो": "o", "ौ": "au",
    "ॉ": "o", "ॅ": "e",
}
HI_VIRAMA = "्"
HI_NUKTA = "़"
HI_MODIFIERS = {"ं": "n", "ँ": "n", "ः": "h"}


def devanagari_latin(text: str) -> str:
    """Devanagari to lowercase Latin with word-final schwa deletion."""
    s = nfc(text)
    out: list[str] = []
    i = 0
    n = len(s)
    while i < n:
        ch = s[i]
        if ch in HI_CONS:
            j = i + 1
            base = HI_CONS[ch]
            if j < n and s[j] == HI_NUKTA:
                base = HI_NUKTA_CONS.get(ch, base); j += 1
            nxt = s[j] if j < n else ""
            if nxt == HI_VIRAMA:
                out.append(base); i = j + 1; continue
            if nxt in HI_SIGNS:
                out.append(base + HI_SIGNS[nxt]); i = j + 1; continue
            # inherent vowel, dropped at the end of a word (Hindi schwa deletion)
            at_word_end = j >= n or not ("ऀ" <= s[j] <= "ॿ")
            out.append(base if at_word_end else base + "a"); i = j; continue
        if ch in HI_VOWELS:
            out.append(HI_VOWELS[ch]); i += 1; continue
        if ch in HI_MODIFIERS:
            out.append(HI_MODIFIERS[ch]); i += 1; continue
        if ch in HI_SIGNS or ch in (HI_VIRAMA, HI_NUKTA):
            i += 1; continue
        out.append(ch); i += 1
    return "".join(out)


def to_latin(text: str) -> str:
    """Any mix of Tamil, Devanagari and Latin to lowercase Latin."""
    return devanagari_latin(tamil_phonemic(text)).lower()
