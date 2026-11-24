from __future__ import annotations

from dataclasses import dataclass, field

from ..extract.engines import PdfDocument
from ..jd import JobDescription
from ..parse import ResumeView

CATEGORIES = {
    "parseability": "Parseability",
    "structure": "Structure",
    "contact": "Contact",
    "content": "Content",
    "readability": "Readability",
    "formatting": "Formatting",
    "keywords": "Keywords",
}


@dataclass
class CheckResult:
    id: str
    category: str
    name: str
    score: float  # 0-100
    message: str
    evidence: list[str] = field(default_factory=list)
    fix: str | None = None
    weight: float = 1.0
    info: bool = False  # informational: shown, never scored

    @property
    def severity(self) -> str:
        if self.info:
            return "info"
        if self.score >= 85:
            return "pass"
        if self.score >= 60:
            return "warn"
        return "fail"

    def to_dict(self) -> dict:
        return {
            "id": self.id, "category": self.category, "name": self.name, "score": round(self.score, 1),
            "message": self.message, "evidence": self.evidence[:12], "fix": self.fix,
            "weight": self.weight, "info": self.info, "severity": self.severity,
        }


@dataclass
class Context:
    doc: PdfDocument
    view: ResumeView  # the best-effort ("modern") parse used for content-level checks
    jd: JobDescription | None


def scale(value: float, bad: float, good: float) -> float:
    """Linearly map ``value`` to 0..100 where ``bad`` -> 0 and ``good`` -> 100 (either direction)."""
    if good == bad:
        return 100.0
    t = (value - bad) / (good - bad)
    return max(0.0, min(100.0, t * 100))


def band(value: float, lo: float, hi: float, slack: float) -> float:
    """100 inside [lo, hi], falling to 0 at ``slack`` outside it."""
    if lo <= value <= hi:
        return 100.0
    dist = lo - value if value < lo else value - hi
    return max(0.0, 100.0 * (1 - dist / slack))


def weighted_mean(results: list[CheckResult]) -> float:
    scored = [r for r in results if not r.info and r.weight > 0]
    total = sum(r.weight for r in scored)
    if not total:
        return 0.0
    return sum(r.score * r.weight for r in scored) / total


def plural(n: int, word: str) -> str:
    return f"{n} {word}{'' if n == 1 else 's'}"
