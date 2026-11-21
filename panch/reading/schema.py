"""Extract schema for Sarvam Document AI (ARCHITECTURE section A field list).

Every field is a STRING on purpose. Asking for `number` makes the model
convert '௧௨,௪௦௦' or '1,25,000/-' itself and hand back a JSON float: we lose
the native string (the evidence of record) and put a float in the money
path. We read text; module B converts it.

Bump SCHEMA_VERSION whenever this changes so cached reads are not reused.
"""
from __future__ import annotations

import json

SCHEMA_VERSION = "pr1-v1"

_AS_PRINTED = (
    " Copy it exactly as printed, character for character, in the script it is"
    " written in (keep Tamil or Devanagari digits, commas, currency marks and"
    " '/-'). Do not translate, convert, round, compute or correct anything."
    " Leave it empty if it is not on the document or not legible. Never guess."
)


def _s(desc: str) -> dict:
    return {"type": "string", "description": desc + _AS_PRINTED}


EXTRACT_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "invoice_no": _s("Invoice or bill number as printed, including any prefix and financial year, e.g. 'INV-0042' or '42/2025-26'."),
        "invoice_date": _s("Invoice date as printed, near the invoice number."),
        "vendor_name": _s("Name of the seller / supplier issuing the invoice, usually at the top. Not the buyer."),
        "vendor_gstin": _s("Seller's 15-character GSTIN."),
        "buyer_gstin": _s("Buyer's / recipient's 15-character GSTIN, if printed."),
        "po_no": _s("Purchase order, delivery challan or order reference number, if printed."),
        "delivery_date": _s("Delivery or challan date, if printed separately from the invoice date."),
        "line_items": {
            "type": "array",
            "description": "One entry per item row in the item table, top to bottom. Skip subtotal and tax rows.",
            "items": {
                "type": "object",
                "description": "One item row.",
                "properties": {
                    "item": _s("Item description for this row."),
                    "qty": _s("Quantity for this row, with its unit if printed."),
                    "rate": _s("Unit price / rate for this row."),
                    "discount": _s("Discount for this row, if a discount column exists."),
                    "amount": _s("Line amount for this row, as printed in the amount column."),
                },
            },
        },
        "subtotal": _s("Taxable value / subtotal before tax, as printed."),
        "discount": _s("Invoice-level discount, if printed separately from the rows."),
        "cgst": _s("CGST amount in figures."),
        "sgst": _s("SGST amount in figures."),
        "igst": _s("IGST amount in figures."),
        "tax_total": _s("Total tax amount in figures, only if printed as its own line."),
        "total": _s("Grand total / invoice total in figures, usually bottom right, INR."),
        "amount_in_words": _s("Total amount written in words, e.g. 'Rupees Twelve Thousand Only'."),
        "account_holder_name": _s("Bank account holder / beneficiary name in the bank details section."),
        "bank_account": _s("Bank account number in the bank details section."),
        "ifsc": _s("Bank IFSC code in the bank details section."),
        "upi_id": _s("UPI ID, if printed."),
        "vendor_phone": _s("Seller's phone number printed on the invoice."),
    },
}

# Field names in the schema that map one-to-one to money values.
MONEY_FIELDS = ("subtotal", "discount", "cgst", "sgst", "igst", "tax_total", "total")
ID_FIELDS = ("vendor_gstin", "buyer_gstin", "ifsc")
TEXT_FIELDS = ("vendor_name", "account_holder_name", "po_no", "upi_id", "vendor_phone")
LINE_FIELDS = ("item", "qty", "rate", "discount", "amount")
ALL_FIELDS = tuple(EXTRACT_SCHEMA["properties"].keys())


def schema_json() -> str:
    return json.dumps(EXTRACT_SCHEMA, ensure_ascii=False, sort_keys=True)
