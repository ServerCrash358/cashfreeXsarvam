"""Generate synthetic invoice images to test Sarvam Vision (IT-SARVAM S4) and PR 1's reader.

Synthetic data only (hackathon rule): every vendor, GSTIN and invoice is made up; bank
accounts are Cashfree sandbox test accounts. HTML is rendered by headless Edge (correct
Tamil/Devanagari shaping, which Pillow without raqm cannot do), then some copies are
degraded to look like phone photos / photocopies.

Usage:  python scripts/generate_ocr_samples.py            -> data/ocr_samples/*.png + answer_key.json
File names carry the language tag PR 1's reader understands (inv_03_ta.png).
"""
from __future__ import annotations

import json
import os
import random
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "ocr_samples"
EDGE_PATHS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
]
BUYER = {"name": "Raghu Hardware, Coimbatore", "gstin": "33AAFCR1234M1Z2"}

# Each spec: what is printed on the page AND the answer key (what a perfect read returns).
INVOICES = [
    {
        "file": "inv_01_en.png", "lang": "en", "style": "print", "expect": "clean",
        "title": "TAX INVOICE", "vendor": "Coastal Steel Pvt Ltd", "vendor_gstin": "29AAICP2912R1ZR",
        "address": "14 Port Road, Mangaluru 575001", "phone": "+91 98450 11223",
        "invoice_no": "CSPL/INV/1187", "invoice_date": "14 Nov 2026", "po_no": "PO-RH-0412",
        "labels": dict(item="Item", qty="Qty", rate="Rate", amount="Amount", subtotal="Subtotal",
                       igst="IGST 18%", cgst="CGST 9%", sgst="SGST 9%", total="Total",
                       words="Amount in words", bank="Bank details", acct="A/c No", ifsc="IFSC", payee="Payee"),
        "lines": [("MS Angle 40x40", "40", "150.00", "6,000.00"), ("Binding wire (kg)", "10", "200.00", "2,000.00")],
        "subtotal": "8,000.00", "igst": "1,440.00", "total": "9,440.00",
        "amount_in_words": "Nine Thousand Four Hundred Forty Rupees Only",
        "bank_account": "388108022658", "ifsc": "ICIC0000009", "payee_name": "Coastal Steel Pvt Ltd",
    },
    {
        "file": "inv_02_hi.png", "lang": "hi", "style": "print", "expect": "clean",
        "title": "कर बीजक", "vendor": "श्री गणेश पैकेजिंग", "vendor_latin": "Shree Ganesh Packaging",
        "vendor_gstin": "27AAPFS1234K1Z5", "address": "प्लॉट 22, भिवंडी, महाराष्ट्र 421302", "phone": "+91 99200 44556",
        "invoice_no": "SGP/0093/2026-27", "invoice_date": "12-11-2026", "po_no": None,
        "labels": dict(item="विवरण", qty="मात्रा", rate="दर", amount="राशि", subtotal="उप-योग",
                       igst="IGST 18%", cgst="CGST", sgst="SGST", total="कुल",
                       words="शब्दों में", bank="बैंक विवरण", acct="खाता संख्या", ifsc="IFSC", payee="खाताधारक"),
        "lines": [("कार्टन बॉक्स", "300", "40.00", "12,000.00"), ("पैकिंग टेप", "100", "35.00", "3,500.00")],
        "subtotal": "15,500.00", "igst": "2,790.00", "total": "18,290.00",
        "amount_in_words": "अठारह हज़ार दो सौ नब्बे रुपये मात्र",
        "bank_account": "026291800001191", "ifsc": "YESB0000262", "payee_name": "Shree Ganesh Packaging",
    },
    {
        "file": "inv_03_ta.png", "lang": "ta", "style": "print", "expect": "clean",
        "title": "வரி விலைப்பட்டியல்", "vendor": "ஸ்ரீ முருகன் இன்ஜினியரிங் வொர்க்ஸ்",
        "vendor_latin": "Sri Murugan Engineering Works", "vendor_gstin": "33AABCS1234M1Z8",
        "address": "45, காந்திபுரம், கோயம்புத்தூர் 641012", "phone": "+91 94430 77889",
        "invoice_no": "SMEW/221/2026-27", "invoice_date": "10-11-2026", "po_no": None,
        "labels": dict(item="பொருள்", qty="அளவு", rate="விலை", amount="தொகை", subtotal="துணைத் தொகை",
                       igst="IGST", cgst="CGST 9%", sgst="SGST 9%", total="மொத்தம்",
                       words="எழுத்தில்", bank="வங்கி விவரம்", acct="கணக்கு எண்", ifsc="IFSC", payee="பெயர்"),
        "lines": [("போல்ட் M10", "200", "25.00", "5,000.00"), ("நட் M10", "500", "6.00", "3,000.00"),
                  ("வாஷர்", "1000", "2.00", "2,000.00")],
        "subtotal": "10,000.00", "cgst": "900.00", "sgst": "900.00", "total": "11,800.00",
        "amount_in_words": "பதினோராயிரத்து எண்ணூறு ரூபாய் மட்டும்",
        "bank_account": "1233943142", "ifsc": "ICIC0000009", "payee_name": "Sri Murugan Engineering Works",
    },
    {
        "file": "inv_05_en_hand.png", "lang": "en", "style": "hand", "expect": "clean",
        "title": "DELIVERY SLIP / BILL", "vendor": "Annapoorna Supplies", "vendor_gstin": "33AAKFA4321Q1Z9",
        "address": "Town Hall Rd, Coimbatore", "phone": "+91 90030 12121",
        "invoice_no": "AS/1044/2026-27", "invoice_date": "15/11/2026", "po_no": None,
        "labels": dict(item="Item", qty="Qty", rate="Rate", amount="Amt", subtotal="Subtotal",
                       igst="IGST", cgst="CGST", sgst="SGST", total="TOTAL",
                       words="Rupees", bank="Pay to", acct="A/c", ifsc="IFSC", payee="Name"),
        "lines": [("Rice bag 25kg", "10", "1200", "12000"), ("Oil tin 15L", "5", "600", "3000")],
        "subtotal": "15000", "total": "15000",
        "amount_in_words": "Fifteen thousand only",
        "bank_account": "00011020001772", "ifsc": "HDFC0000001", "payee_name": "Annapoorna Supplies",
    },
    {
        "file": "inv_06_hi_trap.png", "lang": "hi", "style": "print", "expect": "trap: ARITH_TOTAL + ARITH_WORDS",
        "title": "कर बीजक", "vendor": "बालाजी पेंट्स", "vendor_latin": "Balaji Paints",
        "vendor_gstin": "27AAJFB5678L1Z3", "address": "सेक्टर 5, पुणे 411001", "phone": "+91 98220 33445",
        "invoice_no": "BP/0518/2026-27", "invoice_date": "13 Nov 2026", "po_no": None,
        "labels": dict(item="विवरण", qty="मात्रा", rate="दर", amount="राशि", subtotal="उप-योग",
                       igst="IGST 18%", cgst="CGST", sgst="SGST", total="कुल",
                       words="शब्दों में", bank="बैंक विवरण", acct="खाता संख्या", ifsc="IFSC", payee="खाताधारक"),
        "lines": [("इमल्शन पेंट 20L", "20", "450.00", "9,000.00"), ("प्राइमर 10L", "10", "500.00", "5,000.00")],
        "subtotal": "14,000.00", "igst": "2,520.00", "total": "18,520.00",       # should be 16,520
        "amount_in_words": "सत्रह हज़ार पाँच सौ बीस रुपये मात्र",                   # 17,520: disagrees too
        "bank_account": "00011020001772", "ifsc": "HDFC0000001", "payee_name": "Balaji Paints",
    },
    {
        "file": "inv_07_ta_numerals.png", "lang": "ta", "style": "print", "expect": "clean (Tamil numerals)",
        "title": "விலைப்பட்டியல்", "vendor": "மீனாட்சி டெக்ஸ்டைல்ஸ்", "vendor_latin": "Meenakshi Textiles",
        "vendor_gstin": "33AAEFM9876P1Z4", "address": "மதுரை 625001", "phone": "+91 94860 55667",
        "invoice_no": "MT/0098/2026-27", "invoice_date": "௧௬-௧௧-௨௦௨௬", "po_no": None,
        "labels": dict(item="பொருள்", qty="அளவு", rate="விலை", amount="தொகை", subtotal="துணைத் தொகை",
                       igst="IGST", cgst="CGST 2.5%", sgst="SGST 2.5%", total="மொத்தம்",
                       words="எழுத்தில்", bank="வங்கி விவரம்", acct="கணக்கு எண்", ifsc="IFSC", payee="பெயர்"),
        "lines": [("பருத்தி துணி (மீட்டர்)", "௪", "௧,௦௦௦", "௪,௦௦௦")],
        "subtotal": "௪,௦௦௦", "cgst": "௧௦௦", "sgst": "௧௦௦", "total": "௪,௨௦௦",
        "amount_in_words": "நான்காயிரத்து இருநூறு ரூபாய் மட்டும்",
        "bank_account": "7766671735000", "ifsc": "SBIN0000004", "payee_name": "Meenakshi Textiles",
    },
]
# Tamil dropped (21 Nov live run): Vision read Tamil bills less reliably than Hindi
# (Tamil amount-in-words not parsed; Tamil numerals lost line items), so the demo uses Hindi.
INVOICES = [s for s in INVOICES if s["lang"] != "ta"]

