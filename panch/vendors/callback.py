"""Vendor call-back on the old number (ARCHITECTURE section E2).
Uses the vendor-master phone ONLY, never the number printed on the invoice."""
from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional

from panch.models import CheckResult, Invoice, Vendor
from panch.voice import render
from panch.voice.digits import extract_digits


@dataclass
class CallbackSession:
    id: str
    vendor_id: str
    invoice_id: str
    phone_used: str
    expected_last4: str               # from the invoice's (new) account
    lang: str
    prompt: str
    started_at: str
    invoice_phone_ignored: Optional[str] = None
    result: Optional[dict] = field(default=None)

    def public(self) -> dict:
        d = {k: v for k, v in self.__dict__.items() if k != "expected_last4"}
        d["phone_used"] = mask_phone(self.phone_used)
        d["invoice_phone_ignored"] = mask_phone(self.invoice_phone_ignored)
        return d


def mask_phone(p: Optional[str]) -> Optional[str]:
    return None if not p else "xxxxxx" + p[-4:]


def start_callback(vendor: Vendor, invoice: Invoice) -> CallbackSession:
    if not vendor.phone_on_file:
        raise ValueError("no phone on file: cannot call back")
    prompt = render("callback_prompt", vendor.language, vendor=vendor.legal_name, amount=invoice.total)
    return CallbackSession(id="cb_" + secrets.token_hex(4), vendor_id=vendor.id, invoice_id=invoice.id,
                           phone_used=vendor.phone_on_file, expected_last4=invoice.account_last4,
                           lang=vendor.language, prompt=prompt, started_at=datetime.now().isoformat(timespec="seconds"),
                           invoice_phone_ignored=invoice.vendor_phone_on_invoice)


def finish_callback(session: CallbackSession, transcript: Optional[str],
                    audio: Optional[bytes] = None) -> CheckResult:
    """Pure comparison of the spoken last four with the invoice account's last four."""
    ev = {"phone_used": mask_phone(session.phone_used), "transcript": transcript,
          "audio_sha256": hashlib.sha256(audio).hexdigest() if audio else None,
          "invoice_account_last4": session.expected_last4}
    if not transcript or not transcript.strip():
        return CheckResult("CALLBACK_NO_ANSWER", False, "ask", ev, "callback_no_answer")
    digits = extract_digits(transcript, session.lang)
    spoken = digits[-4:] if len(digits) >= 4 else digits
    ev["spoken_last4"] = spoken
    if len(spoken) < 4:
        return CheckResult("CALLBACK_NO_ANSWER", False, "ask", {**ev, "reason": "fewer than four digits heard"},
                           "callback_no_answer")
    if spoken != session.expected_last4:
        return CheckResult("CALLBACK_MISMATCH", False, "block", ev, "callback_mismatch")
    return CheckResult("CALLBACK_MISMATCH", True, "info", ev, "callback_ok")
