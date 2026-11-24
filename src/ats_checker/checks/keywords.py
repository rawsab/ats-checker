"""Skill/keyword matching against the SWE taxonomy and (optionally) a job description."""

from __future__ import annotations

import re
from dataclasses import dataclass

from rapidfuzz import fuzz

from ..jd import JobDescription
from ..lexicon import Skill, all_skills, taxonomy
from ..parse import ResumeView
from .base import CheckResult, Context, scale

CAT = "keywords"


@dataclass
class SkillHit:
    name: str
    category: str | None
    count: int
    in_recent_role: bool
    in_bullets: bool
    in_skills: bool

    @property
    def where(self) -> str:
        if self.in_recent_role:
            return "recent role"
        if self.in_bullets:
            return "experience/projects"
        if self.in_skills:
            return "skills list only"
        return "elsewhere"


def find_skills(view: ResumeView, skills: list[Skill] | tuple[Skill, ...] | None = None, *, exact: bool = False) -> dict[str, SkillHit]:
    skills = skills if skills is not None else all_skills()
    recent = " \n".join(view.roles[0].bullets + [view.roles[0].header]) if view.roles else ""
    bullets = " \n".join(view.bullets + [r.header for r in view.roles + view.projects])
    skills_text = view.section_text("skills")
    hits = {}
    for s in skills:
        pat = s.exact if exact else s.fuzzy
        count = len(pat.findall(view.text))
        if not count:
            continue
        hits[s.name] = SkillHit(
            name=s.name, category=s.category, count=count,
            in_recent_role=bool(pat.search(recent)),
            in_bullets=bool(pat.search(bullets)),
            in_skills=bool(pat.search(skills_text)),
        )
    return hits


def _fuzzy_fallback(view: ResumeView, skill: Skill) -> bool:
    """Semantic ranker: tolerate small spelling variants of long multi-char terms."""
    if len(skill.name) < 6:
        return False
    needle = skill.name.lower()
    return any(fuzz.ratio(needle, tok) >= 90 for tok in set(re.findall(r"[a-z][a-z0-9.+#\-]{4,}", view.text.lower())))


# --- generic (no JD) ---------------------------------------------------------------------

def taxonomy_coverage(ctx: Context, view: ResumeView | None = None) -> CheckResult:
    view = view or ctx.view
    hits = find_skills(view)
    cats = taxonomy()
    by_cat = {c: [h.name for h in hits.values() if h.category == c] for c in cats}
    covered = sum(1 for v in by_cat.values() if v)
    score = 0.5 * scale(covered, 2, 5) + 0.5 * scale(len(hits), 5, 18)
    ev = [f"{c}: {', '.join(v) if v else '—'}" for c, v in by_cat.items()]
    msg = f"{len(hits)} recognized SWE skills across {covered}/{len(cats)} categories."
    fix = None if score >= 85 else "Name concrete technologies (languages, frameworks, cloud, datastores, CI tooling) and testing practices you've used."
    return CheckResult("kw.taxonomy", CAT, "SWE skill coverage", score, msg, ev, fix, weight=2)


def skills_in_context(ctx: Context, view: ResumeView | None = None) -> CheckResult:
    view = view or ctx.view
    hits = find_skills(view)
    listed = [h for h in hits.values() if h.in_skills]
    if not listed:
        return CheckResult("kw.context", CAT, "Skills backed by experience", 60,
                           "No skills section with recognizable skills to cross-check.", weight=1.5)
    backed = [h for h in listed if h.in_bullets]
    ratio = len(backed) / len(listed)
    unbacked = [h.name for h in listed if not h.in_bullets]
    return CheckResult("kw.context", CAT, "Skills backed by experience", scale(ratio, 0.2, 0.65),
                       f"{len(backed)}/{len(listed)} listed skills also appear in an experience or project bullet.",
                       [f"list-only: {', '.join(unbacked)}"] if unbacked else [],
                       "Weave key skills into bullets ('Built X in Go on Kubernetes…'); semantic rankers weight in-context mentions higher."
                       if ratio < 0.65 else None, weight=1.5)


# --- JD match ------------------------------------------------------------------------------

def _jd_coverage(view: ResumeView, skills: list[Skill], *, semantic: bool) -> tuple[list[str], list[str]]:
    hits = find_skills(view, skills, exact=not semantic)
    matched, missing = [], []
    for s in skills:
        if s.name in hits or (semantic and _fuzzy_fallback(view, s)):
            matched.append(s.name)
        else:
            missing.append(s.name)
    return matched, missing


def jd_required(ctx: Context, view: ResumeView | None = None) -> CheckResult:
    view = view or ctx.view
    jd = ctx.jd
    if not jd.required:
        return CheckResult("kw.jd_required", CAT, "JD required skills", 100, "No specific required technologies found in the JD.", info=True)
    matched, missing = _jd_coverage(view, jd.required, semantic=True)
    ratio = len(matched) / len(jd.required)
    return CheckResult("kw.jd_required", CAT, "JD required skills", scale(ratio, 0.3, 0.85),
                       f"Matched {len(matched)}/{len(jd.required)} required keywords ({ratio:.0%}).",
                       [f"✓ {', '.join(matched)}" if matched else "✓ none", f"✗ {', '.join(missing)}" if missing else "✗ none"],
                       f"If you genuinely have them, add: {', '.join(missing[:8])}." if missing else None, weight=4)


