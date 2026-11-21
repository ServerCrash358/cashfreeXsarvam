"""Pre-demo check: drives EVERY path of the running app (live Sarvam + live Secure ID, simulated payouts)
and prints PASS/FAIL per step. Run before the demo:

    .venv/Scripts/python scripts/demo_check.py                 # app on http://localhost:8000
    .venv/Scripts/python scripts/demo_check.py --relay 8001    # also: Relay end to end against a 2nd app on :8001
                                                              #   started with RELAY_WEBHOOK_URL=http://127.0.0.1:8099/hook

Never prints keys or full account numbers. Costs a few Sarvam calls (TTS, STT, one Vision read).
"""
from __future__ import annotations

import argparse
import hashlib
import hmac
import importlib.util
import json
import subprocess
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
RESULTS: list[tuple[str, bool, str]] = []
EXPECTED = {"A": "PAY", "B": "PAY", "C": "PAY", "D": "BLOCK", "E": "BLOCK", "F": "ASK", "G": "BLOCK", "H": "PAY"}
FULL_ACCOUNTS = ["34978321547298", "000100289877623", "00224412311300", "007711000031", "02014457596969",
                 "026291800001191", "1233943142", "7766671735000"]


def check(name: str, ok: bool, detail: str = ""):
    RESULTS.append((name, bool(ok), detail))
    print(f"{'PASS' if ok else 'FAIL'}  {name}" + (f"  -- {detail}" if detail else ""), flush=True)


class App:
    def __init__(self, base):
        self.c = httpx.Client(base_url=base, timeout=180)

    def get(self, p, **kw):
        return self.c.get(p, **kw)

    def post(self, p, **kw):
        return self.c.post(p, **kw)

    def state(self, lang="en"):
        return self.get(f"/api/state?lang={lang}").json()

    def inv(self, iid, lang="en"):
        return next(i for i in self.state(lang)["invoices"] if i["id"] == iid)

    def reset(self):
        assert self.post("/api/reset").status_code == 200

    def plan(self, cash="30000", lang="en"):
        return self.post("/api/plan", json={"cash": cash, "lang": lang}).json()

    def approve(self, bid, transcript=None, channel="voice", lang="en", audio=None):
        if audio is not None:
            return self.post(f"/api/bundles/{bid}/approve", data={"channel": channel, "lang": lang},
                             files={"audio": ("a.wav", audio, "audio/wav")}).json()
        return self.post(f"/api/bundles/{bid}/approve", data={"transcript": transcript, "channel": channel,
                                                               "lang": lang}).json()

    def pin(self, bid, pin):
        return self.post(f"/api/bundles/{bid}/pin", json={"pin": pin}).json()

    def tts(self, text, lang):
        r = self.post("/api/tts", json={"text": text, "lang": lang})
        return r.content if r.status_code == 200 else None


def fresh_invoice_image() -> Path:
    """Render a NEW (never cached) invoice image: E with a different number, so Vision runs live."""
    spec = importlib.util.spec_from_file_location("mki", ROOT / "scripts" / "make_invoice_images.py")
    mki = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mki)
    batch = json.loads((ROOT / "data" / "fixtures" / "demo_batch.json").read_text(encoding="utf-8"))
    buyer = json.loads((ROOT / "data" / "fixtures" / "vendors.json").read_text(encoding="utf-8"))["buyer"]
    e = dict(next(r for r in batch["invoices"] if r["id"] == "E"))
    e["invoice_no"] = f"AS/{int(time.time()) % 100000}/2026-27"
    tmp = Path(tempfile.mkdtemp(prefix="tp_check_"))
    html = tmp / "fresh.html"
    html.write_text(mki.page(e, buyer), encoding="utf-8")
    png = tmp / "fresh_E.png"
    subprocess.run([mki.EDGE, "--headless", "--disable-gpu", "--hide-scrollbars", f"--screenshot={png}",
                    "--window-size=820,900", html.resolve().as_uri()], check=True, capture_output=True, timeout=60)
    return png


