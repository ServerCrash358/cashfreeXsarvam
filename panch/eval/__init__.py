"""Evaluation harness (ARCHITECTURE K): mutate the clean demo invoices into labelled clean controls
(incl. legitimate twins) and planted traps, run the full gate offline, report three numbers:
traps blocked, clean auto-paid rate, clean falsely held. Claim only what is measured here."""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass, field
from datetime import timedelta
from pathlib import Path
from typing import Optional

from panch.cashfree import VerificationClient
from panch.fingerprint import HistoryEntry
from panch.models import Vendor, VendorAccount
from panch.normalise import parse_amount, parse_date
from panch.reading import invoice_from_extract
from panch.vendors import find_vendor

ROOT = Path(__file__).resolve().parents[2]
TOM_WELLS = ("1233943142", "ICIC0000009")       # sandbox account registered to someone else


@dataclass
class Case:
    id: str
    kind: str                     # clean / trap
    what: str
    raw: dict
    expect_code: Optional[str] = None
    extra_history: list = field(default_factory=list)


def _d(raw: dict):
    return parse_date(raw["invoice_date"])[0]


def _redate(raw: dict, days: int = 0, fmt: str = "%d-%b-%Y") -> dict:
    r = copy.deepcopy(raw)
    r["invoice_date"] = (_d(raw) + timedelta(days=days)).strftime(fmt)
    return r


def _set(raw: dict, **kw) -> dict:
    r = copy.deepcopy(raw)
    r.update(kw)
    return r


def _bump(x: str, add: int) -> str:
    return f"{int(parse_amount(x)) + add:,}"


def build_cases(batch: dict) -> list[Case]:
    base = {r["id"]: r for r in batch["invoices"] if r.get("expected") == "PAY"}   # A, B, C, H
    cases: list[Case] = []

    # ---------------- clean controls (20)
    for k, r in base.items():
        cases.append(Case(f"clean-{k}", "clean", "original", copy.deepcopy(r)))
        cases.append(Case(f"clean-{k}-date", "clean", "date written differently", _set(_redate(r), id=f"{k}d")))
        amt = str(parse_amount(r["total"]))
        cases.append(Case(f"clean-{k}-fmt", "clean", "total written 'Rs. x.00/-'", _set(r, id=f"{k}f", total=f"Rs. {amt}/-")))
    A, B, C, H = base["A"], base["B"], base["C"], base["H"]
    cases += [
        Case("twin-recurring-B", "clean", "recurring vendor, same bill next month",
             _set(_redate(B, 30), id="Bt1", invoice_no="SGP/0101/2026-27"), extra_history=[B]),
        Case("twin-same-amount-other-vendor", "clean", "A's goods and amount, billed by vendor C",
             _set(A, id="At2", vendor_name=C["vendor_name"], vendor_name_latin=None, vendor_gstin=C["vendor_gstin"],
                  payee_name=C["payee_name"], bank_account=C["bank_account"], ifsc=C["ifsc"],
                  invoice_no="CSPL/INV/1201")),
        Case("twin-name-spelling", "clean", "vendor name spelled 'Shri Ganesh Packaging' (same GSTIN)",
             _set(B, id="Bt3", vendor_name="Shri Ganesh Packaging", vendor_name_latin="Shri Ganesh Packaging",
                  payee_name="Shri Ganesh Packaging", invoice_no="SGP/0094/2026-27")),
        Case("twin-same-vendor-new-goods", "clean", "same vendor and amount, different goods, 3 weeks later",
             _set(_redate(A, 21), id="At4", invoice_no="SMEW/240/2026-27",
                  line_items=[{"item": "Turned shaft EN8", "qty": "31", "rate": "400", "amount": "12,400"}]),
             extra_history=[A]),
        Case("twin-nonrecurring-repeat-40d", "clean", "same goods again after 40 days (non-recurring vendor)",
             _set(_redate(H, 40), id="Ht5", invoice_no="MT/0131/2026-27"), extra_history=[H]),
        Case("twin-same-day-other-order", "clean", "second bill same day, different order and amount",
             _set(B, id="Bt6", invoice_no="SGP/0095/2026-27", subtotal="9,000", total="9,000",
                  amount_in_words="नौ हज़ार रुपये मात्र",
                  line_items=[{"item": "Corrugated box 3-ply", "qty": "450", "rate": "20", "amount": "9,000"}]),
             extra_history=[B]),
        Case("twin-same-po-new-delivery", "clean", "same PO, second delivery with different quantity",
             _set(_redate(C, 10), id="Ct7", invoice_no="CSPL/INV/1240", subtotal="3,750.00", igst="1,050.00",
                  tax_total="1,050.00", total="4,800.00", amount_in_words="Four Thousand Eight Hundred Only",
                  line_items=[{"item": "MS flat bar 50x6", "qty": "125", "rate": "30", "amount": "3,750.00"}]),
             extra_history=[C]),
        Case("twin-indic-digits", "clean", "all figures in Devanagari digits",
             _set(B, id="Bt8", invoice_no="SGP/0096/2026-27", subtotal="१८,०००", total="₹१८,०००/-")),
    ]

    # ---------------- traps (20)
    for k, r in base.items():
        cases.append(Case(f"trap-{k}-inflated", "trap", "total inflated by Rs 1,000 (words left off)",
                          _set(r, id=f"{k}x1", total=_bump(r["total"], 1000), amount_in_words=None), "ARITH_TOTAL"))
        ln = copy.deepcopy(r["line_items"])
        ln[0]["qty"] = str(int(parse_amount(ln[0]["qty"])) + 2)
        cases.append(Case(f"trap-{k}-line", "trap", "quantity changed, line amount left as printed",
                          _set(r, id=f"{k}x2", line_items=ln), "ARITH_LINE"))
        cases.append(Case(f"trap-{k}-dup", "trap", "disguised duplicate: new number, date rewritten",
                          _set(_redate(r), id=f"{k}x3", invoice_no=r["invoice_no"].replace("/", "-") + "-R"),
                          "DUP_EXACT", extra_history=[r]))
        cases.append(Case(f"trap-{k}-account", "trap", "bank account swapped to someone else's",
                          _set(r, id=f"{k}x4", bank_account=TOM_WELLS[0], ifsc=TOM_WELLS[1]), "NAME_MISMATCH"))
    cases += [
        Case("trap-A-words", "trap", "amount in words says 21,400",
             _set(A, id="Ax5", amount_in_words="Twenty One Thousand Four Hundred Rupees Only"), "ARITH_WORDS"),
        Case("trap-C-gst-split", "trap", "interstate bill charging CGST+SGST",
             _set(C, id="Cx5", igst=None, cgst="1,050.00", sgst="1,050.00"), "ARITH_GST_SPLIT"),
        Case("trap-B-dup-number", "trap", "same invoice number already paid, amount changed",
             _set(B, id="Bx5", total="19,000", subtotal="19,000", amount_in_words="उन्नीस हज़ार रुपये मात्र",
                  line_items=[{"item": "Corrugated box 5-ply", "qty": "633", "rate": "30", "amount": "18,990"},
                              {"item": "Freight", "qty": "1", "rate": "10", "amount": "10"}]),
             "DUP_NUMBER", extra_history=[B]),
        Case("trap-H-account-shared", "trap", "pays into another vendor's account",
             _set(H, id="Hx5", bank_account=C["bank_account"], ifsc=C["ifsc"]), "ACCOUNT_SHARED"),
    ]
    return cases


