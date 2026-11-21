# panch/models.py  (owned by PR 2; others import it)
#
# Copied verbatim from ARCHITECTURE.md section 7 so PR 1 can run before PR 2
# lands. If PR 2's version is already on main, keep theirs and drop this file.
# One non-interface change, flagged for PR 2: `account_number` has
# repr=False so printing or logging an Invoice never leaks the full number.
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from enum import Enum
from typing import Literal, Optional


class Outcome(str, Enum):
    PAY = "PAY"; ASK = "ASK"; BLOCK = "BLOCK"; DEFER = "DEFER"


@dataclass(frozen=True)
class CheckResult:
    code: str                                  # e.g. "ARITH_TOTAL"
    passed: bool
    severity: Literal["block", "ask", "info"]
    evidence: dict                             # values compared, crop refs
    message_key: str                           # templates/<lang>/<key>.txt


@dataclass(frozen=True)
class LineItem:
    item_key: str; qty: Decimal; rate: Decimal; amount: Decimal


@dataclass
class Invoice:
    id: str
    source_hash: str                           # hash of the image/PDF
    vendor_name_raw: str
    vendor_key: str                            # phonetic key
    gstin: Optional[str]
    number_raw: Optional[str]; number_norm: Optional[str]
    date: Optional[date]; date_ambiguous: bool
    lines: list[LineItem]
    subtotal: Optional[Decimal]; tax: Optional[Decimal]; total: Optional[Decimal]
    words_amount: Optional[Decimal]
    payee_name: Optional[str]
    account_number: Optional[str] = field(repr=False)  # in memory only; never logged
    ifsc: Optional[str]
    stable: dict[str, bool] = field(default_factory=dict)  # per-field multi-read agreement
    confidence: dict[str, float] = field(default_factory=dict)  # per-field, if Extract returns it
    raw_native: dict[str, str] = field(default_factory=dict)    # evidence of record, native script
    pages: dict[str, int] = field(default_factory=dict)          # page number per field
    language: Optional[str] = None
    po_number: Optional[str] = None
    buyer_gstin: Optional[str] = None
    discount: Optional[Decimal] = None
    cgst: Optional[Decimal] = None; sgst: Optional[Decimal] = None; igst: Optional[Decimal] = None
    vendor_phone_on_invoice: Optional[str] = None  # recorded, never used for call-backs


@dataclass
class Decision:
    invoice_id: str
    outcome: Outcome
    codes: list[str]
    checks: list[CheckResult]
