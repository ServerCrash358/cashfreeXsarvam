"""Normalisation (ARCHITECTURE section B). Pure functions; never translate money fields."""
from __future__ import annotations

import re
import unicodedata
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Optional

# --- numerals -------------------------------------------------------------
_DIGIT_MAP = {}
for base in (0x0BE6, 0x0966):            # Tamil, Devanagari digits
    for i in range(10):
        _DIGIT_MAP[chr(base + i)] = str(i)
TRADITIONAL_TAMIL = {"௰": 10, "௱": 100, "௲": 1000}


def to_ascii_digits(text: str) -> str:
    return "".join(_DIGIT_MAP.get(ch, ch) for ch in text)


def has_traditional_tamil(text: str) -> bool:
    return any(ch in TRADITIONAL_TAMIL for ch in text)


# --- amounts --------------------------------------------------------------
_SCALE_WORDS = {
    "lakh": 10**5, "lakhs": 10**5, "lac": 10**5, "lacs": 10**5, "लाख": 10**5, "லட்சம்": 10**5,
    "crore": 10**7, "crores": 10**7, "cr": 10**7, "करोड़": 10**7, "करोड": 10**7, "கோடி": 10**7,
}


def parse_amount(text: Optional[str]) -> Optional[Decimal]:
    """'₹1,25,000.50/-' -> Decimal('125000.50'); '1.5 lakh' -> 150000. None if unreadable."""
    if text is None:
        return None
    if has_traditional_tamil(text):
        return None                       # flagged, never parsed silently
    s = to_ascii_digits(str(text)).strip().lower()
    s = re.sub(r"(rs\.?|inr|₹|/-|only|रु\.?|ரூ\.?)", " ", s)
    scale = 1
    for word, mult in _SCALE_WORDS.items():
        if re.search(rf"(?<![a-z]){re.escape(word)}(?![a-z])", s):
            scale = mult
            s = s.replace(word, " ")
            break
    s = s.replace(",", "").replace(" ", "")
    if not re.fullmatch(r"\d+(\.\d{1,2})?", s):
        return None
    try:
        return (Decimal(s) * scale).quantize(Decimal("0.01"))
    except InvalidOperation:
        return None


# --- amount in words ------------------------------------------------------
_EN_UNITS = {w: i for i, w in enumerate(
    "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen "
    "fifteen sixteen seventeen eighteen nineteen".split())}
_EN_TENS = {"twenty": 20, "thirty": 30, "forty": 40, "fourty": 40, "fifty": 50, "sixty": 60,
            "seventy": 70, "eighty": 80, "ninety": 90}
_HI_WORDS = (
    "शून्य एक दो तीन चार पाँच छह सात आठ नौ दस ग्यारह बारह तेरह चौदह पंद्रह सोलह सत्रह अठारह उन्नीस बीस "
    "इक्कीस बाईस तेईस चौबीस पच्चीस छब्बीस सत्ताईस अट्ठाईस उनतीस तीस इकतीस बत्तीस तैंतीस चौंतीस पैंतीस छत्तीस "
    "सैंतीस अड़तीस उनतालीस चालीस इकतालीस बयालीस तैंतालीस चवालीस पैंतालीस छियालीस सैंतालीस अड़तालीस उनचास पचास "
    "इक्यावन बावन तिरपन चौवन पचपन छप्पन सत्तावन अट्ठावन उनसठ साठ इकसठ बासठ तिरसठ चौंसठ पैंसठ छियासठ सड़सठ "
    "अड़सठ उनहत्तर सत्तर इकहत्तर बहत्तर तिहत्तर चौहत्तर पचहत्तर छिहत्तर सतहत्तर अठहत्तर उन्यासी अस्सी इक्यासी "
    "बयासी तिरासी चौरासी पचासी छियासी सत्तासी अट्ठासी नवासी नब्बे इक्यानवे बानवे तिरानवे चौरानवे पचानवे छियानवे "
    "सत्तानवे अट्ठानवे निन्यानवे").split()
