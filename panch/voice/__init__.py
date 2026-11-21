"""Voice layer (ARCHITECTURE section L): templates, Bulbul TTS, Saaras STT.
Sarvam only reads/hears/speaks; every sentence comes from a template."""
from __future__ import annotations

import base64
import os
from pathlib import Path
from typing import Optional

from panch.voice.digits import extract_digits, numbers_from_speech, spoken_to_digits  # noqa: F401

ROOT = Path(__file__).resolve().parents[2]
TEMPLATES = ROOT / "templates"
LANG_CODES = {"en": "en-IN", "hi": "hi-IN", "ta": "ta-IN"}


def _fmt(v) -> str:
    """Numbers above four digits with Indian commas, for correct pronunciation."""
    from decimal import Decimal, InvalidOperation
    if isinstance(v, bool):          # bool is an int subclass; Decimal("True") raises
        return str(v)
    if isinstance(v, (int, Decimal)) or (isinstance(v, str) and v.replace(".", "", 1).isdigit()):
        try:
            d = Decimal(str(v))
        except InvalidOperation:     # e.g. native-script or superscript digits: show as written
            return str(v)
        whole = int(d)
        s = str(whole)
        if len(s) > 3:
            head, tail = s[:-3], s[-3:]
            groups = []
            while len(head) > 2:
                groups.insert(0, head[-2:])
                head = head[:-2]
            if head:
                groups.insert(0, head)
            s = ",".join(groups + [tail])
        frac = d - whole
        return s + (f".{int(frac * 100):02d}" if frac else "")
    return str(v)


def template_path(message_key: str, lang: str) -> Path:
    return TEMPLATES / lang / f"{message_key}.txt"


def render(message_key: str, lang: str = "en", **vars) -> str:
    p = template_path(message_key, lang)
    if not p.exists():
        p = template_path(message_key, "en")
    if not p.exists():
        return message_key
    text = p.read_text(encoding="utf-8").strip()

    class _Safe(dict):
        def __missing__(self, k):
            return "—"
    # identifiers (account last four, invoice/GST numbers, codes) are shown as written, never comma-formatted
    raw_keys = ("last4", "number", "gstin", "ifsc", "code", "known_accounts", "phone")
    return text.format_map(_Safe({k: (str(v) if any(t in k for t in raw_keys) else _fmt(v)) for k, v in vars.items()}))


def _client():
    from sarvamai import SarvamAI
    key = os.getenv("SARVAM_API_KEY")
    if not key:
        raise RuntimeError("SARVAM_API_KEY not set")
    return SarvamAI(api_subscription_key=key)


def speak(text: str, lang: str = "en") -> bytes:
    """Bulbul TTS -> WAV bytes. Raises on failure; callers fall back to text."""
    c = _client()
    last_err: Optional[Exception] = None
    attempts = (
        {"model": "bulbul:v4-flash", "speaker": SPEAKERS.get(lang)},
        {"model": "bulbul:v4-flash"},
        {"model": "bulbul:v2", "speaker": "anushka"},
    )
    for kwargs in attempts:
        kwargs = {k: v for k, v in kwargs.items() if v}
        try:
            r = c.text_to_speech.convert(text=text[:2500], language_code=LANG_CODES.get(lang, "en-IN"), **kwargs)
            return base64.b64decode(r.audios[0])
        except Exception as e:  # try the next model
            last_err = e
    raise RuntimeError(f"TTS failed: {last_err}")


SPEAKERS = {"ta": "vijay_ta_narration", "hi": "ritu_hi_customer", "en": "shubh_enhi_ads"}


def transcribe(audio: bytes, lang: Optional[str] = None, keyterms: Optional[list[str]] = None,
               filename: str = "audio.webm", content_type: str = "audio/webm") -> str:
    """Saaras STT. Tries saaras:v3 codemix (mode documented for v3), then plain defaults."""
    c = _client()
    last_err: Optional[Exception] = None
    attempts = (
        {"model": "saaras:v4", "mode": "codemix"},
        {"model": "saaras:v3", "mode": "codemix"},
        {"model": "saaras:v3"},
    )
    for kw in attempts:
        try:
            args = dict(file=(filename, audio, content_type), **kw)
            if keyterms:
                args["keyterms"] = keyterms
            if lang:
                args["language_code"] = LANG_CODES.get(lang, "unknown")
            r = c.speech_to_text.transcribe(**args)
            return getattr(r, "transcript", "") or ""
        except Exception as e:
            last_err = e
    raise RuntimeError(f"STT failed: {last_err}")
