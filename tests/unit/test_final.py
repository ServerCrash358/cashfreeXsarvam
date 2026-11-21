"""U-PAY-13 shuffle test, GSTIN/Udyam identity checks, GST-parts tax fallback, recorded Vision contract."""
import json
import random
from decimal import Decimal as D
from pathlib import Path

from panch.checks import effective_tax, run_invariants
from panch.engine import Engine
from panch.vendors import verify_identity
from tests.unit.test_more import CFG, inv

ROOT = Path(__file__).resolve().parents[2]


def test_u_pay_13_hundred_shuffled_event_sequences_never_double_pay():
    """100 shuffled + duplicated webhook sequences: one transfer per invoice, final state by rank, no repay."""
    rng = random.Random(13)
    for trial in range(100):
        e = Engine(live=False); e.cfg["payout_mode"] = "sim"
        _, b = e.make_plan(D("4000"))                                       # H only
        e.approve_voice(b.id, f"yes 1 bill 4000 code {b.code}"); e.approve_pin(b.id, "2468"); e.execute(b.id)
        tid = e.ledger.for_invoice("H")[0].transfer_id
        evs = [("PENDING", None), ("SUCCESS", "COMPLETED"), ("SUCCESS", "COMPLETED"), ("PENDING", None)]
        if trial % 2:
            evs.append(("REVERSED", None))
        seq = evs + rng.sample(evs, k=len(evs))                              # duplicates
        rng.shuffle(seq)
        for n, (st, sc) in enumerate(seq):
            body = {"event_time": str(n % 3), "data": {"transfer_id": tid, "status": st, "status_code": sc}}
            e.webhook(json.dumps(body).encode(), {}, verify=False)
            e.sweep()
        atts = e.ledger.for_invoice("H")
        assert len(atts) == 1, trial                                        # never a second transfer
        assert atts[0].state in ("SUCCESS", "REVERSED"), (trial, atts[0].state)
        if atts[0].state == "REVERSED":
            assert e.state["H"]["payment"] == "reversed"                    # reopened, not repaid
        e.audit.reset()


class IdClient:
    def __init__(self, gst, udyam):
        self.g, self.u = gst, udyam

    def gstin(self, gstin, name=None):
        return self.g

    def udyam(self, udyam, vid):
        return self.u


def test_identity_checks_only_ever_ask():
    ok = verify_identity(inv(), IdClient({"valid": True, "legal_name_of_business": "Acme"},
                                         {"status": "SUCCESS", "enterprise_type": "Micro"}), CFG, udyam="UDYAM-X")
    assert all(c.passed for c in ok)
    bad = verify_identity(inv(), IdClient({"valid": False}, {"status": "UDYAM_NOT_FOUND"}), CFG, udyam="UDYAM-X")
    assert bad and all(c.severity == "ask" for c in bad)
    renamed = verify_identity(inv(payee_name="Totally Different Traders Pvt Ltd"),
                              IdClient({"valid": True, "legal_name_of_business": "Zebra Logistics"}, {}), CFG)
    assert any(c.code == "NAME_MISMATCH" and not c.passed for c in renamed)


def test_new_vendor_lane_runs_gstin_check():
    from panch.vendors import verify_vendor
    seen = {}

    class C(IdClient):
        def bank(self, *a, **k):
            return {"account_status": "VALID", "name_at_bank": "ACME"}

        def gstin(self, gstin, name=None):
            seen["gstin"] = gstin
            return {"valid": None}
    lane, ch = verify_vendor(inv(), None, [], C({}, {}), CFG)
    assert lane == "NEW_VENDOR" and seen["gstin"] == "29AAFFK7777F1ZT"
    assert any(c.code == "VENDOR_UNVERIFIABLE" and c.severity == "ask" for c in ch)


def test_tax_falls_back_to_gst_parts_when_total_tax_not_printed():
    i = inv(tax=None, subtotal=D("7500"), total=D("9600"), words_amount=None, igst=D("2100"),
            gstin="27AABCC5555E1ZT")
    assert effective_tax(i) == D("2100")
    assert not [c for c in run_invariants(i, CFG) if c.code == "ARITH_TOTAL" and not c.passed]


def test_recorded_vision_contract_masks_account_and_keeps_fields():
    rec = json.loads((ROOT / "tests" / "contract" / "vision_read_inv_B_hi.json").read_text(encoding="utf-8"))
    blob = json.dumps(rec, ensure_ascii=False)
    assert "000100289877623" not in blob                                    # exported reads are masked
    assert "18000" in blob.replace(",", "")


# ---------------------------------------------------- review fixes (second Claude review)
class _DupClient:
    secret = "s"

    def __init__(self, status_body=None):
        self.status_body = status_body

    def get_status(self, tid):
        if self.status_body is None:
            raise TimeoutError("status endpoint down")
        return 200, self.status_body


def _attempt(e):
    from panch.payouts import Attempt, apply_event
    a = e.ledger.add(Attempt("pn_dup", "B", "b", "x", D("18000")))
    apply_event(a, "SENT")
    return a


def test_duplicate_response_with_status_down_is_unknown_never_failed():
    """Regression: a 409 duplicate + failed status call used to mark FAILED, which allowed a second payment."""
    e = Engine(live=False); e.payouts = _DupClient(None)
    a = _attempt(e)
    e._apply_cf(a, {"code": "transfer_id_already_exists", "message": "dup"}, "api_response", http=409)
    assert a.state == "UNKNOWN"
    assert e.ledger.can_start("B", D("18000"), D("18000"))                 # no second attempt allowed


def test_duplicate_response_takes_original_status():
    e = Engine(live=False); e.payouts = _DupClient({"status": "SUCCESS", "status_code": "COMPLETED", "cf_transfer_id": "9"})
    a = _attempt(e)
    e._apply_cf(a, {"status": "REJECTED", "status_code": "DUPLICATE_TRANSFER"}, "api_response", http=200)
    assert a.state == "SUCCESS" and a.cf_transfer_id == "9"


def test_simulated_webhook_route_sim_only_and_no_secret_needed(monkeypatch):
    os = __import__("os"); os.environ["TIJORIPAY_OFFLINE"] = "1"
    from fastapi.testclient import TestClient
    import app.main as m
    c = TestClient(m.app)
    c.post("/api/reset"); m.engine.cfg["payout_mode"] = "sim"
    monkeypatch.setattr(m.engine.payouts, "sec", "")                       # empty secret, as on a teammate's .env
    p = c.post("/api/plan", json={"cash": "4000"}).json()
    c.post(f"/api/bundles/{p['bundle']['id']}/approve", data={"transcript": p["bundle"]["code"], "channel": "typed"})
    c.post(f"/api/bundles/{p['bundle']['id']}/pin", json={"pin": "2468"})
    c.post(f"/api/bundles/{p['bundle']['id']}/execute")
    for _ in range(3):
        c.post("/api/sweep")
    tid = m.engine.ledger.for_invoice("H")[0].transfer_id
    r = c.post("/api/simulate/webhook", json={"transfer_id": tid, "status": "REVERSED"}).json()
    assert r["state"] == "REVERSED" and r["simulated"] is True
    # an empty secret must never let a real webhook through
    assert c.post("/webhooks/cashfree/payouts", content=b"{}", headers={"x-webhook-signature": "x",
                                                                        "x-webhook-timestamp": "1"}).status_code == 401
    m.engine.cfg["payout_mode"] = "live"
    assert c.post("/api/simulate/webhook", json={"transfer_id": tid}).status_code == 403
    m.engine.cfg["payout_mode"] = "sim"
    c.post("/api/reset")                                                 # leave the shared app clean
