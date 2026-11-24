"""Render a report dict (fresh or loaded from history) with Rich."""

from __future__ import annotations

from rich import box
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from ..checks.base import CATEGORIES
from ..lexicon import taxonomy
from .charts import bar, color, delta, grade

SEV_STYLE = {"fail": ("✗", "red"), "warn": ("!", "yellow3"), "pass": ("✓", "green"), "info": ("i", "cyan")}


def _header(report: dict, version: dict | None) -> Panel:
    f = report["file"]
    t = Text()
    t.append(f["name"], style="bold")
    t.append(f"  ·  {f['pages']} page(s)  ·  {f['size_bytes'] / 1024:.0f} KB  ·  {f['sha256'][:10]}", style="grey62")
    if version:
        t.append("\n")
        t.append(f"v{version['version']}", style="bold magenta")
        t.append(f" of “{version['lineage_name']}”", style="magenta")
        status = {"existing": "same file seen before", "new_version": "new version detected",
                  "new_lineage": "first time seeing this resume"}.get(version.get("status"), "")
        if status:
            t.append(f"  ({status}", style="grey62")
            if version.get("similarity") is not None and version.get("status") == "new_version":
                t.append(f", {version['similarity']:.0%} similar to an existing version", style="grey62")
            t.append(")", style="grey62")
        if version.get("doc_date"):
            t.append(f"  ·  PDF created {version['doc_date'][:10]}", style="grey62")
    jd = report.get("jd")
    t.append("\n")
    if jd:
        t.append("Job: ", style="grey62")
        t.append(jd["title"] or "(untitled JD)", style="bold cyan")
        t.append(f"  ·  {len(jd['required'])} required / {len(jd['preferred'])} preferred keywords", style="grey62")
        if jd.get("min_years"):
            t.append(f"  ·  {jd['min_years']}+ yrs", style="grey62")
    else:
        t.append("No job description: keywords ranked against the generic SWE taxonomy.", style="grey62")
    return Panel(t, title="[bold]ATS Check[/]", title_align="left", border_style="grey42", box=box.ROUNDED)


def _overall(report: dict, prev: dict | None) -> Panel:
    score = report["overall"]
    t = Text(justify="center")
    t.append(f"\n{score:.0f}", style=f"bold {color(score)}")
    t.append(" / 100\n", style="grey62")
    t.append(grade(score), style=color(score))
    if prev:
        t.append("\n")
        t.append_text(delta(score, prev["overall"]))
        t.append(" vs last version", style="grey50")
    t.append("\n")
    return Panel(t, title="Overall", border_style=color(score), width=24, box=box.ROUNDED)


def _profiles(report: dict, prev: dict | None) -> Panel:
    prev_scores = {p["key"]: p["score"] for p in prev["profiles"]} if prev else {}
    tbl = Table(box=None, pad_edge=False, show_header=False, expand=True)
    tbl.add_column("ATS", min_width=22, max_width=34, no_wrap=True, overflow="ellipsis")
    tbl.add_column("bar", width=24, no_wrap=True)
    tbl.add_column("score", justify="right", width=4)
    tbl.add_column("Δ", width=6)
    tbl.add_column("note", ratio=1, style="grey62", overflow="ellipsis", no_wrap=True)
    checks_by_id = {}
    for p in report["profiles"]:
        checks_by_id.update({c["id"]: c for c in p["checks"]})
    for p in report["profiles"]:
        name = Text(p["name"], style="bold")
        name.append(f"\n{p['resembles']}", style="grey50")
        note = ""
        if p.get("capped_by"):
            note = f"⛔ capped by: {checks_by_id.get(p['capped_by'], {}).get('name', p['capped_by'])}"
        elif p["top_issues"]:
            note = "↳ " + checks_by_id.get(p["top_issues"][0], {}).get("name", p["top_issues"][0])
        tbl.add_row(name, bar(p["score"], 24), Text(f"{p['score']:.0f}", style=f"bold {color(p['score'])}"),
                    delta(p["score"], prev_scores.get(p["key"])), note)
    return Panel(tbl, title="Simulated ATS profiles", title_align="left", border_style="grey42", box=box.ROUNDED)


def _categories(report: dict, prev: dict | None) -> Panel:
    prev_cats = prev["categories"] if prev else {}
    tbl = Table(box=None, show_header=False, expand=True, pad_edge=False)
    tbl.add_column("cat", width=13)
    tbl.add_column("bar", width=18, no_wrap=True)
    tbl.add_column("score", justify="right", width=4)
    tbl.add_column("Δ", width=6)
    for cat, score in report["categories"].items():
        tbl.add_row(CATEGORIES.get(cat, cat), bar(score, 18), Text(f"{score:.0f}", style=color(score)),
                    delta(score, prev_cats.get(cat)))
    return Panel(tbl, title="Categories", title_align="left", border_style="grey42", box=box.ROUNDED)


