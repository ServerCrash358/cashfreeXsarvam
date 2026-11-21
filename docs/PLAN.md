# PLAN.md: execution plan for 21 Nov

## 0. Gate: the first 30 minutes

Nothing else matters if the payout rail does not work. Two people, in parallel:

1. **Payouts smoke test** ([INTEGRATION_TESTS.md](INTEGRATION_TESTS.md) suite `IT-CF-PAYOUT`, cases P1-P3): get Payouts test credentials, fund the sandbox balance (ask the desk how), add a beneficiary on the success test account, send a Rs 1 transfer, read its status, and capture one real webhook with its signature headers.
2. **Desk questions** ([SYSTEM.md](SYSTEM.md) section 7): Relay required? Live call required for PS3? Does Vision count under our Sarvam rule? Does ASK count as caught or as a block? How to fund Payouts? Do reversal accounts send `TRANSFER_REVERSED`?
3. **Vision probe** (`IT-SARVAM` S4): run one printed and one handwritten invoice through Document Intelligence; time it; look at the output shape.

If the Payouts step fails and the desk cannot fix it, switch to the fallback (section 9).

## 1. Team split (5 people) and the four teammate PRs

| Owner | Workstream | PR | Modules |
|---|---|---|---|
| Teammate 1 | Reading and normalisation | PR 1 | A, B (`panch/reading`, `panch/normalise`) |
| Teammate 2 | Checks, fingerprint, decision | PR 2 | C, D, F (`panch/checks`, `panch/fingerprint`, `panch/decide`) |
| Teammate 3 | Cashfree integration | PR 3 | E (verification), I, I2 (`panch/cashfree`, `panch/vendors`, `panch/payouts`) |
| Teammate 4 | Voice, approval, call-back, UI | PR 4 | E2, H, L, M (`panch/voice`, `panch/approval`, `app/`) |
| Krish | Data, evaluation, audit, planner, demo | (main) | G, J, K, N, design note, rehearsal |

Each PR's task spec is in `docs/tasks/`. Shared interfaces are in [ARCHITECTURE.md](ARCHITECTURE.md) section 7; agree on them before writing code.

## 2. Timeline

| Time | Milestone |
|---|---|
| 11:30-12:00 | Gate (section 0). Shared interfaces agreed. Repo cloned by everyone, `.env` filled locally. |
| 12:00-12:45 | **Thin slice:** one clean invoice from cached Vision output → checks → PAY → bundle (button approval) → one real sandbox payout → webhook → status on screen. |
| 12:45-1:30 | All invariants, fingerprint routing, bank verification with our name match, quarantine. |
| 1:30-2:15 | Lunch at desks. Call-back flow, bundle-hash approval with voice, reversal handling. |
| 2:15-3:00 | Planner, audit, scoreboard on the labelled batch; demo batch locked. |
| 3:00-3:30 | Two full rehearsals, backup recording, design note finished. **3:30 freeze.** |
| 4:00 | Round 1 (10 minutes including Q&A). |

## 3. Build order and cuts

**Order:** thin slice → invariants → fingerprint → bank verification and quarantine → payout state machine with UNKNOWN → vendor call-back → bundle-hash approval → planner → audit → scoreboard polish.

**Cut in this order if behind:** regret table → audit viewer polish → spoken code in approval (keep the button and the hash) → threshold sweep chart.

**Never cut:** arithmetic and duplicate checks, bank verification with our own name match, one real sandbox payout, the idempotent state machine, the clean-control false-block number.

## 4. Demo batch (hand-checked numbers)

| Invoice | Vendor situation | Amount (Rs) | Expected outcome |
|---|---|---|---|
| A | micro supplier, clean, 3 days to deadline | 12,400 | PAY-ready, then DEFER (cash) |
| B | small supplier, clean, 5 days to deadline | 18,000 | PAY |
| C | medium supplier, clean, no deadline | 9,600 | PAY-ready, then DEFER (cash) |
| D | disguised duplicate of a paid invoice (new number, same delivery date) | 21,000 | BLOCK `DUP_EXACT` |
| E | lines add up to less than the printed total | 15,000 | BLOCK `ARITH_TOTAL` |
| F | known vendor, new account; call-back last four do not match | 11,000 | ASK → BLOCK `CALLBACK_MISMATCH` |
| G | bank-registered name does not match the vendor | 5,000 | BLOCK `NAME_MISMATCH` |
| H | micro supplier, clean, 1 day to deadline | 4,000 | PAY (then reversed in the demo) |

