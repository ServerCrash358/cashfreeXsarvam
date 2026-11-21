"""Amount in words to Decimal: English, Hindi, Tamil. Pure, no I/O.

Strict by design: an unknown word, or numbers in an impossible order
("five twenty"), returns None instead of a best guess.

NATIVE-CHECK: the Hindi and Tamil word lists below need a native speaker's
review before the demo (UNIT_TESTS U-NORM-7..9).
"""
from __future__ import annotations

import re
from decimal import Decimal
from functools import lru_cache

from .numerals import dominant_script, nfc
from .translit import tamil_phonemic

# Token kinds: "n" additive number, "h" hundred multiplier, "s" scale,
# "f" filler (ignored), "p" paise marker.

# ---------------------------------------------------------------- English
_EN_UNITS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6,
    "seven": 7, "eight": 8, "nine": 9, "ten": 10, "eleven": 11, "twelve": 12,
    "thirteen": 13, "fourteen": 14, "fifteen": 15, "sixteen": 16,
    "seventeen": 17, "eighteen": 18, "nineteen": 19, "twenty": 20,
    "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50, "sixty": 60,
    "seventy": 70, "eighty": 80, "ninety": 90, "ninty": 90,
}
_EN_SCALES = {
    "thousand": 1_000, "lakh": 100_000, "lakhs": 100_000, "lac": 100_000,
    "lacs": 100_000, "million": 1_000_000, "crore": 10_000_000, "crores": 10_000_000,
}
_EN_FILLERS = {"rupees", "rupee", "rs", "inr", "only", "and", "indian", "the", "sum", "of", "amount", "total"}
_EN_PAISE = {"paise", "paisa"}

# ------------------------------------------------------------------ Hindi
# Nukta and chandrabindu are normalised away before lookup (see _hi_key).
_HI_NUMBERS = """
एक 1|दो 2|तीन 3|चार 4|पांच 5|पाच 5|छह 6|छः 6|छै 6|छे 6|सात 7|आठ 8|नौ 9|दस 10|
ग्यारह 11|बारह 12|तेरह 13|चौदह 14|पंद्रह 15|पन्द्रह 15|सोलह 16|सत्रह 17|अठारह 18|उन्नीस 19|बीस 20|
इक्कीस 21|बाईस 22|बाइस 22|तेईस 23|तेइस 23|चौबीस 24|पच्चीस 25|छब्बीस 26|सत्ताईस 27|सत्ताइस 27|अट्ठाईस 28|अठ्ठाईस 28|अट्ठाइस 28|उनतीस 29|तीस 30|
इकतीस 31|इकत्तीस 31|बत्तीस 32|तैंतीस 33|तेंतीस 33|चौंतीस 34|चौतीस 34|पैंतीस 35|छत्तीस 36|सैंतीस 37|अड़तीस 38|अडतीस 38|उनतालीस 39|चालीस 40|
इकतालीस 41|बयालीस 42|तैंतालीस 43|चौवालीस 44|चवालीस 44|पैंतालीस 45|छियालीस 46|सैंतालीस 47|अड़तालीस 48|उनचास 49|पचास 50|
इक्यावन 51|बावन 52|तिरपन 53|तिरेपन 53|चौवन 54|पचपन 55|छप्पन 56|सत्तावन 57|अट्ठावन 58|उनसठ 59|साठ 60|
इकसठ 61|बासठ 62|तिरसठ 63|चौंसठ 64|पैंसठ 65|छियासठ 66|सड़सठ 67|अड़सठ 68|उनहत्तर 69|सत्तर 70|
इकहत्तर 71|बहत्तर 72|तिहत्तर 73|चौहत्तर 74|पचहत्तर 75|छिहत्तर 76|सतहत्तर 77|अठहत्तर 78|उन्यासी 79|उनासी 79|अस्सी 80|
इक्यासी 81|बयासी 82|तिरासी 83|चौरासी 84|पचासी 85|छियासी 86|सत्तासी 87|अट्ठासी 88|नवासी 89|नब्बे 90|
इक्यानवे 91|बानवे 92|तिरानवे 93|चौरानवे 94|पचानवे 95|पंचानवे 95|छियानवे 96|सत्तानवे 97|अट्ठानवे 98|निन्यानवे 99|शून्य 0
"""
_HI_SCALES = {"हजार": 1_000, "हज़ार": 1_000, "लाख": 100_000, "करोड": 10_000_000, "करोड़": 10_000_000}
_HI_HUNDRED = {"सौ"}
_HI_FILLERS = {"रुपये", "रुपए", "रुपया", "रु", "मात्र", "केवल", "और", "सिर्फ", "सिर्फ़", "कुल"}
_HI_PAISE = {"पैसे", "पैसा"}


def _hi_key(word: str) -> str:
    w = nfc(word).replace("़", "").replace("ँ", "ं")
    return w.strip(".,-/")


_HI_LEX: dict[str, tuple[str, int]] = {}
for _item in _HI_NUMBERS.replace("\n", "").split("|"):
    if _item.strip():
        _w, _v = _item.rsplit(" ", 1)
        _HI_LEX[_hi_key(_w)] = ("n", int(_v))
