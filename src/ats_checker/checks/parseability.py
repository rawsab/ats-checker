"""Can an ATS get clean text out of this PDF at all?"""

from __future__ import annotations

import re
from itertools import combinations

from rapidfuzz import fuzz

from ..extract.layout import detect_columns, header_footer_words, hidden_words
from ..parse.contact import EMAIL, PHONE
from ..parse.sections import split_sections
from .base import CheckResult, Context, plural, scale

CAT = "parseability"


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip().lower()


def extractable(ctx: Context) -> CheckResult:
    doc = ctx.doc
    per_page = doc.char_count / max(doc.page_count, 1)
    if doc.char_count < 200:
        return CheckResult("parse.extractable", CAT, "Text is extractable", 0,
                           f"Only {doc.char_count} characters of real text. This PDF is probably a scanned image or exported as outlines.",
                           fix="Export from your editor as a text PDF (File → Export/Download → PDF), not Print → Save as image/scan.",
                           weight=4)
    # Thin-but-real text is a content problem (see word count), not an extraction one.
    score = 100 if per_page >= 600 else max(70.0, scale(per_page, 200, 600))
    msg = f"{doc.char_count:,} characters over {plural(doc.page_count, 'page')}."
    return CheckResult("parse.extractable", CAT, "Text is extractable", score, msg, weight=4)


def engine_agreement(ctx: Context) -> CheckResult:
    texts = {k: _norm(v) for k, v in ctx.doc.texts.items() if v.strip()}
    if len(texts) < 2:
        return CheckResult("parse.agreement", CAT, "Parsers agree on the text", 0,
                           "Only one extraction engine could read this file.", weight=3)
    pairs = {f"{a}↔{b}": fuzz.ratio(texts[a], texts[b]) for a, b in combinations(sorted(texts), 2)}
    content = {f"{a}↔{b}": fuzz.token_set_ratio(texts[a], texts[b]) for a, b in combinations(sorted(texts), 2)}
    worst_order = min(pairs.values())
    worst_content = min(content.values())
    # Content disagreement (different words) is far worse than ordering disagreement.
    score = 0.6 * scale(worst_content, 80, 99) + 0.4 * scale(worst_order, 55, 92)
    evidence = [f"{k}: order {pairs[k]:.0f}%, words {content[k]:.0f}%" for k in pairs]
    if score >= 85:
        msg = "All three extraction engines produce essentially the same text."
        fix = None
    else:
        msg = (f"Extraction engines disagree (word overlap as low as {worst_content:.0f}%, "
               f"reading-order similarity {worst_order:.0f}%). Different ATSs will see different resumes.")
        fix = "Simplify layout: single column, no text boxes, no tables for layout. Run with --show-text to see each view."
    return CheckResult("parse.agreement", CAT, "Parsers agree on the text", score, msg, evidence, fix, weight=3)


_GARBLED = re.compile(r"\(cid:\d+\)|�|[-]")
_LIGATURES = re.compile(r"[ﬀ-ﬆ]")


def glyphs(ctx: Context) -> CheckResult:
    text = ctx.doc.texts.get("pdfminer", "") + ctx.doc.texts.get("pypdf", "")
    garbled = _GARBLED.findall(text)
    ligs = _LIGATURES.findall(text)
    n = len(garbled) + len(ligs) * 0.3
    score = scale(n, 25, 0)
    ev = []
    if garbled:
        ev.append(f"{len(garbled)} unmapped glyphs, e.g. {', '.join(sorted(set(garbled))[:5])!s}")
    if ligs:
        ev.append(f"{len(ligs)} ligature characters (ﬁ/ﬂ) that break keyword matches like 'conﬁgured'")
    msg = "No garbled characters." if not ev else "Some characters don't map to real text."
    fix = None if not ev else "Use a standard font (Calibri, Arial, Helvetica, Garamond, Latin Modern) and embed it; avoid icon fonts for bullets/contact icons."
    return CheckResult("parse.glyphs", CAT, "Characters decode cleanly", score, msg, ev, fix, weight=2)


def columns(ctx: Context) -> CheckResult:
    cols = detect_columns(ctx.doc)
    if not cols:
        return CheckResult("parse.columns", CAT, "Single-column layout", 100, "No multi-column layout detected.", weight=3)
    ev = [f"page {c.page}: gutter at x≈{c.gutter_x:.0f}pt ({c.gutter_width:.0f}pt wide)" for c in cols]
    return CheckResult(
        "parse.columns", CAT, "Single-column layout", 35,
        f"Multi-column layout on {plural(len(cols), 'page')}. Line-by-line parsers will interleave the columns.",
        ev, "Move sidebar content (skills, contact) into the main column as normal sections.", weight=3,
    )