- Batch total: 12,400 + 18,000 + 9,600 + 21,000 + 15,000 + 11,000 + 5,000 + 4,000 = **Rs 96,000**.
- Clean and payable: A + B + C + H = **Rs 44,000**. Cash limit **Rs 30,000** forces a choice.
- Planner: best bundle H + B = **Rs 22,000** of deadline-protected payments. Naive earliest-deadline-first pays H, A, C = Rs 26,000 but protects only **Rs 16,400**.
- H goes to the success-then-reversed test account to show a reversal reopening the bill without repaying.

## 5. Ten-minute demo script

| Time | Beat |
|---|---|
| 0:00-1:00 | Raghu's problem; last month's fake account number. |
| 1:00-2:30 | The batch of 8 lands; outcomes appear with reasons in Tamil/Hindi (from cached reads; say so). |
| 2:30-4:00 | **Failure case:** invoice F. Call-back to the vendor's number on file; spoken last four do not match; blocked; the owner hears why in his language. |
| 4:00-5:30 | Plan under Rs 30,000 with the regret line; bundle approval: "Do bill, kul 22,000 rupaye, code 4-7-2"; payouts fire. |
| 5:30-6:30 | **Success case:** B's webhook lands (`TRANSFER_SUCCESS`, COMPLETED). H is reversed; the bill reopens and is not repaid. |
| 6:30-7:30 | Scoreboard: traps caught (BLOCK) and clean auto-paid rate on our labelled batch, including the legitimate twins. |
| 7:30-10:00 | Q&A. |

Spoken lines must be native-checked. Write amounts with commas for Bulbul ("22,000").

## 6. Submission

- Working end-to-end demo ending in a sandbox payout.
- **Success case:** invoice B, from read to `TRANSFER_SUCCESS`.
- **Failure case:** invoice F, changed account caught by the old-number call-back.
- **Design note outline:** the decision table (what blocks vs asks), why we match names ourselves, the UNKNOWN state and no-retry rule, bundle-hash approval and its honest limit, what we chose not to use (Sarvam chat model, learned fraud model, invoice-number dedupe, auto-repay, reverse penny drop), what is canned in the sandbox, the measured clean-control numbers.

## 7. Risks

| Risk | Response |
|---|---|
| Payouts can't be funded or reversal webhooks don't fire | Desk first; poll status as fallback; if dead, fallback plan |
| Vision slow or wrong on handwriting | Cached demo batch; multi-read; ASK on instability |
| Venue Wi-Fi blocks webhooks | Phone hotspot; status polling |
| Noisy room breaks voice | Typed code fallback; headset mic |
| Scope pile-up | Thin slice by 12:45; cut list above |
| Teammates' code doesn't fit together | Shared interfaces (ARCHITECTURE section 7) agreed at 11:45; integrate every hour on `main` |

## 8. Questions to ask (copy to the desk)

1. "Is Relay required, and is a live call required for PS3?"
2. "How do we fund the sandbox Payouts balance, and which host is canonical for Payouts v2?"
3. "Do the reversal test accounts send TRANSFER_REVERSED webhooks?"
4. "Is bank-verification name match enabled on our test account?"
5. "On the curveball batch, does a HOLD/ASK count as caught or as a block?"
6. "Is Sarvam Vision fine to use for reading invoices?"

## 9. Fallbacks

1. **PS2 on Payment Links** if Payouts cannot run: allowlist ranker with a proxy/swap audit, Payment Links with partial payments, the queue re-forming on `PAYMENT_LINK_EVENT`. Test link payment completion first (`IT-CF-PG` L1-L4).
2. **PS1 invariant gate** if Kannada handwriting reads well: PAN structure (soft), checksums, digits vs words, PAN verification, Rs 500 Payment Link to fund.
