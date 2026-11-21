"""The only module that talks to Sarvam Document AI. Everything else gets a
`JobOutput` and can be tested with a fake.

SDK surface used (read from the installed sarvamai 0.1.48 source):
    client.doc_ai.extract(file=[(name, fh, mime)], schema=..., output_format="json", mode="basic")
    client.doc_ai.parse(file=[...], language="ta-IN", content_type="mixed")
    client.doc_ai.get_status(job_id)            -> .status, .usage
    client.doc_ai.get_results(job_id, format=)  -> extract: result + annotations; parse: documents
Extract has no `language` argument in 0.1.48; Parse does (it defaults to Indic).
"""
from __future__ import annotations

import logging
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional

from .config import ReadingConfig
from .schema import schema_json

log = logging.getLogger("panch.reading.vision")

TERMINAL = {"completed", "partially_completed", "failed", "rejected"}
USABLE = {"completed", "partially_completed"}

MIME = {
    ".pdf": "application/pdf", ".png": "image/png", ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg", ".tif": "image/tiff", ".tiff": "image/tiff",
}


@dataclass
class JobOutput:
    pipeline: str                           # "extract" or "parse"
    status: str                             # terminal status, or "timeout" / "error"
    job_id: Optional[str] = None
    usage: dict = field(default_factory=dict)
    result: dict = field(default_factory=dict)        # extract
    annotations: dict = field(default_factory=dict)   # extract: confidence + sources per leaf
    documents: list = field(default_factory=list)     # parse
    elapsed_s: float = 0.0
    error: Optional[str] = None

    @property
    def usable(self) -> bool:
        return self.status in USABLE

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "JobOutput":
        known = {k: d[k] for k in cls.__dataclass_fields__ if k in d}
        return cls(**known)


class VisionError(RuntimeError):
    pass


def _dump(model: Any) -> dict:
    if model is None:
        return {}
    if isinstance(model, dict):
        return model
    if hasattr(model, "model_dump"):
        return model.model_dump()
    if hasattr(model, "dict"):
        return model.dict()
    return dict(model)


def _status_code(exc: Exception) -> Optional[int]:
    return getattr(exc, "status_code", None)


def make_sdk_client():
    """Real SarvamAI client from SARVAM_API_KEY (loads .env if python-dotenv is there)."""
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except ImportError:  # pragma: no cover
        pass
    key = os.environ.get("SARVAM_API_KEY")
    if not key:
        raise VisionError("SARVAM_API_KEY is not set (put it in .env, never in code)")
    from sarvamai import SarvamAI
    return SarvamAI(api_subscription_key=key)


class VisionClient:
    def __init__(
        self,
        sdk: Any = None,
        *,
        config: Optional[ReadingConfig] = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self._sdk = sdk
        self.cfg = config or ReadingConfig.load()
        self._sleep = sleep
        self._clock = clock

    @property
    def sdk(self):
        if self._sdk is None:
            self._sdk = make_sdk_client()
        return self._sdk

    # ----------------------------------------------------------- public
    def extract(self, path: str | os.PathLike, *, language: Optional[str] = None) -> JobOutput:
        p = Path(path)

        def start():
            with open(p, "rb") as fh:
                kwargs: dict = dict(
                    file=[(p.name, fh, MIME.get(p.suffix.lower(), "application/octet-stream"))],
                    schema=schema_json(),
                    output_format="json",
                    mode=self.cfg.extract_mode,
                )
                if self.cfg.extract_send_language and language:
                    # UNVERIFIED: the endpoint may ignore or reject this field.
                    kwargs["request_options"] = {"additional_body_parameters": {"language": language}}
                return self.sdk.doc_ai.extract(**kwargs)

        return self._run("extract", start, results_format=None)

    def parse(self, path: str | os.PathLike, *, language: str) -> JobOutput:
        p = Path(path)

        def start():
            with open(p, "rb") as fh:
                return self.sdk.doc_ai.parse(
                    file=[(p.name, fh, MIME.get(p.suffix.lower(), "application/octet-stream"))],
                    language=language,
                    content_type=self.cfg.parse_content_type,
                )

        return self._run("parse", start, results_format="json")

    # ---------------------------------------------------------- private
    def _start_with_retry(self, start: Callable[[], Any]):
        # Only retry when the server clearly did not accept the job (429/503):
        # a blind retry after a timeout could create and bill a second job.
        delay = 2.0
        for attempt in range(3):
            try:
                return start()
            except Exception as exc:  # noqa: BLE001 - SDK raises ApiError subclasses
                if _status_code(exc) in (429, 503) and attempt < 2:
                    self._sleep(delay); delay *= 2
                    continue
                raise

    def _call_with_retry(self, fn: Callable[[], Any]):
        delay = 1.0
        for attempt in range(self.cfg.status_retries + 1):
            try:
                return fn()
            except Exception as exc:  # noqa: BLE001
                code = _status_code(exc)
                if code is not None and code < 500 and code != 429:
                    raise
                if attempt >= self.cfg.status_retries:
                    raise
                self._sleep(delay); delay = min(delay * 2, 10.0)

    def _run(self, pipeline: str, start: Callable[[], Any], results_format: Optional[str]) -> JobOutput:
        t0 = self._clock()
        try:
            job = self._start_with_retry(start)
        except Exception as exc:  # noqa: BLE001
            return JobOutput(pipeline, "error", error=f"start failed: {type(exc).__name__}: {exc}",
                             elapsed_s=self._clock() - t0)
        job_id = getattr(job, "job_id", None)
        status = str(getattr(job, "status", "") or "").lower()
        usage: dict = {}
        while status not in TERMINAL:
            if self._clock() - t0 > self.cfg.job_timeout_s:
                return JobOutput(pipeline, "timeout", job_id=job_id, usage=usage,
                                 elapsed_s=self._clock() - t0, error="job did not finish in time")
            self._sleep(self.cfg.poll_interval_s)
            try:
                st = self._call_with_retry(lambda: self.sdk.doc_ai.get_status(job_id))
            except Exception as exc:  # noqa: BLE001
                return JobOutput(pipeline, "error", job_id=job_id, elapsed_s=self._clock() - t0,
                                 error=f"status failed: {type(exc).__name__}: {exc}")
            status = str(getattr(st, "status", "") or "").lower()
            usage = _dump(getattr(st, "usage", None))

        out = JobOutput(pipeline, status, job_id=job_id, usage=usage)
        if status in USABLE:
            try:
                if results_format:
                    res = self._call_with_retry(lambda: self.sdk.doc_ai.get_results(job_id, format=results_format))
                else:
                    res = self._call_with_retry(lambda: self.sdk.doc_ai.get_results(job_id))
                d = _dump(res)
                out.result = d.get("result") or {}
                out.annotations = d.get("annotations") or {}
                out.documents = d.get("documents") or []
                out.usage = d.get("usage") or usage
            except Exception as exc:  # noqa: BLE001
                out.status = "error"
                out.error = f"results failed: {type(exc).__name__}: {exc}"
        out.elapsed_s = self._clock() - t0
        log.info("%s job %s -> %s in %.1fs", pipeline, job_id, out.status, out.elapsed_s)
        return out
