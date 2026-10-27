import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from app import db, service
from app.workflow import PAYLOAD_FIELDS, build_payload, send_event


def serve(handler_fn):
    class H(BaseHTTPRequestHandler):
        def do_POST(self):
            handler_fn(self)

        def log_message(self, *a):
            pass

    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_port}/hook"


def test_payload_is_minimal():
    p = build_payload(5, 2, "Shortlisted", "2026-01-01T00:00:00+00:00")
    assert set(p) == set(PAYLOAD_FIELDS)
    assert p == {"candidate_id": 5, "job_id": 2, "status": "Shortlisted", "timestamp": "2026-01-01T00:00:00+00:00"}


def test_disabled_when_no_url():
    assert send_event(build_payload(1, 1, "Pending Review"), url="") == "disabled"


def test_unreachable_n8n_does_not_raise():
    assert send_event(build_payload(1, 1, "Pending Review"), url="http://127.0.0.1:9/none", timeout=1).startswith("failed")


def test_delivered_and_http_error_and_timeout():
    srv, url = serve(lambda h: (h.send_response(200), h.end_headers()))
    assert send_event(build_payload(1, 1, "Pending Review"), url=url) == "delivered"
    srv.shutdown()

    srv, url = serve(lambda h: (h.send_response(500), h.end_headers()))
    assert send_event(build_payload(1, 1, "Pending Review"), url=url) == "failed: HTTP 500"
    srv.shutdown()

    def slow(h):
        time.sleep(1.5)
        h.send_response(200)
        h.end_headers()

    srv, url = serve(slow)
    assert send_event(build_payload(1, 1, "Pending Review"), url=url, timeout=0.2) == "failed: timeout"
    srv.shutdown()


def test_screening_survives_unavailable_n8n(monkeypatch, resume_text):
    monkeypatch.setenv("N8N_WEBHOOK_URL", "http://127.0.0.1:9/none")
    cid = service.ingest_resume_text(resume_text, "a.txt")["candidate_id"]
    jid = service.create_job({"title": "Dev", "required_skills": ["Python"], "preferred_skills": []})
    out = service.run_screening(cid, jid)
    assert out["screening_id"]
    with db.session() as conn:
        assert conn.execute("SELECT COUNT(*) FROM screenings").fetchone()[0] == 1
        ev = conn.execute("SELECT delivery_status FROM workflow_events WHERE event_type='screening_completed'").fetchone()
    assert ev["delivery_status"].startswith("failed")
