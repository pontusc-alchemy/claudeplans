"""In-process tests of the CLI library mirror (PlanClient) over the real ASGI app.

The `client` fixture (see conftest) injects a sync-portal-bridged ASGITransport
client into PlanClient, so these exercise the full router -> core -> filesystem
stack with no socket. PlanClient stays sync; the bridge is harness-only.
"""

import json

import pytest

from claudeplans_cli import output
from claudeplans_cli.client import PlanClient
from claudeplans_cli.errors import exit_code_for
from claudeplans_contracts import Forbidden, NotFound, StaleRevision

_CREATE_BODY = {
    "type": "plan",
    "slug": "p1",
    "title": "Plan One",
    "phases": [{"slug": "a", "name": "Alpha", "tasks": [{"text": "t1"}]}],
}


def test_create_returns_rev_and_namespaced_doc(client: PlanClient) -> None:
    reply = client.create_document("dev", "demo", _CREATE_BODY)
    assert reply.rev
    assert reply.data is not None
    assert reply.data["slug"] == "p1"
    assert reply.data["owner_id"] == "dev"


def test_get_add_task_toggle_round_trips(client: PlanClient) -> None:
    client.create_document("dev", "demo", _CREATE_BODY)
    got = client.get_document("dev", "demo", "p1")
    assert got.data is not None
    added = client.add_task("dev", "demo", "p1", "a", "t2")
    assert added.rev
    # Toggle needs the current rev as If-Match.
    toggled = client.toggle_task("dev", "demo", "p1", "a", 0, True, rev=added.rev)
    assert toggled.data is not None
    assert toggled.data["phases"][0]["tasks"][0]["checked"] is True


def test_set_document_status_round_trips(client: PlanClient) -> None:
    client.create_document("dev", "demo", _CREATE_BODY)
    reply = client.set_document_status("dev", "demo", "p1", "active")
    assert reply.data is not None
    assert reply.data["status"] == "active"


def test_get_missing_slug_raises_not_found(client: PlanClient) -> None:
    with pytest.raises(NotFound) as excinfo:
        client.get_document("dev", "demo", "ghost")
    assert exit_code_for(excinfo.value) == 5  # NOT_FOUND, moved off Typer's usage 2


def test_cross_namespace_write_raises_forbidden(client: PlanClient) -> None:
    with pytest.raises(Forbidden) as excinfo:
        client.create_document("evil", "demo", _CREATE_BODY)
    assert exit_code_for(excinfo.value) == 3


def test_stale_rev_toggle_raises_stale_revision(client: PlanClient) -> None:
    client.create_document("dev", "demo", _CREATE_BODY)
    with pytest.raises(StaleRevision) as excinfo:
        client.toggle_task("dev", "demo", "p1", "a", 0, True, rev="999999999")
    assert exit_code_for(excinfo.value) == 9


def test_emit_prints_single_line_json(
    client: PlanClient, capsys: pytest.CaptureFixture[str]
) -> None:
    client.create_document("dev", "demo", _CREATE_BODY)
    reply = client.get_document("dev", "demo", "p1")
    output.emit(reply)
    out = capsys.readouterr().out
    # Single line: exactly one trailing newline, none embedded.
    assert out.count("\n") == 1
    parsed = json.loads(out)
    assert parsed["data"]["slug"] == "p1"
    assert parsed["rev"] == reply.rev


# --- Full method coverage: every remaining PlanClient method end-to-end. ---


def test_put_research_refs(client: PlanClient) -> None:
    # A research doc must exist for the ref to be valid; create it, then link.
    client.create_document(
        "dev", "demo", {"type": "research", "slug": "r1", "title": "R1"}
    )
    client.create_document("dev", "demo", _CREATE_BODY)
    reply = client.put_research_refs("dev", "demo", "p1", ["r1"], "r1")
    assert reply.data is not None
    assert reply.data["research_refs"] == ["r1"]
    assert reply.data["primary_parent_ref"] == "r1"


