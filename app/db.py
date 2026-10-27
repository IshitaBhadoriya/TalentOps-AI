"""SQLite persistence. Plain sqlite3 (standard library), foreign keys ON, CHECK constraints for statuses."""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .config import REVIEW_STATUSES, settings
from .models import normalize_email

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    email TEXT,
    email_normalized TEXT,
    phone TEXT,
    profile_json TEXT NOT NULL,
    resume_text TEXT NOT NULL,
    source_filename TEXT,
    is_synthetic INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
-- Unique only when an email exists, so candidates without email are still storable.
CREATE UNIQUE INDEX IF NOT EXISTS ux_candidates_email
    ON candidates(email_normalized) WHERE email_normalized IS NOT NULL;

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    required_skills_json TEXT NOT NULL DEFAULT '[]',
    preferred_skills_json TEXT NOT NULL DEFAULT '[]',
    min_experience_years REAL,
    created_at TEXT NOT NULL
);

-- One row per screening run. History is append-only: re-screening adds a new row.
CREATE TABLE IF NOT EXISTS screenings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    candidate_id INTEGER NOT NULL REFERENCES candidates(id) ON DELETE CASCADE,
    job_id INTEGER NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    score REAL,
    meets_all_required INTEGER NOT NULL DEFAULT 0,
    result_json TEXT NOT NULL,
    review_status TEXT NOT NULL DEFAULT 'Pending Review'
        CHECK (review_status IN ({",".join("'" + s + "'" for s in REVIEW_STATUSES)})),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS workflow_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type TEXT NOT NULL,
    candidate_id INTEGER,
    job_id INTEGER,
    status TEXT,
    detail TEXT,
    delivery_status TEXT NOT NULL DEFAULT 'not_applicable',
    created_at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def connect() -> sqlite3.Connection:
    path = Path(settings.db_path)
    if str(path) != ":memory:":
        path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def session():
    conn = connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db() -> None:
    with session() as c:
        c.executescript(SCHEMA)


# ---------- candidates ----------
def find_by_email(conn, email: Optional[str]):
    n = normalize_email(email)
    if not n:
        return None
    return conn.execute("SELECT * FROM candidates WHERE email_normalized = ?", (n,)).fetchone()


def find_possible_duplicates(conn, name: Optional[str], phone: Optional[str]) -> list[dict]:
    """Soft signals only (same phone digits / same name). These are WARNINGS; never auto-merged."""
    out: dict[int, dict] = {}
    digits = "".join(ch for ch in (phone or "") if ch.isdigit())
    if len(digits) >= 10:
        for r in conn.execute("SELECT id, name, phone FROM candidates WHERE phone IS NOT NULL"):
            if "".join(ch for ch in r["phone"] if ch.isdigit())[-10:] == digits[-10:]:
                out[r["id"]] = {"id": r["id"], "name": r["name"], "reason": "same phone number"}
    if name:
        for r in conn.execute("SELECT id, name FROM candidates WHERE lower(name) = lower(?)", (name,)):
            out.setdefault(r["id"], {"id": r["id"], "name": r["name"], "reason": "same name (not a reliable match)"})
    return list(out.values())


def insert_candidate(conn, profile: dict, resume_text: str, filename: Optional[str], synthetic: bool = False) -> int:
    en = normalize_email(profile.get("email"))
    cur = conn.execute(
        "INSERT INTO candidates (name, email, email_normalized, phone, profile_json, resume_text, "
        "source_filename, is_synthetic, created_at) VALUES (?,?,?,?,?,?,?,?,?)",
        (profile.get("name"), profile.get("email"), en, profile.get("phone"), json.dumps(profile),
         resume_text, filename, int(synthetic), now()),
    )
    return cur.lastrowid


def candidate_row_to_dict(r) -> dict:
    d = dict(r)
    d["profile"] = json.loads(d.pop("profile_json"))
    return d


