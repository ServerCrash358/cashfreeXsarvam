r"""Payout state machine (ARCHITECTURE sections I and I2). Pure: no I/O.

INTENT -> SENT -> PENDING -> SUCCESS (+ COMPLETED) -> REVERSED
            \-> UNKNOWN (timeout/5XX) -> poll -> any of the above
PENDING -> FAILED / REJECTED  (terminal; only these allow a new attempt)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Optional

RANK = {"INTENT": 0, "SENT": 1, "UNKNOWN": 1, "PENDING": 2, "SUCCESS": 3, "FAILED": 3, "REJECTED": 3,
        "REVERSED": 4}
ACTIVE = {"INTENT", "SENT", "UNKNOWN", "PENDING"}
TERMINAL_FAILURE = {"FAILED", "REJECTED"}

# Cashfree transfer statuses and webhook event types -> our states. A mapped "SUCCESS" only becomes our
# SUCCESS when status_code is COMPLETED (see apply_event); anything else is held at PENDING.
CF_TO_STATE = {
    "RECEIVED": "PENDING", "APPROVAL_PENDING": "PENDING", "VALIDATION_PENDING": "PENDING", "PENDING": "PENDING",
    "QUEUED": "PENDING", "SUCCESS": "SUCCESS", "FAILED": "FAILED", "REJECTED": "REJECTED",
    "MANUALLY_REJECTED": "REJECTED", "REVERSED": "REVERSED",
    "TRANSFER_ACKNOWLEDGED": "SUCCESS", "TRANSFER_SUCCESS": "SUCCESS", "TRANSFER_FAILED": "FAILED",
    "TRANSFER_REJECTED": "REJECTED", "TRANSFER_REVERSED": "REVERSED",
}


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


def _ignore(att: Attempt, entry: dict, note: str) -> bool:
    entry["applied"] = False
    entry["note"] = note
    att.history.append(entry)
    return False


def apply_event(att: Attempt, new_state: str, status_code: Optional[str] = None, source: str = "",
                now: Optional[datetime] = None) -> bool:
    """Apply one observation (API response, webhook or status poll). Returns True if the state changed.

    - SUCCESS is final only with status_code COMPLETED; SUCCESS with any other or no code is held at PENDING.
    - Forward only: a lower-rank event after a higher one is logged and ignored.
    - FAILED/REJECTED are terminal; after SUCCESS the only move is REVERSED (a payout that landed can't fail).
    """
    now = now or datetime.now()
    if new_state == "SUCCESS" and status_code != "COMPLETED":
        new_state = "PENDING"
    entry = {"at": now.isoformat(timespec="seconds"), "from": att.state, "to": new_state,
             "status_code": status_code, "source": source}
    if new_state not in RANK:
        return _ignore(att, entry, "unknown state; ignored")
    if new_state == att.state:
        if status_code and status_code != att.status_code:
            att.status_code = status_code
        entry["applied"] = False
        att.history.append(entry)
        return False
    if att.state in TERMINAL_FAILURE:
        return _ignore(att, entry, "terminal failure; ignored")
    if att.state == "SUCCESS" and new_state != "REVERSED":
        return _ignore(att, entry, "already succeeded; only a reversal can follow")
    if RANK[new_state] < RANK[att.state]:
        return _ignore(att, entry, "lower rank after higher; ignored")
    if new_state == "REVERSED" and att.state != "SUCCESS":
        # Cashfree only reverses a transfer that completed, so this is authoritative: we just missed the
        # SUCCESS event. Recorded so the audit shows it.
        entry["note"] = "reversal seen before success"
    att.state = new_state
    if status_code:
        att.status_code = status_code
    entry["applied"] = True
    att.history.append(entry)
    return True
