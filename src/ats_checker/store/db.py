"""SQLite history of resumes, versions ("documents"), job descriptions and runs.

A *lineage* is one resume over time; each distinct PDF (by content hash) is a *document*
(a version in that lineage); every invocation of ``ats check`` is a *run*.
"""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

from platformdirs import user_data_dir

from ..extract.engines import pdf_date

SCHEMA = """
CREATE TABLE IF NOT EXISTS lineages (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    contact_key TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    lineage_id INTEGER NOT NULL REFERENCES lineages(id),
    sha256 TEXT NOT NULL UNIQUE,
    filename TEXT NOT NULL,
    path TEXT,
    size_bytes INTEGER,
    pages INTEGER,
    xmp_document_id TEXT,
    pdf_created TEXT,
    pdf_producer TEXT,
    contact_key TEXT,
    text TEXT NOT NULL,
    label TEXT,
    created_at TEXT NOT NULL,
    doc_date TEXT  -- PDF CreationDate (or ModDate) as UTC ISO; orders versions
);
CREATE TABLE IF NOT EXISTS jds (
    id INTEGER PRIMARY KEY,
    sha256 TEXT NOT NULL UNIQUE,
    title TEXT,
    source TEXT,
    text TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runs (
    id INTEGER PRIMARY KEY,
    document_id INTEGER NOT NULL REFERENCES documents(id),
    jd_id INTEGER REFERENCES jds(id),
    created_at TEXT NOT NULL,
    label TEXT,
    overall REAL NOT NULL,
    report TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_docs_lineage ON documents(lineage_id);
CREATE INDEX IF NOT EXISTS idx_runs_doc ON runs(document_id);
"""


def data_dir() -> Path:
    return Path(os.environ.get("ATS_CHECKER_HOME") or user_data_dir("ats-checker"))


# Versions are ordered by when the PDF was made, falling back to when we first saw it,
# so checking an old export after a newer one still slots it in as the earlier version.
def _order(alias: str) -> str:
    return f"(COALESCE({alias}.doc_date, {alias}.created_at), {alias}.id)"


