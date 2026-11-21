"""Probe Sarvam Document AI on one or two real invoices and save the raw output.

Run this FIRST, before trusting any mapping code. It calls the SDK directly
(no cache, no mapping) so you see exactly what comes back.

Windows (PowerShell, from the repo root, venv active):
    $env:PYTHONUTF8 = "1"
    python scripts\\probe_vision.py data\\probe\\printed.png data\\probe\\handwritten.jpg
    python scripts\\probe_vision.py data\\probe\\printed.png --parse --language ta-IN

Writes data/probe/<file>.extract.json (and .parse.json). Those files hold
whatever Vision read, account numbers included: keep data/probe/ out of git
and use synthetic invoices only.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from panch.reading.config import ReadingConfig  # noqa: E402
from panch.reading.mapping import mask_account  # noqa: E402
from panch.reading.schema import schema_json  # noqa: E402
from panch.reading.vision import MIME, TERMINAL, make_sdk_client  # noqa: E402

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")


def dump(model):
    if hasattr(model, "model_dump"):
        return model.model_dump()
    return model if isinstance(model, dict) else dict(model)


def wait(client, job_id, timeout):
    t0 = time.monotonic()
    while True:
        st = client.doc_ai.get_status(job_id)
        status = str(st.status).lower()
        print(f"   status={status} after {time.monotonic() - t0:.0f}s")
        if status in TERMINAL:
            return status, dump(st)
        if time.monotonic() - t0 > timeout:
            return "timeout", dump(st)
        time.sleep(3)


def probe(client, path: Path, out_dir: Path, args, cfg):
    mime = MIME.get(path.suffix.lower(), "application/octet-stream")
    print(f"\n== {path.name} ({mime})")

    t0 = time.monotonic()
    with open(path, "rb") as fh:
        job = client.doc_ai.extract(file=[(path.name, fh, mime)], schema=schema_json(),
                                    output_format="json", mode="basic")
    print(f"   extract job {job.job_id} accepted")
    status, st = wait(client, job.job_id, args.timeout)
    res = dump(client.doc_ai.get_results(job.job_id)) if status in ("completed", "partially_completed") else {}
    elapsed = time.monotonic() - t0
    out = {"file": path.name, "elapsed_s": round(elapsed, 1), "status": status, "status_response": st, "results": res}
    target = out_dir / f"{path.name}.extract.json"
    with open(target, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1, default=str)
    print(f"   -> {status} in {elapsed:.0f}s, saved {target.relative_to(ROOT)}")

    result = res.get("result") or {}
    ann = res.get("annotations") or {}
    print(f"   top-level keys: {sorted(res.keys())}")
    print(f"   result keys:    {sorted(result.keys())}")
    for k in ("total", "invoice_no", "invoice_date", "vendor_name", "amount_in_words", "bank_account"):
        v = result.get(k)
        if k == "bank_account":
            v = mask_account(v) if isinstance(v, str) else v
        print(f"   {k:16} = {v!r}  (type {type(v).__name__})")
    print(f"   annotations['total'] = {json.dumps(ann.get('total'), ensure_ascii=False, default=str)[:400]}")
    rows = result.get("line_items") or []
    print(f"   line_items: {len(rows)} rows; first = {json.dumps(rows[:1], ensure_ascii=False)[:300]}")
    print("   CHECK: are values strings? does annotations carry confidence, input_page, region?")

    if args.parse:
        lang = args.language or cfg.default_language
        t0 = time.monotonic()
        with open(path, "rb") as fh:
            job = client.doc_ai.parse(file=[(path.name, fh, mime)], language=lang,
                                      content_type=args.content_type)
        status, st = wait(client, job.job_id, args.timeout)
        res = dump(client.doc_ai.get_results(job.job_id, format="json")) if status in (
            "completed", "partially_completed") else {}
        target = out_dir / f"{path.name}.parse.json"
        with open(target, "w", encoding="utf-8") as f:
            json.dump({"file": path.name, "elapsed_s": round(time.monotonic() - t0, 1), "status": status,
                       "language": lang, "results": res}, f, ensure_ascii=False, indent=1, default=str)
        print(f"   parse ({lang}) -> {status}, saved {target.relative_to(ROOT)}")
        docs = res.get("documents") or []
        if docs:
            page = (docs[0].get("pages") or [{}])[0]
            print(f"   parse page keys: {sorted(page.keys())}")
            print(f"   content head: {str(page.get('content'))[:300]!r}")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("files", nargs="+", type=Path)
    ap.add_argument("--parse", action="store_true", help="also run Parse (json) to look for bounding boxes")
    ap.add_argument("--language", help="BCP-47 code for Parse, e.g. ta-IN, hi-IN, en-IN")
    ap.add_argument("--content-type", default="mixed", choices=["printed", "handwritten", "mixed"])
    ap.add_argument("--timeout", type=float, default=300)
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "probe")
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    cfg = ReadingConfig.load()
    client = make_sdk_client()
    for f in args.files:
        if not f.is_file():
            print(f"missing: {f}")
            continue
        try:
            probe(client, f, args.out, args, cfg)
        except Exception as exc:  # show the API error body, then keep going
            body = getattr(exc, "body", None)
            print(f"   ERROR {type(exc).__name__}: {exc}\n   body: {body}")


if __name__ == "__main__":
    main()
