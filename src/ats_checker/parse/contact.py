"""Extract contact details the way a parser would: regexes over plain text."""

from __future__ import annotations

import re
from dataclasses import dataclass, field

EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
PHONE = re.compile(r"(?<!\d)(?:\+?\d{1,3}[\s.\-]?)?(?:\(\d{3}\)|\d{3})[\s.\-]?\d{3}[\s.\-]?\d{4}(?!\d)")
LINKEDIN = re.compile(r"(?:https?://)?(?:[a-z]{2,3}\.)?linkedin\.com/in/[A-Za-z0-9_\-%]+/?", re.IGNORECASE)
GITHUB = re.compile(r"(?:https?://)?(?:www\.)?github\.com/[A-Za-z0-9_\-]+/?", re.IGNORECASE)
URL = re.compile(r"(?:https?://)?(?:www\.)?[a-z0-9\-]+(?:\.[a-z0-9\-]+)*\.(?:dev|io|me|com|net|org|app|ai|sh|xyz|co|tech|page|site)(?:/[^\s|,]*)?", re.IGNORECASE)
LOCATION = re.compile(
    r"\b[A-Z][a-zA-Z.]+(?:\s[A-Z][a-zA-Z.]+)*,\s?(?:[A-Z]{2}|[A-Z][a-z]+)\b(?!\s?\d{4})"
)

_PROFESSIONAL_DOMAINS_BAD = {"hotmail.com", "aol.com", "yahoo.com", "ymail.com", "rocketmail.com"}


@dataclass
class Contact:
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    linkedin: str | None = None
    github: str | None = None
    portfolio: str | None = None
    location: str | None = None
    other_urls: list[str] = field(default_factory=list)

    def key(self) -> str | None:
        """Stable identity across resume versions (used to group versions)."""
        if self.email:
            return self.email.lower()
        if self.name:
            return self.name.lower()
        return None


def _guess_name(lines: list[str]) -> str | None:
    for line in lines[:4]:
        s = line.strip()
        if EMAIL.search(s) or PHONE.search(s) or "http" in s or len(s) > 40:
            continue
        # strip trailing title fragments like "Jane Doe | Software Engineer"
        s = re.split(r"\s[|•·–-]\s", s)[0].strip()
        words = s.split()
        if 2 <= len(words) <= 4 and all(w[0].isupper() for w in words if w[0].isalpha()):
            return s
    return None


def extract_contact(text: str) -> Contact:
    lines = [l for l in text.splitlines() if l.strip()]
    head = "\n".join(lines[:12])
    c = Contact()
    c.name = _guess_name(lines)
    if m := EMAIL.search(text):
        c.email = m.group(0)
    if m := PHONE.search(head) or PHONE.search(text):
        c.phone = m.group(0).strip()
    if m := LINKEDIN.search(text):
        c.linkedin = m.group(0)
    if m := GITHUB.search(text):
        c.github = m.group(0)
    if m := LOCATION.search(head):
        c.location = m.group(0)
    for m in URL.finditer(head):
        url = m.group(0)
        low = url.lower()
        if "linkedin.com" in low or "github.com" in low or (c.email and low in c.email.lower()):
            continue
        if "@" in head[max(0, m.start() - 1) : m.start()]:
            continue
        c.other_urls.append(url)
    if c.other_urls:
        c.portfolio = c.other_urls[0]
    return c


def email_is_unprofessional(email: str) -> str | None:
    local, _, domain = email.lower().partition("@")
    if domain in _PROFESSIONAL_DOMAINS_BAD:
        return f"{domain} addresses read as dated to some recruiters"
    if re.search(r"(69|420|xx|lol|sexy|babe|gamer|princess|hottie)", local):
        return "the email's local part may read as unprofessional"
    if len(re.findall(r"\d", local)) >= 5:
        return "lots of digits make the email hard to remember"
    return None
