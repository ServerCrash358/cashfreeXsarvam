"""Shared plumbing for every Cashfree call: sandbox guard, auth headers, JSON with exact amounts,
and logging that never shows keys or full account numbers."""
from __future__ import annotations

import base64
import json
import logging
import os
import re
import time
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urlparse

import httpx

log = logging.getLogger("panch.cashfree")

# Hosts we are allowed to talk to. Anything else (e.g. api.cashfree.com) is production.
SANDBOX_HOSTS = {"sandbox.cashfree.com", "payout-gamma.cashfree.com"}


class CashfreeUnavailable(Exception):
    """Auth/IP/network problem: callers may fall back to disclosed fixtures."""


class NotSandbox(RuntimeError):
    """Raised when the configuration points at anything other than the Cashfree sandbox."""


def assert_sandbox(base_url: str) -> None:
    """Red line: sandbox only. Refuse to build a client for production keys or hosts."""
    env = (os.getenv("CASHFREE_ENV") or "sandbox").strip().lower()
    if env != "sandbox":
        raise NotSandbox(f"CASHFREE_ENV is {env!r}; Panch only runs against the sandbox")
    host = (urlparse(base_url).hostname or "").lower()
    if host not in SANDBOX_HOSTS:
        raise NotSandbox(f"{host or base_url!r} is not a Cashfree sandbox host")


def signature_header(client_id: str, pubkey_path: Optional[str]) -> dict:
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


# ----------------------------------------------------------------- JSON bodies
_DEC = "__panch_decimal__"


def dumps_exact(body: Any) -> bytes:
    """JSON with Decimal amounts written as exact JSON numbers (never via float)."""
    def enc(o):
        if isinstance(o, Decimal):
            return f"{_DEC}{o:f}{_DEC}"
        raise TypeError(f"not JSON serialisable: {type(o).__name__}")
    text = json.dumps(body, default=enc, separators=(",", ":"))
    return re.sub(rf'"{_DEC}(-?[0-9.]+){_DEC}"', r"\1", text).encode()


# ---------------------------------------------------------------- redaction
_ACCOUNT_KEYS = {"bank_account", "bank_account_number", "account", "account_number"}
_SECRET_KEYS = {"x-client-secret", "client_secret", "secret", "x-cf-signature"}


def mask(value: Optional[str]) -> str:
    v = str(value or "")
    return ("xx" + v[-4:]) if v else ""


def redact(obj: Any) -> Any:
    """Copy of a request/response body that is safe to log."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            kl = str(k).lower()
            if kl in _SECRET_KEYS:
                out[k] = "***"
            elif kl in _ACCOUNT_KEYS:
                out[k] = mask(v)
            else:
                out[k] = redact(v)
        return out
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


def send(method: str, url: str, headers: dict, body: Optional[dict] = None, params: Optional[dict] = None,
         timeout: float = 30) -> httpx.Response:
    """One HTTP call. Network errors propagate as httpx exceptions; each client maps them."""
    content = dumps_exact(body) if body is not None else None
    log.debug("cashfree %s %s params=%s body=%s", method, urlparse(url).path, redact(params or {}), redact(body or {}))
    r = httpx.request(method, url, headers={**headers, "Content-Type": "application/json"}, content=content,
                      params=params, timeout=timeout)
    log.debug("cashfree %s %s -> %s", method, urlparse(url).path, r.status_code)
    return r
