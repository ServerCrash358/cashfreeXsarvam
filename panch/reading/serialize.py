"""Invoice <-> JSON, for handing real reads to PR 2 without calling Sarvam.

Decimals travel as strings and dates as ISO strings, so nothing becomes a
float. The full account number is left out unless asked for.

Field names come from panch/models.py at runtime (PR 2 owns it), so this
works whatever fields Invoice and LineItem have, dataclass or pydantic v2.
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from ..models import Invoice, LineItem
from .mapping import make_invoice, make_line_item, mask_account, model_fields

_DECIMAL_ATTRS = {"subtotal", "tax", "total", "words_amount", "discount", "cgst", "sgst", "igst"}
_LINE_DECIMAL_ATTRS = {"qty", "rate", "amount", "discount"}


def _line_to_dict(line: LineItem) -> dict:
    out = {}
    for name in model_fields(type(line)):
        v = getattr(line, name)
        out[name] = str(v) if isinstance(v, Decimal) else v
    return out


def invoice_to_dict(inv: Invoice, *, include_account: bool = False) -> dict:
    d: dict[str, Any] = {}
    for name in model_fields(type(inv)):
        v = getattr(inv, name)
        if name == "account_number":
            d["account_number"] = v if include_account else None
            d["account_last4_masked"] = mask_account(v)
        elif name == "lines":
            d["lines"] = [_line_to_dict(l) for l in v]
        elif isinstance(v, Decimal):
            d[name] = str(v)
        elif isinstance(v, date):
            d[name] = v.isoformat()
        else:
            d[name] = v
    return d


def invoice_from_dict(d: dict) -> Invoice:
    kw = {k: v for k, v in d.items() if k in model_fields(Invoice)}
    for k in _DECIMAL_ATTRS:
        if kw.get(k) is not None:
            kw[k] = Decimal(kw[k])
    if kw.get("date"):
        kw["date"] = date.fromisoformat(kw["date"])
    kw["lines"] = [
        make_line_item(**{k: Decimal(v) if k in _LINE_DECIMAL_ATTRS and v is not None else v
                          for k, v in l.items()})
        for l in kw.get("lines", [])
    ]
    kw.setdefault("account_number", None)
    return make_invoice(**kw)
