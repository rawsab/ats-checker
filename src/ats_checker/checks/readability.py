from __future__ import annotations

import re

import textstat

from .base import CheckResult, Context, band

CAT = "readability"


def _prose(ctx: Context) -> str:
    # Readability formulas need sentences; treat each bullet as one.
    bullets = ctx.view.bullets
    if bullets:
        return "\n".join(b.rstrip(".") + "." for b in bullets)
    return ctx.view.text


def _word_target(years: float) -> tuple[int, int]:
    if years < 3:
        return 350, 700
    if years < 8:
        return 450, 900
    return 550, 1100


def flesch(ctx: Context) -> CheckResult:
    ease = textstat.flesch_reading_ease(_prose(ctx))
    # Technical resumes naturally score low (jargon, long words); 25–60 is the healthy band.
    score = band(ease, 25, 60, 30)
    msg = f"Flesch reading ease {ease:.0f} (technical resumes: 25–60 is healthy)."
    fix = None
    if ease < 25:
        fix = "Shorten bullets and split compound ones; trim stacked adjectives and nominalizations ('the implementation of' → 'implemented')."
    elif ease > 60:
        fix = "Bullets read very simply; add the technical how (stack, scale, design decisions)."
    return CheckResult("read.flesch", CAT, "Reading ease", score, msg, fix=fix, weight=1)


def grade(ctx: Context) -> CheckResult:
    g = textstat.flesch_kincaid_grade(_prose(ctx))
    score = band(g, 8, 15, 6)
    return CheckResult("read.grade", CAT, "Grade level", score, f"Flesch-Kincaid grade {g:.1f} (target 8–15).",
                       fix=None if score >= 85 else "Aim for crisp bullets a busy engineer can skim.", weight=1)


def word_count(ctx: Context) -> CheckResult:
    words = len(re.findall(r"\b\w+\b", ctx.view.text))
    lo, hi = _word_target(ctx.view.years)
    pages = max(ctx.doc.page_count, 1)
    score = band(words, lo, hi * (1.0 if pages == 1 else 1.3), 300)
    return CheckResult("read.words", CAT, "Word count", score,
                       f"{words} words ({ctx.view.years:.1f} yrs of experience → target {lo}–{hi}).",
                       fix=None if score >= 85 else ("Cut older/less relevant bullets." if words > hi else "Add more detail to recent roles and projects."),
                       weight=1)


def density(ctx: Context) -> CheckResult:
    """Text density per page: wall-of-text resumes get skimmed badly."""
    doc = ctx.doc
    if not doc.pages:
        return CheckResult("read.density", CAT, "Whitespace balance", 0, "No pages.", weight=0.5)
    ratios = []
    for p in doc.pages:
        text_area = sum((w.x1 - w.x0) * (w.bottom - w.top) for w in p.words)
        ratios.append(text_area / (p.width * p.height))
    r = max(ratios)
    score = band(r, 0.08, 0.30, 0.15)
    return CheckResult("read.density", CAT, "Whitespace balance", score, f"Text covers {r:.0%} of the densest page.",
                       fix=None if score >= 85 else ("Add spacing between sections; trim content." if r > 0.30 else "Page looks sparse; consider adding projects."),
                       weight=0.5)


def run(ctx: Context) -> list[CheckResult]:
    return [flesch(ctx), grade(ctx), word_count(ctx), density(ctx)]
