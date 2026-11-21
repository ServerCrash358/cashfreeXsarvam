"""Panch owner app (M): FastAPI routes for voice, approval, call-back and the UI.

Run (when you are ready):  uvicorn app.main:app --reload --port 8000

PR 4 owns this file. Other modules plug in here:
- batches/decisions: GET /api/batches/{id} serves app/demo_fixture.json until
  reading (PR 1) + checks/decide (PR 2) + planner (Krish) are wired in.
- payouts (PR 3): POST /api/bundles/{id}/execute calls
  `panch.payouts.execute_bundle(bundle, approval)` once it exists; webhook
  handling should call `app.events.publish("payout", ...)` so the UI updates.
- audit (Krish): every approval and call-back is sent to `panch.audit.append`
  when that module exists.

Audio travels as base64 JSON (no python-multipart dependency).
"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Literal, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app import events
from panch.approval import (SECOND_APPROVER_REQUIRED, ApprovalStore, Approver, BundleError,
                            BundleItem, assert_executable, make_approver, make_bundle,
                            prompt_text)
from panch.vendors.callback import CallbackSession, finish_callback, start_callback
from panch.voice.client import VoiceClient, VoiceUnavailable
from panch.voice.templates import LANGS, TemplateMissing, format_inr, render

try:  # optional .env loading; python-dotenv is pinned in requirements
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:  # pragma: no cover
    pass

HERE = Path(__file__).resolve().parent
FIXTURE = HERE / "demo_fixture.json"
DEV = os.getenv("PANCH_DEV", "1") == "1"

@asynccontextmanager
async def lifespan(_app):
    events.bind_loop(asyncio.get_running_loop())
    yield


app = FastAPI(title="Panch", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=HERE / "static"), name="static")

def load_approvers() -> list[Approver]:
    """PANCH_APPROVERS="owner:<salt>:<pbkdf2 hex>,partner:<salt>:<hex>" (make with
    panch.approval.make_approver). In dev only, fall back to owner PIN 1234 and
    partner PIN 5678 so the flow can be rehearsed; never use those in the demo."""
    spec = os.getenv("PANCH_APPROVERS", "").strip()
    if spec:
        out = []
        for part in spec.split(","):
            aid, salt, h = part.strip().split(":")
            out.append(Approver(aid, salt, h))
        return out
    if DEV:
        return [make_approver("owner", "1234", "devsalt-owner"),
                make_approver("partner", "5678", "devsalt-partner")]
    return []


_second = os.getenv("PANCH_SECOND_APPROVER_ABOVE")
voice = VoiceClient()
approvals = ApprovalStore(load_approvers(), Decimal(_second) if _second else None)
callbacks: dict[str, CallbackSession] = {}
account_change_approved: set[str] = set()   # invoice ids whose new account the owner approved (E2)
callback_failed: dict[str, str] = {}         # invoice id -> CALLBACK_MISMATCH / CALLBACK_NO_ANSWER


def now() -> datetime:
    return datetime.now(timezone.utc)


def audit(action: str, payload: dict) -> None:
    try:
        from panch.audit import append  # type: ignore  (Krish)
    except ImportError:
        return
    try:
        append(action, payload)
    except Exception as e:  # never let audit failure hide the decision; surface it
        events.publish("error", where="audit", detail=str(e))


# --- helpers --------------------------------------------------------------------

def load_batch(batch_id: str) -> dict:
    if batch_id != "demo":
        raise HTTPException(404, "only the demo batch is served until the pipeline is wired in")
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def account_hash(number: str, ifsc: str) -> str:
    return hashlib.sha256(f"{number}|{ifsc.upper()}".encode()).hexdigest()


def safe_render(key: str, lang: str, **vars) -> str:
    try:
        return render(key, lang, **vars)
    except TemplateMissing:
        return f"[{key}: missing {lang} template]"
    except KeyError as e:
        return f"[{key}: missing value {e}]"


def tts(text: str, lang: str) -> Optional[str]:
    """Base64 audio, or None when Sarvam is not configured (UI shows text only)."""
    if not voice.available:
        return None
    try:
        return base64.b64encode(voice.speak(text, lang)).decode()
    except VoiceUnavailable:
        return None
    except Exception as e:
        events.publish("error", where="tts", detail=str(e))
        return None


def public_invoice(inv: dict, vendors: dict, lang: str) -> dict:
    """Never send full account numbers to the browser: last four only."""
    v = vendors.get(inv["vendor_id"], {})
    acct = inv.get("account_number") or ""
    codes = list(inv.get("codes", []))
    if inv["id"] in account_change_approved and "ACCOUNT_CHANGED" in codes:
        codes.remove("ACCOUNT_CHANGED")
    outcome = inv["outcome"]
    failed = callback_failed.get(inv["id"])
    if failed:
        codes = [c for c in codes if c != "ACCOUNT_CHANGED"] + [failed]
        outcome = "BLOCK" if failed == "CALLBACK_MISMATCH" else "ASK"
    if outcome == "ASK" and not codes:
        outcome = "PAY"
    reasons = [{"code": c, "text": safe_render(c.lower(), lang)} for c in codes] or \
              [{"code": "PAY_READY", "text": safe_render("pay_ready", lang)}]
    return {
        "id": inv["id"], "label": inv.get("label"), "vendor_id": inv["vendor_id"],
        "vendor_name": v.get("name", inv["vendor_id"]), "enterprise_type": v.get("enterprise_type"),
        "amount": inv["amount"], "amount_display": format_inr(Decimal(inv["amount"])),
        "outcome": outcome, "codes": codes, "reasons": reasons,
        "msme_days_left": inv.get("msme_days_left"), "account_last4": acct[-4:],
        "account_change_approved": inv["id"] in account_change_approved,
    }


# --- pages and events -------------------------------------------------------------

@app.get("/")
def index():
    return FileResponse(HERE / "static" / "index.html")


@app.get("/api/health")
def health():
    mods = {}
    for m in ("panch.models", "panch.normalise", "panch.reading", "panch.checks", "panch.decide",
              "panch.payouts", "panch.planner", "panch.audit"):
        try:
            __import__(m)
            mods[m] = True
        except ImportError:
            mods[m] = False
    return {"voice": voice.available, "dev": DEV, "modules": mods, "langs": LANGS,
            "approvers": sorted(approvals.approvers),
            "dev_pins": DEV and not os.getenv("PANCH_APPROVERS")}


@app.get("/api/events")
async def sse(request: Request):
    last = int(request.headers.get("last-event-id", "0") or 0)
    return StreamingResponse(events.stream(last), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


# --- batches ------------------------------------------------------------------------

@app.get("/api/batches/{batch_id}")
def get_batch(batch_id: str, lang: str = "ta"):
    b = load_batch(batch_id)
    vendors = {v["id"]: v for v in b["vendors"]}
    invs = [public_invoice(i, vendors, lang) for i in b["invoices"]]
    by_id = {i["id"]: i for i in invs}
    plan = b.get("plan", {})
    for iid in plan.get("deferred", []):
        if by_id.get(iid, {}).get("outcome") == "PAY":
            by_id[iid]["outcome"] = "DEFER"
            by_id[iid]["reasons"] = [{"code": "CASH_DEFERRED", "text": safe_render("cash_deferred", lang)}]
    return {"batch_id": b["batch_id"], "buyer": b.get("buyer"), "cash_limit": b.get("cash_limit"),
            "invoices": invs, "plan": plan, "source": "fixture"}


# --- speech ---------------------------------------------------------------------------

class SpeakReq(BaseModel):
    message_key: str
    lang: str = "ta"
    vars: dict = Field(default_factory=dict)
    audio: bool = True


@app.post("/api/speak")
def speak(req: SpeakReq):
    vars = {k: (Decimal(v) if k in ("amount", "total") and isinstance(v, (str, int)) else v)
            for k, v in req.vars.items()}
    text = safe_render(req.message_key, req.lang, **vars)
    return {"text": text, "audio_b64": tts(text, req.lang) if req.audio else None}


def _transcribe(audio_b64: Optional[str], transcript: Optional[str], lang: str,
                keyterms=(), mime: str = "audio/wav") -> str:
    if transcript is not None:
        if not DEV:
            raise HTTPException(400, "typed transcripts are only accepted in dev mode")
        return transcript
    if not audio_b64:
        raise HTTPException(400, "send audio_b64 (or transcript in dev mode)")
    ext = "webm" if "webm" in mime else "wav"
    try:
        return voice.transcribe(base64.b64decode(audio_b64), lang, keyterms,
                                filename=f"audio.{ext}", content_type=mime)
    except VoiceUnavailable as e:
        raise HTTPException(503, f"speech-to-text unavailable: {e}")


# --- bundle approval (H) ---------------------------------------------------------------

class BundleReq(BaseModel):
    batch_id: str = "demo"
    invoice_ids: list[str]
    cash_limit: Optional[str] = None
    lang: str = "ta"


@app.post("/api/bundles")
def create_bundle(req: BundleReq):
    b = load_batch(req.batch_id)
    vendors = {v["id"]: v for v in b["vendors"]}
    invs = {i["id"]: i for i in b["invoices"]}
    items = []
    for iid in req.invoice_ids:
        inv = invs.get(iid)
        if inv is None:
            raise HTTPException(404, f"unknown invoice {iid}")
        pub = public_invoice(inv, vendors, req.lang)
        if pub["outcome"] == "BLOCK":
            raise HTTPException(409, f"invoice {iid} is blocked: {pub['codes']}")
        items.append(BundleItem(
            invoice_id=iid, beneficiary_id=inv["beneficiary_id"],
            account_hash=account_hash(inv["account_number"], inv["ifsc"]),
            amount=Decimal(inv["amount"]), vendor_name=pub["vendor_name"],
            account_change_pending="ACCOUNT_CHANGED" in pub["codes"],
            changed_account=iid in account_change_approved,
        ))
    cash = Decimal(req.cash_limit or b.get("cash_limit") or "0")
    try:
        bundle = approvals.add(make_bundle(items, cash, now()))
    except BundleError as e:
        raise HTTPException(409, {"code": e.code, "detail": str(e)})
    text = prompt_text(bundle, req.lang)
    audit("bundle_created", {"bundle_id": bundle.id, "hash": bundle.hash,
                             "items": [i.invoice_id for i in bundle.items], "total": str(bundle.total)})
    events.publish("bundle", bundle_id=bundle.id, count=bundle.count, total=str(bundle.total))
    return {
        "bundle_id": bundle.id, "hash": bundle.hash, "count": bundle.count,
        "total": str(bundle.total), "total_display": format_inr(bundle.total),
        "code": bundle.code, "expires_at": bundle.expires_at.isoformat(),
        "approvers_required": approvals.required(bundle.id),
        "items": [{"invoice_id": i.invoice_id, "vendor_name": i.vendor_name,
                   "amount_display": format_inr(i.amount)} for i in bundle.items],
        "prompt": text, "audio_b64": tts(text, req.lang),
    }


class ApproveReq(BaseModel):
    channel: Literal["voice", "typed"] = "voice"
    lang: str = "ta"
    audio_b64: Optional[str] = None
    mime: str = "audio/wav"
    transcript: Optional[str] = None     # dev only: lets you rehearse without a mic
    code: Optional[str] = None           # typed fallback


@app.post("/api/bundles/{bundle_id}/approve")
def approve(bundle_id: str, req: ApproveReq):
    if bundle_id not in approvals.bundles:
        raise HTTPException(404, "unknown bundle")
    if req.channel == "typed":
        response = req.code or ""
    else:
        response = _transcribe(req.audio_b64, req.transcript, req.lang, mime=req.mime)
    # Step 1 of 2: the spoken (or typed) confirmation. It never authorises on its own.
    result = approvals.confirm(bundle_id, response, now(), channel=req.channel, lang=req.lang)
    bundle = approvals.bundles[bundle_id]
    key = "approval_pin" if result.valid else "approval_invalid"
    text = safe_render(key, req.lang, count=bundle.count, total=bundle.total)
    audit("approval_confirmation", {"bundle_id": bundle_id, "hash": bundle.hash, "channel": req.channel,
                                    "valid": result.valid, "codes": list(result.codes),
                                    "checks": result.checks, "transcript": result.transcript})
    events.publish("approval", bundle_id=bundle_id, step="confirm", valid=result.valid,
                   codes=list(result.codes))
    return {"valid": result.valid, "codes": list(result.codes), "checks": result.checks,
            "transcript": result.transcript, "message": text, "audio_b64": tts(text, req.lang),
            "next": "pin" if result.valid else "confirm",
            "approvers_required": approvals.required(bundle_id)}


class PinReq(BaseModel):
    approver_id: str = "owner"
    pin: str
    bundle_hash: str          # the hash the screen showed when the PIN was tapped
    lang: str = "ta"


@app.post("/api/bundles/{bundle_id}/pin")
def pin_tap(bundle_id: str, req: PinReq):
    """Step 2 of 2: the PIN tap is the authority (ARCHITECTURE H)."""
    if bundle_id not in approvals.bundles:
        raise HTTPException(404, "unknown bundle")
    auth = approvals.tap_pin(bundle_id, req.approver_id, req.pin, req.bundle_hash, now())
    bundle = approvals.bundles[bundle_id]
    if auth.valid:
        key = "approval_authorised"
    elif auth.codes == (SECOND_APPROVER_REQUIRED,):
        key = "approval_second"
    else:
        key = "approval_invalid"
    text = safe_render(key, req.lang, count=bundle.count, total=bundle.total)
    audit("approval_pin", {"bundle_id": bundle_id, "hash": bundle.hash, "approver": req.approver_id,
                           "valid": auth.valid, "codes": list(auth.codes),
                           "approvers": list(auth.approvers), "required": auth.required})
    events.publish("approval", bundle_id=bundle_id, step="pin", valid=auth.valid,
                   codes=list(auth.codes), approvers=list(auth.approvers))
    return {"authorised": auth.valid, "codes": list(auth.codes), "approvers": list(auth.approvers),
            "required": auth.required, "message": text, "audio_b64": tts(text, req.lang)}


@app.post("/api/bundles/{bundle_id}/execute")
def execute(bundle_id: str):
    bundle = approvals.bundles.get(bundle_id)
    if bundle is None:
        raise HTTPException(404, "unknown bundle")
    auth = approvals.authorisations.get(bundle_id)
    try:
        assert_executable(bundle, auth)
    except BundleError as e:
        raise HTTPException(409, {"code": e.code, "detail": str(e)})
    try:
        from panch.payouts import execute_bundle  # type: ignore  (PR 3)
    except ImportError:
        raise HTTPException(501, "payouts module (PR 3) is not on main yet")
    result = execute_bundle(bundle, auth)
    return {"bundle_id": bundle_id, "result": result}


# --- vendor call-back (E2) ------------------------------------------------------------

class CallbackReq(BaseModel):
    batch_id: str = "demo"
    invoice_id: str


@app.post("/api/callbacks")
def create_callback(req: CallbackReq):
    b = load_batch(req.batch_id)
    inv = next((i for i in b["invoices"] if i["id"] == req.invoice_id), None)
    if inv is None:
        raise HTTPException(404, "unknown invoice")
    vendor = next((v for v in b["vendors"] if v["id"] == inv["vendor_id"]), None)
    if vendor is None:
        raise HTTPException(404, "vendor not in vendor master")
    session = start_callback(vendor, inv, buyer=b.get("buyer", "Raghu Hardware"), now=now())
    callbacks[session.id] = session
    audit("callback_started", {"session": session.id, "vendor_id": session.vendor_id,
                               "invoice_id": session.invoice_id, "phone_used": session.public()["phone_used"]})
    events.publish("callback", session_id=session.id, invoice_id=session.invoice_id, state="started")
    return {**session.public(), "audio_b64": tts(session.prompt, session.lang)}


class CallbackResultReq(BaseModel):
    audio_b64: Optional[str] = None
    mime: str = "audio/wav"
    transcript: Optional[str] = None     # dev only


@app.post("/api/callbacks/{session_id}/result")
def callback_result(session_id: str, req: CallbackResultReq):
    s = callbacks.get(session_id)
    if s is None:
        raise HTTPException(404, "unknown call-back")
    transcript = _transcribe(req.audio_b64, req.transcript, s.lang, mime=req.mime)
    audio_sha = hashlib.sha256(base64.b64decode(req.audio_b64)).hexdigest() if req.audio_b64 else None
    s.result = finish_callback(s, transcript, audio_sha256=audio_sha)
    if s.result.passed:
        callback_failed.pop(s.invoice_id, None)
    else:
        callback_failed[s.invoice_id] = s.result.code
    audit("callback_result", {"session": s.id, "invoice_id": s.invoice_id, "code": s.result.code,
                              "passed": s.result.passed, "evidence": s.result.evidence})
    events.publish("callback", session_id=s.id, invoice_id=s.invoice_id, state="finished",
                   passed=s.result.passed, code=s.result.code, message_key=s.result.message_key)
    return {**s.public(), "transcript": transcript}


class OwnerDecisionReq(BaseModel):
    approve: bool
    lang: str = "ta"


@app.post("/api/callbacks/{session_id}/owner")
def owner_account_change(session_id: str, req: OwnerDecisionReq):
    """Separate owner approval of the account change, only after a matching call-back."""
    s = callbacks.get(session_id)
    if s is None or s.result is None:
        raise HTTPException(404, "call-back not finished")
    if not s.result.passed:
        raise HTTPException(409, "call-back did not match; this account cannot be approved")
    if req.approve:
        account_change_approved.add(s.invoice_id)
    audit("account_change_decision", {"session": s.id, "invoice_id": s.invoice_id, "approved": req.approve})
    events.publish("account_change", invoice_id=s.invoice_id, approved=req.approve)
    return {"invoice_id": s.invoice_id, "approved": req.approve}


# --- dev helpers (rehearse the UI before PR 3 lands) -----------------------------------

class SimReq(BaseModel):
    invoice_id: str
    state: Literal["PENDING", "SUCCESS", "FAILED", "REVERSED"]


@app.post("/api/dev/payout-event")
def simulate_payout(req: SimReq):
    if not DEV:
        raise HTTPException(404)
    b = load_batch("demo")
    inv = next((i for i in b["invoices"] if i["id"] == req.invoice_id), None)
    if inv is None:
        raise HTTPException(404)
    vendor = next(v for v in b["vendors"] if v["id"] == inv["vendor_id"])
    key = {"PENDING": "payout_pending", "SUCCESS": "payout_success",
           "FAILED": "payout_failed", "REVERSED": "payout_reversed"}[req.state]
    return events.publish("payout", invoice_id=req.invoice_id, state=req.state, simulated=True,
                          message_key=key, vars={"vendor": vendor["name"], "amount": inv["amount"]})
