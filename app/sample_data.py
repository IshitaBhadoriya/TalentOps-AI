"""Fully synthetic sample data (fictional people, example.com emails). No real candidate information."""
from . import service

SAMPLE_JOB = {
    "title": "AI Intern - Recruitment Automation",
    "description": (
        "Support the team building recruitment automation tools. You will parse resumes, build semantic matching "
        "of candidates to job descriptions, expose results through REST APIs and webhooks, and automate recruiter "
        "workflows."
    ),
    "required_skills": ["Python", "SQL", "REST APIs", "Machine Learning"],
    "preferred_skills": ["NLP", "Embeddings", "n8n", "Docker"],
    "min_experience_years": None,
}

SAMPLE_RESUMES = {
    "asha_verma.txt": """Asha Verma
asha.verma@example.com | +91 98765 43210

Summary
Final-year student with hands-on Python and machine learning project experience.

Skills
Python, SQL, scikit-learn, Pandas, FastAPI, Git, Docker

Education
B.Tech Computer Science, Example Institute of Technology, CGPA 8.4

Projects
Resume classifier: built a text classification pipeline in Python using scikit-learn and TF-IDF features
Built REST APIs with FastAPI for serving model predictions and wrote unit tests with pytest
Sentiment analysis of product reviews using NLP techniques and sentence embeddings

Certifications
Machine Learning Specialization (online course)
""",
    "rohan_mehta.txt": """Rohan Mehta
rohan.mehta@example.com
+91 91234 56789

Professional Summary
Backend developer with 2 years of experience in Java and databases.

Skills
Java, MySQL, Spring Boot, Linux, Git

Experience
Software Engineer Intern - built internal tools in Java and wrote complex SQL queries for reporting
Maintained REST endpoints for an inventory service

Education
B.E. Information Technology, Sample College of Engineering
""",
    "priya_nair.txt": """Priya Nair
priya.nair@example.com

Skills
Python, Pandas, NumPy, Excel, Power BI, SQL

Experience
Data Analyst Intern - automated weekly reports with Python scripts and workflow automation using n8n
Trained a regression model to forecast monthly demand (machine learning)

Projects
Candidate funnel dashboard using Python and SQL; exposed metrics through a small REST API

Certifications
Docker Essentials
""",
    "arjun_singh_noemail.txt": """Arjun Singh

Skills
Python, HTML, CSS

Projects
Portfolio website and a small Python script that renames files

Education
Diploma in Computer Applications
""",
    # Same email as Asha on purpose: demonstrates duplicate detection (should NOT create a second record).
    "asha_verma_resubmission.txt": """Asha Verma
ASHA.VERMA@EXAMPLE.COM

Skills
Python, SQL

Projects
Updated resume re-submitted through a second channel
""",
}


def load_demo() -> dict:
    created, duplicates = [], []
    job_id = service.create_job(SAMPLE_JOB)
    for fname, text in SAMPLE_RESUMES.items():
        res = service.ingest_resume_text(text, fname, synthetic=True, file_type="text")
        (duplicates if res["duplicate"] else created).append(res["candidate_id"])
        if not res["duplicate"]:
            service.run_screening(res["candidate_id"], job_id)
    return {"job_id": job_id, "candidates_created": created, "duplicates_detected": len(duplicates)}
