# PR 4: voice, approval, call-back, UI: what landed and how it plugs in

Nothing here has been run yet. Run `pytest tests/unit -q` (needs `pytest`) and `uvicorn app.main:app --port 8000` to check.

## Files

| Path | What |
|---|---|
| `panch/voice/numbers.py` | Pure transcript parsing: Tamil/Devanagari digits, spoken digits (en/hi/ta, script + romanised), counts, "22 hazaar", yes/no/ambiguous |
| `panch/voice/templates.py` | `render(key, lang, **vars)`, `format_inr` (Indian commas), never falls back to English |
| `panch/voice/client.py` | Bulbul `speak` and Saaras `transcribe` wrappers (sarvamai). No chat model |
| `templates/{en,hi,ta}/messages.json` | All reason-code and flow messages. **Hindi and Tamil need a native check** |
| `panch/approval/__init__.py` | `make_bundle`, `check_approval`, `assert_executable`, `ApprovalStore` (bundle hash + nonce + 3-digit code, TTL 2 min, single use) |
| `panch/vendors/callback.py` | `start_callback` (vendor-master phone only), `finish_callback` → `CheckResult` |
| `app/main.py`, `app/events.py`, `app/static/index.html` | FastAPI routes, SSE, owner dashboard (language switch, reasons with 🔊, plan, voice/typed approval, call-back panel, live feed) |
| `app/demo_fixture.json` | UI placeholder batch mirroring PLAN.md section 4 until the pipeline is wired |
| `tests/unit/test_approval.py`, `test_voice.py`, `test_callback.py` | U-APR-1..9, U-VEN-9..11, U-DEC-6 (templates) |

## v3 changes (after the BUILD_PROMPT / ARCHITECTURE v3 pull)

- **Voice never authorises alone.** Approval is now two steps: (1) spoken or typed *confirmation* (`ApprovalStore.confirm`, `POST /api/bundles/{id}/approve`), then (2) a **PIN tap bound to the shown `bundle_hash`** (`ApprovalStore.tap_pin`, `POST /api/bundles/{id}/pin`). Only the resulting `Authorisation` passes `assert_executable`. Three wrong PINs lock the bundle.
- **Second approver (stretch, U-APR-11):** required when any item has `changed_account=True` or the total exceeds `PANCH_SECOND_APPROVER_ABOVE`.
- **PINs:** `PANCH_APPROVERS="owner:<salt>:<pbkdf2hex>,partner:<salt>:<hex>"`, generated with `panch.approval.make_approver(id, pin)`. Dev mode falls back to owner 1234 / partner 5678 (badge shows "DEV PINs"). Never use those in the demo.
- New templates: `dup_number`, `arith_gst_split`, `new_vendor`, `approval_pin`, `approval_second`, `approval_authorised`, `payment_readback`.
- Call-back reads the v3 field `vendor_phone_on_invoice` (recorded, never dialled) and records transcript, transcript hash, audio hash and phone used.
- Tests added: U-APR-10, U-APR-11, PIN binding, lockout, expiry.

## Contracts other PRs should know

- **Message keys** are lower-cased reason codes (`ARITH_TOTAL` → `arith_total`). PR 2: set `CheckResult.message_key` that way. Templates exist for every code in ARCHITECTURE section 5.
- **PR 3 (payouts):** expose `panch.payouts.execute_bundle(bundle, authorisation)` (an `Authorisation`, not a voice confirmation). Call `panch.approval.assert_executable(bundle, authorisation)` first (the route already does). On webhook/poll updates call `app.events.publish("payout", invoice_id=..., state="SUCCESS|FAILED|REVERSED|PENDING", message_key="payout_success|payout_failed|payout_reversed|payout_pending", vars={"vendor": name, "amount": "4000"})`.
- **Bundle items** carry `account_change_pending=True` for any `ACCOUNT_CHANGED` invoice until the owner approves the change after a matching call-back (`POST /api/callbacks/{id}/owner`). `make_bundle` refuses such items.
- **Krish (planner, audit, batches):** `GET /api/batches/{id}` reads `app/demo_fixture.json` today; swap in real decisions + `plan()` output with the same shape (`invoices[]`, `plan.bundle`, `plan.deferred`, `plan.regret`). `panch.audit.append(action, payload)` is called for bundle creation, approval, call-back and account-change decisions if the module exists.
- `CheckResult` is imported from `panch.models` (PR 2). `callback.py` has a temporary identical fallback until PR 2 lands. Delete it then.

## Endpoints

`GET /` UI · `GET /api/health` · `GET /api/events` (SSE) · `GET /api/batches/demo?lang=ta` · `POST /api/speak` · `POST /api/bundles` · `POST /api/bundles/{id}/approve` (voice: `audio_b64` WAV; typed: `code`; dev: `transcript`) · `POST /api/bundles/{id}/execute` · `POST /api/callbacks` · `POST /api/callbacks/{id}/result` · `POST /api/callbacks/{id}/owner` · `POST /api/dev/payout-event` (dev only, `PANCH_DEV=1`, default on; **set `PANCH_DEV=0` for the demo** so typed transcripts are refused).

## UNVERIFIED (check with IT-SARVAM)

- `text_to_speech.convert(language_code=...)` keyword and the `audios` response field; `speech_to_text.transcribe(mode="codemix")` with `saaras:v4`; the `transcript` response field.
- Bulbul v4-flash persona names per language: set `PANCH_TTS_SPEAKER_TA/HI/EN` once known.
- The browser records 16 kHz mono WAV, so Saaras gets a plain format.

## Honest limits (for the design note)

- No speaker verification: a cloned voice that hears the code live could approve.
- The 3-digit code proves the approval is for this exact bundle and is fresh. It is not a secret from the owner.
- The vendor's phone on file could itself be compromised.
