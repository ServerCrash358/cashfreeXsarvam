"""Vendor lanes, bank verification and our own name match (ARCHITECTURE section E)."""
from __future__ import annotations

import hashlib
from difflib import SequenceMatcher
from typing import Optional

from panch.models import CheckResult, Invoice, Vendor
from panch.normalise import clean_name, vendor_key


def account_hash(account: str, ifsc: str) -> str:
    return hashlib.sha256(f"{account}|{ifsc}".encode()).hexdigest()[:16]


def name_score(a: Optional[str], b: Optional[str]) -> int:
    """0-100. Token-sorted, initials-aware, phonetic-aware. Subset of tokens (proprietor name inside a
    business name) scores high. Pure."""
    ca, cb = clean_name(a), clean_name(b)
    if not ca or not cb:
        return 0
    ta, tb = ca.split(), cb.split()
    if ca == cb or " ".join(sorted(ta)) == " ".join(sorted(tb)):
        return 100
    sa, sb = set(ta), set(tb)
    small, big = (sa, sb) if len(sa) <= len(sb) else (sb, sa)
    if small and small <= big:
        return 95
    # initials-aware: "j doe" vs "john doe"
    def covers(x, y):
        return all(any(t == u or (len(t) == 1 and u.startswith(t)) for u in y) for t in x)
    if covers(ta, tb) or covers(tb, ta):
        return 88
    pa, pb = vendor_key(ca), vendor_key(cb)
    phon = SequenceMatcher(None, pa, pb).ratio()
    ratio = SequenceMatcher(None, " ".join(sorted(ta)), " ".join(sorted(tb))).ratio()
    return int(round(max(ratio, phon) * 100))


def find_vendor(inv: Invoice, vendors: list[Vendor]) -> Optional[Vendor]:
    """Hard key first (GSTIN), then the phonetic vendor key."""
    if inv.gstin:
        for v in vendors:
            if v.gstin and v.gstin == inv.gstin:
                return v
    for v in vendors:
        if vendor_key(v.legal_name) == inv.vendor_key:
            return v
    return None


def lane_for(inv: Invoice, vendor: Optional[Vendor]) -> str:
    if vendor is None:
        return "NEW_VENDOR"
    for acc in vendor.accounts:
        if acc.account_number == inv.account_number and acc.ifsc == inv.ifsc and acc.status == "verified":
            return "KNOWN"
    return "CHANGED_ACCOUNT"


def _name_check(label: str, a: Optional[str], b: Optional[str], cfg: dict) -> CheckResult:
    s = name_score(a, b)
    hi, lo = int(cfg.get("name_pass", 85)), int(cfg.get("name_ask", 60))
    ev = {"pair": label, "a": a, "b": b, "our_score": s}
    if s >= hi:
        return CheckResult("NAME_MISMATCH", True, "info", ev, "name_ok")
    if s >= lo:
        return CheckResult("NAME_MISMATCH", False, "ask", ev, "name_partial")
    return CheckResult("NAME_MISMATCH", False, "block", ev, "name_mismatch")


#: Cashfree account_status_code values that hard-BLOCK even when the
#: coarse status is not INVALID. A fraud flag must never degrade to ASK.
FRAUD_BLOCK_CODES = frozenset({"FRAUD_ACCOUNT"})


def verify_identity(inv: Invoice, client, cfg: dict, udyam: Optional[str] = None) -> list[CheckResult]:
    """GSTIN (and Udyam if known) for a vendor we have never seen (FR5). Only ever ASKs: Cashfree's sandbox
    knows a handful of published IDs, so 'not found' is a sandbox gap, not proof of fraud."""
    out: list[CheckResult] = []
    if inv.gstin and hasattr(client, "gstin"):
        g = client.gstin(inv.gstin, inv.payee_name or inv.vendor_name_raw)
        ev = {"gstin": inv.gstin, "valid": g.get("valid"), "legal_name": g.get("legal_name_of_business"),
              "status": g.get("gst_in_status"), "canned": g.get("canned")}
        if g.get("valid") is True:
            out.append(CheckResult("VENDOR_UNVERIFIABLE", True, "info", ev, "gstin_ok"))
            if g.get("legal_name_of_business"):
                out.append(_name_check("invoice payee vs GST legal name", inv.payee_name or inv.vendor_name_raw,
                                       g.get("legal_name_of_business"), cfg))
        else:
            out.append(CheckResult("VENDOR_UNVERIFIABLE", False, "ask", ev, "vendor_unverifiable"))
    if udyam and hasattr(client, "udyam"):
        u = client.udyam(udyam, f"tp_{inv.id}"[:50])
        ev = {"udyam": udyam, "status": u.get("status"), "enterprise_type": u.get("enterprise_type"),
              "canned": u.get("canned")}
        ok = u.get("status") == "SUCCESS"
        out.append(CheckResult("VENDOR_UNVERIFIABLE", ok, "info" if ok else "ask", ev,
                               "udyam_ok" if ok else "vendor_unverifiable"))
    return out


