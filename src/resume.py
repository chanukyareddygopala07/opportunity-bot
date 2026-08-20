"""Phase 19 — Aawara resume system.

Fact-locked resume builder + Rudra tailoring.

Rules (from the product spec):
- A resume is built ONLY from facts the student supplied (profile fields,
  education, experience, projects). Nothing is invented.
- Tailoring for a job may REORDER facts and REPHRASE wording, and may
  re-emphasize skills the student already listed that appear in the job
  description. It may never add a skill, project, GPA or date that the
  student did not provide.
- Outputs: structured dict, plain-text ATS form, and a PDF export.
"""
import re
from datetime import date

from src import db

CONTACT_KEYS = ("email", "phone", "linkedin", "github", "website")


def profile_resume(user):
    """Build the base (untailored) resume dict from the user profile.

    `user` is the row from users; extra resume sections live in the
    user's resume_json column (education, experience, projects, awards,
    contact). All values are copied verbatim — never invented.
    """
    extra = db.get_user_resume(user["id"]) if user.get("id") else {}
    skills = [s for s in (user.get("skills") or []) if s]
    interests = [i for i in (user.get("interests") or []) if i]
    education = [e for e in (extra.get("education") or []) if isinstance(e, dict)]
    experience = [x for x in (extra.get("experience") or []) if isinstance(x, dict)]
    projects = [p for p in (extra.get("projects") or []) if isinstance(p, dict)]
    awards = [a for a in (extra.get("awards") or []) if a]
    contact = {}
    for key in CONTACT_KEYS:
        value = (extra.get("contact") or {}).get(key) or user.get(key)
        if value:
            contact[key] = str(value)

    degree_parts = [p for p in [
        user.get("degree"),
        user.get("branch"),
        user.get("university"),
    ] if p]
    if user.get("graduation_year"):
        degree_parts.append(str(user["graduation_year"]))
    elif user.get("current_year"):
        degree_parts.append(f"Year {user['current_year']}")
    degree_line = " — ".join(degree_parts)
    if user.get("cgpa") is not None:
        degree_line = f"{degree_line} · CGPA {user['cgpa']}"

    if education:
        education_rows = education
    elif degree_line:
        education_rows = [{"title": degree_line}]
    else:
        education_rows = []

    return {
        "name": user.get("username") or user.get("email") or "Student",
        "contact": contact,
        "headline": (
            f"{user.get('degree') or 'Student'} student"
            f"{f' in {user['branch']}' if user.get('branch') else ''}"
            f"{f' — {user['university']}' if user.get('university') else ''}"
        ),
        "education": education_rows,
        "experience": experience,
        "projects": projects,
        "skills": skills,
        "interests": interests,
        "awards": awards,
    }


def _normalize(text):
    return re.sub(r"[^a-z0-9+#.]", "", (text or "").lower())


def _skill_overlap(skills, job_text):
    lowered = (job_text or "").lower()
    matched = []
    for s in skills:
        words = [w for w in re.split(r"[^a-z0-9+#.]+", s.lower()) if w]
        if not words:
            continue
        pattern = r"\s*".join(re.escape(w) for w in words)
        if re.search(r"(?<![a-z0-9+#.])" + pattern + r"(?![a-z0-9+#.])", lowered):
            matched.append(s)
    return matched


