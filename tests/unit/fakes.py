"""Offline fakes for the Sarvam SDK. No network anywhere in tests/unit.

The response shapes follow the sarvamai 0.1.48 types (DocAiStartJobResponse,
DocAiJobStatusResponse, DocAiGetResultsResponse_Extract). Once the probe has
run, replace CLEAN_RESULT with a real response from data/probe/.
"""
from __future__ import annotations

import copy
from types import SimpleNamespace

CLEAN_RESULT = {
    "invoice_no": "INV-0042",
    "invoice_date": "03-11-2026",
    "vendor_name": "M/s. Sri Murugan Hardwares Pvt Ltd",
    "vendor_gstin": "33AAICP2912R1ZR",
    "buyer_gstin": "33ABCDE0987F6GH",
    "po_no": "PO-118",
    "delivery_date": "",
    "line_items": [
        {"item": "PVC pipe 1 inch", "qty": "10 Nos", "rate": "450.00", "discount": "", "amount": "4,500.00"},
        {"item": "Gate valve", "qty": "5", "rate": "1,200.00", "discount": "", "amount": "6,000.00"},
    ],
    "subtotal": "10,500.00",
    "discount": "",
    "cgst": "945.00",
    "sgst": "945.00",
    "igst": "",
    "tax_total": "1,890.00",
    "total": "₹ 12,390.00",
    "amount_in_words": "Rupees Twelve Thousand Three Hundred Ninety Only",
    "account_holder_name": "JOHN DOE",
    "bank_account": "026291800001191",
    "ifsc": "YESB0000262",
    "upi_id": "",
    "vendor_phone": "+91 98400 12345",
}


def annotations_for(result: dict, confidence: float = 0.97, page: int = 1) -> dict:
    def leaf():
        return {"confidence": confidence,
                "sources": [{"input_page": page, "block_ids": ["b1"],
                             "region": {"x": 0.1, "y": 0.2, "width": 0.3, "height": 0.05,
                                        "coordinate_space": "normalized"}}]}
    out: dict = {}
    for k, v in result.items():
        if isinstance(v, list):
            out[k] = [{kk: leaf() for kk in row} for row in v]
        else:
            out[k] = leaf()
    return out


def result_with(**changes) -> dict:
    r = copy.deepcopy(CLEAN_RESULT)
    r.update(changes)
    return r


class FakeDocAi:
    """Replays canned results. `by_variant` maps a variant name ('orig',
    'binar', 'up2x') to (status, result); the variant is read from the
    uploaded file name."""

    def __init__(self, by_variant: dict, polls_before_done: int = 1):
        self.by_variant = by_variant
        self.polls_before_done = polls_before_done
        self.calls: list[dict] = []
        self._jobs: dict[str, dict] = {}

    @staticmethod
    def _variant_of(name: str) -> str:
        for v in ("binar", "up2x"):
            if f"_{v}." in name:
                return v
        return "orig"

    def extract(self, **kwargs):
        name = kwargs["file"][0][0]
        self.calls.append({"op": "extract", "name": name, **{k: v for k, v in kwargs.items() if k != "file"}})
        v = self._variant_of(name)
        status, result = self.by_variant[v]
        job_id = f"job_{len(self.calls)}_{v}"
        self._jobs[job_id] = {"status": status, "result": result, "polls": 0}
        return SimpleNamespace(job_id=job_id, status="accepted", run_id="r1")

    def get_status(self, job_id):
        j = self._jobs[job_id]
        j["polls"] += 1
        status = j["status"] if j["polls"] >= self.polls_before_done else "processing"
        usage = {"pages_total": 1, "pages_processed": 1,
                 "pages_succeeded": 1 if status == "completed" else 0,
                 "pages_failed": 0 if status == "completed" else 1}
        return SimpleNamespace(job_id=job_id, status=status, usage=usage)

    def get_results(self, job_id, format=None):
        j = self._jobs[job_id]
        return {"job_id": job_id, "type": "extract", "status": j["status"],
                "usage": {"pages_total": 1}, "result": j["result"],
                "annotations": annotations_for(j["result"]), "version": 1}


class FakeSdk:
    def __init__(self, doc_ai: FakeDocAi):
        self.doc_ai = doc_ai


class ExplodingClient:
    """Fails the test if anything tries to call Vision."""

    def extract(self, *a, **k):  # pragma: no cover
        raise AssertionError("Vision was called in offline mode")
