"""Layout heuristics computed from word positions: columns, header/footer text, hidden text."""

from __future__ import annotations

import re
from dataclasses import dataclass, replace

from .engines import HEADER_FOOTER_MARGIN_PT, Page, PdfDocument, Word, _rows_text


@dataclass
class ColumnInfo:
    page: int
    gutter_x: float
    gutter_width: float
    rows_spanning_gutter: float  # fraction of rows that cross the gutter


def detect_columns(doc: PdfDocument) -> list[ColumnInfo]:
    """Find a vertical whitespace gutter with text on both sides on most rows.

    Single-column resumes with right-aligned dates have a gap mid-row too, but their
    full-width bullet lines cross that gap, so the gap never stays empty.
    """
    found = []
    for page in doc.pages:
        info = _page_gutter(page)
        if info:
            found.append(info)
    return found


def _page_gutter(page: Page) -> ColumnInfo | None:
    body = [w for w in page.words if w.upright and w.text.strip()]
    if len(body) < 40:
        return None
    rows = _rows(body)
    if len(rows) < 12:
        return None
    bin_w = 2.0
    nbins = int(page.width / bin_w) + 1
    coverage = [0] * nbins
    for row in rows:
        covered = set()
        for w in row:
            for b in range(int(w.x0 / bin_w), min(int(w.x1 / bin_w) + 1, nbins)):
                covered.add(b)
        for b in covered:
            coverage[b] += 1
    n = len(rows)
    lo, hi = int(page.width * 0.2 / bin_w), int(page.width * 0.8 / bin_w)
    best: tuple[int, int] | None = None
    start = None
    for b in range(lo, hi + 1):
        empty = coverage[b] <= max(1, 0.04 * n)
        if empty and start is None:
            start = b
        if (not empty or b == hi) and start is not None:
            end = b
            if best is None or (end - start) > (best[1] - best[0]):
                best = (start, end)
            start = None
    if not best or (best[1] - best[0]) * bin_w < 10:
        return None
    g0, g1 = best
    left = sum(1 for row in rows if any(w.x1 <= g0 * bin_w for w in row))
    right = sum(1 for row in rows if any(w.x0 >= g1 * bin_w for w in row))
    if left < 0.3 * n or right < 0.3 * n:
        return None
    spanning = max(coverage[g0:g1] or [0]) / n
    return ColumnInfo(
        page=page.number,
        gutter_x=(g0 + g1) / 2 * bin_w,
        gutter_width=(g1 - g0) * bin_w,
        rows_spanning_gutter=spanning,
    )


def layout_text(doc: PdfDocument) -> str:
    """Column-aware reading: split each page at its gutter (if any), then read row by row.

    This is how layout-aware parsers recover a sidebar resume, while keeping right-aligned
    dates on the same line as their job title.
    """
    out = []
    for page in doc.pages:
        info = _page_gutter(page)
        if not info:
            out.append(_rows_text(page))
            continue
        left = [w for w in page.words if (w.x0 + w.x1) / 2 < info.gutter_x]
        right = [w for w in page.words if (w.x0 + w.x1) / 2 >= info.gutter_x]
        out.append(_rows_text(replace(page, words=left)) + "\n\n" + _rows_text(replace(page, words=right)))
    return "\n\n".join(out)


def _rows(words: list[Word]) -> list[list[Word]]:
    rows: list[list[Word]] = []
    for w in sorted(words, key=lambda w: (w.top, w.x0)):
        if rows and abs(rows[-1][0].top - w.top) <= 2.5:
            rows[-1].append(w)
        else:
            rows.append([w])
    return rows


def header_footer_words(doc: PdfDocument) -> list[Word]:
    out = []
    for page in doc.pages:
        for w in page.words:
            if w.top < HEADER_FOOTER_MARGIN_PT or w.bottom > page.height - HEADER_FOOTER_MARGIN_PT:
                out.append(w)
    return out


def _is_white(color: tuple | None) -> bool:
    if not color:
        return False
    if len(color) == 1:  # gray
        return color[0] >= 0.97
    if len(color) == 3:  # rgb
        return all(c >= 0.97 for c in color)
    if len(color) == 4:  # cmyk
        return all(c <= 0.03 for c in color)
    return False


def hidden_words(doc: PdfDocument) -> list[Word]:
    """White or microscopic text: the classic keyword-stuffing trick ATSs now flag."""
    return [w for w in doc.words if _is_white(w.color) or (0 < w.size < 3)]


_SUBSET = re.compile(r"^[A-Z]{6}\+")
_STYLE = re.compile(r"[-,]?(Bold|Italic|Oblique|Regular|Medium|Light|Semibold|SemiBold|Black|"
                    r"Heavy|Thin|Book|Roman|MT|PS|BoldItalic|BoldMT|ItalicMT)+$")


def font_family(fontname: str) -> str:
    name = _SUBSET.sub("", fontname)
    prev = None
    while prev != name:
        prev = name
        name = _STYLE.sub("", name)
    return name or fontname


def font_stats(doc: PdfDocument) -> dict:
    families: dict[str, int] = {}
    sizes: dict[float, int] = {}
    for w in doc.words:
        families[font_family(w.fontname)] = families.get(font_family(w.fontname), 0) + len(w.text)
        size = round(w.size * 2) / 2
        sizes[size] = sizes.get(size, 0) + len(w.text)
    total = sum(sizes.values()) or 1
    body_size = max(sizes, key=sizes.get) if sizes else 0.0
    # ignore sizes used for a tiny sliver of text (bullets, separators) when finding the minimum
    meaningful = [s for s, n in sizes.items() if n / total >= 0.02 and s >= 3]
    return {
        "families": dict(sorted(families.items(), key=lambda kv: -kv[1])),
        "body_size": body_size,
        "min_size": min(meaningful) if meaningful else body_size,
        "max_size": max(meaningful) if meaningful else body_size,
    }


def margins(doc: PdfDocument) -> dict[str, float]:
    lefts, rights, tops, bottoms = [], [], [], []
    for page in doc.pages:
        ws = [w for w in page.words if w.text.strip()]
        if not ws:
            continue
        lefts.append(min(w.x0 for w in ws))
        rights.append(page.width - max(w.x1 for w in ws))
        tops.append(min(w.top for w in ws))
        bottoms.append(page.height - max(w.bottom for w in ws))
    if not lefts:
        return {"left": 0.0, "right": 0.0, "top": 0.0, "bottom": 0.0}
    return {"left": min(lefts), "right": min(rights), "top": min(tops), "bottom": min(bottoms)}
