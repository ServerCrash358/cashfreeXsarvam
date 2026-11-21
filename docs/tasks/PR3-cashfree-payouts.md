# PR 3: Cashfree verification, payouts, state machine and webhooks (modules E, I, I2)

**Branch:** `feat/pr3-cashfree-payouts` · **Owner:** Teammate 3 · **Read first:** [docs/AGENTS.md](../AGENTS.md), [docs/ARCHITECTURE.md](../ARCHITECTURE.md) sections E, I, I2 and 7, [docs/DEPENDENCIES.md](../DEPENDENCIES.md) sections 4-5.

## Goal
Every rupee leaves through this code, and none leaves twice. Also the vendor and bank verification that decides whether an account belongs to the vendor.

## First 30 minutes (the gate for the whole team)
Run `IT-CF-PAYOUT` P1-P3 and `IT-CF-WH` W1-W2 from [docs/INTEGRATION_TESTS.md](../INTEGRATION_TESTS.md): find the working Payouts host, fund the sandbox balance (ask the desk), Rs 1 transfer to the success account, capture one real webhook. **Tell the team the result immediately.**

## Scope
- `panch/cashfree/http.py`: shared httpx client, auth headers, base URLs from env, timeouts, logging without secrets or full account numbers.
- `panch/cashfree/signature.py`: `verify_signature(secret, timestamp, raw_body, signature)`; cross-check with `Cashfree.PGVerifyWebhookSignature`.
- `panch/cashfree/verification.py`: bank account sync, GSTIN, Udyam clients.
- `panch/vendors/master.py` + `panch/vendors/verify.py`: vendor master (SQLite), `name_score` (our own matching), name triangle, `ACCOUNT_CHANGED`, `ACCOUNT_SHARED`, `BANK_INVALID`, `NAME_MISMATCH`, `VENDOR_UNVERIFIABLE`.
- `panch/payouts/ids.py`: `transfer_id` = `pn_` + 32 hex of SHA-256(vendor | fingerprint | account | amount | attempt).
- `panch/payouts/state.py`: pure `apply_event(state, event)` with state ranks; INTENT → SENT → UNKNOWN/PENDING → SUCCESS/FAILED/REJECTED → REVERSED.
- `panch/payouts/client.py`: beneficiary, transfer, status; INTENT recorded before the POST; UNKNOWN on timeout/5XX; polling with backoff; retry only after confirmed terminal failure; `DUPLICATE_TRANSFER` means fetch the original.
- `app/routes/webhooks.py`: `POST /webhooks/cashfree/payouts` (raw body, signature, dedupe, apply by rank).

## Tests to implement
Offline: `U-VEN-1` to `U-VEN-8`, `U-PAY-1` to `U-PAY-13`, `U-SIG-1` to `U-SIG-3`. Integration (run once, record): `IT-CF-VRS` V1-V10, `IT-CF-GST` G1-G4, `IT-CF-UDYAM` U1-U3, `IT-CF-PAYOUT` P1-P14, `IT-CF-WH` W1-W7.

## Acceptance
- A Rs 1 sandbox payout completes end to end with a verified webhook (or the blocker is documented with the desk's answer).
- 100 shuffled/duplicated event sequences give zero double payments (`U-PAY-13`).
- The timeout account (P11) recovers via polling with no second POST.

## Out of scope
Reading, decisions, voice/UI, planner.

## Coordinate with
PR 2 (check results → `decide`), PR 4 (call-back updates the vendor master; approval gates `execute`), Krish (audit entries for every payout step).
