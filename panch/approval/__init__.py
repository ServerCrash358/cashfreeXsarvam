"""Bundle-hash approval (ARCHITECTURE section H). Voice never authorises alone: a PIN tap
bound to the same bundle_hash is the authority. Pure apart from nonce generation."""
from __future__ import annotations

import hashlib
import hmac
import json
import re
import secrets
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional

from panch.models import ApprovalResult, Bundle, BundleItem
from panch.normalise import to_ascii_digits
from panch.voice.digits import numbers_from_speech

TTL = timedelta(minutes=2)
YES = {"yes", "haan", "han", "haa", "ha", "ok", "okay", "theek", "thik", "sari", "aamaa", "aama", "aam",
       "हाँ", "हां", "हा", "ठीक", "ஆமா", "ஆம்", "சரி", "kar", "pay", "approve", "approved", "confirm"}
NO = {"no", "nahi", "nahin", "mat", "ruko", "cancel", "stop", "नहीं", "नही", "मत", "இல்லை", "வேண்டாம்", "illai",
      "vendaam", "wait"}


def canonical_hash(items: list[BundleItem], cash_limit: Decimal, created_at: datetime, nonce: str) -> str:
    payload = {
        "items": [{"pos": n, "invoice": i.invoice_id, "beneficiary": i.beneficiary_id,
                   "account_hash": i.account_hash, "amount": str(i.amount)} for n, i in enumerate(items)],
        "cash_limit": str(cash_limit), "created_at": created_at.isoformat(), "nonce": nonce,
    }
    return hashlib.sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def make_bundle(items: list[BundleItem], cash_limit: Decimal, now: datetime,
                nonce: Optional[str] = None) -> Bundle:
    nonce = nonce or secrets.token_hex(8)
    h = canonical_hash(items, cash_limit, now, nonce)
    code = f"{int(hashlib.sha256((h + nonce).encode()).hexdigest(), 16) % 1000:03d}"
    return Bundle(id="b_" + h[:12], items=list(items), cash_limit=cash_limit, created_at=now,
                  expires_at=now + TTL, nonce=nonce, hash=h, code=code)


def bundle_still_matches(bundle: Bundle) -> bool:
    return canonical_hash(bundle.items, bundle.cash_limit, bundle.created_at, bundle.nonce) == bundle.hash


def check_approval(bundle: Bundle, transcript_or_code: str, now: datetime,
                   channel: str = "voice") -> ApprovalResult:
    """Voice: yes + total + count + code. Typed: the 3-digit code. Either way a PIN tap follows."""
    reasons = []
    if bundle.status in ("used", "approved"):
        reasons.append("replay: bundle already used")
    if now > bundle.expires_at:
        reasons.append("expired")
    if not bundle_still_matches(bundle):
        reasons.append("bundle changed (hash mismatch)")
    text = to_ascii_digits(transcript_or_code or "").lower()
    toks = set(re.findall(r"[\wऀ-ॿ஀-௿]+", text))
    nums = numbers_from_speech(text)
    code_ok = bundle.code in nums
    if channel == "typed":
        yes_ok = total_ok = count_ok = True
    else:
        has_no = bool(toks & NO)
        yes_ok = bool(toks & YES) and not has_no
        if has_no:
            reasons.append("ambiguous or negative speech")
        total_ok = str(int(bundle.total)) in nums
        count_ok = str(len(bundle.items)) in nums
    if not yes_ok:
        reasons.append("no clear yes")
    if not total_ok:
        reasons.append("total not confirmed")
    if not count_ok:
        reasons.append("count not confirmed")
    if not code_ok:
        reasons.append("code wrong")
    ok = not reasons
    return ApprovalResult(ok, yes_ok, total_ok, count_ok, code_ok, reasons)


def hash_pin(pin: str, salt: str) -> str:
    return hashlib.sha256((salt + ":" + pin).encode()).hexdigest()


def confirm_pin(bundle: Bundle, pin: str, pin_hash: str, salt: str, now: datetime) -> list[str]:
    """The authority. Returns reasons for refusal; empty list means approved (single use)."""
    reasons = []
    if bundle.status != "voice_ok":
        reasons.append("voice/typed confirmation not done" if bundle.status == "proposed" else f"bundle {bundle.status}")
    if now > bundle.expires_at:
        reasons.append("expired")
    if not bundle_still_matches(bundle):
        reasons.append("bundle changed (hash mismatch)")
    if not hmac.compare_digest(hash_pin(pin, salt), pin_hash):
        reasons.append("wrong PIN")
    return reasons
