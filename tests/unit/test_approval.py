"""U-APR-1..9 (docs/UNIT_TESTS.md section H). Offline, pure."""
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from panch.approval import (ApprovalStore, BundleError, BundleItem, assert_executable,
                            check_approval, make_approver, make_bundle, prompt_text)

T0 = datetime(2026, 11, 21, 14, 0, tzinfo=timezone.utc)
H = BundleItem("inv_H", "ben_lakshmi", "a" * 64, Decimal("4000"), "Lakshmi Electricals")
B = BundleItem("inv_B", "ben_ganesh", "b" * 64, Decimal("18000"), "Ganesh Pipes")
OWNER = make_approver("owner", "2468", "s1")
PARTNER = make_approver("partner", "1357", "s2")


def bundle(nonce="n1", items=(H, B), cash="30000"):
    return make_bundle(list(items), Decimal(cash), T0, nonce=nonce)


def voice(b, extra=""):
    code = "-".join(b.code)
    return f"haan, 22,000, do bill, {code} {extra}".strip()


def authorised(b, store=None):
    """Full v3 flow: spoken confirmation, then the owner's PIN tap."""
    store = store or ApprovalStore([OWNER, PARTNER])
    store.add(b)
    assert store.confirm(b.id, voice(b), T0).valid
    auth = store.tap_pin(b.id, "owner", "2468", b.hash, T0 + timedelta(seconds=10))
    assert auth.valid, auth.codes
    return auth


def test_u_apr_1_valid_voice():
    b = bundle()
    r = check_approval(b, voice(b), T0 + timedelta(seconds=30))
    assert r.valid, r.codes
    assert r.checks == {"hash": True, "ttl": True, "fresh": True, "yes": True,
                        "code": True, "total": True, "count": True}


def test_u_apr_1_valid_hindi_script_and_tamil():
    b = bundle()
    hi = f"हाँ, २२,००० रुपये, दो बिल, कोड {' '.join(b.code)}"
    assert check_approval(b, hi, T0).valid
    ta_digits = {"0": "பூஜ்ஜியம்", "1": "ஒன்று", "2": "இரண்டு", "3": "மூன்று", "4": "நான்கு",
                 "5": "ஐந்து", "6": "ஆறு", "7": "ஏழு", "8": "எட்டு", "9": "ஒன்பது"}
    ta = f"ஆம், 22,000, ரெண்டு பில், {' '.join(ta_digits[d] for d in b.code)}"
    assert check_approval(b, ta, T0, lang="ta").valid


def test_u_apr_1_typed_fallback():
    b = bundle()
    assert check_approval(b, b.code, T0, channel="typed").valid
    bad = str((int(b.code) + 1) % 1000).zfill(3)
    r = check_approval(b, bad, T0, channel="typed")
    assert not r.valid and "CODE_MISMATCH" in r.codes


def test_u_apr_2_single_use():
    store = ApprovalStore([OWNER])
    b = store.add(bundle())
    assert store.confirm(b.id, voice(b), T0).valid
    again = store.confirm(b.id, voice(b), T0 + timedelta(seconds=5))
    assert not again.valid and "ALREADY_USED" in again.codes
    assert store.tap_pin(b.id, "owner", "2468", b.hash, T0).valid
    replay = store.tap_pin(b.id, "owner", "2468", b.hash, T0 + timedelta(seconds=5))
    assert not replay.valid and "ALREADY_USED" in replay.codes


def test_u_apr_3_amount_changed_after_approval():
    b = bundle()
    auth = authorised(b)
    tampered = replace(b, items=(H, replace(B, amount=Decimal("18001"))))
    assert not check_approval(tampered, voice(b), T0).valid
    with pytest.raises(BundleError) as e:
        assert_executable(tampered, auth)
    assert e.value.code == "HASH_MISMATCH"
    assert_executable(b, auth)  # the untouched bundle still executes


@pytest.mark.parametrize("mutate", [
    lambda b: replace(b, items=tuple(reversed(b.items))),                          # order
    lambda b: replace(b, items=(replace(b.items[0], account_hash="c" * 64), b.items[1])),  # account
    lambda b: replace(b, cash_limit=Decimal("50000")),                             # cash limit
])
def test_u_apr_4_order_account_cash_change_invalidates(mutate):
    b = bundle()
    auth = authorised(b)
    m = mutate(b)
    assert "HASH_MISMATCH" in check_approval(m, voice(b), T0).codes
    with pytest.raises(BundleError):
        assert_executable(m, auth)


def test_u_apr_5_expired():
    b = bundle()
    r = check_approval(b, voice(b), T0 + timedelta(minutes=2, seconds=1))
    assert not r.valid and "EXPIRED" in r.codes


def test_u_apr_6_yes_without_code():
    b = bundle()
    r = check_approval(b, "haan", T0)
    assert not r.valid
    assert {"CODE_MISMATCH", "TOTAL_MISMATCH", "COUNT_MISMATCH"} <= set(r.codes)


def test_u_apr_7_ambiguous():
    b = bundle()
    r = check_approval(b, voice(b).replace("haan", "haan... nahi"), T0)
    assert not r.valid and "AMBIGUOUS" in r.codes


def test_refusal_and_no_consent():
    b = bundle()
    assert "REFUSED" in check_approval(b, voice(b).replace("haan", "nahi"), T0).codes
    assert "NO_CONSENT" in check_approval(b, voice(b).replace("haan, ", ""), T0).codes


