"""Turn extracted text into a structured view of the resume."""

from __future__ import annotations

from dataclasses import dataclass

from .contact import Contact, extract_contact
from .experience import Role, all_bullets, parse_roles, total_experience_months
from .sections import Section, find, split_sections


@dataclass
class ResumeView:
    """What one parser "sees" in the resume."""

    text: str
    sections: list[Section]
    contact: Contact
    roles: list[Role]  # experience roles only
    projects: list[Role]
    experience_months: int

    @property
    def bullets(self) -> list[str]:
        return all_bullets(self.roles) + all_bullets(self.projects)

    @property
    def section_names(self) -> list[str]:
        return [s.name for s in self.sections if s.name and s.name != "preamble"]

    def section_text(self, name: str) -> str:
        return "\n".join(s.text for s in find(self.sections, name))

    @property
    def years(self) -> float:
        return self.experience_months / 12


def parse_text(text: str, *, lenient: bool = True) -> ResumeView:
    sections = split_sections(text, lenient=lenient)
    roles = parse_roles(sections, ("experience", "leadership"))
    roles = [r for r in roles if r.section == "experience"] + [r for r in roles if r.section != "experience"]
    projects = parse_roles(sections, ("projects",))
    return ResumeView(
        text=text,
        sections=sections,
        contact=extract_contact(text),
        roles=[r for r in roles if r.section == "experience"],
        projects=projects + [r for r in roles if r.section != "experience"],
        experience_months=total_experience_months(roles),
    )
