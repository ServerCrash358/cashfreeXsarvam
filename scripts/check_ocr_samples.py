"""Run data/ocr_samples/*.png through PR 1's read_invoice (live Sarvam Vision) and score each
field against answer_key.json. IT-SARVAM S4.

Usage:  python scripts/check_ocr_samples.py [file ...]      (needs SARVAM_API_KEY in .env)
Writes data/ocr_samples/report.json and prints a per-field table.
"""
from __future__ import annotations

import json
import sys
import time
from decimal import Decimal
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env")
except ImportError:
    pass

from panch.reading import read_invoice  # noqa: E402
from panch.reading.reader import get_read_artifacts  # noqa: E402

SAMPLES = ROOT / "data" / "ocr_samples"


def dec(v):
    if v in (None, ""):
        return None
    try:
        return Decimal(str(v).replace(",", "")).quantize(Decimal("0.01"))
    except Exception:
        return None


def norm(s):
    return None if s is None else "".join(str(s).split()).upper()


def score(inv, key: dict) -> dict:
    checks = {
        "gstin": norm(inv.gstin) == norm(key["vendor_gstin"]),
        "invoice_no": norm(inv.number_raw) == norm(key["invoice_no"]),
        "subtotal": dec(inv.subtotal) == dec(key["subtotal"]),
        "total": dec(inv.total) == dec(key["total"]),
        "account": norm(inv.account_number) == norm(key["bank_account"]),
        "ifsc": norm(inv.ifsc) == norm(key["ifsc"]),
        "lines": len(inv.lines) == len(key["line_items"]),
        "line_amounts": [dec(l.amount) for l in inv.lines] == [dec(l["amount"]) for l in key["line_items"]],
        "words_read": inv.words_amount is not None,
        "vendor_read": bool(inv.vendor_name_raw),
        "date": inv.date is not None,
    }
    return checks


def main() -> None:
    key = json.loads((SAMPLES / "answer_key.json").read_text(encoding="utf-8"))
    files = sys.argv[1:] or sorted(key)
    report = {}
    for name in files:
        t = time.time()
        try:
            inv = read_invoice(SAMPLES / name)
        except Exception as e:
            report[name] = {"error": f"{type(e).__name__}: {e}"}
            print(f"{name}: ERROR {e}")
            continue
        art = get_read_artifacts(inv) or {}
        s = score(inv, key[name])
        unstable = sorted(k for k, v in (inv.stable or {}).items() if v is False)
        report[name] = {
            "seconds": round(time.time() - t, 1), "checks": s, "passed": sum(s.values()), "of": len(s),
            "unstable_fields": unstable, "language": art.get("language"),
            "jobs": art.get("jobs"),
            "read": {"vendor": inv.vendor_name_raw, "gstin": inv.gstin, "no": inv.number_raw,
                     "date": str(inv.date), "subtotal": str(inv.subtotal), "total": str(inv.total),
                     "words_amount": str(inv.words_amount), "account_last4": (inv.account_number or "")[-4:],
                     "ifsc": inv.ifsc, "lines": len(inv.lines)},
            "expect": key[name]["expect"],
        }
        bad = [k for k, v in s.items() if not v]
        print(f"{name:24s} {sum(s.values()):2d}/{len(s)}  {report[name]['seconds']:5.1f}s  "
              f"wrong: {', '.join(bad) or '-'}  unstable: {', '.join(unstable) or '-'}")
    (SAMPLES / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2, default=str),
                                         encoding="utf-8")
    print(f"report: {SAMPLES / 'report.json'}")


if __name__ == "__main__":
    main()
