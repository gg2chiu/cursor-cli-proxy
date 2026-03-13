"""Health check endpoint."""
import shutil

from fastapi import APIRouter

from src.model_registry import model_registry
from src.routes.common import session_manager

router = APIRouter()


def _check_session_storage() -> bool:
    try:
        session_manager.load_sessions()
        return True
    except Exception:
        return False


@router.get("/health")
async def health():
    checks = {
        "cursor_agent": shutil.which("cursor-agent") is not None,
        "model_registry": model_registry._models is not None,
        "session_storage": _check_session_storage(),
    }
    status = "healthy" if all(checks.values()) else "degraded"
    return {"status": status, "checks": checks}
