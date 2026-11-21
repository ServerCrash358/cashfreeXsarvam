"""IT-CF-VRS, IT-CF-GST, IT-CF-UDYAM against the Cashfree sandbox (docs/INTEGRATION_TESTS.md).
Every case asserts canned=False: a fixture fallback is not a sandbox result."""
import pytest

from panch.cashfree import VerificationClient

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def vc():
    c = VerificationClient(live=True)
    if not (c.cid and c.sec):
        pytest.skip("CASHFREE_CLIENT_ID/_SECRET not set in .env")
    return c


def _live(d):
    assert d.get("canned") is False, f"fell back to fixtures: {d.get('live_error')}"
    return d


@pytest.mark.parametrize("vid,name,score,result", [
    ("V1", "john doe", 100, "DIRECT_MATCH"),
    ("V2", "john d", 85, "GOOD_PARTIAL_MATCH"),
    ("V3", "j doe", 70, "MODERATE_PARTIAL_MATCH"),
    ("V4", "jane d", 38, "POOR_PARTIAL_MATCH"),
])
def test_v1_v4_john_doe_name_tiers(vc, vid, name, score, result):
    d = _live(vc.bank("026291800001191", "YESB0000262", name))
    assert d["account_status"] == "VALID", vid
    assert d["name_at_bank"].upper() == "JOHN DOE", vid
    assert round(float(d["name_match_score"])) == score and d["name_match_result"] == result, vid


@pytest.mark.parametrize("account,good,bad", [("1233943142", "tom wells", "tim lee"),
                                              ("388108022658", "bob hope", "bane hue")])
def test_v5_v6_v9_other_accounts_and_icic_pairing(vc, account, good, bad):
    hi = _live(vc.bank(account, "ICIC0000009", good))
    lo = _live(vc.bank(account, "ICIC0000009", bad))
    assert hi["account_status"] == "VALID"
    assert round(float(hi["name_match_score"])) == 100 and round(float(lo["name_match_score"])) == 38


def test_v7_no_name_means_no_score(vc):
    d = _live(vc.bank("026291800001191", "YESB0000262", None))
    assert d["account_status"] == "VALID"
    assert not d.get("name_match_score")


def test_g1_valid_gstin(vc):
    d = _live(vc.gstin("29AAICP2912R1ZR"))
    assert d.get("valid") is True and d.get("legal_name_of_business")


def test_g2_invalid_gstin(vc):
    assert _live(vc.gstin("29AAIZP2912R1ZR")).get("valid") is False


def test_g3_sandbox_gstin_that_fails_a_real_checksum(vc):
    assert _live(vc.gstin("27ABCFGH5678D1Z")).get("valid") is True


def test_g4_gstin_not_in_test_table_record_behaviour(vc):
    d = _live(vc.gstin("29ZZZZZ0000Z1Z0"))
    print("G4 behaviour:", {k: d.get(k) for k in ("valid", "_http", "code", "message")})


@pytest.mark.parametrize("udyam,status", [("UDYAM-UP-43-1234567", "SUCCESS"),
                                          ("UDYAM-MH-43-1234567", "UDYAM_NOT_FOUND"),
                                          ("UDYAM-KA-43-1234567", "UDYAM_IS_CANCELLED")])
def test_u1_u3_udyam(vc, udyam, status):
    import uuid
    d = _live(vc.udyam(udyam, "pn" + uuid.uuid4().hex[:20]))
    assert d.get("status") == status
    if status == "SUCCESS":
        assert d.get("enterprise_type")
