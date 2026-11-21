"""Vision output (one JobOutput per variant) -> Invoice. Pure: no I/O.

Key names in `stable`, `confidence`, `raw_native` and `pages` are the
Invoice attribute names (e.g. "total", "gstin", "number", "date", "lines"),
so PR 2 can do `inv.stable.get("total")`. Line fields in raw_native are
"lines[0].qty" etc.

Rules (brief section 5):
- raw_native holds the string exactly as read, from the primary variant.
- stable[x] is True only when every usable variant agrees after
  normalisation AND the value parsed AND (if configured) confidence is high
  enough. When variants disagree, the primary ('orig') value is kept and
  stable[x] is False, which is visible and routes to ASK. Nothing is picked
  silently and nothing is guessed: unreadable is None.
- Account numbers are masked to the last four everywhere except
  Invoice.account_number (raw_native and artifacts included).
"""
from __future__ import annotations

import dataclasses
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Optional

# Submodules only: panch/normalise/__init__.py and panch/reading/__init__.py
# belong to main and PR 1 must not depend on what they export.
from ..models import Invoice, LineItem
from ..normalise.amounts import parse_amount, parse_quantity
from ..normalise.dates import parse_date
from ..normalise.invoice_number import norm_invoice_number
from ..normalise.names import vendor_key
from ..normalise.numerals import canon_account, canon_id, canon_phone, has_traditional_tamil_numerals, nfc
from ..normalise.translit import to_latin
from ..normalise.words import words_to_amount
from .schema import LINE_FIELDS, MONEY_FIELDS
from .vision import JobOutput


# --------------------------------------------------------------- models
# panch/models.py is owned by PR 2 and may drift from ARCHITECTURE section 7,
# so PR 1 never calls Invoice(...) / LineItem(...) directly.
def model_fields(cls) -> dict[str, bool]:
    """Constructor field names of a dataclass or pydantic v2 model -> is it required."""
    if dataclasses.is_dataclass(cls):
        return {f.name: f.default is dataclasses.MISSING and f.default_factory is dataclasses.MISSING
                for f in dataclasses.fields(cls) if f.init}
    pyd = getattr(cls, "model_fields", None)
    if isinstance(pyd, dict):
        return {name: info.is_required() for name, info in pyd.items()}
    raise TypeError(f"{cls!r} is neither a dataclass nor a pydantic v2 model")


def make_model(cls, **values):
    """cls(**values) keeping only fields cls has; a required field we don't know gets None."""
    fields = model_fields(cls)
    kw = {k: v for k, v in values.items() if k in fields}
    kw.update({name: None for name, required in fields.items() if required and name not in kw})
    return cls(**kw)


def make_invoice(**values) -> Invoice:
    return make_model(Invoice, **values)


def make_line_item(**values) -> LineItem:
    return make_model(LineItem, **values)

FIELD_TO_ATTR = {
    "invoice_no": "number", "invoice_date": "date", "vendor_name": "vendor_name",
    "vendor_gstin": "gstin", "buyer_gstin": "buyer_gstin", "po_no": "po_number",
    "delivery_date": "delivery_date", "subtotal": "subtotal", "discount": "discount",
    "cgst": "cgst", "sgst": "sgst", "igst": "igst", "tax_total": "tax", "total": "total",
    "amount_in_words": "words_amount", "account_holder_name": "payee_name",
    "bank_account": "account_number", "ifsc": "ifsc", "upi_id": "upi_id",
    "vendor_phone": "vendor_phone_on_invoice",
}
SECRET_ATTRS = {"account_number"}


def mask_account(value: Optional[str]) -> Optional[str]:
    if not value:
        return value
    digits = "".join(ch for ch in value if ch.isalnum())
    return "XXXX" + digits[-4:] if len(digits) > 4 else "XXXX"


