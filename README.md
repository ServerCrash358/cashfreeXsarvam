# Panch (working name)

Our build for the Sarvam x Cashfree Buildathon (Bengaluru, 21 Nov 2026), Problem Statement 3: **pay the right bill, to the right person**. Panch reads multilingual invoices (Tamil, Hindi, English; printed and handwritten), pays only what survives deterministic checks, confirms changed bank details by calling the vendor's number on file, plans payments under limited cash and MSME deadlines, takes a replay-proof voice approval, and pays through Cashfree Payouts without ever paying twice.

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
| [docs/BUILD_PROMPT.md](docs/BUILD_PROMPT.md) | One-page brief to paste into a coding agent |

## Setup

```bash
python -m venv .venv
```

```bash
.venv/Scripts/pip install -r requirements.txt
```

Copy `.env.example` to `.env` and fill in your test keys (never commit `.env`). For webhooks, set an ngrok authtoken with `ngrok config add-authtoken <token>`.

## Working on `main`

Run `git pull --rebase origin main` before every push. Never force-push.
