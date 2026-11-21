# TijoriPay: demo notes

**PS3: pay the right bill, to the right person.** These notes are for whoever presents. They cover the 10-minute flow, one invoice traced end to end through real OCR output, what each component does, and the questions judges are likely to ask. Click-by-click script: [DEMO_FLOW.md](DEMO_FLOW.md). Design rationale: [DESIGN_NOTE.md](DESIGN_NOTE.md).

**Pitch in one line:** a small business owner gets bills in Tamil, Hindi and English, some of them doctored. TijoriPay reads them, catches the bad ones with checks it can explain, decides what to pay with the little cash available, gets a replay-proof approval in the owner's language, and pays through Cashfree without ever paying twice.

---

## 1. Before going on stage (5 minutes)

```powershell
.venv\Scripts\python -m pytest -q
```

```powershell
$env:PANCH_VISION_OFFLINE = "1"; .venv\Scripts\python -m uvicorn app.main:app --port 8000
```

```powershell
$env:PYTHONUTF8 = "1"; .venv\Scripts\python scripts\demo_check.py
```

- The last command drives every path against the running app: **62/62 PASS** on 21 Nov. It costs a few Sarvam calls, then resets the demo.
- Open http://localhost:8000. Hindi is the default owner language; the tabs at the top switch to தமிழ் or EN.
- **Demo PIN: 2468** (a test value).
- Payouts show **simulated**: our Cashfree Payouts test account has no funds yet, so `payout_mode` is `sim`.
- Have `data/demo/` open in a file window for the upload moment.

---

## 2. The flow (10 minutes)

| Time | Click | What's on screen | Say |
|---|---|---|---|
| 0:00 | (page open) | 8 bills ₹96,000 · 4 ready ₹44,000 · 1 needs you | "A small manufacturer. Eight bills this week in three languages, and ₹30,000 in the bank." |
| 0:40 | Upload `inv_B_hi.png`, then **Read with Sarvam Vision** | The bill comes back **BLOCK · DUP_EXACT** | "Sarvam Vision reads a Hindi bill. It's a second scan of bill B, which we already have, so it's blocked. We match the goods, amount and date, not the invoice number." |
| 1:30 | Click **E**, then ▶ | "Subtotal plus tax is 14,160, but the bill asks for 15,000. Blocked." (in Hindi) | "Every decision has a reason in the owner's language, and Bulbul can read it out." |
| 2:10 | Click **D**, then **G** | D: same goods, amount and date as paid bill KE/0312. G: "the bank says this account belongs to 'BENE AC HOLDER', not Lakshmi" | "D is a renumbered duplicate. For G, a live Cashfree Secure ID check says the account belongs to someone else." |
| 3:00 | **Step 1: Call vendor on the number on file**, ▶ Bulbul, type or say "seven seven two three", **Submit** | Called xxxxxx1234 (vendor master); the invoice's number xxxxxx9876 is ignored. **CALLBACK_MISMATCH**: 7723 vs 1191 | "The invoice says pay a new account. A fraudster controls that account *and* the phone printed on the bill, so we call the number we already had. Bulbul asks, Saaras hears, code compares. No match, so the bill is blocked for good." |
| 4:30 | **Step 2: Plan payments** with ₹30,000 | Pay **H + B, ₹22,000** protected; earliest-first would protect **₹16,400** | "MSME law: micro and small suppliers must be paid within 15 days, or the deduction is lost. We protect the most rupees with the cash we have." |
| 5:30 | **Step 3:** ▶ read-back, say or type "हाँ, 2 बिल, 22,000, कोड x-y-z", **Check**, PIN 2468, **Confirm PIN** | "Confirmed. Now tap your PIN", then approved | "The approval is bound to a hash of this exact bundle, lasts 2 minutes and works once. Voice is the conversation; the PIN is the authority." |
| 6:30 | **Step 4: Pay ₹22,000 via Cashfree**, then **Reconcile now** ×2 | B and H go SENT → PENDING → **SUCCESS** (simulated) | "A 200 from the API means submitted, not paid. We record the intent first, poll instead of resending, and count a bill as paid only at SUCCESS plus COMPLETED." |
| 7:30 | **Simulate reversal** on H | H becomes **REVERSED**, and the bill reopens as ASK: "payment came back… not re-sent automatically" | "The money came back. We never repay automatically; it goes back through checks and a fresh approval." |
| 8:15 | **Scoreboard**, then **Audit ledger** | 4/4 traps blocked, 4/4 clean paid, 0 held. Hash chain **intact** | "On 40 of our own test cases: 20/20 traps blocked, zero false blocks on clean bills, measured." |
| 9:00 | Q&A | — | See section 5 |

