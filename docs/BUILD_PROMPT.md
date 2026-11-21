# BUILD_PROMPT.md: one-page brief to paste into a coding agent

Adapted from the team's `panch-build-prompt.md` and aligned with ARCHITECTURE v3. If anything here disagrees with [ARCHITECTURE.md](ARCHITECTURE.md), ARCHITECTURE wins.

## 1. Mission
Build **TijoriPay**, an end-to-end demo for PS3 (pay the right bill, to the right person):
- Read a batch of multilingual invoices (Tamil, Hindi, English; printed and handwritten).
- Pay only what survives a deterministic gate.
- Confirm changed bank details by calling the vendor's number on file.
- Plan payments under limited cash and MSME deadlines.
- Take a replay-proof bundle approval (voice read-back plus a PIN tap).
- Pay through Cashfree Payouts sandbox without ever paying twice.
- Show a scoreboard: traps blocked, clean auto-paid rate, clean falsely held.

Repo: `git clone https://github.com/ServerCrash358/cashfreeXsarvam.git`. Work in a **git clone**, not a downloaded ZIP, so you can pull and push. Read order: `docs/AGENTS.md` → `docs/ARCHITECTURE.md` → `docs/PLAN.md` → `docs/SYSTEM.md` → `docs/DEPENDENCIES.md` → `docs/UNIT_TESTS.md` → `docs/INTEGRATION_TESTS.md` → your `docs/tasks/PR*.md`.

## 2. Red lines
- Money never moves to an account not verified as belonging to the claimed vendor.
- A retry never becomes a second payment: no resend after timeout/5XX until Cashfree's status is terminal.
- Approval is bound to a bundle hash plus a one-time nonce; **a PIN tap is the authority, voice never authorises alone**.
- Every payment traces to its invoice, its checks and its approver.
- No Sarvam chatbot/LLM decides or writes anything. Vision reads, Saaras hears, Bulbul speaks; amounts and decisions are deterministic; explanations are templates.
- Never translate fields used for matching or money (GSTIN, invoice number, account, IFSC, amounts, dates). Keep the native string as evidence; transliterate vendor names only.
- `Decimal`, never `float`. Never log or display full Aadhaar or full bank account numbers (last four only).
- Never commit `.env`; synthetic data and sandbox only. Never silently correct a read value: uncertainty goes to ASK.

## 3. Scope
| Tier | Items |
|---|---|
| **P0** (never cut) | one intake queue; Vision Extract with the fixed schema + multi-read/confidence; normalisation (FY-preserving invoice numbers); invariants incl. `ARITH_GST_SPLIT` and digits vs words; economic fingerprint with two-track duplicate rule; three vendor lanes (`KNOWN`, `CHANGED_ACCOUNT`, `NEW_VENDOR`); twin clean controls + three metrics |
| **P1** (never cut) | bank verification with our own name match; changed-account quarantine; old-number call-back; fuzzy duplicates → ASK, invariant failures → BLOCK |
| **P2** (never cut) | payout state machine with UNKNOWN; deterministic `transfer_id`; INTENT before send; status check before retry; ledger (one active transfer per invoice, cumulative ≤ amount); reconciliation sweep; verified webhooks; reversal never auto-repays |
| **P3** (thin) | cash/deadline planner (regret table cut first); bundle-hash approval with spoken total + count + code and PIN tap, typed fallback; owner-language templates; owner UI; plain append-only audit log (hash chain and viewer polish cut first) |
| **Stretch** | second approver above a threshold or for `CHANGED_ACCOUNT` items (cut before anything in P3) |
| **Out of scope** | anomaly heuristics, learned fraud model, chat interface, invoice-number-only dedupe, auto-repay, reverse penny drop, Payment Links for PS3, multi-accountant roles, WhatsApp approvals, vendor self-service portal, PO/GRN match, discount optimiser, Tally export, analytics, native Android app, Sarvam translation of matching fields |

## 4. Contracts and codes
Implement the dataclasses and functions in ARCHITECTURE section 7 exactly (the v3 `Invoice` adds `confidence`, `raw_native`, `pages`, `language`, `po_number`, `buyer_gstin`, `discount`, `cgst/sgst/igst`, `vendor_phone_on_invoice`). Reason codes are ARCHITECTURE section 5, including `DUP_NUMBER`, `ARITH_GST_SPLIT` and `NEW_VENDOR`.

