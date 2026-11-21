# DEPENDENCIES.md: packages, services, environment and sandbox data

Labels: **VERIFIED** = read in official docs or in the installed SDK source; **UNVERIFIED** = not yet confirmed.

## 1. Python

Python 3.11 (the team's `.venv`). Install: `pip install -r requirements.txt`.

### Pinned (installed in the current `.venv`)
| Package | Version | Use |
|---|---|---|
| fastapi | 0.165.0 | backend API |
| starlette | 1.10.0 | FastAPI dependency (SSE responses) |
| uvicorn | 0.54.0 | ASGI server |
| httpx | 0.28.1 | REST calls to Cashfree Payouts / Verification and Sarvam |
| pydantic | 2.14.4 | models and validation |
| python-dotenv | 1.2.4 | load `.env` |
| websockets | 17.4 | Sarvam streaming (optional) |
| sarvamai | 0.1.48 | Sarvam SDK (Vision, Saaras, Bulbul) |
| cashfree_pg | 6.0.7 | Cashfree PG SDK (orders, links, refunds, simulate, webhook signature); **does not cover Payouts or Verification** |

### To add (not installed yet; pin after installing)
| Package | Use |
|---|---|
| pytest | unit and integration tests |
| rapidfuzz | name matching |
| Pillow | synthetic invoice rendering, preprocessing variants |
| respx | mocking httpx in contract tests |

## 2. Environment variables

See `.env.example`. Never commit `.env`.

| Variable | Meaning |
|---|---|
| `SARVAM_API_KEY` | Sarvam subscription key |
| `CASHFREE_CLIENT_ID`, `CASHFREE_CLIENT_SECRET` | PG / Verification test keys |
| `CASHFREE_PAYOUT_CLIENT_ID`, `CASHFREE_PAYOUT_CLIENT_SECRET` | Payouts test keys (Payouts keys are separate from PG keys: VERIFIED) |
| `CASHFREE_ENV` | `sandbox` |
| `CASHFREE_PAYOUT_BASE_URL` | `https://sandbox.cashfree.com/payout` (or `https://payout-gamma.cashfree.com`; host conflict, see section 4) |
| `PUBLIC_BASE_URL` | ngrok or hosted URL for webhooks |

## 3. Sarvam (installed SDK `sarvamai` 0.1.48: method names VERIFIED from source)

```python
from sarvamai import SarvamAI
client = SarvamAI(api_subscription_key=os.environ["SARVAM_API_KEY"])  # constructor arg name: confirm
```

| Capability | SDK call | Notes |
|---|---|---|
| Speech to text | `client.speech_to_text.transcribe(file=..., model="saaras:v4", mode="codemix", language_code="ta-IN", keyterms=[...], with_timestamps=False, input_audio_codec=...)` | REST for audio under 30 s. Models: `saaras:v3` (default), `saaras:v4` (22 Indic languages + English). Modes: transcribe, translate, verbatim, translit, codemix. The docstring says `mode` applies only to v3 but lists modes for v4 too: **test**. `keyterms` biases recognition (vendor names). |
| Text to speech | `client.text_to_speech.convert(text=..., language_code=..., model="bulbul:v4-flash", speaker=..., pace=..., speech_sample_rate=...)` | Returns **base64** audio. v4-flash: 200+ personas `<name>_<lang>_<style>`, default `shubh_enhi_ads`; pitch/loudness not supported; pace 0.5-2.0; max 2,500 characters; **write numbers over 4 digits with commas**. |
| Document reading (Vision) | `job = client.document_intelligence.create_job(...)`, `job.upload_file(path)`, `job.start()`, `job.wait_until_complete()`, `job.download_output(path)` | Async; 20-90 s per document (UNVERIFIED); output schema and bounding boxes UNVERIFIED. |
| Streaming | `speech_to_text_streaming`, `text_to_speech_streaming` | optional for live calls |
| Not used | `chat`, `chat_completion`, `responses`, `decisions` | team rule: no Sarvam LLM |

Bulbul v4-flash languages (docs): hi, en, bn, gu, kn, mr, pa, ta, te, ml, od.

## 4. Cashfree

Auth headers for REST: `x-client-id`, `x-client-secret`, `x-api-version`. PG SDK default `XApiVersion` is `2026-01-01` (VERIFIED in the installed SDK); Payouts examples use `2024-01-01`.

### PG SDK methods available (VERIFIED in `cashfree_pg` 6.0.7)
`PGCreateOrder`, `PGFetchOrder`, `PGOrderFetchPayments`, `PGCreateLink`, `PGFetchLink`, `PGLinkFetchOrders`, `PGCancelLink`, `PGOrderCreateRefund`, `PGOrderFetchRefund(s)`, `PGSimulatePayment`, `PGFetchSimulation`, `PGSimulateSettlement`, `PGFetchSettlements`, `PGVerifyWebhookSignature(signature, rawBody, timestamp)` (base64 HMAC-SHA256 of `timestamp + rawBody` keyed with the client secret, no separator).

### REST endpoints (VERIFIED in docs unless noted)
| Area | Endpoint | Key fields |
|---|---|---|
| Bank verification | `POST https://sandbox.cashfree.com/verification/bank-account/sync` | req `bank_account`, `ifsc`, `name` (optional; name match only if sent), `phone`; resp `account_status` (VALID/INVALID), `account_status_code`, `name_at_bank`, `name_match_score`, `name_match_result` (DIRECT_MATCH, GOOD_PARTIAL_MATCH, MODERATE_PARTIAL_MATCH, POOR_PARTIAL_MATCH, NO_MATCH). 400 `invalid_request` = service not enabled. Name-match activation: UNVERIFIED |
| GSTIN | `POST /verification/gstin` | req `GSTIN`, optional `business_name`; resp `valid`, `legal_name_of_business`, `trade_name_of_business`, `gst_in_status`, `taxpayer_type` |
| Udyam | `POST /verification/udyam` | req `verification_id`, `udyam`; resp `status` SUCCESS / UDYAM_NOT_FOUND / UDYAM_IS_CANCELLED, `enterprise_name`, `enterprise_type` |
| UPI penny drop | `POST /verification/upi/penny-drop` | `x-api-version` required; duplicate `verification_id` → 409 |
| Validate payout (UPI) | `POST /payout/validatePayout` | `transfer_id` + `vpa` or `phone`; returns `name_at_bank` and single-use `transfer_token` (1 hour) |
| Beneficiary | `POST /payout/beneficiary` | `beneficiary_id` (≤ 50), `beneficiary_name`, `beneficiary_instrument_details{bank_account_number, bank_ifsc, vpa}`; only `VERIFIED` can be paid; duplicate → 409 |
| Transfer | `POST /payout/transfers` | `transfer_id` (≤ 40, alphanumeric/underscore), `transfer_amount` (≥ 1), `beneficiary_details`, `transfer_mode`; duplicate `transfer_id` → 200 with `REJECTED` / `DUPLICATE_TRANSFER`; no idempotency key documented; on 5XX check status before retrying |
| Transfer status | `GET /payout/transfers?transfer_id=` | statuses RECEIVED, APPROVAL_PENDING, VALIDATION_PENDING, PENDING, QUEUED, SUCCESS, FAILED, REJECTED, REVERSED, MANUALLY_REJECTED; final success = SUCCESS + `status_code` COMPLETED |
| Payout webhooks | (configured in dashboard) | `TRANSFER_ACKNOWLEDGED`, `TRANSFER_SUCCESS`, `TRANSFER_FAILED`, `TRANSFER_REVERSED`, `TRANSFER_REJECTED`, `LOW_BALANCE_ALERT`, `BENEFICIARY_INCIDENT`; payload `data{transfer_id, cf_transfer_id, status, status_code, transfer_amount, transfer_utr, ...}`; deliveries stop after > 5 failures |

**Host conflict (VERIFIED as a conflict):** most Payouts v2 pages give `https://sandbox.cashfree.com/payout`; Getting Started gives `https://payout-gamma.cashfree.com` for v1/v1.2; Validate Payout v2 pages list both. Use whichever our credentials work with. UNVERIFIED: how to fund the sandbox Payouts balance; whether reversal webhooks fire.

## 5. Sandbox test data (VERIFIED in docs; confirm on the day)

### Bank account verification (score depends on the name you send)
| Account | Holder | 100 DIRECT | 85 GOOD | 70 MODERATE | 38 POOR |
|---|---|---|---|---|---|
| 026291800001191 | JOHN DOE | "john doe" | "john d" | "j doe" | "jane d" |
| 1233943142 | TOM WELLS | "tom wells" | "tom w" | "t wells" | "tim lee" |
| 388108022658 | BOB HOPE | "bob hope" | "bob h" | "b hope" | "bane hue" |

IFSC pairing (from the Payouts page): 026291800001191 with YESB0000262; the other two with ICIC0000009. No row gives NO_MATCH or an invalid account.

### Payouts transfers
| Account / IFSC | Result |
|---|---|
| 000100289877623 / SBIN0008752 | Success (Payouts page) but "failed at bank" (Verification page): conflict |
| 2640101002729 / CNRR0002640; 1234567890 / ICIC0000001 | Invalid IFSC |
| 026291800001190 / YESB0000262; 234005000876 / ICIC0000007 | Invalid account |
| 007711000031 / HDFC0000077 | Pending |
| 00224412311300 / YESB0000001 | Pending, then success |
| 7766666351000 / YESB0000001 | Pending, then failure |
| 7766671735000 / SBIN0000004 | Success, then reversed |
| 02014457596969 / CITI0000001 | Success, then reversed |
| 34978321547298 / KKBK0000001 | Timeout 25 s, then success |
| VPAs success@upi / failure@upi | UPI success / failure |

Test OTP 111000. Some transfer modes need enabling via the Support Form.

### GSTIN, Udyam, PAN
- Valid GSTINs: 29AAICP2912R1ZR, 27ABCFGH5678D1Z, 36JKLPQR9012E2Y, 45XYZLMN2345G3W, 12PQRST6789A4BC, 39ABCDE0987F6GH, 23UVWXYZ5678H5D, 05BBICP2912R1ZR. Invalid: 29AAIZP2912R1ZR, 05BBICA2912R1ZR. (Several "valid" ones would fail a real checksum: do not hard-block on checksum.)
- Udyam: UDYAM-UP-43-1234567 success; UDYAM-MH-43-1234567 not found; UDYAM-KA-43-1234567 cancelled.
- PAN (for reference): valid ABCPV1234D, XYZPP4321W, AZJPG7110R; invalid DEFPV0126D, TUVPP5678W.

### PG (fallback and seeding)
- UPI collect `testsuccess@gocash` (success), `testfailure@gocash` (failure); test card 4111 1111 1111 1111, expiry 03/2028, CVV 123, OTP 111000 (confirm on the test-data page).
- `PGSimulatePayment` takes `entity` PAYMENTS / SUBS_PAYMENTS / VBA_TRANSFER with the `cf_payment_id`; payment-link support UNVERIFIED.

## 6. Tools

| Tool | State on Krish's machine | Notes |
|---|---|---|
| Git + Credential Manager | installed; identity set | first push opens a browser sign-in |
| ngrok 3.3.1 | installed; **authtoken not set** | `ngrok config add-authtoken <token>`; consider `ngrok update` |
| GitHub CLI (`gh`) | not installed | optional |
| Postman | optional | for Relay sample events |
| Cashfree dashboard | merchant.cashfree.com, Switch to Test | Relay under PG products |
