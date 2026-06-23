"""The __main__ Server subclass must close the feed BEFORE delegating to uvicorn.

This is the load-bearing shutdown ordering: closing the feed first pushes the
sentinel so open SSE generators drain during uvicorn's graceful wait, instead of
being force-cancelled at the timeout (uvicorn runs the lifespan shutdown only after
the wait). The super().shutdown is monkeypatched to a no-op so no real server runs.
"""

import asyncio

import pytest
import uvicorn

from claudeplans.__main__ import _Server
from claudeplans.events import EventFeed
from claudeplans.main import app


async def test_shutdown_closes_feed_before_delegating(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    feed = EventFeed()
    app.state.feed = feed
    closed_before_super: bool = False

    async def _noop_super(_self: uvicorn.Server, sockets: object = None) -> None:
        nonlocal closed_before_super
        closed_before_super = feed._closed

    monkeypatch.setattr(uvicorn.Server, "shutdown", _noop_super)

    # An active subscriber whose loop must terminate once the feed closes.
    received: list[object] = []

    async def consume() -> None:
        with feed.subscribe() as sub:
            async for event in sub:
                received.append(event)

    task = asyncio.ensure_future(consume())
    await asyncio.sleep(0)  # let it register its queue

    server = _Server(uvicorn.Config("claudeplans.main:app"))
    await server.shutdown()

    assert closed_before_super  # closed FIRST, before delegating to super
    assert feed._closed
    await asyncio.wait_for(task, 1)  # the sentinel ended the active loop
