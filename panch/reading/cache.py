"""Disk cache for Vision output, keyed by file content hash.

Cache files contain whatever Vision read, including full account numbers, so
the cache folder must stay git-ignored (data/cache/ is in .gitignore).
Writes are atomic (temp file + os.replace) so a crash never leaves half a
JSON file, which matters on Windows where antivirus can hold files briefly.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Optional

from .vision import JobOutput


def file_sha256(path: str | os.PathLike) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _atomic_write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as f:
            json.dump(data, f, ensure_ascii=False, indent=1, default=str)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class VisionCache:
    def __init__(self, root: str | os.PathLike):
        self.root = Path(root)

    def key(self, source_hash: str, variant: str, pipeline: str, extra: str = "") -> str:
        tag = hashlib.sha256(extra.encode("utf-8")).hexdigest()[:8] if extra else "0"
        return f"{source_hash[:24]}_{variant}_{pipeline}_{tag}"

    def _path(self, key: str) -> Path:
        return self.root / "jobs" / f"{key}.json"

    def get(self, key: str) -> Optional[JobOutput]:
        p = self._path(key)
        if not p.exists():
            return None
        with open(p, encoding="utf-8") as f:
            return JobOutput.from_dict(json.load(f))

    def put(self, key: str, out: JobOutput) -> None:
        _atomic_write_json(self._path(key), out.to_dict())

    # artifacts sidecar (crops, per-variant values, reasons)
    def artifacts_path(self, source_hash: str) -> Path:
        return self.root / "artifacts" / f"{source_hash[:24]}.json"

    def put_artifacts(self, source_hash: str, data: dict) -> None:
        _atomic_write_json(self.artifacts_path(source_hash), data)

    def get_artifacts(self, source_hash: str) -> Optional[dict]:
        p = self.artifacts_path(source_hash)
        if not p.exists():
            return None
        with open(p, encoding="utf-8") as f:
            return json.load(f)

    def variants_dir(self) -> Path:
        d = self.root / "variants"
        d.mkdir(parents=True, exist_ok=True)
        return d
