"""Cashfree HTTP clients (Secure ID verification + Payouts v2) and webhook signature check.
REST via httpx: the cashfree_pg SDK covers PG only. Never logs keys or full account numbers."""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from typing import Optional

import httpx

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "data" / "fixtures"


def verify_signature(secret: str, timestamp: str, raw_body: bytes, signature: str) -> bool:
    """base64(HMAC-SHA256(secret, timestamp + raw_body)), compared in constant time."""
    mac = hmac.new(secret.encode(), timestamp.encode() + raw_body, hashlib.sha256).digest()
    return hmac.compare_digest(base64.b64encode(mac).decode(), signature or "")


def _signature_header(client_id: str, pubkey_path: Optional[str]) -> dict:
    """2FA public-key mode: X-Cf-Signature = RSA-OAEP(clientId.epoch). UNVERIFIED; IP whitelisting is
    the default. Only used if *_PUBLIC_KEY_PATH is set (needs the `cryptography` package)."""
    if not pubkey_path:
        return {}
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import padding
    key = serialization.load_pem_public_key(Path(pubkey_path).read_bytes())
    msg = f"{client_id}.{int(time.time())}".encode()
    enc = key.encrypt(msg, padding.OAEP(mgf=padding.MGF1(algorithm=hashes.SHA1()), algorithm=hashes.SHA1(), label=None))
    return {"x-cf-signature": base64.b64encode(enc).decode()}


class CashfreeUnavailable(Exception):
    """Auth/IP/network problem: callers may fall back to disclosed fixtures."""


class VerificationClient:
    """Secure ID: bank account (sync), GSTIN, Udyam. Falls back to canned sandbox fixtures
    (marked canned=True) when the live API is unreachable, e.g. IP not whitelisted."""

    def __init__(self, base_url: str = "https://sandbox.cashfree.com/verification", live: Optional[bool] = None):
        self.base = base_url.rstrip("/")
        self.cid = os.getenv("CASHFREE_CLIENT_ID", "")
        self.sec = os.getenv("CASHFREE_CLIENT_SECRET", "")
        self.pubkey = os.getenv("CASHFREE_SECURE_ID_PUBLIC_KEY_PATH")
        self.live = bool(self.cid and self.sec) if live is None else live
        self.fixtures = json.loads((FIXTURES / "verification.json").read_text(encoding="utf-8"))
        self.last_error: Optional[str] = None
        # Memoised bank verifications: one account never pays for two penny drops.
        self._bank_cache: dict = {}

    def cache_clear(self) -> None:
        self._bank_cache.clear()

    def _post(self, path: str, body: dict) -> dict:
        h = {"x-client-id": self.cid, "x-client-secret": self.sec, "Content-Type": "application/json",
             **_signature_header(self.cid, self.pubkey)}
        try:
            r = httpx.post(self.base + path, headers=h, json=body, timeout=20)
        except httpx.HTTPError as e:
            raise CashfreeUnavailable(f"network: {type(e).__name__}")
        if r.status_code in (401, 403):
            raise CashfreeUnavailable(f"HTTP {r.status_code}: {r.json().get('message', '')[:120]}")
        data = r.json()
        data["_http"] = r.status_code
        return data

    def bank(self, account: str, ifsc: str, name: Optional[str] = None) -> dict:
        key = (account, ifsc, name)
        if key in self._bank_cache:
            return self._bank_cache[key]
        body = {"bank_account": account, "ifsc": ifsc}
        if name:
            body["name"] = name
        if self.live:
            try:
                d = self._post("/bank-account/sync", body)
                d["canned"] = False
                self._bank_cache[key] = d
                return d
            except CashfreeUnavailable as e:
                self.last_error = str(e)
        fx = self.fixtures["bank"].get(account)
        if fx is None:
            res = {"account_status": "UNVERIFIABLE", "canned": True, "note": "not in sandbox test data"}
        else:
            res = {**fx, "canned": True, "live_error": self.last_error}
        self._bank_cache[key] = res
        return res

    def gstin(self, gstin: str, business_name: Optional[str] = None) -> dict:
        if self.live:
            try:
                d = self._post("/gstin", {"GSTIN": gstin, **({"business_name": business_name} if business_name else {})})
                d["canned"] = False
                return d
            except CashfreeUnavailable as e:
                self.last_error = str(e)
        return {**self.fixtures["gstin"].get(gstin, {"valid": None, "note": "not in sandbox data"}), "canned": True}

    def udyam(self, udyam: str, verification_id: str) -> dict:
        if self.live:
            try:
                d = self._post("/udyam", {"verification_id": verification_id, "udyam": udyam})
                d["canned"] = False
                return d
            except CashfreeUnavailable as e:
                self.last_error = str(e)
        return {**self.fixtures["udyam"].get(udyam, {"status": "UNVERIFIABLE"}), "canned": True}