_HI_UNITS = {w: i for i, w in enumerate(_HI_WORDS)}
_HI_UNITS.update({"पांच": 5, "छः": 6, "छे": 6})
# Romanised Hindi (Hinglish speech) for common numbers
_HINGLISH = {"ek": 1, "do": 2, "teen": 3, "char": 4, "chaar": 4, "paanch": 5, "panch": 5, "chhe": 6, "che": 6,
             "saat": 7, "aath": 8, "nau": 9, "das": 10, "gyarah": 11, "barah": 12, "baarah": 12, "terah": 13,
             "chaudah": 14, "pandrah": 15, "solah": 16, "satrah": 17, "atharah": 18, "atharah": 18,
             "unnis": 19, "bees": 20, "bais": 22, "baais": 22, "pachchis": 25, "pachees": 25, "tees": 30,
             "chalis": 40, "pachas": 50, "saath": 60, "sattar": 70, "assi": 80, "nabbe": 90}
_TA_UNITS = {"ஒன்று": 1, "ஒரு": 1, "இரண்டு": 2, "மூன்று": 3, "நான்கு": 4, "ஐந்து": 5, "ஆறு": 6, "ஏழு": 7,
             "எட்டு": 8, "ஒன்பது": 9, "பத்து": 10, "பூஜ்ஜியம்": 0, "சைபர்": 0}
_MULT = {"hundred": 100, "सौ": 100, "sau": 100, "thousand": 1000, "हज़ार": 1000, "हजार": 1000, "hazaar": 1000,
         "hazar": 1000, "ஆயிரம்": 1000, "lakh": 10**5, "lakhs": 10**5, "लाख": 10**5, "crore": 10**7,
         "करोड़": 10**7, "करोड": 10**7, "லட்சம்": 10**5, "கோடி": 10**7}
_FILLER = {"rupees", "rupee", "and", "only", "रुपये", "रुपए", "रूपये", "मात्र", "केवल", "rs", "ரூபாய்", "மட்டும்",
           "paise", "inr", "rupaye", "sirf"}


def _word_value(tok: str) -> Optional[int]:
    if tok in _EN_UNITS:
        return _EN_UNITS[tok]
    if tok in _EN_TENS:
        return _EN_TENS[tok]
    if tok in _HI_UNITS:
        return _HI_UNITS[tok]
    if tok in _HINGLISH:
        return _HINGLISH[tok]
    if tok in _TA_UNITS:
        return _TA_UNITS[tok]
    if tok.isdigit():
        return int(tok)
    return None


def words_to_amount(text: Optional[str], lang: str = "en") -> Optional[Decimal]:
    """'Twenty two thousand only' -> 22000; 'अठारह हज़ार रुपये मात्र' -> 18000. None if any token unknown."""
    if not text:
        return None
    s = to_ascii_digits(text).lower().replace("-", " ").replace(",", " ")
    s = re.sub(r"[^\w\sऀ-ॿ஀-௿]", " ", s)
    tokens = [t for t in s.split() if t not in _FILLER]
    if not tokens:
        return None
    total, current, seen = 0, 0, False
    for tok in tokens:
        if tok in _MULT:
            m = _MULT[tok]
            current = max(current, 1)
            if m == 100:
                current *= 100
            else:
                total += current * m
                current = 0
            seen = True
            continue
        v = _word_value(tok)
        if v is None:
            return None                  # unknown word: never guess
        current += v
        seen = True
    return Decimal(total + current).quantize(Decimal("0.01")) if seen else None


# --- dates ----------------------------------------------------------------
_MONTHS = {m: i + 1 for i, m in enumerate(
    "jan feb mar apr may jun jul aug sep oct nov dec".split())}
_MONTHS.update({"sept": 9, "जनवरी": 1, "फरवरी": 2, "मार्च": 3, "अप्रैल": 4, "मई": 5, "जून": 6, "जुलाई": 7,
                "अगस्त": 8, "सितंबर": 9, "सितम्बर": 9, "अक्टूबर": 10, "नवंबर": 11, "नवम्बर": 11, "दिसंबर": 12,
                "दिसम्बर": 12, "ஜனவரி": 1, "பிப்ரவரி": 2, "மார்ச்": 3, "ஏப்ரல்": 4, "மே": 5, "ஜூன்": 6,
                "ஜூலை": 7, "ஆகஸ்ட்": 8, "செப்டம்பர்": 9, "அக்டோபர்": 10, "நவம்பர்": 11, "டிசம்பர்": 12})


def _year(y: str) -> int:
    n = int(y)
    return n + 2000 if n < 100 else n