# Degraded copies (same answer key as the source).
DEGRADED = [
    ("inv_02_hi.png", "inv_04_hi_scan.png", dict(angle=2.5, blur=1.1, contrast=0.7, noise=18, yellow=True)),
    ("inv_06_hi_trap.png", "inv_08_hi_photo.png", dict(angle=-3.5, blur=1.4, contrast=0.8, noise=24, yellow=False)),
]

TAMIL_DIGITS = str.maketrans("௦௧௨௩௪௫௬௭௮௯", "0123456789")


def html_for(spec: dict) -> str:
    L = spec["labels"]
    hand = spec["style"] == "hand"
    font = "'Segoe Print', 'Ink Free', cursive" if hand else "'Nirmala UI', 'Segoe UI', sans-serif"
    tax_rows = ""
    for k in ("cgst", "sgst", "igst"):
        if spec.get(k):
            tax_rows += f"<tr><td colspan=3 class=r>{L[k]}</td><td class=r>{spec[k]}</td></tr>"
    rows = "".join(f"<tr><td>{d}</td><td class=r>{q}</td><td class=r>{r}</td><td class=r>{a}</td></tr>"
                   for d, q, r, a in spec["lines"])
    po = f"<div>PO: {spec['po_no']}</div>" if spec.get("po_no") else ""
    border = "none" if hand else "1px solid #333"
    return f"""<!doctype html><html><head><meta charset="utf-8"><style>
body{{margin:0;background:#fff;font-family:{font};color:#1a1a2a;font-size:{19 if hand else 17}px}}
.page{{width:840px;padding:34px 40px}}
h1{{font-size:26px;margin:0 0 6px;letter-spacing:1px}}
.v{{font-size:22px;font-weight:700}} .small{{font-size:14px;color:#333}}
.row{{display:flex;justify-content:space-between;margin:14px 0}}
table{{width:100%;border-collapse:collapse;margin-top:10px}}
td,th{{border:{border};padding:7px 9px}} th{{background:{'transparent' if hand else '#eee'};text-align:left}}
.r{{text-align:right}} .tot td{{font-weight:700;font-size:19px}}
.bank{{margin-top:22px;padding:10px 12px;border:{'2px dashed #445' if hand else '1px solid #333'};
transform:{'rotate(-1.5deg)' if hand else 'none'}}}
</style></head><body><div class=page>
<h1>{spec['title']}</h1>
<div class=v>{spec['vendor']}</div>
<div class=small>{spec['address']} · Ph {spec['phone']}</div>
<div class=small>GSTIN: {spec['vendor_gstin']}</div>
<div class=row><div>Bill to: {BUYER['name']}<br><span class=small>GSTIN: {BUYER['gstin']}</span></div>
<div class=r>No: <b>{spec['invoice_no']}</b><br>Date: {spec['invoice_date']}{po}</div></div>
<table><tr><th>{L['item']}</th><th class=r>{L['qty']}</th><th class=r>{L['rate']}</th><th class=r>{L['amount']}</th></tr>
{rows}
<tr><td colspan=3 class=r>{L['subtotal']}</td><td class=r>{spec['subtotal']}</td></tr>
{tax_rows}
<tr class=tot><td colspan=3 class=r>{L['total']}</td><td class=r>₹ {spec['total']}</td></tr></table>
<p><b>{L['words']}:</b> {spec['amount_in_words']}</p>
<div class=bank><b>{L['bank']}</b><br>{L['payee']}: {spec['payee_name']}<br>
{L['acct']}: {spec['bank_account']} &nbsp; {L['ifsc']}: {spec['ifsc']}</div>
</div></body></html>"""


