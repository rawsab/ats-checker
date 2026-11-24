import json
import shutil

from typer.testing import CliRunner

from ats_checker.cli import app
from ats_checker.store.db import Store

runner = CliRunner()


def check(path, *extra):
    result = runner.invoke(app, ["check", str(path), "--json", *extra])
    assert result.exit_code == 0, result.output
    return json.loads(result.stdout)


def test_rename_is_same_document_and_edit_is_new_version(pdfs, tmp_path):
    first = check(pdfs["Jane_Doe_Resume.pdf"])
    assert first["run"]["status"] == "new_lineage" and first["run"]["version"] == 1

    renamed = tmp_path / "resume.pdf"
    shutil.copy(pdfs["Jane_Doe_Resume.pdf"], renamed)
    again = check(renamed)
    assert again["run"]["status"] == "existing"
    assert again["run"]["version"] == 1

    edited = check(pdfs["Jane_Doe_Resume_edited.pdf"], "--label", "v2 rewrite")
    assert edited["run"]["status"] == "new_version"
    assert edited["run"]["version"] == 2
    assert edited["run"]["lineage_id"] == first["run"]["lineage_id"]

    store = Store()
    assert len(store.lineages()) == 1
    assert len(store.runs()) == 3


def test_no_save_writes_nothing(pdfs):
    check(pdfs["Jane_Doe_Resume.pdf"], "--no-save")
    assert Store().runs() == []


def test_history_compare_trend_commands(pdfs):
    check(pdfs["Jane_Doe_Resume.pdf"])
    check(pdfs["Jane_Doe_Resume_edited.pdf"])
    for args in (["history"], ["resumes"], ["compare"], ["trend"], ["show"], ["export", "-f", "md"]):
        result = runner.invoke(app, args)
        assert result.exit_code == 0, (args, result.output)
    assert "Scores" in runner.invoke(app, ["compare"]).output


def test_jd_file_option(pdfs, tmp_path):
    jd = tmp_path / "jd.txt"
    jd.write_text("Backend Engineer\nRequirements:\n- Go\n- Kubernetes\n- Haskell\n")
    report = check(pdfs["Jane_Doe_Resume.pdf"], "--jd", str(jd), "--no-save")
    assert set(report["jd"]["required"]) == {"Go", "Kubernetes", "Haskell"}


def test_versions_ordered_by_pdf_creation_date(pdfs, tmp_path):
    from pypdf import PdfReader, PdfWriter

    def with_date(src, name, date):
        w = PdfWriter(clone_from=PdfReader(src))
        w.add_metadata({"/CreationDate": date, "/ModDate": date})
        out = tmp_path / name
        w.write(out)
        return out

    newer = with_date(pdfs["Jane_Doe_Resume_edited.pdf"], "new.pdf", "D:20260301120000Z")
    older = with_date(pdfs["Jane_Doe_Resume.pdf"], "old.pdf", "D:20250101120000-05'00'")
    first = check(newer)                     # checked first, but made later
    second = check(older)
    assert second["run"]["status"] == "new_version"
    assert second["run"]["version"] == 1     # older PDF slots in before
    store = Store()
    series = store.lineage_series(first["run"]["lineage_id"])
    assert [r["filename"] for r in series] == ["old.pdf", "new.pdf"]
    assert [r["version"] for r in series] == [1, 2]
    assert series[0]["doc_date"] == "2025-01-01T17:00:00+00:00"
    prev = store.previous_version_run(series[1]["document_id"], None)
    assert prev["filename"] == "old.pdf"
    assert store.previous_version_run(series[0]["document_id"], None) is None
    assert runner.invoke(app, ["versions"]).exit_code == 0

