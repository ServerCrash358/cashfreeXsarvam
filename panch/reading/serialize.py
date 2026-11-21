"""Invoice <-> JSON, for handing real reads to PR 2 without calling Sarvam.

Decimals travel as strings and dates as ISO strings, so nothing becomes a
float. The full account number is left out unless asked for.
"""
from __future__ import annotations

import dataclasses
from datetime import date
from decimal import Decimal
from typing import Any

from ..models import Invoice, LineItem
from .mapping import mask_account

_DECIMAL_ATTRS = {"subtotal", "tax", "total", "words_amount", "discount", "cgst", "sgst", "igst"}


def invoice_to_dict(inv: Invoice, *, include_account: bool = False) -> dict:
    d: dict[str, Any] = {}
    for f in dataclasses.fields(inv):
        v = getattr(inv, f.name)
        if f.name == "account_number":
            d["account_number"] = v if include_account else None
            d["account_last4_masked"] = mask_account(v)
        elif f.name == "lines":
            d["lines"] = [{"item_key": l.item_key, "qty": str(l.qty), "rate": str(l.rate),
                           "amount": str(l.amount)} for l in v]
        elif isinstance(v, Decimal):
            d[f.name] = str(v)
        elif isinstance(v, date):
            d[f.name] = v.isoformat()
        else:
            d[f.name] = v
    return d


def invoice_from_dict(d: dict) -> Invoice:
    kw = {k: v for k, v in d.items() if k in {f.name for f in dataclasses.fields(Invoice)}}
    for k in _DECIMAL_ATTRS:
        if kw.get(k) is not None:
            kw[k] = Decimal(kw[k])
    if kw.get("date"):
        kw["date"] = date.fromisoformat(kw["date"])
    kw["lines"] = [LineItem(item_key=l["item_key"], qty=Decimal(l["qty"]), rate=Decimal(l["rate"]),
                            amount=Decimal(l["amount"])) for l in kw.get("lines", [])]
    kw.setdefault("account_number", None)
    return Invoice(**kw)
