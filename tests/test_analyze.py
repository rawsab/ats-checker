from ats_checker.analyze import analyze


def checks(report):
    return {c["id"]: c for c in report["checks"]}


def profiles(report):
    return {p["key"]: p for p in report["profiles"]}


def test_clean_resume_scores_well(pdfs):
    report, _ = analyze(pdfs["Jane_Doe_Resume.pdf"])
    assert report["overall"] >= 85
    c = checks(report)
    for cid in ("parse.columns", "parse.hidden_text", "parse.header_footer", "struct.sections", "contact.fields"):
        assert c[cid]["severity"] == "pass", cid
    assert report["resume"]["bullet_count"] >= 7
    assert {"Go", "PostgreSQL", "Kubernetes"} <= set(report["resume"]["skills"])
    assert report["resume"]["contact"]["email"] == "jane.doe@gmail.com"


def test_two_column_flags_layout_and_caps_legacy(pdfs):
    report, _ = analyze(pdfs["two_column.pdf"])
    c = checks(report)
    assert c["parse.columns"]["severity"] == "fail"
    legacy = profiles(report)["legacy"]
    assert legacy["capped_by"] == "parse.columns"
    assert legacy["score"] <= 50
    # the layout-aware reader still recovers the experience section
    assert "experience" in report["resume"]["sections"]


def test_image_only_pdf_is_unreadable(pdfs):
    report, _ = analyze(pdfs["image_only.pdf"])
    assert checks(report)["parse.extractable"]["score"] == 0
    assert all(p["score"] <= 5 for p in report["profiles"])


def test_header_contact_lost_by_legacy_parser(pdfs):
    report, _ = analyze(pdfs["header_contact.pdf"])
    assert checks(report)["parse.header_footer"]["severity"] == "fail"
    legacy = profiles(report)["legacy"]
    legacy_contact = next(c for c in legacy["checks"] if c["id"] == "contact.fields")
    assert "email" in legacy_contact["message"]
    assert profiles(report)["modern"]["score"] > legacy["score"]


def test_white_text_flagged(pdfs):
    report, _ = analyze(pdfs["white_text.pdf"])
    assert checks(report)["parse.hidden_text"]["score"] == 0
    assert all(p["capped_by"] == "parse.hidden_text" for p in report["profiles"])


def test_tight_word_spacing_not_merged(pdfs):
    from ats_checker.extract.engines import load_pdf

    doc = load_pdf(pdfs["tight_spacing.pdf"])
    assert not [w.text for w in doc.words if len(w.text) > 25 and "/" not in w.text]
    report, _ = analyze(pdfs["tight_spacing.pdf"])
    assert checks(report)["content.verbs"]["score"] >= 85


def test_table_flagged(pdfs):
    report, _ = analyze(pdfs["table_skills.pdf"])
    assert checks(report)["parse.tables"]["severity"] in ("warn", "fail")


def test_jd_match(pdfs):
    from ats_checker.jd import parse_jd

    jd = parse_jd(JD)
    report, _ = analyze(pdfs["Jane_Doe_Resume.pdf"], jd)
    c = checks(report)
    assert c["kw.jd_required"]["score"] > 60
    assert "Snowflake" in c["kw.jd_required"]["evidence"][1]
    assert c["kw.jd_years"]["score"] == 100


JD = """Senior Backend Engineer

Requirements:
- 5+ years of experience
- Go, PostgreSQL, Kubernetes, AWS
- Snowflake

Nice to have:
- Rust is a plus
"""
