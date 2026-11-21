"""Preprocessed variants for multi-read: original, binarised, upscaled.

Needs Pillow (not yet in requirements.txt). Without Pillow, or for PDFs
(rasterising a PDF needs another library), only the original is read and
this is recorded in the read artifacts.
"""
from __future__ import annotations

import logging
from pathlib import Path

log = logging.getLogger("panch.reading.variants")

IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp"}

try:  # optional dependency
    from PIL import Image, ImageOps
    HAVE_PIL = True
except ImportError:  # pragma: no cover
    HAVE_PIL = False


def _otsu(hist: list[int]) -> int:
    total = sum(hist)
    sum_all = sum(i * h for i, h in enumerate(hist))
    sum_b = w_b = 0
    best_t, best_var = 127, -1.0
    for t in range(256):
        w_b += hist[t]
        if w_b == 0:
            continue
        w_f = total - w_b
        if w_f == 0:
            break
        sum_b += t * hist[t]
        m_b = sum_b / w_b
        m_f = (sum_all - sum_b) / w_f
        var = w_b * w_f * (m_b - m_f) ** 2
        if var > best_var:
            best_var, best_t = var, t
    return best_t


def _binarise(src: Path, dst: Path) -> None:
    with Image.open(src) as im:
        g = ImageOps.autocontrast(ImageOps.exif_transpose(im).convert("L"))
        t = _otsu(g.histogram())
        g.point(lambda v: 255 if v > t else 0).save(dst, format="PNG")


def _upscale(src: Path, dst: Path, max_side: int) -> bool:
    with Image.open(src) as im:
        im = ImageOps.exif_transpose(im)
        w, h = im.size
        if max(w, h) * 2 > max_side:
            return False
        if im.mode not in ("RGB", "L"):
            im = im.convert("RGB")
        im.resize((w * 2, h * 2), Image.LANCZOS).save(dst, format="PNG")
    return True


def make_variants(path: Path, wanted: tuple[str, ...], out_dir: Path, source_hash: str,
                  upscale_max_side: int) -> tuple[dict[str, Path], dict[str, str]]:
    """Returns ({variant: file}, {skipped variant: reason}). 'orig' is always the input."""
    made: dict[str, Path] = {}
    skipped: dict[str, str] = {}
    is_image = path.suffix.lower() in IMAGE_SUFFIXES
    for v in wanted:
        if v == "orig":
            made[v] = path
            continue
        if not is_image:
            skipped[v] = f"not an image ({path.suffix}); PDFs are read once"
            continue
        if not HAVE_PIL:
            skipped[v] = "Pillow not installed"
            continue
        dst = out_dir / f"{source_hash[:24]}_{v}.png"
        try:
            if dst.exists():
                made[v] = dst
            elif v == "binar":
                _binarise(path, dst); made[v] = dst
            elif v == "up2x":
                if _upscale(path, dst, upscale_max_side):
                    made[v] = dst
                else:
                    skipped[v] = f"2x would exceed {upscale_max_side}px"
            else:
                skipped[v] = "unknown variant"
        except Exception as exc:  # noqa: BLE001 - a bad variant must not stop the read
            log.warning("variant %s failed for %s: %s", v, path.name, exc)
            skipped[v] = f"failed: {exc}"
    return made, skipped
