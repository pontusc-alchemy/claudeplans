import json
from pathlib import Path
from typing import Any, cast

from pydantic import JsonValue

from claudeplans import templates
from claudeplans.auth.registry import UserRegistry
from claudeplans.lineage import AncestorRef, ChildRef
from claudeplans.navigation import (
    _split_lineages,
    build_user_tree,
    list_users,
    load_project_lineage,
    resolve_ancestors,
    resolve_children,
)
from claudeplans.projects import ProjectRegistry
from claudeplans.storage.filesystem import FilesystemRepository
from claudeplans.storage.repository import CREATE
from claudeplans_contracts import Document, document_key
from claudeplans_contracts.enums import DocStatus, DocType


def _doc(
    project: str,
    slug: str,
    doc_type: str = "plan",
    *,
    owner: str = "dev",
    primary: str | None = None,
    refs: list[str] | None = None,
    status: str | None = None,
) -> dict[str, JsonValue]:
    # The model requires primary_parent_ref to be a member of research_refs, so a
    # parent implies the ref unless the caller spells the full list out.
    doc: dict[str, JsonValue] = {
        "type": doc_type,
        "project": project,
        "slug": slug,
        "title": f"{slug} title",
        "owner_id": owner,
    }
    if primary is not None:
        doc["primary_parent_ref"] = primary
        doc["research_refs"] = refs if refs is not None else [primary]
    elif refs is not None:
        doc["research_refs"] = refs
    if status is not None:
        doc["status"] = status
    return doc


async def _put(repo: FilesystemRepository, doc: dict[str, JsonValue]) -> None:
    key = document_key(str(doc["owner_id"]), str(doc["project"]), str(doc["slug"]))
    await repo.put(key, doc, CREATE)


def _document(
    slug: str,
    *,
    project: str = "projA",
    doc_type: DocType = DocType.plan,
    primary: str | None = None,
    status: DocStatus = DocStatus.draft,
) -> Document:
    # The real Document handed to resolve_ancestors/resolve_children as `doc`.
    return Document(
        type=doc_type,
        project=project,
        slug=slug,
        title=f"{slug} title",
        owner_id="dev",
        research_refs=[primary] if primary is not None else [],
        primary_parent_ref=primary,
        status=status,
    )


async def test_resolve_ancestors_of_a_root_is_empty(tmp_path: Path) -> None:
    repo = FilesystemRepository(tmp_path / "data")
    await _put(repo, _doc("projA", "top"))

    assert await resolve_ancestors(repo, "dev", "projA", _document("top")) == []


async def test_resolve_ancestors_returns_the_trail_root_first_excluding_self(
    tmp_path: Path,
) -> None:
    repo = FilesystemRepository(tmp_path / "data")
    await _put(repo, _doc("projA", "a"))
    await _put(repo, _doc("projA", "b", primary="a"))
    await _put(repo, _doc("projA", "c", primary="b"))

    trail = await resolve_ancestors(repo, "dev", "projA", _document("c", primary="b"))

    # Root first, nearest parent last, and never the doc itself.
    assert trail == [
        AncestorRef(slug="a", title="a title"),
        AncestorRef(slug="b", title="b title"),
    ]


async def test_resolve_ancestors_is_orthogonal_to_doc_type(tmp_path: Path) -> None:
    repo = FilesystemRepository(tmp_path / "data")
    await _put(repo, _doc("projA", "plan-top", "plan"))
    await _put(repo, _doc("projA", "sub-research", "research", primary="plan-top"))

    trail = await resolve_ancestors(
        repo,
        "dev",
        "projA",
        _document("sub-research", doc_type=DocType.research, primary="plan-top"),
    )

    assert trail == [AncestorRef(slug="plan-top", title="plan-top title")]


async def test_resolve_ancestors_stops_at_a_dangling_middle_hop(
    tmp_path: Path,
) -> None:
    repo = FilesystemRepository(tmp_path / "data")
    # p points at a slug that was never created; the walk must not invent it.
    await _put(repo, _doc("projA", "p", primary="ghost"))
    await _put(repo, _doc("projA", "x", primary="p"))

    trail = await resolve_ancestors(repo, "dev", "projA", _document("x", primary="p"))

    assert trail == [AncestorRef(slug="p", title="p title")]


