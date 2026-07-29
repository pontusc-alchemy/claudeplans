import json
from pathlib import Path
from typing import Any, cast

from pydantic import JsonValue

from claudeplans import templates
from claudeplans.auth.registry import UserRegistry
from claudeplans.lineage import ChildRef, ParentRef
from claudeplans.navigation import (
    build_user_tree,
    list_users,
    load_project_lineage,
    resolve_children,
    resolve_parent,
)
from claudeplans.projects import ProjectRegistry
from claudeplans.storage.filesystem import FilesystemRepository
from claudeplans.storage.repository import CREATE
from claudeplans_contracts import Document, document_key
from claudeplans_contracts.enums import DocType


def _doc(
    project: str,
    slug: str,
    doc_type: str,
    *,
    owner: str = "dev",
    primary: str | None = None,
    refs: list[str] | None = None,
    status: str | None = None,
) -> dict[str, JsonValue]:
    doc: dict[str, JsonValue] = {
        "type": doc_type,
        "project": project,
        "slug": slug,
        "title": f"{slug} title",
        "owner_id": owner,
    }
    if primary is not None:
        doc["primary_parent_ref"] = primary
    if refs is not None:
        doc["research_refs"] = refs
    if status is not None:
        doc["status"] = status
    return doc


async def _put(repo: FilesystemRepository, doc: dict[str, JsonValue]) -> None:
    key = document_key(str(doc["owner_id"]), str(doc["project"]), str(doc["slug"]))
    await repo.put(key, doc, CREATE)


async def test_build_user_tree_groups_sorts_and_reflects_lineage(
    tmp_path: Path,
) -> None:
    repo = FilesystemRepository(tmp_path / "data")
    # projB inserted first, projA second — must come back sorted A then B.
    await _put(repo, _doc("projB", "r1", "research"))
    await _put(repo, _doc("projB", "p1", "plan", primary="r1", refs=["r1"]))
    await _put(repo, _doc("projA", "solo", "plan"))

    trees = await build_user_tree(repo, "dev")

    assert [t.project for t in trees] == ["projA", "projB"]
    proj_a, proj_b = trees
    assert proj_a.doc_count == 1
    assert proj_a.lineage.research == ()
    assert len(proj_a.lineage.unlinked_plans) == 1
    assert proj_b.doc_count == 2
    assert len(proj_b.lineage.research) == 1
    node = proj_b.lineage.research[0]
    assert node.slug == "r1"
    assert [p.slug for p in node.plans] == ["p1"]


async def test_build_user_tree_partitions_archived_docs(tmp_path: Path) -> None:
    repo = FilesystemRepository(tmp_path / "data")
    await _put(repo, _doc("projA", "active-plan", "plan"))
    await _put(repo, _doc("projA", "old-plan", "plan", status="archived"))

    trees = await build_user_tree(repo, "dev")

    assert len(trees) == 1
    tree = trees[0]
    assert tree.doc_count == 2  # total, including the archived doc
    assert [p.slug for p in tree.lineage.unlinked_plans] == ["active-plan"]
    assert [p.slug for p in tree.archived.unlinked_plans] == ["old-plan"]


async def test_build_user_tree_empty_archived_yields_empty_lineage(
    tmp_path: Path,
) -> None:
    repo = FilesystemRepository(tmp_path / "data")
    await _put(repo, _doc("projA", "p1", "plan"))

    trees = await build_user_tree(repo, "dev")

    assert trees[0].archived.research == ()
    assert trees[0].archived.unlinked_plans == ()


async def test_load_project_lineage_partitions_archived_docs(tmp_path: Path) -> None:
    repo = FilesystemRepository(tmp_path / "data")
    await _put(repo, _doc("projA", "active-plan", "plan"))
    await _put(repo, _doc("projA", "old-plan", "plan", status="archived"))

    active, archived = await load_project_lineage(repo, "dev", "projA")

    assert [p.slug for p in active.unlinked_plans] == ["active-plan"]
    assert [p.slug for p in archived.unlinked_plans] == ["old-plan"]


