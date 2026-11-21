# PR 4: work done (voice, approval, call-back, UI)

Owner: Teammate 4. Modules: E2 (call-back), H (bundle approval), L (voice), M (UI). Built against [ARCHITECTURE.md](ARCHITECTURE.md) v3 and [UNIT_TESTS.md](UNIT_TESTS.md). Integration notes for other PRs are in [PR4_NOTES.md](PR4_NOTES.md).

## Status

| Item | State |
|---|---|
| Unit tests (`tests/unit`) | **107 passed** (Python 3.14.6, pytest 9.0.3, offline) |
| App boots and serves UI | Yes: `python -m uvicorn app.main:app --port 8000`, 18 routes; voice badge "Sarvam on" with a key in `.env` |
| Click-through on demo fixture | Done: bundle → spoken confirmation → PIN → (execute 501 until PR 3) → simulated webhooks; call-back on F blocks |
| Live Sarvam (Bulbul / Saaras), `sarvamai` 0.1.48 | **Run 21 Nov, pass.** SDK kwargs confirmed (`language_code`, `model`, `speaker`, file tuple, `mode`, `keyterms`). Results below |
| Real payouts | Waiting on PR 3 (`panch.payouts.execute_bundle`) |
| Python 3.11 + pinned versions | Not run yet (tested on system Python 3.14, FastAPI 0.141, uvicorn 0.40) |

## What was built

### Voice layer: `panch/voice/`
- `numbers.py` (pure): Tamil/Devanagari digits → ASCII; spoken digits in English, Hindi and Tamil (script and romanised); small counts ("do bill", "das"); amounts with multipliers ("22 hazaar"); yes / no / ambiguous detection. Weak English words ("to", "for") count as digits only inside a digit run. Leading zeros kept ("025", "0471").
- `templates.py`: `render(key, lang, **vars)`; Decimal amounts formatted with Indian commas ("1,25,000") so Bulbul reads them right; **never falls back to English**; refuses a half-filled sentence.
- `client.py`: Bulbul `speak` and Saaras `transcribe` wrappers over `sarvamai`. No chat/LLM endpoint (team rule). Persona per language via `PANCH_TTS_SPEAKER_TA/HI/EN`.

### Templates: `templates/{en,hi,ta}/messages.json`
Every reason code in ARCHITECTURE section 5 (incl. v3 `DUP_NUMBER`, `ARITH_GST_SPLIT`, `NEW_VENDOR`) plus flow messages: approval prompt / PIN / second approver / authorised, call-back prompt / ok / owner confirm, payout success / failed / reversed / pending, payment read-back. Placeholders identical across languages (tested). **Hindi and Tamil need a native-speaker check before the demo.**

### Bundle-hash approval: `panch/approval/`
- `make_bundle`: ordered items + cash limit + created/expiry time + nonce → SHA-256 over canonical JSON; 3-digit code from hash + nonce; TTL 2 minutes. Refuses empty bundles, non-Decimal or non-positive amounts, duplicate invoices, totals over the cash limit, and any item with an **unapproved account change**.
- Step 1, **confirmation** (`check_approval`, `ApprovalStore.confirm`): voice transcript must contain yes (no "no"), the total, the bill count and the code; or the typed code. Single use.
- Step 2, **PIN tap = the authority** (`check_pin`, `authorise`, `ApprovalStore.tap_pin`): PBKDF2-hashed PINs, tap bound to the `bundle_hash` shown on screen, within TTL, single use, **locked after 3 wrong PINs**. Voice never authorises alone.
- **Second approver** (stretch): required when any item came through `CHANGED_ACCOUNT` or the total is above `PANCH_SECOND_APPROVER_ABOVE`; the same person twice does not count.
- `assert_executable(bundle, authorisation)`: payouts gate; recomputes the hash, so any change to amount, account, order or cash limit after approval is refused; a bare voice confirmation is refused.

### Vendor call-back: `panch/vendors/callback.py`
- `start_callback`: dials only the **vendor-master phone**; the phone printed on the invoice (`vendor_phone_on_invoice`) is recorded and never used. Prompt in the vendor's language.
- `finish_callback` (pure): spoken last four vs invoice account → pass, `CALLBACK_MISMATCH` (BLOCK) or `CALLBACK_NO_ANSWER` (ASK: no phone on file, unreadable account, fewer than four digits heard). Evidence: masked phone, transcript, transcript hash, audio hash, spoken and expected last four.