@dataclass
class FieldValue:
    raw: Optional[str]
    value: Any = None
    compare: Any = None
    parse_failed: bool = False
    traditional: bool = False
    coerced: bool = False                # Vision returned a number, not text
    confidence: Optional[float] = None
    page: Optional[int] = None
    region: Optional[dict] = None


@dataclass
class LineRead:
    raw: dict
    item_key: str
    qty: Optional[Decimal]
    rate: Optional[Decimal]
    discount: Optional[Decimal]
    amount: Optional[Decimal]
    complete: bool
    page: Optional[int] = None
    confidence: Optional[float] = None


@dataclass
class VariantRead:
    variant: str
    status: str
    fields: dict[str, FieldValue] = field(default_factory=dict)
    lines: list[LineRead] = field(default_factory=list)
    pages_total: Optional[int] = None

    @property
    def lines_compare(self):
        return tuple(sorted(((l.qty, l.rate, l.discount, l.amount) for l in self.lines),
                            key=lambda t: tuple(str(x) for x in t)))


# ------------------------------------------------------------ helpers
def _raw(v: Any) -> tuple[Optional[str], bool]:
    """(text or None, coerced). Never invents text for dicts / lists."""
    if v is None:
        return None, False
    if isinstance(v, str):
        s = nfc(v).strip()
        return (s or None), False
    if isinstance(v, bool):
        return None, False
    if isinstance(v, (int, float)):
        return repr(v), True
    return None, False


def _ann_leaf(a: Any) -> tuple[Optional[float], Optional[int], Optional[dict]]:
    """annotations leaf -> (confidence, page, region). Shape is UNVERIFIED until
    the probe: {"confidence": 0.93, "sources": [{"input_page": 1, "region": {...}}]}."""
    if not isinstance(a, dict):
        return None, None, None
    conf = a.get("confidence")
    conf = float(conf) if isinstance(conf, (int, float)) and not isinstance(conf, bool) else None
    page = region = None
    srcs = a.get("sources")
    if isinstance(srcs, dict):
        srcs = [srcs]
    if isinstance(srcs, list) and srcs and isinstance(srcs[0], dict):
        s0 = srcs[0]
        p = s0.get("input_page", s0.get("source_page", s0.get("page")))
        page = int(p) if isinstance(p, (int, float)) and not isinstance(p, bool) else None
        region = s0.get("region") if isinstance(s0.get("region"), dict) else None
    return conf, page, region


def _canon(name: str, raw: Optional[str]) -> tuple[Any, Any, bool]:
    """(value, comparison key, parse_failed)."""
    if raw is None:
        return None, None, False
    if name in MONEY_FIELDS:
        v = parse_amount(raw)
        return v, v, v is None
    if name in ("invoice_date", "delivery_date"):
        d, amb = parse_date(raw)
        return (d, amb), d, d is None
    if name == "invoice_no":
        n = norm_invoice_number(raw) or None
        return n, n, n is None
    if name == "vendor_name":
        k = vendor_key(raw) or None
        return k, k, k is None
    if name in ("vendor_gstin", "buyer_gstin", "ifsc"):
        v = canon_id(raw)
        return v, v, v is None
    if name == "bank_account":
        v = canon_account(raw)
        return v, v, v is None
    if name == "amount_in_words":
        v = words_to_amount(raw)
        return v, v, v is None
    if name == "vendor_phone":
        v = canon_phone(raw)
        return v, v, v is None
    v = " ".join(raw.split())
    return v, v.casefold(), False


def _item_key(text: Optional[str]) -> str:
    if not text:
        return ""
    return " ".join(re.findall(r"[a-z0-9]+", to_latin(nfc(text))))