async def test_resolve_ancestors_terminates_on_a_cycle(tmp_path: Path) -> None:
    repo = FilesystemRepository(tmp_path / "data")
    # Written straight through the repo, past the write-path acyclicity guard.
    await _put(repo, _doc("projA", "a", primary="b"))
    await _put(repo, _doc("projA", "b", primary="a"))

    trail = await resolve_ancestors(repo, "dev", "projA", _document("a", primary="b"))

    assert [ref.slug for ref in trail] == ["b"]


async def test_resolve_children_lists_children_of_any_doc_type(tmp_path: Path) -> None:
    repo = FilesystemRepository(tmp_path / "data")
    await _put(repo, _doc("projA", "plan-top", "plan"))
    await _put(repo, _doc("projA", "sub-plan", "plan", primary="plan-top"))
    await _put(repo, _doc("projA", "sub-research", "research", primary="plan-top"))

    children = await resolve_children(repo, "dev", "projA", _document("plan-top"))

    assert children == [
        ChildRef(slug="sub-plan", title="sub-plan title"),
        ChildRef(slug="sub-research", title="sub-research title"),
    ]


async def test_resolve_children_of_a_leaf_is_empty(tmp_path: Path) -> None:
    repo = FilesystemRepository(tmp_path / "data")
    await _put(repo, _doc("projA", "top"))
    await _put(repo, _doc("projA", "leaf", primary="top"))

    leaf = _document("leaf", primary="top")

    assert await resolve_children(repo, "dev", "projA", leaf) == []


async def test_resolve_children_are_sorted_by_slug(tmp_path: Path) -> None:
    repo = FilesystemRepository(tmp_path / "data")
    await _put(repo, _doc("projA", "top"))
    # Inserted c, a, b — the listing order must not leak into the result.
    await _put(repo, _doc("projA", "c", primary="top"))
    await _put(repo, _doc("projA", "a", primary="top"))
    await _put(repo, _doc("projA", "b", primary="top"))
    await _put(repo, _doc("projA", "solo"))

    children = await resolve_children(repo, "dev", "projA", _document("top"))

    assert [child.slug for child in children] == ["a", "b", "c"]


async def test_resolve_children_crosses_the_archived_boundary(tmp_path: Path) -> None:
    repo = FilesystemRepository(tmp_path / "data")
    # Archived parent, active child: the parent still lists the child back.
    await _put(repo, _doc("projA", "old-audit", "research", status="archived"))
    await _put(repo, _doc("projA", "still-open", primary="old-audit"))
    archived_parent = _document("old-audit", doc_type=DocType.research)
    assert await resolve_children(repo, "dev", "projA", archived_parent) == [
        ChildRef(slug="still-open", title="still-open title")
    ]

    # Active parent, archived child: the archived sub-doc still appears.
    await _put(repo, _doc("projA", "live", "research"))
    await _put(repo, _doc("projA", "done-leg", primary="live", status="archived"))
    active_parent = _document("live", doc_type=DocType.research)
    assert await resolve_children(repo, "dev", "projA", active_parent) == [
        ChildRef(slug="done-leg", title="done-leg title")
    ]


async def test_resolve_children_excludes_grandchildren(tmp_path: Path) -> None:
    repo = FilesystemRepository(tmp_path / "data")
    await _put(repo, _doc("projA", "top"))
    await _put(repo, _doc("projA", "kid", primary="top"))
    await _put(repo, _doc("projA", "grandkid", primary="kid"))

    children = await resolve_children(repo, "dev", "projA", _document("top"))

    assert children == [ChildRef(slug="kid", title="kid title")]


def test_split_lineages_partitions_active_and_archived() -> None:
    docs = [
        _document("live"),
        _document("live-kid", primary="live"),
        _document("old", status=DocStatus.archived),
    ]

    active, archived = _split_lineages(docs)

    assert [n.slug for n in active.roots] == ["live"]
    assert [n.slug for n in active.roots[0].children] == ["live-kid"]
    assert [n.slug for n in archived.roots] == ["old"]


async def test_load_project_lineage_partitions_archived_docs(tmp_path: Path) -> None:
    repo = FilesystemRepository(tmp_path / "data")
    await _put(repo, _doc("projA", "active-top"))
    await _put(repo, _doc("projA", "active-kid", primary="active-top"))
    await _put(repo, _doc("projA", "old-plan", status="archived"))

    active, archived = await load_project_lineage(repo, "dev", "projA")

    assert [n.slug for n in active.roots] == ["active-top"]
    assert [n.slug for n in active.roots[0].children] == ["active-kid"]
    assert [n.slug for n in archived.roots] == ["old-plan"]


