# PR 2: Invariants, fingerprint and decision engine (modules C, D, F)

**Branch:** `feat/pr2-checks-decision` · **Owner:** Teammate 2 · **Read first:** [docs/AGENTS.md](../AGENTS.md), [docs/ARCHITECTURE.md](../ARCHITECTURE.md) sections C, D, F, 5 and 7.

## Goal
The pure heart of Panch: given an `Invoice` (and vendor history), return `CheckResult`s and one `Decision` (PAY / ASK / BLOCK) with reason codes and template keys. No I/O.

## Scope
- `panch/models.py`: the shared dataclasses from ARCHITECTURE section 7 (`Outcome`, `CheckResult`, `LineItem`, `Invoice`, `Decision`). **Land this first and push to `main` early** so other PRs import it.
- `panch/checks/invariants.py`: `ARITH_LINE`, `ARITH_SUBTOTAL`, `ARITH_TOTAL`, `ARITH_WORDS` (BLOCK) and soft checks `GSTIN_FORMAT`, `IFSC_FORMAT`, `DATE_IMPLAUSIBLE`, `TAX_RATE` (ASK). GSTIN checksum is soft: sandbox test GSTINs may fail a real checksum.
- `panch/fingerprint/`: `fingerprint(inv)` and `route_duplicates(inv, history, vendor)` implementing the routing table (`DUP_EXACT` BLOCK, `DUP_FUZZY` ASK, recurring new-period PAY, similar name + different GSTIN not a duplicate).
- `panch/decide/`: `decide(inv, checks)` with the evaluation order in ARCHITECTURE section F.
- `config/thresholds.yaml`: tolerances, fuzzy thresholds, name-match bands (no hard-coded values in logic).
- `templates/{en,hi,ta}/`: one message file per reason code (placeholders only; native-speaker review later).

## Tests to implement (offline)
`U-CHK-1` to `U-CHK-9`, `U-FP-1` to `U-FP-7` (including the legitimate twins), `U-DEC-1` to `U-DEC-7` from [docs/UNIT_TESTS.md](../UNIT_TESTS.md).

## Acceptance
- All listed unit tests pass; outputs are deterministic.
- Every BLOCK/ASK carries a reason code, evidence and an existing template key.
- Fuzzy duplicates never BLOCK; `VENDOR_UNVERIFIABLE` never BLOCKs.

## Out of scope
Reading (PR 1), Cashfree calls (PR 3), voice/UI (PR 4), planner (Krish).

## Coordinate with
PR 1 (`Invoice` fields), PR 3 (bank/vendor check results feed `decide`), Krish (evaluation harness uses `decide`).
