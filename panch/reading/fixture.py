"""Reading: Vision Extract output (cached for the demo) -> Invoice. Extract, don't translate:
money fields are canonicalised in code and the native string kept as evidence."""
from __future__ import annotations

import hashlib
import json
from decimal import Decimal
from typing import Optional

from panch.models import Invoice, LineItem
from panch.normalise import norm_invoice_number, parse_amount, parse_date, vendor_key, words_to_amount


def _amt(v) -> Optional[Decimal]:
    a = parse_amount(v) if v not in (None, "") else None
    return a.quantize(Decimal("0.01")) if a is not None else None


def invoice_from_extract(raw: dict) -> Invoice:
    lines = []
    for ln in raw.get("line_items") or []:
        qty, rate, amount = _amt(ln.get("qty")), _amt(ln.get("rate")), _amt(ln.get("amount"))
        lines.append(LineItem(item_key=ln.get("item", ""), qty=qty or Decimal("0"), rate=rate or Decimal("0"),
                              amount=amount or Decimal("0"), discount=_amt(ln.get("discount")) or Decimal("0")))
    d, amb = parse_date(raw.get("invoice_date"))
    name_latin = raw.get("vendor_name_latin") or raw.get("vendor_name") or ""
    lang = raw.get("language", "en")
    stable = dict(raw.get("stable") or {})
    for f in ("total", "subtotal"):          # a value we could not parse is never silently accepted
        if raw.get(f) not in (None, "") and _amt(raw.get(f)) is None:
            stable[f] = False
    if raw.get("invoice_date") and d is None:
        stable["date"] = False
    return Invoice(
        id=raw["id"],
        source_hash=hashlib.sha256(json.dumps(raw, sort_keys=True, ensure_ascii=False).encode()).hexdigest()[:16],
        vendor_name_raw=raw.get("vendor_name") or "",
        vendor_key=vendor_key(name_latin),
        gstin=(raw.get("vendor_gstin") or None),
        number_raw=raw.get("invoice_no"),
        number_norm=norm_invoice_number(raw.get("invoice_no")),
        date=d, date_ambiguous=amb,
        lines=lines,
        subtotal=_amt(raw.get("subtotal")),
        tax=_amt(raw.get("tax_total")),
        total=_amt(raw.get("total")),
        words_amount=words_to_amount(raw.get("amount_in_words"), lang),
        payee_name=raw.get("payee_name"),
        account_number=raw.get("bank_account"),
        ifsc=(raw.get("ifsc") or "").upper() or None,
        stable=stable,
        raw_native={k: str(raw[k]) for k in ("vendor_name", "invoice_no", "invoice_date", "total", "amount_in_words")
                    if raw.get(k) is not None},
        language=lang,
        po_number=raw.get("po_no"),
        buyer_gstin=raw.get("buyer_gstin"),
        cgst=_amt(raw.get("cgst")), sgst=_amt(raw.get("sgst")), igst=_amt(raw.get("igst")),
        vendor_phone_on_invoice=raw.get("vendor_phone"),
    )