async def test_load_project_lineage_skips_unloadable_doc(tmp_path: Path) -> None:
    root = tmp_path / "data"
    repo = FilesystemRepository(root)
    await _put(repo, _doc("projA", "good"))
    # An envelope repo.list() returns (rev is a string) but get_document rejects:
    # the body carries a forbidden extra field, so strict validation fails.
    poison = root / "dev" / "projA" / "bad.json"
    poison.write_text(
        json.dumps(
            {
                "rev": "1",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
                "document": {
                    "type": "plan",
                    "project": "projA",
                    "slug": "bad",
                    "title": "bad",
                    "owner_id": "dev",
                    "BOGUS_FIELD": 1,
                },
            }
        )
    )

    active, archived = await load_project_lineage(repo, "dev", "projA")

    assert [n.slug for n in active.roots] == ["good"]
    assert archived.roots == ()


async def test_build_user_tree_groups_sorts_and_reflects_lineage(
    tmp_path: Path,
) -> None:
    repo = FilesystemRepository(tmp_path / "data")
    # projB inserted first, projA second — must come back sorted A then B.
    await _put(repo, _doc("projB", "r1", "research"))
    await _put(repo, _doc("projB", "p1", "plan", primary="r1"))
    await _put(repo, _doc("projA", "solo", "plan"))

    trees = await build_user_tree(repo, "dev")

    assert [t.project for t in trees] == ["projA", "projB"]
    proj_a, proj_b = trees
    assert proj_a.doc_count == 1
    assert [n.slug for n in proj_a.lineage.roots] == ["solo"]
    assert proj_b.doc_count == 2
    assert [n.slug for n in proj_b.lineage.roots] == ["r1"]
    assert [n.slug for n in proj_b.lineage.roots[0].children] == ["p1"]


async def test_build_user_tree_partitions_archived_docs(tmp_path: Path) -> None:
    repo = FilesystemRepository(tmp_path / "data")
    await _put(repo, _doc("projA", "active-plan", "plan"))
    await _put(repo, _doc("projA", "old-plan", "plan", status="archived"))

    trees = await build_user_tree(repo, "dev")

    assert len(trees) == 1
    tree = trees[0]
    assert tree.doc_count == 2  # total, including the archived doc
    assert [n.slug for n in tree.lineage.roots] == ["active-plan"]
    assert [n.slug for n in tree.archived.roots] == ["old-plan"]


async def test_build_user_tree_empty_archived_yields_empty_lineage(
    tmp_path: Path,
) -> None:
    repo = FilesystemRepository(tmp_path / "data")
    await _put(repo, _doc("projA", "p1", "plan"))

    trees = await build_user_tree(repo, "dev")

    assert trees[0].archived.roots == ()
    assert trees[0].archived.over_cap == ()


async def test_build_user_tree_scoped_to_user(tmp_path: Path) -> None:
    repo = FilesystemRepository(tmp_path / "data")
    await _put(repo, _doc("projA", "p1", "plan", owner="dev"))
    await _put(repo, _doc("projX", "p9", "plan", owner="alice"))

    trees = await build_user_tree(repo, "dev")

    assert [t.project for t in trees] == ["projA"]


async def test_build_user_tree_skips_unloadable_doc(tmp_path: Path) -> None:
    root = tmp_path / "data"
    repo = FilesystemRepository(root)
    await _put(repo, _doc("projA", "good", "plan"))
    poison = root / "dev" / "projA" / "bad.json"
    poison.write_text(
        json.dumps(
            {
                "rev": "1",
                "created_at": "2026-01-01T00:00:00Z",
                "updated_at": "2026-01-01T00:00:00Z",
                "document": {
                    "type": "plan",
                    "project": "projA",
                    "slug": "bad",
                    "title": "bad",
                    "owner_id": "dev",
                    "BOGUS_FIELD": 1,
                },
            }
        )
    )

    trees = await build_user_tree(repo, "dev")

    assert [t.project for t in trees] == ["projA"]
    assert trees[0].doc_count == 1  # poison skipped, only the good doc counts
    assert [n.slug for n in trees[0].lineage.roots] == ["good"]


async def test_build_user_tree_uses_registry_display_name(tmp_path: Path) -> None:
    repo = FilesystemRepository(tmp_path / "data")
    await _put(repo, _doc("projA", "p1", "plan"))
    project_registry = ProjectRegistry(tmp_path / "projects.json")
    project_registry.set("dev", "projA", "Project Alpha (2026)")

    trees = await build_user_tree(repo, "dev", project_registry)

    assert trees[0].project == "projA"  # slug identity unchanged
    assert trees[0].name == "Project Alpha (2026)"  # display name from registry


