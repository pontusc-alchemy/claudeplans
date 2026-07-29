"""In-process HTTP tests over the FastAPI app via httpx ASGITransport.

No socket: ASGITransport drives the app object directly, so these exercise the full
router -> core -> filesystem stack against a tmp_path data root. asyncio_mode=auto
makes `async def test_*` run without an explicit marker.
"""

import json
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport

from claudeplans.config import AuthMode, FilesystemSettings, Settings
from claudeplans.main import create_app

BASE = "/v1/users/dev/projects/demo/docs"


def _client(tmp_path: Path, version: str = "dev") -> httpx.AsyncClient:
    app = create_app(
        Settings(
            auth_mode=AuthMode.noop,
            filesystem=FilesystemSettings(root=str(tmp_path)),
            version=version,
        )
    )
    return httpx.AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _create_plan(client: httpx.AsyncClient) -> httpx.Response:
    """Create a plan doc with one phase carrying one task; return the response."""
    return await client.post(
        BASE,
        json={
            "type": "plan",
            "slug": "p1",
            "title": "Plan One",
            "phases": [
                {"slug": "a", "name": "Alpha", "tasks": [{"text": "t1"}]},
            ],
        },
    )


async def test_create_returns_201_with_etag_and_envelope(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        resp = await _create_plan(client)
        assert resp.status_code == 201
        assert resp.headers["ETag"]
        body = resp.json()
        assert body["data"]["slug"] == "p1"
        assert body["data"]["owner_id"] == "dev"
        assert body["data"]["project"] == "demo"
        assert isinstance(body["warnings"], list)


async def test_get_returns_200_with_etag_and_envelope(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        await _create_plan(client)
        resp = await client.get(f"{BASE}/p1")
        assert resp.status_code == 200
        assert resp.headers["ETag"]
        body = resp.json()
        assert body["data"]["slug"] == "p1"
        assert isinstance(body["warnings"], list)


async def test_full_lifecycle_reflects_every_change(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        await _create_plan(client)
        # Add a second phase (no If-Match: stable-key, retry-safe).
        resp = await client.post(
            f"{BASE}/p1/phases",
            json={"slug": "b", "name": "Beta"},
        )
        assert resp.status_code == 200
        # Append a task to phase b (no If-Match).
        resp = await client.post(
            f"{BASE}/p1/phases/b/tasks",
            json={"text": "t2"},
        )
        assert resp.status_code == 200
        # Toggle that task using the rev from the previous response as If-Match.
        rev = resp.headers["ETag"]
        resp = await client.put(
            f"{BASE}/p1/phases/b/tasks/0/toggle",
            json={"checked": True},
            headers={"If-Match": rev},
        )
        assert resp.status_code == 200
        # Set phase b's status (stable-key).
        resp = await client.put(
            f"{BASE}/p1/phases/b/status",
            json={"status": "done"},
        )
        assert resp.status_code == 200
        # Final GET reflects every mutation.
        body = (await client.get(f"{BASE}/p1")).json()["data"]
        slugs = [p["slug"] for p in body["phases"]]
        assert slugs == ["a", "b"]
        phase_b = body["phases"][1]
        assert phase_b["status"] == "done"
        assert phase_b["tasks"][0]["text"] == "t2"
        assert phase_b["tasks"][0]["checked"] is True


async def test_get_missing_slug_returns_404(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        resp = await client.get(f"{BASE}/nope")
        assert resp.status_code == 404
        assert "detail" in resp.json()


async def test_write_to_foreign_namespace_is_forbidden(tmp_path: Path) -> None:
    # The noop caller is DEV_USER (namespace "dev"); a write under another uid 403s.
    async with _client(tmp_path) as client:
        resp = await client.post(
            "/v1/users/someone-else/projects/demo/docs",
            json={"type": "plan", "slug": "p1", "title": "Plan One"},
        )
        assert resp.status_code == 403


async def test_read_is_allowed_across_namespaces(tmp_path: Path) -> None:
    # Reads are read-all, not namespace-gated: a missing doc 404s (not 403).
    async with _client(tmp_path) as client:
        resp = await client.get("/v1/users/someone-else/projects/demo/docs/nope")
        assert resp.status_code == 404


async def test_foreign_write_precedes_not_found(tmp_path: Path) -> None:
    # A no-precondition write to a non-existent doc in a foreign namespace returns
    # 403 (not 404): authz precedes NotFound, so existence is never leaked.
    async with _client(tmp_path) as client:
        resp = await client.put(
            "/v1/users/someone-else/projects/demo/docs/ghost/status",
            json={"status": "active"},
        )
        assert resp.status_code == 403


# Write routes that need NO If-Match: the guard fires before any read, so a
# cross-namespace caller gets 403 regardless of whether the doc exists. The
# If-Match-gated routes (delete/move/toggle/edit/remove) return 428 first by
# dependency ordering and are out of scope here.
_FOREIGN = "/v1/users/someone-else/projects/demo/docs"
_NO_PRECONDITION_WRITES = [
    ("POST", _FOREIGN, {"type": "plan", "slug": "p1", "title": "Plan One"}),
    ("PUT", f"{_FOREIGN}/p1/status", {"status": "active"}),
    (
        "PUT",
        f"{_FOREIGN}/p1/research-refs",
        {"research_refs": ["r1"], "primary_parent_ref": "r1"},
    ),
    ("POST", f"{_FOREIGN}/p1/phases", {"slug": "b", "name": "Beta"}),
    ("POST", f"{_FOREIGN}/p1/phases/a/tasks", {"text": "t1"}),
    (
        "POST",
        f"{_FOREIGN}/p1/sections",
        {"anchor": "ctx", "heading": "Context", "body": "b"},
    ),
]


@pytest.mark.parametrize(("method", "url", "body"), _NO_PRECONDITION_WRITES)
async def test_every_no_precondition_write_verb_403s_cross_namespace(
    tmp_path: Path, method: str, url: str, body: dict
) -> None:
    async with _client(tmp_path) as client:
        resp = await client.request(method, url, json=body)
        assert resp.status_code == 403


async def test_toggle_with_stale_if_match_returns_409(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        await _create_plan(client)
        resp = await client.put(
            f"{BASE}/p1/phases/a/tasks/0/toggle",
            json={"checked": True},
            headers={"If-Match": "999999999"},
        )
        assert resp.status_code == 409


async def test_delete_with_wrong_if_match_returns_409(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        await _create_plan(client)
        resp = await client.request(
            "DELETE",
            f"{BASE}/p1",
            headers={"If-Match": "999999999"},
        )
        assert resp.status_code == 409


async def test_toggle_without_if_match_returns_428(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        await _create_plan(client)
        resp = await client.put(
            f"{BASE}/p1/phases/a/tasks/0/toggle",
            json={"checked": True},
        )
        assert resp.status_code == 428


async def test_malformed_create_body_returns_422(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        # Missing the required `title` field.
        resp = await client.post(
            BASE,
            json={"type": "plan", "slug": "p1"},
        )
        assert resp.status_code == 422
        # RequestValidationError path: no errors.pydantic.dev URL leaks into the body.
        assert "errors.pydantic.dev" not in resp.text
        for entry in resp.json()["detail"]:
            assert "url" not in entry


async def test_delta_referencing_missing_phase_returns_422(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        await _create_plan(client)
        # No phase "ghost": core raises the domain ValidationError -> 422.
        resp = await client.post(
            f"{BASE}/p1/phases/ghost/tasks",
            json={"text": "t"},
        )
        assert resp.status_code == 422


async def test_drift_warning_surfaces_in_envelope(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        await _create_plan(client)
        # Mark phase a (which has an open task) done: the linter flags the mismatch.
        resp = await client.put(
            f"{BASE}/p1/phases/a/status",
            json={"status": "done"},
        )
        assert resp.status_code == 200
        warnings = resp.json()["warnings"]
        assert any(
            w["code"] == "phase-done-open-tasks" and w["path"] == "phases.a"
            for w in warnings
        )


async def test_drift_warning_suppressed_for_unrelated_phase_write(
    tmp_path: Path,
) -> None:
    async with _client(tmp_path) as client:
        # Build a doc with two phases: a (will carry drift) and b (write target).
        await client.post(
            BASE,
            json={
                "type": "plan",
                "slug": "p1",
                "title": "Plan One",
                "phases": [
                    {"slug": "a", "name": "Alpha", "tasks": [{"text": "t1"}]},
                    {"slug": "b", "name": "Beta"},
                ],
            },
        )
        # Mark phase a done while it still has an open task -> drift on phases.a.
        resp = await client.put(
            f"{BASE}/p1/phases/a/status",
            json={"status": "done"},
        )
        assert resp.status_code == 200
        assert any(
            w["code"] == "phase-done-open-tasks" and w["path"] == "phases.a"
            for w in resp.json()["warnings"]
        )
        # Write that touches only phase b (scope=phases.b): phases.a drift suppressed.
        resp = await client.put(
            f"{BASE}/p1/phases/b/status",
            json={"status": "done"},
        )
        assert resp.status_code == 200
        assert not any(w["path"] == "phases.a" for w in resp.json()["warnings"])
        # Plain doc GET (scope=None) must still surface the phases.a warning.
        body = (await client.get(f"{BASE}/p1")).json()
        assert any(
            w["code"] == "phase-done-open-tasks" and w["path"] == "phases.a"
            for w in body["warnings"]
        )


@pytest.fixture
async def health_client(tmp_path: Path) -> AsyncIterator[httpx.AsyncClient]:
    async with _client(tmp_path) as client:
        yield client


async def test_healthz_ok(health_client: httpx.AsyncClient) -> None:
    resp = await health_client.get("/healthz")
    assert resp.status_code == 200
    assert resp.json() == {"status": "ok"}


async def test_readyz_ok(health_client: httpx.AsyncClient) -> None:
    resp = await health_client.get("/readyz")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ready"


async def test_status_reports_version_and_backend(
    health_client: httpx.AsyncClient,
) -> None:
    body = (await health_client.get("/status")).json()
    assert body["version"] == "dev"
    assert body["storage_backend"] == "filesystem"


async def test_status_reports_configured_version(tmp_path: Path) -> None:
    async with _client(tmp_path, version="1.2.3") as client:
        resp = await client.get("/status")
        assert resp.json()["version"] == "1.2.3"


async def test_openapi_schema_has_version_and_v1_paths(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        resp = await client.get("/openapi.json")
        assert resp.status_code == 200
        schema = resp.json()
        assert schema["info"]["version"] == "dev"
        assert any(path.startswith("/v1/") for path in schema["paths"])


async def test_swagger_ui_served(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        resp = await client.get("/docs")
        assert resp.status_code == 200
        assert "swagger" in resp.text.lower()


async def _create_research(client: httpx.AsyncClient) -> httpx.Response:
    """Create a research doc (which cannot carry phases) with one section."""
    return await client.post(
        BASE,
        json={
            "type": "research",
            "slug": "r1",
            "title": "Research One",
            "sections": [{"anchor": "intro", "heading": "Intro", "body": "hi"}],
        },
    )


async def test_add_phase_to_research_doc_422_and_not_persisted(tmp_path: Path) -> None:
    # Adding a phase to a research doc violates the invariant; write-time
    # re-validation must 422 it and leave nothing persisted (no poison document).
    async with _client(tmp_path) as client:
        await _create_research(client)
        resp = await client.post(f"{BASE}/r1/phases", json={"slug": "x", "name": "X"})
        assert resp.status_code == 422
        # The doc is still readable and unchanged: nothing reached disk.
        get = await client.get(f"{BASE}/r1")
        assert get.status_code == 200
        assert get.json()["data"]["phases"] == []


async def test_add_phase_duplicate_slug_422_and_doc_readable(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        await _create_plan(client)
        resp = await client.post(f"{BASE}/p1/phases", json={"slug": "a", "name": "Dup"})
        assert resp.status_code == 422
        get = await client.get(f"{BASE}/p1")
        assert get.status_code == 200
        assert [p["slug"] for p in get.json()["data"]["phases"]] == ["a"]


async def test_section_lifecycle_over_http(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        await _create_plan(client)
        # Add a section.
        resp = await client.post(
            f"{BASE}/p1/sections",
            json={"anchor": "ctx", "heading": "Context", "body": "b"},
        )
        assert resp.status_code == 200
        # Absolute set of a field.
        resp = await client.put(
            f"{BASE}/p1/sections/ctx", json={"heading": "Context 2"}
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["sections"][0]["heading"] == "Context 2"
        # Merge patch reflected in the envelope.
        resp = await client.patch(
            f"{BASE}/p1/sections/ctx", json={"patch": {"heading": "Patched"}}
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["sections"][0]["heading"] == "Patched"
        # Remove returns 200 + envelope (NOT 204).
        resp = await client.request("DELETE", f"{BASE}/p1/sections/ctx")
        assert resp.status_code == 200
        assert resp.json()["data"]["sections"] == []


async def test_patch_section_invalid_type_returns_422(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        await _create_plan(client)
        await client.post(
            f"{BASE}/p1/sections",
            json={"anchor": "ctx", "heading": "Context"},
        )
        # level must be an int; the merge re-validates Section -> pydantic 422.
        resp = await client.patch(
            f"{BASE}/p1/sections/ctx", json={"patch": {"level": "notanint"}}
        )
        assert resp.status_code == 422
        # PydanticValidationError path: no errors.pydantic.dev URL leaks into the body.
        assert "errors.pydantic.dev" not in resp.text
        for entry in resp.json()["detail"]:
            assert "url" not in entry


async def test_research_refs_invariant_422_and_valid_set_200(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        await _create_plan(client)
        # Create the research doc so the ref resolves.
        await client.post(
            BASE,
            json={"type": "research", "slug": "r1", "title": "R1"},
        )
        # primary not among refs violates the invariant -> 422 on write-time revalidate.
        resp = await client.put(
            f"{BASE}/p1/research-refs",
            json={"research_refs": ["r1"], "primary_parent_ref": "other"},
        )
        assert resp.status_code == 422
        # A consistent set with a valid research ref succeeds.
        resp = await client.put(
            f"{BASE}/p1/research-refs",
            json={"research_refs": ["r1"], "primary_parent_ref": "r1"},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["primary_parent_ref"] == "r1"


async def test_move_phase_if_match_semantics(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        await _create_plan(client)
        resp = await client.post(f"{BASE}/p1/phases", json={"slug": "b", "name": "B"})
        assert resp.status_code == 200
        rev = resp.headers["ETag"]
        # No If-Match -> 428.
        resp_no = await client.post(f"{BASE}/p1/phases/b/move", json={"to_index": 0})
        assert resp_no.status_code == 428
        # Stale If-Match -> 409.
        resp_stale = await client.post(
            f"{BASE}/p1/phases/b/move",
            json={"to_index": 0},
            headers={"If-Match": "999999999"},
        )
        assert resp_stale.status_code == 409
        # Correct If-Match -> 200 and the order changes.
        resp_ok = await client.post(
            f"{BASE}/p1/phases/b/move",
            json={"to_index": 0},
            headers={"If-Match": rev},
        )
        assert resp_ok.status_code == 200
        assert [p["slug"] for p in resp_ok.json()["data"]["phases"]] == ["b", "a"]


async def test_remove_task_returns_200_with_envelope(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        resp = await _create_plan(client)
        rev = resp.headers["ETag"]
        resp = await client.request(
            "DELETE",
            f"{BASE}/p1/phases/a/tasks/0",
            headers={"If-Match": rev},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["phases"][0]["tasks"] == []


async def test_corrupt_document_returns_500_clean(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        await _create_plan(client)
        # Overwrite the envelope on disk with one missing the `document` key.
        envelope_path = tmp_path / "dev" / "demo" / "p1.json"
        envelope_path.write_text(json.dumps({"rev": "1", "created_at": "x"}))
        resp = await client.get(f"{BASE}/p1")
        assert resp.status_code == 500
        assert resp.json() == {"detail": "stored document is corrupt"}
        # No filesystem path leaked in the body.
        assert str(tmp_path) not in resp.text


async def test_oversized_body_returns_413(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            auth_mode=AuthMode.noop,
            filesystem=FilesystemSettings(root=str(tmp_path)),
            max_body_bytes=1024,
        )
    )
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            BASE, content=b"x" * 2048, headers={"Content-Type": "application/json"}
        )
        assert resp.status_code == 413


async def test_deeply_nested_body_returns_422_not_500(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        depth = 5000
        body = (
            '{"type":"plan","slug":"p1","title":"t","frontmatter":'
            + '{"a":' * depth
            + "1"
            + "}" * depth
            + "}"
        )
        resp = await client.post(
            BASE, content=body, headers={"Content-Type": "application/json"}
        )
        assert resp.status_code == 422
        assert resp.json()["detail"][0]["msg"] == "request body is too deeply nested"


async def test_oversized_chunked_body_returns_413(tmp_path: Path) -> None:
    # No Content-Length (streamed/chunked): the byte-count backstop must still 413,
    # not the 400 that a plain exception in the body parser would produce.
    app = create_app(
        Settings(
            auth_mode=AuthMode.noop,
            filesystem=FilesystemSettings(root=str(tmp_path)),
            max_body_bytes=1024,
        )
    )

    async def chunks() -> AsyncIterator[bytes]:
        for _ in range(4):
            yield b"x" * 512  # 2048 total, streamed without a Content-Length

    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post(
            BASE, content=chunks(), headers={"Content-Type": "application/json"}
        )
        assert resp.status_code == 413


async def test_non_object_document_returns_500_clean(tmp_path: Path) -> None:
    async with _client(tmp_path) as client:
        await _create_plan(client)
        # Valid JSON but not an object on disk: a clean 500, not a raw AttributeError.
        envelope_path = tmp_path / "dev" / "demo" / "p1.json"
        envelope_path.write_text("[1, 2, 3]")
        resp = await client.get(f"{BASE}/p1")
        assert resp.status_code == 500
        assert resp.json() == {"detail": "stored document is corrupt"}
        assert str(tmp_path) not in resp.text