for _w, _v in _HI_SCALES.items():
    _HI_LEX[_hi_key(_w)] = ("s", _v)
for _w in _HI_HUNDRED:
    _HI_LEX[_hi_key(_w)] = ("h", 100)
for _w in _HI_FILLERS:
    _HI_LEX[_hi_key(_w)] = ("f", 0)
for _w in _HI_PAISE:
    _HI_LEX[_hi_key(_w)] = ("p", 0)

# ------------------------------------------------------------------ Tamil
# Written in Tamil script and converted with the same transliteration as the
# input, so both sides always agree. A trailing "u" may be elided before a
# vowel (sandhi): இரண்டு + ஆயிரம் -> இரண்டாயிரம்.
_TA_WORDS = """
ஒன்று 1|ஒரு 1|ஓர் 1|இரண்டு 2|ரெண்டு 2|மூன்று 3|நான்கு 4|நாலு 4|ஐந்து 5|அஞ்சு 5|ஆறு 6|ஏழு 7|எட்டு 8|ஒன்பது 9|
பத்து 10|பதினொன்று 11|பதினொரு 11|பன்னிரண்டு 12|பன்னிரெண்டு 12|பதின்மூன்று 13|பதிமூன்று 13|பதினான்கு 14|பதினாலு 14|
பதினைந்து 15|பதினஞ்சு 15|பதினாறு 16|பதினேழு 17|பதினெட்டு 18|பத்தொன்பது 19|
இருபது 20|முப்பது 30|நாற்பது 40|ஐம்பது 50|அறுபது 60|எழுபது 70|எண்பது 80|தொண்ணூறு 90|
இருபத்து 20|முப்பத்து 30|நாற்பத்து 40|ஐம்பத்து 50|அறுபத்து 60|எழுபத்து 70|எண்பத்து 80|தொண்ணூற்று 90|
நூறு 100|நூற்று 100|இருநூறு 200|இருநூற்று 200|முந்நூறு 300|முன்னூறு 300|முந்நூற்று 300|முன்னூற்று 300|
நானூறு 400|நானூற்று 400|ஐந்நூறு 500|ஐநூறு 500|ஐந்நூற்று 500|ஐநூற்று 500|அறுநூறு 600|அறுநூற்று 600|
எழுநூறு 700|எழுநூற்று 700|எண்ணூறு 800|எண்ணூற்று 800|தொள்ளாயிரம் 900|தொள்ளாயிரத்து 900
"""
# Irregular multiplier forms of thousand (value = multiple of 1000).
_TA_THOUSANDS = {"ஓராயிரம்": 1, "ஒராயிரம்": 1, "மூவாயிரம்": 3, "நாலாயிரம்": 4, "ஐயாயிரம்": 5,
                 "ஓராயிரத்து": 1, "மூவாயிரத்து": 3, "நாலாயிரத்து": 4, "ஐயாயிரத்து": 5}
_TA_SCALES = {"ஆயிரம்": 1_000, "ஆயிரத்து": 1_000, "லட்சம்": 100_000, "லட்சத்து": 100_000,
              "இலட்சம்": 100_000, "இலட்சத்து": 100_000, "லட்ச": 100_000, "லக்ஷம்": 100_000,
              "கோடி": 10_000_000, "கோடியே": 10_000_000, "கோடியை": 10_000_000}
_TA_FILLERS = {"ரூபாய்": 0, "ரூபாய்கள்": 0, "ரூ": 0, "மட்டும்": 0, "மட்டுமே": 0, "மற்றும்": 0, "உம்": 0}
_TA_PAISE = {"பைசா": 0, "காசு": 0}

_TA_VOWEL_START = ("a", "e", "i", "o", "u")


def _build_ta_lex() -> dict[str, tuple[str, int]]:
    lex: dict[str, tuple[str, int]] = {}
    for item in _TA_WORDS.replace("\n", "").split("|"):
        if item.strip():
            w, v = item.rsplit(" ", 1)
            v = int(v)
            lex[tamil_phonemic(w)] = ("n", v)
    for w, mult in _TA_THOUSANDS.items():
        lex[tamil_phonemic(w)] = ("t", mult)  # multiplier already applied to 1000
    for w, v in _TA_SCALES.items():
        lex[tamil_phonemic(w)] = ("s", v)
    for w in _TA_FILLERS:
        lex[tamil_phonemic(w)] = ("f", 0)
    for w in _TA_PAISE:
        lex[tamil_phonemic(w)] = ("p", 0)
    return lex


_TA_LEX = _build_ta_lex()
_TA_ENTRIES = sorted(_TA_LEX, key=len, reverse=True)


def _segment_tamil_word(ph: str) -> list[tuple[str, int]] | None:
    """Split one phonemic Tamil word into lexicon tokens (fewest tokens wins)."""

    @lru_cache(maxsize=None)
    def best(i: int) -> tuple[tuple[str, int], ...] | None:
        if i == len(ph):
            return ()
        options = []
        for entry in _TA_ENTRIES:
            cands = [entry]
            if entry.endswith("u"):
                cands.append(entry[:-1])  # sandhi: final u elided before a vowel
            for form in cands:
                if not ph.startswith(form, i):
                    continue
                j = i + len(form)
                if form is not entry and not ph.startswith(_TA_VOWEL_START, j):
                    continue
                rest = best(j)
                if rest is not None:
                    options.append((_TA_LEX[entry],) + rest)
        if not options:
            return None
        return min(options, key=len)

    res = best(0)
    return list(res) if res is not None else None


