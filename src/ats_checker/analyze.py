"""The full pipeline: PDF → views → checks → simulated ATS scores → report dict."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from . import __version__
from .checks import contact, content, formatting, keywords, parseability, readability, structure
from .checks.base import CATEGORIES, CheckResult, Context, weighted_mean
from .extract.engines import PdfDocument, load_pdf
from .extract.layout import layout_text
from .jd import JobDescription
from .parse import parse_text
from .simulators.runner import run_profiles


def general_checks(ctx: Context) -> list[CheckResult]:
    parse_checks = parseability.run(ctx)
    if next(c for c in parse_checks if c.id == "parse.extractable").score == 0:
        # Nothing readable: every downstream check would just be noise.
        return parse_checks
    return (
        parse_checks
        + structure.run(ctx)
        + contact.run(ctx)
        + content.run(ctx)
        + readability.run(ctx)
        + formatting.run(ctx)
        + keywords.run(ctx)
    )


def analyze(path: Path, jd: JobDescription | None = None, *, profiles: list[str] | None = None) -> tuple[dict, PdfDocument]:
    doc = load_pdf(path)
    view = parse_text(layout_text(doc), lenient=True)
    ctx = Context(doc=doc, view=view, jd=jd)
    checks = general_checks(ctx)
    profile_results = run_profiles(ctx, checks, profiles)

    categories = {}
    for cat in CATEGORIES:
        in_cat = [c for c in checks if c.category == cat]
        if any(not c.info for c in in_cat):
            categories[cat] = round(weighted_mean(in_cat), 1)
    overall = sum(p.score for p in profile_results) / len(profile_results) if profile_results else 0

    skills = keywords.find_skills(view)
    report = {
        "tool_version": __version__,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "file": {
            "name": doc.filename, "path": str(doc.path), "sha256": doc.sha256, "size_bytes": doc.size_bytes,
            "pages": doc.page_count, "metadata": doc.metadata, "xmp_document_id": doc.xmp_document_id,
        },
        "overall": round(overall, 1),
        "categories": categories,
        "profiles": [p.to_dict() for p in profile_results],
        "checks": [c.to_dict() for c in checks],
        "resume": {
            "contact": vars(view.contact),
            "sections": view.section_names,
            "experience_years": round(view.years, 1),
            "roles": [{"header": r.header, "start": r.start.raw, "end": r.end.raw, "bullets": len(r.bullets)} for r in view.roles],
            "bullet_count": len(view.bullets),
            "skills": {h.name: {"category": h.category, "count": h.count, "where": h.where} for h in skills.values()},
        },
        "jd": None if not jd else {
            "title": jd.title, "source": jd.source, "sha256": jd.sha256,
            "required": [s.name for s in jd.required], "preferred": [s.name for s in jd.preferred],
            "min_years": jd.min_years, "seniority": jd.seniority,
        },
        "ai": None,
    }
    return report, doc


def bullets_for_ai(doc: PdfDocument) -> list[dict]:
    view = parse_text(layout_text(doc))
    return [{"role": r.header, "bullet": b} for r in view.roles + view.projects for b in r.bullets]
