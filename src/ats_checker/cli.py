"""`ats`: check a resume against simulated ATSs and track versions over time."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Annotated

import typer
from rich import box
from rich.console import Console
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

from .input import normalize_path
from .report.charts import color, delta, line_chart, sparkline
from .report.render import render, render_profile_text

app = typer.Typer(add_completion=False, no_args_is_help=False, rich_markup_mode="rich",
                  help="Local ATS simulator & resume checker for software engineering roles.")
console = Console()
err = Console(stderr=True)

PROFILE_KEYS = ["legacy", "modern", "keyword", "semantic", "skim"]


def _interactive() -> bool:
    return sys.stdin.isatty() and sys.stdout.isatty()


def _ask_path() -> Path:
    while True:
        raw = Prompt.ask("[bold]Drop your resume PDF here[/] (or paste its path)")
        path = normalize_path(raw)
        if path.is_file() and path.suffix.lower() == ".pdf":
            return path
        console.print(f"[red]Not a PDF file:[/] {path}")


def _read_pasted_jd():
    from .jd import load_jd, parse_jd

    console.print("[bold]Paste the job description[/] [grey62](or a URL / file path). "
                  "Finish with two empty lines or Ctrl-D. Press Enter now to skip.[/]")
    lines: list[str] = []
    blanks = 0
    while True:
        try:
            line = input()
        except EOFError:
            break
        if not lines and not line.strip():
            return None
        if not lines and (line.strip().startswith(("http://", "https://")) or Path(line.strip()).expanduser().is_file()):
            return load_jd(line.strip())
        if not line.strip():
            blanks += 1
            if blanks >= 2:
                break
        else:
            blanks = 0
        lines.append(line)
    text = "\n".join(lines).strip()
    return parse_jd(text, source="pasted") if text else None


def _store():
    from .store.db import Store

    return Store()


def _save(store, report: dict, doc, jd, label: str | None, interactive: bool) -> tuple[int, dict, dict | None]:
    from .extract.layout import layout_text
    from .parse import parse_text
    from .store.identity import lineage_name_for, resolve

    text = layout_text(doc)
    contact = parse_text(text).contact
    match = resolve(store, doc, text, contact.key())
    if match.status == "ask":
        link = interactive and Confirm.ask(
            f"This looks like a new version of [magenta]“{match.lineage_name}”[/] "
            f"({match.similarity:.0%} similar, {match.reason}). Link it?", default=True)
        match.status = "new_version" if link else "new_lineage"
    if match.status == "existing":
        document_id = match.document_id
        store.touch_document(document_id, doc)
    else:
        lineage_id = match.lineage_id
        if match.status == "new_lineage":
            lineage_id = store.create_lineage(lineage_name_for(doc, label, contact.name), contact.key())
        document_id = store.add_document(lineage_id, doc, text, contact.key(), label)
    jd_id = store.upsert_jd(jd) if jd else None
    prev_row = store.previous_version_run(document_id, jd_id)
    run_id = store.add_run(document_id, jd_id, report, label)
    version = store.version_info(document_id) | {"status": match.status, "similarity": match.similarity}
    report["run"] = {"id": run_id, **version}
    prev = json.loads(prev_row["report"]) if prev_row else None
    return run_id, version, prev


@app.callback(invoke_without_command=True)
def main(ctx: typer.Context):
    """Run [bold]ats check[/] when no command is given."""
    if ctx.invoked_subcommand is None:
        ctx.invoke(check)


@app.command()
def check(
    path: Annotated[str | None, typer.Argument(help="Resume PDF (drag & drop works). Prompted if omitted.")] = None,
    jd: Annotated[str | None, typer.Option("--jd", "-j", help="Job description: file path, URL or text.")] = None,
    no_jd: Annotated[bool, typer.Option("--no-jd", help="Don't prompt for a job description.")] = False,
    label: Annotated[str | None, typer.Option("--label", "-l", help="Name this version, e.g. 'post-rewrite'.")] = None,
    ai: Annotated[bool, typer.Option("--ai", help="Add Claude feedback on bullets (needs the [ai] extra + API key).")] = False,
    profile: Annotated[list[str] | None, typer.Option("--profile", "-p", help=f"Only run these ATS profiles: {', '.join(PROFILE_KEYS)}.")] = None,
    show_text: Annotated[str | None, typer.Option("--show-text", help="Print the raw text a profile saw.")] = None,
    as_json: Annotated[bool, typer.Option("--json", help="Print the full report as JSON (no prompts).")] = False,
    no_save: Annotated[bool, typer.Option("--no-save", help="Don't record this run in history.")] = False,
    verbose: Annotated[bool, typer.Option("--verbose", "-v", help="Show passing checks and more evidence.")] = False,
):
    """Check a resume PDF against simulated ATS profiles."""
    from .analyze import analyze, bullets_for_ai
    from .extract.engines import NotAPdfError
    from .jd import load_jd

    interactive = _interactive() and not as_json
    if profile:
        bad = [p for p in profile if p not in PROFILE_KEYS]
        if bad:
            raise typer.BadParameter(f"unknown profile(s): {', '.join(bad)}", param_hint="--profile")

    if path:
        pdf = normalize_path(path)
        if not pdf.is_file():
            err.print(f"[red]File not found:[/] {pdf}")
            raise typer.Exit(1)
    elif interactive:
        pdf = _ask_path()
    else:
        err.print("[red]No resume path given.[/]")
        raise typer.Exit(2)

    job = None
    try:
        if jd:
            with err.status("Loading job description…"):
                job = load_jd(jd)
        elif interactive and not no_jd:
            job = _read_pasted_jd()
    except Exception as exc:  # network errors, unreadable files
        err.print(f"[yellow]Couldn't load the job description ({exc}); continuing without it.[/]")

    try:
        with err.status("Parsing with 3 PDF engines and 5 simulated ATSs…"):
            report, doc = analyze(pdf, job, profiles=profile)
    except NotAPdfError as exc:
        err.print(f"[red]{exc}[/]")
        raise typer.Exit(1)

    if ai:
        from .ai import review_bullets

        with err.status("Asking Claude to review your bullets…"):
            report["ai"] = review_bullets(bullets_for_ai(doc), jd_title=job.title if job else None)

    version = prev = None
    if not no_save:
        store = _store()
        try:
            _, version, prev = _save(store, report, doc, job, label, interactive)
        finally:
            store.close()

    if as_json:
        print(json.dumps(report, indent=2, default=str))
        return
    render(report, console, prev=prev, version=version, verbose=verbose)
    if show_text:
        render_profile_text(report, show_text, console)
    if version:
        console.print(f"[grey50]Saved as run #{report['run']['id']}. "
                      f"`ats compare` to diff against the last version, `ats trend` for history.[/]")


def _when(iso: str) -> str:
    try:
        return datetime.fromisoformat(iso).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso


@app.command()
def history(
    resume: Annotated[int | None, typer.Option("--resume", "-r", help="Only runs for this resume (lineage) id.")] = None,
    limit: Annotated[int, typer.Option("--limit", "-n")] = 30,
):
    """List past runs."""
    store = _store()
    rows = store.runs(resume, limit)
    if not rows:
        console.print("No runs yet. Try [bold]ats check[/].")
        return
    tbl = Table(box=box.SIMPLE_HEAD, header_style="grey62")
    for col, kw in [("Run", {"justify": "right"}), ("When", {"no_wrap": True}), ("Resume", {"no_wrap": True}),
                    ("Ver", {"justify": "right"}), ("File", {"overflow": "ellipsis", "no_wrap": True, "max_width": 32}),
                    ("Job", {"overflow": "ellipsis", "no_wrap": True, "max_width": 30}),
                    ("Score", {"justify": "right"}), ("Label", {"overflow": "ellipsis", "no_wrap": True, "max_width": 24})]:
        tbl.add_column(col, **kw)
    for r in rows:
        tbl.add_row(str(r["id"]), _when(r["created_at"]), f"{r['lineage_name']} [grey50]#{r['lineage_id']}[/]",
                    f"v{r['version']}", r["filename"], r["jd_title"] or "[grey50]—[/]",
                    Text(f"{r['overall']:.0f}", style=color(r["overall"])), r["label"] or "")
    console.print(tbl)


@app.command()
def resumes():
    """List tracked resumes (lineages) and their versions."""
    store = _store()
    rows = store.lineages()
    if not rows:
        console.print("No resumes tracked yet. Try [bold]ats check[/].")
        return
    tbl = Table(box=box.SIMPLE_HEAD, header_style="grey62")
    for col in ("ID", "Resume", "Versions", "Runs", "Trend", "Latest", "Last run"):
        tbl.add_column(col, justify="right" if col in ("ID", "Versions", "Runs", "Latest") else "left")
    for r in rows:
        series = [s["overall"] for s in store.lineage_series(r["id"])]
        latest = r["last_score"]
        tbl.add_row(str(r["id"]), r["name"], str(r["versions"]), str(r["runs"]), sparkline(series),
                    Text(f"{latest:.0f}", style=color(latest)) if latest is not None else "—",
                    _when(r["last_run"]) if r["last_run"] else "—")
    console.print(tbl)


@app.command()
def show(
    run_id: Annotated[int | None, typer.Argument(help="Run id (default: latest).")] = None,
    verbose: Annotated[bool, typer.Option("--verbose", "-v")] = False,
    show_text: Annotated[str | None, typer.Option("--show-text", help="Print the raw text a profile saw.")] = None,
):
    """Re-render a saved report."""
    store = _store()
    run_id = run_id or (store.runs(limit=1)[0]["id"] if store.runs(limit=1) else None)
    row = store.run(run_id) if run_id else None
    if not row:
        err.print("[red]Run not found.[/]")
        raise typer.Exit(1)
    report = json.loads(row["report"])
    prev_row = store.previous_version_run(row["document_id"], row["jd_id"])
    version = store.version_info(row["document_id"])
    render(report, console, prev=json.loads(prev_row["report"]) if prev_row else None, version=version, verbose=verbose)
    if show_text:
        render_profile_text(report, show_text, console)


@app.command()
def compare(
    run_a: Annotated[int | None, typer.Argument(help="Older run (default: previous version of B).")] = None,
    run_b: Annotated[int | None, typer.Argument(help="Newer run (default: latest run).")] = None,
):
    """Diff two runs: scores, checks, skills and sections."""
    store = _store()
    if run_b is None and run_a is not None:
        run_a, run_b = None, run_a
    if run_b is None:
        latest = store.runs(limit=1)
        if not latest:
            err.print("[red]No runs yet.[/]")
            raise typer.Exit(1)
        run_b = latest[0]["id"]
    rb = store.run(run_b)
    if not rb:
        err.print(f"[red]Run {run_b} not found.[/]")
        raise typer.Exit(1)
    ra = store.run(run_a) if run_a else store.previous_version_run(rb["document_id"], rb["jd_id"])
    if not ra:
        err.print("[yellow]No earlier version of this resume to compare against. Pass two run ids: ats compare A B[/]")
        raise typer.Exit(1)
    a, b = json.loads(ra["report"]), json.loads(rb["report"])

    console.print(Text.assemble(("Comparing ", "grey62"), (f"run #{ra['id']} (v{ra['version']}, {ra['filename']})", "bold"),
                                (" → ", "grey62"), (f"run #{rb['id']} (v{rb['version']}, {rb['filename']})", "bold")))
    if a.get("jd", {}) and b.get("jd") and a["jd"]["sha256"] != b["jd"]["sha256"]:
        console.print("[yellow]Note: these runs used different job descriptions.[/]")

    tbl = Table(box=box.SIMPLE_HEAD, header_style="grey62", title="Scores", title_justify="left")
    tbl.add_column("")
    tbl.add_column("Before", justify="right")
    tbl.add_column("After", justify="right")
    tbl.add_column("Δ")
    tbl.add_row(Text("Overall", style="bold"), f"{a['overall']:.0f}", Text(f"{b['overall']:.0f}", style=color(b["overall"])),
                delta(b["overall"], a["overall"]))
    pa = {p["key"]: p for p in a["profiles"]}
    for p in b["profiles"]:
        old = pa.get(p["key"], {}).get("score")
        tbl.add_row(p["name"], f"{old:.0f}" if old is not None else "—", Text(f"{p['score']:.0f}", style=color(p["score"])),
                    delta(p["score"], old))
    for cat, score in b["categories"].items():
        old = a["categories"].get(cat)
        tbl.add_row(Text(cat.title(), style="grey62"), f"{old:.0f}" if old is not None else "—",
                    Text(f"{score:.0f}", style=color(score)), delta(score, old))
    console.print(tbl)

    ca = {c["id"]: c for c in a["checks"]}
    changed = [(c, ca.get(c["id"])) for c in b["checks"] if not c["info"]]
    changed = [(c, o) for c, o in changed if o is None or abs(c["score"] - o["score"]) >= 3]
    if changed:
        ct = Table(box=box.SIMPLE_HEAD, header_style="grey62", title="Checks that moved", title_justify="left")
        ct.add_column("Check")
        ct.add_column("Before", justify="right")
        ct.add_column("After", justify="right")
        ct.add_column("Δ")
        ct.add_column("Now", style="grey62", overflow="fold")
        for c, o in sorted(changed, key=lambda co: (co[0]["score"] - (co[1]["score"] if co[1] else 0))):
            ct.add_row(c["name"], f"{o['score']:.0f}" if o else "new", Text(f"{c['score']:.0f}", style=color(c["score"])),
                       delta(c["score"], o["score"] if o else None), c["message"])
        console.print(ct)

    sa, sb = set(a["resume"]["skills"]), set(b["resume"]["skills"])
    seca, secb = set(a["resume"]["sections"]), set(b["resume"]["sections"])
    diff = Text()
    for label, added, removed in (("Skills", sb - sa, sa - sb), ("Sections", secb - seca, seca - secb)):
        if added or removed:
            diff.append(f"{label}: ", style="bold")
            if added:
                diff.append("+ " + ", ".join(sorted(added)) + "  ", style="green")
            if removed:
                diff.append("− " + ", ".join(sorted(removed)), style="red")
            diff.append("\n")
    diff.append(f"Bullets: {a['resume']['bullet_count']} → {b['resume']['bullet_count']}   "
                f"Pages: {a['file']['pages']} → {b['file']['pages']}", style="grey62")
    console.print(diff)


@app.command()
def trend(
    resume: Annotated[int | None, typer.Argument(help="Resume (lineage) id; default: most recent.")] = None,
    by: Annotated[str, typer.Option("--by", help="Plot 'profiles' or 'categories'.")] = "profiles",
):
    """Chart scores across versions of a resume."""
    store = _store()
    if resume is None:
        latest = store.runs(limit=1)
        if not latest:
            err.print("[red]No runs yet.[/]")
            raise typer.Exit(1)
        resume = latest[0]["lineage_id"]
    rows = store.lineage_series(resume)
    if not rows:
        err.print(f"[red]No runs for resume #{resume}.[/]")
        raise typer.Exit(1)
    reports = [json.loads(r["report"]) for r in rows]
    labels = [f"v{r['version']}" for r in rows]
    series: dict[str, list[float]] = {"Overall": [r["overall"] for r in reports]}
    if by == "categories":
        cats = list(dict.fromkeys(c for r in reports for c in r["categories"]))
        for c in cats:
            series[c.title()] = [r["categories"].get(c, 0) for r in reports]
    else:
        for key in PROFILE_KEYS:
            vals = [next((p["score"] for p in r["profiles"] if p["key"] == key), None) for r in reports]
            if any(v is not None for v in vals):
                name = next(p["name"] for r in reports for p in r["profiles"] if p["key"] == key)
                series[name] = [v if v is not None else 0 for v in vals]

    console.print(Text(f"{rows[0]['lineage_name']}: {len(rows)} version(s)", style="bold magenta"))
    if len(rows) >= 2:
        width = min(console.width, 110)
        console.print(line_chart(series, labels, title=f"Scores by {by}", width=width))
    tbl = Table(box=box.SIMPLE_HEAD, header_style="grey62")
    tbl.add_column("Series")
    tbl.add_column("Trend")
    for lab in labels:
        tbl.add_column(lab, justify="right")
    for name, vals in series.items():
        tbl.add_row(name, sparkline(vals), *[Text(f"{v:.0f}", style=color(v)) for v in vals])
    meta = Table(box=box.SIMPLE, show_header=False)
    meta.add_column(style="grey62")
    meta.add_column()
    for r, lab in zip(rows, labels):
        meta.add_row(lab, f"{r['filename']}  [grey50]run #{r['id']} · {_when(r['created_at'])}"
                          f"{' · ' + r['label'] if r['label'] else ''}[/]")
    console.print(tbl)
    console.print(meta)


@app.command()
def label(run_id: int, text: str):
    """Attach a label to a run (and its resume version)."""
    store = _store()
    if not store.set_label(run_id, text):
        err.print(f"[red]Run {run_id} not found.[/]")
        raise typer.Exit(1)
    console.print(f"Labeled run #{run_id}: [bold]{text}[/]")


@app.command()
def rename(resume: int, name: str):
    """Rename a tracked resume (lineage)."""
    _store().rename_lineage(resume, name)
    console.print(f"Resume #{resume} is now [bold]{name}[/].")


@app.command()
def export(
    run_id: Annotated[int | None, typer.Argument(help="Run id (default: latest).")] = None,
    fmt: Annotated[str, typer.Option("--format", "-f", help="json or md")] = "md",
    output: Annotated[Path | None, typer.Option("--output", "-o")] = None,
):
    """Export a saved report as JSON or Markdown."""
    from .report.markdown import to_markdown

    store = _store()
    run_id = run_id or (store.runs(limit=1)[0]["id"] if store.runs(limit=1) else None)
    report = store.report(run_id) if run_id else None
    if not report:
        err.print("[red]Run not found.[/]")
        raise typer.Exit(1)
    out = json.dumps(report, indent=2) if fmt == "json" else to_markdown(report)
    if output:
        output.write_text(out, encoding="utf-8")
        console.print(f"Wrote {output}")
    else:
        print(out)


if __name__ == "__main__":
    app()
