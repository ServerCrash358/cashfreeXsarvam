"""Module A orchestration: file -> variants -> Vision (cached) -> Invoice."""
from __future__ import annotations

import logging
import os
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Iterable, Optional, Protocol

from ..models import Invoice
from .cache import VisionCache, file_sha256
from .config import ReadingConfig
from .language import detect_from_text, resolve_language
from .mapping import build_invoice, read_variant
from .schema import SCHEMA_VERSION
from .variants import IMAGE_SUFFIXES, make_variants
from .vision import JobOutput, VisionClient

log = logging.getLogger("panch.reading")

SUPPORTED_SUFFIXES = IMAGE_SUFFIXES | {".pdf"}


class VisionLike(Protocol):
    def extract(self, path: str | os.PathLike, *, language: Optional[str] = None) -> JobOutput: ...


class VisionCacheMiss(RuntimeError):
    """Offline mode and nothing cached for this file: pre-run it first."""


_default_client: Optional[VisionClient] = None


def _client(cfg: ReadingConfig) -> VisionClient:
    global _default_client
    if _default_client is None:
        _default_client = VisionClient(config=cfg)
    return _default_client


def read_invoice(
    path: str | os.PathLike,
    *,
    variants: Optional[tuple[str, ...]] = None,
    language: Optional[str] = None,
    client: Optional[VisionLike] = None,
    config: Optional[ReadingConfig] = None,
) -> Invoice:
    """Read one invoice image or PDF into an Invoice.

    Never raises for a bad read: a failed or partial Vision job gives an
    Invoice whose unread fields are None with stable=False. Raises
    VisionCacheMiss only in offline mode when nothing is cached, and
    FileNotFoundError for a missing file.
    """
    cfg = config or ReadingConfig.load()
    p = Path(path)
    if not p.is_file():
        raise FileNotFoundError(str(p))
    wanted = tuple(variants) if variants else cfg.variants
    if "orig" not in wanted:
        wanted = ("orig",) + wanted
    source_hash = file_sha256(p)
    lang, lang_src = resolve_language(p, language)
    cache = VisionCache(cfg.cache_dir)

    files, skipped = make_variants(p, wanted, cache.variants_dir(), source_hash, cfg.upscale_max_side)
    extra = f"{SCHEMA_VERSION}|{cfg.extract_mode}|" + ((lang or "") if cfg.extract_send_language else "")

    def run(variant: str) -> tuple[str, Optional[JobOutput], str]:
        key = cache.key(source_hash, variant, "extract", extra)
        hit = cache.get(key)
        if hit is not None:
            return variant, hit, "cache"
        if cfg.offline:
            return variant, None, "not cached (offline)"
        vc = client or _client(cfg)
        out = vc.extract(files[variant], language=lang)
        if out.usable:
            cache.put(key, out)
        return variant, out, "live"

    order = [v for v in wanted if v in files]
    outputs: dict[str, JobOutput] = {}
    sources: dict[str, str] = {}
    workers = max(1, min(len(order), cfg.max_parallel_jobs))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        for variant, out, src in ex.map(run, order):
            sources[variant] = src
            if out is None:
                skipped[variant] = src
            else:
                outputs[variant] = out

    if cfg.offline and not outputs:
        raise VisionCacheMiss(f"{p.name}: no cached Vision read (run scripts/read_batch.py first)")

    reads = [read_variant(v, outputs[v]) for v in order if v in outputs and outputs[v].usable]
    single_page = p.suffix.lower() in IMAGE_SUFFIXES or any(r.pages_total == 1 for r in reads)
    if lang is None and reads:
        f = reads[0].fields
        lang = detect_from_text(f["vendor_name"].raw, f["words_amount"].raw)
        lang_src = "detected_script" if lang else lang_src
    if lang is None:
        lang, lang_src = cfg.default_language, "default"

    inv, artifacts = build_invoice(source_hash=source_hash, reads=reads, language=lang,
                                   single_page=single_page, min_confidence=cfg.min_confidence)
    artifacts.update({
        "file": p.name,
        "language": lang,
        "language_source": lang_src,
        "schema_version": SCHEMA_VERSION,
        "variants_skipped": skipped,
        "jobs": {v: {"status": o.status, "job_id": o.job_id, "elapsed_s": round(o.elapsed_s, 1),
                     "error": o.error, "source": sources.get(v), "usage": o.usage}
                 for v, o in outputs.items()},
    })
    cache.put_artifacts(source_hash, artifacts)
    return inv


def get_read_artifacts(invoice_or_hash: Invoice | str, config: Optional[ReadingConfig] = None) -> Optional[dict]:
    """Crops (page + region per field), per-variant values and unstable reasons."""
    cfg = config or ReadingConfig.load()
    if isinstance(invoice_or_hash, Invoice):
        h = invoice_or_hash.source_hash
    else:
        h = invoice_or_hash[4:] if invoice_or_hash.startswith("inv_") else invoice_or_hash
    cache = VisionCache(cfg.cache_dir)
    if len(h) >= 24:
        return cache.get_artifacts(h)
    # an invoice id carries only 16 hex chars: find the matching sidecar
    for f in sorted((cache.root / "artifacts").glob(f"{h}*.json")):
        return cache.get_artifacts(f.stem)
    return None


def iter_invoice_files(folder: str | os.PathLike) -> Iterable[Path]:
    for f in sorted(Path(folder).iterdir()):
        if f.is_file() and f.suffix.lower() in SUPPORTED_SUFFIXES:
            yield f


def read_folder(folder: str | os.PathLike, *, config: Optional[ReadingConfig] = None,
                client: Optional[VisionLike] = None, parallel: Optional[int] = None) -> list[Invoice]:
    """Read every invoice in a folder, a few files at a time."""
    cfg = config or ReadingConfig.load()
    files = list(iter_invoice_files(folder))
    n = max(1, parallel or max(1, cfg.max_parallel_jobs // max(1, len(cfg.variants))))
    with ThreadPoolExecutor(max_workers=n) as ex:
        return list(ex.map(lambda f: read_invoice(f, config=cfg, client=client), files))
