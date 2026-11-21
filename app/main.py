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


UPLOADS = ROOT / "data" / "uploads"


@app.post("/api/upload")
async def upload(files: list[UploadFile] = File(...)):
    """Curveball intake: invoice images/PDFs -> Sarvam Vision Extract (PR 1, cached by file hash) -> gate."""
    from panch.reading import read_invoice
    UPLOADS.mkdir(parents=True, exist_ok=True)
    results = []
    for f in files:
        name = Path(f.filename or "upload").name
        dest = UPLOADS / name
        dest.write_bytes(await f.read())
        try:
            inv = await asyncio.to_thread(read_invoice, dest)
            if inv.total is None and not inv.lines and not inv.vendor_name_raw:
                # nothing readable (not an invoice, or Vision failed): report it, don't add a blank bill
                results.append({"file": name, "error": "could not read an invoice from this file"})
                continue
            inv_id = engine.add_invoice(inv, name)
            v = engine.invoice_view(inv_id, engine.cfg["owner_lang"])
            results.append({"file": name, "id": inv_id, "outcome": v["outcome"], "codes": v["codes"]})
        except Exception as e:  # a bad read must never take the app down
            results.append({"file": name, "error": f"{type(e).__name__}: {str(e)[:200]}"})
    return {"results": results}


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
    if cb_id not in engine.callbacks:
        raise HTTPException(404, "no such call-back")
    if audio is not None:
        data = await audio.read()
        s = engine.callbacks[cb_id]
        try:
            transcript = await asyncio.to_thread(voice.transcribe, data, s.lang, None, audio.filename or "a.webm",
                                                 audio.content_type or "audio/webm")
        except Exception as e:
            raise HTTPException(502, f"speech-to-text failed: {e}")
    try:
        res = engine.finish_callback(cb_id, transcript or "", data)
    except ValueError as e:
        raise HTTPException(409, str(e))
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
    """Demo aid, SIM MODE ONLY: injects a payout event for a simulated transfer, labelled simulated.
    It never signs anything (an empty or shared secret would make forged webhooks pass), and it is
    refused in live mode, where only a real, signature-verified Cashfree delivery can move money state."""
    if engine.cfg.get("payout_mode") != "sim":
        raise HTTPException(403, "simulated webhooks are only available in sim payout mode")
    body = await request.json()
    att = engine.ledger.attempts.get(body["transfer_id"])
    if not att:
        raise HTTPException(404, "unknown transfer")
    if not att.simulated:
        raise HTTPException(403, "only simulated transfers can receive simulated events")
    status = body.get("status", "REVERSED")
    payload = {"type": f"TRANSFER_{status}", "event_time": time.strftime("%Y-%m-%dT%H:%M:%S"), "simulated": True,
               "data": {"transfer_id": att.transfer_id, "cf_transfer_id": att.cf_transfer_id, "status": status,
                        "status_code": body.get("status_code"), "transfer_amount": float(att.amount)}}
    return {**engine.webhook(json.dumps(payload).encode(), {}, verify=False), "simulated": True}


@app.get("/api/relay")
def relay_status():
    """Whether Relay is wired, and the last events we triggered (no secrets in them)."""
    return {"enabled": engine.relay.enabled, "events": engine.relay.sent[-20:]}


@app.post("/api/relay/callbacks/{cb_id}/result")
async def relay_callback_result(cb_id: str, request: Request):
    """Relay HTTP action -> us: what the vendor said on the call Relay placed. Authenticated with
    x-tijoripay-signature = hex HMAC-SHA256(RELAY_SHARED_SECRET, raw body). Relay only reports the
    transcript; the comparison and the decision happen here, exactly as for a call made from the UI."""
    raw = await request.body()
    if not engine.relay.check_inbound(raw, request.headers.get("x-tijoripay-signature")):
        raise HTTPException(401, "bad or missing relay signature")
    if cb_id not in engine.callbacks:
        raise HTTPException(404, "no such call-back")
    body = json.loads(raw or b"{}")
    try:
        res = engine.finish_callback(cb_id, str(body.get("transcript", "")))
    except ValueError as e:
        raise HTTPException(409, str(e))
    engine.audit.append("relay_callback_result", {"code": res.code, "passed": res.passed}, actor="relay",
                        entity=engine.callbacks[cb_id].invoice_id)
    return {"code": res.code, "passed": res.passed}


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
