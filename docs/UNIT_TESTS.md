# UNIT_TESTS.md: offline unit tests and the evaluation harness

All unit tests run **offline**: no Cashfree, no Sarvam, no network. External clients are mocked (`respx` for httpx; fakes for the Sarvam SDK). Sandbox and SDK tests live in [INTEGRATION_TESTS.md](INTEGRATION_TESTS.md).

Run: `pytest tests/unit -q`. Every number below is hand-checked; if you change one, recheck it.

## 1. Conventions

- File per module: `tests/unit/test_<module>.py`. Test IDs below (`U-NORM-1` ...) go in the test name or docstring.
- Pure functions get table-driven tests (`pytest.mark.parametrize`).
- Money is `Decimal`; compare with exact `Decimal` values, never floats.
- Every BLOCK/ASK test also asserts the reason code.

## 2. Test cases by module

### B. Normalisation (`panch/normalise`)
| ID | Input | Expected |
|---|---|---|
| U-NORM-1 | `"௧௨,௪௦௦"` (Tamil digits) | `Decimal("12400")` |
| U-NORM-2 | `"१२,४००"` (Devanagari digits) | `Decimal("12400")` |
| U-NORM-3 | `"₹ 1,25,000.00/-"` | `Decimal("125000.00")` |
| U-NORM-4 | `"1.25 lakh"` | `Decimal("125000")` |
| U-NORM-5 | `"Twelve Thousand Three Hundred Ninety Only"` | `Decimal("12390")` |
| U-NORM-6 | `"One Lakh Twenty Five Thousand"` | `Decimal("125000")` |
| U-NORM-7 | `"बारह हज़ार चार सौ"` | `Decimal("12400")` |
| U-NORM-8 | `"एक लाख पच्चीस हज़ार"` | `Decimal("125000")` |
| U-NORM-9 | `"பன்னிரண்டாயிரத்து நானூறு"` (native-check) | `Decimal("12400")` |
| U-NORM-10 | `"03-11-2026"`, `"3 Nov 2026"`, `"2026-11-03"`, `"3rd November 2026"` | all `date(2026, 11, 3)` |
| U-NORM-11 | `"03/11/26"` | `date(2026, 11, 3)` with `ambiguous=True` |
| U-NORM-12 | `"௰"` (traditional Tamil ten) | flagged, not silently parsed |
| U-NORM-13 | vendor `"M/s. Sri Murugan Hardwares Pvt Ltd"` and `"Sri Murugan Hardware"` | same phonetic key |
| U-NORM-14 | invoice numbers `"INV-0042"`, `"inv 42"`, `"42"` | same normalised number |

### C. Invariants (`panch/checks`)
Base invoice: lines (10 x 450.00) and (5 x 1,200.00); subtotal 10,500.00; tax 18% = 1,890.00; total 12,390.00; words "Twelve Thousand Three Hundred Ninety Only".
| ID | Change | Expected |
|---|---|---|
| U-CHK-1 | none | all pass |
| U-CHK-2 | line 1 amount printed 4,600 | BLOCK `ARITH_LINE` |
| U-CHK-3 | subtotal printed 10,050 | BLOCK `ARITH_SUBTOTAL` |
| U-CHK-4 | total printed 12,930 | BLOCK `ARITH_TOTAL` |
| U-CHK-5 | words "Twelve Thousand Nine Hundred Thirty" | BLOCK `ARITH_WORDS` |
| U-CHK-6 | 1 paisa rounding difference on a line | pass (within tolerance) |
| U-CHK-7 | GSTIN `27ABCFGH5678D1Z` (sandbox "valid" but malformed PAN segment) | flag `GSTIN_FORMAT` → ASK, **not** BLOCK |
| U-CHK-8 | tax rate not in configured slab list | flag `TAX_RATE` → ASK |
| U-CHK-9 | invoice date in the future | flag `DATE_IMPLAUSIBLE` → ASK |

### D. Fingerprint and duplicate routing (`panch/fingerprint`): includes the legitimate twins
| ID | Case | Expected |
|---|---|---|
| U-FP-1 | same vendor, same lines and total, same invoice date, new number `"42/2026-27"` vs `"INV-0042"` | BLOCK `DUP_EXACT` |
| U-FP-2 | same vendor, same lines in a different order, same date | BLOCK `DUP_EXACT` |
| U-FP-3 | same vendor, one quantity differs, total within 1%, date 4 days apart | ASK `DUP_FUZZY` |
| U-FP-4 | **twin:** recurring vendor, identical monthly bill Rs 9,600, dated 3 Oct and 3 Nov | PAY (no duplicate) |
| U-FP-5 | **twin:** "Sri Murugan Hardware" vs "Sri Murugan Hardwares", different GSTINs | not a duplicate |
| U-FP-6 | same content, date written `"3 Nov"` vs `"03-11-2026"` | BLOCK `DUP_EXACT` |
| U-FP-7 | fingerprint is stable across input orderings and number formats | equal fingerprints |