def run(cases: Optional[list[Case]] = None, cfg: Optional[dict] = None) -> dict:
    from panch.engine import assess
    batch = json.loads((ROOT / "data" / "fixtures" / "demo_batch.json").read_text(encoding="utf-8"))
    vfx = json.loads((ROOT / "data" / "fixtures" / "vendors.json").read_text(encoding="utf-8"))
    cfg = cfg or json.loads((ROOT / "config" / "settings.json").read_text(encoding="utf-8"))
    cases = cases or build_cases(batch)
    vendors = []
    for v in copy.deepcopy(vfx)["vendors"]:
        accs = [VendorAccount(**a) for a in v.pop("accounts")]
        vendors.append(Vendor(**v, accounts=accs))
    verifier = VerificationClient(live=False)          # offline: canned sandbox fixtures only
    base_hist = []
    for h in batch["history"]:
        inv = invoice_from_extract(h)
        v = find_vendor(inv, vendors)
        base_hist.append(HistoryEntry(inv, v.id if v else "", h["status"]))
    rows = []
    for c in cases:
        hist = list(base_hist)
        for i, h in enumerate(c.extra_history):
            hinv = invoice_from_extract(_set(h, id=f"hist-{c.id}-{i}"))
            hv = find_vendor(hinv, vendors)
            hist.append(HistoryEntry(hinv, hv.id if hv else "", "paid"))
        inv = invoice_from_extract(c.raw)
        lane, v, dec = assess(inv, vendors, hist, verifier, cfg)
        rows.append({"case": c.id, "kind": c.kind, "what": c.what, "expect_code": c.expect_code,
                     "outcome": dec.outcome.value, "codes": dec.codes, "lane": lane,
                     "caught_by_expected_code": (c.expect_code in dec.codes) if c.expect_code else None})
    traps = [r for r in rows if r["kind"] == "trap"]
    clean = [r for r in rows if r["kind"] == "clean"]
    n = lambda rs, o: sum(1 for r in rs if r["outcome"] == o)  # noqa: E731
    summary = {
        "cases": len(rows), "traps": len(traps), "clean": len(clean),
        "traps_blocked": n(traps, "BLOCK"), "traps_held_ask": n(traps, "ASK"), "traps_missed_pay": n(traps, "PAY"),
        "traps_with_expected_code": sum(1 for r in traps if r["caught_by_expected_code"]),
        "clean_auto_paid": n(clean, "PAY"), "clean_falsely_held": n(clean, "ASK"),
        "clean_false_blocks": n(clean, "BLOCK"), "verification": "canned sandbox fixtures (offline)",
    }
    summary["claim"] = ("zero false blocks on our clean controls, measured"
                        if summary["clean_false_blocks"] == 0 else "false blocks present")
    return {"summary": summary, "rows": rows}
