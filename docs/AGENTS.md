# AGENTS.md: read this first

This repo is the team's build for the **Sarvam x Cashfree Buildathon (Bengaluru, 21 Nov 2026)**, Problem Statement 3: *pay the right bill, to the right person*. The build is called **Panch** (working name). These docs carry the full context behind every decision, so a coding agent can build without re-deriving it.

## Read in this order

1. [SYSTEM.md](SYSTEM.md): the problem, the event rules and the requirements.
2. [ARCHITECTURE.md](ARCHITECTURE.md): the technical spec. **Canonical** wherever docs differ.
3. [PLAN.md](PLAN.md): today's execution: team split, timeline, build order, demo.
4. [DEPENDENCIES.md](DEPENDENCIES.md): packages, env vars, Sarvam and Cashfree endpoints, sandbox test data.
5. [UNIT_TESTS.md](UNIT_TESTS.md): offline unit tests and the evaluation harness.
6. [INTEGRATION_TESTS.md](INTEGRATION_TESTS.md): Cashfree test-environment, Relay, Sarvam SDK and communication test suites.
7. [BUILD_PLAN.md](BUILD_PLAN.md): the full decision report and history (why PS3, what critics said).

## Red lines (never break these)

- **Money never moves to an account that has not been verified** as belonging to the claimed vendor.
- **A retry never becomes a second payment.** No resend after a timeout or 5XX until Cashfree's status is terminal.
- **Approval cannot be spoofed, replayed or given by accident.** Approval is bound to a bundle hash plus a one-time nonce.
- **Every payment traces** to its invoice, its checks and its approver (audit ledger).
- **No Sarvam chatbot or LLM decides anything.** Sarvam is used only to read documents (Vision), hear speech (Saaras) and speak (Bulbul). Amounts and decisions come from deterministic code. Every explanation comes from a template per language.
- **Amounts are `Decimal`, never `float`.** Paise precision. Round only at display.
- **Never display, log or store a full Aadhaar number** (last four only), even though PS3 rarely needs it. **Never log or display full bank account numbers** either (last four; full number only inside the beneficiary record).
- **Never commit `.env` or any key.** Use `.env.example`. Use secrets in Relay; never paste keys into prompts.
- **Synthetic data only.** Sandbox (test mode) only. No real customer data.
- **Never silently correct a read value.** Uncertainty must be visible and goes to ASK.
- **Never translate fields used for matching or money** (GSTIN, invoice number, account, IFSC, amounts, dates). Extract, canonicalise in code, keep the native string as evidence. Vendor names are transliterated, never translated.
- **Voice never authorises alone.** A PIN tap bound to the bundle hash is the authority.
- **Call-backs use the vendor-master phone only**, never a number printed on the invoice.

Build order is P0 → P3 in [ARCHITECTURE.md](ARCHITECTURE.md) section 0.

## Open questions that change the code

Ask the desks; record the answers in [SYSTEM.md](SYSTEM.md) section 7.

1. Is Relay required, and is a live call required for PS3? The core is built behind FastAPI either way.
2. Does Sarvam Vision count as allowed input under the team rule "Sarvam is only user-facing speech"? This doc assumes **yes** (it is input).
3. Does the scorer count ASK/HOLD on a planted trap as caught, and ASK on a clean invoice as a block?
4. How is the sandbox Payouts balance funded, and do reversal test accounts really send `TRANSFER_REVERSED`?

## Conventions

- Python 3.11, FastAPI, httpx, pydantic v2. Pinned versions are in `requirements.txt`.
- Checks are **pure functions**: input in, result out, no I/O. I/O lives in thin clients (`panch/cashfree/`, `panch/voice/`, `panch/reading/`).
- Every check returns `CheckResult(code, passed, severity, evidence, message_key)`. Never raise for a business outcome.
- IDs are deterministic. `transfer_id` derives from the invoice fingerprint (see [ARCHITECTURE.md](ARCHITECTURE.md) section I).
- Configuration (cash limit, thresholds, vendor flags) lives in config files, never hard-coded. No hard-coded test GSTINs or amounts in logic.
- Label anything not confirmed in docs or a real run as `UNVERIFIED` in comments and docs.
- Unit tests are offline: Cashfree and Sarvam are mocked. Integration suites run against the sandbox only when explicitly run.

## Git workflow

- Everyone pushes to `main`. Run `git pull --rebase origin main` before every push. Never force-push.
- Small commits with clear messages. Never commit `.env`, `.venv/`, generated audio, or large images (keep synthetic data generators, not outputs, unless the demo batch is small).

## Definition of done (per module)

A module is done when:
1. its pure logic has unit tests from [UNIT_TESTS.md](UNIT_TESTS.md) passing;
2. it returns reason codes and evidence, not just booleans;
3. its integration suite case (if any) has run once against the sandbox, with the result recorded;
4. it writes an audit entry for anything that affects money.

## What not to build

- A chat interface, or any free-form LLM reply.
- A learned fraud model.
- Duplicate detection on invoice number alone.
- Auto-repay after a reversal.
- A native Android app (the Pixel is not part of this build).
- Anything Payment-Link-based for PS3 (that is the PS2 fallback only).
- Anomaly-signal heuristics, reverse penny drop, multi-accountant roles, WhatsApp approvals, a vendor self-service portal, PO/GRN matching, a discount optimiser, Tally export or analytics.
- The second-approver rule is **stretch only**: cut it before anything in P3.

A one-page brief to paste into a coding agent is in [BUILD_PROMPT.md](BUILD_PROMPT.md).
