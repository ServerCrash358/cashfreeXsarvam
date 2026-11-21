"""Invariants and soft checks (ARCHITECTURE section C). Pure functions."""
from __future__ import annotations

import re
from decimal import Decimal
from typing import Optional

from panch.models import CheckResult, Invoice

PAISA = Decimal("0.01")
_GST_CHARS = "0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ"
GSTIN_RE = re.compile(r"^\d{2}[A-Z]{5}\d{4}[A-Z][1-9A-Z]Z[0-9A-Z]$")
IFSC_RE = re.compile(r"^[A-Z]{4}0[A-Z0-9]{6}$")


def _r(code, passed, severity, evidence, key=None) -> CheckResult:
    return CheckResult(code, passed, severity, evidence, key or code.lower())


def gstin_checksum_char(first14: str) -> str:
    total = 0
    for i, ch in enumerate(first14):
        p = _GST_CHARS.index(ch) * (1 if i % 2 == 0 else 2)
        total += p // 36 + p % 36
    return _GST_CHARS[(36 - total % 36) % 36]


def gstin_valid(gstin: Optional[str]) -> bool:
    if not gstin or not GSTIN_RE.match(gstin):
        return False
    return gstin_checksum_char(gstin[:14]) == gstin[14]


def _s(v) -> str:
    return None if v is None else str(v)


def run_invariants(inv: Invoice, cfg: dict) -> list[CheckResult]:
    """Hard invariants (BLOCK on failure) and soft checks (ASK). Missing data -> ASK, never silent pass."""
    out: list[CheckResult] = []
    tol_line = Decimal(str(cfg.get("line_tolerance", "0.01")))
    tol_total = Decimal(str(cfg.get("total_tolerance", "1.00")))

    # ARITH_LINE
    for i, ln in enumerate(inv.lines):
        expected = (ln.qty * ln.rate - ln.discount).quantize(PAISA)
        ok = abs(expected - ln.amount) <= tol_line
        if not ok:
            out.append(_r("ARITH_LINE", False, "block",
                          {"line": i + 1, "item": ln.item_key, "qty_x_rate": _s(expected), "printed": _s(ln.amount)}))
    if inv.lines and not any(c.code == "ARITH_LINE" for c in out):
        out.append(_r("ARITH_LINE", True, "info", {"lines": len(inv.lines)}))

    line_sum = sum((ln.amount for ln in inv.lines), Decimal("0"))
    # ARITH_SUBTOTAL
    if inv.subtotal is not None and inv.lines:
        ok = abs(line_sum - inv.subtotal) <= tol_line * max(1, len(inv.lines))
        out.append(_r("ARITH_SUBTOTAL", ok, "info" if ok else "block",
                      {"sum_of_lines": _s(line_sum), "printed_subtotal": _s(inv.subtotal)}))
    # ARITH_TOTAL
    if inv.total is None or inv.subtotal is None:
        out.append(_r("LOW_CONFIDENCE_READ", False, "ask", {"field": "total/subtotal", "reason": "missing"}))
    else:
        tax = inv.tax or Decimal("0")
        expected = inv.subtotal + tax
        ok = abs(expected - inv.total) <= tol_total
        out.append(_r("ARITH_TOTAL", ok, "info" if ok else "block",
                      {"subtotal": _s(inv.subtotal), "tax": _s(tax), "subtotal_plus_tax": _s(expected),
                       "printed_total": _s(inv.total), "gap": _s(inv.total - expected)}))
        # tax components must add up to tax
        parts = [p for p in (inv.cgst, inv.sgst, inv.igst) if p is not None]
        if parts and abs(sum(parts, Decimal("0")) - tax) > tol_line * 2:
            out.append(_r("ARITH_TOTAL", False, "block",
                          {"tax_components": [_s(p) for p in parts], "printed_tax": _s(tax)}, "arith_tax_parts"))
    # ARITH_WORDS
    if inv.words_amount is not None and inv.total is not None:
        ok = inv.words_amount == inv.total
        out.append(_r("ARITH_WORDS", ok, "info" if ok else "block",
                      {"in_words": _s(inv.words_amount), "in_figures": _s(inv.total),
                       "native": inv.raw_native.get("amount_in_words")}))
    elif inv.raw_native.get("amount_in_words") and inv.words_amount is None:
        out.append(_r("LOW_CONFIDENCE_READ", False, "ask",
                      {"field": "amount_in_words", "native": inv.raw_native.get("amount_in_words"),
                       "reason": "could not read the amount in words"}))

    out.extend(gst_split(inv))
    out.extend(soft_checks(inv, cfg))
    # unstable reads on money-critical fields
    for f in ("account_number", "ifsc", "total", "subtotal"):
        if inv.stable.get(f) is False:
            out.append(_r("LOW_CONFIDENCE_READ", False, "ask", {"field": f, "reason": "reads disagree"}))
    if inv.date_ambiguous:
        out.append(_r("LOW_CONFIDENCE_READ", False, "ask", {"field": "date", "reason": "day/month ambiguous"}))
    return out


def gst_split(inv: Invoice) -> list[CheckResult]:
    tax = inv.tax or Decimal("0")
    if tax == 0 and not any((inv.cgst, inv.sgst, inv.igst)):
        return [_r("ARITH_GST_SPLIT", True, "info", {"note": "no GST charged"})]
    if not inv.gstin or not inv.buyer_gstin:
        return [_r("ARITH_GST_SPLIT", False, "ask", {"reason": "GSTIN missing; cannot check split"})]
    same_state = inv.gstin[:2] == inv.buyer_gstin[:2]
    cg, sg, ig = inv.cgst or Decimal("0"), inv.sgst or Decimal("0"), inv.igst or Decimal("0")
    if same_state:
        ok = ig == 0 and cg == sg and cg > 0
        expect = "CGST = SGST, no IGST (same state)"
    else:
        ok = cg == 0 and sg == 0 and ig > 0
        expect = "IGST only (different states)"
    stable = inv.stable.get("gstin", True) and inv.stable.get("buyer_gstin", True)
    sev = "info" if ok else ("block" if stable else "ask")
    return [_r("ARITH_GST_SPLIT", ok, sev,
               {"vendor_state": inv.gstin[:2], "buyer_state": inv.buyer_gstin[:2], "expected": expect,
                "cgst": _s(cg), "sgst": _s(sg), "igst": _s(ig)})]


def soft_checks(inv: Invoice, cfg: dict) -> list[CheckResult]:
    out = []
    if inv.gstin and not gstin_valid(inv.gstin):
        out.append(_r("GSTIN_FORMAT", False, "ask", {"gstin": inv.gstin, "note": "format/checksum (soft)"}))
    if inv.ifsc and not IFSC_RE.match(inv.ifsc):
        out.append(_r("IFSC_FORMAT", False, "ask", {"ifsc": inv.ifsc}))
    slabs = [Decimal(str(s)) for s in cfg.get("gst_slabs", [0, 5, 12, 18, 28])]
    if inv.subtotal and inv.tax:
        rate = (inv.tax / inv.subtotal * 100).quantize(Decimal("0.1"))
        if not any(abs(rate - s) <= Decimal("0.2") for s in slabs):
            out.append(_r("TAX_RATE", False, "ask", {"effective_rate_pct": _s(rate)}))
    limit = cfg.get("per_invoice_limit")
    if limit and inv.total and inv.total > Decimal(str(limit)):
        out.append(_r("OVER_LIMIT", False, "ask", {"total": _s(inv.total), "limit": str(limit)}))
    return out
