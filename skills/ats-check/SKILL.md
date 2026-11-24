---
name: ats-check
description: Check a resume PDF's ATS parseability and keyword fit with the local `ats` CLI (simulated legacy/modern parsers, keyword and semantic rankers, recruiter skim), and use it in an edit → rebuild → re-check loop. Use when the user asks to check, score, debug or improve a resume or CV for applicant tracking systems, tailor it to a job description, or verify that resume edits didn't break parsing. Geared toward software engineering resumes.
---

# ATS resume check

`ats` is a local, offline CLI. It extracts a resume PDF with three PDF engines, runs it through five simulated ATS profiles, and reports scores, issues and fixes. It keeps a history of resume versions so you can tell whether an edit helped.

## 1. Make sure the tool is installed

```bash
command -v ats >/dev/null 2>&1 && echo installed || echo missing
```

If it's missing, install it. This needs `uv`; if `uv` isn't available, ask the user to install it from https://docs.astral.sh/uv/ first.

```bash
uv tool install git+https://github.com/rawsab/ats-checker
```

## 2. Run a check

Always use `--md`. It prints a compact Markdown report and never prompts for input. Don't run bare `ats` or `ats check` without `--md` or `--json`: those are interactive and will hang waiting for input.

```bash
ats check path/to/resume.pdf --md --no-jd                 # generic SWE check
ats check path/to/resume.pdf --md --jd job.txt            # tailored to a job description (file)
ats check path/to/resume.pdf --md --jd "https://…"        # …or a job posting URL
```

- If the user gives you job description text, save it to a file and pass `--jd <file>`.
- Add `--label "short description of the change"` to name a version. This makes history readable.
- Add `--no-save` for throwaway checks that shouldn't enter the user's history (for example, experiments on a temp copy).
- `--show-text legacy` (or `modern`) appends the raw text that parser extracted. This is the best way to debug scrambled columns, merged words, or missing contact details.
- `--json` returns the full report (about 70 KB, mostly raw text). Use it only when you need a specific field, for example `ats check r.pdf --json --no-save --no-jd | jq '.checks[] | select(.severity=="fail")'`.

## 3. Read the report

- **Overall** is the mean of the five profile scores. 90+ is excellent, 80+ strong, under 70 needs work.
- **Profiles**: Legacy Parser (strict, reads rows straight across the page, skips header/footer zones and tables), Modern Parser (layout-aware), Keyword Ranker (exact matches), Semantic Ranker (synonyms, credits skills used in bullets), and Recruiter Skim (a human's first glance).
- A **knockout** means a critical failure capped that profile's score, for example a multi-column layout on the Legacy Parser, or hidden text anywhere. Fix knockouts first; they cost far more than anything else.
- **Issues** are sorted worst first and tagged FAIL or WARN, each with evidence and a fix.
- When the PDF is a new version of a resume already checked, scores show changes in parentheses, and a "Changed since previous version" section lists the checks that moved.

## 4. Iteration loop

1. Run the check on the current PDF. Summarize the overall score, any knockouts, and the top 3–5 issues.
2. Propose specific edits to the resume source (LaTeX, Markdown, Typst, DOCX, etc.), worst issues first. Make them once the user agrees, or right away if they asked you to iterate on your own.
3. Rebuild the PDF with the project's own build command (for example `latexmk -pdf`, `typst compile`, `pandoc`). Never hand-edit the PDF.
4. Re-run the check with `--label` describing the change. Confirm the targeted scores moved and nothing regressed.
5. Repeat until no FAIL issues remain and the user is satisfied. `ats versions` lists every version with its score; `ats compare` diffs the latest version against the previous one.

## Rules

- **Never fabricate experience, skills, employers, dates or metrics.** If the JD wants a skill the resume lacks, suggest adding it only if the user actually has it. For missing metrics, ask the user, or leave a clear placeholder like `[X%]`.
- **Never game the parser.** No white or tiny text, no keyword stuffing, no keywords hidden in metadata. The tool flags these as knockouts, and real ATSs and recruiters catch them too.
- Treat scores as guidance, not truth. These are simulations of ATS behaviour, not any specific vendor's system. Prefer fixes that also make the resume read better to a human.
- Some findings are judgment calls. For example, an "-ing" verb for a current role is fine, and slightly tight margins can be acceptable. Say so instead of making the resume worse to satisfy a check.
- Resumes contain personal data. The tool runs locally; don't paste resume contents into other services without the user's consent.
