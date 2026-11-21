# PR 4: Voice, vendor call-back, bundle approval and UI (modules E2, H, L, M)

**Branch:** `feat/pr4-voice-approval-ui` · **Owner:** Teammate 4 · **Read first:** [docs/AGENTS.md](../AGENTS.md), [docs/ARCHITECTURE.md](../ARCHITECTURE.md) sections E2, H, L, M, 3 and 7.

## Goal
Make voice catch a trap (call-back on the vendor's number on file), make approval impossible to replay (bundle hash), and give the owner a screen that shows every decision and payout live.

## Scope
- `panch/voice/`: Saaras (`speech_to_text.transcribe`, `saaras:v4`, `mode="codemix"`, `keyterms`) and Bulbul (`text_to_speech.convert`, `bulbul:v4-flash`, base64 audio) wrappers; `render(message_key, lang, **vars)` from `templates/`; `extract_digits(transcript, lang)` for en/hi/ta spoken digits. Numbers above four digits written with commas.
- `panch/vendors/callback.py`: `start_callback(vendor, invoice)` uses the **vendor-master phone only**; `finish_callback(session, transcript)` → match / `CALLBACK_MISMATCH` / `CALLBACK_NO_ANSWER`. In the demo the vendor is a teammate (Relay call if the desk requires Relay, otherwise browser audio).
- `panch/approval/`: `make_bundle(items, cash_limit, now)` (canonical JSON, SHA-256, nonce, 3-digit code, 2-minute TTL) and `check_approval(bundle, transcript_or_code, now)` (yes + total + count + code; single use). Typed-code fallback.
- `app/`: FastAPI app, routes from ARCHITECTURE section 3 that are not webhooks, server-sent events, and a simple owner UI: batch table with outcome chips and reasons in the owner's language, side-by-side crop vs value for ASK, plan + approval panel, live payout status, audit and scoreboard tabs.

## Tests to implement
Offline: `U-VEN-9` to `U-VEN-11`, `U-APR-1` to `U-APR-9`, `U-DEC-6` (templates exist). Integration (run once, record): `IT-SARVAM` S2, S3, S5-S12; `IT-COMM` C2-C4, C7, C9; `IT-RELAY` R6-R8 if Relay is used.

## Acceptance
- A replayed approval clip and a changed bundle are both rejected (`C7`, `U-APR-2..4`).
- The call-back compares spoken last four with the invoice account and never uses the invoice's phone.
- The UI updates within 2 seconds of a webhook; the demo never waits on Vision.

## Out of scope
Reading, invariants, Cashfree clients, planner.

## Coordinate with
PR 2 (template keys per reason code), PR 3 (approved bundle → `execute`; call-back result → vendor master), Krish (planner output feeds `make_bundle`; demo script).
