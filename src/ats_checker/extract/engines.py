"""Run several independent PDF text extractors over one file.

Different real-world ATSs read PDFs in different ways, so the disagreements between
these engines are themselves a signal:

- ``rows``    pdfplumber words grouped into visual rows across the whole page width
              (how naive/legacy parsers read: two columns get interleaved)
- ``pdfminer`` pdfminer layout analysis (text boxes, roughly column-aware)
- ``pypdf``   content-stream order with no layout analysis
"""

from __future__ import annotations

import hashlib
import io
import logging
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path

import pdfplumber
from pdfminer.high_level import extract_text as pdfminer_extract_text
from pypdf import PdfReader

# pdfminer/pypdf are noisy about slightly malformed PDFs; that's not our user's problem.
for _name in ("pdfminer", "pypdf"):
    logging.getLogger(_name).setLevel(logging.ERROR)

# Text closer than this to the page's top/bottom edge is treated as living in the
# document header/footer region, which many legacy ATS parsers skip entirely.
HEADER_FOOTER_MARGIN_PT = 30.0


@dataclass
class Word:
    text: str
    x0: float
    x1: float
    top: float
    bottom: float
    page: int
    size: float
    fontname: str
    color: tuple | None
    upright: bool = True


@dataclass
class Page:
    number: int
    width: float
    height: float
    words: list[Word]
    image_count: int
    image_area_ratio: float
    table_bboxes: list[tuple[float, float, float, float]]
    rotated_chars: int
    char_count: int


@dataclass
class PdfDocument:
    path: Path
    filename: str
    size_bytes: int
    sha256: str
    page_count: int
    metadata: dict[str, str]
    xmp_document_id: str | None
    xmp_instance_id: str | None
    pages: list[Page]
    texts: dict[str, str]
    hyperlinks: list[str] = field(default_factory=list)
    errors: dict[str, str] = field(default_factory=dict)

    @property
    def words(self) -> list[Word]:
        return [w for p in self.pages for w in p.words]

    @property
    def char_count(self) -> int:
        return sum(p.char_count for p in self.pages)

    @property
    def created_iso(self) -> str | None:
        """When the PDF was made (CreationDate, else ModDate), as UTC ISO-8601."""
        return pdf_date(self.metadata.get("CreationDate")) or pdf_date(self.metadata.get("ModDate"))


class NotAPdfError(ValueError):
    pass


def _color(value) -> tuple | None:
    if value is None:
        return None
    if isinstance(value, (int, float)):
        return (float(value),)
    try:
        return tuple(float(v) for v in value)
    except (TypeError, ValueError):
        return None


def _rows_text(page: Page, *, skip_header_footer: bool = False, skip_tables: bool = False) -> str:
    """Rebuild page text row-by-row across the full width, like a naive parser."""
    words = page.words
    if skip_header_footer:
        words = [
            w
            for w in words
            if w.top >= HEADER_FOOTER_MARGIN_PT and w.bottom <= page.height - HEADER_FOOTER_MARGIN_PT
        ]
    if skip_tables and page.table_bboxes:
        words = [w for w in words if not _in_any_bbox(w, page.table_bboxes)]
    rows: list[list[Word]] = []
    for w in sorted(words, key=lambda w: (round(w.top), w.x0)):
        if rows and abs(rows[-1][0].top - w.top) <= 2.5:
            rows[-1].append(w)
        else:
            rows.append([w])
    lines = []
    for row in rows:
        row.sort(key=lambda w: w.x0)
        parts = [row[0].text]
        for prev, cur in zip(row, row[1:]):
            gap = cur.x0 - prev.x1
            parts.append("   " if gap > 12 else " ")
            parts.append(cur.text)
        lines.append("".join(parts))
    return "\n".join(lines)


def _in_any_bbox(w: Word, bboxes) -> bool:
    cx, cy = (w.x0 + w.x1) / 2, (w.top + w.bottom) / 2
    return any(x0 <= cx <= x1 and top <= cy <= bottom for x0, top, x1, bottom in bboxes)


def rows_text(doc: PdfDocument, *, skip_header_footer=False, skip_tables=False) -> str:
    return "\n\n".join(
        _rows_text(p, skip_header_footer=skip_header_footer, skip_tables=skip_tables)
        for p in doc.pages
    )