class PayoutsClient:
    """Payouts v2: beneficiary, transfers, status. 200 means submitted, never paid."""

    API_VERSION = "2024-01-01"

    def __init__(self, base_url: Optional[str] = None):
        self.base = (base_url or os.getenv("CASHFREE_PAYOUT_BASE_URL") or "https://sandbox.cashfree.com/payout").rstrip("/")
        self.cid = os.getenv("CASHFREE_PAYOUT_CLIENT_ID") or os.getenv("CASHFREE_CLIENT_ID", "")
        self.sec = os.getenv("CASHFREE_PAYOUT_CLIENT_SECRET") or os.getenv("CASHFREE_CLIENT_SECRET", "")
        self.pubkey = os.getenv("CASHFREE_PAYOUT_PUBLIC_KEY_PATH")

    @property
    def secret(self) -> str:
        return self.sec

    def _h(self) -> dict:
        return {"x-client-id": self.cid, "x-client-secret": self.sec, "x-api-version": self.API_VERSION,
                "Content-Type": "application/json", **_signature_header(self.cid, self.pubkey)}

    def _do(self, method: str, path: str, **kw) -> tuple[int, dict]:
        """Returns (http_status, body). Raises TimeoutError on timeout/5XX (caller marks UNKNOWN)."""
        try:
            r = httpx.request(method, self.base + path, headers=self._h(), timeout=30, **kw)
        except (httpx.TimeoutException, httpx.NetworkError) as e:
            raise TimeoutError(type(e).__name__)
        if r.status_code >= 500:
            raise TimeoutError(f"HTTP {r.status_code}")
        if r.status_code in (401, 403):
            raise CashfreeUnavailable(f"HTTP {r.status_code}: {r.text[:160]}")
        try:
            return r.status_code, r.json()
        except ValueError:
            return r.status_code, {"raw": r.text[:300]}

    def create_beneficiary(self, beneficiary_id: str, name: str, account: str, ifsc: str,
                           phone: Optional[str] = None) -> tuple[int, dict]:
        body = {"beneficiary_id": beneficiary_id, "beneficiary_name": name,
                "beneficiary_instrument_details": {"bank_account_number": account, "bank_ifsc": ifsc}}
        if phone:
            body["beneficiary_contact_details"] = {"beneficiary_phone": phone}
        return self._do("POST", "/beneficiary", json=body)

    def get_beneficiary(self, beneficiary_id: str) -> tuple[int, dict]:
        return self._do("GET", "/beneficiary", params={"beneficiary_id": beneficiary_id})

    def transfer(self, transfer_id: str, amount, beneficiary_id: str, mode: str = "banktransfer",
                 remarks: str = "TijoriPay") -> tuple[int, dict]:
        body = {"transfer_id": transfer_id, "transfer_amount": float(amount),  # API takes a JSON number
                "transfer_mode": mode, "transfer_remarks": remarks[:70],
                "beneficiary_details": {"beneficiary_id": beneficiary_id}}
        return self._do("POST", "/transfers", json=body)

    def get_status(self, transfer_id: str) -> tuple[int, dict]:
        return self._do("GET", "/transfers", params={"transfer_id": transfer_id})
