"""TijoriPay engine: wires the pure modules to state, Cashfree and Sarvam. One instance per app."""
from __future__ import annotations

import copy
import json
import threading
from dataclasses import asdict
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Optional

from panch.approval import check_approval, confirm_pin, make_bundle
from panch.audit import Audit
from panch.cashfree import CashfreeUnavailable, PayoutsClient, VerificationClient, verify_signature
from panch.checks import run_invariants
from panch.decide import decide
from panch.fingerprint import HistoryEntry, fingerprint, route_duplicates
from panch.models import Bundle, BundleItem, CheckResult, Invoice, Outcome, PlanItem, Vendor, VendorAccount
from panch.payouts import CF_TO_STATE, Attempt, Ledger, apply_event, transfer_id
from panch.planner import msme_deadline, plan
from panch.reading import invoice_from_extract
from panch.vendors import account_hash, find_vendor, frozen_by, verify_vendor
from panch.vendors.callback import CallbackSession, finish_callback, start_callback
from panch.voice import render
from panch.relay import RelayClient

ROOT = Path(__file__).resolve().parents[1]
_lock = threading.RLock()


def assess(inv: Invoice, vendors: list[Vendor], history: list[HistoryEntry], verifier, cfg: dict,
           callback_result: Optional[CheckResult] = None):
    """The whole gate for one invoice: invariants, duplicates, vendor lane + bank, decision.
    Returns (lane, vendor or None, Decision). Deterministic given the verifier's answers."""
    v = find_vendor(inv, vendors)
    checks = run_invariants(inv, cfg)
    checks += route_duplicates(inv, history, v.id if v else None, v.recurring if v else False, cfg)
    lane, vchecks = verify_vendor(inv, v, vendors, verifier, cfg, callback_result)
    checks += vchecks
    return lane, v, decide(inv, checks)


def _j(v):
    if isinstance(v, Decimal):
        return str(v)
    if isinstance(v, (date, datetime)):
        return v.isoformat()
    return v


