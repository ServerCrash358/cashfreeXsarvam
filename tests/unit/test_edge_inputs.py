"""Edge-input hardening for PR2 pure modules (additive; adapts to main's APIs).

Covers: zero/empty/negative money, tolerance boundaries, GSTIN and IFSC
variants, current-config tax boundaries, date edges, duplicate windows,
decision precedence. Every assertion holds severity != block unless the
spec mandates BLOCK.
"""

from datetime import date
from decimal import Decimal as D

from panch.checks import run_invariants
from panch.decide import decide
from panch.fingerprint import HistoryEntry, route_duplicates
from panch.models import Invoice, LineItem

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CFG = json.loads((ROOT / "config" / "settings.json").read_text(encoding="utf-8"))

TODAY = date(2026, 11, 10)
VALID_GSTIN = "29AAFFK7777F1ZT"  # passes the checksum gate (used across the suite)


def inv(id_="X", **kw) -> Invoice:
    base = dict(
        id=id_, source_hash="h", vendor_name_raw="Acme", vendor_key="acm",
        gstin=VALID_GSTIN, number_raw="1", number_norm="1", date=TODAY,
        date_ambiguous=False,
        lines=[LineItem("bolt", D("10"), D("100"), D("1000"))],
        subtotal=D("1000"), tax=D("0"), total=D("1000"),
        words_amount=D("1000"), payee_name="Acme",
        account_number="111122223333", ifsc="HDFC0000001",
        buyer_gstin="29AAICP2912R1ZR",
    )
    base.update(kw)
    return Invoice(**base)


def failed(results):
    return [c for c in results if not c.passed]


def codes(results):
    return {c.code for c in failed(results)}


# ---- money shapes ----

def test_zero_value_invoice_no_crash_no_block():
    zero = inv(lines=[LineItem("free", D("1"), D("0"), D("0"))],
               subtotal=D("0"), tax=D("0"), total=D("0"), words_amount=D("0"))
    assert all(c.severity != "block" for c in failed(run_invariants(zero, CFG)))


def test_empty_lines_skips_quietly():
    e = inv(lines=[], subtotal=None, tax=None, total=D("0"), words_amount=D("0"))
    res = failed(run_invariants(e, CFG))
    assert all(c.severity != "block" for c in res)
    assert "LOW_CONFIDENCE_READ" in {c.code for c in res}


def test_credit_note_negative_amounts_pass():
    cn = inv(lines=[LineItem("ret", D("1"), D("-100"), D("-100"))],
             subtotal=D("-100"), tax=None, total=None, words_amount=None)
    assert "ARITH_LINE" not in codes(run_invariants(cn, CFG))


def test_line_tolerance_boundary():
    ok = inv(lines=[LineItem("x", D("3"), D("33.33"), D("100.00"))],
             subtotal=D("100.00"), total=D("100.00"), words_amount=None)
    assert "ARITH_LINE" not in codes(run_invariants(ok, CFG))
    bad = inv(lines=[LineItem("x", D("3"), D("33.33"), D("100.02"))],
              subtotal=D("100.02"), total=D("100.02"), words_amount=None)
    r = [c for c in run_invariants(bad, CFG) if c.code == "ARITH_LINE" and not c.passed]
    assert r and all(c.severity == "block" for c in r)


def test_total_tolerance_boundary():
    assert "ARITH_TOTAL" not in codes(run_invariants(inv(total=D("1001.00")), CFG))
    r = [c for c in run_invariants(inv(total=D("1001.01")), CFG)
         if c.code == "ARITH_TOTAL" and not c.passed]
    assert r and all(c.severity == "block" for c in r)


# ---- identifier variants ----

def test_gstin_valid_passes_variants_flag_soft():
    assert "GSTIN_FORMAT" not in codes(run_invariants(inv(gstin=VALID_GSTIN), CFG))
    for bad in ("29AAFFK7777F1ZX", "SHORT", "29AAFFK7777F1ZA"):
        r = [c for c in run_invariants(inv(gstin=bad), CFG) if c.code == "GSTIN_FORMAT"]
        assert r and all(c.severity == "ask" for c in r), bad


def test_ifsc_variants_never_block():
    assert "IFSC_FORMAT" not in codes(run_invariants(inv(ifsc="HDFC0000001"), CFG))
    for bad in ("HDFC000001", "hdfc0000001", "NOTANIFSC"):
        r = [c for c in run_invariants(inv(ifsc=bad), CFG) if c.code == "IFSC_FORMAT"]
        assert r and all(c.severity != "block" for c in r), bad


def test_tax_boundaries_follow_current_config():
    assert "TAX_RATE" not in codes(run_invariants(inv(subtotal=D("1000"), tax=D("180"),
                                                       total=D("1180")), CFG))
    assert "TAX_RATE" not in codes(run_invariants(inv(subtotal=D("1000"), tax=D("50"),
                                                       total=D("1050")), CFG))
    r = [c for c in run_invariants(inv(subtotal=D("1000"), tax=D("70"),
                                       total=D("1070")), CFG) if c.code == "TAX_RATE"]
    assert r and all(c.severity == "ask" for c in r)


def test_missing_and_ambiguous_dates_ask():
    assert "LOW_CONFIDENCE_READ" in codes(run_invariants(inv(total=None), CFG))
    assert "LOW_CONFIDENCE_READ" in codes(run_invariants(inv(date_ambiguous=True), CFG))


# ---- duplicate windows ----

def hist(prev, status="paid"):
    return [HistoryEntry(prev, "V1", status)]


def test_recurring_twin_in_new_period_silent():
    from datetime import timedelta
    old = inv("P", date=TODAY - timedelta(days=31))
    new = inv("N", number_norm="2", date=TODAY)
    assert failed(route_duplicates(new, hist(old), "V1", recurring=True, cfg=CFG)) == []


def test_same_content_off_by_days_is_fuzzy_not_exact():
    from datetime import timedelta
    old = inv("P", date=TODAY - timedelta(days=4))
    new = inv("N", number_norm="2", date=TODAY)
    res = failed(route_duplicates(new, hist(old), "V1", cfg=CFG))
    assert [c.code for c in res] == ["DUP_FUZZY"]


def test_unknown_vendor_is_info_only():
    assert failed(route_duplicates(inv("N"), hist(inv("P")), None)) == []


def test_other_vendor_never_matches():
    old = inv("P")
    new = inv("N", vendor_key="other")
    assert failed(route_duplicates(new, hist(old), "V2", cfg=CFG)) == []


# ---- decision precedence ----

def test_block_beats_multiple_asks_with_all_codes():
    bad = inv(total=D("2000"))
    d = decide(bad, run_invariants(bad, CFG))
    assert d.outcome.value == "BLOCK"
    assert {"ARITH_TOTAL"} <= set(d.codes)


def test_failed_info_never_decides():
    from panch.models import CheckResult
    d = decide(inv(), [CheckResult("NOTE", False, "info", {}, "note")])
    assert d.outcome.value == "PAY"


def test_over_limit_lives_in_checks_as_ask():
    big = inv(lines=[LineItem("x", D("1"), D("200000"), D("200000"))],
              subtotal=D("200000"), total=D("200000"), words_amount=None)
    r = [c for c in run_invariants(big, CFG) if c.code == "OVER_LIMIT"]
    assert r and all(c.severity == "ask" for c in r)


def test_every_result_has_code_and_template_key():
    for c in run_invariants(inv(total=D("2000")), CFG):
        assert c.code and c.message_key
    d = decide(inv(), run_invariants(inv(), CFG))
    assert all(c.code and c.message_key for c in d.checks)
