"""Compact Markdown report: for exports and for coding agents iterating on a resume."""

from __future__ import annotations

from ..checks.base import CATEGORIES


def _delta(cur: float, prev: float | None) -> str:
    if prev is None:
        return ""
    d = cur - prev
    return " (±0)" if abs(d) < 0.5 else f" ({'+' if d > 0 else '−'}{abs(d):.0f})"


def to_markdown(report: dict, *, prev: dict | None = None, version: dict | None = None) -> str:
    f = report["file"]
    out = [f"# ATS report: {f['name']}", ""]
    meta = [f"{f['pages']} page(s)"]
    if version:
        meta.insert(0, f"v{version['version']} of “{version['lineage_name']}”")
        if version.get("doc_date"):
            meta.append(f"PDF created {version['doc_date'][:10]}")
    if run := report.get("run"):
        meta.append(f"run #{run['id']}")
    out += [" · ".join(meta), ""]
    out += [f"**Overall: {report['overall']:.0f}/100{_delta(report['overall'], prev['overall'] if prev else None)}**"
            + (" vs previous version" if prev else ""), ""]
    jd = report.get("jd")
    out += [f"Job: **{jd['title']}**" if jd else "Job: none (ranked against the generic SWE skills taxonomy)", ""]

    prev_profiles = {p["key"]: p["score"] for p in prev["profiles"]} if prev else {}
    out += ["## Simulated ATS profiles", "", "| Profile | Score | Note |", "|---|---:|---|"]
    for p in report["profiles"]:
        names = {c["id"]: c["name"] for c in p["checks"]}
        if p.get("capped_by"):
            note = f"**knockout:** {names.get(p['capped_by'], p['capped_by'])}"
        elif p["top_issues"]:
            note = "top issue: " + ", ".join(names.get(i, i) for i in p["top_issues"][:2])
        else:
            note = ""
        out.append(f"| {p['name']} ({p['resembles']}) | {p['score']:.0f}{_delta(p['score'], prev_profiles.get(p['key']))} | {note} |")

    prev_cats = prev["categories"] if prev else {}
    out += ["", "## Categories", "", "| Category | Score |", "|---|---:|"]
    out += [f"| {CATEGORIES.get(c, c)} | {s:.0f}{_delta(s, prev_cats.get(c))} |" for c, s in report["categories"].items()]

    if jd:
        checks = {c["id"]: c for c in report["checks"]}
        out += ["", "## Job description match", ""]
        for cid in ("kw.jd_required", "kw.jd_preferred", "kw.jd_years", "kw.jd_title"):
            c = checks.get(cid)
            if c and not c["info"]:
                out.append(f"- **{c['name']}** ({c['score']:.0f}): {c['message']}")
                out += [f"  - {e}" for e in c["evidence"][:2]]

    out += ["", "## Issues (worst first)", ""]
    issues = sorted((c for c in report["checks"] if c["severity"] in ("fail", "warn")),
                    key=lambda c: -c["weight"] * (100 - c["score"]))
    if not issues:
        out.append("None.")
    for c in issues:
        out.append(f"- **[{c['severity'].upper()}] {c['name']}** ({c['score']:.0f}): {c['message']}")
        out += [f"  - {e}" for e in c["evidence"][:4]]
        if c.get("fix"):
            out.append(f"  - *Fix:* {c['fix']}")

    if prev:
        prev_checks = {c["id"]: c for c in prev["checks"]}
        moved = [(c, prev_checks[c["id"]]) for c in report["checks"]
                 if c["id"] in prev_checks and not c["info"] and abs(c["score"] - prev_checks[c["id"]]["score"]) >= 3]
        if moved:
            out += ["", "## Changed since previous version", ""]
            out += [f"- {c['name']}: {o['score']:.0f} → {c['score']:.0f}" for c, o in moved]

    skills = report["resume"]["skills"]
    shown = sorted(n for n, s in skills.items() if s["where"] in ("recent role", "experience/projects"))
    listed = sorted(n for n, s in skills.items() if s["where"] not in ("recent role", "experience/projects"))
    out += ["", "## Skills detected", "",
            f"- In experience/project bullets: {', '.join(shown) or 'none'}",
            f"- Listed only (not shown in any bullet): {', '.join(listed) or 'none'}", ""]
    return "\n".join(out)
