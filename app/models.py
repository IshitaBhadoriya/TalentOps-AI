"""Pydantic models for structured, validated candidate/job data."""
from __future__ import annotations

import re
from typing import Literal, Optional

from pydantic import BaseModel, Field, field_validator

EMAIL_RE = re.compile(r"^[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}$")


def normalize_email(email: Optional[str]) -> Optional[str]:
    """Lower-case and trim. Returns None for empty/invalid input (never raises)."""
    if not email:
        return None
    cleaned = email.strip().lower().strip(".,;:<>()[]\"'")
    return cleaned if EMAIL_RE.match(cleaned) else None


class CandidateProfile(BaseModel):
    name: Optional[str] = None
    name_confidence: Literal["none", "uncertain", "high"] = "none"
    email: Optional[str] = None
    phone: Optional[str] = None
    skills: list[str] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    experience: list[str] = Field(default_factory=list)
    projects: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    declared_years_experience: Optional[float] = None  # as written in the resume; uncertain
    excerpts: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)

    @field_validator("email")
    @classmethod
    def _check_email(cls, v: Optional[str]) -> Optional[str]:
        if v is None:
            return None
        n = normalize_email(v)
        if n is None:
            raise ValueError("invalid email address")
        return n


class JobCreate(BaseModel):
    title: str = Field(min_length=2, max_length=200)
    description: str = Field(default="", max_length=20000)
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    min_experience_years: Optional[float] = Field(default=None, ge=0, le=60)

    @field_validator("required_skills", "preferred_skills")
    @classmethod
    def _clean(cls, v: list[str]) -> list[str]:
        seen, out = set(), []
        for item in v:
            s = item.strip()
            if s and s.lower() not in seen:
                seen.add(s.lower())
                out.append(s)
        return out


class StatusUpdate(BaseModel):
    status: Literal["Pending Review", "Shortlisted", "Further Review Required"]


class ScreenRequest(BaseModel):
    candidate_id: int
    job_id: int