---

## 3. One invoice, end to end, on real OCR: bill B (Hindi)

This trace uses **Sarvam Vision's actual output** for `data/demo/inv_B_hi.png`, recorded on 21 Nov and saved in [tests/contract/vision_read_inv_B_hi.json](../tests/contract/vision_read_inv_B_hi.json). The source of truth for what's printed on the invoice is [data/fixtures/demo_batch.json](../data/fixtures/demo_batch.json) (id `B`). **Every field below matches it.**

### 3a. What Sarvam Vision read (Extract, basic mode, our fixed schema)

| Field | Printed on the bill (native, kept as evidence) | Canonical value used by the checks | Confidence |
|---|---|---|---|
| Vendor | श्री गणेश पैकेजिंग | key `kns pkjn` (transliterated, phonetic) | 0.9999 |
| GSTIN | 09AAKFG4321D1ZO | same (never translated) | 1.0 |
| Invoice no. | SGP/0093/2026-27 | `sgp-93@fy2026-27` (financial year kept) | 1.0 |
| Date | **11 नवंबर 2026** (Hindi month) | 2026-11-11 | 1.0 |
| Line | Corrugated box 5-ply · **६००** × **३०** = **१८,०००** (Devanagari digits) | 600 × 30 = 18000 | read stable |
| Subtotal / total | 18,000 / 18,000 | 18000 / 18000 | 1.0 / 1.0 |
| Amount in words | **अठारह हज़ार रुपये मात्र** | 18000 | 0.9991 |
| Payee | Shree Ganesh Packaging | same | 1.0 |
| Account / IFSC | XXXX7623 / SBIN0008752 | full number kept in memory only, never logged | 1.0 / 1.0 |
| Phone on invoice | 9415022233 | recorded, **never used for call-backs** | 1.0 |
| Language | — | hi-IN (detected) | — |

Three reads (the original image plus two preprocessed versions) agreed on every field, so every field is marked `stable=True`.

### 3b. What the gate did with it

1. **Arithmetic:**
   - line 600 × 30 = 18,000 ✓
   - lines sum to the subtotal ✓
   - subtotal + tax (none printed, and no GST lines) = total ✓
   - **the words अठारह हज़ार equal the figures 18,000** ✓
   - GST split: no GST was charged, so nothing to check ✓
2. **Duplicates:** the vendor is found by GSTIN, so this is Shree Ganesh (marked recurring). Last month's bill SGP/0087 has identical goods and amount but is **30+ days earlier from a recurring vendor**, so it's a legitimate repeat, not a duplicate ✓
3. **Vendor lane:** the account and IFSC match the verified account on file, so the lane is **KNOWN**, and no bank check is needed for a known, verified account ✓
4. **Names:** the payee "Shree Ganesh Packaging" matches the legal name, scoring 100 ✓
5. **Decision:** **PAY**. B is small (Udyam), invoiced 11 Nov, so the deadline is 26 Nov, 5 days away. The planner puts it in the bundle.
6. **The second scan:** uploading the same image again gives identical economic content (vendor, goods, amount, date), so it's **BLOCK DUP_EXACT**. One bill, one payment.

