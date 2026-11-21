"""Payout ledger (ARCHITECTURE section I): the control that stops double payment.
Cashfree's DUPLICATE_TRANSFER rejection is the backstop, not the control."""
from __future__ import annotations

from decimal import Decimal
from typing import Optional

from panch.payouts.state import ACTIVE, Attempt


class Ledger:
    """At most one active transfer per invoice; confirmed + in-flight never exceed the invoice amount."""

    def __init__(self):
        self.attempts: dict[str, Attempt] = {}

    def for_invoice(self, invoice_id: str) -> list[Attempt]:
        return [a for a in self.attempts.values() if a.invoice_id == invoice_id]

    def can_start(self, invoice_id: str, amount: Decimal, invoice_amount: Decimal) -> Optional[str]:
        """None if a new attempt may start, else the reason it may not."""
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
