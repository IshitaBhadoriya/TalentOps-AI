"""Optional n8n webhook integration. Failure here must never lose or block a screening record."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import requests

from .config import settings

PAYLOAD_FIELDS = ("candidate_id", "job_id", "status", "timestamp")


def build_payload(candidate_id: int, job_id: int, status: str, timestamp: Optional[str] = None) -> dict:
    """Minimum necessary data only: no name, email, phone or resume text."""
    return {
        "candidate_id": int(candidate_id),
        "job_id": int(job_id),
        "status": status,
        "timestamp": timestamp or datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }


def send_event(payload: dict, url: Optional[str] = None, timeout: Optional[float] = None) -> str:
    """Return a delivery status string. Never raises.

    'disabled'            - no webhook URL configured
    'delivered'           - HTTP 2xx
    'failed: <reason>'    - timeout, connection error or non-2xx response
    """
    url = settings.webhook_url if url is None else url
    if not url:
        return "disabled"
    try:
        resp = requests.post(url, json=payload, timeout=timeout or settings.webhook_timeout)
        if 200 <= resp.status_code < 300:
            return "delivered"
        return f"failed: HTTP {resp.status_code}"
    except requests.Timeout:
        return "failed: timeout"
    except requests.RequestException as exc:
        return f"failed: {type(exc).__name__}"
    except Exception as exc:  # defensive: never propagate
        return f"failed: {type(exc).__name__}"
