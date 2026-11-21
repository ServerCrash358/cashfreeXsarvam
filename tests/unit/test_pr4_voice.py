"""PR 4 additions on top of the stable build: shapes seen in live Saaras runs (IT-SARVAM S2,
21 Nov), spoken digits in three languages, and PIN lockout. Offline."""
from datetime import datetime, timedelta
from decimal import Decimal as D

import pytest

from panch.approval import check_approval, make_bundle
from panch.models import BundleItem
from panch.voice.digits import extract_digits

T0 = datetime(2026, 11, 21, 14, 0)


def bundle():
    items = [BundleItem("H", "ben_h", "a" * 64, D("4000")), BundleItem("B", "ben_b", "b" * 64, D("18000"))]
    return make_bundle(items, D("30000"), T0, nonce="fixed")


@pytest.mark.parametrize("tx", [
    "हाँ, 22002 बिल, कोड {c}।",            # live: Saaras joined "baees hazaar, do bill"
    "हाँ, 22,002 बिल कोड {c}।",
    "ஆமாம், 22002 பில் கோட் {c}.",
    "ஆமாம், 22002 bill code {c}.",
    "हाँ, 2 bill, 22,000, code {c}.",       # count-first order the prompt now asks for
    "हाँ, दो बिल 22,000, कोड {c}।",
    "ஆமாம், ரெண்டு பில் 22,000 கோட் {c}.",
])
def test_live_saaras_transcripts_approve(tx):
    b = bundle()
    r = check_approval(b, tx.format(c=b.code), T0)
    assert r.ok, r.reasons


def test_merged_number_must_be_exactly_total_plus_count():
    b = bundle()
    assert not check_approval(b, f"haan 22003 bill {b.code}", T0).ok     # 22,000 + 3
    assert not check_approval(b, f"haan 22002 {b.code}", T0).ok          # no bill word


@pytest.mark.parametrize("text", [
    "four seven two nine", "चार सात दो नौ", "char saat do nau", "நாலு ஏழு இரண்டு ஒன்பது",
    "நான்கு ஏழு இரெண்டு ஒன்பது", "naalu ezhu rendu onbadhu", "4729.", "4729।", "௪௭௨௯", "४७२९",
])
def test_callback_digits_three_languages(text):
    assert extract_digits(text) == "4729"


def test_pin_lockout_after_three_wrong(monkeypatch):
    from panch.engine import Engine
    e = Engine(live=False)
    st = e.state_view() if hasattr(e, "state_view") else None  # noqa: F841 (engine warm-up)
    b = bundle()
    b.status = "voice_ok"
    e.bundles[b.id] = b
    for _ in range(3):
        assert "wrong PIN" in e.approve_pin(b.id, "0000")
    assert b.status == "locked"
    assert e.approve_pin(b.id, "2468")      # right PIN no longer works on a locked bundle
    assert b.status == "locked"