def test_add_and_set_phase_status_and_remove(client: PlanClient) -> None:
    client.create_document("dev", "demo", _CREATE_BODY)
    added = client.add_phase("dev", "demo", "p1", "b", "Beta", "todo")
    assert added.data is not None
    assert [p["slug"] for p in added.data["phases"]] == ["a", "b"]
    set_ = client.set_phase_status("dev", "demo", "p1", "b", "done")
    assert set_.data is not None
    assert set_.data["phases"][1]["status"] == "done"
    removed = client.remove_phase("dev", "demo", "p1", "b")
    assert removed.data is not None
    assert [p["slug"] for p in removed.data["phases"]] == ["a"]


def test_move_phase_with_rev(client: PlanClient) -> None:
    client.create_document("dev", "demo", _CREATE_BODY)
    added = client.add_phase("dev", "demo", "p1", "b", "Beta", "todo")
    assert added.rev
    moved = client.move_phase("dev", "demo", "p1", "b", 0, rev=added.rev)
    assert moved.data is not None
    assert [p["slug"] for p in moved.data["phases"]] == ["b", "a"]


def test_edit_task_round_trip_persists(client: PlanClient) -> None:
    created = client.create_document("dev", "demo", _CREATE_BODY)
    assert created.rev
    edited = client.edit_task("dev", "demo", "p1", "a", 0, "t1-edited", rev=created.rev)
    assert edited.data is not None
    # Re-fetch (do not trust only the mutation response) and assert persistence.
    refetched = client.get_document("dev", "demo", "p1")
    assert refetched.data is not None
    assert refetched.data["phases"][0]["tasks"][0]["text"] == "t1-edited"


def test_remove_task_with_rev(client: PlanClient) -> None:
    created = client.create_document("dev", "demo", _CREATE_BODY)
    assert created.rev
    removed = client.remove_task("dev", "demo", "p1", "a", 0, rev=created.rev)
    assert removed.data is not None
    assert removed.data["phases"][0]["tasks"] == []


def test_section_lifecycle(client: PlanClient) -> None:
    client.create_document("dev", "demo", _CREATE_BODY)
    added = client.add_section("dev", "demo", "p1", "ctx", "Context", "body", 2)
    assert added.data is not None
    assert added.data["sections"][0]["heading"] == "Context"
    set_ = client.set_section("dev", "demo", "p1", "ctx", "Context 2", None, None)
    assert set_.data is not None
    assert set_.data["sections"][0]["heading"] == "Context 2"
    patched = client.patch_section("dev", "demo", "p1", "ctx", {"heading": "Patched"})
    assert patched.data is not None
    assert patched.data["sections"][0]["heading"] == "Patched"
    removed = client.remove_section("dev", "demo", "p1", "ctx")
    assert removed.data is not None
    assert removed.data["sections"] == []


def test_delete_document_with_rev(client: PlanClient) -> None:
    created = client.create_document("dev", "demo", _CREATE_BODY)
    assert created.rev
    deleted = client.delete_document("dev", "demo", "p1", rev=created.rev)
    # DELETE returns 204: no body, data is None.
    assert deleted.data is None
    with pytest.raises(NotFound):
        client.get_document("dev", "demo", "p1")


def test_set_phase_prose_round_trips(client: PlanClient) -> None:
    client.create_document("dev", "demo", _CREATE_BODY)
    set_ = client.set_phase(
        "dev",
        "demo",
        "p1",
        "a",
        None,
        intro="The why",
        exit_criteria="Done when green",
        notes="!!! note\n    A card",
    )
    assert set_.data is not None
    refetched = client.get_document("dev", "demo", "p1")
    assert refetched.data is not None
    phase = refetched.data["phases"][0]
    assert phase["intro"] == "The why"
    assert phase["exit_criteria"] == "Done when green"
    assert phase["notes"] == "!!! note\n    A card"


def test_section_placement_round_trips(client: PlanClient) -> None:
    from claudeplans_contracts import SectionPlacement

    client.create_document("dev", "demo", _CREATE_BODY)
    added = client.add_section(
        "dev",
        "demo",
        "p1",
        "ctx",
        "Context",
        "body",
        2,
        placement=SectionPlacement.trail,
    )
    assert added.data is not None
    assert added.data["sections"][0]["placement"] == "trail"
    # set back to lead
    set_ = client.set_section(
        "dev",
        "demo",
        "p1",
        "ctx",
        None,
        None,
        None,
        placement=SectionPlacement.lead,
    )
    assert set_.data is not None
    assert set_.data["sections"][0]["placement"] == "lead"
