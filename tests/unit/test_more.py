"""More offline unit + API tests (UNIT_TESTS.md U-CHK, U-FP, U-VEN, U-PLAN, U-PAY, U-AUD, U-PRIV)."""
import copy
import json
import os
from datetime import date, datetime
from decimal import Decimal as D
from pathlib import Path

import pytest

from panch.audit import Audit
from panch.checks import run_invariants
from panch.engine import Engine
from panch.fingerprint import HistoryEntry, route_duplicates
from panch.models import Invoice, LineItem, Outcome, PlanItem, Vendor, VendorAccount
from panch.payouts import Attempt, Ledger, apply_event
from panch.planner import msme_deadline, plan
from panch.reading import invoice_from_extract
from panch.vendors import lane_for, name_score, verify_vendor
from panch.vendors.callback import finish_callback, start_callback
from panch.voice import _fmt, render

ROOT = Path(__file__).resolve().parents[2]
CFG = json.loads((ROOT / "config" / "settings.json").read_text(encoding="utf-8"))
BATCH = json.loads((ROOT / "data" / "fixtures" / "demo_batch.json").read_text(encoding="utf-8"))
RAW = {r["id"]: r for r in BATCH["invoices"]}


def inv(id_="X", **kw) -> Invoice:
    base = dict(id=id_, source_hash="h", vendor_name_raw="Acme", vendor_key="acm", gstin="29AAFFK7777F1ZT",
                number_raw="1", number_norm="1", date=date(2026, 11, 10), date_ambiguous=False,
                lines=[LineItem("bolt", D("10"), D("100"), D("1000"))], subtotal=D("1000"), tax=D("0"),
                total=D("1000"), words_amount=D("1000"), payee_name="Acme", account_number="111122223333",
                ifsc="HDFC0000001", buyer_gstin="29AAICP2912R1ZR")
    base.update(kw)
    return Invoice(**base)


def codes(checks, failed_only=True):
    return {c.code for c in checks if not (failed_only and c.passed)}


def vendor(**kw) -> Vendor:
    base = dict(id="V1", legal_name="Acme", gstin="29AAFFK7777F1ZT", udyam=None, enterprise_type="micro",
                msme_rule_applies=True, agreement_days=None, recurring=False, phone_on_file="9000000001",
                account_holder_name="Acme", language="en",
                accounts=[VendorAccount("111122223333", "HDFC0000001", "onboarding", "2026-01-01")])
    base.update(kw)
    return Vendor(**base)


class FakeBank:
    def __init__(self, name="ACME", status="VALID"):
        self.name, self.status, self.calls = name, status, 0

    def bank(self, account, ifsc, name=None):
        self.calls += 1
        return {"account_status": self.status, "name_at_bank": self.name, "canned": True}


# --------------------------------------------------------------- invariants
def test_clean_invoice_has_no_failures():
    assert codes(run_invariants(inv(), CFG)) == set()


def test_line_and_subtotal_and_words():
    bad = inv(lines=[LineItem("bolt", D("10"), D("100"), D("900"))], words_amount=D("1100"))
    c = codes(run_invariants(bad, CFG))
    assert {"ARITH_LINE", "ARITH_SUBTOTAL", "ARITH_WORDS"} <= c


def test_one_paisa_line_tolerance():
    ok = inv(lines=[LineItem("x", D("3"), D("33.33"), D("99.99"))], subtotal=D("99.99"), total=D("99.99"),
             words_amount=None)
    assert "ARITH_LINE" not in codes(run_invariants(ok, CFG))


def test_gst_split_intra_and_inter_state():
    intra_ok = inv(subtotal=D("1000"), tax=D("180"), total=D("1180"), words_amount=None, cgst=D("90"), sgst=D("90"))
    assert "ARITH_GST_SPLIT" not in codes(run_invariants(intra_ok, CFG))
    intra_bad = inv(subtotal=D("1000"), tax=D("180"), total=D("1180"), words_amount=None, igst=D("180"))
    r = [c for c in run_invariants(intra_bad, CFG) if c.code == "ARITH_GST_SPLIT"][0]
    assert not r.passed and r.severity == "block"
    inter_ok = inv(gstin="27AABCC5555E1ZT", subtotal=D("1000"), tax=D("180"), total=D("1180"), words_amount=None,
                   igst=D("180"))
    assert "ARITH_GST_SPLIT" not in codes(run_invariants(inter_ok, CFG))


def test_gst_split_asks_when_gstin_unstable():
    bad = inv(subtotal=D("1000"), tax=D("180"), total=D("1180"), words_amount=None, igst=D("180"),
              stable={"gstin": False})
    r = [c for c in run_invariants(bad, CFG) if c.code == "ARITH_GST_SPLIT"][0]
    assert r.severity == "ask"


