"""Economic fingerprint and two-track duplicate routing (ARCHITECTURE section D). Pure."""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from decimal import Decimal
from typing import Optional

from panch.models import CheckResult, Invoice


@dataclass
class HistoryEntry:
    invoice: Invoice
    vendor_id: str
    status: str            # paid / pending


def item_norm(text: str) -> str:
    """Item text compared on letters/digits only, so '5-ply' == '5 ply' whatever the intake path."""
    return " ".join(re.findall(r"[^\W_]+", (text or "").lower()))


def line_multiset(inv: Invoice) -> tuple:
    return tuple(sorted((item_norm(ln.item_key), str(ln.qty.normalize()), str(ln.rate.normalize()))
                        for ln in inv.lines))


def fingerprint(inv: Invoice, vendor_id: Optional[str] = None) -> str:
    parts = [vendor_id or inv.vendor_key, repr(line_multiset(inv)), str(inv.total),
             inv.date.isoformat() if inv.date else "", (inv.po_number or "").upper()]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


def route_duplicates(inv: Invoice, history: list[HistoryEntry], vendor_id: Optional[str],
                     recurring: bool = False, cfg: Optional[dict] = None) -> list[CheckResult]:
    cfg = cfg or {}
    fuzzy_pct = Decimal(str(cfg.get("dup_fuzzy_total_pct", "1")))
    fuzzy_days = int(cfg.get("dup_fuzzy_days", 7))
    new_period_days = int(cfg.get("dup_new_period_days", 25))
    out: list[CheckResult] = []
    if not vendor_id:
        return [CheckResult("DUP_EXACT", True, "info", {"note": "unknown vendor; no history"}, "dup_none")]
    mine = [h for h in history if h.vendor_id == vendor_id and h.invoice.id != inv.id]
    lines = line_multiset(inv)
    for h in mine:
        prev = h.invoice
        ev = {"matched_invoice": prev.id, "matched_number": prev.number_raw, "matched_status": h.status,
              "matched_date": prev.date.isoformat() if prev.date else None,
              "this_number": inv.number_raw, "this_date": inv.date.isoformat() if inv.date else None,
              "total": str(inv.total)}
        # cheap layer: same normalised number (FY kept), already paid
        if inv.number_norm and prev.number_norm == inv.number_norm and h.status == "paid":
            out.append(CheckResult("DUP_NUMBER", False, "block", {**ev, "number_norm": inv.number_norm}, "dup_number"))
            continue
        same_content = prev.total == inv.total and line_multiset(prev) == lines
        same_ref = (inv.date and prev.date == inv.date) or (inv.po_number and prev.po_number == inv.po_number)
        days = abs((inv.date - prev.date).days) if inv.date and prev.date else None
        if same_content and same_ref:
            out.append(CheckResult("DUP_EXACT", False, "block",
                                   {**ev, "hard_key": "vendor GSTIN/ID", "economic_match": "lines + total + date/PO"},
                                   "dup_exact"))
        elif same_content and days is not None and days >= new_period_days and recurring:
            continue           # legitimate recurring bill in a new period
        elif prev.total and inv.total and days is not None:
            close = abs(prev.total - inv.total) <= prev.total * fuzzy_pct / 100
            if close and days <= fuzzy_days:
                out.append(CheckResult("DUP_FUZZY", False, "ask", {**ev, "days_apart": days}, "dup_fuzzy"))
    if not out:
        out.append(CheckResult("DUP_EXACT", True, "info", {"compared_with": len(mine)}, "dup_none"))
    return out
