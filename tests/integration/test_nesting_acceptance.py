"""Acceptance for unlimited nesting: the depth-3 chain the two-level fold could
not render, the caller shapes that asked for it, and the v1-store guarantee."""

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
from _view_harness import DOCS, client_for

from claudeplans.storage.filesystem import FilesystemRepository
from claudeplans.storage.repository import CREATE
from claudeplans_contracts import MAX_LINEAGE_DEPTH

PROJECT = "/v1/users/dev/projects/demo"


async def _create(client: httpx.AsyncClient, slug: str, **fields: object) -> None:
    body: dict[str, object] = {"type": "plan", "slug": slug, "title": slug, **fields}
    parent = body.get("primary_parent_ref")
    if parent is not None:
        body.setdefault("research_refs", [parent])
    resp = await client.post(DOCS, json=body)
    assert resp.status_code == 201, resp.text


async def _chain(client: httpx.AsyncClient) -> None:
    """The driving case: reviews -> pr-219-review -> pr-219-mental-model."""
    await _create(client, "reviews", type="research", title="Reviews")
    await _create(
        client, "pr-219-review", title="PR 219 review", primary_parent_ref="reviews"
    )
    await _create(
        client,
        "pr-219-mental-model",
        title="PR 219 mental model",
        primary_parent_ref="pr-219-review",
    )


async def test_sidebar_renders_all_three_levels(tmp_path: Path) -> None:
    """The bullet the whole change hangs on: the deepest doc must not vanish."""
    async with client_for(tmp_path) as client:
        await _chain(client)
        body = (await client.get(f"{DOCS}/reviews/view")).text
        for title in ("Reviews", "PR 219 review", "PR 219 mental model"):
            assert title in body
        assert body.index("PR 219 review") < body.index("PR 219 mental model")


async def test_deepest_doc_shows_a_multi_hop_trail_to_the_root(
    tmp_path: Path,
) -> None:
    async with client_for(tmp_path) as client:
        await _chain(client)
        body = (await client.get(f"{DOCS}/pr-219-mental-model/view")).text
        assert "doc-lineage-trail" in body
        # Root-first: every ancestor is linked, in order, above the current title.
        assert body.index("Reviews") < body.index("PR 219 review")
        assert 'href="/v1/users/dev/projects/demo/docs/reviews/view"' in body
        assert 'href="/v1/users/dev/projects/demo/docs/pr-219-review/view"' in body


async def test_a_middle_doc_shows_both_its_trail_and_its_children(
    tmp_path: Path,
) -> None:
    """Previously impossible: the two chrome blocks were mutually exclusive."""
    async with client_for(tmp_path) as client:
        await _chain(client)
        body = (await client.get(f"{DOCS}/pr-219-review/view")).text
        assert "doc-lineage-trail" in body
        assert "doc-subdoc-index" in body
        # The shared class is what keeps the CSS adjacency rule matching.
        assert body.count("doc-chrome") >= 2


async def test_existing_shallow_docs_render_unchanged(tmp_path: Path) -> None:
    """Acceptance bullet 4: no user action needed for a research + one hop."""
    async with client_for(tmp_path) as client:
        await _create(client, "r1", type="research", title="Research One")
        await _create(client, "p1", title="Plan One", primary_parent_ref="r1")
        parent = (await client.get(f"{DOCS}/r1/view")).text
        assert "doc-subdoc-index" in parent
        assert "Plan One" in parent
        child = (await client.get(f"{DOCS}/p1/view")).text
        assert "doc-lineage-trail" in child
        assert "Research One" in child


# --- the caesari-ai caller shape ---


async def test_any_type_parent_with_mixed_type_children(tmp_path: Path) -> None:
    """A dossier doc parenting a REQ doc and a work-map doc, as asked for."""
    async with client_for(tmp_path) as client:
        await _create(client, "dossier", type="research", title="Dossier")
        await _create(client, "req", title="REQ", primary_parent_ref="dossier")
        await _create(
            client,
            "work-map",
            type="research",
            title="Work map",
            primary_parent_ref="dossier",
        )
        body = (await client.get(f"{DOCS}/dossier/view")).text
        assert "REQ" in body
        assert "Work map" in body


async def test_a_child_keeps_its_own_flat_view_url(tmp_path: Path) -> None:
    """Identity holds at depth: the parent never enters the key or the URL."""
    async with client_for(tmp_path) as client:
        await _chain(client)
        resp = await client.get(f"{DOCS}/pr-219-mental-model/view")
        assert resp.status_code == 200