def test_soft_checks_never_block():
    weird = inv(gstin="29AAFFK7777F1ZX", ifsc="HDFC000001", subtotal=D("1000"), tax=D("70"), total=D("1070"),
                words_amount=None, cgst=D("35"), sgst=D("35"))
    for c in run_invariants(weird, CFG):
        if c.code in ("GSTIN_FORMAT", "IFSC_FORMAT", "TAX_RATE"):
            assert c.severity == "ask"
    assert {"GSTIN_FORMAT", "IFSC_FORMAT", "TAX_RATE"} <= codes(run_invariants(weird, CFG))


def test_missing_total_or_unreadable_value_asks():
    assert "LOW_CONFIDENCE_READ" in codes(run_invariants(inv(total=None), CFG))
    r = copy.deepcopy(RAW["A"]); r["total"] = "12,4OO"           # letter O instead of zero
    assert "LOW_CONFIDENCE_READ" in codes(run_invariants(invoice_from_extract(r), CFG))
    assert "LOW_CONFIDENCE_READ" in codes(run_invariants(inv(date_ambiguous=True), CFG))


def test_over_limit_asks():
    big = inv(lines=[LineItem("x", D("1"), D("200000"), D("200000"))], subtotal=D("200000"), total=D("200000"),
              words_amount=None)
    assert "OVER_LIMIT" in codes(run_invariants(big, CFG))


# ---------------------------------------------------------------- duplicates
def test_dup_number_fuzzy_and_vendor_scoping():
    prev = inv("P", number_norm="KE312FY2627")
    hist = [HistoryEntry(prev, "V1", "paid")]
    assert "DUP_NUMBER" in codes(route_duplicates(inv("N", number_norm="KE312FY2627"), hist, "V1"))
    fuzzy = inv("N2", number_norm="9", date=date(2026, 11, 13), lines=[LineItem("nut", D("10"), D("100"), D("1000"))])
    assert "DUP_FUZZY" in codes(route_duplicates(fuzzy, hist, "V1"))
    assert codes(route_duplicates(inv("N3", number_norm="9"), hist, "V2")) == set()   # other vendor
    assert codes(route_duplicates(inv("N4"), hist, None)) == set()                     # unknown vendor


def test_same_po_identical_content_is_exact_duplicate():
    prev = inv("P", number_norm="1", po_number="PO-9")
    again = inv("N", number_norm="2", po_number="PO-9", date=date(2026, 11, 20))
    assert "DUP_EXACT" in codes(route_duplicates(again, [HistoryEntry(prev, "V1", "pending")], "V1"))


# ------------------------------------------------------------------- vendors
def test_lanes_and_bank_only_when_needed():
    v = vendor()
    bank = FakeBank()
    lane, ch = verify_vendor(inv(), v, [v], bank, CFG)
    assert lane == "KNOWN" and bank.calls == 0 and codes(ch) == set()
    lane, ch = verify_vendor(inv(account_number="999988887777"), v, [v], bank, CFG)
    assert lane == "CHANGED_ACCOUNT" and bank.calls == 1 and "ACCOUNT_CHANGED" in codes(ch)
    lane, ch = verify_vendor(inv(), None, [], FakeBank(), CFG)
    assert lane == "NEW_VENDOR" and "NEW_VENDOR" in codes(ch)


def test_bank_invalid_and_unverifiable():
    v = vendor()
    _, ch = verify_vendor(inv(account_number="9"), v, [v], FakeBank(status="INVALID"), CFG)
    assert "BANK_INVALID" in codes(ch)
    _, ch = verify_vendor(inv(account_number="9"), v, [v], FakeBank(status="UNVERIFIABLE"), CFG)
    r = [c for c in ch if c.code == "VENDOR_UNVERIFIABLE"][0]
    assert r.severity == "ask"                   # never BLOCK on sandbox gaps


def test_account_shared_blocks():
    a, b = vendor(), vendor(id="V2", legal_name="Other", gstin="29AAGFA2222G1ZU",
                            accounts=[VendorAccount("555566667777", "SBIN0000001", "onboarding", "2026-01-01")])
    _, ch = verify_vendor(inv(account_number="555566667777", ifsc="SBIN0000001"), a, [a, b], FakeBank(), CFG)
    assert "ACCOUNT_SHARED" in codes(ch)