def run_main(app: App):
    # ---------------------------------------------------------------- boot
    r = app.get("/")
    check("UI page served", r.status_code == 200 and "TijoriPay" in r.text)
    app.reset()
    s = app.state("hi")
    got = {i["id"]: i["outcome"] for i in s["invoices"]}
    check("Demo batch outcomes A-H", got == EXPECTED, str(got))
    check("Secure ID live (no fallback)", not s["verification_last_error"], s["verification_last_error"] or "live")
    check("Payout mode is sim", s["payout_mode"] == "sim", s["payout_mode"])
    sb = s["scoreboard"]
    check("Scoreboard at load", len(sb["traps_blocked"]) == 3 and sb["traps_held_ask"] == ["F"]
          and len(sb["clean_auto_paid"]) == 4 and not sb["clean_false_blocks"], json.dumps(sb)[:160])

    # ------------------------------------------------------------ languages
    for lang, probe in (("hi", "रोका"), ("ta", "நிறுத்"), ("en", "Blocked")):
        e = app.inv("E", lang)
        check(f"Reasons in {lang} (E)", any(probe in x["text"] for x in e["reasons"]), e["reasons"][0]["text"][:70])
    g = app.inv("G", "en")
    nm = [x for x in g["reasons"] if x["code"] == "NAME_MISMATCH"]
    check("G blocked: bank-registered name isn't the vendor", bool(nm) and nm[0]["severity"] == "block",
          nm[0]["text"][:90] if nm else "")
    check("Account last four shown as written (no comma)", "xx3142" in json.dumps(g["reasons"]), "")
    d = app.inv("D", "en")
    check("D reason cites the paid original", any("KE/0312" in x["text"] for x in d["reasons"]))

    # ------------------------------------------------------------ Bulbul TTS (live)
    for lang, text in (("hi", "दो बिल, कुल 22,000 रुपये।"), ("ta", "இரண்டு பில்கள், மொத்தம் 22,000 ரூபாய்."),
                       ("en", "Two bills, total 22,000 rupees.")):
        a = app.tts(text, lang)
        check(f"Bulbul TTS {lang}", a is not None and len(a) > 10000, f"{len(a) if a else 0} bytes")

    # ------------------------------------------------------------ F call-back by VOICE (live Saaras) -> mismatch
    cb = app.post("/api/invoices/F/callback").json()
    check("Call-back uses master phone, ignores invoice phone",
          cb.get("phone_used", "").endswith("1234") and cb.get("invoice_phone_ignored", "").endswith("9876"))
    wav = app.tts("The last four digits are seven seven two three", "en")
    r = app.post(f"/api/callbacks/{cb['id']}/result", files={"audio": ("reply.wav", wav, "audio/wav")}).json()
    check("Vendor reply heard by Saaras -> CALLBACK_MISMATCH", r.get("code") == "CALLBACK_MISMATCH"
          and r.get("evidence", {}).get("spoken_last4") == "7723", json.dumps(r.get("evidence", {}))[:120])
    check("F now BLOCK", app.inv("F")["outcome"] == "BLOCK")
    r2 = app.post("/api/invoices/F/callback")
    check("Mismatch is final (no re-call)", r2.status_code in (400, 409), str(r2.status_code))
    r3 = app.post(f"/api/callbacks/{cb['id']}/result", data={"transcript": "one one nine one"})
    check("Same call can't be answered twice", r3.status_code == 409, str(r3.status_code))
    s = app.state()
    check("Scoreboard after call-back: 4/4 blocked", len(s["scoreboard"]["traps_blocked"]) == 4)

    # ------------------------------------------------------------ F genuine change: match -> owner PIN -> KNOWN
    app.reset()
    cb = app.post("/api/invoices/F/callback").json()
    r = app.post(f"/api/callbacks/{cb['id']}/result", data={"transcript": "one one nine one"}).json()
    check("Matching digits pass the call-back", r.get("passed") is True)
    check("Still ASK until owner approves", app.inv("F")["outcome"] == "ASK")
    check("Account change refused with wrong PIN",
          app.post("/api/invoices/F/approve-account", json={"pin": "0000"}).json().get("ok") is False)
    check("Account change approved with PIN",
          app.post("/api/invoices/F/approve-account", json={"pin": "2468"}).json().get("ok") is True)
    f = app.inv("F")
    check("F becomes KNOWN + PAY", f["lane"] == "KNOWN" and f["outcome"] == "PAY", f"{f['lane']} {f['outcome']}")

    # ------------------------------------------------------------ upload: cached rescan, fresh live Vision, junk
    app.reset()
    r = app.post("/api/upload", files=[("files", ("inv_B_hi.png", (ROOT / "data/demo/inv_B_hi.png").read_bytes(),
                                                  "image/png"))]).json()["results"][0]
    check("Upload rescan of B -> BLOCK DUP_EXACT", r.get("outcome") == "BLOCK" and "DUP_EXACT" in r.get("codes", []),
          json.dumps(r)[:120])
    try:
        png = fresh_invoice_image()
        t = time.time()
        r = app.post("/api/upload", files=[("files", (png.name, png.read_bytes(), "image/png"))]).json()["results"][0]
        check("Fresh image -> LIVE Sarvam Vision -> ARITH_TOTAL", "ARITH_TOTAL" in r.get("codes", []),
              f"{time.time() - t:.0f}s {json.dumps(r)[:120]}")
    except Exception as ex:  # Edge or Vision unavailable
        check("Fresh image -> LIVE Sarvam Vision", False, f"{type(ex).__name__}: {ex}")
    r = app.post("/api/upload", files=[("files", ("junk.png", b"not an image", "image/png"))])
    check("Junk upload handled (no crash)", r.status_code == 200 and "error" in r.json()["results"][0],
          json.dumps(r.json())[:120])
    check("App still healthy after uploads", app.get("/api/state").status_code == 200)

    # ------------------------------------------------------------ planner
    app.reset()
    p = app.plan("30000")
    check("Plan ₹30,000 -> H+B, 22,000 vs naive 16,400", p["chosen"] == ["H", "B"] and p["protected"] == "22000.00"
          and p["naive_protected"] == "16400.00", f"{p['chosen']} {p['protected']} {p['naive_protected']}")
    p0 = app.plan("0")
    check("Plan ₹0 -> nothing paid", p0["chosen"] == [], str(p0["chosen"]))
    p2 = app.plan("100000")
    check("Plan ₹1,00,000 -> all 4 clean", sorted(p2["chosen"]) == ["A", "B", "C", "H"], str(p2["chosen"]))

    # ------------------------------------------------------------ approval: refusals
    p = app.plan("30000", "hi")
    bid, code = p["bundle"]["id"], p["bundle"]["code"]
    check("Hindi read-back prompt", "22,000" in p["bundle"]["prompt"] and "बिल" in p["bundle"]["prompt"])
    check("PIN before confirmation refused", app.pin(bid, "2468").get("ok") is False)
    wrong = f"{(int(code) + 1) % 1000:03d}"
    check("Wrong typed code refused", app.approve(bid, wrong, "typed").get("ok") is False)
    check("'haan' without code/total refused", app.approve(bid, "haan kar do").get("ok") is False)
    check("Ambiguous 'haan... nahi' refused", app.approve(bid, f"haan nahi 2 bill 22000 code {code}").get("ok") is False)
    check("Execute before approval refused", app.post(f"/api/bundles/{bid}/execute").status_code == 400)

    # PIN lockout on a separate bundle
    pl = app.plan("30000")
    app.approve(pl["bundle"]["id"], pl["bundle"]["code"], "typed")
    for _ in range(3):
        app.pin(pl["bundle"]["id"], "1111")
    check("3 wrong PINs lock the bundle", app.pin(pl["bundle"]["id"], "2468").get("ok") is False)

    # ------------------------------------------------------------ approval by VOICE (live Saaras, Hindi)
    p = app.plan("30000", "hi")
    bid, code = p["bundle"]["id"], p["bundle"]["code"]
    digits = {"0": "शून्य", "1": "एक", "2": "दो", "3": "तीन", "4": "चार", "5": "पाँच", "6": "छह", "7": "सात", "8": "आठ", "9": "नौ"}
    spoken = f"हाँ, दो बिल, बाईस हज़ार रुपये, कोड {' '.join(digits[c] for c in code)}"
    wav = app.tts(spoken, "hi")
    r = app.approve(bid, channel="voice", lang="hi", audio=wav)
    check("Spoken Hindi approval (Bulbul -> Saaras) accepted", r.get("ok") is True,
          f"heard: {r.get('transcript')!r} reasons={r.get('reasons')}")
    if not r.get("ok"):                                       # fall back so the rest of the run continues
        app.approve(bid, f"haan 2 bill 22000 code {code}")
    check("PIN confirms", app.pin(bid, "2468").get("ok") is True)

    # ------------------------------------------------------------ pay, reconcile, single use
    ex = app.post(f"/api/bundles/{bid}/execute")
    check("Pay executes 2 transfers", ex.status_code == 200 and len(ex.json()["results"]) == 2)
    check("Bundle is single use", app.post(f"/api/bundles/{bid}/execute").status_code == 400)
    for _ in range(3):
        app.post("/api/sweep")
    s = app.state()
    paid = {i["id"]: (i["payment"], i["payouts"][0]["state"]) for i in s["invoices"] if i["payouts"]}
    check("B and H paid (SUCCESS)", paid.get("B") == ("paid", "SUCCESS") and paid.get("H") == ("paid", "SUCCESS"),
          str(paid))
    h = next(i for i in s["invoices"] if i["id"] == "H")
    tid = h["payouts"][0]["transfer_id"]
    check("Transfer ID deterministic format", tid.startswith("pn_") and len(tid) == 35, tid)
    check("Payout lookup endpoint", app.get(f"/api/payouts/{tid}").json().get("state") == "SUCCESS")

    # ------------------------------------------------------------ reversal + webhooks
    r = app.post("/api/simulate/webhook", json={"transfer_id": tid, "status": "REVERSED"}).json()
    check("Simulated reversal applied", r.get("state") == "REVERSED" and r.get("simulated") is True)
    h = app.inv("H")
    check("H reopened as ASK, explains the reversal", h["payment"] == "reversed" and h["outcome"] == "ASK"
          and h["reasons"][0]["code"] == "PAYOUT_REVERSED")
    check("H not repaid (one transfer)", len(h["payouts"]) == 1)
    p = app.plan("30000")
    check("Reversed bill not re-planned automatically", "H" not in p["chosen"], str(p["chosen"]))
    r = app.post("/webhooks/cashfree/payouts", content=b'{"data":{"transfer_id":"x"}}',
                 headers={"x-webhook-signature": "forged", "x-webhook-timestamp": "1"})
    check("Forged Cashfree webhook rejected (401)", r.status_code == 401, str(r.status_code))

    # ------------------------------------------------------------ audit + privacy
    a = app.get("/api/audit").json()
    check("Audit hash chain intact", a["chain_ok"] is True, f"{len(a['entries'])} entries")
    blob = json.dumps(a) + json.dumps(app.state()) + json.dumps(app.get("/api/relay").json())
    check("No full account number in audit/state/relay", not any(n in blob for n in FULL_ACCOUNTS))
    acts = {e["action"] for e in a["entries"]}
    check("Audit covers decision/plan/approval/payout/webhook",
          {"decision", "plan", "approval_voice", "approval_pin", "payout_intent", "webhook"} <= acts,
          ", ".join(sorted(acts))[:160])
    app.reset()


