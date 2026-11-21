"""Payouts v2 HTTP client: beneficiary, transfer, status (ARCHITECTURE section I).
HTTP only; the state machine and ledger live in panch/payouts. A 200 means submitted, never paid."""
from __future__ import annotations

import os
from decimal import Decimal
from typing import Optional

import httpx

from panch.cashfree.http import CashfreeUnavailable, assert_sandbox, send, signature_header


class PayoutsClient:
    API_VERSION = "2024-01-01"

    def __init__(self, base_url: Optional[str] = None):
        self.base = (base_url or os.getenv("CASHFREE_PAYOUT_BASE_URL") or "https://sandbox.cashfree.com/payout").rstrip("/")
        assert_sandbox(self.base)
        self.cid = os.getenv("CASHFREE_PAYOUT_CLIENT_ID") or os.getenv("CASHFREE_CLIENT_ID", "")
        self.sec = os.getenv("CASHFREE_PAYOUT_CLIENT_SECRET") or os.getenv("CASHFREE_CLIENT_SECRET", "")
        self.pubkey = os.getenv("CASHFREE_PAYOUT_PUBLIC_KEY_PATH")

    @property
    def secret(self) -> str:
        return self.sec

    def _h(self) -> dict:
        return {"x-client-id": self.cid, "x-client-secret": self.sec, "x-api-version": self.API_VERSION,
                **signature_header(self.cid, self.pubkey)}

    def _do(self, method: str, path: str, body: Optional[dict] = None, params: Optional[dict] = None) -> tuple[int, dict]:
        """Returns (http_status, body). Raises TimeoutError on timeout/network error/5XX: the caller marks the
        transfer UNKNOWN and polls; it never re-POSTs."""
        try:
            r = send(method, self.base + path, self._h(), body=body, params=params, timeout=30)
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
        return self._do("POST", "/beneficiary", body=body)

    def get_beneficiary(self, beneficiary_id: str) -> tuple[int, dict]:
        return self._do("GET", "/beneficiary", params={"beneficiary_id": beneficiary_id})

    def transfer(self, transfer_id: str, amount, beneficiary_id: str, mode: str = "banktransfer",
                 remarks: str = "Panch") -> tuple[int, dict]:
        # Decimal goes on the wire as an exact JSON number (panch.cashfree.http.dumps_exact), never via float
        amt = Decimal(str(amount)).quantize(Decimal("0.01"))
        body = {"transfer_id": transfer_id, "transfer_amount": amt, "transfer_mode": mode,
                "transfer_remarks": remarks[:70], "beneficiary_details": {"beneficiary_id": beneficiary_id}}
        return self._do("POST", "/transfers", body=body)

    def get_status(self, transfer_id: str) -> tuple[int, dict]:
        return self._do("GET", "/transfers", params={"transfer_id": transfer_id})
