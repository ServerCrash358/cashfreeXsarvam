# SYSTEM.md: problem, rules and requirements

Paraphrased from the organisers' problem-statement PDF and builder briefing (21 Nov 2026). Where something is not confirmed, it says so.

## 1. The event

| Item | Value |
|---|---|
| Event | Sarvam x Cashfree Buildathon, Cashfree office, Bengaluru, Sat 21 Nov 2026 |
| Scale | about 150 builders in about 30 teams of ~5 |
| Build | 11:30 to 3:30 (code freeze), lunch 1:30 (optional) |
| Round 1 | 4:00, five panels, **10 minutes per team including Q&A**, hard stop |
| Final | 6:00, six teams (top team per panel + one wildcard), 12 minutes |
| Winners | 7:20 PM. Prize pool Rs 3,00,000+ cash and credits |
| Help | onboarding desk (accounts), Relay team (canvas, actions, webhooks), Sarvam team (voice, credits), IT (Wi-Fi), WhatsApp group |

Note: an earlier agenda said 13-minute demos; the later briefing says 10. We use 10.

## 2. What the organisers want (all problem statements)

- Messy, multilingual, real-world input that ends in a **verified, settled or safely refused** sandbox payment. A demo that stops at extraction or scoring is incomplete.
- Submission:
  - a working end-to-end demo ending in a sandbox payment or payout;
  - a short note on key design choices, **including what we chose not to use and why**;
  - one success case and one failure case the agent handled.
- **Demo-day curveball:** a fresh batch we have never seen (new handwriting, names, planted traps). The agent is tested on it.
- Ground rules: synthetic data only; sandbox only (Cashfree answers only to its published test data, so synthetic documents must be built around it); Sarvam where Indian languages matter; Cashfree where money and verification matter; every decision explainable to a non-technical reviewer.
- From the Relay briefing: "speaks Indian languages, takes real decisions and finishes with a payment"; no chatbots (the agent talks, decides and acts); a demo shows a **live call in an Indian language** and **the money on screen**. Whether the live call applies to PS3 is an open question (section 7).

## 3. Problem Statement 3: pay the right bill, to the right person

**Persona.** Raghu runs a hardware wholesale business in Coimbatore. About sixty invoices a week arrive in Tamil, Hindi and English, some printed, some handwritten on delivery slips with bank details scribbled underneath. His accountant retypes them into a banking portal every Friday. Last month an invoice from a familiar vendor arrived with a new account number. It looked fine. It was not the vendor's account.

**Challenge.** Read a pile of multilingual invoices, pay the right vendors the right amounts in the right order, and know when to stop and say no.

**What makes it hard.**
- Invoices disagree with themselves: totals, tax and line items drift; amounts appear in figures and in words, in lakh notation and regional scripts.
- The same invoice comes back in disguise: new number, different date format, slightly different spelling.
- A familiar vendor with new bank details is the oldest trick.
- Time has legal weight: registered micro and small suppliers must be paid within 15 days (no written agreement) or within the agreed term up to 45 days (written agreement) for the buyer to claim the expense in that year. Cash is limited, so the order of payment matters.
- Money that has left cannot be un-sent: retries, failures and bank reversals must never become double payments.

**The moment they want to see.** A doctored invoice goes in; the agent declines to pay it and tells the owner why in his own language, while the clean invoices go out and come back confirmed.

**Red lines.**
1. Money never moves to an account not verified as belonging to the claimed vendor.
2. Approval cannot be spoofed, replayed or given by accident.
3. A retry must never become a second payment.
4. Every payment traces to its invoice, its checks and its approver.

**Questions the design must answer.**
1. When should the agent pay on its own, and when must it stop and ask?
2. How should it treat a familiar vendor whose bank details have changed?
3. With limited cash and deadlines that carry tax consequences, what gets paid first?
4. What happens when a payout fails, or is reversed after it looked successful?

Our answers are in [ARCHITECTURE.md](ARCHITECTURE.md) (sections F, E, G and I respectively).

**Levels.**
- **Solid:** reads a batch, verifies one vendor's account, completes a sandbox payout.
- **Strong:** catches duplicates, wrong arithmetic and changed bank details, with the owner approving in his own language.
- **Exceptional:** decides the order of payment against cash and deadlines, and handles failure and reversal without ever paying twice.

**Curveball for PS3.** Invoices with planted problems: a duplicate, a changed account, wrong arithmetic, a mismatched name. Scored on how many are caught **and** how many good invoices are wrongly blocked.

**Building blocks named by the organisers.** Sarvam: Vision (invoice reading), translation and chat models, Saaras and Bulbul for voice approvals. Cashfree: Secure ID (bank account verification with name match, PAN, GST), Payouts, Webhooks. We do not use the chat models (team rule).

