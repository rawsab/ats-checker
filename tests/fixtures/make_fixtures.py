"""Generate synthetic resume PDFs that exercise specific ATS failure modes.

    uv run python tests/fixtures/make_fixtures.py [out_dir]
"""

from __future__ import annotations

import sys
from pathlib import Path

# reportlab's bundled TTFs carry a ToUnicode map, so "•" extracts as a real character
# (the built-in Type1 Helvetica turns it into an unmapped "(cid:127)").
import reportlab
from reportlab.lib.colors import white
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from reportlab.platypus import Table, TableStyle

_FONT_DIR = Path(reportlab.__file__).parent / "fonts"
pdfmetrics.registerFont(TTFont("Body", str(_FONT_DIR / "Vera.ttf")))
pdfmetrics.registerFont(TTFont("Body-Bold", str(_FONT_DIR / "VeraBd.ttf")))

W, H = LETTER
M = 54  # 0.75in margins

CONTACT = "jane.doe@gmail.com  |  (415) 555-0134  |  San Francisco, CA"
LINKS = [("linkedin.com/in/janedoe", "https://linkedin.com/in/janedoe"),
         ("github.com/janedoe", "https://github.com/janedoe")]

EXPERIENCE = [
    ("Senior Software Engineer, Acme Cloud", "Jan 2022 – Present", [
        "Architected a multi-tenant billing service in Go and PostgreSQL handling 12M requests/day with p99 latency under 80ms.",
        "Migrated 40 services from EC2 to Kubernetes on AWS using Terraform, cutting infrastructure cost by 32%.",
        "Led a team of 4 engineers to ship a real-time usage dashboard in React and TypeScript adopted by 3,000 customers.",
        "Introduced contract testing and GitHub Actions CI/CD, reducing failed deploys by 60%.",
    ]),
    ("Software Engineer, Brightline Labs", "Jun 2019 – Dec 2021", [
        "Built REST and gRPC APIs in Python (FastAPI) serving 2M monthly active users.",
        "Reduced Redis cache misses by 45% by redesigning key expiry and adding read-through caching.",
        "Developed Kafka-based event pipeline processing 500K events/minute with exactly-once delivery.",
    ]),
]
EDUCATION = [("B.S. Computer Science, University of Washington", "Sep 2015 – Jun 2019")]
SKILLS = [
    "Languages: Go, Python, TypeScript, SQL, Java",
    "Infrastructure: AWS, Kubernetes, Docker, Terraform, GitHub Actions",
    "Data: PostgreSQL, Redis, Kafka, Elasticsearch",
]
PROJECTS = [("Distributed rate limiter (open source)", [
    "Wrote a token-bucket rate limiter in Rust with Redis backend, benchmarked at 1.2M ops/sec.",
])]


class Writer:
    def __init__(self, c: Canvas, x: float, y: float, width: float):
        self.c, self.x, self.y, self.width = c, x, y, width

    def line(self, text: str, size: float = 10.5, font: str = "Body", gap: float = 3, right: str | None = None):
        self.c.setFont(font, size)
        self.c.drawString(self.x, self.y, text)
        if right:
            self.c.drawRightString(self.x + self.width, self.y, right)
        self.y -= size + gap

    def header(self, text: str):
        self.y -= 4
        self.line(text.upper(), 12, "Body-Bold", gap=4)

    def bullet(self, text: str, size: float = 10.5):
        lines = simpleSplit(text, "Body", size, self.width - 12)
        self.c.setFont("Body", size)
        self.c.drawString(self.x, self.y, "•")
        for i, ln in enumerate(lines):
            self.c.drawString(self.x + 12, self.y, ln)
            self.y -= size + 2.5
        self.y -= 1

    def link(self, label: str, url: str, x: float):
        self.c.drawString(x, self.y, label)
        tw = self.c.stringWidth(label, "Body", 10.5)
        self.c.linkURL(url, (x, self.y - 2, x + tw, self.y + 10), relative=0)
        return x + tw + 16


def _canvas(path: Path, title: str = "Jane Doe Resume") -> Canvas:
    c = Canvas(str(path), pagesize=LETTER)
    c.setTitle(title)
    c.setAuthor("Jane Doe")
    return c


def _body(w: Writer, *, skills_as_table=False, experience=EXPERIENCE):
    w.header("Experience")
    for title, dates, bullets in experience:
        w.line(title, 11, "Body-Bold", right=dates)
        for b in bullets:
            w.bullet(b)
    w.header("Projects")
    for title, bullets in PROJECTS:
        w.line(title, 11, "Body-Bold")
        for b in bullets:
            w.bullet(b)
    w.header("Skills")
    if skills_as_table:
        rows = [s.split(": ", 1) for s in SKILLS]
        t = Table(rows, colWidths=[110, w.width - 110])
        t.setStyle(TableStyle([("GRID", (0, 0), (-1, -1), 0.5, "black"), ("FONT", (0, 0), (-1, -1), "Body", 10)]))
        tw, th = t.wrapOn(w.c, w.width, 200)
        t.drawOn(w.c, w.x, w.y - th + 10)
        w.y -= th + 6
    else:
        for s in SKILLS:
            w.line(s)
    w.header("Education")
    for school, dates in EDUCATION:
        w.line(school, right=dates)


