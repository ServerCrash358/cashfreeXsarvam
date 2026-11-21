"""The gate (docs/PLAN.md section 0; INTEGRATION_TESTS IT-CF-PAYOUT P1-P3, P12).

Proves the payout pipe works end to end against the Cashfree SANDBOX:
  1. the keys authenticate on the configured host,
  2. a beneficiary can be added,
  3. a Rs 1 transfer can be sent,
  4. its status can be read until it is final.

Run from the repo root with the venv active:
  python scripts/smoke_payout.py                      # Rs 1 to the docs' success test account
  python scripts/smoke_payout.py --status pn_smoke_...   # only re-read an earlier transfer (no new POST)

It never re-POSTs a transfer: a timeout is UNKNOWN and is resolved by polling, exactly like the app.
Webhooks for this transfer arrive at the running app (POST /webhooks/cashfree/payouts) if PUBLIC_BASE_URL is
registered in the dashboard; the app verifies the signature and logs it as webhook_unmatched (W1/W2 evidence).
"""
from __future__ import annotations

import argparse
import sys
import time
from datetime import datetime
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(ROOT / ".env")

from panch.cashfree import CashfreeUnavailable, NotSandbox, PayoutsClient, mask  # noqa: E402
from panch.payouts import CF_TO_STATE, Attempt, apply_event  # noqa: E402
from panch.vendors import account_hash  # noqa: E402

HINTS = {
    "ERROR_SELECTING_FUND_SOURCE": "The sandbox has no funded balance. Dashboard (Test mode) -> Payouts -> "
                                   "Fund Sources, add/fund one (or ask the Cashfree desk), then run again.",
    "INSUFFICIENT_BALANCE": "Sandbox balance too low. Fund it under Payouts -> Fund Sources.",
}


def say(msg: str):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


def poll(client: PayoutsClient, att: Attempt, polls: int, wait: float) -> Attempt:
    for i in range(polls):
        try:
            code, body = client.get_status(att.transfer_id)
        except TimeoutError as e:
            say(f"status poll {i + 1}: timeout ({e}); still {att.state}")
        else:
            status, sc = body.get("status"), body.get("status_code")
            say(f"status poll {i + 1}: HTTP {code} status={status} status_code={sc} "
                f"cf_transfer_id={body.get('cf_transfer_id')} utr={body.get('transfer_utr')}")
            if status in CF_TO_STATE:
                apply_event(att, CF_TO_STATE[status], sc, source="smoke poll")
            elif code == 404:
                say("  not found yet (normal right after a timeout); keep polling, never re-POST")
            if att.state in ("SUCCESS", "FAILED", "REJECTED", "REVERSED"):
                hint = HINTS.get(sc or "")
                if hint:
                    say("  HINT: " + hint)
                return att
        if i < polls - 1:
            time.sleep(wait * (1.5 ** i))
    return att


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--account", default="000100289877623", help="payee account (sandbox success account)")
    ap.add_argument("--ifsc", default="SBIN0008752")
    ap.add_argument("--name", default="Panch Smoke Test")
    ap.add_argument("--amount", default="1")
    ap.add_argument("--base", default=None, help="override CASHFREE_PAYOUT_BASE_URL (e.g. https://payout-gamma.cashfree.com)")
    ap.add_argument("--polls", type=int, default=6)
    ap.add_argument("--wait", type=float, default=3.0, help="seconds before the first re-poll (backs off x1.5)")
    ap.add_argument("--status", metavar="TRANSFER_ID", help="only poll this existing transfer; no new POST")
    a = ap.parse_args()

    try:
        client = PayoutsClient(a.base)
    except NotSandbox as e:
        say(f"REFUSED: {e}")
        return 1
    say(f"host {client.base}  client id {'set' if client.cid else 'MISSING'}  secret {'set' if client.sec else 'MISSING'}")
    if not (client.cid and client.sec):
        say("Fill CASHFREE_PAYOUT_CLIENT_ID/_SECRET (or CASHFREE_CLIENT_ID/_SECRET) in .env first.")
        return 1

    if a.status:
        att = Attempt(a.status, "smoke", "smoke", "-", Decimal("0"), state="UNKNOWN")
        att = poll(client, att, a.polls, a.wait)
        say(f"RESULT {att.transfer_id}: {att.state} {att.status_code or ''}")
        return 0 if att.state == "SUCCESS" else 2

    amount = Decimal(a.amount)
    ben_id = "pn_smoke_" + account_hash(a.account, a.ifsc)[:12]
    try:
        code, body = client.create_beneficiary(ben_id, a.name, a.account, a.ifsc)
    except CashfreeUnavailable as e:
        say(f"AUTH FAILED: {e}")
        say("  HINT: whitelist this machine's IP in the dashboard (Payouts -> Developers -> IP whitelisting), "
            "check the keys, or try --base https://payout-gamma.cashfree.com")
        return 1
    except TimeoutError as e:
        say(f"beneficiary call timed out ({e}); run again (adding a beneficiary is idempotent)")
        return 1
    say(f"beneficiary {ben_id} -> acct {mask(a.account)} / {a.ifsc}: HTTP {code} "
        f"status={body.get('beneficiary_status')} code={body.get('code')} {(body.get('message') or '')[:100]}")
    if code not in (200, 201, 409):
        say("beneficiary not created; fix the error above before sending money")
        return 1

    tid = f"pn_smoke_{datetime.now():%Y%m%d%H%M%S}"
    att = Attempt(tid, "smoke", "smoke", ben_id, amount)
    say(f"INTENT {tid} Rs {amount} (recorded before the call)")
    apply_event(att, "SENT", source="smoke")
    try:
        code, body = client.transfer(tid, amount, ben_id, remarks="Panch smoke test")
        say(f"transfer POST: HTTP {code} status={body.get('status')} status_code={body.get('status_code')} "
            f"cf_transfer_id={body.get('cf_transfer_id')} {(body.get('message') or '')[:100]}")
        if body.get("status") in CF_TO_STATE:
            apply_event(att, CF_TO_STATE[body["status"]], body.get("status_code"), source="smoke post")
        elif 400 <= code < 500:
            apply_event(att, "FAILED", body.get("code"), source="smoke post")
    except TimeoutError as e:
        apply_event(att, "UNKNOWN", source=f"smoke post {e}")
        say(f"transfer POST timed out ({e}): state UNKNOWN. Polling; NOT re-sending.")

    if att.state not in ("FAILED", "REJECTED"):
        att = poll(client, att, a.polls, a.wait)
    elif HINTS.get(att.status_code or ""):
        say("  HINT: " + HINTS[att.status_code])

    say(f"RESULT {tid}: {att.state} {att.status_code or ''}")
    if att.state in ("PENDING", "UNKNOWN", "SENT"):
        say(f"  not final yet; re-check later with: python scripts/smoke_payout.py --status {tid}")
        return 2
    return 0 if att.state == "SUCCESS" else 1


if __name__ == "__main__":
    sys.exit(main())