async def test_nesting_needs_no_new_verb(tmp_path: Path) -> None:
    """Created and relinked through the existing create / refs verbs."""
    async with client_for(tmp_path) as client:
        await _create(client, "a", type="research", title="A")
        await _create(client, "b", title="B")
        resp = await client.put(
            f"{DOCS}/b/research-refs",
            json={"research_refs": ["a"], "primary_parent_ref": "a"},
        )
        assert resp.status_code == 200
        assert resp.json()["data"]["primary_parent_ref"] == "a"


# --- write-path guards ---


@pytest.mark.parametrize("target", ["self", "ghost"], ids=["self", "dangling"])
async def test_create_rejects_an_unresolvable_parent(
    tmp_path: Path, target: str
) -> None:
    """create bypasses the refs endpoint, so it carries the guard itself.

    A self-parent on create can never resolve — the doc does not exist yet — so
    the existence check catches it before the cycle check ever runs.
    """
    async with client_for(tmp_path) as client:
        resp = await client.post(
            DOCS,
            json={
                "type": "plan",
                "slug": "self",
                "title": "Self",
                "research_refs": [target],
                "primary_parent_ref": target,
            },
        )
        assert resp.status_code == 422
        assert "do not resolve" in resp.text


async def test_relink_rejects_a_two_cycle(tmp_path: Path) -> None:
    async with client_for(tmp_path) as client:
        await _create(client, "a", type="research", title="A")
        await _create(client, "b", title="B", primary_parent_ref="a")
        resp = await client.put(
            f"{DOCS}/a/research-refs",
            json={"research_refs": ["b"], "primary_parent_ref": "b"},
        )
        assert resp.status_code == 422
        assert "cycle" in resp.text


async def test_relink_rejects_a_deep_cycle(tmp_path: Path) -> None:
    async with client_for(tmp_path) as client:
        await _create(client, "a", type="research", title="A")
        await _create(client, "b", title="B", primary_parent_ref="a")
        await _create(client, "c", title="C", primary_parent_ref="b")
        resp = await client.put(
            f"{DOCS}/a/research-refs",
            json={"research_refs": ["c"], "primary_parent_ref": "c"},
        )
        assert resp.status_code == 422
        assert "cycle" in resp.text


async def test_a_dangling_ref_is_still_rejected(tmp_path: Path) -> None:
    """Only the research-type check was dropped, not the existence check."""
    async with client_for(tmp_path) as client:
        await _create(client, "a", type="research", title="A")
        resp = await client.put(
            f"{DOCS}/a/research-refs", json={"research_refs": ["nope"]}
        )
        assert resp.status_code == 422
        assert "nope" in resp.text


# --- the v1 store guarantee ---


async def test_an_unmigrated_v1_doc_still_roots_its_children(tmp_path: Path) -> None:
    """The load-bearing case for existing deployments, whose stores are all v1.

    list() projects straight off the envelope without migrating, so a doc written
    before the rename still carries `primary_research_ref` on disk.
    """
    repo = FilesystemRepository(tmp_path)
    for slug, extra in (
        ("r1", {}),
        ("p1", {"research_refs": ["r1"], "primary_research_ref": "r1"}),
    ):
        await repo.put(
            f"dev/demo/{slug}",
            {
                "schema_version": 1,
                "type": "research" if slug == "r1" else "plan",
                "project": "demo",
                "slug": slug,
                "title": slug.upper(),
                "owner_id": "dev",
                **extra,
            },
            CREATE,
        )
    async with client_for(tmp_path) as client:
        lineage = (await client.get(f"{PROJECT}/lineage")).json()
        assert [r["slug"] for r in lineage["roots"]] == ["r1"]
        assert [c["slug"] for c in lineage["roots"][0]["children"]] == ["p1"]
        assert "doc-lineage-trail" in (await client.get(f"{DOCS}/p1/view")).text


async def test_a_v1_doc_migrates_on_read(tmp_path: Path) -> None:
    repo = FilesystemRepository(tmp_path)
    await repo.put(
        "dev/demo/p1",
        {
            "schema_version": 1,
            "type": "plan",
            "project": "demo",
            "slug": "p1",
            "title": "P1",
            "owner_id": "dev",
            "research_refs": ["r1"],
            "primary_research_ref": "r1",
        },
        CREATE,
    )
    async with client_for(tmp_path) as client:
        body = (await client.get(f"{DOCS}/p1")).json()["data"]
        assert body["primary_parent_ref"] == "r1"
        assert "primary_research_ref" not in json.dumps(body)


# --- the write-time depth cap ---