def _contact_block(w: Writer):
    w.line("Jane Doe", 20, "Body-Bold", gap=6)
    w.line("Backend Software Engineer · Go, Kubernetes, PostgreSQL", 11)
    w.line(CONTACT, 10.5, gap=0)
    w.y -= 13
    x = w.x
    w.c.setFont("Body", 10.5)
    for label, url in LINKS:
        x = w.link(label, url, x)
    w.y -= 16


def clean(path: Path, experience=EXPERIENCE):
    c = _canvas(path)
    w = Writer(c, M, H - 60, W - 2 * M)
    _contact_block(w)
    _body(w, experience=experience)
    c.save()


def edited(path: Path):
    """Same person, a later revision: one bullet rewritten, one added."""
    exp = [list(e) for e in EXPERIENCE]
    exp[0][2] = exp[0][2][:2] + [
        "Designed an OpenTelemetry tracing rollout across 25 services, cutting incident triage time by 50%.",
        "Mentored 3 junior engineers through design reviews and on-call onboarding.",
    ]
    clean(path, experience=[tuple(e) for e in exp])


def two_column(path: Path):
    c = _canvas(path)
    side_w = 160
    side = Writer(c, M, H - 60, side_w)
    main = Writer(c, M + side_w + 30, H - 60, W - 2 * M - side_w - 30)
    side.line("Jane Doe", 18, "Body-Bold", gap=6)
    for part in CONTACT.split("  |  "):
        side.line(part, 9.5)
    side.header("Skills")
    for s in SKILLS:
        for ln in simpleSplit(s, "Body", 9.5, side_w):
            side.line(ln, 9.5)
    side.header("Education")
    for ln in simpleSplit(EDUCATION[0][0], "Body", 9.5, side_w) + [EDUCATION[0][1]]:
        side.line(ln, 9.5)
    main.header("Experience")
    older = ("Software Engineering Intern, Northwind", "May 2018 – Aug 2018", [
        "Implemented a Python CLI that automated release notes for 30 repositories, saving 5 hours per release.",
        "Added integration tests in Java for the payments SDK, raising coverage from 52% to 81%.",
        "Profiled a slow PostgreSQL query path and added indexes, cutting report generation from 40s to 3s.",
    ])
    for title, dates, bullets in EXPERIENCE + [older]:
        main.line(title, 10.5, "Body-Bold")
        main.line(dates, 9.5)
        for b in bullets:
            main.bullet(b, 9.5)
    main.header("Projects")
    for title, bullets in PROJECTS:
        main.line(title, 10.5, "Body-Bold")
        for b in bullets:
            main.bullet(b, 9.5)
    c.save()


def table_skills(path: Path):
    c = _canvas(path)
    w = Writer(c, M, H - 60, W - 2 * M)
    _contact_block(w)
    _body(w, skills_as_table=True)
    c.save()


def header_contact(path: Path):
    """Contact info placed in the page header zone (top ~0.25in)."""
    c = _canvas(path)
    c.setFont("Body", 9)
    c.drawString(M, H - 20, "Jane Doe  ·  " + CONTACT)
    w = Writer(c, M, H - 70, W - 2 * M)
    w.line("Backend Software Engineer", 14, "Body-Bold")
    _body(w)
    c.save()


def white_text(path: Path):
    c = _canvas(path)
    w = Writer(c, M, H - 60, W - 2 * M)
    _contact_block(w)
    _body(w)
    c.setFillColor(white)
    c.setFont("Body", 6)
    c.drawString(M, 30, "Kubernetes Rust Scala Spark Snowflake Airflow PyTorch TensorFlow Kafka Cassandra")
    c.save()


def tight_spacing(path: Path):
    """LaTeX-style text: each word placed separately with a ~2.9pt gap and no space glyphs."""
    c = _canvas(path)
    w = Writer(c, M, H - 60, W - 2 * M)
    _contact_block(w)

    def words(text: str):
        c.setFont("Body", 9)
        x = w.x
        for word in text.split():
            c.drawString(x, w.y, word)
            x += c.stringWidth(word, "Body", 9) + 2.9
        w.y -= 12

    w.header("Experience")
    for title, dates, bullets in EXPERIENCE:
        w.line(title, 10, "Body-Bold", right=dates)
        for b in bullets:
            c.setFont("Body", 9)
            c.drawString(w.x, w.y, "•")
            w.x += 10
            words(b[:95])
            w.x -= 10
    w.header("Skills")
    for line in SKILLS:
        words(line)
    w.header("Education")
    w.line(EDUCATION[0][0], 10, right=EDUCATION[0][1])
    c.save()


def image_only(path: Path):
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (1275, 1650), "white")
    d = ImageDraw.Draw(img)
    for i in range(40):
        d.rectangle((90, 90 + i * 36, 1100 - (i % 5) * 80, 108 + i * 36), fill="black")
    c = _canvas(path)
    from reportlab.lib.utils import ImageReader

    c.drawImage(ImageReader(img), 0, 0, W, H)
    c.save()


ALL = {
    "Jane_Doe_Resume.pdf": clean,
    "Jane_Doe_Resume_edited.pdf": edited,
    "two_column.pdf": two_column,
    "table_skills.pdf": table_skills,
    "header_contact.pdf": header_contact,
    "white_text.pdf": white_text,
    "image_only.pdf": image_only,
    "tight_spacing.pdf": tight_spacing,
}


def build(out: Path) -> dict[str, Path]:
    out.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, fn in ALL.items():
        fn(out / name)
        paths[name] = out / name
    return paths


if __name__ == "__main__":
    out = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).parent / "out"
    for p in build(out).values():
        print(p)
