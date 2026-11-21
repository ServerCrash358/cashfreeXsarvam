"""Bundle-hash approval (H). Pure: no I/O, no clock reads (pass `now`).

The owner approves ONE exact bundle: ordered (invoice, beneficiary, account
hash, amount) + cash limit + creation/expiry time + one-time nonce, hashed
with SHA-256 over canonical JSON. A 3-digit code is derived from the hash and
the nonce. Approval needs: yes (no "no"), the total, the bill count and the
code (voice), or the code (typed fallback). TTL 2 minutes, single use.

**Voice never authorises alone (ARCHITECTURE v3, H).** The spoken/typed step
is only the *confirmation*. The authority is a PIN tap on screen bound to the
same `bundle_hash` (`check_pin` + `authorise`). A second approver's PIN is
required when the total is above an owner-set threshold or any item came
through the CHANGED_ACCOUNT lane (stretch, U-APR-11).

Before any payout, call `assert_executable(bundle, authorisation)`: it
recomputes the hash, so any change to amounts, accounts, order or cash limit
after the approval makes it invalid.

Honest limits: no speaker verification; a PIN can be shoulder-surfed.
Disclose in the design note.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Collection, Literal, Optional, Sequence

from panch.voice import numbers as nums
from panch.voice.templates import format_inr, render, spoken_code

TTL = timedelta(minutes=2)
CODE_DIGITS = 3

# Result codes (ARCHITECTURE: APPROVAL_INVALID at bundle level; these are the details)
HASH_MISMATCH = "HASH_MISMATCH"
EXPIRED = "EXPIRED"
ALREADY_USED = "ALREADY_USED"
NO_CONSENT = "NO_CONSENT"
AMBIGUOUS = "AMBIGUOUS"
REFUSED = "REFUSED"
CODE_MISMATCH = "CODE_MISMATCH"
TOTAL_MISMATCH = "TOTAL_MISMATCH"
COUNT_MISMATCH = "COUNT_MISMATCH"
NOT_CONFIRMED = "NOT_CONFIRMED"
PIN_MISSING = "PIN_MISSING"
PIN_WRONG = "PIN_WRONG"
PIN_LOCKED = "PIN_LOCKED"
UNKNOWN_APPROVER = "UNKNOWN_APPROVER"
SECOND_APPROVER_REQUIRED = "SECOND_APPROVER_REQUIRED"

MAX_PIN_ATTEMPTS = 3
PIN_ITERATIONS = 100_000


class BundleError(ValueError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class BundleItem:
    invoice_id: str
    beneficiary_id: str
    account_hash: str          # never the account number itself
    amount: Decimal
    vendor_name: str = ""      # display only, not hashed
    # True while an ACCOUNT_CHANGED item still waits for its separate account-change approval (E2)
    account_change_pending: bool = False
    # True for an item that came through the CHANGED_ACCOUNT lane (change already approved):
    # the bundle then needs a second approver (U-APR-11)
    changed_account: bool = False


@dataclass(frozen=True)
class Bundle:
    id: str
    items: tuple[BundleItem, ...]
    cash_limit: Decimal
    created_at: datetime
    expires_at: datetime
    nonce: str
    hash: str

    @property
    def total(self) -> Decimal:
        return sum((i.amount for i in self.items), Decimal("0"))

    @property
    def count(self) -> int:
        return len(self.items)

    @property
    def code(self) -> str:
        return approval_code(self.hash, self.nonce)


@dataclass(frozen=True)
class ApprovalResult:
    valid: bool
    bundle_id: str
    bundle_hash: str
    channel: str
    codes: tuple[str, ...]
    checks: dict = field(default_factory=dict)   # yes/code/total/count/ttl/fresh -> bool
    transcript: Optional[str] = None
    at: Optional[datetime] = None

    @property
    def outcome_code(self) -> Optional[str]:
        return None if self.valid else "APPROVAL_INVALID"


# --- hashing ----------------------------------------------------------------

def _money(d: Decimal) -> str:
    return str(nums.to_decimal(d).quantize(Decimal("0.01")))


def canonical(items: Sequence[BundleItem], cash_limit: Decimal, created_at: datetime,
              expires_at: datetime, nonce: str) -> str:
    body = {
        "items": [
            {"pos": n, "invoice_id": i.invoice_id, "beneficiary_id": i.beneficiary_id,
             "account_hash": i.account_hash, "amount": _money(i.amount)}
            for n, i in enumerate(items)
        ],
        "cash_limit": _money(cash_limit),
        "created_at": created_at.isoformat(),
        "expires_at": expires_at.isoformat(),
        "nonce": nonce,
    }
    return json.dumps(body, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def bundle_hash(items, cash_limit, created_at, expires_at, nonce) -> str:
    return hashlib.sha256(canonical(items, cash_limit, created_at, expires_at, nonce).encode()).hexdigest()


def approval_code(hash_hex: str, nonce: str) -> str:
    digest = hashlib.sha256(f"{hash_hex}:{nonce}:code".encode()).hexdigest()
    return str(int(digest, 16) % 10 ** CODE_DIGITS).zfill(CODE_DIGITS)


def recompute_hash(bundle: Bundle) -> str:
    return bundle_hash(bundle.items, bundle.cash_limit, bundle.created_at, bundle.expires_at, bundle.nonce)


# --- creation -----------------------------------------------------------------

def make_bundle(items: Sequence[BundleItem], cash_limit, now: datetime,
                nonce: Optional[str] = None, ttl: timedelta = TTL) -> Bundle:
    """Freeze an ordered set of payments for approval.

    Refuses (BundleError) when: empty; an amount is not positive; an invoice
    appears twice; an item still has an unapproved account change (U-APR-9);
    the total exceeds the cash limit.
    """
    items = tuple(items)
    cash_limit = nums.to_decimal(cash_limit)
    if not items:
        raise BundleError("EMPTY", "bundle has no items")
    seen = set()
    for i in items:
        if not isinstance(i.amount, Decimal):
            raise BundleError("NOT_DECIMAL", f"amount for {i.invoice_id} must be Decimal")
        if i.amount <= 0:
            raise BundleError("BAD_AMOUNT", f"amount for {i.invoice_id} must be positive")
        if i.invoice_id in seen:
            raise BundleError("DUPLICATE_ITEM", f"invoice {i.invoice_id} appears twice")
        seen.add(i.invoice_id)
        if i.account_change_pending:
            raise BundleError("ACCOUNT_CHANGE_UNAPPROVED",
                              f"invoice {i.invoice_id}: account change not yet approved by the owner")
    total = sum((i.amount for i in items), Decimal("0"))
    if total > cash_limit:
        raise BundleError("OVER_CASH_LIMIT", f"total {total} exceeds cash limit {cash_limit}")
    nonce = nonce or secrets.token_hex(16)
    expires_at = now + ttl
    h = bundle_hash(items, cash_limit, now, expires_at, nonce)
    return Bundle(id="bdl_" + h[:12], items=items, cash_limit=cash_limit,
                  created_at=now, expires_at=expires_at, nonce=nonce, hash=h)


def prompt_text(bundle: Bundle, lang: str) -> str:
    """What Bulbul says: count, total and the code, from the template."""
    return render("approval_prompt", lang, count=bundle.count, total=bundle.total,
                  code=spoken_code(bundle.code))


# --- checking -----------------------------------------------------------------

def _spoken_total_ok(tokens, total: Decimal, skip: set[int], transcript: str, lang: str) -> bool:
    if any(a == total for a in nums.amounts_in(tokens, skip)):
        return True
    # Totals in words ("बाईस हज़ार") come from the normaliser (PR 1) when it lands.
    try:
        from panch.normalise import words_to_amount  # type: ignore
    except ImportError:
        return False
    try:
        value = words_to_amount(transcript, lang)
    except Exception:
        return False
    return value is not None and Decimal(value) == total


def _merged_total_count(tokens, bundle: Bundle, skip: set[int]) -> bool:
    """Saaras number normalisation joins "baees hazaar, do bill" into "22002 बिल"
    (observed live, saaras:v4, 21 Nov). Accept a number directly before a bill word
    that equals total + count exactly; both values must still match the bundle."""
    for i, t in enumerate(tokens[:-1]):
        if i in skip or t.number is None or tokens[i + 1].raw not in nums.BILL_WORDS:
            continue
        if Decimal(t.number) == bundle.total + bundle.count:
            return True
    return False


def check_approval(bundle: Bundle, response: str, now: datetime, *,
                   channel: Literal["voice", "typed"] = "voice",
                   used_nonces: Collection[str] = (), lang: str = "hi") -> ApprovalResult:
    """Decide whether `response` approves exactly this bundle. Never raises.

    voice: `response` is the Saaras transcript; needs yes (and no "no"),
           the total, the count and the code.
    typed: `response` is the code typed on the screen that shows the bundle.
    The caller records `bundle.nonce` in its used set when the result is valid.
    """
    codes: list[str] = []
    checks: dict[str, bool] = {}

    checks["hash"] = recompute_hash(bundle) == bundle.hash
    if not checks["hash"]:
        codes.append(HASH_MISMATCH)
    checks["ttl"] = now <= bundle.expires_at
    if not checks["ttl"]:
        codes.append(EXPIRED)
    checks["fresh"] = bundle.nonce not in used_nonces
    if not checks["fresh"]:
        codes.append(ALREADY_USED)

    if channel == "typed":
        typed = nums.extract_digits(response or "")
        checks["code"] = typed == bundle.code
        if not checks["code"]:
            codes.append(CODE_MISMATCH)
    else:
        tokens = nums.tokenize(response or "")
        c = nums.consent(tokens)
        checks["yes"] = c == "yes"
        if c == "ambiguous":
            codes.append(AMBIGUOUS)
        elif c == "no":
            codes.append(REFUSED)
        elif c == "none":
            codes.append(NO_CONSENT)

        code_idx: set[int] = set()
        checks["code"] = False
        for start, end, digits in nums.digit_runs(tokens):
            pos = digits.find(bundle.code)
            if pos >= 0:
                checks["code"] = True
                code_idx = set(range(start + pos, start + pos + len(bundle.code)))
                break
        if not checks["code"]:
            for i, t in enumerate(tokens):   # code said as one number: "472"
                if t.number is not None and t.raw == bundle.code:
                    checks["code"], code_idx = True, {i}
                    break
        if not checks["code"]:
            codes.append(CODE_MISMATCH)

        checks["total"] = _spoken_total_ok(tokens, bundle.total, code_idx, response or "", lang)
        checks["count"] = bundle.count in nums.small_numbers(tokens, code_idx)
        if not (checks["total"] and checks["count"]) and _merged_total_count(tokens, bundle, code_idx):
            checks["total"] = checks["count"] = True
        if not checks["total"]:
            codes.append(TOTAL_MISMATCH)
        if not checks["count"]:
            codes.append(COUNT_MISMATCH)

    return ApprovalResult(valid=not codes, bundle_id=bundle.id, bundle_hash=bundle.hash,
                          channel=channel, codes=tuple(codes), checks=checks,
                          transcript=response if channel == "voice" else None, at=now)


# --- PIN tap: the authority ---------------------------------------------------------

@dataclass(frozen=True)
class Approver:
    id: str
    salt: str
    pin_hash: str          # hash_pin(pin, salt); the PIN itself is never stored


def hash_pin(pin: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pin.encode(), salt.encode(), PIN_ITERATIONS).hex()


def make_approver(approver_id: str, pin: str, salt: Optional[str] = None) -> Approver:
    salt = salt or secrets.token_hex(8)
    return Approver(approver_id, salt, hash_pin(pin, salt))


@dataclass(frozen=True)
class Authorisation:
    valid: bool
    bundle_id: str
    bundle_hash: str
    codes: tuple[str, ...]
    approvers: tuple[str, ...]          # approver ids whose PIN tap was accepted
    required: int                       # 1, or 2 when a second approver is needed
    confirmation: Optional[ApprovalResult] = None
    at: Optional[datetime] = None

    @property
    def outcome_code(self) -> Optional[str]:
        return None if self.valid else "APPROVAL_INVALID"


def approvers_required(bundle: Bundle, second_approver_above: Optional[Decimal] = None) -> int:
    """2 when any item came through CHANGED_ACCOUNT or the total is above the threshold."""
    if any(i.changed_account for i in bundle.items):
        return 2
    if second_approver_above is not None and bundle.total > nums.to_decimal(second_approver_above):
        return 2
    return 1


def check_pin(bundle: Bundle, approver: Optional[Approver], pin: Optional[str],
              tapped_hash: str, now: datetime) -> tuple[str, ...]:
    """One PIN tap. Pure. Returns failure codes (empty = this tap is good).

    `tapped_hash` is the bundle hash the screen showed when the PIN was tapped,
    so a tap on a stale or different screen never authorises this bundle.
    """
    codes: list[str] = []
    if approver is None:
        codes.append(UNKNOWN_APPROVER)
    elif not pin:
        codes.append(PIN_MISSING)
    elif not hmac.compare_digest(hash_pin(pin, approver.salt), approver.pin_hash):
        codes.append(PIN_WRONG)
    if tapped_hash != bundle.hash or recompute_hash(bundle) != bundle.hash:
        codes.append(HASH_MISMATCH)
    if now > bundle.expires_at:
        codes.append(EXPIRED)
    return tuple(codes)


def authorise(bundle: Bundle, confirmation: Optional[ApprovalResult], approver_ids: Sequence[str],
              required: int, now: datetime, used_nonces: Collection[str] = ()) -> Authorisation:
    """Combine the spoken/typed confirmation with accepted PIN taps. Pure."""
    codes: list[str] = []
    if confirmation is None or not confirmation.valid or confirmation.bundle_hash != bundle.hash:
        codes.append(NOT_CONFIRMED)
    if recompute_hash(bundle) != bundle.hash:
        codes.append(HASH_MISMATCH)
    if now > bundle.expires_at:
        codes.append(EXPIRED)
    if bundle.nonce in used_nonces:
        codes.append(ALREADY_USED)
    distinct = tuple(dict.fromkeys(approver_ids))
    if not distinct:
        codes.append(PIN_MISSING)
    elif len(distinct) < required:
        codes.append(SECOND_APPROVER_REQUIRED)
    return Authorisation(valid=not codes, bundle_id=bundle.id, bundle_hash=bundle.hash,
                         codes=tuple(codes), approvers=distinct, required=required,
                         confirmation=confirmation, at=now)


def assert_executable(bundle: Bundle, authorisation) -> None:
    """Gate in front of payouts (I). Raises BundleError unless this exact bundle
    was confirmed AND authorised by PIN. A bare ApprovalResult (voice/typed
    confirmation only) is refused: voice never authorises alone (U-APR-10)."""
    if not isinstance(authorisation, Authorisation) or not authorisation.valid:
        raise BundleError("NOT_AUTHORISED", "bundle has no valid PIN authorisation")
    if authorisation.bundle_id != bundle.id or authorisation.bundle_hash != bundle.hash:
        raise BundleError("HASH_MISMATCH", "authorisation is for a different bundle")
    if recompute_hash(bundle) != authorisation.bundle_hash:
        raise BundleError("HASH_MISMATCH", "bundle changed after approval")


class ApprovalStore:
    """In-memory single-use ledger. The app persists approvals in SQLite/audit.

    Flow per bundle: confirm (voice or typed code, once) -> tap_pin (one or two
    approvers) -> authorisation. Three wrong PINs lock the bundle; make a new one.
    """

    def __init__(self, approvers: Sequence[Approver] = (), second_approver_above=None):
        self.approvers: dict[str, Approver] = {a.id: a for a in approvers}
        self.second_approver_above = second_approver_above
        self.bundles: dict[str, Bundle] = {}
        self.confirmed_nonces: set[str] = set()
        self.authorised_nonces: set[str] = set()
        self.confirmations: dict[str, ApprovalResult] = {}
        self.taps: dict[str, list[str]] = {}
        self.wrong_pins: dict[str, int] = {}
        self.authorisations: dict[str, Authorisation] = {}
        self.attempts: dict[str, list] = {}

    def add(self, bundle: Bundle) -> Bundle:
        self.bundles[bundle.id] = bundle
        return bundle

    def required(self, bundle_id: str) -> int:
        return approvers_required(self.bundles[bundle_id], self.second_approver_above)

    def confirm(self, bundle_id: str, response: str, now: datetime, *,
                channel: Literal["voice", "typed"] = "voice", lang: str = "hi") -> ApprovalResult:
        bundle = self.bundles[bundle_id]
        result = check_approval(bundle, response, now, channel=channel,
                                used_nonces=self.confirmed_nonces, lang=lang)
        self.attempts.setdefault(bundle_id, []).append(result)
        if result.valid:
            self.confirmed_nonces.add(bundle.nonce)
            self.confirmations[bundle_id] = result
        return result

    approve = confirm  # backwards-compatible name

    def tap_pin(self, bundle_id: str, approver_id: str, pin: Optional[str],
                tapped_hash: str, now: datetime) -> Authorisation:
        bundle = self.bundles[bundle_id]
        required = self.required(bundle_id)
        if self.wrong_pins.get(bundle_id, 0) >= MAX_PIN_ATTEMPTS:
            return Authorisation(False, bundle.id, bundle.hash, (PIN_LOCKED,),
                                 tuple(self.taps.get(bundle_id, [])), required,
                                 self.confirmations.get(bundle_id), now)
        codes = check_pin(bundle, self.approvers.get(approver_id), pin, tapped_hash, now)
        if codes:
            if PIN_WRONG in codes:
                self.wrong_pins[bundle_id] = self.wrong_pins.get(bundle_id, 0) + 1
            auth = Authorisation(False, bundle.id, bundle.hash, codes,
                                 tuple(self.taps.get(bundle_id, [])), required,
                                 self.confirmations.get(bundle_id), now)
            self.attempts.setdefault(bundle_id, []).append(auth)
            return auth
        taps = self.taps.setdefault(bundle_id, [])
        if approver_id not in taps:
            taps.append(approver_id)
        auth = authorise(bundle, self.confirmations.get(bundle_id), taps, required, now,
                         self.authorised_nonces)
        self.attempts.setdefault(bundle_id, []).append(auth)
        if auth.valid:
            self.authorised_nonces.add(bundle.nonce)
            self.authorisations[bundle_id] = auth
        return auth


__all__ = [
    "Bundle", "BundleItem", "BundleError", "ApprovalResult", "ApprovalStore",
    "Approver", "Authorisation", "make_approver", "hash_pin", "approvers_required",
    "make_bundle", "check_approval", "check_pin", "authorise", "assert_executable",
    "prompt_text", "approval_code", "recompute_hash", "format_inr", "TTL",
]
