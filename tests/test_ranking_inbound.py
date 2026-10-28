from fastapi.testclient import TestClient

from app import service
from app.main import app

STRONG = "Ann Strong\nann@example.com\nSkills\nPython, SQL\nProjects\nBuilt REST APIs in Python with SQL databases\n"
WEAK = "Bob Weak\nbob@example.com\nSkills\nPython\nProjects\nWrote a Python script to rename files\n"
NONE = "Cy None\ncy@example.com\nProjects\nOrganised a campus event for students\n"


def setup_job():
    jid = service.create_job({"title": "Dev", "required_skills": ["Python", "SQL", "REST APIs"], "preferred_skills": []})
    for t in (WEAK, NONE, STRONG):
        service.ingest_resume_text(t, "x.txt")
    return jid


def test_screen_all_and_ranking_order_and_ties():
    jid = setup_job()
    with TestClient(app) as c:
        assert c.post(f"/api/jobs/{jid}/screen-all").json()["newly_screened"] == 3
        assert c.post(f"/api/jobs/{jid}/screen-all").json()["newly_screened"] == 0  # idempotent, history untouched
        r = c.get(f"/api/jobs/{jid}/ranking").json()
    names = [i["name"] for i in r["items"]]
    assert names == ["Ann Strong", "Bob Weak", "Cy None"]
    assert [i["rank"] for i in r["items"]] == [1, 2, 3]
    assert r["items"][0]["meets_all_required"] and r["items"][2]["missing_required"] == ["Python", "SQL", "REST APIs"]
    assert "not a hiring decision" in r["note"]


def test_ranking_ties_share_rank():
    jid = service.create_job({"title": "Dev", "required_skills": ["Python"], "preferred_skills": []})
    service.ingest_resume_text("A B\na@example.com\nSkills\nPython\n", "1")
    service.ingest_resume_text("C D\nc@example.com\nSkills\nPython\n", "2")
    service.screen_all(jid)
    assert [i["rank"] for i in service.ranking(jid)["items"]] == [1, 1]


def test_ranking_csv_and_404():
    jid = setup_job()
    service.screen_all(jid)
    with TestClient(app) as c:
        csv_text = c.get(f"/api/jobs/{jid}/ranking.csv").text
        assert csv_text.splitlines()[0].startswith("rank,candidate_id,name,score")
        assert "Ann Strong" in csv_text
        assert c.get("/api/jobs/999/ranking").status_code == 404


def test_inbound_disabled_without_token(resume_pdf):
    with TestClient(app) as c:
        r = c.post("/api/inbound/resume", files={"file": ("cv.pdf", resume_pdf)})
        assert r.status_code == 503


def test_inbound_auth_and_flow(monkeypatch, resume_pdf):
    monkeypatch.setenv("TALENTOPS_INBOUND_TOKEN", "secret-token")
    jid = service.create_job({"title": "Dev", "required_skills": ["Python", "Kubernetes"], "preferred_skills": []})
    with TestClient(app) as c:
        f = {"file": ("cv.pdf", resume_pdf, "application/pdf")}
        assert c.post("/api/inbound/resume", files=f).status_code == 401
        assert c.post("/api/inbound/resume", files=f, headers={"X-API-Key": "wrong"}).status_code == 401
        ok = c.post("/api/inbound/resume", files=f, data={"job_id": str(jid)}, headers={"X-API-Key": "secret-token"})
        body = ok.json()
        assert ok.status_code == 200 and body["screening_id"] and body["review_status"] == "Pending Review"
        assert body["counts"] == {"matched": 1, "partial": 0, "insufficient": 1}
        assert "jane" not in str(body).lower()  # no personal data returned to the automation tool
        dup = c.post("/api/inbound/resume", files=f, headers={"X-API-Key": "secret-token"}).json()
        assert dup["duplicate"] is True and dup["screening_id"] is None
        bad = c.post("/api/inbound/resume", files={"file": ("x.txt", b"hello")}, headers={"X-API-Key": "secret-token"})
        assert bad.status_code == 422
        nojob = c.post("/api/inbound/resume", files=f, data={"job_id": "999"}, headers={"X-API-Key": "secret-token"})
        assert nojob.status_code == 404