async def test_build_user_tree_falls_back_to_slug_when_name_unset(
    tmp_path: Path,
) -> None:
    repo = FilesystemRepository(tmp_path / "data")
    await _put(repo, _doc("projA", "p1", "plan"))

    trees = await build_user_tree(repo, "dev")

    assert trees[0].name == "projA"  # no registry → slug is the display name


async def test_list_users_unions_storage_registry_current(tmp_path: Path) -> None:
    repo = FilesystemRepository(tmp_path / "data")
    await _put(repo, _doc("projA", "p1", "plan", owner="dev"))
    await _put(repo, _doc("projX", "p9", "plan", owner="zoe"))
    registry = UserRegistry(tmp_path / "users.json")
    alice = registry.mint("Alice")  # registered but owns no documents

    users = await list_users(repo, registry, "dev")
    by_uid = {u.uid: u for u in users}

    assert set(by_uid) == {"dev", "zoe", alice.uid}
    assert by_uid["dev"].current is True
    assert by_uid["zoe"].current is False
    assert by_uid[alice.uid].current is False
    assert by_uid[alice.uid].name == "Alice"  # registry display name
    assert by_uid["zoe"].name == "zoe"  # raw uid when no registry record
    assert [u.name for u in users] == sorted(u.name for u in users)  # sorted by name


async def test_list_users_ignores_stray_root_level_file(tmp_path: Path) -> None:
    root = tmp_path / "data"
    repo = FilesystemRepository(root)
    registry = UserRegistry(tmp_path / "users.json")
    await _put(repo, _doc("projA", "p1", "plan", owner="dev"))
    # A stray single-segment *.json directly under the root must not mint a user.
    (root / "stray.json").write_text('{"rev": "1", "document": {}}')

    users = await list_users(repo, registry, "dev")

    assert {u.uid for u in users} == {"dev"}


async def test_registry_path_outside_storage_walk(tmp_path: Path) -> None:
    repo = FilesystemRepository(tmp_path / "data")
    registry = UserRegistry(tmp_path / "users.json")
    registry.mint("Alice")  # writes tmp_path/users.json, a sibling of data/
    await _put(repo, _doc("projA", "p1", "plan", owner="dev"))

    keys = [e.key for e in await repo.list("")]

    assert keys == ["dev/projA/p1"]  # the registry file is never walked as a doc


def test_registry_records_sorted_by_name(tmp_path: Path) -> None:
    registry = UserRegistry(tmp_path / "users.json")
    assert registry.records() == []
    registry.mint("Zoe")
    registry.mint("Alice")
    assert [r.name for r in registry.records()] == ["Alice", "Zoe"]


async def test_build_sidebar_marks_active_doc_by_project_and_slug(
    tmp_path: Path,
) -> None:
    repo = FilesystemRepository(tmp_path / "data")
    registry = UserRegistry(tmp_path / "users.json")
    await _put(repo, _doc("projA", "shared", "plan"))
    await _put(repo, _doc("projB", "shared", "plan"))  # same slug, other project

    projects = await build_user_tree(repo, "dev")
    users = await list_users(repo, registry, "dev")
    sidebar = templates.build_sidebar(
        users=users,
        projects=projects,
        current_uid="dev",
        current_project="projA",
        current_slug="shared",
        view_url=lambda p, s: f"/view/{p}/{s}",
    )

    sb_projects = cast(list[dict[str, Any]], sidebar["projects"])
    by_project = {p["project"]: p for p in sb_projects}
    a_doc = by_project["projA"]["roots"][0]
    b_doc = by_project["projB"]["roots"][0]
    assert a_doc["current"] is True
    assert a_doc["view_url"] == "/view/projA/shared"
    assert b_doc["current"] is False  # the project guard discriminates
    assert by_project["projA"]["current"] is True
    assert by_project["projB"]["current"] is False


async def test_build_sidebar_nests_a_doc_under_its_primary_parent(
    tmp_path: Path,
) -> None:
    repo = FilesystemRepository(tmp_path / "data")
    registry = UserRegistry(tmp_path / "users.json")
    await _put(repo, _doc("projA", "r1", "research"))
    await _put(repo, _doc("projA", "r2", "research"))
    # p2's primary is r2 but it also cites r1 -> placement keys on the primary only.
    await _put(repo, _doc("projA", "p2", "plan", primary="r2", refs=["r1", "r2"]))

    projects = await build_user_tree(repo, "dev")
    users = await list_users(repo, registry, "dev")
    sidebar = templates.build_sidebar(
        users=users,
        projects=projects,
        current_uid="dev",
        current_project="projA",
        current_slug="p2",
        view_url=lambda p, s: f"/view/{p}/{s}",
    )

    sb_projects = cast(list[dict[str, Any]], sidebar["projects"])
    roots = {r["title"]: r for r in sb_projects[0]["roots"]}
    assert [c["title"] for c in roots["r2 title"]["children"]] == ["p2 title"]
    assert roots["r1 title"]["children"] == []