### 3c. A trap through the same path (live, 21 Nov)

- **The test:** a freshly rendered copy of E, with a new invoice number so it had never been cached, went through **live** Vision in 7–10 s.
- **What Vision read:**
  - lines 12,000;
  - CGST 1,080 and SGST 1,080, but no tax-total line;
  - total 15,000;
  - words "Fifteen Thousand".
- **What the gate did:** it added up the GST lines (2,160): 12,000 + 2,160 = 14,160 ≠ 15,000, so **BLOCK ARITH_TOTAL**.
- **Why the words don't save it:** they match the inflated total, which is exactly how this kind of fraud looks.

### 3d. Known OCR limit (handwriting style, invoice G)

- **What happened:** on G (handwriting-style font, Tamil), Vision read the GSTIN with **one extra digit** and flagged four fields unstable across the three reads.
- **What the gate did:** the bad GSTIN fails the format check, which is a question, never a silent pass. G is blocked anyway by the bank-name mismatch.
- **What to tell judges:** shaky reads become an ASK; they never slip through.

---

## 4. Components, end to end

```
invoice image/PDF
  └─ A. Reading ── Sarvam Vision Extract (basic mode, string schema) ×3 reads ─ cache by file hash
       └─ B. Normalise ── Indic digits, lakh/crore, Hindi/Tamil words, dates, FY-safe invoice no., transliterated names
            └─ C. Invariants ── line, subtotal, total, words, GST split (BLOCK) · soft checks (ASK)
            └─ D. Duplicates ── economic fingerprint, exact / near / same-number, earlier bill in batch wins
            └─ E. Vendor lanes ── KNOWN / CHANGED_ACCOUNT / NEW_VENDOR · Cashfree Secure ID (bank, GSTIN, Udyam)
                 └─ E2. Call-back ── vendor-master phone · Bulbul asks · Saaras hears · code compares
            └─ F. Decide ── PAY / ASK / BLOCK (+ DEFER from the planner), codes + evidence + template
  └─ G. Planner ── cash + MSME 43B(h) deadlines → exact subset search
  └─ H. Approval ── bundle hash + nonce + 3-digit code · voice/typed confirm · PIN tap · 2 min · single use
  └─ I. Payouts ── Cashfree Payouts v2 · deterministic transfer_id · INTENT first · UNKNOWN → poll · ledger
       └─ I2. Status ── 60 s sweep + signed webhooks · reversal reopens, never repays
  └─ J. Audit ── append-only, hash-chained log of every step
  └─ K. Scoreboard / eval ── demo batch + 40 mutated cases
  └─ L. Voice ── Bulbul TTS, Saaras STT, ta/hi/en templates
  └─ O. Relay ── optional signed triggers to a Cashfree Relay agent (call-back, alerts)
  └─ M. UI ── FastAPI + one page: bills, reasons, 4 steps, scoreboard, audit
```

