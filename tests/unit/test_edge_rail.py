"""Edge tests across the payout-rail seams (A2/A3/B1/B2/C1). Additive only.

Pins down: planner boundaries, approval expiry/replay/tamper, UNKNOWN
recovery, callback mismatch code + phone masking, duplicate webhooks.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal as D

from panch.approval import bundle_still_matches, check_approval, make_bundle
from panch.engine import Engine
from panch.models import BundleItem, Invoice, LineItem, Vendor, VendorAccount
from panch.payouts import Attempt, apply_event
from panch.planner import msme_deadline, plan
from panch.vendors.callback import finish_callback, start_callback

DAY = date(2026, 11, 21)


def vendor(**kw) -> Vendor:
    base = dict(id="V1", legal_name="Acme", gstin="29AAFFK7777F1ZT", udyam=None,
                enterprise_type="micro", msme_rule_applies=True,
                agreement_days=None, recurring=False, phone_on_file="9000000001",
                account_holder_name="Acme", language="en",
                accounts=[VendorAccount("111122223333", "HDFC0000001",
                                        "onboarding", "2026-01-01")])
    base.update(kw)
    return Vendor(**base)


def bundle(items=(("I1", "B1", "aabbcc", "4000"),), cash="30000"):
    return make_bundle(
        [BundleItem(i, b, h, D(a)) for i, b, h, a in items],
        D(cash), datetime.now(),
    )


# ---- planner boundaries (C1) ----

def test_agreement_zero_means_no_agreement():
    assert msme_deadline(DAY, vendor(agreement_days=0)) == DAY + timedelta(days=15)


def test_empty_batch_plans_nothing():
    p = plan([], D("30000"), DAY)
    assert p.chosen == [] and p.deferred == [] and p.protected == D("0")


def test_exact_cash_boundary_picks_item():
    from panch.models import PlanItem
    items = [PlanItem("I1", "v", D("30000"), None)]
    p = plan(items, D("30000"), DAY)
    assert [i.invoice_id for i in p.chosen] == ["I1"] and p.deferred == []


# ---- approval binding (B2) ----

def test_expired_bundle_rejected():
    b = make_bundle([BundleItem("I1", "B1", "aa", D("4000"))], D("30000"),
                    datetime.now() - timedelta(minutes=5))
    r = check_approval(b, b.code, datetime.now(), channel="typed")
    assert not r.ok and "expired" in r.reasons


def test_tampered_bundle_rejected():
    b = bundle()
    b.items[0].amount = D("4001")
    assert not bundle_still_matches(b)
    r = check_approval(b, b.code, datetime.now(), channel="typed")
    assert not r.ok and "bundle changed (hash mismatch)" in r.reasons


def test_replay_after_used_rejected():
    b = bundle()
    b.status = "used"
    r = check_approval(b, b.code, datetime.now(), channel="typed")
    assert not r.ok and any("replay" in x for x in r.reasons)


# ---- UNKNOWN recovery (A2) ----

def test_unknown_recovers_via_status_poll():
    att = Attempt("t1", "H", "b", "B1", D("4000"))
    assert apply_event(att, "SENT", source="api")
    assert apply_event(att, "UNKNOWN", source="api timeout")
    assert att.state == "UNKNOWN"
    assert apply_event(att, "SUCCESS", "COMPLETED", source="poll")
    assert att.state == "SUCCESS"


def test_success_without_completed_stays_pending():
    att = Attempt("t2", "H", "b", "B1", D("4000"))
    assert apply_event(att, "SUCCESS", "SENT_TO_BENEFICIARY", source="api")
    assert att.state == "PENDING"


# ---- call-back (B1) ----

def test_callback_mismatch_blocks_with_code():
    v = vendor()
    i = Invoice(id="F", source_hash="h", vendor_name_raw="Acme", vendor_key="acm",
                gstin="29AAFFK7777F1ZT", number_raw="7", number_norm="7",
                date=DAY, date_ambiguous=False, lines=[], subtotal=None,
                tax=None, total=D("11000"), words_amount=None,
                payee_name="Acme", account_number="026291800001191",
                ifsc="YESB0000262")
    s = start_callback(v, i)
    assert s.phone_used == "9000000001"
    r = finish_callback(s, "one one nine two")
    assert r.code == "CALLBACK_MISMATCH" and not r.passed and r.severity == "block"


def test_callback_public_view_masks_phone():
    v = vendor()
    i = Invoice(id="F", source_hash="h", vendor_name_raw="Acme", vendor_key="acm",
                gstin=None, number_raw="7", number_norm="7", date=DAY,
                date_ambiguous=False, lines=[], subtotal=None, tax=None,
                total=D("11000"), words_amount=None, payee_name="Acme",
                account_number="026291800001191", ifsc="YESB0000262",
                vendor_phone_on_invoice="9123409876")
    s = start_callback(v, i)
    pub = s.public()
    assert pub["phone_used"].endswith("0001") and "9000000001" not in str(pub)
    assert "expected_last4" not in pub


# ---- webhooks (A3) ----

def test_duplicate_webhook_applied_once():
    import json
    e = Engine(live=False)
    e.cfg["payout_mode"] = "sim"
    _, b = e.make_plan(D("4000"))
    assert e.approve_voice(b.id, f"yes 1 bill 4000 code {b.code}").ok
    assert e.approve_pin(b.id, "2468") == []
    e.execute(b.id)
    tid = e.ledger.for_invoice("H")[0].transfer_id
    body = json.dumps({"event_time": "9", "data": {"transfer_id": tid, "status": "SUCCESS",
                                                   "status_code": "COMPLETED"}}).encode()
    first = e.webhook(body, {}, verify=False)
    second = e.webhook(body, {}, verify=False)
    assert first["state"] == "SUCCESS" and second.get("duplicate") is True
    assert e.ledger.for_invoice("H")[0].state == "SUCCESS"
