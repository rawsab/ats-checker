from __future__ import annotations

import re

from ..extract.layout import font_stats, margins
from .base import CheckResult, Context, scale

CAT = "formatting"

_BAD_TOKENS = {"final", "copy", "draft", "untitled", "new", "document", "doc", "updated", "latest"}


def _generic_filename(stem: str) -> bool:
    tokens = [t for t in re.split(r"[\s_\-.()]+", stem.lower()) if t]
    if not tokens or all(t in {"resume", "cv", "my"} for t in tokens):
        return True
    return any(t in _BAD_TOKENS or re.fullmatch(r"v?\d+", t) for t in tokens)


def page_count(ctx: Context) -> CheckResult:
    pages, years = ctx.doc.page_count, ctx.view.years
    limit = 1 if years < 5 else 2
    if pages <= limit:
        return CheckResult("fmt.pages", CAT, "Page count", 100, f"{pages} page(s) for {years:.1f} years of experience.", weight=1.5)
    score = 55 if pages == limit + 1 else 20
    return CheckResult("fmt.pages", CAT, "Page count", score,
                       f"{pages} pages; with {years:.1f} years, {limit} page(s) is the norm for SWE.",
                       fix="Cut older roles to 1–2 bullets, drop coursework/objective, merge skills lines.", weight=1.5)


def fonts(ctx: Context) -> CheckResult:
    st = font_stats(ctx.doc)
    fams = [f for f, n in st["families"].items() if n > 20]
    score = 100.0
    ev = [f"families: {', '.join(fams[:5])}", f"body {st['body_size']}pt, range {st['min_size']}–{st['max_size']}pt"]
    problems = []
    if len(fams) > 2:
        score -= 15 * (len(fams) - 2)
        problems.append(f"{len(fams)} font families")
    if st["min_size"] and st["min_size"] < 9:
        score -= 30 if st["min_size"] < 8 else 15
        problems.append(f"text as small as {st['min_size']}pt")
    if st["body_size"] and st["body_size"] < 9.5:
        score -= 15
        problems.append(f"body size {st['body_size']}pt")
    msg = "Fonts are consistent and readable." if not problems else "; ".join(problems).capitalize() + "."
    return CheckResult("fmt.fonts", CAT, "Fonts", max(score, 0), msg, ev,
                       "Use 1–2 font families, body 10–11pt, nothing under 9pt." if problems else None, weight=1)


def page_margins(ctx: Context) -> CheckResult:
    m = margins(ctx.doc)
    smallest = min(m["left"], m["right"])
    score = scale(smallest, 18, 36)
    return CheckResult("fmt.margins", CAT, "Margins", score,
                       f"Side margins ≈ {m['left'] / 72:.2f}in / {m['right'] / 72:.2f}in.",
                       fix=None if score >= 85 else "Keep margins ≥ 0.5in; tighter margins get clipped when printed or previewed.",
                       weight=0.5)


def file_props(ctx: Context) -> CheckResult:
    doc = ctx.doc
    ev, score = [], 100.0
    mb = doc.size_bytes / 1_048_576
    if mb > 2:
        score -= 30
        ev.append(f"file is {mb:.1f}MB (some portals cap uploads at 2MB)")
    stem = doc.path.stem
    if _generic_filename(stem) or " " in stem:
        score -= 20
        ev.append(f"filename '{doc.filename}' looks generic/versioned")
    title = doc.metadata.get("Title", "").strip()
    if not title or re.search(r"untitled|microsoft word|\.docx?$", title, re.IGNORECASE):
        score -= 10
        ev.append(f"PDF title metadata is '{title or '(empty)'}', which some ATSs display to recruiters")
    return CheckResult("fmt.file", CAT, "File hygiene", max(score, 0),
                       "File name, size and metadata look good." if not ev else "Filename/metadata could be cleaner.",
                       ev, "Name it 'First_Last_Resume.pdf' and set the document title to your name." if ev else None,
                       weight=0.5)


def run(ctx: Context) -> list[CheckResult]:
    return [page_count(ctx), fonts(ctx), page_margins(ctx), file_props(ctx)]
