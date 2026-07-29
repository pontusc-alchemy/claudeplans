"""Shared in-process client for the view-page tests (see test_view.py's own copy,
which additionally drives real uvicorn for the SSE routes)."""

from pathlib import Path

import httpx
from httpx import ASGITransport

from claudeplans.config import AuthMode, FilesystemSettings, Settings
from claudeplans.main import create_app

DOCS = "/v1/users/dev/projects/demo/docs"


def client_for(tmp_path: Path) -> httpx.AsyncClient:
    """An AsyncClient bound to a fresh app over `tmp_path`, noop auth."""
    app = create_app(
        Settings(
            auth_mode=AuthMode.noop,
            filesystem=FilesystemSettings(root=str(tmp_path)),
        )
    )
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")