# --------------------------------------------------------------- compose
def _compose(tokens: list[tuple[str, int]], hundred_multiplies: bool) -> Decimal | None:
    """Combine tokens with Indian scales. Returns None on impossible order."""
    total = 0
    current = 0
    limit: float = float("inf")      # largest additive value allowed next
    last_scale: float = float("inf")
    seen_number = False
    for kind, val in tokens:
        if kind == "f":
            continue
        if kind == "n":
            if not hundred_multiplies and val == 100 and 0 < current < 10 and limit == 1:
                current *= 100            # Tamil "ஒரு நூறு" = 1 x 100
                limit = 100
                continue
            if val >= limit:
                return None
            else:
                current += val
                if val < 20:
                    limit = 1 if val else limit
                elif val < 100:
                    limit = 10 if val % 10 == 0 else 1
                else:
                    limit = 100 if val % 100 == 0 else (10 if val % 10 == 0 else 1)
            seen_number = True
        elif kind == "h":
            if current >= 100:
                return None
            current = (current or 1) * 100
            limit = 100
            seen_number = True
        elif kind in ("s", "t"):
            scale = val if kind == "s" else 1_000
            mult = (current or 1) if kind == "s" else val
            if kind == "t" and current:
                return None
            if scale >= last_scale:
                return None
            total += mult * scale
            current = 0
            limit = float("inf")
            last_scale = scale
            seen_number = True
        else:
            return None
    if not seen_number:
        return None
    return Decimal(total + current)


def _split_paise(tokens: list[tuple[str, int]]):
    """('... rupees and fifty paise') -> (rupee tokens, paise tokens or None)."""
    idx = [i for i, t in enumerate(tokens) if t[0] == "p"]
    if not idx:
        return tokens, None
    p = idx[0]
    before, after = tokens[:p], tokens[p + 1:]
    if any(t[0] not in ("f",) for t in after):
        return before, after              # "and paise fifty"
    # "fifty paise": take the number tokens right before the marker,
    # back to the last filler ("and").
    k = len(before)
    while k > 0 and before[k - 1][0] != "f":
        k -= 1
    return before[:k], before[k:]


def _finish(tokens, hundred_multiplies: bool) -> Decimal | None:
    rupee_toks, paise_toks = _split_paise(tokens)
    rupees = _compose(rupee_toks, hundred_multiplies)
    if rupees is None:
        return None
    if paise_toks is None:
        return rupees
    paise = _compose(paise_toks, hundred_multiplies)
    if paise is None or paise >= 100:
        return None
    return rupees + paise / 100


def _en_tokens(text: str):
    words = re.split(r"[\s,\-/.()]+", text.lower())
    toks = []
    for w in words:
        if not w:
            continue
        if w in _EN_UNITS:
            toks.append(("n", _EN_UNITS[w]))
        elif w == "hundred":
            toks.append(("h", 100))
        elif w in _EN_SCALES:
            toks.append(("s", _EN_SCALES[w]))
        elif w in _EN_FILLERS:
            toks.append(("f", 0))
        elif w in _EN_PAISE:
            toks.append(("p", 0))
        else:
            return None
    return toks


def _hi_tokens(text: str):
    toks = []
    for w in re.split(r"[\s,\-/()]+", nfc(text)):
        k = _hi_key(w)
        if not k:
            continue
        if k not in _HI_LEX:
            return None
        toks.append(_HI_LEX[k])
    return toks


def _ta_tokens(text: str):
    toks = []
    for w in re.split(r"[\s,\-/()]+", nfc(text)):
        w = w.strip(".")
        if not w:
            continue
        seg = _segment_tamil_word(tamil_phonemic(w))
        if seg is None:
            return None
        toks.extend(seg)
    return toks


def words_to_amount(text: str | None, lang: str | None = None) -> Decimal | None:
    """'Twelve Thousand Three Hundred Ninety Only' -> Decimal('12390').

    `lang` may be 'en', 'hi', 'ta' or a BCP-47 code ('ta-IN'). If it is None or
    'auto', the script of the text decides. The script also wins when it
    clearly disagrees with `lang` (English words on a Tamil invoice).
    """
    if text is None or not str(text).strip():
        return None
    text = nfc(str(text))
    script = dominant_script(text)
    code = (lang or "auto").split("-")[0].lower()
    if code not in ("en", "hi", "ta") or (script and script != code):
        code = script or "en"
    if code == "en":
        toks = _en_tokens(text)
        return None if toks is None else _finish(toks, hundred_multiplies=True)
    if code == "hi":
        toks = _hi_tokens(text)
        return None if toks is None else _finish(toks, hundred_multiplies=True)
    toks = _ta_tokens(text)
    return None if toks is None else _finish(toks, hundred_multiplies=False)