def load_pdf(path: Path) -> PdfDocument:
    data = path.read_bytes()
    if not data.startswith(b"%PDF"):
        raise NotAPdfError(f"{path.name} is not a PDF file")

    errors: dict[str, str] = {}
    pages: list[Page] = []
    hyperlinks: list[str] = []
    metadata: dict[str, str] = {}

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for raw in pdf.metadata.items():
            key, value = raw
            if isinstance(value, (str, int, float)):
                metadata[str(key)] = str(value)
        for i, p in enumerate(pdf.pages, start=1):
            raw_words = p.extract_words(
                extra_attrs=["size", "fontname", "non_stroking_color", "upright"],
                # LaTeX/justified PDFs often encode word spaces as ~3pt position gaps with no
                # space glyph; pdfplumber's default 3pt tolerance would glue those words together.
                x_tolerance=1.5,
                keep_blank_chars=False,
                use_text_flow=False,
            )
            words = [
                Word(
                    text=w["text"],
                    x0=float(w["x0"]),
                    x1=float(w["x1"]),
                    top=float(w["top"]),
                    bottom=float(w["bottom"]),
                    page=i,
                    size=float(w.get("size") or 0),
                    fontname=str(w.get("fontname") or ""),
                    color=_color(w.get("non_stroking_color")),
                    upright=bool(w.get("upright", True)),
                )
                for w in raw_words
            ]
            page_area = float(p.width * p.height) or 1.0
            image_area = sum(
                abs(float(im["x1"]) - float(im["x0"])) * abs(float(im["bottom"]) - float(im["top"]))
                for im in p.images
            )
            try:
                tables = [t.bbox for t in p.find_tables()]
            except Exception as exc:  # pdfplumber table finder can choke on odd PDFs
                tables = []
                errors.setdefault("tables", str(exc))
            for link in p.hyperlinks:
                uri = link.get("uri")
                if uri:
                    hyperlinks.append(str(uri))
            pages.append(
                Page(
                    number=i,
                    width=float(p.width),
                    height=float(p.height),
                    words=words,
                    image_count=len(p.images),
                    image_area_ratio=min(image_area / page_area, 1.0),
                    table_bboxes=[tuple(float(v) for v in t) for t in tables],
                    rotated_chars=sum(1 for c in p.chars if not c.get("upright", True)),
                    char_count=len(p.chars),
                )
            )

    xmp_doc_id = xmp_inst_id = None
    try:
        reader = PdfReader(io.BytesIO(data))
        pypdf_text = "\n\n".join((pg.extract_text() or "") for pg in reader.pages)
        try:
            xmp = reader.xmp_metadata
            if xmp is not None:
                xmp_doc_id = xmp.xmpmm_document_id or None
                xmp_inst_id = xmp.xmpmm_instance_id or None
        except Exception:
            pass
    except Exception as exc:
        pypdf_text = ""
        errors["pypdf"] = str(exc)

    try:
        miner_text = pdfminer_extract_text(io.BytesIO(data)) or ""
    except Exception as exc:
        miner_text = ""
        errors["pdfminer"] = str(exc)

    doc = PdfDocument(
        path=path,
        filename=path.name,
        size_bytes=len(data),
        sha256=hashlib.sha256(data).hexdigest(),
        page_count=len(pages),
        metadata=metadata,
        xmp_document_id=_clean_uuid(xmp_doc_id),
        xmp_instance_id=_clean_uuid(xmp_inst_id),
        pages=pages,
        texts={},
        hyperlinks=sorted(set(hyperlinks)),
        errors=errors,
    )
    doc.texts = {
        "rows": rows_text(doc),
        "pdfminer": miner_text,
        "pypdf": pypdf_text,
    }
    return doc


_PDF_DATE = re.compile(r"D?:?(\d{4})(\d{2})?(\d{2})?(\d{2})?(\d{2})?(\d{2})?\s*([Zz+\-])?(\d{2})?'?(\d{2})?")


def pdf_date(raw: str | None) -> str | None:
    """Parse a PDF date string ("D:20261123233911-05'00'") into UTC ISO-8601."""
    if not raw:
        return None
    m = _PDF_DATE.match(str(raw).strip())
    if not m:
        return None
    y, mo, d, h, mi, s, sign, oh, om = m.groups()
    try:
        dt = datetime(int(y), int(mo or 1), int(d or 1), int(h or 0), int(mi or 0), int(s or 0))
    except ValueError:
        return None
    offset = timedelta(0)
    if sign in ("+", "-") and oh:
        offset = timedelta(hours=int(oh), minutes=int(om or 0)) * (1 if sign == "+" else -1)
    return dt.replace(tzinfo=timezone(offset)).astimezone(UTC).isoformat(timespec="seconds")


def _clean_uuid(value: str | None) -> str | None:
    if not value:
        return None
    value = re.sub(r"^(uuid:|xmp\.did:|xmp\.iid:)", "", str(value).strip(), flags=re.IGNORECASE)
    return value or None
