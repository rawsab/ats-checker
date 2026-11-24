from __future__ import annotations

from ..parse import ResumeView
from ..parse.contact import email_is_unprofessional
from .base import CheckResult, Context

CAT = "contact"


def fields(ctx: Context, view: ResumeView) -> CheckResult:
    c = view.contact
    weights = {"email": 35, "phone": 20, "linkedin": 15, "github": 20, "name": 10}
    have = {k: bool(getattr(c, k)) for k in weights}
    score = sum(w for k, w in weights.items() if have[k])
    missing = [k for k, ok in have.items() if not ok]
    ev = [f"{k}: {getattr(c, k)}" for k in weights if have[k]]
    if not missing:
        return CheckResult("contact.fields", CAT, "Contact details parsed", 100, "Name, email, phone, LinkedIn and GitHub all found.", ev, weight=3)
    fix = "Put contact details as plain text at the top of the page (not in an icon font, image or the PDF header)."
    if missing == ["github"]:
        fix = "Add your GitHub URL; for SWE roles recruiters look for it."
    return CheckResult("contact.fields", CAT, "Contact details parsed", score, f"Couldn't find: {', '.join(missing)}.", ev, fix, weight=3)


def email_quality(ctx: Context, view: ResumeView) -> CheckResult:
    email = view.contact.email
    if not email:
        return CheckResult("contact.email", CAT, "Professional email", 0, "No email found.", weight=1)
    issue = email_is_unprofessional(email)
    if issue:
        return CheckResult("contact.email", CAT, "Professional email", 70, f"{email}: {issue}.",
                           fix="Use firstname.lastname@ on Gmail, Outlook, iCloud or your own domain.", weight=1)
    return CheckResult("contact.email", CAT, "Professional email", 100, f"{email} looks professional.", weight=1)


def links_clickable(ctx: Context, view: ResumeView) -> CheckResult:
    c = view.contact
    targets = [u for u in (c.linkedin, c.github, c.portfolio) if u]
    if not targets:
        return CheckResult("contact.links", CAT, "Profile links are clickable", 100, "No profile links to check.", info=True)
    links = " ".join(ctx.doc.hyperlinks).lower()

    def _key(u: str) -> str:
        return u.lower().split("://")[-1].removeprefix("www.").rstrip("/")

    dead = [u for u in targets if _key(u) not in links]
    if not dead:
        return CheckResult("contact.links", CAT, "Profile links are clickable", 100, "All profile URLs are real hyperlinks.", weight=0.5)
    return CheckResult("contact.links", CAT, "Profile links are clickable", 60,
                       f"{len(dead)} of {len(targets)} profile URLs are plain text, not hyperlinks.",
                       dead, "Make them clickable links; recruiters read the PDF too.", weight=0.5)


ALL = [fields, email_quality, links_clickable]


def run(ctx: Context, view: ResumeView | None = None) -> list[CheckResult]:
    view = view or ctx.view
    return [fn(ctx, view) for fn in ALL]
