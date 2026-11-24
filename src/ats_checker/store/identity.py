"""Decide whether a PDF is a resume we've seen, a new version of one, or a new resume.

People rename files ("resume.pdf" forever) and also keep many different files for the same
resume, so file names are ignored. Signals, strongest first:

1. identical bytes (sha256)         → the same document
2. same XMP DocumentID              → a re-export of the same source document
3. text similarity + same contact   → an edited version
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .db import Store

AUTO_LINK = 0.55  # Jaccard over word 3-shingles
AUTO_LINK_SAME_CONTACT = 0.25
ASK = 0.15


@dataclass
class Match:
    status: str  # "existing" | "new_version" | "new_lineage" | "ask"
    document_id: int | None = None
    lineage_id: int | None = None
    lineage_name: str | None = None
    similarity: float | None = None
    reason: str = ""


def shingles(text: str, k: int = 3) -> set[tuple[str, ...]]:
    words = re.findall(r"[a-z0-9][a-z0-9+#.\-]*", text.lower())
    return {tuple(words[i : i + k]) for i in range(max(len(words) - k + 1, 1))}


def jaccard(a: set, b: set) -> float:
    if not a or not b:
        return 0.0
    return len(a & b) / len(a | b)


def resolve(store: Store, doc, text: str, contact_key: str | None) -> Match:
    if row := store.document_by_sha(doc.sha256):
        return Match("existing", row["id"], row["lineage_id"], None, 1.0, "identical file contents")

    mine = shingles(text)
    best: Match | None = None
    seen_lineages: set[int] = set()
    for cand in store.documents():  # newest first, so the first hit per lineage is its latest version
        if cand["lineage_id"] in seen_lineages:
            continue
        seen_lineages.add(cand["lineage_id"])
        sim = jaccard(mine, shingles(cand["text"]))
        same_contact = bool(contact_key and cand["contact_key"] == contact_key)
        if doc.xmp_document_id and cand["xmp_document_id"] == doc.xmp_document_id and sim >= ASK:
            return Match("new_version", None, cand["lineage_id"], cand["lineage_name"], sim, "same PDF DocumentID")
        if sim >= AUTO_LINK or (same_contact and sim >= AUTO_LINK_SAME_CONTACT):
            status, reason = "new_version", "similar text" + (" and same contact details" if same_contact else "")
        elif sim >= ASK or same_contact:
            status, reason = "ask", "somewhat similar" + (", same contact details" if same_contact else "")
        else:
            continue
        m = Match(status, None, cand["lineage_id"], cand["lineage_name"], sim, reason)
        rank = {"new_version": 1, "ask": 0}
        if best is None or (rank[m.status], m.similarity) > (rank[best.status], best.similarity):
            best = m
    return best or Match("new_lineage", reason="no similar resume in history")


def lineage_name_for(doc, label: str | None, contact_name: str | None) -> str:
    if label:
        return label
    stem = re.sub(r"[_\-]+", " ", doc.path.stem).strip()
    if re.fullmatch(r"(?i)(my\s*)?(resume|cv)(\s*\(?\d+\)?)?", stem) and contact_name:
        return f"{contact_name} resume"
    return stem or "resume"
