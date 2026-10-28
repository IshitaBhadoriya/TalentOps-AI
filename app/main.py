"""FastAPI app: a thin local API for the React UI. Also serves the built UI from frontend/dist."""
from __future__ import annotations

import csv
import hmac
import io
from typing import Optional

from fastapi import FastAPI, File, Form, Header, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles

from . import db, service
from .config import ROOT, settings
from .extraction import ExtractionError
from .matching import get_embedder
from .models import JobCreate, ScreenRequest, StatusUpdate
from .sample_data import load_demo

app = FastAPI(title="TalentOps AI", version="0.1.0")


@app.on_event("startup")
def _startup() -> None:
    db.init_db()


@app.get("/api/health")
def health():
    return {"status": "ok"}


@app.get("/api/config")
def config():
    return {
        "embedding_backend_setting": settings.embedding_backend,
        "n8n_webhook_configured": bool(settings.webhook_url),
        "max_upload_mb": settings.max_upload_bytes / 1024 / 1024,
    }


@app.get("/api/backend-info")
def backend_info():
    """Loads the similarity backend (first call may take a few seconds) and reports which one is active."""
    e = get_embedder()
    return {"name": e.name, "kind": e.kind}


@app.get("/api/metrics")
def metrics():
    with db.session() as conn:
        return db.compute_metrics(conn)


@app.post("/api/candidates/upload")
async def upload(file: UploadFile = File(...)):
    data = await file.read(settings.max_upload_bytes + 1)  # read at most limit+1 bytes
    try:
        return service.ingest_upload(file.filename or "", data)
    except ExtractionError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@app.get("/api/candidates")
def candidates(q: str = Query("", max_length=100)):
    return service.list_candidates(q)


@app.get("/api/candidates/{candidate_id}")
def candidate(candidate_id: int):
    try:
        return service.get_candidate(candidate_id)
    except service.NotFound as exc:
        raise HTTPException(404, str(exc))


@app.get("/api/jobs")
def jobs():
    return service.list_jobs()


@app.post("/api/jobs")
def create_job(job: JobCreate):
    return {"job_id": service.create_job(job.model_dump())}


@app.post("/api/screenings")
def screen(req: ScreenRequest):
    try:
        return service.run_screening(req.candidate_id, req.job_id)
    except service.NotFound as exc:
        raise HTTPException(404, str(exc))


@app.patch("/api/screenings/{screening_id}/status")
def set_status(screening_id: int, body: StatusUpdate):
    try:
        return service.update_review_status(screening_id, body.status)
    except service.NotFound as exc:
        raise HTTPException(404, str(exc))


@app.get("/api/jobs/{job_id}/ranking")
def job_ranking(job_id: int):
    try:
        return service.ranking(job_id)
    except service.NotFound as exc:
        raise HTTPException(404, str(exc))


@app.post("/api/jobs/{job_id}/screen-all")
def job_screen_all(job_id: int):
    try:
        return service.screen_all(job_id)
    except service.NotFound as exc:
        raise HTTPException(404, str(exc))


@app.get("/api/jobs/{job_id}/ranking.csv")
def job_ranking_csv(job_id: int):
    try:
        data = service.ranking(job_id)
    except service.NotFound as exc:
        raise HTTPException(404, str(exc))
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["rank", "candidate_id", "name", "score", "matched", "partial", "insufficient_evidence",
                "meets_all_required", "review_status", "missing_required"])
    for i in data["items"]:
        c = i["counts"]
        w.writerow([i["rank"], i["candidate_id"], i["name"] or "", i["score"], c["matched"], c["partial"],
                    c["insufficient"], i["meets_all_required"], i["review_status"], "; ".join(i["missing_required"])])
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="ranking_job_{job_id}.csv"'})


@app.post("/api/inbound/resume")
async def inbound_resume(file: UploadFile = File(...), job_id: Optional[int] = Form(None),
                         x_api_key: Optional[str] = Header(None)):
    """Intake endpoint for automation (n8n): store + parse a resume and optionally screen it against a job.

    Protected by a shared secret (TALENTOPS_INBOUND_TOKEN). Returns only IDs, counts and status - no resume text.
    """
    token = settings.inbound_token
    if not token:
        raise HTTPException(503, "Inbound endpoint is disabled. Set TALENTOPS_INBOUND_TOKEN in .env and restart.")
    if not x_api_key or not hmac.compare_digest(x_api_key.encode(), token.encode()):
        raise HTTPException(401, "Invalid or missing X-API-Key header.")
    data = await file.read(settings.max_upload_bytes + 1)
    try:
        ing = service.ingest_upload(file.filename or "", data)
    except ExtractionError as exc:
        raise HTTPException(422, str(exc))
    out = {"candidate_id": ing["candidate_id"], "duplicate": ing["duplicate"], "job_id": job_id,
           "screening_id": None, "score": None, "counts": None, "meets_all_required": None, "review_status": None}
    if job_id is not None:
        try:
            s = service.run_screening(ing["candidate_id"], job_id)
        except service.NotFound:
            raise HTTPException(404, f"Resume stored as candidate #{ing['candidate_id']}, but job #{job_id} was not found.")
        r = s["result"]
        out.update(screening_id=s["screening_id"], score=r["score"], counts=r["counts"],
                   meets_all_required=r["meets_all_required"], review_status="Pending Review")
    return out


@app.get("/api/events")
def events():
    with db.session() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM workflow_events ORDER BY id DESC LIMIT 100")]


@app.post("/api/demo/load")
def demo():
    return load_demo()


_dist = ROOT / "frontend" / "dist"
if _dist.exists():
    app.mount("/assets", StaticFiles(directory=_dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        target = (_dist / path).resolve()
        inside = _dist.resolve() in target.parents
        return FileResponse(target if path and inside and target.is_file() else _dist / "index.html")
