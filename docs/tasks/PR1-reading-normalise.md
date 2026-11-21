# PR 1: Reading and normalisation (modules A, B)

**Branch:** `feat/pr1-reading-normalise` · **Owner:** Teammate 1 · **Read first:** [docs/AGENTS.md](../AGENTS.md), [docs/ARCHITECTURE.md](../ARCHITECTURE.md) sections A, B and 7.

## Goal
Turn an invoice image/PDF into a populated `Invoice` (see `panch/models.py` interface in ARCHITECTURE section 7) with every value normalised and every unstable field flagged. Nothing in this PR decides anything.

## Scope
- `panch/reading/vision.py`: Sarvam Document Intelligence job (`create_job` → `upload_file` → `start` → `wait_until_complete` → `download_output`), async-friendly, with a cache keyed by the file hash so the demo never waits on Vision.
- `panch/reading/multiread.py`: original + binarised + upscaled variants; field-level agreement → `Invoice.stable[field]`.
- `panch/reading/parse.py`: map Vision output to `Invoice` fields (vendor, GSTIN, number, date, lines, subtotal, tax, total, amount in words, payee name, account, IFSC). Keep crops/spans as references if Vision returns layout (UNVERIFIED).
- `panch/normalise/`: `parse_amount`, `words_to_amount` (en, hi, ta), `parse_date` (returns `(date, ambiguous)`), `vendor_key`, `norm_invoice_number`, Indic digit mapping.
- `scripts/read_batch.py`: read a folder, write cached JSON per invoice.

## v3 additions (priority: P0 enabler, ship first)
- **One queue** keyed by file hash; split into small jobs to respect page caps (reported: Extract 20 pages, Parse 30, some pages say 10 per job); keep the page number on every field.
- **Extract with the fixed schema** in ARCHITECTURE section A (incl. `buyer_gstin`, `po_no`, `cgst/sgst/igst`, `discount`, `vendor_phone`); **Parse** `output_format="json"` for bounding boxes.
- Store `raw_native` and canonical value per field; record detected language.
- Per-field confidence if returned, else multi-read; low confidence on account, IFSC or any amount must surface (never auto-pay).
- **Never translate** GSTIN, invoice number, account, IFSC, amounts, dates. Invoice numbers keep the financial-year part.
- Vendor names: transliterate (Sarvam Roman output if the team rule allows, else a local library), cache by content hash; phonetic key + trigram/Jaro-Winkler.
- Extra tests: `U-NORM-15` to `U-NORM-17`; integration `IT-SARVAM` S15-S19.

## Tests to implement (offline)
`U-NORM-1` to `U-NORM-14` from [docs/UNIT_TESTS.md](../UNIT_TESTS.md). Mock the Sarvam client for reading tests; add one recorded Vision output as a fixture in `tests/contract/`.

## Integration cases to run once (record results in INTEGRATION_TESTS.md)
`IT-SARVAM` S1 and S4 (printed + handwritten invoice: latency, output schema, bounding boxes).

## Acceptance
- `read_invoice(path) -> Invoice` works on the cached demo batch with no network.
- All `U-NORM` tests pass; money is `Decimal`; no field is silently "corrected".
- Unstable or ambiguous fields are visible (`stable=False`, `date_ambiguous=True`).

## Out of scope
Checks, decisions, Cashfree calls, UI.

## Coordinate with
PR 2 (consumes `Invoice`), Krish (synthetic batch and the cached demo outputs). Tamil/Hindi word lists need a native-speaker check.
