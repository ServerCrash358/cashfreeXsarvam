"""Offline unit tests (subset of docs/UNIT_TESTS.md). Cashfree and Sarvam are never called."""
import base64
import hashlib
import hmac
from datetime import date, datetime, timedelta
from decimal import Decimal as D

import pytest

from panch.approval import check_approval, confirm_pin, hash_pin, make_bundle
from panch.cashfree import verify_signature
from panch.checks import gstin_valid, run_invariants
from panch.decide import decide
from panch.engine import Engine
from panch.models import BundleItem, Outcome, PlanItem
from panch.normalise import norm_invoice_number, parse_amount, parse_date, vendor_key, words_to_amount
from panch.payouts import Attempt, Ledger, apply_event, transfer_id
from panch.planner import plan
from panch.vendors import name_score
from panch.voice.digits import extract_digits


# ---------------------------------------------------------------- normalise
@pytest.mark.parametrize("text,expected", [
    ("₹1,25,000/-", D("125000.00")), ("Rs. 18,000.50", D("18000.50")), ("१८,०००", D("18000.00")),
    ("௪௦", D("40.00")), ("1.5 lakh", D("150000.00")), ("2 करोड़", D("20000000.00")), ("abc", None),
])
def test_parse_amount(text, expected):
    assert parse_amount(text) == expected


def test_traditional_tamil_numerals_not_parsed():
    assert parse_amount("௲") is None


@pytest.mark.parametrize("text,lang,expected", [
    ("Twenty One Thousand Rupees Only", "en", D("21000")), ("Twelve Thousand Four Hundred Only", "en", D("12400")),
    ("अठारह हज़ार रुपये मात्र", "hi", D("18000")), ("One Lakh Twenty Five Thousand", "en", D("125000")),
    ("Twenty blorp", "en", None),
])
def test_words_to_amount(text, lang, expected):
    assert words_to_amount(text, lang) == expected


def test_dates():
    assert parse_date("5 Nov 2026") == (date(2026, 11, 5), False)
    assert parse_date("05-Nov-2026") == (date(2026, 11, 5), False)
    assert parse_date("11 नवंबर 2026") == (date(2026, 11, 11), False)
    assert parse_date("9 நவம்பர் 2026") == (date(2026, 11, 9), False)
    assert parse_date("2026-11-12") == (date(2026, 11, 12), False)
    assert parse_date("05/11/2026") == (date(2026, 11, 5), True)       # ambiguous day/month
    assert parse_date("25/11/2026") == (date(2026, 11, 25), False)
    assert parse_date("3rd November 2026") == (date(2026, 11, 3), False)


def test_invoice_number_keeps_financial_year():
    assert norm_invoice_number("KE/0312/2026-27") == norm_invoice_number("ke-312/26-27")
    assert norm_invoice_number("42/2025-26") != norm_invoice_number("42/2026-27")


def test_vendor_key_phonetic():
    assert vendor_key("Sri Venkateshwara Traders") == vendor_key("Venkateswara")


def test_gstin_checksum_soft():
    assert gstin_valid("29AAICP2912R1ZR")
    assert not gstin_valid("29AAICP2912R1ZX")


# ------------------------------------------------------------ name matching
def test_name_score():
    assert name_score("JOHN DOE", "John Doe") == 100
    assert name_score("John Doe Packaging", "John Doe") >= 85        # proprietor inside business name
    assert name_score("J Doe", "John Doe") >= 85
    assert name_score("TOM WELLS", "Lakshmi Narayanan") < 60


# --------------------------------------------------------------- whole batch
@pytest.fixture(scope="module")
def engine():
    e = Engine(live=False)
    e.cfg["payout_mode"] = "sim"
    e.payouts.sec = "test-webhook-secret"   # an empty secret is rejected: anyone could forge that signature
    return e


