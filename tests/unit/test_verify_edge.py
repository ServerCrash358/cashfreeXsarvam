"""A1 edge tests: fraud-code hard block and verification caching (offline)."""

from datetime import date
from decimal import Decimal as D

from panch.cashfree import VerificationClient
from panch.models import Invoice, LineItem, Vendor, VendorAccount
from panch.vendors import FRAUD_BLOCK_CODES, verify_vendor

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CFG = json.loads((ROOT / "config" / "settings.json").read_text(encoding="utf-8"))

ACCT, IFSC = "999988887777", "HDFC0000001"


def inv(**kw) -> Invoice:
    base = dict(id="X", source_hash="h", vendor_name_raw="Acme", vendor_key="acm",
                gstin="29AAFFK7777F1ZT", number_raw="1", number_norm="1",
                date=date(2026, 11, 10), date_ambiguous=False,
                lines=[LineItem("bolt", D("10"), D("100"), D("1000"))],
                subtotal=D("1000"), tax=D("0"), total=D("1000"),
                words_amount=D("1000"), payee_name="Acme",
                account_number=ACCT, ifsc=IFSC,
                buyer_gstin="29AAICP2912R1ZR")
    base.update(kw)
    return Invoice(**base)


def vendor(**kw) -> Vendor:
    base = dict(id="V1", legal_name="Acme", gstin="29AAFFK7777F1ZT", udyam=None,
                enterprise_type="micro", msme_rule_applies=True,
                agreement_days=None, recurring=False, phone_on_file="9000000001",
                account_holder_name="Acme", language="en",
                accounts=[VendorAccount("111122223333", "HDFC0000001",
                                        "onboarding", "2026-01-01")])
    base.update(kw)
    return Vendor(**base)


class FakeBank:
    def __init__(self, status="VALID", code="ACCOUNT_IS_VALID", name="ACME"):
        self.status, self.code, self.name = status, code, name
        self.calls = 0

    def bank(self, account, ifsc, name=None):
        self.calls += 1
        return {"account_status": self.status, "account_status_code": self.code,
                "name_at_bank": self.name, "canned": True}


def failed(checks):
    return [c for c in checks if not c.passed]


def test_fraud_code_hard_blocks_even_when_status_not_invalid():
    bank = FakeBank(status="RECEIVED", code="FRAUD_ACCOUNT")
    _, ch = verify_vendor(inv(), vendor(), [vendor()], bank, CFG)
    r = [c for c in failed(ch) if c.code == "BANK_INVALID"]
    assert r and all(c.severity == "block" for c in r)
    assert r[0].evidence["account_status_code"] == "FRAUD_ACCOUNT"


def test_fraud_set_contains_fraud_account():
    assert "FRAUD_ACCOUNT" in FRAUD_BLOCK_CODES


def test_invalid_status_still_blocks_without_code():
    bank = FakeBank(status="INVALID", code=None)
    _, ch = verify_vendor(inv(), vendor(), [vendor()], bank, CFG)
    r = [c for c in failed(ch) if c.code == "BANK_INVALID"]
    assert r and all(c.severity == "block" for c in r)


def test_pending_status_without_fraud_code_only_asks():
    bank = FakeBank(status="RECEIVED", code="PENDING_AT_BANK")
    _, ch = verify_vendor(inv(), vendor(), [vendor()], bank, CFG)
    codes = {c.code for c in failed(ch)}
    assert "BANK_INVALID" not in codes
    assert "VENDOR_UNVERIFIABLE" in codes


def test_bank_cache_serves_repeat_verification():
    c = VerificationClient(live=False)
    first = c.bank("026291800001191", "YESB0000262", "john doe")
    second = c.bank("026291800001191", "YESB0000262", "john doe")
    assert first is second
    assert first["account_status"] == "VALID"


def test_bank_cache_keyed_by_name():
    c = VerificationClient(live=False)
    c.bank("026291800001191", "YESB0000262", "john doe")
    c.bank("026291800001191", "YESB0000262", "jane d")
    assert len(c._bank_cache) == 2
    c.cache_clear()
    assert c._bank_cache == {}


def test_bank_cache_covers_unknown_accounts():
    c = VerificationClient(live=False)
    a = c.bank("000000000000", "XXXX0000000")
    b = c.bank("000000000000", "XXXX0000000")
    assert a is b and a["account_status"] == "UNVERIFIABLE"
