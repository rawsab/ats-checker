# ats-checker

A local, offline ATS simulator for software-engineering resumes. Point it at a PDF and it reads the file the way different applicant tracking systems do, scores it, tells you what to fix, and keeps a history of every resume version so you can see whether your edits helped.

```
uv tool install .          # installs the `ats` command
ats                        # then drag your resume PDF into the terminal
```

## What it does

**Three PDF engines.** The resume is extracted with pdfplumber (row-by-row), pdfminer (layout boxes) and pypdf (content-stream order). When the three disagree, different ATSs will see different resumes.

**Five simulated ATS profiles.** These model styles of parser and ranker, not specific vendors:

| Profile | Reads the PDF like… | Cares most about |
|---|---|---|
| Legacy Parser | rows straight across the page; skips header/footer zones and tables; strict section names | columns, contact in header, standard headers, dates |
| Modern Parser | layout-aware, column-splitting; lenient section names | clean text, hidden text, sections |
| Keyword Ranker | exact keyword search | JD/taxonomy hits, frequency, recency |
| Semantic Ranker | synonyms + fuzzy (`k8s` = Kubernetes) | skills shown in bullets, not just listed |
| Recruiter Skim | a human's 6-second pass | top third of page 1, quantified impact, density, length |

Some failures are knockouts that cap a profile's score: a two-column layout for the Legacy Parser, white or hidden text for every profile, and an image-only PDF.

**About 35 checks** across parseability, structure, contact, content (action verbs, quantified impact, weak phrases, tense), readability, formatting, and keywords. Keywords are matched against a built-in SWE skills taxonomy and, optionally, a job description. Every finding comes with evidence and a concrete fix.

**Version tracking.** Every run is saved to SQLite. Versions are identified by content, never by filename:

1. Identical bytes count as the same document, even if renamed.
2. The same PDF XMP DocumentID counts as a re-export of the same source.
3. Similar text plus the same contact details count as a new version of the same resume. If the match is ambiguous, you're asked.

Versions are ordered by the PDF's creation date (falling back to when you first checked it), so checking an old export later still slots it in as an earlier version.

## Usage

```bash
ats check resume.pdf                       # prompts you to paste a JD (Enter to skip)
ats check resume.pdf --jd job.txt          # JD from a file…
ats check resume.pdf --jd https://…        # …or a URL
ats check resume.pdf --no-jd --label "post-rewrite"
ats check resume.pdf --show-text legacy    # see exactly what the Legacy Parser read
ats check resume.pdf --json --no-save      # machine-readable, nothing saved

ats check resume.pdf --md                  # compact Markdown report (for agents/scripts)

ats history                 # past runs
ats versions [RESUME]       # a resume's versions, ordered by PDF creation date
ats resumes                 # tracked resumes, version counts, sparkline trends
ats show [RUN]              # re-render a saved report
ats compare [A] [B]         # diff two runs (default: latest vs previous version)
ats trend [RESUME] --by profiles|categories
ats label RUN "text"  ·  ats rename RESUME "name"  ·  ats export RUN -f md|json
```

### Use it from a coding agent (Claude Code, Codex, …)

The repo ships an [`ats-check` agent skill](skills/ats-check/SKILL.md). It teaches an agent to run the checker, read the report and iterate on your resume source in a loop: edit, rebuild the PDF, re-check, compare. It never invents experience and never games the parser.

```bash
ats skill install                    # Claude Code: ~/.claude/skills/ats-check
ats skill install --project          # Claude Code, this project only: ./.claude/skills/ats-check
ats skill install --target codex     # Codex: ~/.codex/skills/ats-check
ats skill install --target <dir>     # any agent that reads SKILL.md skills
```

Restart the agent session, then ask something like *"check my resume's ATS parseability and fix the worst issues"*. Agents use `ats check resume.pdf --md`, a compact Markdown report that never prompts for input and includes changes since the previous version.

### Optional AI bullet review

```bash
uv tool install '.[ai]'
export ANTHROPIC_API_KEY=…    # or `ant auth login`
ats check resume.pdf --ai
```

Only the extracted bullet text is sent to Claude, never the PDF or your contact details. The default model is `claude-opus-5-5`; override it with `ATS_AI_MODEL`.

## Data

History lives in `~/Library/Application Support/ats-checker/runs.db` (macOS) or the platform equivalent. Set `ATS_CHECKER_HOME` to put it somewhere else.

## Development

```bash
uv sync --extra ai
uv run pytest
uv run python tests/fixtures/make_fixtures.py   # writes sample PDFs to tests/fixtures/out/
```

The fixtures are synthetic resumes, each built to trigger one failure mode: two-column layout, table-based skills, contact details in the header zone, white text, and an image-only PDF.

Scoring weights and knockout caps live in `src/ats_checker/simulators/profiles.py`. The skills taxonomy, synonyms, action verbs and section aliases are in `src/ats_checker/data/`.