async def test_build_user_tree_scoped_to_user(tmp_path: Path) -> None:
    repo = FilesystemRepository(tmp_path / "data")
    await _put(repo, _doc("projA", "p1", "plan", owner="dev"))
    await _put(repo, _doc("projX", "p9", "plan", owner="alice"))

    trees = await build_user_tree(repo, "dev")

    assert [t.project for t in trees] == ["projA"]


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


async def test_registry_path_outside_storage_walk(tmp_path: Path) -> None:
    repo = FilesystemRepository(tmp_path / "data")
    registry = UserRegistry(tmp_path / "users.json")
    registry.mint("Alice")  # writes tmp_path/users.json, a sibling of data/
    await _put(repo, _doc("projA", "p1", "plan", owner="dev"))

    keys = [e.key for e in await repo.list("")]

    assert keys == ["dev/projA/p1"]  # the registry file is never walked as a doc


async def test_build_user_tree_skips_unloadable_doc(tmp_path: Path) -> None:
    root = tmp_path / "data"
    repo = FilesystemRepository(root)
    await _put(repo, _doc("projA", "good", "plan"))
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

    trees = await build_user_tree(repo, "dev")

    assert [t.project for t in trees] == ["projA"]
    assert trees[0].doc_count == 1  # poison skipped, only the good doc counts
    assert [n.slug for n in trees[0].lineage.unlinked_plans] == ["good"]


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
    a_doc = by_project["projA"]["unlinked_plans"][0]
    b_doc = by_project["projB"]["unlinked_plans"][0]
    assert a_doc["current"] is True
    assert a_doc["view_url"] == "/view/projA/shared"
    assert b_doc["current"] is False  # the project guard discriminates
    assert by_project["projA"]["current"] is True
    assert by_project["projB"]["current"] is False


async def test_build_sidebar_plan_appears_under_primary_research_node(
    tmp_path: Path,
) -> None:
    repo = FilesystemRepository(tmp_path / "data")
    registry = UserRegistry(tmp_path / "users.json")
    await _put(repo, _doc("projA", "r1", "research"))
    await _put(repo, _doc("projA", "r2", "research"))
    # p2's primary is r2 but it also cites r1 -> p2 is a backlink under r1.
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
    research = {r["title"]: r for r in sb_projects[0]["research"]}
    r2 = research["r2 title"]
    assert [pl["title"] for pl in r2["plans"]] == ["p2 title"]


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
    assert all(not d["current"] for d in proj["unlinked_plans"])


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


async def test_list_users_ignores_stray_root_level_file(tmp_path: Path) -> None:
    root = tmp_path / "data"
    repo = FilesystemRepository(root)
    registry = UserRegistry(tmp_path / "users.json")
    await _put(repo, _doc("projA", "p1", "plan", owner="dev"))
    # A stray single-segment *.json directly under the root must not mint a user.
    (root / "stray.json").write_text('{"rev": "1", "document": {}}')

    users = await list_users(repo, registry, "dev")

    assert {u.uid for u in users} == {"dev"}


def test_registry_records_sorted_by_name(tmp_path: Path) -> None:
    registry = UserRegistry(tmp_path / "users.json")
    assert registry.records() == []
    registry.mint("Zoe")
    registry.mint("Alice")
    assert [r.name for r in registry.records()] == ["Alice", "Zoe"]


async def test_build_sidebar_entries_carry_status_and_type(tmp_path: Path) -> None:
    repo = FilesystemRepository(tmp_path / "data")
    registry = UserRegistry(tmp_path / "users.json")
    await _put(repo, _doc("projA", "r1", "research"))
    await _put(repo, _doc("projA", "p1", "plan", primary="r1", refs=["r1"]))

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
    research = sb_projects[0]["research"][0]
    assert research["type"] == "research"
    assert research["status"] == "draft"  # _doc helper leaves the default status
    plan = research["plans"][0]
    assert plan["type"] == "plan"
    assert plan["status"] == "draft"


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


def _plan_document(
    slug: str,
    *,
    primary: str | None = None,
    refs: list[str] | None = None,
    doc_type: DocType = DocType.plan,
) -> Document:
    """A real Document to hand to resolve_parent (the `doc` under test)."""
    return Document(
        type=doc_type,
        project="projA",
        slug=slug,
        title=f"{slug} title",
        owner_id="dev",
        research_refs=refs or [],
        primary_parent_ref=primary,
    )


