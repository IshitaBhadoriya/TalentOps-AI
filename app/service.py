"""Application logic that ties extraction, parsing, matching, storage and workflow events together."""
from __future__ import annotations

import json
from typing import Optional

from . import db
from .config import REVIEW_STATUSES, settings
from .extraction import extract_text
from .matching import get_embedder, match_candidate
from .parsing import parse_resume
from .workflow import build_payload, send_event


class NotFound(Exception):
    pass


def ingest_resume_text(text: str, filename: Optional[str], synthetic: bool = False, file_type: str = "text") -> dict:
    """Parse + store a candidate. Never overwrites an existing record that has the same email."""
    profile = parse_resume(text).model_dump()
    with db.session() as conn:
        existing = db.find_by_email(conn, profile.get("email"))
        if existing:
            db.log_event(conn, "duplicate_detected", existing["id"], None, None,
                         f"Upload '{filename}' matched existing candidate #{existing['id']} by email; not stored again.")
            return {
                "duplicate": True, "candidate_id": existing["id"], "profile": profile, "text_preview": text[:1500],
                "message": f"Duplicate: a candidate with this email already exists (#{existing['id']}). "
                           f"The existing record was kept unchanged; you can screen it against a job.",
                "possible_duplicates": [],
            }
        possible = db.find_possible_duplicates(conn, profile.get("name"), profile.get("phone"))
        cid = db.insert_candidate(conn, profile, text, filename, synthetic)
        db.log_event(conn, "candidate_ingested", cid, None, None, f"Stored from '{filename}' ({file_type}).")
        msg = "Candidate stored."
        if possible:
            msg += " Warning: possible duplicate(s) found by phone/name - review manually, nothing was merged."
        return {"duplicate": False, "candidate_id": cid, "profile": profile, "text_preview": text[:1500],
                "message": msg, "possible_duplicates": possible}


def ingest_upload(filename: str, data: bytes) -> dict:
    result = extract_text(filename, data, settings.max_upload_bytes)  # raises ExtractionError
    return ingest_resume_text(result.text, filename, False, result.file_type)


def create_job(job: dict) -> int:
    with db.session() as conn:
        jid = db.insert_job(conn, job)
        db.log_event(conn, "job_created", None, jid, None, job["title"])
        return jid


def run_screening(candidate_id: int, job_id: int) -> dict:
    # Compute outside the DB session (embedding can be slow on first call).
    with db.session() as conn:
        cand = conn.execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone()
        job = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not cand or not job:
            raise NotFound("Candidate or job not found.")
        cand, job = db.candidate_row_to_dict(cand), db.job_row_to_dict(job)
    result = match_candidate(cand["resume_text"], cand["profile"].get("declared_years_experience"), job,
                             get_embedder())
    with db.session() as conn:
        ts = db.now()
        cur = conn.execute(
            "INSERT INTO screenings (candidate_id, job_id, score, meets_all_required, result_json, review_status, "
            "created_at, updated_at) VALUES (?,?,?,?,?,?,?,?)",
            (candidate_id, job_id, result["score"], int(result["meets_all_required"]), json.dumps(result),
             "Pending Review", ts, ts),
        )
        sid = cur.lastrowid
        # The screening is committed with this session; webhook delivery happens afterwards and cannot undo it.
        eid = db.log_event(conn, "screening_completed", candidate_id, job_id, "Pending Review",
                           f"Screening #{sid} stored.", "pending")
    _deliver(eid, candidate_id, job_id, "Pending Review")
    return {"screening_id": sid, "result": result}


def _deliver(event_id: int, candidate_id: int, job_id: int, status: str) -> str:
    delivery = send_event(build_payload(candidate_id, job_id, status))
    with db.session() as conn:
        conn.execute("UPDATE workflow_events SET delivery_status=? WHERE id=?", (delivery, event_id))
    return delivery


def update_review_status(screening_id: int, status: str) -> dict:
    if status not in REVIEW_STATUSES:
        raise ValueError(f"Invalid status. Allowed: {REVIEW_STATUSES}")
    with db.session() as conn:
        row = conn.execute("SELECT * FROM screenings WHERE id=?", (screening_id,)).fetchone()
        if not row:
            raise NotFound("Screening not found.")
        conn.execute("UPDATE screenings SET review_status=?, updated_at=? WHERE id=?", (status, db.now(), screening_id))
        eid = db.log_event(conn, "review_status_changed", row["candidate_id"], row["job_id"], status,
                           f"Screening #{screening_id}: {row['review_status']} -> {status} (set by human reviewer).",
                           "pending")
    delivery = _deliver(eid, row["candidate_id"], row["job_id"], status)
    return {"screening_id": screening_id, "status": status, "delivery": delivery}


