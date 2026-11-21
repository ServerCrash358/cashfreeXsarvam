"""Cash and MSME-deadline planner (ARCHITECTURE section G). Pure."""
from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from itertools import combinations
from typing import Optional

from panch.models import Plan, PlanItem, Vendor


def msme_deadline(invoice_date: Optional[date], vendor: Vendor) -> Optional[date]:
    """43B(h)/MSMED: 15 days without a written agreement, else agreed days capped at 45.
    Only micro/small Udyam-registered vendors (not medium, not traders)."""
    if not invoice_date or not vendor.msme_rule_applies or vendor.enterprise_type not in ("micro", "small"):
        return None
    days = min(vendor.agreement_days, 45) if vendor.agreement_days else 15
    return invoice_date + timedelta(days=days)


def plan(items: list[PlanItem], cash: Decimal, today: date, next_run_days: int = 7,
         exact_limit: int = 25) -> Plan:
    horizon = today + timedelta(days=next_run_days)
    at_risk = [i for i in items if i.deadline and i.deadline <= horizon]
    others = [i for i in items if i not in at_risk]

    def prot(sel):
        return sum((i.amount for i in sel if i in at_risk), Decimal("0"))

    best: list[PlanItem] = []
    if len(at_risk) <= exact_limit:
        best_key = (Decimal("-1"), Decimal("0"))
        for r in range(len(at_risk) + 1):
            for combo in combinations(at_risk, r):
                total = sum((i.amount for i in combo), Decimal("0"))
                if total > cash:
                    continue
                # maximise protected rupees, then prefer earlier deadlines (smaller sum of ordinals)
                key = (total, -Decimal(sum(i.deadline.toordinal() for i in combo)))
                if key > best_key:
                    best_key, best = key, list(combo)
    else:
        spent = Decimal("0")
        for i in sorted(at_risk, key=lambda x: (x.deadline, -x.amount)):
            if spent + i.amount <= cash:
                best.append(i)
                spent += i.amount
    chosen = sorted(best, key=lambda x: x.deadline)
    spent = sum((i.amount for i in chosen), Decimal("0"))
    for i in sorted(others, key=lambda x: (x.deadline or date.max, x.invoice_id)):
        if spent + i.amount <= cash:
            chosen.append(i)
            spent += i.amount
    deferred = [i for i in items if i not in chosen]

    # naive: earliest deadline first, then the rest
    naive, nspent = [], Decimal("0")
    for i in sorted(items, key=lambda x: (x.deadline or date.max, x.invoice_id)):
        if nspent + i.amount <= cash:
            naive.append(i)
            nspent += i.amount
    return Plan(cash, chosen, deferred, prot(chosen), naive, prot(naive))
