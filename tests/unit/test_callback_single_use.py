"""A call-back mismatch is final: no second answer on the same call, no new call to retry.
Found 21 Nov: submitting again with the right digits overwrote CALLBACK_MISMATCH."""
import pytest

from panch.engine import Engine


def _changed_account_bill(e: Engine) -> str:
    return next(k for k, st in e.state.items() if st["lane"] == "CHANGED_ACCOUNT")


def test_second_answer_on_same_call_is_refused():
    e = Engine(live=False)
    inv = _changed_account_bill(e)
    s = e.start_callback(inv)
    wrong = "0000" if s.expected_last4 != "0000" else "1111"
    assert not e.finish_callback(s.id, " ".join(wrong)).passed
    with pytest.raises(ValueError):
        e.finish_callback(s.id, " ".join(s.expected_last4))       # retry with the right digits
    assert not e.callback_results[inv].passed


def test_new_call_after_mismatch_is_refused():
    e = Engine(live=False)
    inv = _changed_account_bill(e)
    s = e.start_callback(inv)
    wrong = "0000" if s.expected_last4 != "0000" else "1111"
    e.finish_callback(s.id, " ".join(wrong))
    with pytest.raises(ValueError):
        e.start_callback(inv)


def test_no_answer_can_be_retried_with_a_new_call():
    e = Engine(live=False)
    inv = _changed_account_bill(e)
    s1 = e.start_callback(inv)
    assert e.finish_callback(s1.id, "").code == "CALLBACK_NO_ANSWER"
    s2 = e.start_callback(inv)                                       # allowed: nobody answered
    assert e.finish_callback(s2.id, " ".join(s2.expected_last4)).passed
