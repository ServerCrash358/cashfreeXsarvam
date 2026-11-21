# TijoriPay

Our build for the Sarvam x Cashfree Buildathon (Bengaluru, 21 Nov 2026), Problem Statement 3: **pay the right bill, to the right person**. TijoriPay reads multilingual invoices (Tamil, Hindi, English; printed and handwritten), pays only what survives deterministic checks, confirms changed bank details by calling the vendor's number on file, plans payments under limited cash and MSME deadlines, takes a replay-proof voice approval, and pays through Cashfree Payouts without ever paying twice.

## Docs (start here)

| Doc | What it covers |
|---|---|
| [docs/AGENTS.md](docs/AGENTS.md) | Read first: red lines, conventions, read order |
| [docs/SYSTEM.md](docs/SYSTEM.md) | Problem, event rules, requirements, open questions |
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | Canonical technical spec, diagrams, shared interfaces |
| [docs/PLAN.md](docs/PLAN.md) | Today's plan, team split, demo script |
| [docs/DEPENDENCIES.md](docs/DEPENDENCIES.md) | Packages, env vars, Sarvam/Cashfree endpoints, sandbox test data |
| [docs/UNIT_TESTS.md](docs/UNIT_TESTS.md) | Offline unit tests and the evaluation harness |
| [docs/INTEGRATION_TESTS.md](docs/INTEGRATION_TESTS.md) | Cashfree test env, Relay, Sarvam SDK, communication suites |
| [docs/BUILD_PLAN.md](docs/BUILD_PLAN.md) | Full decision report and history |
| [docs/RELAY.md](docs/RELAY.md) | Cashfree Relay adapter and canvas recipe |
| [docs/DEMO_FLOW.md](docs/DEMO_FLOW.md) | 10-minute demo script |
| [docs/DESIGN_NOTE.md](docs/DESIGN_NOTE.md) | Submission design note |
| [docs/BUILD_PROMPT.md](docs/BUILD_PROMPT.md) | One-page brief to paste into a coding agent |

## Setup

```bash
python -m venv .venv
```

```bash
.venv/Scripts/pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in your test keys (never commit `.env`). The demo runs on one laptop: payout status comes from the 60-second status sweep, so no public webhook URL (ngrok) is needed.

## Run the stable build

```bash
.venv/Scripts/python -m pytest tests/unit -q
```

```bash
.venv/Scripts/python -m uvicorn app.main:app --port 8000
```

Open http://localhost:8000. The 8-invoice demo batch (A–H) loads from cached Vision output in `data/fixtures/demo_batch.json`.

- **Cashfree needs IP whitelisting:** test mode enforces 2FA. Add your public IP under Developers → Two-Factor Authentication on both the Payouts and Secure ID dashboards. Payouts and Secure ID share one key pair.
- If Secure ID is unreachable, bank checks fall back to canned sandbox fixtures and are marked `canned`.
- **Demo owner PIN: `2468`.** It's a test value; its hash lives in `config/settings.json`.
- **Payouts mode:** `config/settings.json` → `payout_mode` is `live` (real sandbox) or `sim`. If the live API is unavailable, the transfer is marked SIMULATED.
- Regenerate templates with `.venv/Scripts/python scripts/write_templates.py`. The Hindi and Tamil text needs native-speaker review.

Code map:

| Path | What it holds |
|---|---|
| `panch/normalise` | numerals, amounts, words, dates, invoice numbers, names |
| `panch/checks` | invariants and soft checks |
| `panch/fingerprint` | duplicate routing |
| `panch/vendors` | lanes, bank verification, name match, call-back |
| `panch/decide` | decision engine |
| `panch/planner` | cash and MSME-deadline planner |
| `panch/approval` | bundle hash, voice check, PIN |
| `panch/payouts` | transfer IDs, state machine, ledger |
| `panch/cashfree` | REST clients and webhook signature check |
| `panch/voice` | Bulbul, Saaras, templates, spoken digits |
| `panch/audit` | hash chain |
| `panch/engine.py` | wiring |
| `app/` | FastAPI app and the owner UI |

## Working on `main`

Run `git pull --rebase origin main` before every push. Never force-push.
