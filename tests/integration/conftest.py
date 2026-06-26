"""Shared CLI test harness: a sync transport that drives the ASGI app in-process.

PlanClient is sync, but httpx 0.28.1's ASGITransport is async-only, so a plain sync
`httpx.Client` cannot drive it. `_SyncASGITransport` bridges the gap with an anyio
blocking portal: the sync transport hands each request to the running app on a
worker event loop and blocks for the fully-read response. This keeps PlanClient
sync (production builds a normal sync Client) while still exercising the full
router -> core -> filesystem stack with no socket. The bridge lives only in the
test harness — production never imports it.
"""

from collections.abc import Iterator
from pathlib import Path

import httpx
import pytest
from anyio.from_thread import BlockingPortal, start_blocking_portal
from fastapi import FastAPI
from httpx import ASGITransport, BaseTransport, Request, Response

from claudeplans.config import AuthMode, FilesystemSettings, Settings
from claudeplans.main import create_app
from claudeplans_cli.client import PlanClient


class SyncASGITransport(BaseTransport):
    """Drive an async ASGITransport from sync code via a blocking portal."""

    def __init__(self, app: FastAPI) -> None:
        self._async = ASGITransport(app=app)
        self._portal_cm = start_blocking_portal()
        self._portal: BlockingPortal = self._portal_cm.__enter__()

    def handle_request(self, request: Request) -> Response:
        return self._portal.call(self._dispatch, request)

    async def _dispatch(self, request: Request) -> Response:
        resp = await self._async.handle_async_request(request)
        await resp.aread()
        return Response(resp.status_code, headers=resp.headers, content=resp.content)

    def close(self) -> None:
        self._portal_cm.__exit__(None, None, None)


def build_app(tmp_path: Path) -> FastAPI:
    """The ASGI app wired to a tmp_path data root with dev no-op auth.

    Both registry paths are pinned under tmp_path so test runs never write
    registry files into the repo working directory.
    """
    return create_app(
        Settings(
            auth_mode=AuthMode.noop,
            filesystem=FilesystemSettings(root=str(tmp_path / "data")),
            registry_path=str(tmp_path / "users.json"),
            project_registry_path=str(tmp_path / "projects.json"),
        )
    )


def plan_client(transport: SyncASGITransport) -> PlanClient:
    """A PlanClient bound to the in-process transport."""
    return PlanClient(
        http_client=httpx.Client(transport=transport, base_url="http://test")
    )


@pytest.fixture
def transport(tmp_path: Path) -> Iterator[SyncASGITransport]:
    t = SyncASGITransport(build_app(tmp_path))
    try:
        yield t
    finally:
        t.close()


@pytest.fixture
def client(transport: SyncASGITransport) -> PlanClient:
    return plan_client(transport)
