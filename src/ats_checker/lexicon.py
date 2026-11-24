"""Loads the bundled data files (taxonomy, synonyms, verbs, ...) and builds matchers."""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import cache
from importlib import resources

import yaml


def _data(name: str) -> str:
    return resources.files("ats_checker.data").joinpath(name).read_text(encoding="utf-8")


@cache
def section_aliases() -> dict[str, dict[str, list[str]]]:
    return yaml.safe_load(_data("section_aliases.yaml"))


@cache
def action_verbs() -> frozenset[str]:
    return frozenset(line.strip().lower() for line in _data("action_verbs.txt").splitlines() if line.strip())


@cache
def weak_phrases() -> tuple[str, ...]:
    return tuple(line.strip().lower() for line in _data("weak_phrases.txt").splitlines() if line.strip())


@cache
def taxonomy() -> dict[str, list[str]]:
    return yaml.safe_load(_data("swe_skills.yaml"))


@cache
def synonyms() -> dict[str, list[str]]:
    return yaml.safe_load(_data("synonyms.yaml"))


_IRREGULAR_PRESENT = {
    "built": ["build", "builds"], "led": ["lead", "leads"], "wrote": ["write", "writes"],
    "drove": ["drive", "drives"], "grew": ["grow", "grows"], "rebuilt": ["rebuild", "rebuilds"],
    "rewrote": ["rewrite", "rewrites"], "ran": ["run", "runs"], "made": ["make", "makes"],
}


@cache
def present_tense_verbs() -> frozenset[str]:
    """Present-tense forms of the action verbs ("develop", "develops"), for tense checks."""
    out: set[str] = set()
    for v in action_verbs():
        if v in _IRREGULAR_PRESENT:
            out.update(_IRREGULAR_PRESENT[v])
        elif v.endswith("ied"):
            out.update({v[:-3] + "y", v[:-3] + "ies"})
        elif v.endswith("ed"):
            stems = {v[:-1], v[:-2]}
            if len(v) > 4 and v[-3] == v[-4]:  # shipped -> ship
                stems.add(v[:-3])
            for s in stems:
                if len(s) >= 3:
                    out.update({s, s + "s"})
    out.update(v for verbs in _IRREGULAR_PRESENT.values() for v in verbs)
    return frozenset(out - action_verbs())


# Short canonical names that are also ordinary English words or letters: match these
# case-sensitively so "go to market" or "grade C" don't count as skills.
_CASE_SENSITIVE = {"Go", "R", "C", "Rust", "Swift", "Spring", "Express", "Dart", "Spark",
                   "Lambda", "Helm", "Phoenix", "Flutter", "Ruby", "Agile", "Security",
                   "Caching", "Concurrency", "Algorithms", "REST", "Vue", "Rails", "Elixir"}
_BOUNDARY_L = r"(?<![A-Za-z0-9+#&/.])"
_BOUNDARY_R = r"(?![A-Za-z0-9+#&]|/[A-Za-z])"


# Extra context exclusions for skills that collide with common resume phrases.
_EXCLUDE_AFTER = {"Spring": r"(?!\s*['’]?\d{2,4}|\s+(?:semester|term|break|quarter|intern))"}


@dataclass(frozen=True)
class Skill:
    name: str
    category: str | None
    exact: re.Pattern  # canonical name (+ plural), used by exact-match rankers
    fuzzy: re.Pattern  # canonical name or any synonym


def _pattern(terms: list[str], case_sensitive: bool, after: str = "") -> re.Pattern:
    alts = []
    for t in sorted(set(terms), key=len, reverse=True):
        esc = re.escape(t).replace(r"\ ", r"[\s\-]+")
        alts.append(esc + (r"s?" if t[-1].isalpha() and len(t) > 3 else ""))
    flags = 0 if case_sensitive else re.IGNORECASE
    return re.compile(_BOUNDARY_L + "(?:" + "|".join(alts) + ")" + _BOUNDARY_R + after, flags)


def make_skill(name: str, category: str | None = None) -> Skill:
    cs = name in _CASE_SENSITIVE or len(name) <= 2
    exact = _pattern([name], cs, _EXCLUDE_AFTER.get(name, ""))
    # synonyms are lowercase in the data file; short ones (js, ts, k8s) are safe case-insensitive
    aliases = synonyms().get(name, [])
    fuzzy = _combine(exact, _pattern(aliases, False)) if aliases else exact
    return Skill(name=name, category=category, exact=exact, fuzzy=fuzzy)


def _combine(a: re.Pattern, b: re.Pattern) -> re.Pattern:
    # Merge patterns with different case sensitivity by inlining the flag per alternative.
    pa = a.pattern if not (a.flags & re.IGNORECASE) else "(?i:" + a.pattern + ")"
    pb = "(?i:" + b.pattern + ")" if b.flags & re.IGNORECASE else b.pattern
    return re.compile(pa + "|" + pb)


@cache
def all_skills() -> tuple[Skill, ...]:
    return tuple(make_skill(name, cat) for cat, names in taxonomy().items() for name in names)


@cache
def skill_by_name() -> dict[str, Skill]:
    return {s.name.lower(): s for s in all_skills()}