_VERSION = (f"(SELECT COUNT(*) FROM documents d2 WHERE d2.lineage_id = d.lineage_id "
            f"AND {_order('d2')} <= {_order('d')}) AS version")


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: Path | None = None):
        self.path = path or data_dir() / "runs.db"
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(self.path)
        self.conn.row_factory = sqlite3.Row
        self.conn.executescript(SCHEMA)
        self._migrate()

    def _migrate(self):
        cols = {r["name"] for r in self.conn.execute("PRAGMA table_info(documents)")}
        if "doc_date" not in cols:
            self.conn.execute("ALTER TABLE documents ADD COLUMN doc_date TEXT")
            for row in self.conn.execute("SELECT id, pdf_created FROM documents").fetchall():
                self.conn.execute("UPDATE documents SET doc_date = ? WHERE id = ?",
                                  (pdf_date(row["pdf_created"]), row["id"]))
            self.conn.commit()

    def close(self):
        self.conn.close()

    # --- documents & lineages ------------------------------------------------------------

    def document_by_sha(self, sha: str) -> sqlite3.Row | None:
        return self.conn.execute("SELECT * FROM documents WHERE sha256 = ?", (sha,)).fetchone()

    def documents(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT d.*, l.name AS lineage_name FROM documents d JOIN lineages l ON l.id = d.lineage_id "
            "ORDER BY d.created_at DESC"
        ).fetchall()

    def create_lineage(self, name: str, contact_key: str | None) -> int:
        cur = self.conn.execute("INSERT INTO lineages (name, contact_key, created_at) VALUES (?, ?, ?)",
                                (name, contact_key, _now()))
        self.conn.commit()
        return cur.lastrowid

    def add_document(self, lineage_id: int, doc, text: str, contact_key: str | None, label: str | None) -> int:
        cur = self.conn.execute(
            "INSERT INTO documents (lineage_id, sha256, filename, path, size_bytes, pages, xmp_document_id, "
            "pdf_created, pdf_producer, contact_key, text, label, created_at, doc_date) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (lineage_id, doc.sha256, doc.filename, str(doc.path), doc.size_bytes, doc.page_count,
             doc.xmp_document_id, doc.metadata.get("CreationDate"), doc.metadata.get("Producer"),
             contact_key, text, label, _now(), doc.created_iso),
        )
        self.conn.commit()
        return cur.lastrowid

    def touch_document(self, document_id: int, doc):
        """Same bytes seen again (maybe renamed/moved): remember the latest name and path."""
        self.conn.execute("UPDATE documents SET filename = ?, path = ? WHERE id = ?",
                          (doc.filename, str(doc.path), document_id))
        self.conn.commit()

    def version_info(self, document_id: int) -> dict:
        row = self.conn.execute(
            f"SELECT d.lineage_id, l.name, d.label, d.doc_date, {_VERSION} "
            "FROM documents d JOIN lineages l ON l.id = d.lineage_id WHERE d.id = ?", (document_id,)
        ).fetchone()
        return {"lineage_id": row["lineage_id"], "lineage_name": row["name"], "version": row["version"],
                "label": row["label"], "doc_date": row["doc_date"]}

    def lineages(self) -> list[sqlite3.Row]:
        return self.conn.execute(
            "SELECT l.*, COUNT(DISTINCT d.id) AS versions, COUNT(r.id) AS runs, MAX(r.created_at) AS last_run, "
            "(SELECT r2.overall FROM runs r2 JOIN documents d2 ON d2.id = r2.document_id "
            " WHERE d2.lineage_id = l.id ORDER BY r2.id DESC LIMIT 1) AS last_score "
            "FROM lineages l LEFT JOIN documents d ON d.lineage_id = l.id LEFT JOIN runs r ON r.document_id = d.id "
            "GROUP BY l.id ORDER BY last_run DESC"
        ).fetchall()

    def rename_lineage(self, lineage_id: int, name: str):
        self.conn.execute("UPDATE lineages SET name = ? WHERE id = ?", (name, lineage_id))
        self.conn.commit()

    # --- JDs & runs ------------------------------------------------------------------------

    def upsert_jd(self, jd) -> int:
        row = self.conn.execute("SELECT id FROM jds WHERE sha256 = ?", (jd.sha256,)).fetchone()
        if row:
            return row["id"]
        cur = self.conn.execute("INSERT INTO jds (sha256, title, source, text, created_at) VALUES (?,?,?,?,?)",
                                (jd.sha256, jd.title, jd.source, jd.text, _now()))
        self.conn.commit()
        return cur.lastrowid

    def add_run(self, document_id: int, jd_id: int | None, report: dict, label: str | None) -> int:
        cur = self.conn.execute(
            "INSERT INTO runs (document_id, jd_id, created_at, label, overall, report) VALUES (?,?,?,?,?,?)",
            (document_id, jd_id, report["created_at"], label, report["overall"], json.dumps(report)),
        )
        self.conn.commit()
        return cur.lastrowid

    def set_label(self, run_id: int, label: str) -> bool:
        cur = self.conn.execute("UPDATE runs SET label = ? WHERE id = ?", (label, run_id))
        self.conn.execute("UPDATE documents SET label = ? WHERE id = (SELECT document_id FROM runs WHERE id = ?)",
                          (label, run_id))
        self.conn.commit()
        return cur.rowcount > 0

    _RUN_COLS = ("SELECT r.id, r.document_id, r.jd_id, r.created_at, r.overall, COALESCE(r.label, d.label) AS label, "
                 "d.filename, d.lineage_id, d.doc_date, l.name AS lineage_name, j.title AS jd_title, "
                 f"{_VERSION} "
                 "FROM runs r JOIN documents d ON d.id = r.document_id JOIN lineages l ON l.id = d.lineage_id "
                 "LEFT JOIN jds j ON j.id = r.jd_id ")

    def runs(self, lineage_id: int | None = None, limit: int = 30) -> list[sqlite3.Row]:
        where, args = ("WHERE d.lineage_id = ? ", (lineage_id,)) if lineage_id else ("", ())
        return self.conn.execute(self._RUN_COLS + where + "ORDER BY r.id DESC LIMIT ?", (*args, limit)).fetchall()

    def run(self, run_id: int) -> sqlite3.Row | None:
        return self.conn.execute(self._RUN_COLS.replace("SELECT ", "SELECT r.report, ", 1) + "WHERE r.id = ?",
                                 (run_id,)).fetchone()

    def report(self, run_id: int) -> dict | None:
        row = self.run(run_id)
        return json.loads(row["report"]) if row else None

    def previous_version_run(self, document_id: int, jd_id: int | None) -> sqlite3.Row | None:
        """Latest run of the version before this one in the same lineage (same JD preferred)."""
        rows = self.conn.execute(
            self._RUN_COLS.replace("SELECT ", "SELECT r.report, ", 1)
            + "WHERE d.lineage_id = (SELECT lineage_id FROM documents WHERE id = ?) "
            f"AND {_order('d')} < (SELECT COALESCE(doc_date, created_at), id FROM documents WHERE id = ?) "
            "ORDER BY COALESCE(d.doc_date, d.created_at) DESC, d.id DESC, (r.jd_id IS ?) DESC, r.id DESC LIMIT 1",
            (document_id, document_id, jd_id),
        ).fetchall()
        return rows[0] if rows else None

    def lineage_series(self, lineage_id: int, jd_id: int | None = None) -> list[sqlite3.Row]:
        """One run per version (the latest, preferring a given JD), oldest version first."""
        return self.conn.execute(
            self._RUN_COLS.replace("SELECT ", "SELECT r.report, ", 1)
            + "WHERE r.id IN (SELECT (SELECT r2.id FROM runs r2 WHERE r2.document_id = d3.id "
            "  ORDER BY (r2.jd_id IS ?) DESC, r2.id DESC LIMIT 1) FROM documents d3 WHERE d3.lineage_id = ?) "
            "ORDER BY COALESCE(d.doc_date, d.created_at), d.id",
            (jd_id, lineage_id),
        ).fetchall()

    def delete_run(self, run_id: int) -> bool:
        cur = self.conn.execute("DELETE FROM runs WHERE id = ?", (run_id,))
        self.conn.commit()
        return cur.rowcount > 0
