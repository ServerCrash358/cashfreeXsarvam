"""Pre-run a folder of invoices through Vision and fill the cache.

Run this BEFORE the demo, then demo with PANCH_VISION_OFFLINE=1 so nothing
waits on a live Vision call.

Windows (PowerShell, from the repo root, venv active):
    $env:PYTHONUTF8 = "1"
    python scripts\\read_batch.py data\\demo
    python scripts\\read_batch.py data\\demo --export data\\demo_reads     # JSON for PR 2
    $env:PANCH_VISION_OFFLINE = "1"; python scripts\\read_batch.py data\\demo   # cache-only check

Account numbers are masked in everything this prints and exports, unless
--include-accounts is given (synthetic data only).
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from panch.reading import ReadingConfig, VisionCacheMiss, read_invoice  # noqa: E402
from panch.reading.reader import iter_invoice_files  # noqa: E402
from panch.reading.serialize import invoice_to_dict  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("folder", type=Path)
    ap.add_argument("--export", type=Path, help="write one <file>.invoice.json per invoice here")
    ap.add_argument("--include-accounts", action="store_true")
    ap.add_argument("--variants", help="comma list, e.g. orig or orig,binar,up2x")
    ap.add_argument("--parallel", type=int, default=2, help="invoices at a time (each runs its variants in parallel)")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO if args.verbose else logging.WARNING, format="%(message)s")

    cfg = ReadingConfig.load()
    variants = tuple(args.variants.split(",")) if args.variants else None
    files = list(iter_invoice_files(args.folder))
    if not files:
        print(f"no invoice files in {args.folder}")
        return
    print(f"{len(files)} files, variants={variants or cfg.variants}, offline={cfg.offline}")
    if args.export:
        args.export.mkdir(parents=True, exist_ok=True)

    from concurrent.futures import ThreadPoolExecutor

    def one(f: Path):
        t0 = time.monotonic()
        try:
            return f, read_invoice(f, variants=variants, config=cfg), time.monotonic() - t0, None
        except VisionCacheMiss as exc:
            return f, None, 0.0, str(exc)
        except Exception as exc:  # noqa: BLE001 - report and keep going
            return f, None, time.monotonic() - t0, f"{type(exc).__name__}: {exc}"

    with ThreadPoolExecutor(max_workers=max(1, args.parallel)) as ex:
        results = list(ex.map(one, files))

    for f, inv, secs, err in results:
        if err:
            print(f"\n{f.name}: ERROR {err}")
            continue
        unstable = sorted(k for k, ok in inv.stable.items() if not ok)
        print(f"\n{f.name}  [{inv.language}]  {secs:.0f}s  id={inv.id}")
        print(f"  vendor   {inv.vendor_name_raw!r}  key={inv.vendor_key!r}  gstin={inv.gstin}")
        print(f"  number   {inv.number_raw!r} -> {inv.number_norm!r}   date {inv.date} ambiguous={inv.date_ambiguous}")
        print(f"  lines    {len(inv.lines)}   subtotal {inv.subtotal}  tax {inv.tax}  total {inv.total}  words {inv.words_amount}")
        print(f"  payee    {inv.payee_name!r}  account {inv.raw_native.get('account_number')}  ifsc {inv.ifsc}")
        print(f"  UNSTABLE {unstable or 'none'}")
        if args.export:
            out = args.export / f"{f.name}.invoice.json"
            with open(out, "w", encoding="utf-8") as fh:
                json.dump(invoice_to_dict(inv, include_account=args.include_accounts), fh,
                          ensure_ascii=False, indent=1)
    if args.export:
        print(f"\nexported to {args.export}")


if __name__ == "__main__":
    main()
