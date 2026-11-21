"""Deterministic transfer IDs (ARCHITECTURE section I). Pure."""
from __future__ import annotations

import hashlib
from decimal import Decimal


def transfer_id(vendor_id: str, fp: str, account: str, amount: Decimal, attempt: int = 1) -> str:
    """pn_ + 32 hex of SHA-256(vendor|fingerprint|account|amount|attempt): 35 chars, <= 40 allowed.
    Same payment -> same ID, so a missed exact duplicate collides at Cashfree (DUPLICATE_TRANSFER)."""
    raw = f"{vendor_id}|{fp}|{account}|{Decimal(amount).quantize(Decimal('0.01'))}|{attempt}"
    return "pn_" + hashlib.sha256(raw.encode()).hexdigest()[:32]
