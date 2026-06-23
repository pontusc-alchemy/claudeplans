"""In-process tests for the live-view pages, assets, and SSE stream.

feed + render_cache are built in create_app (not only in lifespan), so the
non-streaming routes work under a plain ASGITransport. The SSE routes do NOT:
httpx's ASGITransport buffers the whole response before returning, so a stream that
yields one frame and then blocks for the next deadlocks. The SSE tests therefore
run the app on a real loopback uvicorn server (which streams incrementally), driven
by httpx over TCP, with short timeouts so a missing frame fails fast.
"""

import asyncio
import socket
import threading
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import httpx
import pytest
import uvicorn
from httpx import ASGITransport

from claudeplans import templates
from claudeplans.config import AuthMode, FilesystemSettings, Settings
from claudeplans.main import create_app
from claudeplans_contracts import Document
from claudeplans_contracts.enums import DocType

DOCS = "/v1/users/dev/projects/demo/docs"
VIEW = "/v1/users/dev/projects/demo/docs/p1/view"
EVENTS = "/v1/users/dev/projects/demo/docs/p1/events"
LINEAGE = "/v1/users/dev/projects/demo/"

PLAN_BODY: dict[str, object] = {
    "type": "plan",
    "slug": "p1",
    "title": "Plan One",
    "phases": [{"slug": "a", "name": "Alpha", "tasks": [{"text": "t1"}]}],
}


def _client(tmp_path: Path) -> httpx.AsyncClient:
    app = create_app(
        Settings(
            auth_mode=AuthMode.noop,
            filesystem=FilesystemSettings(root=str(tmp_path)),
        )
    )
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _read_frame(lines: AsyncIterator[str]) -> list[str]:
    """Accumulate SSE lines up to the blank-line frame boundary."""
    frame: list[str] = []
    async for line in lines:
        if line == "":
            return frame
        frame.append(line)
    return frame


