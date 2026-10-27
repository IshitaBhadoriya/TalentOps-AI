import sqlite3

import pytest

from app import db, service
from app.models import normalize_email

A = "Asha One\nasha@example.com\n\nSkills\nPython, SQL\n"


def test_persistence_across_connections(resume_text):
    r = service.ingest_resume_text(resume_text, "a.txt")
    assert not r["duplicate"]
    with db.session() as conn:  # brand-new connection
        row = conn.execute("SELECT * FROM candidates WHERE id=?", (r["candidate_id"],)).fetchone()
    assert row["email_normalized"] == "jane.tester@example.com"


def test_duplicate_email_detected_and_not_overwritten():
    first = service.ingest_resume_text(A, "a.txt")
    second = service.ingest_resume_text(A.replace("Python, SQL", "Java").replace("asha@", "ASHA@"), "b.txt")
    assert second["duplicate"] and second["candidate_id"] == first["candidate_id"]
    assert "Duplicate" in second["message"]
    with db.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM candidates").fetchone()[0] == 1
        stored = conn.execute("SELECT profile_json FROM candidates").fetchone()[0]
        events = conn.execute("SELECT COUNT(*) FROM workflow_events WHERE event_type='duplicate_detected'").fetchone()[0]
    assert "Python" in stored and "Java" not in stored  # original untouched
    assert events == 1


def test_missing_email_candidates_are_both_stored():
    t = "Skills\nPython, SQL\nProjects\nBuilt a small Python script for files\n"
    r1 = service.ingest_resume_text("Sam Alpha\n" + t, "1.txt")
    r2 = service.ingest_resume_text("Tom Beta\n" + t, "2.txt")
    assert not r1["duplicate"] and not r2["duplicate"]
    assert r1["candidate_id"] != r2["candidate_id"]


def test_same_name_is_warned_not_merged():
    service.ingest_resume_text("Sam Alpha\nsam1@example.com\nSkills\nPython\n", "1.txt")
    r2 = service.ingest_resume_text("Sam Alpha\nsam2@example.com\nSkills\nPython\n", "2.txt")
    assert not r2["duplicate"] and r2["possible_duplicates"]
    assert len(service.list_candidates()) == 2


def test_unique_index_enforced_at_database_level(resume_text):
    service.ingest_resume_text(resume_text, "a.txt")
    with pytest.raises(sqlite3.IntegrityError):
        with db.session() as conn:
            db.insert_candidate(conn, {"email": "Jane.Tester@example.com"}, "x", "x")


def test_review_status_constraint():
    with db.session() as conn:
        cid = db.insert_candidate(conn, {"name": "X"}, "text", None)
        jid = db.insert_job(conn, {"title": "Job"})
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute("INSERT INTO screenings (candidate_id, job_id, result_json, review_status, created_at, updated_at)"
                         " VALUES (?,?,?,?,?,?)", (cid, jid, "{}", "Rejected", "t", "t"))


def test_screening_history_preserved_and_status_flow(resume_text):
    cid = service.ingest_resume_text(resume_text, "a.txt")["candidate_id"]
    jid = service.create_job({"title": "Dev", "required_skills": ["Python"], "preferred_skills": []})
    s1 = service.run_screening(cid, jid)["screening_id"]
    s2 = service.run_screening(cid, jid)["screening_id"]
    service.update_review_status(s2, "Shortlisted")
    c = service.get_candidate(cid)
    assert [s["id"] for s in c["screenings"]] == [s2, s1]  # both kept
    assert c["screenings"][0]["review_status"] == "Shortlisted"
    assert c["screenings"][1]["review_status"] == "Pending Review"
    with db.session() as conn:
        m = db.compute_metrics(conn)
    assert m["shortlisted"] == 1 and m["pending_review"] == 0 and m["screenings_run"] == 2
    assert m["pct_meeting_all_required"] == 100.0
    assert normalize_email("X@y.io") == "x@y.io"