async def test_build_sidebar_no_active_when_no_current_doc(tmp_path: Path) -> None:
    repo = FilesystemRepository(tmp_path / "data")
    registry = UserRegistry(tmp_path / "users.json")
    await _put(repo, _doc("projA", "p1", "plan"))

    projects = await build_user_tree(repo, "dev")
    users = await list_users(repo, registry, "dev")
    sidebar = templates.build_sidebar(
        users=users,
        projects=projects,
        current_uid="dev",
        current_project=None,
        current_slug=None,
        view_url=lambda p, s: f"/view/{p}/{s}",
    )

    sb_projects = cast(list[dict[str, Any]], sidebar["projects"])
    proj = sb_projects[0]
    assert proj["current"] is False
    assert all(not d["current"] for d in proj["roots"])


async def test_build_sidebar_project_current_with_and_without_open_doc(
    tmp_path: Path,
) -> None:
    repo = FilesystemRepository(tmp_path / "data")
    registry = UserRegistry(tmp_path / "users.json")
    await _put(repo, _doc("projA", "p1", "plan"))
    projects = await build_user_tree(repo, "dev")
    users = await list_users(repo, registry, "dev")

    # Doc-view page (a slug is open): the project is still the active ancestor.
    on_doc = templates.build_sidebar(
        users=users,
        projects=projects,
        current_uid="dev",
        current_project="projA",
        current_slug="p1",
        view_url=lambda p, s: f"/view/{p}/{s}",
    )
    a_on_doc = cast(list[dict[str, Any]], on_doc["projects"])[0]
    assert a_on_doc["current"] is True

    # Lineage page (no slug open): the project is still the active ancestor.
    on_lin = templates.build_sidebar(
        users=users,
        projects=projects,
        current_uid="dev",
        current_project="projA",
        current_slug=None,
        view_url=lambda p, s: f"/view/{p}/{s}",
    )
    a_on_lin = cast(list[dict[str, Any]], on_lin["projects"])[0]
    assert a_on_lin["current"] is True


async def test_build_sidebar_entries_carry_status_and_type(tmp_path: Path) -> None:
    repo = FilesystemRepository(tmp_path / "data")
    registry = UserRegistry(tmp_path / "users.json")
    await _put(repo, _doc("projA", "r1", "research"))
    await _put(repo, _doc("projA", "p1", "plan", primary="r1"))

    projects = await build_user_tree(repo, "dev")
    users = await list_users(repo, registry, "dev")
    sidebar = templates.build_sidebar(
        users=users,
        projects=projects,
        current_uid="dev",
        current_project="projA",
        current_slug=None,
        view_url=lambda p, s: f"/view/{p}/{s}",
    )
    sb_projects = cast(list[dict[str, Any]], sidebar["projects"])
    root = sb_projects[0]["roots"][0]
    assert root["type"] == "research"
    assert root["status"] == "draft"  # _doc helper leaves the default status
    child = root["children"][0]
    assert child["type"] == "plan"
    assert child["status"] == "draft"


async def test_sidebar_carries_display_name(tmp_path: Path) -> None:
    repo = FilesystemRepository(tmp_path / "data")
    registry = UserRegistry(tmp_path / "users.json")
    project_registry = ProjectRegistry(tmp_path / "projects.json")
    await _put(repo, _doc("projA", "p1", "plan"))
    project_registry.set("dev", "projA", "My Named Project")

    projects = await build_user_tree(repo, "dev", project_registry)
    users = await list_users(repo, registry, "dev")
    sidebar = templates.build_sidebar(
        users=users,
        projects=projects,
        current_uid="dev",
        current_project=None,
        current_slug=None,
        view_url=lambda p, s: f"/view/{p}/{s}",
    )

    sb_projects = cast(list[dict[str, Any]], sidebar["projects"])
    proj = sb_projects[0]
    assert proj["project"] == "projA"  # identity key preserved
    assert proj["name"] == "My Named Project"  # display name in context
