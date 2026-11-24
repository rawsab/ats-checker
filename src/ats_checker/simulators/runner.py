"""Run every simulated ATS profile against a resume."""

from __future__ import annotations

from dataclasses import dataclass, replace

from ..checks import contact, keywords, structure
from ..checks.base import CheckResult, Context, weighted_mean
from ..lexicon import all_skills
from ..parse import ResumeView, parse_text
from ..parse.contact import extract_contact
from ..parse.experience import DATE_RANGE
from .profiles import PROFILES, Profile


@dataclass
class ProfileResult:
    key: str
    name: str
    resembles: str
    description: str
    score: float
    checks: list[CheckResult]
    text_seen: str
    sections_seen: list[str]
    capped_by: str | None = None  # knockout check that limited the score

    @property
    def top_issues(self) -> list[CheckResult]:
        bad = [c for c in self.checks if not c.info and c.score < 85]
        ranked = sorted(bad, key=lambda c: (c.id != self.capped_by, (c.score - 100) * c.weight))
        return ranked[:3]

    def to_dict(self) -> dict:
        return {
            "key": self.key, "name": self.name, "resembles": self.resembles, "description": self.description,
            "score": round(self.score, 1), "sections_seen": self.sections_seen, "capped_by": self.capped_by,
            "checks": [c.to_dict() for c in self.checks],
            "top_issues": [c.id for c in self.top_issues],
            "text_seen": self.text_seen,
        }


def _rank_check(view: ResumeView, ctx: Context, *, semantic: bool) -> CheckResult:
    score, matched, missing = keywords.ranker_score(view, ctx.jd, semantic=semantic)
    cid = "rank.semantic" if semantic else "rank.exact"
    label = "Semantic keyword fit" if semantic else "Exact keyword fit"
    target = "JD" if ctx.jd and ctx.jd.keywords else "SWE taxonomy"
    miss_label = "missing required" if ctx.jd and ctx.jd.keywords else "empty categories"
    return CheckResult(cid, "keywords", label, score, f"Ranked against the {target}: {len(matched)} keywords matched.",
                       [f"matched: {', '.join(matched[:15])}"] + ([f"{miss_label}: {', '.join(missing[:12])}"] if missing else []),
                       f"Add these if you have them: {', '.join(missing[:8])}." if missing and score < 85 else None)


def _skim_top(ctx: Context) -> CheckResult:
    """What's visible in the top third of page 1."""
    if not ctx.doc.pages:
        return CheckResult("skim.top", "content", "Top third of page 1", 0, "Empty document.")
    page = ctx.doc.pages[0]
    words = [w for w in page.words if w.top < page.height / 3]
    text = " ".join(w.text for w in sorted(words, key=lambda w: (round(w.top), w.x0)))
    c = extract_contact(text)
    skills = [s.name for s in all_skills() if s.fuzzy.search(text)]
    has_role = bool(DATE_RANGE.search(text)) or any(k in text.lower() for k in ("engineer", "developer", "swe"))
    score = (40 if (c.email or c.phone) else 0) + 30 * min(len(skills), 3) / 3 + (30 if has_role else 0)
    ev = [f"contact: {'yes' if c.email or c.phone else 'no'}", f"skills visible: {', '.join(skills[:6]) or 'none'}",
          f"role/title visible: {'yes' if has_role else 'no'}"]
    return CheckResult("skim.top", "content", "Top third of page 1", score,
                       "Contact, a role/title and core skills are visible at a glance." if score >= 85 else "The top of page 1 doesn't sell you quickly.",
                       ev, None if score >= 85 else "Put contact + a one-line headline ('Backend Engineer · Go, Kubernetes, Postgres') and your most recent role in the top third.")


def run_profile(profile: Profile, ctx: Context, general: dict[str, CheckResult]) -> ProfileResult:
    text = profile.read(ctx.doc)
    if profile.key in ("legacy", "modern"):
        view = parse_text(text, lenient=profile.lenient)
        own = {c.id: c for c in structure.run(ctx, view) + contact.run(ctx, view)}
    else:
        view = ctx.view
        own = {}
    own["rank.exact"] = _rank_check(view, ctx, semantic=False)
    own["rank.semantic"] = _rank_check(view, ctx, semantic=True)
    if profile.key == "skim":
        own["skim.top"] = _skim_top(ctx)
    pool = {**general, **own}
    checks = [replace(pool[cid], weight=w) for cid, w in profile.weights.items() if cid in pool]
    score = weighted_mean(checks)
    capped_by = None
    for cid, cap in profile.caps.items():
        check = pool.get(cid)
        if check and not check.info and check.score < 60 and score > cap:
            score, capped_by = cap, cid
    return ProfileResult(profile.key, profile.name, profile.resembles, profile.description, score, checks,
                         text, view.section_names, capped_by)


def run_profiles(ctx: Context, general: list[CheckResult], keys: list[str] | None = None) -> list[ProfileResult]:
    by_id = {c.id: c for c in general}
    return [run_profile(p, ctx, by_id) for p in PROFILES if not keys or p.key in keys]

