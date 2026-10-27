"""Rule-based resume parsing (regex + section heuristics).

Design notes
- Nothing is invented: a field that cannot be found stays empty and produces a warning.
- Name detection is a heuristic and is always labelled 'uncertain'.
- `parse_resume` is the single entry point; a local-LLM parser could later implement the same
  signature (text -> CandidateProfile) and be swapped in without touching the rest of the app.
"""
from __future__ import annotations

import re
from typing import Optional

from .models import CandidateProfile, normalize_email

EMAIL_FIND = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
PHONE_FIND = re.compile(r"\+?\d[\d\s().\-]{8,16}\d")
YEARS_FIND = re.compile(
    r"(\d{1,2}(?:\.\d)?)\+?\s*(?:years?|yrs?)(?:\s+of)?\s+(?:[\w/\-]+\s+){0,3}?experience"
    r"|experience\s+(?:of\s+)?(\d{1,2}(?:\.\d)?)\+?\s*(?:years?|yrs?)",
    re.IGNORECASE,
)

SECTION_ALIASES = {
    "skills": {"skills", "technical skills", "key skills", "core competencies", "skills & tools", "tools"},
    "education": {"education", "academic background", "qualifications", "academics"},
    "experience": {"experience", "work experience", "professional experience", "employment",
                   "employment history", "internships", "work history"},
    "projects": {"projects", "academic projects", "personal projects", "key projects"},
    "certifications": {"certifications", "certificates", "licenses", "licenses & certifications",
                       "courses", "training"},
    "summary": {"summary", "profile", "professional summary", "objective", "about me", "career objective"},
}
HEADING_LOOKUP = {alias: sec for sec, aliases in SECTION_ALIASES.items() for alias in aliases}

# canonical skill -> aliases. Used for lexicon-based skill detection AND requirement matching.
SKILL_LEXICON: dict[str, list[str]] = {
    "Python": [], "Java": [], "JavaScript": ["js"], "TypeScript": [], "C++": [], "C#": [], "Go": ["golang"],
    "SQL": [], "PostgreSQL": ["postgres"], "MySQL": [], "SQLite": [], "MongoDB": [],
    "React": ["react.js", "reactjs"], "Node.js": ["node", "nodejs"], "FastAPI": [], "Flask": [], "Django": [],
    "REST APIs": ["rest api", "restful api", "rest"], "Webhooks": ["webhook"], "Docker": [], "Git": [],
    "Linux": [], "AWS": [], "Azure": [], "Kubernetes": [],
    "Machine Learning": ["ml"], "Deep Learning": [], "NLP": ["natural language processing"],
    "scikit-learn": ["sklearn"], "NumPy": [], "Pandas": [], "PyTorch": [], "TensorFlow": [],
    "Sentence Transformers": ["sentence-transformers"], "Embeddings": ["embedding"],
    "Data Analysis": ["data analytics"], "Excel": [], "Power BI": [], "Tableau": [],
    "n8n": [], "Automation": ["workflow automation"], "Recruitment": ["talent acquisition", "recruiting"],
    "Applicant Tracking System": ["ats"], "Resume Screening": ["cv screening"],
    "Communication": [], "Stakeholder Management": [], "Testing": ["pytest", "unit testing"],
}


def _term_regex(term: str) -> re.Pattern:
    return re.compile(r"(?<![A-Za-z0-9+#])" + re.escape(term) + r"(?![A-Za-z0-9+#])", re.IGNORECASE)


def aliases_for(term: str) -> list[str]:
    """Return the term plus any known aliases (case-insensitive lookup)."""
    low = term.strip().lower()
    for canon, aliases in SKILL_LEXICON.items():
        group = [canon, *aliases]
        if low in {g.lower() for g in group}:
            return group
    return [term.strip()]


def term_in_text(term: str, text: str) -> bool:
    return any(_term_regex(a).search(text) for a in aliases_for(term))


def _clean_line(line: str) -> str:
    return re.sub(r"^[\s\-\u2022\u25cf\u25aa*·>]+", "", line).strip()


def split_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current: Optional[str] = None
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        key = line.lower().rstrip(":").strip()
        if len(line) <= 40 and key in HEADING_LOOKUP:
            current = HEADING_LOOKUP[key]
            sections.setdefault(current, [])
            continue
        if current:
            cleaned = _clean_line(line)
            if cleaned:
                sections[current].append(cleaned[:300])
    return sections


def extract_email(text: str) -> Optional[str]:
    for m in EMAIL_FIND.findall(text):
        n = normalize_email(m)
        if n:
            return n
    return None


def extract_phone(text: str) -> Optional[str]:
    for m in PHONE_FIND.findall(text):
        digits = re.sub(r"\D", "", m)
        if 10 <= len(digits) <= 13:
            return m.strip()
    return None


def extract_name(text: str) -> tuple[Optional[str], str]:
    """Heuristic: first short alphabetic line near the top that is not a heading."""
    for line in [l.strip() for l in text.splitlines() if l.strip()][:5]:
        if "@" in line or re.search(r"\d", line) or line.lower().rstrip(":") in HEADING_LOOKUP:
            continue
        words = line.split()
        if 2 <= len(words) <= 4 and all(re.fullmatch(r"[A-Za-z.'\-]+", w) for w in words):
            return line.title() if line.isupper() else line, "uncertain"
    return None, "none"


def extract_skills(text: str, sections: dict[str, list[str]]) -> list[str]:
    found: dict[str, str] = {}
    for line in sections.get("skills", []):
        line = re.sub(r"^[A-Za-z /&]{2,30}:\s*", "", line)  # drop "Languages:" style labels
        for tok in re.split(r"[,;|/\u2022]", line):
            tok = tok.strip(" .")
            if 1 < len(tok) <= 40:
                found.setdefault(tok.lower(), tok)
    for canon in SKILL_LEXICON:
        if term_in_text(canon, text):
            found.setdefault(canon.lower(), canon)
    return list(found.values())


def extract_years(text: str) -> Optional[float]:
    for m in YEARS_FIND.finditer(text):
        val = m.group(1) or m.group(2)
        if val:
            return float(val)
    return None


def parse_resume(text: str) -> CandidateProfile:
    sections = split_sections(text)
    name, conf = extract_name(text)
    email, phone = extract_email(text), extract_phone(text)
    skills = extract_skills(text, sections)
    years = extract_years(text)

    warnings: list[str] = []
    if not name:
        warnings.append("Candidate name could not be detected.")
    elif conf == "uncertain":
        warnings.append("Candidate name is a heuristic guess (uncertain) - please verify.")
    if not email:
        warnings.append("No email found: duplicate detection by email is not possible for this candidate.")
    if not phone:
        warnings.append("No phone number found.")
    for sec, label in [("skills", "Skills"), ("education", "Education"), ("experience", "Work experience"),
                       ("projects", "Projects"), ("certifications", "Certifications")]:
        if not sections.get(sec):
            warnings.append(f"No '{label}' section detected (information may be missing or formatted unusually).")
    if years is not None:
        warnings.append("Years of experience is self-declared text in the resume and is not verified.")

    return CandidateProfile(
        name=name, name_confidence=conf, email=email, phone=phone, skills=skills,
        education=sections.get("education", [])[:15], experience=sections.get("experience", [])[:20],
        projects=sections.get("projects", [])[:15], certifications=sections.get("certifications", [])[:15],
        declared_years_experience=years, excerpts=sections.get("summary", [])[:3], warnings=warnings,
    )
