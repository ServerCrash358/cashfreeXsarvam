# PR1_HANDOFF.md: what PR 2 gets from `read_invoice`

```python
from panch.reading import read_invoice, get_read_artifacts
inv = read_invoice("data/demo/inv_B_ta.png")          # -> panch.models.Invoice
art = get_read_artifacts(inv)                         # crops, per-variant values, reasons
```

## Keys
`inv.stable`, `inv.confidence`, `inv.raw_native` and `inv.pages` use **Invoice attribute names**: `number`, `date`, `vendor_name`, `gstin`, `buyer_gstin`, `po_number`, `subtotal`, `discount`, `cgst`, `sgst`, `igst`, `tax`, `total`, `words_amount`, `payee_name`, `account_number`, `ifsc`, `upi_id`, `vendor_phone_on_invoice`, `delivery_date`, and `lines`. Line raw strings are `raw_native["lines[0].qty"]` and so on.

## What the flags mean (proposed contract, agree before 14:40)
- `stable[x] is False` means: the variants disagreed, the value did not parse (raw text is in `raw_native`), it used traditional Tamil numerals, Vision returned a number instead of text, confidence was below `min_confidence`, or the job was partial and the field is missing. **PR 2 emits `LOW_CONFIDENCE_READ`** from this; PR 1 returns facts only.
- A field missing from the document is `None` with `stable[x] is True` (consistently absent). A field that was there but unreadable is `None` with `stable[x] is False`.
- If `stable["lines"]`, `stable["total"]` or `stable["subtotal"]` is False, an `ARITH_*` mismatch is probably a reading problem, not doctoring: treat it as ASK, the same way `ARITH_GST_SPLIT` already does for unstable GSTINs.
- Incomplete line rows (qty, rate or amount unreadable) are left out of `inv.lines` and set `stable["lines"] = False`. `LineItem` cannot hold None.
- `date_ambiguous` is only True for a two-digit-year date whose day and month could swap. It is evidence; on its own it should not trigger ASK.
- `tax` is the printed tax total only. It is never computed from CGST + SGST.
- `discount` is the invoice-level discount, or the sum of row discounts when only rows have one (`art["discount_source"]` says which). `LineItem` has no discount field, so `ARITH_LINE` on a discounted row needs `raw_native["lines[i].discount"]`.

## Privacy
- `inv.account_number` is the only place the full number lives. `raw_native`, artifacts, exports and `repr(inv)` show `XXXX` plus the last four.
- `data/cache/` holds raw Vision output and is git-ignored.

## Not in `Invoice` (raise a small PR on `models.py` if you need them)
`delivery_date` and `upi_id` are in `art["extra"]`. Per-line discount is in `raw_native`. Crop boxes are in `art["crops"]`.