async def test_resolve_parent_covers_found_none_wrongtype_and_dangling(
    tmp_path: Path,
) -> None:
    repo = FilesystemRepository(tmp_path / "data")
    await _put(repo, _doc("projA", "r1", "research"))
    await _put(repo, _doc("projA", "q1", "plan"))  # a plan the ref may wrongly target

    # (a) parent found -> ParentRef with the research doc's slug + title.
    child = _plan_document("p1", primary="r1", refs=["r1"])
    parent = await resolve_parent(repo, "dev", "projA", child)
    assert parent == ParentRef(slug="r1", title="r1 title")

    # (b) no primary_parent_ref -> None.
    standalone = _plan_document("p2")
    assert await resolve_parent(repo, "dev", "projA", standalone) is None

    # (c) primary points at a doc whose type == "plan" (not research) -> None.
    mis_typed = _plan_document("p3", primary="q1", refs=["q1"])
    assert await resolve_parent(repo, "dev", "projA", mis_typed) is None

    # (d) dangling ref (no listing entry matches the slug) -> None.
    dangling = _plan_document("p4", primary="ghost", refs=["ghost"])
    assert await resolve_parent(repo, "dev", "projA", dangling) is None


async def test_resolve_children_lists_primary_children_sorted(
    tmp_path: Path,
) -> None:
    repo = FilesystemRepository(tmp_path / "data")
    await _put(repo, _doc("projA", "r1", "research"))
    # Inserted p2 before p1; build_lineage sorts children by slug.
    await _put(repo, _doc("projA", "p2", "plan", primary="r1", refs=["r1"]))
    await _put(repo, _doc("projA", "p1", "plan", primary="r1", refs=["r1"]))
    await _put(repo, _doc("projA", "solo", "plan"))  # no primary -> not a child

    research = _plan_document("r1", doc_type=DocType.research)
    children = await resolve_children(repo, "dev", "projA", research)
    assert children == [
        ChildRef(slug="p1", title="p1 title"),
        ChildRef(slug="p2", title="p2 title"),
    ]

    # A plan is a leaf -> no children.
    leaf = _plan_document("p1", primary="r1", refs=["r1"])
    assert await resolve_children(repo, "dev", "projA", leaf) == []

    # A childless research doc -> empty.
    await _put(repo, _doc("projA", "r9", "research"))
    childless = _plan_document("r9", doc_type=DocType.research)
    assert await resolve_children(repo, "dev", "projA", childless) == []


async def test_resolve_children_crosses_the_archived_boundary(tmp_path: Path) -> None:
    """The index is status-agnostic, reciprocal to resolve_parent's upward trail.

    An archived research doc still lists its (active) child, and an active research
    doc still lists its archived child — build_lineage folds both statuses in one set,
    so the parent<->child link survives regardless of either side's status.
    """
    repo = FilesystemRepository(tmp_path / "data")

    # Archived parent, active child (the resolve_parent asymmetry repro): the child's
    # trail points up to the archived parent, so the parent must list the child back.
    await _put(repo, _doc("projA", "old-audit", "research", status="archived"))
    await _put(
        repo,
        _doc("projA", "still-open", "plan", primary="old-audit", refs=["old-audit"]),
    )
    archived_parent = _plan_document("old-audit", doc_type=DocType.research)
    assert await resolve_children(repo, "dev", "projA", archived_parent) == [
        ChildRef(slug="still-open", title="still-open title")
    ]

    # Active parent, archived child: the archived sub-plan still appears in the index.
    await _put(repo, _doc("projA", "live", "research"))
    await _put(
        repo,
        _doc(
            "projA",
            "done-leg",
            "plan",
            primary="live",
            refs=["live"],
            status="archived",
        ),
    )
    active_parent = _plan_document("live", doc_type=DocType.research)
    assert await resolve_children(repo, "dev", "projA", active_parent) == [
        ChildRef(slug="done-leg", title="done-leg title")
    ]


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
