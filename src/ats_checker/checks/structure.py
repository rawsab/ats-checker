"""Sections, dates and chronology, evaluated on a particular parser's view."""

from __future__ import annotations

from ..parse import ResumeView
from .base import CheckResult, Context, plural

CAT = "structure"


def required_sections(ctx: Context, view: ResumeView) -> CheckResult:
    found = set(view.section_names)
    need = ["experience", "education", "skills"]
    missing = [s for s in need if s not in found]
    ev = [f"found: {', '.join(dict.fromkeys(view.section_names)) or 'none'}"]
    # Early-career SWE resumes live or die by projects.
    wants_projects = view.years < 3 and "projects" not in found
    score = 100 - 30 * len(missing) - (10 if wants_projects else 0)
    if missing:
        msg = f"Missing or unrecognized: {', '.join(missing)}."
        fix = "Use plain headers exactly like 'Experience', 'Education', 'Skills'."
    elif wants_projects:
        msg = "Core sections found; no Projects section (important with < 3 years of experience)."
        fix = "Add a Projects section with 2–3 technical projects, the stack used and results."
    else:
        msg = "Experience, Education and Skills all recognized."
        fix = None
    return CheckResult("struct.sections", CAT, "Standard sections present", max(score, 0), msg, ev, fix, weight=3)


def header_naming(ctx: Context, view: ResumeView) -> CheckResult:
    nonstandard = [s.header for s in view.sections if s.via in ("lenient", "fuzzy")]
    unknown = [s.header for s in view.sections if s.via == "unknown"]
    score = 100 - 8 * len(nonstandard) - 15 * len(unknown)
    ev = [f"non-standard: {h}" for h in nonstandard] + [f"unrecognized: {h}" for h in unknown]
    if not ev:
        return CheckResult("struct.headers", CAT, "Standard header names", 100, "All section headers use standard names.", weight=1.5)
    return CheckResult("struct.headers", CAT, "Standard header names", max(score, 20),
                       f"{plural(len(nonstandard) + len(unknown), 'header')} may not map to a standard field in stricter ATSs.",
                       ev, "Rename creative headers ('Where I've Worked', 'Toolbox') to standard ones.", weight=1.5)


def date_formats(ctx: Context, view: ResumeView) -> CheckResult:
    roles = view.roles
    if not roles:
        return CheckResult("struct.dates", CAT, "Parseable, consistent dates", 30,
                           "No date ranges found in Experience. ATSs compute years of experience from these.",
                           fix="Put a date range on every role, e.g. 'Jan 2022 – Present'.", weight=2)
    unparsed = [r.header for r in roles if not r.start.value or not r.end.value]
    fmts = {p.fmt for r in roles for p in (r.start, r.end) if p.fmt not in ("present", "unknown")}
    score = 100 - 25 * len(unparsed) - (15 if len(fmts) > 1 else 0) - (10 if fmts == {"year"} else 0)
    ev = [f"formats used: {', '.join(sorted(fmts)) or 'none'}"] + [f"unparsed: {h[:60]}" for h in unparsed]
    if score >= 100:
        msg = f"All {plural(len(roles), 'role')} have parseable dates in one format."
        fix = None
    else:
        msg = "Dates are inconsistent or missing on some roles." if unparsed or len(fmts) > 1 else "Year-only dates hide tenure length."
        fix = "Use one format everywhere: 'MMM YYYY – MMM YYYY' (e.g. 'Jun 2021 – Aug 2023')."
    return CheckResult("struct.dates", CAT, "Parseable, consistent dates", max(score, 0), msg, ev, fix, weight=2)


def chronology(ctx: Context, view: ResumeView) -> CheckResult:
    dated = [r for r in view.roles if r.start.value]
    if len(dated) < 2:
        return CheckResult("struct.chronology", CAT, "Reverse-chronological order", 100,
                           "Not enough dated roles to check order.", info=True)
    inversions = sum(1 for a, b in zip(dated, dated[1:]) if (b.end.value, b.start.value) > (a.end.value, a.start.value))
    if not inversions:
        return CheckResult("struct.chronology", CAT, "Reverse-chronological order", 100, "Roles are newest-first.", weight=1.5)
    return CheckResult("struct.chronology", CAT, "Reverse-chronological order", 45,
                       f"{plural(inversions, 'role')} out of reverse-chronological order. ATSs treat the first role as your current one.",
                       fix="List roles newest first.", weight=1.5)


def gaps(ctx: Context, view: ResumeView) -> CheckResult:
    dated = sorted((r for r in view.roles if r.start.value and r.end.value), key=lambda r: r.start.value)
    found = []
    for a, b in zip(dated, dated[1:]):
        gap = (b.start.value.year - a.end.value.year) * 12 + b.start.value.month - a.end.value.month
        if gap >= 6:
            found.append(f"{gap} months between '{a.header[:30]}' and '{b.header[:30]}'")
    msg = "No employment gaps of 6+ months." if not found else f"{plural(len(found), 'gap')} of 6+ months (often fine for students; be ready to explain)."
    return CheckResult("struct.gaps", CAT, "Employment gaps", 100, msg, found, info=True)


def section_length(ctx: Context, view: ResumeView) -> CheckResult:
    roles = view.roles
    if not roles:
        return CheckResult("struct.bullets", CAT, "Roles have bullets", 30, "No roles with bullets detected.",
                           fix="Describe each role with 2–5 bullets starting with '•'.", weight=1.5)
    thin = [r.header[:50] for r in roles if len(r.bullets) < 2]
    bloated = [r.header[:50] for r in roles if len(r.bullets) > 7]
    score = 100 - 15 * len(thin) - 8 * len(bloated)
    ev = [f"thin: {h}" for h in thin] + [f"long: {h}" for h in bloated]
    msg = (f"{plural(len(roles), 'role')}, {sum(len(r.bullets) for r in roles)} bullets."
           + (" Some roles have < 2 bullets." if thin else "") + (" Some have > 7." if bloated else ""))
    return CheckResult("struct.bullets", CAT, "Roles have bullets", max(score, 20), msg, ev,
                       "Aim for 3–5 bullets per recent role, fewer for older ones." if ev else None, weight=1.5)


ALL = [required_sections, header_naming, date_formats, chronology, gaps, section_length]


def run(ctx: Context, view: ResumeView | None = None) -> list[CheckResult]:
    view = view or ctx.view
    return [fn(ctx, view) for fn in ALL]
