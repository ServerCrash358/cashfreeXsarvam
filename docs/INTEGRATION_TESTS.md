# INTEGRATION_TESTS.md: Cashfree test environment, Relay, Sarvam SDK and communication suites

These suites call real services (Cashfree test mode, Relay, Sarvam). **They are not run in CI and were not run when this doc was written.** Run them deliberately, record the result in the Status column (date, pass/fail, notes), and update the docs if a fact changes. Expected results come from the docs and the installed SDKs; anything marked UNVERIFIED is the point of the test.

Layout: `tests/integration/test_<suite>.py`, marked `@pytest.mark.integration`, skipped unless `RUN_INTEGRATION=1`. Contract tests that replay recorded responses offline live in `tests/contract/`.

---

## IT-CF-VRS: Cashfree bank account verification (`/verification/bank-account/sync`)
| ID | Request | Expected | Status |
|---|---|---|---|
| V1 | 026291800001191 + YESB0000262, name "john doe" | VALID, `name_at_bank` JOHN DOE, 100 DIRECT_MATCH | **RAN 21 Nov**: HTTP 200, VALID, `name_at_bank` JOHN DOE, but `name_match_score`/`result` **null** (name match not active on our account; we rely on our own `name_score`). Needed IP whitelisting first (2FA enforced in test mode). |
| V2 | same, name "john d" | 85 GOOD_PARTIAL_MATCH | |
| V3 | same, name "j doe" | 70 MODERATE_PARTIAL_MATCH | |
| V4 | same, name "jane d" | 38 POOR_PARTIAL_MATCH | |
| V5 | 1233943142 + ICIC0000009, "tom wells" / "tim lee" | 100 / 38 | |
| V6 | 388108022658 + ICIC0000009, "bob hope" / "bane hue" | 100 / 38 | |
| V7 | no `name` field | no score fields (name match only when sent) | |
| V8 | service not enabled | 400 `invalid_request` (detect and report clearly) | |
| V9 | IFSC pairing for 1233943142 and 388108022658 | confirm ICIC0000009 works (UNVERIFIED pairing) | |
| V10 | name-match activation on our account | UNVERIFIED: record result | |

## IT-CF-GST / IT-CF-UDYAM
| ID | Request | Expected | Status |
|---|---|---|---|
| G1 | GSTIN 29AAICP2912R1ZR | `valid` true, legal name present | |
| G2 | GSTIN 29AAIZP2912R1ZR | `valid` false | |
| G3 | GSTIN 27ABCFGH5678D1Z | `valid` true (sandbox) even though a real checksum would fail | |
| G4 | a GSTIN not in the test table | record behaviour (drives `VENDOR_UNVERIFIABLE`) | |
| U1 | UDYAM-UP-43-1234567 | SUCCESS, `enterprise_type` present | |
| U2 | UDYAM-MH-43-1234567 | UDYAM_NOT_FOUND | |
| U3 | UDYAM-KA-43-1234567 | UDYAM_IS_CANCELLED | |

## IT-CF-UPI (optional, UPI payees)
| ID | Request | Expected | Status |
|---|---|---|---|
| UP1 | penny drop `success@upi` | VALID | |
| UP2 | `invalid@upi` | INVALID | |
| UP3 | `expired@upi` | EXPIRED | |
| UP4 | `validatePayout` `success@upi` | `name_at_bank` + `transfer_token` (1 hour) | |
| UP5 | reuse `verification_id` | 409 | |

