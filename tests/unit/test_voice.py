"""Voice layer: digit extraction (U-VEN-9 part), templates (U-DEC-6 part), formatting."""
from decimal import Decimal

import pytest

from panch.voice.numbers import consent, extract_digits, tokenize
from panch.voice.templates import (LANGS, TemplateMissing, available_keys, format_inr,
                                   placeholders, render)

REASON_KEYS = {
    "arith_line", "arith_subtotal", "arith_total", "arith_words", "dup_exact", "dup_fuzzy",
    "bank_invalid", "name_mismatch", "account_shared", "account_changed", "callback_mismatch",
    "callback_no_answer", "vendor_unverifiable", "low_confidence_read", "gstin_format",
    "ifsc_format", "date_implausible", "tax_rate", "over_limit", "cash_deferred",
    "approval_invalid", "pay_ready", "dup_number", "arith_gst_split", "new_vendor",
}
FLOW_KEYS = {
    "approval_prompt", "approval_ok", "approval_retry", "approval_pin", "approval_second",
    "approval_authorised", "payment_readback", "callback_prompt", "callback_ok",
    "callback_owner_confirm", "payout_success", "payout_failed", "payout_reversed", "payout_pending",
}


@pytest.mark.parametrize("text,expected", [
    ("four seven two nine", "4729"),
    ("4 7 2 9", "4729"),
    ("4729", "4729"),
    ("4-7-2-9", "4729"),
    ("चार सात दो नौ", "4729"),
    ("char saat do nau", "4729"),
    ("நாலு ஏழு இரண்டு ஒன்பது", "4729"),
    ("நான்கு ஏழு ரெண்டு ஒன்பது", "4729"),
    ("naalu ezhu rendu onbadhu", "4729"),
    ("௪௭௨௯", "4729"),
    ("४७२९", "4729"),
    ("last digits are four seven two nine", "4729"),
    ("0471", "0471"),
    ("025", "025"),
    ("zero four seven one", "0471"),
])
def test_u_ven_9_extract_digits(text, expected):
    assert extract_digits(text, "ta") == expected


def test_weak_words_are_not_digits_alone():
    assert extract_digits("I want to go for lunch", "en") == ""
    assert extract_digits("one two three four", "en") == "1234"


def test_consent():
    assert consent(tokenize("haan ji")) == "yes"
    assert consent(tokenize("ஆம்")) == "yes"
    assert consent(tokenize("nahi")) == "no"
    assert consent(tokenize("haan... nahi")) == "ambiguous"
    assert consent(tokenize("22,000")) == "none"


@pytest.mark.parametrize("value,expected", [
    (Decimal("22000"), "22,000"),
    (Decimal("125000"), "1,25,000"),
    (Decimal("12390.50"), "12,390.50"),
    (Decimal("4000"), "4,000"),
    (Decimal("999"), "999"),
    (Decimal("10000000"), "1,00,00,000"),
])
def test_format_inr(value, expected):
    assert format_inr(value) == expected


@pytest.mark.parametrize("lang", LANGS)
def test_u_dec_6_every_key_exists_in_every_language(lang):
    missing = (REASON_KEYS | FLOW_KEYS) - available_keys(lang)
    assert not missing, f"{lang} missing {sorted(missing)}"


@pytest.mark.parametrize("key", sorted(REASON_KEYS | FLOW_KEYS))
def test_placeholders_match_across_languages(key):
    en = placeholders(key, "en")
    for lang in LANGS:
        assert placeholders(key, lang) == en, (key, lang)


def test_render_never_falls_back_to_english():
    with pytest.raises(TemplateMissing):
        render("no_such_key", "ta")


def test_render_refuses_half_filled_sentence():
    with pytest.raises(KeyError):
        render("approval_prompt", "hi", count=2)


def test_render_formats_decimals():
    assert "22,000" in render("approval_prompt", "hi", count=2, total=Decimal("22000"), code="4-7-2")