def test_name_partial_asks():
    v = vendor()
    _, ch = verify_vendor(inv(account_number="9"), v, [v], FakeBank(name="ACMEE TRADING CORP"), CFG)
    sev = {c.severity for c in ch if c.code == "NAME_MISMATCH" and not c.passed}
    assert sev and sev <= {"ask", "block"}
    assert name_score("Venkateshwara Stores", "Venkateswara Stores") >= 85


def test_callback_match_no_answer_and_masking():
    v, i = vendor(), inv(account_number="026291800001191", vendor_phone_on_invoice="9123409876")
    s = start_callback(v, i)
    assert s.phone_used == v.phone_on_file
    assert s.public()["phone_used"].endswith("0001") and "9000000001" not in json.dumps(s.public())
    assert finish_callback(s, "one one nine one").passed
    assert finish_callback(s, "").code == "CALLBACK_NO_ANSWER"
    assert finish_callback(s, "nine one").code == "CALLBACK_NO_ANSWER"
    assert finish_callback(s, "ஒன்று ஒன்று ஒன்பது ஒன்று").passed


def test_callback_needs_phone_on_file():
    with pytest.raises(ValueError):
        start_callback(vendor(phone_on_file=None), inv())


# ------------------------------------------------------------------- planner
def test_msme_deadline_rules():
    d = date(2026, 11, 1)
    assert msme_deadline(d, vendor()) == date(2026, 11, 16)
    assert msme_deadline(d, vendor(agreement_days=60)) == date(2026, 12, 16)          # capped at 45
    assert msme_deadline(d, vendor(enterprise_type="medium")) is None
    assert msme_deadline(d, vendor(msme_rule_applies=False)) is None


def test_planner_never_exceeds_cash_and_greedy_fallback():
    items = [PlanItem(f"I{i}", "v", D(1000 + i), date(2026, 11, 22)) for i in range(30)]
    p = plan(items, D("10000"), date(2026, 11, 21), exact_limit=25)
    assert sum(i.amount for i in p.chosen) <= D("10000") and p.protected > 0
    p0 = plan(items, D("0"), date(2026, 11, 21))
    assert p0.chosen == [] and len(p0.deferred) == 30


# ------------------------------------------------------------------- payouts
def test_terminal_failure_ignores_later_success_and_ledger_cap():
    a = Attempt("t", "B", "b", "x", D("18000"))
    apply_event(a, "SENT"); apply_event(a, "REJECTED", "ERROR_SELECTING_FUND_SOURCE")
    assert not apply_event(a, "SUCCESS", "COMPLETED") and a.state == "REJECTED"
    led = Ledger(); led.add(a)
    assert led.can_start("B", D("18000"), D("18000")) is None                       # retry allowed after failure
    led.add(Attempt("t2", "B", "b", "x", D("18000"), state="SUCCESS"))
    assert led.can_start("B", D("1"), D("18000"))                                    # would exceed amount


def test_reversal_before_success_is_ignored():
    a = Attempt("t", "H", "b", "x", D("4000")); apply_event(a, "SENT")
    assert not apply_event(a, "REVERSED") and a.state == "SENT"


# --------------------------------------------------------------------- audit
def test_audit_detects_tampering(tmp_path):
    au = Audit(tmp_path / "a.jsonl")
    au.append("x", {"amount": "4000"}); au.append("y", {"amount": "18000"})
    assert au.verify_chain()
    au.entries[0]["payload"]["amount"] = "40000"
    assert not au.verify_chain()


def test_audit_never_holds_full_account_numbers():
    e = Engine(live=False)
    blob = json.dumps(e.audit.entries)
    for r in RAW.values():
        assert r["bank_account"] not in blob


# --------------------------------------------------------------------- voice
def test_indian_number_format_and_render():
    assert _fmt(D("125000")) == "1,25,000" and _fmt(22000) == "22,000" and _fmt(D("4000.50")) == "4,000.50"
    assert "22,000" in render("approval_prompt", "hi", count=2, total=D("22000"), code_spoken="1 2 3")
    assert render("dup_exact", "ta", matched_number="X") and "—" in render("dup_exact", "en")   # missing var
    assert render("no_such_key", "ta") == "no_such_key"


# ----------------------------------------------------------- engine flows
def test_callback_match_then_owner_approves_account_change():
    e = Engine(live=False)
    s = e.start_callback("F")
    assert e.finish_callback(s.id, "one one nine one").passed
    assert e.state["F"]["decision"].outcome == Outcome.ASK              # still needs the owner
    assert e.approve_account_change("F", "0000") == ["wrong PIN"]
    assert e.approve_account_change("F", "2468") == []
    assert e.state["F"]["lane"] == "KNOWN" and e.state["F"]["decision"].outcome == Outcome.PAY