# ---------- jobs ----------
def insert_job(conn, job: dict) -> int:
    cur = conn.execute(
        "INSERT INTO jobs (title, description, required_skills_json, preferred_skills_json, "
        "min_experience_years, created_at) VALUES (?,?,?,?,?,?)",
        (job["title"], job.get("description", ""), json.dumps(job.get("required_skills", [])),
         json.dumps(job.get("preferred_skills", [])), job.get("min_experience_years"), now()),
    )
    return cur.lastrowid


def job_row_to_dict(r) -> dict:
    d = dict(r)
    d["required_skills"] = json.loads(d.pop("required_skills_json"))
    d["preferred_skills"] = json.loads(d.pop("preferred_skills_json"))
    return d


# ---------- events ----------
def log_event(conn, event_type: str, candidate_id=None, job_id=None, status=None, detail=None,
              delivery_status: str = "not_applicable") -> int:
    cur = conn.execute(
        "INSERT INTO workflow_events (event_type, candidate_id, job_id, status, detail, delivery_status, created_at) "
        "VALUES (?,?,?,?,?,?,?)",
        (event_type, candidate_id, job_id, status, detail, delivery_status, now()),
    )
    return cur.lastrowid


# ---------- metrics ----------
def pipeline_stage(latest_status: Optional[str]) -> str:
    """Stage definitions (explicit):
    Ingested = candidate stored, never screened; Screened = latest screening is Pending Review;
    Shortlisted / Further Review Required = latest screening's review status."""
    return "Ingested" if latest_status is None else ("Screened" if latest_status == "Pending Review" else latest_status)


STAGES = ["Ingested", "Screened", "Shortlisted", "Further Review Required"]


def latest_screening_per_candidate(conn) -> dict[int, sqlite3.Row]:
    rows = conn.execute(
        "SELECT s.* FROM screenings s JOIN (SELECT candidate_id, MAX(id) mid FROM screenings GROUP BY candidate_id) m "
        "ON s.id = m.mid"
    ).fetchall()
    return {r["candidate_id"]: r for r in rows}


def compute_metrics(conn) -> dict:
    total = conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0]
    latest = latest_screening_per_candidate(conn)
    by_status = {s: 0 for s in REVIEW_STATUSES}
    for r in latest.values():
        by_status[r["review_status"]] += 1
    stage_counts = {s: 0 for s in STAGES}
    cand_ids = [r["id"] for r in conn.execute("SELECT id FROM candidates")]
    for cid in cand_ids:
        stage_counts[pipeline_stage(latest[cid]["review_status"] if cid in latest else None)] += 1
    n_screenings = conn.execute("SELECT COUNT(*) FROM screenings").fetchone()[0]
    n_meet = conn.execute("SELECT COUNT(*) FROM screenings WHERE meets_all_required = 1").fetchone()[0]
    recent = [dict(r) for r in conn.execute("SELECT * FROM workflow_events ORDER BY id DESC LIMIT 10")]
    return {
        "candidates_processed": total,
        "screenings_run": n_screenings,
        "pending_review": by_status["Pending Review"],
        "shortlisted": by_status["Shortlisted"],
        "further_review_required": by_status["Further Review Required"],
        "pct_meeting_all_required": round(100 * n_meet / n_screenings, 1) if n_screenings else None,
        "stage_counts": stage_counts,
        "recent_events": recent,
        "definitions": {
            "candidates_processed": "Distinct candidate records stored (duplicates by email are not counted twice).",
            "pending_review / shortlisted / further_review_required":
                "Candidates whose MOST RECENT screening has that review status.",
            "pct_meeting_all_required":
                "Share of all screening runs in which every required skill was 'matched' (keyword evidence). "
                "Partial or insufficient evidence does not count. Not a hiring-success measure.",
            "stage_counts": "Ingested = never screened; Screened = latest screening awaiting review; "
                            "Shortlisted / Further Review Required = latest review status.",
        },
    }
