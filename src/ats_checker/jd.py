"""Load a job description and pull out what an ATS would screen on."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

from .lexicon import Skill, all_skills, make_skill

_PREFERRED_HEAD = re.compile(r"(preferred|nice[\s-]to[\s-]have|bonus|plus|desired|good to have|extra credit)", re.IGNORECASE)
_REQUIRED_HEAD = re.compile(r"(requirements|required|qualifications|must[\s-]have|what you.?ll need|you have|minimum|basic qualifications|who you are|what we.?re looking for)", re.IGNORECASE)
_PREFERRED_INLINE = re.compile(r"(a plus|is a plus|are a plus|preferred|nice to have|bonus|ideally)", re.IGNORECASE)
YEARS = re.compile(r"(\d{1,2})\s*\+?\s*(?:-\s*\d{1,2}\s*)?(?:years?|yrs?)", re.IGNORECASE)
SENIORITY = ["intern", "new grad", "junior", "associate", "mid", "senior", "staff", "principal", "lead", "manager", "director"]

# Tech-looking tokens in a JD that aren't in our taxonomy: OAuth2, WebRTC, gRPC-web, Three.js...
_TECH_TOKEN = re.compile(r"\b(?:[A-Z][a-z]+[A-Z][A-Za-z]+|[A-Za-z]+\.js|[A-Z]{2,}[a-z]*\d*|[A-Za-z]+\d+[A-Za-z]*)\b")
_TOKEN_STOP = {"US", "USA", "EEO", "PTO", "CEO", "CTO", "HR", "OK", "LLC", "IT", "UI", "UX", "AI",
               "BS", "MS", "PhD", "B.S", "M.S", "ID", "FAQ", "ADA", "TBD", "API", "APIs", "SaaS",
               "WFH", "NYC", "SF", "EST", "PST", "LGBTQ", "LGBTQIA", "DEI", "MBA", "GPA", "IPO"}


@dataclass
class JobDescription:
    text: str
    source: str
    title: str | None
    required: list[Skill] = field(default_factory=list)
    preferred: list[Skill] = field(default_factory=list)
    min_years: int | None = None
    seniority: str | None = None

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.text.strip().encode()).hexdigest()

    @property
    def keywords(self) -> list[tuple[Skill, str]]:
        return [(s, "required") for s in self.required] + [(s, "preferred") for s in self.preferred]


def load_jd(arg: str) -> JobDescription:
    if re.match(r"https?://", arg):
        return parse_jd(fetch_url(arg), source=arg)
    path = Path(arg).expanduser()
    if path.exists():
        return parse_jd(path.read_text(encoding="utf-8", errors="replace"), source=str(path))
    return parse_jd(arg, source="inline")


def fetch_url(url: str) -> str:
    import httpx
    from bs4 import BeautifulSoup

    resp = httpx.get(url, follow_redirects=True, timeout=20,
                     headers={"User-Agent": "Mozilla/5.0 (ats-checker; +local)"})
    resp.raise_for_status()
    soup = BeautifulSoup(resp.text, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript", "svg", "form"]):
        tag.decompose()
    main = soup.find("main") or soup.find(attrs={"class": re.compile("job|posting|description", re.IGNORECASE)}) or soup.body or soup
    text = main.get_text("\n")
    return re.sub(r"\n\s*\n+", "\n\n", text).strip()


def _segments(text: str) -> list[tuple[str, str]]:
    """Label each line 'required' / 'preferred' / 'other' based on the heading above it."""
    mode = "other"
    out = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        is_heading = len(line) < 70 and not line.endswith(".") and (line.endswith(":") or len(line.split()) <= 7)
        if is_heading and _PREFERRED_HEAD.search(line):
            mode = "preferred"
            continue
        if is_heading and _REQUIRED_HEAD.search(line):
            mode = "required"
            continue
        if is_heading and len(line.split()) <= 4 and line[:1].isupper() and not re.search(r"[,;]", line):
            # some other heading ("About us", "Benefits"); stop attributing lines to requirements
            mode = "other"
            continue
        label = "preferred" if _PREFERRED_INLINE.search(line) else mode
        out.append((label, line))
    return out


def parse_jd(text: str, *, source: str = "inline") -> JobDescription:
    text = text.strip()
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    title = next((l for l in lines[:5] if len(l) < 90 and re.search(r"engineer|developer|swe|sde|programmer|architect", l, re.IGNORECASE)), lines[0][:90] if lines else None)
    segs = _segments(text)
    has_sections = any(label != "other" for label, _ in segs)

    req: dict[str, Skill] = {}
    pref: dict[str, Skill] = {}
    for label, line in segs:
        bucket = pref if label == "preferred" else req
        if label == "other" and has_sections:
            # mentioned in the blurb but not in requirements: still worth matching, lower weight
            bucket = pref
        for skill in all_skills():
            if skill.fuzzy.search(line):
                bucket.setdefault(skill.name, skill)
        known = {s.lower() for s in req} | {s.lower() for s in pref}
        for tok in _TECH_TOKEN.findall(line):
            if tok in _TOKEN_STOP or tok.lower() in known or len(tok) < 3:
                continue
            if any(sk.fuzzy.fullmatch(tok) for sk in all_skills()):
                continue
            bucket.setdefault(tok, make_skill(tok, None))
    for name in list(pref):
        if name in req:
            del pref[name]

    years = [int(m.group(1)) for m in YEARS.finditer(text) if int(m.group(1)) <= 20]
    head = " ".join(lines[:3]).lower()
    seniority = next((s for s in SENIORITY if re.search(rf"\b{s}\b", (title or "").lower())), None) \
        or next((s for s in SENIORITY if re.search(rf"\b{s}\b", head)), None)
    return JobDescription(
        text=text,
        source=source,
        title=title,
        required=list(req.values()),
        preferred=list(pref.values()),
        min_years=min(years) if years else None,
        seniority=seniority,
    )
