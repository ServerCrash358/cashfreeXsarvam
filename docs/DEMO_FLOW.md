# TijoriPay demo flow (10 minutes, one laptop)

Walked through end to end in the app on 21 Nov, using the buttons rather than the API.

## Before you start (5 minutes ahead)

```powershell
.venv\Scripts\python -m pytest -q
```

```powershell
$env:PANCH_VISION_OFFLINE = "1"; .venv\Scripts\python -m uvicorn app.main:app --port 8000
```

- Open http://localhost:8000. If anything looks off, click **Reset the demo batch**.
- `config/settings.json` must have `"payout_mode": "sim"` until Cashfree funds our Payouts test account. Payouts show a **simulated** tag.
- Demo PIN: `2468`. It's a test value.
- Owner language: Hindi by default. The tabs at the top switch to தமிழ் or EN.
- Have the 8 invoice images in `data/demo/` open in a file window, for the upload moment.

## The script

| # | Time | Do | What the judges see | Say |
|---|---|---|---|---|
| 0 | 0:00 | (page open) | Tiles: **8 bills ₹96,000 · 4 ready ₹44,000 · 1 needs you (F)** | "A kirana-sized business: 8 bills this week in Tamil, Hindi and English, and only ₹30,000 in the bank." |
| 1 | 0:45 | Click **Read with Sarvam Vision** and upload `data/demo/inv_B_hi.png` | The bill is read and comes back **BLOCK DUP_EXACT** | "Sarvam Vision reads the Hindi bill. It's a rescan of bill B, so it's caught as the same bill and blocked. Same goods, amount and date, whatever the scan." |
| 2 | 1:30 | Click rows **D, E, G** | Reasons in Hindi, with evidence | D: "the same LED panels, amount and date as a bill we already paid; only the number changed." E: "the lines add to ₹14,160 but it asks for ₹15,000." G: "the bank says this account belongs to TOM WELLS, not Lakshmi Hardware" (a live Cashfree Secure ID check). |
| 3 | 3:00 | F: **Call vendor on the number on file**, then ▶ **Bulbul**, then type or speak "seven seven two three" and **Submit** | We call the number ending 1234 (vendor master). The number on the invoice (ending 9876) is ignored. **CALLBACK_MISMATCH**: the vendor said 7723, the invoice account ends 1191 | "The invoice asks us to pay a new account. A fraudster controls both the account and the phone printed on it, so we call the number we already had. Bulbul asks in the vendor's language, Saaras hears the answer, and code compares. The answer doesn't match, so the bill is blocked, and calling again won't unblock it." |
| 4 | 4:30 | **Plan payments** (₹30,000) | Pay **H + B, ₹22,000 protected**; earliest-first would protect **₹16,400**. A and C deferred | "MSME law: micro and small suppliers must be paid within 15 days or we lose the tax deduction. The planner protects the most rupees with the cash we have." |
| 5 | 5:30 | ▶ the Hindi read-back. Say or type "हाँ, 2 बिल, 22,000, कोड X-Y-Z", then **Check**, then PIN `2468`, then **Confirm PIN** | "Confirmed. Now tap your PIN", then approved | "The approval is bound to a hash of this exact bundle, lasts 2 minutes and works once. Voice is the conversation; the PIN is the authority. Change one rupee and it's void." |
| 6 | 6:30 | **Pay ₹22,000 via Cashfree**, then **Reconcile now** ×2 | B and H go SENT → PENDING → **SUCCESS**, tagged simulated | "API 200 means submitted, not paid. We record the intent before calling, poll on a timeout instead of resending, and count a bill as paid only at SUCCESS + COMPLETED." |
| 7 | 7:30 | On H: **Simulate reversal** | H becomes **REVERSED**, and the bill reopens as **ASK** with the reason "payment came back… not re-sent automatically" | "The money came back. We never repay automatically: it goes back through verification and needs a fresh approval." |
| 8 | 8:15 | **Scoreboard**, then **Audit ledger** | 4/4 traps blocked, 4/4 clean paid, 0 falsely held. The hash chain is intact | "On our 40-case evaluation set: 20/20 traps blocked and zero false blocks on clean controls, measured." |
| 9 | 9:00 | Q&A | — | Be open about two things: the live Cashfree transfer `667850829` was rejected because the test account has no funds, so payouts are simulated; and the Hindi and Tamil wording still needs a native speaker's check. |

## If something goes wrong

| Problem | Fix |
|---|---|
| Upload says `VisionCacheMiss` | That file was never read live. Run `scripts\read_batch.py data\demo` with network, or demo with a cached image |
| TTS ▶ is silent | Sarvam key or network. Read the prompt aloud; the text is on screen |
| Approval "expired" | 2-minute limit: click **Plan payments** again for a fresh bundle |
| "locked after 3 wrong PINs" | Plan again (a new bundle) |
| State is messy | **Reset the demo batch** |
