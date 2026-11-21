# TijoriPay: design note

**Problem Statement 3: pay the right bill, to the right person.** TijoriPay reads a batch of multilingual invoices (Tamil, Hindi, English; printed and handwritten). It pays only what survives deterministic checks, plans payments under limited cash and MSME deadlines, takes an approval that can't be replayed, and pays through Cashfree Payouts without ever paying twice.

## 1. What decides what

| Outcome | When | Examples (reason codes) |
|---|---|---|
| **BLOCK** | Something is provably wrong: numbers disagree, or money would go to the wrong person | `ARITH_LINE`, `ARITH_SUBTOTAL`, `ARITH_TOTAL`, `ARITH_WORDS`, `ARITH_GST_SPLIT`, `DUP_EXACT`, `DUP_NUMBER`, `NAME_MISMATCH` (< 60), `BANK_INVALID` / fraud flag, `ACCOUNT_SHARED`, `CALLBACK_MISMATCH` |
| **ASK** | Something is uncertain; the owner decides | `DUP_FUZZY`, `ACCOUNT_CHANGED` (frozen until the call-back), `NEW_VENDOR`, `LOW_CONFIDENCE_READ`, `VENDOR_UNVERIFIABLE`, partial name match (60-84), soft flags (`GSTIN_FORMAT`, `IFSC_FORMAT`, `TAX_RATE`, `OVER_LIMIT`), `PAYOUT_REVERSED` |
| **PAY** | Every check passes; the invoice enters the proposed bundle | — |
| **DEFER** | Clean, but this run's cash goes to bills with nearer MSME deadlines | `CASH_DEFERRED` |

- Any BLOCK wins over ASKs, and every outcome carries its codes, its evidence and a sentence from a template in the owner's language.
- Near-duplicates and sandbox gaps **ask rather than block**. That keeps legitimate bills from being stopped on the unseen batch.
- Nothing is paid without an approved bundle.

## 2. Why these choices

- **Duplicates by economic content, not by invoice number.** The fingerprint covers vendor, line items, total, date and PO.
  - An exact match is blocked, whatever number it carries.
  - The same number reused in the same financial year is also blocked.
  - A recurring vendor's identical bill in a new month is paid.
  - Invoice numbers keep their financial year, because "42/2025-26" and "42/2026-27" are different bills.
- **We match names ourselves.** Cashfree bank verification gives us `name_at_bank`. On our test account its own name-match score comes back empty, so name matching is not enabled.
  - We score names ourselves: tokens sorted, initials allowed, phonetic and honorific-insensitive.
  - The score is checked across a triangle: invoice payee vs vendor legal name, and bank name vs account holder on file.
- **A changed account triggers a call-back on the number on file.** An attacker who edits an invoice controls its account number *and* the phone printed on it, so we only ever call the vendor-master number.
  - Bulbul asks for the last four digits in the vendor's language, Saaras transcribes the answer, and code compares.
  - A mismatch blocks.
  - A match still needs the owner's PIN before the new account is trusted.
- **Extract, don't translate.** Vision Extract runs in `basic` mode, and every field is read as text.
  - `advanced` mode "checks that line items add up", which could silently repair the very arithmetic traps we must catch.
  - Money fields are canonicalised in code; the native string is kept as evidence.
- **Plan under cash and deadlines.** The rule is 43B(h)/MSMED: micro and small vendors must be paid within 15 days, or the agreed term capped at 45.
  - The planner does an exact subset search for the rupees of deduction protected.
  - Demo: ₹30,000 cash. H + B protects ₹22,000; paying the earliest deadline first protects ₹16,400.
- **Approval can't be replayed.**
  - **The bundle:** a SHA-256 over the canonical JSON of the order, amounts, account hashes, cash limit, time and a nonce.
  - **Spoken confirmation:** the owner gives a yes, the bill count, the total and a 3-digit code, in their own language.
  - **The PIN tap is the authority:** it's bound to the same hash, lasts 2 minutes, works once, and three wrong PINs lock the bundle.
  - Any change to the bundle invalidates the approval.
- **Never pay twice.**
  - The `transfer_id` is deterministic: `pn_` plus 32 hex characters derived from vendor, fingerprint, account, amount and attempt.
  - INTENT is recorded before the call is sent.
  - A timeout or 5XX becomes **UNKNOWN, not FAILED**, and we poll status rather than resend.
  - Success counts only at SUCCESS with status COMPLETED.
  - The ledger allows one active transfer per invoice.
  - A sweep every 60 seconds catches webhooks that never arrive.
  - Webhooks are verified with an HMAC over the raw body, deduplicated, and applied by state rank.
  - **A reversal reopens the bill and is never repaid automatically.**
