"""Roles, date ranges and bullets out of the Experience (and Projects) sections."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date

from .sections import Section, find

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
_MONTH_RE = r"(?:jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sept?(?:ember)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?"
_SEASON_RE = r"(?:spring|summer|fall|autumn|winter)"
_POINT = (
    rf"(?:(?:{_MONTH_RE}|{_SEASON_RE})\s+\d{{4}}"  # Jan 2020 / Summer 2021
    r"|\d{1,2}/\d{4}"  # 05/2020
    r"|\d{4}-\d{2}"  # 2020-05
    r"|\d{4})"  # 2020
)
_END = rf"(?:{_POINT}|present|current|now|today|ongoing)"
DATE_RANGE = re.compile(rf"(?P<start>{_POINT})\s*(?:-|–|—|to|until|→)\s*(?P<end>{_END})", re.IGNORECASE)
SINGLE_DATE = re.compile(rf"(?:{_MONTH_RE}|{_SEASON_RE})\s+\d{{4}}", re.IGNORECASE)

BULLET_CHARS = "•●▪◦‣∙·○■□➢➤►▸-–*"
# "(cid:N)" at line start is an unmapped bullet glyph; parsers still see a bullet there.
_BULLET_RE = re.compile(rf"^\s*(?:[{re.escape(BULLET_CHARS)}]|\(cid:\d+\))\s*")


@dataclass
class DatePoint:
    raw: str
    value: date | None
    fmt: str  # "month-name" | "season" | "numeric" | "year" | "present"


@dataclass
class Role:
    header: str
    start: DatePoint
    end: DatePoint
    bullets: list[str] = field(default_factory=list)
    section: str = "experience"

    @property
    def is_current(self) -> bool:
        return self.end.fmt == "present"

    @property
    def months(self) -> int:
        if not (self.start.value and self.end.value):
            return 0
        return max(0, (self.end.value.year - self.start.value.year) * 12
                   + self.end.value.month - self.start.value.month)


def parse_point(raw: str, *, today: date | None = None) -> DatePoint:
    s = raw.strip().lower().rstrip(".")
    today = today or date.today()
    if s in {"present", "current", "now", "today", "ongoing"}:
        return DatePoint(raw, today, "present")
    if m := re.match(r"(spring|summer|fall|autumn|winter)\s+(\d{4})", s):
        month = {"spring": 3, "summer": 6, "fall": 9, "autumn": 9, "winter": 12}[m.group(1)]
        return DatePoint(raw, date(int(m.group(2)), month, 1), "season")
    if m := re.match(r"([a-z]+)\.?\s+(\d{4})", s):
        month = _MONTHS.get(m.group(1)[:4]) or _MONTHS.get(m.group(1)[:3])
        if month:
            return DatePoint(raw, date(int(m.group(2)), month, 1), "month-name")
    if m := re.match(r"(\d{1,2})/(\d{4})", s):
        if 1 <= int(m.group(1)) <= 12:
            return DatePoint(raw, date(int(m.group(2)), int(m.group(1)), 1), "numeric")
    if m := re.match(r"(\d{4})-(\d{2})", s):
        if 1 <= int(m.group(2)) <= 12:
            return DatePoint(raw, date(int(m.group(1)), int(m.group(2)), 1), "numeric")
    if m := re.match(r"(\d{4})$", s):
        return DatePoint(raw, date(int(m.group(1)), 1, 1), "year")
    return DatePoint(raw, None, "unknown")


def is_bullet(line: str) -> bool:
    return bool(_BULLET_RE.match(line))


def strip_bullet(line: str) -> str:
    return _BULLET_RE.sub("", line).strip()


def _continues(prev: str, line: str) -> bool:
    """Heuristic: is ``line`` a wrapped continuation of the bullet ``prev``?"""
    if DATE_RANGE.search(line):
        return False
    if line[:1].islower() or line[:1] in "(&,":
        return True
    return not prev.rstrip().endswith((".", "!", "?")) and len(line.split()) >= 4


def parse_roles(sections: list[Section], names=("experience",)) -> list[Role]:
    roles: list[Role] = []
    for name in names:
        for sec in find(sections, name):
            roles.extend(_roles_in(sec, name))
    return roles


def _roles_in(sec: Section, name: str) -> list[Role]:
    roles: list[Role] = []
    pending_header: list[str] = []
    current: Role | None = None
    last_was_bullet = False
    force_bullet = False  # some extractors put the bullet glyph on its own line
    for line in sec.lines:
        if is_bullet(line) and not strip_bullet(line):
            force_bullet = True
            continue
        if force_bullet:
            line, force_bullet = "• " + line, False
        m = DATE_RANGE.search(line)
        if m and not is_bullet(line):
            header = " ".join(pending_header[-2:] + [line[: m.start()].strip(" ,|–-"), line[m.end():].strip(" ,|–-")]).strip()
            current = Role(
                header=re.sub(r"\s+", " ", header),
                start=parse_point(m.group("start")),
                end=parse_point(m.group("end")),
                section=name,
            )
            roles.append(current)
            pending_header = []
            last_was_bullet = False
            continue
        if is_bullet(line):
            text = strip_bullet(line)
            if current is None:
                # projects often have bullets without a date range
                current = Role(header=" ".join(pending_header[-2:]), start=DatePoint("", None, "unknown"),
                               end=DatePoint("", None, "unknown"), section=name)
                roles.append(current)
                pending_header = []
            if text:
                current.bullets.append(text)
            last_was_bullet = True
            continue
        if last_was_bullet and current and current.bullets and _continues(current.bullets[-1], line):
            current.bullets[-1] = current.bullets[-1] + " " + line
            continue
        pending_header.append(line)
        last_was_bullet = False
    return roles


def all_bullets(roles: list[Role]) -> list[str]:
    return [b for r in roles for b in r.bullets]


def total_experience_months(roles: list[Role]) -> int:
    """Union of role date ranges so overlapping jobs aren't double counted."""
    spans = sorted(
        (r.start.value, r.end.value) for r in roles if r.start.value and r.end.value and r.section == "experience"
    )
    total, cur_s, cur_e = 0, None, None
    for s, e in spans:
        if cur_e is None or s > cur_e:
            if cur_e is not None:
                total += (cur_e.year - cur_s.year) * 12 + cur_e.month - cur_s.month
            cur_s, cur_e = s, e
        else:
            cur_e = max(cur_e, e)
    if cur_e is not None:
        total += (cur_e.year - cur_s.year) * 12 + cur_e.month - cur_s.month
    return total