def tables(ctx: Context) -> CheckResult:
    n = sum(len(p.table_bboxes) for p in ctx.doc.pages)
    if not n:
        return CheckResult("parse.tables", CAT, "No layout tables", 100, "No tables detected.", weight=1.5)
    return CheckResult("parse.tables", CAT, "No layout tables", 55,
                       f"{plural(n, 'table')} detected. Many parsers drop or scramble table cells.",
                       fix="Replace tables with plain lines (e.g. 'Languages: Python, Go, TypeScript').", weight=1.5)


def images(ctx: Context) -> CheckResult:
    n = sum(p.image_count for p in ctx.doc.pages)
    area = max((p.image_area_ratio for p in ctx.doc.pages), default=0)
    if not n:
        return CheckResult("parse.images", CAT, "No images or graphics", 100, "No embedded images.", weight=1)
    score = 40 if area > 0.3 else 75
    return CheckResult("parse.images", CAT, "No images or graphics", score,
                       f"{plural(n, 'image')} embedded (largest covers {area:.0%} of a page). ATSs ignore any text inside images; photos are discouraged for US/CA SWE roles.",
                       fix="Remove photos, logos and skill-bar graphics; write proficiency as text if needed.", weight=1)


def header_footer(ctx: Context) -> CheckResult:
    words = header_footer_words(ctx.doc)
    if not words:
        return CheckResult("parse.header_footer", CAT, "Nothing important in header/footer", 100,
                           "No text in the page header/footer zones.", weight=2)
    text = " ".join(w.text for w in words)
    critical = bool(EMAIL.search(text) or PHONE.search(text))
    if critical:
        return CheckResult("parse.header_footer", CAT, "Nothing important in header/footer", 25,
                           "Contact details sit in the page header/footer zone, which several ATSs skip entirely.",
                           [text[:120]], "Move your name/email/phone into the body of the page (top margin ≥ 0.5in).", weight=2)
    return CheckResult("parse.header_footer", CAT, "Nothing important in header/footer", 80,
                       "Some text sits in the header/footer zone (often page numbers); it may be ignored.",
                       [text[:120]], weight=2)


def hidden_text(ctx: Context) -> CheckResult:
    hidden = hidden_words(ctx.doc)
    if not hidden:
        return CheckResult("parse.hidden_text", CAT, "No hidden text", 100, "No white or microscopic text.", weight=3)
    sample = " ".join(w.text for w in hidden[:25])
    return CheckResult("parse.hidden_text", CAT, "No hidden text", 0,
                       f"{plural(len(hidden), 'word')} of white/microscopic text. Modern ATSs flag this as keyword stuffing and recruiters see it in the plain-text view.",
                       [sample], "Delete the hidden text.", weight=3)


def rotated(ctx: Context) -> CheckResult:
    n = sum(p.rotated_chars for p in ctx.doc.pages)
    if n < 5:
        return CheckResult("parse.rotated", CAT, "No rotated text", 100, "No rotated/vertical text.", weight=0.5)
    return CheckResult("parse.rotated", CAT, "No rotated text", 40, f"{n} rotated characters; most parsers drop them.",
                       fix="Keep all text horizontal.", weight=0.5)


def reading_order(ctx: Context) -> CheckResult:
    orders = {}
    for engine, text in ctx.doc.texts.items():
        names = [s.name for s in split_sections(text) if s.name and s.name != "preamble"]
        orders[engine] = names
    distinct = {tuple(v) for v in orders.values() if v}
    if len(distinct) <= 1:
        return CheckResult("parse.order", CAT, "Consistent reading order", 100,
                           "Every engine reads the sections in the same order.", weight=2)
    ev = [f"{k}: {' → '.join(v) or '(none)'}" for k, v in orders.items()]
    return CheckResult("parse.order", CAT, "Consistent reading order", 50,
                       "Engines read your sections in different orders, so content can be attributed to the wrong section.",
                       ev, "Use a single top-to-bottom flow with no side-by-side blocks.", weight=2)


ALL = [extractable, engine_agreement, glyphs, columns, tables, images, header_footer, hidden_text, rotated, reading_order]


def run(ctx: Context) -> list[CheckResult]:
    return [fn(ctx) for fn in ALL]