### E. Vendor and bank checks (`panch/vendors`, pure parts)
| ID | Case | Expected |
|---|---|---|
| U-VEN-1 | `name_at_bank` "JOHN DOE", payee "John Doe" | pass |
| U-VEN-2 | payee "J Doe" | ASK (score band 60-84) |
| U-VEN-3 | payee "Jane D" | BLOCK `NAME_MISMATCH` |
| U-VEN-4 | `account_status` INVALID | BLOCK `BANK_INVALID` |
| U-VEN-5 | invoice account not in vendor's known accounts | ASK `ACCOUNT_CHANGED` |
| U-VEN-6 | **twin:** legitimate new account, bank name matches, call-back last four match | after owner approves the change → PAY |
| U-VEN-7 | same account hash under two vendors | BLOCK `ACCOUNT_SHARED` |
| U-VEN-8 | GSTIN not in fixture/sandbox data | ASK `VENDOR_UNVERIFIABLE` (never BLOCK) |
| U-VEN-9 | call-back spoken digits "four seven two nine" / "நாலு ஏழு இரண்டு ஒன்பது" (native-check) / "चार सात दो नौ" vs invoice last four 4729 | match |
| U-VEN-10 | call-back last four 4729 vs invoice 4792 | BLOCK `CALLBACK_MISMATCH` |
| U-VEN-11 | call-back uses vendor-master phone even if invoice prints another number | phone used = vendor master |

### F. Decision engine (`panch/decide`)
| ID | Inputs | Expected |
|---|---|---|
| U-DEC-1 | all checks pass, known vendor, known account | PAY-ready |
| U-DEC-2 | `ARITH_TOTAL` + `ACCOUNT_CHANGED` | BLOCK, codes include both |
| U-DEC-3 | only `DUP_FUZZY` | ASK |
| U-DEC-4 | only `LOW_CONFIDENCE_READ` | ASK |
| U-DEC-5 | `VENDOR_UNVERIFIABLE` | ASK, never BLOCK |
| U-DEC-6 | each outcome has a message key that exists in `templates/{ta,hi,en}` | true |
| U-DEC-7 | same input twice | identical output (determinism) |

### G. Planner (`panch/planner`)
Cash Rs 30,000; H 4,000 (deadline 1 day), A 12,400 (3 days), B 18,000 (5 days), C 9,600 (no deadline; medium enterprise).
| ID | Case | Expected |
|---|---|---|
| U-PLAN-1 | optimise | bundle {H, B} = 22,000; deferred A, C |
| U-PLAN-2 | naive earliest-deadline-first | {H, A, C} = 26,000; protected 16,400 |
| U-PLAN-3 | cash 50,000 | all of H, A, B, C (44,000) |
| U-PLAN-4 | vendor flagged medium/trader | no legal deadline applied |
| U-PLAN-5 | written agreement 60 days | deadline capped at 45 days |
| U-PLAN-6 | more than 25 candidates | falls back to greedy; still within cash |

### H. Approval (`panch/approval`)
| ID | Case | Expected |
|---|---|---|
| U-APR-1 | correct total, count and code within TTL | valid |
| U-APR-2 | same approval reused | invalid (single use) |
| U-APR-3 | change an amount after approval | hash changes; approval invalid |
| U-APR-4 | change order / account / cash limit | invalid |
| U-APR-5 | expired TTL (2 min) | invalid |
| U-APR-6 | "haan" without code | invalid |
| U-APR-7 | "haan... nahi" | invalid (ambiguous) |
| U-APR-8 | spoken total "22,000" vs bundle 22,000; count "do" = 2 | valid |
| U-APR-9 | bundle containing an unapproved changed-account item | cannot be created |

### I. Payout state machine (`panch/payouts`)
| ID | Case | Expected |
|---|---|---|
| U-PAY-1 | `transfer_id` | `^pn_[0-9a-f]{32}$`, length 35, ≤ 40 |
| U-PAY-2 | same invoice/account/amount/attempt | same `transfer_id` |
| U-PAY-3 | amount changes | different `transfer_id` |
| U-PAY-4 | INTENT written before the (mocked) API call | true |
| U-PAY-5 | API times out | state UNKNOWN; **no second POST** |
| U-PAY-6 | UNKNOWN, status poll says SUCCESS COMPLETED | SUCCESS; no retry |
| U-PAY-7 | UNKNOWN, status poll says FAILED | eligible for attempt 2 with a new `transfer_id` |
| U-PAY-8 | response REJECTED `DUPLICATE_TRANSFER` | fetch original; no new attempt |
| U-PAY-9 | status SUCCESS with `SENT_TO_BENEFICIARY` | not final |
| U-PAY-10 | `TRANSFER_REVERSED` after SUCCESS | REVERSED; bill reopened; no payout created |
| U-PAY-11 | duplicate webhook delivered twice | applied once |
| U-PAY-12 | `TRANSFER_SUCCESS` arrives before `TRANSFER_ACKNOWLEDGED` | ends SUCCESS; the late lower-rank event is ignored |
| U-PAY-13 | 100 random orderings of duplicated/delayed events for one transfer | exactly zero double payments |

