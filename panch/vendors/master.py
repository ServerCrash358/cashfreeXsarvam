"""Vendor master (ARCHITECTURE sections E and 4): who we pay, their accounts and where each came from.
Pure helpers; the engine owns the live list."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable, Optional

from panch.models import Invoice, Vendor, VendorAccount


def load_vendors(path: Path) -> tuple[dict, list[Vendor]]:
    """Read the vendor-master fixture. Returns (buyer, vendors)."""
    fx = json.loads(Path(path).read_text(encoding="utf-8"))
    vendors = []
    for v in fx["vendors"]:
        v = dict(v)
        accs = [VendorAccount(**a) for a in v.pop("accounts")]
        vendors.append(Vendor(**v, accounts=accs))
    return fx.get("buyer", {}), vendors


def frozen_by(vendor_id: Optional[str], invoice_id: str,
              others: Iterable[tuple[str, Optional[str], str, str]]) -> Optional[str]:
    """CHANGED_ACCOUNT freezes the whole vendor (U-VEN-13). Returns the invoice ID holding the freeze, or None.

    `others` yields (invoice_id, vendor_id, lane, outcome) for the rest of the batch. A freeze holds while a
    changed-account invoice of the same vendor is still ASK (call-back or owner approval pending). It lifts when
    that invoice is BLOCKed (change rejected) or becomes KNOWN (change approved)."""
    if not vendor_id:
        return None
    for oid, vid, lane, outcome in others:
        if oid != invoice_id and vid == vendor_id and lane == "CHANGED_ACCOUNT" and outcome == "ASK":
            return oid
    return None


def onboard_vendor(vendor_id: str, inv: Invoice, gst: dict, enterprise_type: Optional[str],
                   phone_on_file: str, account_holder_name: str, today: str, udyam: Optional[str] = None,
                   agreement_days: Optional[int] = None, recurring: bool = False, language: str = "en") -> Vendor:
    """Owner onboards a NEW_VENDOR after GSTIN + Udyam + bank verification (U-VEN-12).
    The phone on file comes from the owner, never from the invoice."""
    et = (enterprise_type or "").lower() or None
    return Vendor(
        id=vendor_id, legal_name=gst.get("legal_name_of_business") or inv.vendor_name_raw, gstin=inv.gstin,
        udyam=udyam, enterprise_type=et, msme_rule_applies=et in ("micro", "small"), agreement_days=agreement_days,
        recurring=recurring, phone_on_file=phone_on_file, account_holder_name=account_holder_name, language=language,
        accounts=[VendorAccount(inv.account_number or "", inv.ifsc or "", "onboarding", today)])