def verify_vendor(inv: Invoice, vendor: Optional[Vendor], vendors: list[Vendor], client,
                  cfg: dict, callback_result: Optional[CheckResult] = None) -> tuple[str, list[CheckResult]]:
    """Returns (lane, checks). Bank verification runs for CHANGED_ACCOUNT and NEW_VENDOR."""
    lane = lane_for(inv, vendor)
    out: list[CheckResult] = []
    # ACCOUNT_SHARED: this account belongs to a different vendor in the master
    for v in vendors:
        if vendor and v.id == vendor.id:
            continue
        if any(a.account_number == inv.account_number and a.ifsc == inv.ifsc for a in v.accounts):
            out.append(CheckResult("ACCOUNT_SHARED", False, "block",
                                   {"account_last4": inv.account_last4, "other_vendor": v.legal_name},
                                   "account_shared"))
    if lane == "KNOWN":
        out.append(CheckResult("ACCOUNT_CHANGED", True, "info",
                               {"lane": lane, "account_last4": inv.account_last4, "provenance": next(
                                   a.provenance for a in vendor.accounts if a.account_number == inv.account_number)},
                               "account_known"))
        out.append(_name_check("invoice payee vs vendor legal name", inv.payee_name or inv.vendor_name_raw,
                               vendor.legal_name, cfg))
        return lane, out

    if lane == "NEW_VENDOR":
        out.append(CheckResult("NEW_VENDOR", False, "ask", {"vendor_name": inv.vendor_name_raw, "gstin": inv.gstin},
                               "new_vendor"))
        out.extend(verify_identity(inv, client, cfg))
    else:
        known = ", ".join("xx" + a.last4 for a in vendor.accounts)
        out.append(CheckResult("ACCOUNT_CHANGED", False, "ask",
                               {"lane": lane, "invoice_account_last4": inv.account_last4, "known_accounts": known,
                                "invoice_ifsc": inv.ifsc}, "account_changed"))

    claimed = vendor.account_holder_name if vendor else (inv.payee_name or inv.vendor_name_raw)
    bank = client.bank(inv.account_number or "", inv.ifsc or "", claimed) if inv.account_number else \
        {"account_status": "UNVERIFIABLE"}
    status = bank.get("account_status")
    status_code = bank.get("account_status_code")
    ev = {"account_last4": inv.account_last4, "account_status": status, "account_status_code": status_code,
          "name_at_bank": bank.get("name_at_bank"),
          "cashfree_name_match": bank.get("name_match_result"), "cashfree_score": bank.get("name_match_score"),
          "canned": bank.get("canned"), "live_error": bank.get("live_error")}
    if status == "INVALID" or status_code in FRAUD_BLOCK_CODES:
        out.append(CheckResult("BANK_INVALID", False, "block", ev, "bank_invalid"))
    elif status != "VALID":
        out.append(CheckResult("VENDOR_UNVERIFIABLE", False, "ask", ev, "vendor_unverifiable"))
    else:
        out.append(CheckResult("BANK_INVALID", True, "info", ev, "bank_valid"))
        # name triangle: bank name vs account holder on file, and invoice payee vs legal name
        out.append(_name_check("name at bank vs account holder on file", bank.get("name_at_bank"), claimed, cfg))
        if vendor:
            out.append(_name_check("invoice payee vs vendor legal name", inv.payee_name or inv.vendor_name_raw,
                                   vendor.legal_name, cfg))
    if callback_result is not None:
        out.append(callback_result)
    return lane, out