def parse_date(text: Optional[str]) -> tuple[Optional[date], bool]:
    """Day-first (India). Returns (date, ambiguous). Ambiguous when day and month both <= 12
    in a purely numeric format and they differ."""
    if not text:
        return None, False
    s = to_ascii_digits(text).strip().lower()
    s = re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", s)
    try:
        m = re.fullmatch(r"(\d{4})-(\d{1,2})-(\d{1,2})", s)
        if m:                            # ISO is unambiguous
            return date(int(m[1]), int(m[2]), int(m[3])), False
        m = re.fullmatch(r"(\d{1,2})[./\-](\d{1,2})[./\-](\d{2,4})", s)
        if m:
            d, mo, y = int(m[1]), int(m[2]), _year(m[3])
            amb = d <= 12 and mo <= 12 and d != mo
            return date(y, mo, d), amb
        m = re.fullmatch(r"(\d{1,2})[\s\-/.]*([^\d\s\-/.,]+)[\s\-/.,]*(\d{2,4})", s)
        if m:
            word = m[2].strip(".")
            mo = _MONTHS.get(word) or _MONTHS.get(word[:3])
            if mo:
                return date(_year(m[3]), mo, int(m[1])), False
        m = re.fullmatch(r"([^\d\s]+)[\s.]+(\d{1,2}),?\s+(\d{2,4})", s)
        if m:
            mo = _MONTHS.get(m[1]) or _MONTHS.get(m[1][:3])
            if mo:
                return date(_year(m[3]), mo, int(m[2])), False
    except ValueError:
        return None, False
    return None, False


# --- names ----------------------------------------------------------------
_HONORIFICS = {"sri", "shri", "shree", "sree", "m/s", "ms", "messrs", "mr", "mrs", "smt", "thiru", "tvl"}
_SUFFIXES = {"pvt", "private", "ltd", "limited", "llp", "co", "company", "and", "&", "inc", "enterprises",
             "traders", "trading", "agencies", "works", "the"}


def clean_name(name: Optional[str]) -> str:
    if not name:
        return ""
    s = unicodedata.normalize("NFKC", name).lower()
    s = s.replace("m/s", " ").replace("&", " ")
    s = re.sub(r"[^\w\s]", " ", s)
    toks = [t for t in s.split() if t not in _HONORIFICS and t not in _SUFFIXES]
    return " ".join(toks)


def _phonetic(tok: str) -> str:
    t = tok
    for a, b in (("sh", "s"), ("ksh", "ks"), ("th", "t"), ("dh", "d"), ("bh", "b"), ("ph", "f"),
                 ("w", "v"), ("ee", "i"), ("oo", "u"), ("aa", "a"), ("z", "j"), ("y", "i")):
        t = t.replace(a, b)
    t = t[0] + re.sub(r"[aeiou]", "", t[1:]) if t else t
    return re.sub(r"(.)\1+", r"\1", t)


def vendor_key(name: Optional[str]) -> str:
    """Phonetic key so 'Venkateshwara' and 'Venkateswara' collapse. Latin script only;
    native-script names should be transliterated first (UNVERIFIED which transliterator)."""
    return " ".join(_phonetic(t) for t in clean_name(name).split())


# --- invoice numbers ------------------------------------------------------
def norm_invoice_number(text: Optional[str]) -> Optional[str]:
    """Strip prefixes, separators, leading zeros and case, but KEEP the financial year.
    'KE/0312/2026-27' -> 'KE312FY2627'; 'ke-312/26-27' -> 'KE312FY2627'."""
    if not text:
        return None
    s = to_ascii_digits(text).upper().strip()
    fy = ""
    m = re.search(r"(?:20)?(\d{2})\s*[-/]\s*(?:20)?(\d{2})\s*$", s)
    if m and (int(m[2]) - int(m[1])) % 100 == 1:
        fy = f"FY{m[1]}{m[2]}"
        s = s[: m.start()]
    s = re.sub(r"^(INVOICE|INV|BILL|NO|NUMBER)[\s.:#\-/]*", "", s)
    s = re.sub(r"[^A-Z0-9]", " ", s)
    parts = [(p.lstrip("0") or "0") if p.isdigit() else p for p in s.split()]
    return "".join(parts) + fy
