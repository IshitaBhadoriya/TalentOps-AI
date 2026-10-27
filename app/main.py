"""FastAPI app: a thin local API for the React UI. Also serves the built UI from frontend/dist."""
from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse
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