## IT-CF-PAYOUT: Payouts v2 (the gate)
| ID | Step | Expected | Status |
|---|---|---|---|
| P1 | find working host: `sandbox.cashfree.com/payout` vs `payout-gamma.cashfree.com` | one authenticates; record which | **RAN 21 Nov**: both authenticate after IP whitelisting. v2 `sandbox.cashfree.com/payout` GET transfers/beneficiary → 404 not_found (auth OK). v1 gamma `/authorize` → token; `getBalance` → "No data found" (funding still UNVERIFIED). Payouts and Secure ID share one key pair. |
| P2 | create beneficiary on 000100289877623 / SBIN0008752 | VERIFIED (docs conflict on this account: record) | **RAN 21 Nov** via the app: beneficiary created, `POST /transfers` accepted (cf_transfer_id 667850829, RECEIVED), then status REJECTED `ERROR_SELECTING_FUND_SOURCE`: the sandbox account has **no funded fund source**. Fund it under Payouts → Fund Sources, then retry with a new plan + approval (attempt 2, new transfer_id). |
| P3 | transfer Rs 1 | SUCCESS or INSUFFICIENT_BALANCE; record how balance was funded | |
| P4 | same `transfer_id` again | 200, REJECTED, DUPLICATE_TRANSFER | |
| P5 | invalid IFSC 2640101002729 / CNRR0002640 | rejected / failed | |
| P6 | invalid account 026291800001190 / YESB0000262 | failed | |
| P7 | pending 007711000031 / HDFC0000077 | stays PENDING | |
| P8 | 00224412311300 / YESB0000001 | PENDING then SUCCESS (+ webhook) | |
| P9 | 7766666351000 / YESB0000001 | PENDING then FAILED (+ webhook) | |
| P10 | 7766671735000 / SBIN0000004 | SUCCESS then REVERSED; **does `TRANSFER_REVERSED` arrive? when?** | |
| P11 | 34978321547298 / KKBK0000001 | 25 s timeout then SUCCESS: our client must go UNKNOWN and recover by polling, no second POST | |
| P12 | `GET /payout/transfers?transfer_id=` | status, `status_code`, `cf_transfer_id` | |
| P13 | duplicate beneficiary | 409 | |
| P14 | unfunded balance | REJECTED / INSUFFICIENT_BALANCE handled as terminal failure | |

## IT-CF-PG: payment gateway (fallback plans and seeding)
| ID | Step | Expected | Status |
|---|---|---|---|
| L1 | `PGCreateLink` Rs 500, partial payments on, minimum 100 | link created, `link_url` | |
| L2 | pay the link in a browser (test UPI/card) | `PAYMENT_LINK_EVENT`; status PAID | |
| L3 | pay 100 of 500 | PARTIALLY_PAID, `link_amount_paid` 100 | |
| L4 | link webhook signature | record header names and scheme (docs inconsistent) | |
| O1 | `PGCreateOrder` duplicate `order_id` | 409 | |
| O2 | pay order with `testsuccess@gocash` / `testfailure@gocash` | PAID / failed | |
| O3 | `PGSimulatePayment` on the `cf_payment_id` | status forced as requested | |
| O4 | refund with `refund_note` SUCCESS / FAILED / PENDING | simulated outcome | |

## IT-CF-WH: webhook delivery and verification (all Cashfree products)
| ID | Case | Expected | Status |
|---|---|---|---|
| W1 | register the webhook URL (dashboard, test mode) through ngrok or a hotspot | test delivery received | |
| W2 | verify a real Payouts delivery with base64 HMAC-SHA256(timestamp + raw body) | valid | |
| W3 | same check with `Cashfree.PGVerifyWebhookSignature` | agrees with W2 | |
| W4 | tampered body | rejected 401 | |
| W5 | redelivery of the same event | applied once | |
| W6 | out-of-order events (forced by replaying recorded payloads) | final state correct | |
| W7 | endpoint down for > 5 deliveries | Cashfree stops; our poller reconciles | |

---

## IT-RELAY: Cashfree Relay agent (only if Relay is used)
Facts from the briefing: triggers (schedule, event, inbound webhook), steps (logic, routers, actions), HTTP action with JSON body, secret properties, Sarvam actions (TTS, translation, data extraction), AWS Lambda, Runs page, Draft toggle, 240 voice-call minutes per account.
| ID | Case | Expected | Status |
|---|---|---|---|
| R1 | create agent from a template, open on canvas | agent saved as Draft | |
| R2 | inbound webhook trigger; send a sample event from Postman | a Run appears, pass | |
| R3 | HTTP action → our `/batches/{id}` (key from a secret property, never in the prompt) | 200; Run shows response | |
| R4 | our endpoint returns 500 | Run marked fail; visible error | |
| R5 | our endpoint slow (> 10 s) | record Relay's timeout behaviour | |
| R6 | Sarvam TTS action speaks a Tamil and a Hindi template with "22,000" | correct pronunciation | |
| R7 | outbound voice call to a teammate's phone (call-back flow E2) | call connects; language correct | |
| R8 | capture the callee's spoken answer into a variable and pass it to our HTTP action | UNVERIFIED capability: record | |
| R9 | payment/refund event trigger in test mode | fires on a sandbox event | |
| R10 | call-minute usage after rehearsal | under the 240-minute budget | |
| R11 | flip Draft on; rerun R2 | live agent runs | |

