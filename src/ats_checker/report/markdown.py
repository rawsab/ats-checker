from __future__ import annotations

from ..checks.base import CATEGORIES


def to_markdown(report: dict) -> str:
    f = report["file"]
    out = [f"# ATS report: {f['name']}", "",
           f"*{report['created_at']} · {f['pages']} page(s)*", "",
           f"**Overall: {report['overall']:.0f}/100**", ""]
    if report.get("jd"):
        out += [f"Job: **{report['jd']['title']}**", ""]
    out += ["## Simulated ATS profiles", "", "| Profile | Score | Note |", "|---|---:|---|"]
    for p in report["profiles"]:
        note = f"capped by `{p['capped_by']}`" if p.get("capped_by") else ""
        out.append(f"| {p['name']} ({p['resembles']}) | {p['score']:.0f} | {note} |")
    out += ["", "## Categories", "", "| Category | Score |", "|---|---:|"]
    out += [f"| {CATEGORIES.get(c, c)} | {s:.0f} |" for c, s in report["categories"].items()]
    out += ["", "## Issues", ""]
    for c in sorted(report["checks"], key=lambda c: c["score"]):
        if c["severity"] not in ("fail", "warn"):
            continue
        out.append(f"- **{c['name']}** ({c['score']:.0f}): {c['message']}")
        out += [f"  - {e}" for e in c["evidence"][:4]]
        if c.get("fix"):
            out.append(f"  - *Fix:* {c['fix']}")
    skills = report["resume"]["skills"]
    out += ["", "## Skills detected", "", ", ".join(sorted(skills)) or "none", ""]
    return "\n".join(out)
