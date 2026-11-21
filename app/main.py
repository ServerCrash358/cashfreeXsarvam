"""TijoriPay FastAPI app. Run: .venv/Scripts/python -m uvicorn app.main:app --port 8000"""
from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import time
from contextlib import asynccontextmanager
from decimal import Decimal
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

from panch.engine import Engine, _j  # noqa: E402
from panch import voice  # noqa: E402

import os  # noqa: E402
engine = Engine(live=os.getenv("TIJORIPAY_OFFLINE") != "1")   # tests set TIJORIPAY_OFFLINE=1


@asynccontextmanager
async def lifespan(app):
    async def loop():
        while True:
            await asyncio.sleep(int(engine.cfg.get("sweep_seconds", 60)))
            try:
                await asyncio.to_thread(engine.sweep)
            except Exception as e:  # never let the sweep die
                engine.emit("sweep_error", {"error": type(e).__name__})
    task = asyncio.create_task(loop())
    yield
    task.cancel()


app = FastAPI(title="TijoriPay", lifespan=lifespan)


def _plan_view(lang: str):
    p = engine.plan_result
    if not p:
        return None
    b = list(engine.bundles.values())[-1]
    return {"cash_limit": str(p.cash_limit), "chosen": [i.invoice_id for i in p.chosen],
            "deferred": [i.invoice_id for i in p.deferred], "protected": str(p.protected),
            "naive_chosen": [i.invoice_id for i in p.naive_chosen], "naive_protected": str(p.naive_protected),
            "bundle": {"id": b.id, "hash": b.hash, "code": b.code, "status": b.status, "total": str(b.total),
                       "count": len(b.items), "expires_at": b.expires_at.isoformat(timespec="seconds"),
                       "prompt": engine.approval_prompt(b, lang)}}


@app.get("/")
def index():
    return FileResponse(ROOT / "app" / "static" / "index.html")


@app.get("/api/state")
def state(lang: str = "en"):
    return {"today": engine.today.isoformat(), "owner_lang": engine.cfg["owner_lang"],
            "payout_mode": engine.cfg.get("payout_mode"), "payout_base": engine.payouts.base,
            "verification_last_error": engine.verifier.last_error,
            "invoices": [engine.invoice_view(k, lang) for k in sorted(engine.invoices)],
            "plan": _plan_view(lang), "scoreboard": engine.scoreboard(), "events": engine.events[-20:]}


@app.post("/api/reset")
def reset():
    engine.reset()
    return {"ok": True}


@app.post("/api/invoices/{inv_id}/callback")
def callback_start(inv_id: str):
    try:
        s = engine.start_callback(inv_id)
    except ValueError as e:
        raise HTTPException(400, str(e))
    return s.public()


@app.post("/api/callbacks/{cb_id}/result")
async def callback_result(cb_id: str, transcript: Optional[str] = Form(None), audio: Optional[UploadFile] = File(None)):
    data = None
    if audio is not None:
        data = await audio.read()
        s = engine.callbacks[cb_id]
        try:
            transcript = await asyncio.to_thread(voice.transcribe, data, s.lang, None, audio.filename or "a.webm",
                                                 audio.content_type or "audio/webm")
        except Exception as e:
            raise HTTPException(502, f"speech-to-text failed: {e}")
    res = engine.finish_callback(cb_id, transcript or "", data)
    return {"code": res.code, "passed": res.passed, "severity": res.severity, "evidence": res.evidence}


@app.post("/api/invoices/{inv_id}/approve-account")
async def approve_account(inv_id: str, request: Request):
    body = await request.json()
    reasons = engine.approve_account_change(inv_id, str(body.get("pin", "")))
    return {"ok": not reasons, "reasons": reasons}


@app.post("/api/plan")
async def make_plan(request: Request):
    body = await request.json() if (await request.body()) else {}
    p, b = engine.make_plan(Decimal(str(body["cash"])) if body.get("cash") else None)
    return _plan_view(body.get("lang", "en"))


@app.post("/api/bundles/{bid}/approve")
async def approve(bid: str, transcript: Optional[str] = Form(None), channel: str = Form("voice"),
                  lang: str = Form("en"), audio: Optional[UploadFile] = File(None)):
    if bid not in engine.bundles:
        raise HTTPException(404, "no such bundle")
    if audio is not None:
        data = await audio.read()
        try:
            transcript = await asyncio.to_thread(voice.transcribe, data, lang, None, audio.filename or "a.webm",
                                                 audio.content_type or "audio/webm")
        except Exception as e:
            raise HTTPException(502, f"speech-to-text failed: {e}")
    res = engine.approve_voice(bid, transcript or "", channel)
    return {"transcript": transcript, **res.__dict__}


@app.post("/api/bundles/{bid}/pin")
async def pin(bid: str, request: Request):
    body = await request.json()
    reasons = engine.approve_pin(bid, str(body.get("pin", "")))
    return {"ok": not reasons, "reasons": reasons}


@app.post("/api/bundles/{bid}/execute")
def execute(bid: str):
    try:
        return {"results": engine.execute(bid)}
    except ValueError as e:
        raise HTTPException(400, str(e))


@app.post("/api/sweep")
def sweep():
    engine.sweep()
    return {"ok": True}


@app.post("/webhooks/cashfree/payouts")
async def cf_webhook(request: Request):
    raw = await request.body()
    headers = {k.lower(): v for k, v in request.headers.items()}
    res = engine.webhook(raw, headers)
    return JSONResponse(res, status_code=200 if res.get("ok") else 401)


@app.post("/api/simulate/webhook")
async def simulate_webhook(request: Request):
    """Demo aid: builds a payout webhook signed with our secret and sends it through the real verifier.
    Labelled SIMULATED in the UI; a real Cashfree delivery uses the same path."""
    body = await request.json()
    att = engine.ledger.attempts.get(body["transfer_id"])
    if not att:
        raise HTTPException(404, "unknown transfer")
    status = body.get("status", "REVERSED")
    payload = {"type": f"TRANSFER_{status}", "event_time": time.strftime("%Y-%m-%dT%H:%M:%S"),
               "data": {"transfer_id": att.transfer_id, "cf_transfer_id": att.cf_transfer_id, "status": status,
                        "status_code": body.get("status_code"), "transfer_amount": float(att.amount)}}
    raw = json.dumps(payload).encode()
    ts = str(int(time.time()))
    sig = base64.b64encode(hmac.new(engine.payouts.secret.encode(), ts.encode() + raw, hashlib.sha256).digest()).decode()
    return engine.webhook(raw, {"x-webhook-timestamp": ts, "x-webhook-signature": sig})


@app.post("/api/tts")
async def tts(request: Request):
    body = await request.json()
    try:
        audio = await asyncio.to_thread(voice.speak, body["text"], body.get("lang", "en"))
    except Exception as e:
        raise HTTPException(502, f"text-to-speech failed: {e}")
    return Response(audio, media_type="audio/wav")


@app.get("/api/audit")
def audit():
    return {"chain_ok": engine.audit.verify_chain(), "entries": engine.audit.entries[-200:]}


@app.get("/api/payouts/{tid}")
def payout(tid: str):
    a = engine.ledger.attempts.get(tid)
    if not a:
        raise HTTPException(404, "unknown transfer")
    return a.to_dict()
