"""Relay adapter: off by default, safe payloads, signed both ways, never decides. Offline (httpx mocked)."""
import hashlib
import hmac
import json
import os

import httpx
import pytest

from panch.engine import Engine
from panch.relay import RelayClient


class Hit:
    def __init__(self):
        self.calls = []

    def __call__(self, url, content=None, headers=None, timeout=None):
        self.calls.append({"url": url, "body": json.loads(content), "headers": headers})
        return httpx.Response(200)


def relay_engine(monkeypatch, secret="s3cret"):
    hit = Hit()
    monkeypatch.setattr(httpx, "post", hit)
    e = Engine(live=False)
    e.relay = RelayClient(url="https://relay.example/hook", secret=secret, sync=True)
    return e, hit


def test_relay_off_when_not_configured():
    r = RelayClient(url="")
    rec = r.trigger("batch_ready", bills=8)
    assert not r.enabled and rec["result"]["skipped"]


def test_unknown_event_refused():
    with pytest.raises(ValueError):
        RelayClient(url="x").trigger("pay_everyone")


def test_callback_request_payload_is_safe_and_signed(monkeypatch):
    e, hit = relay_engine(monkeypatch)
    s = e.start_callback("F")
    call = hit.calls[-1]
    body = call["body"]
    assert body["event"] == "callback_requested" and body["callback_id"] == s.id
    assert body["phone"] == "9876501234"                         # vendor MASTER phone (Relay must dial it)
    assert "9123409876" not in json.dumps(body)                  # never the phone printed on the invoice
    assert "1191" not in json.dumps(body) and "026291800001191" not in json.dumps(body)  # no expected digits/account
    raw = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode()
    assert call["headers"]["x-tijoripay-signature"] == hmac.new(b"s3cret", raw, hashlib.sha256).hexdigest()


def test_payout_and_block_events(monkeypatch):
    e, hit = relay_engine(monkeypatch)
    e.cfg["payout_mode"] = "sim"
    s = e.start_callback("F")
    e.finish_callback(s.id, "seven seven two three")              # F turns BLOCK -> bill_blocked
    assert any(c["body"]["event"] == "bill_blocked" and c["body"]["invoice_id"] == "F" for c in hit.calls)
    from decimal import Decimal as D
    _, b = e.make_plan(D("4000"))
    e.approve_voice(b.id, b.code, channel="typed"); e.approve_pin(b.id, "2468"); e.execute(b.id)
    for _ in range(3):
        e.sweep()
    assert any(c["body"]["event"] == "payout_success" and c["body"]["invoice_id"] == "H" for c in hit.calls)


def test_relay_down_never_breaks_the_flow(monkeypatch):
    def boom(*a, **k):
        raise httpx.ConnectError("down")
    monkeypatch.setattr(httpx, "post", boom)
    e = Engine(live=False)
    e.relay = RelayClient(url="https://relay.example/hook", secret="x", sync=True)
    s = e.start_callback("F")                                    # still works
    assert e.relay.sent[-1]["result"]["ok"] is False and s.id in e.callbacks


def test_inbound_result_endpoint_requires_signature_and_decides_here(monkeypatch):
    os.environ["TIJORIPAY_OFFLINE"] = "1"
    from fastapi.testclient import TestClient
    import app.main as m
    c = TestClient(m.app)
    c.post("/api/reset")
    m.engine.relay = RelayClient(url="", secret="s3cret")
    s = m.engine.start_callback("F")
    body = json.dumps({"transcript": "seven seven two three"}).encode()
    path = f"/api/relay/callbacks/{s.id}/result"
    assert c.post(path, content=body).status_code == 401                                   # unsigned
    assert c.post(path, content=body, headers={"x-tijoripay-signature": "nope"}).status_code == 401
    sig = hmac.new(b"s3cret", body, hashlib.sha256).hexdigest()
    r = c.post(path, content=body, headers={"x-tijoripay-signature": sig}).json()
    assert r == {"code": "CALLBACK_MISMATCH", "passed": False}                              # our code compared
    assert m.engine.state["F"]["decision"].outcome.value == "BLOCK"
    m.engine.relay = RelayClient(url="", secret="")
    assert c.post(path, content=body, headers={"x-tijoripay-signature": sig}).status_code == 401  # no secret: refuse
    c.post("/api/reset")
