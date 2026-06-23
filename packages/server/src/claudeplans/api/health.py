"""Liveness, readiness, and status probes — no /v1 prefix, no envelope.

These are operational endpoints (load balancer / orchestrator probes), not part of
the document API, so they return bare JSON rather than the {data, warnings[]} shape.
"""

from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from ..config import StorageBackend
from .deps import SettingsDep

router = APIRouter(tags=["health"])


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    """Liveness: the process is up. No dependencies, so it never probes the backend."""
    return {"status": "ok"}


@router.get("/readyz")
async def readyz(settings: SettingsDep) -> JSONResponse:
    """Readiness: the backend is reachable.

    Readiness gains backend-specific probes as backends land; today it checks the
    only backend's root is accessible (creatable/statable).
    """
    if settings.storage_backend is StorageBackend.filesystem:
        try:
            Path(settings.filesystem.root).mkdir(parents=True, exist_ok=True)
        except OSError:
            return JSONResponse({"status": "not ready"}, status_code=503)
    return JSONResponse({"status": "ready"}, status_code=200)


@router.get("/status")
async def status(request: Request, settings: SettingsDep) -> dict[str, str]:
    """Build/config summary: version plus the active backend and auth mode."""
    return {
        "status": "ok",
        "version": request.app.version,
        "storage_backend": settings.storage_backend,
        "auth_mode": settings.auth_mode,
    }