### I2. Webhook signature (`panch/cashfree`)
| ID | Case | Expected |
|---|---|---|
| U-SIG-1 | secret, timestamp, raw body; expected = base64(HMAC-SHA256(secret, timestamp + body)) computed in the test | valid; also agrees with `Cashfree.PGVerifyWebhookSignature` |
| U-SIG-2 | body re-serialised (spaces changed) | invalid (must use raw body) |
| U-SIG-3 | wrong secret / tampered body / missing header | invalid; 401 |

### J. Audit (`panch/audit`)
| ID | Case | Expected |
|---|---|---|
| U-AUD-1 | append three entries | each `prev_hash` equals the previous `hash` |
| U-AUD-2 | edit an old entry | chain verification fails |
| U-AUD-3 | payout trace | payout → approval → decision → checks → invoice image hash |

### Privacy
| ID | Case | Expected |
|---|---|---|
| U-PRIV-1 | mask `"655675523712"` | `"XXXX XXXX 3712"` |
| U-PRIV-2 | logs after a full run | no 12-digit Aadhaar and no full account numbers |

### Additional cases (v3)
| ID | Case | Expected |
|---|---|---|
| U-NORM-15 | `"42/2025-26"` vs `"42/2026-27"` | different normalised numbers (financial year kept) |
| U-NORM-16 | GSTIN, account, IFSC with Tamil/Devanagari digits | converted to ASCII, otherwise byte-for-byte |
| U-NORM-17 | same vendor name transliterated twice (cached) | identical output |
| U-CHK-10 | vendor and buyer GSTIN both state 33; taxable 10,500; CGST 9% = 945 and SGST 9% = 945 | pass (945 + 945 = 1,890) |
| U-CHK-11 | vendor state 29, buyer state 33, CGST + SGST charged | BLOCK `ARITH_GST_SPLIT` |
| U-CHK-12 | same as U-CHK-11 but a GSTIN read is unstable | ASK, not BLOCK |
| U-CHK-13 | line 10 x 450 with discount 500 | taxable 4,000 |
| U-FP-8 | same vendor, same normalised number incl. financial year, already paid | BLOCK `DUP_NUMBER` |
| U-FP-9 | two different vendors (different GSTINs and accounts), identical amount and lines | not a duplicate |
| U-FP-10 | duplicate decision without a hard key and with only one soft signal | not BLOCK |
| U-VEN-12 | unknown vendor | ASK `NEW_VENDOR`; after GST + Udyam + bank verification and owner onboarding → `KNOWN` |
| U-VEN-13 | `CHANGED_ACCOUNT` lane | all pending payments to that vendor frozen until resolved |
| U-PAY-14 | a second active transfer for the same invoice | refused by the ledger |
| U-PAY-15 | confirmed + in-flight + new amount > invoice amount | refused |
| U-PAY-16 | transfer stuck in PENDING with no webhook | sweep polls and resolves it |
| U-PAY-17 | API returns 200 | state SENT/PENDING, invoice not marked paid |
| U-APR-10 | valid spoken confirmation but no PIN | not authorised |
| U-APR-11 | bundle above threshold or with a `CHANGED_ACCOUNT` item | needs a second approver's PIN |

## 3. Evaluation harness (scoreboard)

**Purpose:** measure what the curveball measures, honestly.

**Labelled batch (about 40 documents):**
- 20 clean, including 8 **legitimate twins** built to look guilty: monthly recurring bills, legitimate new accounts with matching bank names (call-back passes), similar vendor names with different GSTINs, amounts in words only, different date formats.
- 20 traps: 5 disguised duplicates, 5 changed accounts (call-back fails), 5 wrong arithmetic (lines, totals, words), 5 mismatched names.
- Mutations are generated at the **text/field level**; about 40 documents run through the full pipeline offline (rendering 200 images through Vision live is not feasible).
- A teammate who has not seen the checks plants a **blind** set of 10 for a final run.

**Report three headline numbers, separately:**
1. **Traps blocked** = traps with outcome BLOCK / all traps.
2. **Clean auto-paid rate** = clean invoices that entered the bundle without a question / all clean invoices.
3. **Clean falsely held** = clean invoices that got ASK / all clean invoices.

Also report: false holds (ASK on clean), false blocks (BLOCK on clean), traps that only reached ASK, per-check catch and false-block counts, and the threshold sweep for `DUP_FUZZY` and the name-match band. Show results under both interpretations of ASK until the organisers answer.

**Claim allowed:** "zero false blocks on our clean controls, measured." Never claim it for the unseen batch. Our mutation set is ours; the headline rests on true-by-construction invariants (line sum vs total, digits vs words, bank-registered name vs claimed vendor).
