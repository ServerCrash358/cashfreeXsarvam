"""Thin I/O wrapper over the Sarvam SDK: Bulbul speaks, Saaras hears.

SDK method names come from DEPENDENCIES.md (read from sarvamai 0.1.48).
Parameter names marked UNVERIFIED must be confirmed by IT-SARVAM S1, S2, S8.
No chat/LLM endpoint is used here (team rule).
"""
from __future__ import annotations

import base64
import os
from typing import Optional, Sequence

from .templates import BCP47

TTS_MODEL = os.getenv("PANCH_TTS_MODEL", "bulbul:v4-flash")
STT_MODEL = os.getenv("PANCH_STT_MODEL", "saaras:v4")
STT_MODE = os.getenv("PANCH_STT_MODE", "codemix")
# Persona per language, e.g. PANCH_TTS_SPEAKER_TA=<name>_ta_<style>. Unset -> API default.
_SPEAKER_ENV = {"ta": "PANCH_TTS_SPEAKER_TA", "hi": "PANCH_TTS_SPEAKER_HI", "en": "PANCH_TTS_SPEAKER_EN"}

MAX_TTS_CHARS = 2500


class VoiceUnavailable(RuntimeError):
    """No Sarvam key configured, or the SDK is not installed."""


class VoiceClient:
    def __init__(self, api_key: Optional[str] = None, sdk_client=None):
        self._sdk = sdk_client
        self._key = api_key or os.getenv("SARVAM_API_KEY")

    @property
    def sdk(self):
        if self._sdk is None:
            if not self._key:
                raise VoiceUnavailable("SARVAM_API_KEY is not set")
            try:
                from sarvamai import SarvamAI
            except ImportError as e:  # pragma: no cover
                raise VoiceUnavailable("sarvamai is not installed") from e
            self._sdk = SarvamAI(api_subscription_key=self._key)  # arg name: IT-SARVAM S1
        return self._sdk

    @property
    def available(self) -> bool:
        return self._sdk is not None or bool(self._key)

    def speak(self, text: str, lang: str) -> bytes:
        """Text (already rendered from a template) to audio bytes (WAV by default)."""
        if len(text) > MAX_TTS_CHARS:
            raise ValueError(f"TTS text is {len(text)} chars; max {MAX_TTS_CHARS}")
        kwargs = dict(text=text, language_code=BCP47.get(lang, lang), model=TTS_MODEL)  # UNVERIFIED kw: language_code
        speaker = os.getenv(_SPEAKER_ENV.get(lang, ""), "")
        if speaker:
            kwargs["speaker"] = speaker
        resp = self.sdk.text_to_speech.convert(**kwargs)
        audios = getattr(resp, "audios", None) or (resp.get("audios") if isinstance(resp, dict) else None)
        if not audios:
            raise RuntimeError("Bulbul returned no audio")
        return base64.b64decode("".join(audios))

    def transcribe(self, audio: bytes, lang: str, keyterms: Sequence[str] = (),
                   filename: str = "audio.wav", content_type: str = "audio/wav") -> str:
        """Audio (< 30 s, REST) to transcript text."""
        kwargs = dict(
            file=(filename, audio, content_type),
            model=STT_MODEL,
            mode=STT_MODE,                       # UNVERIFIED for v4 (IT-SARVAM S2/S3)
            language_code=BCP47.get(lang, lang),
        )
        if keyterms:
            kwargs["keyterms"] = list(keyterms)
        resp = self.sdk.speech_to_text.transcribe(**kwargs)
        text = getattr(resp, "transcript", None)
        if text is None and isinstance(resp, dict):
            text = resp.get("transcript")
        return text or ""


_default: Optional[VoiceClient] = None


def default_client() -> VoiceClient:
    global _default
    if _default is None:
        _default = VoiceClient()
    return _default


def speak(text: str, lang: str) -> bytes:
    return default_client().speak(text, lang)


def transcribe(audio: bytes, lang: str, keyterms: Sequence[str] = ()) -> str:
    return default_client().transcribe(audio, lang, keyterms)
