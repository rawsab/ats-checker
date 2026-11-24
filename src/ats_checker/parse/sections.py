"""Split resume text into sections by recognizing header lines."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from rapidfuzz import fuzz

from ..lexicon import section_aliases


@dataclass
class Section:
    name: str | None  # canonical name, or None for an unrecognized header
    header: str
    lines: list[str] = field(default_factory=list)
    via: str = "strict"  # "strict" | "lenient" | "fuzzy" | "unknown" | "preamble"

    @property
    def text(self) -> str:
        return "\n".join(self.lines)


def _norm(line: str) -> str:
    s = line.strip().lower()
    s = re.sub(r"^[^a-z]+|[^a-z]+$", "", s)  # strip leading icons/numbers, trailing colons
    return re.sub(r"\s+", " ", s)


def _looks_like_header(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 40 or len(s.split()) > 5:
        return False
    letters = [c for c in s if c.isalpha()]
    return bool(letters) and s.rstrip(":").isupper() and not re.search(r"\d{4}", s)


def classify_header(line: str, *, lenient: bool) -> tuple[str | None, str] | None:
    """Return (canonical, via) if ``line`` is a section header, else None."""
    if len(line.strip()) > 45:
        return None
    norm = _norm(line)
    if not norm:
        return None
    norm_amp = norm.replace("&", "and")
    for canon, groups in section_aliases().items():
        if norm in groups["strict"] or norm_amp in groups["strict"]:
            return canon, "strict"
    if lenient:
        for canon, groups in section_aliases().items():
            if norm in groups["lenient"] or norm_amp in groups["lenient"]:
                return canon, "lenient"
        if _looks_like_header(line):
            best = (None, 0.0)
            for canon, groups in section_aliases().items():
                for alias in groups["strict"] + groups["lenient"]:
                    score = fuzz.ratio(norm, alias)
                    if score > best[1]:
                        best = (canon, score)
            if best[1] >= 88:
                return best[0], "fuzzy"
            return None, "unknown"
    return None


def split_sections(text: str, *, lenient: bool = True) -> list[Section]:
    sections = [Section(name="preamble", header="", via="preamble")]
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        hit = classify_header(line, lenient=lenient)
        if hit:
            canon, via = hit
            sections.append(Section(name=canon, header=line, via=via))
        else:
            sections[-1].lines.append(line)
    return sections


def find(sections: list[Section], name: str) -> list[Section]:
    return [s for s in sections if s.name == name]
