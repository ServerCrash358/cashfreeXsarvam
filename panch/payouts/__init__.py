"""Payout state machine, deterministic transfer IDs and the ledger (ARCHITECTURE section I)."""
from __future__ import annotations

import hashlib
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional

RANK = {"INTENT": 0, "SENT": 1, "UNKNOWN": 1, "PENDING": 2, "SUCCESS": 3, "FAILED": 3, "REJECTED": 3,
        "REVERSED": 4}
ACTIVE = {"INTENT", "SENT", "UNKNOWN", "PENDING"}
CF_TO_STATE = {
    "RECEIVED": "PENDING", "APPROVAL_PENDING": "PENDING", "VALIDATION_PENDING": "PENDING", "PENDING": "PENDING",
    "QUEUED": "PENDING", "SUCCESS": "SUCCESS", "FAILED": "FAILED", "REJECTED": "REJECTED",
    "MANUALLY_REJECTED": "REJECTED", "REVERSED": "REVERSED",
    "TRANSFER_ACKNOWLEDGED": "SUCCESS", "TRANSFER_SUCCESS": "SUCCESS", "TRANSFER_FAILED": "FAILED",
    "TRANSFER_REJECTED": "REJECTED", "TRANSFER_REVERSED": "REVERSED",
}


def transfer_id(vendor_id: str, fp: str, account: str, amount: Decimal, attempt: int = 1) -> str:
    """pn_ + 32 hex of SHA-256(vendor|fingerprint|account|amount|attempt): 35 chars, <= 40 allowed."""
    raw = f"{vendor_id}|{fp}|{account}|{Decimal(amount).quantize(Decimal('0.01'))}|{attempt}"
    return "pn_" + hashlib.sha256(raw.encode()).hexdigest()[:32]


@dataclass
class Attempt:
    transfer_id: str
    invoice_id: str
    bundle_id: str
    beneficiary_id: str
    amount: Decimal
    attempt: int = 1
    state: str = "INTENT"
    status_code: Optional[str] = None
    cf_transfer_id: Optional[str] = None
    utr: Optional[str] = None
    simulated: bool = False
    history: list = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"transfer_id": self.transfer_id, "invoice_id": self.invoice_id, "bundle_id": self.bundle_id,
                "amount": str(self.amount), "attempt": self.attempt, "state": self.state,
                "status_code": self.status_code, "cf_transfer_id": self.cf_transfer_id, "utr": self.utr,
                "simulated": self.simulated, "history": self.history}


def apply_event(att: Attempt, new_state: str, status_code: Optional[str] = None, source: str = "",
                now: Optional[datetime] = None) -> bool:
    """Apply by state rank. A lower-rank event after a higher one is logged and ignored.
    SUCCESS is final only with status_code COMPLETED; otherwise held at PENDING."""
    now = now or datetime.now()
    if new_state == "SUCCESS" and status_code not in (None, "COMPLETED"):
        new_state = "PENDING"
    entry = {"at": now.isoformat(timespec="seconds"), "from": att.state, "to": new_state,
             "status_code": status_code, "source": source}
    if new_state == att.state:
        if status_code and status_code != att.status_code:
            att.status_code = status_code
        entry["applied"] = False
        att.history.append(entry)
        return False
    if RANK[new_state] < RANK[att.state] and not (att.state == "UNKNOWN" and new_state in ("SENT",)):
        entry["applied"] = False
        entry["note"] = "lower rank after higher; ignored"
        att.history.append(entry)
        return False
    if att.state in ("FAILED", "REJECTED") and new_state != att.state:
        entry["applied"] = False
        entry["note"] = "terminal failure; ignored"
        att.history.append(entry)
        return False
    if new_state == "REVERSED" and att.state != "SUCCESS":
        entry["applied"] = False
        entry["note"] = "reversal before success; poll status"
        att.history.append(entry)
        return False
    att.state = new_state
    if status_code:
        att.status_code = status_code
    entry["applied"] = True
    att.history.append(entry)
    return True


class Ledger:
    """At most one active transfer per invoice; confirmed + in-flight never exceed the invoice amount."""

    def __init__(self):
        self.attempts: dict[str, Attempt] = {}

    def for_invoice(self, invoice_id: str) -> list[Attempt]:
        return [a for a in self.attempts.values() if a.invoice_id == invoice_id]

    def can_start(self, invoice_id: str, amount: Decimal, invoice_amount: Decimal) -> Optional[str]:
        atts = self.for_invoice(invoice_id)
        if any(a.state in ACTIVE for a in atts):
            return "an active transfer already exists for this invoice"
        committed = sum((a.amount for a in atts if a.state in ACTIVE | {"SUCCESS"}), Decimal("0"))
        if committed + amount > invoice_amount:
            return "would exceed the invoice amount"
        return None

    def add(self, att: Attempt) -> Attempt:
        if att.transfer_id in self.attempts:
            raise ValueError("transfer_id collision")
        self.attempts[att.transfer_id] = att
        return att

    def open_for_sweep(self) -> list[Attempt]:
        return [a for a in self.attempts.values() if a.state in ("SENT", "UNKNOWN", "PENDING")]
