"""Simulated ATS archetypes.

These model *styles* of parsing and ranking seen across the ATS market rather than any
specific vendor. Each profile chooses how it reads the PDF (which text view, how strict
its section matching is) and how much it cares about each check. All tuning lives in
``PROFILE_WEIGHTS``.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from ..extract.engines import PdfDocument, rows_text
from ..extract.layout import layout_text

PROFILE_WEIGHTS: dict[str, dict[str, float]] = {
    "legacy": {
        "parse.extractable": 4, "parse.columns": 4, "parse.tables": 2, "parse.header_footer": 2.5,
        "parse.glyphs": 2, "parse.agreement": 1, "parse.images": 1, "parse.hidden_text": 2, "parse.rotated": 0.5,
        "struct.sections": 3, "struct.headers": 2.5, "struct.dates": 2.5, "struct.chronology": 1, "struct.bullets": 1,
        "contact.fields": 3, "rank.exact": 2, "kw.jd_years": 1.5,
    },
    "modern": {
        "parse.extractable": 4, "parse.columns": 1, "parse.tables": 0.5, "parse.glyphs": 2, "parse.hidden_text": 3,
        "parse.order": 1, "parse.agreement": 0.5,
        "struct.sections": 2.5, "struct.headers": 1, "struct.dates": 2, "struct.chronology": 1, "struct.bullets": 1,
        "contact.fields": 3, "contact.links": 0.5, "rank.semantic": 2.5, "kw.jd_years": 1,
    },
    "keyword": {
        "parse.extractable": 1, "rank.exact": 6, "kw.taxonomy": 1, "kw.jd_years": 2, "kw.jd_title": 1,
        "parse.hidden_text": 1,
    },
    "semantic": {
        "parse.extractable": 1, "rank.semantic": 6, "kw.context": 2, "kw.jd_title": 1.5, "kw.jd_years": 1,
        "content.quantified": 1, "parse.hidden_text": 1.5,
    },
    "skim": {
        "skim.top": 3, "content.bullets": 3, "content.verbs": 1.5, "content.quantified": 2.5, "content.length": 1,
        "content.weak": 1, "fmt.pages": 1.5, "fmt.fonts": 1, "read.density": 1, "struct.chronology": 1,
        "parse.hidden_text": 1, "contact.links": 0.5, "kw.jd_title": 1, "parse.columns": 0.5,
    },
}

# Knockouts: if a check scores below 60 for this profile, the profile's score is capped.
# Weighted averages dilute fatal problems (a scrambled two-column resume still "passes"
# most checks), so these model the failure modes that actually sink an application.
PROFILE_CAPS: dict[str, dict[str, float]] = {
    "legacy": {"parse.extractable": 5, "parse.columns": 50, "contact.fields": 55, "struct.sections": 55,
               "parse.hidden_text": 60, "parse.glyphs": 65},
    "modern": {"parse.extractable": 5, "parse.hidden_text": 55, "contact.fields": 65, "struct.sections": 65},
    "keyword": {"parse.extractable": 5, "parse.hidden_text": 60},
    "semantic": {"parse.extractable": 5, "parse.hidden_text": 50},
    "skim": {"parse.extractable": 5, "parse.hidden_text": 60, "content.bullets": 50},
}


@dataclass(frozen=True)
class Profile:
    key: str
    name: str
    resembles: str
    description: str
    read: Callable[[PdfDocument], str]  # the text this ATS "sees"
    lenient: bool  # section header matching

    @property
    def weights(self) -> dict[str, float]:
        return PROFILE_WEIGHTS[self.key]

    @property
    def caps(self) -> dict[str, float]:
        return PROFILE_CAPS[self.key]


def _legacy_text(doc: PdfDocument) -> str:
    return rows_text(doc, skip_header_footer=True, skip_tables=True)


def _modern_text(doc: PdfDocument) -> str:
    return layout_text(doc)


PROFILES: list[Profile] = [
    Profile("legacy", "Legacy Parser", "older enterprise ATSs",
            "Reads rows straight across the page, skips header/footer zones and tables, accepts only standard section names.",
            _legacy_text, lenient=False),
    Profile("modern", "Modern Parser", "newer startup-focused ATSs",
            "Layout-aware text boxes, lenient section names, reads everything on the page.",
            _modern_text, lenient=True),
    Profile("keyword", "Keyword Ranker", "boolean/keyword search used by recruiters",
            "Exact keyword hits against the JD (or SWE taxonomy), weighted by frequency and recency.",
            _modern_text, lenient=True),
    Profile("semantic", "Semantic Ranker", "AI-assisted matching in newer ATSs",
            "Synonym- and fuzzy-aware matching; credits skills demonstrated in bullets over bare lists.",
            _modern_text, lenient=True),
    Profile("skim", "Recruiter Skim", "a human's 6-second first pass",
            "What a recruiter sees at a glance: top third of page 1, impact, density, length.",
            _modern_text, lenient=True),
]

BY_KEY = {p.key: p for p in PROFILES}