## 4. Rules and facts that shape the design

- **43B(h) / MSMED rule (verified via secondary sources, statute text not read):** 15 days with no written agreement; the agreed term, capped at 45 days, with one. Applies to Udyam-registered micro and small enterprises; medium enterprises and traders are excluded. Effect: late payment moves the deduction to the year of payment. Effective date conflicts across sources (UNVERIFIED). We model "rule applies" as a per-vendor flag.
- **Aadhaar:** show and store last four digits only.
- **Team rule on Sarvam:** Vision reads, Saaras hears, Bulbul speaks. No Sarvam chat model. Decisions and amounts are deterministic; explanations are templates.

## 5. Platform: Cashfree Relay (from the briefing)

- Relay is Cashfree's agent platform inside the merchant dashboard (test mode). Left menu: Overview, Agents, Runs, Connections.
- An agent is: **trigger** (schedule, event such as payment/refund/dispute, or inbound webhook) → **decide** (prompt and rules) → **act**.
- Actions: Sarvam actions (text-to-speech, translation, data extraction), create payment link, issue refund, **HTTP action** (any endpoint, JSON body), **secret properties** for keys, **AWS Lambda** for custom code. Not supported: creating or sending images. The Relay desk can add simple API calls on the spot.
- Testing: add an inbound webhook trigger, copy its URL, send a sample event (e.g. from Postman), watch the agent run; Runs shows each run's time, duration and pass/fail. Flip Draft on when it works.
- Limits: up to 240 minutes of voice calls per account; Sarvam credits handed out on the day; test mode only; sample data only.
- Existing Relay templates: Abandoned cart, Failed payment, COD guard (voice), Refunds shield, Dispute defender, Reconciliation.
- "Every loop adds mass": Relay's context engine builds memory from signals, decisions and outcomes. For us, the vendor master (accounts, provenance, call-back results, payment history) is that memory.

## 6. Requirements

### Functional
| ID | Requirement |
|---|---|
| FR1 | Accept a batch of invoice images/PDFs (Tamil, Hindi, English; printed and handwritten). |
| FR2 | Extract vendor, GSTIN, invoice number, dates, line items, subtotal, tax, total, amount in words, bank details. |
| FR3 | Check arithmetic and figures-versus-words consistency. |
| FR4 | Detect duplicates by economic content, not invoice number. |
| FR5 | Verify the vendor (GSTIN, Udyam) and the bank account (status and bank-registered name). |
| FR6 | Quarantine changed bank details; confirm by call-back on the vendor-master phone number. |
| FR7 | Decide PAY / ASK / BLOCK / DEFER per invoice, with a reason code and a template message in the owner's language. |
| FR8 | Plan payments under a cash limit using deadlines. |
| FR9 | Obtain a bundle approval that cannot be replayed. |
| FR10 | Execute payouts idempotently; handle pending, failure, timeout and reversal without double-paying. |
| FR11 | Keep an audit trail from payout back to the invoice image. |
| FR12 | Report a scoreboard: traps caught (BLOCK) and clean auto-paid rate on a labelled batch. |

### Non-functional
- Deterministic and explainable: same input, same output; every outcome has evidence.
- The demo never waits on a Vision job live (pre-run and cache, process new files in the background).
- Works over a phone hotspot (venue Wi-Fi may block ngrok).
- Secrets only in `.env` or Relay secrets.

## 7. Open questions (record answers here)

| # | Question | Answer |
|---|---|---|
| 1 | Is Relay required? Is a live call required for PS3? | |
| 2 | Does Sarvam Vision count as allowed input under the team rule? | assumed yes |
| 3 | Does ASK/HOLD count as caught on traps, and as a block on clean invoices? | |
| 4 | How do we fund the sandbox Payouts balance? Which host is canonical for Payouts v2? | |
| 5 | Do reversal test accounts deliver `TRANSFER_REVERSED` webhooks, and when? | |
| 6 | Is bank-verification name match enabled on our test account? | |
| 7 | How is the curveball batch delivered (images, PDFs), and do we run it live? | |

## 8. Glossary

- **ASK:** the agent stops and asks the owner (uncertain, changed account, new vendor).
- **BLOCK:** a check failed; no payment; the reason is shown.
- **DEFER:** clean, but no cash left in this run.
- **Bundle:** the exact set of payments, in order, that the owner approves.
- **Fingerprint:** the invoice's economic identity (vendor, line items, total, date).
- **Quarantine:** a changed account waiting for call-back and owner approval.
- **UNKNOWN:** a payout whose outcome we have not yet confirmed (timeout, 5XX).
