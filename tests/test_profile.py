import pytest
from pydantic import ValidationError

from app.models import CandidateProfile, JobCreate, normalize_email
from app.parsing import parse_resume


def test_email_normalization():
    assert normalize_email("  Jane.Tester@Example.COM ") == "jane.tester@example.com"
    assert normalize_email("not-an-email") is None
    assert normalize_email(None) is None and normalize_email("") is None


def test_profile_validation_rejects_bad_email():
    with pytest.raises(ValidationError):
        CandidateProfile(email="nope")
    assert CandidateProfile(email="A@B.com").email == "a@b.com"


def test_job_validation_dedupes_skills():
    j = JobCreate(title="Engineer", required_skills=["Python", " python ", ""], preferred_skills=[])
    assert j.required_skills == ["Python"]
    with pytest.raises(ValidationError):
        JobCreate(title="x")


def test_parse_resume_fields(resume_text):
    p = parse_resume(resume_text)
    assert p.email == "jane.tester@example.com"
    assert p.phone and "90000" in p.phone
    assert {"Python", "SQL", "Docker"} <= set(p.skills)
    assert p.name == "Jane Tester" and p.name_confidence == "uncertain"
    assert p.education and p.projects


def test_parser_does_not_fabricate():
    p = parse_resume("Some random notes without structure at all, just a sentence about gardening.")
    assert p.email is None and p.phone is None and p.name is None
    assert p.experience == [] and p.education == [] and p.certifications == []
    assert any("No email" in w for w in p.warnings)
    assert any("name could not" in w for w in p.warnings)


def test_declared_years_marked_unverified():
    p = parse_resume("Alex Doe\nSummary\nEngineer with 3 years of experience in backend.")
    assert p.declared_years_experience == 3.0
    assert any("not verified" in w for w in p.warnings)
