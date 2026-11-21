"""Approving a changed account must require bank verification, not just a matching call-back.
Found 21 Nov: G (account registered to TOM WELLS, vendor holder Lakshmi Narayanan) went to PAY
after a matching call-back + PIN, because the approved account became KNOWN and the KNOWN lane
skips bank verification."""
from panch.engine import Engine

PIN = "2468"


def _confirm_callback(e: Engine, inv: str):
    s = e.start_callback(inv)
    assert e.finish_callback(s.id, " ".join(s.expected_last4)).passed


def _bank_checks(e: Engine, inv: str):
    return {(c.code, c.evidence.get("pair", "")): c.passed for c in e.state[inv]["decision"].checks}


def test_unverified_account_cannot_be_approved():
    e = Engine(live=False)
    _confirm_callback(e, "G")
    assert e.state["G"]["decision"].outcome.value == "BLOCK"          # canned: TOM WELLS at the bank
    reasons = e.approve_account_change("G", PIN)
    assert reasons and "bank verification" in reasons[0]
    assert e.state["G"]["decision"].outcome.value != "PAY"
    v = e.vendor(e.state["G"]["vendor_id"])
    assert not any(a.provenance == "call-back" for a in v.accounts)


def test_verified_account_is_approved_once():
    e = Engine(live=False)
    _confirm_callback(e, "F")
    assert _bank_checks(e, "F")[("BANK_INVALID", "")]                # canned: JOHN DOE, VALID
    assert e.approve_account_change("F", PIN) == []
    v = e.vendor(e.state["F"]["vendor_id"])
    n = sum(1 for a in v.accounts if a.provenance == "call-back")
    assert e.approve_account_change("F", PIN) == []          # second approval is a no-op
    assert sum(1 for a in v.accounts if a.provenance == "call-back") == n == 1


def test_wrong_pin_still_refused():
    e = Engine(live=False)
    _confirm_callback(e, "F")
    assert e.approve_account_change("F", "0000")