---

## IT-SARVAM: Sarvam SDK (`sarvamai` 0.1.48)
| ID | Call | Expected | Status |
|---|---|---|---|
| S1 | `SarvamAI(api_subscription_key=...)` with our key | client created; a trivial call succeeds (confirm arg name) | |
| S2 | `speech_to_text.transcribe` with `saaras:v4`, `mode="codemix"`, Hinglish approval clip | transcript contains "22,000" (or words) and the code digits | **RAN 21 Nov** (Bulbul audio round trip, en/hi/ta): "seven seven two three" → "7723" in all three; digits come back as numerals. |
| S3 | same with `saaras:v3`, `mode="codemix"` | compare; settles the "mode only for v3" docstring conflict | |
| S4 | `document_intelligence` job on one printed and one handwritten invoice | job completes; record latency and output schema; check bounding boxes | |
| S5 | Tamil clip of spoken digits "4-7-2-9" | digits recovered | |
| S6 | 8 kHz telephony audio (call-back) | transcript usable | |
| S7 | `keyterms=[vendor names]` | vendor names spelled correctly | |
| S8 | `text_to_speech.convert` `bulbul:v4-flash`, `ta-IN`, `hi-IN`, `en-IN`, text with "22,000" | base64 decodes to playable audio; numbers spoken correctly; record latency | **RAN 21 Nov**: 200 for ta/hi/en via the app's `/api/tts` (speakers vijay_ta_narration, ritu_hi_customer, shubh_enhi_ads). Pronunciation not yet reviewed by ear. |
| S9 | invalid speaker persona | clear error | |
| S10 | text over 2,500 characters | rejected; our templates stay short | |
| S11 | invalid key | 401/403 handled; no key in logs | |
| S12 | rate limit / 429 | backoff works | |
| S13 | streaming STT/TTS (optional, live call) | works over the hotspot | |
| S14 | credits used after rehearsal | within the day's allocation | |
| S15 | Document AI **Extract** with our field schema on a printed Tamil, a printed Hindi and a handwritten English invoice | fields returned; record whether per-field confidence exists | **RAN 21 Nov**: 8 rendered demo invoices (ta/hi/en, 2 in a handwriting-style font) via `scripts/read_batch.py`: ~10 s each, all fields returned; GST parts read but no tax total when none is printed (gate now falls back to the GST sum). Handwriting-style G misread its GSTIN (extra digit) and flagged 4 fields unstable, so it is ASKed, never silently passed. All 8 reach the expected outcomes through the gate. |
| S16 | **Parse** with `output_format="json"` | bounding boxes per block; map to fields for the audit view | |
| S17 | page caps: a 12-page and a 25-page PDF | record the real per-job cap (10, 20 or 30) and the error returned | |
| S18 | language detection on mixed Tamil/English invoice | detected language recorded | |
| S19 | transliteration of 10 vendor names (if allowed) run twice | identical output both runs (else cache is mandatory) | |

---

## IT-COMM: end-to-end communication
| ID | Flow | Expected | Status |
|---|---|---|---|
| C1 | Cashfree → ngrok/hotspot → `/webhooks/cashfree/payouts` | delivered and verified on venue network | |
| C2 | backend → UI server-sent events | events arrive in order; UI updates within 2 s | |
| C3 | approval round trip: Bulbul prompt → owner speech → Saaras → check → execute | under 15 s; record | |
| C4 | call-back round trip: Bulbul → vendor speech → Saaras → compare last four | correct result; transcript in audit | |
| C5 | full batch: upload 8 → decisions → plan → approval → payouts → webhooks → audit | matches [PLAN.md](PLAN.md) section 4 outcomes | |
| C6 | drop the network after POST transfer | UNKNOWN → poll → final; exactly one transfer at Cashfree | |
| C7 | replay a recorded approval clip for a new bundle | rejected (`APPROVAL_INVALID`) | |
| C8 | Relay HTTP action ↔ backend contract (if Relay) | schema matches; errors surface in Runs | |
| C9 | Vision job started at upload, demo continues | UI never blocks; cached results labelled | |
| C10 | restart the backend mid-run | state recovered from SQLite; no duplicate payouts | |