class Engine:
    def __init__(self, live: bool = True):
        self.cfg = json.loads((ROOT / "config" / "settings.json").read_text(encoding="utf-8"))
        self.live = live
        self.audit = Audit(ROOT / "data" / "runtime" / "audit.jsonl")
        # live only when keys exist (live=None decides from the keys). Forcing live=True without
        # keys called Cashfree with empty credentials and left changed accounts UNVERIFIABLE.
        self.verifier = VerificationClient(live=None if live else False)
        self.payouts = PayoutsClient()
        # Relay (Cashfree's agent canvas) only in live mode, and only if RELAY_WEBHOOK_URL is set; off in tests
        self.relay = RelayClient() if live else RelayClient(url="")
        self.reset()

    # ------------------------------------------------------------------ state
    def reset(self):
        with _lock:
            fx = json.loads((ROOT / "data" / "fixtures" / "vendors.json").read_text(encoding="utf-8"))
            self.buyer = fx["buyer"]
            self.vendors: list[Vendor] = []
            for v in fx["vendors"]:
                accs = [VendorAccount(**a) for a in v.pop("accounts")]
                self.vendors.append(Vendor(**v, accounts=accs))
            batch = json.loads((ROOT / "data" / "fixtures" / "demo_batch.json").read_text(encoding="utf-8"))
            self.today = date.fromisoformat(self.cfg.get("today") or batch["today"])
            self.raw = {r["id"]: r for r in batch["invoices"]}
            self.expected = {r["id"]: r.get("expected") for r in batch["invoices"]}
            self.history: list[HistoryEntry] = []
            for h in batch["history"]:
                inv = invoice_from_extract(h)
                v = find_vendor(inv, self.vendors)
                self.history.append(HistoryEntry(inv, v.id if v else "", h["status"]))
            self.invoices: dict[str, Invoice] = {k: invoice_from_extract(r) for k, r in self.raw.items()}
            self.state: dict[str, dict] = {}
            self.callbacks: dict[str, CallbackSession] = {}
            self.callback_results: dict[str, CheckResult] = {}
            self.bundles: dict[str, Bundle] = {}
            self.ledger = Ledger()
            self.plan_result = None
            self.webhook_seen: set = set()
            self.events: list[dict] = []
            self.audit.reset()
            self.audit.append("batch_loaded", {"invoices": list(self.raw), "source": "cached Vision Extract"})
            for inv_id in self.invoices:
                self.evaluate(inv_id)
            counts: dict = {}
            for st in self.state.values():
                counts[st["decision"].outcome.value] = counts.get(st["decision"].outcome.value, 0) + 1
            self.relay.trigger("batch_ready", bills=len(self.invoices), outcomes=counts,
                               owner_language=self.cfg.get("owner_lang"))

    def add_invoice(self, inv: Invoice, filename: str) -> str:
        """A newly read invoice (live Vision upload or curveball batch) joins the batch and is decided."""
        with _lock:
            if inv.id in self.invoices:
                self.audit.append("intake_duplicate_file", {"file": filename}, entity=inv.id)
                return inv.id                      # same file twice: one queue keyed by file hash
            self.invoices[inv.id] = inv
            self.raw[inv.id] = {"file": filename}
            self.expected[inv.id] = None
            self.audit.append("invoice_ingested", {"file": filename, "source_hash": inv.source_hash,
                                                   "language": inv.language}, entity=inv.id)
            self.evaluate(inv.id)
            return inv.id

    def vendor(self, vid: Optional[str]) -> Optional[Vendor]:
        return next((v for v in self.vendors if v.id == vid), None)

    def emit(self, kind: str, data: dict):
        self.events.append({"at": datetime.now().isoformat(timespec="seconds"), "kind": kind, **data})
        self.events = self.events[-200:]

    # ------------------------------------------------------------- decisions
    def evaluate(self, inv_id: str, cascade: bool = True):
        with _lock:
            inv = self.invoices[inv_id]
            lane, v, dec = assess(inv, self.vendors, self.history + self._pending_entries(inv_id), self.verifier,
                                  self.cfg, self.callback_results.get(inv_id))
            prev = self.state.get(inv_id, {})
            # PR 3 (U-VEN-13): a pending account change freezes every other unpaid bill of that vendor
            src = None if lane == "CHANGED_ACCOUNT" or not v else frozen_by(
                v.id, inv_id, ((k, s["vendor_id"], s["lane"], s["decision"].outcome.value)
                               for k, s in self.state.items()))
            if src and prev.get("payment", "unpaid") == "unpaid" and dec.outcome == Outcome.PAY:
                other = self.invoices[src]
                dec = decide(inv, dec.checks + [CheckResult(
                    "ACCOUNT_CHANGED", False, "ask",
                    {"frozen_by_invoice": src, "invoice_account_last4": other.account_last4,
                     "known_accounts": ", ".join("xx" + a.last4 for a in v.accounts)}, "account_changed")])
            self.state[inv_id] = {
                "lane": lane, "vendor_id": v.id if v else None, "decision": dec,
                "fingerprint": fingerprint(inv, v.id if v else None),
                "payment": prev.get("payment", "unpaid"),
                "deadline": msme_deadline(inv.date, v) if v else None,
            }
            was = prev.get("decision").outcome if prev.get("decision") else None
            if was is not None and was != Outcome.BLOCK and dec.outcome == Outcome.BLOCK:
                self.relay.trigger("bill_blocked", invoice_id=inv_id, vendor=v.legal_name if v else inv.vendor_name_raw,
                                   amount=str(inv.total), codes=dec.codes)
            self.audit.append("decision", {"outcome": dec.outcome.value, "codes": dec.codes, "lane": lane},
                              entity=inv_id)
            self.emit("decision", {"invoice": inv_id, "outcome": dec.outcome.value})
            # a changed-account bill appearing or resolving moves the freeze: re-check the vendor's other bills
            if cascade and v and "CHANGED_ACCOUNT" in (lane, prev.get("lane")):
                for k, s in list(self.state.items()):
                    if k != inv_id and s["vendor_id"] == v.id and s["payment"] == "unpaid":
                        self.evaluate(k, cascade=False)

    def _pending_entries(self, inv_id: str) -> list[HistoryEntry]:
        """Other invoices in this batch count as history: anything paid or in flight, and any UNPAID invoice
        ingested earlier (first one in wins), so two scans of one bill can never both be PAY. Earlier invoices
        that are themselves BLOCKed don't count (a blocked trap must not shadow the genuine bill)."""
        out = []
        order = list(self.invoices)
        pos = order.index(inv_id) if inv_id in order else len(order)
        for k, st in self.state.items():
            if k == inv_id:
                continue
            if st.get("payment") in ("paid", "in_flight"):
                out.append(HistoryEntry(self.invoices[k], st["vendor_id"] or "", "paid" if st["payment"] == "paid" else "pending"))
            elif (k in order and order.index(k) < pos and st.get("payment") in ("unpaid", "failed")
                  and st["decision"].outcome != Outcome.BLOCK):
                out.append(HistoryEntry(self.invoices[k], st["vendor_id"] or "", "pending"))
        return out

    def explain(self, inv_id: str, lang: str) -> list[dict]:
        st = self.state[inv_id]
        inv = self.invoices[inv_id]
        v = self.vendor(st["vendor_id"])
        out = []
        for c in st["decision"].checks:
            if c.passed:
                continue
            out.append({"code": c.code, "severity": c.severity,
                        "text": render(c.message_key, lang, **{k: v2 for k, v2 in c.evidence.items() if v2 is not None}),
                        "evidence": c.evidence})
        if st.get("payment") == "reversed":       # reopened after a reversal: say so, never "ready to pay"
            out.insert(0, {"code": "PAYOUT_REVERSED", "severity": "ask",
                           "text": render("payout_reversed", lang, amount=inv.total,
                                          vendor=v.legal_name if v else inv.vendor_name_raw),
                           "evidence": {"transfers": [a.transfer_id for a in self.ledger.for_invoice(inv_id)]}})
        if not out:
            key = "outcome_defer" if st.get("deferred") else "outcome_pay"
            out.append({"code": "CASH_DEFERRED" if st.get("deferred") else "OK", "severity": "info",
                        "text": render(key, lang, amount=inv.total, vendor=v.legal_name if v else inv.vendor_name_raw),
                        "evidence": {}})
        return out

    # ------------------------------------------------------------ call-back
    def start_callback(self, inv_id: str) -> CallbackSession:
        with _lock:
            st = self.state[inv_id]
            if st["lane"] != "CHANGED_ACCOUNT":
                raise ValueError("call-back is only for a changed account on a known vendor")
            prev = self.callback_results.get(inv_id)
            if prev is not None and prev.code == "CALLBACK_MISMATCH" and not prev.passed:
                # a mismatch is final: calling again until the digits match would defeat the check
                raise ValueError("vendor already gave different digits on the number on file: bill stays blocked")
            s = start_callback(self.vendor(st["vendor_id"]), self.invoices[inv_id])
            self.callbacks[s.id] = s
            self.audit.append("callback_started", {"phone_used": s.public()["phone_used"],
                                                   "invoice_phone_ignored": s.public()["invoice_phone_ignored"]},
                              entity=inv_id)
            # Relay places the call: it gets the vendor-MASTER phone (it must dial it), the exact template prompt
            # in the vendor's language, and where to post what it heard. Never the expected digits or any account.
            r = self.relay.trigger("callback_requested", invoice_id=inv_id, callback_id=s.id, vendor=s.vendor_id,
                                   phone=s.phone_used, language=s.lang, prompt=s.prompt,
                                   result_path=f"/api/relay/callbacks/{s.id}/result")
            if self.relay.enabled:
                self.audit.append("relay_trigger", {"event": "callback_requested", "result": r.get("result")},
                                  entity=inv_id)
            return s

    def finish_callback(self, cb_id: str, transcript: str, audio: Optional[bytes] = None) -> CheckResult:
        with _lock:
            s = self.callbacks[cb_id]
            if s.result is not None:
                # one answer per call: a second submission must not overwrite a mismatch
                raise ValueError("this call already has a result; start a new call if it was not answered")
            prev = self.callback_results.get(s.invoice_id)
            if prev is not None and prev.code == "CALLBACK_MISMATCH" and not prev.passed:
                raise ValueError("vendor already gave different digits on the number on file: bill stays blocked")
            res = finish_callback(s, transcript, audio)
            s.result = {"code": res.code, "passed": res.passed, "evidence": res.evidence}
            self.callback_results[s.invoice_id] = res
            self.audit.append("callback_result", s.result, entity=s.invoice_id)
            self.evaluate(s.invoice_id)
            return res

    def approve_account_change(self, inv_id: str, pin: str) -> list[str]:
        """Owner approves a call-back-confirmed account change; account joins the master (old kept)."""
        with _lock:
            res = self.callback_results.get(inv_id)
            if not res or not res.passed:
                return ["call-back has not confirmed this account"]
            inv = self.invoices[inv_id]
            v = self.vendor(self.state[inv_id]["vendor_id"])
            if any(a.account_number == inv.account_number and a.ifsc == inv.ifsc for a in v.accounts):
                return []                     # already approved: never add the account twice
            # Red line: money never moves to an account not verified as the vendor's. Once added to
            # the master the account is KNOWN and bank verification is skipped, so require it here.
            checks = self.state[inv_id]["decision"].checks
            bank_ok = any(c.code == "BANK_INVALID" and c.passed for c in checks)
            bank_name_ok = any(c.code == "NAME_MISMATCH" and c.passed
                               and str(c.evidence.get("pair", "")).startswith("name at bank") for c in checks)
            if not (bank_ok and bank_name_ok):
                return ["bank verification has not confirmed this account belongs to the vendor"]
            blocking = [c.code for c in checks if not c.passed and c.severity == "block"]
            if blocking:
                return [f"bill is blocked: {', '.join(blocking)}"]
            from panch.approval import hash_pin
            import hmac
            if not hmac.compare_digest(hash_pin(pin, self.cfg["pin_salt"]), self.cfg["pin_hash"]):
                return ["wrong PIN"]
            v.accounts.append(VendorAccount(inv.account_number, inv.ifsc, "call-back", self.today.isoformat()))
            self.audit.append("account_change_approved", {"vendor": v.id, "new_last4": inv.account_last4}, entity=inv_id)
            self.evaluate(inv_id)
            return []

    # --------------------------------------------------------------- planning
    def make_plan(self, cash: Optional[Decimal] = None):
        with _lock:
            cash = Decimal(str(cash if cash is not None else self.cfg["cash_limit"]))
            items = []
            for k, st in self.state.items():
                # a terminal FAILED/REJECTED attempt may be retried, but only via a new plan + fresh approval
                if st["decision"].outcome in (Outcome.PAY, Outcome.DEFER) and st["payment"] in ("unpaid", "failed"):
                    items.append(PlanItem(k, st["vendor_id"], self.invoices[k].total, st["deadline"]))
            p = plan(items, cash, self.today, int(self.cfg.get("next_run_days", 7)))
            chosen = {i.invoice_id for i in p.chosen}
            for i in items:
                self.state[i.invoice_id]["deferred"] = i.invoice_id not in chosen
                d = self.state[i.invoice_id]["decision"]
                d.outcome = Outcome.PAY if i.invoice_id in chosen else Outcome.DEFER
                d.codes = [] if i.invoice_id in chosen else ["CASH_DEFERRED"]
            self.plan_result = p
            bitems = []
            seen_fp: set = set()
            for i in p.chosen:
                inv = self.invoices[i.invoice_id]
                fp = self.state[i.invoice_id]["fingerprint"]
                if fp in seen_fp:            # backstop: one economic bill never twice in a bundle
                    self.audit.append("bundle_duplicate_dropped", {"fingerprint": fp[:16]}, entity=i.invoice_id)
                    continue
                seen_fp.add(fp)
                ah = account_hash(inv.account_number, inv.ifsc)
                bitems.append(BundleItem(i.invoice_id, f"pnb_{i.vendor_id}_{ah[:8]}", ah, i.amount))
            b = make_bundle(bitems, cash, datetime.now())
            self.bundles[b.id] = b
            self.audit.append("plan", {"cash": str(cash), "chosen": [i.invoice_id for i in p.chosen],
                                       "protected": str(p.protected), "naive_protected": str(p.naive_protected),
                                       "bundle": b.id, "bundle_hash": b.hash}, entity=b.id)
            return p, b

    def approval_prompt(self, b: Bundle, lang: str) -> str:
        return render("approval_prompt", lang, count=len(b.items), total=b.total, code_spoken=" ".join(b.code))

    def approve_voice(self, bundle_id: str, transcript: str, channel: str = "voice"):
        with _lock:
            b = self.bundles[bundle_id]
            res = check_approval(b, transcript, datetime.now(), channel)
            if res.ok:
                b.status = "voice_ok"
            self.audit.append("approval_voice", {"channel": channel, "transcript": transcript, **asdict(res)},
                              actor="owner", entity=bundle_id)
            return res

    def approve_pin(self, bundle_id: str, pin: str) -> list[str]:
        with _lock:
            b = self.bundles[bundle_id]
            reasons = confirm_pin(b, pin, self.cfg["pin_hash"], self.cfg["pin_salt"], datetime.now())
            if not reasons:
                b.status = "approved"
            elif "wrong PIN" in reasons:
                # PR 4: three wrong PINs lock this bundle; the owner must make a fresh plan
                fails = self.__dict__.setdefault("_pin_fails", {})
                fails[bundle_id] = fails.get(bundle_id, 0) + 1
                if fails[bundle_id] >= 3:
                    b.status = "locked"
                    reasons.append("locked after 3 wrong PINs: make a new plan")
            self.audit.append("approval_pin", {"ok": not reasons, "reasons": reasons, "bundle_hash": b.hash},
                              actor="owner", entity=bundle_id)
            return reasons

    # ---------------------------------------------------------------- payouts
    def execute(self, bundle_id: str) -> list[dict]:
        with _lock:
            b = self.bundles[bundle_id]
            if b.status != "approved":
                raise ValueError(f"bundle not approved (status {b.status})")
            b.status = "used"                 # single use
            results = []
            for it in b.items:
                results.append(self._pay_one(b, it))
            return results

    def _pay_one(self, b: Bundle, it: BundleItem) -> dict:
        inv = self.invoices[it.invoice_id]
        st = self.state[it.invoice_id]
        v = self.vendor(st["vendor_id"])
        if st["decision"].outcome != Outcome.PAY:
            return {"invoice": inv.id, "skipped": "decision changed since approval"}
        why = self.ledger.can_start(inv.id, it.amount, inv.total)
        if why:
            return {"invoice": inv.id, "skipped": why}
        attempt_no = 1 + len(self.ledger.for_invoice(inv.id))
        tid = transfer_id(v.id, st["fingerprint"], inv.account_number, it.amount, attempt_no)
        att = self.ledger.add(Attempt(tid, inv.id, b.id, it.beneficiary_id, it.amount, attempt_no))
        self.audit.append("payout_intent", {"transfer_id": tid, "amount": str(it.amount), "bundle_hash": b.hash},
                          entity=inv.id)
        st["payment"] = "in_flight"
        mode = self.cfg.get("payout_mode", "live")
        if mode == "live":
            try:
                code, body = self.payouts.create_beneficiary(it.beneficiary_id, v.account_holder_name,
                                                             inv.account_number, inv.ifsc, v.phone_on_file)
                self.audit.append("beneficiary", {"http": code, "status": body.get("beneficiary_status"),
                                                  "code": body.get("code")}, entity=inv.id)
                apply_event(att, "SENT", source="api")
                code, body = self.payouts.transfer(tid, it.amount, it.beneficiary_id, remarks=f"TijoriPay inv {inv.id}")
                self._apply_cf(att, body, "api_response", http=code)
            except TimeoutError as e:
                apply_event(att, "UNKNOWN", source=f"api {e}")
            except CashfreeUnavailable as e:
                att.simulated = True
                att.history.append({"note": f"live payout unavailable ({e}); simulated", "at": datetime.now().isoformat()})
                apply_event(att, "SENT", source="sim")
        else:
            att.simulated = True
            apply_event(att, "SENT", source="sim")
        self.audit.append("payout_sent", att.to_dict(), entity=inv.id)
        self._sync_invoice(att)
        return att.to_dict()

    def _apply_cf(self, att: Attempt, body: dict, source: str, http: Optional[int] = None):
        status = (body or {}).get("status") or (body or {}).get("transfer_status")
        if body.get("code") == "transfer_id_already_exists" or body.get("status_code") == "DUPLICATE_TRANSFER":
            # "Already sent": the ORIGINAL transfer exists. Never mark this attempt FAILED (that would let a
            # retry create a second payment): take the original's status, or hold at UNKNOWN and poll.
            att.history.append({"note": "duplicate transfer: fetching original status", "source": source})
            try:
                _, body = self.payouts.get_status(att.transfer_id)
                status = body.get("status")
            except Exception:
                body, status = {}, None
            state = CF_TO_STATE.get(status or "", None)
            if state:
                att.cf_transfer_id = body.get("cf_transfer_id") or att.cf_transfer_id
                att.utr = body.get("transfer_utr") or att.utr
                apply_event(att, state, body.get("status_code"), source=f"{source} (duplicate)")
            else:
                apply_event(att, "UNKNOWN", source=f"{source} (duplicate; status unavailable, will poll)")
            return
        att.cf_transfer_id = body.get("cf_transfer_id") or att.cf_transfer_id
        att.utr = body.get("transfer_utr") or att.utr
        state = CF_TO_STATE.get(status or "", None)
        if state:
            apply_event(att, state, body.get("status_code"), source=source)
        else:
            att.history.append({"note": f"unmapped response http={http}", "body_code": body.get("code"),
                                "message": (body.get("message") or "")[:120], "source": source})
            # PR 3: only a 4XX on the transfer POST itself means "not created" (terminal). A 4XX on a status
            # poll (429, 404 while it registers) says nothing about the transfer: keep polling, never FAIL it,
            # or a retry could become a second payment.
            if http and 400 <= http < 500 and source == "api_response":
                apply_event(att, "FAILED", body.get("code"), source=source)

    def _sync_invoice(self, att: Attempt):
        st = self.state[att.invoice_id]
        inv = self.invoices[att.invoice_id]
        v = self.vendor(st["vendor_id"])
        if att.state == "SUCCESS":
            if st["payment"] != "paid":
                st["payment"] = "paid"
                self.relay.trigger("payout_success", invoice_id=inv.id, vendor=v.legal_name, amount=str(att.amount),
                                   transfer_id=att.transfer_id, simulated=att.simulated)
                self.emit("payout", {"invoice": inv.id, "state": "SUCCESS",
                                     "text": render("payout_success", self.cfg["owner_lang"], amount=att.amount,
                                                    vendor=v.legal_name)})
        elif att.state == "REVERSED":
            if st["payment"] != "reversed":
                st["payment"] = "reversed"
                # reopen: never auto-repay; back through verification and a fresh approval
                d = st["decision"]
                d.outcome = Outcome.ASK
                d.codes = ["PAYOUT_REVERSED"]
                self.relay.trigger("payout_reversed", invoice_id=inv.id, vendor=v.legal_name, amount=str(att.amount),
                                   transfer_id=att.transfer_id, simulated=att.simulated)
                self.emit("payout", {"invoice": inv.id, "state": "REVERSED",
                                     "text": render("payout_reversed", self.cfg["owner_lang"], amount=att.amount,
                                                    vendor=v.legal_name)})
                self.audit.append("bill_reopened", {"transfer_id": att.transfer_id}, entity=inv.id)
        elif att.state in ("FAILED", "REJECTED"):
            st["payment"] = "failed"
        else:
            st["payment"] = "in_flight"

    def sweep(self):
        """Reconciliation: poll status for SENT/UNKNOWN/PENDING so a lost webhook never strands a bill."""
        with _lock:
            for att in self.ledger.open_for_sweep():
                if att.simulated:
                    nxt = {"SENT": ("PENDING", None), "UNKNOWN": ("PENDING", None),
                           "PENDING": ("SUCCESS", "COMPLETED")}[att.state]
                    apply_event(att, nxt[0], nxt[1], source="sim_sweep")
                else:
                    try:
                        code, body = self.payouts.get_status(att.transfer_id)
                        if code == 404 and att.state == "UNKNOWN":
                            att.history.append({"note": "not found after UNKNOWN; safe to retry later", "source": "sweep"})
                            continue
                        self._apply_cf(att, body, "sweep", http=code)
                    except Exception as e:
                        att.history.append({"note": f"sweep error {type(e).__name__}", "source": "sweep"})
                self._sync_invoice(att)

    def webhook(self, raw: bytes, headers: dict, verify: bool = True) -> dict:
        ts = headers.get("x-webhook-timestamp", "")
        sig = headers.get("x-webhook-signature", "")
        if verify and not verify_signature(self.payouts.secret, ts, raw, sig):
            self.audit.append("webhook_rejected", {"reason": "bad signature"})
            return {"ok": False, "reason": "bad signature"}
        body = json.loads(raw or b"{}")
        data = body.get("data") or body
        etype = body.get("type") or body.get("event") or data.get("event_type") or ""
        tid = data.get("transfer_id")
        key = (data.get("cf_transfer_id") or tid, data.get("status") or etype, body.get("event_time"))
        with _lock:
            if key in self.webhook_seen:
                return {"ok": True, "duplicate": True}
            self.webhook_seen.add(key)
            att = self.ledger.attempts.get(tid)
            if not att:
                self.audit.append("webhook_unmatched", {"transfer_id": tid, "type": etype})
                return {"ok": True, "unmatched": True}
            state = CF_TO_STATE.get(data.get("status") or "", None) or CF_TO_STATE.get(etype, None)
            applied = apply_event(att, state, data.get("status_code"), source=f"webhook {etype}") if state else False
            self.audit.append("webhook", {"type": etype, "transfer_id": tid, "applied": applied}, entity=att.invoice_id)
            self._sync_invoice(att)
            return {"ok": True, "applied": applied, "state": att.state}

    # -------------------------------------------------------------- scoreboard
    def scoreboard(self) -> dict:
        traps = [k for k, e in self.expected.items() if e == "BLOCK"]
        clean = [k for k, e in self.expected.items() if e == "PAY"]
        out = lambda k: self.state[k]["decision"].outcome
        blocked = [k for k in traps if out(k) == Outcome.BLOCK]
        held = [k for k in traps if out(k) == Outcome.ASK]
        missed = [k for k in traps if out(k) in (Outcome.PAY, Outcome.DEFER)]   # a trap that got through (e.g. owner approved it)
        auto = [k for k in clean if out(k) in (Outcome.PAY, Outcome.DEFER)]
        false_held = [k for k in clean if out(k) == Outcome.ASK and self.state[k]["payment"] != "reversed"]
        false_block = [k for k in clean if out(k) == Outcome.BLOCK]
        return {"traps": len(traps), "traps_blocked": blocked, "traps_held_ask": held, "traps_missed": missed,
                "clean": len(clean), "clean_auto_paid": auto, "clean_falsely_held": false_held,
                "clean_false_blocks": false_block,
                "claim": "zero false blocks on our clean controls, measured" if not false_block else "false blocks present"}

    # ------------------------------------------------------------------- views
    def invoice_view(self, inv_id: str, lang: str) -> dict:
        inv = self.invoices[inv_id]
        st = self.state[inv_id]
        v = self.vendor(st["vendor_id"])
        atts = [a.to_dict() for a in self.ledger.for_invoice(inv_id)]
        return {
            "id": inv_id, "vendor": v.legal_name if v else inv.vendor_name_raw, "vendor_native": inv.vendor_name_raw,
            "language": inv.language, "number": inv.number_raw, "date": _j(inv.date), "total": _j(inv.total),
            "account_last4": inv.account_last4, "ifsc": inv.ifsc, "lane": st["lane"],
            "outcome": st["decision"].outcome.value, "codes": st["decision"].codes,
            "deadline": _j(st["deadline"]), "payment": st["payment"],
            "reasons": self.explain(inv_id, lang), "raw_native": inv.raw_native,
            "file": self.raw[inv_id].get("file"), "payouts": atts,
            "enterprise_type": v.enterprise_type if v else None,
        }
