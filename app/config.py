"""Central configuration. All values can be overridden with environment variables or a .env file."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load_dotenv() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()


class Settings:
    """Read lazily so tests can override environment variables."""

    @property
    def db_path(self) -> str:
        return os.environ.get("TALENTOPS_DB_PATH", str(ROOT / "data" / "talentops.db"))

    @property
    def max_upload_bytes(self) -> int:
        return int(float(os.environ.get("TALENTOPS_MAX_UPLOAD_MB", "5")) * 1024 * 1024)

    @property
    def webhook_url(self) -> str:
        # Empty string = n8n integration disabled.
        return os.environ.get("N8N_WEBHOOK_URL", "").strip()

    @property
    def webhook_timeout(self) -> float:
        return float(os.environ.get("N8N_TIMEOUT_SECONDS", "3"))

    @property
    def inbound_token(self) -> str:
        # Shared secret for /api/inbound/resume (used by n8n). Empty = endpoint disabled.
        return os.environ.get("TALENTOPS_INBOUND_TOKEN", "").strip()

    @property
    def embedding_backend(self) -> str:
        # auto | embedding | tfidf
        return os.environ.get("TALENTOPS_EMBEDDING_BACKEND", "auto").lower()

    @property
    def model_name(self) -> str:
        return os.environ.get("TALENTOPS_MODEL_NAME", "all-MiniLM-L6-v2")


settings = Settings()

REVIEW_STATUSES = ["Pending Review", "Shortlisted", "Further Review Required"]
