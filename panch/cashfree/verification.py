"""Secure ID clients: bank account (sync), GSTIN, Udyam (ARCHITECTURE section E)."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from typing import Optional

import httpx

from panch.cashfree.http import CashfreeUnavailable, assert_sandbox, send, signature_header

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "data" / "fixtures"


class VerificationClient:
    """Secure ID: bank account (sync), GSTIN, Udyam. Falls back to canned sandbox fixtures
    (marked canned=True) when the live API is unreachable, e.g. IP not whitelisted.
    Answers are cached per input so a re-evaluation never re-runs the same check."""

    def __init__(self, base_url: str = "https://sandbox.cashfree.com/verification", live: Optional[bool] = None):
        self.base = base_url.rstrip("/")
        assert_sandbox(self.base)
        self.cid = os.getenv("CASHFREE_CLIENT_ID", "")
        self.sec = os.getenv("CASHFREE_CLIENT_SECRET", "")
        self.pubkey = os.getenv("CASHFREE_SECURE_ID_PUBLIC_KEY_PATH")
        self.live = bool(self.cid and self.sec) if live is None else live
        self.fixtures = json.loads((FIXTURES / "verification.json").read_text(encoding="utf-8"))
        self.last_error: Optional[str] = None
        self._cache: dict[str, dict] = {}

    @staticmethod
    def _key(kind: str, *parts: Optional[str]) -> str:
        """Cache key: a hash, so full account numbers are never held as dict keys."""
        return kind + ":" + hashlib.sha256("|".join(p or "" for p in parts).encode()).hexdigest()[:24]

    def _cached(self, key: str, fetch) -> dict:
        if key in self._cache:
            return dict(self._cache[key])
        d = fetch()
        if not d.get("live_error"):              # never cache an outage; retry it next time
            self._cache[key] = dict(d)
        return d

    def _post(self, path: str, body: dict) -> dict:
        h = {"x-client-id": self.cid, "x-client-secret": self.sec, **signature_header(self.cid, self.pubkey)}
        try:
            r = send("POST", self.base + path, h, body=body, timeout=20)
        except httpx.HTTPError as e:
            raise CashfreeUnavailable(f"network: {type(e).__name__}")
        if r.status_code in (401, 403):
            try:
                msg = r.json().get("message", "")
            except ValueError:
                msg = r.text
            raise CashfreeUnavailable(f"HTTP {r.status_code}: {msg[:120]}")
        try:
            data = r.json()
        except ValueError:
            raise CashfreeUnavailable(f"HTTP {r.status_code}: non-JSON body")
        data["_http"] = r.status_code
        return data

    def bank(self, account: str, ifsc: str, name: Optional[str] = None) -> dict:
        def fetch():
            body = {"bank_account": account, "ifsc": ifsc}
            if name:
                body["name"] = name
            if self.live:
                try:
                    d = self._post("/bank-account/sync", body)
                    d["canned"] = False
                    return d
                except CashfreeUnavailable as e:
                    self.last_error = str(e)
            fx = self.fixtures["bank"].get(account)
            if fx is None:
                return {"account_status": "UNVERIFIABLE", "canned": True, "note": "not in sandbox test data",
                        "live_error": self.last_error if self.live else None}
            return {**fx, "canned": True, "live_error": self.last_error if self.live else None}
        return self._cached(self._key("bank", account, ifsc, name), fetch)

    def gstin(self, gstin: str, business_name: Optional[str] = None) -> dict:
        def fetch():
            if self.live:
                try:
                    d = self._post("/gstin", {"GSTIN": gstin, **({"business_name": business_name} if business_name else {})})
                    d["canned"] = False
                    return d
                except CashfreeUnavailable as e:
                    self.last_error = str(e)
            fx = self.fixtures["gstin"].get(gstin, {"valid": None, "note": "not in sandbox data"})
            return {**fx, "canned": True, "live_error": self.last_error if self.live else None}
        return self._cached(self._key("gstin", gstin, business_name), fetch)

    def udyam(self, udyam: str, verification_id: str) -> dict:
        def fetch():
            if self.live:
                try:
                    d = self._post("/udyam", {"verification_id": verification_id, "udyam": udyam})
                    d["canned"] = False
                    return d
                except CashfreeUnavailable as e:
                    self.last_error = str(e)
            fx = self.fixtures["udyam"].get(udyam, {"status": "UNVERIFIABLE"})
            return {**fx, "canned": True, "live_error": self.last_error if self.live else None}
        return self._cached(self._key("udyam", udyam), fetch)
