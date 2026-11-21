"""Message templates per language. No generated text anywhere (team rule).

Layout: `templates/<lang>/<message_key>.txt` (one file per message, as in
ARCHITECTURE.md L) wins; otherwise the key is looked up in
`templates/<lang>/messages.json`. Variables use `{name}` placeholders.

Message keys are the lower-cased reason codes (`ARITH_TOTAL` -> `arith_total`)
plus flow messages (`approval_prompt`, `callback_prompt`, ...). PR 2's
`CheckResult.message_key` should follow the same convention.
"""
from __future__ import annotations

import json
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
from pathlib import Path
from string import Formatter

TEMPLATES_DIR = Path(__file__).resolve().parents[2] / "templates"
LANGS = ("ta", "hi", "en")
BCP47 = {"ta": "ta-IN", "hi": "hi-IN", "en": "en-IN"}


class TemplateMissing(KeyError):
    pass


@lru_cache(maxsize=None)
def _bundle(lang: str) -> dict[str, str]:
    path = TEMPLATES_DIR / lang / "messages.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in data.items() if not k.startswith("_")}  # "_review" notes


def template(message_key: str, lang: str) -> str:
    key = message_key.lower()
    single = TEMPLATES_DIR / lang / f"{key}.txt"
    if single.exists():
        return single.read_text(encoding="utf-8").strip()
    bundle = _bundle(lang)
    if key in bundle:
        return bundle[key]
    # Never fall back to English silently: a reason the owner can't read is no reason.
    raise TemplateMissing(f"no template '{key}' for language '{lang}'")


def available_keys(lang: str) -> set[str]:
    keys = set(_bundle(lang))
    d = TEMPLATES_DIR / lang
    if d.exists():
        keys |= {p.stem for p in d.glob("*.txt")}
    return keys


def placeholders(message_key: str, lang: str) -> set[str]:
    return {f for _, f, _, _ in Formatter().parse(template(message_key, lang)) if f}


def format_inr(amount) -> str:
    """Indian digit grouping, commas always (Bulbul reads "22,000" correctly).

    Decimal("125000") -> "1,25,000"; Decimal("12390.50") -> "12,390.50".
    """
    d = amount if isinstance(amount, Decimal) else Decimal(str(amount))
    d = d.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    sign = "-" if d < 0 else ""
    whole, frac = f"{abs(d):.2f}".split(".")
    if len(whole) > 3:
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{sign}{whole}" + ("" if frac == "00" else f".{frac}")


def spoken_code(code: str) -> str:
    """"472" -> "4-7-2" so TTS reads digits one by one."""
    return "-".join(code)


def _prepare(vars: dict) -> dict:
    out = {}
    for k, v in vars.items():
        out[k] = format_inr(v) if isinstance(v, Decimal) else v
    return out


def render(message_key: str, lang: str, **vars) -> str:
    """Fill a template. Decimal values are formatted as Indian rupee figures.

    Raises TemplateMissing if the key does not exist for `lang`, and KeyError if
    a placeholder is not supplied (a half-filled sentence must never be spoken).
    """
    return template(message_key, lang).format_map(_prepare(vars))
