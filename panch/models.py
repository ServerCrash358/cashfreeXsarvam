"""Shared interfaces (ARCHITECTURE section 7). Change only by a small PR to main."""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from typing import Literal, Optional


class Outcome(str, Enum):
    PAY = "PAY"
    ASK = "ASK"
    BLOCK = "BLOCK"
    DEFER = "DEFER"


@dataclass(frozen=True)
class CheckResult:
    code: str                                  # e.g. "ARITH_TOTAL"
    passed: bool
    severity: Literal["block", "ask", "info"]
    evidence: dict
    message_key: str                           # templates/<lang>/<key>.txt


@dataclass(frozen=True)
class LineItem:
    item_key: str
    qty: Decimal
    rate: Decimal
    amount: Decimal
    discount: Decimal = Decimal("0")


@dataclass
class Invoice:
    id: str
    source_hash: str
    vendor_name_raw: str
    vendor_key: str
    gstin: Optional[str]
    number_raw: Optional[str]
    number_norm: Optional[str]
    date: Optional[date]
    date_ambiguous: bool
    lines: list[LineItem]
    subtotal: Optional[Decimal]
    tax: Optional[Decimal]
    total: Optional[Decimal]
    words_amount: Optional[Decimal]
    payee_name: Optional[str]
    account_number: Optional[str] = field(repr=False)  # in memory only; never logged (repr hidden: PR 1)
    ifsc: Optional[str]
    stable: dict[str, bool] = field(default_factory=dict)
    confidence: dict[str, float] = field(default_factory=dict)
    raw_native: dict[str, str] = field(default_factory=dict)
    pages: dict[str, int] = field(default_factory=dict)
    language: Optional[str] = None
    po_number: Optional[str] = None
    buyer_gstin: Optional[str] = None
    discount: Optional[Decimal] = None
    cgst: Optional[Decimal] = None
    sgst: Optional[Decimal] = None
    igst: Optional[Decimal] = None
    vendor_phone_on_invoice: Optional[str] = None  # recorded, never used for call-backs

    @property
    def account_last4(self) -> str:
        return (self.account_number or "")[-4:]


@dataclass
class Decision:
    invoice_id: str
    outcome: Outcome
    codes: list[str]
    checks: list[CheckResult]


@dataclass
class VendorAccount:
    account_number: str
    ifsc: str
    provenance: str                            # onboarding / invoice / call-back
    first_seen: str
    status: str = "verified"

    @property
    def last4(self) -> str:
        return self.account_number[-4:]


@dataclass
class Vendor:
    id: str
    legal_name: str
    gstin: Optional[str]
    udyam: Optional[str]
    enterprise_type: Optional[str]             # micro / small / medium
    msme_rule_applies: bool
    agreement_days: Optional[int]
    recurring: bool
    phone_on_file: Optional[str]
    account_holder_name: str
    language: str = "en"
    accounts: list[VendorAccount] = field(default_factory=list)


@dataclass
class PlanItem:
    invoice_id: str
    vendor_id: str
    amount: Decimal
    deadline: Optional[date]


@dataclass
class Plan:
    cash_limit: Decimal
    chosen: list[PlanItem]
    deferred: list[PlanItem]
    protected: Decimal
    naive_chosen: list[PlanItem]
    naive_protected: Decimal


@dataclass
class BundleItem:
    invoice_id: str
    beneficiary_id: str
    account_hash: str
    amount: Decimal


@dataclass
class Bundle:
    id: str
    items: list[BundleItem]
    cash_limit: Decimal
    created_at: datetime
    expires_at: datetime
    nonce: str
    hash: str
    code: str
    status: str = "proposed"                   # proposed / voice_ok / approved / used / expired

    @property
    def total(self) -> Decimal:
        return sum((i.amount for i in self.items), Decimal("0"))


@dataclass
class ApprovalResult:
    ok: bool
    yes_ok: bool
    total_ok: bool
    count_ok: bool
    code_ok: bool
    reasons: list[str]