def test_callback_only_for_changed_account():
    e = Engine(live=False)
    with pytest.raises(ValueError):
        e.start_callback("A")


def test_pin_lockout_after_three_wrong():
    e = Engine(live=False)
    _, b = e.make_plan()
    assert e.approve_voice(b.id, f"yes 2 bills 22000 code {b.code}").ok
    for _ in range(3):
        e.approve_pin(b.id, "1111")
    assert e.bundles[b.id].status == "locked"
    assert e.approve_pin(b.id, "2468")                                   # locked: correct PIN refused


def test_unknown_webhook_and_out_of_order():
    e = Engine(live=False); e.cfg["payout_mode"] = "sim"
    assert e.webhook(b'{"data":{"transfer_id":"nope","status":"SUCCESS"}}', {}, verify=False).get("unmatched")
    _, b = e.make_plan(D("4000"))
    e.approve_voice(b.id, f"yes 1 bill 4000 code {b.code}"); e.approve_pin(b.id, "2468"); e.execute(b.id)
    tid = e.ledger.for_invoice("H")[0].transfer_id
    e.webhook(json.dumps({"event_time": "1", "data": {"transfer_id": tid, "status": "SUCCESS",
                                                       "status_code": "COMPLETED"}}).encode(), {}, verify=False)
    r = e.webhook(json.dumps({"event_time": "0", "data": {"transfer_id": tid, "status": "PENDING"}}).encode(), {},
                  verify=False)
    assert r["state"] == "SUCCESS" and e.state["H"]["payment"] == "paid"


# ------------------------------------------------------------------ API layer
@pytest.fixture(scope="module")
def client():
    os.environ["TIJORIPAY_OFFLINE"] = "1"
    from fastapi.testclient import TestClient
    import app.main as m
    m.engine.cfg["payout_mode"] = "sim"
    return TestClient(m.app), m


def test_api_state_and_reasons_in_owner_language(client):
    c, _ = client
    s = c.get("/api/state?lang=ta").json()
    assert [i["outcome"] for i in s["invoices"]] == ["PAY", "PAY", "PAY", "BLOCK", "BLOCK", "ASK", "BLOCK", "PAY"]
    e = next(i for i in s["invoices"] if i["id"] == "E")
    assert "நிறுத்தப்பட்டது" in e["reasons"][0]["text"]
    assert all(len(i["account_last4"]) == 4 for i in s["invoices"])
    assert "026291800001191" not in json.dumps(s)                    # no full account numbers leave the server


def test_api_full_flow_with_signed_webhook(client):
    c, m = client
    c.post("/api/reset"); m.engine.cfg["payout_mode"] = "sim"
    p = c.post("/api/plan", json={"cash": "30000", "lang": "en"}).json()
    assert p["chosen"] == ["H", "B"] and p["protected"] == "22000.00"
    bid, code = p["bundle"]["id"], p["bundle"]["code"]
    assert c.post(f"/api/bundles/{bid}/execute").status_code == 400            # not approved yet
    r = c.post(f"/api/bundles/{bid}/approve", data={"transcript": f"haan 2 bill 22000 code {code}", "channel": "voice"})
    assert r.json()["ok"]
    assert c.post(f"/api/bundles/{bid}/pin", json={"pin": "2468"}).json()["ok"]
    assert len(c.post(f"/api/bundles/{bid}/execute").json()["results"]) == 2
    for _ in range(3):
        c.post("/api/sweep")
    tid = m.engine.ledger.for_invoice("H")[0].transfer_id
    assert c.post("/webhooks/cashfree/payouts", content=b"{}", headers={"x-webhook-signature": "x",
                                                                        "x-webhook-timestamp": "1"}).status_code == 401
    assert c.post("/api/simulate/webhook", json={"transfer_id": tid, "status": "REVERSED"}).json()["state"] == "REVERSED"
    s = c.get("/api/state").json()
    h = next(i for i in s["invoices"] if i["id"] == "H")
    assert h["payment"] == "reversed" and h["outcome"] == "ASK"
    assert c.get("/api/audit").json()["chain_ok"]


def test_api_typed_code_fallback_and_wrong_code(client):
    c, _ = client
    c.post("/api/reset")
    p = c.post("/api/plan", json={}).json()
    bid, code = p["bundle"]["id"], p["bundle"]["code"]
    wrong = str((int(code) + 1) % 1000).zfill(3)
    assert not c.post(f"/api/bundles/{bid}/approve", data={"transcript": wrong, "channel": "typed"}).json()["ok"]
    assert c.post(f"/api/bundles/{bid}/approve", data={"transcript": code, "channel": "typed"}).json()["ok"]