def _issues(report: dict, *, verbose: bool) -> Panel | None:
    order = {"fail": 0, "warn": 1, "info": 2, "pass": 3}
    shown = [c for c in report["checks"] if c["severity"] in ("fail", "warn") or (verbose and c["severity"] == "info")]
    if verbose:
        shown += [c for c in report["checks"] if c["severity"] == "pass"]
    shown.sort(key=lambda c: (order[c["severity"]], -c["weight"] * (100 - c["score"])))
    if not shown:
        return Panel(Text("No issues found. 🎉", style="green"), title="Issues", border_style="green")
    tbl = Table(box=box.SIMPLE_HEAD, expand=True, show_edge=False, header_style="grey62")
    tbl.add_column("", width=1)
    tbl.add_column("Check", ratio=2)
    tbl.add_column("Finding", ratio=5)
    tbl.add_column("Score", justify="right", width=5)
    for c in shown:
        icon, style = SEV_STYLE[c["severity"]]
        finding = Text(c["message"])
        for ev in c["evidence"][: (6 if verbose else 3)]:
            finding.append(f"\n  {ev}", style="grey50")
        if c.get("fix") and c["severity"] in ("fail", "warn"):
            finding.append("\n→ ", style="cyan")
            finding.append(c["fix"], style="cyan")
        tbl.add_row(Text(icon, style=f"bold {style}"), Text(c["name"], style=style),
                    finding, "" if c["info"] else Text(f"{c['score']:.0f}", style=color(c["score"])))
    return Panel(tbl, title="Issues & fixes", title_align="left", border_style="grey42", box=box.ROUNDED)


def _skills(report: dict) -> Panel:
    skills = report["resume"]["skills"]
    tbl = Table(box=None, show_header=False, expand=True, pad_edge=False)
    tbl.add_column("cat", style="grey62", width=12, no_wrap=True)
    tbl.add_column("skills")
    for cat in taxonomy():
        names = [(n, s) for n, s in skills.items() if s["category"] == cat]
        t = Text()
        for i, (n, s) in enumerate(names):
            if i:
                t.append(" · ", style="grey35")
            t.append(n, style="green" if s["where"] in ("recent role", "experience/projects") else "yellow3")
        if not names:
            t.append("—", style="grey35")
        tbl.add_row(cat.replace("_", " "), t)
    legend = Text("green = shown in experience/projects  ·  yellow = listed only", style="grey50")
    return Panel(Group(tbl, legend), title="SWE skills detected", title_align="left", border_style="grey42", box=box.ROUNDED)


def _jd(report: dict) -> Panel | None:
    jd = report.get("jd")
    if not jd:
        return None
    req = next((c for c in report["checks"] if c["id"] == "kw.jd_required"), None)
    pref = next((c for c in report["checks"] if c["id"] == "kw.jd_preferred"), None)
    t = Text()
    for label, c in (("Required", req), ("Preferred", pref)):
        if not c or c["info"]:
            continue
        t.append(f"{label}: ", style="bold")
        t.append(f"{c['message']}\n", style=color(c["score"]))
        for ev in c["evidence"]:
            t.append(f"  {ev}\n", style="green" if ev.startswith("✓") else "red")
    return Panel(t, title="Job description match", title_align="left", border_style="grey42", box=box.ROUNDED)


def _ai(report: dict) -> Panel | None:
    ai = report.get("ai")
    if not ai:
        return None
    if ai.get("error"):
        return Panel(Text(ai["error"], style="yellow3"), title="AI review", border_style="yellow3")
    tbl = Table(box=box.SIMPLE_HEAD, expand=True, show_edge=False, header_style="grey62")
    tbl.add_column("Issue", ratio=1, style="yellow3")
    tbl.add_column("Original → Suggestion", ratio=5)
    for item in ai.get("bullets", []):
        t = Text(item["original"], style="grey62")
        t.append("\n→ ", style="cyan")
        t.append(item["suggestion"], style="cyan")
        tbl.add_row(", ".join(item.get("issues", [])), t)
    body = Group(Text(ai.get("summary", ""), style="italic"), tbl) if ai.get("summary") else tbl
    return Panel(body, title=f"AI review ({ai.get('model', '')})", title_align="left", border_style="magenta", box=box.ROUNDED)


def _side_by_side(console: Console, left, right, *, left_width: int):
    """Two panels in a row on wide terminals, stacked on narrow ones."""
    if console.width < left_width + 50:
        return Group(left, right)
    grid = Table.grid(expand=True)
    grid.add_column(width=left_width)
    grid.add_column(ratio=1)
    grid.add_row(left, right)
    return grid


def render(report: dict, console: Console, *, prev: dict | None = None, version: dict | None = None, verbose: bool = False):
    console.print(_header(report, version))
    console.print(_side_by_side(console, _overall(report, prev), _profiles(report, prev), left_width=24))
    console.print(_side_by_side(console, _categories(report, prev), _skills(report), left_width=58))
    for panel in (_jd(report), _issues(report, verbose=verbose), _ai(report)):
        if panel is not None:
            console.print(panel)


def render_profile_text(report: dict, key: str, console: Console):
    p = next((p for p in report["profiles"] if p["key"] == key), None)
    if not p:
        console.print(f"[red]Unknown profile '{key}'.[/]")
        return
    console.print(Panel(Text(p["text_seen"] or "(no text)"), title=f"What the {p['name']} sees",
                        subtitle=f"sections: {', '.join(p['sections_seen']) or 'none'}", border_style="cyan"))