def jd_preferred(ctx: Context, view: ResumeView | None = None) -> CheckResult:
    view = view or ctx.view
    jd = ctx.jd
    if not jd.preferred:
        return CheckResult("kw.jd_preferred", CAT, "JD preferred skills", 100, "No preferred/bonus technologies listed.", info=True)
    matched, missing = _jd_coverage(view, jd.preferred, semantic=True)
    ratio = len(matched) / len(jd.preferred)
    return CheckResult("kw.jd_preferred", CAT, "JD preferred skills", scale(ratio, 0.0, 0.6),
                       f"Matched {len(matched)}/{len(jd.preferred)} preferred keywords.",
                       [f"✓ {', '.join(matched)}" if matched else "✓ none", f"✗ {', '.join(missing)}" if missing else "✗ none"],
                       weight=1.5)


def jd_years(ctx: Context, view: ResumeView | None = None) -> CheckResult:
    view = view or ctx.view
    jd = ctx.jd
    if not jd.min_years:
        return CheckResult("kw.jd_years", CAT, "Years of experience", 100, "JD doesn't state a years requirement.", info=True)
    have = view.years
    score = 100 if have >= jd.min_years else scale(have, jd.min_years - 3, jd.min_years)
    return CheckResult("kw.jd_years", CAT, "Years of experience", score,
                       f"JD asks for {jd.min_years}+ years; dated roles add up to {have:.1f}.",
                       fix=None if score >= 85 else "Knockout filters compare these numbers directly; make sure every relevant role (incl. internships, if allowed) has dates.",
                       weight=2)


_SENIORITY_WORDS = re.compile(r"\b(senior|sr\.?|junior|jr\.?|staff|principal|lead|ii|iii|iv|i|intern|new grad)\b", re.IGNORECASE)


def jd_title(ctx: Context, view: ResumeView | None = None) -> CheckResult:
    view = view or ctx.view
    title = ctx.jd.title
    if not title:
        return CheckResult("kw.jd_title", CAT, "Title alignment", 100, "No title found in JD.", info=True)
    core = _SENIORITY_WORDS.sub("", title.split(",")[0].split(" - ")[0]).strip().lower()
    candidates = [r.header for r in view.roles] + view.text.splitlines()[:4]
    # token_set: "Backend Software Engineer" fully contains "backend engineer"
    best = max((fuzz.token_set_ratio(core, c.lower()) for c in candidates if c.strip() and len(c) < 90), default=0)
    return CheckResult("kw.jd_title", CAT, "Title alignment", scale(best, 50, 90),
                       f"Closest match to '{core}' in your titles/headline: {best:.0f}%.",
                       fix=None if best >= 85 else f"Add a headline under your name that mirrors the role, e.g. '{title.split(',')[0]}'.",
                       weight=1)


def run(ctx: Context) -> list[CheckResult]:
    out = [taxonomy_coverage(ctx), skills_in_context(ctx)]
    if ctx.jd:
        out += [jd_required(ctx), jd_preferred(ctx), jd_years(ctx), jd_title(ctx)]
    return out


# --- ranker scores used by the simulator profiles ----------------------------------------

def ranker_score(view: ResumeView, jd: JobDescription | None, *, semantic: bool) -> tuple[float, list[str], list[str]]:
    """Score keyword fit the way a keyword (exact) or semantic ranker would.

    Exact ranker: canonical names only, rewards frequency and recency.
    Semantic ranker: synonyms + fuzzy, rewards skills demonstrated in bullets over lists.
    """
    if jd and jd.keywords:
        targets = jd.keywords
    else:
        # Without a JD, rank against the taxonomy: up to 3 skills per category count.
        targets = [(s, "generic") for s in all_skills()]
    hits = find_skills(view, [s for s, _ in targets], exact=not semantic)

    def credit(h: SkillHit) -> float:
        if semantic:
            return 1.0 if h.in_bullets else 0.6 if h.in_skills else 0.7
        place = 1.0 if h.in_recent_role else 0.9 if h.in_bullets else 0.75 if h.in_skills else 0.6
        return place * (0.7 + 0.3 * min(h.count, 3) / 3)

    matched = [s.name for s, _ in targets if s.name in hits]
    if jd and jd.keywords:
        weights = {"required": 2.0, "preferred": 1.0}
        total = sum(weights[k] for _, k in targets)
        got = sum(weights[k] * credit(hits[s.name]) for s, k in targets if s.name in hits)
        if semantic:
            for s, k in targets:
                if s.name not in hits and _fuzzy_fallback(view, s):
                    got += weights[k] * 0.8
                    matched.append(s.name)
        ratio = got / total if total else 0
        score = scale(ratio, 0.25, 0.85)
        missing = [s.name for s, k in targets if s.name not in matched and k == "required"]
    else:
        per_cat: dict[str, list[float]] = {}
        for h in hits.values():
            per_cat.setdefault(h.category, []).append(credit(h))
        cat_scores = [sum(sorted(v, reverse=True)[:3]) / 3 for v in per_cat.values()]
        score = scale(sum(cat_scores) / len(taxonomy()), 0.1, 0.6)
        missing = [c for c in taxonomy() if c not in per_cat]
    return score, matched, missing
