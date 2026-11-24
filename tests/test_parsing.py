from datetime import date
from pathlib import Path

import pytest

from ats_checker.input import normalize_path
from ats_checker.jd import parse_jd
from ats_checker.lexicon import all_skills
from ats_checker.parse import parse_text
from ats_checker.parse.experience import parse_point


@pytest.mark.parametrize("raw,expected", [
    ("/Users/me/My\\ Resume\\ \\(1\\).pdf", "/Users/me/My Resume (1).pdf"),
    ("'/Users/me/My Resume.pdf' ", "/Users/me/My Resume.pdf"),
    ('"/tmp/a b.pdf"', "/tmp/a b.pdf"),
    ("file:///tmp/My%20Resume.pdf", "/tmp/My Resume.pdf"),
    ("/tmp/plain.pdf", "/tmp/plain.pdf"),
])
def test_normalize_path(raw, expected):
    assert normalize_path(raw) == Path(expected)


def skills_in(text):
    return {s.name for s in all_skills() if s.fuzzy.search(text)}


def test_skill_matching_avoids_false_positives():
    assert skills_in("Built services in Go on k8s") >= {"Go", "Kubernetes"}
    assert "Go" not in skills_in("ready to go to market")
    assert "JavaScript" not in skills_in("Node.js")
    assert "Spring" not in skills_in("Teaching assistant, Spring 2023")
    assert "Spring" in skills_in("Java Spring services")
    assert {"C++", "C#"} <= skills_in("C++ and C#")


@pytest.mark.parametrize("raw,value,fmt", [
    ("Jan 2022", date(2022, 1, 1), "month-name"),
    ("September 2019", date(2019, 9, 1), "month-name"),
    ("05/2020", date(2020, 5, 1), "numeric"),
    ("2018", date(2018, 1, 1), "year"),
    ("Summer 2021", date(2021, 6, 1), "season"),
])
def test_parse_point(raw, value, fmt):
    p = parse_point(raw)
    assert (p.value, p.fmt) == (value, fmt)


def test_roles_and_bullets():
    text = """Jane Doe
jane@example.com
EXPERIENCE
Software Engineer, Acme   Jan 2021 – Present
• Built a thing in Go that served 1M users and
wrapped onto a second line.
• Reduced latency by 30%.
Intern, Beta Co
Jun 2019 - Aug 2019
- Wrote tests in Python.
EDUCATION
BS CS, State U   2015 – 2019
"""
    v = parse_text(text)
    assert [r.header.split(",")[0] for r in v.roles] == ["Software Engineer", "Intern"]
    assert v.roles[0].bullets[0].endswith("second line.")
    assert len(v.roles[0].bullets) == 2
    assert v.roles[0].is_current
    assert {"experience", "education"} <= set(v.section_names)


def test_strict_vs_lenient_headers():
    text = "Where I've Worked\nTOOLBOX\nPython\nExperience\n"
    assert "skills" not in parse_text(text, lenient=False).section_names
    assert "skills" in parse_text(text, lenient=True).section_names


def test_jd_parsing():
    jd = parse_jd("""Staff Software Engineer, Infra
About us
We use Kafka everywhere.
Requirements
- 8+ years building distributed systems
- Python or Go
Nice to have
- Terraform
""")
    assert jd.title.startswith("Staff Software Engineer")
    assert jd.seniority == "staff"
    assert jd.min_years == 8
    req = {s.name for s in jd.required}
    pref = {s.name for s in jd.preferred}
    assert {"Python", "Go", "Distributed Systems"} <= req
    assert "Terraform" in pref and "Kafka" in pref
