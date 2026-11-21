"""Reading config: config/reading.json plus environment overrides."""
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG_PATH = REPO_ROOT / "config" / "reading.json"


@dataclass
class ReadingConfig:
    default_language: str = "en-IN"
    variants: tuple[str, ...] = ("orig", "binar", "up2x")
    extract_mode: str = "basic"            # NEVER "advanced": it reconciles line items with the total
    extract_send_language: bool = False    # Extract has no language param in sarvamai 0.1.48 (UNVERIFIED server-side)
    parse_for_crops: bool = False
    parse_content_type: str = "mixed"      # printed | handwritten | mixed
    poll_interval_s: float = 3.0
    job_timeout_s: float = 300.0
    max_parallel_jobs: int = 4
    status_retries: int = 4
    min_confidence: Optional[float] = None  # set after the probe; None = not used
    upscale_max_side: int = 4000
    cache_dir: Path = field(default_factory=lambda: REPO_ROOT / "data" / "cache" / "vision")
    offline: bool = False                   # True: cache only, never call Vision (demo mode)

    @classmethod
    def load(cls, path: str | os.PathLike | None = None) -> "ReadingConfig":
        p = Path(path) if path else DEFAULT_CONFIG_PATH
        data: dict = {}
        if p.exists():
            with open(p, encoding="utf-8") as f:
                data = {k: v for k, v in json.load(f).items() if not k.startswith("_")}
        known = {f.name for f in fields(cls)}
        cfg = cls(**{k: v for k, v in data.items() if k in known})
        cfg.variants = tuple(cfg.variants)
        cache = Path(cfg.cache_dir)
        cfg.cache_dir = cache if cache.is_absolute() else REPO_ROOT / cache
        if cfg.extract_mode != "basic":
            raise ValueError("extract_mode must be 'basic': 'advanced' reconciles totals and hides arithmetic traps")
        env_off = os.environ.get("PANCH_VISION_OFFLINE")
        if env_off is not None:
            cfg.offline = env_off.strip().lower() in ("1", "true", "yes")
        return cfg
