"""Decision engine (ARCHITECTURE section F). Pure and deterministic."""
from __future__ import annotations

from panch.models import CheckResult, Decision, Invoice, Outcome


def decide(inv: Invoice, checks: list[CheckResult]) -> Decision:
    failed = [c for c in checks if not c.passed]
    blocks = [c for c in failed if c.severity == "block"]
    asks = [c for c in failed if c.severity == "ask"]
    if blocks:
        codes = list(dict.fromkeys(c.code for c in blocks)) + list(dict.fromkeys(c.code for c in asks))
        return Decision(inv.id, Outcome.BLOCK, list(dict.fromkeys(codes)), checks)
    if asks:
        return Decision(inv.id, Outcome.ASK, list(dict.fromkeys(c.code for c in asks)), checks)
    return Decision(inv.id, Outcome.PAY, [], checks)