def test_u_apr_8_spoken_total_and_count_word():
    b = bundle()
    r = check_approval(b, f"haan 22 hazaar do bill {' '.join(b.code)}", T0)
    assert r.valid, r.codes


@pytest.mark.parametrize("tx", [
    "हाँ, 22002 बिल, कोड {c}।",          # observed live: Saaras merged "22,000, do bill"
    "ஆமாம், 22002 பில் கோட் {c}.",
    "haan, 2 bill, 22,000, code {c}",     # count-first order the prompt now asks for
])
def test_live_saaras_shapes(tx):
    b = bundle()
    assert check_approval(b, tx.format(c=b.code), T0).valid


def test_merged_number_must_match_exactly():
    b = bundle()
    assert not check_approval(b, f"haan 22003 bill {b.code}", T0).valid   # 22,000 + 3 bills
    assert not check_approval(b, f"haan 22002 {b.code}", T0).valid        # no bill word: no split


def test_wrong_total_or_count_fails():
    b = bundle()
    assert "TOTAL_MISMATCH" in check_approval(b, voice(b).replace("22,000", "21,000"), T0).codes
    assert "COUNT_MISMATCH" in check_approval(b, voice(b).replace("do bill", "teen bill"), T0).codes


def test_u_apr_9_unapproved_account_change_cannot_enter_bundle():
    pending = BundleItem("inv_F", "ben_new", "f" * 64, Decimal("11000"), account_change_pending=True)
    with pytest.raises(BundleError) as e:
        make_bundle([H, pending], Decimal("30000"), T0)
    assert e.value.code == "ACCOUNT_CHANGE_UNAPPROVED"


def test_bundle_guards():
    with pytest.raises(BundleError) as e:
        make_bundle([H, B], Decimal("20000"), T0)
    assert e.value.code == "OVER_CASH_LIMIT"
    with pytest.raises(BundleError):
        make_bundle([H, H], Decimal("30000"), T0)
    with pytest.raises(BundleError):
        make_bundle([], Decimal("30000"), T0)


def test_hash_and_code_deterministic_and_nonce_bound():
    a, b = bundle("same"), bundle("same")
    assert a.hash == b.hash and a.code == b.code
    c = bundle("other")
    assert c.hash != a.hash
    # a replayed approval for an old bundle does not carry over to a new one
    auth_old = authorised(a)
    with pytest.raises(BundleError):
        assert_executable(c, auth_old)


def test_u_apr_10_voice_without_pin_is_not_authorised():
    store = ApprovalStore([OWNER])
    b = store.add(bundle())
    confirmation = store.confirm(b.id, voice(b), T0)
    assert confirmation.valid
    with pytest.raises(BundleError) as e:
        assert_executable(b, confirmation)          # a confirmation is not an authorisation
    assert e.value.code == "NOT_AUTHORISED"
    assert b.id not in store.authorisations


def test_pin_before_confirmation_is_not_enough():
    store = ApprovalStore([OWNER])
    b = store.add(bundle())
    auth = store.tap_pin(b.id, "owner", "2468", b.hash, T0)
    assert not auth.valid and "NOT_CONFIRMED" in auth.codes


def test_pin_bound_to_shown_hash_and_locked_after_three_wrong():
    store = ApprovalStore([OWNER])
    b = store.add(bundle())
    store.confirm(b.id, voice(b), T0)
    assert "HASH_MISMATCH" in store.tap_pin(b.id, "owner", "2468", "0" * 64, T0).codes
    assert "UNKNOWN_APPROVER" in store.tap_pin(b.id, "nobody", "2468", b.hash, T0).codes
    for _ in range(3):
        assert "PIN_WRONG" in store.tap_pin(b.id, "owner", "0000", b.hash, T0).codes
    locked = store.tap_pin(b.id, "owner", "2468", b.hash, T0)
    assert not locked.valid and locked.codes == ("PIN_LOCKED",)


def test_pin_after_expiry_fails():
    store = ApprovalStore([OWNER])
    b = store.add(bundle())
    store.confirm(b.id, voice(b), T0)
    late = store.tap_pin(b.id, "owner", "2468", b.hash, T0 + timedelta(minutes=3))
    assert not late.valid and "EXPIRED" in late.codes


def test_u_apr_11_second_approver_for_changed_account_item():
    store = ApprovalStore([OWNER, PARTNER])
    item = replace(B, changed_account=True)
    b = store.add(make_bundle([H, item], Decimal("30000"), T0, nonce="n2"))
    assert store.required(b.id) == 2
    assert store.confirm(b.id, voice(b), T0).valid
    first = store.tap_pin(b.id, "owner", "2468", b.hash, T0)
    assert not first.valid and first.codes == ("SECOND_APPROVER_REQUIRED",)
    same_again = store.tap_pin(b.id, "owner", "2468", b.hash, T0)
    assert not same_again.valid                       # same person twice is not two approvers
    second = store.tap_pin(b.id, "partner", "1357", b.hash, T0)
    assert second.valid and second.approvers == ("owner", "partner")
    assert_executable(b, second)


def test_u_apr_11_second_approver_above_threshold():
    store = ApprovalStore([OWNER, PARTNER], second_approver_above=Decimal("20000"))
    b = store.add(bundle())                            # total 22,000 > 20,000
    assert store.required(b.id) == 2
    small = ApprovalStore([OWNER], second_approver_above=Decimal("50000"))
    assert small.required(small.add(bundle("n3")).id) == 1


def test_prompt_uses_template_with_commas():
    b = bundle()
    text = prompt_text(b, "en")
    assert "22,000" in text and "-".join(b.code) in text and "2 bills" in text