def read_variant(variant: str, out: JobOutput) -> VariantRead:
    res = out.result if isinstance(out.result, dict) else {}
    ann = out.annotations if isinstance(out.annotations, dict) else {}
    vr = VariantRead(variant=variant, status=out.status,
                     pages_total=(out.usage or {}).get("pages_total"))
    for name, attr in FIELD_TO_ATTR.items():
        raw, coerced = _raw(res.get(name))
        value, cmp, failed = _canon(name, raw)
        conf, page, region = _ann_leaf(ann.get(name))
        vr.fields[attr] = FieldValue(
            raw=raw, value=value, compare=cmp, parse_failed=failed,
            traditional=has_traditional_tamil_numerals(raw), coerced=coerced,
            confidence=conf, page=page, region=region,
        )
    rows = res.get("line_items") or []
    row_anns = ann.get("line_items") if isinstance(ann.get("line_items"), list) else []
    if isinstance(rows, list):
        for i, row in enumerate(rows):
            if not isinstance(row, dict):
                continue
            raws = {k: _raw(row.get(k))[0] for k in LINE_FIELDS}
            if not any(raws.values()):
                continue
            qty = parse_quantity(raws["qty"])
            rate = parse_amount(raws["rate"])
            disc = parse_amount(raws["discount"])
            amt = parse_amount(raws["amount"])
            complete = (qty is not None and rate is not None and amt is not None
                        and (raws["discount"] is None or disc is not None))
            rann = row_anns[i] if i < len(row_anns) and isinstance(row_anns[i], dict) else {}
            conf, page, _ = _ann_leaf(rann.get("amount"))
            vr.lines.append(LineRead(raw=raws, item_key=_item_key(raws["item"]), qty=qty, rate=rate,
                                     discount=disc, amount=amt, complete=complete,
                                     page=page, confidence=conf))
    return vr


def _display(attr: str, v: FieldValue):
    if attr in SECRET_ATTRS:
        return mask_account(v.value)
    val = v.value
    if isinstance(val, tuple):
        return [str(x) if x is not None else None for x in val]
    return None if val is None else str(val)