def list_candidates(q: str = "") -> list[dict]:
    with db.session() as conn:
        latest = db.latest_screening_per_candidate(conn)
        rows = conn.execute("SELECT * FROM candidates ORDER BY id DESC").fetchall()
        out = []
        ql = q.strip().lower()
        for r in rows:
            d = db.candidate_row_to_dict(r)
            hay = " ".join([d.get("name") or "", d.get("email") or "", " ".join(d["profile"].get("skills", []))]).lower()
            if ql and ql not in hay:
                continue
            ls = latest.get(d["id"])
            out.append({
                "id": d["id"], "name": d["name"], "email": d["email"], "phone": d["phone"],
                "skills": d["profile"].get("skills", []), "source_filename": d["source_filename"],
                "is_synthetic": bool(d["is_synthetic"]), "created_at": d["created_at"],
                "stage": db.pipeline_stage(ls["review_status"] if ls else None),
                "latest_score": ls["score"] if ls else None,
            })
        return out


def get_candidate(candidate_id: int) -> dict:
    with db.session() as conn:
        r = conn.execute("SELECT * FROM candidates WHERE id=?", (candidate_id,)).fetchone()
        if not r:
            raise NotFound("Candidate not found.")
        d = db.candidate_row_to_dict(r)
        d["text_preview"] = d.pop("resume_text")[:3000]
        hist = conn.execute(
            "SELECT s.*, j.title AS job_title FROM screenings s JOIN jobs j ON j.id = s.job_id "
            "WHERE s.candidate_id=? ORDER BY s.id DESC", (candidate_id,)).fetchall()
        d["screenings"] = []
        for h in hist:
            h = dict(h)
            h["result"] = json.loads(h.pop("result_json"))
            d["screenings"].append(h)
        d["events"] = [dict(e) for e in conn.execute(
            "SELECT * FROM workflow_events WHERE candidate_id=? ORDER BY id DESC LIMIT 30", (candidate_id,))]
        return d


def list_jobs() -> list[dict]:
    with db.session() as conn:
        return [db.job_row_to_dict(r) for r in conn.execute("SELECT * FROM jobs ORDER BY id DESC")]


def screen_all(job_id: int) -> dict:
    """Screen every candidate that has no screening for this job yet. Existing history is untouched."""
    with db.session() as conn:
        if not conn.execute("SELECT 1 FROM jobs WHERE id=?", (job_id,)).fetchone():
            raise NotFound("Job not found.")
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM candidates WHERE id NOT IN (SELECT candidate_id FROM screenings WHERE job_id=?) ORDER BY id",
            (job_id,))]
    for cid in ids:
        run_screening(cid, job_id)
    return {"job_id": job_id, "newly_screened": len(ids)}


def ranking(job_id: int) -> dict:
    """Latest screening per candidate for one job, ordered by coverage score (highest first).

    The order is a REVIEW-PRIORITY aid. Ties share a rank. It is not a hiring decision and no candidate is rejected.
    """
    with db.session() as conn:
        job = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not job:
            raise NotFound("Job not found.")
        rows = conn.execute(
            "SELECT s.id AS screening_id, s.candidate_id, s.score, s.meets_all_required, s.review_status, "
            "s.result_json, c.name, c.is_synthetic FROM screenings s "
            "JOIN (SELECT candidate_id, MAX(id) mid FROM screenings WHERE job_id=? GROUP BY candidate_id) m ON s.id=m.mid "
            "JOIN candidates c ON c.id = s.candidate_id "
            "ORDER BY (s.score IS NULL), s.score DESC, s.candidate_id", (job_id,)).fetchall()
    items = []
    for r in rows:
        res = json.loads(r["result_json"])
        items.append({
            "screening_id": r["screening_id"], "candidate_id": r["candidate_id"], "name": r["name"],
            "is_synthetic": bool(r["is_synthetic"]), "score": r["score"], "counts": res["counts"],
            "meets_all_required": bool(r["meets_all_required"]), "review_status": r["review_status"],
            "missing_required": [q["requirement"] for q in res["requirements"]
                                 if q["type"] == "required" and q["status"] == "insufficient"],
        })
    scores = [i["score"] for i in items]
    for i in items:  # competition ranking: ties share the same rank
        i["rank"] = 1 + sum(1 for sc in scores if sc is not None and i["score"] is not None and sc > i["score"]) \
            if i["score"] is not None else None
    return {
        "job": db.job_row_to_dict(job), "items": items,
        "note": "Order is a review-priority aid based on requirement coverage evidence. It is not a hiring decision; "
                "equal scores share a rank and insufficient evidence does not mean a skill is absent.",
    }