async def test_view_page_renders(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        await client.post(DOCS, json=PLAN_BODY)
        resp = await client.get(VIEW)
        assert resp.status_code == 200
        assert resp.headers["content-type"].startswith("text/html")
        body = resp.text
        assert 'id="doc"' in body
        assert 'hx-ext="sse,morph"' in body
        assert "Plan One" in body
        assert "/assets/js/htmx.min.js" in body
        assert "/assets/js/idiomorph-ext.min.js" in body
        assert "/assets/js/sse.js" in body
        csp = resp.headers["content-security-policy"]
        assert "script-src 'self'" in csp
        assert "unsafe-eval" not in csp


async def test_assets_served(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        resp = await client.get("/assets/js/htmx.min.js")
        assert resp.status_code == 200
        assert resp.text.startswith("var htmx")


async def test_idiomorph_ext_served(tmp_path: Path) -> None:
    # The htmx-integration build (not the core morph) is what registers the "morph"
    # extension the template's hx-ext="...,morph" requires, so it must be served.
    async with _client(tmp_path) as client:
        resp = await client.get("/assets/js/idiomorph-ext.min.js")
        assert resp.status_code == 200
        assert "defineExtension" in resp.text


async def test_script_injection_neutralized_in_page(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        await client.post(DOCS, json=PLAN_BODY)
        await client.post(
            f"{DOCS}/p1/sections",
            json={
                "anchor": "intro",
                "heading": "Intro",
                "body": "<script>alert(1)</script>",
                "level": 2,
            },
        )
        resp = await client.get(VIEW)
        assert resp.status_code == 200
        # The vendored <script src=...> tags are fine; the injected inline script must
        # not survive as an executable element.
        assert "<script>alert(1)</script>" not in resp.text


async def test_morph_target_id_cannot_be_spoofed(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        await client.post(DOCS, json=PLAN_BODY)
        await client.post(
            f"{DOCS}/p1/sections",
            json={
                "anchor": "intro",
                "heading": "Intro",
                "body": "# Pwned {#doc-status .pill .done}",
                "level": 2,
            },
        )
        resp = await client.get(VIEW)
        assert resp.status_code == 200
        # Only the template's own trusted #doc-status survives; the attr_list-injected
        # duplicate is stripped, so idiomorph's id-matching can't be corrupted.
        assert resp.text.count('id="doc-status"') == 1


def test_research_body_has_no_phases_container() -> None:
    # Research docs carry no phases, so the body must omit the <ol id="phases">
    # container entirely (the template guards it behind `{% if phases %}`).
    doc = Document(
        type=DocType.research,
        project="demo",
        slug="r1",
        title="Research One",
        owner_id="dev",
    )
    body = templates.render_doc_body(doc)
    assert '<ol id="phases"' not in body


async def test_lineage_page_renders(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        await client.post(
            DOCS, json={"type": "research", "slug": "r1", "title": "Research One"}
        )
        await client.post(
            DOCS,
            json={
                "type": "plan",
                "slug": "p1",
                "title": "Plan One",
                "research_refs": ["r1"],
                "primary_research_ref": "r1",
            },
        )
        resp = await client.get(LINEAGE)
        assert resp.status_code == 200
        body = resp.text
        assert 'id="lineage"' in body
        assert "Research One" in body
        assert "Plan One" in body
        # The plan link nests under the research node, so it follows it in the markup.
        assert body.index("Research One") < body.index("Plan One")


# --- SSE: needs a real socket server (ASGITransport can't stream) -----------


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def live_server(tmp_path: Path) -> Iterator[str]:
    """Run the app on a loopback uvicorn server; yield its base URL."""
    app = create_app(
        Settings(
            auth_mode=AuthMode.noop,
            filesystem=FilesystemSettings(root=str(tmp_path)),
        )
    )
    port = _free_port()
    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    # Wait for startup so the first request never races the bind.
    for _ in range(100):
        if server.started:
            break
        threading.Event().wait(0.05)
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.should_exit = True
        thread.join(timeout=5)


async def test_sse_emits_on_connect_and_on_mutation(live_server: str) -> None:
    async with httpx.AsyncClient(base_url=live_server) as client:
        await client.post(DOCS, json=PLAN_BODY)
        async with client.stream("GET", EVENTS) as r:
            assert r.headers["content-type"].startswith("text/event-stream")
            lines = r.aiter_lines()
            # Snapshot-on-connect frame.
            first = await asyncio.wait_for(_read_frame(lines), 5)
            assert "event: message" in first
            assert any('id="doc-title"' in line for line in first)
            # A mutation publishes an Event the already-subscribed stream receives.
            resp = await client.put(
                f"{DOCS}/p1/phases/a/status", json={"status": "done"}
            )
            assert resp.status_code == 200
            nxt = await asyncio.wait_for(_read_frame(lines), 5)
            assert any('phase-a-status" class="pill done"' in line for line in nxt)


async def test_reconnect_resyncs(live_server: str) -> None:
    async with httpx.AsyncClient(base_url=live_server) as client:
        await client.post(DOCS, json=PLAN_BODY)
        await client.put(f"{DOCS}/p1/phases/a/status", json={"status": "done"})
        # A fresh connection's snapshot already reflects the mutation (no replay).
        async with client.stream("GET", EVENTS) as r:
            first = await asyncio.wait_for(_read_frame(r.aiter_lines()), 5)
            assert any('phase-a-status" class="pill done"' in line for line in first)


async def test_sse_injection_neutralized_end_to_end(live_server: str) -> None:
    async with httpx.AsyncClient(base_url=live_server) as client:
        await client.post(DOCS, json=PLAN_BODY)
        await client.post(
            f"{DOCS}/p1/sections",
            json={
                "anchor": "intro",
                "heading": "Intro",
                "body": "<script>alert(1)</script>",
                "level": 2,
            },
        )
        # The snapshot frame is the sanitized body; the injected script must not
        # survive as an executable element in the pushed stream.
        async with client.stream("GET", EVENTS) as r:
            first = await asyncio.wait_for(_read_frame(r.aiter_lines()), 5)
            assert not any("<script>alert(1)</script>" in line for line in first)


async def test_delete_while_watching_emits_removed_frame(live_server: str) -> None:
    async with httpx.AsyncClient(base_url=live_server) as client:
        resp = await client.post(DOCS, json=PLAN_BODY)
        rev = resp.headers["etag"]
        async with client.stream("GET", EVENTS) as r:
            lines = r.aiter_lines()
            await asyncio.wait_for(_read_frame(lines), 5)  # drain the snapshot frame
            deleted = await client.delete(f"{DOCS}/p1", headers={"If-Match": rev})
            assert deleted.status_code == 204
            frame = await asyncio.wait_for(_read_frame(lines), 5)
            assert any("This document was removed." in line for line in frame)