- **Audit.** An append-only, hash-chained log covers ingestion, every decision, each call-back, the plan and bundle hash, approvals, payout intent and send, and webhooks. Editing any entry breaks the chain, and the UI shows this.

## 3. What we chose not to use, and why

| Not used | Why |
|---|---|
| Sarvam chat model or any LLM for decisions, amounts or explanations | Decisions must be deterministic and explainable; every sentence is a reviewed template. Sarvam only reads (Vision), hears (Saaras) and speaks (Bulbul). |
| Sarvam translation of fields | Translating GSTINs, numbers, accounts, amounts or dates is lossy. We extract, then canonicalise in code. |
| Vision Extract `advanced` mode | It may "fix" the arithmetic we are checking. |
| A learned fraud model or anomaly heuristics | No honest training data in 4 hours; rules with evidence are auditable. |
| Dedupe on invoice number alone | Trivially defeated by renumbering (our trap D). |
| Auto-repay after a reversal | A reversal often means the account is wrong; the bill must be re-verified and re-approved. |
| Reverse penny drop, Payment Links | Not needed for paying vendors; Payment Links belong to the PS2 fallback. |
| Voice-only approval | No speaker verification; a cloned voice could approve. Voice is the conversation; the PIN is the authority. |

## 4. What is real, and what is canned or simulated

| Piece | Status |
|---|---|
| Sarvam Bulbul TTS (ta/hi/en) and Saaras STT | **Live**, verified 21 Nov |
| Sarvam Vision Extract | **Live** on our rendered demo invoices (`data/demo/`), cached by file hash. The demo runs from the cache (`PANCH_VISION_OFFLINE=1`) so it never waits on a 20-90 s job |
| Cashfree Secure ID bank verification | **Live** (after IP whitelisting). It falls back to canned copies of Cashfree's published sandbox data, marked `canned`, only if the API is unreachable |
| GSTIN / Udyam verification | Called for new vendors. Sandbox data only covers a few published IDs, so others come back unverifiable, which asks |
| Cashfree Payouts | **Live call made:** beneficiary created and transfer `667850829` accepted (RECEIVED), then **rejected `ERROR_SELECTING_FUND_SOURCE`**, because our test Payouts account has no funded fund source. Success, pending and reversal are therefore shown in **simulated mode**, labelled SIMULATED in the UI, through the same state machine, ledger and signed-webhook verifier |
| Invoices, vendors, accounts | Synthetic, built on Cashfree's published sandbox test accounts |
| Cashfree Relay | Optional orchestration and voice layer ([RELAY.md](RELAY.md)). TijoriPay fires signed inbound-webhook triggers (call-back needed, bill blocked, payout success or reversal); a Relay agent can place the vendor call and post back only the transcript, and our code compares and decides. It's off unless `RELAY_WEBHOOK_URL` is set |
| Payout webhooks | The demo runs on one laptop with no public URL, so Cashfree cannot deliver webhooks to us. Status comes from the **60-second status sweep** (the second path to the truth). The receiver and its signature check are built and tested, and the reversal step is shown with a labelled simulated event |

## 5. Measured results (our own labelled set, not the unseen batch)

- **Demo batch:** 8 invoices worth ₹96,000.
  - **Clean, PAY:** A, B, C, H.
  - **Blocked:** D `DUP_EXACT`, E `ARITH_TOTAL`, G `NAME_MISMATCH`.
  - **F:** asked about first (`ACCOUNT_CHANGED`), then blocked `CALLBACK_MISMATCH` after the call-back.
- **Evaluation harness** (`scripts/run_eval.py`, [EVAL_REPORT.md](EVAL_REPORT.md)): 40 mutated cases.
  - 20 traps: **20/20 blocked**, each by its expected code.
  - 20 clean controls, 8 of them legitimate twins: **20/20 auto-paid, 0 falsely held, 0 false blocks**.
  - Claim: *zero false blocks on our clean controls, measured.*
- **Tests:** about 200 offline unit and API tests.
- **Success case (B):** read, then PAY, then planned, then approved by voice and PIN, then paid. The paid state is SUCCESS/COMPLETED in simulation; the live sandbox call reached Cashfree but was rejected for funds.
- **Failure case (F):** the bank details changed to a valid account whose name matches. The call-back on the master phone heard different last four digits, so the bill was blocked.

## 6. Honest limits

- There's no speaker verification. The 3-digit code proves the approval is fresh and bound to this bundle; it isn't a secret, so the PIN is the authority.
- The vendor's phone on file could itself be compromised.
- Hindi and Tamil templates and spoken-number word lists need native-speaker review.
- Handwriting accuracy on unseen invoices is unmeasured. Unstable reads go to ASK, never silently through.