| Component | Code | What it does | External service |
|---|---|---|---|
| **A. Reading** | `panch/reading/` (PR 1) | Runs Extract on the original image plus binarised and upscaled versions; agreement across reads marks a field stable; caches by file hash; demo runs offline from the cache | **Sarvam Vision** (`doc_ai.extract`, basic mode) |
| **B. Normalise** | `panch/normalise/` | Turns Tamil/Devanagari digits, ₹ formats, lakh/crore, number words, Hindi/Tamil months and invoice numbers into exact values. Never guesses; unreadable means None, which becomes ASK | — |
| **C. Invariants** | `panch/checks/` | Line arithmetic, subtotal, total (falling back to the sum of GST lines), words vs figures, CGST/SGST vs IGST by state; soft checks for GSTIN format, IFSC, tax rate, limit | — |
| **D. Duplicates** | `panch/fingerprint/` | Fingerprint of vendor, items (text compared on letters and digits only), total, date and PO. Exact → BLOCK; near → ASK; same number in the same FY → BLOCK; a recurring bill in a new month passes | — |
| **E. Vendor and bank** | `panch/vendors/` (PR 3) | Lanes; our own name match (tokens, initials, phonetics) with the threshold triangle; fraud-code block; freezes the vendor's other bills during an account change | **Cashfree Secure ID**: bank-account sync, GSTIN, Udyam |
| **E2. Call-back** | `panch/vendors/callback.py` | Uses only the master phone; one answer per call; a mismatch is final; a match still needs the owner's PIN | **Bulbul** (asks), **Saaras** (hears), **Relay** (places the call, if configured) |
| **F. Decide** | `panch/decide/` | Any BLOCK wins, otherwise ASKs, otherwise PAY. Deterministic; every outcome carries codes, evidence and a template key | — |
| **G. Planner** | `panch/planner/` | Deadline = invoice date + 15 days (or the agreed term, at most 45), micro and small only; picks the subset under cash that protects the most rupees; shows the naive plan for comparison | — |
| **H. Approval** | `panch/approval/` | SHA-256 over the canonical bundle; 3-digit code; voice check needs yes + count + total + code; PIN is the authority; 2-minute expiry, single use, lock after 3 wrong PINs | **Bulbul** read-back, **Saaras** for spoken approval |
| **I. Payouts** | `panch/payouts/`, `panch/cashfree/` (PR 3) | `transfer_id` = `pn_` + 32 hex; INTENT before sending; timeout or 5XX means UNKNOWN; a duplicate answer means fetch the original; 4XX on a poll is never FAILED; one active transfer per invoice; sandbox hosts only | **Cashfree Payouts v2**: beneficiary, transfers, status |
| **I2. Status and webhooks** | `panch/engine.py`, `panch/cashfree/signature.py` | 60 s sweep; HMAC-checked webhooks, deduplicated and applied by state rank; reversal reopens the bill | Cashfree webhooks (needs a public URL; the laptop demo uses the sweep) |
| **J. Audit** | `panch/audit/` | Each entry hashes the previous one; editing any entry breaks the chain; no full account numbers | — |
| **K. Eval** | `panch/eval/`, `scripts/run_eval.py` | 20 clean controls (8 legitimate look-alikes) + 20 planted traps → [EVAL_REPORT.md](EVAL_REPORT.md) | — |
| **L. Voice** | `panch/voice/`, `templates/{hi,ta,en}/` | Every sentence comes from a template. Amounts get Indian commas; identifiers are shown as written | **Bulbul**, **Saaras** |
| **O. Relay** | `panch/relay/`, [RELAY.md](RELAY.md) | Signed events out (`batch_ready`, `callback_requested`, `bill_blocked`, payout events); a signed transcript comes back in; Relay never decides | **Cashfree Relay** (off until `RELAY_WEBHOOK_URL` is set) |
| **M. UI** | `app/main.py`, `app/static/index.html` (PR 4) | Bills table with reasons, the four steps, scoreboard, audit, upload, language tabs, voice orb | — |

**Tests:** 265 unit and API tests, plus `scripts/demo_check.py` (62 live checks, Relay included through a local stand-in).

---

## 5. Likely questions

**What if Vision misreads an amount?**
- **Three reads must agree.** We read each image three times (original, binarised, upscaled) and a field counts only if all three agree. Otherwise it's unstable, which means ASK.
- **The arithmetic catches it.** A misread total also breaks the arithmetic checks.
- **No guessing.** We never "correct" a value; uncertainty goes to the owner.
- **Example:** on G, Vision got the GSTIN wrong, and it was flagged, not trusted.

**Why not use Extract's "advanced" mode?**
It "checks that line items add up to the total", which could quietly repair exactly the arithmetic fraud we're trying to catch. We read what's printed, and our code does the arithmetic.

**Why not an LLM to decide or explain?**
Money decisions must be deterministic and explainable. The same input always gives the same output with the same reason. Sarvam reads, hears and speaks; it never decides. Every sentence is a reviewed template.

