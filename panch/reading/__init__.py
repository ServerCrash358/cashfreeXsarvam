"""Module A: intake and reading (Sarvam Vision, multi-read, crops).

    from panch.reading import read_invoice
    inv = read_invoice("data/demo/inv_B_ta.png")

Demo mode (cache only, never calls Sarvam): set PANCH_VISION_OFFLINE=1, or
"offline": true in config/reading.json.
"""
from .config import ReadingConfig
from .reader import VisionCacheMiss, get_read_artifacts, read_folder, read_invoice
from .vision import JobOutput, VisionClient

__all__ = ["read_invoice", "read_folder", "get_read_artifacts", "ReadingConfig",
           "VisionClient", "JobOutput", "VisionCacheMiss"]

# Cached Vision output (demo fixtures / pre-read batches) -> Invoice; used by the engine.
from .fixture import invoice_from_extract  # noqa: E402

__all__.append("invoice_from_extract")