def test_demo_batch_decisions(engine):
    got = {k: (s["decision"].outcome, s["decision"].codes) for k, s in engine.state.items()}
    for k in "ABCH":
        assert got[k][0] == Outcome.PAY, k
    assert got["D"] == (Outcome.BLOCK, ["DUP_EXACT"])
    assert got["E"][0] == Outcome.BLOCK and "ARITH_TOTAL" in got["E"][1]
    assert got["F"] == (Outcome.ASK, ["ACCOUNT_CHANGED"])
    assert got["G"][0] == Outcome.BLOCK and "NAME_MISMATCH" in got["G"][1]


def test_every_failed_check_has_templates(engine):
    from panch.voice import template_path
    for s in engine.state.values():
        for c in s["decision"].checks:
            if not c.passed:
                for lang in ("en", "hi", "ta"):
                    assert template_path(c.message_key, lang).exists(), (c.message_key, lang)


def test_recurring_twin_not_duplicate(engine):
    # B repeats last month's Ganesh bill exactly (recurring vendor, new period): must stay PAY
    assert engine.state["B"]["decision"].outcome == Outcome.PAY


def test_callback_mismatch_blocks_and_uses_master_phone(engine):
    s = engine.start_callback("F")
    assert s.phone_used == "9876501234" and s.invoice_phone_ignored == "9123409876"
    res = engine.finish_callback(s.id, "the last four digits are seven seven two three")
    assert res.code == "CALLBACK_MISMATCH" and not res.passed
    assert engine.state["F"]["decision"].outcome == Outcome.BLOCK


def test_plan_and_full_payout_flow(engine):
    p, b = engine.make_plan(D("30000"))
    assert [i.invoice_id for i in p.chosen] == ["H", "B"]
    assert p.protected == D("22000") and p.naive_protected == D("16400")
    assert engine.approve_pin(b.id, "2468")                                   # PIN before voice refused
    r = engine.approve_voice(b.id, f"haan, 2 bill, 22,000 rupaye, code {' '.join(b.code)}")
    assert r.ok, r.reasons
    assert engine.approve_pin(b.id, "0000") == ["wrong PIN"]
    assert engine.approve_pin(b.id, "2468") == []
    engine.execute(b.id)
    with pytest.raises(ValueError):
        engine.execute(b.id)                                                  # single use
    for _ in range(3):
        engine.sweep()
    assert engine.state["H"]["payment"] == "paid" and engine.state["B"]["payment"] == "paid"
    # signed reversal webhook reopens H; never auto-repaid
    tid = engine.ledger.for_invoice("H")[0].transfer_id
    body = b'{"type":"TRANSFER_REVERSED","event_time":"t1","data":{"transfer_id":"%s","status":"REVERSED"}}' % tid.encode()
    ts = "1700000000"
    sig = base64.b64encode(hmac.new(engine.payouts.secret.encode(), ts.encode() + body, hashlib.sha256).digest()).decode()
    assert engine.webhook(body, {"x-webhook-timestamp": ts, "x-webhook-signature": "bad"})["ok"] is False
    assert engine.webhook(body, {"x-webhook-timestamp": ts, "x-webhook-signature": sig})["state"] == "REVERSED"
    assert engine.webhook(body, {"x-webhook-timestamp": ts, "x-webhook-signature": sig}).get("duplicate")
    assert engine.state["H"]["payment"] == "reversed"
    assert engine.state["H"]["decision"].outcome == Outcome.ASK
    assert len(engine.ledger.for_invoice("H")) == 1
    assert engine.audit.verify_chain()


# ----------------------------------------------------------------- approval
def _bundle(now):
    items = [BundleItem("H", "b1", "h1", D("4000")), BundleItem("B", "b2", "h2", D("18000"))]
    return make_bundle(items, D("30000"), now, nonce="n1")


def test_bundle_changes_invalidate():
    now = datetime(2026, 11, 21, 12)
    b = _bundle(now)
    b.items[0] = BundleItem("H", "b1", "h1", D("4001"))
    assert "bundle changed (hash mismatch)" in check_approval(b, f"yes 2 22000 {b.code}", now).reasons


