"""IT-CF-PAYOUT against the Cashfree sandbox (docs/INTEGRATION_TESTS.md). Sends Rs 1 sandbox transfers.
The sandbox must be funded (Payouts -> Fund Sources) or transfers come back REJECTED ERROR_SELECTING_FUND_SOURCE."""
import time
from datetime import datetime
from decimal import Decimal

import pytest

from panch.cashfree import PayoutsClient
from panch.payouts import CF_TO_STATE, Attempt, apply_event
from panch.vendors import account_hash

pytestmark = pytest.mark.integration

FINAL = {"SUCCESS", "FAILED", "REJECTED", "REVERSED"}


@pytest.fixture(scope="module")
def pc():
    c = PayoutsClient()
    if not (c.cid and c.sec):
        pytest.skip("Payouts keys not set in .env")
    return c


def _ben(pc, account, ifsc, name="Panch IT"):
    bid = "pn_it_" + account_hash(account, ifsc)[:12]
    code, body = pc.create_beneficiary(bid, name, account, ifsc)
    assert code in (200, 201, 409), (code, body)
    return bid


def _tid(tag):
    return f"pn_it_{tag}_{datetime.now():%m%d%H%M%S%f}"[:40]


def _send_and_poll(pc, account, ifsc, tag, polls=8):
    bid = _ben(pc, account, ifsc)
    tid = _tid(tag)
    att = Attempt(tid, tag, "it", bid, Decimal("1"))
    apply_event(att, "SENT")
    try:
        code, body = pc.transfer(tid, Decimal("1"), bid, remarks=f"Panch IT {tag}")
        if body.get("status") in CF_TO_STATE:
            apply_event(att, CF_TO_STATE[body["status"]], body.get("status_code"))
        elif 400 <= code < 500:
            apply_event(att, "FAILED", body.get("code"))
    except TimeoutError:
        apply_event(att, "UNKNOWN")
    for i in range(polls):
        if att.state in FINAL:
            break
        time.sleep(2 * 1.5 ** i)
        try:
            _, body = pc.get_status(tid)
        except TimeoutError:
            continue
        if body.get("status") in CF_TO_STATE:
            apply_event(att, CF_TO_STATE[body["status"]], body.get("status_code"))
    print(f"{tag}: {tid} -> {att.state} {att.status_code}")
    return att


def test_p1_host_authenticates(pc):
    code, body = pc.get_status("pn_it_does_not_exist")
    assert code in (200, 400, 404), (code, body)                 # auth OK; 401/403 would have raised
    print("P1 host:", pc.base, "->", code, body.get("code"))


def test_p2_p13_beneficiary_and_duplicate(pc):
    bid = _ben(pc, "000100289877623", "SBIN0008752")
    code, body = pc.create_beneficiary(bid, "Panch IT", "000100289877623", "SBIN0008752")
    assert code == 409, (code, body)                             # P13
    code, body = pc.get_beneficiary(bid)
    print("P2 beneficiary_status:", body.get("beneficiary_status"))


def test_p3_p12_rs1_transfer_reaches_final(pc):
    att = _send_and_poll(pc, "000100289877623", "SBIN0008752", "p3")
    assert att.state in FINAL, "still not final: record and re-check with scripts/smoke_payout.py --status"
    if att.status_code == "ERROR_SELECTING_FUND_SOURCE":
        pytest.fail("sandbox not funded: Payouts -> Fund Sources")
    assert att.state == "SUCCESS" and att.status_code == "COMPLETED"


def test_p4_same_transfer_id_is_rejected_as_duplicate(pc):
    bid = _ben(pc, "000100289877623", "SBIN0008752")
    tid = _tid("p4")
    pc.transfer(tid, Decimal("1"), bid)
    code, body = pc.transfer(tid, Decimal("1"), bid)
    print("P4 second POST:", code, body)
    assert body.get("status_code") == "DUPLICATE_TRANSFER" or body.get("code") == "transfer_id_already_exists"


@pytest.mark.parametrize("tag,account,ifsc", [("p5", "2640101002729", "CNRR0002640"),
                                              ("p6", "026291800001190", "YESB0000262")])
def test_p5_p6_bad_account_or_ifsc_fails(pc, tag, account, ifsc):
    bid = "pn_it_" + account_hash(account, ifsc)[:12]
    code, body = pc.create_beneficiary(bid, "Panch IT", account, ifsc)
    if code not in (200, 201, 409):
        print(f"{tag}: rejected at beneficiary: {code} {body.get('code')}")
        return
    att = _send_and_poll(pc, account, ifsc, tag)
    assert att.state in ("FAILED", "REJECTED")


def test_p8_pending_then_success(pc):
    assert _send_and_poll(pc, "00224412311300", "YESB0000001", "p8").state in ("SUCCESS", "PENDING")


def test_p9_pending_then_failure(pc):
    assert _send_and_poll(pc, "7766666351000", "YESB0000001", "p9").state in ("FAILED", "PENDING")


def test_p10_success_then_reversed_record_timing(pc):
    att = _send_and_poll(pc, "7766671735000", "SBIN0000004", "p10", polls=10)
    print("P10 history:", [(h["to"], h.get("status_code")) for h in att.history])
    assert att.state in ("SUCCESS", "REVERSED", "PENDING")


@pytest.mark.slow
def test_p11_timeout_account_recovers_by_polling_with_one_post(pc, monkeypatch):
    bid = _ben(pc, "34978321547298", "KKBK0000001")
    posts = []
    real = pc.transfer

    def counted(*a, **k):
        posts.append(a[0])
        return real(*a, **k)

    monkeypatch.setattr(pc, "transfer", counted)
    tid = _tid("p11")
    att = Attempt(tid, "p11", "it", bid, Decimal("1"))
    apply_event(att, "SENT")
    try:
        _, body = pc.transfer(tid, Decimal("1"), bid)
        apply_event(att, CF_TO_STATE.get(body.get("status"), "PENDING"), body.get("status_code"))
    except TimeoutError:
        apply_event(att, "UNKNOWN")
    for i in range(10):
        if att.state in FINAL:
            break
        time.sleep(3)
        try:
            _, body = pc.get_status(tid)
            if body.get("status") in CF_TO_STATE:
                apply_event(att, CF_TO_STATE[body["status"]], body.get("status_code"))
        except TimeoutError:
            pass
    print("P11:", [(h["to"], h.get("source")) for h in att.history])
    assert posts == [tid]                                        # exactly one POST, whatever happened
