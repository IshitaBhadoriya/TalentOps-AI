from fastapi.testclient import TestClient

from app.main import app


def client():
    return TestClient(app)


def test_upload_screen_review_flow(resume_pdf, resume_docx):
    with client() as c:
        r = c.post("/api/candidates/upload", files={"file": ("cv.pdf", resume_pdf, "application/pdf")})
        assert r.status_code == 200 and not r.json()["duplicate"]
        cid = r.json()["candidate_id"]

        dup = c.post("/api/candidates/upload", files={"file": ("cv2.docx", resume_docx, "application/octet-stream")})
        assert dup.json()["duplicate"] and dup.json()["candidate_id"] == cid

        jid = c.post("/api/jobs", json={"title": "Dev", "required_skills": ["Python", "Kubernetes"]}).json()["job_id"]
        s = c.post("/api/screenings", json={"candidate_id": cid, "job_id": jid}).json()
        statuses = {x["requirement"]: x["status"] for x in s["result"]["requirements"]}
        assert statuses == {"Python": "matched", "Kubernetes": "insufficient"}

        assert c.patch(f"/api/screenings/{s['screening_id']}/status", json={"status": "Shortlisted"}).status_code == 200
        assert c.patch(f"/api/screenings/{s['screening_id']}/status", json={"status": "Rejected"}).status_code == 422
        m = c.get("/api/metrics").json()
        assert m["candidates_processed"] == 1 and m["shortlisted"] == 1
        assert c.get("/api/candidates", params={"q": "python"}).json()[0]["id"] == cid
        assert c.get("/api/candidates", params={"q": "zzz"}).json() == []


def test_invalid_upload_returns_helpful_422():
    with client() as c:
        r = c.post("/api/candidates/upload", files={"file": ("cv.txt", b"hello", "text/plain")})
        assert r.status_code == 422 and "Only PDF and DOCX" in r.json()["detail"]


def test_demo_load_is_synthetic_and_detects_duplicate():
    with client() as c:
        d = c.post("/api/demo/load").json()
        assert len(d["candidates_created"]) == 4 and d["duplicates_detected"] == 1
        assert all(x["is_synthetic"] for x in c.get("/api/candidates").json())
