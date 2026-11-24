"""Bullet quality, judged the way SWE recruiters and hiring managers read them."""

from __future__ import annotations

import re
from collections import Counter

from ..lexicon import action_verbs, present_tense_verbs, weak_phrases
from .base import CheckResult, Context, band, plural, scale

CAT = "content"

_QUANT = re.compile(
    r"\d+(?:\.\d+)?\s*(?:%|x\b|k\b|m\b|b\b|ms\b|s\b|\+|×)|\$\s?\d|\b\d{2,}(?:,\d{3})*\b|"
    r"\b(?:one|two|three|four|five|six|seven|eight|nine|ten|dozens|hundreds|thousands|millions)\b",
    re.IGNORECASE,
)
_PRONOUNS = re.compile(r"\b(I|me|my|mine|we|our|us)\b")
_STOP = set(["a", "an", "the", "and", "or", "of", "to", "in", "on", "for", "with", "by", "from", "at", "as", "is", "are", "was", "were", "be", "been", "this", "that", "these", "those", "it", "its", "into", "over", "under", "across", "via", "using", "use", "used", "per", "than", "then", "also", "our", "their", "your"])


def _first_word(b: str) -> str:
    m = re.match(r"[A-Za-z][A-Za-z\-']*", b)
    return m.group(0).lower() if m else ""


def _bullets(ctx: Context) -> list[str]:
    return [b for b in ctx.view.bullets if len(b.split()) >= 3]


def bullet_presence(ctx: Context) -> CheckResult | None:
    if _bullets(ctx):
        return None
    return CheckResult("content.bullets", CAT, "Bullet points detected", 0,
                       "No bullet points detected, so content checks were skipped.",
                       fix="Use real bullet characters (•) for achievements under each role and project.", weight=3)


def action_verb_use(ctx: Context) -> CheckResult:
    bullets = _bullets(ctx)
    verbs = action_verbs()
    strong = [b for b in bullets if _first_word(b) in verbs]
    weakish = [b for b in bullets if _first_word(b) not in verbs and not _first_word(b).endswith("ed")]
    ratio = (len(strong) + 0.6 * (len(bullets) - len(strong) - len(weakish))) / len(bullets)
    return CheckResult("content.verbs", CAT, "Bullets start with action verbs", scale(ratio, 0.4, 0.9),
                       f"{len(strong)}/{len(bullets)} bullets start with a strong action verb.",
                       [f"“{b[:70]}”" for b in weakish[:4]],
                       "Lead with what you did: 'Built', 'Reduced', 'Migrated', 'Designed'…" if weakish else None, weight=2)


def quantified(ctx: Context) -> CheckResult:
    bullets = _bullets(ctx)
    q = [b for b in bullets if _QUANT.search(b)]
    ratio = len(q) / len(bullets)
    unq = [b for b in bullets if not _QUANT.search(b)]
    return CheckResult("content.quantified", CAT, "Quantified impact", scale(ratio, 0.15, 0.55),
                       f"{len(q)}/{len(bullets)} bullets ({ratio:.0%}) include a number, % or scale.",
                       [f"“{b[:70]}”" for b in unq[:4]],
                       "Add scale and outcomes: latency (p99 ↓ 40%), throughput, users, $ saved, build time, test coverage."
                       if ratio < 0.55 else None, weight=2.5)


def bullet_length(ctx: Context) -> CheckResult:
    bullets = _bullets(ctx)
    lengths = [len(b.split()) for b in bullets]
    short = [b for b, n in zip(bullets, lengths) if n < 8]
    long = [b for b, n in zip(bullets, lengths) if n > 35]
    avg = sum(lengths) / len(lengths)
    score = 0.6 * band(avg, 12, 28, 14) + 0.4 * scale((len(short) + len(long)) / len(bullets), 0.5, 0.05)
    ev = [f"too long ({len(b.split())}w): “{b[:60]}…”" for b in long[:3]] + [f"too short: “{b}”" for b in short[:3]]
    return CheckResult("content.length", CAT, "Bullet length", score,
                       f"Average {avg:.0f} words per bullet (sweet spot 12–28).", ev,
                       "Keep bullets to 1–2 lines: action + what + how + result." if ev else None, weight=1)


def weak_language(ctx: Context) -> CheckResult:
    text = ctx.view.text.lower()
    found = Counter()
    for phrase in weak_phrases():
        n = len(re.findall(rf"\b{re.escape(phrase)}\b", text))
        if n:
            found[phrase] += n
    total = sum(found.values())
    return CheckResult("content.weak", CAT, "No weak phrases or buzzwords", scale(total, 8, 0),
                       "No weak phrases or buzzwords." if not total else f"{plural(total, 'weak phrase')}/buzzword(s) found.",
                       [f"“{p}” ×{n}" for p, n in found.most_common(8)],
                       "Replace 'responsible for / worked on / helped' with what you actually built or changed." if total else None,
                       weight=1.5)


def pronouns(ctx: Context) -> CheckResult:
    hits = [b for b in _bullets(ctx) if _PRONOUNS.search(b)]
    return CheckResult("content.pronouns", CAT, "No first-person pronouns", scale(len(hits), 6, 0),
                       "No first-person pronouns in bullets." if not hits else f"{plural(len(hits), 'bullet')} use I/we/my.",
                       [f"“{b[:70]}”" for b in hits[:3]], "Drop pronouns: 'I built X' → 'Built X'." if hits else None, weight=0.75)


def tense(ctx: Context) -> CheckResult:
    present = present_tense_verbs()
    wrong = []
    for role in ctx.view.roles:
        if role.is_current:
            continue
        for b in role.bullets:
            fw = _first_word(b)
            if fw in present or fw.endswith("ing"):
                wrong.append(b)
    total = sum(len(r.bullets) for r in ctx.view.roles if not r.is_current) or 1
    return CheckResult("content.tense", CAT, "Past roles in past tense", scale(len(wrong) / total, 0.4, 0.0),
                       "Past roles use past tense consistently." if not wrong else f"{plural(len(wrong), 'bullet')} in past roles use present tense or -ing.",
                       [f"“{b[:70]}”" for b in wrong[:3]], "Past roles: 'Built', not 'Build'/'Building'." if wrong else None, weight=0.75)


def repetition(ctx: Context) -> CheckResult:
    bullets = _bullets(ctx)
    starts = Counter(_first_word(b) for b in bullets)
    over_starts = {w: n for w, n in starts.items() if n >= 3 and w}
    words = Counter(w for b in bullets for w in re.findall(r"[a-z][a-z\-]{3,}", b.lower()) if w not in _STOP)
    over_words = {w: n for w, n in words.most_common(5) if n >= max(5, len(bullets) // 3)}
    issues = len(over_starts) + len(over_words)
    ev = [f"starts with “{w}” ×{n}" for w, n in over_starts.items()] + [f"“{w}” ×{n}" for w, n in over_words.items()]
    return CheckResult("content.repetition", CAT, "Varied wording", scale(issues, 5, 0),
                       "Wording is varied." if not issues else "Some verbs/words are repeated a lot.", ev,
                       "Vary verbs: Built → Architected / Shipped / Implemented." if issues else None, weight=0.75)


def run(ctx: Context) -> list[CheckResult]:
    missing = bullet_presence(ctx)
    if missing:
        return [missing]
    return [action_verb_use(ctx), quantified(ctx), bullet_length(ctx), weak_language(ctx),
            pronouns(ctx), tense(ctx), repetition(ctx)]