async def _chain_of(client: httpx.AsyncClient, n: int, prefix: str = "d") -> None:
    """A root plus n-1 descendants: d00 -> d01 -> ... -> d{n-1}."""
    await _create(client, f"{prefix}00", type="research", title="Root")
    for i in range(1, n):
        await _create(
            client, f"{prefix}{i:02d}", primary_parent_ref=f"{prefix}{i - 1:02d}"
        )


async def test_create_past_the_depth_cap_is_rejected(tmp_path: Path) -> None:
    async with client_for(tmp_path) as client:
        await _chain_of(client, MAX_LINEAGE_DEPTH)
        resp = await client.post(
            DOCS,
            json={
                "type": "plan",
                "slug": "too-deep",
                "title": "Too deep",
                "research_refs": [f"d{MAX_LINEAGE_DEPTH - 1:02d}"],
                "primary_parent_ref": f"d{MAX_LINEAGE_DEPTH - 1:02d}",
            },
        )
        assert resp.status_code == 422
        assert str(MAX_LINEAGE_DEPTH) in resp.text


async def test_reparenting_a_deep_subtree_past_the_cap_is_rejected(
    tmp_path: Path,
) -> None:
    """Moving a doc carries its descendants, so the check spans both directions.

    Each chain alone fits; joined they would not. Validating only the moved doc's
    own chain would let its descendants land past the cap, surfacing later only as
    silent truncation.
    """
    half = MAX_LINEAGE_DEPTH // 2 + 2
    async with client_for(tmp_path) as client:
        await _chain_of(client, half, prefix="a")
        await _chain_of(client, half, prefix="b")
        resp = await client.put(
            f"{DOCS}/b00/research-refs",
            json={
                "research_refs": [f"a{half - 1:02d}"],
                "primary_parent_ref": f"a{half - 1:02d}",
            },
        )
        assert resp.status_code == 422
        assert "past the limit" in resp.text


async def test_reparenting_a_shallow_subtree_within_the_cap_succeeds(
    tmp_path: Path,
) -> None:
    """The cap must not reject a legal move — the guard is a bound, not a wall."""
    async with client_for(tmp_path) as client:
        await _chain_of(client, 3, prefix="a")
        await _chain_of(client, 3, prefix="b")
        resp = await client.put(
            f"{DOCS}/b00/research-refs",
            json={"research_refs": ["a02"], "primary_parent_ref": "a02"},
        )
        assert resp.status_code == 200


async def test_a_pre_existing_on_disk_cycle_still_surfaces(tmp_path: Path) -> None:
    """The base server had no acyclicity check, so a stored cycle is reachable data.

    A cycle has no root, so the fold would never enter it and both docs would be
    absent from the sidebar, the lineage page and the JSON — with no warning. They
    are promoted to roots and named instead.
    """
    repo = FilesystemRepository(tmp_path)
    for slug, other in (("a", "b"), ("b", "a")):
        await repo.put(
            f"dev/demo/{slug}",
            {
                "schema_version": 1,
                "type": "research",
                "project": "demo",
                "slug": slug,
                "title": slug.upper(),
                "owner_id": "dev",
                "research_refs": [other],
                "primary_research_ref": other,
            },
            CREATE,
        )
    async with client_for(tmp_path) as client:
        lineage = (await client.get(f"{PROJECT}/lineage")).json()
        assert lineage["cycle_roots"] == ["a"]

        def slugs(nodes: list[Any]) -> set[str]:
            out: set[str] = set()
            for n in nodes:
                out.add(str(n["slug"]))
                out |= slugs(n["children"])
            return out

        assert slugs(lineage["roots"]) == {"a", "b"}
        # And they are reachable in the browsable surfaces, not just the JSON.
        assert (await client.get(f"{DOCS}/a/view")).status_code == 200
        assert "B" in (await client.get(f"{PROJECT}/")).text


async def test_renaming_an_ancestor_reflects_in_a_descendant_trail(
    tmp_path: Path,
) -> None:
    """Liveness by construction: the trail is shell chrome resolved per GET.

    The FragmentCache is keyed on the doc's own rev and wraps only #doc, so a
    stale ancestor title would otherwise survive until the descendant changed.
    """
    async with client_for(tmp_path) as client:
        await _chain(client)
        renamed = await client.put(f"{DOCS}/reviews", json={"title": "Renamed root"})
        assert renamed.status_code == 200
        body = (await client.get(f"{DOCS}/pr-219-mental-model/view")).text
        assert "Renamed root" in body
        assert "Reviews" not in body