**Why not translate the invoice?**
Translating GSTINs, invoice numbers, amounts or dates can corrupt them. We extract in the original script, convert to canonical values in code, and keep the native text as evidence.

**How do you catch a duplicate with a new invoice number?**
By economic content: same vendor (found by GSTIN), same goods, quantities and rates, same total, and the same date or PO. D is caught this way. A recurring supplier's identical bill next month is correctly paid.

**Why call the number on file, not the one on the invoice?**
Whoever forged the bank details also controls the phone printed on the forged invoice. The vendor-master number reaches the real vendor. And a mismatch is final, so retrying until it matches doesn't work.

**Cashfree gives a name-match score. Why your own?**
On our test account Cashfree's score comes back empty (the feature isn't enabled), and we want an explainable threshold anyway: 85 or more passes, 60–84 asks, under 60 blocks. Cashfree's tier is kept as evidence.

**Can a voice clone approve a payment?**
Not on its own. Voice confirms what's being approved (count, total, a fresh code bound to the bundle hash). The authority is a PIN tap on the same hash, it works once, and it expires in 2 minutes. We say openly that there's no speaker verification.

**How do you guarantee no double payment?**
- **Same input, same transfer ID.** The `transfer_id` comes from the bill itself, so the same bill always gets the same ID, and Cashfree rejects a duplicate ID.
- **Intent first, no resend.** The intent is recorded before sending. A timeout means UNKNOWN, and we poll Cashfree instead of resending.
- **The ledger.** It allows one active transfer per invoice.
- **Duplicates in the batch.** Two scans of one bill can't both be paid: the earlier one wins.
- **Tested.** A test replays 100 shuffled, duplicated event sequences and never sees a second transfer.

**What happens on a reversal?**
The bill reopens as unpaid with the reason, goes back through verification, and needs a fresh approval. We never repay automatically, because a reversal often means the account itself is wrong.

**Is the payout real?**
- **What reached Cashfree:** the live sandbox call created the beneficiary, and Cashfree accepted transfer `667850829` (RECEIVED).
- **Why it was rejected:** `ERROR_SELECTING_FUND_SOURCE`, because our test Payouts account has no fund source and only Cashfree can add one.
- **What the demo shows:** the success and reversal steps run in simulated mode through the same state machine and ledger, and are labelled.
- **When funded:** switching back to live is one config line.

**Where does Relay fit?**
- **What it does:** Relay is the orchestration and voice layer. When the owner asks for a call-back, TijoriPay sends a signed event to a Relay agent, which can place the call; the transcript comes back signed, and our code decides.
- **What it gets:** only the master phone and the prompt, never accounts or the expected digits.
- **In this demo:** it's off until the agent's URL is configured. The full path is tested against a local stand-in.

**How do you know it doesn't block good bills?**
On 40 mutated cases (20 clean, including 8 look-alikes such as recurring bills, name spelling variants, the same purchase order twice, and Devanagari figures): 0 false blocks and 0 false holds. We claim exactly that: "zero false blocks on our clean controls, measured". This is not a claim about unseen data.

**What about the unseen (curveball) batch?**
Upload it, and Vision reads it live in about 10 seconds per page. Anything uncertain becomes ASK, never PAY. If time is short, pre-read it with `scripts/read_batch.py` and demo from the cache.

**What did you deliberately not build?**
- a chat interface, an LLM making decisions, or a learned fraud model;
- invoice-number-only deduplication;
- automatic repayment, reverse penny drop, Payment Links (that was the PS2 fallback);
- voice-only approval.

**What's not finished?**
- **A funded live payout:** blocked on Cashfree funding our test account.
- **Native-speaker review:** the Hindi and Tamil wording.
- **One threshold decision:** should "J Doe" vs "John Doe" pass or ask?
- **The real Relay agent:** still to be built on the canvas.