def test_approval_rules():
    now = datetime(2026, 11, 21, 12)
    b = _bundle(now)
    assert check_approval(b, f"yes two bills twenty two thousand code {' '.join(b.code)}", now).ok
    assert not check_approval(b, f"haan... nahi, 2 22000 {b.code}", now).ok             # ambiguous
    assert not check_approval(b, "haan kar do", now).ok                                # no code/total
    assert not check_approval(b, f"yes 2 22000 {b.code}", now + timedelta(minutes=3)).ok  # expired
    b.status = "used"
    assert "replay: bundle already used" in check_approval(b, f"yes 2 22000 {b.code}", now).reasons


def test_pin_requires_voice_first():
    now = datetime(2026, 11, 21, 12)
    b = _bundle(now)
    assert confirm_pin(b, "1", hash_pin("1", "s"), "s", now)
    b.status = "voice_ok"
    assert confirm_pin(b, "1", hash_pin("1", "s"), "s", now) == []


# ------------------------------------------------------------------ payouts
def test_transfer_id_deterministic():
    t = transfer_id("V", "fp", "123", D("4000"), 1)
    assert t == transfer_id("V", "fp", "123", D("4000.00"), 1) and len(t) == 35 and t.startswith("pn_")
    assert t != transfer_id("V", "fp", "123", D("4000"), 2)


def test_state_machine_rank_and_completed():
    a = Attempt("t", "H", "b", "x", D("1"))
    apply_event(a, "SENT")
    apply_event(a, "SUCCESS", "SENT_TO_BENEFICIARY")
    assert a.state == "PENDING"                         # not final without COMPLETED
    apply_event(a, "SUCCESS", "COMPLETED")
    assert a.state == "SUCCESS"
    assert not apply_event(a, "PENDING")               # lower rank ignored
    apply_event(a, "REVERSED")
    assert a.state == "REVERSED"


def test_ledger_one_active_transfer():
    led = Ledger()
    led.add(Attempt("t1", "H", "b", "x", D("4000"), state="UNKNOWN"))
    assert led.can_start("H", D("4000"), D("4000"))
    with pytest.raises(ValueError):
        led.add(Attempt("t1", "H", "b", "x", D("4000")))


def test_webhook_signature():
    body, ts = b'{"a":1}', "123"
    sig = base64.b64encode(hmac.new(b"sec", b"123" + body, hashlib.sha256).digest()).decode()
    assert verify_signature("sec", ts, body, sig)
    assert not verify_signature("sec", ts, body + b" ", sig)


def test_extract_digits_multilingual():
    assert extract_digits("seven seven two three") == "7723"
    assert extract_digits("double seven two three") == "7723"
    assert extract_digits("सात सात दो तीन") == "7723"
    assert extract_digits("ஏழு ஏழு இரண்டு மூன்று") == "7723"
    assert extract_digits("1191") == "1191"


def test_planner_worked_example():
    items = [PlanItem("H", "v", D("4000"), date(2026, 11, 22)), PlanItem("A", "v", D("12400"), date(2026, 11, 24)),
             PlanItem("B", "v", D("18000"), date(2026, 11, 26)), PlanItem("C", "v", D("9600"), None)]
    p = plan(items, D("30000"), date(2026, 11, 21))
    assert p.protected == D("22000") and p.naive_protected == D("16400")


def test_decide_block_beats_ask():
    from panch.models import CheckResult
    e = Engine.__new__(Engine)
    inv = type("I", (), {"id": "x"})()
    d = decide(inv, [CheckResult("DUP_FUZZY", False, "ask", {}, "k"), CheckResult("ARITH_TOTAL", False, "block", {}, "k")])
    assert d.outcome == Outcome.BLOCK and d.codes[0] == "ARITH_TOTAL"


# ------------------------------------------------------------- eval harness
def test_eval_harness_scoreboard():
    from panch.eval import run
    s = run()["summary"]
    assert s["traps"] == 20 and s["clean"] == 20
    assert s["traps_missed_pay"] == 0
    assert s["clean_false_blocks"] == 0
    assert s["traps_with_expected_code"] == 20