# ---------------------------------------------------------------- Relay end to end (stand-in receiver)
def run_relay(port: int, secret: str):
    got: list[dict] = []

    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            raw = self.rfile.read(int(self.headers.get("content-length", 0)))
            sig_ok = hmac.compare_digest(hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest(),
                                         self.headers.get("x-tijoripay-signature", ""))
            got.append({"body": json.loads(raw), "sig_ok": sig_ok})
            self.send_response(200); self.end_headers(); self.wfile.write(b"{}")

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 8099), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    app = App(f"http://127.0.0.1:{port}")
    try:
        check("Relay: app reports enabled", app.get("/api/relay").json().get("enabled") is True)
        app.reset(); time.sleep(1)
        check("Relay: batch_ready received + signed", any(g["body"]["event"] == "batch_ready" and g["sig_ok"] for g in got))
        cb = app.post("/api/invoices/F/callback").json(); time.sleep(1)
        req = [g for g in got if g["body"]["event"] == "callback_requested"]
        check("Relay: callback_requested received + signed", bool(req) and req[-1]["sig_ok"])
        if req:
            b = req[-1]["body"]
            check("Relay: payload has master phone, prompt, result path; no invoice phone/account",
                  b["phone"].endswith("1234") and b["prompt"] and b["result_path"].endswith("/result")
                  and "9123409876" not in json.dumps(b) and "026291800001191" not in json.dumps(b)
                  and "\"1191\"" not in json.dumps(b))
        body = json.dumps({"transcript": "seven seven two three"}).encode()
        path = f"/api/relay/callbacks/{cb['id']}/result"
        check("Relay -> us unsigned rejected", app.post(path, content=body).status_code == 401)
        sig = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        r = app.post(path, content=body, headers={"x-tijoripay-signature": sig}).json()
        check("Relay -> us signed transcript -> our code decides MISMATCH", r.get("code") == "CALLBACK_MISMATCH")
        time.sleep(1)
        check("Relay: bill_blocked received for F", any(g["body"]["event"] == "bill_blocked"
                                                        and g["body"].get("invoice_id") == "F" for g in got))
        p = app.plan("4000")
        app.approve(p["bundle"]["id"], p["bundle"]["code"], "typed"); app.pin(p["bundle"]["id"], "2468")
        app.post(f"/api/bundles/{p['bundle']['id']}/execute")
        for _ in range(3):
            app.post("/api/sweep")
        time.sleep(1)
        check("Relay: payout_success received", any(g["body"]["event"] == "payout_success" for g in got))
        app.reset()
    finally:
        srv.shutdown()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--relay", type=int, default=0, help="port of a 2nd app started with RELAY_WEBHOOK_URL=http://127.0.0.1:8099/hook")
    ap.add_argument("--relay-secret", default="demo-check-secret")
    ap.add_argument("--skip-main", action="store_true")
    a = ap.parse_args()
    if not a.skip_main:
        run_main(App(a.base))
    if a.relay:
        run_relay(a.relay, a.relay_secret)
    bad = [r for r in RESULTS if not r[1]]
    print(f"\n{len(RESULTS) - len(bad)}/{len(RESULTS)} passed")
    sys.exit(1 if bad else 0)