### App and UI: `app/`
- `main.py` (FastAPI): batch view (fixture for now), `/api/speak`, bundle create / approve / **pin** / execute, call-back start / result / owner decision, SSE events, dev payout simulator. Full account numbers never leave the server (last four only). Audit hook calls `panch.audit.append` when Krish's module lands.
- `events.py`: thread-safe server-sent events so payouts/webhooks update every open screen.
- `static/index.html`: owner dashboard: language switch (தமிழ் / हिंदी / English), outcome chips with reasons and 🔊, payment plan with the regret line, approval panel (code, voice record as 16 kHz WAV, typed code, PIN pad, second-approver count), call-back panel, live activity feed. Light and dark themes.
- `demo_fixture.json`: UI placeholder mirroring PLAN.md section 4 (A–H, Rs 96,000, cash Rs 30,000, plan H + B) on Cashfree sandbox test accounts.

## Live Sarvam results (IT-SARVAM S1, S2, S8; 21 Nov)

| Case | Result |
|---|---|
| S8 Bulbul `bulbul:v4-flash` hi / ta, default persona | audio OK, 2.5-3.8 s per prompt |
| S8 Bulbul `bulbul:v3` hi / ta | audio OK, 1.5-2.4 s |
| S2 Saaras `saaras:v4`, `codemix` and `transcribe`, hi and ta | 0.3-0.6 s per clip; all 8 approval replies (2 languages × 2 modes × 2 word orders) **valid** |
| Call-back digits ta / hi / en | Saaras returns "4729." in all three → digits 4729 |
| **Finding:** Saaras joins "बाईस हज़ार, दो बिल" into **"22002 बिल"** (number normalisation) | Fixed two ways: prompts now ask for **count before total** ("2 bill, 22,000"), and the checker accepts a number equal to exactly total + count directly before a bill word |
| **Finding:** prompts did not ask for the bill count although the checker needs it | Fixed in en/hi/ta `approval_prompt` and `approval_retry` |
| Saaras returns codes as one number ("026", "420") | Handled; leading zeros kept |

Installed SDK personas include Tamil `gokul_ta_narration`, `aravind_ta_ads`, `vijay_ta_narration` and Hindi `ritu_hi_banking`, `ishita_hi_banking`, `simran_hi_customer`. Set `PANCH_TTS_SPEAKER_TA/HI/EN` after a listen.

## Tests: `tests/unit/`
- `test_approval.py`: U-APR-1 to U-APR-11 plus PIN binding, lockout, expiry, PIN-before-confirmation, cash/duplicate guards, nonce binding.
- `test_callback.py`: U-VEN-9, U-VEN-10, U-VEN-11, no-answer and no-phone cases, prompt language.
- `test_voice.py`: digit extraction in three languages and scripts (U-VEN-9), consent, Indian formatting, every template key in every language (U-DEC-6), placeholder parity, no English fallback.
- Bug found and fixed by the tests: leading zeros were dropped from typed codes and account digits.

## Before the demo (checklist)
- [x] Set `SARVAM_API_KEY`; run IT-SARVAM S1, S2, S8 (done 21 Nov, see above).
- [ ] Choose Bulbul personas (`PANCH_TTS_SPEAKER_TA/HI/EN`) by ear.
- [ ] Try a real microphone in the venue room (the live tests used Bulbul audio, not a human voice).
- [ ] Native-check Hindi and Tamil templates.
- [ ] Set real PINs: `PANCH_APPROVERS` (from `panch.approval.make_approver`) and **`PANCH_DEV=0`** (disables typed transcripts, dev PINs and the payout simulator).
- [ ] Wire PR 3 `execute_bundle(bundle, authorisation)` and webhook → `app.events.publish("payout", ...)`.
- [ ] Swap the fixture for real batch decisions and `plan()` output; remove the temporary `CheckResult` fallback in `callback.py` once `panch/models.py` (PR 2) is on main.
- [ ] Re-run tests on the team's Python 3.11 `.venv`; add `pytest` to `requirements.txt`.

## Honest limits (design note)
- No speaker verification; a PIN can be shoulder-surfed; the 3-digit code proves freshness and binding, not secrecy.
- The vendor's phone on file could itself be compromised.
- Spoken-number word lists are best-effort and need checking against real Saaras output.
