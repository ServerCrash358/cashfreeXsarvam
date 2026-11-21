"""Cashfree Relay adapter (ARCHITECTURE section O).

Relay is Cashfree's hosted agent canvas (triggers, HTTP actions, secret properties, Sarvam voice actions).
TijoriPay's deterministic core stays here; Relay is an *orchestration and voice* layer around it:

  TijoriPay --(inbound-webhook trigger)--> Relay agent      e.g. "place the vendor call-back"
  Relay agent --(HTTP action)--> TijoriPay /api/relay/...   e.g. "vendor said 7-7-2-3"   (needs a public URL)

Config (.env): RELAY_WEBHOOK_URL (the agent's inbound-webhook trigger URL, from the Relay canvas) and
RELAY_SHARED_SECRET (sent to Relay in a header, and required from Relay on our /api/relay/* endpoints).
If RELAY_WEBHOOK_URL is unset, Relay is off and every call is a no-op: the app works the same without it.

Payloads carry no secrets and no full account numbers or phone numbers (last four only). Relay never
decides anything: it can trigger a call and report what was heard; the code compares and decides.
UNVERIFIED: the exact inbound-webhook payload shape Relay expects; we send flat JSON with an `event` field.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import threading
from datetime import datetime
from typing import Optional

import httpx

EVENTS = {"callback_requested", "bill_blocked", "payout_success", "payout_reversed", "batch_ready"}


class RelayClient:
    def __init__(self, url: Optional[str] = None, secret: Optional[str] = None, sync: bool = False):
        self.url = url if url is not None else os.getenv("RELAY_WEBHOOK_URL", "")
        self.secret = secret if secret is not None else os.getenv("RELAY_SHARED_SECRET", "")
        self.sync = sync                       # tests use sync=True; the app fires in a background thread
        self.sent: list[dict] = []             # last events (for the UI / audit), never includes secrets

    @property
    def enabled(self) -> bool:
        return bool(self.url)

    def _post(self, payload: dict) -> dict:
        raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
        headers = {"Content-Type": "application/json"}
        if self.secret:
            headers["x-tijoripay-signature"] = hmac.new(self.secret.encode(), raw, hashlib.sha256).hexdigest()
        try:
            r = httpx.post(self.url, content=raw, headers=headers, timeout=5)
            return {"ok": r.status_code < 300, "http": r.status_code}
        except httpx.HTTPError as e:            # Relay down must never break the payment flow
            return {"ok": False, "error": type(e).__name__}

    def trigger(self, event: str, **data) -> dict:
        if event not in EVENTS:
            raise ValueError(f"unknown relay event {event}")
        payload = {"event": event, "source": "tijoripay", "at": datetime.now().isoformat(timespec="seconds"), **data}
        record = {"event": event, "data": data, "at": payload["at"]}
        if not self.enabled:
            record["result"] = {"ok": False, "skipped": "relay not configured"}
        elif self.sync:
            record["result"] = self._post(payload)
        else:
            record["result"] = {"ok": None, "queued": True}
            threading.Thread(target=lambda: record.update(result=self._post(payload)), daemon=True).start()
        self.sent.append(record)
        self.sent = self.sent[-50:]
        return record

    def check_inbound(self, raw: bytes, signature: Optional[str]) -> bool:
        """Relay -> us: HMAC-SHA256(shared secret, raw body), hex. No secret configured -> refuse everything."""
        if not self.secret or not signature:
            return False
        expected = hmac.new(self.secret.encode(), raw, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)


def mask_phone(p: Optional[str]) -> Optional[str]:
    return None if not p else "xxxxxx" + p[-4:]