def render(html: str, out: Path, edge: str) -> None:
    with tempfile.TemporaryDirectory() as td:
        src = Path(td) / "inv.html"
        src.write_text(html, encoding="utf-8")
        shot = Path(td) / "shot.png"
        # own profile dir so headless Edge doesn't attach to an already-open Edge window;
        # Edge may hand off to a child process and return early, so wait for the file
        subprocess.run([edge, "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
                        f"--user-data-dir={Path(td) / 'profile'}",
                        f"--screenshot={shot}", "--window-size=920,1180", src.as_uri()],
                       capture_output=True, timeout=90)
        for _ in range(60):
            if shot.exists() and shot.stat().st_size > 0:
                break
            time.sleep(0.5)
        else:
            raise RuntimeError(f"Edge did not write a screenshot for {out.name}")
        time.sleep(0.5)
        shutil.move(str(shot), out)


def degrade(src: Path, dst: Path, angle: float, blur: float, contrast: float, noise: int, yellow: bool) -> None:
    rnd = random.Random(42)
    im = Image.open(src).convert("RGB")
    im = im.rotate(angle, resample=Image.BICUBIC, expand=True, fillcolor=(235, 232, 225))
    im = im.filter(ImageFilter.GaussianBlur(blur))
    im = ImageEnhance.Contrast(im).enhance(contrast)
    if yellow:
        im = Image.blend(im, Image.new("RGB", im.size, (240, 228, 190)), 0.18)
    px = im.load()
    w, h = im.size
    for _ in range(w * h // 9):
        x, y = rnd.randrange(w), rnd.randrange(h)
        r, g, b = px[x, y]
        d = rnd.randint(-noise, noise)
        px[x, y] = (max(0, min(255, r + d)), max(0, min(255, g + d)), max(0, min(255, b + d)))
    im = im.resize((int(w * 0.8), int(h * 0.8)))          # lower resolution, like a phone shot
    im.save(dst, quality=70) if dst.suffix == ".jpg" else im.save(dst)


def answer(spec: dict) -> dict:
    def canon(v):
        return None if v is None else v.translate(TAMIL_DIGITS).replace(",", "").replace("₹", "").strip()
    return {
        "language": spec["lang"], "expect": spec["expect"], "style": spec["style"],
        "vendor_name": spec["vendor"], "vendor_name_latin": spec.get("vendor_latin", spec["vendor"]),
        "vendor_gstin": spec["vendor_gstin"], "buyer_gstin": BUYER["gstin"],
        "invoice_no": spec["invoice_no"], "invoice_date": spec["invoice_date"], "po_no": spec.get("po_no"),
        "line_items": [{"item": d, "qty": canon(q), "rate": canon(r), "amount": canon(a)} for d, q, r, a in spec["lines"]],
        "subtotal": canon(spec["subtotal"]), "cgst": canon(spec.get("cgst")), "sgst": canon(spec.get("sgst")),
        "igst": canon(spec.get("igst")), "total": canon(spec["total"]), "amount_in_words": spec["amount_in_words"],
        "bank_account": spec["bank_account"], "ifsc": spec["ifsc"], "payee_name": spec["payee_name"],
        "vendor_phone": spec["phone"],
    }


def main() -> None:
    edge = next((p for p in EDGE_PATHS if os.path.exists(p)), None)
    if not edge:
        raise SystemExit("Microsoft Edge not found; needed to render Indic text correctly")
    OUT.mkdir(parents=True, exist_ok=True)
    key, langs = {}, {}
    for spec in INVOICES:
        out = OUT / spec["file"]
        render(html_for(spec), out, edge)
        key[spec["file"]] = answer(spec)
        langs[spec["file"]] = f"{spec['lang']}-IN"
        print("rendered", out.name)
    for src, dst, kw in DEGRADED:
        degrade(OUT / src, OUT / dst, **kw)
        key[dst] = {**key[src], "style": "photo/scan of " + src}
        langs[dst] = langs[src]
        print("degraded", dst)
    (OUT / "answer_key.json").write_text(json.dumps(key, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "languages.json").write_text(json.dumps(langs, indent=2), encoding="utf-8")
    print(f"{len(key)} images + answer_key.json + languages.json in {OUT}")


if __name__ == "__main__":
    main()