## 5. Rules (no deviations)
- **Decision order:**
  1. Any invariant failure, `DUP_EXACT`, `DUP_NUMBER` or `CALLBACK_MISMATCH` → BLOCK.
  2. `DUP_FUZZY`, `ACCOUNT_CHANGED`, `LOW_CONFIDENCE_READ`, `VENDOR_UNVERIFIABLE`, `NEW_VENDOR`, `OVER_LIMIT` or a soft flag → ASK.
  3. Otherwise PAY-ready; the planner may turn it into DEFER.
  4. Every outcome carries codes, evidence and a template key that exists in `templates/{ta,hi,en}/`. Deterministic. Nothing is paid without an approved bundle.
- **Name triangle:** our own score ≥ 85 pass, 60-84 ASK, < 60 `NAME_MISMATCH` BLOCK. Cashfree's tier is evidence only. GSTIN checksum is a soft flag.
- **Call-back:** use the master phone only. Bulbul asks for the last four digits; Saaras transcribes; code compares. Record transcript, audio hash and phone used.
- **Approval:** canonical-JSON SHA-256 over order, amounts, account hashes, cash limit, time and nonce. Spoken count + total + code, then a PIN tap. TTL 2 minutes; single use; any change invalidates it.
- **Payouts:** `transfer_id = pn_ + 32 hex`, 35 characters. Success is final only at SUCCESS + COMPLETED. Verify the webhook as base64 HMAC-SHA256(secret, timestamp + raw body) on the raw body. Deduplicate events and apply by state rank. Sweep every 60 s. Try `sandbox.cashfree.com/payout`, then `payout-gamma.cashfree.com`, and record which works. Record how the sandbox balance was funded.
- **Planner:** deadline = acceptance + 15 days, or the agreed term capped at 45 days, micro/small only. Exact subset search maximising deduction-protected rupees; greedy beyond ~25 candidates.
- **Vision:** pre-run and cache the demo batch; never block the demo. Respect page caps, keep page numbers, and keep Parse bounding boxes for the audit view.

## 6. Demo acceptance (8 invoices, Rs 96,000; cash Rs 30,000; clean A+B+C+H = Rs 44,000)
| Invoice | Expected |
|---|---|
| A, micro, 12,400 | PAY-ready, then DEFER |
| B, small, 18,000 | PAY; ends `TRANSFER_SUCCESS` COMPLETED (**success case**) |
| C, medium, 9,600 | PAY-ready, then DEFER |
| D, disguised duplicate, 21,000 | BLOCK `DUP_EXACT` |
| E, 15,000 | BLOCK `ARITH_TOTAL` |
| F, changed account, 11,000 | ASK, then BLOCK `CALLBACK_MISMATCH` (**failure case**) |
| G, 5,000 | BLOCK `NAME_MISMATCH` |
| H, micro, 4,000 | PAY, then `REVERSED` and reopened unpaid |

The plan shows H + B = Rs 22,000, against the naive plan's Rs 16,400 protected. The submission needs one real sandbox payout, reasons in the owner's language, and a design note stating what was not used and what is canned.

## 7. Tests and delivery
- Unit tests: every ID in [UNIT_TESTS.md](UNIT_TESTS.md), including the v3 additions (offline; `Decimal` exact; every BLOCK/ASK asserts its code).
- Integration: [INTEGRATION_TESTS.md](INTEGRATION_TESTS.md) (BAV, GST/Udyam, Payouts P1-P14, webhooks W1-W7, Sarvam S1-S19, communication C1-C10; Relay only if required). Record results in the Status column.
- Deliver: `app/` + `panch/` per the canonical layout; `templates/{ta,hi,en}/`; `config/`; a synthetic-data generator; `tests/{unit,integration,contract}`; SQLite schema per ARCHITECTURE section 4.
- Build order: thin slice → P0 → P1 → P2 → P3 → scoreboard → UI polish. Done = unit tests pass, codes plus evidence returned, one sandbox run recorded where there is I/O, and an audit entry for anything affecting money.
- Git: small commits, `git pull --rebase origin main` before every push, never force-push, never commit `.env`.
