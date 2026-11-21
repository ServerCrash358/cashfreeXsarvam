"""UNIT_TESTS.md section 2, module B. Offline, pure."""
from datetime import date
from decimal import Decimal

import pytest

from panch.normalise import (
    canon_account,
    canon_id,
    has_traditional_tamil_numerals,
    norm_invoice_number,
    parse_amount,
    parse_date,
    parse_quantity,
    vendor_key,
    words_to_amount,
)


# U-NORM-1..4 ---------------------------------------------------------------
@pytest.mark.parametrize(
    "text, expected",
    [
        ("௧௨,௪௦௦", Decimal("12400")),          # U-NORM-1 Tamil digits
        ("१२,४००", Decimal("12400")),           # U-NORM-2 Devanagari digits
        ("₹ 1,25,000.00/-", Decimal("125000.00")),  # U-NORM-3
        ("1.25 lakh", Decimal("125000")),       # U-NORM-4
        ("Rs.12,390.00", Decimal("12390.00")),
        ("INR 125,000", Decimal("125000")),
        ("ரூ. 4,000", Decimal("4000")),
        ("रु 18,000/-", Decimal("18000")),
        ("2 crore", Decimal("20000000")),
        ("12400", Decimal("12400")),
    ],
)
def test_parse_amount(text, expected):
    got = parse_amount(text)
    assert got == expected and isinstance(got, Decimal)


@pytest.mark.parametrize("text", ["12,40", "12.345", "twelve", "12 apples", "", None, "1,2,3"])
def test_parse_amount_refuses_to_guess(text):
    assert parse_amount(text) is None


def test_parse_quantity_drops_units():
    assert parse_quantity("10 Nos") == Decimal("10")
    assert parse_quantity("2.5 kg") == Decimal("2.5")
    assert parse_quantity("10 x 4") is None


# U-NORM-5..9 ---------------------------------------------------------------
@pytest.mark.parametrize(
    "text, lang, expected",
    [
        ("Twelve Thousand Three Hundred Ninety Only", "en", Decimal("12390")),  # U-NORM-5
        ("One Lakh Twenty Five Thousand", "en", Decimal("125000")),            # U-NORM-6
        ("बारह हज़ार चार सौ", "hi", Decimal("12400")),                           # U-NORM-7
        ("एक लाख पच्चीस हज़ार", "hi", Decimal("125000")),                        # U-NORM-8
        ("பன்னிரண்டாயிரத்து நானூறு", "ta", Decimal("12400")),                     # U-NORM-9 native-check
        ("ஒரு லட்சம் இருபத்தைந்து ஆயிரம்", "ta", Decimal("125000")),              # brief section 7
        ("Rupees Twenty-Two Thousand Only", "en", Decimal("22000")),
        ("Twelve Thousand and Fifty Paise Only", "en", Decimal("12000.50")),
        ("Fourty Thousand", "en", Decimal("40000")),
        ("ஐயாயிரம்", "ta", Decimal("5000")),
        ("நூற்றைம்பது", "ta", Decimal("150")),
        ("இருநூற்று முப்பத்தைந்து", "ta", Decimal("235")),
        ("Twelve Thousand", "ta-IN", Decimal("12000")),  # English words on a Tamil invoice
    ],
)
def test_words_to_amount(text, lang, expected):
    assert words_to_amount(text, lang) == expected


@pytest.mark.parametrize(
    "text, lang",
    [
        ("five twenty", "en"),             # impossible order
        ("thousand lakh", "en"),
        ("twelve thousand bananas", "en"),
        ("", "en"),
        (None, "en"),
    ],
)
def test_words_to_amount_refuses_to_guess(text, lang):
    assert words_to_amount(text, lang) is None


# U-NORM-10..11 -------------------------------------------------------------
@pytest.mark.parametrize("text", ["03-11-2026", "3 Nov 2026", "2026-11-03", "3rd November 2026",
                                  "Nov 3, 2026", "03-Nov-26", "௦௩-௧௧-௨௦௨௬", "3 நவம்பர் 2026",
                                  "3 नवंबर 2026"])
def test_parse_date_formats(text):
    d, _amb = parse_date(text)
    assert d == date(2026, 11, 3)


def test_parse_date_two_digit_year_is_ambiguous():
    assert parse_date("03/11/26") == (date(2026, 11, 3), True)   # U-NORM-11


def test_parse_date_not_ambiguous_when_swap_impossible():
    assert parse_date("15/11/26") == (date(2026, 11, 15), False)


def test_parse_date_invalid():
    assert parse_date("31-02-2026") == (None, False)
    assert parse_date("sometime") == (None, False)


# U-NORM-12 -----------------------------------------------------------------
def test_traditional_tamil_numeral_flagged_not_parsed():
    assert has_traditional_tamil_numerals("௰")
    assert parse_amount("௰") is None


# U-NORM-13 -----------------------------------------------------------------
def test_vendor_key_collapses_variants():
    a = vendor_key("M/s. Sri Murugan Hardwares Pvt Ltd")
    assert a == vendor_key("Sri Murugan Hardware")
    assert a == vendor_key("ஸ்ரீ முருகன் ஹார்ட்வேர்ஸ்")
    assert a == vendor_key("श्री मुरुगन हार्डवेयर्स")
    assert vendor_key("Venkateshwara Traders") == vendor_key("Venkateswara")


def test_vendor_key_keeps_different_names_apart():
    assert vendor_key("Sri Murugan Hardware") != vendor_key("Lakshmi Textiles")


# U-NORM-14..15 -------------------------------------------------------------
def test_invoice_number_same_norm():
    assert norm_invoice_number("INV-0042") == norm_invoice_number("inv 42") == norm_invoice_number("42") == "42"


def test_invoice_number_keeps_financial_year():
    a = norm_invoice_number("42/2025-26")
    b = norm_invoice_number("42/2026-27")
    assert a != b
    assert a == norm_invoice_number("INV/42/FY25-26")
    assert a != norm_invoice_number("42")


def test_invoice_number_keeps_series():
    assert norm_invoice_number("A-42") != norm_invoice_number("B-42")


# U-NORM-16 -----------------------------------------------------------------
def test_ids_native_digits_to_ascii_otherwise_untouched():
    assert canon_id("௨௯AAICP௨௯௧௨R௧ZR") == "29AAICP2912R1ZR"
    assert canon_id("YESB०००0262") == "YESB0000262"
    assert canon_account("०२६२ ९१८० ०००१ १९१") == "026291800001191"
    assert canon_id("27ABCFGH5678D1Z") == "27ABCFGH5678D1Z"   # malformed stays malformed


# U-NORM-17 -----------------------------------------------------------------
def test_transliteration_deterministic():
    name = "ஸ்ரீ வெங்கடேஸ்வரா ஸ்டோர்ஸ்"
    assert vendor_key(name) == vendor_key(name)
