"""Render the synthetic demo batch (data/fixtures/demo_batch.json) to invoice images (module N).
HTML -> PNG via headless Edge, which shapes Tamil/Devanagari correctly. Some invoices use a
handwriting-style font. Synthetic data only.
Usage: .venv/Scripts/python scripts/make_invoice_images.py [out_dir]"""
import html
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "data" / "demo"
EDGE = r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe"
HANDWRITTEN = {"F", "G"}            # handwriting-style font for these
LABELS = {
    "en": dict(inv="TAX INVOICE", no="Invoice No", date="Date", to="Bill To", item="Item", qty="Qty", rate="Rate",
               amt="Amount", sub="Subtotal", total="Total", words="Amount in words", bank="Bank details",
               acct="A/c No", phone="Phone"),
    "hi": dict(inv="कर बीजक", no="बिल नं.", date="दिनांक", to="ख़रीदार", item="विवरण", qty="मात्रा", rate="दर",
               amt="रकम", sub="उप-योग", total="कुल", words="शब्दों में", bank="बैंक विवरण", acct="खाता सं.",
               phone="फ़ोन"),
    "ta": dict(inv="வரி விலைப்பட்டியல்", no="பில் எண்", date="தேதி", to="வாங்குபவர்", item="பொருள்", qty="அளவு",
               rate="விலை", amt="தொகை", sub="துணைத்தொகை", total="மொத்தம்", words="எழுத்தில்", bank="வங்கி விவரம்",
               acct="கணக்கு எண்", phone="தொலைபேசி"),
}


def page(r: dict, buyer: dict) -> str:
    L = LABELS[r.get("language", "en")]
    e = lambda v: html.escape(str(v)) if v not in (None, "") else ""  # noqa: E731
    font = "'Ink Free','Segoe Print',cursive" if r["id"] in HANDWRITTEN else "'Nirmala UI','Segoe UI',Arial"
    rows = "".join(f"<tr><td>{e(l['item'])}</td><td class=n>{e(l['qty'])}</td><td class=n>{e(l['rate'])}</td>"
                   f"<td class=n>{e(l['amount'])}</td></tr>" for l in r["line_items"])
    tax = "".join(f"<tr><td colspan=3 class=n>{k.upper()}</td><td class=n>{e(r[k])}</td></tr>"
                  for k in ("cgst", "sgst", "igst") if r.get(k))
    return f"""<!doctype html><meta charset=utf-8><style>
body{{font-family:{font},'Nirmala UI';margin:28px;color:#111;width:760px;background:#fffef8}}
h1{{font-size:26px;margin:0}} .muted{{color:#444;font-size:14px}} table{{width:100%;border-collapse:collapse;margin:14px 0}}
td,th{{border:1px solid #888;padding:6px 8px;font-size:15px}} .n{{text-align:right}} .box{{border:1px solid #888;padding:8px;margin-top:10px}}
</style>
<div style="display:flex;justify-content:space-between"><div><h1>{e(r['vendor_name'])}</h1>
<div class=muted>GSTIN: {e(r['vendor_gstin'])}</div><div class=muted>{L['phone']}: {e(r.get('vendor_phone'))}</div></div>
<div style="text-align:right"><b>{L['inv']}</b><div>{L['no']}: {e(r['invoice_no'])}</div><div>{L['date']}: {e(r['invoice_date'])}</div>
{f"<div>PO: {e(r['po_no'])}</div>" if r.get('po_no') else ''}</div></div>
<div class=box>{L['to']}: {e(buyer['name'])} · GSTIN {e(r.get('buyer_gstin'))}</div>
<table><tr><th>{L['item']}</th><th>{L['qty']}</th><th>{L['rate']}</th><th>{L['amt']}</th></tr>{rows}
<tr><td colspan=3 class=n>{L['sub']}</td><td class=n>{e(r['subtotal'])}</td></tr>{tax}
<tr><td colspan=3 class=n><b>{L['total']}</b></td><td class=n><b>{e(r['total'])}</b></td></tr></table>
<div>{L['words']}: <b>{e(r.get('amount_in_words'))}</b></div>
<div class=box><b>{L['bank']}</b><br>{e(r.get('payee_name'))}<br>{L['acct']}: {e(r['bank_account'])} · IFSC: {e(r['ifsc'])}</div>
<p class=muted style="margin-top:18px">SYNTHETIC TEST INVOICE · Cashfree sandbox data · not a real bill</p>"""


def main():
    batch = json.loads((ROOT / "data" / "fixtures" / "demo_batch.json").read_text(encoding="utf-8"))
    buyer = json.loads((ROOT / "data" / "fixtures" / "vendors.json").read_text(encoding="utf-8"))["buyer"]
    OUT.mkdir(parents=True, exist_ok=True)
    tmp = OUT / "_html"
    tmp.mkdir(exist_ok=True)
    for r in batch["invoices"]:
        h = tmp / f"inv_{r['id']}_{r['language']}.html"
        h.write_text(page(r, buyer), encoding="utf-8")
        png = OUT / f"inv_{r['id']}_{r['language']}.png"
        subprocess.run([EDGE, "--headless", "--disable-gpu", "--hide-scrollbars", f"--screenshot={png}",
                        "--window-size=820,900", h.resolve().as_uri()], check=True, capture_output=True, timeout=60)
        print(png.name, png.stat().st_size, "bytes")


if __name__ == "__main__":
    main()
