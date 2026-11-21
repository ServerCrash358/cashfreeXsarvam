"""Append-only, hash-chained audit ledger (ARCHITECTURE section J). JSONL on disk."""
from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

_lock = threading.Lock()


class Audit:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.entries: list[dict] = []
        if path.exists():
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.strip():
                    self.entries.append(json.loads(line))

    def append(self, action: str, payload: dict, actor: str = "panch", entity: Optional[str] = None) -> dict:
        payload = json.loads(json.dumps(payload, default=str))   # snapshot: later mutation can't alter the record
        with _lock:
            prev = self.entries[-1]["hash"] if self.entries else "0" * 64
            e = {"id": len(self.entries) + 1, "at": datetime.now().isoformat(timespec="seconds"), "actor": actor,
                 "action": action, "entity": entity, "payload": payload, "prev_hash": prev}
            e["hash"] = hashlib.sha256((prev + json.dumps({k: e[k] for k in e if k != "hash"}, sort_keys=True,
                                                          default=str)).encode()).hexdigest()
            self.entries.append(e)
            with self.path.open("a", encoding="utf-8") as f:
                f.write(json.dumps(e, default=str, ensure_ascii=False) + "\n")
            return e

    def verify_chain(self) -> bool:
        prev = "0" * 64
        for e in self.entries:
            body = {k: e[k] for k in e if k != "hash"}
            h = hashlib.sha256((prev + json.dumps(body, sort_keys=True, default=str)).encode()).hexdigest()
            if e["prev_hash"] != prev or e["hash"] != h:
                return False
            prev = e["hash"]
        return True

    def for_entity(self, entity: str) -> list[dict]:
        return [e for e in self.entries if e.get("entity") == entity]

    def reset(self):
        with _lock:
            self.entries = []
            if self.path.exists():
                self.path.unlink()
