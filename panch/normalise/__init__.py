"""Module B: normalisation. Every function here is pure (no I/O, no network),
deterministic, and returns None instead of guessing.

Interface (ARCHITECTURE.md section 7):
    parse_amount(text) -> Decimal | None
    words_to_amount(text, lang) -> Decimal | None
    parse_date(text) -> tuple[date | None, bool]
    vendor_key(name) -> str
    norm_invoice_number(text) -> str
"""
from .amounts import parse_amount, parse_quantity
from .dates import parse_date
from .invoice_number import norm_invoice_number
from .names import vendor_key, vendor_translit
from .numerals import (
    canon_account,
    canon_id,
    canon_phone,
    dominant_script,
    has_traditional_tamil_numerals,
    to_ascii_digits,
)
from .words import words_to_amount

__all__ = [
    "parse_amount", "parse_quantity", "words_to_amount", "parse_date",
    "vendor_key", "vendor_translit", "norm_invoice_number",
    "canon_account", "canon_id", "canon_phone", "dominant_script",
    "has_traditional_tamil_numerals", "to_ascii_digits",
]
