"""Voice layer (L): templates, transcript parsing, Sarvam Bulbul/Saaras wrapper."""
from .numbers import extract_digits
from .templates import format_inr, render

__all__ = ["render", "format_inr", "extract_digits", "speak", "transcribe"]


def speak(text: str, lang: str) -> bytes:
    from .client import speak as _speak
    return _speak(text, lang)


def transcribe(audio: bytes, lang: str, keyterms=()) -> str:
    from .client import transcribe as _transcribe
    return _transcribe(audio, lang, keyterms)