# --------------------------------------------------------------- build
def build_invoice(
    *,
    source_hash: str,
    reads: list[VariantRead],
    language: Optional[str],
    single_page: bool,
    min_confidence: Optional[float] = None,
) -> tuple[Invoice, dict]:
    """reads[0] is the primary variant. Returns (Invoice, artifacts dict)."""
    inv_id = "inv_" + source_hash[:16]
    artifacts: dict = {"invoice_id": inv_id, "source_hash": source_hash,
                       "variants_read": [r.variant for r in reads], "fields": {}, "lines": {}, "crops": {}}

    if not reads:
        stable = {a: False for a in FIELD_TO_ATTR.values()}
        stable["lines"] = False
        inv = make_invoice(
            id=inv_id, source_hash=source_hash, vendor_name_raw="", vendor_key="", gstin=None,
            number_raw=None, number_norm=None, date=None, date_ambiguous=False, lines=[],
            subtotal=None, tax=None, total=None, words_amount=None, payee_name=None,
            account_number=None, ifsc=None, stable=stable, language=language,
        )
        artifacts["no_usable_read"] = True
        return inv, artifacts

    primary = reads[0]
    partial = any(r.status == "partially_completed" for r in reads)
    stable: dict[str, bool] = {}
    confidence: dict[str, float] = {}
    raw_native: dict[str, str] = {}
    pages: dict[str, int] = {}

    for attr in FIELD_TO_ATTR.values():
        vals = [r.fields[attr] for r in reads]
        p = vals[0]
        reasons = []
        if any(v.compare != p.compare for v in vals[1:]):
            reasons.append("variants_disagree")
        if p.parse_failed:
            reasons.append("traditional_tamil_numerals" if p.traditional else "unparseable")
        if p.coerced:
            reasons.append("returned_as_number")
        if min_confidence is not None and p.confidence is not None and p.confidence < min_confidence:
            reasons.append("low_confidence")
        if partial and p.raw is None:
            reasons.append("partial_job")
        stable[attr] = not reasons
        if p.confidence is not None:
            confidence[attr] = p.confidence
        if p.raw is not None:
            raw_native[attr] = mask_account(p.raw) if attr in SECRET_ATTRS else p.raw
        page = p.page if p.page is not None else (1 if single_page else None)
        if page is not None and p.raw is not None:
            pages[attr] = page
        artifacts["fields"][attr] = {
            "page": page, "region": p.region, "confidence": p.confidence,
            "unstable_reasons": reasons,
            "per_variant": {r.variant: _display(attr, r.fields[attr]) for r in reads},
        }
        if p.region is not None:
            artifacts["crops"][attr] = {"page": page, "region": p.region, "variant": primary.variant}

    # line items
    line_reasons = []
    if any(r.lines_compare != primary.lines_compare for r in reads[1:]):
        line_reasons.append("variants_disagree")
    incomplete = [i for i, l in enumerate(primary.lines) if not l.complete]
    if incomplete:
        line_reasons.append(f"incomplete_rows:{incomplete}")
    if min_confidence is not None and any(l.confidence is not None and l.confidence < min_confidence
                                          for l in primary.lines):
        line_reasons.append("low_confidence")
    if partial and not primary.lines:
        line_reasons.append("partial_job")
    stable["lines"] = not line_reasons
    lines: list[LineItem] = []
    for i, l in enumerate(primary.lines):
        for k, v in l.raw.items():
            if v is not None:
                raw_native[f"lines[{i}].{k}"] = v
        if l.complete:
            # discount reaches LineItem only if the model has that field (make_model
            # drops it otherwise); when unread, the model's own default applies.
            # It also stays in raw_native and feeds Invoice.discount below.
            extra = {"discount": l.discount} if l.discount is not None else {}
            lines.append(make_line_item(item_key=l.item_key, qty=l.qty, rate=l.rate, amount=l.amount, **extra))
    if primary.lines:
        page = primary.lines[0].page if primary.lines[0].page is not None else (1 if single_page else None)
        if page is not None:
            pages["lines"] = page
    artifacts["lines"] = {
        "unstable_reasons": line_reasons,
        "rows": [{**l.raw, "complete": l.complete} for l in primary.lines],
        "dropped_incomplete_rows": incomplete,
    }

    f = primary.fields
    date_val = f["date"].value or (None, False)
    discount = f["discount"].value
    line_discounts = [l.discount for l in primary.lines if l.discount is not None]
    if discount is None and line_discounts and f["discount"].raw is None:
        discount = sum(line_discounts, Decimal(0))
        artifacts["discount_source"] = "sum_of_line_discounts"

    inv = make_invoice(
        id=inv_id,
        source_hash=source_hash,
        vendor_name_raw=f["vendor_name"].raw or "",
        vendor_key=f["vendor_name"].value or "",
        gstin=f["gstin"].value,
        number_raw=f["number"].raw,
        number_norm=f["number"].value,
        date=date_val[0],
        date_ambiguous=bool(date_val[1]),
        lines=lines,
        subtotal=f["subtotal"].value,
        tax=f["tax"].value,
        total=f["total"].value,
        words_amount=f["words_amount"].value,
        payee_name=f["payee_name"].value,
        account_number=f["account_number"].value,
        ifsc=f["ifsc"].value,
        stable=stable,
        confidence=confidence,
        raw_native=raw_native,
        pages=pages,
        language=language,
        po_number=f["po_number"].value,
        buyer_gstin=f["buyer_gstin"].value,
        discount=discount,
        cgst=f["cgst"].value,
        sgst=f["sgst"].value,
        igst=f["igst"].value,
        vendor_phone_on_invoice=f["vendor_phone_on_invoice"].value,
    )
    delivery = f["delivery_date"].value
    artifacts["extra"] = {
        "delivery_date": str(delivery[0]) if delivery and delivery[0] else None,
        "upi_id": f["upi_id"].value,
    }
    return inv, artifacts


def dumps_artifacts(artifacts: dict) -> str:
    return json.dumps(artifacts, ensure_ascii=False, default=str)
