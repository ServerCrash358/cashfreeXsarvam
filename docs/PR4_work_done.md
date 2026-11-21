# PR 4: work done (voice, approval, call-back, UI)

Branch `shubhang`. Owner: Teammate 4. Modules: E2 (call-back), H (bundle approval), L (voice), M (UI).

## How this branch relates to `main`

While PR 4 was being built, `main` received Krish's integrated **stable build** (`a58f6f0`), which already contains working versions of the PR 4 modules wired into `panch/engine.py` and the live sandbox payout path. This branch **merges `origin/main` and keeps main's files and APIs** for `app/`, `panch/approval`, `panch/vendors/callback.py`, `panch/voice` and the `.txt` templates. PR 4's standalone versions (earlier commits on this branch) were removed in the merge so there is one implementation. What PR 4 adds on top of main is below.

## Fixes ported into main's modules (found by live Sarvam tests)

| # | Problem in main | Evidence | Fix |
|---|---|---|---|
| 1 | Every **Hindi** voice approval fails: Saaras ends sentences with a danda, and the token pattern keeps it, so the code reads as `"026।"` | live transcript `'हाँ, 22002 बिल, कोड 026।'` | strip `।` / `॥` in `panch/approval` and `panch/voice/digits.py` |
| 2 | Saaras v4 joins "बाईस हज़ार, दो बिल" into **"22002 बिल"**, so total and count both fail | live, hi and ta, codemix and transcribe | `_merged_total_count`: accept a number right before a bill word only when it equals exactly total + count |
| 3 | Approval prompt asks "total, count", the order that triggers #2 | | `templates/{en,hi,ta}/approval_prompt.txt` now ask count before total |
| 4 | Tamil "yes" from Saaras is `ஆமாம்`, not in the yes list | live transcript | added `ஆமாம்`, `aamaam`, `haanji`, `जी` |
| 5 | No limit on PIN guesses | | `Engine.approve_pin`: 3 wrong PINs lock the bundle (status `locked`); a fresh plan is needed |
| 6 | Fewer spoken-digit spellings | | more Tamil script/romanised and Hinglish digit words in `digits.py` |

Tests: `tests/unit/test_pr4_voice.py` (live transcript shapes, exact-match guard, call-back digits in three languages and scripts incl. danda, PIN lockout). **Full suite: 51 passed** (main's 33 + PR 4's 18), Python 3.14.6, pytest 9.0.3.

## Live Sarvam results (IT-SARVAM S1, S2, S8; 21 Nov, `sarvamai` 0.1.48)

| Case | Result |
|---|---|
| S8 Bulbul `bulbul:v4-flash` hi / ta, default persona | audio OK, 2.5-3.8 s per prompt |
| S8 Bulbul `bulbul:v3` hi / ta | audio OK, 1.5-2.4 s |
| S2 Saaras `saaras:v4`, `codemix` and `transcribe`, hi and ta | 0.3-0.6 s per clip; with fixes 1-4 all 8 approval replies (2 languages × 2 modes × 2 word orders) are valid |
| Call-back digits ta / hi / en | Saaras returns `"4729."` in all three; digits 4729 |
| SDK kwargs | `language_code`, `model`, `speaker`, file tuple, `mode`, `keyterms` confirmed in the installed SDK |

Speakers available in the SDK include `vijay_ta_narration`, `gokul_ta_narration`, `ritu_hi_customer`, `ritu_hi_banking` (main already uses `vijay_ta_narration` and `ritu_hi_customer`).

## Not carried over from the standalone PR 4 (available in this branch's history if wanted)
- Second approver for CHANGED_ACCOUNT items or above a threshold (stretch; main has one owner PIN in `config/settings.json`).
- PBKDF2 PIN hashing (main uses salted SHA-256; changing it changes the settings format).
- Owner-language messages for PIN steps and payout pending/failed.

## Before the demo
- [ ] Try a real microphone in the venue room (live tests used Bulbul audio, not a human voice).
- [ ] Native-check the Hindi and Tamil approval prompts.
- [ ] Rotate the Sarvam key after the event (it was shared in a chat).
