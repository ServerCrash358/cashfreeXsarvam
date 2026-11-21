"""Webhook signature check (ARCHITECTURE section I2). Pure."""
from __future__ import annotations

import base64
import hashlib
import hmac


def verify_signature(secret: str, timestamp: str, raw_body: bytes, signature: str) -> bool:
    """base64(HMAC-SHA256(secret, timestamp + raw_body)) on the RAW body, compared in constant time.
    Same scheme as Cashfree.PGVerifyWebhookSignature in the cashfree_pg SDK (no separator)."""
    if not secret or not timestamp or not signature:
        return False
    mac = hmac.new(secret.encode(), timestamp.encode() + raw_body, hashlib.sha256).digest()
    return hmac.compare_digest(base64.b64encode(mac).decode(), signature)
