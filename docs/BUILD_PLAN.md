# Build plan (working name: **Panch**)

**Status:** v3, 21 Nov 2026. This is the decision report and history. **[ARCHITECTURE.md](ARCHITECTURE.md) is canonical** wherever the two differ.

**Changes in v3 (from the latest review):**
- Mandatory core: true-by-construction invariants, economic fingerprint, bank-detail quarantine, one live payout. Ordering/regret and the hash-chained audit are thin layers.
- **Vendor call-back on the old number**: for a changed account, call the vendor-master phone (never the invoice's), ask for the last four digits of the new account, compare in code. Voice now catches a trap.
- **UNKNOWN is not FAILED**: `SENT → UNKNOWN → status check`; no retry until Cashfree's status is terminal; reversals never auto-repay.
- **Bundle-hash approval**: the owner approves one hashed bundle (order, amounts, accounts, cash limit, nonce); any change invalidates it; spoken total + bill count + one-time code.
- **Legitimate twins** in the scoreboard; report traps caught (BLOCK) and clean auto-paid rate separately; ASK on a clean bill is a false hold.
- **Duplicates:** fuzzy matches go to ASK; only identical economic content with the same date or delivery reference is BLOCK. GSTIN checksum is a soft flag (sandbox test GSTINs may fail a real checksum).
- Claims softened: "zero false blocks on our clean controls, measured", never on the unseen batch.
- Integration suites for the Cashfree test environment, Relay, the Sarvam SDK and end-to-end communication are in [INTEGRATION_TESTS.md](INTEGRATION_TESTS.md).
**One line:** an invoice-to-payout agent for Problem Statement 3 that treats every invoice as a claim, pays only what survives a deterministic gate, plans payments under limited cash and legal deadlines, never double-pays, and shows a live scoreboard of traps caught versus good invoices wrongly blocked.

---

## 1. What we are building (plain language)

Raghu's accountant retypes about sixty multilingual invoices into a banking portal every Friday. Panch replaces the retyping and the guessing:

1. It reads a batch of invoices (Tamil, Hindi, English; printed and handwritten).
2. It checks each one: do the numbers agree, has it been paid before in disguise, is the vendor real, does the bank account belong to that vendor.
3. It decides one of: **PAY**, **ASK the owner**, **BLOCK with a reason**, or **DEFER** (cash ran out).
4. It plans which approved invoices to pay first with the cash available, using legal deadlines.
5. The owner approves one exact plan by voice, in his own language, with a spoken challenge that cannot be replayed.
6. Money leaves through a state machine that cannot pay twice, even across retries, failures and reversals.
7. Every payment can be traced from the bank transfer back to the invoice image, the checks and the approver.
8. A scoreboard shows how many planted traps it caught and how many good invoices it wrongly held, measured on a batch we generated.

## 2. The rules we are working under

| Item | Value |
|---|---|
| Event | Sarvam x Cashfree Buildathon, Bengaluru, 21 Nov 2026 |
| Team / time | about 5 people, build 11:30-3:30 (4h), code freeze 3:30 |
| Demo | Round 1: 10 min incl. Q&A (5 panels; top team per panel + a wildcard reach the final, 12 min) |
| Submission | working end-to-end demo ending in a sandbox payout + short design note (incl. what we chose NOT to use) + one success case and one failure case |
| Curveball | a fresh unseen batch with planted traps (duplicate, changed account, wrong arithmetic, mismatched name); scored on catches AND good invoices wrongly blocked |
| Data | synthetic only; Cashfree sandbox answers only to its published test data |
| Team rule on Sarvam | Sarvam Vision reads, Saaras hears, Bulbul speaks. **No Sarvam chatbot/LLM.** All decisions and amounts come from deterministic code; explanations come from pre-written templates per language |
| Red lines (PS3) | money never moves to an unverified account; approval can't be spoofed, replayed or accidental; a retry never becomes a second payment; every payment traces to invoice, checks and approver |

Open question: whether Sarvam Vision (reading invoices) counts under the "Sarvam is only user-facing speech" rule. Assumed yes (it is input). **Confirm.**

## 3. How we got here (decision trail)

- Round 1: free-choice ideas (Bill Bolo, AdvanceBack, Pakka, etc.) were stress-tested by hostile critics. A "caterer refund" and "short-payment" idea led, but that was before the official problem statements and the Relay briefing.
- The official problem statements replaced free choice. The user leans PS3.
- Wave 1 (this session): three ideators proposed three unique takes per problem statement; a reality miner checked competition and rules; a docs verifier checked the Cashfree sandbox.
- Wave 2 (done): three blind, shuffled hostile critics ranked 12 takes (4 per problem statement) on Cashfree depth and demonstrability, unseen-batch robustness, and build/demo risk. Average rank (1 = best): T10 bank-detail quarantine 2.7, T9 invoice fingerprint 3.3, T12 scarcity-ordered queue 4.0, T3 invariant gate (PS1) 5.0, T4 confidence-map court (PS1) 6.0, T11 signed pay-plan 6.3, T2 four-way name verdict (PS1) 6.7, T5 cash-in scheduler (PS2) 7.0, T8 allowlist ranker (PS2) 7.7, T7 seeded exploration (PS2) 8.7, T6 claim ledger (PS2) 9.3, T1 spoken read-back (PS1) 11.3.
  - The three best average ranks are all PS3 takes, and all three critics suggested combining them: detection from T9 and T10, ordering and execution from T12. That combination is Panch.
  - Dissent: the robustness critic guessed PS1 is the least crowded (about 6-8 teams, against 12-14 on PS3) and picked T3. That crowd estimate is a guess. The demo-risk critic found PS3 has the most published sandbox support for a live payment, provided Payouts can be funded.
  - Cut: T1, T6, and T7 as a headline. T11's signed plan is reduced to a light confirmation, because it catches none of the planted traps.
  - Fallbacks: section 17.
- Honest note: PS3 is the same family as an earlier idea (Bill Bolo) that I had retired and then reinstated, so anchoring is possible. The critics are blind and shuffled to test that.

## 4. What makes it unique (and what does not)

Baseline every team will build: read invoice, recompute total, verify bank with name match, voice "yes", payout, webhook, duplicate check on invoice number. That alone is not unique. An existing public repo ("Hisaab") already does duplicates, bank-change flags and arithmetic with a mocked payment.

Our differentiators, in order of importance:

1. **A measured scoreboard.** We ship a labelled mutation-tested batch and report catch rate and false-block rate per check, with a threshold sweep. Other teams will claim; we measure. This directly mirrors how the curveball is scored. Honest limit (from the critics): a mutation set we write ourselves is circular, because the organisers' traps are not our imagination. So the core claims rest on logical invariants that cannot be argued with (arithmetic, digits versus words, checksums, deterministic fingerprints) and on a measured false-block rate on our clean controls (target: zero), including legitimate recurring orders. Most PS3 teams will catch the four planted traps, so false blocks and end-to-end quality are what separate teams.
2. **Duplicates by economic fingerprint, not invoice number.** Disguised repeats (new number, different date format, respelled vendor, shuffled lines) are caught; legitimate monthly repeat orders stay clean.
3. **Payment ordering under scarcity.** A deterministic solver picks what to pay with limited cash given legal deadlines, and prints a regret table of the alternatives.
4. **Reversal-safe execution.** A state machine with deterministic transfer IDs and status-before-retry. Failure and reversal never auto-repay.
5. **Challenge-bound voice approval.** The owner approves a hash of one exact plan by repeating random digits. Replays, wrong plans, expired nonces and accidental "haan" all fail.
6. **Changed bank details treated as a claim to prove.** Quarantine plus an identity triangle (invoice name, GST/Udyam legal name, bank name) and call-back to the number on file, never the one on the invoice.
7. **A real audit trail.** Hash-chained, append-only; every payment traces invoice crop, extracted fields, checks, approver, transfer ID and webhook events.
8. **Real sandbox payouts**, not a mock.

What is NOT unique: reading invoices with Vision, using bank verification, and voice approval as a concept.

## 5. System overview

```
invoice images (batch)
   -> [A] Intake + Sarvam Vision (multi-read)
   -> [B] Normalisation (numerals, words, dates, names)
   -> [C] Integrity checks (arithmetic)
   -> [D] Fingerprint + duplicate engine
   -> [E] Vendor + bank verification (GST, Udyam, bank account, name triangle)
   -> [F] Decision engine: PAY / ASK / BLOCK / DEFER  (+ reason code + template)
   -> [G] Payment planner (cash, deadlines)
   -> [H] Voice approval (plan hash + spoken digits)
   -> [I] Payout execution + webhook state machine
   -> [J] Audit ledger
   [K] Evaluation harness runs the whole pipeline on mutated batches
   [L] Voice layer, [M] UI, [N] synthetic data, run through everything
```

## 6. Components, one by one

### A. Intake and reading (Sarvam Vision)
- Input: invoice images or PDFs, printed and handwritten, in Tamil, Hindi and English. Delivery slips may have bank details scribbled underneath.
- Vision (async job; latency 20-90s, handwriting accuracy unverified) extracts fields: vendor name, GSTIN, invoice number, date, line items (item, quantity, rate, amount), subtotal, tax, total, amount in words, bank account and IFSC if present.
- **Multi-read for stability:** read each field from the original and two preprocessed variants (binarised, upscaled). A field is "stable" only if reads agree. Unstable fields lower confidence and force ASK, never silent correction.
- Keep the crop (bounding box) for every field for the audit and for the owner screen.
- Pre-run and cache the demo batch; process new files in the background. Never block the live demo on a Vision job.

### B. Normalisation
- Numerals: Tamil, Devanagari and Latin digits to one form.
- Amount in words: Tamil, Hindi and English number words and lakh/crore notation to integers (compare against figures).
- Dates: at least six formats ("3 Nov", "03-11-2026", Tamil month names) to ISO dates.
- Vendor names: a phonetic key across scripts so "Sri Murugan Hardware" and its Tamil spelling collapse to one identity.
- Invoice numbers: strip prefixes, zeros, case and separators.

### C. Integrity checks (arithmetic)
- Line items: quantity x rate = amount; sum of lines = subtotal.
- Subtotal + tax = total; tax must match a valid slab (confirm the current GST slabs before hard-coding).
- Figures versus words versus lines versus tax: all must agree within a stated tolerance (paise).
- Other logical invariants (cheap, and the claims that survive unseen traps): GSTIN checksum and format, IFSC format, account-number length, plausible dates (not in the future, not before the delivery), and the vendor's PAN embedded in its GSTIN matching the PAN on record.
- A failure gives reason code `ARITH_*` and a specific message (which two numbers disagree).

### D. Fingerprint and duplicate engine
- Reduce each invoice to an economic identity: normalised vendor, line-item multiset (item, quantity, rate, order-insensitive), total, date window, delivery-slip or PO reference if present.
- Score a new invoice against the ledger with weighted evidence; flag above a threshold chosen from the sweep in section K.
- Protect legitimate repeat orders (same items, new dates and POs) with a margin and a "recurring vendor" rule.
- Defence in depth: the payout `transfer_id` is derived from the fingerprint, so a missed duplicate still collides at the payment layer (Cashfree returns REJECTED / DUPLICATE_TRANSFER).

### E. Vendor and bank verification (Cashfree Secure ID)
- Vendor master: legal name, GSTIN, Udyam number, known account(s), phone on file, first-seen provenance of each account.
- GSTIN verification and Udyam verification (sandbox test data exists; confirm behaviour). Udyam status gives micro/small versus medium, which drives deadlines (section G).
- Bank account verification (`POST /verification/bank-account/sync`): returns `name_at_bank`, `account_status` and a name-match score/tier only if a name is sent. **We do our own name matching** against `name_at_bank` with our own tiers, because the Cashfree tier behaviour in sandbox is canned and activation is unconfirmed.
- Name triangle: invoice name versus GST/Udyam legal name versus bank name. All must clear the threshold.
- Changed account on a known vendor: **quarantine**, never auto-pay. Owner approves the *change* separately, after a call-back to the number on file.
- Same account under two different vendors: refuse.
- Vendors whose GSTIN or Udyam number is not in the sandbox test data return nothing. Mark them `UNVERIFIABLE` and route to ASK, never BLOCK, so good vendors are not wrongly stopped. State in the design note which results are canned.
- Aadhaar numbers are never displayed or stored in full (last four only).

### F. Decision engine
Four outcomes: **PAY** (all checks pass, known vendor, unchanged verified account, under limit), **ASK** (needs the owner: low confidence, changed bank details, new vendor), **BLOCK** (a check failed: reason shown), **DEFER** (clean but cash ran out).
- Every outcome carries a reason code, the evidence and a template message in Tamil, Hindi and English. No generated text.
- Reason codes: `DUP_ECON`, `ARITH_TOTAL`, `ARITH_WORDS`, `ARITH_TAX`, `VENDOR_UNKNOWN`, `GST_INVALID`, `UDYAM_CANCELLED`, `BANK_INVALID`, `NAME_MISMATCH`, `ACCOUNT_CHANGED`, `ACCOUNT_SHARED`, `LOW_CONFIDENCE_READ`, `OVER_LIMIT`, `CASH_DEFERRED`, `APPROVAL_FAILED`.
- Unknown: whether the scorer counts a HOLD/ASK as caught or as wrongly blocked. **Ask the organisers.** Until answered, keep ASK narrow (only when genuinely uncertain).

### G. Payment planner
- Inputs: cash available, list of PAY-ready invoices, each with due date, Udyam class and amount.
- Legal rule (per vendor flag, confirm current text): Udyam-registered micro and small suppliers must be paid within 15 days (no written agreement) or the agreed term capped at 45 days (written agreement) for the buyer to claim the expense that year. Medium enterprises and traders are excluded. Make "rule applies?" a config flag per vendor.
- Solver: an exact subset search (about 60 invoices is small) maximising rupees of tax deduction protected, then early-payment discounts, then vendor priority, under the cash limit.
- Output: the chosen plan, the deferred list with reasons, and a **regret table** (what each alternative ordering would have cost).
- Illustrative demo numbers (hand-checked): cash Rs 30,000; clean invoices H Rs 4,000 (1 day left), A Rs 12,400 (3 days), B Rs 18,000 (5 days), C Rs 9,600 (no deadline). Best subset protecting deadlines is H + B = Rs 22,000. A naive earliest-deadline-first plan pays H, A, then C = Rs 26,000 and protects only Rs 16,400. A is deferred and flagged.

### H. Voice approval
- Bulbul reads the plan in the owner's language: count, total, payees. It adds a random 4-digit challenge derived from the plan hash plus a one-time nonce.
- The owner repeats "haan" and the digits; Saaras transcribes; code compares.
- Fails on: a replayed clip (different nonce), a different plan (hash mismatch), an expired nonce, ambiguous speech ("haan... nahi"), accidental "haan" without the digits.
- Changed-bank items need a separate explicit approval with an extra warning.
- Honest limit: no speaker verification, so a voice clone remains a risk; say so in the design note. Provide a button approval as a fallback.
- Scope (critics' verdict): this catches none of the planted traps, so keep it light. Bulbul reads the plan and the reasons; the owner says approve and repeats the digits; a typed-digit fallback is ready because a noisy room will hurt Saaras on digits. Spend no more than about an hour on it.

### I. Payout execution and webhooks
- Add beneficiary (`POST /payout/beneficiary`), then `POST /payout/transfers` with `transfer_id` derived from vendor, invoice fingerprint, account and amount (max 40 characters, alphanumeric and underscore: use a short prefix plus a 32-hex-character digest, keep the full digest in our ledger and check for collisions).
- State machine: `INTENT` (recorded before any API call) → `SENT` → `PENDING` → `SUCCESS` | `FAILED` | `REJECTED` | `REVERSED`.
- Retry only after the status API (not just a webhook) confirms a terminal FAILED/REJECTED. On a 5XX or timeout, check status first, never resend blindly.
- Webhook receiver: verify the signature (base64 HMAC-SHA256 over timestamp + raw body, client secret; the docs conflict in places, so **test against a real delivery**), deduplicate by event, handle out-of-order events by state rank, poll when unsure.
- Reversal after success: reopen the liability, send it back to the queue, require re-verification and a fresh approval. Never auto-repay.
- Sandbox test accounts simulate success, pending-then-success, pending-then-failure, success-then-reversed and timeout (see section 13).

### J. Audit ledger
- Append-only, hash-chained records. Each payment links: invoice image and field crops, extracted values and confidences, every check result, the approval record (plan hash, challenge, transcript, timestamp), transfer ID, and every webhook event.
- An auditor view lets a reviewer click any payment and walk back to the ink. This answers "how would an auditor trace a decision to what is on the page".

### K. Evaluation harness (the scoreboard)
- A generator makes labelled mutations from clean invoices: renumbered, reformatted dates, respelled vendor, shuffled lines, amount in words only, swapped account, altered digits, mismatched names, plus 100 clean recurring-order controls. Mutate at the text/field level and run about 40 through the full pipeline offline; pushing 200 images through Vision live is infeasible, and we say so.
- Report a confusion matrix, catch rate and false-block rate per check, and a threshold sweep. Hold the chosen threshold with a margin.
- A teammate who has not seen the checks plants the traps for a blind run, to resemble the curveball.
- Report how HOLD/ASK outcomes are counted under both interpretations until the organisers answer.

### L. Voice layer
- Saaras for the owner's spoken approval and digits (code-mixed Tamil/Hindi/English). Bulbul for the plan read-back and reasons (check the current language list before choosing demo languages).
- All spoken text comes from templates with variables, so wording is reviewable and no model improvises.
- Native-speaker review of every Tamil and Hindi template before the demo.

### M. UI
- Owner view: batch table with outcome chips, reasons in his language, the proposed plan, an approve step, and payout status updating from webhooks.
- Audit view (section J) and scoreboard view (section K).
- Officer-style side-by-side: invoice crop beside the extracted value for ASK items.

### N. Synthetic data
- A generator renders invoices in three scripts, printed and handwriting-style, with planted traps.
- Bind vendors to Cashfree's published test data: bank accounts JOHN DOE `026291800001191`, TOM WELLS `1233943142`, BOB HOPE `388108022658` (name sent determines the tier: 100/85/70/38). Only three test accounts exist for bank verification, so other vendors use a **local, disclosed fixture** for their GST/legal names. Test GSTINs and Udyam numbers are published.
- Payout accounts for success, pending, failure and reversal come from the Payouts test table.

### O. Platform choice (undecided)
- **Custom:** FastAPI backend plus a web UI (browser mic for Saaras, audio playback for Bulbul).
- **Relay:** Cashfree's agent canvas calls our backend through an HTTP action, and handles the live call in the demo.
- The briefing says a live call in an Indian language is shown; the problem statements say end-to-end demo ending in a payout. **Ask the desks which is required.** Our core (sections A to K) is the same either way.

## 7. Demo plan (10 minutes including Q&A)

| Time | Beat |
|---|---|
| 0:00-1:00 | Problem: Raghu, Coimbatore, last month's fake account number |
| 1:00-3:00 | Batch of 8 invoices processed; outcomes appear with reasons in Tamil/Hindi |
| 3:00-4:30 | Failure case: the doctored invoice is blocked; owner hears why in his language |
| 4:30-6:00 | Plan under limited cash with the regret table; voice approval with spoken digits; payouts fire |
| 6:00-7:30 | Webhooks land; one reversal arrives; the agent reopens it and does not repay |
| 7:30-8:30 | Scoreboard: traps caught versus clean invoices wrongly held, on a batch we did not tune on |
| 8:30-10:00 | Q&A |

Illustrative batch (hand-checked total Rs 96,000): A 12,400 + B 18,000 + C 9,600 + D 21,000 (disguised duplicate) + E 15,000 (arithmetic wrong) + F 11,000 (account changed) + G 5,000 (name mismatch) + H 4,000 = Rs 96,000. Clean and payable: A, B, C, H = Rs 44,000, so a Rs 30,000 cash limit forces a real ordering decision.

Spoken lines, Hinglish (Tamil version to be native-checked): refusal "Yeh bill pehle ho chuka hai, sirf number badla hai. Paisa nahi bheja." Approval prompt "4 payments, total 22,000 rupaye. Haan boliye aur yeh code bolein: 4-7-2-9."

## 8. What we chose NOT to use (design-note material)

| Not used | Why |
|---|---|
| A Sarvam chat model for decisions or explanations | Team rule; arithmetic and policy must be deterministic and explainable |
| A learned fraud model | No training data; thresholds from a measurable sweep are auditable |
| Invoice-number-only duplicate check | Defeated by renumbering |
| Cashfree name-match score as the only gate | Canned in sandbox, activation unconfirmed; we match names ourselves |
| Auto-repay on reversal | Money that left cannot be un-sent safely; needs re-verification and approval |
| Reverse penny drop for the call-back proof | Not confirmed in sandbox; call-back to the number on file instead |
| Full Aadhaar anywhere | Red line; last four only |

## 9. Cashfree facts (verified in docs, with the gaps)

| Area | Verified | Unverified / gap |
|---|---|---|
| Bank verification | `POST /verification/bank-account/sync`; test accounts and tiers (100/85/70/38 by the name sent) | name-match activation; no NO_MATCH or invalid test row |
| GST / Udyam | endpoints and test data (valid, invalid, cancelled, not found) | sandbox behaviour beyond the table |
| Payouts v2 | beneficiary, transfer, status values (incl. REVERSED), webhook events, duplicate `transfer_id` returns REJECTED | how to fund a sandbox balance; whether reversal webhooks fire; host conflict between `sandbox.cashfree.com/payout` and `payout-gamma` |
| Webhook signature | base64 HMAC-SHA256 over timestamp + raw body | page conflicts; test with a real delivery |
| Payment Links (PS2 backup) | partial payments, expiry, `link_amount_paid`, `PAYMENT_LINK_EVENT` | how to complete a sandbox link payment; signature scheme |

## 10. Risks and mitigations

| Risk | Mitigation |
|---|---|
| Payouts sandbox can't be funded or reversal webhooks don't fire | Smoke-test in the first 20 minutes; ask the desk; if it fails, switch to the PS2 backup |
| Vision latency or handwriting errors | Multi-read stability, cached demo batch, ASK on instability |
| Wrong threshold causes false blocks on unseen batch | Threshold sweep, margin, blind trap set, narrow ASK |
| HOLD/ASK counted as a block by the scorer | Ask organisers; measure both ways |
| Voice approval spoofed | Challenge-bound plan hash; disclose limits; button fallback |
| Sandbox answers are canned | Synthetic vendors mapped to published test data; disclose fixtures |
| Over-scope for 4 hours | Critics estimate about 14 build hours per take; build ONE pipeline and ONE evaluation corpus, not three; cut in the order in section 11 |
| Our mutation set is circular | Lead with logical invariants and clean-control false-block rate; label the rest as our own tests |
| Fresh batch's vendors are not in sandbox GST/Udyam data | `UNVERIFIABLE` goes to ASK, not BLOCK; disclose canned results |
| Hard-coded test values (cash limit, GSTINs, thresholds) break on the unseen batch | Keep them in config; never hard-code test GSTINs or Rs 30,000 |
| Venue Wi-Fi blocks ngrok webhooks | Phone hotspot for the laptop; poll status as a fallback |
| Noisy room hurts Saaras | Typed-digit fallback; short phrases; headset mic |

## 11. Team split (5 people)

| Person | Owns |
|---|---|
| 1 | Vision pipeline, multi-read, preprocessing, field crops |
| 2 | Normalisation, integrity checks, fingerprint and duplicate engine |
| 3 | Cashfree integration: verification, payouts, state machine, webhooks |
| 4 | Voice (Saaras/Bulbul), approval protocol, templates, UI |
| 5 | Synthetic data, mutation harness and scoreboard, audit ledger, demo and design note |

Timeline: by 12:15 a clean invoice goes through to a sandbox payout end to end; by 1:30 all checks and the decision engine; 2:15 planner, approval and reversal handling; 3:00 scoreboard and rehearsal; 3:30 freeze.

First 30 minutes, two people in parallel (settles the biggest unknowns): (1) fund the sandbox Payouts balance, add a beneficiary, fire a Rs 1 transfer to the success test account, read the result, and capture a real webhook with its signature headers; (2) create a Rs 500 Payment Link, pay it through the hosted page and capture the webhook (this decides the PS2 fallback). If the Payouts step fails and cannot be fixed with the desk, switch to the fallback.

Scope cuts, in order: the solver's regret table, then the audit viewer polish, then the spoken-digit approval (keep a button), then the scoreboard's threshold sweep. Never cut: arithmetic and duplicate checks, bank verification with our own name match, the real sandbox payout, the idempotent state machine, and the clean-control false-block measurement.

## 12. Definition of done mapped to the brief

- **Solid:** reads a batch, verifies one vendor's account, completes a sandbox payout.
- **Strong:** catches duplicates, arithmetic errors and changed bank details; owner approves in his own language.
- **Exceptional:** payment ordering under cash and deadlines; failure and reversal without double payment (plus the scoreboard as our extra).

## 13. Sandbox test data we will use

- Bank verification: accounts above; names to send for tiers: "john doe" 100, "john d" 85, "j doe" 70, "jane d" 38 (and the equivalents for the other two accounts).
- Payouts: success account `000100289877623` (SBIN0008752; docs conflict), pending then success `00224412311300` (YESB0000001), pending then failure `7766666351000` (YESB0000001), success then reversed `7766671735000` (SBIN0000004) and `02014457596969` (CITI0000001). Confirm each against the Payouts test-data page.
- GSTIN valid `29AAICP2912R1ZR`; invalid `29AAIZP2912R1ZR`. Udyam success `UDYAM-UP-43-1234567`, not found `UDYAM-MH-43-1234567`, cancelled `UDYAM-KA-43-1234567`.

## 14. Competition and where we sit

- "Hisaab" (public repo, 11 Oct): duplicates, bank-change flags, arithmetic, approval chain; payment mocked; no MSME deadlines, cash ordering or real payout.
- Others tackle invoice matching without duplicate/bank/payout logic, or merchant-side reconciliation.
- Absence from a README is weak evidence; other teams may be building the same thing today.

## 15. Questions to ask the desks

1. Is Relay required, or can we build custom? Is a live call required for PS3?
2. Does Sarvam Vision count as allowed input under the "speech only" rule?
3. How do we fund a sandbox Payouts balance, and which host is canonical for v2?
4. Do reversal test accounts deliver `TRANSFER_REVERSED` webhooks, and when?
5. Is bank-verification name match enabled on our test account?
6. How is the held-out batch delivered, and does HOLD count as caught or blocked?

## 16. Open items before we commit

- Wave-2 verdict is in (section 3). Remaining: the desk questions below and the first-30-minute payout and link test.
- The questions above.
- A native-speaker review of Tamil and Hindi templates.

## 17. Fallback

If Payouts can't run in the sandbox, or the critics favour another problem statement: PS2 on Payment Links only (a say-do claim ledger with a cash-in window scheduler, a proxy audit and the 360-dials-a-day arithmetic as the framing). Its queue re-forming on payment webhooks is the demo moment. Caveat from the critics: PS2's only money rail is a Payment Link whose sandbox payment completion and webhook signature are unverified, so test that first.

Second fallback: PS1 with an offline invariant gate (PAN structure, checksums, digits versus words) and a Rs 500 Payment Link to fund, if Kannada handwriting reads well in a 30-minute Vision test and the link payment can be completed. The PAN fifth-character rule must be soft (a flag, not a block), because many names have no surname and transliteration is ambiguous.

## 18. What is still unverified (do not present as fact)

- Everything marked unverified in section 9.
- The 43B(h) effective date and whether unregistered micro/small suppliers are covered.
- Kannada and Tamil handwriting accuracy of Sarvam Vision.
- That other teams won't land on the same mechanisms.