def tailor(resume, opportunity=None, job_text=None):
    """Return (tailored_dict, notes) — reorders/rephrases facts only.

    - Skills that appear in the JD move to the top of the skills list and
      get an explicit "(matches JD)" marker is NOT added; instead they are
      listed first so ATS parsers match them.
    - Nothing outside `resume` is ever added. `notes` documents what was
      changed so the student can audit every edit.
    """
    notes = []
    tailored = {
        "name": resume.get("name"),
        "contact": dict(resume.get("contact") or {}),
        "headline": resume.get("headline"),
        "education": list(resume.get("education") or []),
        "experience": [dict(x) for x in (resume.get("experience") or [])],
        "projects": [dict(p) for p in (resume.get("projects") or [])],
        "skills": list(resume.get("skills") or []),
        "interests": list(resume.get("interests") or []),
        "awards": list(resume.get("awards") or []),
    }

    if opportunity and not job_text:
        job_text = " ".join(filter(None, [
            opportunity.get("title"),
            opportunity.get("description"),
            " ".join(str(x) for x in (opportunity.get("preferred_skills") or [])),
            " ".join(str(x) for x in (opportunity.get("requirements") or [])),
        ]))

    if not job_text:
        return tailored, ["no job description provided — resume unchanged"]

    matched = _skill_overlap(tailored["skills"], job_text)
    if matched:
        others = [s for s in tailored["skills"] if s not in matched]
        tailored["skills"] = matched + others
        notes.append(
            f"reordered skills: put {len(matched)} skills matching the job "
            f"description first ({', '.join(matched[:5])}"
            f"{'…' if len(matched) > 5 else ''})"
        )
    else:
        notes.append("no listed skills matched the job description — skills unchanged")

    headline = (resume.get("headline") or "").lower()
    role = opportunity.get("title") if opportunity else None
    if role and _normalize(role) and _normalize(role) not in _normalize(headline):
        notes.append("kept headline unchanged (never rewrites your identity lines)")
    return tailored, notes


def render_text(resume):
    """ATS-friendly plain text (no markdown, no tables)."""
    lines = []
    name = resume.get("name") or "Student"
    lines.append(name)
    contact = resume.get("contact") or {}
    contact_line = " · ".join(str(v) for v in contact.values() if v)
    if contact_line:
        lines.append(contact_line)
    if resume.get("headline"):
        lines.append(resume["headline"])
    lines.append("")

    def section(title, rows):
        if not rows:
            return
        lines.append(title.upper())
        lines.append("")
        for row in rows:
            lines.append(_row_to_text(row))
            lines.append("")
        lines.append("")

    section("Education", resume.get("education") or [])
    section("Experience", resume.get("experience") or [])
    section("Projects", resume.get("projects") or [])

    skills = resume.get("skills") or []
    if skills:
        lines.append("SKILLS")
        lines.append("")
        lines.append(", ".join(skills))
        lines.append("")

    interests = resume.get("interests") or []
    if interests:
        lines.append("INTERESTS")
        lines.append("")
        lines.append(", ".join(interests))
        lines.append("")

    section("Awards", resume.get("awards") or [])
    return "\n".join(lines).rstrip() + "\n"


def _row_to_text(row):
    parts = []
    for key in ("role", "title", "company", "institution", "organization"):
        if row.get(key):
            parts.append(str(row[key]))
    for key in ("start", "end", "year", "date"):
        if row.get(key):
            parts.append(str(row[key]))
    for key in ("description", "details"):
        if row.get(key):
            parts.append(str(row[key]))
    return " — ".join(parts)


def render_pdf(resume, path=None):
    """Render the resume to a PDF via reportlab.

    `path` may be a filename (str) or a writeable file-like object
    (e.g. io.BytesIO). Returns the target as passed in.
    """
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.styles import ParagraphStyle
    from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer
    from reportlab.lib.enums import TA_LEFT

    text = render_text(resume)
    title = ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=15, leading=19, spaceAfter=6)
    body = ParagraphStyle("body", fontName="Helvetica", fontSize=9.5, leading=13,
                          alignment=TA_LEFT, splitLongWords=1)
    heading = ParagraphStyle("heading", fontName="Helvetica-Bold", fontSize=11,
                             leading=14, spaceBefore=10, spaceAfter=4)

    doc = SimpleDocTemplate(path or f"aawara_resume_{date.today().isoformat()}.pdf",
                            pagesize=A4,
                            leftMargin=18 * mm, rightMargin=18 * mm,
                            topMargin=16 * mm, bottomMargin=16 * mm)
    story = []
    blocks = text.split("\n\n")
    for i, block in enumerate(blocks):
        block = block.strip()
        if not block:
            continue
        is_section_head = block.isupper() and len(block) < 40
        if i == 0:
            story.append(Paragraph(block.splitlines()[0], title))
        elif is_section_head:
            story.append(Paragraph(block, heading))
        else:
            story.append(Paragraph(block.replace("\n", "<br/>"), body))
            story.append(Spacer(1, 3))
    doc.build(story)
    return doc.filename