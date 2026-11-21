# Cashfree Relay in TijoriPay

Relay is Cashfree's hosted agent canvas: triggers, HTTP actions, secret properties and Sarvam voice actions. TijoriPay keeps every decision in its own deterministic code. Relay is the **orchestration and voice layer around it**: it can place the vendor call-back and send alerts. It never compares, decides or pays.

The code is in [panch/relay/\_\_init\_\_.py](../panch/relay/__init__.py) and the tests in [tests/unit/test_relay.py](../tests/unit/test_relay.py). It's **off unless `RELAY_WEBHOOK_URL` is set**, and the app works the same without it.

## How it connects

```
TijoriPay ──(POST, inbound-webhook trigger)──▶ Relay agent "TijoriPay"
   events: batch_ready · callback_requested · bill_blocked · payout_success · payout_reversed
   header: x-tijoripay-signature = hex HMAC-SHA256(RELAY_SHARED_SECRET, raw body)

Relay agent ──(HTTP action)──▶ TijoriPay  POST /api/relay/callbacks/{callback_id}/result   {"transcript": "..."}
   same signature header; without a valid signature: 401
   (needs TijoriPay on a public URL; on the single-laptop demo the answer is entered in the UI instead)
```

| Event | Sent when | Payload (no secrets; accounts never included) |
|---|---|---|
| `batch_ready` | The batch is loaded or reset | bill count, outcome counts, owner language |
| `callback_requested` | The owner clicks **Call vendor on the number on file** | invoice and call-back IDs, the **vendor-master phone** (Relay has to dial it), the vendor's language, the **exact template prompt** to speak, and `result_path` |
| `bill_blocked` | A bill turns BLOCK after load (for example F after a mismatched call-back) | invoice, vendor, amount, reason codes |
| `payout_success` / `payout_reversed` | A transfer is confirmed, or comes back | invoice, vendor, amount, `transfer_id`, `simulated` flag |

Relay never receives the expected digits, any account number, or the phone printed on the invoice.

## Building the agent on the Relay canvas

Do this in the Payment Gateway dashboard → Relay. Names on the canvas may differ slightly.

1. **New agent**, named "TijoriPay".
2. **Trigger: Inbound webhook.** Copy its URL into `.env` as `RELAY_WEBHOOK_URL`.
3. **Secret property:** `TIJORIPAY_SECRET`. Choose a random value and put the same value in `.env` as `RELAY_SHARED_SECRET`.
4. **Branch on `event`:**
   - **`callback_requested`:**
     1. A Sarvam voice-call or TTS action dials `phone`, speaks `prompt` in `language`, and records the reply. Use a teammate's phone as the vendor in the demo. Voice minutes are limited, about 240 in total.
     2. Sarvam STT, in the same `language`, turns the reply into text.
     3. An **HTTP action** posts `{"transcript": <text>}` to `<PUBLIC_BASE_URL><result_path>`, with the header `x-tijoripay-signature` = HMAC-SHA256(`TIJORIPAY_SECRET`, body). If the canvas can't compute an HMAC, put a small AWS Lambda step in between.
   - **`bill_blocked`, `payout_success`, `payout_reversed`:** a notification action, for example a message to the owner using the `vendor` and `amount` fields.
5. Turn the agent on. Restart TijoriPay, then check `GET /api/relay`: it should show `enabled: true` and your events with `ok: true`.

## On the demo laptop

- **Works without a public URL:** TijoriPay → Relay. The triggers fire, and Relay can place the call and send alerts.
- **Needs a public URL:** Relay → TijoriPay. Until there is one, type the vendor's answer into the call-back panel.
- **If Relay is down or slow:** each trigger runs in the background with a 5-second timeout, and a failure is just recorded.

UNVERIFIED until it's built on the canvas: the exact payload format Relay's inbound-webhook trigger expects (we send flat JSON with an `event` field), and whether the canvas can compute an HMAC itself.
