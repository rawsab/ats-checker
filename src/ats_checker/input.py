"""Turn whatever the terminal produced from a drag-and-drop or paste into a real path."""

from __future__ import annotations

import re
import shlex
from pathlib import Path
from urllib.parse import unquote, urlparse


def normalize_path(raw: str) -> Path:
    s = raw.strip()
    if s.startswith("file://"):
        s = unquote(urlparse(s).path)
    elif len(s) >= 2 and s[0] == s[-1] and s[0] in "'\"":
        s = s[1:-1]
    elif "\\" in s:
        # macOS Terminal/iTerm escape spaces and parens on drop: /a/My\ Resume\ (1).pdf
        try:
            parts = shlex.split(s)
            s = parts[0] if len(parts) == 1 else " ".join(parts)
        except ValueError:
            s = re.sub(r"\\(.)", r"\1", s)
    return Path(s).expanduser()
