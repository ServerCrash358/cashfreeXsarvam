"""Which language is this invoice in?

`read_invoice(path)` gets only a path, and Parse needs a language code
(`auto` is not a Document AI value), so the code comes from, in order:
1. the `language=` argument,
2. a `languages.json` next to the file: {"inv_A.png": "ta-IN", ...},
3. a tag in the file name: inv_A_ta.png, bill-hi.jpg, F.en.pdf,
4. after reading: the dominant script of the vendor name / amount in words,
5. config default_language.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from ..normalise.numerals import dominant_script

_TAG = re.compile(r"(?:^|[_\-. ])(ta|hi|en)(?:[_\-. ]|$)")
SUPPORTED = {"ta": "ta-IN", "hi": "hi-IN", "en": "en-IN"}


def resolve_language(path: Path, explicit: Optional[str]) -> tuple[Optional[str], str]:
    if explicit:
        return explicit, "explicit"
    manifest = path.parent / "languages.json"
    if manifest.exists():
        try:
            with open(manifest, encoding="utf-8") as f:
                table = json.load(f)
            if path.name in table:
                return table[path.name], "manifest"
        except (OSError, ValueError):
            pass
    m = _TAG.search(path.stem.lower())
    if m:
        return SUPPORTED[m.group(1)], "filename"
    return None, "unknown"


def detect_from_text(*texts: Optional[str]) -> Optional[str]:
    script = dominant_script(" ".join(t for t in texts if t))
    return SUPPORTED.get(script) if script else None
